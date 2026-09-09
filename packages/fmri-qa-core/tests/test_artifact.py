"""What `analyze` puts in an artifact: every value a consumer needs, resolved.

The artifact is the contract between the calculation half and every consumer,
so these pin that everything a report needs is settled at build time — derived
properties into plain fields, curves extracted, masks and outlines materialized
— with no metric object left for a reader to walk. The `.npz` round trip that
carries it to disk is `test_artifact_archive.py`.
"""

import warnings
from dataclasses import asdict, replace

import numpy as np
import pytest

import fmriqc as q
from fmriqc.analysis.build import _convex_hull


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
    assert m.displacement_unit == "mm"  # the voxel size is known
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


def test_displacement_reports_mm_with_a_known_voxel_size_else_voxels(
    artifact, make_scan
) -> None:
    """Motion/COM peak displacement follows the header's voxel size, like FWHM.

    `artifact` is built from a NIfTI with a 3 mm header, so both peaks -- and
    the combined FWHM -- report in mm. `make_scan` builds a scan with no header
    metadata at all, so the same numbers fall back to voxels; `displacement_unit`
    says which happened rather than leaving a reader to guess from the value
    alone.
    """
    known = artifact.measurements
    assert known.displacement_unit == "mm"
    assert known.fwhm_unit == "mm"

    unmetered = q.build_artifact(q.run_qa(make_scan(), roi_size=9)).measurements
    assert unmetered.displacement_unit == "vox"
    assert unmetered.fwhm_unit == "vox"


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


def test_the_direction_and_the_label_are_the_same_axis(tmp_path, write_scan) -> None:
    """`provenance.pe_dir` and `measurements.pe_label` cannot name two axes.

    They answer different questions -- what the metadata resolved, and what the
    run measured on -- so an override may legitimately separate them, and that
    is the *only* thing that may. Both are now derived from an axis rather than
    one of them from a sidecar word, so a reader comparing the acquisition block
    against the measurements block sees one story.
    """
    scan = q.QAScan.from_nifti(write_scan(tmp_path))

    agreed = q.analyze(scan, q.AnalysisSettings(roi_size=9))
    assert agreed.provenance.pe_dir == agreed.measurements.pe_label == "col"

    overridden = q.analyze(scan, q.AnalysisSettings(roi_size=9, pe_axis_override=0))
    assert overridden.provenance.pe_dir == "col"  # what the sidecar resolved
    assert overridden.measurements.pe_label == "row"  # what the run measured


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


def test_the_default_roi_size_is_the_shared_fbirn_constant() -> None:
    """The ROI side has one definition, spoken by prep and by the artifact."""
    assert q.AnalysisSettings().roi_size == q.FBIRN_ROI_SIZE


def test_undeterminable_clipping_survives_the_archive(tmp_path, make_scan) -> None:
    """ "Not determinable" is a third answer, and it round-trips as one.

    A scan whose storage cannot support the rail test publishes the whole
    clipping block as None -- not as zero counts and a False verdict, which
    would report a scanner verified against a check that never ran. The
    distinction is only worth having if it survives to the reader, so it is
    pinned through `save_artifact`/`load_artifact` rather than in memory alone.
    """
    scan = replace(make_scan(), stored_integer=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        artifact = q.analyze(scan, q.AnalysisSettings(roi_size=9))

    for name in ("clipped_any", "clipped_kept", "n_clipped_kept", "n_clipped_pre"):
        assert getattr(artifact.measurements, name) is None, name
    assert artifact.measurements.clip_ceiling is None

    loaded = q.load_artifact(q.save_artifact(artifact, tmp_path / "undet.qa.npz"))
    assert loaded.measurements.clipped_any is None
    assert loaded.measurements.n_clipped_kept is None


def test_integer_storage_still_answers_the_clipping_question(make_scan) -> None:
    """The same phantom, stored as integers, gets a real verdict."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        artifact = q.analyze(make_scan(), q.AnalysisSettings(roi_size=9))

    m = artifact.measurements
    assert m.clipped_any is False  # answered, and the answer is "no rail found"
    assert m.n_clipped_kept == 0 and m.n_clipped_pre == 0
