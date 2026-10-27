"""Decode a scan from bytes: NIfTI and BIDS sidecar in, `QAScan` out.

`scan_from_bytes` is the whole decoder, and `parse_sidecar` its JSON step. Both
take bytes, so they run where there is no filesystem, such as a browser page
under Pyodide handed the bytes of a dropped file. `fmriqa_io.load_scan` reads
the files and calls `scan_from_bytes`.

Import rule: this subpackage imports only the standard library (no filesystem
or subprocess use), numpy, nibabel and `fmriqa`. It never imports netCDF4,
dcm2niix or another `fmriqa_io` submodule, so it stays installable and
importable under Pyodide. `tests/test_decode_isolation.py` checks this.
"""

from .scan import scan_from_bytes
from .sidecar import parse_sidecar

__all__ = [
    "parse_sidecar",
    "scan_from_bytes",
]
