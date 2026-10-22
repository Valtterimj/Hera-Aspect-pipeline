import json
import logging
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits

from aspect_pipeline.utils.errors import ValidationError
from aspect_pipeline.utils.utilities import id_to_channel
from aspect_pipeline.utils.visualise import BIN_DTYPE, BIN_FRAME_SHAPE

logger = logging.getLogger(__name__)

"""
Scripts to compare files either exactly bit-by-bit or format aware keyword-value

The coce for comparison is mostly AI generated

"""

COMPARE_FILETYPES = ("json", "bin", "fits")
FITS_BLOCK_SIZE = 2880
FITS_CARD_SIZE = 80
_COMPARE_CHUNK_SIZE = 1 << 20
_HEX_CONTEXT = 8
_HEX_MAX_SHOWN = 32
_BIN_FILENAME_RE = re.compile(r"dc_(\d+)_exp_")
_JSON_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_inputs(path_a: Path, path_b: Path, filetype: str, max_diffs: int) -> None:
    """Check filetype, limit and that both paths are existing files."""
    if filetype not in COMPARE_FILETYPES:
        logger.error("Unknown filetype %r, expected one of %s", filetype, COMPARE_FILETYPES)
        raise ValidationError(f"Unknown filetype {filetype!r}, expected one of {COMPARE_FILETYPES}", stage="compare")
    if max_diffs < 0:
        logger.error("max_diffs must be >= 0, got %d", max_diffs)
        raise ValidationError(f"max_diffs must be >= 0, got {max_diffs}", stage="compare")
    for p in (path_a, path_b):
        if not p.is_file():
            logger.error("Not an existing file: %s", p)
            raise ValidationError("Not an existing file", stage="compare", path=str(p))


def _style() -> tuple[str, str, str, str]:
    """ANSI codes (red, green, bold, reset), empty when stdout is not a terminal."""
    if sys.stdout.isatty():
        return "\033[31m", "\033[32m", "\033[1m", "\033[0m"
    return "", "", "", ""


# ---------------------------------------------------------------------------
# Exact (byte-by-byte) comparison
# ---------------------------------------------------------------------------

@dataclass
class DiffRange:
    """A contiguous run of differing bytes (or a tail present in only one file)."""
    start: int
    length: int
    only_in: str | None = None
    location: str = ""
    window_start: int = 0
    window_a: bytes = b""
    window_b: bytes = b""


@dataclass
class ComparisonResult:
    """Outcome of a byte-by-byte comparison of two files."""
    path_a: Path
    path_b: Path
    filetype: str
    size_a: int
    size_b: int
    differing_bytes: int = 0
    range_count: int = 0
    ranges: list[DiffRange] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return self.differing_bytes == 0


@dataclass
class _FitsHdu:
    index: int
    header_start: int
    data_start: int
    data_end: int


def compare_exact(path_a: Path, path_b: Path, filetype: str, max_ranges: int = 20) -> ComparisonResult:
    """
    Compare two files byte by byte and locate every differing byte range.

    Args:
        path_a: Path to the first file.
        path_b: Path to the second file.
        filetype: One of "json", "bin", "fits". Controls how difference
            locations are described (byte offset / line:column / FITS HDU+card).
        max_ranges: Maximum number of differing ranges to keep details for.
            All ranges are still counted. A size-mismatch tail is always kept.

    Returns:
        ComparisonResult with file sizes (bytes), total differing bytes,
        total differing range count and the detailed ranges.

    Raises:
        ValidationError: If filetype is unknown, max_ranges is negative,
            or either path is not an existing regular file.
    """
    _validate_inputs(path_a, path_b, filetype, max_ranges)

    result = ComparisonResult(
        path_a=path_a,
        path_b=path_b,
        filetype=filetype,
        size_a=path_a.stat().st_size,
        size_b=path_b.stat().st_size,
    )

    _scan_differences(result, max_ranges)
    _attach_windows(result)
    _attach_locations(result)
    return result


def _scan_differences(result: ComparisonResult, max_ranges: int) -> None:
    """Stream both files in chunks and record contiguous differing ranges."""
    run_start: int | None = None
    run_end = 0

    def close_run() -> None:
        result.range_count += 1
        if len(result.ranges) < max_ranges:
            result.ranges.append(DiffRange(start=run_start, length=run_end - run_start))

    offset = 0
    with open(result.path_a, "rb") as fa, open(result.path_b, "rb") as fb:
        while True:
            chunk_a = fa.read(_COMPARE_CHUNK_SIZE)
            chunk_b = fb.read(_COMPARE_CHUNK_SIZE)
            n = min(len(chunk_a), len(chunk_b))
            if n == 0:
                break
            if chunk_a[:n] != chunk_b[:n]:
                arr_a = np.frombuffer(chunk_a, dtype=np.uint8, count=n)
                arr_b = np.frombuffer(chunk_b, dtype=np.uint8, count=n)
                idx = np.flatnonzero(arr_a != arr_b) + offset
                result.differing_bytes += int(idx.size)
                breaks = np.flatnonzero(np.diff(idx) != 1)
                starts = np.concatenate(([idx[0]], idx[breaks + 1]))
                ends = np.concatenate((idx[breaks], [idx[-1]])) + 1
                for s, e in zip(starts.tolist(), ends.tolist()):
                    if run_start is not None and s == run_end:
                        # Run continues across a chunk boundary
                        run_end = e
                        continue
                    if run_start is not None:
                        close_run()
                    run_start, run_end = s, e
            offset += n

    if run_start is not None:
        close_run()

    if result.size_a != result.size_b:
        common = min(result.size_a, result.size_b)
        extra = abs(result.size_a - result.size_b)
        result.differing_bytes += extra
        result.range_count += 1
        result.ranges.append(DiffRange(
            start=common,
            length=extra,
            only_in="A" if result.size_a > result.size_b else "B",
        ))


def _attach_windows(result: ComparisonResult) -> None:
    """Read a small hex window (with context) around each stored range from both files."""
    with open(result.path_a, "rb") as fa, open(result.path_b, "rb") as fb:
        for r in result.ranges:
            r.window_start = max(0, r.start - _HEX_CONTEXT)
            win_len = (r.start - r.window_start) + min(r.length, _HEX_MAX_SHOWN) + _HEX_CONTEXT
            fa.seek(r.window_start)
            fb.seek(r.window_start)
            r.window_a = fa.read(win_len)
            r.window_b = fb.read(win_len)


def _attach_locations(result: ComparisonResult) -> None:
    """Describe where each range lies, according to the file type."""
    if result.filetype == "json":
        data_a = result.path_a.read_bytes()
        data_b = result.path_b.read_bytes() if result.size_b > result.size_a else b""
        for r in result.ranges:
            data = data_b if r.only_in == "B" else data_a
            line = data.count(b"\n", 0, r.start) + 1
            col = r.start - (data.rfind(b"\n", 0, r.start) + 1) + 1
            r.location = f"line {line}, col {col} (byte column)"
    elif result.filetype == "fits":
        layout_a = _fits_hdu_layout(result.path_a)
        layout_b = _fits_hdu_layout(result.path_b) if any(r.only_in == "B" for r in result.ranges) else []
        for r in result.ranges:
            if r.only_in == "B":
                r.location = _fits_location(r, result.path_b, layout_b)
            else:
                r.location = _fits_location(r, result.path_a, layout_a)


def _fits_hdu_layout(path: Path) -> list[_FitsHdu]:
    """
    Walk FITS headers (standard library only) to map byte offsets to HDUs.

    Stops quietly at the first malformed or truncated HDU; offsets beyond the
    parsed structure are then reported as unknown.
    """
    layout: list[_FitsHdu] = []
    size = path.stat().st_size
    with open(path, "rb") as f:
        pos = 0
        while pos < size:
            header_start = pos
            cards: dict[str, str] = {}
            found_end = False
            while not found_end:
                block = f.read(FITS_BLOCK_SIZE)
                if len(block) < FITS_BLOCK_SIZE:
                    return layout
                pos += FITS_BLOCK_SIZE
                for i in range(0, FITS_BLOCK_SIZE, FITS_CARD_SIZE):
                    card = block[i:i + FITS_CARD_SIZE].decode("ascii", errors="replace")
                    key = card[:8].rstrip()
                    if key == "END":
                        found_end = True
                        break
                    if card[8:10] == "= ":
                        cards[key] = card[10:].split("/", 1)[0].strip()
            try:
                data_size = _fits_data_size(cards)
            except (KeyError, ValueError):
                return layout
            padded = -(-data_size // FITS_BLOCK_SIZE) * FITS_BLOCK_SIZE
            layout.append(_FitsHdu(len(layout), header_start, pos, pos + padded))
            pos += padded
            f.seek(pos)
    return layout


def _fits_data_size(cards: dict[str, str]) -> int:
    """Data-unit size in bytes (unpadded) per the FITS standard."""
    naxis = int(cards.get("NAXIS", "0"))
    if naxis == 0:
        return 0
    bitpix = abs(int(cards["BITPIX"]))
    dims = [int(cards[f"NAXIS{i}"]) for i in range(1, naxis + 1)]
    if cards.get("GROUPS") == "T" and dims[0] == 0:
        dims = dims[1:]
    pcount = int(cards.get("PCOUNT", "0"))
    gcount = int(cards.get("GCOUNT", "1"))
    return bitpix * gcount * (pcount + math.prod(dims)) // 8


def _fits_location(r: DiffRange, path: Path, layout: list[_FitsHdu]) -> str:
    """Describe a range's position as HDU / header card / data offset."""
    block = r.start // FITS_BLOCK_SIZE
    for hdu in layout:
        if hdu.header_start <= r.start < hdu.data_end:
            if r.start < hdu.data_start:
                first_card = (r.start - hdu.header_start) // FITS_CARD_SIZE
                last_byte = min(r.start + r.length, hdu.data_start) - 1
                last_card = (last_byte - hdu.header_start) // FITS_CARD_SIZE
                with open(path, "rb") as f:
                    f.seek(hdu.header_start + first_card * FITS_CARD_SIZE)
                    card = f.read(FITS_CARD_SIZE).decode("ascii", errors="replace").rstrip()
                cards = f"card {first_card}" if first_card == last_card else f"cards {first_card}-{last_card}"
                return f"block {block}, HDU {hdu.index} header, {cards}: '{card}'"
            return f"block {block}, HDU {hdu.index} data, data byte {r.start - hdu.data_start}"
    return f"block {block}, outside parsed FITS structure"


def print_exact_comparison(result: ComparisonResult) -> None:
    """
    Print a human-readable byte comparison report to stdout, highlighting differing bytes.

    Args:
        result: Output of compare_exact.
    """
    red, green, bold, reset = _style()

    print(f"A: {result.path_a}  ({result.size_a} bytes)")
    print(f"B: {result.path_b}  ({result.size_b} bytes)")
    if result.identical:
        print(f"{green}{bold}IDENTICAL{reset}: files match byte for byte.")
        return

    print(f"{red}{bold}DIFFERENT{reset}: {result.differing_bytes} differing byte(s) "
          f"in {result.range_count} range(s).")
    if result.size_a != result.size_b:
        print(f"  Size mismatch: A is {result.size_a} bytes, B is {result.size_b} bytes.")

    shown = len(result.ranges)
    for n, r in enumerate(result.ranges, start=1):
        print()
        what = f"only in {r.only_in}" if r.only_in else "differ"
        head = f"#{n}  offset 0x{r.start:08X} ({r.start}), {r.length} byte(s) {what}"
        print(head + (f"  [{r.location}]" if r.location else ""))
        print(f"    A: {_hex_line(r.window_a, r, red, reset)}")
        print(f"    B: {_hex_line(r.window_b, r, green, reset)}")
        if r.length > _HEX_MAX_SHOWN:
            print(f"    ... {r.length - _HEX_MAX_SHOWN} more differing byte(s) in this range")

    if result.range_count > shown:
        print(f"\n... {result.range_count - shown} more range(s) not shown (raise --max-diffs to see them).")


def _hex_line(window: bytes, r: DiffRange, hl: str, reset: str) -> str:
    """Format a byte window as hex + ASCII, marking bytes inside the differing range."""
    if not window:
        return "<EOF>"
    diff_lo = r.start - r.window_start
    diff_hi = diff_lo + min(r.length, _HEX_MAX_SHOWN)
    hex_parts: list[str] = []
    asc_parts: list[str] = []
    for i, b in enumerate(window):
        h = f"{b:02X}"
        a = chr(b) if 32 <= b < 127 else "."
        if diff_lo <= i < diff_hi:
            # Brackets keep the highlight visible when colour is unavailable
            h = f"{hl}{h}{reset}" if hl else f"[{h}]"
            a = f"{hl}{a}{reset}" if hl else a
        hex_parts.append(h)
        asc_parts.append(a)
    return " ".join(hex_parts) + "  |" + "".join(asc_parts) + "|"


# ---------------------------------------------------------------------------
# Format-aware comparison
# ---------------------------------------------------------------------------

@dataclass
class FormatDiff:
    """One semantic difference, optionally with per-element detail lines."""
    where: str
    message: str
    details: list[str] = field(default_factory=list)


@dataclass
class FormatComparisonResult:
    """Outcome of a format-aware comparison of two files."""
    path_a: Path
    path_b: Path
    filetype: str
    difference_count: int = 0
    differences: list[FormatDiff] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def identical(self) -> bool:
        return self.difference_count == 0

    def add(self, where: str, message: str, max_diffs: int) -> FormatDiff:
        """Count a difference and keep it if under max_diffs."""
        diff = FormatDiff(where, message)
        self.difference_count += 1
        if len(self.differences) < max_diffs:
            self.differences.append(diff)
        return diff


def compare_format(path_a: Path, path_b: Path, filetype: str, max_diffs: int = 20) -> FormatComparisonResult:
    """
    Compare two files by their decoded content rather than their raw bytes.

    Values are compared exactly; leading/trailing whitespace on keys and string
    values is ignored.
    - json: parsed structure; key order and formatting ignored, list order kept.
    - fits: HDU count, every header keyword's value (keyword order and card
      comments ignored), and data values (NaN equals NaN).
    - bin: little-endian uint16 pixels, shaped by the channel parsed from a
      dc_{id}_exp_ filename; falls back to a flat sample comparison otherwise.

    Args:
        path_a: Path to the first file.
        path_b: Path to the second file.
        filetype: One of "json", "bin", "fits".
        max_diffs: Maximum number of differences (and per-array detail lines)
            to keep. All differences are still counted.

    Returns:
        FormatComparisonResult listing the differences found.

    Raises:
        ValidationError: If filetype is unknown, max_diffs is negative, a path is
            not an existing file, or a file cannot be parsed as the given type.
        ValueError: If a .bin filename names an unknown channel id, a channel
            with no known frame shape (e.g. SWIR), or the sample count does not
            match that channel's frame shape.
    """
    _validate_inputs(path_a, path_b, filetype, max_diffs)
    result = FormatComparisonResult(path_a=path_a, path_b=path_b, filetype=filetype)

    if filetype == "json":
        _diff_json(_load_json(path_a), _load_json(path_b), "$", result, max_diffs)
    elif filetype == "fits":
        _diff_fits_files(result, max_diffs)
    elif filetype == "bin":
        _diff_bin_files(result, max_diffs)
    return result


def _load_json(path: Path) -> Any:
    """Parse a JSON file, converting parse errors into ValidationError."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.error("Invalid JSON in %s: %s", path, e)
        raise ValidationError(f"Invalid JSON: {e}", stage="compare", path=str(path)) from e


def _json_kind(value: Any) -> str:
    """JSON type name of a parsed value (bool kept separate from number)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _short(value: Any, limit: int = 60) -> str:
    """Compact JSON rendering of a value, truncated to limit characters."""
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _diff_json(a: Any, b: Any, where: str, result: FormatComparisonResult, max_diffs: int) -> None:
    """Recursively compare two parsed JSON values."""
    kind_a, kind_b = _json_kind(a), _json_kind(b)
    if kind_a != kind_b:
        result.add(where, f"type {kind_a} -> {kind_b}: {_short(a)} -> {_short(b)}", max_diffs)
        return

    if kind_a == "object":
        stripped_a = {k.strip(): v for k, v in a.items()}
        stripped_b = {k.strip(): v for k, v in b.items()}
        keys = list(stripped_a) + [k for k in stripped_b if k not in stripped_a]
        for key in keys:
            child = f"{where}.{key}" if _JSON_IDENTIFIER_RE.match(key) else f"{where}[{json.dumps(key)}]"
            if key not in stripped_b:
                result.add(child, f"only in A: {_short(stripped_a[key])}", max_diffs)
            elif key not in stripped_a:
                result.add(child, f"only in B: {_short(stripped_b[key])}", max_diffs)
            else:
                _diff_json(stripped_a[key], stripped_b[key], child, result, max_diffs)
    elif kind_a == "array":
        if len(a) != len(b):
            result.add(where, f"array length {len(a)} -> {len(b)}", max_diffs)
        for i in range(max(len(a), len(b))):
            child = f"{where}[{i}]"
            if i >= len(b):
                result.add(child, f"only in A: {_short(a[i])}", max_diffs)
            elif i >= len(a):
                result.add(child, f"only in B: {_short(b[i])}", max_diffs)
            else:
                _diff_json(a[i], b[i], child, result, max_diffs)
    elif kind_a == "string":
        if a.strip() != b.strip():
            result.add(where, f"{_short(a)} -> {_short(b)}", max_diffs)
    elif a != b:
        result.add(where, f"{_short(a)} -> {_short(b)}", max_diffs)


def _diff_fits_files(result: FormatComparisonResult, max_diffs: int) -> None:
    """Compare HDU count, headers and data of two FITS files."""
    try:
        with fits.open(result.path_a) as hdul_a, fits.open(result.path_b) as hdul_b:
            if len(hdul_a) != len(hdul_b):
                result.add("file", f"HDU count {len(hdul_a)} -> {len(hdul_b)}", max_diffs)
            for i in range(min(len(hdul_a), len(hdul_b))):
                _diff_fits_header(hdul_a[i].header, hdul_b[i].header, f"HDU {i} header", result, max_diffs)
                _diff_fits_data(hdul_a[i].data, hdul_b[i].data, f"HDU {i} data", result, max_diffs)
    except OSError as e:
        logger.error("Cannot read FITS file: %s", e)
        raise ValidationError(f"Cannot read FITS file: {e}", stage="compare") from e
    result.notes.append("FITS data indices are in numpy order (last axis = NAXIS1).")


def _normalise_header_value(value: Any) -> Any:
    """Strip leading/trailing whitespace from string header values."""
    return value.strip() if isinstance(value, str) else value


def _diff_fits_header(header_a: fits.Header, header_b: fits.Header, where: str,
                      result: FormatComparisonResult, max_diffs: int) -> None:
    """Compare every keyword's value(s); repeated keywords (COMMENT, HISTORY) compared in order."""
    values_a: dict[str, list[Any]] = {}
    values_b: dict[str, list[Any]] = {}
    for header, values in ((header_a, values_a), (header_b, values_b)):
        for card in header.cards:
            values.setdefault(card.keyword, []).append(_normalise_header_value(card.value))

    keywords = list(values_a) + [k for k in values_b if k not in values_a]
    for kw in keywords:
        label = kw if kw else "(blank keyword)"
        list_a = values_a.get(kw, [])
        list_b = values_b.get(kw, [])
        for j in range(max(len(list_a), len(list_b))):
            name = f"{where}: {label}" + (f"[{j}]" if max(len(list_a), len(list_b)) > 1 else "")
            if j >= len(list_b):
                result.add(name, f"only in A: {list_a[j]!r}", max_diffs)
            elif j >= len(list_a):
                result.add(name, f"only in B: {list_b[j]!r}", max_diffs)
            elif type(list_a[j]) is bool or type(list_b[j]) is bool:
                if type(list_a[j]) is not type(list_b[j]) or list_a[j] != list_b[j]:
                    result.add(name, f"{list_a[j]!r} -> {list_b[j]!r}", max_diffs)
            elif list_a[j] != list_b[j]:
                result.add(name, f"{list_a[j]!r} -> {list_b[j]!r}", max_diffs)


def _diff_fits_data(data_a: Any, data_b: Any, where: str,
                    result: FormatComparisonResult, max_diffs: int) -> None:
    """Compare an HDU's data: image arrays directly, tables column by column."""
    if data_a is None and data_b is None:
        return
    if data_a is None or data_b is None:
        result.add(where, "data only in " + ("B" if data_a is None else "A"), max_diffs)
        return

    names_a = data_a.dtype.names
    names_b = data_b.dtype.names
    if names_a is None and names_b is None:
        _diff_arrays(np.asarray(data_a), np.asarray(data_b), where, result, max_diffs)
        return

    names_a = list(names_a or [])
    names_b = list(names_b or [])
    for name in names_a:
        if name not in names_b:
            result.add(f"{where} column {name}", "only in A", max_diffs)
    for name in names_b:
        if name not in names_a:
            result.add(f"{where} column {name}", "only in B", max_diffs)
    for name in names_a:
        if name in names_b:
            _diff_arrays(np.asarray(data_a[name]), np.asarray(data_b[name]),
                         f"{where} column {name}", result, max_diffs)


def _diff_arrays(a: np.ndarray, b: np.ndarray, where: str,
                 result: FormatComparisonResult, max_diffs: int) -> None:
    """Compare two arrays element-wise and record a summary plus the first differing elements."""
    if a.shape != b.shape:
        result.add(where, f"shape {a.shape} -> {b.shape}", max_diffs)
        return

    numeric = "biufc"
    kind_a, kind_b = a.dtype.kind, b.dtype.kind
    if a.dtype != b.dtype:
        result.add(where, f"dtype {a.dtype} -> {b.dtype}", max_diffs)
        if (kind_a in numeric) != (kind_b in numeric):
            return

    if kind_a in "SU" and kind_b in "SU":
        a = np.char.strip(a)
        b = np.char.strip(b)

    if kind_a == "O" or kind_b == "O":
        flat = [not np.array_equal(x, y) for x, y in zip(a.ravel(), b.ravel())]
        neq = np.array(flat, dtype=bool).reshape(a.shape)
    else:
        neq = np.asarray(a != b)
        if kind_a in "fc" and kind_b in "fc":
            neq &= ~(np.isnan(a) & np.isnan(b))

    count = int(np.count_nonzero(neq))
    if count == 0:
        return

    summary = f"{count} of {a.size} value(s) differ"
    if kind_a in "iuf" and kind_b in "iuf":
        delta = np.abs(a[neq].astype(np.float64) - b[neq].astype(np.float64))
        delta = delta[~np.isnan(delta)]
        if delta.size:
            summary += f", max |A-B| = {delta.max():g}"
    diff = result.add(where, summary, max_diffs)

    for flat_index in np.flatnonzero(neq)[:max_diffs].tolist():
        index = np.unravel_index(flat_index, a.shape)
        index_str = str(tuple(int(i) for i in index)) if a.ndim > 1 else f"[{int(index[0])}]"
        diff.details.append(f"{index_str}: {a[index]!r} -> {b[index]!r}")


def _bin_frame_shape(path: Path) -> tuple[str, tuple[int, int]] | None:
    """
    Channel name and frame shape from a dc_{id}_exp_ filename, or None if the name doesn't match.

    Raises:
        ValueError: If the channel id is unknown or the channel has no known frame shape.
    """
    match = _BIN_FILENAME_RE.search(path.name)
    if not match:
        return None
    channel_id = int(match.group(1))
    channel = id_to_channel.get(channel_id)
    if channel is None:
        raise ValueError(f"Unknown channel id {channel_id} in filename: {path.name}")
    if channel not in BIN_FRAME_SHAPE:
        raise ValueError(f"No known .bin frame shape for channel {channel}: {path.name}")
    return channel, BIN_FRAME_SHAPE[channel]


def _read_bin(path: Path, result: FormatComparisonResult) -> np.ndarray:
    """Read a headerless .bin file as little-endian uint16 samples."""
    size = path.stat().st_size
    if size % BIN_DTYPE.itemsize:
        result.notes.append(f"{path.name}: {size} bytes is not a whole number of uint16 samples; "
                            f"trailing byte ignored.")
    return np.fromfile(path, dtype=BIN_DTYPE)


def _diff_bin_files(result: FormatComparisonResult, max_diffs: int) -> None:
    """Compare two raw .bin frames pixel by pixel."""
    frame_a = _bin_frame_shape(result.path_a)
    frame_b = _bin_frame_shape(result.path_b)
    data_a = _read_bin(result.path_a, result)
    data_b = _read_bin(result.path_b, result)

    if frame_a is not None and frame_a == frame_b:
        channel, shape = frame_a
        for path, data in ((result.path_a, data_a), (result.path_b, data_b)):
            if data.size != math.prod(shape):
                raise ValueError(f"{path.name}: {data.size} samples does not match {channel} frame shape {shape}")
        result.notes.append(f"Decoded as {channel} frame {shape[0]}x{shape[1]}, little-endian uint16; "
                            f"indices are (row, col).")
        _diff_arrays(data_a.reshape(shape), data_b.reshape(shape), "pixels", result, max_diffs)
        return

    if frame_a is None and frame_b is None:
        result.notes.append("Filenames don't match dc_{id}_exp_; compared as flat little-endian uint16 samples.")
    else:
        desc_a = frame_a[0] if frame_a else "unparsed"
        desc_b = frame_b[0] if frame_b else "unparsed"
        result.notes.append(f"Frame types from filenames disagree (A: {desc_a}, B: {desc_b}); "
                            f"compared as flat little-endian uint16 samples.")

    if data_a.size != data_b.size:
        result.add("file", f"sample count {data_a.size} -> {data_b.size}", max_diffs)
    common = min(data_a.size, data_b.size)
    _diff_arrays(data_a[:common], data_b[:common], f"samples [0:{common}]", result, max_diffs)


def print_format_comparison(result: FormatComparisonResult) -> None:
    """
    Print a human-readable format-aware comparison report to stdout.

    Args:
        result: Output of compare_format.
    """
    red, green, bold, reset = _style()

    print(f"A: {result.path_a}")
    print(f"B: {result.path_b}")
    for note in result.notes:
        print(f"  note: {note}")
    if result.identical:
        print(f"{green}{bold}EQUIVALENT{reset}: no {result.filetype} content differences.")
        return

    print(f"{red}{bold}DIFFERENT{reset}: {result.difference_count} {result.filetype} content difference(s).")
    for n, diff in enumerate(result.differences, start=1):
        print(f"  {n}. {bold}{diff.where}{reset}: {diff.message}")
        for line in diff.details:
            print(f"       {line}")

    hidden = result.difference_count - len(result.differences)
    if hidden > 0:
        print(f"\n... {hidden} more difference(s) not shown (raise --max-diffs to see them).")
