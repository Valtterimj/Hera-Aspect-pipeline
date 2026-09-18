from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence, Literal, Optional

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
    dark: str | None
    flat: str | None
    badpixels: str | None
    radiance: str | None
    solar_ssi: str | None

@dataclass(frozen=True)
class DataConfig:
    instrume: str
    origin: str
    swcreate: str
    missphas: str
    observ: str
    object: str
    target: str
    solar_d: str | None

@dataclass(frozen=True)
class PipelineConfig:
    levels: Sequence[Level]
    channels: Sequence[Channel]

@dataclass(frozen=True)
# The main config class
class Config:
    run: RunConfig
    calib: CalibConfig
    data: DataConfig
    pipeline: PipelineConfig
    config_path: Path

@dataclass(frozen=True)
# The main pds4 config class
class pds4_config:
    input: Path
    templates_dir: Path
    output: Path
    products: list[Level]
    channels: list[Channel]

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
    OSERV_ID: HeaderEntry
    FILENAME: HeaderEntry
    ORIGFILE: HeaderEntry
    SWCREATE: HeaderEntry
    DATE: HeaderEntry
    PROCLEVL: HeaderEntry
    DATE_OBS: HeaderEntry
    SC_CLK: HeaderEntry
    OBJECT: HeaderEntry

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