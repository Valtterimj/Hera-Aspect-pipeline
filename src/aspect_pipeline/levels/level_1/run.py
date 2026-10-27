import logging
from pathlib import Path

from aspect_pipeline.utils.classes import Config, CalibConfig
from aspect_pipeline.utils.utilities import parse_levels_to_run, get_path
from aspect_pipeline.levels.level_1.calibrate_header import calibrate_header
from aspect_pipeline.levels.level_1.level_1b import run_level_1b
from aspect_pipeline.levels.level_1.reflectance import reflectance_calibration

logger = logging.getLogger(__name__)

def run_level_1(cfg: Config, channel: str) -> Path:
    """
    main fucntion to run the level 1.
    """
    levels = cfg.pipeline.levels
    levels_to_run = parse_levels_to_run(levels=levels)
    output_dir = cfg.run.output_dir

    if '1A' in levels_to_run:
        fits_path = get_path(input_dir=cfg.run.input_dir, processing_level='0A', subunit=channel.lower(), descriptor=cfg.data.acq_id, extension='fits')
        fits_path = calibrate_header(fits_path=fits_path, output_dir=output_dir, channel=channel, drop_frame=cfg.calib.drop_frame)
        logger.info(f"Level 1A completed.")

    if '1B' in levels_to_run or '1A-extra' in levels_to_run:
        if '1A' not in levels_to_run:
            fits_path = get_path(input_dir=cfg.run.input_dir, processing_level='1A', subunit=channel.lower(), descriptor=cfg.data.acq_id, extension='fits')
        calibration_cfg = cfg.calib
        extra = '1A-extra' in levels_to_run
        fits_path = run_level_1b(fits_file=fits_path, output_dir=output_dir, calibration=calibration_cfg, channel=channel, extra=extra)
        logger.info(f"Level 1B completed.")

    if '1C' in levels_to_run:
        if '1B' not in levels_to_run:
            fits_path = get_path(input_dir=cfg.run.input_dir, processing_level='1B', subunit=channel.lower(), descriptor=cfg.data.acq_id, extension='fits')
        calibration_cfg = cfg.calib
        solar_ssi = Path(calibration_cfg.calibration_dir) / calibration_cfg.solar_ssi
        fits_path = reflectance_calibration(fits_path=fits_path, output_dir=output_dir, solar_ssi=solar_ssi)
        logger.info(f"Level 1C completed.")

    return fits_path
