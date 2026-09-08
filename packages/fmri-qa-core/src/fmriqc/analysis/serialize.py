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
not a silent change of file format. Bumping that version is likewise deliberate,
and comes with a migration: an artifact outlives the build that wrote it, so
older layouts are brought forward on read (`_migrated`) rather than refused.

The JSON document uses Python's `NaN`/`Infinity` tokens. A NaN measurement is
meaningful — it says an estimator could not resolve the value, which is distinct
from the `null` that says the quantity does not apply — so it is preserved
rather than flattened.
"""

import json
import os
import tempfile
import warnings
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any
from zipfile import BadZipFile

import numpy as np

from ..exceptions import InvalidArtifactError
from ..pipeline import AnalysisSettings
from ..types import LENGTH_UNITS, PE_LABELS, BoolArray, FloatArray
from .artifact import (
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
)
from .validation import validate_artifact, validate_document

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

    The write is atomic: the archive goes to a temporary file beside the
    destination and is moved into place only once it is whole. A QA archive is
    read months later by something that never saw the run that wrote it, and a
    truncated `.npz` looks exactly like a complete one until it is opened — so
    an interrupted write must leave the destination untouched, not half-written.
    """
    document, arrays = _decompose(artifact)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Member] = {_DOCUMENT: np.array(json.dumps(document)), **arrays}
    # In the destination's own directory: a move is only atomic within a single
    # filesystem, and the system temporary directory is often on another.
    fd, name = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as fh:
            # savez_compressed takes member names as **kwargs, which collides with
            # its own keyword-only `allow_pickle` for a checker: a `dict[str, ...]`
            # splat could in principle carry that name. Our keys are dotted paths,
            # never it.
            np.savez_compressed(fh, **payload)  # type: ignore[arg-type]
        tmp.replace(out)
    finally:
        # A no-op once the move succeeded; the cleanup that matters is the one
        # after a failure, which must not leave debris beside the archive.
        tmp.unlink(missing_ok=True)
    return out


def load_artifact(path: str | Path) -> QAArtifact:
    """Read a `QAArtifact` back from an `.npz` written by `save_artifact`.

    A file written under an older schema is migrated forward on read (see
    `_migrated`), with a warning; only a version this build has no route from —
    or one from a newer build, which it cannot know the layout of — is refused.

    Raises:
        InvalidArtifactError: If the file is not a readable artifact archive, is
            malformed, or carries a `schema_version` this build cannot reach.
    """
    src = Path(path)
    try:
        with np.load(src, allow_pickle=False) as archive:
            names = list(archive.files)
            if _DOCUMENT not in names:
                raise InvalidArtifactError(src, "not an fmriqc artifact archive")
            document = json.loads(str(archive[_DOCUMENT]))
            if not isinstance(document, dict):
                raise InvalidArtifactError(
                    src, "malformed artifact: expected a JSON object"
                )
            arrays = {name: archive[name] for name in names if name != _DOCUMENT}
    except InvalidArtifactError:
        raise
    except (OSError, ValueError, TypeError, EOFError, BadZipFile) as exc:
        raise InvalidArtifactError(src, str(exc)) from exc

    try:
        # Migration reads the stored document too, so a document that is missing
        # what its own schema carried fails here; that is malformedness, and
        # belongs under the same guard as composing the current layout.
        document = _migrated(document, src)
        validate_document(document)
        artifact = _compose(document, arrays)
        validate_artifact(artifact)
        return artifact
    except InvalidArtifactError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        AttributeError,
        OverflowError,
    ) as exc:
        raise InvalidArtifactError(src, f"malformed artifact: {exc}") from exc


# -- migration -------------------------------------------------------------- #


def _v1_to_v2(document: dict[str, Any]) -> dict[str, Any]:
    """Schema 1 predates the localization diagnostics: record them as unknown.

    A v1 artifact was analyzed by a build that never asked whether the phantom
    segmentation or the summary ROI held, so nothing in the file answers it.
    Inventing a pass would vouch for numbers this package cannot vouch for, and
    inventing a failure would condemn scans that were probably fine; the
    diagnostics are therefore *absent*, not false (see `Measurements`).
    """
    document["measurements"] |= {
        "phantom_fraction": float("nan"),
        "roi_inside_phantom": None,
    }
    return document


def _v2_to_v3(document: dict[str, Any]) -> dict[str, Any]:
    """Schema 2 has the phantom fraction but not the verdict on it.

    The verdict is not re-derived from the stored fraction even though it could
    be: the bounds belong to the segmentation in `prep`, which this module does
    not import at read time (see `analysis`), and a verdict reached by some other
    build's bounds would be a fact about this build, not about the artifact.
    """
    document["measurements"]["phantom_mask_ok"] = None
    return document


def _v3_to_v4(document: dict[str, Any]) -> dict[str, Any]:
    """Schema 3 was trimmed but never recorded by how much.

    The trim is not recomputed from the stored `trim_sec` and `tr` even though
    the arithmetic is one line: `trim_count` belongs to `prep`, and a count this
    build derives would be a fact about this build's rounding, not about the
    volumes the writing build actually dropped. So the field says "not recorded",
    and a reader keeps its frame indices in the analyzed series where they were
    measured (see `Provenance`).
    """
    document["provenance"]["n_trimmed"] = None
    return document


def _v4_to_v5(document: dict[str, Any]) -> dict[str, Any]:
    """Schema 4 recorded neither the plane analyzed nor the mask's contrast.

    Both are measurements the writing build made and did not write down, so
    they come back unknown: the slice cannot be re-derived (it depends on the
    volume, which the artifact does not carry) and the contrast could only be
    recomputed from the stored images with this build's definition. Schema 4
    also stored `settings.roi_size` already clamped to the image; that value is
    still a request that reproduces the run, so it is left as it is.
    """
    document["provenance"] |= {"slice_index": None, "n_slices": None}
    document["measurements"]["phantom_contrast"] = float("nan")
    return document


# One step per version: `_MIGRATIONS[n]` takes a document at schema `n` and
# returns it at `n + 1`. Applied in sequence, so a v1 file reaches the current
# schema through every intermediate step and each migration only has to know
# about its own version bump.
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
    3: _v3_to_v4,
    4: _v4_to_v5,
}


def _migrated(document: dict[str, Any], path: Path) -> dict[str, Any]:
    """Bring a stored document up to the current schema, or refuse it.

    Artifacts outlive the build that wrote them — that is the point of saving
    one — so a schema bump must not orphan a QA archive that a trend database
    has been filling for months. Every older layout this build knows a route
    from is migrated forward here, in memory, and the caller is warned that some
    of what it is reading was reconstructed rather than measured.

    Refused, because neither has an honest answer: a version from a newer build
    (whose layout this one cannot know) and an older version with no route from.
    """
    found = document.get("schema_version")
    if not isinstance(found, int) or isinstance(found, bool):
        raise InvalidArtifactError(path, f"schema version {found!r} is not a version")
    if found == ARTIFACT_SCHEMA_VERSION:
        return document
    if found > ARTIFACT_SCHEMA_VERSION:
        raise InvalidArtifactError(
            path,
            f"schema version {found}, newer than the {ARTIFACT_SCHEMA_VERSION} this "
            f"build understands; upgrade fmri-qa-core to read it",
        )

    version = found
    while version < ARTIFACT_SCHEMA_VERSION:
        step = _MIGRATIONS.get(version)
        if step is None:
            raise InvalidArtifactError(
                path,
                f"schema version {found}; this build reads "
                f"{ARTIFACT_SCHEMA_VERSION} and has no migration from {version}",
            )
        document = step(document)
        version += 1
    document["schema_version"] = ARTIFACT_SCHEMA_VERSION

    warnings.warn(
        f"{path}: artifact written under schema {found}, migrated to "
        f"{ARTIFACT_SCHEMA_VERSION}; fields the older schema did not carry are "
        f"recorded as unknown, not as measurements.",
        stacklevel=3,
    )
    return document


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


def _one_of[T: str](value: Any, allowed: tuple[T, ...], field: str) -> T:
    """`value` as one of `allowed`, or a `ValueError` naming the field.

    A closed-set field is a plain string in the JSON document, and the artifact
    types promise a `Literal`. Checking on the way back in is what makes that
    promise true of a *loaded* artifact rather than only of a freshly built one:
    a hand-edited or foreign document must fail here (as an
    `InvalidArtifactError`, via `load_artifact`'s conversion) instead of being
    handed to a reader that switches on the value.
    """
    for candidate in allowed:
        if value == candidate:
            return candidate
    raise ValueError(f"{field} {value!r} is not one of {allowed}")


def _floats(arrays: dict[str, Any], key: str) -> FloatArray:
    """A required float array member."""
    if arrays[key].dtype.kind not in "fiu":
        raise ValueError(f"{key} must be a real numeric array")
    return np.asarray(arrays[key], dtype=np.float64)


def _bools(arrays: dict[str, Any], key: str) -> BoolArray:
    """A required boolean mask member."""
    if arrays[key].dtype != np.bool_:
        raise ValueError(f"{key} must be a boolean mask")
    return np.asarray(arrays[key], dtype=np.bool_)


def _compose(document: dict[str, Any], arrays: dict[str, Any]) -> QAArtifact:
    """Rebuild an artifact from its JSON document and named arrays."""
    provenance = dict(document["provenance"])
    for field in _PROVENANCE_TUPLES:
        if provenance.get(field) is not None:
            provenance[field] = tuple(provenance[field])
    measurements = dict(document["measurements"])
    measurements["fwhm_unit"] = _one_of(
        measurements["fwhm_unit"], LENGTH_UNITS, "fwhm_unit"
    )
    measurements["pe_label"] = _one_of(measurements["pe_label"], PE_LABELS, "pe_label")
    return QAArtifact(
        schema_version=document["schema_version"],
        settings=AnalysisSettings(**document["settings"]),
        provenance=Provenance(**provenance),
        measurements=Measurements(**measurements),
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
            unit=_one_of(psf["unit"], LENGTH_UNITS, "psf.unit"),
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
