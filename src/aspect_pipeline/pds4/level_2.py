import logging
from pathlib import Path

from aspect_pipeline.pds4.common import (
    CHANNEL_DISPLAY_MAP,
    build_base_metadata,
    find_level1_labels_in_pds4,
    save_pds4_product,
)
from aspect_pipeline.utils.classes import Config, pds4_config

logger = logging.getLogger(__name__)


def generate_level2_label(
    fits_path: Path,
    templates_dir: Path,
    output_path: Path,
    config: pds4_config | Config | Path | str | None = None,
    major_version: str | None = None,
    minor_version: str | None = None,
    config_path: Path | str | None = None,
) -> Path:
    """
    Generate PDS4 label for Level 2 products (2, 2A, 2B).
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

    psa_level = "der"
    m_lid_type = "data_derived"

    print("PSA Level:", proclevl)

    template = "ASPECT_template_2.j2"
    lv1_labels = find_level1_labels_in_pds4(
        output_path, default_version_id=version_id
    )

    if parsed_name:
        subunit = parsed_name.subunit.lower()
        descriptor = parsed_name.descriptor
        found_channels = [
            c
            for c in ("vis", "nir1", "nir2", "swir")
            if c in subunit.split("_")
        ]
        if not found_channels:
            found_channels = ["vis", "nir1", "nir2"]
    elif lv1_labels:
        found_channels = [
            c for c in ("vis", "nir1", "nir2", "swir") if c in lv1_labels
        ]
        descriptor = next(
            (
                lv1_labels[c]["descriptor"]
                for c in found_channels
                if "descriptor" in lv1_labels[c]
            ),
            "0000",
        )
        subunit = "_".join(found_channels)
    else:
        header_channels = [
            c.strip().lower() for c in channel.split(",") if c.strip()
        ]
        found_channels = [
            c for c in ("vis", "nir1", "nir2", "swir") if c in header_channels
        ]
        if not found_channels:
            found_channels = ["vis", "nir1", "nir2"]
        descriptor = "0000"
        subunit = "_".join(found_channels)

    # References matching each Level 1 product's calibration level
    source_references = []
    for c in found_channels:
        if c in lv1_labels:
            source_references.append({
                "lidvid": lv1_labels[c]["lidvid"],
                "reference_type": lv1_labels[c]["reference_type"],
            })
        else:
            source_references.append({
                "lidvid": (
                    f"urn:esa:psa:hera:data_calibrated:asp_cal_sc_{c}_{descriptor}::{version_id}"
                ),
                "reference_type": "data_to_calibrated_source_product",
            })

    print(template)

    instr = "asp"
    product_id = f"{instr}_{psa_level}_{data_type}_{subunit}_{descriptor}"
    metadata["main_logical_lid"] = f"urn:esa:psa:hera:{m_lid_type}:{product_id}"

    channel_str = "-".join(CHANNEL_DISPLAY_MAP.get(c, c) for c in found_channels)
    metadata["title"] = (
        f"Hera ASPECT instrument merged {channel_str} Level {proclevl}"
        f" processed datacube: {stem}"
    )

    wl_range = "Visible"
    if channel in ["NIR1", "NIR2"]:
        wl_range = "Near Infrared"
    elif channel == "SWIR":
        wl_range = "Infrared"
    metadata["wl_range"] = wl_range

    metadata["radiometric_type"] = "Radiance Factor"
    metadata["data_unit"] = "1"
    metadata["data_local_id"] = "data_cube"
    metadata["spectrum_format"] = "3D"

    metadata["source_references"] = source_references
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

