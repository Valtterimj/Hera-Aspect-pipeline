"""Run the pipeline's ORB + FLANN feature matching on the transferred images and inspect each step.

Same steps and settings as estimate_matrix() in
src/aspect_pipeline/levels/level_2/transformation_matrix.py:
  1. laplacian() edges                      (imported from the pipeline)
  2. ORB keypoints on the edge images       (settings COPIED below)
  3. FLANN-LSH knn (k=2) + filter_by_distance() (filter imported, FLANN settings COPIED)
  4. keypoints left without a filtered match
  5. RANSAC homography, moving warped onto the reference (threshold COPIED)
Keep the copied constants in sync with estimate_matrix(). ORB/FLANN-LSH/RANSAC
are randomised, so counts can differ slightly between runs.

The first image is the moving one (warped), the second the reference, as in
estimate_matrix(vis, nir); H maps moving (x, y) -> reference (x, y).

Figures (all drawn over the transferred images, origin lower):
  01_edges.png      Laplacian edges in cyan
  02_keypoints.png  ORB keypoints (circle size ~ keypoint scale)
  03_matches.png    matches kept by filter_by_distance, lines between the images
  04_unmatched.png  keypoints not in any filtered match
  05_alignment.png  warped moving | reference | overlay (reference red, warped green)

Aligned images (with --save, same folder):
  <moving stem>_aligned.fits/.png     moving on the reference grid. Built from the
                                      ORIGINAL image (TRSRC in DATA_DIR) with H x the
                                      transfer matrix TRM* from the moving header, in
                                      one bilinear resampling; without TRM* it falls
                                      back to warping the moving file with H.
                                      (H11..H33, HREF, HNINL, HNMATCH, HMEDERR in header)
  <reference stem>_aligned.fits/.png  unchanged copy of the reference

Usage (from the repository root):
  # show the figures (close the windows to exit)
  uv run python scripts/dart_hera_change_detection/features.py --show

  # save the figures and aligned images to FEATURES_DIR (config.py)
  uv run python scripts/dart_hera_change_detection/features.py --save

  # both; or other files: features.py MOVING.fits REFERENCE.fits --show --save
  uv run python scripts/dart_hera_change_detection/features.py --show --save

  Default inputs: DRACO_TRANSFER (moving) and AFC_TRANSFER (reference) from
  config.py, written by image_transfer.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from aspect_pipeline.levels.level_2.transformation_matrix import filter_by_distance, laplacian  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import AFC_TRANSFER, DATA_DIR, DRACO_TRANSFER, FEATURES_DIR  # noqa: E402
from image_transfer import read_image as read_source  # noqa: E402  (same padding removal as the transfer)
from image_transfer import warp  # noqa: E402

# Copied from estimate_matrix():
ORB_NFEATURES = 5000
FLANN_INDEX = {"algorithm": 6, "table_number": 30, "key_size": 20, "multi_probe_level": 2}  # LSH
FLANN_SEARCH = {"checks": 100}
RANSAC_THRESHOLD = 10.0  # px


def read_image(path: Path) -> np.ndarray:
    """Read the primary-HDU 2-D image as float32, non-finite values set to 0.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the primary HDU has no 2-D image.
    """
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found; run image_transfer.py first")
    with fits.open(path, memmap=False) as hdul:
        if hdul[0].data is None or hdul[0].data.ndim != 2:
            raise ValueError(f"{path}: primary HDU has no 2-D image")
        data = np.array(hdul[0].data, dtype=np.float64, copy=True)
    return np.nan_to_num(data, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)


def detect(img: np.ndarray) -> tuple[np.ndarray, list[cv2.KeyPoint], np.ndarray]:
    """Laplacian edges, then ORB keypoints and descriptors on the edges.

    Raises:
        ValueError: If ORB finds no descriptors.
    """
    edges = laplacian(img)
    kps, des = cv2.ORB_create(nfeatures=ORB_NFEATURES).detectAndCompute(edges, None)
    if des is None:
        raise ValueError("ORB found no descriptors")
    return edges, list(kps), des


def match(des_m: np.ndarray, des_r: np.ndarray) -> list[cv2.DMatch]:
    """FLANN-LSH knn matching (k=2) filtered with the pipeline filter_by_distance."""
    knn = cv2.FlannBasedMatcher(FLANN_INDEX, FLANN_SEARCH).knnMatch(des_m, des_r, k=2)
    good = filter_by_distance(knn)
    print(f"FLANN: {len(knn)} knn sets, {len(good)} after filter_by_distance")
    return good


def unmatched(kp_m: list[cv2.KeyPoint], kp_r: list[cv2.KeyPoint],
              good: list[cv2.DMatch]) -> tuple[list[cv2.KeyPoint], list[cv2.KeyPoint]]:
    """Keypoints of each image that are not part of any filtered match."""
    used_m, used_r = {m.queryIdx for m in good}, {m.trainIdx for m in good}
    um = [k for i, k in enumerate(kp_m) if i not in used_m]
    ur = [k for i, k in enumerate(kp_r) if i not in used_r]
    print(f"unmatched keypoints: moving {len(um)}/{len(kp_m)}, reference {len(ur)}/{len(kp_r)}")
    return um, ur


def homography(pa: np.ndarray, pb: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """RANSAC homography moving -> reference, the inlier mask and median inlier error [px].

    Raises:
        ValueError: With fewer than 4 matches or if no homography is found.
    """
    if len(pa) < 4:
        raise ValueError(f"only {len(pa)} matches after filtering; a homography needs >= 4")
    H, inl = cv2.findHomography(pa, pb, cv2.RANSAC, RANSAC_THRESHOLD)
    if H is None:
        raise ValueError("cv2.findHomography could not estimate a homography")
    inl = inl.ravel().astype(bool)
    err = np.hypot(*(cv2.perspectiveTransform(pa.reshape(-1, 1, 2), H).reshape(-1, 2) - pb).T)
    print(f"RANSAC: {inl.sum()}/{len(inl)} inliers, reprojection error median {np.median(err[inl]):.2f} px")
    print(f"H (moving -> reference) =\n{H}")
    return H, inl, float(np.median(err[inl]))


def save_image(img: np.ndarray, header: fits.Header, stem: Path, title: str) -> None:
    """Write ``img`` as <stem>.fits (with ``header``) and a grey <stem>.png (origin lower)."""
    fits.PrimaryHDU(img.astype(np.float32), header=header).writeto(stem.with_suffix(".fits"), overwrite=True)
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(stretch(img), cmap="gray", origin="lower", interpolation="nearest")
    ax.set(title=title, xlabel="x [px]", ylabel="y [px]")
    fig.savefig(stem.with_suffix(".png"), dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {stem.with_suffix('.fits')}\n  -> {stem.with_suffix('.png')}")


def stretch(img: np.ndarray) -> np.ndarray:
    """Display stretch to [0, 1]: 0.5-99.9 percentile of lit pixels (display only)."""
    lit = img[img > 0.1 * np.percentile(img, 99.9)]
    lo, hi = np.percentile(lit, [0.5, 99.9]) if lit.size else (img.min(), img.max())
    return np.clip((img - lo) / (hi - lo if hi > lo else 1.0), 0, 1)


def draw_keypoints(ax, kps: list[cv2.KeyPoint], color: str) -> None:
    """Circles at keypoint positions, size ~ keypoint scale."""
    if kps:
        xy = np.array([k.pt for k in kps])
        ax.scatter(xy[:, 0], xy[:, 1], s=0.075 * np.array([k.size for k in kps]) ** 2, facecolors="none",
                   edgecolors=color, linewidths=0.6)


def side_by_side(imgs: tuple[np.ndarray, np.ndarray], titles: tuple[str, str], suptitle: str, draw=None):
    """Two panels with the transferred images; ``draw(ax, i)`` adds overlays."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 7))
    for i, (ax, img) in enumerate(zip(axes, imgs)):
        ax.imshow(stretch(img), cmap="gray", origin="lower", interpolation="nearest")
        ax.set(title=titles[i], xlabel="x [px]", ylabel="y [px]")
        if draw:
            draw(ax, i)
    fig.suptitle(suptitle)
    return fig


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moving", nargs="?", type=Path, default=DRACO_TRANSFER)
    ap.add_argument("reference", nargs="?", type=Path, default=AFC_TRANSFER)
    ap.add_argument("--show", action="store_true", help="open the figures in matplotlib windows")
    ap.add_argument("--save", action="store_true", help="save the figures as PNG")
    ap.add_argument("--outdir", type=Path, default=FEATURES_DIR)
    args = ap.parse_args(argv)
    if not args.show:
        matplotlib.use("Agg")
    if args.save:
        args.outdir.mkdir(parents=True, exist_ok=True)

    def output(fig, filename: str) -> None:
        if args.save:
            fig.savefig(args.outdir / filename, dpi=120, bbox_inches="tight")
            print(f"  -> {args.outdir / filename}")
        if not args.show:
            plt.close(fig)

    imgs = (read_image(args.moving), read_image(args.reference))
    names = (f"moving: {args.moving.name}", f"reference: {args.reference.name}")

    # 1-2. Edges and ORB keypoints
    (e_m, kp_m, des_m), (e_r, kp_r, des_r) = detect(imgs[0]), detect(imgs[1])
    edges, kps = (e_m, e_r), (kp_m, kp_r)
    print(f"ORB keypoints: moving {len(kp_m)}, reference {len(kp_r)}")

    def draw_edges(ax, i):
        rgba = np.zeros((*edges[i].shape, 4))
        rgba[..., 1:3] = 1.0
        rgba[..., 3] = 0.9 * edges[i] / max(1, edges[i].max())
        ax.imshow(rgba, origin="lower", interpolation="nearest")

    output(side_by_side(imgs, names, "01 Laplacian edges (cyan)", draw_edges), "01_edges.png")
    output(side_by_side(imgs, tuple(f"{n}\n{len(k)} keypoints" for n, k in zip(names, kps)),
                        "02 ORB keypoints (circle size ~ keypoint scale)",
                        lambda ax, i: draw_keypoints(ax, kps[i], "lime")), "02_keypoints.png")

    # 3. Matches after filtering
    good = match(des_m, des_r)
    pa = np.float32([kp_m[m.queryIdx].pt for m in good]).reshape(-1, 2)
    pb = np.float32([kp_r[m.trainIdx].pt for m in good]).reshape(-1, 2)
    off = imgs[0].shape[1]
    canvas = np.zeros((max(i.shape[0] for i in imgs), off + imgs[1].shape[1]))
    canvas[:imgs[0].shape[0], :off] = stretch(imgs[0])
    canvas[:imgs[1].shape[0], off:] = stretch(imgs[1])
    fig, ax = plt.subplots(figsize=(15, 7.5))
    ax.imshow(canvas, cmap="gray", origin="lower", interpolation="nearest")
    for (xa, ya), (xb, yb) in zip(pa, pb):
        ax.plot([xa, xb + off], [ya, yb], color="deepskyblue", linewidth=0.7)
    ax.axvline(off - 0.5, color="white", linewidth=0.8)
    ax.set(title=f"03 matches after filter_by_distance ({len(good)})\nleft {names[0]} | right {names[1]}",
           xlabel="x [px]", ylabel="y [px]")
    output(fig, "03_matches.png")

    # 4. Keypoints without a filtered match
    um = unmatched(kp_m, kp_r, good)
    output(side_by_side(imgs, tuple(f"{n}\n{len(u)} of {len(k)} keypoints unmatched"
                                    for n, u, k in zip(names, um, kps)),
                        "04 keypoints not matched after filtering",
                        lambda ax, i: draw_keypoints(ax, um[i], "orange")), "04_unmatched.png")

    # 5. RANSAC homography, warp and overlay
    H, inl, med_err = homography(pa, pb)
    ref = imgs[1]
    hdr = fits.getheader(args.moving, 0)
    if "TRM11" in hdr and "TRSRC" in hdr:
        # One resampling from the original: source -> transfer (header) then H.
        m_tr = np.array([[hdr[f"TRM{r}{c}"] for c in (1, 2, 3)] for r in (1, 2, 3)])
        source = DATA_DIR / hdr["TRSRC"]
        warped = warp(read_source(source), H @ m_tr, ref.shape)
        how = f"from the original {source.name} in one resampling (H x transfer matrix)"
    else:
        warped = warp(imgs[0], H, ref.shape)
        how = f"from {args.moving.name} (no TRM* transfer matrix in its header; one extra resampling)"
    print(f"aligned moving image built {how}")
    if args.save:
        for r in range(3):
            for c in range(3):
                hdr[f"H{r + 1}{c + 1}"] = (float(H[r, c]), f"homography moving->reference, row {r + 1} col {c + 1}")
        hdr["HREF"] = (args.reference.name, "reference image")
        hdr["HNINL"] = (int(inl.sum()), "RANSAC inliers")
        hdr["HNMATCH"] = (len(inl), "matches after filter_by_distance")
        hdr["HMEDERR"] = (round(med_err, 3), "median inlier reprojection error [px]")
        hdr["HISTORY"] = "features.py: warped onto the reference grid with the pipeline"
        hdr["HISTORY"] = "ORB/FLANN/RANSAC homography (bilinear); uncovered pixels 0;"
        hdr["HISTORY"] = f"built {how}."[:72]
        save_image(warped, hdr, args.outdir / f"{args.moving.stem}_aligned", f"{names[0]}, warped with H")
        ref_hdr = fits.getheader(args.reference, 0)
        ref_hdr["HISTORY"] = "features.py: unchanged copy, reference of the homography alignment."
        save_image(ref, ref_hdr, args.outdir / f"{args.reference.stem}_aligned", names[1])
    rgb = np.zeros((*ref.shape, 3))
    rgb[..., 0], rgb[..., 1] = stretch(ref), stretch(warped)
    fig, axes = plt.subplots(1, 3, figsize=(20, 7))
    for ax, img, title in zip(axes, (stretch(warped), stretch(ref), rgb),
                              ("moving warped with H", names[1], "reference (red) + warped (green), both = yellow")):
        ax.imshow(img, cmap="gray", origin="lower", interpolation="nearest")
        ax.set(title=title, xlabel="x [px]", ylabel="y [px]")
    fig.suptitle(f"05 RANSAC homography: {inl.sum()}/{len(inl)} inliers")
    output(fig, "05_alignment.png")

    if args.show:
        plt.show()


if __name__ == "__main__":
    main()
