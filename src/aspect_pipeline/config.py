from pathlib import Path
from typing import Any, Sequence

import yaml

from aspect_pipeline.utils.classes import Config, RunConfig, CalibConfig, DataConfig, PipelineConfig, AnalysisConfig, pds4_config
from aspect_pipeline.utils.validate import (require_mapping, require_bool, require_list_of_str, require_str, require_any, resolve_str, resolve_path,
                                            resolve_optional_path, validate_path, expand_levels, validate_levels, validate_channels)
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

    # All sections should be dictionaries
    base_dir = config_path.parent
    run_raw = require_mapping(raw, "run")
    cal_raw = require_mapping(raw, 'calibration')
    data_raw = require_mapping(raw, "data")
    pipeline_raw = require_mapping(raw, "pipeline")
    analysis_raw = require_mapping(raw, "analysis")

    try:
        run = RunConfig(
            input_dir=validate_path(resolve_path(require_str(run_raw, "input_dir"), base_dir), kind='dir'),
            output_dir=resolve_optional_path(run_raw.get("output_dir", ""), base_dir),
            spice_dir=resolve_optional_path(run_raw.get("spice_dir", ""), base_dir),
            overwrite=require_bool(run_raw, "overwrite"),
        )

        calibration = CalibConfig(
            calibration_dir=validate_path(resolve_path(require_str(cal_raw, "calibration_dir"), base_dir)),
            solar_ssi=validate_path(resolve_path(require_str(cal_raw, "solar_ssi"), base_dir)),
            drop_frame=require_bool(cal_raw, "drop_first_frame"),
        )

        data = DataConfig(
            instrume=require_str(data_raw, "instrume"),
            origin=require_str(data_raw, "origin"),
            swcreate=require_str(data_raw, "swcreate"),
            missphas=require_str(data_raw, "missphas"),
            acq_id=require_str(data_raw, "acq_id"),
            major_version=require_str(data_raw, "major_version"),
            minor_version=require_str(data_raw, "minor_version"),
            solar_d=resolve_str(data_raw, "solar_d"),
        )

        analysis = AnalysisConfig(
            instrument=require_any(analysis_raw, "instrument"),
            data_filtering=require_bool(analysis_raw, "data_filtering"),
            save_filtered=require_bool(analysis_raw, "save_filtered"),
            models=require_list_of_str(analysis_raw, "models"),
            z_thresh=require_any(analysis_raw, "z_thresh"),
            z_factor=require_any(analysis_raw, "z_factor"),
            init_guess=require_any(analysis_raw, "init_guess"),
        )

        levels = require_list_of_str(pipeline_raw, "levels")
        channels = require_list_of_str(pipeline_raw, "channels")

        levels = expand_levels(levels)
        validate_levels(levels)
        validate_channels(channels)
    except ValidationError as e:
        raise ConfigError(f"Parsing config dictionary failed: {e}.")

    pipeline = PipelineConfig(
        levels=tuple(levels),
        channels=tuple(channels),
    )

    return Config(run=run, calib=calibration, data=data, pipeline=pipeline, analysis=analysis, config_path=config_path)


def _parse_pds4_config_dict(raw: dict[str, Any], *, config_path: Path) -> pds4_config:

    base_dir = config_path.parent
    pds4_raw = require_mapping(raw, "pds4")

    levels = require_list_of_str(pds4_raw, "products")
    levels = expand_levels(levels)
    validate_levels(levels)

    channels = require_list_of_str(pds4_raw, "channels")
    validate_channels(channels)

    data_raw = raw.get("data", {}) if isinstance(raw.get("data"), dict) else {}
    major_version = str(pds4_raw.get("major_version") or data_raw.get("major_version") or "1")
    minor_version = str(pds4_raw.get("minor_version") or data_raw.get("minor_version") or "0")

    try:
        pds4_cfg = pds4_config(
            input=validate_path(resolve_path(require_str(pds4_raw, "input"), base_dir), kind=None),
            templates_dir=validate_path(resolve_path(require_str(pds4_raw, "templates_dir"), base_dir), kind='dir'),
            output=resolve_optional_path(pds4_raw.get("output", ""), base_dir),
            products=levels,
            channels=channels,
            major_version=major_version,
            minor_version=minor_version,
            config_path=config_path,
        )
    except ValidationError as e:
        raise ConfigError(f'Creating pds4 config failed: {e}')

    return pds4_cfg
