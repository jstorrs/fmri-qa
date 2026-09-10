"""The `.npz` round trip: a saved artifact reads back as the one that was written.

The other half of the artifact contract (`test_artifact.py` pins what goes into
one): that `save_artifact`/`load_artifact` preserve every section, that a
malformed or foreign archive is refused rather than half-read, and that an
archive written under an older schema is migrated forward with the fields that
schema did not carry marked unknown rather than invented.
"""

import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest

import fmriqc as q
from fmriqc.analysis import ARTIFACT_SCHEMA_VERSION


def test_save_load_round_trips_every_section(tmp_path, artifact) -> None:
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
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


def test_save_uses_the_exact_path_given(tmp_path, artifact) -> None:
    """NumPy's own savez would append `.npz`; a caller's name is honoured."""
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
        q.save_artifact(broken, tmp_path / "qa.npz")
    assert not (tmp_path / "qa.npz").exists()


def test_a_refused_save_preserves_the_archive_already_there(tmp_path, artifact) -> None:
    """A rejected write leaves the valid file it would have replaced untouched."""
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
    before = path.read_bytes()
    broken = replace(artifact, provenance=replace(artifact.provenance, n_frames=0))
    with pytest.raises(q.InvalidArtifactError, match="n_frames"):
        q.save_artifact(broken, path)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".*.tmp"))  # and no temporary beside it


def test_a_failed_save_leaves_neither_a_file_nor_a_temporary(
    tmp_path, artifact, monkeypatch
) -> None:
    """An interrupted write must not leave debris in a QA archive.

    The archive a trend database reads is a directory of these files, and a
    truncated one is indistinguishable from a whole one until it is opened. The
    bytes go to a temporary beside the destination and are moved in only once
    they are complete, so a failure leaves the directory exactly as it was.
    """

    def fails(*args, **kwargs):
        raise OSError("no space left on device")

    monkeypatch.setattr(np, "savez_compressed", fails)
    archive_dir = tmp_path / "archive"
    with pytest.raises(OSError, match="no space left on device"):
        q.save_artifact(artifact, archive_dir / "qa.npz")
    assert list(archive_dir.iterdir()) == []


def test_load_rejects_a_file_that_is_not_an_artifact(tmp_path) -> None:
    plain = tmp_path / "plain.npz"
    np.savez_compressed(plain, values=np.arange(3))
    with pytest.raises(q.InvalidArtifactError, match="not an fmriqc artifact"):
        q.load_artifact(plain)


def test_load_rejects_unreadable_bytes(tmp_path) -> None:
    junk = tmp_path / "junk.npz"
    junk.write_bytes(b"not an archive")
    with pytest.raises(q.InvalidArtifactError):
        q.load_artifact(junk)


def test_load_rejects_non_object_documents_and_plain_arrays(tmp_path) -> None:
    for document in ([], None, 4, "text"):
        path = tmp_path / "bad.npz"
        np.savez(path, __document__=np.array(json.dumps(document)))
        with pytest.raises(q.InvalidArtifactError, match="JSON object"):
            q.load_artifact(path)
    path = tmp_path / "plain.npy"
    np.save(path, np.ones(3))
    with pytest.raises(q.InvalidArtifactError):
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
    )
    for field, value in edits:
        path = q.save_artifact(artifact, tmp_path / "bad.npz")

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
        ("images.phantom_mask", np.full((32, 32), 2)),
        ("images.signal", np.full((32, 32), "1")),
        ("images.signal", np.ones((32, 32), dtype=complex)),
        ("images.ghost.pe_signal", np.ones((1, 1), dtype=bool)),
        ("images.phantom_hull", np.zeros((3, 3))),
        ("images.phantom_hull", np.full((3, 2), np.nan)),
    )
    for field, value in edits:
        path = q.save_artifact(artifact, tmp_path / "bad.npz")
        with np.load(path, allow_pickle=False) as archive:
            payload = {key: archive[key] for key in archive.files}
        payload[field] = value
        np.savez(path, **payload)
        with pytest.raises(q.InvalidArtifactError):
            q.load_artifact(path)


def test_artifact_arrays_own_readonly_copies(tmp_path, artifact) -> None:
    signal = artifact.images.signal.copy()
    images = replace(artifact.images, signal=signal)
    signal[:] = 0
    assert images.signal.any()
    loaded = q.load_artifact(q.save_artifact(artifact, tmp_path / "qa.npz"))
    for obj in (artifact, loaded):
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
    loaded = q.load_artifact(q.save_artifact(broken, tmp_path / "failed-motion.npz"))
    assert np.isnan(loaded.curves.translation).all()
    assert np.isnan(loaded.measurements.max_translation)


def test_load_rejects_an_artifact_from_a_newer_build(tmp_path, artifact) -> None:
    """A future layout is refused by name, not misread field by field.

    The one direction that cannot be migrated: this build does not know what a
    later schema put in the file, so guessing would be worse than refusing.
    """
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
    _rewrite_document(path, lambda doc: doc | {"schema_version": 99})
    with pytest.raises(q.InvalidArtifactError, match="schema version 99, newer"):
        q.load_artifact(path)


def test_load_rejects_an_old_version_it_cannot_migrate_from(tmp_path, artifact) -> None:
    """An older version with no route forward is named, not silently mangled."""
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
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
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
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
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
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
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
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
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
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
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
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
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
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
        path = q.save_artifact(artifact, tmp_path / f"{field}.npz")
        _rewrite_document(path, edit)
        with pytest.raises(q.InvalidArtifactError, match=field):
            q.load_artifact(path)


def test_load_rejects_a_document_missing_a_section(tmp_path, artifact) -> None:
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
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
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
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


def _rewrite_document(path, edit) -> None:
    """Rewrite the archive's JSON member through `edit`, keeping every array.

    Writes the member back in the form `save_artifact` uses -- UTF-8 bytes as
    `uint8` -- so what these tests hand the loader is shaped like a real
    archive; `test_a_document_stored_the_old_way_still_reads` covers `<U`.
    """
    with np.load(path, allow_pickle=False) as archive:
        document = json.loads(bytes(archive["__document__"]).decode("utf-8"))
        arrays = {n: archive[n] for n in archive.files if n != "__document__"}
    edited = np.frombuffer(json.dumps(edit(document)).encode("utf-8"), dtype=np.uint8)
    payload = {"__document__": edited, **arrays}
    with Path(path).open("wb") as fh:
        np.savez_compressed(fh, **payload)


# --------------------------------------------------------------------------
# the __document__ member's stored form
# --------------------------------------------------------------------------


def test_the_document_is_stored_as_utf8_bytes(tmp_path, artifact) -> None:
    """`uint8`, not `<U`: the dtype the readers a site already has can take.

    npy-matlab maps `u1 u2 u4 u8 i1 i2 i4 i8 f4 f8 b1` and errors on anything
    else, and RcppCNPy is numeric only, so a `<U` document is one neither can
    open at all.
    """
    saved = q.save_artifact(artifact, tmp_path / "scan.qa.npz")
    with np.load(saved) as archive:
        member = archive["__document__"]
    assert member.dtype == np.uint8
    assert json.loads(bytes(member).decode("utf-8"))["schema_version"] == (
        artifact.schema_version
    )


def test_the_stored_document_is_ascii_even_when_the_text_is_not(
    tmp_path, artifact
) -> None:
    """Unicode rides as `\\uXXXX`, so a consumer needs no encoding to read it.

    `json.dumps` escapes by default; this pins that, because MATLAB's `char()`
    on the uint8 vector is byte-per-character and would mojibake real UTF-8.
    """
    prov = replace(artifact.provenance, scan="sujet_créé_Ω_頭部.nii.gz")
    saved = q.save_artifact(replace(artifact, provenance=prov), tmp_path / "u.qa.npz")
    with np.load(saved) as archive:
        member = archive["__document__"]
    assert bytes(member).isascii()
    assert q.load_artifact(saved).provenance.scan == "sujet_créé_Ω_頭部.nii.gz"


def test_a_name_python_holds_as_a_lone_surrogate_survives(tmp_path, artifact) -> None:
    """What a Windows file name with an undecodable byte becomes in Python.

    It reaches `json.dumps` as an unpaired surrogate, which has no UTF-8 form;
    the ASCII escaping is what keeps the write from raising on it.
    """
    name = "bad_\udcff_name.nii.gz"
    prov = replace(artifact.provenance, scan=name)
    saved = q.save_artifact(replace(artifact, provenance=prov), tmp_path / "s.qa.npz")
    assert q.load_artifact(saved).provenance.scan == name


def test_a_document_stored_the_old_way_still_reads(tmp_path, artifact) -> None:
    """Every archive written before this carries `<U`; it must still load.

    The retired-schema fixtures cover this too, but they also exercise the
    migrations; this isolates the stored form from the layout.
    """
    saved = q.save_artifact(artifact, tmp_path / "new.qa.npz")
    with np.load(saved) as archive:
        members = dict(archive)
    text = bytes(members.pop("__document__")).decode("utf-8")
    old = tmp_path / "old.qa.npz"
    np.savez_compressed(old, __document__=np.array(text), **members)

    with np.load(old) as archive:  # the form this test is about
        assert archive["__document__"].dtype.kind == "U"

    # Compared as documents, not as artifacts: the fixture's motion metrics are
    # NaN, and NaN != NaN would fail a dataclass comparison for reasons that
    # have nothing to do with the stored form.
    loaded = q.load_artifact(old)
    assert asdict(loaded.provenance) == asdict(artifact.provenance)
    assert asdict(loaded.settings) == asdict(artifact.settings)
    assert loaded.schema_version == artifact.schema_version
    assert loaded.measurements.snr == artifact.measurements.snr
