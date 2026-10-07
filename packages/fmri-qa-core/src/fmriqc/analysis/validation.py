"""Validate the published artifact contract at the archive boundary.

Half the contract is not here. An invariant of one record alone is held by that
value object's own constructor (`AnalysisSettings`, `Provenance`,
`Measurements` and `RoiBox` hold their own today), because an artifact built
in-process and printed or rendered is never saved and so never reaches this
module: a new single-record invariant added here would go unchecked for every
consumer but the archive. What is left here is what a constructor cannot see —
facts that span two records (`displacement_unit` against `provenance.voxel_mm`,
`outlier_worst_frame` against `provenance.n_frames`, the ROI box against the
image it sits on), and everything about arrays: their dimensions, shapes and
coordinates.

Scalar types follow the value objects; dimensional relationships and numeric
domains are checked explicitly. NaN/Infinity measurements remain meaningful,
but coordinates and counts must be usable.
"""

import math
from dataclasses import fields
from typing import Any, Literal, get_args, get_origin

import numpy as np

from .._records import UNIONS, resolved_annotations
from ..settings import AnalysisSettings
from .artifact import (
    Curves,
    Measurements,
    Provenance,
    PsfCurves,
    QAArtifact,
    RoiBox,
    _require,
)


def _matches(value: object, annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin in UNIONS:
        return any(_matches(value, choice) for choice in get_args(annotation))
    if origin is Literal:
        return any(type(value) is type(v) and value == v for v in get_args(annotation))
    if origin is tuple:
        args = get_args(annotation)
        return (
            isinstance(value, list | tuple)
            and len(value) == len(args)
            and all(_matches(v, t) for v, t in zip(value, args, strict=True))
        )
    if annotation is float:
        return type(value) in (int, float)
    return type(value) is annotation


def _object(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return {str(k): v for k, v in value.items()}


def validate_document(document: dict[str, Any]) -> None:
    """Check scalar records before constructors or coercions can conceal errors."""
    images = _object(document["images"], "images")
    curves = _object(document["curves"], "curves")
    records = (
        ("settings", document["settings"], AnalysisSettings),
        ("provenance", document["provenance"], Provenance),
        ("measurements", document["measurements"], Measurements),
        ("images.roi", images["roi"], RoiBox),
    )
    for name, value, cls in records:
        record = _object(value, name)
        annotations = resolved_annotations(cls)
        for field in fields(cls):
            if not _matches(record[field.name], annotations[field.name]):
                raise ValueError(f"{name}.{field.name} has an invalid type or value")
    if type(images["has_ghost"]) is not bool:
        raise ValueError("images.has_ghost must be boolean")
    psf = _object(curves["psf"], "curves.psf")
    psf_annotations = resolved_annotations(PsfCurves)
    for name in ("labels", "fwhm", "xmax", "unit"):
        if not _matches(psf[name], psf_annotations[name]):
            raise ValueError(f"curves.psf.{name} has an invalid type or length")
    if not _matches(
        curves["outlier_qthr"], resolved_annotations(Curves)["outlier_qthr"]
    ):
        raise ValueError("curves.outlier_qthr must be numeric")


def validate_artifact(artifact: QAArtifact) -> None:
    """Require coherent settings, dimensions and coordinates after composition."""
    _validate_parameters(artifact)
    _validate_timeseries(artifact)
    _validate_images(artifact)
    _validate_spatial_curves(artifact)


def _validate_parameters(artifact: QAArtifact) -> None:
    p, m = artifact.provenance, artifact.measurements
    # `settings.pe_axis_override` and `measurements.pe_axis` are not checked
    # here: both are `PeAxis | None`, so `validate_document` -- which reads the
    # field annotations -- already refuses any other axis, on save and on load
    # alike. Repeating the domain as a literal `(None, 0, 1)` would be a second
    # place to update the day a pipeline measures a third axis.
    # The converse does not hold: a migrated (schema <= 5) artifact can carry a
    # known voxel size with `displacement_unit` still "vox", because the old
    # peaks were always voxels regardless (see `serialize.migrate`). "mm"
    # without a known voxel size to have produced it, though, is never valid.
    _require(
        m.displacement_unit != "mm" or p.voxel_mm is not None,
        "measurements.displacement_unit is mm but provenance.voxel_mm is unknown",
    )
    _require(0 <= m.outlier_worst_frame < p.n_frames, "invalid outlier_worst_frame")


def _validate_timeseries(artifact: QAArtifact) -> None:
    c, p = artifact.curves, artifact.provenance
    _require(0 < c.outlier_qthr < 1, "invalid curves.outlier_qthr")
    for name in (
        "time",
        "roi_signal",
        "roi_trend",
        "roi_residual",
        "outlier_fraction",
        "shear_pct",
    ):
        _require(
            getattr(c, name).shape == (p.n_frames,), f"curves.{name} shape mismatch"
        )
    for name in ("translation", "scale_pct", "com_deviation"):
        _require(
            getattr(c, name).shape == (p.n_frames, 2), f"curves.{name} shape mismatch"
        )
    _require(
        bool(np.allclose(c.time, np.arange(p.n_frames) * p.tr)),
        "curves.time disagrees with frame count/TR",
    )
    for name in ("spectrum_hz", "spectrum_magnitude"):
        _require(
            getattr(c, name).shape == (p.n_frames // 2,),
            f"curves.{name} shape mismatch",
        )
    _require(
        bool(np.allclose(c.spectrum_hz, np.fft.rfftfreq(p.n_frames, p.tr)[1:])),
        "curves.spectrum_hz disagrees with frame count/TR",
    )


def _validate_images(artifact: QAArtifact) -> None:
    images = artifact.images
    s, p, m = artifact.settings, artifact.provenance, artifact.measurements
    shape = images.signal.shape
    _require(
        len(shape) == 2 and min(shape) > 0, "images.signal must be a nonempty 2-D image"
    )
    if p.matrix is not None:
        _require(p.matrix == shape, "provenance.matrix disagrees with images")
    for name in (
        "sfnr",
        "fluctuation_noise",
        "static_noise",
        "phantom_mask",
        "invalid_mask",
    ):
        _require(getattr(images, name).shape == shape, f"images.{name} shape mismatch")
    _require(
        (images.ghost is not None) == (m.pe_axis is not None),
        "ghost regions disagree with pe_axis",
    )
    if images.ghost is not None:
        for name in ("pe_signal", "pe_ghost", "ro_signal", "ro_ghost"):
            _require(
                getattr(images.ghost, name).shape == shape,
                f"images.ghost.{name} shape mismatch",
            )
    roi = images.roi
    # `RoiBox.__post_init__` has already held the box to being square and
    # positive; what is left is the half that needs the image it sits on.
    _require(
        roi.row1 <= shape[0] and roi.col1 <= shape[1],
        "images.roi must be square and inside the image",
    )
    _require(
        roi.size == min(s.roi_size, *shape),
        "images.roi disagrees with settings.roi_size",
    )
    hull = images.phantom_hull
    _require(
        hull.ndim == 2 and hull.shape[1] == 2,
        "images.phantom_hull must have shape (N, 2)",
    )
    _require(bool(np.isfinite(hull).all()), "images.phantom_hull must be finite")


def _validate_spatial_curves(artifact: QAArtifact) -> None:
    c, m, roi = artifact.curves, artifact.measurements, artifact.images.roi
    wk = c.weisskoff
    for name in ("roi_sizes", "cv", "cv_ideal", "rdc"):
        _require(
            getattr(wk, name).shape == (roi.size,),
            f"curves.weisskoff.{name} shape mismatch",
        )
    _require(
        bool(np.array_equal(wk.roi_sizes, np.arange(1, roi.size + 1))),
        "invalid Weisskoff ROI sizes",
    )
    psf = c.psf
    _require(psf.unit == m.fwhm_unit, "PSF and measurement units disagree")
    labels = ("axis0", "axis1") if m.pe_axis is None else ("PE", "RO")
    _require(psf.labels == labels, "PSF labels disagree with pe_axis")
    _require(math.isfinite(psf.xmax) and psf.xmax > 0, "invalid curves.psf.xmax")
    for x, y, name in (
        (psf.displacement, psf.empirical, "empirical"),
        (psf.model_x, psf.model, "model"),
    ):
        _require(
            x.ndim == 2 and x.shape[0] == 2 and x.shape[1] > 0 and y.shape == x.shape,
            f"curves.psf.{name} shape mismatch",
        )
        _require(
            bool(np.isfinite(x).all()), f"curves.psf.{name} coordinates must be finite"
        )
