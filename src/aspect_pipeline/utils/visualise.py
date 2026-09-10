from pathlib import Path

from astropy.io import fits


def visualise_fits_file(path: Path) -> None:
    """
    Print the primary HDU header of a FITS file.

    :param path: path to the FITS file
    :type path: Path
    """
    with fits.open(path, memmap=False) as hdul:
        print(repr(hdul[0].header))
