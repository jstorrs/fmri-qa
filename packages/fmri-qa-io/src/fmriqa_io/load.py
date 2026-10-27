"""Load a scan from disk: a NIfTI file and the BIDS sidecar beside it.

The file reads are all this module adds. Decoding is `decode.scan_from_bytes`,
which a browser calls directly with the bytes it was handed.
"""

from pathlib import Path

from fmriqa.load.scan import QAScan

from .decode import scan_from_bytes
from .paths import sidecar_path

__all__ = [
    "load_scan",
]


def load_scan(path: str | Path) -> QAScan:
    """Load a 4-D NIfTI series, with its BIDS sidecar when one exists.

    `path` is a single-file NIfTI-1 or NIfTI-2 image (`.nii` or `.nii.gz`). The
    sidecar is the `.json` with the same stem beside it (see `sidecar_path`).

    Raises
    ------
    FileNotFoundError
        If there is no file at `path`.
    InvalidScanError
        If the file is not a 4-D NIfTI series, or the sidecar is not a JSON
        object or holds an invalid phase-encode field or voxel size.
    """
    # Read before the sidecar, so a missing NIfTI fails on the NIfTI and not
    # with a warning about its sidecar.
    nifti = Path(path).read_bytes()
    beside = sidecar_path(path)
    sidecar = beside.read_bytes() if beside.is_file() else None
    return scan_from_bytes(nifti, sidecar, name=str(path), sidecar_name=str(beside))
