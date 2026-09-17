"""`AnalysisSettings`: the record of what a run was asked for.

A leaf of its own, below every layer, because of who speaks it: the request is
common to the pipeline that honours it (`pipeline.run_qa`) and the artifact that
publishes it (`analysis.artifact.QAArtifact`), and reading an artifact must not
load the pipeline to name a type. Here it costs nothing but the shared
vocabulary.
"""

import math
from dataclasses import dataclass

from .exceptions import InvalidScanError
from .types import FBIRN_ROI_SIZE, DetrendMethod, PeAxis, RoiCenter


@dataclass(frozen=True, slots=True)
class AnalysisSettings:
    """The analysis knobs: what the run was asked for, and what that resolved to.

    The first five fields are the request — this record is what `run_qa`,
    `preprocess` and `analyze` take, so re-running with it reproduces the result.
    `roi_size` is the side *asked for*; the side actually analyzed (the same,
    unless the image is smaller) is the ROI the result carries. `detrend_order`
    is the one *resolved* value (the polynomial degree or the spline
    interior-knot count the detrender chose for this series length), recorded
    because it is a run parameter a reader must be able to report but only the
    pipeline knows. A request handed in already carrying one — a published
    record fed back to reproduce its run — is accepted, and the order the new
    run resolves overwrites it.

    `run_qa` writes this record onto its `QAResult`, so an artifact built from
    a result publishes the settings that result was computed with — never a
    default filled in afterwards.

    The knob domains are held by the constructor, not by a validator: a trim
    that names a real duration, a positive ROI side, and a detrend order that is
    absent or non-negative are an `InvalidScanError` when they are not, so
    holding an `AnalysisSettings` means the run it asks for is one that could be
    honoured. `run_qa`'s `replace(settings, detrend_order=...)` passes through
    the same door, so the order a run resolves is held to the same domain as one
    a caller hands in.
    """

    trim_sec: float = 5.0
    detrend: DetrendMethod = "poly"
    center: RoiCenter = "image"
    roi_size: int = FBIRN_ROI_SIZE
    pe_axis_override: PeAxis | None = None
    detrend_order: int | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.trim_sec) or self.trim_sec < 0:
            raise InvalidScanError(
                "trim_sec",
                self.trim_sec,
                "expected a finite value greater than or equal to zero",
            )
        if self.roi_size <= 0:
            raise InvalidScanError(
                "roi_size", self.roi_size, "expected a positive integer"
            )
        if self.detrend_order is not None and self.detrend_order < 0:
            raise InvalidScanError(
                "detrend_order",
                self.detrend_order,
                "expected an integer greater than or equal to zero",
            )
