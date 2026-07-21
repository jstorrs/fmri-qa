"""Phantom fMRI quality-assurance metrics (SNR, SFNR, RDC, ghost, and more).

The public surface is re-exported here; the implementation lives in topical
modules (`ls` the package to find a concern):

* `scan` / `metadata`   -- load a NIfTI + BIDS sidecar into a `QAScan`
* `pipeline`            -- `preprocess` and the full `run_qa` orchestration
* `imaging`             -- low-level raw-array image operations
* `geometry`           -- phantom detection and ROI resolution
* `detrend`            -- polynomial / spline temporal detrending
* `noise`              -- FBIRN ROI metrics (SNR, SFNR, Weisskoff, spikes, ...)
* `ghost`              -- Nyquist ghost ratios and PE-axis estimation
* `saturation` / `motion` / `center_of_mass` / `smoothness` -- per-scan diagnostics
* `hilo`               -- high/low flip-angle thermal/instability separation
* `types`              -- the frozen dataclass value objects

Everything named in `__all__` below is importable straight from `fmriqc`.
"""

import logging

from .center_of_mass import estimate_center_of_mass
from .constants import (
    DETREND_METHODS,
    FBIRN_ROI_SIZE,
    GHOST_TOP_FRACTION,
    HILO_ERODE,
    ROI_CENTER_MODES,
    DetrendMethod,
    RoiCenter,
)
from .detrend import (
    detrend_fn,
    poly_degree,
    poly_residuals,
    spline_nodes,
    spline_residuals,
)
from .exceptions import (
    FmriqcError,
    IncompatibleScansError,
    InvalidChoiceError,
    MissingSidecarError,
)
from .geometry import detect_phantom, resolve_roi, roi_fits
from .ghost import (
    acr_ghosting_ratio,
    estimate_pe_axis,
    ghost_ratio,
    ghost_top_ratio,
    phase_encode_axis,
)
from .hilo import (
    HiLoResult,
    phantom_core_mask,
    run_hilo,
    separate_noise,
)
from .imaging import (
    edge_valid_mask,
    extract_center_slice,
    find_phantom_center,
    fluctuation_noise,
    image_center,
    odd_even_difference,
    roi_indexes,
    segment_phantom,
    trim_count,
    trim_initial,
)
from .motion import estimate_motion
from .noise import (
    drift_percent,
    outlier_fraction,
    percent_fluctuation,
    sfnr,
    snr,
    spike_scores,
    weisskoff,
)
from .pipeline import preprocess, run_qa
from .saturation import detect_saturation
from .scan import QAScan
from .smoothness import estimate_smoothness
from .types import (
    ROI,
    CenterOfMassResult,
    MotionResult,
    OutlierResult,
    PhantomGeometry,
    QAImages,
    QAMetrics,
    QAResult,
    SaturationResult,
    ScanMeta,
    SmoothnessResult,
    SpikeResult,
    WeisskoffResult,
)

# A library configures no handlers of its own (see style/logging.md).
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "DETREND_METHODS",
    "FBIRN_ROI_SIZE",
    "GHOST_TOP_FRACTION",
    "HILO_ERODE",
    "ROI",
    "ROI_CENTER_MODES",
    "CenterOfMassResult",
    "DetrendMethod",
    "FmriqcError",
    "HiLoResult",
    "IncompatibleScansError",
    "InvalidChoiceError",
    "MissingSidecarError",
    "MotionResult",
    "OutlierResult",
    "PhantomGeometry",
    "QAImages",
    "QAMetrics",
    "QAResult",
    "QAScan",
    "RoiCenter",
    "SaturationResult",
    "ScanMeta",
    "SmoothnessResult",
    "SpikeResult",
    "WeisskoffResult",
    "acr_ghosting_ratio",
    "detect_phantom",
    "detect_saturation",
    "detrend_fn",
    "drift_percent",
    "edge_valid_mask",
    "estimate_center_of_mass",
    "estimate_motion",
    "estimate_pe_axis",
    "estimate_smoothness",
    "extract_center_slice",
    "find_phantom_center",
    "fluctuation_noise",
    "ghost_ratio",
    "ghost_top_ratio",
    "image_center",
    "odd_even_difference",
    "outlier_fraction",
    "percent_fluctuation",
    "phantom_core_mask",
    "phase_encode_axis",
    "poly_degree",
    "poly_residuals",
    "preprocess",
    "resolve_roi",
    "roi_fits",
    "roi_indexes",
    "run_hilo",
    "run_qa",
    "segment_phantom",
    "separate_noise",
    "sfnr",
    "snr",
    "spike_scores",
    "spline_nodes",
    "spline_residuals",
    "trim_count",
    "trim_initial",
    "weisskoff",
]
