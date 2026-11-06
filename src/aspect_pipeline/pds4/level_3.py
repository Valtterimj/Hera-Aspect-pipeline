import logging
from pathlib import Path

from aspect_pipeline.pds4.common import (
    CHANNEL_DISPLAY_MAP,
    build_base_metadata,
    find_level1_labels_in_pds4,
    find_level2_label_in_pds4,
    save_pds4_product,
)
from aspect_pipeline.utils.classes import Config, pds4_config

logger = logging.getLogger(__name__)


def generate_level3_label(
    fits_path: Path,
    templates_dir: Path,
    output_path: Path,
    config: pds4_config | Config | Path | str | None = None,
    major_version: str | None = None,
    minor_version: str | None = None,
    config_path: Path | str | None = None,
) -> Path:
    """
    Generate PDS4 label for Level 3 products (3, 3A, 3B, 3C).
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

    template = "ASPECT_template_3.j2"
    lv1_labels = find_level1_labels_in_pds4(
        output_path, default_version_id=version_id
    )

    if parsed_name:
        subunit = parsed_name.subunit.lower()
        descriptor = parsed_name.descriptor
    else:
        subunit = "composition"
        descriptor = "0000"

    if lv1_labels:
        found_channels = [
            c for c in ("vis", "nir1", "nir2", "swir") if c in lv1_labels
        ]
        if not parsed_name:
            descriptor = next(
                (
                    lv1_labels[c]["descriptor"]
                    for c in found_channels
                    if "descriptor" in lv1_labels[c]
                ),
                "0000",
            )
    else:
        header_channels = [
            c.strip().lower() for c in channel.split(",") if c.strip()
        ]
        found_channels = [
            c for c in ("vis", "nir1", "nir2", "swir") if c in header_channels
        ]
        if not found_channels:
            found_channels = ["vis", "nir1", "nir2"]

    lv2_subunit = "_".join(found_channels)

    # Check if Level 2 label exists in pds4 folder
    lv2_label = find_level2_label_in_pds4(
        output_path, default_version_id=version_id
    )
    if lv2_label:
        lv2_lidvid = lv2_label["lidvid"]
    else:
        lv2_lidvid = f"urn:esa:psa:hera:data_derived:asp_der_sc_{lv2_subunit}_{descriptor}::{version_id}"

    # Level 3 references the Level 2 derived product
    source_references = [
        {
            "lidvid": lv2_lidvid,
            "reference_type": "data_to_derived_source_product",
        }
    ]
    print("lv3 references lv2:", lv2_lidvid)
    metadata["derived_to_source_id"] = lv2_lidvid

    print(template)

    instr = "asp"
    product_id = f"{instr}_{psa_level}_{data_type}_{subunit}_{descriptor}"
    metadata["main_logical_lid"] = f"urn:esa:psa:hera:{m_lid_type}:{product_id}"

    metadata["title"] = (
        f"Hera ASPECT instrument Level {proclevl} analysis datacube: {stem}"
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

