"""`AnalysisSettings`: the record of what a run was asked for.

A leaf of its own, below every layer, because of who speaks it: the request is
common to the pipeline that honours it (`pipeline.run_qa`) and the artifact that
publishes it (`analysis.artifact.QAArtifact`), and reading an artifact must not
load the pipeline to name a type. Here it costs nothing but the shared
vocabulary.
"""

from dataclasses import dataclass

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
    """

    trim_sec: float = 5.0
    detrend: DetrendMethod = "poly"
    center: RoiCenter = "image"
    roi_size: int = FBIRN_ROI_SIZE
    pe_axis_override: PeAxis | None = None
    detrend_order: int | None = None
