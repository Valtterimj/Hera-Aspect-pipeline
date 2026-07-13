import numpy as np
from astropy.io import fits
from astropy.io.fits import HDUList
from pathlib import Path

from aspect_pipeline.utils.classes import Issue


def flat_field_calibration(hdul: HDUList, flat: Path) -> tuple[HDUList, list[Issue]]:
    """
    Applies flatfield correction to each 2D frame on the channel
    
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
    channel = header.get('CHANNELS') # Channel (Vis, NIR1, NIR2, SWIR)

    if channel == 'SWIR':
            return hdul, all_issues
    
    try: 
        with fits.open(flat) as flat_hdul:
            flat_field = flat_hdul[0].data
    except Exception as e:
        all_issues.append(
                    Issue(
                        level="error",
                        message=(f"Caught Exception while reading flat field for channel {channel}: {e}"),
                        source=__name__,
                    )
        )
        return hdul, all_issues
    
    # Flat field correction
    try:
        # To store the calibrated datacube
        new_data_cube = hdu.data.astype(np.float64, copy=True)

        new_data_cube /= flat_field
        new_data_cube = np.nan_to_num(new_data_cube, nan=0.0)
        
        hdul[0].data = new_data_cube
        all_issues.append(
                    Issue(
                        level="info",
                        message=(f"Flat field corrected for channel {channel}."),
                        source=__name__,
                    )
        )
        return hdul, all_issues
    except Exception as e:
        all_issues.append(
                    Issue(
                        level="warning",
                        message=(f"Flat field correction failed for {channel}; (reason: {e})"),
                        source=__name__,
                    )
        )
        return hdul, all_issues