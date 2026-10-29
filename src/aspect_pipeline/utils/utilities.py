import re
import subprocess
import numbers
import numpy as np

from datetime import datetime, timezone, timedelta
from pathlib import Path
from astropy.io import fits
from astropy.io.fits import Header, PrimaryHDU, ImageHDU, BinTableHDU, HDUList

from aspect_pipeline.utils.classes import Issue, IssueLevel

import logging
logger = logging.getLogger(__name__)

kelvin: float = 273.15

CHANNELS = ['Vis', 'NIR1', 'NIR2', 'SWIR']

channel_to_id = {
    "Vis"  : 0,
    "NIR1" : 1,
    "NIR2" : 2,
    "SWIR" : 3,
    "all"  : 'P'
}

id_to_channel = {
    0 : "Vis",
    1 : "NIR1",
    2 : "NIR2",
    3 : "SWIR"
}

level_shortcuts = {
    "1": ("1A", "1B", "1C"),
    "3": ("3A", "3B", "3C"),
}

def parse_levels_to_run(levels: list[str]) -> list[str]:
    levels_to_run: list[str] = []
    seen: set[str] = set()

    def add(level: str) -> None:
        if level not in seen:
            levels_to_run.append(level)
            seen.add(level)

    for level in levels:
        if level in level_shortcuts:
            for expanded in level_shortcuts[level]:
                add(expanded)
        else:
            add(level)

    return levels_to_run

def get_current_utc_time_str():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')

def extract_frames(filenames: list[str]) -> list[str]:

    pattern = re.compile(r"_exp_(\d+)\.bin")

    frames = []
    for name in filenames:
        match = pattern.search(name)
        if not match:
            continue
        frames.append(match.group(1))
    
    frames.sort(key=int)
    return frames
    
def list_channel_frames(acq_dir: str | Path, channel: str) -> tuple[int, list[str]]:

    channel_id = channel_to_id[channel]
    if channel_id not in (0, 1, 2, 3):
        raise ValueError(f"Channel must be in [0, 1, 2, 3], got {channel_id}")
    
    p = Path(acq_dir)
    if not p.is_dir():
        raise NotADirectoryError(f"Not a directory: {p}")
    
    pattern = re.compile(rf"dc_{channel_id}_exp_(\d+)\.bin(?:\.jp2)?$")

    matched_files = []
    for file in p.iterdir():
        if not file.is_file():
            continue
        match = pattern.match(file.name)
        if match:
            frame_number = int(match.group(1))
            matched_files.append((frame_number, file.name))
        
    matched_files.sort(key=lambda x: x[0])

    filenames = [name for _, name in matched_files]

    return (len(filenames), filenames)

def decompress_jp2(input_path: str | Path, output_dir: str | Path) -> Path:
    """
    Decompress a JPEG2000 .jp2 image using the C-based './decompress' program.

    Parameters:
        input_path (str | Path): Path object to the input .jp2 file.
        output_dir (str | Path): Directory to store the output .bin file.
    
    Returns:
        Path (Path): Path object to the decompressed .bin file.
    """
    input_path = Path(input_path)
    output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True) # Cretate the output directory if does not exist
    if input_path.suffix == '.jp2':
        output_filename = input_path.stem 
    else:
        raise ValueError("Input file does not end with .jp2")

    output_path = Path(output_dir) / output_filename 

    # Resolve absolute path to decompress binary (relative to this script's location)
    project_root = Path(__file__).resolve().parents[3]
    level0_dir = project_root / "src" / "aspect_pipeline"/ "levels" / "level_0"

    decompress_path = level0_dir / "decompress"

    with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
        subprocess.run([str(decompress_path)], stdin=f_in, stdout=f_out, stderr=subprocess.DEVNULL, check=True)
    
    return output_path

def sc_clock_to_base32(sc_seconds: int, offset: int = 0) -> str:
    """
    Convert a spacecraft time (in seconds) to an unique 6 character image number, increasing by the acquisition time.
    It generated as the base 32 coding of the image capture SC clock seconds. In case of clock counter restart, 
    the time of the restart event will be added to result a continuously increasing number.

    Parameters: 
        sc_seconds (int): The spacecraft clock time in seconds.
        offset (int): Offset to add to clock time (e.g. after clock reset). Default is 0.

    Returns:
        str: A 6-character base-32 string representing the unique image number
    """

    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUV'
    base = 32
    value = sc_seconds + offset
    if value < 0:
        raise ValueError("Clock time + offset must be non-negative")
    result = ''
    for _ in range(6):
        result = alphabet[value % base] + result
        value //= base
    
    return result


def form_fits_name(channel: str, image_number: str, utc_time: str, calib_lvl: str) -> str:
    try:
        utc_format = datetime.strptime(utc_time, "%Y-%m-%dT%H:%M:%S.%f").strftime("%y%m%dT%H%M%S")
    except Exception as e:
        utc_format = 'XXXXXXXXXXXXX'
    if image_number == '':
        image_number = 'XXXXXX'
    channel_id = channel_to_id[channel]
    file_name = f'AS{channel_id}_{image_number}_{utc_format}_{calib_lvl}.fits'
    return file_name

def form_fits_header_val(key: str, value: str, comment: str, hierarch: bool) -> tuple[str, str]:
    try: 
        key = str(key)
        value = str(value)
        comment = str(comment)
        k = f"HIERARCH {key}" if hierarch else key
        card_length = len(k) + len(value) + len(comment) + 7
        if card_length <= 80:
            return (value, comment)
        else: 
            return (value, "")
    except Exception as e:
        raise ValueError(f"Fits header value and comment should be stings. (key: {type(key)}, value: {type(value)}, comment: {type(comment)})") from e

def log_issue(issue: Issue) -> None:
    issue_logger = logging.getLogger(issue.source)
    if issue.level == "info":
        issue_logger.info(issue.message)
    elif issue.level == "warning":
        issue_logger.warning(issue.message)
    elif issue.level == "error":
        issue_logger.warning(issue.message)

def fits_in_dir(folder: Path) -> list[Path]:
    files = []
    for pat in ("*.fits", "*.fit", "*fts"):
        files.extend(folder.glob(pat))
    return sorted(set(files))

def convert_to_float64(hdul: HDUList, index: int = 0) -> tuple[HDUList, Issue]:
    # Replace the .data with a float64
    hdu = hdul[index]
    if hdu.data is not None and np.issubdtype(hdu.data.dtype, np.number):
        hdu.data = hdu.data.astype(np.float64)
        if 'BITPIX' in hdu.header:
            hdu.header['BITPIX'] = -64
        issue = Issue(
            level='info',
            message='HDU data converted to float64',
            source=__name__,
        )
    else:
        issue = Issue(
            level='warning',
            message='HDU data is None or not convertable to float64',
            source=__name__,
        )
    return hdul, issue

def convert_to_float32(hdul: HDUList, index: int = 0) -> tuple[HDUList, Issue]:
    # Replace the data with a float32 
    hdu = hdul[index]
    if hdu.data is not None and np.issubdtype(hdu.data.dtype, np.number):
        hdu.data = hdu.data.astype(np.float32)
        if 'BITPIX' in hdu.header:
            hdu.header['BITPIX'] = -32
        issue = Issue(
            level='info',
            message='HDU data converted to float32',
            source=__name__,
        )
    else:
        issue = Issue(
            level='warning',
            message='HDU data is None or not convertable to float32',
            source=__name__,
        )
    return hdul, issue

def normalize_to_8bit(img: np.ndarray) -> np.ndarray:
    # Compute min and max values in the image
    min_val = np.min(img)
    max_val = np.max(img)

    # Avoid division by zero in case all values are the same
    if max_val - min_val == 0:
        return np.zeros_like(img, dtype=np.uint8)

    # Normalize image to range 0-255
    normalized = (img - min_val) / (max_val - min_val) * 255.0

    # Convert to 8-bit integer
    return normalized.astype(np.uint8)

def find_fits_files(directory: Path, levels: list[str], channels: list[str]) -> tuple[list[Path], list[str]]:
    """
    Search a directory for .fits files matching given level endings.
    """
    matched_files = []
    missing_files = []

    for level in levels:
        suffix = f'{level}.fits'
        if level in ['0A', '1A', '1B', '1C']:
            for channel in channels:
                p = get_path(directory, channel, suffix)
                if p is None:
                    missing_files.append(f'({level}, {channel})')
                else:
                    matched_files.append(p)
        if level in ['2B', '3A', '3B', '3C']:
            ch = 'all'
            p = get_path(directory, ch, suffix)
            if p is None:
                missing_files.append(f'({level}, {channel})')
            else:
                matched_files.append(p)
    
    return matched_files, missing_files

def convert_to_zulu_time(time: str, offset: str | None = None) -> str:
    """
    Converts a local time string to UTC Zulu time.

    Parameters:
        time (str): Time string, e.g. '2020-01-01T01:59:48.000' or '2020-01-01T01:59:48'
        offset (str | None): UTC offset as '±HH:MM', or None if already UTC.

    Returns:
        str: UTC time string with 'Z' suffix, e.g. '2020-01-01T01:59:48.000Z'
    """
    has_ms = '.' in time
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(time, fmt)
            break
        except ValueError:
            continue
    else:
        raise ValueError(f"Cannot parse time string: {time!r}")

    if offset is not None:
        match = re.match(r'^([+-])(\d{2}):(\d{2})$', offset)
        if not match:
            raise ValueError(f"Invalid offset format: {offset!r}. Expected ±HH:MM")
        sign, hours, minutes = match.groups()
        delta = timedelta(hours=int(hours), minutes=int(minutes))
        dt = dt - delta if sign == '+' else dt + delta

    if has_ms:
        precision = len(time.split('.')[1])
        ms_str = f"{dt.microsecond // (10 ** (6 - precision)):0{precision}d}"
        result = dt.strftime("%Y-%m-%dT%H:%M:%S") + '.' + ms_str
    else:
        result = dt.strftime("%Y-%m-%dT%H:%M:%S")

    return result + 'Z'

def convert_processing_levels(level: str) -> str:
    """
    Converts pipeline processing levels to PDS4 format
    0A -> Raw
    1A -> raw
    1B -> Partially Processed
    1C -> Calibrated
    """
    match level:
        case '0A' : return 'Raw'
        case '1A' | '1A-extra' : return 'Raw'
        case '1B' : return 'Partially Processed'
        case '1C' : return 'Calibrated'
        case _ : raise ValueError(f'Processing level should be in (0A, 1A, 1A-extra, 1B, 1C) got: {level}')

def get_wavelengths(fits_file: Path) -> list[str] | None:
    """Get all the wavelenghts of an acquisition from the fits header"""
    try:
        with fits.open(fits_file) as hdul:
            header = hdul[0].header
            channels = header.get('CHANNELS')
            channel_list = channels.split(',')
            wavelengths = []
            for channel in channel_list:
                task_number = header.get(f'{channel}_TASK_NUMBER')
                if task_number == None:
                    raise ValueError('No task number found.')
                number = int(task_number)
                for i in range(number):
                    index = str(i).zfill(3)
                    wl = header.get(f'{channel}_WL_{index}', None)
                    if wl == None:
                        continue
                    wavelengths.append(wl)
                if len(wavelengths) == 0:
                    return None
            return wavelengths
    except Exception:
        return None

def get_wavelengths_by_channel(fits_file: Path) -> dict[str, int]:
    """Get all the wavelenghts of an acquisition from the fits header"""
    try:
        with fits.open(fits_file) as hdul:
            header = hdul[0].header
            channels = header.get('CHANNELS')
            channel_list = channels.split(',')
            all_wavelengths = {}

            for channel in channel_list:
                wavelengths = []
                task_number = header.get(f'{channel}_TASK_NUMBER')
                if task_number == None:
                    raise ValueError('No task number found.')
                number = int(task_number)
                for i in range(number):
                    index = str(i).zfill(3)
                    wl = header.get(f'{channel}_WL_{index}', None)
                    if wl == None:
                        continue
                    wavelengths.append(int(wl))
                all_wavelengths[channel] = wavelengths
            return all_wavelengths
    except Exception:
        return None

def get_exposures(fits_file: Path) -> list[str] | None:
    """Get all the exposures of an acquisition from the fits header"""
    try:
        with fits.open(fits_file) as hdul:
            header = hdul[0].header
            channel = header.get('CHANNELS')
            task_number = header.get(f'{channel}_TASK_NUMBER')
            if task_number == None:
                raise ValueError('No task number found.')
            number = int(task_number)
            exposures = []
            for i in range(number):
                index = str(i).zfill(3)
                exp = header.get(f'{channel}_EXP_{index}', None)
                if exp == None:
                    continue
                exposures.append(exp)
            if len(exposures) == 0:
                return None
            return exposures
    except Exception:
        return None


def check_order(sp: float, channel: str) -> str:
    """
    Checks the order of the acquisition. The order is either high or low based on the third frame's setpoint reading.

    Parameters:
        sp (float): Setpoint value
        channel (str): channel name
    
    Returns: 
        str: high / low 
    """
    match channel:
        case 'Vis' | 'NIR1':
            if sp > 19000:
                return 'HIGH'
            else:
                return 'LOW'
        case 'NIR2':
            if sp > 20000:
                return 'HIGH'
            else:
                return 'LOW'
        case 'SWIR':
            return 'N/A'

def get_path(input_dir: Path, channel: str,  suffix: str) -> Path | None:
    """
        Resolve to path to correct fits file inside the input_dir according to the lvl.
        E.g. if lvl = 1B the input dir should contain a file ending to '*1B.fits'
        suffix should be then '1B.fits'
    """
    if not input_dir.exists() or not input_dir.is_dir():
        raise ValueError(f"Not a valid input directory found.")
    
    matches = list(input_dir.glob(f"*{suffix}"))
    channel_id = f'AS{channel_to_id[channel]}'
    matches = [p for p in matches if p.name.startswith(channel_id)]

    if not matches:
        return None

    # Return first if many
    return matches[0]

def get_frame(fits_path: Path, frame: int) -> np.ndarray:
    """Return the frame from the fits Primary HDU"""
    with fits.open(fits_path) as hdul:
        data = hdul[0].data
        if data is None:
            raise ValueError(f"{fits_path}: primary HDU contains no data")
        if not 0 <= frame < len(data):
            raise IndexError(f"{fits_path}: frame {frame} out of range (0-{len(data) - 1})")
        return np.array(data[frame])