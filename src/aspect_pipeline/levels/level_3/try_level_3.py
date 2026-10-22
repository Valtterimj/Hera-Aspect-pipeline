import ast
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

from aspect_pipeline.levels.level_3.level_3_utilities import denoise_spectra, get_composition_header
from aspect_pipeline.levels.level_3.modules.NN_config_taxonomy import classes
from aspect_pipeline.levels.level_3.modules.NN_evaluate import evaluate
from aspect_pipeline.levels.level_3.modules.utilities_spectra import collect_all_models, normalise_spectra

DEFAULT_SPECTRA = (Path(__file__).resolve().parents[4] / "data" / "spectral"
                   / "600w_exposures_2500-10000-10000_pixel_reflectances(4-pixel_binning).csv")

# Model folders per instrument. SWIR models are left out: they need data up to ~2440 nm.
MODEL_DIRS = {
    "Vis-NIR1-NIR2": "ASPECT-vis-nir1-nir2-1546",
    "NIR1-NIR2": "ASPECT-nir1-nir2-1546",
}


def read_model_grid(model_file: str) -> tuple[np.ndarray, float]:
    """
    Read the wavelength grid and normalisation wavelength stored in a model file.

    Args:
        model_file: path to the .h5 model file

    Returns:
        Wavelengths the model expects as input (nm) and the normalisation wavelength (nm).
    """
    with h5py.File(model_file, "r") as f:
        params = ast.literal_eval(f.attrs["params"])
    return np.array(params["wavelengths"], dtype=float), float(params["normalised_at"])


def resample_nearest(wavelengths: np.ndarray, spectra: np.ndarray, target_wl: np.ndarray) -> np.ndarray:
    """
    Resample spectra onto target wavelengths by taking the nearest measured wavelength.

    Args:
        wavelengths: measured wavelengths (nm), shape (n_wl,)
        spectra: reflectance spectra (unitless), shape (n_spectra, n_wl)
        target_wl: wavelengths to resample onto (nm), shape (n_target,)

    Returns:
        Resampled reflectance spectra (unitless), shape (n_spectra, n_target).
    """
    nearest = np.abs(wavelengths[np.newaxis, :] - target_wl[:, np.newaxis]).argmin(axis=1)
    return spectra[:, nearest]


def try_nn(spectra_path: str | Path = DEFAULT_SPECTRA, instrument: str = "Vis-NIR1-NIR2",
            denoise: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """
    Run the composition and taxonomy neural networks on a spectral data file and print the results.

    The file is space separated without a header: first column wavelength (nm),
    the remaining columns one reflectance spectrum each.

    Args:
        spectra_path: path to the spectral data file
        instrument: 'Vis-NIR1-NIR2' or 'NIR1-NIR2'
        denoise: smooth the spectra with denoise_spectra before normalising

    Returns:
        Composition predictions (fractions, unitless, 0-1), shape (n_spectra, 10), and
        taxonomy class probabilities (unitless, 0-1), shape (n_spectra, n_classes).

    Raises:
        ValueError: if the instrument is not supported.
    """
    if instrument not in MODEL_DIRS:
        raise ValueError(f"Unsupported instrument '{instrument}'. Use one of: {', '.join(MODEL_DIRS)}")

    data = np.loadtxt(spectra_path)
    wavelengths = data[:, 0]
    spectra = data[:, 1:].T

    print(f"Spectral data: {spectra_path}")
    print(f"{len(spectra)} spectra, {len(wavelengths)} wavelengths ({wavelengths[0]:g}-{wavelengths[-1]:g} nm)")
    print(f"Instrument: {instrument}")

    results = {}
    for analysis in ("composition", "taxonomy"):
        model_subdir = os.path.join(analysis, MODEL_DIRS[instrument])
        model_names = collect_all_models(prefix="", subfolder_model=model_subdir, full_path=True)
        model_wl, norm_wl = read_model_grid(model_names[0])

        resampled = resample_nearest(wavelengths, spectra, model_wl)
        if denoise:
            resampled = denoise_spectra(resampled, model_wl)
        normalised = normalise_spectra(data=resampled, wavelength=model_wl, wvl_norm_nm=norm_wl)

        print(f"\n{analysis.capitalize()}: {len(model_names)} models, {len(model_wl)} wavelengths, "
              f"normalised at {norm_wl:g} nm")
        results[analysis] = evaluate(model_names, normalised)

    composition_columns = [name for name, _ in get_composition_header().values()]
    taxonomy_columns = sorted(classes, key=classes.get)

    with pd.option_context("display.max_columns", None, "display.width", 200, "display.precision", 3):
        print("\nComposition:")
        print(pd.DataFrame(results["composition"], columns=composition_columns))
        print("\nTaxonomy:")
        print(pd.DataFrame(results["taxonomy"], columns=taxonomy_columns))

    return results["composition"], results["taxonomy"]
