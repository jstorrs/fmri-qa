"""Validate the published artifact contract at the archive boundary.

Half the contract is not here. An invariant of one record alone is held by that
value object's own constructor (`Provenance`, `Measurements` and `RoiBox`
hold their own today), because an artifact built in-process and printed or
rendered is never saved and so never reaches this module: a new single-record
invariant added here would go unchecked for every consumer but the archive.
What is left here is what a constructor cannot see — facts that span two
records (`displacement_unit` against `provenance.voxel_mm`,
`outlier_worst_frame` against `provenance.n_frames`, the ROI box against the
image it sits on), the settings domains, and everything about arrays: their
dimensions, shapes, and coordinates.

Scalar types follow the value objects; dimensional relationships and numeric
domains are checked explicitly. NaN/Infinity measurements remain meaningful,
but coordinates, counts, and analysis settings must be usable.
"""

import math
from dataclasses import fields
from functools import cache
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

import numpy as np

from ..settings import AnalysisSettings
from .artifact import Measurements, Provenance, QAArtifact, RoiBox, _require

# The two spellings an optional field's annotation can arrive in. `int | None`
# evaluates to a `types.UnionType`, but `Literal[0, 1] | None` -- a `typing`
# special form on the left -- evaluates to `typing.Optional[...]`, whose origin
# is `typing.Union`. They mean the same thing and this validator must accept
# both, or the field it cannot read is silently rejected for every value.
_UNIONS = (UnionType, Union)


def _matches(value: object, annotation: Any) -> bool:
    origin = get_origin(annotation)
    if origin in _UNIONS:
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


@cache
def _resolved_annotations(cls: type) -> dict[str, Any]:
    """Field annotations for `cls`, resolved rather than read off `field.type`.

    `dataclasses.fields(cls).type` is whatever sits in `__annotations__` --
    the live type object today, since none of these four modules use `from
    __future__ import annotations` (PEP 563). But nothing enforces that: the
    day one of them adopts it as a stylistic change, every annotation on that
    class becomes a plain *string*, and `_matches` would compare `value`
    against the string `"float"` and reject every field -- loudly, but for a
    reason nobody would guess from the call site. `get_type_hints` evaluates
    annotations in the class's own defining module regardless of how they're
    stored, so the validator is correct either way. The four record classes
    below are fixed, and this resolution runs on every artifact load and
    save, so it's cached rather than repeated.
    """
    return get_type_hints(cls)


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
        annotations = _resolved_annotations(cls)
        for field in fields(cls):
            if not _matches(record[field.name], annotations[field.name]):
                raise ValueError(f"{name}.{field.name} has an invalid type or value")
    if type(images["has_ghost"]) is not bool:
        raise ValueError("images.has_ghost must be boolean")
    psf = _object(curves["psf"], "curves.psf")
    for name, annotation in (
        ("labels", tuple[str, str]),
        ("fwhm", tuple[float, float]),
        ("xmax", float),
    ):
        if not _matches(psf[name], annotation):
            raise ValueError(f"curves.psf.{name} has an invalid type or length")
    if not _matches(curves["outlier_qthr"], float):
        raise ValueError("curves.outlier_qthr must be numeric")


def validate_artifact(artifact: QAArtifact) -> None:
    """Require coherent settings, dimensions, and coordinates after composition."""
    _validate_parameters(artifact)
    _validate_timeseries(artifact)
    _validate_images(artifact)
    _validate_spatial_curves(artifact)


def _validate_parameters(artifact: QAArtifact) -> None:
    s, p, m = artifact.settings, artifact.provenance, artifact.measurements
    _require(math.isfinite(s.trim_sec) and s.trim_sec >= 0, "invalid settings.trim_sec")
    _require(s.roi_size > 0, "invalid settings.roi_size")
    _require(s.detrend_order is None or s.detrend_order >= 0, "invalid detrend_order")
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
