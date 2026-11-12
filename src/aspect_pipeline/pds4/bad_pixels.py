import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from astropy.io import fits
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

BADPIXEL_CHANNEL_MAP: dict[str, dict[str, str]] = {
    "vis": {
        "detector_id": "AS0",
        "channel_label": "Visible",
    },
    "nir1": {
        "detector_id": "AS1",
        "channel_label": "Near-Infrared 1",
    },
    "nir2": {
        "detector_id": "AS2",
        "channel_label": "Near-Infrared 2",
    },
    "swir": {
        "detector_id": "AS3",
        "channel_label": "Short-Wave Infrared",
    },
}

_DETECTOR_NUM_TO_CHANNEL: dict[str, str] = {
    "0": "vis",
    "1": "nir1",
    "2": "nir2",
    "3": "swir",
}

_CHANNEL_ORDER: tuple[str, ...] = ("vis", "nir1", "nir2", "swir")
_LEVEL3_SUBUNITS: set[str] = {"composition", "taxonomy", "cpx", "ol", "opx", "mgm"}

_ASP_LV1_DIR_RE = re.compile(
    r"^asp_(1b|1c)_(?:sc|hk)_(vis|nir1|nir2|swir)_", re.IGNORECASE
)
_ASP_LV2_DIR_RE = re.compile(
    r"^asp_(?:2|2b)_(?:sc|hk)_([a-z0-9_]+)_[0-9a-zA-Z]+(?:__|$)", re.IGNORECASE
)
_SIM_LV1_DIR_RE = re.compile(r"^AS([0-3])_.*_(1B|1C)$", re.IGNORECASE)
_SIM_LV2_DIR_RE = re.compile(r"^ASP_.*_(?:2|2B)$", re.IGNORECASE)

_PAR_CAL_FILE_RE = re.compile(
    r"^asp_(par|cal)_(?:sc|hk)_(vis|nir1|nir2|swir)_.*\.(?:lblx|xml|fits)$",
    re.IGNORECASE,
)
_DER_LV2_FILE_RE = re.compile(
    r"^asp_der_(?:sc|hk)_([a-z0-9_]+)_[0-9a-zA-Z]+__\d+_\d+\.(?:lblx|xml|fits)$",
    re.IGNORECASE,
)


def normalize_bad_pixel_bytes(raw_bytes: bytes) -> bytes:
    """
    Normalize a BADPIXELS TXT table to single-tab field delimiters and CRLF line endings
    (including a trailing CRLF on the final record) for PDS4 PDS DSV 1 compliance.
    """
    text = raw_bytes.decode("utf-8", errors="replace")
    normalized_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        fields = re.split(r"[\t ]+", stripped)
        normalized_lines.append("\t".join(fields))
    if not normalized_lines:
        return b""
    return ("\r\n".join(normalized_lines) + "\r\n").encode("utf-8")


def inspect_bad_pixel_bytes(raw_bytes: bytes, file_name: str) -> dict[str, Any]:
    """
    Compute file size, MD5 checksum, header byte offset, defect record count,
    and line delimiter from raw BADPIXELS TXT bytes.
    """
    file_size = len(raw_bytes)
    md5_checksum = hashlib.md5(raw_bytes).hexdigest()
    record_delimiter = (
        "Carriage-Return Line-Feed" if b"\r\n" in raw_bytes else "Line-Feed"
    )

    lines = raw_bytes.splitlines(keepends=True)
    offset = 0
    records = 0
    header_checked = False
    for line in lines:
        stripped = line.strip()
        if not header_checked:
            if not stripped:
                offset += len(line)
                continue
            header_checked = True
            if stripped.lower().startswith(b"type"):
                offset += len(line)
                continue
        if stripped:
            records += 1

    return {
        "file_name": file_name,
        "file_size": file_size,
        "md5_checksum": md5_checksum,
        "offset": offset,
        "records": records,
        "record_delimiter": record_delimiter,
        "field_delimiter": "Horizontal Tab",
    }


def inspect_bad_pixel_file(txt_path: Path) -> dict[str, Any]:
    """
    Compute file size, MD5 checksum, header byte offset, defect record count,
    and line delimiter for a BADPIXELS TXT table.
    """
    path = Path(txt_path)
    return inspect_bad_pixel_bytes(path.read_bytes(), path.name)


def resolve_badpixels_dir(
    templates_dir: Path,
    badpixels_dir: Path | str | None = None,
) -> Path:
    """
    Resolve the directory containing AS*_BADPIXELS.TXT files.
    Defaults to `<project_root>/calibration/BADPIXELS` inferred from `templates_dir`.
    """
    if badpixels_dir is not None:
        return Path(badpixels_dir)

    candidate = Path(templates_dir).resolve().parent / "calibration" / "BADPIXELS"
    if candidate.is_dir():
        return candidate

    return Path("calibration/BADPIXELS")


def find_badpixel_txt(badpixels_dir: Path, detector_id: str) -> Path | None:
    """
    Locate `AS{n}_BADPIXELS.TXT` inside `badpixels_dir` (case-insensitive fallback).
    """
    exact = badpixels_dir / f"{detector_id}_BADPIXELS.TXT"
    if exact.is_file():
        return exact

    target_lower = f"{detector_id}_badpixels.txt".lower()
    if badpixels_dir.is_dir():
        for entry in badpixels_dir.iterdir():
            if entry.is_file() and entry.name.lower() == target_lower:
                return entry
    return None


def _extract_channels_from_subunit(subunit: str) -> list[str]:
    tokens = [t.lower() for t in subunit.split("_") if t]
    if any(t in _LEVEL3_SUBUNITS for t in tokens):
        return []
    return [c for c in _CHANNEL_ORDER if c in tokens]


def _extract_channels_from_fits_in_dir(product_dir: Path) -> list[str]:
    for child in sorted(product_dir.iterdir()):
        if child.is_file() and child.suffix.lower() == ".fits":
            try:
                with fits.open(child) as hdul:
                    ch_val = hdul[0].header.get("CHANNELS")
                if ch_val:
                    parsed = [c.strip().lower() for c in str(ch_val).split(",") if c.strip()]
                    found = [c for c in _CHANNEL_ORDER if c in parsed]
                    if found:
                        return found
            except Exception:
                continue
    return []


def _identify_product_level_and_channels(
    product_dir: Path,
) -> tuple[str, list[str]] | None:
    """
    Identify `(level, channels)` if `product_dir` is a Level 1B, 1C, or 2B PDS4
    product directory, otherwise return None.
    """
    if not product_dir.is_dir():
        return None

    name = product_dir.name

    m1 = _ASP_LV1_DIR_RE.match(name)
    if m1:
        return m1.group(1).upper(), [m1.group(2).lower()]

    m2 = _ASP_LV2_DIR_RE.match(name)
    if m2:
        chs = _extract_channels_from_subunit(m2.group(1))
        if chs:
            return "2B", chs

    ms1 = _SIM_LV1_DIR_RE.match(name)
    if ms1:
        ch = _DETECTOR_NUM_TO_CHANNEL.get(ms1.group(1))
        if ch:
            return ms1.group(2).upper(), [ch]

    ms2 = _SIM_LV2_DIR_RE.match(name)
    if ms2:
        for child in sorted(product_dir.iterdir()):
            if child.is_file():
                mf2 = _DER_LV2_FILE_RE.match(child.name)
                if mf2:
                    chs = _extract_channels_from_subunit(mf2.group(1))
                    if chs:
                        return "2B", chs
        fits_chs = _extract_channels_from_fits_in_dir(product_dir)
        return "2B", (fits_chs or ["vis", "nir1", "nir2"])

    for child in sorted(product_dir.iterdir()):
        if not child.is_file():
            continue
        mf1 = _PAR_CAL_FILE_RE.match(child.name)
        if mf1:
            lvl = "1B" if mf1.group(1).lower() == "par" else "1C"
            return lvl, [mf1.group(2).lower()]
        mf2 = _DER_LV2_FILE_RE.match(child.name)
        if mf2:
            chs = _extract_channels_from_subunit(mf2.group(1))
            if chs:
                return "2B", chs

    return None


def _normalize_target_levels(levels: Sequence[str] | None) -> set[str]:
    if not levels:
        return {"1B", "1C", "2B"}
    normalized: set[str] = set()
    for lvl in levels:
        u = str(lvl).strip().upper()
        if u == "2":
            normalized.add("2B")
        elif u in ("1B", "1C", "2B"):
            normalized.add(u)
    return normalized


def find_badpixel_target_dirs(
    output_pds4_dir: Path,
    levels: Sequence[str] | None = None,
    channels: Sequence[str] | None = None,
) -> list[tuple[str, list[str], Path]]:
    """
    Find all Level 1B, 1C, and 2B product directories inside `output_pds4_dir`
    (or `output_pds4_dir` itself).
    Returns a list of `(level, channel_list, product_dir)` tuples filtered by `levels`
    and `channels` if given.
    """
    base = Path(output_pds4_dir)
    if not base.is_dir():
        return []

    allowed_levels = _normalize_target_levels(levels)
    if not allowed_levels:
        return []

    allowed_channels = (
        {c.strip().lower() for c in channels if c and c.strip()}
        if channels
        else None
    )

    def _filter_entry(prod_dir: Path) -> tuple[str, list[str], Path] | None:
        info = _identify_product_level_and_channels(prod_dir)
        if info is None:
            return None
        lvl, dir_chs = info
        if lvl not in allowed_levels:
            return None
        chs = (
            [c for c in dir_chs if c in allowed_channels]
            if allowed_channels is not None
            else dir_chs
        )
        if not chs:
            return None
        return (lvl, chs, prod_dir)

    direct = _filter_entry(base)
    if direct is not None:
        return [direct]

    results: list[tuple[str, list[str], Path]] = []
    for entry in sorted(base.iterdir()):
        item = _filter_entry(entry)
        if item is not None:
            results.append(item)
    return results


def find_level1b_product_dirs(
    output_pds4_dir: Path,
    channels: Sequence[str] | None = None,
) -> list[tuple[str, Path]]:
    """
    Find all Level 1B product directories inside `output_pds4_dir`.
    Returns a list of `(channel_lower, product_dir)` tuples.
    """
    matches = find_badpixel_target_dirs(
        output_pds4_dir=output_pds4_dir,
        levels=("1B",),
        channels=channels,
    )
    return [(chs[0], prod_dir) for _, chs, prod_dir in matches if chs]


def _remove_stale_badpixel_files(product_dir: Path, detector_id: str) -> None:
    """
    Remove any pre-existing `AS{n}_BADPIXELS.TXT` or `as{n}_badpixels.xml` in `product_dir`.
    """
    if not product_dir.is_dir():
        return
    txt_lower = f"{detector_id}_badpixels.txt".lower()
    xml_lower = f"{detector_id}_badpixels.xml".lower()
    for entry in product_dir.iterdir():
        if entry.is_file() and entry.name.lower() in (txt_lower, xml_lower):
            entry.unlink()
            logger.info("Removed stale empty bad pixel file %s from %s", entry.name, product_dir)


def get_badpixel_references(
    channels: Sequence[str],
    templates_dir: Path,
    badpixels_dir: Path | str | None = None,
    version_id: str = "1.0",
) -> list[dict[str, str]]:
    """
    Return PDS4 `<Internal_Reference>` dicts for all channels whose BADPIXELS TXT file
    exists and contains at least one defect row (not empty or header-only).
    """
    bp_dir = resolve_badpixels_dir(
        templates_dir=templates_dir, badpixels_dir=badpixels_dir
    )
    if not bp_dir.is_dir():
        return []

    seen: set[str] = set()
    refs: list[dict[str, str]] = []
    for ch in channels:
        ch_key = ch.strip().lower()
        if not ch_key or ch_key in seen:
            continue
        seen.add(ch_key)

        info = BADPIXEL_CHANNEL_MAP.get(ch_key)
        if info is None:
            continue
        detector_id = info["detector_id"]
        txt_path = find_badpixel_txt(bp_dir, detector_id)
        if txt_path is None:
            continue

        file_stats = inspect_bad_pixel_file(txt_path)
        if file_stats["records"] == 0:
            continue

        refs.append(
            {
                "lidvid": f"urn:esa:psa:hera:data_partially_processed:{detector_id.lower()}_badpixels::{version_id}",
                "reference_type": "data_to_partially_processed_product",
            }
        )
    return refs


def generate_bad_pixel_product(
    txt_path: Path,
    product_dir: Path,
    channel: str,
    templates_dir: Path,
    template_name: str = "BAD_PIXEL_template.j2",
    version_id: str = "1.0",
    start_date_time: str = "2024-01-01T00:00:00Z",
    stop_date_time: str = "2030-12-31T23:59:59Z",
    target: str = "Didymos",
    target_lid: str = "urn:nasa:pds:context:asteroid.65803_didymos",
) -> Path | None:
    """
    Copy a bad pixel TXT table into `product_dir` and render its `as[n]_badpixels.xml` label.
    If the TXT file is empty or contains only a header line (`records == 0`), omits both
    the TXT and XML files (removing any stale copies in `product_dir`) and returns None.
    """
    ch_key = channel.strip().lower()
    info = BADPIXEL_CHANNEL_MAP.get(ch_key)
    if info is None:
        raise ValueError(f"Unsupported channel for bad pixel product: {channel!r}")

    detector_id = info["detector_id"]
    channel_label = info["channel_label"]
    detector_lower = detector_id.lower()

    txt_src = Path(txt_path)
    if not txt_src.is_file():
        raise FileNotFoundError(f"Bad pixel table file not found: {txt_src}")

    dest_dir = Path(product_dir)
    normalized_bytes = normalize_bad_pixel_bytes(txt_src.read_bytes())
    file_stats = inspect_bad_pixel_bytes(normalized_bytes, txt_src.name)
    if file_stats["records"] == 0:
        logger.info(
            "Skipping %s for %s: file is empty or contains only a header line.",
            txt_src.name,
            dest_dir,
        )
        _remove_stale_badpixel_files(dest_dir, detector_id)
        return None

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_txt = dest_dir / txt_src.name
    if txt_src.resolve() != dest_txt.resolve() or dest_txt.read_bytes() != normalized_bytes:
        dest_txt.write_bytes(normalized_bytes)

    metadata: dict[str, Any] = {
        "logical_identifier": f"urn:esa:psa:hera:data_partially_processed:{detector_lower}_badpixels",
        "version_id": version_id,
        "title": f"ASPECT {channel_label} Channel ({detector_id}) Defect and Bad Pixel Table",
        "modification_date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start_date_time": start_date_time,
        "stop_date_time": stop_date_time,
        "target": target,
        "target_lid": target_lid,
        "detector_id": detector_id,
        **file_stats,
    }

    env = Environment(loader=FileSystemLoader(templates_dir))
    template_obj = env.get_template(template_name)
    label_xml = template_obj.render(**metadata)

    xml_path = dest_dir / f"{detector_lower}_badpixels.xml"
    xml_path.write_text(label_xml, encoding="utf-8")
    logger.info(
        "Copied %s and created %s in %s",
        dest_txt.name,
        xml_path.name,
        dest_dir,
    )
    return xml_path


def generate_bad_pixels(
    output_pds4_dir: Path,
    templates_dir: Path,
    badpixels_dir: Path | str | None = None,
    channels: Sequence[str] | None = None,
    levels: Sequence[str] | None = None,
    template_name: str = "BAD_PIXEL_template.j2",
    version_id: str = "1.0",
    start_date_time: str = "2024-01-01T00:00:00Z",
    stop_date_time: str = "2030-12-31T23:59:59Z",
    target: str = "Didymos",
    target_lid: str = "urn:nasa:pds:context:asteroid.65803_didymos",
) -> list[Path]:
    """
    Copy non-empty channel bad pixel tables (`AS[n]_BADPIXELS.TXT`) into matching
    Level 1B, 1C, and 2B PDS4 product folders under `output_pds4_dir` and generate
    `as[n]_badpixels.xml` labels. Empty or header-only `.TXT` files are excluded.
    """
    bp_dir = resolve_badpixels_dir(
        templates_dir=templates_dir, badpixels_dir=badpixels_dir
    )
    if not bp_dir.is_dir():
        logger.warning(
            "Bad pixels source directory '%s' does not exist. Skipping bad pixel PDS4 step.",
            bp_dir,
        )
        return []

    target_dirs = find_badpixel_target_dirs(
        output_pds4_dir=output_pds4_dir,
        levels=levels,
        channels=channels,
    )
    if not target_dirs:
        logger.info(
            "No Level 1B/1C/2B product directories found in '%s' for bad pixel map copy.",
            output_pds4_dir,
        )
        return []

    generated_xmls: list[Path] = []
    for _lvl, prod_channels, prod_dir in target_dirs:
        for ch_key in prod_channels:
            info = BADPIXEL_CHANNEL_MAP.get(ch_key)
            if info is None:
                continue
            detector_id = info["detector_id"]
            txt_path = find_badpixel_txt(bp_dir, detector_id)
            if txt_path is None:
                _remove_stale_badpixel_files(prod_dir, detector_id)
                if ch_key in ("vis", "nir1", "nir2"):
                    logger.warning(
                        "Bad pixel file %s_BADPIXELS.TXT not found in '%s'; skipping %s.",
                        detector_id,
                        bp_dir,
                        prod_dir,
                    )
                else:
                    logger.debug(
                        "No bad pixel file %s_BADPIXELS.TXT in '%s'; skipping %s.",
                        detector_id,
                        bp_dir,
                        prod_dir,
                    )
                continue

            xml_path = generate_bad_pixel_product(
                txt_path=txt_path,
                product_dir=prod_dir,
                channel=ch_key,
                templates_dir=templates_dir,
                template_name=template_name,
                version_id=version_id,
                start_date_time=start_date_time,
                stop_date_time=stop_date_time,
                target=target,
                target_lid=target_lid,
            )
            if xml_path is not None:
                generated_xmls.append(xml_path)

    return generated_xmls
