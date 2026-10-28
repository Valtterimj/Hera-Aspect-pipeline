import logging
import numpy as np
from astropy.io.fits import HDUList
from pathlib import Path
import pandas as pd

from aspect_pipeline.utils.errors import CalibrationError

logger = logging.getLogger(__name__)

"""
Function for converting the pixel values into scientific units.

    Description:
        - Iterated over all 2D images inside the data cube multiplying it with a coefficient.
        - Creates a new FITS file with the calibrated data
"""

def parse_radiance_file(txt_path: str | Path) -> pd.DataFrame: 
    """
    Parse a tab-separated radiance clibration file into a Pandas DataFrame
    Reads 4 columns (Wl[nm, Resp.[DN/s], Radiance[W/m2/nm/sr], Response[DN/(s*W/m2/sr/nm)])
    Converts to numeric, drops invalid and keeors the last duplicate, sorts by wavelength.

    Returns a DataFrane with columns:
    ['wl_nm', 'resp_dn_s', 'radiance_w_m2_nm_sr', 'response_dn_per_w']
    """
    try:
        df = pd.read_csv(
            txt_path,
            sep=r"\t+",
            engine="python",
            comment="#",
        )

        df.columns = [c.strip() for c in df.columns]

        expected_cols = 4
        if df.shape[1] != expected_cols:
            raise ValueError(f"Expected {expected_cols} columns, got {df.shape[1]} in {txt_path}")
        
        df.columns = ["wl_nm", "resp_dn_s", "radiance_w_m2_nm_sr", "response_dn_per_w"]

        for c in df.columns:
            df[c] = pd.to_numeric(df[c].astype(str).str.strip(), errors='coerce')
        
        df = df.dropna(subset=["wl_nm"]).reset_index(drop=True)

        df = df.drop_duplicates(subset=['wl_nm'], keep="last")

        df = df.sort_values("wl_nm").reset_index(drop=True)

        return df
    except Exception as e:
        raise CalibrationError(f'Failed to parse radiance file: {txt_path}; reason: {e}')

def interp_values(df: pd.DataFrame, wl: float) -> dict:
    x = df["wl_nm"].to_numpy()
    out = {}
    for col in ["resp_dn_s", "radiance_w_m2_nm_sr", "response_dn_per_w"]:
        y = df[col].to_numpy()
        out[col] = float(np.interp(wl, x, y))
    
    return out

def radiometric_calibration(hdul: HDUList, radiance_file: Path) -> HDUList:
    """
    Function for converting the pixel values into scientific units.

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
    missphase = header.get('MISSPHAS')

    try: 

        df = parse_radiance_file(radiance_file)

        # Get task information from header
        frames = header.get(f'{channel}_FRAMES').split(',')

        new_data_cube = data.astype(np.float64, copy=True)

        for i, frame in enumerate(frames):
            image = new_data_cube[i]
            wl = header.get(f'{channel}_WL_{frame}')
            exposure = header.get(f'{channel}_EXP_{frame}')
            if wl == None:
                logger.warning(f'No wavelength data found for {channel} frame {frame}. Skipping the frame.')
                continue
            if exposure == None:
                logger.warning(f'No exposure data found for {channel} frame {frame}. Skipping the frame.')
                continue

            interp_vals = interp_values(df, float(wl))
            response = float(interp_vals.get('response_dn_per_w'))
            coefficient = float(exposure) * response

            # For simulated and test data use different formula
            if missphase in ('test', 'SIMULATED'):
                dist_sun = 1
                if channel == 'Vis':
                    int_time = 10
                else:
                    int_time = 20
                # coefficient = (1 / response) * (int_time * dist_sun**2)
                # image /= 0.16
                new_data_cube[i] = ((image * coefficient / (int_time * dist_sun**2)) / 0.16).astype(np.float64)
            else:
                new_data_cube[i] = image / coefficient
        
        hdul[0].data = new_data_cube
        logger.info(f'{channel} radiometrically calibrated.')

    except Exception as e:
        logger.warning(f'{channel} radiometric calibration failed: {e}')

    return hdul