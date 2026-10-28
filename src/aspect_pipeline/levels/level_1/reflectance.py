import logging
import numpy as np
from pathlib import Path
from astropy.io import fits
from scipy.ndimage import gaussian_filter1d

from aspect_pipeline.utils.utilities import parse_filename, generate_filename

logger = logging.getLogger(__name__)

def load_ssi_csv(csv_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """
    Load (wavelength, Fsun 1AU Wm2 per nm) from SSI csv file.
    """
    data = np.genfromtxt(csv_path, delimiter=",", comments="#", dtype=float)
    if data.ndim == 1:  # single data row
        data = data[None, :]
    if data.shape[1] < 2:
        raise ValueError("Expected at least two columns: wavelength, value.")
    wl = data[:, 0].astype(float)
    vals = data[:, 1].astype(float)
    return wl, vals

def gaussian_convolution(
        array: np.ndarray,
        x: np.ndarray,
        fwhm: int,
    ) -> np.ndarray:
    step = x[1] - x[0]
    fwhm_to_sigma = 1. / np.sqrt(8. * np.log(2.))
    array_averaged = gaussian_filter1d(array, sigma=(fwhm_to_sigma * fwhm) / step, mode="nearest")
    return array_averaged

def reflectance_calibration(
        fits_path: Path,
        output_dir: Path,
        solar_ssi: Path,
        fwhm_nm: float = 30.0,
    ) -> Path:
    """
    The image is calibrated by pixel linear transformations. The pixels represent I/f reflectance units.

    Parameters: 
        hdul (HDUList) : hdu list containing the Primary HDU data (image) to be converted to I/f 
        solar_ssi: Path to the csv file containing solar spectral irradiance by wavelength (nm)
        fwhm_nm: Full witdth half maximum of how the detector captures light.
    
    Returns: 
        Reflectance unit converted data inside the same hdul 
    """
    try:
        with fits.open(fits_path) as hdul:
            new_hdul = fits.HDUList([hdu.copy() for hdu in hdul])
            primary_hdu = new_hdul[0]
            primary_header = primary_hdu.header.copy()
            data = primary_hdu.data.copy()
            new_hdul[0].header = primary_header
            new_hdul[0].data = data
            channel = primary_header.get('CHANNELS')
            sun_dist = primary_header.get('SOLAR_D')
            frames = primary_header.get(f'{channel}_FRAMES').split(',')
            wavelengths = []
            for i, frame in enumerate(frames):
                wl = primary_header.get(f'{channel}_WL_{frame}')
                if wl == None:
                    logger.warning(f"No wavelength data found for {channel} frame {frame}. Skipping the frame")
                wavelengths.append(wl)

    except Exception as e:
        logger.error(f'Reflectance conversion failed.')
        return fits_path

    try:

        if primary_header.get('MISSPHAS') == 'SIMULATED': # For simulated data
            au = 1.0
            lambertRadianceAt1au = 217.0
            c = lambertRadianceAt1au / au**2

            for i, frame in enumerate(data):
                data[i] = frame / c

        else:

            if sun_dist in (None, 'UNK', 'N/A'):
                logger.warning(f'Sun distance: {sun_dist}; Using default 1AU')
                sun_dist = float(1)
            else:
                sun_dist = float(sun_dist)
            
            if channel == 'SWIR':
                fwhm_nm = 40.0
            
            wl_nm, ssi_vals = load_ssi_csv(solar_ssi)

            ssi_gaussian = gaussian_convolution(ssi_vals, wl_nm, fwhm_nm)   

            for i, frame in enumerate(data):
                wl = wavelengths[i]
                if wl == None:
                    continue
                else:
                    wl = float(wl)
                ssi_index = int(np.interp(wl_nm, wl))
                f_au = ssi_gaussian[ssi_index]
                IF_frame = np.pi * frame * (sun_dist**2) / f_au
            
                data[i] = IF_frame
        primary_hdu.data = data
    except Exception as e:
        logger.error(f'Reflectance conversion failed: {e}')
        return fits_path

    logger.info(f'Data converted to reflectance.')
    # Create new fits file name and write
    try:
        old_name = fits_path.name
        old_name_atr = parse_filename(old_name)
        old_name_atr.processing_level = '1C'
        fits_name = generate_filename(old_name_atr)
        primary_header = hdul[0].header
        primary_header['FILENAME'] = fits_name
        primary_header['PROCLEVL'] = '1C'
        primary_header['FILENAME'] = fits_name
        primary_header['PROCLEVL'] = '1C'
        fits_file = output_dir / fits_name
        new_hdul.writeto(fits_file, overwrite=True)
        logger.info(f"New fits file created: {fits_file}")
    except Exception as e:
        logger.error(f"Error writing fits file: {e}")

    return fits_file

