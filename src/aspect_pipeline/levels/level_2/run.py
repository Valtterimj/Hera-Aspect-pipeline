from pathlib import Path

from aspect_pipeline.utils.classes import Issue, Config
from aspect_pipeline.levels.level_2.merge_channels import merge_fits_files

def run_level_2(cfg: Config) -> tuple[Path, list[Issue]]:
    """
    main fucntion to run the level 2.
    """
    all_issues: list[Issue] = []

    input_dir = cfg.run.input_dir
    out_dir = cfg.run.output_dir
    channels = cfg.pipeline.channels

    fits, issues = merge_fits_files(input_dir=input_dir, channels=channels, output_dir=out_dir)
    for issue in issues:
        all_issues.append(issue)

    all_issues.append(
                    Issue(
                        level="info",
                        message=(f"Level 2B completed."),
                        source=__name__,
                    )
                )
    
    return fits, all_issues 