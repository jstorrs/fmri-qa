"""Repetition time resolution from the BIDS sidecar and NIfTI header.

The header TR arrives already in seconds, converted by its declared unit (see
`fmriqa_io.decode.nifti.tr_from_header`). The BIDS sidecar `RepetitionTime` is
defined to be seconds and wins whenever it is present.
"""

import math

from ..types import Sidecar
from ..warn import warn

__all__ = [
    "resolve_repetition_time",
]

# Fractional gap between the two sources worth a warning. They are the same
# number written twice, so anything past rounding noise means one is wrong.
TR_RTOL = 1e-3


def _positive_seconds(value: object) -> float | None:
    """Return `value` as positive, finite seconds, or None if it is neither."""
    # `isinstance(True, int)` is true, so exclude JSON booleans explicitly
    # instead of loading one as a 1 s TR.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) and value > 0 else None


def resolve_repetition_time(
    header_tr: float, sidecar: Sidecar, *, source: str
) -> float:
    """Resolve the TR in seconds, preferring the sidecar over the header.

    `header_tr` is pixdim[4] already converted to seconds by `xyzt_units`. The
    sidecar `RepetitionTime` wins when it is a positive, finite number;
    otherwise the header value is used. If both exist and disagree, the sidecar
    still wins (BIDS fixes its unit) but the mismatch warns with both values,
    since one file describes an acquisition that did not happen. Warnings name
    `source`, the scan they are about.
    """
    sidecar_tr = _positive_seconds(sidecar.get("RepetitionTime"))

    if sidecar_tr is None:
        if "RepetitionTime" in sidecar:
            warn(
                f"{source}: ignoring sidecar RepetitionTime "
                f"{sidecar['RepetitionTime']!r} (expected a positive number of "
                f"seconds); using the NIfTI header TR {header_tr:g} s",
            )
        return header_tr

    header_is_usable = math.isfinite(header_tr) and header_tr > 0
    if header_is_usable and not math.isclose(sidecar_tr, header_tr, rel_tol=TR_RTOL):
        warn(
            f"{source}: sidecar RepetitionTime {sidecar_tr:g} s disagrees with the "
            f"NIfTI header TR {header_tr:g} s; using the sidecar value",
        )
    return sidecar_tr
