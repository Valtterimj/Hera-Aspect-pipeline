
from pathlib import Path
from astropy.io import fits 

from aspect_pipeline.utils.utilities import convert_to_float64, convert_to_float32, channel_to_id
from aspect_pipeline.utils.validate import _get_path
from aspect_pipeline.utils.errors import PipelineError
from aspect_pipeline.utils.classes import Issue, CalibConfig
from aspect_pipeline.levels.level_1.extract_cds import extract_cds_pixels
from aspect_pipeline.levels.level_1.dark_background import dark_subtraction
from aspect_pipeline.levels.level_1.flat_field import flat_field_calibration
from aspect_pipeline.levels.level_1.bad_pixels import replace_bad_pixels
from aspect_pipeline.levels.level_1.radiometric import radiometric_calibration

def run_level_1b(fits_file: Path, output_dir: Path, calibration: CalibConfig, channel: str, extra: bool) -> tuple[Path, list[Issue]]:

    all_issues: list[Issue] = []

    with fits.open(fits_file, memmap=False) as hdul:

        order = hdul[0].header.get(f'{channel}_ORDER')

        # Convert the data to float64 for calibration
        hdul, issue = convert_to_float64(hdul)
        all_issues.append(issue)

        # Extract diagnostic pixels from NIR. Convert the values to float64
        hdul, issues = extract_cds_pixels(hdul)
        all_issues.extend(issues)

        calibration_dir = Path(calibration.calibration_dir)
        # Subtrack the dark frame from each image
        dark_dir = calibration_dir / 'DARKS'
        id = channel_to_id[channel]
        dark_file = dark_dir / f'AS{id}_DARKS.fits'
        hdul, issues = dark_subtraction(hdul, dark_file)
        all_issues.extend(issues)

        # Apply flatfield correction
        flat_dir = calibration_dir / 'FLATS'
        flat_file = _get_path(input_dir=flat_dir, channel=channel, suffix=f'{order}.fits')
        hdul, issues = flat_field_calibration(hdul, flat_file)
        all_issues.extend(issues)

        # Replace bad pixels with neigbours
        badpixels_dir = calibration_dir / 'BADPIXELS'
        bp_file = _get_path(input_dir=badpixels_dir, channel=channel, suffix=f'.txt')
        hdul, issues = replace_bad_pixels(hdul, bp_file=bp_file)
        all_issues.extend(issues)

        if extra:
            hdul_extra = hdul.copy()
            hdul_extra, issue = convert_to_float32(hdul_extra)
            all_issues.append(issue)
            stem = fits_file.stem
            suffix = fits_file.suffix
            extra_calibration_level = '1A-extra'
            extra_file = stem[:25] + extra_calibration_level + suffix
            extra_primary_header = hdul_extra[0].header
            extra_primary_header['FILENAME'] = extra_file
            extra_primary_header['PROCLEVL'] = extra_calibration_level
            try:
                extra_fits_file = Path(output_dir) / extra_file
                hdul.writeto(extra_fits_file, overwrite=True)
                all_issues.append(
                        Issue(
                            level="info",
                            message=(f"1A-extra fits file created: {extra_fits_file}"),
                            source=__name__,
                        )
                    )
            except Exception as e:
                all_issues.append(
                        Issue(
                            level="warning",
                            message=(f"Writing 1A-extra fits file failed: {e}"),
                            source=__name__,
                        )
                    )
            extra_fits = Path(output_dir / extra_file)
            hdul_extra.writeto(extra_fits, overwrite=True)
            all_issues.append(
                Issue(
                    level='info',
                    message='1A-extra calibration file created: {extra_fits}',
                    source=__name__,
                )
            )


        radiance_dir = calibration_dir / 'RADIANCE'
        radiance_file = _get_path(input_dir=radiance_dir, channel=channel, suffix=f'{order}.txt')
        hdul, issues = radiometric_calibration(hdul, radiance_file=radiance_file)
        all_issues.extend(issues)

        hdul, issue = convert_to_float32(hdul)
        all_issues.append(issue)

        stem = fits_file.stem
        suffix = fits_file.suffix
        new_calibration_level = '1B'
        file_name = stem[:25] + new_calibration_level + suffix
        primary_header = hdul[0].header
        primary_header['FILENAME'] = file_name
        primary_header['PROCLEVL'] = new_calibration_level

    # create the new fits
    try:
        fits_file = Path(output_dir) / file_name
        hdul.writeto(fits_file, overwrite=True)
        all_issues.append(
                Issue(
                    level="info",
                    message=(f"New fits file created: {fits_file}"),
                    source=__name__,
                )
            )
    except Exception as e:
        raise PipelineError(f'Error writing a fits file.') from e

    return fits_file, all_issues