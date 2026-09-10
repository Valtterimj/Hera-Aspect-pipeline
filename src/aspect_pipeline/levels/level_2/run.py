from pathlib import Path

from aspect_pipeline.utils.classes import Issue, Config, CalibConfig
from aspect_pipeline.utils.utilities import parse_levels_to_run
from aspect_pipeline.utils.validate import _get_path

def run_level_2(cfg: Config, channel: str) -> tuple[Path, list[Issue]]:
    """
    main fucntion to run the level 2.
    """
    all_issues: list[Issue] = []

    levels = cfg.pipeline.levels
    levels_to_run = parse_levels_to_run(levels=levels)
        
    if '2' in levels_to_run:
        input_dir = cfg.run.input_dir
        output_dir = cfg.run.output_dir
        fits_path, issues = run_level_2(fits_file=input_dir, output_dir=output_dir)

        all_issues.extend(issues)
        all_issues.append(
                        Issue(
                            level="info",
                            message=(f"Level 1B completed."),
                            source=__name__,
                        )
                    )
    

    return fits_path, all_issues 