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
* `analysis`  -- the publishable `QAArtifact`: `analyze` (scan -> artifact) and
                 `save_artifact`/`load_artifact` (the `.npz` on-disk form)
* `hilo`      -- high/low flip-angle thermal/instability separation (its own pipeline)
* `types`     -- the shared array dtypes and option Literals

This package is the *calculation* half of fmri-qa. Reports and plots live in the
separate `fmri-qa-report` distribution, which consumes a `QAArtifact` and never
imports the layers above.

Everything named in `__all__` below is importable straight from `fmriqc`.
"""

import logging

from .analysis import (
    ARTIFACT_SCHEMA_VERSION,
    AnalysisSettings,
    ArtifactImages,
    Curves,
    GhostRegions,
    Measurements,
    Provenance,
    PsfCurves,
    QAArtifact,
    RoiBox,
    WeisskoffCurve,
    analyze,
    build_artifact,
    core_version,
    load_artifact,
    save_artifact,
)
from .exceptions import (
    FmriqcError,
    IncompatibleScansError,
    InvalidArtifactError,
    InvalidChoiceError,
    InvalidScanError,
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
from .load.pe_axis import PE_ROWCOL
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
    GHOST_RADIUS,
    GHOST_TOP_FRACTION,
    acr_ghosting_ratio,
    estimate_pe_axis,
    ghost_masks,
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
    phantom_area,
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
    "ARTIFACT_SCHEMA_VERSION",
    "DETREND_METHODS",
    "FBIRN_ROI_SIZE",
    "GHOST_RADIUS",
    "GHOST_TOP_FRACTION",
    "HILO_ERODE",
    "PE_ROWCOL",
    "ROI",
    "ROI_CENTER_MODES",
    "AnalysisSettings",
    "ArtifactImages",
    "CenterOfMassResult",
    "Curves",
    "DetrendMethod",
    "FmriqcError",
    "GhostRegions",
    "HiLoResult",
    "IncompatibleScansError",
    "InvalidArtifactError",
    "InvalidChoiceError",
    "InvalidScanError",
    "Measurements",
    "MissingSidecarError",
    "MotionResult",
    "OutlierResult",
    "PhantomGeometry",
    "Provenance",
    "PsfCurves",
    "QAArtifact",
    "QAImages",
    "QAMetrics",
    "QAResult",
    "QAScan",
    "RoiBox",
    "RoiCenter",
    "SaturationResult",
    "ScanMeta",
    "SmoothnessResult",
    "SpikeResult",
    "WeisskoffCurve",
    "WeisskoffResult",
    "acr_ghosting_ratio",
    "analyze",
    "build_artifact",
    "core_version",
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
    "ghost_masks",
    "ghost_ratio",
    "ghost_top_ratio",
    "image_center",
    "load_artifact",
    "odd_even_difference",
    "outlier_fraction",
    "percent_fluctuation",
    "phantom_area",
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
    "save_artifact",
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
