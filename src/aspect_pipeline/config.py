from pathlib import Path
from typing import Any, Sequence

import yaml

from aspect_pipeline.utils.classes import Config, RunConfig, CalibConfig, DataConfig, PipelineConfig, pds4_config
from aspect_pipeline.utils.validate import (Level, Channel, _require_mapping, _require_bool, _require_list_of_str, _require_str, 
                                                     _resolve_str, _resolve_path, _resolve_optional_path, _validate_path, _expand_levels, _validate_levels, _validate_channels)
from aspect_pipeline.utils.errors import ConfigError, ValidationError

DEFAULT_CANDIDATES = [
    Path("configs/example.yaml")
]

# Public API
def load_config(config_path: str | Path | None = None) -> Config:
    """
    Load, parse and validate the pipeline configurations
    
    :param config_path: path to the configuration file
    :type config_path: str | Path | None
    :return: Config object containing pipeline configurations
    :rtype: Config
    """

    path = _resolve_config_path(config_path=config_path)
    raw = _read_yaml(path)
    config_object = _parse_config_dict(raw=raw, config_path=path)
    return config_object


def load_pds4_config(config_path: str | Path | None) -> pds4_config:
    """
    Load, parse and valudate the pds4 configurations
    called by pipeline/run.py
    """

    path = _resolve_config_path(config_path=config_path)
    raw = _read_yaml(path)
    pds4_config_object = _parse_pds4_config_dict(raw=raw, config_path=path)
    return pds4_config_object



# Internals
def _resolve_config_path(config_path: str | Path | None) -> Path:
    """
    Resolve the config file path
    - If config_path is provided: must exist and be a file.
    - If None: try DEFAULT_CANIDATES, return that first exists.
    
    :param config_path: path to the configuration file
    :type config_path: str | Path | None
    :return: Path object to the configuration
    :rtype: Path
    """
    if config_path is not None:
        p = Path(config_path).expanduser()
        if not p.exists():
            raise ConfigError(f"Config not found {p}")
        if p.is_dir():
            raise ConfigError(f"Config path is a directory, expected a file: {p}")
        return p.resolve()
    
    for p in DEFAULT_CANDIDATES:
        if p.exists() and p.is_file():
            return p.resolve()
    
    tried = ", ".join(str(p) for p in DEFAULT_CANDIDATES)
    raise ConfigError(
        "No config provided and no default config found. "
        f"Tried: {tried}."
        "Run from project root or pass --config"
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    """
    Read YAML file and return a dict. 
    
    :param path: Path object to the config YAML file
    :type path: Path
    :return: dictionary of the top-level config fields
    :rtype: dict[str, Any]
    """

    try: 
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"Failed to read config file: {path}") from e
    
    try:
        obj = yaml.safe_load(text) or {}
    except Exception as e:
        raise ConfigError(f"Failed to parse YAML in config file {path}") from e
    
    if not isinstance(obj, dict):
        raise ConfigError(f"top-level YAML must be a mapping/object in {path}")
    
    return obj

def _parse_config_dict(raw: dict[str, Any], *, config_path: Path) -> Config:
    """
    Convert the raw YAML dict into dataclasses.
    
    :param raw: top-level config dictionary
    :type raw: dict[str, Any]
    :param config_path: Path to the config YAML file
    :type config_path: Path
    :return: Config object
    :rtype: Config
    """

    base_dir = config_path.parent
    run_raw = _require_mapping(raw, "run")
    cal_raw = _require_mapping(raw, 'calibration')
    data_raw = _require_mapping(raw, "data")
    pipeline_raw = _require_mapping(raw, "pipeline")

    try:
        run = RunConfig(
            input_dir=_validate_path(_resolve_path(_require_str(run_raw, "input_dir"), base_dir), kind='dir'),
            output_dir=_resolve_optional_path(run_raw.get("output_dir", ""), base_dir),
            spice_dir=_resolve_optional_path(run_raw.get("spice_dir", ""), base_dir),
            overwrite=_require_bool(run_raw, "overwrite"),
        )

        calibration = CalibConfig(
            calibration_dir=_validate_path(_resolve_path(_require_str(cal_raw, "calibration_dir"), base_dir)),
            solar_ssi=_validate_path(_resolve_path(_require_str(cal_raw, "solar_ssi"), base_dir)),
            drop_frame=_require_bool(cal_raw, "drop_first_frame"),
        )

        data = DataConfig(
            instrume=_require_str(data_raw, "instrume"),
            origin=_require_str(data_raw, "origin"),
            swcreate=_require_str(data_raw, "swcreate"),
            missphas=_require_str(data_raw, "missphas"),
            observ=_require_str(data_raw, "observ"),
            object=_require_str(data_raw, "object"),
            target=_require_str(data_raw, "target"),
            solar_d=_resolve_str(data_raw, "solar_d"),
        )

        levels = _require_list_of_str(pipeline_raw, "levels")
        channels = _require_list_of_str(pipeline_raw, "channels")

        levels = _expand_levels(levels)
        _validate_levels(levels)
        _validate_channels(channels)
    except ValidationError as e:
        raise ConfigError(f"Parsing config dictionary failed: {e}.")

    pipeline = PipelineConfig(
        levels=tuple(levels),
        channels=tuple(channels),
    )

    return Config(run=run, calib=calibration, data=data, pipeline=pipeline, config_path=config_path)


def _parse_pds4_config_dict(raw: dict[str, Any], *, config_path: Path) -> pds4_config:

    base_dir = config_path.parent
    pds4_raw = _require_mapping(raw, "pds4")

    levels = _require_list_of_str(pds4_raw, "products")
    levels = _expand_levels(levels)
    _validate_levels(levels)

    channels = _require_list_of_str(pds4_raw, "channels")
    _validate_channels(channels)

    try:
        pds4_cfg = pds4_config(
            input =  _validate_path(_resolve_path(_require_str(pds4_raw, "input"), base_dir), kind=None),
            templates_dir= _validate_path(_resolve_path(_require_str(pds4_raw, "templates_dir"), base_dir), kind='dir'),
            output = _resolve_optional_path(pds4_raw.get("output", ""), base_dir),
            products = levels,
            channels = channels
        )
    except ValidationError as e:
        raise ConfigError(f'Creating pds4 config failed: {e}')

    return pds4_cfg