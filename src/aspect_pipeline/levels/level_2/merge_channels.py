import os
import logging
import numpy as np
import cv2
from astropy.io import fits
from astropy.io.fits import Header, ImageHDU
from astropy.table import Table, hstack
from pathlib import Path
from typing import Any


from aspect_pipeline.utils.utilities import get_path, get_frame, parse_filename, generate_filename
from aspect_pipeline.utils.errors import PipelineError

from aspect_pipeline.levels.level_2.transformation_matrix import estimate_matrix

logger = logging.getLogger(__name__)

"""
    Function for aligning vis channel images with nir channel images 
    based on asteroid edge detection, feature extraction, and feature matching.

    Steps of the method:
    1. Edge detection 
        Detecting contours of the asteroid using second-order derivative based Laplacian method.
    2. Feature extraction
        Oriented FAST and Rotated BRIEF (ORB) function for detecting FAST keypoints with an orientation
        and BRIEF binary descriptors for keypoints.
    3. Feature matching
        Fast Library for Approximate Nearest Neighbour (FLANN) with LSH for matching keypoints from vis image to nir image keypoints 
        based on approximating their descriptor similarity with locality-sensitive hashing.
        The matches are filtered based by the distance between the first and the second match candidate.
    4. Estimating transformation matrix
        Estimating a 3x3 transformation matrix based on the feature matches using random sample consensus (RANSAC)
    5. Aligning the image
        Applying the transformation matrix to map the visible images to have the same dimensions as near-infrared images
        so that the asteroid appears same sized at the same (x,y) location on the image

"""

def combine_primary_headers(headers: list[Header]) -> Header:
    if not headers:
        raise ValueError('No headers provided for combination')

    channel_order = ['Vis', 'NIR1', 'NIR2', 'SWIR'] # Ensure the order remains in header
    by_channel = {hdr.get('CHANNELS'): hdr for hdr in headers}
    ordered_channels = [c for c in channel_order if c in by_channel]

    if len(ordered_channels) == 1:
        logger.warning(f"Only one header to combine in level 2.")
        return by_channel[ordered_channels[0]]

    base_channel = ordered_channels[0]
    combined_header = by_channel[base_channel].copy()
    combined_header['ORIGFILE'] = ('dc_X_exp_XXX.bin', 'Original file name.')
    combined_header['PROCLEVL'] = ('2B', 'Calibration level')

    def copy_header_key(source: Header, target: Header, key: str):
        if key in source:
            value = source[key]
            comment = source.comments[key]
            if key in target:
                target[key] = (value, comment)
            else:
                target.append((f'HIERARCH {key}', value, comment))
        else:
            channel = source.get('CHANNELS')
            logger.error(f"Key '{key}' not found in source '{channel}' header; skipping.")

    try:
        for channel in ordered_channels[1:]:
            hdr = by_channel[channel]
            copy_header_key(hdr, combined_header, f'{channel}_CCDTEMP')
            copy_header_key(hdr, combined_header, f'{channel}_FPI_TEMP1')
            copy_header_key(hdr, combined_header, f'{channel}_FPI_TEMP2')
            copy_header_key(hdr, combined_header, f'{channel}_ORDER')
            copy_header_key(hdr, combined_header, f'{channel}_FRAMES')
            copy_header_key(hdr, combined_header, f'{channel}_TASK_NUMBER')
            frames = hdr[f'{channel}_FRAMES'].split(',')
            for num in frames:
                copy_header_key(hdr, combined_header, f'{channel}_TASK_{num}')
            for num in frames:
                copy_header_key(hdr, combined_header, f'{channel}_EXP_{num}')
            for num in frames:
                copy_header_key(hdr, combined_header, f'{channel}_WL_{num}')
        combined_header['CHANNELS'] = (','.join(ordered_channels), 'Instrument channels')
    except Exception as e:
        logger.warning(f"Combining headers failed: {e}")
        logger.warning(f'Returning the first header.')
        return headers[0]
    return combined_header

def append_header(hdu: ImageHDU, dict: dict[str, Any]) -> ImageHDU:
    header = hdu.header
    for key, value in dict.items():
        header[key] = value
    return hdu

def merge_fits_files(input_dir: str | Path, channels: list[str], output_dir: str | Path) -> str:
    """
        Combines the FITS files into one single files containing the hyperspectral data cube.
        If the files list contains Vis channel the Vis channel is aligned into same grid with the NIR channel images.
        If the fiels contains the SWIR channel .... 
    
        Parameters:
            files (List[str | Path]): List of all fits files to be combined.
            output_dir (str | Path): Path to the directory where the new file is stored.
    
        Returns 
            (str): path to the created FITS file

    """

    channel_files = {
        'Vis'   : get_path(input_dir, processing_level='1C', subunit='vis', extension='fits') if 'Vis' in channels else None,
        'NIR1'  : get_path(input_dir, processing_level='1C', subunit='nir1', extension='fits') if 'NIR1' in channels else None,
        'NIR2'  : get_path(input_dir, processing_level='1C', subunit='nir2', extension='fits') if 'NIR2' in channels else None,
        'SWIR'  : get_path(input_dir, processing_level='1C', subunit='swir', extension='fits') if 'SWIR' in channels else None,
    }

    valid = [(name, p) for name, p in channel_files.items() if p is not None]

    if len(valid) <= 1:
        logger.error(f"A single channel cannot be combined.\nfiles: {channel_files}")
        raise PipelineError("Level 2 needs more than one channel")

    present = {name for name, _ in valid}
    primary_header_list = []
    image_dict = {}
    cds_dict = {}
    swir_data = None

    for c , file in valid:
        try:
            with fits.open(file) as hdul:
                primary_hdu = hdul[0]
                primary_header = primary_hdu.header
                primary_data = primary_hdu.data
                primary_header_list.append(primary_header.copy())

                if c in ('Vis', 'NIR1', 'NIR2'):
                    image_dict[c] = primary_data
                    if c in ('NIR1', 'NIR2'):
                        if 1 < len(hdul):
                            cds_dict[c] = Table(hdul[1].data, copy=True)
                else:
                    swir_data = primary_data
        except Exception as e:
            logger.error(f"Error in reading channel data {c}: {e}")
            raise PipelineError(f"Reading channel data failed: {e}", channel=c, level='2B', path=str(file)) from e

    # New header
    new_primary_header = combine_primary_headers(primary_header_list)

    new_image_data = []

    if 'Vis' in present and present & {'NIR1', 'NIR2'}:

        vis = get_frame(channel_files['Vis'], 0)
        nir = get_frame(channel_files['NIR1'] or channel_files['NIR2'], 0)

        transform_matrix = estimate_matrix(vis, nir, filter=True) # Use filter true

        vis_data =  image_dict.get('Vis')
        for frame in vis_data:
            # Convert to little-endian float32 for OpenCV
            little_endian = np.ascontiguousarray(frame.astype('<f4'))
            wrapped = cv2.warpPerspective(little_endian, transform_matrix, (640, 512), flags=cv2.INTER_LINEAR )
            # Convert back to big_endian float32
            big_endian = np.ascontiguousarray(wrapped.astype('>f4'))
            new_image_data.append(big_endian)
    else:
        vis_data =  image_dict.get('Vis')
        if vis_data is not None and vis_data.size > 0:
            for frame in vis_data:
                new_image_data.append(frame)

    nir1_data = image_dict.get('NIR1')
    nir2_data = image_dict.get('NIR2')
    if nir1_data is not None and nir1_data.size > 0:
        for frame in nir1_data:
            new_image_data.append(frame)
    if nir2_data is not None and nir2_data.size > 0:
        for frame in nir2_data:
            new_image_data.append(frame)

    # Combine data into one cube
    data_cube = np.stack(new_image_data, axis=0)
    new_primary_hdu = fits.PrimaryHDU(data_cube, new_primary_header)

    # new hdul 
    new_hdul = [new_primary_hdu]

    # Add data to the data cube
    if swir_data is not None:
        swir_hdu = fits.ImageHDU(data=swir_data, name='SWIR')
        new_hdul.append(swir_hdu)
    
    # Extract HDUs containing the binary tables
    if 'NIR1' in cds_dict and 'NIR2' in cds_dict:
        # Combine all columns from both tables
        combined_table_astropy = hstack([cds_dict['NIR1'], cds_dict['NIR2']], join_type='exact')
        combined_table = fits.BinTableHDU(data=combined_table_astropy.as_array())
        new_hdul.append(combined_table)
    elif 'NIR1' in cds_dict:
        combined_table = fits.BinTableHDU(data=cds_dict['NIR1'].as_array())
        new_hdul.append(combined_table)
    elif 'NIR2' in cds_dict:
        combined_table = fits.BinTableHDU(data=cds_dict['NIR2'].as_array())
        new_hdul.append(combined_table)
    
    hdu_list = fits.HDUList(new_hdul)
    # File name for new fits
    old_name_atr = parse_filename(valid[0][1])
    old_name_atr.subunit = '_'.join(ch.lower() for ch, _ in valid)
    old_name_atr.processing_level = '2B'
    fits_name = generate_filename(old_name_atr)
    new_primary_hdu.header['FILENAME'] = fits_name # PrimaryHDU holds a copy of new_primary_header

    # Create the new fits file with dark-subtracted images
    fits_file = os.path.join(output_dir, fits_name)
    hdu_list.writeto(fits_file, overwrite=True)

    logger.info(f"Merged files {present}")

    return fits_file