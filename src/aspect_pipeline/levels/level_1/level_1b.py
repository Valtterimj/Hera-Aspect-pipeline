
import logging
from pathlib import Path
from astropy.io import fits

from aspect_pipeline.utils.utilities import convert_to_float64, convert_to_float32, get_calibration_path, parse_filename, generate_filename, channel_to_id
from aspect_pipeline.utils.errors import PipelineError
from aspect_pipeline.utils.classes import CalibConfig
from aspect_pipeline.levels.level_1.extract_cds import extract_cds_pixels
from aspect_pipeline.levels.level_1.dark_background import dark_subtraction
from aspect_pipeline.levels.level_1.flat_field import flat_field_calibration
from aspect_pipeline.levels.level_1.bad_pixels import replace_bad_pixels
from aspect_pipeline.levels.level_1.radiometric import radiometric_calibration

logger = logging.getLogger(__name__)

def run_level_1b(fits_file: Path, output_dir: Path, calibration: CalibConfig, channel: str, extra: bool) -> Path:

    try:
        with fits.open(fits_file, memmap=False) as hdul:

            order = hdul[0].header.get(f'{channel}_ORDER')

            # Convert the data to float64 for calibration
            hdul = convert_to_float64(hdul)

            # Extract diagnostic pixels from NIR. Convert the values to float64

            #Skip for simulated
            missphas = hdul[0].header.get('MISSPHAS')
            if missphas != 'simulated':
                hdul = extract_cds_pixels(hdul)

            calibration_dir = Path(calibration.calibration_dir)
            # Subtrack the dark frame from each image
            dark_dir = calibration_dir / 'DARKS'
            id = channel_to_id[channel]
            dark_file = dark_dir / f'AS{id}_DARKS.fits'
            hdul = dark_subtraction(hdul, dark_file)

            # Apply flatfield correction
            flat_file = get_calibration_path(cal_dir=calibration_dir, sub_dir='FLATS', channel=channel, suffix=f'{order}.fits')
            hdul = flat_field_calibration(hdul, flat_file)

            # Replace bad pixels with neigbours
            bp_file = get_calibration_path(cal_dir=calibration_dir, sub_dir='BADPIXELS', channel=channel, suffix=f'.txt')
            hdul = replace_bad_pixels(hdul, bp_file=bp_file)

            if extra:
                hdul_extra = hdul.copy()
                hdul_extra = convert_to_float32(hdul_extra)
                old_name = fits_file.name
                old_name_atr = parse_filename(old_name)
                old_name_atr.processing_level = '1A-extra'
                fits_name = generate_filename(old_name_atr)
                extra_file = output_dir / fits_name
                extra_primary_header = hdul_extra[0].header
                extra_primary_header['FILENAME'] = extra_file
                extra_primary_header['PROCLEVL'] = '1A-extra'
                try:
                    extra_fits_file = Path(output_dir) / extra_file
                    hdul.writeto(extra_fits_file, overwrite=True)
                    logger.info(f"1A-extra fits file created: {extra_fits_file}")
                except Exception as e:
                    logger.warning(f"Writing 1A-extra fits file failed: {e}")
                extra_fits = Path(output_dir / extra_file)
                hdul_extra.writeto(extra_fits, overwrite=True)
                logger.info('1A-extra calibration file created: {extra_fits}')


            radiance_dir = calibration_dir / 'RADIANCE'
            radiance_file = get_calibration_path(cal_dir=calibration_dir, sub_dir='RADIANCE', channel=channel, suffix=f'{order}.txt')
            hdul = radiometric_calibration(hdul, radiance_file=radiance_file)

            hdul = convert_to_float32(hdul)

            old_name = fits_file.name
            old_name_atr = parse_filename(old_name)
            old_name_atr.processing_level = '1B'
            fits_name = generate_filename(old_name_atr)
            primary_header = hdul[0].header
            primary_header['FILENAME'] = fits_name
            primary_header['PROCLEVL'] = '1B'

        fits_file = Path(output_dir) / fits_name
        hdul.writeto(fits_file, overwrite=True)
        logger.info(f"New fits file created: {fits_file}")
    except Exception as e:
        raise PipelineError(f'Error calibrating {channel} file.') from e
    return fits_file