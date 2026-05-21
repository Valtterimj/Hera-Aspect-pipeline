import logging

logger = logging.getLogger(__name__)

from aspect_pipeline.utils.errors import PipelineError

from aspect_pipeline.config import load_config

def hello():
    print("Hello from hera-aspect-pipeline!")
    logger.info("Hello from hera-aspect-pipeline")
    try:
        cfg = load_config()
        logger.info("Config found")
        print("run")
        print(cfg.run)
        print("calib:")
        print(cfg.calib)
        print("data:")
        print(cfg.data)
        print("pipeline:")
        print(cfg.pipeline)
        
    except PipelineError as e: 
        logger.error(f"[%s] Loading config failed.", type(e).__name__)
        raise



