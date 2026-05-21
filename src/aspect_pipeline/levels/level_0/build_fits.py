
import numpy as np
from pathlib import Path
from astropy.io import fits
from astropy.io.fits import Header
from dataclasses import is_dataclass, fields

from aspect_pipeline.utils.utilities import list_channel_frames, decompress_jp2, sc_clock_to_base32, form_fits_name
from aspect_pipeline.utils.errors import PipelineError
from aspect_pipeline.utils.classes import InputLayout, Config, Issue, HeaderEntry
from aspect_pipeline.levels.level_0.metadata import collect_metadata

def add_entries_to_header(hdr: Header, entries: object, hierarch: bool = False) -> None:
    if hasattr(entries, "fields") and isinstance(entries.fields, dict):
        entries_dict = entries.fields
    elif is_dataclass(entries):
        entries_dict = {f.name: getattr(entries, f.name) for f in fields(entries)}
    else:
        entries_dict = entries

    for key, entry in entries_dict.items():
        k = f"HIERARCH {key}" if hierarch else key
        value = "" if entry.value is None else str(entry.value)
        comment = None if entry.comment is None else str(entry.comment)

        if not comment:
            hdr[k] = value
            continue

        card_length = len(k) + len(value) + len(comment) + 4
        if card_length <= 80:
            hdr[k] = (value, comment)
        else: 
            hdr[k] = (value, "")

            

def build_fits(input: InputLayout, cfg: Config, channel: str) -> tuple[Path, list[Issue]]:
    """
    Creates a new level_0 FITS file by combining releavnt metadata with the acquisitions.
    
    :param input: object containing the paths to the input directories (meta, acq_)
    :type input: InputLayout
    :param cfg: Pipeline configuration object
    :type cfg: Config
    :param channel: Instrument channel
    :type channel: String
    :return: path to the created FITS file. 
    :rtype: Path
    """

    all_issues: list[Issue] = []

    # Primary HDU
    primary_hdu = fits.PrimaryHDU()
    primary_header = primary_hdu.header

    # Collect metadata
    try:
        meta_data, meta_issues = collect_metadata(input=input, spice=cfg.run.spice_dir, cfg=cfg.data, channel=channel)
        all_issues.extend(meta_issues)
    except PipelineError as e:
        raise PipelineError("build_fits failed. Error while collecting metadata.") from e
    
    # Add to header
    acq_meta = meta_data.acq
    add_entries_to_header(hdr=primary_header, entries=acq_meta, hierarch=False)
    spice_meta = meta_data.spice
    add_entries_to_header(hdr=primary_header, entries=spice_meta, hierarch=False)
    inst_meta = meta_data.instrument
    add_entries_to_header(hdr=primary_header, entries=inst_meta, hierarch=True)
    inst_s_meta = meta_data.instrument_specific
    add_entries_to_header(hdr=primary_header, entries=inst_s_meta, hierarch=True)

    acq_dir = input.acquisition_dir
    frame_n, frame_list = list_channel_frames(acq_dir=acq_dir, channel=channel)

    if frame_n == 0:
        raise PipelineError(f'No matching acquisitions in {acq_dir}. \n'
                            f"Files should follow the file naming convetion e.g 'dc_0_exp_000.bin' for NIR first exposure")
    
    primary_header["ORIGFILE"] = frame_list[0]
    if channel == 'SWIR':
        values = []
        try:
            for i, bin_file in enumerate(frame_list):
                file_path = Path(acq_dir) / bin_file
                with file_path.open('rb') as f:
                    bin_data = f.read()
                if len(bin_data) != 4: 
                    all_issues.append(
                        Issue(
                            level="error",
                            message=(f"SWIR file {file_path} does not contain excatly 4 bytes."
                                    f"Skipping the file."
                                    ),
                            source=__name__,
                        )
                    )
                    continue
                value = int.from_bytes(bin_data, 'big' , signed=False)
                values.append(value)
        except Exception as e:
            all_issues.append(
                Issue(
                    level="error",
                    message=(f"Error reading binary file {file_path}: {e}"
                            f"Skipping the file."
                            ),
                    source=__name__,
                )
            )
        image = np.array(values, dtype=np.uint32)
    else:
        if channel == 'Vis':
            height = 1024
            width = 1024
        else:
            if cfg.data.missphas == 'simulated':
                height = 512
                width = 640
            else:
                height = 518
                width = 648
        image_data = []
        for i, bin_file in enumerate(frame_list):
            try:
                file_path = Path(acq_dir) / bin_file
                if bin_file.endswith(".jp2"):
                    decompressed_output_dir = Path(input.root) / 'decompressed'
                    decompressed_output = decompress_jp2(file_path, decompressed_output_dir)
                    array = np.fromfile(decompressed_output, dtype='<u2').reshape((height, width)) # little-endian 16-bit unsigned
                else:
                    array = np.fromfile(file_path, dtype='<u2').reshape((height, width)) # little-endian 16-bit unsigned
                image_data.append(array)
            except Exception as e:
                all_issues.append(
                    Issue(
                        level="error",
                        message=(f"Error reading binary file {file_path}: {e}"
                                f"Skipping the file."
                                ),
                        source=__name__,
                    )
                )


        image = np.array(image_data) # Stack the images into a cube

    if len(image) == 0:
        raise PipelineError(f"Error creating fits data unit. No data. check the file names and data dimensionality.")
    primary_hdu.data = image

    # Add comments to help the readability
    primary_header.insert('PROCLEVL',('COMMENT', ' - - - - - - - - Instrument data - - - - - - - - '), after=True)
    primary_header.insert('SPICE_MK',('COMMENT', ' - - - - - - - - SPICE data - - - - - - - - '), after=False)
    primary_header.insert('SOL_ELNG',('COMMENT', ' - - - - - - - - Instrument specific data - - - - - - - - '), after=True)

    # Generate FITS file name 
    utc_time = primary_header.get('DATE_OBS')
    sc_clock = primary_header.get('SC_CLK')
    if sc_clock in (None, 'UNK'):
        sc_clock = 0
    image_number = sc_clock_to_base32(sc_seconds=sc_clock)
    fits_name = form_fits_name(channel, image_number, utc_time, '0A')
    primary_header['FILENAME'] = fits_name

    # Create a FITS file 
    fits_file = cfg.run.output_dir / fits_name
    try:
        primary_hdu.writeto(fits_file, overwrite=True)
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