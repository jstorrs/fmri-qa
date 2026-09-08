"""The analysis artifact: what `analyze` puts in it, and the `.npz` round trip.

The artifact is the contract between the calculation half and every consumer, so
these tests pin both halves of it — that everything a report needs is resolved
at build time (no metric object left to walk), and that a saved artifact reads
back equal to the one that was written.
"""

import json
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pytest

import fmriqc as q
from fmriqc.analysis import ARTIFACT_SCHEMA_VERSION
from fmriqc.analysis.build import _convex_hull


@pytest.fixture
def artifact(tmp_path, write_scan) -> q.QAArtifact:
    """An artifact from the synthetic phantom, at a small ROI."""
    scan = q.QAScan.from_nifti(write_scan(tmp_path))
    settings = q.AnalysisSettings(roi_size=9)
    return q.analyze(scan, settings, name="scan.nii.gz", source="scan.nii.gz")


def test_analyze_records_the_requested_and_resolved_settings(artifact) -> None:
    settings = artifact.settings
    assert settings.roi_size == 9
    assert settings.detrend == "poly"
    assert settings.center == "image"
    assert settings.pe_axis_override is None
    # Resolved by the detrender from the series length, not requested.
    assert settings.detrend_order is not None


def test_build_artifact_publishes_the_settings_the_result_was_computed_with(
    make_scan,
) -> None:
    """A result built from `run_qa` carries its own request; nothing is filled in.

    `build_artifact` used to accept settings separately and default them when
    omitted, so a result computed with no trim, phantom centering, and a forced
    PE axis was published as a 5 s trim, image centering, and no override --
    while `n_trimmed` in the same file said 0.
    """
    result = q.run_qa(make_scan(), trim_sec=0, center="phantom", roi_size=9, pe_axis=0)
    artifact = q.build_artifact(result)
    s = artifact.settings
    assert (s.trim_sec, s.center, s.roi_size) == (0, "phantom", 9)
    assert s.pe_axis_override == 0
    assert s.detrend_order == result.images.detrend_order  # the resolved value
    assert artifact.provenance.n_trimmed == 0
    assert artifact.measurements.pe_label == "row"  # the override, not the sidecar


def test_settings_keep_the_requested_roi_size_and_the_images_the_resolved_one(
    make_scan,
) -> None:
    """The request and what it clamped to are two different facts."""
    with pytest.warns(UserWarning, match="not fully inside the phantom"):
        artifact = q.build_artifact(q.run_qa(make_scan(), roi_size=99))
    assert artifact.settings.roi_size == 99
    assert artifact.images.roi.size == 32  # clamped to the 32x32 image


def test_provenance_records_the_plane_analyzed(make_scan) -> None:
    """Which slice of the volume the numbers describe survives into the artifact.

    Under `center="image"` it is the middle plane, under `center="phantom"`
    the largest cross-section; the fixture's disk is the same in every slice,
    so the two modes name the same plane and the count is what tells them apart
    from a single-slice acquisition.
    """
    scan = make_scan(z=5)
    by_image = q.build_artifact(q.run_qa(scan, roi_size=9)).provenance
    by_phantom = q.build_artifact(q.run_qa(scan, roi_size=9, center="phantom"))
    assert (by_image.slice_index, by_image.n_slices) == (2, 5)
    assert by_phantom.provenance.n_slices == 5
    assert 0 <= by_phantom.provenance.slice_index < 5


def test_measurements_record_the_phantom_contrast(artifact) -> None:
    """The second half of the mask verdict is stored beside the first."""
    m = artifact.measurements
    assert m.phantom_contrast >= 4.0  # the fixture's disk stands well clear of air
    assert m.phantom_mask_ok is True


def test_analyze_records_provenance_from_the_sidecar(artifact) -> None:
    prov = artifact.provenance
    assert prov.scan == "scan.nii.gz"
    assert prov.tr == pytest.approx(2.0)
    assert prov.n_frames == 38  # 40 volumes, 5 s of warm-up dropped at TR 2 s
    assert prov.voxel_mm == (3.0, 3.0, 3.0)
    assert prov.matrix == (32, 32)
    assert prov.flip_angle == 77
    assert prov.created and prov.core_version


def test_provenance_records_the_trim_that_frame_indices_count_from(artifact) -> None:
    """`n_trimmed` + `n_frames` accounts for every acquired volume.

    Without the trim count the artifact's frame indices -- the worst outlier
    frame, the seconds in `Curves.time` -- are unmappable: they count from the
    first volume kept, and nothing else in the file says which volume that was.
    """
    prov = artifact.provenance
    assert prov.n_trimmed == 2  # 5 s of warm-up at TR 2 s
    assert prov.n_trimmed + prov.n_frames == 40  # the fixture's acquired volumes


def test_measurements_are_flat_scalars(artifact) -> None:
    """Every reported number is settled -- no metric result object survives."""
    m = artifact.measurements
    assert m.snr > 0 and m.sfnr > 0
    assert m.pe_axis == 1
    assert m.pe_label == "col"  # from the sidecar's PhaseEncodingDirection
    assert m.fwhm_unit == "mm"  # the voxel size is known
    assert isinstance(m.clipped_kept, bool)
    for value in asdict(m).values():
        assert isinstance(value, float | int | str | bool | type(None))


def test_measurements_record_the_localization_diagnostics(artifact) -> None:
    """A reader can tell a declined estimate from an analysis of background.

    Both localizations can fail quietly -- a collapsed segmentation still yields
    a mask and an off-phantom ROI still yields an average -- so the artifact
    carries whether they held. On the fixture phantom the mask covers a middling
    share of the frame and the small ROI sits inside it.
    """
    m = artifact.measurements
    assert 0.0 < m.phantom_fraction < 0.95
    assert m.phantom_mask_ok is True
    assert m.roi_inside_phantom is True


def test_a_noise_only_scan_keeps_its_failed_mask_verdict(tmp_path) -> None:
    """Analyzing background must not save a passing localization.

    Slice selection says no slice holds a phantom, but that warning is gone once
    the run ends; the artifact's verdict is what a report and a trend database
    read. The noise segments to a middling share of the frame, so the verdict
    has to fail on contrast, as the slice test did, and stay failed through the
    archive.
    """
    noise = np.abs(np.random.default_rng(0).normal(size=(32, 32, 1, 40)))
    settings = q.AnalysisSettings(trim_sec=0, center="phantom", roi_size=3)
    with pytest.warns(UserWarning, match="no slice holds a recognizable phantom"):
        artifact = q.analyze(q.QAScan(data=noise, tr=2.0), settings)
    loaded = q.load_artifact(q.save_artifact(artifact, tmp_path / "noise.qa.npz"))
    m = loaded.measurements
    assert 0.0 < m.phantom_fraction < 0.95  # the share alone would have passed
    assert m.phantom_mask_ok is False


def test_an_oversized_roi_is_recorded_as_outside_the_phantom(
    tmp_path, write_scan
) -> None:
    """The ROI-fit warning is transient; the artifact must keep the verdict.

    Analysis still completes (the metrics are simply measured over background at
    the ROI corners), so nothing else in the stored result says the numbers are
    unusable.
    """
    scan = q.QAScan.from_nifti(write_scan(tmp_path))
    with pytest.warns(UserWarning, match="not fully inside the phantom"):
        artifact = q.analyze(scan, q.AnalysisSettings(roi_size=31))
    assert artifact.measurements.roi_inside_phantom is False


def test_pe_label_follows_an_axis_override(tmp_path, write_scan) -> None:
    """An explicit axis wins over the sidecar, so the label names what was used."""
    scan = q.QAScan.from_nifti(write_scan(tmp_path))
    artifact = q.analyze(scan, q.AnalysisSettings(roi_size=9, pe_axis_override=0))
    assert artifact.measurements.pe_axis == 0
    assert artifact.measurements.pe_label == "row"


def test_curves_share_the_frame_count(artifact) -> None:
    curves = artifact.curves
    n = artifact.provenance.n_frames
    assert curves.time.shape == (n,)
    for trace in (curves.roi_signal, curves.roi_trend, curves.roi_residual):
        assert trace.shape == (n,)
    assert curves.outlier_fraction.shape == (n,)
    assert curves.translation.shape == (n, 2)
    assert curves.com_deviation.shape == (n, 2)
    assert curves.shear_pct.shape == (n,)
    # The spectrum is stored DC-dropped, so it is one bin shorter than rfft.
    assert curves.spectrum_hz.shape == (n // 2,)
    assert curves.spectrum_hz[0] > 0
    assert curves.spectrum_magnitude.shape == curves.spectrum_hz.shape


def test_weisskoff_curve_carries_its_own_ideal_line(artifact) -> None:
    """The anchored reference line is precomputed, not left to the plotter."""
    wk = artifact.curves.weisskoff
    assert wk.cv.shape == wk.roi_sizes.shape == wk.rdc.shape == wk.cv_ideal.shape
    # cv_ideal is cv1_pooled / width, so it falls monotonically with ROI width.
    assert np.all(np.diff(wk.cv_ideal) < 0)


def test_psf_curves_are_sampled_for_both_directions(artifact) -> None:
    psf = artifact.curves.psf
    assert psf.labels == ("PE", "RO")
    assert psf.unit == "mm"
    assert psf.xmax > 0 and np.isfinite(psf.xmax)
    assert psf.displacement.shape[0] == psf.empirical.shape[0] == 2
    assert psf.model_x.shape == psf.model.shape
    assert np.all(psf.model <= 1.0 + 1e-12)


def test_images_carry_the_fbirn_quartet_and_its_annotations(artifact) -> None:
    images = artifact.images
    shape = images.signal.shape
    for image in (images.sfnr, images.fluctuation_noise, images.static_noise):
        assert image.shape == shape
    assert images.phantom_mask.shape == shape and images.phantom_mask.any()
    assert images.invalid_mask.shape == shape
    # The hull is a closed polygon of (x, y) plot coordinates.
    assert images.phantom_hull.ndim == 2 and images.phantom_hull.shape[1] == 2
    assert np.array_equal(images.phantom_hull[0], images.phantom_hull[-1])
    roi = images.roi
    assert roi.size == 9 and roi.row1 - roi.row0 == roi.col1 - roi.col0


def test_a_collinear_mask_has_no_hull_rather_than_no_artifact() -> None:
    """A one-row mask has pixels but no area, and Qhull refuses to hull it.

    The outline is built after the whole analysis has run, so letting the
    geometry library's error out would throw away a completed scan over an
    annotation nothing can draw anyway. The empty polygon the docstring promises
    for a mask too small to have a hull covers this case too.
    """
    mask = np.zeros((8, 8), dtype=bool)
    mask[3, 2:7] = True
    assert _convex_hull(mask).shape == (0, 2)


def test_ghost_regions_are_region_matched(artifact) -> None:
    """Each ghost patch and its source are the same patch, rolled half the FOV.

    The synthetic disk is small enough that erosion leaves the patches empty --
    which is exactly why its ghost% is undefined -- but the pairing must hold
    either way, since the ratio compares a patch against the tissue that made it.
    """
    ghost = artifact.images.ghost
    assert ghost is not None  # the PE axis resolved, so the masks were built
    for mask in (ghost.pe_signal, ghost.pe_ghost, ghost.ro_signal, ghost.ro_ghost):
        assert mask.shape == artifact.images.signal.shape
    assert ghost.pe_signal.sum() == ghost.pe_ghost.sum()
    assert ghost.ro_signal.sum() == ghost.ro_ghost.sum()


def test_an_unresolved_pe_axis_is_published_as_unknown() -> None:
    """The artifact says "?", draws no ghost regions, and labels the raw axes.

    A run whose phase-encode axis could not be resolved (see `run_qa`) has no
    ghost regions to sample or draw, and no PE/RO direction to name. Each of
    those degradations is a branch a reader depends on, so they are walked here
    rather than left to a scan that happens to trigger them.
    """
    flat = q.QAScan(data=np.ones((16, 16, 3, 8)), tr=2.0)
    with pytest.warns(UserWarning, match="no phase-encode axis"):
        artifact = q.analyze(flat, q.AnalysisSettings(trim_sec=0.0, roi_size=5))

    assert artifact.measurements.pe_axis is None
    assert artifact.measurements.pe_label == "?"
    assert artifact.images.ghost is None  # nothing to sample, nothing to draw
    assert artifact.curves.psf.labels == ("axis0", "axis1")  # not PE / RO


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


# Fields each schema version introduced, per document section, so a current
# document can be rewritten as the older one it grew out of (the reverse of
# `serialize._MIGRATIONS`).
_ADDED_IN = {
    2: {"measurements": ("phantom_fraction", "roi_inside_phantom")},
    3: {"measurements": ("phantom_mask_ok",)},
    4: {"provenance": ("n_trimmed",)},
    5: {
        "provenance": ("slice_index", "n_slices"),
        "measurements": ("phantom_contrast",),
    },
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


def test_the_default_roi_size_is_the_shared_fbirn_constant() -> None:
    """The ROI side has one definition, spoken by prep and by the artifact."""
    assert q.AnalysisSettings().roi_size == q.FBIRN_ROI_SIZE


def test_load_rejects_a_closed_set_value_from_outside_the_set(
    tmp_path, artifact
) -> None:
    """A stored string must be held to the set its field promises.

    `fwhm_unit`, `pe_label` and the PSF unit are closed sets a reader switches
    on, and JSON carries none of that. Without the check a hand-edited or
    foreign document hands the reader a value its own type says cannot exist,
    and the mistake surfaces wherever that reader happens to branch.
    """
    for field, edit in (
        ("fwhm_unit", _with_measurement("fwhm_unit", "cm")),
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
    """Rewrite the archive's JSON member through `edit`, keeping every array."""
    with np.load(path, allow_pickle=False) as archive:
        document = json.loads(str(archive["__document__"]))
        arrays = {n: archive[n] for n in archive.files if n != "__document__"}
    payload = {"__document__": np.array(json.dumps(edit(document))), **arrays}
    with Path(path).open("wb") as fh:
        np.savez_compressed(fh, **payload)
