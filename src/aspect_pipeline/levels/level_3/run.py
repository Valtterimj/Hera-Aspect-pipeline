from astropy.io import fits
from astropy.io.fits import Header
import numpy as np
from pathlib import Path
from dataclasses import replace
import logging

from aspect_pipeline.utils.classes import Issue, Config, Level2Data, PreparedSpectra
from aspect_pipeline.utils.errors import PipelineError
from aspect_pipeline.utils.utilities import CHANNELS, get_path, get_wavelengths_by_channel, parse_filename, generate_filename

from aspect_pipeline.levels.level_3.spectral_filtering import filter_spectra
from aspect_pipeline.levels.level_3.modules.utilities_spectra import ( normalise_spectra, collect_all_models, load_keras_model)
from aspect_pipeline.levels.level_3.level_3_utilities import ( extract_asteroid, get_composition_header, get_taxonomy_header)
from aspect_pipeline.levels.level_3.modules.NN_evaluate import evaluate
from aspect_pipeline.levels.level_3.mgm import fit
from aspect_pipeline.levels.level_3.modules.BAR_BC_method import calc_spect_params
from tqdm import tqdm

import os


logger = logging.getLogger(__name__)

"""
Level 3 of the ASPECT data processing pipeline. Reads the level 2B file, filters the asteroid
spectra and runs the analyses selected in the config:
    - Level 3A: Filtered spectra; connecting the channel segments, removing outliers, denoising
    - Level 3B: Spectral parameters; slope, band I center, depth, width and area
    - Level 3C: MGM band fits, and NN composition and taxonomy

Config fields used (cfg.analysis):
    instrument (str): Channels used in the NN analysis (C, T), one of NN_INSTRUMENTS:
        'Vis-NIR1-NIR2', 'Vis-NIR1-NIR2-SWIR', 'NIR1-NIR2', 'NIR1-NIR2-SWIR'
    data_filtering (bool): Connect the segments, remove outliers and denoise. If False, only the
        bands overlapping the previous channel are dropped.
    save_filtered (bool): Save the filtered spectra as a level 3A file.
    models (list[str]): Analyses to run, any of
        P = Spectral parameters
        C = Composition
        T = Taxonomy
        M = MGM
    z_thresh (float): Threshold for removing outliers. Increase for less sensitive outlier removal.
    z_factor (float): Denoising factor. Increase for smoother spectra.
    init_guess (list[list[float]]): Initial [strength, center (nm), width (nm)] of each MGM band.
"""

IMAGE_CHANNELS = ('Vis', 'NIR1', 'NIR2')

def load_level_2(cfg: Config) -> Level2Data:
    """Read the level 2B file and check it holds the data for all configured channels.

    Args:
        cfg: Pipeline config. The file is looked up in cfg.run.input_dir by the
            channels in cfg.pipeline.channels.

    Returns:
        Level2Data with the primary header, Vis/NIR reflectance cube, SWIR reflectance
        spectrum and wavelengths (nm) for each channel.

    Raises:
        PipelineError: If the file is not found or cannot be read, a configured channel
            is missing, or the number of wavelengths does not match the data.
    """
    channels = cfg.pipeline.channels
    subunit = '_'.join(ch.lower() for ch in CHANNELS if ch in channels) # channel order vis_nir1_nir2_swir

    try:
        fits_file = get_path(input_dir=cfg.run.input_dir, processing_level='2B', subunit=subunit, extension='fits')
    except (NotADirectoryError, FileNotFoundError, ValueError) as e:
        raise PipelineError(f"Level 2B file not found: {e}", level='3') from e

    try:
        with fits.open(fits_file, memmap=False) as hdul:
            header = hdul[0].header.copy()
            cube = hdul[0].data
            swir = hdul['SWIR'].data if 'SWIR' in hdul else None
    except OSError as e:
        raise PipelineError(f"Reading level 2B file failed: {e}", level='3', path=str(fits_file)) from e

    file_channels = header.get('CHANNELS', '').split(',')
    missing = [ch for ch in channels if ch not in file_channels]
    if missing:
        raise PipelineError(f"Level 2B file has no data for channels {missing}, file contains {file_channels}", level='3', path=str(fits_file))

    try:
        wavelengths = get_wavelengths_by_channel(fits_file)
    except ValueError as e:
        raise PipelineError(f"Reading wavelengths from the level 2B header failed: {e}", level='3', path=str(fits_file)) from e
    no_wavelengths = [ch for ch in file_channels if not wavelengths.get(ch)]
    if no_wavelengths:
        raise PipelineError(f"No wavelengths found for channels {no_wavelengths}", level='3', path=str(fits_file))

    # The cube holds every image channel in the file, not only the configured ones
    n_image_wl = sum(len(wavelengths[ch]) for ch in IMAGE_CHANNELS if ch in file_channels)
    if cube is None or cube.ndim != 3 or cube.shape[0] != n_image_wl:
        shape = None if cube is None else cube.shape
        raise PipelineError(f"Data cube shape {shape} does not match {n_image_wl} Vis/NIR wavelengths", level='3', path=str(fits_file))

    if 'SWIR' in file_channels:
        if swir is None:
            raise PipelineError("Header lists SWIR but the file has no SWIR extension", level='3', path=str(fits_file))
        if swir.size != len(wavelengths['SWIR']):
            raise PipelineError(f"SWIR data size {swir.size} does not match {len(wavelengths['SWIR'])} SWIR wavelengths", level='3', path=str(fits_file))

    logger.info(f"Loaded {fits_file.name}: " + ', '.join(f"{ch} {len(wavelengths[ch])} wl" for ch in file_channels))

    return Level2Data(path=fits_file, header=header, cube=cube, swir=swir, wavelengths=wavelengths)

def prepare_spectra(data: Level2Data) -> PreparedSpectra:
    """Extract the asteroid spectra from the Vis/NIR cube and drop pixels containing zeros.

    Pixels with a zero in any band are excluded, because denoising turns zeros into
    near-zero values and normalising by them overflows.

    Args:
        data: Loaded level 2B data.

    Returns:
        PreparedSpectra with reflectance spectra and wavelengths (nm) of every Vis/NIR band
        in the file, in cube order. The NIR1/NIR2 overlap band is kept.

    Raises:
        PipelineError: If the wavelengths are not ascending within a channel, the channels
            are not in order Vis < NIR1 < NIR2, no asteroid pixels are found,
            or every asteroid pixel contains a zero.
    """
    # TODO: include the SWIR spectrum (data.swir) in the analysis
    # Channel band ranges in the cube order
    channel_bands = {}
    frames = {}
    wavelengths = []
    for ch in IMAGE_CHANNELS:
        if ch in data.wavelengths:
            channel_bands[ch] = slice(len(wavelengths), len(wavelengths) + len(data.wavelengths[ch]))
            frames[ch] = data.header[f'{ch}_FRAMES'].split(',') # Same order as the wavelengths
            wavelengths.extend(data.wavelengths[ch])
    wavelengths = np.array(wavelengths)

    # Bands must be ascending within a channel. Consecutive channels may overlap,
    # but each channel must start and end above the previous one (Vis < NIR1 < NIR2)
    for ch, bands in channel_bands.items():
        if np.any(np.diff(wavelengths[bands]) <= 0):
            raise PipelineError(f"{ch} wavelengths are not ascending: {wavelengths[bands].tolist()}", level='3', path=str(data.path))
    ranges = [(ch, wavelengths[bands][0], wavelengths[bands][-1]) for ch, bands in channel_bands.items()]
    for (prev_ch, prev_first, prev_last), (ch, first, last) in zip(ranges, ranges[1:]):
        if first <= prev_first or last <= prev_last:
            raise PipelineError(f"{ch} range {first}-{last} nm is not above {prev_ch} range {prev_first}-{prev_last} nm", level='3', path=str(data.path))

    combined = extract_asteroid(data.cube, mask_index=0)
    if not combined:
        raise PipelineError("No asteroid pixels found in the data cube", level='3', path=str(data.path))
    coords, spectra = zip(*combined)
    coords = np.array(coords)
    spectra = np.array(spectra)

    valid = np.all(spectra != 0, axis=1)
    if not np.any(valid):
        raise PipelineError(f"All {len(spectra)} asteroid pixels contain zero values", level='3', path=str(data.path))
    excluded_coords = coords[~valid]

    logger.info(f'{len(spectra)} asteroid spectra extracted, {len(excluded_coords)} excluded due to zero values')

    return PreparedSpectra(
        coords=coords[valid],
        excluded_coords=excluded_coords,
        spectra=spectra[valid],
        wavelengths=wavelengths,
        channel_bands=channel_bands,
        frames=frames,
        image_shape=data.cube.shape[1:],
    )

def spectra_to_cube(values: np.ndarray, spectra: PreparedSpectra) -> np.ndarray:
    """Place per-pixel values at their pixel locations in a cube with NaN background.

    Args:
        values: Values of each pixel in spectra.coords, shape (n_pixels, n_layers).
        spectra: PreparedSpectra giving the pixel coordinates and image shape.

    Returns:
        Cube of shape (n_layers, height, width), NaN where no value is given. The values keep their unit.
    """
    cube = np.full((values.shape[1], *spectra.image_shape), np.nan)
    cube[:, spectra.coords[:, 0], spectra.coords[:, 1]] = values.T
    return cube

def filtered_header(data: Level2Data, filtered: PreparedSpectra) -> Header:
    """Copy the 2B header and remove the frames dropped in filtering.

    Dropped frames are removed from {channel}_FRAMES and their {channel}_WL_{idx} and
    {channel}_EXP_{idx} keywords are deleted, so the header matches the filtered bands.

    Args:
        data: Loaded level 2B data.
        filtered: Filtered spectra.

    Returns:
        Copy of the 2B primary header with the frame keywords of the filtered bands.
    """
    header = data.header.copy()
    for ch, frames in filtered.frames.items():
        for frame in header[f'{ch}_FRAMES'].split(','):
            if frame not in frames:
                for key in (f'{ch}_WL_{frame}', f'{ch}_EXP_{frame}'):
                    if key in header:
                        del header[key]
        header[f'{ch}_FRAMES'] = ','.join(frames)
    return header

def save_filtered_spectra(data: Level2Data, filtered: PreparedSpectra, output_dir: Path) -> Path:
    """Save the filtered spectra as a level 3A reflectance cube.

    Args:
        data: Loaded level 2B data.
        filtered: Filtered spectra.
        output_dir: Directory where the file is written.

    Returns:
        Path to the written FITS file.
    """
    header = filtered_header(data, filtered)

    name = generate_filename(replace(parse_filename(data.path.name), processing_level='3A'))
    header['FILENAME'] = name
    header['PROCLEVL'] = '3A'

    cube = spectra_to_cube(filtered.spectra, filtered).astype(data.cube.dtype)
    fits_file = Path(output_dir) / name
    fits.PrimaryHDU(data=cube, header=header).writeto(fits_file, overwrite=True)
    logger.info(f'Filtered spectra saved to: {fits_file}')
    return fits_file

def analysis_header(data: Level2Data, filtered: PreparedSpectra, analysis: str, level: str, layers: list[tuple[str, str]]) -> Header:
    """Make the primary header of an analysis result.

    Args:
        data: Loaded level 2B data.
        filtered: Filtered spectra used in the analysis.
        analysis: Name of the analysis written to ANALYSIS.
        level: Processing level written to PROCLEVL, e.g. '3B'.
        layers: (name, description) of each layer in the result cube, written to LAYER_{idx}.

    Returns:
        Header with the frame keywords of the filtered bands and the analysis keywords.
    """
    header = filtered_header(data, filtered)
    header['PROCLEVL'] = level
    header['ANALYSIS'] = (analysis, 'Type of analysis')
    header.insert('ANALYSIS', ('COMMENT', ' - - - - - - - - Data Analysis - - - - - - - -'), after=False)
    for i, (name, description) in enumerate(layers):
        header[f'LAYER_{i:02d}'] = (name, description)
    return header

def save_analysis_cube(data: Level2Data, filtered: PreparedSpectra, values: np.ndarray, header: Header, subunit: str, output_dir: Path) -> Path:
    """Save per-pixel analysis results as a float32 cube with NaN background.

    Args:
        data: Loaded level 2B data, used for the file name.
        filtered: Filtered spectra giving the pixel coordinates and image shape.
        values: Result of each pixel, shape (n_pixels, n_layers).
        header: Header from analysis_header. FILENAME is set here.
        subunit: Subunit of the file name, e.g. 'spectral_params'.
        output_dir: Directory where the file is written.

    Returns:
        Path to the written FITS file.
    """
    name = generate_filename(replace(parse_filename(data.path.name), processing_level=header['PROCLEVL'], subunit=subunit))
    header['FILENAME'] = name

    cube = spectra_to_cube(values, filtered).astype(np.float32)
    fits_file = Path(output_dir) / name
    fits.PrimaryHDU(data=cube, header=header).writeto(fits_file, overwrite=True)
    return fits_file

SPECTRAL_PARAMETER_LAYERS = [
    ('SLOPE', 'Spectral slope [1/nm]'),
    ('BIC', 'Band I center [nm]'),
    ('BID', 'Band I depth [reflectance]'),
    ('BIW', 'Band I width [nm]'),
    ('BIAR', 'Band I area [nm]'),
]

def calculate_spectral_parameters(filtered: PreparedSpectra) -> np.ndarray:
    """Calculate the spectral slope and band I parameters of each spectrum.

    Args:
        filtered: Filtered spectra.

    Returns:
        Array of shape (n_pixels, 5) with the layers of SPECTRAL_PARAMETER_LAYERS: slope (1/nm),
        band I center (nm), depth (reflectance), width (nm) and area (nm). NaN where a parameter
        could not be calculated.
    """
    if 'Vis' not in filtered.channel_bands:
        logger.warning('No Vis channel: the continuum maximum near 680 nm is outside the data, '
                       'slope and band I parameters may be shifted or NaN')
    logger.info(f'Calculating spectral parameters for {len(filtered.spectra)} spectra')
    return np.column_stack(calc_spect_params(filtered.wavelengths, filtered.spectra, visualise=False))

MGM_CONT_DEGREE = 0 # Degree of the MGM continuum polynomial
MGM_EPS = 0.01 # MGM convergence limit of the RMS between rounds

def calculate_mgm(filtered: PreparedSpectra, init_guess: list[list[float]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Fit the modified Gaussian model (MGM) to each spectrum.

    Spectra that are not finite and positive cannot be fitted, because MGM uses the logarithm
    of the reflectance. Their results are NaN.

    Args:
        filtered: Filtered spectra.
        init_guess: Initial [strength, center (nm), width (nm)] of each band.

    Returns:
        RMS of the fit in ln(reflectance) of shape (n_pixels,), band parameters [strength,
        center (nm), width (nm)] of shape (n_pixels, n_bands, 3), continuum coefficients and
        their p-values of shape (n_pixels, MGM_CONT_DEGREE + 1). NaN where the fit failed.

    Raises:
        PipelineError: If init_guess is not a list of [strength, center, width] triples.
    """
    init_guess = np.asarray(init_guess, dtype=float)
    if init_guess.ndim != 2 or init_guess.shape[1] != 3:
        raise PipelineError(f"MGM init_guess must be a list of [strength, center, width] per band, got {init_guess.tolist()}", level='3')

    n_pixels = len(filtered.spectra)
    rms = np.full(n_pixels, np.nan)
    band_parameters = np.full((n_pixels, len(init_guess), 3), np.nan)
    continuum = np.full((n_pixels, MGM_CONT_DEGREE + 1), np.nan)
    continuum_p = np.full((n_pixels, MGM_CONT_DEGREE + 1), np.nan)

    logger.info(f'Calculating MGM for {n_pixels} spectra')
    failed = 0
    for i, spectrum in enumerate(tqdm(filtered.spectra, desc="MGM", unit="spec")):
        if not np.all(np.isfinite(spectrum) & (spectrum > 0)):
            failed += 1
            continue
        try:
            result = fit(np.column_stack((filtered.wavelengths, spectrum)), init_guess.tolist(), contLinDeg=MGM_CONT_DEGREE, eps=MGM_EPS)
        except UnboundLocalError: # mgm.fit raises this when the first fit round gives a NaN RMS
            failed += 1
            continue
        rms[i], band_parameters[i], continuum[i], continuum_p[i] = result

    if failed:
        logger.warning(f'MGM failed for {failed} of {n_pixels} spectra, their results are NaN')
    return rms, band_parameters, continuum, continuum_p

def save_mgm_table(data: Level2Data, filtered: PreparedSpectra, mgm_results: tuple[np.ndarray, ...], init_guess: list[list[float]], output_dir: Path) -> Path:
    """Save the MGM results as a binary table with one row per pixel.

    Args:
        data: Loaded level 2B data.
        filtered: Filtered spectra giving the pixel coordinates.
        mgm_results: RMS, band parameters, continuum coefficients and p-values from calculate_mgm.
        init_guess: Initial band parameters used in the fit, written to INITGUES.
        output_dir: Directory where the file is written.

    Returns:
        Path to the written FITS file.
    """
    rms, band_parameters, continuum, continuum_p = mgm_results
    n_bands = band_parameters.shape[1]
    n_cont = continuum.shape[1]

    cols = fits.ColDefs([
        fits.Column(name='COORDS', format='2J', array=filtered.coords.astype(np.int32)),
        fits.Column(name='RMS', format='E', array=rms.astype(np.float32)),
        fits.Column(name='BANDPRM', format=f'{n_bands * 3}E', dim=f'(3,{n_bands})', array=band_parameters.astype(np.float32)),
        fits.Column(name='CONTPRM', format=f'{n_cont}E', array=continuum.astype(np.float32)),
        fits.Column(name='CONTPVAL', format=f'{n_cont}E', array=continuum_p.astype(np.float32)),
    ])

    header = analysis_header(data, filtered, 'MGM', '3C', [])
    header['COLUMNS'] = 'pixel coordinates, rms, band parameters, continuum parameters, continuum p-values'
    header['INITGUES'] = str(init_guess)
    name = generate_filename(replace(parse_filename(data.path.name), processing_level='3C', subunit='mgm'))
    header['FILENAME'] = name

    fits_file = Path(output_dir) / name
    fits.HDUList([fits.PrimaryHDU(header=header), fits.BinTableHDU.from_columns(cols)]).writeto(fits_file, overwrite=True)
    return fits_file

# cfg.analysis.instrument -> (channels used, normalisation wavelength in nm, NN model folder)
NN_INSTRUMENTS = {
    'Vis-NIR1-NIR2':      (('Vis', 'NIR1', 'NIR2'), 1546, 'ASPECT-vis-nir1-nir2-1546'),
    'Vis-NIR1-NIR2-SWIR': (('Vis', 'NIR1', 'NIR2', 'SWIR'), 2366, 'ASPECT-vis-nir1-nir2-swir-2366'),
    'NIR1-NIR2':          (('NIR1', 'NIR2'), 1546, 'ASPECT-nir1-nir2-1546'),
    'NIR1-NIR2-SWIR':     (('NIR1', 'NIR2', 'SWIR'), 2366, 'ASPECT-nir1-nir2-swir-2366'),
}

def nn_models(analysis: str, model_folder: str) -> list[str]:
    """List the saved NN models of an analysis.

    Args:
        analysis: 'composition' or 'taxonomy'.
        model_folder: Model folder of the instrument from NN_INSTRUMENTS.

    Returns:
        Sorted paths to the model files.

    Raises:
        PipelineError: If the folder holds no models.
    """
    model_names = sorted(collect_all_models(subfolder_model=os.path.join(analysis, model_folder), full_path=True))
    if not model_names:
        raise PipelineError(f"No {analysis} models found in {os.path.join(analysis, model_folder)}", level='3')
    return model_names

def prepare_nn_input(filtered: PreparedSpectra, instrument: str) -> tuple[np.ndarray, str]:
    """Select the bands of the instrument's channels and normalise them for the NN analysis.

    Args:
        filtered: Filtered spectra.
        instrument: Instrument from cfg.analysis.instrument, a key of NN_INSTRUMENTS.

    Returns:
        Reflectance spectra of the instrument's channels normalised to 1 at the normalisation
        wavelength, shape (n_pixels, n_bands), and the NN model folder of the instrument.

    Raises:
        PipelineError: If the instrument is unknown, a channel it needs is not in the data, or the
            number of bands does not match the input size of the models.
    """
    if instrument not in NN_INSTRUMENTS:
        raise PipelineError(f"Unknown instrument '{instrument}', expected one of {list(NN_INSTRUMENTS)}", level='3')
    channels, norm_wl, model_folder = NN_INSTRUMENTS[instrument]

    missing = [ch for ch in channels if ch not in filtered.channel_bands]
    if missing:
        raise PipelineError(f"Instrument {instrument} needs channels {missing} that are not in the data", level='3')

    # The channels are consecutive in the filtered spectra
    start = filtered.channel_bands[channels[0]].start
    stop = filtered.channel_bands[channels[-1]].stop
    wavelengths = filtered.wavelengths[start:stop]
    spectra = filtered.spectra[:, start:stop]

    # All models of an instrument have the same input size, check it from the first composition model
    model = load_keras_model(nn_models('composition', model_folder)[0])
    n_inputs = model.input_shape[1]
    if len(wavelengths) != n_inputs:
        raise PipelineError(f"Instrument {instrument} models take {n_inputs} bands but the data has {len(wavelengths)}: {wavelengths.tolist()}", level='3')

    logger.info(f'NN input: {instrument}, {len(wavelengths)} bands {wavelengths[0]}-{wavelengths[-1]} nm, normalised at {norm_wl} nm')
    return normalise_spectra(data=spectra, wavelength=wavelengths, wvl_norm_nm=norm_wl), model_folder

def evaluate_nn(analysis: str, model_folder: str, nn_input: np.ndarray, n_layers: int) -> np.ndarray:
    """Evaluate the NN models of an analysis on the normalised spectra.

    Args:
        analysis: 'composition' or 'taxonomy'.
        model_folder: Model folder of the instrument from NN_INSTRUMENTS.
        nn_input: Normalised spectra from prepare_nn_input, shape (n_pixels, n_bands).
        n_layers: Expected number of outputs per pixel.

    Returns:
        Mean prediction of the models, shape (n_pixels, n_layers).

    Raises:
        PipelineError: If the models cannot be evaluated or give an unexpected number of outputs.
    """
    logger.info(f'{analysis.capitalize()} analysis with {model_folder} models for {len(nn_input)} spectra')
    try:
        predictions = np.asarray(evaluate(nn_models(analysis, model_folder), nn_input))
    except (ValueError, OSError) as e:
        raise PipelineError(f"Evaluating {analysis} models failed: {e}", level='3') from e
    if predictions.shape != (len(nn_input), n_layers):
        raise PipelineError(f"{analysis.capitalize()} models gave output shape {predictions.shape}, expected ({len(nn_input)}, {n_layers})", level='3')
    return predictions

def run_spectral_parameters(data: Level2Data, filtered: PreparedSpectra, cfg: Config) -> list[Path]:
    """Calculate and save the spectral parameters (model 'P').

    Args:
        data: Loaded level 2B data.
        filtered: Filtered spectra.
        cfg: Pipeline config.

    Returns:
        Paths to the written FITS files.
    """
    values = calculate_spectral_parameters(filtered)
    header = analysis_header(data, filtered, 'Spectral parameters', '3B', SPECTRAL_PARAMETER_LAYERS)
    fits_file = save_analysis_cube(data, filtered, values, header, 'spectral_params', cfg.run.output_dir)
    logger.info(f'Spectral parameters saved to: {fits_file}')
    return [fits_file]

def run_composition(data: Level2Data, filtered: PreparedSpectra, cfg: Config) -> list[Path]:
    """Run and save the NN composition analysis for cfg.analysis.instrument (model 'C').

    Args:
        data: Loaded level 2B data.
        filtered: Filtered spectra.
        cfg: Pipeline config.

    Returns:
        Paths to the written FITS files: the full composition and the olivine, orthopyroxene
        and clinopyroxene layers.

    Raises:
        PipelineError: If the NN input cannot be prepared or the models fail.
    """
    nn_input, model_folder = prepare_nn_input(filtered, cfg.analysis.instrument)
    layers = list(get_composition_header().values())
    composition = evaluate_nn('composition', model_folder, nn_input, len(layers))

    header = analysis_header(data, filtered, 'Composition', '3C', layers)
    written = [save_analysis_cube(data, filtered, composition, header, 'composition', cfg.run.output_dir)]
    logger.info(f'Full composition analysis saved to: {written[-1]}')
    for i, subunit in enumerate(('ol', 'opx', 'cpx')): # Olivine, orthopyroxene and clinopyroxene
        header = analysis_header(data, filtered, 'Composition', '3C', [layers[i]])
        written.append(save_analysis_cube(data, filtered, composition[:, i:i + 1], header, subunit, cfg.run.output_dir))
        logger.info(f'{layers[i][1]} saved to: {written[-1]}')
    return written

def run_taxonomy(data: Level2Data, filtered: PreparedSpectra, cfg: Config) -> list[Path]:
    """Run and save the NN taxonomy analysis for cfg.analysis.instrument (model 'T').

    Args:
        data: Loaded level 2B data.
        filtered: Filtered spectra.
        cfg: Pipeline config.

    Returns:
        Paths to the written FITS files.

    Raises:
        PipelineError: If the NN input cannot be prepared or the models fail.
    """
    nn_input, model_folder = prepare_nn_input(filtered, cfg.analysis.instrument)
    layers = list(get_taxonomy_header().values())
    taxonomy = evaluate_nn('taxonomy', model_folder, nn_input, len(layers))

    header = analysis_header(data, filtered, 'Taxonomy', '3C', layers)
    fits_file = save_analysis_cube(data, filtered, taxonomy, header, 'taxonomy', cfg.run.output_dir)
    logger.info(f'Taxonomy analysis saved to: {fits_file}')
    return [fits_file]

def run_mgm(data: Level2Data, filtered: PreparedSpectra, cfg: Config) -> list[Path]:
    """Fit and save the MGM (model 'M').

    Args:
        data: Loaded level 2B data.
        filtered: Filtered spectra.
        cfg: Pipeline config.

    Returns:
        Paths to the written FITS files.

    Raises:
        PipelineError: If cfg.analysis.init_guess is not valid.
    """
    mgm_results = calculate_mgm(filtered, cfg.analysis.init_guess)
    fits_file = save_mgm_table(data, filtered, mgm_results, cfg.analysis.init_guess, cfg.run.output_dir)
    logger.info(f'MGM results saved to: {fits_file}')
    return [fits_file]

# Model letter -> analysis, in the order they are run. MGM is last as it is the slowest
ANALYSES = {
    'P': run_spectral_parameters,
    'C': run_composition,
    'T': run_taxonomy,
    'M': run_mgm,
}

def run_level_3(cfg: Config) -> tuple[list[Path], list[Issue]]:
    """Run the level 3 filtering and the analyses in cfg.analysis.models on the level 2B file.

    A failing analysis is logged and recorded as an issue, the other analyses are still run.

    Args:
        cfg: Pipeline config.

    Returns:
        Paths to the written FITS files and the issues of the failed analyses.

    Raises:
        PipelineError: If cfg.analysis.models has an unknown model, or the level 2B file is
            missing or cannot be prepared for the analysis.
    """
    unknown = [m for m in cfg.analysis.models if m not in ANALYSES]
    if unknown:
        raise PipelineError(f"Unknown models {unknown} in analysis.models, expected any of {list(ANALYSES)}", level='3')

    data = load_level_2(cfg)
    prepared = prepare_spectra(data)
    filtered = filter_spectra(prepared, cfg.analysis.data_filtering, cfg.analysis.z_thresh, cfg.analysis.z_factor)

    written = []
    if cfg.analysis.save_filtered:
        written.append(save_filtered_spectra(data, filtered, cfg.run.output_dir))

    issues = []
    for model, analysis in ANALYSES.items():
        if model not in cfg.analysis.models:
            continue
        try:
            written.extend(analysis(data, filtered, cfg))
        except PipelineError as e:
            logger.error(f"Analysis '{model}' skipped: {e}")
            issues.append(Issue(level='error', message=str(e), source=f'level_3:{model}'))

    return written, issues
