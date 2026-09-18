import re
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
from astropy.io import fits

from aspect_pipeline.utils.utilities import id_to_channel

BIN_FRAME_SHAPE = {
    "Vis": (1024, 1024),
    "NIR1": (518, 648),
    "NIR2": (518, 648),
}
BIN_DTYPE = np.dtype("<u2")

_BIN_FILENAME_RE = re.compile(r"dc_(\d+)_exp_")


def _print_stats(frame: np.ndarray) -> None:
    print(f"min={frame.min()} max={frame.max()} mean={frame.mean()}")


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
