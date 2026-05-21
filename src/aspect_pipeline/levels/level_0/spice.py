import spiceypy as spice
import numpy as np
from typing import Tuple
import os
from pathlib import Path
from scipy.spatial.transform import Rotation as R

"""
This is a Python file for using HERA SPICE kernels.
To use this file, you need to have HERA SPICE kernel dataset installed.
You may need to write the correct path to the kernel folder specified in metakernel.
The SPICE dataset has too large file sizes to be uploaded into github.
Refer to the readme files in SPICE dataset for more information about SPICE kernels.
"""

"""
HERA SPICE kernel dataset: https://s2e2.cosmos.esa.int/bitbucket/projects/SPICE_KERNELS/repos/hera/browse
SpiceyPy docs: https://spiceypy.readthedocs.io/en/stable/documentation.html#
WebGeocalc: http://spice.esac.esa.int/webgeocalc/#NewCalculation
"""

"""
Memo:
- hera_plan.tm metakernel provides Milani long term predicted trajectory
- hera_ops.tm is later updated with asteroid phase cubesat trajectories
"""

test_time = '2025-06-15T05:40:46.6666'
test_time = '2027-01-02T05:40:46.6666'

test_et = None

def load_meta_kernel(mk: str | Path):
    """Load the given meta-kernel (.tm) file."""
    mk = str(mk)
    try:
        spice.furnsh(mk)
        print(f"Loaded meta-kernel: {mk}")
        test_et = spice.utc2et(test_time)
    except Exception as e:
        raise Exception(f"Caught an exception while loading meta kernel {mk}: {e}")

def unload_all_kernels():
    spice.kclear()
    print("Unloaded all kernels.")

def list_loaded_kernels():
    """Prints all currently loaded SPICE kernels and their types."""
    count = spice.ktotal("ALL")
    print(f"Total kernels loaded: {count}")
    for i in range(count):
        file, type_, mk_path, index = spice.kdata(i, "ALL")
        print(f"[{i}] Type: {type_:<5}  File: {file}")

def km_to_au(km: float) -> float:
    AU_PER_KM = 149597870.7
    return km / AU_PER_KM

def query_mk_identifier() -> str:
    """
    Query 'MK_IDENTIFIER' from the kernel pool.
    parameters
    identifier, start index, number of values, max length of string
    """
    try:
        mk_id = spice.gcpool("MK_IDENTIFIER", 0, 1, 80)

        if len(mk_id) > 0:
            return mk_id[0]
        else:
            return 'UNK'
    except Exception as e:
        print(f"Caught an exception while querying SPICE: {e}")
        return "UNK"
    
def query_spice_version() -> str:
    """
    Query 'SKD_VERSION' from the kernel pool.
    """
    try:
        version = spice.gcpool("SKD_VERSION", 0, 1)

        if len(version[0]) > 0:
            return version[0]
        else:
            return 'UNK'
    except Exception as e:
        print(f"Caught an exception while querying SPICE: {e}")
        return "UNK"

def get_sc_id(frame_name:str = 'MILANI_SPACECRAFT') -> int:
    try:
        frame_id = spice.namfrm(frame_name)
        return frame_id
    except Exception as e:
        print(f"Caught an exception while querying SPICE: {e}")
        return "UNK"

def utc_2_et(utc: str) -> float:
    return spice.utc2et(utc)

def get_sclk(et: float, sc_frame: str) -> str:
    """
    converts the UTC observation time into SC clock SPICE format

    Parameters:
        et (float)  : Ephemeris time 
        sc_frame (str) : Spacecraft frame name

    Return:
        (str) spacecract clock count in SPICE format

    DISCLAIMER: Does not work with time form telemetry (1). For some reason -999 must be added to sc_id for MILANI sc id
    """
    try:
        # Convert UTC to ET
        sc_id = get_sc_id(sc_frame)
        sclk_str = spice.sce2s(sc_id - 999, et) # What is the correct sc_id value?
        return sclk_str
    except Exception as e:
        print(f"Caught an exception while querying SPICE: {e}")
        return "UNK"

def query_position_distance(
        target: str = 'SUN',
        et: float = test_et,
		frame: str = 'J2000', # Is this the correct frame?
        abcorr: str = 'NONE',
		observer: str = 'MILANI_SPACECRAFT'
    )-> Tuple[np.ndarray, float]:
    """
	Query the position vectors of the target from the perspective of the observer in a specified time within a given reference frame.

	Parameters:
    target (str): The target body
	et (float)  : Ephemeris time 
	frame (str): The reference frame.
    abcorr (str): Aberration correction flag
	observer (str): The observing body.

	Returns:
	tuple:  (A tuple (X, Y, Z) representing the target's position vector relative to the observer im km.),
            (distnace between the target and the observer in km)
	"""

    try:
        state, _ = spice.spkezr(target, et, frame, abcorr, observer)
        position = state[:3] # X, Y, Z
        distance_km = np.linalg.norm(position)
        distance_au = km_to_au(distance_km)
    except Exception as e:
        print(f"Caught an exception while querying SPICE: {e}")
        return (['UNK', 'UNK', 'UNK'], 'UNK')

    return position, distance_au

def query_spacecraft_quaternions(
        frame_name: str = 'HERA_SPACECRAFT',
        et: str = test_et,
        tol: int = 1.0,
        ref: str = 'J2000'
    ) -> np.ndarray: 

    """
    Parameters:
    frame_name: name of the observer that is converted to NAIF ID.
    et (float)  : Ephemeris time 
    tol: Time tolerance.
    ref: Reference frame.

    Returns: Numpy Array containing the 4 quaternions. 

    """
    # Old implementation
    # inst_id = get_sc_id(frame_name=frame_name)
    # print(f'inst_id: {inst_id}')
    # cmat, av, clkout = spice.ckgpav(-9102001, et, tol, ref)
    # quat = spice.m2q(cmat)

    # return(quat)
    try:
        rot_matrix = spice.pxform(ref, frame_name, et)

        X = (1, 0, 0)
        Y = (0, 1, 0)
        Z = (0, 0, 1)

        rotated_X = np.dot(X, rot_matrix)
        rotated_Y = np.dot(Y, rot_matrix)
        rotated_Z = np.dot(Z, rot_matrix)

        rotation_matrix = np.column_stack((rotated_X, rotated_Y, rotated_Z))
        r = R.from_matrix(rotation_matrix)
        quaternion = r.as_quat() # returns (x, y, z, w) format

        return quaternion
    except Exception as e:
        print(f"Caught an exception while querying SPICE: {e}")
        return ['UNK', 'UNK', 'UNK', 'UNK']

def get_boresight_vector(inst_id: int) -> np.ndarray:
    """
    Retrieves the boresight vector defined in the IK kernel for the given instrument ID.

    Parameters:
        inst_id: NAIF instrument ID (e.g., -910210)

    Returns:
        Boresight unit vector as a NumPy array (shape: [3])
    """
    key = f"INS{inst_id}_BORESIGHT"
    try:
        values = spice.gdpool(key, 0, 3)
        return np.array(values)
    except spice.stypes.SpiceyError as e:
        raise ValueError(f"Boresight not found for instrument ID {inst_id}: {e}")

def query_camera_pointing_info(
        camera_frame: str = 'MILANI_NAVCAM',
        et: float = test_et,
        inertial_frame: str = 'J2000',
        target_frame: str = 'DIDYMOS_FIXED',
    ): 
    """
    Parameters:
        camera_frame: Name of the camera frame
        et (float)  : Ephemeris time 
        inertial_frame: Reference frame for RA/DEC (default: 'J2000')
        target_frame: Target body-fixed frame for azimuth

    Returns:
        Tuple of (RA_deg, DEC_deg, NorthAzimuth_deg)
    """

    try:
        inst_id = get_sc_id(frame_name=camera_frame)
        boresight = get_boresight_vector(inst_id) # typically [0, 0, 1]

        # Rotate boresight into inertial frame
        r_cam2j2000 = spice.pxform(camera_frame, inertial_frame, et) # Rotation matrix
        bore_j2000 = r_cam2j2000 @ boresight 

        _, ra_rad, dec_rad = spice.recrad(bore_j2000) # Spherical coordinates
        ra_deg = np.degrees(ra_rad)
        dec_deg = np.degrees(dec_rad)

        # Rotate boresight into body-fixed frame
        r_cam2body = spice.pxform(camera_frame, target_frame, et) # Rotation matrix
        bore_body = r_cam2body @ boresight

        x, y, z = bore_body
        az_rad = np.arctan2(y, x)  # azimuth angle relative to +X axis
        az_deg = (np.degrees(az_rad) + 360) % 360

        return ra_deg, dec_deg, az_deg
    
    except Exception as e:
        print(f"Caught an exception while querying SPICE: {e}")
        return "UNK", 'UNK', 'UNK'

def query_camera_solar_elongation(
    camera_frame: str = 'MILANI_NAVCAM',
    et: float = test_et, 
    abcorr: str = 'LT+S',
    observer:str = 'MILANI_SPACECRAFT'
    ) -> float:
    """
    Computes the solar elongation angle from the camera boresight direction

    Parameters:
        camera_frame: Frame name of the camera (e.g., 'MILANI_NAVCAM')
        et (float)  : Ephemeris time 
        abcorr (str): Aberration correction flag
        observer: Spacecraft name (default 'MILANI_SPACECRAFT')

    Returns:
        Solar elongation angle in degrees (float)
    """
    try:
        inst_id = get_sc_id(frame_name=camera_frame)
        boresight = get_boresight_vector(inst_id) # typically [0, 0, 1]

        r_cam2j2000 = spice.pxform(camera_frame, "J2000", et) # boresight into inertial frame
        bore_j2000 = r_cam2j2000 @ boresight

        sun_state, _ = spice.spkezr("SUN", et, "J2000", abcorr, observer) # Vector from the observer to sun
        sun_vec = sun_state[:3]
        sun_unit = sun_vec / np.linalg.norm(sun_vec)

        dot = np.dot(bore_j2000, sun_unit)
        dot = np.clip(dot, -1.0, 1.0) 
        angle_rad = np.arccos(dot)
        angle_deg = np.degrees(angle_rad)

        return(angle_deg)
    except Exception as e:
        print(f"Caught an exception while querying SPICE: {e}")
        return "UNK"

def list_ck_instruments():
    """
    Lists all currently loaded CK files and the NAIF instrument IDs they contain.
    """
    n_ck = spice.ktotal("CK")
    if n_ck == 0:
        print("No CK kernels are currently loaded.")
        return

    print(f"Loaded CK kernels: {n_ck}\n")

    for i in range(n_ck):
        try:
            ck_file, _, _, _ = spice.kdata(i, "CK")
            print(f"[{i}] CK File: {ck_file}")

            # Get instrument IDs from this CK file
            ids = spice.ckobj(ck_file)
            if ids:
                for inst_id in ids:
                    try:
                        name = spice.bodc2n(inst_id)
                    except spice.stypes.SpiceyError:
                        name = "(name not found)"
                    print(f"    Instrument ID: {inst_id} → {name}")
            else:
                print("    No instrument IDs found in this CK file.")
        except spice.stypes.SpiceyError as e:
            print(f"    Error reading CK file: {e}")

    print("\nDone.")

def check_spk_coverage(body_id: int):
    n_spk = spice.ktotal("SPK")
    if n_spk == 0:
        print("No SPK kernels loaded.")
        return

    for i in range(n_spk):
        spk_file, _, _, _ = spice.kdata(i, "SPK")
        try:
            cover = spice.spkcov(spk_file, body_id)
            count = spice.wncard(cover)  # number of intervals

            if count > 0:
                print(f"\nSPK File: {spk_file}")
                for j in range(count):
                    start_et, end_et = spice.wnfetd(cover, j)
                    start_utc = spice.et2utc(start_et, "ISOC", 3)
                    end_utc = spice.et2utc(end_et, "ISOC", 3)
                    print(f"  Coverage: {start_utc} → {end_utc}")
        except spice.stypes.SpiceyError as e:
            print(f"  [!] Failed reading {spk_file}: {e}")
