import logging
from pathlib import Path

from aspect_pipeline.config import load_config, load_pds4_config
from aspect_pipeline.utils.classes import Issue
from aspect_pipeline.utils.errors import PipelineError, ValidationError, ConfigError, format_exeption_chain
from aspect_pipeline.utils.validate import _validate_output_dir
from aspect_pipeline.utils.utilities import log_issue

from aspect_pipeline.levels.level_0.run import run_level_0


logger = logging.getLogger(__name__)

def run_pipeline(config_path: Path | None) -> None:
    """
    Main function to run the calibration and data analysis pipeline for Hera ASPECT instrument.
    """

    #TODO: adjust the calibration conversion values and test level 1 run for all channels.

    issues: list[Issue] = []

    logger.info(f"Starting the main pipeline. Config file provided: {config_path}")

    try:
        cfg = load_config(config_path=config_path)
    except Exception or ConfigError as e: 
        logger.error(f"[%s] Loading config failed: [%s]", type(e).__name__, format_exeption_chain(e))
        raise

    cfg_path = cfg.config_path
    levels = cfg.pipeline.levels
    channels = cfg.pipeline.channels
    logger.info(f"Configurations loaded from {cfg_path}")

    missphas = cfg.data.missphas
    output_dir = cfg.run.output_dir
    try:
        output_path = _validate_output_dir(output_dir=output_dir, missphas=missphas)
        cfg.run.output_dir = output_path
        logger.info(f"Output directory resolved: {output_path}")
    except ConfigError or ValidationError as e:
        logger.error(f"[%s] Resolving output directory failed: {e}.", type(e).__name__, format_exeption_chain(e))
        raise PipelineError("Resolving output directory failed")
    
    logger.info(f"Running pipeline levels: {levels} for channels: {channels}.")

    if "0A" in levels:
        for channel in cfg.pipeline.channels:
            try:
                logger.info(f"Running level 0 for channel {channel}.")
                fits_file, all_issues = run_level_0(cfg=cfg, channel=channel)
                for issue in all_issues:
                    log_issue(issue)
                    if issue.level == 'warning' or issue.level == 'error':
                        issues.append(issue)
                logger.info(f"Level 0 run finished for channel {channel}.")
            except PipelineError as e:
                logger.error(
                    f"Error running pipeline for channel %s. continuing. %s",
                    channel,
                    format_exeption_chain(e)
                )
                continue
    
    logger.info(f"Pipeline run correctly!")