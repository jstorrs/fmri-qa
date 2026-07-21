"""Phantom fMRI quality-assurance metrics (SNR, SFNR, RDC, ghost, and more).

The public surface is re-exported here; the implementation lives in topical
subpackages (`ls` the package to find a concern):

* `load`      -- NIfTI + BIDS-sidecar I/O: `scan` (`QAScan`), `metadata`
                 (`ScanMeta`), `pe_axis` (phase-encode resolution)
* `prep`      -- preprocessing infrastructure: `imaging` (raw-array ops),
                 `detrend`, `geometry` (phantom/ROI), `images` (`QAImages`)
* `metrics`   -- the physics tests, one module per family: `fbirn`
                 (SNR/SFNR/RDC/drift), `artifacts` (spikes/outliers), `ghost`,
                 `saturation`, `motion`, `center_of_mass`, `smoothness`
* `pipeline`  -- `preprocess`, the full `run_qa` orchestration, and the
                 aggregate `QAMetrics`/`QAResult`
* `hilo`      -- high/low flip-angle thermal/instability separation (its own pipeline)
* `report`    -- multi-page reports (format-agnostic panels + a ReportLab driver)
* `types`     -- the shared array dtypes and option Literals

Everything named in `__all__` below is importable straight from `fmriqc`.
"""

import logging

from .exceptions import (
    FmriqcError,
    IncompatibleScansError,
    InvalidChoiceError,
    MissingSidecarError,
)
from .hilo import (
    HILO_ERODE,
    HiLoResult,
    phantom_core_mask,
    run_hilo,
    separate_noise,
)
from .load.metadata import ScanMeta
from .load.scan import QAScan
from .metrics.artifacts import (
    OutlierResult,
    SpikeResult,
    outlier_fraction,
    spike_scores,
)
from .metrics.center_of_mass import CenterOfMassResult, estimate_center_of_mass
from .metrics.fbirn import (
    WeisskoffResult,
    drift_percent,
    percent_fluctuation,
    sfnr,
    snr,
    weisskoff,
)
from .metrics.ghost import (
    GHOST_TOP_FRACTION,
    acr_ghosting_ratio,
    estimate_pe_axis,
    ghost_ratio,
    ghost_top_ratio,
    phase_encode_axis,
)
from .metrics.motion import MotionResult, estimate_motion
from .metrics.saturation import SaturationResult, detect_saturation
from .metrics.smoothness import SmoothnessResult, estimate_smoothness
from .pipeline import QAMetrics, QAResult, preprocess, run_qa
from .prep.detrend import (
    detrend_fn,
    poly_degree,
    poly_residuals,
    spline_nodes,
    spline_residuals,
)
from .prep.geometry import (
    FBIRN_ROI_SIZE,
    ROI,
    PhantomGeometry,
    detect_phantom,
    resolve_roi,
    roi_fits,
)
from .prep.images import QAImages
from .prep.imaging import (
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
from .types import (
    DETREND_METHODS,
    ROI_CENTER_MODES,
    DetrendMethod,
    RoiCenter,
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
