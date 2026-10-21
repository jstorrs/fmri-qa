"""Repetition time resolution from the BIDS sidecar and NIfTI header.

pixdim[4] is a bare number. Its unit is in the header's `xyzt_units` field, and
scanners do write milliseconds there. Read at face value, a 2 s TR arrives as
2000, and every duration-derived choice goes quietly wrong: the warm-up trim
drops no volumes and the detrend fit picks an absurd order, while the metrics
still look like numbers. So the header value is always converted by its declared
unit. The BIDS sidecar `RepetitionTime` is defined to be seconds and wins
whenever it is present.
"""

import math
from pathlib import Path
from typing import Any

from ..types import Sidecar
from ..warn import warn

__all__: list[str] = []

# NIfTI `xyzt_units` time codes, as nibabel spells them, in seconds. An unknown
# unit is read as seconds, which is what an unlabeled pixdim has always meant in
# practice.
TIME_UNIT_SECONDS: dict[str, float] = {"sec": 1.0, "msec": 1e-3, "usec": 1e-6}

# Fractional gap between the two sources worth a warning. They are the same
# number written twice, so anything past rounding noise means one is wrong.
TR_RTOL = 1e-3


def _tr_from_header(header: Any) -> float:
    """Read pixdim[4] in seconds, converted by the header's declared time unit."""
    unit = str(header.get_xyzt_units()[1])
    return float(header.get_zooms()[3]) * TIME_UNIT_SECONDS.get(unit, 1.0)


def _positive_seconds(value: object) -> float | None:
    """Return `value` as positive, finite seconds, or None if it is neither."""
    # `isinstance(True, int)` is true, so exclude JSON booleans explicitly
    # instead of loading one as a 1 s TR.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def _repetition_time(header: Any, sidecar: Sidecar, path: str | Path) -> float:
    """Resolve the TR in seconds, preferring the sidecar over pixdim[4].

    The sidecar `RepetitionTime` wins when it is a positive, finite number;
    otherwise the header value converted by `xyzt_units` is used. If both exist
    and disagree, the sidecar still wins (BIDS fixes its unit) but the mismatch
    warns with both values, since one file describes an acquisition that did not
    happen.
    """
    header_tr = _tr_from_header(header)
    sidecar_tr = _positive_seconds(sidecar.get("RepetitionTime"))

    if sidecar_tr is None:
        if "RepetitionTime" in sidecar:
            warn(
                f"{path}: ignoring sidecar RepetitionTime "
                f"{sidecar['RepetitionTime']!r} (expected a positive number of "
                f"seconds); using the NIfTI header TR {header_tr:g} s",
            )
        return header_tr

    header_is_usable = math.isfinite(header_tr) and header_tr > 0
    if header_is_usable and not math.isclose(sidecar_tr, header_tr, rel_tol=TR_RTOL):
        warn(
            f"{path}: sidecar RepetitionTime {sidecar_tr:g} s disagrees with the "
            f"NIfTI header TR {header_tr:g} s; using the sidecar value",
        )
    return sidecar_tr
