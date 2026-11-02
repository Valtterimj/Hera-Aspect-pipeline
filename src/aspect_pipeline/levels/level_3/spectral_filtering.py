import logging
from dataclasses import replace

import numpy as np
from tqdm import tqdm

from aspect_pipeline.utils.classes import PreparedSpectra
from aspect_pipeline.levels.level_3.level_3_utilities import remove_outliers, denoise_spectra

logger = logging.getLogger(__name__)

"""
Level 3A spectral filtering:
    1. Connecting segments: removing the overlap of consecutive channels (e.g. NIR1 and NIR2)
    2. Removing outliers
    3. Denoising
"""

MIN_FIT_POINTS = 3 # Minimum number of points of each segment used to fit the line at the overlap

def _line_at(wavelengths: np.ndarray, spectra: np.ndarray, wavelength: float) -> np.ndarray:
    """Fit a line to each spectrum and evaluate it at one wavelength.

    Args:
        wavelengths: Wavelengths of the points in nm, shape (n_points,).
        spectra: Reflectance spectra, shape (n_pixels, n_points).
        wavelength: Wavelength in nm where the lines are evaluated.

    Returns:
        Reflectance of each fitted line at the wavelength, shape (n_pixels,).
    """
    coeffs = np.polyfit(wavelengths, spectra.T, 1) # One line per pixel
    return np.polyval(coeffs, wavelength)

def connect_segments(
        segments: list[tuple[np.ndarray, np.ndarray]],
        correct_offset: bool = True,
) -> tuple[np.ndarray, np.ndarray, list[np.ndarray]]:
    """Join consecutive spectral segments and remove the points of each segment that overlap the previous one.

    Segments are joined from left to right. If a segment overlaps the previous one, lines are
    fitted to the overlapping points of both segments (at least the 3 points at the edge of each
    segment) and the segment is shifted so that the lines meet in the middle of the overlap.
    The overlapping points of the later segment are then dropped. Segments without overlap are
    joined unchanged.

    Args:
        segments: (wavelengths, spectra) of each segment in ascending wavelength order. Wavelengths
            in nm have shape (n_bands,) and reflectance spectra have shape (n_pixels, n_bands).
        correct_offset: Shift the overlapping segments. If False, the overlapping points are only dropped.

    Returns:
        Wavelengths of the joined spectra in nm, joined reflectance spectra of shape (n_pixels, n_bands),
        and for each segment a boolean mask of the bands that were kept.

    Raises:
        ValueError: If no segments are given.
    """
    if not segments:
        raise ValueError("No segments to connect")

    joined_wl = np.asarray(segments[0][0])
    joined = np.asarray(segments[0][1])
    kept = [np.ones(len(joined_wl), dtype=bool)]

    for wavelengths, spectra in segments[1:]:
        wavelengths = np.asarray(wavelengths)
        spectra = np.asarray(spectra)
        overlap = wavelengths <= joined_wl[-1]

        if np.any(overlap) and correct_offset:
            n_prev = max(MIN_FIT_POINTS, np.count_nonzero(joined_wl >= wavelengths[0]))
            n_next = max(MIN_FIT_POINTS, np.count_nonzero(overlap))
            overlap_center = (wavelengths[0] + joined_wl[-1]) / 2

            f_prev = _line_at(joined_wl[-n_prev:], joined[:, -n_prev:], overlap_center)
            f_next = _line_at(wavelengths[:n_next], spectra[:, :n_next], overlap_center)
            # Offset is cast to the segment dtype before adding, the segment keeps its dtype and rounding
            offset = (f_prev - f_next).astype(spectra.dtype)
            spectra = np.clip(spectra + offset[:, np.newaxis], 0, None)

        joined_wl = np.concatenate([joined_wl, wavelengths[~overlap]])
        joined = np.concatenate([joined, spectra[:, ~overlap]], axis=1)
        kept.append(~overlap)

    return joined_wl, joined, kept

def filter_spectra(prepared: PreparedSpectra, apply_filters: bool, z_thresh: float, z_factor: float) -> PreparedSpectra:
    """Connect the channel segments and, if filtering is applied, remove outliers and denoise the spectra.

    Without filtering the overlapping bands are only dropped, so the wavelengths are always strictly ascending.

    Args:
        prepared: Asteroid spectra with the overlapping bands of the channels.
        apply_filters: Correct the segment offsets, remove outliers and denoise.
        z_thresh: Threshold for removing outliers. Increase for less sensitive outlier removal.
        z_factor: Denoising factor. Increase for smoother spectra.

    Returns:
        PreparedSpectra with the filtered reflectance spectra, strictly ascending wavelengths (nm),
        and the channel bands and frames of the bands that were kept.
    """
    channels = list(prepared.channel_bands)
    segments = [(prepared.wavelengths[bands], prepared.spectra[:, bands]) for bands in prepared.channel_bands.values()]
    wavelengths, spectra, kept = connect_segments(segments, correct_offset=apply_filters)

    channel_bands = {}
    frames = {}
    start = 0
    for ch, keep in zip(channels, kept):
        channel_bands[ch] = slice(start, start + np.count_nonzero(keep))
        frames[ch] = [frame for frame, k in zip(prepared.frames[ch], keep) if k]
        start = channel_bands[ch].stop
        if not np.all(keep):
            logger.info(f'{ch}: dropped {np.count_nonzero(~keep)} bands overlapping the previous channel')

    if apply_filters:
        logger.info(f'Applying data filtering. outlier threshold: {z_thresh}, denoising factor: {z_factor}')
        filtered = []
        for spectrum in tqdm(spectra, desc="Filtering spectra", unit="spec"):
            cleaned = remove_outliers(spectrum, wavelengths, z_thresh=z_thresh)[0]
            filtered.append(denoise_spectra(cleaned, wavelengths, z_factor=z_factor).flatten())
        spectra = np.array(filtered)

    return replace(prepared, spectra=spectra, wavelengths=wavelengths, channel_bands=channel_bands, frames=frames)
