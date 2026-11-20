"""Step-by-step image operations for the AFC / DRACO Didymos images.

Functions:
  read_image(path)          FITS -> array, padding (NaN or flag values) removed
  flip(img, dir)            exact mirror: "x" = left<->right, "y" = top<->bottom
  transform(img, flip_dir, factor, deg)
                            flip -> scale -> rotate (CCW, origin='lower') combined
                            into ONE bilinear resampling; flip None, factor 0/1 and
                            deg 0 skip that step. No scaling + a multiple of 90 deg
                            is done exactly (no interpolation).
  warp(img, m, shape)       one bilinear resampling with a 3x3 matrix (also used
                            by features.py)
  asteroid_mask(img, ...)   copied from level_3_utilities.asteroid_mask, plus a
                            `region` option ("largest" region only, or "all");
                            no 15x15 erode, and holes inside are filled
  crop(img, size, ...)      exact size x size square centred on the asteroid mask

Empty areas are filled with FILL (config.py). Each saved image is interpolated
at most once. The _transfer.fits header records the source file (TRSRC) and
the 3x3 matrix TRM11..TRM33 from source pixels to transferred pixels, so
features.py can build its aligned image from the original in one step too.

main() applies, to each image, read -> transform -> crop with the DRACO_* and
AFC_* settings in config.py.

Usage (from the repository root). Every run saves the transferred images as
DRACO_TRANSFER and AFC_TRANSFER (.fits and .png, config.py), overwriting
earlier ones:

  # show the asteroid_mask threshold + overlay figures, then save
  # (2 windows per image, DRACO first; close them to continue)
  uv run python scripts/dart_hera_change_detection/image_transfer.py

  # save only, no figures
  uv run python scripts/dart_hera_change_detection/image_transfer.py --no-visualise

  Options: --size N (crop size [px], default CROP_SIZE)
           --region largest|all (mask region used for the crop centre, default MASK_REGION)

The code is done partly with AI
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits
from matplotlib.patches import Patch
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import (AFC_FITS, AFC_FLIP, AFC_ROTATION, AFC_SCALE, AFC_TRANSFER, CROP_SIZE,  # noqa: E402
                    DRACO_FITS, DRACO_FLIP, DRACO_ROTATION, DRACO_SCALE, DRACO_TRANSFER, FILL, MASK_REGION,
                    TARGET_M_PER_PX)

SENTINEL_COMMENT = re.compile(r"value assigned to|out of range of lookup|negative before conversion", re.I)


def read_image(path: Path | str) -> np.ndarray:
    """Read the 2-D image from a FITS primary HDU and cut away its padding.

    Padding = NaN/inf pixels and flag values declared in header comments
    (e.g. DRACO's ``PXOUTWIN = -1E10 / Value assigned to pixels outside
    window2``). The image is cropped to the bounding box of the valid pixels.

    Returns:
        2-D float64 array (original units).

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If there is no 2-D image, no valid pixel, or invalid pixels
            remain inside the valid bounding box.
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with fits.open(path, memmap=False) as hdul:
        if hdul[0].data is None or hdul[0].data.ndim != 2:
            raise ValueError(f"{path}: primary HDU has no 2-D image")
        data = np.array(hdul[0].data, dtype=np.float64, copy=True)
        header = hdul[0].header
        flags = [float(c.value) for c in header.cards if SENTINEL_COMMENT.search(str(c.comment))]
    valid = np.isfinite(data)
    for value in flags:
        valid &= data != value
    if not valid.any():
        raise ValueError(f"{path}: no valid pixels")
    rows, cols = np.nonzero(valid.any(axis=1))[0], np.nonzero(valid.any(axis=0))[0]
    r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    if not valid[r0:r1, c0:c1].all():
        n = int((~valid[r0:r1, c0:c1]).sum())
        raise ValueError(f"{path}: {n} invalid pixels inside the image area")
    print(f"{path.name}: {data.shape} -> {r1 - r0} x {c1 - c0} (rows {r0}-{r1 - 1}, cols {c0}-{c1 - 1})")
    return data[r0:r1, c0:c1]


def flip(img: np.ndarray, dir: str) -> np.ndarray:
    """Mirror the image: "x" = left<->right (horizontal), "y" = top<->bottom (vertical).

    Raises:
        ValueError: For any other ``dir``.
    """
    if dir == "x":
        return img[:, ::-1].copy()
    if dir == "y":
        return img[::-1, :].copy()
    raise ValueError(f"dir must be 'x' or 'y', got {dir!r}")


def translation(dx: float, dy: float) -> np.ndarray:
    """3x3 matrix that shifts (x, y) pixel coordinates by (dx, dy) [px]."""
    return np.array([[1.0, 0.0, dx], [0.0, 1.0, dy], [0.0, 0.0, 1.0]])


def transform_matrix(shape: tuple[int, int], flip_dir: str | None = None, factor: float = 1.0,
                     deg: float = 0.0) -> tuple[np.ndarray, tuple[int, int]]:
    """Matrix of flip -> scale -> rotate about the image centre, and the output shape.

    Coordinates are (x, y) = (column, row) [px, 0-based]; with origin='lower'
    y points up, so ``deg`` > 0 turns counter-clockwise as displayed. The
    output canvas is just large enough to hold the whole transformed image.

    Args:
        shape: (rows, cols) of the input image.
        flip_dir: "x", "y" or None (no flip).
        factor: scale factor (< 1 shrinks); 1 or 0 = no scaling.
        deg: rotation [deg]; 0 = no rotation.

    Returns:
        (3x3 matrix input (x, y, 1) -> output (x, y, 1), output (rows, cols)).

    Raises:
        ValueError: For an unknown ``flip_dir`` or a negative ``factor``.
    """
    rows, cols = shape
    if factor < 0:
        raise ValueError(f"factor must be > 0 (or 0/1 = no scaling), got {factor}")
    factor = 1.0 if factor == 0 else factor
    if flip_dir is None:
        f = np.eye(3)
    elif flip_dir == "x":
        f = np.array([[-1.0, 0.0, cols - 1], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    elif flip_dir == "y":
        f = np.array([[1.0, 0.0, 0.0], [0.0, -1.0, rows - 1], [0.0, 0.0, 1.0]])
    else:
        raise ValueError(f"flip_dir must be 'x', 'y' or None, got {flip_dir!r}")
    t = np.radians(deg)
    lin = np.eye(3)
    lin[:2, :2] = factor * np.array([[np.cos(t), -np.sin(t)], [np.sin(t), np.cos(t)]])
    # Output size: extent of the transformed pixel area (corners at -0.5 and n - 0.5).
    corners = lin[:2, :2] @ np.array([[-0.5, cols - 0.5, -0.5, cols - 0.5], [-0.5, -0.5, rows - 0.5, rows - 0.5]])
    out_cols, out_rows = (int(np.ceil(e - 1e-6)) for e in np.ptp(corners, axis=1))
    m = translation((out_cols - 1) / 2, (out_rows - 1) / 2) @ lin @ translation(-(cols - 1) / 2, -(rows - 1) / 2) @ f
    return m, (out_rows, out_cols)


def warp(img: np.ndarray, m: np.ndarray, out_shape: tuple[int, int]) -> np.ndarray:
    """Resample ``img`` once (bilinear) with the 3x3 matrix ``m`` (input (x, y) -> output (x, y)).

    ``m`` may be affine or projective (homography). Output pixels that fall
    outside the input are FILL.
    """
    yy, xx = np.indices(out_shape, dtype=np.float64)
    src = np.linalg.inv(m) @ np.vstack([xx.ravel(), yy.ravel(), np.ones(xx.size)])
    sx, sy = src[0] / src[2], src[1] / src[2]
    out = ndimage.map_coordinates(img, [sy, sx], order=1, mode="constant", cval=FILL)
    return out.reshape(out_shape)


def transform(img: np.ndarray, flip_dir: str | None = None, factor: float = 1.0,
              deg: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Flip, scale and rotate in ONE resampling (see transform_matrix for the arguments).

    Without scaling and with a rotation that is a multiple of 90 deg, the
    result is an exact pixel rearrangement (no interpolation at all).

    Returns:
        (transformed image, 3x3 matrix input (x, y) -> output (x, y)).
    """
    m, out_shape = transform_matrix(img.shape, flip_dir, factor, deg)
    if factor in (0, 1) and deg % 90 == 0:
        out = img if flip_dir is None else flip(img, flip_dir)
        out = np.rot90(out, k=int(round(-deg / 90))).copy()  # rot90 turns CCW for origin='upper'
        if out.shape != out_shape:
            raise ValueError(f"internal error: exact path shape {out.shape} != {out_shape}")
        print(f"transform: exact (flip {flip_dir}, rotation {deg:g} deg), {img.shape} -> {out.shape}")
        return out, m
    print(f"transform: one bilinear resampling (flip {flip_dir}, scale {factor:g}, rotation {deg:g} deg), "
          f"{img.shape} -> {out_shape}")
    return warp(img, m, out_shape), m


# ---------------------------------------------------------------------------
# Copied from src/aspect_pipeline/levels/level_3/level_3_utilities.py
# (normalize_to_8bit, overlay_images, asteroid_mask). Changes in asteroid_mask:
# `region` option, origin='lower' in the figures, error if the mask is empty.
# ---------------------------------------------------------------------------


def normalize_to_8bit(img: np.ndarray) -> np.ndarray:
    """Min/max normalise to 0-255 uint8 (copied unchanged)."""
    min_val, max_val = np.min(img), np.max(img)
    if max_val - min_val == 0:
        return np.zeros_like(img, dtype=np.uint8)
    return ((img - min_val) / (max_val - min_val) * 255.0).astype(np.uint8)


def overlay_images(image1: np.ndarray, image2: np.ndarray, mode: str = "red-green") -> np.ndarray:
    """RGB overlay of two equally sized images (copied unchanged)."""
    def normalize(img):
        img = img.astype(np.float32)
        return (img - np.min(img)) / (np.max(img) - np.min(img) + 1e-8)

    rgb = np.zeros((*image1.shape, 3), dtype=np.float32)
    rgb[..., 0] = normalize(image1)
    if mode == "red-green":
        rgb[..., 1] = normalize(image2)
    elif mode == "red-blue":
        rgb[..., 2] = normalize(image2)
    else:
        raise ValueError("Mode must be 'red-green' or 'red-blue'.")
    return rgb


def asteroid_mask(image: np.ndarray, visualise: bool = True, region: str = "largest") -> np.ndarray:
    """Binary asteroid mask: 8-bit normalise, blur, Otsu threshold, close/open (no erode), fill holes.

    Args:
        image: 2-D image.
        visualise: Show the threshold and overlay figures (blocking plt.show()).
        region: "largest" keeps only the largest connected region (Didymos,
            excluding e.g. Dimorphos); "all" keeps the whole mask as in the
            pipeline version.

    Returns:
        uint8 mask (255 = asteroid, 0 = background).

    Raises:
        ValueError: For an unknown ``region`` or an empty mask.
    """
    if region not in ("largest", "all"):
        raise ValueError(f"region must be 'largest' or 'all', got {region!r}")
    original = image.copy()
    img_norm = normalize_to_8bit(np.asarray(image).astype(np.float32, copy=False))
    blurred = cv2.GaussianBlur(img_norm, (5, 5), 0)
    _, th = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 17)))
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    # The pipeline version erodes 15x15 here; removed so the mask keeps the Otsu boundary.
    th = cv2.morphologyEx(th, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))

    n, labels, stats, _ = cv2.connectedComponentsWithStats((th > 0).astype(np.uint8), connectivity=8)
    if n <= 1:
        raise ValueError("asteroid_mask: mask is empty")
    print(f"asteroid_mask: {n - 1} region(s), sizes {sorted(stats[1:, cv2.CC_STAT_AREA].tolist(), reverse=True)} px; "
          f"using {region}")
    if region == "largest":
        th = np.where(labels == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA])), 255, 0).astype(np.uint8)
    before = int((th > 0).sum())
    th = np.where(ndimage.binary_fill_holes(th > 0), 255, 0).astype(np.uint8)
    print(f"asteroid_mask: {before} px, {int((th > 0).sum())} px after filling holes")

    if visualise:
        fig, axs = plt.subplots(1, 2, figsize=(14, 6))
        axs[0].imshow(img_norm, cmap="gray", origin="lower")
        axs[0].set_title("Original (normalised)")
        axs[1].imshow(th, cmap="gray", origin="lower")
        axs[1].set_title(f"Otsu threshold + morphology ({region})")
        for ax in axs:
            ax.axis("off")
        plt.tight_layout()
        plt.show()

        plt.figure()
        plt.suptitle("Image and mask overlay", fontsize=16)
        plt.imshow(overlay_images(original, th), origin="lower")
        plt.axis("off")
        plt.figlegend(handles=[Patch(facecolor="yellow", edgecolor="black", label="Image and mask"),
                               Patch(facecolor="red", edgecolor="black", label="Only in image"),
                               Patch(facecolor="green", edgecolor="black", label="Only in mask")],
                      loc="lower center", ncol=3, frameon=True, fontsize="medium")
        plt.tight_layout(rect=[0, 0.05, 1, 0.95])
        plt.show()
    return th


def crop(img: np.ndarray, size: int, visualise: bool = True,
         region: str = "largest") -> tuple[np.ndarray, tuple[int, int]]:
    """Cut a size x size square centred on the asteroid mask (exact, no interpolation).

    The centre is the (unweighted) centroid of the mask pixels, rounded to the
    nearest pixel; it becomes pixel (size // 2, size // 2) of the result.
    Areas outside the input image are filled with FILL.

    Returns:
        (cropped image, (x0, y0) = input pixel of the crop's pixel (0, 0) [px]).

    Raises:
        ValueError: If size < 1.
    """
    if size < 1:
        raise ValueError(f"size must be >= 1, got {size}")
    mask = asteroid_mask(img, visualise=visualise, region=region)
    rows, cols = np.nonzero(mask)
    cy, cx = int(round(rows.mean())), int(round(cols.mean()))
    r0, c0 = cy - size // 2, cx - size // 2
    pad = max(0, -r0, -c0, r0 + size - img.shape[0], c0 + size - img.shape[1])
    padded = np.pad(img, pad, mode="constant", constant_values=FILL)
    out = padded[r0 + pad:r0 + pad + size, c0 + pad:c0 + pad + size]
    print(f"crop: mask centre (x={cx}, y={cy}) -> {size} x {size}" + (f", padded by {pad} px" if pad else ""))
    return out, (c0, r0)


def save(img: np.ndarray, path: Path, title: str, header: fits.Header | None = None) -> None:
    """Write the array as FITS (with ``header``) and as PNG (origin='lower')."""
    fits.PrimaryHDU(img.astype(np.float32), header=header).writeto(path.with_suffix(".fits"), overwrite=True)
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(img, cmap="gray", origin="lower", vmin=0, vmax=np.percentile(img[img > 0], 99.9))
    ax.set(title=title, xlabel="x [pixel]", ylabel="y [pixel]")
    fig.savefig(path.with_suffix(".png"), dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {path.with_suffix('.fits')}\n  -> {path.with_suffix('.png')}")


def transfer(path: Path, flip_dir: str | None, factor: float, deg: float, size: int, visualise: bool,
             region: str) -> tuple[np.ndarray, fits.Header]:
    """read -> transform (flip/scale/rotate, one resampling) -> crop.

    Returns:
        (transferred image, header recording the source and the 3x3 matrix
        TRM11..TRM33 from read_image() pixels (x, y) to transferred pixels).
    """
    img, m = transform(read_image(path), flip_dir, factor, deg)
    img, (x0, y0) = crop(img, size, visualise=visualise, region=region)
    m = translation(-x0, -y0) @ m
    hdr = fits.Header()
    hdr["TRSRC"] = (path.name, "source image")
    hdr["TRFLIP"] = (str(flip_dir), "flip before scale/rotation")
    hdr["TRSCALE"] = (factor, "scale factor (0/1 = none)")
    hdr["TRROT"] = (deg, "rotation [deg CCW, origin lower]")
    hdr["TRX0"], hdr["TRY0"] = (x0, "crop corner x in transformed image [px]"), (y0, "crop corner y [px]")
    for r in range(3):
        for c in range(3):
            hdr[f"TRM{r + 1}{c + 1}"] = (float(m[r, c]), f"source->transfer (x,y) matrix r{r + 1}c{c + 1}")
    hdr["HISTORY"] = "image_transfer.py: flip/scale/rotate in one bilinear resampling"
    hdr["HISTORY"] = "(exact when no scale and rotation is a multiple of 90 deg), then crop."
    return img, hdr


def main(argv: list[str] | None = None) -> None:
    """Run the transfer on the DRACO and AFC images with the settings in config.py."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", type=int, default=CROP_SIZE, help="crop size [px]")
    ap.add_argument("--region", choices=("largest", "all"), default=MASK_REGION, help="mask region for the centre")
    ap.add_argument("--no-visualise", action="store_true", help="skip the asteroid_mask figures")
    args = ap.parse_args(argv)
    vis = not args.no_visualise

    for path, flip_dir, factor, deg, out, label in (
            (DRACO_FITS, DRACO_FLIP, DRACO_SCALE, DRACO_ROTATION, DRACO_TRANSFER, "DART DRACO"),
            (AFC_FITS, AFC_FLIP, AFC_SCALE, AFC_ROTATION, AFC_TRANSFER, "Hera AFC-1")):
        img, hdr = transfer(path, flip_dir, factor, deg, args.size, vis, args.region)
        out.parent.mkdir(parents=True, exist_ok=True)
        save(img, out.with_suffix(""), f"{label}, {TARGET_M_PER_PX:.3f} m/px", hdr)


if __name__ == "__main__":
    main()
