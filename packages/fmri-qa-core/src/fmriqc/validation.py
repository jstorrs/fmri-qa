"""Validation at the boundary between loaded scans and numerical metrics.

The parameter domains are not here. `AnalysisSettings` holds its own knobs to
theirs, so a request that reaches this module is already one that could be
honoured by some scan; what is left is everything that is only true relative to
*this* scan -- its shape and samples, how many frames the trim leaves it, and
which axis the request and the header settle on between them.
"""

import numpy as np

from .exceptions import InvalidScanError
from .load.pe_axis import in_plane
from .load.scan import QAScan
from .prep.imaging import trim_count
from .settings import AnalysisSettings
from .types import PeAxis

MIN_ANALYSIS_FRAMES = 4


def validate_scan(scan: QAScan) -> None:
    """Validate the structure shared by the main and high/low pipelines."""
    if scan.data.ndim != 4:
        raise InvalidScanError(
            "data shape", scan.data.shape, "expected a 4-D (X, Y, Z, T) series"
        )
    if any(size < 1 for size in scan.data.shape[:3]):
        raise InvalidScanError(
            "spatial shape", scan.data.shape[:3], "every spatial axis must be non-empty"
        )
    if scan.data.shape[-1] < MIN_ANALYSIS_FRAMES:
        raise InvalidScanError(
            "frame count",
            scan.data.shape[-1],
            f"expected at least {MIN_ANALYSIS_FRAMES} frame(s)",
        )
    if not np.isfinite(scan.tr) or scan.tr <= 0:
        raise InvalidScanError(
            "TR", scan.tr, "expected a finite value greater than zero"
        )
    if not np.isfinite(scan.data).all():
        raise InvalidScanError(
            "data", "non-finite", "NaN and infinite samples are unsupported"
        )


def _validate_trim_sec(trim_sec: float) -> None:
    """Require a warm-up trim that names a real duration: the high/low path's copy.

    The single-slice path takes its trim inside an `AnalysisSettings`, which
    holds this domain itself; `run_hilo` takes a loose `trim_sec`, so this is
    the only place that trim is held to being a duration.
    """
    if not np.isfinite(trim_sec) or trim_sec < 0:
        raise InvalidScanError(
            "trim_sec",
            trim_sec,
            "expected a finite value greater than or equal to zero",
        )


def _frames_after_trim(scan: QAScan, trim_sec: float) -> int:
    """How many frames a `trim_sec` warm-up trim would leave of `scan`."""
    return int(scan.data.shape[-1]) - trim_count(tr=scan.tr, trim_sec=trim_sec)


def validate_qa_run(scan: QAScan, settings: AnalysisSettings) -> PeAxis | None:
    """Validate a scan against the request the single-slice QA pipeline got.

    The knobs themselves are already in their domains -- `AnalysisSettings`
    refuses a request that is not -- so what is checked here is what only the
    scan can answer: that the series is analyzable, and that the trim leaves
    enough of it behind.

    Returns the axis the request and the header settle on between them --
    `settings.pe_axis_override` if given, else `scan.pe_axis` narrowed to
    in-plane -- or None when neither names one. This is the one place that
    precedence is decided; `run_qa` falls back to the Nyquist-ghost estimate only
    when the return here is None.
    """
    validate_scan(scan)
    trim_sec = settings.trim_sec
    remaining = _frames_after_trim(scan, trim_sec)
    if remaining < MIN_ANALYSIS_FRAMES:
        raise InvalidScanError(
            "trim_sec",
            trim_sec,
            f"leaves {max(remaining, 0)} frames; "
            f"at least {MIN_ANALYSIS_FRAMES} are required",
        )

    override = settings.pe_axis_override
    candidate = scan.pe_axis if override is None else override
    if candidate is None:
        return None
    # `pe_axis_override` is already a `PeAxis`, so only `scan.pe_axis` -- the
    # header's own answer, read when no explicit axis is given -- can still name
    # the through-plane axis here. That scan is refused by name rather than
    # quietly analyzed on an axis estimated from the Nyquist ghost.
    resolved = in_plane(candidate)
    if resolved is None:
        raise InvalidScanError(
            "phase-encode axis",
            candidate,
            "the single-slice metrics support only in-plane axes 0 and 1",
        )
    return resolved


def validate_hilo_run(
    high: QAScan, low: QAScan, *, trim_sec: float, erode: int
) -> None:
    """Validate parameters shared by both sides of a high/low analysis."""
    validate_scan(high)
    validate_scan(low)
    _validate_trim_sec(trim_sec)
    if erode < 0:
        raise InvalidScanError(
            "erode", erode, "expected an integer greater than or equal to zero"
        )
    for label, scan in (("high", high), ("low", low)):
        remaining = _frames_after_trim(scan, trim_sec)
        if remaining < MIN_ANALYSIS_FRAMES:
            raise InvalidScanError(
                "trim_sec",
                trim_sec,
                f"leaves {max(remaining, 0)} {label}-flip frames; "
                f"at least {MIN_ANALYSIS_FRAMES} are required",
            )
