import logging
import numpy as np
from pathlib import Path
from astropy.io.fits import HDUList

from aspect_pipeline.utils.classes import BadRegion
from aspect_pipeline.utils.errors import CalibrationError

logger = logging.getLogger(__name__)

def parse_bad_pixel_list(txt_path: str | Path) -> list[BadRegion]:
    """
    Parses the tab separated BADPIXELS TXT file into structured region objects. 

    The file foramt should have 5 tab-separated fields per data line:
        Type, Col, Row, SizeX, SizeY
    
    txt_path: str | Path 
        Path to txt file containing bad pixel information

    return: A list of BadRedion elements created based on the txt file
    """

    regions: list[BadRegion] = []

    with open(txt_path, "r", encoding='utf-8', errors='replace') as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            if line.lower().startswith("type"): # Header
                continue
        
            parts = line.split("\t")
            parts = [p.strip() for p in parts if p.strip() != ""]
            if len(parts) != 5:
                logger.warning(f'Error in parsing bad pixels on line {line_no}: Expexted 5 tab fields, got {len(parts)}')
                continue
        
            t, col_s, row_s, sx_s, sy_s = parts
            col = None if col_s == "-" else int(col_s)
            row = None if row_s == "-" else int(row_s)

            regions.append(BadRegion(
                type=t,
                col=col,
                row=row,
                size_x=int(sx_s),
                size_y=int(sy_s)
            ))
        return regions

def slice_region(r: BadRegion) -> tuple[slice, slice]:
    """
    Converts a BadRegion into Numpy index slices (yslice, xslice) for a 2D frame.

    Interpretation rules:
    - P: selects one pixel at (row, col)
    - H: selects rows [row : row+size_y] and cols [x0 : x0+size_x]
    - V: selects rows [y0 : y0+size_y] and cols [col : col+size_x]
    - R: selects rows (row : row+size_y) and cols [col : col+size_X]

    r: BadRegion
        Region definition to convert into slices
    
    return: (yslice, xslice) selecting the pixels from the region
    """
    t = r.type.upper()

    if t == "P":
        if r.row is None or r.col is None:
            raise ValueError("P type requires both row and col")
        return (slice(r.row, r.row + 1), slice(r.col, r.col + 1))
    
    if t == "H":
        if r.row is None:
            raise ValueError("H type requires row")
        x0 = 0 if r.col is None else r.col
        return (slice(r.row, r.row + r.size_y) , slice(x0, x0 + r.size_x))
    
    if t == "V":
        if r.col is None:
            raise ValueError("V type requires a col")
        y0 = 0 if r.row is None else r.row
        return (slice(y0, y0 + r.size_y), slice(r.col, r.col + r.size_x,))
    
    if t == "R":
        if r.row is None or r.col is None:
            raise ValueError("R type requires both row and col")
        return (slice(r.row, r.row + r.size_y), slice(r.col, r.col + r.size_x))
    
    raise ValueError(f"Unknown type: {r.type}")

def slices_to_mask(shape: tuple[int, int], slice_list: list[tuple[slice, slice]]) -> np.ndarray:
    """
    Builds a boolean mask from the sliced regions
    
    shape: tuple[int, int]
        Shape of the frame
    slice_list: list[tuple[slice, slice]]
        List of slice tuples defining all bad pixel regions
    
    returns: Boolean array where True indicates a bad pixel
    """
    mask = np.zeros(shape, dtype=bool)
    for ys, xs in slice_list:
        mask[ys, xs] = True
    return mask

def replace_nan_8neighbor(frame: np.ndarray, max_iter: int = 100) -> np.ndarray:
    """
    Fill NaN pixels in a frame by interatively averaging finite 8-neighbours
    
    In each iteration:
        - Identify NaN pixels
        - For every pixel, compute:
            s[y, x] = sum of finite neihbour values in the 8-connected neighbourhood
            c[y,x] = count of finite neighbours
        - update only NaN pixels with c>0 using s/c
        - Repeat up to 'max_iter' times or when all NaN pixels are replaced.

    frame: np.ndarray
        2D floating array. Bad pixels must be already set to np.nan
    max_iter: int
        Backup to stop the iteration if it is not done already
    
    returns: A new 2D array with NaNs filled gy the average of neihgbouring pixels.
    """

    a = frame.copy()
    for i in range(max_iter):
        nan_mask = np.isnan(a)
        if not nan_mask.any():
            break

        finite = np.isfinite(a)
        s = np.zeros_like(a, dtype=a.dtype)
        c = np.zeros_like(a, dtype=a.dtype)

        for dy, dx in [(-1, -1), (-1, 0), (-1, 1),
                       ( 0, -1),          ( 0, 1),
                       ( 1, -1), ( 1, 0), ( 1, 1)]:
            
            v = np.roll(a, shift=(dy, dx), axis=(0, 1))
            ok = np.roll(finite, shift=(dy, dx), axis=(0, 1))

            if dy == -1: ok[-1, :] = False
            if dy ==  1: ok[0, :] = False
            if dx == -1: ok[:, -1] = False
            if dx ==  1: ok[:, 0] = False

            s += np.where(ok, v, 0.0)
            c += ok.astype(np.float64)

        fill = nan_mask & (c > 0)
        if not fill.any():
            break
        
        a[fill] = s[fill] / c[fill]

    return a

def replace_bad_pixels(hdul: HDUList, bp_file: Path) -> HDUList:
    """
        Replace bad pixels in a FITS data cube using an external bad-pixel map.

        This function:
        1) Read the data cube from FITS primary HDU
        2) Determines the correct bad pixel list file based on FITS header
        3) Parses the bad-pixel list into regions, converts the regions to slices and constructs the boolean bad-pixel maks.
        4) For each frame:
            - set bad pixels to NaN using the mask
            - fill the NaNs with the neighbouring average and iterative process
        5) Writes the corrected cube back to the HDUList

        hdul: HDUList
            Open FITS HDUList with data stored in the primary HDU
        returns: HDUList with bad-pixel corrected data
    """
    # Data from fits file
    hdu = hdul[0]
    header = hdu.header
    data = hdu.data

    channel = header.get('CHANNELS')

    if channel == 'SWIR':
        return hdul

    try:
        regions = parse_bad_pixel_list(bp_file)
    except Exception as e:
        logger.warning(f'Parsing bad pixel list failed; reason: {e}')
        return hdul

    slice_list = []

    for r in regions:
        try:
            slice_list.append(slice_region(r))
        except ValueError as e:
            logger.warning(f'Error slicing the region {r}; reason: {e}')
            
    try:
        if data.ndim == 2:
            bad_mask = slices_to_mask(data.shape, slice_list)

            new_data = data.astype(np.float64, copy=True)
            new_data[bad_mask] = np.nan
            new_data = replace_nan_8neighbor(new_data)

        elif data.ndim == 3:
            bad_mask = slices_to_mask(data.shape[1:], slice_list)

            new_data = data.astype(np.float64, copy=True)
            for i in range(data.shape[0]):
                bad_frame = new_data[i].copy()
                bad_frame[bad_mask] = np.nan
                new_data[i] = (replace_nan_8neighbor(bad_frame))
        
        else: 
            raise CalibrationError(f"Unsupported data dimensionality: {data.ndim}")

        hdul[0].data = new_data

        logger.info(f"Dad pixels replaced for {channel}")
        return hdul

    except Exception as e:
        logger.warning(f"Bad pixel replacement failed for {channel}; (reason: {e})")
        return hdul
