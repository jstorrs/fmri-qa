"""The Python half of the fmri-qa browser page.

Bytes in, values out: no file is touched and no process started, so it runs
under Pyodide. `fmriqa_web.bridge` wraps this surface as strict JSON for the
page's worker. Private to the workspace; not published.
"""

from .document import Recorded, Unrecorded, batch_document, contract
from .exceptions import InvalidResultError, NameCollisionError
from .naming import name_outputs
from .series import SeriesFailure, SeriesReport, analyze_series

__all__ = [
    "InvalidResultError",
    "NameCollisionError",
    "Recorded",
    "SeriesFailure",
    "SeriesReport",
    "Unrecorded",
    "analyze_series",
    "batch_document",
    "contract",
    "name_outputs",
]
