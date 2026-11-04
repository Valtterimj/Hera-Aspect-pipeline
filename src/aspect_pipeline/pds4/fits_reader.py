from astropy.io import fits
from pathlib import Path

"""
Read metadata from a FITS file for PDS4 label generation. 
Extracts header keywords, file structure (offset/size of header and data),
and returns a dictionary ready for Jinja2 rendering.
"""

# FITS header keywords used in PDS4 label
KEYWORDS = {
    # PDS4 label field      : FITS header field
    "origin"                : "ORIGIN",
    "instrument_name"       : "INSTRUME",
    "file_name"             : "FILENAME",
    "original_file"         : "ORIGFILE",
    "creation_date_time"    : "DATE",
    "proclevl"              : "PROCLEVL",
    "start_date_time"       : "DATE_OBS",
    "sc_clock"              : "SC_CLK",
    "target"                : "OBJECT",
    "mk_file_name"          : "SPICE_MK",
    "sc_distance"           : "SOLAR_D",
    "target_distance"       : "TRG_DIST",
    "solar_elongation"      : "SOL_ELNG",
    "channel"               : "CHANNELS",
    "vis_ccdtemp"           : "Vis_CCDTEMP",
    "vis_fpi_temp1"         : "Vis_FPI_TEMP1",
    "vis_fpi_temp2"         : "Vis_FPI_TEMP2",
    "nir1_ccdtemp"           : "NIR1_CCDTEMP",
    "nir1_fpi_temp1"         : "NIR1_FPI_TEMP1",
    "nir1_fpi_temp2"         : "NIR1_FPI_TEMP2",
    "nir2_ccdtemp"           : "NIR2_CCDTEMP",
    "nir2_fpi_temp1"         : "NIR2_FPI_TEMP1",
    "nir2_fpi_temp2"         : "NIR2_FPI_TEMP2",
    "swir_ccdtemp"           : "SWIR_CCDTEMP",
    "swir_fpi_temp1"         : "SWIR_FPI_TEMP1",
    "swir_fpi_temp2"         : "SWIR_FPI_TEMP2",
}

def _read_keywords(header: fits.Header, keyword_map: dict) -> dict:
    return {
        field: header.get(fits_key, None) for field, fits_key in keyword_map.items()
    }

def _get_data_layout(hdul: fits.HDUList) -> list[dict]:
    """
    Calculate the byte offset and byte length of the header blocks and data blocks.
    FITS files are divided into fixed-size 2880-byte blocks each extension consist of:
    - One or more 2880-byte header blocks
    - zero or more 2880-byte data blocks

    Returns a list of dicts, one per extension.
    """

    BLOCK_SIZE = 2880
    extensions = []
    current_offset = 0

    for i, hdu in enumerate(hdul):
        n_cards = len(hdu.header)
        header_blocks = ((n_cards + 1) * 80 + BLOCK_SIZE - 1) // BLOCK_SIZE
        header_length = header_blocks * BLOCK_SIZE

        if hdu.data is not None:
            raw_data_legth = hdu.data.nbytes
            data_blocks = (raw_data_legth + BLOCK_SIZE - 1) // BLOCK_SIZE
            data_length = data_blocks * BLOCK_SIZE
            data_shape = hdu.data.shape
            data_dtype = str(hdu.data.dtype)
        else:
            data_length = 0
            data_shape = None
            data_dtype = None
        
        data_offset = current_offset + header_length

        extensions.append({
            "index"             : i,
            "name"              : hdu.name,
            "extension_type"    : type(hdu).__name__,
            "header_offset"     : current_offset,
            "header_length"     : header_length,
            "data_offset"       : data_offset,
            "data_length"       : data_length,
            "data_shape"        : data_shape,
            "data_dtype"        : data_dtype
        })

        current_offset = data_offset + data_length

    return extensions


def read_fits_metadata(fits_path: Path) -> dict:
    """
    Main entry point. Given a path to a FITS file, return a dictionary of metadata.
    """

    path = Path(fits_path)

    with fits.open(path) as hdul:

        primary_header = hdul[0].header

        keywords = _read_keywords(primary_header, KEYWORDS)
        extensions = _get_data_layout(hdul)

        channels = keywords.get('channel')
        if channels is not None:
            channel_info = {}
            channel_list = channels.split(',')
            for ch in channel_list:
                ch_frames = primary_header.get(f'{ch}_FRAMES')
                ch_frame_n = len(ch_frames.split(','))
                ch_order = primary_header.get(f'{ch}_ORDER')
                channel_info[f'{ch}_frame_n'] = ch_frame_n
                channel_info[f'{ch}_order'] = ch_order


    file_info = {
        "file_name"         : path.name,
        "file_size"         : path.stat().st_size,
        "n_extensions"      : len(extensions)
    }

    metadata = {
        **file_info,
        **keywords,
        **channel_info,
        "extensions"        : extensions
    }

    return metadata
