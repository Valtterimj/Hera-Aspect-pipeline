import shutil
import logging
import re

from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import hashlib
from datetime import timezone, datetime
import traceback


from aspect_pipeline.pds4.fits_reader import read_fits_metadata
import yaml
from aspect_pipeline.utils.classes import pds4_config, Config
from aspect_pipeline.utils.errors import PipelineError
from aspect_pipeline.utils.utilities import convert_to_zulu_time, convert_processing_levels, get_wavelengths_by_channel, parse_filename

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
        logger.warning(f"Schema source directory '{schema_source_dir}' does not exist. Skipping schema copy.")
        return

    # Find all .sch and .xsd files (top-level and subdirectories)
    schema_files = list(Path(schema_source_dir).rglob("*.sch")) + list(Path(schema_source_dir).rglob("*.xsd"))

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
                        pds4_sec = content.get("pds4", {}) if isinstance(content.get("pds4"), dict) else {}
                        data_sec = content.get("data", {}) if isinstance(content.get("data"), dict) else {}
                        if resolved_major is None:
                            val = pds4_sec.get("major_version") or data_sec.get("major_version")
                            if val is not None:
                                resolved_major = str(val)
                        if resolved_minor is None:
                            val = pds4_sec.get("minor_version") or data_sec.get("minor_version")
                            if val is not None:
                                resolved_minor = str(val)
                        if resolved_major is not None and resolved_minor is not None:
                            break
                except Exception as e:
                    logger.debug(f"Could not read version from {p}: {e}")

    final_major = resolved_major if resolved_major is not None else (default_major if default_major is not None else "1")
    final_minor = resolved_minor if resolved_minor is not None else (default_minor if default_minor is not None else "0")
    return final_major, final_minor

def find_level1_labels_in_pds4(output_path: Path, default_version_id: str = "1.0") -> dict[str, dict]:
    """
    Search output_path (and parent if output_path is a product directory)
    for existing Level 1 PDS4 labels (*.lblx, *.xml).
    
    Returns a dict mapping channel name ('vis', 'nir1', 'nir2', 'swir')
    to information about the highest available calibration level for that channel.
    """
    pds4_dir = Path(output_path)
    search_dirs = [pds4_dir]
    if pds4_dir.parent.exists() and pds4_dir.parent != pds4_dir:
        if any(pds4_dir.name.startswith(pfx) for pfx in ('AS0', 'AS1', 'AS2', 'AS3', 'ASP')):
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
        if current is not None and level_priority.get(lvl, 0) <= level_priority.get(current["level_code"], 0):
            continue

        lidvid = None
        try:
            content = file.read_text(encoding="utf-8")
            lid_m = re.search(r"<logical_identifier>\s*([^<\s]+)\s*</logical_identifier>", content)
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
            "reference_type": ref_type_map.get(lvl, "data_to_calibrated_source_product"),
            "lidvid": lidvid,
            "file": file,
        }

    return channel_info

def find_level2_label_in_pds4(output_path: Path, default_version_id: str = "1.0") -> dict | None:
    """
    Search output_path for an existing Level 2 PDS4 label.
    """
    pds4_dir = Path(output_path)
    search_dirs = [pds4_dir]
    if pds4_dir.parent.exists() and pds4_dir.parent != pds4_dir:
        if any(pds4_dir.name.startswith(pfx) for pfx in ('AS0', 'AS1', 'AS2', 'AS3', 'ASP')):
            search_dirs.append(pds4_dir.parent)

    pattern = re.compile(
        r"^asp_der_sc_([a-z0-9_]+)_([0-9a-zA-Z]+)__(\d+_\d+)\.(lblx|xml)$",
        re.IGNORECASE,
    )
    for d in search_dirs:
        if d.is_dir():
            for pat in ("*.lblx", "*.xml"):
                for f in d.rglob(pat):
                    if any(x in f.name.lower() for x in ("composition", "taxonomy", "cpx", "opx", "ol", "mgm")):
                        continue
                    m = pattern.match(f.name)
                    if m:
                        sub = m.group(1).lower()
                        desc = m.group(2)
                        lidvid = None
                        try:
                            content = f.read_text(encoding="utf-8")
                            lid_m = re.search(r"<logical_identifier>\s*([^<\s]+)\s*</logical_identifier>", content)
                            ver_m = re.search(r"<version_id>\s*([^<\s]+)\s*</version_id>", content)
                            if lid_m:
                                v = ver_m.group(1) if ver_m else "1.0"
                                lidvid = f"{lid_m.group(1)}::{v}"
                        except Exception:
                            pass
                        if not lidvid:
                            v = m.group(3).replace("_", ".") if m.group(3) else default_version_id
                            lidvid = f"urn:esa:psa:hera:data_derived:asp_der_sc_{sub}_{desc}::{v}"
                        return {
                            "subunit": sub,
                            "descriptor": desc,
                            "lidvid": lidvid,
                            "file": f,
                        }
    return None

def generate_label(
    fits_path: Path,
    templates_dir: Path,
    output_path: Path,
    config: pds4_config | Config | Path | str | None = None,
    major_version: str | None = None,
    minor_version: str | None = None,
    config_path: Path | str | None = None,
) -> None:
    """
    Generate PDS4 label for a fits file and save it to the output path.
    """
    try:
        metadata = read_fits_metadata(fits_path)

        channel = metadata.get('channel') or ''
        channel_lower = channel.lower() if channel else ''
        channel_names = [c.strip() for c in channel.split(',') if c.strip()]

        metadata['channels'] = [
            {
                'name': c,
                'lid': f"urn:nasa:pds:context:instrument:aspect.{c.lower()}"
            }
            for c in channel_names
        ]

        file_name = fits_path.name
        stem = fits_path.stem
        metadata['file_name'] = file_name

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
            proclevl = metadata.get('proclevl', '')
            data_type = 'sc'
            file_major = None
            file_minor = None

        metadata['proclevl'] = proclevl

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
        metadata['version'] = version
        metadata['version_id'] = version_id
        metadata['major_version'] = major_ver
        metadata['minor_version'] = minor_ver

        if proclevl == '0A':
            print(f'Skipping Level 0A file: {fits_path.name}')
            return
        
        if proclevl in ('1A', '1A-extra'):
            psa_level = 'raw'
            m_lid_type = 'data_raw'
        elif proclevl =='1B':
            psa_level = 'par'
            m_lid_type = 'data_partially_processed'
        elif proclevl == '1C':  # 1C
            psa_level = 'cal'
            m_lid_type = 'data_calibrated'
        else:
            psa_level = 'der'
            m_lid_type = 'data_derived'

        print("PSA Level:", proclevl)

        source_references = []

        if proclevl in ('1A', '1A-extra', '1B', '1C'):
            template = "ASPECT_template_1.j2"
            if parsed_name:
                subunit = parsed_name.subunit.lower()
                descriptor = parsed_name.descriptor
            else:
                SUBUNIT_MAP = {
                    "as0": "vis",
                    "as1": "nir1",
                    "as2": "nir2",
                    "as3": "swir",
                }
                parts = stem.lower().split('_')
                subunit = SUBUNIT_MAP.get(parts[0], channel_lower or "unknown")
                descriptor = "0000"

        elif proclevl in ('2', '2A', '2B'):
            template = "ASPECT_template_2.j2"
            lv1_labels = find_level1_labels_in_pds4(output_path, default_version_id=version_id)

            if parsed_name:
                subunit = parsed_name.subunit.lower()
                descriptor = parsed_name.descriptor
                found_channels = [c for c in ('vis', 'nir1', 'nir2', 'swir') if c in subunit.split('_')]
                if not found_channels:
                    found_channels = ['vis', 'nir1', 'nir2']
            elif lv1_labels:
                found_channels = [c for c in ('vis', 'nir1', 'nir2', 'swir') if c in lv1_labels]
                descriptor = next((lv1_labels[c]['descriptor'] for c in found_channels if 'descriptor' in lv1_labels[c]), "0000")
                subunit = "_".join(found_channels)
            else:
                header_channels = [c.strip().lower() for c in channel.split(',') if c.strip()]
                found_channels = [c for c in ('vis', 'nir1', 'nir2', 'swir') if c in header_channels]
                if not found_channels:
                    found_channels = ['vis', 'nir1', 'nir2']
                descriptor = "0000"
                subunit = "_".join(found_channels)

            # References matching each Level 1 product's calibration level
            for c in found_channels:
                if c in lv1_labels:
                    source_references.append({
                        'lidvid': lv1_labels[c]['lidvid'],
                        'reference_type': lv1_labels[c]['reference_type'],
                    })
                else:
                    source_references.append({
                        'lidvid': f"urn:esa:psa:hera:data_calibrated:asp_cal_sc_{c}_{descriptor}::{version_id}",
                        'reference_type': "data_to_calibrated_source_product",
                    })

            # Dynamic instruments for Level 2
            channel_names = [CHANNEL_DISPLAY_MAP[c] for c in found_channels]
            channel = ",".join(channel_names)
            channel_lower = channel.lower()
            metadata['channels'] = [
                {
                    'name': CHANNEL_DISPLAY_MAP[c],
                    'lid': f"urn:nasa:pds:context:instrument:aspect.{c}"
                }
                for c in found_channels
            ]
            metadata['os_name'] = f"ASPECT_{'_'.join(channel_names)}"

        elif proclevl.startswith('3'):
            template = "ASPECT_template_3.j2"
            lv1_labels = find_level1_labels_in_pds4(output_path, default_version_id=version_id)
            if parsed_name:
                subunit = parsed_name.subunit.lower()
                descriptor = parsed_name.descriptor
            else:
                subunit = 'composition'
                descriptor = "0000"

            if lv1_labels:
                found_channels = [c for c in ('vis', 'nir1', 'nir2', 'swir') if c in lv1_labels]
                if not parsed_name:
                    descriptor = next((lv1_labels[c]['descriptor'] for c in found_channels if 'descriptor' in lv1_labels[c]), "0000")
            else:
                header_channels = [c.strip().lower() for c in channel.split(',') if c.strip()]
                found_channels = [c for c in ('vis', 'nir1', 'nir2', 'swir') if c in header_channels]
                if not found_channels:
                    found_channels = ['vis', 'nir1', 'nir2']

            lv2_subunit = "_".join(found_channels)

            # Check if Level 2 label exists in pds4 folder
            lv2_label = find_level2_label_in_pds4(output_path, default_version_id=version_id)
            if lv2_label:
                lv2_lidvid = lv2_label['lidvid']
            else:
                lv2_lidvid = f"urn:esa:psa:hera:data_derived:asp_der_sc_{lv2_subunit}_{descriptor}::{version_id}"

            # Level 3 references the Level 2 derived product
            source_references = [
                {
                    'lidvid': lv2_lidvid,
                    'reference_type': 'data_to_derived_source_product',
                }
            ]
            print('lv3 references lv2:', lv2_lidvid)
            metadata['derived_to_source_id'] = lv2_lidvid

            # Dynamic instruments for Level 3
            channel_names = [CHANNEL_DISPLAY_MAP[c] for c in found_channels]
            channel = ",".join(channel_names)
            channel_lower = channel.lower()
            metadata['channels'] = [
                {
                    'name': CHANNEL_DISPLAY_MAP[c],
                    'lid': f"urn:nasa:pds:context:instrument:aspect.{c}"
                }
                for c in found_channels
            ]
            metadata['os_name'] = f"ASPECT_{'_'.join(channel_names)}"

        else:
            template = "ASPECT_template_1.j2"
            subunit = "unknown"
            descriptor = "1110"

        print(template)

        instr = "asp"
        product_id = f"{instr}_{psa_level}_{data_type}_{subunit}_{descriptor}"

        metadata["start_date_time"] = convert_to_zulu_time(
            metadata['start_date_time'])
        metadata["processing_level"] = convert_processing_levels(proclevl)
        metadata["reference_list"] = proclevl != '0A'

        ### Identification Area ###
        if proclevl in ('2', '2A', '2B'):
            channel_str = "-".join(CHANNEL_DISPLAY_MAP.get(c, c) for c in found_channels)
            metadata['title'] = (
                f'Hera ASPECT instrument merged {channel_str} Level {proclevl} processed datacube:'
                f' {stem}'
            )
        elif proclevl.startswith('3'):
            metadata['title'] = (
                f'Hera ASPECT instrument Level {proclevl} analysis datacube: {stem}'
            )
        else:
            metadata['title'] = (
                f'Hera ASPECT instrument {channel} channel level {proclevl} processed'
                f' datacube: {stem}'
            )

        metadata["main_logical_lid"] = f"urn:esa:psa:hera:{m_lid_type}:{product_id}"

        # mod history
        metadata["modification_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        ### Observation Area ###
        wl_range = 'Visible'
        if channel in ['NIR1', 'NIR2']:
            wl_range = 'Near Infrared'
        elif channel == 'SWIR':
            wl_range = 'Infrared'
        metadata['wl_range'] = wl_range

        ### Investigation Area ###
        mission_lid = "urn:esa:psa:mission.hera"
        metadata['mission_lid'] = mission_lid

        ### Observing System ###
        observing_system_name = metadata.get('os_name') or f'ASPECT_{channel.replace(",", "_")}'
        metadata['os_name'] = observing_system_name
        # Host
        aspect_lid = "urn:esa:psa:milani.aspect"
        metadata['aspect_lid'] = aspect_lid
        # Instrument
        instrument_lid = f"urn:nasa:pds:context:instrument:aspect.{channel_lower}"
        metadata['instrument_lid'] = instrument_lid

        # Target_Identification
        target = "Didymos" if metadata.get('channel') == "didy" else "Dimorphos"
        target_lid = "urn:nasa:pds:context:asteroid.65803_didymos" if metadata.get(
            'channel') == "didy" else "urn:nasa:pds:context:satellite.65803_didymos.dimorphos"
        metadata['target'] = target
        metadata['target_lid'] = target_lid

        ### Image dictionary ###
        metadata['radiometric_type'] = (
            'Radiance Factor'
            if proclevl in ('1C', '2', '2A', '2B')
            else 'Spectral Radiance'
        )

        ### Spectral Dictionary ###
        net_integration_time = 1
        metadata['net_integration_time'] = net_integration_time

        ### Spectral Characteristics ###
        wavelengths_by_channel = {}
        try:
            wavelengths_by_channel = get_wavelengths_by_channel(fits_file=fits_path)
        except (ValueError, OSError) as e:
            logger.warning(f"Could not read wavelengths from {fits_path.name}: {e}")

        # Flatten wavelengths across all channels in acquisition order
        wavelengths = [
            wl
            for ch_wls in wavelengths_by_channel.values()
            for wl in ch_wls
        ]
        metadata['wavelengths_by_channel'] = wavelengths_by_channel
        metadata['wavelengths'] = wavelengths

        is_linear = False
        bands = []

        if wavelengths:
            wl_floats = [float(w) for w in wavelengths]
            metadata['first_center'] = wl_floats[0]
            metadata['last_center'] = wl_floats[-1]
            n_bands = len(wl_floats)

            # Compute bin width dynamically for each band from the wavelength grid
            for i, w in enumerate(wl_floats):
                if n_bands == 1:
                    bw = 30.0  # default fallback for single-band frame
                elif i == 0:
                    bw = abs(wl_floats[1] - wl_floats[0])
                elif i == n_bands - 1:
                    bw = abs(wl_floats[-1] - wl_floats[-2])
                else:
                    # Central difference: half the distance between adjacent bands
                    bw = abs(wl_floats[i + 1] - wl_floats[i - 1]) / 2.0

                bands.append({
                    'center_wl': f'{w:.1f}',
                    'bin_width': f'{bw:.1f}'
                })

            # Check if sampling interval is constant
            if n_bands > 1:
                diffs = [
                    wl_floats[i + 1] - wl_floats[i] for i in range(n_bands - 1)
                ]
                first_diff = diffs[0]
                if all(abs(d - first_diff) < 0.01 for d in diffs):
                    is_linear = True
                    metadata['sampling_interval'] = f'{first_diff:.1f}'
                    metadata['bin_width'] = f'{first_diff:.1f}'
                else:
                    is_linear = False
                    metadata['sampling_interval'] = None
                    # Average bin width as scalar fallback
                    metadata['bin_width'] = f'{sum(diffs) / len(diffs):.1f}'
            else:
                metadata['bin_width'] = "30.0"
        else:
            metadata['first_center'] = None
            metadata['last_center'] = None
            metadata['sampling_interval'] = None
            metadata['bin_width'] = None

        metadata['is_linear'] = is_linear
        metadata['bands'] = bands

        ## Reference_List
        metadata['source_references'] = source_references
        metadata['raw_to_source_id'] = f'urn:esa:psa:hera:data_raw:asp_raw_sc_{subunit}_{descriptor}::{version_id}'
        metadata['partially_processe_to_source_id'] = f'urn:esa:psa:hera:data_partially_processed:asp_par_sc_{subunit}_{descriptor}::{version_id}'
        metadata['calibrated_to_source_id'] = f'urn:esa:psa:hera:data_calibrated:asp_cal_sc_{subunit}_{descriptor}::{version_id}'

        metadata['calibrated_to_source_id_vis'] = f'urn:esa:psa:hera:data_calibrated:asp_cal_sc_vis_{descriptor}::{version_id}'
        metadata['calibrated_to_source_id_nir1'] = f'urn:esa:psa:hera:data_calibrated:asp_cal_sc_nir1_{descriptor}::{version_id}'
        metadata['calibrated_to_source_id_nir2'] = f'urn:esa:psa:hera:data_calibrated:asp_cal_sc_nir2_{descriptor}::{version_id}'
        metadata['calibrated_to_source_id_swir'] = f'urn:esa:psa:hera:data_calibrated:asp_cal_sc_swir_{descriptor}::{version_id}'

        ### File Area ###
        file_size = fits_path.stat().st_size

        with open(fits_path, 'rb') as f:
            file_md5_checksum = hashlib.md5(f.read()).hexdigest()

        metadata["file_size"] = file_size
        metadata["file_md5_checksum"] = file_md5_checksum

        _dtype_to_pds4 = {
            'uint16':  'UnsignedMSB2',
            'uint32':  'UnsignedMSB4',
            '>f4':     'IEEE754MSBSingle',
            'float32': 'IEEE754MSBSingle',
        }
        primary_dtype = metadata['extensions'][0]['data_dtype']
        metadata['pds4_data_type'] = _dtype_to_pds4.get(
            primary_dtype, 'IEEE754MSBSingle')

        if proclevl in ('0A', '1A'):
            metadata['data_unit'] = 'DN'
        elif proclevl in ('1A-extra', '1B'):
            metadata['data_unit'] = 'W*m**-2*sr**-1*nm**-1'
        else:  # 1C, 2, 2B, 3
            metadata['data_unit'] = '1'

        # local_identifier used for the primary data array; referenced in Discipline_Area
        is_cube = any(c in channel for c in ['Vis', 'NIR1', 'NIR2']) or proclevl in ('2', '2A', '2B', '3C') or proclevl.startswith('3')
        metadata['data_local_id'] = 'data_cube' if is_cube else 'data_spectrum'
        metadata['spectrum_format'] = '3D' if is_cube else '1D'

        env = Environment(loader=FileSystemLoader(templates_dir))
        template_obj = env.get_template(template)
        label_xml = template_obj.render(**metadata)

        product_dir = Path(output_path) if Path(output_path).name == stem else Path(output_path) / stem
        product_dir.mkdir(parents=True, exist_ok=True)

        (product_dir /
        f"{product_id}{version}.lblx").write_text(label_xml, encoding="utf-8")
        shutil.copy2(fits_path, product_dir / fits_path.name)
        
        return

    except Exception as e:
        print(f'\n ERROR generating label for {fits_path.name}:')
        traceback.print_exc()
        raise e
