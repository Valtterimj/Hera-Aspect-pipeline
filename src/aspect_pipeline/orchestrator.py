import logging
from pathlib import Path

from aspect_pipeline.config import load_config, load_pds4_config
from aspect_pipeline.utils.errors import PipelineError, ValidationError, ConfigError, format_exeption_chain
from aspect_pipeline.utils.validate import validate_output_dir
from aspect_pipeline.utils.utilities import find_fits_files
from aspect_pipeline.utils.loggin_config import log_section, print_summary

from aspect_pipeline.levels.level_0.run import run_level_0
from aspect_pipeline.levels.level_1.run import run_level_1
from aspect_pipeline.levels.level_2.run import run_level_2

from aspect_pipeline.pds4.generate_pds4_label import generate_label, copy_schemas


logger = logging.getLogger(__name__)

def run_pipeline(config_path: Path | None) -> None:
    """
    Main function to run the calibration and data analysis pipeline for Hera ASPECT instrument.
    """

    #TODO: adjust the calibration conversion values and test level 1 run for all channels.

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
    acq_id = cfg.data.acq_id
    output_dir = cfg.run.output_dir

    # Resolve the output directory
    try:
        output_path = validate_output_dir(output_dir=output_dir, acq_id=acq_id)
        cfg.run.output_dir = output_path
        logger.info(f"Output directory resolved: {output_path}")
    except ConfigError or ValidationError as e:
        logger.error(f"[%s] Resolving output directory failed: {e}.", type(e).__name__, format_exeption_chain(e))
        raise PipelineError("Resolving output directory failed")
    
    logger.info(f"Running pipeline levels: {levels} for channels: {channels}.")

    if "0A" in levels:
        for channel in cfg.pipeline.channels:
            with log_section(f"Level 0 · {channel}"):
                try:
                    fits_file = run_level_0(cfg=cfg, channel=channel)
                except PipelineError as e:
                    logger.error(
                        f"Error running pipeline for channel %s. continuing. %s",
                        channel,
                        format_exeption_chain(e),
                        exc_info=logger.isEnabledFor(logging.DEBUG),
                    )
                    continue
        cfg.run.input_dir = cfg.run.output_dir # Next level should use the output of this level

    if any(x in levels for x in ["1A", "1A-extra", "1B", "1C"]):
        for channel in cfg.pipeline.channels:
            with log_section(f"Level 1 · {channel}"):
                try:
                    fits_file = run_level_1(cfg=cfg, channel=channel)
                except PipelineError as e:
                    logger.error(
                        f"Error running pipeline for channel %s. Continuing. %s",
                        channel,
                        format_exeption_chain(e),
                        exc_info=logger.isEnabledFor(logging.DEBUG),
                        )
                    continue
        cfg.run.input_dir = cfg.run.output_dir # Next level should use the output of this level

    if '2' in levels:
        with log_section("Level 2"):
            try:
                fits_file = run_level_2(cfg=cfg)
                cfg.run.input_dir = cfg.run.output_dir # Next level should use the output of this level
            except PipelineError as e:
                logger.error(
                    f"Error running pipeline level 2. continuing. %s",
                    format_exeption_chain(e),
                    exc_info=logger.isEnabledFor(logging.DEBUG),
                )


    if any(x in levels for x in ["3A", "3B", "3C"]):
        from aspect_pipeline.levels.level_3.run import run_level_3
        try:
            logger.info(f'Running level 3')

            fits_file, all_issues = run_level_3(cfg=cfg)

        except PipelineError as e:
            logger.error(
                f"Error running pipeline level 3. continuing. %s",
                format_exeption_chain(e)
            )
    
    logger.info(f"Pipeline run correctly!")
    print_summary()


def run_generate_pds4(config_path: Path) -> None:
    """
    Main function to generate pds4 labels
    """

    logger.info("Staring pipeline function: run_generate_pds4")

    try:
        cfg = load_pds4_config(config_path=config_path)
    except ConfigError as e: 
        logger.error(f"[%s] Loading config failed: {e}", type(e).__name__)
        raise

    input = cfg.input
    output = cfg.output
    products = cfg.products
    channels = cfg.channels
    templates_dir = cfg.templates_dir
    if not output or output.is_dir():
            output = input / 'pds4'

    schemas_source_dir = templates_dir.parent / "pds4_templates" / "schema"

    if input.is_file():
        logger.info(f"Generating PDS4 product for file: {input}")
        try: 
            generate_label(input, templates_dir, output, config=cfg)
        except Exception as e:
            raise PipelineError(f'Generating PDS4 label failed for file: {input} \nreason: {e}') 
    
    else:
        logger.info(f"Generating PDS4 products for levels: {products}")
        matches, missing = find_fits_files(input, products, channels)
        if len(missing) > 0:
            logger.warning(f"Missing fits files for the processing levels: {missing}.")
        for file in matches:
            path = file if isinstance(file, Path) and file.is_file() else input / (file.name if hasattr(file, 'name') else file)
            try: 
                generate_label(path, templates_dir, output, config=cfg)
                logger.info(f"PDS4 product created for {file}. Saved to: {output}")
            except Exception as e:
                raise PipelineError(f'Generating PDS4 label failed for file: {file} \nreason: {e}') 

    copy_schemas(schema_source_dir=schemas_source_dir, output_pds4_dir=output)
        