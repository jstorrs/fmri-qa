"""End-to-end pipeline through the public `fmriqc` import surface.

Exercises `run_qa` as a caller sees it, on the synthetic phantom the `make_scan`
fixture builds (no file I/O), so the whole functional core runs deterministically.
"""

import numpy as np
import pytest

import fmriqc as q

from .conftest import MakeScan, synthetic_series

# Fraction of the phantom injected at its N/2-shifted location, big enough for
# the ghost estimate to separate the two candidate axes on a noisy series.
GHOST_FRACTION = 0.08


def _scan_with_ghost_on_axis1(seed: int = 0) -> q.QAScan:
    """A synthetic phantom carrying an injected N/2 ghost along axis 1.

    No `pe_axis`: this is the scan the loader hands over when neither the sidecar
    nor `dim_info` names an axis, so `run_qa` has to find it.
    """
    data = synthetic_series(seed=seed)
    ghosted = data + GHOST_FRACTION * np.roll(data, data.shape[1] // 2, axis=1)
    return q.QAScan(data=ghosted, tr=2.0)


def test_run_qa_returns_finite_core_metrics(make_scan: MakeScan) -> None:
    result = q.run_qa(make_scan(), roi_size=9)
    m = result.metrics
    assert isinstance(result, q.QAResult)
    assert m.snr > 0 and np.isfinite(m.snr)
    assert m.sfnr > 0 and np.isfinite(m.sfnr)
    assert np.isfinite(m.rdc)
    assert m.pe_axis == 1  # the axis we passed through, used for the ghost masks


def test_run_qa_resolves_the_ghost_on_a_separable_phantom(make_scan: MakeScan) -> None:
    """The phantom occupies part of the FOV, so the N/2 ghost region is real.

    A guard on the segmentation as much as on the ghost: a collapsed phantom mask
    (see `detect_phantom`) erodes the rolled ghost region to nothing and turns
    every ghost percentage into a silent NaN, so finite values here say the mask
    separated phantom from background.
    """
    ghost = q.run_qa(make_scan(), roi_size=9).metrics.ghost
    assert ghost is not None
    assert np.isfinite(ghost.ghost_pct)
    assert np.isfinite(ghost.ghost_top_pct)
    # the localized top-10% ghost shares ghost%'s scale and can only exceed it
    assert ghost.ghost_top_pct >= ghost.ghost_pct


def test_the_ghost_masks_are_built_once_for_both_axes(make_scan: MakeScan) -> None:
    """One `GhostResult` per run carries the regions every ghost number came from.

    The percentages and the masks a report draws are the same measurement, so
    they cannot drift apart: each ghost patch is its signal patch rolled half the
    FOV, and the axis it names is the axis the run resolved.
    """
    m = q.run_qa(make_scan(), roi_size=9).metrics
    ghost = m.ghost
    assert ghost is not None
    assert ghost.pe_axis == m.pe_axis == 1
    assert ghost.radius == q.GHOST_RADIUS
    assert ghost.pe_signal.sum() == ghost.pe_ghost.sum() > 0
    assert ghost.ro_signal.sum() == ghost.ro_ghost.sum() > 0


def test_run_qa_estimates_the_pe_axis_from_the_ghost() -> None:
    """With no axis in the metadata, the pipeline reads it off the analyzed slice.

    This is the only place the estimate is made -- the loader no longer guesses
    on the full volume -- so an injected axis-1 ghost has to resolve here or
    nowhere. Everything downstream (the masks, the four percentages, the PE/RO
    smoothness labels) hangs off the answer.
    """
    m = q.run_qa(_scan_with_ghost_on_axis1(), roi_size=9).metrics
    assert m.pe_axis == 1
    assert m.ghost is not None
    assert m.ghost.pe_axis == 1


def test_run_qa_is_deterministic(make_scan: MakeScan) -> None:
    a = q.run_qa(make_scan(seed=1), roi_size=9).metrics
    b = q.run_qa(make_scan(seed=1), roi_size=9).metrics
    assert a.snr == b.snr
    assert a.sfnr == b.sfnr
    assert a.rdc == b.rdc


def test_preprocess_discards_the_full_volume(make_scan: MakeScan) -> None:
    images = q.preprocess(make_scan(), trim_sec=4.0)
    # only the center slice survives: (X, Y, T_trimmed), not the 4-D volume
    assert images.center_slice.ndim == 3
    assert images.detrend_method == "poly"
    # ...so the trim it counts from has to be recorded here or lost with the scan
    assert images.n_trimmed == 2  # 4 s at TR 2 s
    assert images.n_trimmed + images.center_slice.shape[-1] == 40


def test_weisskoff_rdc_matches_the_metric(make_scan: MakeScan) -> None:
    result = q.run_qa(make_scan(), roi_size=9)
    assert result.metrics.rdc == result.metrics.weisskoff.rdc


def test_phantom_centering_localizes_slice_and_roi(make_scan: MakeScan) -> None:
    """`center="phantom"` runs end to end and lands the ROI inside the phantom.

    The alternative localization mode is a documented CLI option, so it is walked
    here: it selects the largest phantom cross-section rather than the middle
    slice, and centers the ROI on the detected phantom center rather than the
    image center.
    """
    result = q.run_qa(make_scan(), roi_size=9, center="phantom")
    assert result.roi.size == 9
    assert q.roi_fits(result.geom.phantom_mask, result.roi.index)
    assert np.isfinite(result.metrics.snr) and result.metrics.snr > 0


def test_both_centering_modes_agree_on_a_centered_phantom(make_scan: MakeScan) -> None:
    """The fixture's disk is image-centered, so the two modes must coincide.

    That makes this a real check on the "phantom" path rather than a tautology:
    an off-by-one in the detected-center or largest-slice selection would move
    the ROI and show up as a mismatch.
    """
    scan = make_scan()
    by_image = q.run_qa(scan, roi_size=9, center="image").roi
    by_phantom = q.run_qa(scan, roi_size=9, center="phantom").roi
    assert np.array_equal(by_image.center, by_phantom.center)
    assert by_image.size == by_phantom.size


def test_the_roi_warning_suggests_the_other_centering_mode(make_scan: MakeScan) -> None:
    """Advice the run has already taken is no advice at all.

    An ROI that will not fit leaves two ways out, and which of them is worth
    trying depends on the mode in use: recommending `center='image'` to a run
    that is already image-centered spends the operator's next attempt on the
    setting that just failed.
    """
    scan = make_scan()
    for center, suggested in (("image", "phantom"), ("phantom", "image")):
        with pytest.warns(UserWarning, match=f"center='{suggested}'"):
            q.run_qa(scan, roi_size=31, center=center)


def test_unknown_centering_mode_is_rejected(make_scan: MakeScan) -> None:
    with pytest.raises(q.InvalidChoiceError):
        q.run_qa(make_scan(), center="middle")  # type: ignore[arg-type]


def test_an_unresolvable_pe_axis_leaves_the_ghost_metrics_undefined() -> None:
    """Every ghost statistic is defined relative to an axis; with none, none.

    A constant volume has no ghost to locate on either axis, so the estimate
    declines. The run continues -- the ROI stability metrics do not need a PE
    axis -- but there is no ghost result at all, rather than the run naming an
    axis nothing measured and publishing four numbers sampled from wherever it
    pointed.
    """
    flat = q.QAScan(data=np.ones((16, 16, 3, 8)), tr=2.0)

    with pytest.warns(UserWarning, match="no phase-encode axis"):
        m = q.run_qa(flat, trim_sec=0.0, roi_size=5).metrics

    assert m.pe_axis is None
    assert m.ghost is None
