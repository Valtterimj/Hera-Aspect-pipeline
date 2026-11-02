import logging
import numpy as np
from astropy.io import fits
from astropy.io.fits import HDUList

from aspect_pipeline.utils.errors import CalibrationError

logger = logging.getLogger(__name__)

"""
    This file extracts correlated double sampling (CDS) pixels surrounding the NIR images, storing them into a separate BinaryTableHDU.
    The function also converts the image data into double precission (float64) values. 

    Binary table architecture
        - BinaryTableHDU can be accessed with hdul[2] (third HDU after primary, and image)
            - Contains one column for each 2D image, named as, Channel_i, where channel is 'NIR1' or 'NIR2' i is the frame number
            - Each column will have 1 row with all cds pixels flattened total of 7984 values
            - utilities offer function read_cds() to retrieve the desired cds pixels from the created file

"""

def extract_cds(image: np.ndarray) -> tuple[np.ndarray, list[list[int]]]:
    # Define diagnostic pixel regions
    top = 5  # Five lines at the top
    bottom = 1  # One line at the bottom
    left = 4  # Four columns on the left
    right = 4  # Four columns on the right

    top_rows = image[:top, :]
    middle_rows = image[top:-bottom, :]
    left_cols = middle_rows[:, :left]
    right_cols = middle_rows[:, -right:]
    middle_sides = np.hstack((left_cols, right_cols))

    bottom_row = image[-1:, :]

    cds_pixels = np.concatenate([
        top_rows.flatten(),
        middle_sides.flatten(),
        bottom_row.flatten()
    ])

    # Remove diagnostic pixels to create the cleaned image
    cleanedImage = image[
        top:-bottom,  # Remove top and bottom rows
        left:-right  # Remove left and right columns
    ]
    return (cleanedImage, cds_pixels)

def extract_cds_pixels(hdul: HDUList) -> HDUList:
    """
    Extracts the CDS pixels from NIR images and strores them in a separate BinaryTable.

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

    if channel in ('Vis', 'SWIR'):
        return hdul
    else:
        try:
            # Get image dimensions
            width = header.get('NAXIS1')
            height = header.get('NAXIS2')
            slices = header.get('NAXIS3')

            if width == 512 and height == 640:
                logger.info(f"Channel {channel} images already has correct shape ({width}, {height}).")
                return hdul

            # Empty array for cleaned data
            cleaned_data = np.zeros((slices, height - 6, width - 8), dtype=np.float64)
            
            # Prepare a list to hold the columns for CDS binary table
            cds_list = []
            # Step 4: Iterate over each slice of the cube
            for i, image in enumerate(data):
                # Extract the cds pixels from the slice
                cleaned_image, cds = extract_cds(image)
                cds_list.append(cds)               
                # Append the cleanedImage to the new image HDU
                cleaned_data[i, :, :] = cleaned_image.astype(np.float64)

            # Create Image HDU with old header
            data = cleaned_data
            hdul[0].data = data
            
            # Create columns for the cds pixels
            frames = header.get(f'{channel}_FRAMES').split(',')
            columns = []
            for i, col in enumerate(cds_list):
                column = fits.Column(
                    name= f'{channel}_{frames[i]}',
                    format=f'{len(col)}J', # unsigned data
                    array=[col]
                )
                columns.append(column)

            # Create a binary table HDU for the cds pixels
            cds_table = fits.BinTableHDU.from_columns(columns)
            hdul.append(cds_table)
            logger.info(f"CDS pixels extracted for channel {channel}.")
            return hdul
        except Exception as e:
            raise CalibrationError(f'Extracting CDS pixels failed; (reason: {e})')
