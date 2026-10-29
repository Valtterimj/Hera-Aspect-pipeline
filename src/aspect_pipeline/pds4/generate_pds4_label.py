import shutil

from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import hashlib
from datetime import timezone, datetime


from aspect_pipeline.pds4.fits_reader import read_fits_metadata
from aspect_pipeline.utils.errors import PipelineError
from aspect_pipeline.utils.utilities import convert_to_zulu_time, convert_processing_levels, get_wavelengths


def generate_label(fits_path: Path, templates_dir: Path, output_path: Path) -> None:
    """
    Generate PDS4 label for a fits file and save it to the output path.
    """
    metadata = read_fits_metadata(fits_path)

    channel = metadata.get('channel')
    channel_lower = channel.lower() if channel else ''
    file_name = metadata.get('file_name')
    stem = file_name.split('.')[0]
    proclevl = metadata['proclevl']
    version = "__1_0"

    if proclevl == '0A':
        print(f'Skipping Level 0A file: {fits_path.name}')
        return
    
    if proclevl in ('1A', '1A-extra'):
        psa_level = 'raw'
        m_lid_type = 'data_raw'
    elif proclevl =='1B':
        psa_level = 'par'
        m_lid_type = 'data_partially_processed'
    elif proclevl == '1C':  #1C
        psa_level = 'cal'
        m_lid_type = 'data_calibrated'
    else:
        psa_level = 'der'
        m_lid_type = 'data_derived'

    if proclevl in ('1A', '1A-extra', '1B', '1C'):
        template = f"ASPECT_template_1.j2"
    elif proclevl in ('2B'):
        template = f"ASPECT_template_2.j2"
    elif proclevl in ('3C'):
        template = f"ASPECT_template_3.j2"

    print("PSA Level:", proclevl)

    data_type = 'sc'  # Science data ('hk' for housekeeping)

    parts = stem.lower().split('_')
    #place holder since name is not updated
    SUBUNIT_MAP = {
        "as0": "vis",
        "as1": "nir1",
        "as2": "nir2",
        "as3": "swir",
    }

    subunit = SUBUNIT_MAP.get(parts[0], "unknown")
    
    instr = "asp"
    descriptor = "1110"
    product_id = f"{instr}_{psa_level}_{data_type}_{subunit}_{descriptor}"

    metadata["start_date_time"] = convert_to_zulu_time(
        metadata['start_date_time'])
    metadata["processing_level"] = convert_processing_levels(proclevl)
    metadata["reference_list"] = proclevl != '0A'

    ### Identification Area ###
    title = f"Hera ASPECT instrument {channel} channel level {proclevl} processed datacube:{stem}"
    metadata["title"] = title

    metadata["main_logical_lid"] = f"urn:esa:psa:hera:{m_lid_type}:{product_id}"

    #mod history
    metadata["modification_date"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    ### Observation Area ###
    wl_range = 'Visible'
    if channel in ['NIR1', 'NIR2']:
        wl_range = 'Near Infrared'
    elif channel == 'SWIR':
        wl_range = 'Infrared'
    metadata['wl_range'] = wl_range

    ### Investigation Area ###
    # lid_reference for comet interception
    mission_lid = "urn:esa:psa:mission.hera"
    metadata['mission_lid'] = mission_lid


    ### Observing System ###
    # TODO: correct the right name and lids
    observing_system_name = f'ASPECT_{channel}'
    metadata['os_name'] = observing_system_name
    # Host
    aspect_lid = "urn:esa:psa:milani.aspect"
    metadata['aspect_lid'] = aspect_lid
    # Instrument
    instrument_lid = f"urn:nasa:pds:context:instrument:aspect.{channel_lower}"
    metadata['instrument_lid'] = instrument_lid

    # Target_Identification
    target = "Didymos" if metadata.get('channel') == "didy" else "Dimorphos"
    target_lid = "urn:nasa:pds:context:asteroid.65803_didymos" if metadata.get(
        'channel') == "didy" else "urn:nasa:pds:context:satellite.65803_didymos.dimorphos"
    metadata['target'] = target
    metadata['target_lid'] = target_lid

    # Mission_Area
    # TODO: Mission_Area

    ### Image dictionary ###
    radiometric_type = 'Spectral Radiance'
    if proclevl == '1C':
        radiometric_type = 'Radiance Factor'
    metadata['radiometric_type'] = radiometric_type

    ### Spectral Dictionary ###
    # The net integration time for FPI is the full observation interval
    # TODO: figure how the 'full observation interval' is determined
    net_integration_time = 1
    metadata['net_integration_time'] = net_integration_time

    ### Spectral Characteristics ###
    # Bin description

    #TODO: check if width differ
    bin_width = 30
    metadata['bin_width'] = bin_width

    # TODO: check if interval is 30 not linear make it dynamic
    wavelengths = get_wavelengths(fits_file=fits_path)
    is_linear = False
    bands = []

    if wavelengths is not None and len(wavelengths) > 0:
        wl_floats = [float(w) for w in wavelengths]
        metadata['first_center'] = wl_floats[0]
        metadata['last_center'] = wl_floats[-1]

        # Pre-build band list in case sampling is non-linear
        bands = [
            {'center_wl': f'{w:.1f}', 'bin_width': f'{bin_width:.1f}'}
            for w in wl_floats
        ]

        if len(wl_floats) > 1:
            diffs = [
                wl_floats[i + 1] - wl_floats[i] for i in range(len(wl_floats) - 1)
            ]
            first_diff = diffs[0]
            if all(abs(d - first_diff) < 0.01 for d in diffs):
                is_linear = True
                metadata['sampling_interval'] = f'{first_diff:.1f}'
            else:
                is_linear = False
                metadata['sampling_interval'] = None
        else:
            is_linear = False
            metadata['sampling_interval'] = None
    else:
        metadata['first_center'] = None
        metadata['last_center'] = None
        metadata['sampling_interval'] = None

    metadata['is_linear'] = is_linear
    metadata['bands'] = bands

    ##Reference_List
    metadata['raw_to_source_id'] = f'urn:esa:psa:hera:data_raw:asp_raw_sc_{subunit}_{descriptor}::1.0'
    metadata['partially_processe_to_source_id'] = f'urn:esa:psa:hera:data_partially_processed:asp_par_sc_{subunit}_{descriptor}::1.0'
    metadata['calibrated_to_source_id'] = f'urn:esa:psa:hera:data_calibrated:asp_cal_sc_{subunit}_{descriptor}::1.0'

    ### File Area ###
    # Map FITS logical dtype (after BZERO scaling) to PDS4 Element_Array data_type.
    # Byte size is inferred by the validator from FITS BITPIX, not the type name.

    # File size
    file_size = fits_path.stat().st_size

    # MD5 checksum
    with open(fits_path, 'rb') as f:
        file_md5_checksum = hashlib.md5(f.read()).hexdigest()

    # Add to metadata dictionary
    metadata["file_size"] = file_size
    metadata["file_md5_checksum"] = file_md5_checksum

    _dtype_to_pds4 = {
        'uint16':  'UnsignedMSB2',
        'uint32':  'UnsignedMSB4',
        '>f4':     'IEEE754MSBSingle',
        'float32': 'IEEE754MSBSingle',
    }
    primary_dtype = metadata['extensions'][0]['data_dtype']
    metadata['pds4_data_type'] = _dtype_to_pds4.get(
        primary_dtype, 'IEEE754MSBSingle')

    if proclevl in ('0A', '1A'):
        metadata['data_unit'] = 'DN'
    elif proclevl in ('1A-extra', '1B'):
        metadata['data_unit'] = 'W*m**-2*sr**-1*nm**-1'
    else:  # 1C
        metadata['data_unit'] = '1'

    # local_identifier used for the primary data array; referenced in Discipline_Area
    metadata['data_local_id'] = 'data_cube' if channel in [
        'Vis', 'NIR1', 'NIR2'] else 'data_spectrum'
    # sp:spectrum_format: 3D hyperspectral cube for Vis, NIR1, NIR2, 1D spectrum for SWIR
    metadata['spectrum_format'] = '3D' if channel in [
        'Vis', 'NIR1', 'NIR2'] else '1D'

    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template(template)
    label_xml = template.render(**metadata)

    product_dir = Path(output_path) / stem
    product_dir.mkdir(parents=True, exist_ok=True)



    (product_dir /
     f"{product_id}{version}.lblx").write_text(label_xml, encoding="utf-8")
    shutil.copy2(fits_path, product_dir / fits_path.name)
    
    return
