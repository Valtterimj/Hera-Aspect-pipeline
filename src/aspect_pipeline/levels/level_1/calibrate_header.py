import numbers
from pathlib import Path
from astropy.io import fits

from aspect_pipeline.utils.classes import Issue, Channel
from aspect_pipeline.utils.errors import CalibrationError, PipelineError

from aspect_pipeline.utils.utilities import form_fits_header_val
from aspect_pipeline.utils.calib_conversions import det_temp_conversion, fpi_temp_conversion, exposure_conversion, wavelength_conversion



def calibrate_header(fits_path: Path, output_dir: Path, channel: str, drop_frame: bool) -> tuple[str, list[Issue]]:
    """
    Parmeters:
        fits_path: Path to the FITS file.
        output_path: Path to the folder where the new fits file will be stored.
        channel: Instrument channel 'NIR' or 'MIR'
    
    Returns:
        tuple (path to the created fits file, list of issues)
    """

    all_issues: list[Issue] = []

    with fits.open(fits_path) as hdul:

        # Data from fits file
        new_hdul = fits.HDUList([hdu.copy() for hdu in hdul])
        hdu = new_hdul[0]
        header = hdu.header
        order = header.get('ORDER')
            
        for ch in ['Vis', 'NIR1', 'NIR2', 'SWIR']:
            
            # Detector temperature calibration
            try:
                det_temp = header.get(f'{ch}_CCDTEMP') # Current value

                if det_temp is None:
                    raise ValueError("Detector temperature missing.")
                
                dn = float(det_temp)
                c, k = det_temp_conversion(dn, ch) # convert to celcius and kelvin
                val = f'{k:.2f}' if isinstance(k, numbers.Number) else str(k)
                c_str = f'{c:.2f}' if isinstance(c, numbers.Number) else str(c)
                com = f'{ch} detector temperature [K] ({c_str} [C])'
                value, comment = form_fits_header_val(key=f'{ch}_CCDTEMP', value=val, comment=com, hierarch=True) # make header value comment pair
                header[f'{ch}_CCDTEMP'] = (value, comment) # add to header
            except (ValueError, TypeError, CalibrationError) as e:
                all_issues.append(
                    Issue(
                        level="warning",
                        message=(
                            f"Failed to compute detector temperature for {ch}_CCDTEMP; (reason: {type(e).__name__}: {e})"
                        ),
                        source=__name__,
                    )
                )
            
            # FPI temperature calibration for FPI 1 and FPI 2
            for i in [1, 2]:
                try:
                    fpi_temp = header.get(f'{ch}_FPI_TEMP{i}')

                    if fpi_temp is None:
                        raise ValueError(f"FPI {i} temperature missing.")
                    
                    dn = float(fpi_temp)
                    c, k = fpi_temp_conversion(dn, ch, i)
                    val = f'{k:.2f}' if isinstance(k, numbers.Number) else str(k)
                    c_str = f'{c:.2f}' if isinstance(c, numbers.Number) else str(c)
                    com = f'{ch} FPI {i} temperature [K] ({c_str} [C])'
                    value, comment = form_fits_header_val(key=f'{ch}_FPI_TEMP{i}', value=val, comment=com, hierarch=True)
                    header[f'{ch}_FPI_TEMP{i}'] = (value, comment)
                except (ValueError, TypeError, CalibrationError) as e:
                    all_issues.append(
                        Issue(
                            level="warning",
                            message=(
                                f"Failed to compute FPI {i} temperature for {ch}_FPI_TEMP{i}; (reason: {type(e).__name__}: {e})"
                            ),
                            source=__name__,
                        )
                    )

        task_number = header.get(f'{channel}_TASK_NUMBER')
        if task_number is None:
            raise CalibrationError(f'{channel}_TASK_NUMBER is not found from header.')
        try:
            tn = int(task_number)
        except (ValueError, TypeError):
            raise CalibrationError(f'{channel}_TASK_NUMBER is not convertable to integer.')

        # Wavelength calibration
        try:
            setpoint1 = [] # Gather all setpoint 1 values
            for i in range(0, tn):
                num = f'{i:03d}'
                task = header.get(f'{channel}_TASK_{num}')
                if task:
                    sp = task.split(' ')[0]
                    setpoint1.append(sp)

            values = [float(value) for value in setpoint1] 

            task_idx = header.index(f'{channel}_TASK_NUMBER')
            task_idx += tn + 1 # index to insert new fields in chronological order
            for i, val in enumerate(values):
                num = f'{i:03d}' # e.g. 1 -> '001'
                wl = wavelength_conversion(val, channel, order) # convert DN values to nm
                com = f'{channel} TASK {num} wavelength [nm]'
                value, comment = form_fits_header_val(key=f'{channel}_WL_{num}', value=wl, comment=com, hierarch=True)
                header.insert(task_idx, (f'HIERARCH {channel}_WL_{num}', value, comment), after=True)
                task_idx += 1 # increase the counter 

        except (ValueError, TypeError, CalibrationError) as e:
                all_issues.append(
                    Issue(
                        level="warning",
                        message=(
                            f"Failed to convert wavelengths for channel: {channel}; (reason: {type(e).__name__}: {e})"
                        ),
                        source=__name__,
                    )
                )  
        
        try:

            setpoint1 = []
            for i in range(0, tn):
                num = f'{i:03d}'
                task = header.get(f'{channel}_TASK_{num}')
                if task:
                    sp = task.split(' ')[3]
                    setpoint1.append(sp)

            values = [float(value) for value in setpoint1] 

            task_idx = header.index(f'{channel}_TASK_NUMBER')
            task_idx += tn * 2 + 1
            for i, val in enumerate(values):
                num = f'{i:03d}'
                exp = exposure_conversion(val, channel)
                com = f'{channel} TASK {num} exposure [s]'
                value, comment = form_fits_header_val(key=f'{channel}_EXP_{num}', value=exp, comment=com, hierarch=True)
                header.insert(task_idx, (f'HIERARCH {channel}_EXP_{num}', value, comment), after=True)
                task_idx += 1

        except (ValueError, TypeError, CalibrationError) as e:
            all_issues.append(
                    Issue(
                        level="warning",
                        message=(
                            f"Failed to convert setpoint values to wavelengths for {channel}; (reason: {type(e).__name__}: {e})"
                        ),
                        source=__name__,
                    )
                )

        # Drop the first frame from the data cube and its header entries
        if drop_frame:
            frames = header.get(f'{channel}_FRAMES').split(',')
            dropped_frame = frames[0]
            header[f'{channel}_FRAMES'] = ','.join(frames[1:])

            for key in (f'{channel}_EXP_{dropped_frame}', f'{channel}_WL_{dropped_frame}'):
                if key in header:
                    del header[key]

            hdu.data = hdu.data[1:]

            all_issues.append(
                Issue(
                    level="info",
                    message=(f"Dropped first frame ({dropped_frame}) from {channel} data cube and header."),
                    source=__name__,
                )
            )

        # Create new fits file name and write
        stem = fits_path.stem
        suffix = fits_path.suffix
        new_calibration_level = '1A'
        file_name = stem[:25] + new_calibration_level + suffix
        primary_header = header
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
        except Exception as e:
            raise PipelineError(f'Error writing a fits file.') from e
        
    return fits_file, all_issues

   