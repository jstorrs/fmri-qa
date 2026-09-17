"""Repetition time resolution from the BIDS sidecar and NIfTI header.

pixdim[4] is a bare number: the unit it is written in lives elsewhere, in the
header's `xyzt_units` field, and scanners do write milliseconds there. Read at
face value, a 2 s TR then arrives as 2000, and every duration-derived choice
downstream is quietly wrong — the warm-up trim drops no volumes, the detrend
fit picks an absurd order — while the metrics still come out looking like
numbers. So the header value is always converted by its declared unit, and the
BIDS sidecar `RepetitionTime`, which is defined to be seconds and so cannot be
misread, wins whenever it is there.
"""

import math
import warnings
from pathlib import Path
from typing import Any

from ..types import Sidecar

# NIfTI `xyzt_units` time codes, as nibabel spells them, in seconds. An unknown
# unit is read as seconds: that is what an unlabelled pixdim has always meant in
# practice, and it leaves a well-formed file untouched.
TIME_UNIT_SECONDS: dict[str, float] = {"sec": 1.0, "msec": 1e-3, "usec": 1e-6}

# Fractional gap between the two sources worth complaining about. They are the
# same number written twice, so anything past rounding noise means one of them
# is wrong about the acquisition and the operator should know.
TR_RTOL = 1e-3


def _tr_from_header(header: Any) -> float:
    """pixdim[4] in seconds, converted by the header's declared time unit."""
    unit = str(header.get_xyzt_units()[1])
    return float(header.get_zooms()[3]) * TIME_UNIT_SECONDS.get(unit, 1.0)


def _positive_seconds(value: object) -> float | None:
    """`value` as a positive, finite number of seconds; None if it is neither."""
    if not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def _repetition_time(header: Any, sidecar: Sidecar, path: str | Path) -> float:
    """The TR in seconds, preferring the sidecar over a converted pixdim[4].

    The sidecar `RepetitionTime` is authoritative when it is a positive, finite
    number; otherwise the header value converted by `xyzt_units` is used. When
    both are present and disagree, the sidecar still wins — BIDS fixes its unit
    — but the mismatch warns, naming both values, since one of the two files
    describes an acquisition that did not happen.
    """
    header_tr = _tr_from_header(header)
    sidecar_tr = _positive_seconds(sidecar.get("RepetitionTime"))

    if sidecar_tr is None:
        if "RepetitionTime" in sidecar:
            warnings.warn(
                f"{path}: ignoring sidecar RepetitionTime "
                f"{sidecar['RepetitionTime']!r} (expected a positive number of "
                f"seconds); using the NIfTI header TR {header_tr:g} s",
                stacklevel=3,  # report at the caller of `QAScan.from_nifti`
            )
        return header_tr

    header_is_usable = math.isfinite(header_tr) and header_tr > 0
    if header_is_usable and not math.isclose(sidecar_tr, header_tr, rel_tol=TR_RTOL):
        warnings.warn(
            f"{path}: sidecar RepetitionTime {sidecar_tr:g} s disagrees with the "
            f"NIfTI header TR {header_tr:g} s; using the sidecar value",
            stacklevel=3,
        )
    return sidecar_tr
