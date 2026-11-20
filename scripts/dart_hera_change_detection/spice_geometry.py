"""Pixel scale at Didymos (m/px) for a Hera AFC and a DART DRACO image, from SPICE.

    m/px = range(spacecraft -> Didymos) [m] x IFOV [rad/px]

  * Epoch: AFC header SPICETIM (UTC); DRACO header ACQTM_ET (ephemeris time).
  * Range: SPICE position of Didymos seen from the spacecraft (light time +
    aberration corrected), from the mission's SPK kernels.
  * IFOV: instrument kernel keyword INS<id>_IFOV. AFC (HERA_AFC-1, -91110) gives
    radians; DRACO gives microradians (dart_draco_004.ti table), using
    DART_DRACO_2X2 (-135102) when the header says BINNING = ON, else -135101.

Kernels (paths in config.py):
  * Hera: the ops meta-kernel named in the AFC header SPICE_MK; if that version
    is not on disk, the newest hera_ops*.tm is used and the mismatch printed.
    Plan meta-kernels are never used.
  * DART: <DART_SPICE>/mk/<DART_MK>.
  * Each image is processed in its own SPICE session (kclear before and after),
    so the two missions' kernels (which define Didymos differently) never mix.
  * Before computing, SPK coverage of the spacecraft and Didymos at the epoch is
    checked per kernel file; the script raises if either is not covered.

Output JSON: {"images": [{path, mission, instrument, utc, et, range_m,
ifov_rad, m_per_px}, ...], "scale_ratio": DRACO m/px / AFC m/px (unitless)}.
Copy scale_ratio into DRACO_SCALE in config.py by hand.

Usage:
    python spice_geometry.py [AFC.fits DRACO.fits] [--out GEOMETRY_JSON]
    (defaults: AFC_FITS, DRACO_FITS and GEOMETRY_JSON from config.py)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import spiceypy as sp
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import AFC_FITS, DART_MK, DART_SPICE, DRACO_FITS, GEOMETRY_JSON, HERA_SPICE  # noqa: E402

MK_ID_RE = re.compile(r"MK_IDENTIFIER\s*=\s*'([^']+)'")
MK_VERSION_RE = re.compile(r"v(\d+)_(\d{8})_(\d+)")


def select_hera_mk(wanted: str) -> Path:
    """Return the Hera ops meta-kernel matching ``wanted``, else the newest one.

    Args:
        wanted: MK identifier from the AFC header SPICE_MK.

    Returns:
        Path to the meta-kernel.

    Raises:
        FileNotFoundError: If no hera_ops*.tm exists.
        ValueError: If only plan meta-kernels exist, or a version cannot be parsed.
    """
    mk_dir = Path(HERA_SPICE) / "mk"
    found = {}
    for path in sorted(mk_dir.glob("hera_ops*.tm")):
        m = MK_ID_RE.search(path.read_text(errors="replace"))
        if m:
            # Prefer the explicitly versioned file over the generic alias.
            if m.group(1) not in found or m.group(1) in path.stem:
                found[m.group(1)] = path
    if not found:
        if list(mk_dir.glob("hera_plan*.tm")):
            raise ValueError(f"only Hera PLAN meta-kernels in {mk_dir}; refusing to use them")
        raise FileNotFoundError(f"no hera_ops*.tm meta-kernel in {mk_dir}")
    if wanted in found:
        print(f"  Hera meta-kernel {found[wanted].name} matches header SPICE_MK")
        return found[wanted]

    def version(ident: str) -> tuple[int, ...]:
        m = MK_VERSION_RE.search(ident)
        if m is None:
            raise ValueError(f"cannot parse version from MK identifier {ident!r}")
        return tuple(int(g) for g in m.groups())

    newest = max(found, key=version)
    print(f"  VERSION MISMATCH: header SPICE_MK {wanted} not on disk; using newest ops {newest}")
    return found[newest]


@contextmanager
def spice_session(mk: Path) -> Iterator[None]:
    """Load one meta-kernel into a clean kernel pool; clear it afterwards.

    Raises:
        FileNotFoundError: If the meta-kernel does not exist.
    """
    if not mk.is_file():
        raise FileNotFoundError(f"meta-kernel not found: {mk}")
    sp.kclear()
    try:
        sp.furnsh(str(mk))
        print(f"  loaded {mk.name} ({sp.ktotal('ALL')} kernels)")
        yield
    finally:
        sp.kclear()


def check_spk_coverage(body: str, et: float) -> None:
    """Print which loaded SPK files cover ``body`` at ``et`` [s TDB].

    Raises:
        ValueError: If no loaded SPK covers the body at that epoch.
    """
    code = sp.bodn2c(body)
    covering = []
    for i in range(sp.ktotal("SPK")):
        file = sp.kdata(i, "SPK")[0]
        ids = sp.spkobj(file)
        if code not in [ids[j] for j in range(sp.card(ids))]:
            continue
        cov = sp.spkcov(file, code)
        if any(a <= et <= b for a, b in (sp.wnfetd(cov, j) for j in range(sp.wncard(cov)))):
            covering.append(Path(file).name)
    if not covering:
        raise ValueError(f"no SPK covers {body} ({code}) at {sp.et2utc(et, 'ISOC', 3)}")
    print(f"  SPK coverage {body}: {', '.join(covering)} (last loaded has priority)")


def instrument(header: fits.Header) -> dict:
    """Identify the camera from the FITS header.

    Returns:
        dict with mission, spacecraft name, instrument ID and the factor that
        converts the IK IFOV value to radians.

    Raises:
        ValueError: For an unrecognised INSTRUME or BINNING value.
    """
    name = str(header.get("INSTRUME", "")).strip()
    if name.startswith("AFC"):
        return {"mission": "HERA", "spacecraft": "HERA", "ins_name": str(header["INSTRNAM"]).strip(),
                "ifov_to_rad": 1.0}
    if name == "DRACO":
        binning = str(header.get("BINNING", "")).strip().upper()
        if binning not in ("ON", "OFF"):
            raise ValueError(f"unexpected DRACO BINNING={binning!r}")
        return {"mission": "DART", "spacecraft": "DART",
                "ins_name": "DART_DRACO_2X2" if binning == "ON" else "DART_DRACO_1X1", "ifov_to_rad": 1e-6}
    raise ValueError(f"unrecognised INSTRUME={name!r}")


def pixel_scale(path: Path) -> dict:
    """Compute range, IFOV and m/px for one image in its own SPICE session.

    Returns:
        dict with path, mission, instrument, utc, et [s TDB], range_m [m],
        ifov_rad [rad/px] and m_per_px [m/px].
    """
    if not path.is_file():
        raise FileNotFoundError(path)
    header = fits.getheader(path, 0)
    cam = instrument(header)
    print(f"{path.name}: {cam['mission']} {cam['ins_name']}")
    if cam["mission"] == "HERA":
        mk = select_hera_mk(str(header["SPICE_MK"]).strip())
    else:
        mk = Path(DART_SPICE) / "mk" / DART_MK
    with spice_session(mk):
        et = sp.str2et(str(header["SPICETIM"])) if cam["mission"] == "HERA" else float(header["ACQTM_ET"])
        utc = sp.et2utc(et, "ISOC", 3)
        check_spk_coverage(cam["spacecraft"], et)
        check_spk_coverage("DIDYMOS", et)
        ins_id = sp.bodn2c(cam["ins_name"])
        ifov = float(sp.gdpool(f"INS{ins_id}_IFOV", 0, 1)[0]) * cam["ifov_to_rad"]
        pos, _lt = sp.spkpos("DIDYMOS", et, "J2000", "LT+S", cam["spacecraft"])
        range_m = float(np.linalg.norm(pos)) * 1000.0
    m_per_px = range_m * ifov
    print(f"  epoch {utc} UTC | range {range_m / 1000:.3f} km | IFOV {ifov * 1e6:.3f} urad/px "
          f"| {m_per_px:.4f} m/px")
    return {"path": str(path.resolve()), "mission": cam["mission"], "instrument": cam["ins_name"],
            "utc": utc, "et": et, "range_m": range_m, "ifov_rad": ifov, "m_per_px": m_per_px}


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("fits_files", nargs="*", type=Path, default=[AFC_FITS, DRACO_FITS])
    ap.add_argument("--out", type=Path, default=GEOMETRY_JSON)
    args = ap.parse_args(argv)

    images = [pixel_scale(p) for p in args.fits_files]
    missions = [img["mission"] for img in images]
    if sorted(missions) != ["DART", "HERA"]:
        raise ValueError(f"need exactly one AFC and one DRACO image, got {missions}")
    hera, dart = (next(i for i in images if i["mission"] == m) for m in ("HERA", "DART"))
    scale_ratio = dart["m_per_px"] / hera["m_per_px"]
    print(f"DRACO / AFC scale ratio: {scale_ratio:.5f}  (set DRACO_SCALE in config.py to this)")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"images": images, "scale_ratio": scale_ratio}, indent=2))
    print(f"written {args.out}")


if __name__ == "__main__":
    main()
