from pathlib import Path

from aspect_pipeline.levels.level_0.build_fits import build_fits

from aspect_pipeline.utils.classes import Config, InputLayout
from aspect_pipeline.utils.validate import validate_level_0_input_dir
from aspect_pipeline.utils.errors import ValidationError

def run_level_0(cfg: Config, channel: str) -> Path:
    """
    Main function to run the level 0. Combines the acqusition binary files and metadata into a single FITS file.
    """

    input_dir = cfg.run.input_dir
    input_layout = validate_level_0_input_dir(input_dir=input_dir)

    fits_path = build_fits(input=input_layout, cfg=cfg, channel=channel)


    return fits_path