import logging
from typing import Literal


Log_level = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

def setup_logging(level: Log_level = "INFO"):
    """
    Configure global logging for the pipeline
    """

    logging.basicConfig(
        level=getattr(logging, level),
        format="%(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )