"""Move a `QAArtifact` to and from a single `.npz` file.

The on-disk form is one compressed NumPy archive: every array is a member under
its dotted path (`curves.weisskoff.cv`, `images.ghost.pe_ghost`), and everything
that is not an array — settings, provenance, the scalar measurements, the
labels — rides in a JSON document stored as the `__document__` member. So the
file is inspectable with nothing but `numpy` and `json`, and an array can be
pulled out without materializing the rest.

The mapping is written out explicitly, section by section, rather than derived
by reflection over the dataclasses: the layout is a published contract pinned by
`ARTIFACT_SCHEMA_VERSION`, and adding a field should be a deliberate edit here,
not a silent change of file format.

The JSON document uses Python's `NaN`/`Infinity` tokens. A NaN measurement is
meaningful — it says an estimator could not resolve the value, which is distinct
from the `null` that says the quantity does not apply — so it is preserved
rather than flattened.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from ..exceptions import InvalidArtifactError
from ..types import BoolArray, FloatArray
from .artifact import (
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
)

# An archive member: a float image/curve or a boolean mask, addressed by its
# dotted path. The two dtypes share one alias because the archive is keyed by
# name, not by kind; each reader re-narrows via `_floats`/`_bools`.
type Member = FloatArray | BoolArray

# The JSON member carrying everything that is not an array.
_DOCUMENT = "__document__"
# Provenance fields stored as JSON lists that must come back as tuples.
_PROVENANCE_TUPLES = ("voxel_mm", "matrix")


def save_artifact(artifact: QAArtifact, path: str | Path) -> Path:
    """Write `artifact` to `path` as a compressed `.npz`. Returns the path.

    Missing parent directories are created. The file name is used exactly as
    given (NumPy's own `savez` would append `.npz` to a name lacking it).
    """
    document, arrays = _decompose(artifact)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Member] = {_DOCUMENT: np.array(json.dumps(document)), **arrays}
    with out.open("wb") as fh:
        # savez_compressed takes member names as **kwargs, which collides with its
        # own keyword-only `allow_pickle` for a checker: a `dict[str, ...]` splat
        # could in principle carry that name. Our keys are dotted paths, never it.
        np.savez_compressed(fh, **payload)  # type: ignore[arg-type]
    return out


def load_artifact(path: str | Path) -> QAArtifact:
    """Read a `QAArtifact` back from an `.npz` written by `save_artifact`.

    Raises:
        InvalidArtifactError: If the file is not a readable artifact archive, or
            its `schema_version` is not the one this package understands.
    """
    src = Path(path)
    try:
        with np.load(src, allow_pickle=False) as archive:
            names = list(archive.files)
            if _DOCUMENT not in names:
                raise InvalidArtifactError(src, "not an fmriqc artifact archive")
            document = json.loads(str(archive[_DOCUMENT]))
            arrays = {name: archive[name] for name in names if name != _DOCUMENT}
    except InvalidArtifactError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise InvalidArtifactError(src, str(exc)) from exc

    found = document.get("schema_version")
    if found != ARTIFACT_SCHEMA_VERSION:
        raise InvalidArtifactError(
            src, f"schema version {found!r}; this build reads {ARTIFACT_SCHEMA_VERSION}"
        )
    try:
        return _compose(document, arrays)
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidArtifactError(src, f"malformed artifact: {exc}") from exc


# -- write ------------------------------------------------------------------ #


def _decompose(artifact: QAArtifact) -> tuple[dict[str, Any], dict[str, Member]]:
    """Split an artifact into its JSON document and its named arrays."""
    curves, curve_arrays = _decompose_curves(artifact.curves)
    images, image_arrays = _decompose_images(artifact.images)
    document = {
        "schema_version": artifact.schema_version,
        "settings": asdict(artifact.settings),
        "provenance": asdict(artifact.provenance),
        "measurements": asdict(artifact.measurements),
        "curves": curves,
        "images": images,
    }
    return document, {**curve_arrays, **image_arrays}


def _decompose_curves(curves: Curves) -> tuple[dict[str, Any], dict[str, Member]]:
    """The curve scalars, and every trace keyed by its dotted path."""
    psf = curves.psf
    document = {
        "outlier_qthr": curves.outlier_qthr,
        "psf": {
            "labels": list(psf.labels),
            "fwhm": list(psf.fwhm),
            "unit": psf.unit,
            "xmax": psf.xmax,
        },
    }
    arrays: dict[str, Member] = {
        "curves.time": curves.time,
        "curves.roi_signal": curves.roi_signal,
        "curves.roi_trend": curves.roi_trend,
        "curves.roi_residual": curves.roi_residual,
        "curves.outlier_fraction": curves.outlier_fraction,
        "curves.spectrum_hz": curves.spectrum_hz,
        "curves.spectrum_magnitude": curves.spectrum_magnitude,
        "curves.translation": curves.translation,
        "curves.scale_pct": curves.scale_pct,
        "curves.shear_pct": curves.shear_pct,
        "curves.com_deviation": curves.com_deviation,
        "curves.weisskoff.roi_sizes": curves.weisskoff.roi_sizes,
        "curves.weisskoff.cv": curves.weisskoff.cv,
        "curves.weisskoff.cv_ideal": curves.weisskoff.cv_ideal,
        "curves.weisskoff.rdc": curves.weisskoff.rdc,
        "curves.psf.displacement": psf.displacement,
        "curves.psf.empirical": psf.empirical,
        "curves.psf.model_x": psf.model_x,
        "curves.psf.model": psf.model,
    }
    return document, arrays


def _decompose_images(
    images: ArtifactImages,
) -> tuple[dict[str, Any], dict[str, Member]]:
    """The image-section scalars, and every image/mask keyed by its dotted path."""
    document = {"roi": asdict(images.roi), "has_ghost": images.ghost is not None}
    arrays: dict[str, Member] = {
        "images.signal": images.signal,
        "images.sfnr": images.sfnr,
        "images.fluctuation_noise": images.fluctuation_noise,
        "images.static_noise": images.static_noise,
        "images.phantom_mask": images.phantom_mask,
        "images.invalid_mask": images.invalid_mask,
        "images.phantom_hull": images.phantom_hull,
    }
    if images.ghost is not None:
        arrays |= {
            "images.ghost.pe_signal": images.ghost.pe_signal,
            "images.ghost.pe_ghost": images.ghost.pe_ghost,
            "images.ghost.ro_signal": images.ghost.ro_signal,
            "images.ghost.ro_ghost": images.ghost.ro_ghost,
        }
    return document, arrays


# -- read ------------------------------------------------------------------- #


def _floats(arrays: dict[str, Any], key: str) -> FloatArray:
    """A required float array member."""
    return np.asarray(arrays[key], dtype=np.float64)


def _bools(arrays: dict[str, Any], key: str) -> BoolArray:
    """A required boolean mask member."""
    return np.asarray(arrays[key], dtype=np.bool_)


def _compose(document: dict[str, Any], arrays: dict[str, Any]) -> QAArtifact:
    """Rebuild an artifact from its JSON document and named arrays."""
    provenance = dict(document["provenance"])
    for field in _PROVENANCE_TUPLES:
        if provenance.get(field) is not None:
            provenance[field] = tuple(provenance[field])
    return QAArtifact(
        schema_version=document["schema_version"],
        settings=AnalysisSettings(**document["settings"]),
        provenance=Provenance(**provenance),
        measurements=Measurements(**document["measurements"]),
        curves=_compose_curves(document["curves"], arrays),
        images=_compose_images(document["images"], arrays),
    )


def _compose_curves(document: dict[str, Any], arrays: dict[str, Any]) -> Curves:
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


def _compose_images(document: dict[str, Any], arrays: dict[str, Any]) -> ArtifactImages:
    """Rebuild the image section."""
    ghost = None
    if document["has_ghost"]:
        ghost = GhostRegions(
            pe_signal=_bools(arrays, "images.ghost.pe_signal"),
            pe_ghost=_bools(arrays, "images.ghost.pe_ghost"),
            ro_signal=_bools(arrays, "images.ghost.ro_signal"),
            ro_ghost=_bools(arrays, "images.ghost.ro_ghost"),
        )
    return ArtifactImages(
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
