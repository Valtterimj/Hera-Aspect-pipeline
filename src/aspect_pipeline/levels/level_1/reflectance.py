import numpy as np
from pathlib import Path
from astropy.io import fits
from scipy.ndimage import gaussian_filter1d

from aspect_pipeline.utils.classes import Issue

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
    all_issues: list[Issue] = []

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
                    all_issues.append(
                        Issue(
                            level='warning',
                            message=f"No wavelength data found for {channel} frame {frame}. Skipping the frame",
                            source=__name__
                        )
                    )
                wavelengths.append(wl)

    except Exception as e:
        all_issues.append(
                Issue(
                    level='error',
                    message=f'Reflectance conversion failed.',
                    source=__name__,
                )
            )
        return fits_path, all_issues

    try: 
        
        if sun_dist in (None, 'UNK', 'N/A'):
            all_issues.append(
                Issue(
                    level='warning',
                    message=f'Sun distance: {sun_dist}; Using default 1AU',
                    source=__name__,
                )
            )
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
            ssi_index = int(np.searchsorted(wl_nm, wl))
            f_au = ssi_gaussian[ssi_index]
            IF_frame = np.pi * frame * (sun_dist**2) / f_au
        
            data[i] = IF_frame
        primary_hdu.data = data
    except Exception as e:
        all_issues.append(
                Issue(
                    level='error',
                    message=f'Reflectance conversion failed: {e}',
                    source=__name__,
                )
            )
        return fits_path, all_issues
    
    all_issues.append(
        Issue(
            level='info',
            message=f'Data converted to reflectance.',
            source=__name__,
        )
    )
    # Create new fits file name and write
    stem = fits_path.stem
    suffix = fits_path.suffix
    new_calibration_level = '1C'
    file_name = stem[:25] + new_calibration_level + suffix
    primary_header['FILENAME'] = file_name
    primary_header['PROCLEVL'] = new_calibration_level
    fits_file = output_dir / file_name
    new_hdul.writeto(fits_file, overwrite=True)
    try:
        new_hdul.writeto(fits_file, overwrite=True)
        all_issues.append(
                Issue(
                    level="info",
                    message=(f"New fits file created: {fits_file}"),
                    source=__name__,
                )
            )
    except Exception:
        all_issues.append(
            Issue(
                level="Error",
                message=(f"Error writing fits dile"),
                source=__name__,
            )
        )
    
    return fits_file, all_issues

