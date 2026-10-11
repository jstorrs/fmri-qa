"""`AnalysisSettings`: the record of what a run was asked for.

A leaf module below every layer. Both the pipeline that honors the request
(`pipeline.run_qa`) and the artifact that publishes it
(`analysis.artifact.QAArtifact`) use it, and reading an artifact must not load
the pipeline just to name a type.
"""

import math
from dataclasses import dataclass

from ._records import coerce_float_fields
from .exceptions import InvalidScanError
from .types import FBIRN_ROI_SIZE, DetrendMethod, PeAxis, RoiCenter


@dataclass(frozen=True, slots=True)
class AnalysisSettings:
    """The analysis knobs: what a run was asked for and what that resolved to.

    The first five fields are the request. `run_qa`, `preprocess` and `analyze`
    take this record, so re-running with it reproduces the result. `roi_size` is
    the side asked for; the side actually analyzed (the same unless the image is
    smaller) is the ROI the result carries. `detrend_order` is the one resolved
    value: the polynomial degree or spline interior-knot count the detrender
    chose for this series length. A reader needs it but only the pipeline knows
    it. A request that already carries one, such as a published record fed back
    to reproduce its run, is accepted, and the order the new run resolves
    overwrites it.

    `run_qa` writes this record onto its `QAResult`, so an artifact built from a
    result publishes the settings it was computed with, never a default filled
    in afterwards.

    The constructor raises `InvalidScanError` unless `trim_sec` is a finite
    non-negative duration, `roi_size` is positive, and `detrend_order` is absent
    or non-negative. Holding an `AnalysisSettings` therefore means the run can
    be honored. `run_qa`'s `replace(settings, detrend_order=...)` goes through
    the same check.
    """

    trim_sec: float = 5.0
    detrend: DetrendMethod = "poly"
    center: RoiCenter = "image"
    roi_size: int = FBIRN_ROI_SIZE
    pe_axis_override: PeAxis | None = None
    detrend_order: int | None = None

    def __post_init__(self) -> None:
        """Coerce floats; refuse a bad `trim_sec`, `roi_size` or `detrend_order`."""
        coerce_float_fields(self)
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
