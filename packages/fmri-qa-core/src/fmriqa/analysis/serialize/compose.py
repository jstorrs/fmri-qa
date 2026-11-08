"""Rebuild a `QAAnalysis` from its JSON document and named arrays.

The read half of the archive layout, mirroring `decompose`. Besides assembling
the value objects, it checks each array member for the dtype its field is
declared with (`_floats`, `_bools`). The document's own fields, closed-set
strings included, are not re-checked here. `fmriqa_io.load_analysis` runs
`validate_document` first, so `compose` trusts what it is handed.
"""

from collections.abc import Mapping
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ...settings import AnalysisSettings
from ...types import BoolArray, FloatArray
from ..values import (
    Curves,
    GhostRegions,
    Measurements,
    Provenance,
    PsfCurves,
    QAAnalysis,
    RoiBox,
    SummaryImages,
    WeisskoffCurve,
)

# Provenance fields stored as JSON lists that must come back as tuples.
_PROVENANCE_TUPLES = ("voxel_mm", "matrix")


def _floats(arrays: Mapping[str, NDArray[Any]], key: str) -> FloatArray:
    """Return a required float array member."""
    if arrays[key].dtype.kind not in "fiu":
        raise ValueError(f"{key} must be a real numeric array")
    return np.asarray(arrays[key], dtype=np.float64)


def _bools(arrays: Mapping[str, NDArray[Any]], key: str) -> BoolArray:
    """Return a required boolean mask member."""
    if arrays[key].dtype != np.bool_:
        raise ValueError(f"{key} must be a boolean mask")
    return np.asarray(arrays[key], dtype=np.bool_)


def compose(document: dict[str, Any], arrays: Mapping[str, NDArray[Any]]) -> QAAnalysis:
    """Rebuild an analysis file from its JSON document and named arrays."""
    provenance = dict(document["provenance"])
    for field in _PROVENANCE_TUPLES:
        if provenance.get(field) is not None:
            provenance[field] = tuple(provenance[field])
    measurements = dict(document["measurements"])
    return QAAnalysis(
        settings=AnalysisSettings(**document["settings"]),
        provenance=Provenance(**provenance),
        measurements=Measurements(**measurements),
        curves=_curves_section(document["curves"], arrays),
        images=_images_section(document["images"], arrays),
    )


def _curves_section(
    document: dict[str, Any], arrays: Mapping[str, NDArray[Any]]
) -> Curves:
    """Rebuild the curve section."""
    psf = document["psf"]
    labels = tuple(psf["labels"])
    fwhm = tuple(float(v) for v in psf["fwhm"])
    return Curves(
        time=_floats(arrays, "curves.time"),
        roi_signal=_floats(arrays, "curves.roi_signal"),
        roi_trend=_floats(arrays, "curves.roi_trend"),
        roi_residual=_floats(arrays, "curves.roi_residual"),
        outlier_fraction=_floats(arrays, "curves.outlier_fraction"),
        outlier_qthr=float(document["outlier_qthr"]),
        spectrum_hz=_floats(arrays, "curves.spectrum_hz"),
        spectrum_magnitude=_floats(arrays, "curves.spectrum_magnitude"),
        translation=_floats(arrays, "curves.translation"),
        scale_pct=_floats(arrays, "curves.scale_pct"),
        shear_pct=_floats(arrays, "curves.shear_pct"),
        com_deviation=_floats(arrays, "curves.com_deviation"),
        weisskoff=WeisskoffCurve(
            roi_sizes=_floats(arrays, "curves.weisskoff.roi_sizes"),
            cv=_floats(arrays, "curves.weisskoff.cv"),
            cv_ideal=_floats(arrays, "curves.weisskoff.cv_ideal"),
            rdc=_floats(arrays, "curves.weisskoff.rdc"),
        ),
        psf=PsfCurves(
            labels=(labels[0], labels[1]),
            fwhm=(fwhm[0], fwhm[1]),
            unit=psf["unit"],
            displacement=_floats(arrays, "curves.psf.displacement"),
            empirical=_floats(arrays, "curves.psf.empirical"),
            model_x=_floats(arrays, "curves.psf.model_x"),
            model=_floats(arrays, "curves.psf.model"),
            xmax=float(psf["xmax"]),
        ),
    )


def _images_section(
    document: dict[str, Any], arrays: Mapping[str, NDArray[Any]]
) -> SummaryImages:
    """Rebuild the image section."""
    ghost = None
    if document["has_ghost"]:
        ghost = GhostRegions(
            pe_signal=_bools(arrays, "images.ghost.pe_signal"),
            pe_ghost=_bools(arrays, "images.ghost.pe_ghost"),
            ro_signal=_bools(arrays, "images.ghost.ro_signal"),
            ro_ghost=_bools(arrays, "images.ghost.ro_ghost"),
        )
    return SummaryImages(
        signal=_floats(arrays, "images.signal"),
        sfnr=_floats(arrays, "images.sfnr"),
        fluctuation_noise=_floats(arrays, "images.fluctuation_noise"),
        static_noise=_floats(arrays, "images.static_noise"),
        phantom_mask=_bools(arrays, "images.phantom_mask"),
        invalid_mask=_bools(arrays, "images.invalid_mask"),
        phantom_hull=_floats(arrays, "images.phantom_hull"),
        roi=RoiBox(**document["roi"]),
        ghost=ghost,
    )
