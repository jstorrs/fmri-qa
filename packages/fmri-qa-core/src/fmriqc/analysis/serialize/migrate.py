"""Bring a stored document up to the current schema, one version step at a time.

An artifact outlives the build that wrote it — that is the point of saving one —
so a schema bump must not orphan a QA archive a trend database has been filling
for months. Every older layout this build knows a route from is migrated forward
here, in memory, on read.

Each `_vN_to_vN1` knows only about its own version bump; `migrated` applies them
in sequence, so a v1 file reaches the current schema through every intermediate
step. A field the older schema did not carry comes back *unknown*, never
reconstructed: a value this build derives would be a fact about this build, not
about the artifact.
"""

import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...exceptions import InvalidArtifactError
from ..artifact import ARTIFACT_SCHEMA_VERSION


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


def _v5_to_v6(document: dict[str, Any]) -> dict[str, Any]:
    """Schema 5 reported `max_translation`/`max_com_displacement` in voxels, always.

    This migration does not follow the "unknown, never reconstructed" pattern
    the others do, because there is nothing to reconstruct: before this build,
    `MotionResult.max_translation` and `CenterOfMassResult.max_displacement`
    computed a voxel `np.hypot` unconditionally, whether or not the header's
    voxel size was known, so every schema <= 5 artifact's stored numbers *are*
    voxels -- a documented fact about the old format, not a value only this
    build could derive. `displacement_unit` is recorded as "vox" outright, not
    left unknown; unlike, say, `phantom_contrast`, `LengthUnit` has no unknown
    state to fall back on ("mm"/"vox" is all `fwhm_unit` has ever offered).

    This can leave a migrated artifact with `displacement_unit` disagreeing
    with `fwhm_unit` -- e.g. "vox" beside a `fwhm_unit` of "mm", when the
    voxel size was known but schema 5 never used it for these two peaks. That
    is real history, not a bug: only an artifact this build produces itself is
    guaranteed to have both fields agree (see `Measurements.displacement_unit`).
    The stored `max_translation`/`max_com_displacement` values themselves are
    left untouched -- converting them to mm now, using `Provenance.voxel_mm`,
    would publish this build's convention as if it were the measurement the
    writing build made.
    """
    document["measurements"]["displacement_unit"] = "vox"
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
    5: _v5_to_v6,
}


def migrated(document: dict[str, Any], path: Path) -> dict[str, Any]:
    """Bring a stored document up to the current schema, or refuse it.

    The caller is warned when anything it is reading was recorded as unknown
    rather than measured. Two versions are refused, because neither has an
    honest answer: one from a newer build (whose layout this one cannot know)
    and an older one with no route from.
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
