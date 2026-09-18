"""Generate dull test data for ASPECT pipeline levels 0-1.

Two primitives (write_bin, write_fits) plus one convenience wrapper per
channel. Run as a script to produce the full default test set:

    python make_test_data.py [raw_dir] [cal_dir]
"""

from pathlib import Path
import sys

import numpy as np
from astropy.io import fits

# (height, width) -- numpy order. Spec gives width x height.
RAW_SHAPE = {"Vis": (1024, 1024), "NIR1": (518, 648), "NIR2": (518, 648)}
CAL_SHAPE = {"Vis": (1024, 1024), "NIR1": (512, 640), "NIR2": (512, 640)}
N_RAW = {"Vis": 11, "NIR1": 13, "NIR2": 13}
CHANNEL_ID = {"Vis": 0, "NIR1": 1, "NIR2": 2}

RAW_DTYPE = np.dtype("<u2")  # little-endian uint16, headerless


def write_bin(path, shape, fill=0, dtype=RAW_DTYPE):
    """Write a headerless binary frame. `fill` is a scalar or an array of `shape`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.broadcast_to(np.asarray(fill), shape).astype(dtype)
    data.tofile(path)
    return path


def write_fits(path, shape, fill=0, dtype=np.float32, header=None):
    """Write a single frame to the primary HDU. `fill` is a scalar or an array of `shape`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = np.broadcast_to(np.asarray(fill), shape).astype(dtype)
    hdu = fits.PrimaryHDU(data=np.array(data))
    if header:
        hdu.header.update(header)
    hdu.writeto(path, overwrite=True)
    return path


def make_raw_set(out_dir, channel, n_files=None, base=1000, step=1):
    """Write n_files raw frames named dc_{c}_exp_{i:03d}.bin; frame i is filled with base + i*step."""
    n_files = N_RAW[channel] if n_files is None else n_files
    shape = RAW_SHAPE[channel]
    c = CHANNEL_ID[channel]
    return [
        write_bin(Path(out_dir) / channel / f"dc_{c}_exp_{i:03d}.bin", shape, base + i * step)
        for i in range(n_files)
    ]


def make_dark(out_dir, channel, fill=100):
    """Write a dark calibration frame named ASc_DARKS.fits into out_dir/TEST_DARK.

    Args:
        out_dir: Calibration root directory.
        channel: Channel name (one of RAW_SHAPE's keys).
        fill: Scalar fill value for the frame.

    Returns:
        Path to the written FITS file.
    """
    c = CHANNEL_ID[channel]
    return write_fits(
        Path(out_dir) / "TEST_DARK" / f"AS{c}_DARKS.fits", CAL_SHAPE[channel], fill,
        header={"CHANNEL": channel, "FRAMETYP": "DARK"},
    )


def make_flat(out_dir, channel, fill_high=2.0, fill_low=1.0):
    """Write high and low flat-field frames into out_dir/TEST_FLATS.

    Args:
        out_dir: Calibration root directory.
        channel: Channel name (one of RAW_SHAPE's keys).
        fill_high: Scalar fill value for the ASc_FLAT_HIGH.fits frame.
        fill_low: Scalar fill value for the ASc_FLAT_LOW.fits frame.

    Returns:
        List of the two written FITS file paths, [high, low].
    """
    c = CHANNEL_ID[channel]
    shape = CAL_SHAPE[channel]
    high = write_fits(
        Path(out_dir) / "TEST_FLATS" / f"AS{c}_FLAT_HIGH.fits", shape, fill_high,
        header={"CHANNEL": channel, "FRAMETYP": "FLAT"},
    )
    low = write_fits(
        Path(out_dir) / "TEST_FLATS" / f"AS{c}_FLAT_LOW.fits", shape, fill_low,
        header={"CHANNEL": channel, "FRAMETYP": "FLAT"},
    )
    return [high, low]


def make_test_set(raw_dir, cal_dir):
    """Write a full synthetic test set: raw frames under raw_dir, calibration files under cal_dir.

    Args:
        raw_dir: Root directory for raw per-channel frames.
        cal_dir: Root directory for calibration files (TEST_DARK/, TEST_FLATS/).

    Returns:
        Tuple of (raw_dir, cal_dir) as Path objects.
    """
    raw_dir = Path(raw_dir)
    cal_dir = Path(cal_dir)
    for ch in RAW_SHAPE:
        make_raw_set(raw_dir, ch)
        make_dark(cal_dir, ch)
        make_flat(cal_dir, ch)
    return raw_dir, cal_dir


if __name__ == "__main__":
    raw_target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("test_data") / "raw"
    cal_target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("test_data") / "cal"
    make_test_set(raw_target, cal_target)
    print(f"Raw test set written to {raw_target.resolve()}")
    print(f"Calibration test set written to {cal_target.resolve()}")