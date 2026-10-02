"""Phantom fMRI quality-assurance metrics (SNR, SFNR, RDC, ghost, and more).

The public surface is re-exported here; the implementation lives in topical
subpackages (`ls` the package to find a concern):

* `convert`   -- DICOM -> NIfTI import: `dcm2niix` (running the converter
                 with the flags a QA series cannot be converted without),
                 `naming` (the date/time/series/description file name), and
                 `session` (`import_dicom`: a directory in, named series out)
* `load`      -- NIfTI + BIDS-sidecar I/O: `scan` (`QAScan`), `metadata`
                 (`ScanMeta`), `pe_axis` (phase-encode resolution),
                 `repetition_time` (TR resolution)
* `prep`      -- preprocessing infrastructure: `imaging` (raw-array ops),
                 `detrend`, `geometry` (phantom/ROI), `images` (`QAImages`),
                 `scale` (`VoxelSize`: the in-plane voxel size, and the unit
                 every length measured against it carries)
* `metrics`   -- the physics tests, one module per family: `fbirn`
                 (SNR/SFNR/RDC/drift), `artifacts` (spikes/outliers), `ghost`
                 (`estimate_ghost`: the whole Nyquist-ghost family off one build
                 of the region-matched masks, which the result carries;
                 `ghost_ratios`/`estimate_pe_axis` score and pick a PE axis
                 before one is settled), `saturation`, `motion`,
                 `center_of_mass`, `smoothness`
* `pipeline`  -- `preprocess`, the full `run_qa` orchestration, and the
                 aggregate `QAMetrics`/`QAResult`
* `analysis`  -- the publishable `QAArtifact`: `artifact` (the value objects),
                 `build` (`analyze`: scan -> artifact), `validation` (the
                 contract), and `serialize` (the netCDF-4 on-disk form, with
                 the per-version migrations that keep an old archive readable)
* `hilo`      -- high/low flip-angle thermal/instability separation (its own pipeline)
* `cli`       -- the three commands (`fmri-qa`, `fmri-qa-hilo`,
                 `fmri-qa-import`) and the two forms the analyzing two report
                 in: the fixed-width `table` and the JSON `record`
* `types`     -- the shared array dtypes and option Literals
* `settings`  -- `AnalysisSettings`, the record of what a run was asked for

This package is the *calculation* half of fmri-qa. Reports and plots live in the
separate `fmri-qa-report` distribution, which consumes a `QAArtifact` and never
imports the layers above.

Everything named in `__all__` below is importable straight from `fmriqc`.

Every one of those names, though, is re-exported *lazily*: this module defines
no eager `from .x import Y` at all. Reaching just far enough to build an
`argparse.ArgumentParser` -- `--version`, `--help`, a bad flag -- used to pay
for every subpackage's imports, scipy and scikit-image included, before a
single argument was parsed. `__getattr__` below (PEP 562) resolves a name to
its owning module and imports that module -- and only that module's chain --
on first access, so `import fmriqc` stays cheap and the cost lands on the call
site that actually uses the name. `_EXPORTS` is the map from defining module to
the names it contributes; `test_lazy_imports.py` asserts its flattened contents
equal `__all__` exactly, so the two cannot silently drift apart.
"""

import logging
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Import statements kept verbatim (not the lazy `_EXPORTS` map below) so
    # mypy and pyright resolve every name statically; never executed at runtime.
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
        load_artifact,
        save_artifact,
    )
    from .convert.session import ImportedSeries, ImportResult, import_dicom
    from .exceptions import (
        ConversionError,
        FmriqcError,
        IncompatibleScansError,
        InvalidArtifactError,
        InvalidChoiceError,
        InvalidScanError,
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
        GhostResult,
        estimate_ghost,
        estimate_pe_axis,
        ghost_masks,
        ghost_ratio,
        ghost_ratios,
    )
    from .metrics.motion import MotionResult, estimate_motion
    from .metrics.saturation import ClipRail, SaturationResult, detect_saturation
    from .metrics.smoothness import SmoothnessResult, estimate_smoothness
    from .pipeline import QAMetrics, QAResult, preprocess, run_qa
    from .prep.detrend import (
        Detrender,
        poly_degree,
        poly_residuals,
        spline_nodes,
        spline_residuals,
    )
    from .prep.geometry import (
        ROI,
        PhantomGeometry,
        detect_phantom,
        resolve_roi,
        roi_fits,
    )
    from .prep.images import QAImages
    from .prep.imaging import (
        edge_valid_mask,
        find_phantom_center,
        fluctuation_noise,
        image_center,
        odd_even_difference,
        phantom_area,
        phantom_contrast,
        phantom_plausible,
        roi_indexes,
        segment_phantom,
        select_slice,
        trim_count,
        trim_initial,
    )
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
    "GHOST_TOP_FRACTION",
    "HILO_ERODE",
    "NAME_STYLES",
    "PE_AXES",
    "PE_ROWCOL",
    "ROI",
    "ROI_CENTER_MODES",
    "AnalysisSettings",
    "Anonymize",
    "ArtifactImages",
    "CenterOfMassResult",
    "ClipRail",
    "ConversionError",
    "Curves",
    "DetrendMethod",
    "Detrender",
    "FmriqcError",
    "GhostRegions",
    "GhostResult",
    "HiLoResult",
    "ImportResult",
    "ImportedSeries",
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
    "edge_valid_mask",
    "estimate_center_of_mass",
    "estimate_ghost",
    "estimate_motion",
    "estimate_pe_axis",
    "estimate_smoothness",
    "find_phantom_center",
    "fluctuation_noise",
    "ghost_masks",
    "ghost_ratio",
    "ghost_ratios",
    "image_center",
    "import_dicom",
    "load_artifact",
    "odd_even_difference",
    "outlier_fraction",
    "percent_fluctuation",
    "phantom_area",
    "phantom_contrast",
    "phantom_core_mask",
    "phantom_plausible",
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
    "select_slice",
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

# Single source of truth for the lazy re-export: which submodule defines each
# name in `__all__`. Keyed by module path (not name) so one dict entry covers
# a whole `from .x import (...)` block, mirroring the import statements above.
# `test_lazy_imports.py` asserts this flattens to exactly `__all__` -- the
# check that stops the two from drifting apart the way two hand-kept lists would.
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
        "load_artifact",
        "save_artifact",
    ),
    ".convert.session": ("ImportResult", "ImportedSeries", "import_dicom"),
    ".exceptions": (
        "ConversionError",
        "FmriqcError",
        "IncompatibleScansError",
        "InvalidArtifactError",
        "InvalidChoiceError",
        "InvalidScanError",
    ),
    ".hilo": (
        "HILO_ERODE",
        "HiLoResult",
        "phantom_core_mask",
        "run_hilo",
        "separate_noise",
    ),
    ".load.metadata": ("ScanMeta",),
    ".load.pe_axis": ("PE_ROWCOL",),
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
        "GHOST_TOP_FRACTION",
        "GhostResult",
        "estimate_ghost",
        "estimate_pe_axis",
        "ghost_masks",
        "ghost_ratio",
        "ghost_ratios",
    ),
    ".metrics.motion": ("MotionResult", "estimate_motion"),
    ".metrics.saturation": ("ClipRail", "SaturationResult", "detect_saturation"),
    ".metrics.smoothness": ("SmoothnessResult", "estimate_smoothness"),
    ".pipeline": ("QAMetrics", "QAResult", "preprocess", "run_qa"),
    ".prep.detrend": (
        "Detrender",
        "poly_degree",
        "poly_residuals",
        "spline_nodes",
        "spline_residuals",
    ),
    ".prep.geometry": (
        "ROI",
        "PhantomGeometry",
        "detect_phantom",
        "resolve_roi",
        "roi_fits",
    ),
    ".prep.images": ("QAImages",),
    ".prep.imaging": (
        "edge_valid_mask",
        "find_phantom_center",
        "fluctuation_noise",
        "image_center",
        "odd_even_difference",
        "phantom_area",
        "phantom_contrast",
        "phantom_plausible",
        "roi_indexes",
        "segment_phantom",
        "select_slice",
        "trim_count",
        "trim_initial",
    ),
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

# Built once from `_EXPORTS`, never hand-maintained: the reverse lookup
# `__getattr__` needs to find a name's owning module in O(1).
_NAME_TO_MODULE: dict[str, str] = {
    name: module for module, names in _EXPORTS.items() for name in names
}


def __getattr__(name: str) -> object:
    """Resolve `fmriqc.<name>` by importing its owning module on first access.

    Caches the result as a module global (assigning into `globals()`), so this
    runs at most once per name -- every later access is a plain attribute
    lookup, same as an eager re-export.
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
