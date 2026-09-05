"""Nyquist-ghost ratios against a synthetically injected N/2 ghost.

A ghost is placed by hand at the phantom's N/2-shifted location on a known axis,
so the recovered ratio, the estimated PE axis, and the top-fraction/ACR variants
have closed-form expected values. `radius=0` and an explicit all-valid mask keep
the region-matched masks exactly the injected blocks (no erosion/edge trimming).
"""

import warnings

import numpy as np

from fmriqc.metrics.ghost import (
    acr_ghosting_ratio,
    estimate_pe_axis,
    ghost_ratio,
    ghost_top_ratio,
)


def _phantom_with_axis0_ghost(ghost: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """8x8 mean image + phantom mask: a 2x2 phantom and its axis-0 N/2 ghost.

    The phantom block sits at rows 2-3, cols 2-3 (signal 100); its N/2 ghost along
    axis 0 (shift 4) lands at rows 6-7, cols 2-3, filled with `ghost` (2x2).
    """
    img = np.zeros((8, 8))
    mask = np.zeros((8, 8), dtype=bool)
    mask[2:4, 2:4] = True
    img[2:4, 2:4] = 100.0
    img[6:8, 2:4] = ghost
    return img, mask


def test_ghost_ratio_recovers_the_injected_ratio() -> None:
    img, mask = _phantom_with_axis0_ghost(np.full((2, 2), 5.0))
    valid = np.ones((8, 8), dtype=bool)
    # mean ghost 5 / mean signal 100 = 0.05 (the fBIRN 5% ghost).
    ratio = ghost_ratio(img, mask, pe_axis=0, radius=0, valid_mask=valid)
    assert np.isclose(ratio, 0.05)


def test_ghost_ratio_is_near_zero_on_the_wrong_axis() -> None:
    img, mask = _phantom_with_axis0_ghost(np.full((2, 2), 5.0))
    valid = np.ones((8, 8), dtype=bool)
    # Along axis 1 the ghost region lands on background, so the ratio collapses.
    ratio = ghost_ratio(img, mask, pe_axis=1, radius=0, valid_mask=valid)
    assert np.isclose(ratio, 0.0)


def test_estimate_pe_axis_picks_the_axis_the_ghost_lands_on() -> None:
    img, mask = _phantom_with_axis0_ghost(np.full((2, 2), 5.0))
    valid = np.ones((8, 8), dtype=bool)
    axis, ratios = estimate_pe_axis(
        img, mask, radius=0, return_ratios=True, valid_mask=valid
    )
    assert axis == 0
    assert ratios[0] > ratios[1]


def test_ghost_top_ratio_isolates_the_brightest_ghost_voxel() -> None:
    # One ghost voxel far brighter than the rest: the region mean dilutes it, but
    # the top-fraction ratio (k=1 of 4 voxels) reports it directly.
    img, mask = _phantom_with_axis0_ghost(np.array([[5.0, 5.0], [5.0, 20.0]]))
    valid = np.ones((8, 8), dtype=bool)
    mean_ratio = ghost_ratio(img, mask, pe_axis=0, radius=0, valid_mask=valid)
    top_ratio = ghost_top_ratio(img, mask, pe_axis=0, radius=0, valid_mask=valid)
    assert np.isclose(mean_ratio, (5 + 5 + 5 + 20) / 4 / 100)  # 0.0875
    assert np.isclose(top_ratio, 20.0 / 100.0)  # 0.20
    assert top_ratio > mean_ratio


def test_acr_ghosting_ratio_is_the_pe_minus_ro_difference() -> None:
    img, mask = _phantom_with_axis0_ghost(np.full((2, 2), 5.0))
    valid = np.ones((8, 8), dtype=bool)
    # |ghost(PE) - ghost(RO)| = |0.05 - 0.0| = 0.05.
    assert np.isclose(
        acr_ghosting_ratio(img, mask, pe_axis=0, radius=0, valid_mask=valid), 0.05
    )


def test_ghost_ratio_is_nan_when_the_ghost_region_is_empty() -> None:
    # A phantom filling the FOV leaves no clear ghost region. Both ratios must
    # return NaN via their explicit empty-region guards -- and without tripping a
    # numpy empty-slice / invalid-divide warning (turned into an error here).
    img = np.full((8, 8), 100.0)
    mask = np.ones((8, 8), dtype=bool)
    valid = np.ones((8, 8), dtype=bool)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ratio = ghost_ratio(img, mask, pe_axis=0, radius=0, valid_mask=valid)
        top = ghost_top_ratio(img, mask, pe_axis=0, radius=0, valid_mask=valid)
    assert np.isnan(ratio)
    assert np.isnan(top)
