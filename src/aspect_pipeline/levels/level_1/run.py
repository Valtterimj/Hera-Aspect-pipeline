from pathlib import Path

from aspect_pipeline.utils.classes import Issue, Config, CalibConfig
from aspect_pipeline.utils.utilities import parse_levels_to_run
from aspect_pipeline.utils.validate import _resolve_level_fits_path
from aspect_pipeline.levels.level_1.calibrate_header import calibrate_header
from aspect_pipeline.levels.level_1.level_1b import run_level_1b
from aspect_pipeline.levels.level_1.reflectance import reflectance_calibration

def run_level_1(cfg: Config, channel: str) -> tuple[Path, list[Issue]]:
    """
    main fucntion to run the level 1.
    """
    all_issues: list[Issue] = []

    levels = cfg.pipeline.levels
    levels_to_run = parse_levels_to_run(levels=levels)

    if '1A' in levels_to_run: 
        fits_path = _resolve_level_fits_path(input_dir=cfg.run.input_dir, channel=channel, lvl='0A')
        output_dir = cfg.run.output_dir
        fits_path, issues = calibrate_header(fits_path=fits_path, output_dir=output_dir, channel=channel)
        all_issues.extend(issues)
        all_issues.append(
                        Issue(
                            level="info",
                            message=(f"Level 1A completed."),
                            source=__name__,
                        )
                    )
    if '1B' in levels_to_run or '1A-extra' in levels_to_run:
        if '1A' not in levels_to_run:
            fits_path = _resolve_level_fits_path(input_dir=cfg.run.input_dir, channel=channel, lvl="1A")
        calibration_cfg = cfg.calib
        extra = '1A-extra' in levels_to_run
        fits_path, issues = run_level_1b(fits_file=fits_path, output_dir=output_dir, calibration=calibration_cfg, channel=channel, extra=extra)
        all_issues.extend(issues)
        all_issues.append(
                        Issue(
                            level="info",
                            message=(f"Level 1B completed."),
                            source=__name__,
                        )
                    )
    
    if '1C' in levels_to_run:
        if '1B' not in levels_to_run:
            fits_path = _resolve_level_fits_path(input_dir=cfg.run.input_dir, channel=channel, lvl="1B")
        calibration_cfg = cfg.calib
        solar_ssi = Path(calibration_cfg.calibration_dir) / calibration_cfg.solar_ssi
        fits_path, issues = reflectance_calibration(fits_path=fits_path, output_dir=output_dir, solar_ssi=solar_ssi)
        all_issues.extend(issues)
        all_issues.append(
                        Issue(
                            level="info",
                            message=(f"Level 1C completed."),
                            source=__name__,
                        )
                    )

    return fits_path, all_issues 