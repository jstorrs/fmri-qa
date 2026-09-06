"""End-to-end pipeline through the public `fmriqc` import surface.

Exercises `run_qa` as a caller sees it, on the synthetic phantom the `make_scan`
fixture builds (no file I/O), so the whole functional core runs deterministically.
"""

import numpy as np
import pytest

import fmriqc as q

from .conftest import MakeScan


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
    m = q.run_qa(make_scan(), roi_size=9).metrics
    assert np.isfinite(m.ghost_pct)
    assert np.isfinite(m.ghost_top_pct)
    # the localized top-10% ghost shares ghost%'s scale and can only exceed it
    assert m.ghost_top_pct >= m.ghost_pct


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


def test_unknown_centering_mode_is_rejected(make_scan: MakeScan) -> None:
    with pytest.raises(q.InvalidChoiceError):
        q.run_qa(make_scan(), center="middle")  # type: ignore[arg-type]
