"""Validation at the boundary between loaded scans and numerical metrics."""

import numpy as np

from .exceptions import InvalidScanError
from .load.pe_axis import in_plane
from .load.scan import QAScan
from .prep.imaging import trim_count
from .types import PeAxis

MIN_ANALYSIS_FRAMES = 4


def validate_scan(scan: QAScan, *, minimum_frames: int = 1) -> None:
    """Validate the structure shared by the main and high/low pipelines."""
    if scan.data.ndim != 4:
        raise InvalidScanError(
            "data shape", scan.data.shape, "expected a 4-D (X, Y, Z, T) series"
        )
    if any(size < 1 for size in scan.data.shape[:3]):
        raise InvalidScanError(
            "spatial shape", scan.data.shape[:3], "every spatial axis must be non-empty"
        )
    if scan.data.shape[-1] < minimum_frames:
        raise InvalidScanError(
            "frame count",
            scan.data.shape[-1],
            f"expected at least {minimum_frames} frame(s)",
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
    """Require a warm-up trim that names a real duration."""
    if not np.isfinite(trim_sec) or trim_sec < 0:
        raise InvalidScanError(
            "trim_sec",
            trim_sec,
            "expected a finite value greater than or equal to zero",
        )


def _frames_after_trim(scan: QAScan, trim_sec: float) -> int:
    """How many frames a `trim_sec` warm-up trim would leave of `scan`."""
    return int(scan.data.shape[-1]) - trim_count(tr=scan.tr, trim_sec=trim_sec)


def validate_qa_run(
    scan: QAScan, *, trim_sec: float, roi_size: int, pe_axis: PeAxis | None
) -> None:
    """Validate parameters required by the single-slice QA pipeline."""
    validate_scan(scan, minimum_frames=MIN_ANALYSIS_FRAMES)
    _validate_trim_sec(trim_sec)
    if roi_size <= 0:
        raise InvalidScanError("roi_size", roi_size, "expected a positive integer")

    remaining = _frames_after_trim(scan, trim_sec)
    if remaining < MIN_ANALYSIS_FRAMES:
        raise InvalidScanError(
            "trim_sec",
            trim_sec,
            f"leaves {max(remaining, 0)} frames; "
            f"at least {MIN_ANALYSIS_FRAMES} are required",
        )

    resolved_pe = scan.pe_axis if pe_axis is None else pe_axis
    # `pe_axis` is already a `PeAxis`, so only `scan.pe_axis` -- the header's own
    # answer, read when no explicit axis is given -- can still name the
    # through-plane axis here. That scan is refused by name rather than quietly
    # analyzed on an axis estimated from the Nyquist ghost.
    if resolved_pe is not None and in_plane(resolved_pe) is None:
        raise InvalidScanError(
            "phase-encode axis",
            resolved_pe,
            "the single-slice metrics support only in-plane axes 0 and 1",
        )


def validate_hilo_run(
    high: QAScan, low: QAScan, *, trim_sec: float, erode: int
) -> None:
    """Validate parameters shared by both sides of a high/low analysis."""
    validate_scan(high, minimum_frames=MIN_ANALYSIS_FRAMES)
    validate_scan(low, minimum_frames=MIN_ANALYSIS_FRAMES)
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
