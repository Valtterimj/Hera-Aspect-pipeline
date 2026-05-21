from pathlib import Path

from aspect_pipeline.levels.level_0.build_fits import build_fits

from aspect_pipeline.utils.classes import Config, InputLayout, Issue
from aspect_pipeline.utils.validate import _validate_level_0_input_dir
from aspect_pipeline.utils.errors import ValidationError

def run_level_0(cfg: Config, channel: str) -> tuple[Path, list[Issue]]:
    """
    Main function to run the level 0. Combines the acqusition binary files and metadata into a single FITS file.
    """

    all_issues: list[Issue] = []

    input_dir = cfg.run.input_dir
    input_layout = _validate_level_0_input_dir(input_dir=input_dir)
    
    fits_path, issues = build_fits(input=input_layout, cfg=cfg, channel=channel)
    all_issues.extend(issues)

    
    return fits_path, all_issues