"""Phantom fMRI quality-assurance metrics (SNR, SFNR, RDC, ghost and more).

The root exports the analysis chain (`QAScan`, `analyze`, `run_qa`, the
metric estimators), its result and value types, the exceptions,
and the shared option types. Helpers live in their subpackages; import them
from there (`fmriqa.prep.geometry`, `fmriqa.metrics.ghost`, ...).

This package is the calculation half of fmri-qa. Reports and plots live in the
separate `fmri-qa-report` distribution, which consumes a `QAArtifact` and never
imports the layers above.

Every name in `__all__` is re-exported lazily, so this module has no eager
`from .x import Y`. Otherwise building an `argparse.ArgumentParser`
(`--version`, `--help`, a bad flag) would import every subpackage, scipy and
scikit-image included, before parsing an argument. `__getattr__` (PEP 562)
imports a name's owning module on first access, so `import fmriqa` stays cheap.
`_EXPORTS` maps each defining module to its names, and `test_lazy_imports.py`
asserts it flattens to exactly `__all__`.
"""

import logging
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Plain imports, not the lazy `_EXPORTS` map below, so mypy and pyright
    # resolve every name statically. Never executed at runtime.
    from .analysis import (
        ARTIFACT_SCHEMA_VERSION,
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
    )
    from .exceptions import (
        FmriqaError,
        IncompatibleScansError,
        InvalidArtifactError,
        InvalidChoiceError,
        InvalidScanError,
    )
    from .hilo import (
        HILO_ERODE,
        HiLoResult,
        run_hilo,
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
        GHOST_RADIUS,
        GhostResult,
        estimate_ghost,
        estimate_pe_axis,
    )
    from .metrics.motion import MotionResult, estimate_motion
    from .metrics.saturation import ClipRail, SaturationResult, detect_saturation
    from .metrics.smoothness import SmoothnessResult, estimate_smoothness
    from .pipeline import QAMetrics, QAResult, preprocess, run_qa
    from .prep.detrend import (
        Detrender,
    )
    from .prep.geometry import (
        ROI,
        PhantomGeometry,
        detect_phantom,
        resolve_roi,
    )
    from .prep.images import QAImages
    from .prep.scale import VoxelSize
    from .settings import AnalysisSettings
    from .types import (
        ANONYMIZE_MODES,
        DETREND_METHODS,
        FBIRN_ROI_SIZE,
        NAME_STYLES,
        PE_AXES,
        ROI_CENTER_MODES,
        Anonymize,
        DetrendMethod,
        NameStyle,
        PeAxis,
        RoiCenter,
    )
    from .version import core_version

# A library configures no handlers of its own (see style/logging.md).
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "ANONYMIZE_MODES",
    "ARTIFACT_SCHEMA_VERSION",
    "DETREND_METHODS",
    "FBIRN_ROI_SIZE",
    "GHOST_RADIUS",
    "HILO_ERODE",
    "NAME_STYLES",
    "PE_AXES",
    "ROI",
    "ROI_CENTER_MODES",
    "AnalysisSettings",
    "Anonymize",
    "ArtifactImages",
    "CenterOfMassResult",
    "ClipRail",
    "Curves",
    "DetrendMethod",
    "Detrender",
    "FmriqaError",
    "GhostRegions",
    "GhostResult",
    "HiLoResult",
    "IncompatibleScansError",
    "InvalidArtifactError",
    "InvalidChoiceError",
    "InvalidScanError",
    "Measurements",
    "MotionResult",
    "NameStyle",
    "OutlierResult",
    "PeAxis",
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
    "VoxelSize",
    "WeisskoffCurve",
    "WeisskoffResult",
    "analyze",
    "build_artifact",
    "core_version",
    "detect_phantom",
    "detect_saturation",
    "drift_percent",
    "estimate_center_of_mass",
    "estimate_ghost",
    "estimate_motion",
    "estimate_pe_axis",
    "estimate_smoothness",
    "outlier_fraction",
    "percent_fluctuation",
    "preprocess",
    "resolve_roi",
    "run_hilo",
    "run_qa",
    "sfnr",
    "snr",
    "spike_scores",
    "weisskoff",
]

# Which submodule defines each name in `__all__`, keyed by module path so one
# entry mirrors one `from .x import (...)` block above.
_EXPORTS: dict[str, tuple[str, ...]] = {
    ".analysis": (
        "ARTIFACT_SCHEMA_VERSION",
        "ArtifactImages",
        "Curves",
        "GhostRegions",
        "Measurements",
        "Provenance",
        "PsfCurves",
        "QAArtifact",
        "RoiBox",
        "WeisskoffCurve",
        "analyze",
        "build_artifact",
    ),
    ".exceptions": (
        "FmriqaError",
        "IncompatibleScansError",
        "InvalidArtifactError",
        "InvalidChoiceError",
        "InvalidScanError",
    ),
    ".hilo": (
        "HILO_ERODE",
        "HiLoResult",
        "run_hilo",
    ),
    ".load.metadata": ("ScanMeta",),
    ".load.scan": ("QAScan",),
    ".metrics.artifacts": (
        "OutlierResult",
        "SpikeResult",
        "outlier_fraction",
        "spike_scores",
    ),
    ".metrics.center_of_mass": ("CenterOfMassResult", "estimate_center_of_mass"),
    ".metrics.fbirn": (
        "WeisskoffResult",
        "drift_percent",
        "percent_fluctuation",
        "sfnr",
        "snr",
        "weisskoff",
    ),
    ".metrics.ghost": (
        "GHOST_RADIUS",
        "GhostResult",
        "estimate_ghost",
        "estimate_pe_axis",
    ),
    ".metrics.motion": ("MotionResult", "estimate_motion"),
    ".metrics.saturation": ("ClipRail", "SaturationResult", "detect_saturation"),
    ".metrics.smoothness": ("SmoothnessResult", "estimate_smoothness"),
    ".pipeline": ("QAMetrics", "QAResult", "preprocess", "run_qa"),
    ".prep.detrend": ("Detrender",),
    ".prep.geometry": (
        "ROI",
        "PhantomGeometry",
        "detect_phantom",
        "resolve_roi",
    ),
    ".prep.images": ("QAImages",),
    ".prep.scale": ("VoxelSize",),
    ".settings": ("AnalysisSettings",),
    ".version": ("core_version",),
    ".types": (
        "ANONYMIZE_MODES",
        "DETREND_METHODS",
        "FBIRN_ROI_SIZE",
        "NAME_STYLES",
        "PE_AXES",
        "ROI_CENTER_MODES",
        "Anonymize",
        "DetrendMethod",
        "NameStyle",
        "PeAxis",
        "RoiCenter",
    ),
}

# Reverse lookup of `_EXPORTS`, for `__getattr__`.
_NAME_TO_MODULE: dict[str, str] = {
    name: module for module, names in _EXPORTS.items() for name in names
}


def __getattr__(name: str) -> object:
    """Resolve `fmriqa.<name>` by importing its owning module on first access.

    Caches the result as a module global (assigning into `globals()`), so this
    runs at most once per name. Later accesses are plain attribute lookups, as
    with an eager re-export.
    """
    try:
        module_path = _NAME_TO_MODULE[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module_path, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the public names, matching what an eager module would show."""
    return sorted(__all__)
