import hashlib
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
import yaml

from aspect_pipeline.pds4.fits_reader import read_fits_metadata
from aspect_pipeline.utils.classes import Config, pds4_config
from aspect_pipeline.utils.utilities import (
    convert_processing_levels,
    convert_to_zulu_time,
    get_wavelengths_by_channel,
    parse_filename,
)

logger = logging.getLogger(__name__)

CHANNEL_DISPLAY_MAP = {
    "vis": "Vis",
    "nir1": "NIR1",
    "nir2": "NIR2",
    "swir": "SWIR",
}


def copy_schemas(schema_source_dir: Path, output_pds4_dir: Path) -> None:
    """
    Copies all .sch and .xsd schema and schematron files to the {output}/schema directory.
    """
    dest_dir = Path(output_pds4_dir) / "schema"
    dest_dir.mkdir(parents=True, exist_ok=True)

    if not schema_source_dir or not Path(schema_source_dir).exists():
        logger.warning(
            f"Schema source directory '{schema_source_dir}' does not exist. Skipping schema copy."
        )
        return

    # Find all .sch and .xsd files (top-level and subdirectories)
    schema_files = list(Path(schema_source_dir).rglob("*.sch")) + list(
        Path(schema_source_dir).rglob("*.xsd")
    )

    if not schema_files:
        logger.warning(f"No .sch or .xsd files found in '{schema_source_dir}'.")
        return

    copied_count = 0
    for src in schema_files:
        dest = dest_dir / src.name
        # Copy if file does not exist or has newer modification timestamp
        if not dest.exists() or src.stat().st_mtime > dest.stat().st_mtime:
            shutil.copy2(src, dest)
            copied_count += 1

    logger.info(f"Copied {copied_count} schema/schematron file(s) into: {dest_dir}")


def resolve_version(
    config: pds4_config | Config | Path | str | None = None,
    config_path: Path | str | None = None,
    major_version: str | None = None,
    minor_version: str | None = None,
    default_major: str | None = None,
    default_minor: str | None = None,
) -> tuple[str, str]:
    """
    Resolve major and minor version strings.
    Checks:
      1. Explicit major_version / minor_version arguments
      2. config object (pds4_config or Config)
      3. config / config_path YAML file (data or pds4 section)
      4. Default candidate YAML file (e.g. configs/example.yaml)
      5. Fallback to ('1', '0')
    """
    if major_version is not None and minor_version is not None:
        return str(major_version), str(minor_version)

    resolved_major = str(major_version) if major_version is not None else None
    resolved_minor = str(minor_version) if minor_version is not None else None

    # Try extracting from passed config object
    if config is not None:
        if hasattr(config, "major_version") and hasattr(config, "minor_version"):
            if resolved_major is None and config.major_version is not None:
                resolved_major = str(config.major_version)
            if resolved_minor is None and config.minor_version is not None:
                resolved_minor = str(config.minor_version)
        elif hasattr(config, "data"):
            if resolved_major is None and hasattr(config.data, "major_version"):
                resolved_major = str(config.data.major_version)
            if resolved_minor is None and hasattr(config.data, "minor_version"):
                resolved_minor = str(config.data.minor_version)
        elif isinstance(config, (str, Path)):
            config_path = config

    # If still not fully resolved, try reading YAML from config_path or default candidate
    if resolved_major is None or resolved_minor is None:
        candidates = []
        if config_path:
            candidates.append(Path(config_path))
        candidates.extend([
            Path("configs/example.yaml"),
            Path("configs/pipeline.yaml"),
        ])
        for p in candidates:
            if p.is_file():
                try:
                    content = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
                    if isinstance(content, dict):
                        pds4_sec = (
                            content.get("pds4", {})
                            if isinstance(content.get("pds4"), dict)
                            else {}
                        )
                        data_sec = (
                            content.get("data", {})
                            if isinstance(content.get("data"), dict)
                            else {}
                        )
                        if resolved_major is None:
                            val = pds4_sec.get("major_version") or data_sec.get(
                                "major_version"
                            )
                            if val is not None:
                                resolved_major = str(val)
                        if resolved_minor is None:
                            val = pds4_sec.get("minor_version") or data_sec.get(
                                "minor_version"
                            )
                            if val is not None:
                                resolved_minor = str(val)
                        if resolved_major is not None and resolved_minor is not None:
                            break
                except Exception as e:
                    logger.debug(f"Could not read version from {p}: {e}")

    final_major = (
        resolved_major
        if resolved_major is not None
        else (default_major if default_major is not None else "1")
    )
    final_minor = (
        resolved_minor
        if resolved_minor is not None
        else (default_minor if default_minor is not None else "0")
    )
    return final_major, final_minor


def find_level1_labels_in_pds4(
    output_path: Path, default_version_id: str = "1.0"
) -> dict[str, dict]:
    """
    Search output_path (and parent if output_path is a product directory)
    for existing Level 1 PDS4 labels (*.lblx, *.xml).

    Returns a dict mapping channel name ('vis', 'nir1', 'nir2', 'swir')
    to information about the highest available calibration level for that channel.
    """
    pds4_dir = Path(output_path)
    search_dirs = [pds4_dir]
    if pds4_dir.parent.exists() and pds4_dir.parent != pds4_dir:
        if any(
            pds4_dir.name.startswith(pfx)
            for pfx in ("AS0", "AS1", "AS2", "AS3", "ASP", "asp_")
        ):
            search_dirs.append(pds4_dir.parent)

    label_files: list[Path] = []
    seen_files = set()
    for d in search_dirs:
        if d.is_dir():
            for pat in ("*.lblx", "*.xml"):
                for f in d.rglob(pat):
                    try:
                        resolved = f.resolve()
                    except Exception:
                        resolved = f
                    if resolved not in seen_files:
                        seen_files.add(resolved)
                        label_files.append(f)

    # Regex matching Level 1 labels: asp_{raw|par|cal}_sc_{channel}_{descriptor}__...
    pattern = re.compile(
        r"^asp_(raw|par|cal)_sc_(vis|nir1|nir2|swir)_([0-9a-zA-Z]+)__(\d+_\d+)\.(lblx|xml)$",
        re.IGNORECASE,
    )
    level_priority = {"cal": 3, "par": 2, "raw": 1}
    collection_map = {
        "cal": "data_calibrated",
        "par": "data_partially_processed",
        "raw": "data_raw",
    }
    ref_type_map = {
        "cal": "data_to_calibrated_source_product",
        "par": "data_to_partially_processed_source_product",
        "raw": "data_to_raw_source_product",
    }

    channel_info: dict[str, dict] = {}

    for file in label_files:
        m = pattern.match(file.name)
        if not m:
            continue
        lvl = m.group(1).lower()
        ch = m.group(2).lower()
        desc = m.group(3)
        ver_str = m.group(4)

        current = channel_info.get(ch)
        if current is not None and level_priority.get(lvl, 0) <= level_priority.get(
            current["level_code"], 0
        ):
            continue

        lidvid = None
        try:
            content = file.read_text(encoding="utf-8")
            lid_m = re.search(
                r"<logical_identifier>\s*([^<\s]+)\s*</logical_identifier>", content
            )
            ver_m = re.search(r"<version_id>\s*([^<\s]+)\s*</version_id>", content)
            if lid_m:
                v = ver_m.group(1) if ver_m else "1.0"
                lidvid = f"{lid_m.group(1)}::{v}"
        except Exception:
            pass

        if not lidvid:
            coll = collection_map.get(lvl, "data_calibrated")
            v = ver_str.replace("_", ".") if ver_str else default_version_id
            lidvid = f"urn:esa:psa:hera:{coll}:asp_{lvl}_sc_{ch}_{desc}::{v}"

        channel_info[ch] = {
            "channel": ch,
            "level_code": lvl,
            "descriptor": desc,
            "version": ver_str,
            "reference_type": ref_type_map.get(
                lvl, "data_to_calibrated_source_product"
            ),
            "lidvid": lidvid,
            "file": file,
        }

    return channel_info


def find_level2_label_in_pds4(
    output_path: Path, default_version_id: str = "1.0"
) -> dict | None:
    """
    Search output_path for an existing Level 2 PDS4 label.
    """
    pds4_dir = Path(output_path)
    search_dirs = [pds4_dir]
    if pds4_dir.parent.exists() and pds4_dir.parent != pds4_dir:
        if any(
            pds4_dir.name.startswith(pfx)
            for pfx in ("AS0", "AS1", "AS2", "AS3", "ASP", "asp_")
        ):
            search_dirs.append(pds4_dir.parent)

    pattern = re.compile(
        r"^asp_der_sc_([a-z0-9_]+)_([0-9a-zA-Z]+)__(\d+_\d+)\.(lblx|xml)$",
        re.IGNORECASE,
    )
    for d in search_dirs:
        if d.is_dir():
            for pat in ("*.lblx", "*.xml"):
                for f in d.rglob(pat):
                    if any(
                        x in f.name.lower()
                        for x in (
                            "composition",
                            "taxonomy",
                            "cpx",
                            "opx",
                            "ol",
                            "mgm",
                        )
                    ):
                        continue
                    m = pattern.match(f.name)
                    if m:
                        sub = m.group(1).lower()
                        desc = m.group(2)
                        lidvid = None
                        try:
                            content = f.read_text(encoding="utf-8")
                            lid_m = re.search(
                                r"<logical_identifier>\s*([^<\s]+)\s*</logical_identifier>",
                                content,
                            )
                            ver_m = re.search(
                                r"<version_id>\s*([^<\s]+)\s*</version_id>", content
                            )
                            if lid_m:
                                v = ver_m.group(1) if ver_m else "1.0"
                                lidvid = f"{lid_m.group(1)}::{v}"
                        except Exception:
                            pass
                        if not lidvid:
                            v = (
                                m.group(3).replace("_", ".")
                                if m.group(3)
                                else default_version_id
                            )
                            lidvid = (
                                f"urn:esa:psa:hera:data_derived:asp_der_sc_{sub}_{desc}::{v}"
                            )
                        return {
                            "subunit": sub,
                            "descriptor": desc,
                            "lidvid": lidvid,
                            "file": f,
                        }
    return None


def build_base_metadata(
    fits_path: Path,
    config: pds4_config | Config | Path | str | None = None,
    major_version: str | None = None,
    minor_version: str | None = None,
    config_path: Path | str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Extract common metadata, file details, spectral characteristics, and resolved version.
    Returns (metadata, context).
    """
    metadata = read_fits_metadata(fits_path)

    file_name = fits_path.name
    stem = fits_path.stem
    metadata["file_name"] = file_name

    parsed_name = None
    try:
        parsed_name = parse_filename(file_name)
    except Exception:
        parsed_name = None

    if parsed_name:
        proclevl = parsed_name.processing_level
        data_type = parsed_name.type
        file_major = parsed_name.major_version
        file_minor = parsed_name.minor_version
    else:
        proclevl = metadata.get("proclevl", "")
        data_type = "sc"
        file_major = None
        file_minor = None

    metadata["proclevl"] = proclevl

    major_ver, minor_ver = resolve_version(
        config=config,
        config_path=config_path,
        major_version=major_version,
        minor_version=minor_version,
        default_major=file_major,
        default_minor=file_minor,
    )
    version = f"__{major_ver}_{minor_ver}"
    version_id = f"{major_ver}.{minor_ver}"
    metadata["version"] = version
    metadata["version_id"] = version_id
    metadata["major_version"] = major_ver
    metadata["minor_version"] = minor_ver

    if metadata.get("start_date_time"):
        metadata["start_date_time"] = convert_to_zulu_time(metadata["start_date_time"])
    metadata["processing_level"] = convert_processing_levels(proclevl)
    metadata["reference_list"] = proclevl != "0A"
    metadata["modification_date"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    metadata["mission_lid"] = "urn:esa:psa:mission.hera"
    metadata["aspect_lid"] = "urn:esa:psa:milani.aspect"

    target = "Didymos" if metadata.get("channel") == "didy" else "Dimorphos"
    target_lid = (
        "urn:nasa:pds:context:asteroid.65803_didymos"
        if metadata.get("channel") == "didy"
        else "urn:nasa:pds:context:satellite.65803_didymos.dimorphos"
    )
    metadata["target"] = target
    metadata["target_lid"] = target_lid
    metadata["net_integration_time"] = 1

    # Spectral Characteristics
    wavelengths_by_channel = {}
    try:
        wavelengths_by_channel = get_wavelengths_by_channel(fits_file=fits_path)
    except (ValueError, OSError) as e:
        logger.warning(f"Could not read wavelengths from {fits_path.name}: {e}")

    wavelengths = [
        wl for ch_wls in wavelengths_by_channel.values() for wl in ch_wls
    ]
    metadata["wavelengths_by_channel"] = wavelengths_by_channel
    metadata["wavelengths"] = wavelengths

    is_linear = False
    bands = []

    if wavelengths:
        wl_floats = [float(w) for w in wavelengths]
        metadata["first_center"] = wl_floats[0]
        metadata["last_center"] = wl_floats[-1]
        n_bands = len(wl_floats)

        for i, w in enumerate(wl_floats):
            if n_bands == 1:
                bw = 30.0
            elif i == 0:
                bw = abs(wl_floats[1] - wl_floats[0])
            elif i == n_bands - 1:
                bw = abs(wl_floats[-1] - wl_floats[-2])
            else:
                bw = abs(wl_floats[i + 1] - wl_floats[i - 1]) / 2.0

            bands.append({"center_wl": f"{w:.1f}", "bin_width": f"{bw:.1f}"})

        if n_bands > 1:
            diffs = [
                wl_floats[i + 1] - wl_floats[i] for i in range(n_bands - 1)
            ]
            first_diff = diffs[0]
            if all(abs(d - first_diff) < 0.01 for d in diffs):
                is_linear = True
                metadata["sampling_interval"] = f"{first_diff:.1f}"
                metadata["bin_width"] = f"{first_diff:.1f}"
            else:
                is_linear = False
                metadata["sampling_interval"] = None
                metadata["bin_width"] = f"{sum(diffs) / len(diffs):.1f}"
        else:
            metadata["bin_width"] = "30.0"
    else:
        metadata["first_center"] = None
        metadata["last_center"] = None
        metadata["sampling_interval"] = None
        metadata["bin_width"] = None

    metadata["is_linear"] = is_linear
    metadata["bands"] = bands

    # File Area
    file_size = fits_path.stat().st_size
    with open(fits_path, "rb") as f:
        file_md5_checksum = hashlib.md5(f.read()).hexdigest()

    metadata["file_size"] = file_size
    metadata["file_md5_checksum"] = file_md5_checksum

    _dtype_to_pds4 = {
        "uint16": "UnsignedMSB2",
        "uint32": "UnsignedMSB4",
        ">f4": "IEEE754MSBSingle",
        "float32": "IEEE754MSBSingle",
    }
    primary_dtype = metadata["extensions"][0]["data_dtype"]
    metadata["pds4_data_type"] = _dtype_to_pds4.get(
        primary_dtype, "IEEE754MSBSingle"
    )

    context = {
        "stem": stem,
        "file_name": file_name,
        "parsed_name": parsed_name,
        "proclevl": proclevl,
        "data_type": data_type,
        "major_ver": major_ver,
        "minor_ver": minor_ver,
        "version": version,
        "version_id": version_id,
        "channel": metadata.get("channel") or "",
    }

    return metadata, context


def save_pds4_product(
    metadata: dict[str, Any],
    template_name: str,
    templates_dir: Path,
    output_path: Path,
    fits_path: Path,
    product_id: str,
    version: str,
    stem: str,
) -> Path:
    """
    Render Jinja2 template and save the resulting .lblx file and renamed .fits file.
    """
    pds4_fits_name = f"{product_id}{version}.fits"
    metadata["file_name"] = pds4_fits_name

    env = Environment(loader=FileSystemLoader(templates_dir))
    template_obj = env.get_template(template_name)
    label_xml = template_obj.render(**metadata)

    product_dir = (
        Path(output_path)
        if Path(output_path).name == stem
        else Path(output_path) / stem
    )
    product_dir.mkdir(parents=True, exist_ok=True)

    lblx_path = product_dir / f"{product_id}{version}.lblx"
    lblx_path.write_text(label_xml, encoding="utf-8")

    # Remove any stale unrenamed FITS file if present from prior runs
    old_fits_copy = product_dir / fits_path.name
    if old_fits_copy.is_file() and fits_path.name != pds4_fits_name:
        old_fits_copy.unlink()

    shutil.copy2(fits_path, product_dir / pds4_fits_name)
    return product_dir

