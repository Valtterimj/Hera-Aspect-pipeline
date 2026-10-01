import shutil

from jinja2 import Environment, FileSystemLoader
from pathlib import Path

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

    metadata["start_date_time"] = convert_to_zulu_time(metadata['start_date_time'])
    metadata["processing_level"] = convert_processing_levels(proclevl)
    metadata["reference_list"] = proclevl != '0A'

    template = f"ASPECT_template.xml.j2"

    ### Identification Area ###
    title = f"Hera ASPECT instrument {channel} channel level {proclevl} processed datacube:{stem}"
    metadata["title"] = title

    ### Observation Area ###
    wl_range = 'Visible'
    if channel in ['NIR1', 'NIR2']:
        wl_range = 'Near Infrared'
    elif channel == 'SWIR':
        wl_range = 'Infrared'
    metadata['wl_range'] = wl_range

    ### Investigation Area ###
    # lid_reference for comet interception 
    #TODO: correct the right lid once comet interceptor dictionary is done.
    mission_lid = "urn:nasa:pds:context:investigation:mission.hera"
    metadata['mission_lid'] = mission_lid

    ### Observing System ###
    #TODO: correct the right name and lids 
    observing_system_name = f'ASPECT_{channel}'
    metadata['os_name'] = observing_system_name
    # Host
    aspect_lid = "urn:nasa:pds:contect:instrument_host.spacecraft.aspect"
    metadata['aspect_lid'] = aspect_lid
    # Instrument
    instrument_lid = f"urn:nasa:pds:contect:instrument:.aspect.{channel_lower}"
    metadata['instrument_lid'] = instrument_lid

    ### Image dictionary ###
    radiometric_type = 'Spectral Radiance'
    if proclevl == '1C': 
        radiometric_type = 'Radiance Factor'
    metadata['radiometric_type'] = radiometric_type

    ### Spectral Dictionary ###
    # The net integration time for FPI is the full observation interval
    #TODO: figure how the 'full observation interval' is determined
    net_integration_time = 1
    metadata['net_integration_time'] = net_integration_time

    ### Spectral Characteristics ###
    # Bin description
    sampling_interval = 30
    metadata['sampling_interval'] = sampling_interval
    bin_width = 30
    metadata['bin_width'] = bin_width
    
    wavelengths = get_wavelengths(fits_file=fits_path)
    if wavelengths != None:
        first_center = wavelengths[0]
        last_center = wavelengths[-1]
        metadata['first_center'] = first_center
        metadata['last_center'] = last_center

    
    ### File Area ###
    # Map FITS logical dtype (after BZERO scaling) to PDS4 Element_Array data_type.
    # Byte size is inferred by the validator from FITS BITPIX, not the type name.
    _dtype_to_pds4 = {
        'uint16':  'UnsignedMSB2',
        'uint32':  'UnsignedMSB4',
        '>f4':     'IEEE754MSBSingle',
        'float32': 'IEEE754MSBSingle',
    }
    primary_dtype = metadata['extensions'][0]['data_dtype']
    metadata['pds4_data_type'] = _dtype_to_pds4.get(primary_dtype, 'IEEE754MSBSingle')

    if proclevl in ('0A', '1A'):
        metadata['data_unit'] = 'DN'
    elif proclevl in ('1A-extra', '1B'):
        metadata['data_unit'] = 'W*m**-2*sr**-1*nm**-1'
    else:  # 1C
        metadata['data_unit'] = '1'

    # local_identifier used for the primary data array; referenced in Discipline_Area
    metadata['data_local_id'] = 'data_cube' if channel in ['Vis', 'NIR1', 'NIR2'] else 'data_spectrum'
    # sp:spectrum_format: 3D hyperspectral cube for Vis, NIR1, NIR2, 1D spectrum for SWIR
    metadata['spectrum_format'] = '3D' if channel in ['Vis', 'NIR1', 'NIR2'] else '1D'

    env = Environment(loader=FileSystemLoader(templates_dir))
    template = env.get_template(template)
    label_xml = template.render(**metadata)
    
    product_dir = Path(output_path) / stem
    product_dir.mkdir(parents=True, exist_ok=True)

    (product_dir / f"ASPECT_{stem}.xml").write_text(label_xml, encoding="utf-8")
    shutil.copy2(fits_path, product_dir / fits_path.name)
    return 
