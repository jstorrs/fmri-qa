"""The analysis artifact: what `analyze` puts in it, and the `.npz` round trip.

The artifact is the contract between the calculation half and every consumer, so
these tests pin both halves of it — that everything a report needs is resolved
at build time (no metric object left to walk), and that a saved artifact reads
back equal to the one that was written.
"""

import json
from dataclasses import asdict
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


def test_analyze_records_provenance_from_the_sidecar(artifact) -> None:
    prov = artifact.provenance
    assert prov.scan == "scan.nii.gz"
    assert prov.tr == pytest.approx(2.0)
    assert prov.n_frames == 38  # 40 volumes, 5 s of warm-up dropped at TR 2 s
    assert prov.voxel_mm == (3.0, 3.0, 3.0)
    assert prov.matrix == (32, 32)
    assert prov.flip_angle == 77
    assert prov.created and prov.core_version


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
    assert loaded.provenance == artifact.provenance
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


# Fields each schema version introduced, so a current document can be rewritten
# as the older one it grew out of (the reverse of `serialize._MIGRATIONS`).
_ADDED_IN = {2: ("phantom_fraction", "roi_inside_phantom"), 3: ("phantom_mask_ok",)}


def _as_schema(version: int):
    """An edit turning a current document into one at `version`."""

    def edit(document):
        measurements = dict(document["measurements"])
        for added, names in _ADDED_IN.items():
            if added > version:
                for name in names:
                    del measurements[name]
        return {**document, "schema_version": version, "measurements": measurements}

    return edit


def test_load_rejects_a_document_missing_a_section(tmp_path, artifact) -> None:
    path = q.save_artifact(artifact, tmp_path / "qa.npz")
    _rewrite_document(path, lambda doc: {**doc, "images": {}})
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
