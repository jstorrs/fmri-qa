"""Bring a stored document up to the current schema, one version step at a time.

An analysis file outlives the build that wrote it, so a schema bump must not orphan a
QA archive a trend database has filled for months. Every older layout this build
knows a route from is migrated forward here, in memory, on read.

Each `_vN_to_vN1` handles one version bump, and `migrated` applies them in
sequence. A field the older schema did not carry comes back unknown, never
reconstructed, because a value this build derives would be a fact about this
build, not about the analysis file.

Bumping `ARTIFACT_SCHEMA_VERSION` is not done until the outgoing version has a
committed fixture. Run the old code (a `git worktree` checkout of the last commit
at that version) over the shared synthetic phantom and save the file to
fmri-qa-io's `tests/fixtures/schema_v{N}.qa.nc`, or `.qa.npz` if that build still
wrote that container. `test_artifact_fixtures.py` finds either, and the loader
tells them apart by leading bytes. A migration tested only against a same-build document
synthesized to look old (as `test_artifact_archive.py` does) proves the step
matches its docstring, not that a real file from that version still parses.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ...exceptions import InvalidArtifactError
from ...warn import warn
from ..artifact import ARTIFACT_SCHEMA_VERSION


def _v1_to_v2(document: dict[str, Any]) -> dict[str, Any]:
    """Migrate schema 1 to 2, recording the localization diagnostics as unknown.

    A v1 build never asked whether the phantom segmentation or the summary ROI
    held, so nothing in the file answers it. A made-up pass would vouch for
    numbers this package cannot vouch for, and a made-up failure would condemn
    scans that were probably fine. So the diagnostics are absent, not false (see
    `Measurements`).
    """
    document["measurements"] |= {
        "phantom_fraction": float("nan"),
        "roi_inside_phantom": None,
    }
    return document


def _v2_to_v3(document: dict[str, Any]) -> dict[str, Any]:
    """Migrate schema 2 to 3, recording the phantom-mask verdict as unknown.

    The verdict is not re-derived from the stored fraction. The bounds belong to
    the segmentation in `prep`, which this module does not import at read time
    (see `analysis`), and a verdict from another build's bounds would describe
    this build, not the analysis file.
    """
    document["measurements"]["phantom_mask_ok"] = None
    return document


def _v3_to_v4(document: dict[str, Any]) -> dict[str, Any]:
    """Migrate schema 3 to 4, recording the trim count as not recorded.

    The trim is not recomputed from the stored `trim_sec` and `tr`.
    `trim_count` belongs to `prep`, and a count this build derives would reflect
    this build's rounding, not the volumes the writing build dropped. So the
    field says "not recorded", and frame indices stay in the analyzed series
    where they were measured (see `Provenance`).
    """
    document["provenance"]["n_trimmed"] = None
    return document


def _v4_to_v5(document: dict[str, Any]) -> dict[str, Any]:
    """Migrate schema 4 to 5, recording the plane and mask contrast as unknown.

    The writing build made both measurements and did not write them down. The
    slice cannot be re-derived, since it depends on the volume, which the
    analysis file does not carry. The contrast could only be recomputed with this
    build's definition. Schema 4 also stored `settings.roi_size` already clamped
    to the image. That value still reproduces the run, so it is left as it is.
    """
    document["provenance"] |= {"slice_index": None, "n_slices": None}
    document["measurements"]["phantom_contrast"] = float("nan")
    return document


def _v5_to_v6(document: dict[str, Any]) -> dict[str, Any]:
    """Migrate schema 5 to 6, declaring its displacements to be in voxels.

    Unlike the other steps, this one does not record "unknown, never
    reconstructed", because there is nothing to reconstruct.
    `MotionResult.max_translation` and `CenterOfMassResult.max_displacement` used
    to compute a voxel `np.hypot` unconditionally, whether or not the voxel size
    was known. So every schema <= 5 analysis file's stored numbers *are* voxels. That
    is a documented fact about the old format, not a value only this build could
    derive. `displacement_unit` is recorded as "vox" outright. `LengthUnit` has
    no unknown state to fall back on.

    A migrated analysis file can therefore have `displacement_unit` "vox" beside a
    `fwhm_unit` of "mm". That is real history, not a bug. Only an analysis file this
    build produces is guaranteed to have both agree (see
    `Measurements.displacement_unit`). The stored values are left untouched.
    Converting them to mm with `Provenance.voxel_mm` would publish this build's
    convention as the writing build's measurement.
    """
    document["measurements"]["displacement_unit"] = "vox"
    return document


def _v6_to_v7(document: dict[str, Any]) -> dict[str, Any]:
    """Migrate schema 6 to 7, carrying its clipping answers forward unchanged.

    Schema 7 lets the clipping block be None, meaning the series was not stored
    as integers and the rail test could not run. No schema 6 document needs that
    value, because the build that wrote it ran the test unconditionally and
    recorded a bool. This step edits nothing.

    It cannot audit those bools. A schema 6 analysis file built from a
    float-converted NIfTI carries `clipped_any` False, which this build would
    call not determinable, but the analysis file does not record the storage datatype.
    Rewriting to None would condemn every genuinely clean scan with them, so the
    values stay, as with the steps above. `Measurements` says what a schema <= 6
    False is worth.
    """
    return document


# One step per version: `_MIGRATIONS[n]` takes a document at schema `n` and
# returns it at `n + 1`. They are applied in sequence, so a v1 file reaches the
# current schema through every intermediate step and each migration only has to
# know about its own version bump.
_MIGRATIONS: dict[int, Callable[[dict[str, Any]], dict[str, Any]]] = {
    1: _v1_to_v2,
    2: _v2_to_v3,
    3: _v3_to_v4,
    4: _v4_to_v5,
    5: _v5_to_v6,
    6: _v6_to_v7,
}


def migrated(document: dict[str, Any], path: Path) -> dict[str, Any]:
    """Bring a stored document up to the current schema, or refuse it.

    The caller is warned when anything it reads was recorded as unknown rather
    than measured. Two kinds of version are refused: one from a newer build,
    whose layout this one cannot know, and an older one with no route from it.
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

    warn(
        f"{path}: analysis file written under schema {found}, migrated to "
        f"{ARTIFACT_SCHEMA_VERSION}; fields the older schema did not carry are "
        f"recorded as unknown, not as measurements.",
    )
    return document
