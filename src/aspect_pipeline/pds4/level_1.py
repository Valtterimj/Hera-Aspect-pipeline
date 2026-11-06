import logging
from pathlib import Path

from aspect_pipeline.pds4.common import build_base_metadata, save_pds4_product
from aspect_pipeline.utils.classes import Config, pds4_config

logger = logging.getLogger(__name__)


def generate_level1_label(
    fits_path: Path,
    templates_dir: Path,
    output_path: Path,
    config: pds4_config | Config | Path | str | None = None,
    major_version: str | None = None,
    minor_version: str | None = None,
    config_path: Path | str | None = None,
) -> Path:
    """
    Generate PDS4 label for Level 1 products (1A, 1A-extra, 1B, 1C).
    """
    metadata, ctx = build_base_metadata(
        fits_path=fits_path,
        config=config,
        major_version=major_version,
        minor_version=minor_version,
        config_path=config_path,
    )

    proclevl = ctx["proclevl"]
    stem = ctx["stem"]
    parsed_name = ctx["parsed_name"]
    data_type = ctx["data_type"]
    version = ctx["version"]
    version_id = ctx["version_id"]
    channel = ctx["channel"]
    channel_lower = channel.lower() if channel else ""
    channel_names = [c.strip() for c in channel.split(",") if c.strip()]

    metadata["channels"] = [
        {"name": c, "lid": f"urn:nasa:pds:context:instrument:aspect.{c.lower()}"}
        for c in channel_names
    ]

    if proclevl in ("1A", "1A-extra"):
        psa_level = "raw"
        m_lid_type = "data_raw"
    elif proclevl == "1B":
        psa_level = "par"
        m_lid_type = "data_partially_processed"
    elif proclevl == "1C":
        psa_level = "cal"
        m_lid_type = "data_calibrated"
    else:
        psa_level = "raw"
        m_lid_type = "data_raw"

    print("PSA Level:", proclevl)

    template = "ASPECT_template_1.j2"
    if parsed_name:
        subunit = parsed_name.subunit.lower()
        descriptor = parsed_name.descriptor
    else:
        SUBUNIT_MAP = {
            "as0": "vis",
            "as1": "nir1",
            "as2": "nir2",
            "as3": "swir",
        }
        parts = stem.lower().split("_")
        subunit = SUBUNIT_MAP.get(parts[0], channel_lower or "unknown")
        descriptor = "0000"

    print(template)

    instr = "asp"
    product_id = f"{instr}_{psa_level}_{data_type}_{subunit}_{descriptor}"
    metadata["main_logical_lid"] = f"urn:esa:psa:hera:{m_lid_type}:{product_id}"

    metadata["title"] = (
        f"Hera ASPECT instrument {channel} channel level {proclevl} processed"
        f" datacube: {stem}"
    )

    wl_range = "Visible"
    if channel in ["NIR1", "NIR2"]:
        wl_range = "Near Infrared"
    elif channel == "SWIR":
        wl_range = "Infrared"
    metadata["wl_range"] = wl_range

    metadata["radiometric_type"] = (
        "Radiance Factor" if proclevl == "1C" else "Spectral Radiance"
    )

    if proclevl in ("0A", "1A"):
        metadata["data_unit"] = "DN"
    elif proclevl in ("1A-extra", "1B"):
        metadata["data_unit"] = "W*m**-2*sr**-1*nm**-1"
    else:  # 1C
        metadata["data_unit"] = "1"

    is_cube = any(c in channel for c in ["Vis", "NIR1", "NIR2"])
    metadata["data_local_id"] = "data_cube" if is_cube else "data_spectrum"
    metadata["spectrum_format"] = "3D" if is_cube else "1D"

    metadata["source_references"] = []
    metadata["raw_to_source_id"] = (
        f"urn:esa:psa:hera:data_raw:asp_raw_sc_{subunit}_{descriptor}::{version_id}"
    )
    metadata["partially_processe_to_source_id"] = (
        f"urn:esa:psa:hera:data_partially_processed:asp_par_sc_{subunit}_{descriptor}::{version_id}"
    )
    metadata["calibrated_to_source_id"] = (
        f"urn:esa:psa:hera:data_calibrated:asp_cal_sc_{subunit}_{descriptor}::{version_id}"
    )

    metadata["calibrated_to_source_id_vis"] = (
        f"urn:esa:psa:hera:data_calibrated:asp_cal_sc_vis_{descriptor}::{version_id}"
    )
    metadata["calibrated_to_source_id_nir1"] = (
        f"urn:esa:psa:hera:data_calibrated:asp_cal_sc_nir1_{descriptor}::{version_id}"
    )
    metadata["calibrated_to_source_id_nir2"] = (
        f"urn:esa:psa:hera:data_calibrated:asp_cal_sc_nir2_{descriptor}::{version_id}"
    )
    metadata["calibrated_to_source_id_swir"] = (
        f"urn:esa:psa:hera:data_calibrated:asp_cal_sc_swir_{descriptor}::{version_id}"
    )

    return save_pds4_product(
        metadata=metadata,
        template_name=template,
        templates_dir=templates_dir,
        output_path=output_path,
        fits_path=fits_path,
        product_id=product_id,
        version=version,
        stem=stem,
    )

