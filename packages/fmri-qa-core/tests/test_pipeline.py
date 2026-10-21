"""End-to-end pipeline through the public `fmriqa` import surface.

Exercises `run_qa` as a caller sees it, on the `make_scan` phantom (no file
I/O).
"""

import gc
import weakref
from dataclasses import fields, replace

import numpy as np
import pytest

import fmriqa as q
from fmriqa.prep.geometry import roi_fits

from .conftest import MakeScan, synthetic_series

# Fraction of the phantom injected at its N/2-shifted location, big enough for
# the ghost estimate to separate the two candidate axes on a noisy series.
GHOST_FRACTION = 0.08


def _scan_with_ghost_on_axis1(seed: int = 0) -> q.QAScan:
    """A synthetic phantom carrying an injected N/2 ghost along axis 1.

    No `pe_axis`: the scan the loader hands over when neither the sidecar nor
    `dim_info` names an axis, so `run_qa` has to find it.
    """
    data = synthetic_series(seed=seed)
    ghosted = data + GHOST_FRACTION * np.roll(data, data.shape[1] // 2, axis=1)
    return q.QAScan(data=ghosted, tr=2.0)


def test_run_qa_returns_finite_core_metrics(make_scan: MakeScan) -> None:
    result = q.run_qa(make_scan(), q.AnalysisSettings(roi_size=9))
    m = result.metrics
    assert isinstance(result, q.QAResult)
    assert m.snr > 0 and np.isfinite(m.snr)
    assert m.sfnr > 0 and np.isfinite(m.sfnr)
    assert np.isfinite(m.rdc)
    assert m.pe_axis == 1  # the axis we passed through, used for the ghost masks


def test_run_qa_resolves_the_ghost_on_a_separable_phantom(make_scan: MakeScan) -> None:
    """The phantom occupies part of the FOV, so the N/2 ghost region is real.

    A collapsed phantom mask (see `detect_phantom`) erodes the rolled ghost
    region to nothing and turns every ghost percentage into a silent NaN.
    Finite values mean the mask separated phantom from background.
    """
    ghost = q.run_qa(make_scan(), q.AnalysisSettings(roi_size=9)).metrics.ghost
    assert ghost is not None
    assert np.isfinite(ghost.ghost_pct)
    assert np.isfinite(ghost.ghost_top_pct)
    # the localized top-10% ghost shares ghost%'s scale and can only exceed it
    assert ghost.ghost_top_pct >= ghost.ghost_pct


def test_the_ghost_masks_are_built_once_for_both_axes(make_scan: MakeScan) -> None:
    """One `GhostResult` per run carries the regions every ghost number came from.

    The percentages and the masks a report draws are one measurement. Each ghost
    patch is its signal patch rolled half the FOV, and its axis is the one the
    run resolved.
    """
    m = q.run_qa(make_scan(), q.AnalysisSettings(roi_size=9)).metrics
    ghost = m.ghost
    assert ghost is not None
    assert ghost.pe_axis == m.pe_axis == 1
    assert ghost.radius == q.GHOST_RADIUS
    assert ghost.pe_signal.sum() == ghost.pe_ghost.sum() > 0
    assert ghost.ro_signal.sum() == ghost.ro_ghost.sum() > 0


def test_run_qa_estimates_the_pe_axis_from_the_ghost() -> None:
    """With no axis in the metadata, the pipeline reads it off the analyzed slice.

    This is the only place the estimate is made, since the loader no longer
    guesses on the full volume. The masks, percentages and PE/RO smoothness
    labels all depend on it.
    """
    m = q.run_qa(_scan_with_ghost_on_axis1(), q.AnalysisSettings(roi_size=9)).metrics
    assert m.pe_axis == 1
    assert m.ghost is not None
    assert m.ghost.pe_axis == 1


def test_run_qa_is_deterministic(make_scan: MakeScan) -> None:
    a = q.run_qa(make_scan(seed=1), q.AnalysisSettings(roi_size=9)).metrics
    b = q.run_qa(make_scan(seed=1), q.AnalysisSettings(roi_size=9)).metrics
    assert a.snr == b.snr
    assert a.sfnr == b.sfnr
    assert a.rdc == b.rdc


def test_preprocess_discards_the_full_volume(make_scan: MakeScan) -> None:
    scan = make_scan()
    data_ref = weakref.ref(scan.data)
    images = q.preprocess(scan, q.AnalysisSettings(trim_sec=4.0))
    assert not np.shares_memory(images.center_slice, scan.data)
    del scan
    gc.collect()
    assert data_ref() is None
    # only the center slice survives: (X, Y, T_trimmed), not the 4-D volume
    assert images.center_slice.ndim == 3
    assert images.detrender is not None
    assert images.detrender.method == "poly"
    # ...so the trim it counts from has to be recorded here or lost with the scan
    assert images.n_trimmed == 2  # 4 s at TR 2 s
    assert images.n_trimmed + images.center_slice.shape[-1] == 40


def test_run_qa_records_the_request_it_answered(make_scan: MakeScan) -> None:
    """The result carries its own settings, so a later projection cannot guess.

    `pe_axis_override` is the argument as given, not the resolved axis. They
    differ when the override was left to the metadata.
    """
    result = q.run_qa(
        make_scan(), q.AnalysisSettings(trim_sec=0, center="phantom", roi_size=9)
    )
    s = result.settings
    assert (s.trim_sec, s.center, s.roi_size) == (0, "phantom", 9)
    assert s.pe_axis_override is None and result.metrics.pe_axis == 1
    assert result.images.detrender is not None
    assert s.detrend_order == result.images.detrender.order


def test_a_request_carrying_a_stale_detrend_order_is_re_resolved(
    make_scan: MakeScan,
) -> None:
    """A record fed back reproduces the run, which rewrites `detrend_order` itself."""
    first = q.run_qa(make_scan(), q.AnalysisSettings(roi_size=9)).settings
    again = q.run_qa(make_scan(), replace(first, detrend_order=99)).settings
    assert again == first


def test_an_explicit_pe_axis_overrides_the_header(make_scan: MakeScan) -> None:
    """An explicit override wins over a header axis that names a different one.

    `make_scan` sets the header's axis to 1 (see `conftest.make_scan`), so the
    override only shows if the resolved axis is 0.
    """
    result = q.run_qa(make_scan(), q.AnalysisSettings(roi_size=9, pe_axis_override=0))
    assert result.settings.pe_axis_override == 0
    assert result.metrics.pe_axis == 0


def test_preprocess_records_which_plane_it_cut(make_scan: MakeScan) -> None:
    images = q.preprocess(make_scan(z=5))
    assert (images.slice_index, images.n_slices) == (2, 5)  # the middle of five


def test_the_images_do_not_carry_a_phase_encode_axis() -> None:
    """The axis lives in `QAMetrics`, not in the preprocessed images.

    A run resolves it and publishes it from the ghost it measured
    (`QAMetrics.pe_axis`). A copy here could only agree or be a bug.
    """
    assert "pe_axis" not in {f.name for f in fields(q.QAImages)}


def test_weisskoff_rdc_matches_the_metric(make_scan: MakeScan) -> None:
    result = q.run_qa(make_scan(), q.AnalysisSettings(roi_size=9))
    assert result.metrics.rdc == result.metrics.weisskoff.rdc


def test_phantom_centering_localizes_slice_and_roi(make_scan: MakeScan) -> None:
    """`center="phantom"` runs end to end and lands the ROI inside the phantom.

    This documented CLI option picks the largest phantom cross-section instead of
    the middle slice, and centers the ROI on the detected phantom center.
    """
    result = q.run_qa(make_scan(), q.AnalysisSettings(roi_size=9, center="phantom"))
    assert result.roi.size == 9
    assert roi_fits(result.geom.phantom_mask, result.roi)
    assert np.isfinite(result.metrics.snr) and result.metrics.snr > 0


def test_both_centering_modes_agree_on_a_centered_phantom(make_scan: MakeScan) -> None:
    """The fixture's disk is image-centered, so the two modes must coincide.

    An off-by-one in the detected-center or largest-slice selection would move
    the ROI and show up as a mismatch.
    """
    scan = make_scan()
    by_image = q.run_qa(scan, q.AnalysisSettings(roi_size=9, center="image")).roi
    by_phantom = q.run_qa(scan, q.AnalysisSettings(roi_size=9, center="phantom")).roi
    assert np.array_equal(by_image.center, by_phantom.center)
    assert by_image.size == by_phantom.size


def test_the_roi_warning_suggests_the_other_centering_mode(make_scan: MakeScan) -> None:
    """Advice never recommends the setting that just failed.

    An ROI that will not fit leaves two ways out, and which one is worth trying
    depends on the mode in use. Recommending `center='image'` to a run that is already
    image-centered wastes the operator's next attempt.
    """
    scan = make_scan()
    for center, suggested in (("image", "phantom"), ("phantom", "image")):
        with pytest.warns(UserWarning, match=f"center='{suggested}'"):
            q.run_qa(scan, q.AnalysisSettings(roi_size=31, center=center))


def test_unknown_centering_mode_is_rejected(make_scan: MakeScan) -> None:
    settings = q.AnalysisSettings(center="middle")  # type: ignore[arg-type]
    with pytest.raises(q.InvalidChoiceError):
        q.run_qa(make_scan(), settings)


def test_an_unresolvable_pe_axis_leaves_the_ghost_metrics_undefined() -> None:
    """With no PE axis there is no ghost result.

    A constant volume has no ghost on either axis, so the estimate declines. The
    run continues, since the ROI metrics need no PE axis, but must not name an
    axis nothing measured or publish four numbers sampled from it.
    """
    flat = q.QAScan(data=np.ones((16, 16, 3, 8)), tr=2.0)

    with pytest.warns(UserWarning, match="no phase-encode axis"):
        m = q.run_qa(flat, q.AnalysisSettings(trim_sec=0.0, roi_size=5)).metrics

    assert m.pe_axis is None
    assert m.ghost is None


def test_metrics_pe_axis_is_read_off_the_ghost_it_was_measured_with(
    make_scan: MakeScan,
) -> None:
    """The axis and the ghost family cannot disagree.

    `QAMetrics.pe_axis` is a property over `ghost`, not a field beside it. A
    stored copy could only agree or be a bug, and would allow "resolved an axis
    but measured no ghost". Re-adding the field would pass every other test in
    this module, so this one catches it.
    """
    assert "pe_axis" not in {f.name for f in fields(q.QAMetrics)}

    m = q.run_qa(make_scan(), q.AnalysisSettings(roi_size=9)).metrics
    assert m.ghost is not None
    assert m.pe_axis == m.ghost.pe_axis
