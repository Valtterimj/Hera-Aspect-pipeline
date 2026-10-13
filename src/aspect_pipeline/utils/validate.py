
import re
from pathlib import Path
from typing import Any, Literal, Sequence, get_args

from aspect_pipeline.utils.errors import ValidationError
from aspect_pipeline.utils.classes import Level, Channel, InputLayout
from aspect_pipeline.utils.utilities import channel_to_id


ALLOWED_LEVELS = list(get_args(Level))
ALLOWED_CHANNELS = set(get_args(Channel))

def _require_mapping(d: dict[str, Any], key: str) -> dict[str, Any]:
    v = d.get(key)
    if not isinstance(v, dict):
        raise ValidationError(f"Missing or invalid section '{key}:' Must be a mapping/object")
    return v

def _require_str(d: dict[str, Any], key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or v.strip() == "":
        raise ValidationError(f"Missing or invalid string: {key}")
    return v.strip()

def _resolve_str(d: dict[str, Any], key: str) -> str | None:
    s = d.get(key)
    if not isinstance(s, str) or s.strip() == "":
        return None
    else:
        return s.strip()

def _require_any(d: dict[str, Any], key: str) -> Any:
    s = d.get(key)
    return s

def _require_bool(d: dict[str, Any], key: str) -> bool:
    v = d.get(key)
    if not isinstance(v, bool):
        raise ValidationError(f"Missing or invalid boolean: {key}")
    return v

def _require_list_of_str(d: dict[str, Any], key:str) -> list[str]:
    v = d.get(key)
    if not isinstance(v, list) or len(v) == 0:
        raise ValidationError(f"Missing or invalid list: {key}, must be non-empty list")
    out: list[str] = []
    for i, item in enumerate(v):
        itm = str(item)
        if not isinstance(itm, str) or itm.strip() == "":
            raise ValidationError(f"Invalid item in {key}[{i}], must be non-empty string")
        out.append(itm.strip())
    return out

def _resolve_path(raw_path: str, base_dir: Path) -> Path:
    p = Path(raw_path).expanduser()
    if not p.is_absolute():
        p = base_dir / p
    return p.resolve()

def _resolve_optional_path(raw_value: Any, base_dir: Path) -> Path | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, str):
        if raw_value.strip() == "":
            return None
        return _resolve_path(raw_path=raw_value, base_dir=base_dir)
    raise ValidationError(f"Resolving path failed, (must be a string, Path or empty)")

def _validate_path(path: Path, kind: Literal["file", "dir"] | None = None) -> Path:
    """Validate that path exists. Can specify type (file or dir) use None if both are fine"""
    if kind not in {"file", "dir", None}:
        raise ValueError(f"Invalid kind '{kind}', expected 'file', 'dir', or None.")
    
    if not path.exists():
        raise ValidationError(f"Path does not exists: {path}")
    
    if kind == 'file' and not path.is_file():
        raise ValidationError(f"Path is not an existing file: {path}")
    
    if kind == 'dir' and not path.is_dir():
        raise ValidationError(f"Path is not an existing directory: {path}")

    return path

def _expand_levels(levels: Sequence[str]) -> list[str]:
    expanded_levels = set()

    for level in levels:
        if level in ALLOWED_LEVELS:
            expanded_levels.add(level)
        elif level == "0":
            expanded_levels.add("0A")
        elif  level == "1":
            expanded_levels.update(["1A", "1B", "1C"])
        elif level == "3":
            expanded_levels.update(["3A", "3B", "3C"])
    
    return [l for l in ALLOWED_LEVELS if l in expanded_levels]

def _validate_levels(levels: list[str]) -> None:
    bad = [x for x in levels if x not in ALLOWED_LEVELS]
    if bad:
        raise ValidationError(
            f"Invalid pipeline.levels: {bad}. "
            f"Allowed: {sorted(ALLOWED_LEVELS)}"
        )

def _validate_channels(channels: Sequence[str]) -> None:
    bad = [x for x in channels if x not in ALLOWED_CHANNELS]
    if bad:
        raise ValidationError(
            f"Invalid pipeline.channels: {bad}. "
            f"Allowed: {sorted(ALLOWED_CHANNELS)}"
        )

def _validate_float_string(value) -> str | None:
    if value is None:
        return None
    
    s = str(value).strip()
    if not s:
        return None
    
    try:
        float(s)
        return s
    except (ValueError, TypeError):
        return None

def _validate_output_dir(output_dir: Path | None, missphas: str, base_dir: Path | None = None) -> Path:

    if output_dir:
        output_path = output_dir.expanduser()
        if output_path.exists() and not output_path.is_dir():
            raise ValidationError(f"Output path exists but is not a directory: {output_path}")
        base_output = output_path
    else:
        if not base_dir:
            base_dir = Path.cwd()
        base_output = base_dir / "outputs"
    
    final_output = base_output / missphas

    final_output.mkdir(parents=True, exist_ok=True)
    if not final_output.exists() or not final_output.is_dir():
        raise ValidationError(f"Failed to create output directory: {final_output}")
    
    return final_output
    
def _validate_level_0_input_dir(input_dir: Path) -> InputLayout:

    _ACQ_RE = re.compile(r"^acq_\d+.*$") # folder name for images. Has to start with acq_

    input_dir = input_dir.expanduser()

    if not input_dir.exists():
        raise ValidationError(f"Input directory does not exist: {input_dir}")
    if not input_dir.is_dir():
        raise ValidationError(f"Input path is not a directory: {input_dir}")
    
    root = input_dir
    
    meta_dir = root / "meta"
    if not meta_dir.exists():
        raise ValidationError(f"Missing required directory: {meta_dir}")
    if not meta_dir.is_dir():
        raise ValidationError(f"'meta' exists but it's not a directory: {meta_dir}")
    
    telemetry_json = meta_dir / "telemetry.json"
    config_json = meta_dir / "config.json"

    missing = [p.name for p in (telemetry_json, config_json) if not p.exists()]
    if missing:
        raise ValidationError(f"Missing required file(s) in {meta_dir}: {', '.join(missing)}")

    for p in (telemetry_json, config_json):
        if not p.is_file():
            raise ValidationError(f"Required path exists but is not a file: {p}")
    
    candidates: list[Path] = [
        p for p in root.iterdir()
        if p.is_dir() and _ACQ_RE.match(p.name)
    ]
    if not candidates:
        raise ValidationError(f"No acquisition directory found. Expected folder like 'acq_000/' under: {root}")
    
    candidates.sort(key=lambda p: p.name)
    acq_dir = candidates[0]
    
    return InputLayout(
        root=root,
        meta_dir=meta_dir,
        telemetry_json=telemetry_json,
        config_json=config_json,
        acquisition_dir=acq_dir,
    )

def _get_path(input_dir: Path, channel: str,  suffix: str) -> Path:
    """
        Resolve to path to correct fits file inside the input_dir according to the lvl.
        E.g. if lvl = 1B the input dir should contain a file ending to '*1A.fits'
    """
    if not input_dir.exists() or not input_dir.is_dir():
        raise ValidationError(f"Not a valid input directory found.")
    
    matches = list(input_dir.glob(f"*{suffix}", case_sensitive=False))
    channel_id = f'AS{channel_to_id[channel]}'
    matches = [p for p in matches if p.name.startswith(channel_id)]

    if not matches:
        raise ValidationError(f"No file with suffix '{suffix}' for channel '{channel}' found in {input_dir}.")
    
    return matches[0]



    