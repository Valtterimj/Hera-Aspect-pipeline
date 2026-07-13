import numpy as np
from astropy.io.fits import HDUList
from astropy.io import fits
from pathlib import Path

from aspect_pipeline.utils.classes import Issue

def dark_subtraction(hdul: HDUList, dark: Path) -> tuple[HDUList, list[Issue]]:

    """
    Function for subtracting a dark frame from each 2D image.

    Parmeters:
        hdul (HDUList): The HDU list of the FITS file that is modified
    
    Returns:
        The modified HDU list of the FITS file
    """
    all_issues: list[Issue] = []

    # Data from fits file
    hdu = hdul[0]
    header = hdu.header
    data = hdu.data
    channel = header.get('CHANNELS')

    if channel == 'SWIR':
            return hdul, all_issues

    try: 
        with fits.open(dark) as dark_hdul:
            dark_frame = dark_hdul[0].data
    except Exception as e:
        all_issues.append(
                    Issue(
                        level="error",
                        message=(f"Caught Exception while reading dark frame for channel {channel}: {e}"),
                        source=__name__,
                    )
        )
        return hdul, all_issues
    
    # Do dark fram correction
    try:
        # To store the calibrated datacube
        new_data_cube = data.astype(np.float64, copy=True)

        new_data_cube -= dark_frame
        new_data_cube = np.clip(new_data_cube, 0, None)

        hdul[0].data = new_data_cube
        all_issues.append(
                    Issue(
                        level="info",
                        message=(f"Dark frame subtracted for channel {channel}."),
                        source=__name__,
                    )
        )
        return hdul, all_issues
    except Exception as e:
        all_issues.append(
                    Issue(
                        level="warning",
                        message=(f"Dark frame subtraction failed for {channel}; (reason: {e})"),
                        source=__name__,
                    )
        )
        return hdul, all_issues