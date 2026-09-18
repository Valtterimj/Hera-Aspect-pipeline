import os
import numpy as np
import cv2
from astropy.io import fits
from astropy.io.fits import Header, PrimaryHDU, ImageHDU, BinTableHDU, HDUList
from astropy.table import Table, hstack
from pathlib import Path
from typing import List
from pathlib import Path
from typing import Any


from aspect_pipeline.utils.classes import Issue
from aspect_pipeline.utils.utilities import get_path, get_frame, channel_to_id

from aspect_pipeline.levels.level_2.transformation_matrix import estimate_matrix

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
    if len(headers) == 1:
        print(f"[WARNING] Only one header to combine in level 2.")
        return headers[0]
    
    combined_header = headers[0].copy()
    combined_header['ORIGFILE'] = ('dc_X_exp_XXX.bin', 'Original file name.')
    combined_header['PROCLEVL'] = ('2B', 'Calibration level')

    def copy_header_key(source: Header, target: Header, key: str, id: int):
        if key in source:
            value = source[key]
            comment = source.comments[key]
            if key in target:
                target[key] = (value, comment)
            else:
                insert_idx = target.index(f'AS{id}_FPI_TEMP2')
                target.insert(insert_idx, (f'HIERARCH {key}', value, comment), after=True)
        else:
            channel = source.get('ASP_CHANNELS')
            print(f"[INFO] Key '{key}' not found in source '{channel}' header; skipping.")

    
    try:
        channel_0 = combined_header.get('ASP_CHANNELS')
        channels = [channel_0]
        for hdr in headers[1:]:
            channel = hdr.get('ASP_CHANNELS')
            channels.append(channel)
            channel_id = channel_to_id[channel]
            task_number = int(hdr.get(f'AS{channel_id}_TASK_NUMBER'))
            copy_header_key(hdr, combined_header, f'AS{channel_id}_CCDTEMP', channel_id)
            copy_header_key(hdr, combined_header, f'AS{channel_id}_FPI_TEMP1', channel_id)
            copy_header_key(hdr, combined_header, f'AS{channel_id}_FPI_TEMP2', channel_id)
            for i in range(task_number - 1, -1, -1):
                num = f'{i:03d}' # e.g. 1 -> 001
                copy_header_key(hdr, combined_header, f'AS{channel_id}_WL_{num}', channel_id)
            for i in range(task_number - 1, -1, -1):
                num = f'{i:03d}' # e.g. 1 -> 001
                copy_header_key(hdr, combined_header, f'AS{channel_id}_EXP_{num}', channel_id)
            for i in range(task_number - 1, -1, -1):
                num = f'{i:03d}' # e.g. 1 -> 001
                copy_header_key(hdr, combined_header, f'AS{channel_id}_TASK_{num}', channel_id)
            copy_header_key(hdr, combined_header, f'AS{channel_id}_TASK_NUMBER', channel_id)
            copy_header_key(hdr, combined_header, f'AS{channel_id}_ORDER', channel_id)
            copy_header_key(hdr, combined_header, f'AS{channel_id}_FRAMES', channel_id)
        channel_order = ['Vis', 'NIR1', 'NIR2', 'SWIR'] # Ensure the order remains in header
        channels_string = ','.join(sorted(channels, key=lambda x: channel_order.index(x)))
        combined_header['ASP_CHANNELS'] = (channels_string, 'Instrument channels')
    except Exception as e:
        print(f"[WARNING] Combining headers failed: {e}")
        print(f'Returning the first header.')
        headers[0]
    return combined_header

def append_header(hdu: ImageHDU, dict: dict[str, Any]) -> ImageHDU:
    header = hdu.header
    for key, value in dict.items():
        header[key] = value
    return hdu

def merge_fits_files(input_dir: str | Path, channels: list[str], output_dir: str | Path) -> tuple[str, list[Issue]]:
    """
        Combines the FITS files into one single files containing the hyperspectral data cube.
        If the files list contains Vis channel the Vis channel is aligned into same grid with the NIR channel images.
        If the fiels contains the SWIR channel .... 
    
        Parameters:
            files (List[str | Path]): List of all fits files to be combined.
            output_dir (str | Path): Path to the directory where the new file is stored.
    
        Returns 
            (str): path to the created FITS file
            (list): list of Issue objects

    """

    all_issues: list[Issue] = []

    channel_files = {
        'Vis'   : get_path(input_dir, 'Vis', '1C.fits') if 'Vis' in channels else None,
        'NIR1'  : get_path(input_dir, 'NIR1', '1C.fits') if 'NIR1' in channels else None,
        'NIR2'  : get_path(input_dir, 'NIR2', '1C.fits') if 'NIR2' in channels else None,
        'SWIR'  : get_path(input_dir, 'SWIR', '1C.fits') if 'SWIR' in channels else None,
    }

    valid = [(name, p) for name, p in channel_files.items() if p is not None]

    if len(valid) <= 1:
        all_issues.append(
            Issue(
                level="warning",
                message=(f"A single channel cannot be combined."),
                source=__name__,
            )
        )
        #TODO: return still 2B or just the 1C?
        valid_n, valid_f = valid[0]
        return valid_f, all_issues

    present = {name for name, _ in valid}
    primary_header_list = []
    image_dict = {}
    cds_dict = {}
    swir_data = None

    print('present:', present)
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
            all_issues.append(
                        Issue(
                            level="Error",
                            message=(f"Error in reading channel data {c}: {e}"),
                            source=__name__,
                        )
                    )

    # New header
    new_primary_header = combine_primary_headers(primary_header_list)
    new_image_data = []

    if 'Vis' in present and present & {'NIR1', 'NIR2'}:

        vis = get_frame(channel_files['Vis'], 0)
        nir = get_frame(channel_files.get('NIR1', channel_files.get('NIR2')), 0)

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
        swir_hdu = fits.ImageHDU(data=swir_data)
        new_hdul.append(swir_hdu)
    
    # Extract HDUs containing the binary tables
    if 'NIR1' in cds_dict and 'NIR2' in cds_dict:
        # Combine all columns from both tables
        combined_table_astropy = hstack([cds_dict['NIR1'], cds_dict['NIR2']], join_type='exact')
        combined_table = fits.BinTableHDU(data=combined_table_astropy.as_array())
        new_hdul.append(combined_table)
    elif 'NIR1' in cds_dict:
        combined_table = fits.BinTableHDU(data=cds_dict['NIR2'].as_array())
        new_hdul.append(combined_table)
    elif 'NIR2' in cds_dict:
        combined_table = fits.BinTableHDU(data=cds_dict['NIR2'].as_array())
        new_hdul.append(combined_table)
    
    hdu_list = fits.HDUList(new_hdul)
    # File name for new fits
    _, file_path = valid[0]
    stem = file_path.stem
    suffix = file_path.suffix
    new_calibration_level = '2B'
    file_name = 'ASP'+ stem[3:25] + new_calibration_level + suffix
    primary_header = hdu_list[0].header
    primary_header['FILENAME'] = file_name
    primary_header['PROCLEVL'] = new_calibration_level
    # Create the new fits file with dark-subtracted images
    fits_file = os.path.join(output_dir, file_name)
    hdu_list.writeto(fits_file, overwrite=True)

    all_issues.append(
            Issue(
                level="Info",
                message=(f"Merged files {present}"),
                source=__name__,
            )
        )

    return(fits_file, all_issues)