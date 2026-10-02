"""The artifact round trip: a saved artifact reads back as the one written.

The other half of the artifact contract (`test_artifact.py` pins what goes into
one): that `save_artifact`/`load_artifact` preserve every section, that the
netCDF-4 file they agree on says what it holds, that a malformed or foreign
file is refused rather than half-read, that the `.npz` container every earlier
build wrote still opens, and that a file written under an older schema is
migrated forward with the fields that schema did not carry marked unknown
rather than invented.

Everything asserted about the stored bytes goes through `netCDF4` and `xarray`
rather than the package's own reader: the reason for this container is that a
reader which knows nothing about fmriqc can open it, so the tests read it as
one. `netCDF4` is the Unidata C library itself -- what `ncdump`, MATLAB and R
read through -- so a file it opens cleanly is a file those open too, and it is a
dependency of this package rather than something to skip when absent. xarray is
a dev dependency for the same claim one level up, and "opens cleanly" is
asserted as *no warning at all*: a netCDF library warns about what a file gets
subtly wrong, and those are exactly the defects that would reach a user as a
puzzle rather than as an error.
"""

import json
import os
import stat
import sys
import warnings
from dataclasses import asdict, replace

# `netCDF4` is imported here and not in each test on purpose: the two "without a
# warning" tests below run under `simplefilter("error")`, and importing the
# wheel raises its own Cython `RuntimeWarning`. Taking the import at module
# scope means every test enters that filter with the library already loaded, so
# what the filter can catch is what opening the artifact does and nothing else.
import netCDF4
import numpy as np
import pytest

import fmriqc as q
from fmriqc.analysis import ARTIFACT_SCHEMA_VERSION
from fmriqc.analysis.serialize import netcdf
from fmriqc.analysis.serialize.compose import _floats
from fmriqc.analysis.serialize.decompose import decompose


def test_save_load_round_trips_every_section(tmp_path, artifact) -> None:
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    loaded = q.load_artifact(path)

    assert loaded.schema_version == ARTIFACT_SCHEMA_VERSION
    assert loaded.settings == artifact.settings
    assert loaded.provenance == artifact.provenance
    assert _same_scalars(loaded.measurements, artifact.measurements)
    assert loaded.curves.psf.labels == artifact.curves.psf.labels
    assert loaded.curves.outlier_qthr == artifact.curves.outlier_qthr
    assert loaded.images.roi == artifact.images.roi

    for section, names in (
        ("curves", ["time", "roi_signal", "roi_residual", "com_deviation"]),
        ("images", ["signal", "sfnr", "static_noise", "phantom_hull"]),
    ):
        for name in names:
            before = getattr(getattr(artifact, section), name)
            after = getattr(getattr(loaded, section), name)
            assert np.array_equal(before, after), f"{section}.{name}"
    assert np.array_equal(loaded.images.phantom_mask, artifact.images.phantom_mask)
    assert loaded.images.phantom_mask.dtype == np.bool_
    assert loaded.images.ghost is not None
    assert np.array_equal(loaded.images.ghost.pe_ghost, artifact.images.ghost.pe_ghost)


def test_analysis_reexports_the_one_error_load_artifact_raises() -> None:
    """`fmriqc.analysis.InvalidArtifactError` is the same object as `q`'s.

    A reader that may only cross the published-artifact seam (`fmri-qa-report`)
    still needs to catch the one error `load_artifact` raises by name.
    """
    from fmriqc.analysis import InvalidArtifactError

    assert InvalidArtifactError is q.InvalidArtifactError


def test_save_uses_the_exact_path_given(tmp_path, artifact) -> None:
    """A caller's name is honoured exactly, suffix or no suffix."""
    path = q.save_artifact(artifact, tmp_path / "nested" / "run1.artifact")
    assert path.is_file() and path.name == "run1.artifact"
    assert q.load_artifact(path).measurements.snr == artifact.measurements.snr


def test_save_refuses_an_artifact_the_reader_would_reject(tmp_path, artifact) -> None:
    """What `save_artifact` writes, `load_artifact` reads: one contract, both ends.

    The producer used to skip the checks the reader applies, so an artifact
    carrying a value no analysis touches -- here a text echo time -- was written
    without complaint and refused on the way back in.
    """
    broken = replace(artifact, provenance=replace(artifact.provenance, te="0.03"))
    with pytest.raises(q.InvalidArtifactError, match=r"provenance\.te"):
        q.save_artifact(broken, tmp_path / "qa.nc")
    assert not (tmp_path / "qa.nc").exists()


def test_save_refuses_an_roi_box_that_is_square_but_off_the_image(
    tmp_path, artifact
) -> None:
    """A legal box is still wrong if it is drawn where the image is not.

    `RoiBox` holds itself to being square with a positive side, which it can see
    on its own; that the box lies inside the image it annotates is a fact about
    the image, so it is the archive boundary that holds it.
    """
    roi = artifact.images.roi
    offset = artifact.images.signal.shape[0]
    moved = replace(
        roi,
        row0=roi.row0 + offset,
        row1=roi.row1 + offset,
        col0=roi.col0 + offset,
        col1=roi.col1 + offset,
    )
    broken = replace(artifact, images=replace(artifact.images, roi=moved))
    with pytest.raises(q.InvalidArtifactError, match="inside the image"):
        q.save_artifact(broken, tmp_path / "qa.nc")
    assert not (tmp_path / "qa.nc").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_a_saved_archive_respects_the_umask(tmp_path, artifact) -> None:
    """An archive is handed to colleagues, so it must not come out owner-only."""
    old_umask = os.umask(0o022)
    try:
        path = q.save_artifact(artifact, tmp_path / "qa.nc")
    finally:
        os.umask(old_umask)
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_a_refused_save_preserves_the_archive_already_there(tmp_path, artifact) -> None:
    """A rejected write leaves the valid file it would have replaced untouched."""
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    before = path.read_bytes()
    broken = replace(artifact, provenance=replace(artifact.provenance, te="0.03"))
    with pytest.raises(q.InvalidArtifactError, match=r"provenance\.te"):
        q.save_artifact(broken, path)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".*.tmp"))  # and no temporary beside it


@pytest.mark.parametrize("version", [99, 0, 4.0, "7", True])
def test_save_refuses_an_artifact_whose_schema_version_is_not_the_current_one(
    tmp_path, artifact, version
) -> None:
    """The writer holds itself to the one check the reader applies first.

    `load_artifact` refuses any `schema_version` but the exact current one
    (migrating older ones forward); `save_artifact` used to write such a value
    without complaint, so the archive was refused only when something later
    tried to read it back.
    """
    path = tmp_path / "qa.nc"
    q.save_artifact(artifact, path)
    before = path.read_bytes()
    broken = replace(artifact, schema_version=version)
    with pytest.raises(q.InvalidArtifactError, match="schema version"):
        q.save_artifact(broken, path)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".*.tmp"))


def test_a_failed_save_leaves_neither_a_file_nor_a_temporary(
    tmp_path, artifact, monkeypatch
) -> None:
    """An interrupted write must not leave debris in a QA archive.

    The archive a trend database reads is a directory of these files, and a
    truncated one is indistinguishable from a whole one until it is opened. The
    bytes go to a temporary beside the destination and are moved in only once
    they are complete, so a failure leaves the directory exactly as it was.

    The failure is provoked at the fsync, which is the last thing to happen
    before the rename and so the point at which a temporary full of bytes
    already exists -- the case the cleanup is actually for.
    """

    def fails(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "fsync", fails)
    archive_dir = tmp_path / "archive"
    with pytest.raises(OSError, match="no space left on device"):
        q.save_artifact(artifact, archive_dir / "qa.nc")
    assert list(archive_dir.iterdir()) == []


def test_load_rejects_a_netcdf_file_that_is_not_an_artifact(tmp_path) -> None:
    """A well-formed netCDF carrying no document is a file, not an artifact."""
    path = tmp_path / "weather.nc"
    _write_netcdf(path, {"temperature": np.arange(3.0)}, attributes={})
    with pytest.raises(q.InvalidArtifactError, match="not an fmriqc artifact"):
        q.load_artifact(path)


def test_load_rejects_an_npz_that_is_not_an_artifact(tmp_path) -> None:
    plain = tmp_path / "plain.npz"
    np.savez_compressed(plain, values=np.arange(3))
    with pytest.raises(q.InvalidArtifactError, match="not an fmriqc artifact"):
        q.load_artifact(plain)


def test_load_rejects_a_document_attribute_that_is_not_text(tmp_path) -> None:
    """The document is JSON text; a numeric attribute of that name is not it."""
    path = tmp_path / "numeric.nc"
    signal = {"images.signal": np.ones((2, 2))}
    _write_netcdf(path, signal, attributes={"document": np.int32(7)})
    with pytest.raises(q.InvalidArtifactError, match="document attribute is not text"):
        q.load_artifact(path)


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("junk.bin", b"not an archive"),
        ("plain.npy", None),  # a NumPy array file: neither container
        ("empty.nc", b""),
        ("truncated.nc", None),  # a real artifact, cut off mid-file
    ],
)
def test_load_rejects_a_file_that_is_neither_container(
    tmp_path, artifact, name, content
) -> None:
    """The container is decided by the leading bytes, and nothing else matches.

    Including the case that matters most for an archive: a file that starts
    with HDF5's signature because it really is an artifact, and stops in the
    middle because the write that produced it did not finish.
    """
    path = tmp_path / name
    if content is not None:
        path.write_bytes(content)
    elif name.endswith(".npy"):
        np.save(path, np.ones(3))
    else:
        whole = q.save_artifact(artifact, tmp_path / "whole.nc").read_bytes()
        path.write_bytes(whole[: len(whole) // 2])
    with pytest.raises(q.InvalidArtifactError):
        q.load_artifact(path)


def test_load_rejects_a_path_that_is_not_a_readable_file(tmp_path) -> None:
    """A name that is a directory, or nothing at all, is not an artifact either.

    Both fail at the open that sniffs the leading bytes, before any container
    reader is chosen -- and a caller of `load_artifact` still has exactly one
    exception type to catch.
    """
    (tmp_path / "archive").mkdir()
    for path in (tmp_path / "archive", tmp_path / "absent.qa.nc"):
        with pytest.raises(q.InvalidArtifactError):
            q.load_artifact(path)


def test_load_rejects_non_object_documents(tmp_path) -> None:
    for document in ([], None, 4, "text"):
        path = tmp_path / "bad.nc"
        signal = {"images.signal": np.ones((2, 2))}
        _write_netcdf(path, signal, attributes={"document": json.dumps(document)})
        with pytest.raises(q.InvalidArtifactError, match="JSON object"):
            q.load_artifact(path)


def test_load_rejects_invalid_scalar_records(tmp_path, artifact) -> None:
    edits = (
        ("schema_version", 4.0),
        ("settings", []),
        ("settings.detrend", "invalid"),
        ("settings.center", "invalid"),
        ("settings.roi_size", True),
        ("settings.roi_size", 0),
        ("settings.trim_sec", float("nan")),
        ("settings.detrend_order", -1),
        ("settings.pe_axis_override", 2),
        ("provenance.n_frames", 0),
        ("provenance.n_trimmed", -1),
        ("provenance.tr", 0),
        ("provenance.matrix", [1, 2, 3]),
        ("provenance.matrix", [1, 2]),
        ("provenance.voxel_mm", [3, -1, 3]),
        ("measurements.snr", "100"),
        ("measurements.pe_axis", 2),
        ("measurements.outlier_worst_frame", 999),
        ("measurements.n_clipped_kept", -1),
        ("images.has_ghost", "false"),
        ("images.has_ghost", False),
        ("images.roi.row0", -1),
        ("images.roi.row1", 999),
        ("curves", []),
        ("curves.outlier_qthr", "0.001"),
        ("curves.outlier_qthr", 0),
        ("curves.psf.labels", []),
        ("curves.psf.labels", ["bad", "labels"]),
        ("curves.psf.fwhm", [1]),
        ("curves.psf.xmax", float("inf")),
        ("curves.psf.unit", "vox"),
        ("curves.psf.unit", "cm"),
    )
    for field, value in edits:
        path = q.save_artifact(artifact, tmp_path / "bad.nc")

        def edit(doc, field=field, value=value):
            target = doc
            keys = field.split(".")
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
            return doc

        _rewrite_document(path, edit)
        with pytest.raises(q.InvalidArtifactError):
            q.load_artifact(path)


def test_load_rejects_inconsistent_arrays(tmp_path, artifact) -> None:
    """An array whose shape contradicts the document is refused, not reshaped.

    Each replacement is written with private dimensions rather than into the
    shared one it no longer fits, so what the loader sees is a file that is
    perfectly well-formed netCDF and a perfectly wrong artifact -- the shape
    check in `validation` is the only thing standing between the two.
    """
    edits = (
        ("curves.roi_signal", np.zeros(1)),
        ("curves.translation", np.zeros((38, 3))),
        ("curves.time", np.zeros(38)),
        ("curves.spectrum_hz", np.zeros(19)),
        ("curves.spectrum_magnitude", np.zeros(1)),
        ("curves.weisskoff.cv", np.zeros(1)),
        ("curves.weisskoff.roi_sizes", np.zeros(9)),
        ("curves.psf.empirical", np.zeros((1, 2))),
        ("curves.psf.model_x", np.full((2, 100), np.nan)),
        ("images.signal", np.ones(1)),
        ("images.sfnr", np.ones((1, 1))),
        ("images.phantom_mask", np.ones((1, 1), dtype=bool)),
        ("images.phantom_mask", np.full((32, 32), 2.0)),
        ("images.ghost.pe_signal", np.ones((1, 1), dtype=bool)),
        ("images.phantom_hull", np.zeros((3, 3))),
        ("images.phantom_hull", np.full((3, 2), np.nan)),
    )
    for field, value in edits:
        path = q.save_artifact(artifact, tmp_path / "bad.nc")
        document, arrays = _read_netcdf(path)
        _write_netcdf(
            path,
            arrays | {field: value},
            attributes={"document": json.dumps(document)},
        )
        with pytest.raises(q.InvalidArtifactError):
            q.load_artifact(path)


def test_load_rejects_an_array_that_is_not_real_numbers() -> None:
    """A member of a kind no measurement can be is refused, not coerced.

    Checked against `compose` directly rather than through a file, because the
    layout stores float64 and flagged bytes and refuses every other dtype at
    `encode` -- so the guard now answers only for a hand-built `.npz`, which is
    exactly where a foreign array could still arrive.
    """
    for value in (np.full((2, 2), "1"), np.ones((2, 2), dtype=complex)):
        with pytest.raises(ValueError, match="real numeric array"):
            _floats({"images.signal": value}, "images.signal")


def test_artifact_arrays_own_readonly_copies(tmp_path, artifact) -> None:
    signal = artifact.images.signal.copy()
    images = replace(artifact.images, signal=signal)
    signal[:] = 0
    assert images.signal.any()
    loaded = q.load_artifact(q.save_artifact(artifact, tmp_path / "qa.nc"))
    for obj in (artifact, loaded):
        assert obj.images.ghost is not None
        for array in (
            obj.images.signal,
            obj.images.phantom_mask,
            obj.curves.time,
            obj.curves.translation,
            obj.curves.weisskoff.cv,
            obj.curves.psf.empirical,
            obj.images.ghost.pe_signal,
        ):
            with pytest.raises(ValueError, match="read-only"):
                array.flat[0] = 0


def test_failed_motion_survives_the_artifact_round_trip(tmp_path, artifact) -> None:
    n = artifact.provenance.n_frames
    broken = replace(
        artifact,
        measurements=replace(
            artifact.measurements,
            max_translation=float("nan"),
            max_scale_pct=float("nan"),
            max_shear_pct=float("nan"),
        ),
        curves=replace(
            artifact.curves,
            translation=np.full((n, 2), np.nan),
            scale_pct=np.full((n, 2), np.nan),
            shear_pct=np.full(n, np.nan),
        ),
    )
    loaded = q.load_artifact(q.save_artifact(broken, tmp_path / "failed-motion.nc"))
    assert np.isnan(loaded.curves.translation).all()
    assert np.isnan(loaded.measurements.max_translation)


def test_load_rejects_an_artifact_from_a_newer_build(tmp_path, artifact) -> None:
    """A future layout is refused by name, not misread field by field.

    The one direction that cannot be migrated: this build does not know what a
    later schema put in the file, so guessing would be worse than refusing.
    """
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, lambda doc: doc | {"schema_version": 99})
    with pytest.raises(q.InvalidArtifactError, match="schema version 99, newer"):
        q.load_artifact(path)


def test_load_rejects_an_old_version_it_cannot_migrate_from(tmp_path, artifact) -> None:
    """An older version with no route forward is named, not silently mangled."""
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, lambda doc: doc | {"schema_version": 0})
    with pytest.raises(q.InvalidArtifactError, match="no migration from 0"):
        q.load_artifact(path)


def test_load_migrates_a_schema_1_artifact(tmp_path, artifact) -> None:
    """An archive predating the localization diagnostics still reads back.

    An artifact outlives the build that wrote it -- that is what saving one is
    for -- so a schema bump must not orphan a QA archive a trend database has
    been filling for months. Everything schema 1 did carry survives; the two
    diagnostics it did not are unknown rather than invented, since a fabricated
    pass would vouch for numbers nothing here can vouch for.
    """
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, _as_schema(1))

    with pytest.warns(UserWarning, match="migrated to"):
        loaded = q.load_artifact(path)

    assert loaded.schema_version == ARTIFACT_SCHEMA_VERSION
    assert loaded.measurements.phantom_mask_ok is None
    assert loaded.measurements.roi_inside_phantom is None
    assert np.isnan(loaded.measurements.phantom_fraction)
    # everything schema 1 did carry is untouched
    assert loaded.measurements.snr == artifact.measurements.snr
    assert loaded.provenance.scan == artifact.provenance.scan
    assert loaded.provenance.n_frames == artifact.provenance.n_frames
    assert np.array_equal(loaded.images.phantom_mask, artifact.images.phantom_mask)


def test_load_migrating_a_schema_2_artifact_keeps_what_it_recorded(
    tmp_path, artifact
) -> None:
    """Only the field the older schema lacked comes back unknown.

    Schema 2 measured the phantom fraction and the ROI fit; it just had no
    verdict field. The migration must not throw away the two it does have.
    """
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, _as_schema(2))

    with pytest.warns(UserWarning, match="schema 2, migrated"):
        loaded = q.load_artifact(path)

    m, before = loaded.measurements, artifact.measurements
    assert m.phantom_mask_ok is None  # the one field schema 2 lacked
    assert m.phantom_fraction == before.phantom_fraction
    assert m.roi_inside_phantom is True


def test_load_migrating_a_schema_3_artifact_leaves_the_trim_unrecorded(
    tmp_path, artifact
) -> None:
    """Schema 3 trimmed warm-up volumes but never wrote down how many.

    The count is not re-derived from the stored `trim_sec` and `tr`: that would
    publish this build's rounding as the writing build's decision, and a frame
    index mapped through a guess is worse than one a reader knows it cannot map.
    Everything schema 3 did record survives.
    """
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, _as_schema(3))

    with pytest.warns(UserWarning, match="schema 3, migrated"):
        loaded = q.load_artifact(path)

    assert loaded.provenance.n_trimmed is None  # the one field schema 3 lacked
    assert loaded.provenance.n_frames == artifact.provenance.n_frames
    assert loaded.provenance.tr == artifact.provenance.tr
    assert loaded.measurements.phantom_mask_ok is True


def test_load_migrating_a_schema_4_artifact_leaves_slice_and_contrast_unrecorded(
    tmp_path, artifact
) -> None:
    """Schema 4 chose a slice and judged a mask without writing either down.

    Neither is re-derived: the slice depends on a volume the artifact does not
    carry, and a contrast recomputed from the stored images would be this
    build's definition passed off as the writing build's measurement. The
    verdict schema 4 did record is kept as it was made.
    """
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, _as_schema(4))

    with pytest.warns(UserWarning, match="schema 4, migrated"):
        loaded = q.load_artifact(path)

    assert loaded.provenance.slice_index is None
    assert loaded.provenance.n_slices is None
    assert np.isnan(loaded.measurements.phantom_contrast)
    assert loaded.measurements.phantom_mask_ok is True
    assert loaded.settings.roi_size == artifact.settings.roi_size


def test_load_migrating_a_schema_5_artifact_reports_displacement_in_voxels(
    tmp_path, artifact
) -> None:
    """Schema 5 always measured peak motion/COM displacement in voxels.

    Unlike the other migrated fields, this is not "unknown": schema <= 5 never
    converted these two peaks to mm even when the voxel size was known, so
    "vox" is a fact about the old format, not a guess -- even though this
    fixture's own `fwhm_unit` is "mm" (voxel size known), showing the two units
    can disagree on a migrated artifact in a way they never do on a fresh one.
    """
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, _as_schema(5))

    with pytest.warns(UserWarning, match="schema 5, migrated"):
        loaded = q.load_artifact(path)

    assert loaded.measurements.displacement_unit == "vox"
    assert loaded.measurements.fwhm_unit == "mm"  # this fixture's voxel size is known
    # The stored numbers themselves are untouched by the migration -- NaN on this
    # fixture, whose motion fit does not converge for every frame (see
    # `_both_nan`: NaN != NaN, so a direct `==` would fail on a faithful copy).
    assert _both_nan(
        loaded.measurements.max_translation, artifact.measurements.max_translation
    )
    assert loaded.measurements.max_com_displacement == (
        artifact.measurements.max_com_displacement
    )


def test_load_migrating_a_schema_6_artifact_keeps_its_clipping_answers(
    tmp_path, artifact
) -> None:
    """Schema 6 always answered the clipping question, and its answers stand.

    Schema 7 lets the block be None -- "the series did not arrive as integers,
    so the rail test could not run" -- but no schema 6 document needs that: the
    build that wrote it ran the test unconditionally and recorded a bool either
    way. Rewriting them to unknown would condemn every genuinely clean scan
    along with the ones that were never checkable, and the artifact does not
    record the storage datatype to tell them apart. So the step carries them
    through untouched, which is what this pins.
    """
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, _as_schema(6))

    with pytest.warns(UserWarning, match="schema 6, migrated"):
        loaded = q.load_artifact(path)

    before, after = artifact.measurements, loaded.measurements
    assert after.clipped_any == before.clipped_any is not None
    assert after.clipped_kept == before.clipped_kept is not None
    assert after.n_clipped_kept == before.n_clipped_kept
    assert after.n_clipped_pre == before.n_clipped_pre


# Fields each schema version introduced, per document section, so a current
# document can be rewritten as the older one it grew out of (the reverse of
# `serialize.migrate._MIGRATIONS`). Division of labour with
# `test_artifact_fixtures.py`: this file's migration tests check each step in
# isolation against this hand-maintained description of the schema history;
# that file loads real `.npz` archives an old build actually wrote, which
# this table cannot stand in for (see its module docstring). Keep both.
_ADDED_IN = {
    2: {"measurements": ("phantom_fraction", "roi_inside_phantom")},
    3: {"measurements": ("phantom_mask_ok",)},
    4: {"provenance": ("n_trimmed",)},
    5: {
        "provenance": ("slice_index", "n_slices"),
        "measurements": ("phantom_contrast",),
    },
    6: {"measurements": ("displacement_unit",)},
    # 7 added no field: it widened four existing clipping fields to allow None,
    # so a schema 6 document has exactly the same keys a current one does.
    7: {},
}


def _as_schema(version: int):
    """An edit turning a current document into one at `version`."""

    def edit(document):
        sections = {
            name: dict(document[name]) for name in ("measurements", "provenance")
        }
        for added, removals in _ADDED_IN.items():
            if added > version:
                for section, names in removals.items():
                    for name in names:
                        del sections[section][name]
        return {**document, "schema_version": version, **sections}

    return edit


def _with_measurement(name: str, value: object):
    """An edit replacing one stored measurement."""
    return lambda doc: {**doc, "measurements": doc["measurements"] | {name: value}}


def _with_psf_unit(value: object):
    """An edit replacing the stored PSF unit."""
    return lambda doc: {
        **doc,
        "curves": {**doc["curves"], "psf": doc["curves"]["psf"] | {"unit": value}},
    }


def test_load_rejects_a_closed_set_value_from_outside_the_set(
    tmp_path, artifact
) -> None:
    """A stored string must be held to the set its field promises.

    `fwhm_unit`, `displacement_unit`, `pe_label` and the PSF unit are closed
    sets a reader switches on, and JSON carries none of that. Without the check
    a hand-edited or foreign document hands the reader a value its own type
    says cannot exist, and the mistake surfaces wherever that reader happens to
    branch.
    """
    for field, edit in (
        ("fwhm_unit", _with_measurement("fwhm_unit", "cm")),
        ("displacement_unit", _with_measurement("displacement_unit", "cm")),
        ("pe_label", _with_measurement("pe_label", "diagonal")),
        ("psf.unit", _with_psf_unit("cm")),
    ):
        path = q.save_artifact(artifact, tmp_path / f"{field}.nc")
        _rewrite_document(path, edit)
        with pytest.raises(q.InvalidArtifactError, match=field):
            q.load_artifact(path)


def test_load_rejects_clipped_kept_disagreeing_with_its_count(
    tmp_path, artifact
) -> None:
    """A document must not say the count is 5 but the flag is False.

    `clipped_kept` is a property of `n_clipped_kept` in the type that measures
    it, not an independent fact -- storing both is only for the flat artifact.
    """
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, _with_measurement("n_clipped_kept", 5))
    with pytest.raises(q.InvalidArtifactError, match="clipped_kept"):
        q.load_artifact(path)


def test_load_rejects_clipped_any_disagreeing_with_its_counts(
    tmp_path, artifact
) -> None:
    """`clipped_any` is derived from both clipping counts, and must still hold."""
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, _with_measurement("n_clipped_pre", 3))
    with pytest.raises(q.InvalidArtifactError, match="clipped_any"):
        q.load_artifact(path)


def test_load_rejects_fwhm_pe_null_when_pe_axis_is_known(tmp_path, artifact) -> None:
    """`fwhm_pe` is None exactly when `pe_axis` is None, never independently."""
    assert artifact.measurements.pe_axis is not None
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, _with_measurement("fwhm_pe", None))
    with pytest.raises(q.InvalidArtifactError, match="fwhm_pe"):
        q.load_artifact(path)


def test_load_rejects_a_document_missing_a_section(tmp_path, artifact) -> None:
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(path, lambda doc: {**doc, "images": {}})
    with pytest.raises(q.InvalidArtifactError, match="malformed artifact"):
        q.load_artifact(path)


def test_load_rejects_a_schema_1_archive_missing_its_measurements(
    tmp_path, artifact
) -> None:
    """A migration reads the stored document, so its failures are read failures.

    Bringing a v1 document forward assumes it carries the sections v1 carried.
    One that does not is malformed, and must be refused as such rather than
    raise the bare KeyError of whichever migration step reached for it.
    """
    path = q.save_artifact(artifact, tmp_path / "qa.nc")
    _rewrite_document(
        path,
        lambda doc: (
            {k: v for k, v in doc.items() if k != "measurements"}
            | {"schema_version": 1}
        ),
    )
    with pytest.raises(q.InvalidArtifactError, match="malformed artifact"):
        q.load_artifact(path)


def _same_scalars(left, right) -> bool:
    """Compare two scalar dataclasses, treating NaN as equal to NaN.

    An undefined metric is stored and read back as NaN, and NaN != NaN would make
    a faithful round trip look like a failure.
    """
    a, b = asdict(left), asdict(right)
    if a.keys() != b.keys():
        return False
    return all(
        x == y or (isinstance(x, float) and isinstance(y, float) and _both_nan(x, y))
        for x, y in ((a[k], b[k]) for k in a)
    )


def _both_nan(x: float, y: float) -> bool:
    return bool(np.isnan(x) and np.isnan(y))


# --------------------------------------------------------------------------
# reading and writing the stored file without going through the serializer
# --------------------------------------------------------------------------
#
# Every test above that corrupts a stored artifact does it through these two,
# and they deliberately drive `netCDF4` directly rather than the package's own
# `netcdf` module. Two reasons: a test that wrote through the writer could only
# ever produce files the writer permits, which is the opposite of what a
# rejection test needs; and reading the file back through a plain netCDF reader
# is itself the claim this container was chosen for.


# The CF marker the writer puts on a mask, and what tells one apart on the way
# back in. Spelled out here rather than imported, so a change to the marker has
# to be made in both places deliberately.
_FLAG_VALUES = np.array([0, 1], dtype=np.uint8)


def _read_netcdf(path) -> tuple[dict, dict[str, np.ndarray]]:
    """The document and every array of a stored artifact, read with netCDF4 alone.

    The coordinate variables are skipped -- a variable named for a dimension is
    that axis, derived on the way out and not part of what the artifact
    carries -- so what this returns is what `decompose` produced.
    """
    with netCDF4.Dataset(str(path)) as dataset:
        dataset.set_auto_mask(False)
        document = json.loads(dataset.getncattr("document"))
        arrays = {
            name: (
                np.asarray(variable[...] != 0)
                if "flag_values" in variable.ncattrs()
                else np.asarray(variable[...])
            )
            for name, variable in dataset.variables.items()
            if name not in dataset.dimensions
        }
    return document, arrays


def _write_netcdf(path, arrays, attributes) -> None:
    """A netCDF file holding exactly `arrays` and `attributes`, no layout rules.

    Every array gets dimensions of its own, because a test's replacement array
    generally no longer fits the axis the real one shared -- which is the point
    of it. Booleans are stored as the flagged bytes the real writer uses;
    anything else is stored as float64, so an "array" a document says is a mask
    arrives as numbers and is refused for being numbers.
    """
    with (
        netCDF4.Dataset(str(path), "w", format="NETCDF4") as dataset,
        warnings.catch_warnings(),
    ):
        # netCDF4 1.7.4 trips NumPy 2.5's deprecation of setting `.shape` on
        # every multi-dimensional write; `netcdf.write` drops the same warning,
        # and its comment says why.
        warnings.filterwarnings(
            "ignore",
            message="Setting the shape on a NumPy array",
            category=DeprecationWarning,
        )
        dataset.setncatts(attributes)
        for name, array in arrays.items():
            dimensions = tuple(f"{name}_axis{axis}" for axis in range(array.ndim))
            for dimension, length in zip(dimensions, array.shape, strict=True):
                dataset.createDimension(dimension, length)
            is_mask = array.dtype == np.bool_
            stored = dataset.createVariable(
                name, np.dtype(np.uint8 if is_mask else np.float64), dimensions
            )
            stored[...] = array.astype(np.uint8 if is_mask else np.float64)
            if is_mask:
                stored.flag_values = _FLAG_VALUES


def _rewrite_document(path, edit) -> None:
    """Rewrite the stored document through `edit`, keeping every array as it is."""
    document, arrays = _read_netcdf(path)
    _write_netcdf(path, arrays, {"document": json.dumps(edit(document))})


# --------------------------------------------------------------------------
# what the netCDF file says about itself
# --------------------------------------------------------------------------


def test_the_file_is_netcdf4(tmp_path, artifact) -> None:
    """HDF5's signature: what a netCDF-4 file starts with, and what is sniffed.

    Also what `load_artifact` dispatches on -- the container is decided by
    these bytes and never by the file's name, because `--artifact` writes
    whatever name the user asked for.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    assert saved.read_bytes()[:8] == b"\x89HDF\r\n\x1a\n"
    with netCDF4.Dataset(str(saved)) as dataset:
        assert dataset.data_model == "NETCDF4"
        # Flat: xarray's `open_dataset` sees only the root group, so everything
        # a reader needs has to be in it.
        assert not dataset.groups


def test_the_document_rides_as_an_ascii_global_attribute(tmp_path, artifact) -> None:
    """One attribute, readable as text, holding the whole non-array record.

    This is what MATLAB reads as `jsondecode(ncreadatt(f, '/', 'document'))`
    and R as `ncatt_get(f, 0, "document")`, so it has to be text a reader can
    take without being told an encoding.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        stored = dataset.getncattr("document")
    assert isinstance(stored, str) and stored.isascii()
    assert json.loads(stored)["schema_version"] == artifact.schema_version


def test_the_cheap_attributes_answer_without_decoding_the_document(
    tmp_path, artifact
) -> None:
    """A reader that never touches JSON can still tell what the file is."""
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        attributes = {name: dataset.getncattr(name) for name in dataset.ncattrs()}
    assert attributes["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert attributes["Conventions"] == "CF-1.10"
    assert "fmri-qa" in attributes["title"]
    assert attributes["source"].startswith("fmri-qa-core ")


# How each JSON scalar is published as an attribute. `bool` before `int`
# because a Python bool is an int, and a verdict stored as a number a reader
# has to know is a verdict would be the guessing the flagged masks avoid.
_ATTRIBUTE_DTYPES = ((bool, np.uint8), (int, np.int32), (float, np.float64))


def _section_attributes(path, section: str) -> dict[str, object]:
    """Every `<section>.*` global attribute of a stored artifact, by field name."""
    with netCDF4.Dataset(str(path)) as dataset:
        return {
            name.removeprefix(f"{section}."): dataset.getncattr(name)
            for name in dataset.ncattrs()
            if name.startswith(f"{section}.")
        }


def test_every_resolved_measurement_is_published_as_its_own_attribute(
    tmp_path, artifact
) -> None:
    """`ncreadatt(f, '/', 'measurements.snr')`: a number without a JSON parser.

    The attribute is the document's own value in the netCDF type that holds it,
    so a reader that never decodes the document still gets exactly what the
    document says -- including a NaN, which means the estimator could not
    resolve the value.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    document, _ = _read_netcdf(saved)
    measured = document["measurements"]
    published = _section_attributes(saved, "measurements")

    assert set(published) == {k for k, v in measured.items() if v is not None}
    for name, value in measured.items():
        if value is None:
            continue
        stored = published[name]
        if isinstance(value, str):
            assert stored == value, name
            continue
        # `getncattr` is typed as returning anything at all, so the numeric
        # attributes are named as arrays before their dtype is asked about.
        number = np.asarray(stored)
        expected = next(d for kind, d in _ATTRIBUTE_DTYPES if isinstance(value, kind))
        assert number.dtype == expected, name
        assert number == value or (np.isnan(number) and np.isnan(value)), name


def test_a_measurement_the_document_calls_null_has_no_attribute(
    tmp_path, artifact
) -> None:
    """Absence is how "does not apply" is spelled, since NaN already means more.

    The fixture's clipping check runs, so `clip_ceiling` is null because the
    series has no rail -- not because nothing looked. An attribute cannot be
    null, and publishing NaN for it would say the estimator tried and failed.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    document, _ = _read_netcdf(saved)
    published = _section_attributes(saved, "measurements")

    assert document["measurements"]["clip_ceiling"] is None
    assert "clip_ceiling" not in published
    # and the distinction it protects: a NaN measurement *is* published
    assert np.isnan(document["measurements"]["max_translation"])
    assert np.isnan(np.asarray(published["max_translation"]))


def test_save_refuses_a_measurement_no_attribute_can_hold(tmp_path, artifact) -> None:
    """An integer past NC_INT is refused rather than published wrapped around."""
    counts = replace(artifact.measurements, n_clipped_pre=2**31, clipped_any=True)
    with pytest.raises(q.InvalidArtifactError, match="netCDF integer"):
        q.save_artifact(replace(artifact, measurements=counts), tmp_path / "qa.nc")
    assert not (tmp_path / "qa.nc").exists()


def test_encode_refuses_an_empty_list(artifact) -> None:
    """An attribute is a *typed* vector, and an empty list names no type."""
    document, arrays = decompose(artifact)
    document["provenance"]["voxel_mm"] = []
    with pytest.raises(ValueError, match="voxel_mm is an empty list"):
        netcdf.encode(document, arrays)


def test_encode_refuses_a_value_no_attribute_can_hold(artifact) -> None:
    """A list of objects: a JSON shape with no attribute form at all.

    A nested object flattens into the name, and a list of ints, floats or
    strings becomes a vector or a line of words. An object *inside* a list has
    nowhere to go;
    `validate_document` refuses it before `save_artifact` reaches this, so the
    fallthrough answers for `encode` called directly.
    """
    document, arrays = decompose(artifact)
    document["measurements"]["snr"] = [{"value": 1.0}]
    with pytest.raises(ValueError, match="no attribute can hold"):
        netcdf.encode(document, arrays)


def test_the_stored_document_is_ascii_even_when_the_text_is_not(
    tmp_path, artifact
) -> None:
    """Unicode rides as `\\uXXXX`, so a consumer needs no encoding to read it.

    `json.dumps` escapes by default; this pins that, because a netCDF text
    attribute is bytes a reader takes as characters without being told which.
    """
    prov = replace(artifact.provenance, scan="sujet_créé_Ω_頭部.nii.gz")
    saved = q.save_artifact(replace(artifact, provenance=prov), tmp_path / "u.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        assert dataset.getncattr("document").isascii()
    assert q.load_artifact(saved).provenance.scan == "sujet_créé_Ω_頭部.nii.gz"


def test_a_name_python_holds_as_a_lone_surrogate_survives(tmp_path, artifact) -> None:
    """What a Windows file name with an undecodable byte becomes in Python.

    It reaches `json.dumps` as an unpaired surrogate, which has no UTF-8 form;
    the ASCII escaping is what keeps the write from raising on it.
    """
    name = "bad_\udcff_name.nii.gz"
    prov = replace(artifact.provenance, scan=name)
    saved = q.save_artifact(replace(artifact, provenance=prov), tmp_path / "s.qa.nc")
    assert q.load_artifact(saved).provenance.scan == name


def test_every_recorded_provenance_field_is_published_as_its_own_attribute(
    tmp_path, artifact
) -> None:
    """`ncreadatt(f, '/', 'provenance.tr')`: the run's own record, un-decoded.

    The rule the measurements follow, applied to the section that says where
    the series came from -- with one shape the measurements never take. A JSON
    list is a vector attribute of its element type, so `voxel_mm` is three
    doubles and `matrix` two integers, each arriving in one call.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    document, _ = _read_netcdf(saved)
    recorded = document["provenance"]
    published = _section_attributes(saved, "provenance")

    assert set(published) == {k for k, v in recorded.items() if v is not None}
    for name, value in recorded.items():
        if value is None:
            continue
        stored = published[name]
        if isinstance(value, str):
            assert stored == value, name
            continue
        # `getncattr` is typed as returning anything at all, so the numeric
        # attributes are named as arrays before their dtype is asked about.
        number = np.asarray(stored)
        element = value[0] if isinstance(value, list) else value
        expected = next(d for kind, d in _ATTRIBUTE_DTYPES if isinstance(element, kind))
        assert number.dtype == expected, name
        shape = (len(value),) if isinstance(value, list) else ()
        assert number.shape == shape, name
        assert np.array_equal(number, value), name

    assert np.asarray(published["voxel_mm"]).shape == (3,)
    assert np.asarray(published["matrix"]).shape == (2,)


def test_a_provenance_field_the_document_calls_null_has_no_attribute(
    tmp_path, artifact
) -> None:
    """Absence is how "not recorded" is spelled, as it is for a measurement.

    The synthetic phantom's sidecar gives a flip angle and no echo time, and
    nothing anywhere names a coil. A netCDF attribute cannot say "nobody wrote
    this down", and a zero would say something else entirely.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    document, _ = _read_netcdf(saved)
    published = _section_attributes(saved, "provenance")

    assert document["provenance"]["te"] is None
    assert document["provenance"]["coil"] is None
    assert not {"te", "coil"} & set(published)
    assert published["flip_angle"] == document["provenance"]["flip_angle"]


def test_every_setting_is_published_as_its_own_attribute(tmp_path, artifact) -> None:
    """`ncreadatt(f, '/', 'settings.roi_size')`: what the run was asked for.

    The same rule as the measurements, applied to the knobs: a float is a
    double, an integer an NC_INT, the method names are text, and an override
    nobody gave -- `pe_axis_override` is None unless `--pe-axis` was passed --
    is no attribute at all rather than a number that would read as an axis.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    document, _ = _read_netcdf(saved)
    asked = document["settings"]
    published = _section_attributes(saved, "settings")

    assert set(published) == {k for k, v in asked.items() if v is not None}
    assert asked["pe_axis_override"] is None
    assert "pe_axis_override" not in published
    assert published["detrend"] == asked["detrend"]
    assert published["center"] == asked["center"]
    for name in ("trim_sec", "roi_size", "detrend_order"):
        number = np.asarray(published[name])
        expected = next(
            d for kind, d in _ATTRIBUTE_DTYPES if isinstance(asked[name], kind)
        )
        assert number.dtype == expected, name
        assert number == asked[name], name


def test_provenance_text_is_published_as_the_scanner_supplied_it(
    tmp_path, artifact
) -> None:
    """Unlike a measurement, this text is not this package's to constrain.

    A scan name comes from a file system and a manufacturer from a scanner
    header, so neither is a closed vocabulary that could be held to ASCII.
    netCDF4 writes a `str` attribute as UTF-8 NC_CHAR, and what a reader gets
    back is the same string.
    """
    prov = replace(
        artifact.provenance, scan="sujet_créé_Ω_頭部.nii.gz", manufacturer="Siemens™"
    )
    saved = q.save_artifact(replace(artifact, provenance=prov), tmp_path / "u.qa.nc")
    published = _section_attributes(saved, "provenance")

    assert published["scan"] == "sujet_créé_Ω_頭部.nii.gz"
    assert published["manufacturer"] == "Siemens™"
    assert q.load_artifact(saved).provenance == prov


def test_a_lone_surrogate_name_is_published_escaped_rather_than_refused(
    tmp_path, artifact
) -> None:
    """The one string with no UTF-8 form: lossy but present beats no file.

    A Windows file name with an undecodable byte reaches Python as an unpaired
    surrogate, which `str.encode` cannot render. The convenience attribute
    carries the escape rather than failing the save; the document beside it
    still spells the name exactly, and that is what `load_artifact` reads.
    """
    name = "bad_\udcff_name.nii.gz"
    prov = replace(artifact.provenance, scan=name)
    saved = q.save_artifact(replace(artifact, provenance=prov), tmp_path / "s.qa.nc")

    assert _section_attributes(saved, "provenance")["scan"] == "bad_\\udcff_name.nii.gz"
    assert q.load_artifact(saved).provenance.scan == name


def test_save_refuses_a_provenance_integer_no_attribute_can_hold(
    tmp_path, artifact
) -> None:
    """The NC_INT bound the measurements are held to, over a reachable field.

    `n_trimmed` is only required to be non-negative, so a document can carry a
    count past NC_INT and still be a valid artifact; publishing it wrapped
    around would be a number a reader has no way to distrust.
    """
    prov = replace(artifact.provenance, n_trimmed=2**31)
    with pytest.raises(q.InvalidArtifactError, match="netCDF integer"):
        q.save_artifact(replace(artifact, provenance=prov), tmp_path / "qa.nc")
    assert not (tmp_path / "qa.nc").exists()


def test_a_whole_number_setting_is_published_as_a_double(tmp_path, artifact) -> None:
    """`trim_sec=5` is a float field given an int: NC_DOUBLE, not NC_INT."""
    settings = q.AnalysisSettings(trim_sec=5, roi_size=9)
    saved = q.save_artifact(
        replace(artifact, settings=settings), tmp_path / "scan.qa.nc"
    )
    trim = np.asarray(_section_attributes(saved, "settings")["trim_sec"])
    assert trim.dtype == np.float64
    assert trim == 5.0


def test_a_voxel_size_mixing_ints_and_floats_saves_as_doubles(
    tmp_path, artifact
) -> None:
    """`(3.0, 3, 3.0)` is one vector of doubles, not a list of two kinds."""
    prov = replace(artifact.provenance, voxel_mm=(3.0, 3, 3.0))
    saved = q.save_artifact(replace(artifact, provenance=prov), tmp_path / "v.qa.nc")
    voxel = np.asarray(_section_attributes(saved, "provenance")["voxel_mm"])
    assert voxel.dtype == np.float64
    assert voxel.shape == (3,)
    assert q.load_artifact(saved).provenance.voxel_mm == (3.0, 3.0, 3.0)


def test_every_curve_and_image_scalar_is_published_as_its_own_attribute(
    tmp_path, artifact
) -> None:
    """The last of the document: nothing in it now needs JSON to read.

    These two sections nest -- the `psf` block, the `roi` box -- and the nest
    flattens into the name, so `curves.psf.fwhm` is a two-double vector and
    `images.roi.row0` an integer, by the same table as every other section. The
    one new shape is a list of words: `curves.psf.labels` is one text, `PE RO`,
    spelled the way CF spells `flag_meanings`.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    document, _ = _read_netcdf(saved)

    for section in ("curves", "images"):
        recorded = dict(netcdf._leaves(section, document[section]))
        published = _section_attributes(saved, section)
        assert set(published) == {
            name.removeprefix(f"{section}.") for name in recorded
        }, section
        for path, value in recorded.items():
            stored = published[path.removeprefix(f"{section}.")]
            if isinstance(value, list) and isinstance(value[0], str):
                assert stored == " ".join(value), path
                continue
            if isinstance(value, str):
                assert stored == value, path
                continue
            number = np.asarray(stored)
            element = value[0] if isinstance(value, list) else value
            expected = next(
                d for kind, d in _ATTRIBUTE_DTYPES if isinstance(element, kind)
            )
            assert number.dtype == expected, path
            assert np.array_equal(number, value), path

    assert _section_attributes(saved, "curves")["psf.labels"] == "PE RO"
    assert np.asarray(_section_attributes(saved, "images")["has_ghost"]) == 1


# The axes the layout publishes, as a reader meets them. Spelled out rather
# than read back off the file, since the point is that these names are the
# contract a foreign reader is handed -- and each of them is also the name of
# the coordinate variable carrying that axis's values.
_DIMENSIONS = {
    "frame",
    "frequency",
    "image_axis",
    "roi_width",
    "psf_direction",
    "psf_lag",
    "psf_model_sample",
    "row",
    "col",
    "hull_vertex",
    "hull_coord",
}


def _declared(path) -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    """Each variable's dimensions and each dimension's length, read as netCDF."""
    with netCDF4.Dataset(str(path)) as dataset:
        declared = {name: var.dimensions for name, var in dataset.variables.items()}
        lengths = {name: len(dim) for name, dim in dataset.dimensions.items()}
    return declared, lengths


def test_every_stored_array_is_declared_over_named_dimensions(
    tmp_path, artifact
) -> None:
    """The file says which axis each array lies along, not just how long it is."""
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    declared, lengths = _declared(saved)

    assert set(declared) == set(decompose(artifact)[1]) | _DIMENSIONS
    assert all(dimensions for dimensions in declared.values())
    assert lengths["frame"] == artifact.provenance.n_frames
    assert (lengths["row"], lengths["col"]) == artifact.images.signal.shape


def test_curves_along_one_axis_share_one_dimension(tmp_path, artifact) -> None:
    """Sharing a dimension is the file's claim that two arrays share an axis.

    A reader that opens this in xarray gets the per-frame traces aligned on
    `frame` without being told which of them belong together; a bag of
    equal-length vectors would leave it guessing.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    declared, _ = _declared(saved)

    assert declared["curves.roi_signal"] == declared["curves.time"] == ("frame",)
    assert declared["curves.spectrum_hz"] == declared["curves.spectrum_magnitude"]
    assert declared["curves.translation"] == ("frame", "image_axis")
    assert declared["images.sfnr"] == declared["images.phantom_mask"] == ("row", "col")
    assert declared["images.ghost.pe_ghost"] == ("row", "col")
    assert declared["curves.weisskoff.cv"] == declared["curves.weisskoff.rdc"]


def test_axes_that_only_happen_to_match_stay_separate(tmp_path, artifact) -> None:
    """Three length-2 axes, three meanings: none of them is the others.

    `image_axis` is (row, col) in array order, `psf_direction` is (PE, RO) in
    the order the PSF curves use (or axis0, axis1 when no PE axis resolved),
    and `hull_coord` is the hull's (x, y) plot order. Declaring them as one
    dimension because they are all 2 long would publish a relationship that is
    not there.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    declared, lengths = _declared(saved)

    paired = ("image_axis", "psf_direction", "hull_coord")
    assert all(lengths[axis] == 2 for axis in paired)
    assert declared["curves.translation"][1] == "image_axis"
    assert declared["curves.psf.empirical"][0] == "psf_direction"
    assert declared["images.phantom_hull"][1] == "hull_coord"
    # and the two PSF abscissas are not each other either
    assert declared["curves.psf.empirical"][1] != declared["curves.psf.model"][1]


# --------------------------------------------------------------------------
# the coordinate variables
# --------------------------------------------------------------------------
#
# CF (section 1.3) spells an axis's values as a 1-D variable named for the
# dimension itself. Without one a reader is told a trace lies along `frame` but
# not where along it, and xarray reports "dimensions without coordinates"; with
# one, a plot has an abscissa and two artifacts have something to align on.
# They are derived when the file is written and never read back -- exactly like
# the `measurements.*` attributes -- so these read the file rather than the
# package.


# What each axis's coordinate holds. An axis that is a position carries the
# position as NC_INT; an axis the artifact already publishes values for carries
# those values, in the dtype the curve itself has.
_COORDINATE_DTYPES = {
    "frame": np.int32,
    "frequency": np.float64,
    "image_axis": np.int32,
    "roi_width": np.float64,
    "psf_direction": np.int32,
    "psf_lag": np.int32,
    "psf_model_sample": np.int32,
    "row": np.int32,
    "col": np.int32,
    "hull_vertex": np.int32,
    "hull_coord": np.int32,
}

# The axes whose coordinate is the index along them, and the three length-2
# axes whose two positions are named instead.
_INDEX_AXES = ("frame", "row", "col", "psf_lag", "psf_model_sample", "hull_vertex")
_LABEL_AXES = {"image_axis": "row col", "psf_direction": "PE RO", "hull_coord": "x y"}


def _axes(path) -> dict[str, tuple[np.ndarray, dict[str, object]]]:
    """Each dimension's own coordinate variable: its values and its attributes."""
    with netCDF4.Dataset(str(path)) as dataset:
        dataset.set_auto_mask(False)
        return {
            axis: (
                np.asarray(dataset[axis][...]),
                {
                    name: dataset[axis].getncattr(name)
                    for name in dataset[axis].ncattrs()
                },
            )
            for axis in dataset.dimensions
        }


def test_every_dimension_carries_a_coordinate_variable(tmp_path, artifact) -> None:
    """One 1-D variable per axis, named for it and as long as it is.

    This is the whole claim: a reader that opens the file finds every axis
    resolved, rather than eleven dimensions it has to number itself.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    _, lengths = _declared(saved)
    axes = _axes(saved)
    with netCDF4.Dataset(str(saved)) as dataset:
        declared = {
            axis: (dataset[axis].dimensions, dataset[axis].dtype)
            for axis in dataset.dimensions
        }

    assert set(declared) == _DIMENSIONS
    for axis, (dimensions, dtype) in declared.items():
        assert dimensions == (axis,), axis
        assert dtype == _COORDINATE_DTYPES[axis], axis
    assert {axis: len(values) for axis, (values, _) in axes.items()} == lengths
    assert all("long_name" in attributes for _, attributes in axes.values())


def test_an_index_axis_counts_from_zero(tmp_path, artifact) -> None:
    """Where the axis is a position, the coordinate is that position."""
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    axes = _axes(saved)

    for axis in _INDEX_AXES:
        values, _ = axes[axis]
        assert np.array_equal(values, np.arange(len(values), dtype=np.int32)), axis


def test_a_value_axis_is_the_curve_it_labels(tmp_path, artifact) -> None:
    """Two axes have real values already, and the coordinate is those values.

    The curves stay exactly where they are under their own dotted names: the
    coordinate is a second spelling of the same numbers, because the dimension's
    name is the only one CF reads as the axis.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    axes = _axes(saved)
    _, arrays = decompose(artifact)

    assert np.array_equal(axes["frequency"][0], arrays["curves.spectrum_hz"])
    assert np.array_equal(axes["roi_width"][0], arrays["curves.weisskoff.roi_sizes"])
    assert axes["frequency"][1]["units"] == "Hz"
    # and the curves themselves are still there to be read under their own names
    assert {"curves.spectrum_hz", "curves.weisskoff.roi_sizes"} <= set(arrays)


def test_the_frame_axis_counts_the_way_the_artifact_counts(tmp_path, artifact) -> None:
    """Frame 0 is the first *analyzed* volume, not the first acquired one.

    Every frame index in the artifact counts from the trimmed series (see
    `Provenance`), so `measurements.outlier_worst_frame` indexes this
    coordinate directly and the acquired volume number is the index plus
    `provenance.n_trimmed`. A reader that took the coordinate for an
    acquisition number would be wrong by the warm-up, so the offset is named in
    the coordinate's own comment rather than left to be inferred.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    frame, attributes = _axes(saved)["frame"]

    assert np.array_equal(frame, np.arange(artifact.provenance.n_frames))
    assert artifact.provenance.n_trimmed  # the fixture really does drop warm-up
    worst = artifact.measurements.outlier_worst_frame
    assert frame[worst] == worst
    assert int(np.argmax(artifact.curves.outlier_fraction)) == worst
    # `getncattr` is typed as returning anything at all, so the comment is
    # named as text before it is searched.
    assert "n_trimmed" in str(attributes["comment"])


def test_a_named_axis_carries_its_labels_as_flags(tmp_path, artifact) -> None:
    """(row, col), (PE, RO) and (x, y) are named as flagged ints, not strings.

    NC_STRING is a netCDF-4-only type that Octave's netCDF package and older
    readers handle poorly, and the flag vocabulary already says exactly this
    much for the masks -- so the three length-2 axes use it too.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    axes = _axes(saved)

    for axis, meanings in _LABEL_AXES.items():
        values, attributes = axes[axis]
        flags = np.asarray(attributes["flag_values"])
        assert np.array_equal(values, [0, 1]), axis
        assert np.array_equal(flags, [0, 1]), axis
        assert flags.dtype == np.int32, axis
        assert attributes["flag_meanings"] == meanings, axis


def test_every_per_frame_variable_points_at_the_time_axis(tmp_path, artifact) -> None:
    """The frame index is one answer; the seconds are the other, and both ride.

    `curves.time` cannot be the `frame` coordinate -- a coordinate variable is
    named for its dimension -- so it is named as an auxiliary coordinate
    instead, which is what makes xarray hand a reader
    `ds["curves.roi_signal"].coords["curves.time"]`. The two PSF sample axes
    work the same way, and their lags are 2-D on top of that.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    declared, _ = _declared(saved)
    with netCDF4.Dataset(str(saved)) as dataset:
        labelled = {
            name: dataset[name].getncattr("coordinates")
            for name in declared
            if "coordinates" in dataset[name].ncattrs()
        }

    per_frame = {
        name
        for name, dimensions in declared.items()
        if dimensions[:1] == ("frame",) and name not in _DIMENSIONS
    }
    assert len(per_frame) > 1
    for name in per_frame - {"curves.time"}:
        assert labelled[name] == "curves.time", name
    # An array never names itself as its own label.
    assert "curves.time" not in labelled
    assert labelled["curves.psf.empirical"] == "curves.psf.displacement"
    assert labelled["curves.psf.model"] == "curves.psf.model_x"
    assert "curves.psf.displacement" not in labelled


def test_the_coordinates_are_stored_plain(tmp_path, artifact) -> None:
    """No filters and no chunking on eleven short vectors of ascending numbers.

    A deflated, checksummed variable costs HDF5 a couple of kilobytes of filter
    and chunk-index metadata whatever it holds, which for these would be most
    of what they add: the eleven axes grow the phantom's artifact by 3,322 B
    stored plain, against 27,265 B filtered. The checksum is not missed,
    because nothing reads them back -- `load_artifact` rebuilds the artifact
    from the arrays and the document.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        stored = {
            axis: (dataset[axis].filters(), dataset[axis].chunking())
            for axis in dataset.dimensions
        }

    assert set(stored) == _DIMENSIONS
    for axis, (filters, chunking) in stored.items():
        assert not any(filters.values()), (axis, filters)
        assert chunking == "contiguous", axis


def test_the_reader_ignores_the_coordinate_variables(tmp_path, artifact) -> None:
    """Derived on the way out, and not a word of them on the way back in.

    The dotted arrays and the JSON document stay the single source of truth, so
    `compose` is handed exactly what `decompose` produced -- an axis it has no
    field for never reaches it, and a coordinate cannot become a second answer
    to a question the document already answers.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    _, arrays = netcdf.read(saved)

    assert set(arrays) == set(decompose(artifact)[1])
    assert not set(arrays) & _DIMENSIONS
    loaded = q.load_artifact(saved)
    assert np.array_equal(loaded.curves.time, artifact.curves.time)
    assert np.array_equal(loaded.curves.spectrum_hz, artifact.curves.spectrum_hz)
    assert np.array_equal(loaded.images.phantom_hull, artifact.images.phantom_hull)


def test_an_artifact_without_ghost_regions_still_carries_every_axis(
    tmp_path, artifact
) -> None:
    """The one optional section owns no axis, so nothing is lost when it is.

    `images.ghost` is the only part of an artifact that can be absent, and its
    four masks lie along `row`/`col` like every other image -- so a ghost-less
    artifact declares the same eleven axes and resolves all eleven. The rest of
    the `replace` is what "no PE axis resolved" means elsewhere in the artifact:
    the ghost regions, `pe_axis`, `pe_label`, `fwhm_pe`/`fwhm_ro`, and the PSF
    labels go together.
    """
    without = replace(
        artifact,
        images=replace(artifact.images, ghost=None),
        measurements=replace(
            artifact.measurements,
            pe_axis=None,
            pe_label="?",
            fwhm_pe=None,
            fwhm_ro=None,
        ),
        curves=replace(
            artifact.curves,
            psf=replace(artifact.curves.psf, labels=("axis0", "axis1")),
        ),
    )
    saved = q.save_artifact(without, tmp_path / "ng.qa.nc")
    declared, _ = _declared(saved)

    assert q.load_artifact(saved).images.ghost is None
    assert not [name for name in declared if name.startswith("images.ghost.")]
    axes = _axes(saved)
    assert set(axes) == _DIMENSIONS
    # The direction labels are this artifact's, not a fixed vocabulary: a file
    # that said "PE RO" here would contradict its own document.
    _, attributes = axes["psf_direction"]
    assert attributes["flag_meanings"] == "axis0 axis1"


def test_encode_omits_an_axis_whose_values_are_not_stored(artifact) -> None:
    """A coordinate is derived or left out; it is never invented.

    `encode` takes whatever arrays it is handed, and an axis whose values live
    in an array that is not among them gets no coordinate rather than a made-up
    one -- and nothing points at a label the file does not carry either.
    """
    document, arrays = decompose(artifact)
    without = {
        k: v
        for k, v in arrays.items()
        if k not in ("curves.spectrum_hz", "curves.time")
    }
    content = netcdf.encode(document, without)

    assert {"frequency", "frame"} <= set(content.dimensions)
    assert "frequency" not in content.coordinates
    assert "frame" in content.coordinates  # an index needs nothing but a length
    assert "coordinates" not in content.variables["curves.roi_signal"].attributes


def test_encode_refuses_an_axis_with_no_coordinate_declared(
    artifact, monkeypatch
) -> None:
    """An axis the coordinate table has never heard of stops the write.

    The failure the test above rules out, seen from the other side: an axis
    added to the variable layout and forgotten here is refused by name rather
    than written as a dimension a reader cannot resolve.
    """
    document, arrays = decompose(artifact)
    monkeypatch.delitem(netcdf._COORDINATES, "frame")
    with pytest.raises(ValueError, match="frame axis has no coordinate"):
        netcdf.encode(document, arrays)


def test_every_axis_the_layout_uses_has_a_coordinate_declared() -> None:
    """Two hand-written tables, one contract: an axis needs an entry in both.

    The dimensions a variable is declared over and the values a reader is
    handed for them are both published claims, so neither table is derived from
    the other and adding an axis to one without the other is caught here rather
    than by a reader.
    """
    used = {axis for layout in netcdf._LAYOUT.values() for axis in layout.dimensions}
    assert used == set(netcdf._COORDINATES) == _DIMENSIONS


def test_masks_are_stored_as_cf_flagged_bytes(tmp_path, artifact) -> None:
    """netCDF has no boolean, so a mask is 0/1 bytes that say what they mean.

    The flags are what makes the file self-describing enough to reconstruct a
    `bool` array from it -- and what a reader with no fmriqc knowledge reads to
    learn that 1 is inside the phantom.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        dataset.set_auto_mask(False)
        mask = dataset["images.phantom_mask"]
        stored = np.asarray(mask[...])
        attributes = {name: mask.getncattr(name) for name in mask.ncattrs()}

    assert stored.dtype == np.uint8
    assert set(np.unique(stored)) <= {0, 1}
    assert np.array_equal(attributes["flag_values"], _FLAG_VALUES)
    assert attributes["flag_meanings"] == "outside inside"
    assert q.load_artifact(saved).images.phantom_mask.dtype == np.bool_


def test_the_units_a_reader_is_told_are_the_ones_that_are_certain(
    tmp_path, artifact
) -> None:
    """Seconds, hertz and percent are labelled; a unit the file cannot know is not.

    The PSF abscissas are mm or voxels depending on what the header gave, so
    they carry a long name and no `units` rather than a guess.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        attributes = {
            name: set(variable.ncattrs())
            for name, variable in dataset.variables.items()
        }
        units = {
            name: dataset[name].getncattr("units")
            for name in ("curves.time", "curves.spectrum_hz", "curves.shear_pct")
        }

    assert units == {
        "curves.time": "s",
        "curves.spectrum_hz": "Hz",
        "curves.shear_pct": "percent",
    }
    assert "units" not in attributes["curves.psf.displacement"]
    assert all("long_name" in value for value in attributes.values())


def test_every_array_is_compressed_and_checksummed(tmp_path, artifact) -> None:
    """Deflate and a Fletcher-32 checksum on every array, floats shuffled.

    The coordinate variables are deliberately excluded and covered by
    `test_the_coordinates_are_stored_plain`: they are a few hundred bytes of
    ascending numbers, and a filter pipeline costs more metadata than they hold
    data.

    The checksum is the one the zip container gave the `.npz` for free and
    netCDF-3 would have dropped: without it a flipped byte in an image reads
    back as a plausible number.

    What is asserted about `shuffle` is that the filter is *on* for the floats
    and off for the byte masks, not that it makes this file smaller -- on this
    fixture it does not. The phantom is stored as `uint16`, so its mean image
    holds only a few hundred distinct float64 values and plain deflate finds
    runs the shuffle breaks up: 138,250 B with the filter against 134,219 B
    without. Shuffle is kept on for the acquisitions the container is for,
    whose mean and SFNR images are noisy float64 with a distinct value in
    nearly every voxel, where it saves around 13%.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    with netCDF4.Dataset(str(saved)) as dataset:
        filters = {
            name: (variable.filters(), variable.dtype)
            for name, variable in dataset.variables.items()
            if name not in dataset.dimensions
        }

    assert filters  # a layout with no variables would pass every claim below
    for name, (applied, dtype) in filters.items():
        assert applied["zlib"] and applied["complevel"] == 4, name
        assert applied["fletcher32"], name
        assert applied["shuffle"] == (dtype != np.uint8), name


def test_loaded_arrays_are_plain_native_endian_ndarrays(tmp_path, artifact) -> None:
    """What a caller gets is an ordinary array, not a masked or byte-swapped one.

    netCDF4 masks `_FillValue` and out-of-range values unless told not to, and
    a `MaskedArray` reaching `compose` would make a fill value indistinguishable
    from a measurement. Byte order is the same kind of claim one level down: an
    artifact written on one machine and read on another must arrive as numbers
    this machine can compute with directly.
    """
    loaded = q.load_artifact(q.save_artifact(artifact, tmp_path / "scan.qa.nc"))
    for array in (
        loaded.images.signal,
        loaded.images.phantom_mask,
        loaded.curves.time,
        loaded.curves.translation,
    ):
        assert type(array) is np.ndarray
        assert not isinstance(array, np.ma.MaskedArray)
        assert array.dtype.byteorder in ("=", "|")


def test_a_flipped_byte_inside_an_array_is_refused(tmp_path, artifact) -> None:
    """A corrupted array fails to read rather than reading as wrong numbers.

    Written as a file that is nearly all array -- one variable of incompressible
    noise, whose chunk is much the largest thing in it -- so that the byte
    flipped in the middle of it is inside that chunk whatever HDF5 does with
    the metadata around it. The rest is HDF5's fixed overhead, the stored
    document and its attributes, and the `row`/`col` axes the one variable
    declares -- a few tens of kilobytes, so the array is made large enough to
    dwarf them.
    """
    noise = np.random.default_rng(0).standard_normal((256, 256))
    document, _ = decompose(artifact)
    content = netcdf.encode(document, {"images.signal": noise})
    path = tmp_path / "noise.nc"
    netcdf.write(content, path)
    raw = bytearray(path.read_bytes())
    assert len(raw) < noise.nbytes * 1.6  # the array really is most of the file

    raw[len(raw) // 2] ^= 0xFF
    path.write_bytes(bytes(raw))
    with pytest.raises(q.InvalidArtifactError):
        netcdf.read(path)


def test_a_flipped_byte_anywhere_is_refused_or_harmless(tmp_path, artifact) -> None:
    """However a stored artifact is damaged, `load_artifact` is what answers.

    A reader of a QA archive must not have to catch whichever exception an HDF5
    error, a JSON parse or a shape check happened to raise; one type means "this
    file is not a readable artifact" and nothing else escapes. The offsets are
    landmarks rather than a random sweep, so the test says the same thing on
    every run: the signature, the superblock behind it, the text of the stored
    document, and the tail where the last chunk lies.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.nc")
    whole = saved.read_bytes()
    document_at = whole.find(b'"schema_version"')
    assert document_at > 0  # the document is stored as plain text, so this finds it
    path = tmp_path / "damaged.nc"

    for offset in (0, 64, document_at + 8, len(whole) - 4096, len(whole) - 1):
        damaged = bytearray(whole)
        damaged[offset] ^= 0xFF
        path.write_bytes(bytes(damaged))
        try:
            loaded = q.load_artifact(path)
        except q.InvalidArtifactError:
            continue
        # A flip that lands in slack space changes nothing a reader can see.
        assert np.array_equal(loaded.images.sfnr, artifact.images.sfnr), offset


def test_an_artifact_with_no_hull_round_trips(tmp_path, artifact) -> None:
    """A phantom too small to outline stores an empty array, and reads back one.

    `_convex_hull` yields `(0, 2)` for a mask with no area (see
    `analysis/build.py`), which netCDF-3 could not have stored at all: a
    zero-length dimension there is *the* unlimited one, of which a file may
    have one. netCDF-4 has ordinary zero-length dimensions.
    """
    images = replace(artifact.images, phantom_hull=np.zeros((0, 2)))
    saved = q.save_artifact(replace(artifact, images=images), tmp_path / "flat.qa.nc")
    loaded = q.load_artifact(saved)

    assert loaded.images.phantom_hull.shape == (0, 2)
    _, lengths = _declared(saved)
    assert lengths["hull_vertex"] == 0
    assert np.array_equal(loaded.images.signal, artifact.images.signal)
    # and the axis still carries a coordinate variable, of no length
    with netCDF4.Dataset(str(saved)) as dataset:
        vertex = dataset["hull_vertex"]
        assert vertex.dimensions == ("hull_vertex",)
        assert np.asarray(vertex[...]).shape == (0,)


def test_xarray_opens_the_artifact_without_a_warning(tmp_path, artifact) -> None:
    """`xr.open_dataset` is the one-line path a notebook takes to an artifact."""
    saved = str(q.save_artifact(artifact, tmp_path / "scan.qa.nc"))
    # Imported here, before the filter, and not at the top of the module: what
    # is asserted is that *opening the file* warns about nothing, and importing
    # either library under `error` raises the netCDF4 wheel's own Cython
    # `RuntimeWarning` -- a defect in the wheel that no artifact can fix, and
    # one a test of the file must not be able to trip over.
    import xarray as xr

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with xr.open_dataset(saved) as dataset:
            dimensions = set(dataset.sizes)
            variables = set(dataset.data_vars)
            attributes = dict(dataset.attrs)
            sfnr = dataset["images.sfnr"].to_numpy()
            time = dataset["curves.time"]

    assert dimensions == _DIMENSIONS
    assert {"curves.weisskoff.cv", "images.ghost.pe_ghost"} <= variables
    assert attributes["schema_version"] == artifact.schema_version
    assert attributes["measurements.snr"] == artifact.measurements.snr
    assert np.allclose(sfnr, artifact.images.sfnr, equal_nan=True)
    # The dotted name survives, and so does the axis the trace lies along.
    assert time.dims == ("frame",)
    assert time.attrs["units"] == "s"


def test_xarray_hands_over_the_provenance_attributes(tmp_path, artifact) -> None:
    """What a notebook gets for free: the run's record, typed, without JSON.

    A vector attribute arrives as an array and text as a `str` -- so
    `ds.attrs["provenance.voxel_mm"]` is a voxel size to compute with rather
    than something to parse, and a non-ASCII scan name written as UTF-8 NC_CHAR
    is the same string on the way back out.
    """
    prov = replace(artifact.provenance, scan="sujet_créé_Ω_頭部.nii.gz")
    saved = str(q.save_artifact(replace(artifact, provenance=prov), tmp_path / "u.nc"))
    # Imported before the filter, for the reason the test above gives.
    import xarray as xr

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with xr.open_dataset(saved) as dataset:
            attributes = dict(dataset.attrs)

    assert isinstance(attributes["provenance.tr"], float)
    assert attributes["provenance.tr"] == prov.tr
    voxel = np.asarray(attributes["provenance.voxel_mm"])
    assert voxel.shape == (3,)
    assert np.array_equal(voxel, prov.voxel_mm)
    assert attributes["provenance.scan"] == "sujet_créé_Ω_頭部.nii.gz"


def test_xarray_resolves_every_axis_as_a_coordinate(tmp_path, artifact) -> None:
    """What the coordinate variables buy a notebook, in the library that uses them.

    Without them `xr.open_dataset` reports "dimensions without coordinates" and
    a plot runs against 0..n-1. With them every axis is an index xarray can
    select and align on, `curves.time` rides along as a second label on the
    per-frame traces, and `ds["curves.roi_signal"].plot()` draws against
    seconds without the caller supplying anything.
    """
    saved = str(q.save_artifact(artifact, tmp_path / "scan.qa.nc"))
    # Imported before the filter, for the reason the test above gives.
    import xarray as xr

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with xr.open_dataset(saved) as dataset:
            coordinates = set(dataset.coords)
            indexes = set(dataset.indexes)
            frame = dataset["frame"].to_numpy()
            trace = dataset["curves.roi_signal"]
            seconds = trace.coords["curves.time"].to_numpy()
            labelled = dataset["image_axis"].attrs["flag_meanings"]

    assert coordinates > _DIMENSIONS  # every axis, and `curves.time` besides
    assert "curves.time" in coordinates
    assert indexes == _DIMENSIONS  # each one selectable and alignable
    assert np.array_equal(frame, np.arange(artifact.provenance.n_frames))
    assert trace.dims == ("frame",)
    assert np.array_equal(seconds, artifact.curves.time)
    assert labelled == "row col"


def test_the_unidata_library_opens_the_artifact_without_a_warning(
    tmp_path, artifact
) -> None:
    """The C library itself: what `ncdump`, MATLAB and R read through.

    The headline claim of this container is that a reader which has never heard
    of fmriqc opens the file, finds the axes named, and can turn the flagged
    bytes back into a mask on its own.
    """
    saved = str(q.save_artifact(artifact, tmp_path / "scan.qa.nc"))

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with netCDF4.Dataset(saved) as dataset:
            assert dataset.data_model == "NETCDF4"
            assert set(dataset.dimensions) == _DIMENSIONS
            mask = dataset["images.phantom_mask"]
            document = dataset.getncattr("document")
            snr = dataset.getncattr("measurements.snr")
            flags = np.asarray(mask.flag_values)
            stored = np.asarray(mask[:])

    assert '"schema_version"' in document
    assert snr == artifact.measurements.snr
    assert np.array_equal(flags, [0, 1])
    assert np.array_equal(stored != 0, artifact.images.phantom_mask)


# --------------------------------------------------------------------------
# the layout, before a file exists
# --------------------------------------------------------------------------


def test_the_layout_declares_every_array_the_artifact_publishes(artifact) -> None:
    """`decompose` and the netCDF layout are one contract in two files.

    A field added to one and not the other would be an array with no declared
    axes; `encode` refuses it, and this says so before a save has to.
    """
    document, arrays = decompose(artifact)
    content = netcdf.encode(document, arrays)
    assert set(content.variables) == set(arrays)


def test_encode_refuses_an_array_the_layout_does_not_declare(artifact) -> None:
    document, arrays = decompose(artifact)
    with pytest.raises(ValueError, match="not an array this artifact layout"):
        netcdf.encode(document, arrays | {"curves.invented": np.zeros(3)})


def test_encode_refuses_an_array_of_the_wrong_rank(artifact) -> None:
    document, arrays = decompose(artifact)
    with pytest.raises(ValueError, match="rank 2"):
        netcdf.encode(document, arrays | {"curves.time": np.zeros((3, 3))})


def test_encode_refuses_two_arrays_that_disagree_about_one_axis(artifact) -> None:
    """A shared dimension is a claim, and a file cannot make it two ways."""
    document, arrays = decompose(artifact)
    with pytest.raises(ValueError, match="already fixed it at"):
        netcdf.encode(document, arrays | {"curves.roi_signal": np.zeros(3)})


def test_encode_refuses_a_dtype_the_container_would_narrow(artifact) -> None:
    """A QA number quietly stored at half its precision is a silent loss."""
    document, arrays = decompose(artifact)
    narrowed = arrays["curves.time"].astype(np.float32)
    with pytest.raises(ValueError, match="dtype float32"):
        netcdf.encode(document, arrays | {"curves.time": narrowed})


# --------------------------------------------------------------------------
# the retired `.npz` container
# --------------------------------------------------------------------------
#
# Nothing writes one any more, and every artifact written before this one does
# -- so the reader stays, and these build the two forms by hand rather than
# through a writer that no longer exists. The committed fixtures in
# `test_artifact_fixtures.py` cover real historical bytes; these isolate the
# stored form from the schema history the fixtures also exercise.


def _as_npz(path, document: str, arrays, document_member) -> None:
    """An `.npz` artifact in the layout the retired writer used."""
    np.savez_compressed(path, __document__=document_member(document), **arrays)


def _as_utf8_bytes(text: str) -> np.ndarray:
    """The document member as the last `.npz` builds wrote it."""
    return np.frombuffer(text.encode("utf-8"), dtype=np.uint8)


def test_load_rejects_a_damaged_npz(tmp_path, artifact) -> None:
    """A zip that starts right and stops early is refused, not half-read.

    NumPy's loader answers a damaged archive with whichever of four libraries'
    exceptions it reached -- `BadZipFile`, an inflate error, a truncated member
    -- and the reader turns all of them into the one thing a caller can act on.
    """
    saved = q.save_artifact(artifact, tmp_path / "new.qa.nc")
    document, arrays = _read_netcdf(saved)
    old = tmp_path / "old.qa.npz"
    _as_npz(old, json.dumps(document), arrays, _as_utf8_bytes)

    whole = old.read_bytes()
    old.write_bytes(whole[: len(whole) // 2])
    assert old.read_bytes()[:4] == b"PK\x03\x04"  # still claims to be the container
    with pytest.raises(q.InvalidArtifactError):
        q.load_artifact(old)


@pytest.mark.parametrize(
    "document_member", [_as_utf8_bytes, np.array], ids=["uint8", "unicode"]
)
def test_an_npz_artifact_still_loads(tmp_path, artifact, document_member) -> None:
    """Both stored forms of the old document member, opened by the same call.

    `uint8` is what the last `.npz` builds wrote; a NumPy `<U` string is what
    everything before them wrote. Neither is written now, and both must read.

    Compared as documents, not as artifacts: the fixture's motion metrics are
    NaN, and NaN != NaN would fail a dataclass comparison for reasons that have
    nothing to do with the stored form.
    """
    saved = q.save_artifact(artifact, tmp_path / "new.qa.nc")
    document, arrays = _read_netcdf(saved)
    old = tmp_path / "old.qa.npz"
    _as_npz(old, json.dumps(document), arrays, document_member)

    assert old.read_bytes()[:4] == b"PK\x03\x04"  # the other container, by its magic
    loaded = q.load_artifact(old)
    assert asdict(loaded.provenance) == asdict(artifact.provenance)
    assert asdict(loaded.settings) == asdict(artifact.settings)
    assert loaded.schema_version == artifact.schema_version
    assert loaded.measurements.snr == artifact.measurements.snr
    assert loaded.images.phantom_mask.dtype == np.bool_
