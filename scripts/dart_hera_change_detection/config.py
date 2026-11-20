"""
Configurations for DART Hera image comparison

How to run
==========

1. Define (this file)
---------------------
  HERA_SPICE  Hera SPICE "kernels" directory (contains mk/ with hera_ops*.tm).
              The ops meta-kernel matching the AFC header SPICE_MK is used;
              plan meta-kernels never are. Kernel paths inside the .tm files
              must point to this directory.
  DART_SPICE  DART SPICE root directory (contains mk/).
  DART_MK     DART meta-kernel file name in <DART_SPICE>/mk/.
  AFC_FITS, DRACO_FITS   input images
  OUTPUT_DIR, FEATURES_DIR   where the results are written
  DRACO_* / AFC_*   flip, scale and rotation for image_transfer.py.
              DRACO_SCALE must be set by hand to "scale_ratio" from
              spice_geometry.json after running step a).
  CROP_SIZE, MASK_REGION, FILL   crop settings for image_transfer.py

2. Order and commands (from the repository root)
------------------------------------------------
  a) spice_geometry.py: m/px of each image from SPICE (range x IFOV) and the
     DRACO/AFC scale ratio -> GEOMETRY_JSON ("scale_ratio").
       uv run python scripts/dart_hera_change_detection/spice_geometry.py

     Copy "scale_ratio" into DRACO_SCALE above (it is not read automatically).

  b) image_transfer.py: flip/scale/rotate/crop both images to a common scale
     and orientation -> AFC_TRANSFER, DRACO_TRANSFER (.fits and .png).
       uv run python scripts/dart_hera_change_detection/image_transfer.py                 # mask figures + save
       uv run python scripts/dart_hera_change_detection/image_transfer.py --no-visualise  # save only
       options: --size N, --region largest|all (override CROP_SIZE, MASK_REGION)

  c) features.py: pipeline ORB + FLANN matching and RANSAC homography on the
     transferred images (needs b) -> FEATURES_DIR figures 01-05 and the
     aligned pair <stem>_transfer_aligned.fits/.png.
       uv run python scripts/dart_hera_change_detection/features.py --show         # figures only
       uv run python scripts/dart_hera_change_detection/features.py --save         # save figures + aligned images
       uv run python scripts/dart_hera_change_detection/features.py --show --save  # both
"""


from pathlib import Path

# --- SPICE ---------------------------------------------------------------
HERA_SPICE = "/Users/valtterimj/Downloads/Work/Hera/hera_spice/kernels"
DART_SPICE = "/Users/valtterimj/Downloads/Work/Hera/dart_spice"
DART_MK = "dart_v04.tm"

# --- Input images and output directories ----------------------------------
DATA_DIR = Path(__file__).resolve().parents[2] / "hera_inst/asteroid/draco_afc"
AFC_FITS = DATA_DIR / "afc_par_sc_afc1_1_065133199__1_.fits"
DRACO_FITS = DATA_DIR / "dart_0401929888_05627_02_iof.fits"
OUTPUT_DIR = DATA_DIR / "output"
FEATURES_DIR = OUTPUT_DIR / "features"
GEOMETRY_JSON = OUTPUT_DIR / "spice_geometry.json"
# Written by image_transfer.py, read by features.py (names follow the inputs):
AFC_TRANSFER = OUTPUT_DIR / f"{AFC_FITS.stem}_transfer.fits"
DRACO_TRANSFER = OUTPUT_DIR / f"{DRACO_FITS.stem}_transfer.fits"

# --- image_transfer.py: applied in the order flip -> scale -> rotate -> crop --
# Flip: "x" (left<->right), "y" (top<->bottom) or None.
# Rotation: degrees counter-clockwise as displayed with origin='lower'.
# Scale: SET MANUALLY from spice_geometry.py: DRACO_SCALE = "scale_ratio" in
# output/spice_geometry.json (DRACO m/px / AFC m/px); AFC is the reference (1.0).
DRACO_FLIP = "x"
DRACO_SCALE = 0.86575
DRACO_ROTATION = -37.44  # deg
AFC_FLIP = None
AFC_SCALE = 1.0
AFC_ROTATION = -90.0  # deg
TARGET_M_PER_PX = 5.730  # AFC m/px from spice_geometry.json; used in PNG titles only
CROP_SIZE = 200  # px
MASK_REGION = "largest"  # "largest" (Didymos only) or "all" (whole asteroid_mask)
FILL = 0.0  # value of empty areas created by rotate() and crop()