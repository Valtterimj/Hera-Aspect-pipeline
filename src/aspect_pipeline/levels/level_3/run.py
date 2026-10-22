from astropy.io import fits
import numpy as np
import pandas as pd
from pathlib import Path

from aspect_pipeline.utils.classes import Issue, Config, CalibConfig
from aspect_pipeline.utils.utilities import get_path, get_wavelengths, get_wavelengths_by_channel

from aspect_pipeline.levels.level_3.modules.utilities_spectra import ( normalise_spectra, collect_all_models)
from aspect_pipeline.levels.level_3.level_3_utilities import ( extract_asteroid, nir2_offset_correction, remove_outliers, denoise_spectra, validate_instrument, get_composition_header, get_taxonomy_header)
from aspect_pipeline.levels.level_3.modules.NN_evaluate import evaluate
#from aspect_pipeline.levels.level_3.try_utilities import get_reflectances, plot_4_spectra, plot_spectra
from aspect_pipeline.levels.level_3.mgm import fit, plot
# from aspect_pipeline.levels.level_3.try_utilities import show_mgm_figures, visualise_composition
from aspect_pipeline.levels.level_3.modules.BAR_BC_method import calc_spect_params
from aspect_pipeline.levels.level_3.modules.NN_config_taxonomy import classes
from tqdm import tqdm
import time

import os

"""
The level 3 of the ASPECT data processing pipeline consist of 3 sublevels:
    - Level 3A: Data filtering; Connecting segments, removing outliers, smoothing
    - Level 3B: Spectral parameters; Albedo, slope, band depths
    - Level 3C Composition analysis; Asteroid taxonomy, mineral content 

Parameters:
    instrument:int
        'vis-nir1-nir2' = ASPECT vis nir1 nir2
        'vis-nir1-nir2'-swir = ASPECT vis nir1 nir2 swir
        'nir1-nir2' = ASPECT nir1 nir2
        'nir1-nir2-swir' = ASPECT nir1 nir2 swir
    
    models:str
        C = Composition
        T = Taxonomy
        M = MGM
    
    nir_overlap:int
        1231 nm is the default wavelength used to align nir1 and nir2 segments
    
    z_thresh:int
        Threshold for determining outliers from the spectra. Low values gives more outliers. Default 1

"""

def run_level_3(cfg: Config):

    """
    Execute the steps 3A, 3B, 3C. Opens the FITS file containing the combined data product. Performs data filtering (if applied) and desired analysis algoritms defined in models parameter.

    Parameters:
        fits_file (str) : file path to the fits file with strucutre as output from level 2B. xs
        isntrument (str) : defines which channels are included inthe analysis.
        data_filtering (bool) : are connecting NIR segments, removing outliers, and smoothing applied
        models (str) : which analysis are applied C = Composition, T = Taxonomy, M = MGM
        nir_overlap (int) : What is the wavelength in nm where NIR1 and NIR2 overlap.
        z_thresh (int) : threshold for removing outliers
        initGuess (list[list[float]]) : initial guesses for MGM

    Returns:

    """

    input_dir = cfg.run.input_dir
    fits_file = get_path(input_dir=input_dir, channel='all', suffix='2B.fits')

    output_dir = cfg.run.output_dir

    instrument = cfg.analysis.instrument
    data_filtering = cfg.analysis.data_filtering
    models = cfg.analysis.models
    nir_overlap = cfg.analysis.nir_overlap
    z_factor = cfg.analysis.z_factor
    z_thresh = cfg.analysis.z_thresh
    init_guess = cfg.analysis.init_guess

    save_filtered = False

    with fits.open(fits_file) as hdul:
        primary_hdu = hdul[0]
        primary_header = primary_hdu.header
        primary_data = primary_hdu.data
        black_frame = np.zeros_like(primary_data[0]) # Used for analysis results

    validate_instrument(instrument)
    wavelengths = get_wavelengths_by_channel(fits_file)

    all_wl = np.sort(np.concatenate([wavelengths[ch] for ch in wavelengths.keys()]))

    # Extract the spectrums from data cube
    print(f'Extracting asteroid spectra')
    combined = extract_asteroid(primary_data, mask_index=0)

    coords, spectras = zip(*combined)
    coords = np.array(coords) 
    spectras = np.array(spectras)
    print(f'{len(spectras)} spectras extracted')

    match instrument:
        case 'Vis-NIR1-NIR2': 
            norm_wl = 1546
            start_idx = 0
            end_idx = int(np.where(all_wl == wavelengths['NIR2'][-1])[0]) + 1
            model_name = 'ASPECT-vis-nir1-nir2-1546'
        case 'Vis-NIR1-NIR2-SWIR':
            norm_wl = 2348
            start_idx = 0
            end_idx = len(all_wl)
            model_name = 'ASPECT-vis-nir1-nir2-swir-2366'
        case 'NIR1-NIR2': 
            norm_wl = 1546
            start_idx = int(np.where(all_wl == wavelengths['NIR1'][0])[0])
            end_idx = int(np.where(all_wl == wavelengths['NIR2'][-1])[0]) + 1
            model_name = 'ASPECT-nir1-nir2-1546'
        case 'NIR1-NIR2-SWIR':
            norm_wl = 2348
            start_idx = int(np.where(all_wl == wavelengths['NIR1'][0])[0])
            end_idx = len(all_wl)
            model_name = 'ASPECT-nir1-nir2-swir-2366'

    # Select the range based on instrument selection
    selected_wl = all_wl[start_idx:end_idx]
    first_nir1_idx = int(np.where(selected_wl == wavelengths['NIR1'][0])[0])
    nir1_len = len(wavelengths['NIR1'])
    nir2_len = len(wavelengths['NIR2'])
    first_nir2_idx = first_nir1_idx + nir1_len
    selected_wl = np.array(list(dict.fromkeys(selected_wl)))

    # Exclude pixels with zeros in the selected range. Denoising turns zeros into
    # near-zero values and normalising by them overflows. Excluded pixels are written as NaN.
    valid = np.all(spectras[:, start_idx:end_idx] != 0, axis=1)
    excluded_coords = coords[~valid]
    coords = coords[valid]
    spectras = spectras[valid]
    print(f'{len(excluded_coords)} spectras excluded due to zero values')

    denoised_spectras = []
    if data_filtering:
        print(f'Applying data filtering')
        print(f'outlier threshold: {z_thresh}, denoising factor: {z_factor}')
        for i, spectra in enumerate(tqdm(spectras, desc="Filtering spectra", unit="spec")):
            #3A
            nir1_spectra = spectra[first_nir1_idx : first_nir1_idx + nir1_len]
            nir2_spectra = spectra[first_nir1_idx + nir1_len : first_nir1_idx + nir1_len + nir2_len]
            nir2_offset_correction_result = nir2_offset_correction(
                nir1_wavelengths=wavelengths['NIR1'],
                nir1_spectra=nir1_spectra,
                nir2_wavelengths=wavelengths['NIR2'],
                nir2_spectra=nir2_spectra,
                overlap_wavelength=nir_overlap
            )

            connected = np.concatenate(
                [spectra[start_idx:first_nir1_idx + nir1_len], nir2_offset_correction_result[0][1:]] +
                ([spectra[first_nir1_idx + nir1_len + nir2_len:end_idx]])
            )

            # Remove outliers
            cleaned = remove_outliers(connected, selected_wl, z_thresh=z_thresh)[0]

            # denoise spectra 
            denoised = denoise_spectra(cleaned, selected_wl, z_factor=z_factor).flatten()

            denoised_spectras.append(denoised)

    else:
        # Only select the range remove the nir1-nir2 ovelap
        selected_wl = np.array(list(dict.fromkeys(selected_wl)))
        if nir1_len + nir2_len == 26: # Remove the overlapping wl 
            for i, spectra in enumerate(spectras):
                #3A
                denoised = np.delete(spectra[start_idx:end_idx], first_nir1_idx + nir1_len)
        denoised_spectras = spectras

    denoised_spectras = np.array(denoised_spectras)

    #Metadata
    stem = fits_file.stem
    suffix = fits_file.suffix

    if save_filtered:
        print(f'Saving denoised spectra')
        hdr = primary_header.copy()

        
        denoised_bands = denoised_spectras.shape[1]
        height, width = primary_data.shape[1:]
        new_cube = np.zeros((denoised_bands, height, width), dtype=primary_data.dtype)
        for i, (y, x) in enumerate(coords):
            new_cube[:, y, x] = denoised_spectras[i]
        new_cube[:, excluded_coords[:, 0], excluded_coords[:, 1]] = np.nan

        denoised_header = primary_header.copy()
        calibration_lvl = '3A'
        primary_header['PROCLEVL'] = calibration_lvl
        denoised_file_name = stem[:25] + calibration_lvl + suffix
        denoised_header['FILENAME'] = denoised_file_name
        denoised_hdu = fits.PrimaryHDU(data=new_cube, header=denoised_header)
        fits_file = os.path.join(output_dir, denoised_file_name)
        denoised_hdu.writeto(fits_file, overwrite=True)
        print(f'New fits file created: {fits_file}')

    # denoised_spectras[denoised_spectras == 0] = 1e-5# replace 0 values

    if 'P' in models:
        print('Calculating spectral parameters')
        calibration_lvl = '3B'
        all_results = calc_spect_params(selected_wl, denoised_spectras, visualise=False)
        SLOPES, BIC, BID, BIW, BIAR = all_results

        template_frame = np.full_like(black_frame, np.nan)
        layer_count = len(all_results)
        cube = np.stack([template_frame] * layer_count, axis=0)

        for n, result in enumerate(all_results):
            for i, val in enumerate(result):
                coordinate = coords[i]
                cube[n, coordinate[0], coordinate[1]] = val
        
        print('Writing results into files')
        primary_header['ANALYSIS'] = ('Spectral parameters', 'Type of analysis')
        primary_header.insert('ANALYSIS', ('COMMENT', ' - - - - - - - - Data Analysis - - - - - - - -'), after=False)
        p_file_name = stem[:25] + calibration_lvl + suffix
        p_header = primary_header.copy()
        p_header['FILENAME'] = p_file_name
        p_header['LAYER_00'] = ('SLOPE', 'Spectral slope')
        p_header['LAYER_01'] = ('BIC', 'First band center')
        p_header['LAYER_02'] = ('BID', 'First band depth')
        p_header['LAYER_03'] = ('BIW', 'First band width')
        p_header['LAYER_04'] = ('BIAR', 'First band area')
        p_hdu = fits.PrimaryHDU(data=cube, header=p_header)
        fits_file = os.path.join(output_dir, p_file_name)
        p_hdu.writeto(fits_file, overwrite=True)
        print(f'New fits file created: {fits_file}')
    
    calibration_lvl = '3C'
    primary_header['PROCLEVL'] = calibration_lvl

    if 'M' in models:
        print('MGM analysis')
        print(denoised_spectras.shape)
        print(len(denoised_spectras))
        mgm_results = []
        for i, spectra in enumerate(tqdm(denoised_spectras[:5000])):
            combined = np.column_stack((selected_wl, spectra))
            result = fit(combined, init_guess, contLinDeg=0, eps=0.01)
            mgm_results.append(result)

        _, _band_parameters, _continuum, _p_values = mgm_results[0]
        len_of_bp = len(_band_parameters)
        len_of_bpl = len(_band_parameters[0])
        len_of_cont = len(_continuum)
        len_of_p = len(_p_values)

        # Binary HDU columns
        n = len(mgm_results)
        coordinates = coords
        rms_array = np.zeros(n, dtype=np.float32)
        band_parameters = np.zeros((n, len_of_bp, len_of_bpl), dtype=np.float32)
        continuum_parameters = np.zeros((n, len_of_cont), dtype=np.float32)
        continuum_p_values = np.zeros((n, len_of_p), dtype=np.float32)

        # Append the data to columns
        for i, result in enumerate(mgm_results):
            rms, bp, cont_vals, cont_pvals = result
            rms_array[i] = rms
            band_parameters[i] = bp
            continuum_parameters[i] = cont_vals
            continuum_p_values[i] = cont_pvals

        cols = fits.ColDefs([
            fits.Column(name='COORDS', format='2J', array=coordinates[:5000]),
            fits.Column(name='RMS', format=f'E', array=rms_array),
            fits.Column(name='BANDPRM', format='6E', dim='(3,2)', array=band_parameters),
            fits.Column(name='CONTPRM', format=f'{len_of_cont}E', array=continuum_parameters),
            fits.Column(name='CONTPVAL', format=f'{len_of_p}E', array=continuum_p_values)
        ])
        bin_table_hdu = fits.BinTableHDU.from_columns(cols)

        mgm_header = primary_header.copy()
        mgm_header['ANALYSIS'] = ('MGM', 'Type of analysis')
        mgm_header.insert('ANALYSIS', ('COMMENT', ' - - - - - - - - Data Analysis - - - - - - - -'), after=False)
        mgm_name = stem[:25] + calibration_lvl + '_MGM' + suffix
        mgm_header['FILENAME'] = mgm_name
        mgm_header['COLUMNS'] = 'pixel coordinates, rms, band parameters, continuum parameters, continuum p-values'
        mgm_header['INITGUES'] = str(init_guess)

        mgm_primary_hdu = fits.PrimaryHDU(header=mgm_header)
        new_hdul = fits.HDUList([mgm_primary_hdu, bin_table_hdu])
        fits_file = os.path.join(output_dir, mgm_name)
        new_hdul.writeto(fits_file, overwrite=True)
        print(f'New fits file created: {fits_file}')

    if 'C' in models or 'T' in models:
        print(f'Normalising spectras at {norm_wl}nm')
        spectra_normalized = normalise_spectra(
            data=denoised_spectras,
            wavelength=selected_wl,
            wvl_norm_nm=norm_wl
        )

    if 'C' in models:
        
        print('Composition analysis with Neural Network')
        model_subdir = os.path.join('composition', model_name)
        prefix = ""
        model_names = collect_all_models(prefix=prefix, subfolder_model=model_subdir, full_path=True)
        composition = evaluate(model_names, spectra_normalized)
        composition = np.array(composition)
        composition = np.nan_to_num(composition, nan=1e-5)   # replaces NaN with 1e-5
        composition[composition == 0] = 1e-5    
        zeros = (composition == 0).sum()
        nans  = np.isnan(composition).sum()

        print("Zeros:", zeros)
        print("NaNs:", nans)
        mean_row = np.mean(composition, axis=0) # means of all the results
        print('Mean:')
        print(mean_row)
        ol_frame = black_frame.copy()
        opx_frame = black_frame.copy()
        cpx_frame = black_frame.copy()
        cube = np.stack([black_frame] * len(composition[0]), axis=0)

        for i, result in enumerate(composition):
            result = composition[i]
            coordinate = coords[i]
            ol_frame[coordinate[0], coordinate[1]] = result[0]
            opx_frame[coordinate[0], coordinate[1]] = result[1]
            cpx_frame[coordinate[0], coordinate[1]] = result[2]
            for n in range(len(composition[0])):
                cube[n, coordinate[0], coordinate[1]] = result[n]

        for frame in (ol_frame, opx_frame, cpx_frame):
            frame[excluded_coords[:, 0], excluded_coords[:, 1]] = np.nan
        cube[:, excluded_coords[:, 0], excluded_coords[:, 1]] = np.nan

        print('Writing results into files')
        #Olivine
        primary_header['ANALYSIS'] = ('Composition', 'Type of analysis')
        primary_header.insert('ANALYSIS', ('COMMENT', ' - - - - - - - - Data Analysis - - - - - - - -'), after=False)
        ol_file_name = stem[:25] + calibration_lvl + '_OL_comp' + suffix
        ol_header = primary_header.copy()
        ol_header['FILENAME'] = ol_file_name
        ol_header['LAYER_00'] = ('OL (vol%)', 'Olivine volume percentage')
        ol_hdu = fits.PrimaryHDU(data=ol_frame, header=ol_header)
        fits_file = os.path.join(output_dir, ol_file_name)
        ol_hdu.writeto(fits_file, overwrite=True)
        print(f'New fits file created: {fits_file}')

        #Orthopyroxene
        opx_file_name = stem[:25] + calibration_lvl + '_OPX_comp' + suffix
        opx_header = primary_header.copy()
        opx_header['FILENAME'] = opx_file_name
        opx_header['LAYER_00'] = ('OPX (vol%)', 'Orthopyroxene volume percentage')
        opx_hdu = fits.PrimaryHDU(data=opx_frame, header=opx_header)
        fits_file = os.path.join(output_dir, opx_file_name)
        opx_hdu.writeto(fits_file, overwrite=True)
        print(f'New fits file created: {fits_file}')

        #Clinopyroxene
        cpx_file_name = stem[:25] + calibration_lvl + '_CPX_comp' + suffix
        cpx_header = primary_header.copy()
        cpx_header['FILENAME'] = cpx_file_name
        cpx_header['LAYER_00'] = ('CPX (vol%)', 'Clinopyroxene volume percentage')
        cpx_hdu = fits.PrimaryHDU(data=cpx_frame, header=cpx_header)
        fits_file = os.path.join(output_dir, cpx_file_name)
        cpx_hdu.writeto(fits_file, overwrite=True)
        print(f'New fits file created: {fits_file}')

        #All composition results
        composition_file_name = stem[:25] + calibration_lvl + '_Composition' + suffix
        composition_header = primary_header.copy()
        composition_header['FILENAME'] = composition_file_name
        layers_metadata = get_composition_header()
        for key, (value, comment) in layers_metadata.items():
            composition_header[key] = (value, comment)
        composition_hdu = fits.PrimaryHDU(data=cube, header=composition_header)
        fits_file = os.path.join(output_dir, composition_file_name)
        composition_hdu.writeto(fits_file, overwrite=True)
        print(f'New fits file created: {fits_file}')
        
    if 'T' in models:
        print('Taxonomy analysis with Neural Network')
        model_subdir = os.path.join('taxonomy', model_name)
        prefix = ""
        model_names = collect_all_models(prefix=prefix, subfolder_model=model_subdir, full_path=True)

        predictions = evaluate(model_names, spectra_normalized)
        taxonomy = {k: predictions[:, index] for k, index in classes.items()}

        df = pd.DataFrame(taxonomy)
        taxonomy = np.array(predictions)
        layer_count = len(taxonomy[0])

        cube = np.stack([black_frame] * layer_count, axis=0)

        for i, result in enumerate(taxonomy):
            result = taxonomy[i]
            coordinate = coords[i]
            for n in range(layer_count):
                cube[n, coordinate[0], coordinate[1]] = result[n]
        cube[:, excluded_coords[:, 0], excluded_coords[:, 1]] = np.nan

        print('Writing results into files')
        taxonomy_header = primary_header.copy()
        taxonomy_header['ANALYSIS'] = ('Taxonomy', 'Type of analysis')
        taxonomy_header.insert('ANALYSIS', ('COMMENT', ' - - - - - - - - Data Analysis - - - - - - - -'), after=False)
        taxonomy_name = stem[:25] + calibration_lvl + '_Taxonomy' + suffix
        taxonomy_header['FILENAME'] = taxonomy_name
        layers_metadata = get_taxonomy_header()
        for key, (value, comment) in layers_metadata.items():
            taxonomy_header[key] = (value, comment)
        taxonomy_hdu = fits.PrimaryHDU(data=cube, header=taxonomy_header)
        fits_file = os.path.join(output_dir, taxonomy_name)
        taxonomy_hdu.writeto(fits_file, overwrite=True)
        print(f'New fits file created: {fits_file}')

    return None, None
