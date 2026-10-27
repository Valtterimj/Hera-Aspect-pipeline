import logging
import numpy as np
from astropy.io import fits
from astropy.io.fits import HDUList
from pathlib import Path

logger = logging.getLogger(__name__)


def flat_field_calibration(hdul: HDUList, flat: Path) -> HDUList:
    """
    Applies flatfield correction to each 2D frame on the channel

    Parmeters:
        hdul (HDUList): The HDU list of the FITS file that is modified

    Returns:
        The modified HDU list of the FITS file
    """
    # Data from fits file
    hdu = hdul[0]
    header = hdu.header
    data = hdu.data
    channel = header.get('CHANNELS') # Channel (Vis, NIR1, NIR2, SWIR)

    if channel == 'SWIR':
            return hdul

    try:
        with fits.open(flat) as flat_hdul:
            flat_field = flat_hdul[0].data
    except Exception as e:
        logger.error(f"Caught Exception while reading flat field for channel {channel}: {e}")
        return hdul

    # Flat field correction
    try:
        # To store the calibrated datacube
        new_data_cube = hdu.data.astype(np.float64, copy=True)

        new_data_cube /= flat_field
        new_data_cube = np.nan_to_num(new_data_cube, nan=0.0)

        hdul[0].data = new_data_cube
        logger.info(f"Flat field corrected for channel {channel}.")
        return hdul
    except Exception as e:
        logger.warning(f"Flat field correction failed for {channel}; (reason: {e})")
        return hdul