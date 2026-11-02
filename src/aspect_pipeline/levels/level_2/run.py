import logging
from pathlib import Path

from aspect_pipeline.utils.classes import Config
from aspect_pipeline.levels.level_2.merge_channels import merge_fits_files

logger = logging.getLogger(__name__)

def run_level_2(cfg: Config) -> Path:
    """
    main fucntion to run the level 2.
    """
    input_dir = cfg.run.input_dir
    out_dir = cfg.run.output_dir
    channels = cfg.pipeline.channels

    fits = merge_fits_files(input_dir=input_dir, channels=channels, output_dir=out_dir)

    logger.info(f"Level 2B completed.")

    return fits