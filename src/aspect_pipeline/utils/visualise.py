import re
from pathlib import Path

import cv2
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from astropy.io import fits

from aspect_pipeline.utils.utilities import id_to_channel, get_frame, normalize_to_8bit
from aspect_pipeline.levels.level_2.transformation_matrix import estimate_matrix

BIN_FRAME_SHAPE = {
    "Vis": (1024, 1024),
    "NIR1": (518, 648),
    "NIR2": (518, 648),
}
BIN_DTYPE = np.dtype("<u2")

_BIN_FILENAME_RE = re.compile(r"dc_(\d+)_exp_")


def _print_stats(frame: np.ndarray) -> None:
    """Print min/max/mean over the non-NaN values of a frame, plus its NaN count."""
    if frame.size == 0:
        print("empty frame")
        return
    n_nan = int(np.count_nonzero(np.isnan(frame))) if np.issubdtype(frame.dtype, np.floating) else 0
    nan_info = f"nan={n_nan}/{frame.size} ({n_nan / frame.size:.1%})"
    if n_nan == frame.size:
        print(f"all values NaN {nan_info}")
        return
    print(f"min={np.nanmin(frame)} max={np.nanmax(frame)} mean={np.nanmean(frame)} {nan_info}")


def _browse_cube(path: Path, data: np.ndarray) -> None:
    n_frames = data.shape[0]
    frame_idx = 0

    fig, ax = plt.subplots()
    im = ax.imshow(data[frame_idx], cmap="gray")
    fig.colorbar(im, ax=ax)
    ax.set_title(f"{path.name} — frame {frame_idx}/{n_frames - 1}")
    _print_stats(data[frame_idx])

    def on_key(event: object) -> None:
        nonlocal frame_idx
        if event.key == "right":
            new_idx = min(frame_idx + 1, n_frames - 1)
        elif event.key == "left":
            new_idx = max(frame_idx - 1, 0)
        else:
            return
        if new_idx == frame_idx:
            return
        frame_idx = new_idx
        im.set_data(data[frame_idx])
        im.autoscale()
        ax.set_title(f"{path.name} — frame {frame_idx}/{n_frames - 1}")
        _print_stats(data[frame_idx])
        fig.canvas.draw_idle()

    fig.canvas.mpl_connect("key_press_event", on_key)
    plt.show()


def visualise_fits_file(path: Path) -> None:
    """
    Print the primary HDU header of a FITS file, then visualise its data.

    1D data is printed along with its min/max/mean. 2D data is shown as an
    image with its min/max/mean printed. 3D data (frame index first, matching
    the pipeline's stacked-cube convention) opens an interactive window where
    left/right arrow keys step through frames, printing each frame's
    min/max/mean as it is shown.

    :param path: path to the FITS file
    :type path: Path
    :raises ValueError: if the primary HDU data has an unsupported number of
        dimensions (not 1D, 2D or 3D)
    """
    path = Path(path)
    with fits.open(path, memmap=False) as hdul:
        print(repr(hdul[0].header))
        data = hdul[0].data
        if data is None:
            return
        data = np.array(data)

    if data.ndim == 1:
        print(data)
        _print_stats(data)
    elif data.ndim == 2:
        plt.imshow(data, cmap="gray")
        plt.colorbar()
        plt.title(path.name)
        _print_stats(data)
        plt.show()
    elif data.ndim == 3:
        _browse_cube(path, data)
    else:
        raise ValueError(f"{path}: unsupported primary HDU data ndim={data.ndim}")


def visualise_bin_file(path: Path) -> None:
    """
    Read a headerless raw .bin frame, print its min/max/mean, and display it.

    :param path: path to the .bin file, named like dc_{channel_id}_exp_{n}.bin
    :type path: Path
    :raises ValueError: if the channel cannot be determined from the filename,
        or the channel has no known 2D frame shape (e.g. SWIR)
    """
    path = Path(path)
    match = _BIN_FILENAME_RE.search(path.name)
    if not match:
        raise ValueError(f"Cannot determine channel from filename: {path.name}")

    channel_id = int(match.group(1))
    channel = id_to_channel.get(channel_id)
    if channel is None or channel not in BIN_FRAME_SHAPE:
        raise ValueError(f"Unsupported channel for .bin visualisation: {channel_id}")

    shape = BIN_FRAME_SHAPE[channel]
    frame = np.fromfile(path, dtype=BIN_DTYPE).reshape(shape)

    print(f"min={frame.min()} max={frame.max()} mean={frame.mean()}")

    plt.imshow(frame, cmap="gray")
    plt.colorbar()
    plt.title(path.name)
    plt.show()


def visualise_alignment(vis: Path, nir: Path) -> None:
    """
    Debug the level 2 Vis-NIR alignment: show each estimation step, then a red/green overlay.

    The Vis frame is warped onto the NIR grid exactly as in level 2 merge_channels
    (float32, INTER_LINEAR, dsize (640, 512)). In the overlay NIR is red, warped Vis is
    green, and where both are bright the colours add up to yellow.

    Args:
        vis: path to the Vis FITS file (frame 0 is used).
        nir: path to the NIR1 or NIR2 FITS file (frame 0 is used).

    Raises:
        ValueError: if a FITS primary HDU has no data, or no homography could be estimated.
        IndexError: if a file has no frame 0.
    """
    vis_frame = get_frame(vis, 0)
    nir_frame = get_frame(nir, 0)

    matrix = estimate_matrix(vis=vis_frame, nir=nir_frame, filter=True, verbose=True)
    if matrix is None:
        raise ValueError(f"No homography could be estimated between {vis} and {nir}")

    # Warp Vis onto the NIR grid with the same settings as level 2 merge_channels
    vis_le = np.ascontiguousarray(vis_frame.astype("<f4"))
    warped_vis = cv2.warpPerspective(vis_le, matrix, (640, 512), flags=cv2.INTER_LINEAR)

    nir_8bit = normalize_to_8bit(nir_frame)
    vis_8bit = normalize_to_8bit(warped_vis)
    if nir_8bit.shape != vis_8bit.shape:
        raise ValueError(f"Warped Vis shape {vis_8bit.shape} does not match NIR shape {nir_8bit.shape}")

    overlay = np.zeros((*nir_8bit.shape, 3), dtype=np.uint8)
    overlay[..., 0] = nir_8bit  # red: NIR
    overlay[..., 1] = vis_8bit  # green: warped Vis

    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    axes[0].imshow(nir_8bit, cmap="gray")
    axes[0].set_title(f"NIR ({Path(nir).name})")
    axes[1].imshow(vis_8bit, cmap="gray")
    axes[1].set_title(f"Warped Vis ({Path(vis).name})")
    axes[2].imshow(overlay)
    axes[2].set_title("Overlay")
    axes[2].legend(
        handles=[
            Patch(color="red", label="NIR only"),
            Patch(color="lime", label="Vis only"),
            Patch(color="yellow", label="Both"),
        ],
        loc="upper right",
    )
    for ax in axes:
        ax.axis("off")
    fig.suptitle("Vis-NIR alignment")
    fig.tight_layout()
    plt.show()
