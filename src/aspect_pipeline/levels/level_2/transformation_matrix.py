import cv2
import logging
import numpy as np

from aspect_pipeline.utils.utilities import normalize_to_8bit

logger = logging.getLogger(__name__)

def laplacian(img: np.ndarray) -> np.ndarray:
    """
    Compute the Laplacian edge image of a frame after 8-bit normalisation and Gaussian blur.

    Args:
        img: 2D image frame.

    Returns:
        8-bit Laplacian edge image (unitless, 0-255), same shape as img.

    Raises:
        ValueError: if img is None.
    """

    # Check if the image was loaded successfully
    if img is None:
        logger.error("Image not found or unable to open")
        raise ValueError("Image not found or unable to open")

    # Normalize the image to 8 bit integers
    img = normalize_to_8bit(img)

    # Apply gaussian blur
    img = cv2.GaussianBlur(img, (3, 3), sigmaX=0, sigmaY=0)

    # Apply Laplacian operator
    laplacian = cv2.Laplacian(img, cv2.CV_8U, ksize=3) 

    return laplacian

def filter_by_orientation(matches, keypoints1, keypoints2, threshold=10) -> list[cv2.DMatch]:
    filtered_matches = []
    for m in matches:
        angle1 = keypoints1[m.queryIdx].angle
        angle2 = keypoints2[m.trainIdx].angle
        angle_diff = abs(angle1 - angle2)
        if angle_diff < threshold or angle_diff > (360 - threshold):
            filtered_matches.append(m)
    return filtered_matches

def filter_by_distance(matches: list[list[cv2.DMatch]]) -> list[cv2.DMatch]:
    ratio_thresh = 0.85  # Adjustable
    good_matches = []
    for m in matches:
        if len(m) == 2:
            match1, match2 = m
            if match1.distance < ratio_thresh * match2.distance:
                good_matches.append(match1)
        elif len(m) == 1:
            match1 = m[0]
            good_matches.append(match1)
    distance_thresh = 60  # Adjustable
    good_matches = [m for m in good_matches if m.distance < distance_thresh]
    return good_matches

def _show_images(title: str, images: list[tuple[str, np.ndarray]]) -> None:
    """Show images side by side in a blocking matplotlib window (debug only)."""
    import matplotlib.pyplot as plt  # imported lazily so the pipeline never loads matplotlib

    fig, axes = plt.subplots(1, len(images), figsize=(6 * len(images), 6))
    axes = np.atleast_1d(axes)
    for ax, (name, img) in zip(axes, images):
        if img.ndim == 2:
            ax.imshow(img, cmap="gray")
        else:
            ax.imshow(img)
        ax.set_title(name)
        ax.axis("off")
    fig.suptitle(title)
    fig.tight_layout()
    plt.show()


def _print_image_stats(name: str, img: np.ndarray) -> None:
    """Print shape, dtype and min/max/mean of an image (debug only)."""
    print(f"{name}: shape={img.shape} dtype={img.dtype} "
          f"min={img.min()} max={img.max()} mean={img.mean():.3f}")


def estimate_matrix(vis: np.ndarray, nir: np.ndarray, filter: bool = True, verbose: bool = False) -> np.ndarray:
    """
    Estimate the homography that maps Vis pixel coordinates onto NIR pixel coordinates.

    Args:
        vis: 2D Vis frame.
        nir: 2D NIR frame.
        filter: if True, the feature matches are filtered by the ratio of the distance
            between the 1st and 2nd match suggestion (recommended). If False, the matches
            are filtered based on the angle of the keypoint calculated by ORB.
        verbose: if True, show the images after each step and print the main statistics.
            Debug use only; has no effect on the result.

    Returns:
        3x3 homography matrix (float64, unitless) mapping Vis (x, y) pixel coordinates
        to NIR (x, y) pixel coordinates, as returned by cv2.findHomography. Usable directly
        with cv2.warpPerspective to resample Vis onto the NIR grid. None if
        cv2.findHomography could not estimate a homography.
    """
    if verbose:
        print("=== estimate_matrix: input ===")
        _print_image_stats("Vis", vis)
        _print_image_stats("NIR", nir)
        _show_images("Input frames", [("Vis", vis), ("NIR", nir)])

    # Step 1: Edge detection
    edges1 = laplacian(vis)
    edges2 = laplacian(nir)

    if verbose:
        print("=== Step 1: Laplacian edges ===")
        _print_image_stats("Vis edges", edges1)
        _print_image_stats("NIR edges", edges2)
        _show_images("Step 1: Laplacian edges", [("Vis edges", edges1), ("NIR edges", edges2)])

    # Step 2: Feature detection using ORB
    orb = cv2.ORB_create(nfeatures=5000) # create ORB feature detector
    # keypoints and binary descriptions
    keypoints1, descriptors1 = orb.detectAndCompute(edges1, None)
    keypoints2, descriptors2 = orb.detectAndCompute(edges2, None)

    if verbose:
        print("=== Step 2: ORB features ===")
        print(f"Vis keypoints: {len(keypoints1)}")
        print(f"NIR keypoints: {len(keypoints2)}")
        kp_img1 = cv2.drawKeypoints(edges1, keypoints1, None, color=(0, 255, 0))
        kp_img2 = cv2.drawKeypoints(edges2, keypoints2, None, color=(0, 255, 0))
        _show_images("Step 2: ORB keypoints", [(f"Vis ({len(keypoints1)})", kp_img1),
                                               (f"NIR ({len(keypoints2)})", kp_img2)])

    # Step 3: Match features
    # FLANN
    index_params = dict(algorithm=6,  # FLANN_INDEX_LSH
                    table_number=30,  # Number of hash tables
                    key_size=20,     # Size of the key
                    multi_probe_level=2)  # Number of probes
        
    search_params = dict(checks=100)

    flann = cv2.FlannBasedMatcher(index_params, search_params) # Initialize the FLANN

    flann_matches = flann.knnMatch(descriptors1, descriptors2, k=2) # Match features

    #Filter the matches based on the distance. Other option is filter_by_orientation
    if filter: 
        matches = filter_by_distance(flann_matches)
    else:
        matches = filter_by_orientation(flann_matches)

    if verbose:
        print("=== Step 3: FLANN matches ===")
        print(f"Raw knn match sets: {len(flann_matches)}")
        print(f"Filtered matches ({'distance ratio' if filter else 'orientation'}): {len(matches)}")
        raw_img = cv2.drawMatchesKnn(edges1, keypoints1, edges2, keypoints2, flann_matches, None,
                                     flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
        filtered_img = cv2.drawMatches(edges1, keypoints1, edges2, keypoints2, matches, None,
                                       flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
        _show_images("Step 3a: FLANN matches before filtering",
                     [(f"Raw ({len(flann_matches)} sets)", raw_img)])
        _show_images("Step 3b: FLANN matches after filtering",
                     [(f"Filtered ({len(matches)})", filtered_img)])


    # Step 4: Extract location of good matches and estimate transformation matrix
    # arrays to store x and y coordinates
    points1 = np.zeros((len(matches), 2), dtype=np.float32)
    points2 = np.zeros((len(matches), 2), dtype=np.float32)

    #Extract keypoint coordinates 
    for i, match in enumerate(matches):
        points1[i, :] = keypoints1[match.queryIdx].pt
        points2[i, :] = keypoints2[match.trainIdx].pt

    # Estimate transformation matrix
    H, mask = cv2.findHomography(points1, points2, cv2.RANSAC, 10.0)

    if verbose:
        print("=== Step 4: Homography (RANSAC) ===")
        print(f"Point pairs used: {len(matches)}")
        if H is None or mask is None:
            print("findHomography failed: no homography could be estimated")
        else:
            n_inliers = int(mask.sum())
            ratio = n_inliers / len(matches) if len(matches) else 0.0
            print(f"RANSAC inliers: {n_inliers}/{len(matches)} ({ratio:.1%})")
            print(f"H =\n{H}")


    #Return the transformation matrix
    return(H)