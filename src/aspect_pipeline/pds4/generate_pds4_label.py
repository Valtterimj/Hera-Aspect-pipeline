import logging
import traceback
from pathlib import Path

from aspect_pipeline.pds4.common import (
    CHANNEL_DISPLAY_MAP,
    copy_schemas,
    find_level1_labels_in_pds4,
    find_level2_label_in_pds4,
    resolve_version,
)
from aspect_pipeline.pds4.fits_reader import read_fits_metadata
from aspect_pipeline.pds4.level_1 import generate_level1_label
from aspect_pipeline.pds4.level_2 import generate_level2_label
from aspect_pipeline.pds4.level_3 import generate_level3_label
from aspect_pipeline.utils.classes import Config, pds4_config
from aspect_pipeline.utils.utilities import parse_filename

logger = logging.getLogger(__name__)

__all__ = [
    "generate_label",
    "generate_level1_label",
    "generate_level2_label",
    "generate_level3_label",
    "copy_schemas",
    "resolve_version",
    "find_level1_labels_in_pds4",
    "find_level2_label_in_pds4",
    "CHANNEL_DISPLAY_MAP",
]


def generate_label(
    fits_path: Path,
    templates_dir: Path,
    output_path: Path,
    config: pds4_config | Config | Path | str | None = None,
    major_version: str | None = None,
    minor_version: str | None = None,
    config_path: Path | str | None = None,
) -> None:
    """
    Generate PDS4 label for a fits file and save it to the output path.
    Routes to generate_level1_label, generate_level2_label, or generate_level3_label
    based on the processing level of the FITS file.
    """
    try:
        proclevl = ""
        try:
            parsed = parse_filename(fits_path.name)
            if parsed and parsed.processing_level:
                proclevl = parsed.processing_level
        except Exception:
            pass

        if not proclevl:
            meta = read_fits_metadata(fits_path)
            proclevl = meta.get("proclevl", "")

        if proclevl == "0A":
            print(f"Skipping Level 0A file: {fits_path.name}")
            return

        if proclevl in ("1A", "1A-extra", "1B", "1C"):
            generate_level1_label(
                fits_path=fits_path,
                templates_dir=templates_dir,
                output_path=output_path,
                config=config,
                major_version=major_version,
                minor_version=minor_version,
                config_path=config_path,
            )
        elif proclevl in ("2", "2A", "2B"):
            generate_level2_label(
                fits_path=fits_path,
                templates_dir=templates_dir,
                output_path=output_path,
                config=config,
                major_version=major_version,
                minor_version=minor_version,
                config_path=config_path,
            )
        elif proclevl.startswith("3"):
            generate_level3_label(
                fits_path=fits_path,
                templates_dir=templates_dir,
                output_path=output_path,
                config=config,
                major_version=major_version,
                minor_version=minor_version,
                config_path=config_path,
            )
        else:
            # Fallback for unrecognized levels
            generate_level1_label(
                fits_path=fits_path,
                templates_dir=templates_dir,
                output_path=output_path,
                config=config,
                major_version=major_version,
                minor_version=minor_version,
                config_path=config_path,
            )

    except Exception as e:
        print(f"\n ERROR generating label for {fits_path.name}:")
        traceback.print_exc()
        raise e
