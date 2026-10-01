# Hera ASPECT Pipeline

## Overview

This repository contains the ground data processing pipeline for the ASPECT instrument's four channels — **Vis** (visible imager), **NIR1** and **NIR2** (near-infrared imagers), and **SWIR** (short-wave-infrared spectrometer) — aboard ESA's [Hera](https://www.esa.int/Space_Safety/Hera) mission. The pipeline processes raw binary instrument data through a sequence of calibration levels (0A → 1A → 1B → 1C), then merges the per-channel products into a combined hyperspectral data cube (level 2).

The pipeline is operated from the command line via the `aspect` CLI.

> **Current implementation status:** Levels 0A through 2 are implemented and runnable. Level 3 (spectral analysis) and PDS4 label generation are **not yet implemented** — see [Not Yet Implemented](#not-yet-implemented) for details.

---

## Table of Contents

1. [Requirements](#requirements)
2. [Installation](#installation)
   - [Using uv (recommended)](#using-uv-recommended)
   - [Using pip](#using-pip)
   - [Compile the JPEG 2000 decompressor](#compile-the-jpeg-2000-decompressor)
3. [Repository Structure](#repository-structure)
4. [Input Data Format](#input-data-format)
5. [Calibration Files](#calibration-files)
6. [Configuration](#configuration)
7. [Running the Pipeline](#running-the-pipeline)
8. [Processing Levels](#processing-levels)
9. [Outputs](#outputs)
10. [Not Yet Implemented](#not-yet-implemented)
11. [Contact](#contact)

---

## Requirements

| Requirement | Notes |
|---|---|
| Python 3.12+ | |
| C compiler (`clang` or `gcc`) | Required only if raw files are JPEG 2000 compressed (`.bin.jp2`) |
| [Jasper library](https://jasper-software.github.io/jasper-manual/latest/html/index.html) | Required only if raw files are JPEG 2000 compressed |

Python dependencies are managed via `pyproject.toml` and include: `astropy`, `numpy`, `scipy`, `matplotlib`, `pandas`, `opencv-python`, `spiceypy`, `pyyaml`, `xarray`.

---

## Installation

### Using uv (recommended)

[uv](https://github.com/astral-sh/uv) is a fast Python package manager. It reads `uv.lock` to reproduce the exact dependency environment. Works the same way on macOS, Linux and Windows.

```bash
# 1. Clone the repository
git clone https://github.com/Valtterimj/Hera-Aspect-pipeline.git
cd Hera-Aspect-pipeline

# 2. Create the virtual environment and install all dependencies
uv venv
uv sync
```

Activate the environment (needed if you want to call `aspect` directly instead of via `uv run`):

```bash
# macOS / Linux
source .venv/bin/activate

# Windows (Command Prompt)
.venv\Scripts\activate.bat

# Windows (PowerShell)
.venv\Scripts\Activate.ps1
```

`uv sync` installs the package itself (including the `aspect` CLI entry point) and all locked dependencies in one step. Without activating, you can still run commands via `uv run aspect ...`.

### Using pip

This project uses a **`src` layout** — the package lives under `src/aspect_pipeline/` rather than the project root. `pyproject.toml` tells the build backend (hatchling) where to find it:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/aspect_pipeline"]
```

Without installing the package properly, Python will **not** be able to resolve the `aspect_pipeline` imports and the pipeline will fail with `ModuleNotFoundError`.

The correct way to install with pip is **editable mode** (`-e`), which registers the `src/` directory on the Python path:

```bash
# 1. Clone the repository
git clone https://github.com/Valtterimj/Hera-Aspect-pipeline.git
cd Hera-Aspect-pipeline

# 2. Create the virtual environment
python -m venv .venv

# 3. Activate it
#   macOS / Linux:
source .venv/bin/activate
#   Windows (Command Prompt):
.venv\Scripts\activate.bat
#   Windows (PowerShell):
.venv\Scripts\Activate.ps1

# 4. Install the package and all dependencies in editable mode
pip install -e .
```

The `-e .` flag instructs pip to use `pyproject.toml` in the current directory. Hatchling uses this to correctly resolve `src/aspect_pipeline` as the package root, and the `aspect` CLI entry point will be registered in your environment.

> **Do not** attempt `pip install aspect_pipeline` or manually add `src/` to `PYTHONPATH` — use `pip install -e .` from the project root.

### Compile the JPEG 2000 decompressor

Raw acquisition files may be JPEG 2000 compressed (`.bin.jp2`). In that case the pipeline uses a compiled C subprocess to decompress them on the fly before reading them as raw frames. If your input files are uncompressed `.bin` files this step is not needed.

First, install the Jasper library if not already present:

- macOS: `brew install jasper`
- Ubuntu/Debian: `sudo apt-get install libjasper-dev`
- Windows: see the [Jasper documentation](https://jasper-software.github.io/jasper-manual/latest/html/index.html) for build instructions, or build/run the pipeline under WSL.
- See the [Jasper documentation](https://jasper-software.github.io/jasper-manual/latest/html/index.html) for other platforms.

Then compile from the project root:

```bash
cd src/aspect_pipeline/levels/level_0
cc decompress.c -o decompress $(pkg-config --cflags --libs jasper)
```

The resulting `decompress` binary must remain in that directory (`src/aspect_pipeline/levels/level_0/`) — the pipeline locates it there at runtime, relative to the installed package location.

---

## Repository Structure

```text
Hera-Aspect-pipeline/
│
├── pyproject.toml              # Project metadata, dependencies, build config
├── uv.lock                     # Locked dependency versions (uv)
├── README.md
│
├── configs/
│   └── example.yaml            # Annotated example config — copy and edit this
│
├── calibration/                # Calibration reference files
│   ├── DARKS/                  # Dark background frames (AS<id>_DARKS.fits)
│   ├── FLATS/                  # Flat field frames (AS<id>_FLAT_HIGH/LOW.fits)
│   ├── BADPIXELS/               # Bad pixel lists (AS<id>_BADPIXELS.txt)
│   ├── RADIANCE/                # Radiance conversion coefficients (AS<id>_RADIANCE_HIGH/LOW.txt)
│   └── SOLAR/                  # Solar spectral irradiance data (.csv)
│
├── src/
│   └── aspect_pipeline/
│       ├── cli.py               # CLI entry point (`aspect` command)
│       ├── main.py              # `aspect test` debug command
│       ├── config.py            # YAML config loading and validation
│       ├── orchestrator.py      # Top-level pipeline orchestrator (`aspect run`)
│       ├── levels/
│       │   ├── level_0/         # Level 0: raw binary → FITS
│       │   │   ├── run.py
│       │   │   ├── build_fits.py
│       │   │   ├── metadata.py
│       │   │   ├── spice.py
│       │   │   ├── decompress.c        # JP2 decompressor source
│       │   │   └── decompress          # Compiled binary (after build step)
│       │   ├── level_1/         # Level 1: header + radiometric calibration
│       │   │   ├── run.py
│       │   │   ├── calibrate_header.py # 1A
│       │   │   ├── level_1b.py         # 1B (+ optional 1A-extra)
│       │   │   ├── extract_cds.py
│       │   │   ├── dark_background.py
│       │   │   ├── flat_field.py
│       │   │   ├── bad_pixels.py
│       │   │   ├── radiometric.py
│       │   │   └── reflectance.py      # 1C
│       │   ├── level_2/         # Level 2: channel alignment and merging
│       │   │   ├── run.py
│       │   │   ├── merge_channels.py
│       │   │   └── transformation_matrix.py
│       │   └── level_3/         # Not yet implemented (empty)
│       └── utils/                # Shared classes, validation, error types, visualisation
│
└── outputs/                      # Default location for pipeline outputs (gitignored)
```

---

## Input Data Format

The pipeline expects input data in a specific directory layout. The path to this directory is set via `run.input_dir` in the configuration file.

```text
<input_dir>/
│
├── meta/
│   ├── telemetry.json      # Instrument telemetry (temperatures, clocks, modes)
│   └── config.json         # Instrument configuration for the acquisition
│
└── acq_000/                # Acquisition directory (must match 'acq_<digits>*')
    ├── dc_0_exp_000.bin    # Vis raw frame (channel id 0)
    ├── dc_1_exp_000.bin    # NIR1 raw frame (channel id 1)
    ├── dc_2_exp_000.bin    # NIR2 raw frame (channel id 2)
    ├── dc_3_exp_000.bin    # SWIR raw sample (channel id 3)
    └── ...
```

**Key points:**

- The `meta/` subdirectory and both JSON files are **required**. The pipeline raises a `ValidationError` if they are missing.
- The acquisition folder must match the pattern `acq_<digits>*`. If multiple matching folders exist, the pipeline uses the lexicographically first one.
- Channel IDs in filenames: `dc_0_*` = Vis, `dc_1_*` = NIR1, `dc_2_*` = NIR2, `dc_3_*` = SWIR.
- **Vis** frames: raw 16-bit unsigned little-endian binary, 1024×1024 pixels.
- **NIR1/NIR2** frames: raw 16-bit unsigned little-endian binary, 518×648 pixels (512×640 if `data.missphas` is set to `"simulated"`).
- **SWIR** frames: exactly 4 bytes each, big-endian unsigned 32-bit integer — one scalar sample per file, not an image.
- JPEG 2000 compressed files (`.bin.jp2`) are supported for the imaging channels if the `decompress` binary has been compiled (see [Compile the JPEG 2000 decompressor](#compile-the-jpeg-2000-decompressor)).

---

## Calibration Files

All calibration files must reside inside the directory specified by `calibration.calibration_dir`, under fixed subdirectory names — individual calibration file paths are **not configurable per-file**, only the parent `calibration_dir` is.

```text
<calibration_dir>/
├── DARKS/
│   └── AS<id>_DARKS.fits            # Dark background frame (PrimaryHDU)
├── FLATS/
│   ├── AS<id>_FLAT_HIGH.fits        # Flat field, high gain/exposure
│   └── AS<id>_FLAT_LOW.fits         # Flat field, low gain/exposure
├── BADPIXELS/
│   └── AS<id>_BADPIXELS.txt         # Bad pixel region list
└── RADIANCE/
    ├── AS<id>_RADIANCE_HIGH.txt     # Radiance conversion coefficients, high
    └── AS<id>_RADIANCE_LOW.txt      # Radiance conversion coefficients, low
```

Where `<id>` is the channel ID: `0` = Vis, `1` = NIR1, `2` = NIR2, `3` = SWIR. The `_HIGH`/`_LOW` flat and radiance files are selected automatically at runtime based on the acquisition's `{channel}_ORDER` header value.

The solar spectral irradiance file is configured separately via `calibration.solar_ssi` (see [Configuration](#configuration)) and is not required to live under `calibration_dir`, though by convention it's kept in `calibration/SOLAR/`.

**Bad pixel file format** — each line specifies one bad region:

```
<type> <col> <row> <size_x> <size_y>
```

Where `type` is one of:

| Code | Region type |
|---|---|
| `P` | Single pixel |
| `H` | Horizontal cluster |
| `V` | Vertical cluster |
| `R` | Rectangular region |

Use `-` for coordinates not applicable to the region type.

---

## Configuration

The pipeline is controlled by a YAML configuration file. By default, when run from the project root, the pipeline searches for `configs/example.yaml`. A custom path can be passed with `--config`.

Copy the example as a starting point and edit it for your run:

```bash
cp configs/example.yaml configs/my_run.yaml
```

### Full configuration reference

```yaml
# ── Run-time settings ─────────────────────────────────────────────────────────
run:
  # (Required) Path to input data. Relative to this config file, or absolute.
  input_dir: "../data/test"

  # (Optional) Root output directory. If empty, outputs/<missphas>/ is created
  # relative to the current working directory (not relative to the config file).
  output_dir: "../outputs/test"

  # (Optional) SPICE meta-kernel path. Should be absolute. If empty, SPICE
  # header fields are populated with 'UNK'.
  spice_dir: ""

  # Whether to overwrite existing output files.
  overwrite: true

# ── Calibration files ─────────────────────────────────────────────────────────
calibration:
  # (Required for level 1) Directory containing DARKS/, FLATS/, BADPIXELS/,
  # RADIANCE/ subdirectories (see Calibration Files). Relative to this config
  # file, or absolute.
  calibration_dir: "../calibration/TEST"

  # (Required for level 1C) Path to the solar spectral irradiance CSV.
  # Relative to this config file, or absolute.
  solar_ssi: "../calibration/SOLAR/ssi_yearly_avg_e2024_c20250221.csv"

  # Whether to drop the first frame of each channel's data cube (and its
  # corresponding header entries) during level 1A.
  drop_first_frame: true

# ── Observation metadata ──────────────────────────────────────────────────────
data:
  instrume: "ASPECT"                  # Camera/instrument ID
  origin:   "ESA-HERA"                # Mission
  swcreate: "ASPECTCAL"               # Software identification string
  missphas: "test"                    # Mission phase ID (used in output dir name)
  observ:   "pipeline-testing"        # Observation ID
  object:   "dark"                    # Human-readable target name
  target:   "DARK"                    # SPICE target body name

  # (Optional) Manually set the solar distance in AU for reflectance
  # calibration (level 1C). Overrides the SPICE-derived value when set.
  # Use a numeric string e.g. "1" or "1.2", or leave empty to use SPICE.
  solar_d: ""

# ── Pipeline control ────────────────────────────────────────────────────────
pipeline:
  # Processing levels to execute.
  # "0" is shorthand for ["0A"]; "1" is shorthand for ["1A", "1B", "1C"].
  # Allowed values: "0", "1", "1A", "1B", "1C", "2"
  levels: ["0", "1", "2"]

  # Instrument channels to process.
  # Allowed values: "Vis", "NIR1", "NIR2", "SWIR"
  channels: ["Vis"]
```

### Notes on paths

All path fields (`input_dir`, `output_dir`, `spice_dir`, `calibration_dir`, `solar_ssi`) may be:

- **Absolute** paths (recommended for `spice_dir`)
- **Relative** to the directory containing the config file — **except** `run.output_dir` when left empty, which then falls back to `outputs/<missphas>/` relative to the current working directory.

---

## Running the Pipeline

### Default execution

Run from the project root with `configs/example.yaml` present (or copy it to `configs/example.yaml` if you started from elsewhere):

```bash
aspect run
```

### Custom configuration file

```bash
aspect run --config path/to/my_run.yaml
```

The path may be absolute or relative to the current working directory.

### Visualise a FITS or raw binary file

View a FITS product (prints the header, then shows the data — an interactive frame browser for 3D cubes, a static image for 2D, min/max/mean for 1D):

```bash
aspect view --fits path/to/file.fits
```

View a raw, headerless `.bin` frame (filename must follow the `dc_<id>_exp_<n>.bin` convention so the channel and frame shape can be determined; not supported for SWIR, which has no 2D shape):

```bash
aspect view --bin path/to/dc_0_exp_000.bin
```

### Generate a synthetic test dataset

Writes synthetic raw per-channel `.bin` frames and matching `DARKS`/`FLATS` calibration FITS files for Vis, NIR1 and NIR2, useful for exercising individual pipeline components without real instrument data:

```bash
aspect make-test-set --input path/to/raw_output_dir --calibration path/to/calibration_output_dir
```

> Note: this generates raw frames and calibration files only — it does not create the `meta/telemetry.json`, `meta/config.json`, or `acq_<digits>*/` wrapper directory that `aspect run`'s level 0 stage requires as input. It's a building block for testing calibration steps, not a ready-to-run acquisition directory.

### Config smoke test

Loads the config (default search path, or none passed) and prints the parsed `run`, `calib`, `data` and `pipeline` sections — useful for checking a config file parses as expected:

```bash
aspect test
```

---

## Processing Levels

The `levels` list in the configuration controls which levels are executed. Levels are processed in order within a single `aspect run` invocation; each level takes the output of the previous one as input automatically.

| Level | Config value | Input file | Description |
|---|---|---|---|
| **0A** | `"0"` | Raw binary + JSON metadata | Reads raw binary frames, queries SPICE for geometry, assembles a FITS file with a fully populated header. Produces one `AS<id>_..._0A.fits` per channel. |
| **1A** | `"1"` (or `"1A"`) | `*_0A.fits` | Populates detector/FPI temperature calibration and per-frame wavelength/exposure header fields. Optionally drops the first frame (`calibration.drop_first_frame`). Produces `*_1A.fits`. |
| **1B** | `"1"` (or `"1B"`) | `*_1A.fits` | Full radiometric calibration: CDS pixel extraction → dark subtraction → flat-field correction → bad pixel replacement → radiance conversion. Produces `*_1B.fits` in physical units. Optionally also writes a `*_1A-extra.fits` snapshot before radiometric conversion. |
| **1C** | `"1"` (or `"1C"`) | `*_1B.fits` | Converts radiance to reflectance using solar spectral irradiance and heliocentric distance (from SPICE, or `data.solar_d` override). Produces `*_1C.fits`. |
| **2** | `"2"` | Per-channel `*_1C.fits` | Aligns Vis onto the NIR grid (feature matching + RANSAC transform) and merges all requested channels into a single hyperspectral data cube with a combined header. Produces one `ASP..._2B.fits` file. |

**Shorthand:** `"1"` in the levels list runs all of 1A, 1B and 1C in sequence; `"0"` runs 0A.

### Chaining runs

If you run level 0 and level 1 in separate invocations, set `run.input_dir` in the second config to point to the output directory of the first run (the directory containing `*_0A.fits`). The pipeline resolves the correct input file by searching for a FITS file matching the expected level suffix and channel prefix.

---

## Outputs

By default the pipeline writes per-channel outputs to:

```
outputs/<missphas>/
```

relative to the current working directory. This can be overridden with `run.output_dir` in the config.

### Output file naming

Per-channel products (levels 0A–1C):

```
AS<channel_id>_<BASE32_SC_CLOCK>_<YYMMDDTHHMMSS>_<LEVEL>.fits
```

For example:

```
AS0_0ABC12_260115T123456_0A.fits
AS0_0ABC12_260115T123456_1A.fits
AS0_0ABC12_260115T123456_1B.fits
AS0_0ABC12_260115T123456_1C.fits
```

The spacecraft clock is encoded as a 6-character base-32 string derived from the SC clock counter, producing a compact, monotonically increasing image identifier. `<channel_id>` is `0`=Vis, `1`=NIR1, `2`=NIR2, `3`=SWIR.

The merged level 2 product uses an `ASP` prefix instead, e.g. `ASP0ABC12_260115T123456_2B.fits`.

### FITS file structure

Each per-channel output file contains a `PrimaryHDU` with the image data array (frames × rows × columns for the imaging channels; a 1-D array for SWIR) and a populated header containing three groups of keywords:

**Acquisition metadata**

| Keyword | Description |
|---|---|
| `INSTRUME` | Instrument ID |
| `ORIGIN` | Mission |
| `MISSPHAS` | Mission phase ID |
| `OSERV_ID` | Observation ID |
| `FILENAME` | Output filename |
| `ORIGFILE` | Source raw filename |
| `SWCREATE` | Processing software ID |
| `DATE` | File creation timestamp (UTC) |
| `PROCLEVL` | Processing level of this file |
| `DATE_OBS` | Observation timestamp (UTC) |
| `SC_CLK` | Spacecraft clock at acquisition |
| `OBJECT` | Target name |

**SPICE geometry** (populated when `spice_dir` is provided; otherwise `UNK`)

| Keyword | Description |
|---|---|
| `SPICE_MK` | SPICE meta-kernel used |
| `SPICEVER` | SPICE dataset version |
| `SUN_POSX/Y/Z` | Sun position vector (km) |
| `SOLAR_D` | Heliocentric distance (AU) |
| `EARTPOSX/Y/Z` | Earth position vector (km) |
| `EARTH_D` | Geocentric distance (AU) |
| `TARGET` | Observation target |
| `TRG_POSX/Y/Z` | Target position vector (km) |
| `TRG_DIST` | Distance to target (km) |
| `SC_QUATW/X/Y/Z` | Spacecraft attitude quaternion |
| `CAM_RA/DEC` | Camera boresight (RA/Dec, deg) |
| `CAM_NAZ` | Camera nadir azimuth (deg) |
| `SOL_ELNG` | Solar elongation (deg) |

**Instrument-specific metadata** (stored as `HIERARCH` keywords)

| Keyword | Description |
|---|---|
| `CHANNELS` | Active channel(s) |
| `<CH>_CCDTEMP` | Detector temperature, for each of Vis/NIR1/NIR2/SWIR |
| `<CH>_FPI_TEMP1/2` | Fabry-Pérot etalon temperatures, for each channel |
| `<CH>_FRAMES` | Comma-separated list of frame labels present in the data cube |
| `<CH>_TASK_NUMBER` | Number of acquisition tasks |
| `<CH>_TASK_<N>` | Setpoints and exposure DN from the task file, per frame |
| `<CH>_ORDER` | Acquisition order ('LOW' / 'HIGH'), added at level 1A |
| `<CH>_WL_<N>` | Tuned wavelength (nm) for frame N, added at level 1A |
| `<CH>_EXP_<N>` | Exposure in seconds for frame N, added at level 1A |

The level 2 merged product's header combines these across all present channels, with the lowest-wavelength channel (Vis, else NIR1, else NIR2, else SWIR) as the base and the other channels' instrument-specific keywords appended.

---

## PDS4 Label Generation

The pipeline can generate [PDS4](https://pds.nasa.gov/datastandards/pds4/)-compliant XML product labels for any FITS file produced by the processing pipeline. Each label is generated from a shared Jinja2 template ([`pds4_templates/ASPECT_template.xml.j2`](pds4_templates/ASPECT_template.xml.j2)) that is filled in with metadata read directly from the FITS headers and file structure. The correct array type (`Array_3D_Spectrum` for Vis, NIR1, NIR2, `Array_1D_Spectrum` for SWIR), element data type, and axis dimensions are determined automatically from the FITS file content.

### Running PDS4 generation

Configure the `pds4:` section in your config file (see [Configuration](#configuration)), then run:

```bash
aspect pds4 --config path/to/pipeline.yaml
```

The path may be absolute or relative to the current working directory. If `--config` is omitted the pipeline looks for `configs/pipeline.yaml` in the project root.

To generate labels for a single FITS file, set `pds4.input` to the file path directly and omit `pds4.products`. To process a whole output directory, set `pds4.input` to the directory and list the desired levels in `pds4.products`.

### Output layout

For each processed FITS file a subdirectory is created containing the XML label and a copy of the FITS file:

```text
<output>/pds4/
└── <STEM>/
    ├── ASPECT_<STEM>.xml    # PDS4 label
    └── <STEM>.fits             # Copy of the FITS data product
```

Where `<STEM>` is the filename stem of the source FITS file (e.g. `NIR1_000000_200101T015948_1A`). If `pds4.output` is empty the `pds4/` directory is created inside the directory given by `pds4.input`.

---

## Contact

Maintained by **Valtteri Pitkänen**
GitHub: https://github.com/Valtterimj
Email: valtteri.m.pitkanen@aalto.fi | valtterimj@gmail.com
