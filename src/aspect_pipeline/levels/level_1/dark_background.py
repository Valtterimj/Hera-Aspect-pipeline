import logging
import numpy as np
from astropy.io.fits import HDUList
from astropy.io import fits
from pathlib import Path

logger = logging.getLogger(__name__)

def dark_subtraction(hdul: HDUList, dark: Path) -> HDUList:

    """
    Function for subtracting a dark frame from each 2D image.

    Parmeters:
        hdul (HDUList): The HDU list of the FITS file that is modified

    Returns:
        The modified HDU list of the FITS file
    """
    # Data from fits file
    hdu = hdul[0]
    header = hdu.header
    data = hdu.data
    channel = header.get('CHANNELS')

    if channel == 'SWIR':
            return hdul

    try:
        with fits.open(dark) as dark_hdul:
            dark_frame = dark_hdul[0].data
    except Exception as e:
        logger.error(f"Caught Exception while reading dark frame for channel {channel}: {e}")
        return hdul

    # Do dark fram correction
    try:
        # To store the calibrated datacube
        new_data_cube = data.astype(np.float64, copy=True)

        new_data_cube -= dark_frame
        new_data_cube = np.clip(new_data_cube, 0, None)

        hdul[0].data = new_data_cube
        logger.info(f"Dark frame subtracted for channel {channel}.")
        return hdul
    except Exception as e:
        logger.warning(f"Dark frame subtraction failed for {channel}; (reason: {e})")
        return hdul