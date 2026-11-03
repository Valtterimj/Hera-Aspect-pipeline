from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence, Literal, Optional

import numpy as np
from astropy.io.fits import Header

Level = Literal["0A", "1A", "1B", "1C","2", "2B", "3A", "3B", "3C"]
Channel = Literal["Vis", "NIR1", "NIR2", "SWIR"]
IssueLevel = Literal["info", "warning", "error"]

@dataclass(frozen=False)
class RunConfig:
    input_dir: Path
    output_dir: Path
    spice_dir: Path | None
    overwrite: bool

@dataclass(frozen=True)
class CalibConfig:
    calibration_dir: Path
    solar_ssi: Path
    drop_frame: bool

@dataclass(frozen=True)
class DataConfig:
    instrume: str
    origin: str
    swcreate: str
    missphas: str
    acq_id: str
    major_version: str
    minor_version: str
    solar_d: str | None

@dataclass(frozen=True)
class PipelineConfig:
    levels: Sequence[Level]
    channels: Sequence[Channel]

@dataclass(frozen=True)
class AnalysisConfig:
    instrument: str
    data_filtering: bool
    save_filtered: bool
    models: list[str]
    z_thresh: int
    z_factor: int
    init_guess: list[tuple[float, float, float]]

@dataclass(frozen=True)
# The main config class
class Config:
    run: RunConfig
    calib: CalibConfig
    data: DataConfig
    pipeline: PipelineConfig
    analysis: AnalysisConfig
    config_path: Path

@dataclass(frozen=True)
# The main pds4 config class
class pds4_config:
    input: Path
    templates_dir: Path
    output: Path
    products: list[Level]
    channels: list[Channel]
    major_version: str = "1"
    minor_version: str = "0"
    config_path: Optional[Path] = None

@dataclass(frozen=True)
class InputLayout:
    # Validated input directory layout.
    root: Path
    meta_dir: Path
    telemetry_json: Path
    config_json: Path
    acquisition_dir: Path

@dataclass(frozen=True)
class HeaderEntry:
    value: str
    comment: Optional[str] = None

@dataclass(frozen=False)
class AcqMetadata:
    INSTRUME: HeaderEntry
    ORIGIN: HeaderEntry
    MISSPHAS: HeaderEntry
    ACQ_ID: HeaderEntry
    FILENAME: HeaderEntry
    ORIGFILE: HeaderEntry
    DATE: HeaderEntry
    DATE_OBS: HeaderEntry
    SWCREATE: HeaderEntry
    PROCLEVL: HeaderEntry
    COV_TARG: HeaderEntry
    VIS_AVG: HeaderEntry

@dataclass(frozen=False)
class SpiceMetadata:
    SPICE_MK: HeaderEntry
    SPICEVER: HeaderEntry
    SPICECLK: HeaderEntry
    SUN_POSY: HeaderEntry
    SUN_POSX: HeaderEntry
    SUN_POSZ: HeaderEntry
    SOLAR_D: HeaderEntry
    EARTPOSX: HeaderEntry
    EARTPOSY: HeaderEntry
    EARTPOSZ: HeaderEntry
    EARTH_D: HeaderEntry
    TARGET: HeaderEntry
    TRG_POSX: HeaderEntry
    TRG_POSY: HeaderEntry
    TRG_POSZ: HeaderEntry
    TRG_DIST: HeaderEntry
    SC_QUATW: HeaderEntry
    SC_QUATX: HeaderEntry
    SC_QUATY: HeaderEntry
    SC_QUATZ: HeaderEntry
    CAM_RA: HeaderEntry
    CAM_DEC: HeaderEntry
    CAM_NAZ: HeaderEntry
    SOL_ELNG: HeaderEntry

@dataclass(frozen=False)
class InstrumentMetadata:
    CHANNELS: HeaderEntry
    Vis_CCDTEMP: HeaderEntry
    Vis_FPI_TEMP1: HeaderEntry
    Vis_FPI_TEMP2: HeaderEntry
    NIR1_CCDTEMP: HeaderEntry
    NIR1_FPI_TEMP1: HeaderEntry
    NIR1_FPI_TEMP2: HeaderEntry
    NIR2_CCDTEMP: HeaderEntry
    NIR2_FPI_TEMP1: HeaderEntry
    NIR2_FPI_TEMP2: HeaderEntry
    SWIR_CCDTEMP: HeaderEntry
    SWIR_FPI_TEMP1: HeaderEntry
    SWIR_FPI_TEMP2: HeaderEntry

@dataclass(frozen=True)
class InstrumentSpecificMetadata:
    fields: dict[str, HeaderEntry] = field(default_factory=dict)

@dataclass(frozen=True)
# Main metadata class
class Metadata:
    acq: AcqMetadata
    spice: SpiceMetadata
    instrument: InstrumentMetadata
    instrument_specific: InstrumentSpecificMetadata

@dataclass()
# <instrument_acronym>_<processing_level>_[type]_[subunit]_<descriptor>__<major_version>_<minor_version>.<extension>
# each variable as class
class Filename:
    instrument_acronym: str
    processing_level: str
    type: str
    subunit: str
    descriptor: str
    major_version: str
    minor_version: str
    extension: str

@dataclass(frozen=True, slots=True)
class Issue:
    level: IssueLevel
    message: str
    source: str

@dataclass
class BadRegion:
    """
    One bad-pixel region specification from the BADPIXELS TXT file

    type: str
        Region type code:
        'P' = single pixel,
        'H' = horizontal cluster,
        'V' = vertical cluster,
        'R' = rectangular region
    col: int | None
        Column (x) start coordinate in pixels. None if file contains '-'
    row: int | None
        Row (y) start coordinate in pixels. None if file contains '-'
    size_x: int
        width of the region in pixels
    size_y: int
        height of the region in pixels
    """
    type: str
    col: int | None
    row: int | None
    size_x: int
    size_y: int

@dataclass
class Level2Data:
    """Contents of a level 2B file needed by level 3.

    Attributes:
        path: Path to the 2B FITS file.
        header: Primary header of the 2B file.
        cube: Vis/NIR reflectance cube (bands, y, x).
        swir: SWIR reflectance spectrum (one value per wavelength), or None if the file has no SWIR.
        wavelengths: Wavelengths in nm for each channel in the file.
    """
    path: Path
    header: Header
    cube: np.ndarray
    swir: np.ndarray | None
    wavelengths: dict[str, list[int]]

@dataclass
class PreparedSpectra:
    """Per-pixel spectra of the asteroid used by the level 3 analysis.

    Attributes:
        coords: (y, x) pixel coordinates of the spectra, shape (n_pixels, 2).
        excluded_coords: (y, x) coordinates of asteroid pixels left out of the analysis, shape (n_excluded, 2).
        spectra: Reflectance spectra, shape (n_pixels, n_bands).
        wavelengths: Wavelength in nm of each band, ascending, shape (n_bands,).
        channel_bands: Band range of each channel in spectra and wavelengths.
        frames: Frame index ('000', '001', ...) of each band of a channel, in band order.
        image_shape: (height, width) of the original image in pixels.
    """
    coords: np.ndarray
    excluded_coords: np.ndarray
    spectra: np.ndarray
    wavelengths: np.ndarray
    channel_bands: dict[str, slice]
    frames: dict[str, list[str]]
    image_shape: tuple[int, int]