"""Nyquist-ghost ratios against a synthetically injected N/2 ghost.

A ghost is placed by hand at the phantom's N/2-shifted location on a known
axis, so the ratios, estimated PE axis and top-fraction/ACR variants have
closed-form values. `radius=0` and an all-valid mask keep the region-matched
masks equal to the injected blocks.
"""

import warnings

import numpy as np
import pytest

from fmriqc.metrics.ghost import (
    GhostResult,
    estimate_ghost,
    estimate_pe_axis,
    ghost_ratios,
)
from fmriqc.types import PeAxis, readout_axis

ALL_VALID = np.ones((8, 8), dtype=bool)


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


def _ghost_on_axis0(ghost: np.ndarray) -> GhostResult:
    """`estimate_ghost` over the injected phantom, with axis 0 as the PE axis."""
    img, mask = _phantom_with_axis0_ghost(ghost)
    return estimate_ghost(img, mask, 0, valid_mask=ALL_VALID, radius=0)


def test_ghost_ratio_recovers_the_injected_ratio() -> None:
    # mean ghost 5 / mean signal 100 = 0.05 (the FBIRN 5% ghost).
    result = _ghost_on_axis0(np.full((2, 2), 5.0))
    assert np.isclose(result.pe_ratio, 0.05)
    assert np.isclose(result.ghost_pct, 5.0)


def test_readout_ratio_is_near_zero_on_the_axis_the_ghost_missed() -> None:
    # Along axis 1 the ghost region lands on background, so the ratio collapses.
    # That is what makes the readout ratio a background-relative baseline.
    result = _ghost_on_axis0(np.full((2, 2), 5.0))
    assert np.isclose(result.ro_ratio, 0.0)


@pytest.mark.parametrize("expected_axis", [0, 1])
def test_estimate_pe_axis_picks_the_axis_the_ghost_lands_on(
    expected_axis: PeAxis,
) -> None:
    img, mask = _phantom_with_axis0_ghost(np.full((2, 2), 5.0))
    if expected_axis == 1:
        img, mask = img.T, mask.T
    ratios = ghost_ratios(img, mask, radius=0, valid_mask=ALL_VALID)
    axis = estimate_pe_axis(img, mask, radius=0, valid_mask=ALL_VALID)
    assert axis == expected_axis
    assert ratios[expected_axis] > ratios[readout_axis(expected_axis)]


@pytest.mark.parametrize("ghost", [0.0, 5.0])
def test_estimate_pe_axis_is_none_when_finite_ratios_are_equal(ghost: float) -> None:
    img, mask = _phantom_with_axis0_ghost(np.full((2, 2), ghost))
    img[2:4, 6:8] = ghost  # the axis-1 N/2 ghost matches axis 0 exactly

    ratios = ghost_ratios(img, mask, radius=0, valid_mask=ALL_VALID)

    assert ratios[0] == ratios[1] == ghost / 100.0
    assert estimate_pe_axis(img, mask, radius=0, valid_mask=ALL_VALID) is None


@pytest.mark.parametrize("expected_axis", [0, 1])
def test_estimate_pe_axis_resolves_a_strict_win_even_for_nearly_equal_ratios(
    expected_axis: PeAxis,
) -> None:
    img, mask = _phantom_with_axis0_ghost(np.full((2, 2), 5.0 + 1e-12))
    img[2:4, 6:8] = 5.0
    if expected_axis == 1:
        img, mask = img.T, mask.T

    ratios = ghost_ratios(img, mask, radius=0, valid_mask=ALL_VALID)

    assert ratios[expected_axis] > ratios[readout_axis(expected_axis)]
    assert np.isclose(ratios[0], ratios[1])
    assert estimate_pe_axis(img, mask, radius=0, valid_mask=ALL_VALID) == expected_axis


def test_estimate_pe_axis_is_none_when_neither_axis_is_measurable() -> None:
    """A mask filling the frame leaves no ghost region on either axis.

    Both ratios are then NaN (no measurement, not a low one). `max` used to
    answer with whichever axis it saw first, indistinguishable from a real
    result.
    """
    img = np.full((8, 8), 5.0)
    mask = np.ones((8, 8), dtype=bool)
    ratios = ghost_ratios(img, mask, radius=0, valid_mask=ALL_VALID)
    axis = estimate_pe_axis(img, mask, radius=0, valid_mask=ALL_VALID)
    assert axis is None
    assert all(np.isnan(r) for r in ratios.values())


@pytest.mark.parametrize("expected_axis", [0, 1])
@pytest.mark.parametrize("ghost", [0.0, 5.0])
def test_estimate_pe_axis_ignores_an_unmeasurable_axis(
    expected_axis: PeAxis, ghost: float
) -> None:
    """The one axis with a real ratio wins, in either order.

    A phantom spanning the FOV along axis 0 leaves that ratio NaN while axis 1's
    is real. `ratios[1] > ratios[0]` is False against a NaN, which used to hand
    the answer to axis 0.
    """
    img = np.zeros((8, 8))
    mask = np.zeros((8, 8), dtype=bool)
    mask[:, 2:4] = True  # spans axis 0, so its N/2 roll never clears the phantom
    img[:, 2:4] = 100.0
    img[:, 6:8] = ghost  # the axis-1 ghost
    if expected_axis == 0:
        img, mask = img.T, mask.T

    ratios = ghost_ratios(img, mask, radius=0, valid_mask=ALL_VALID)
    axis = estimate_pe_axis(img, mask, radius=0, valid_mask=ALL_VALID)

    assert np.isnan(ratios[readout_axis(expected_axis)])
    assert ratios[expected_axis] == ghost / 100.0
    assert axis == expected_axis


def test_top_ratio_isolates_the_brightest_ghost_voxel() -> None:
    # One ghost voxel far brighter than the rest: the region mean dilutes it, but
    # the top-fraction ratio (k=1 of 4 voxels) reports it directly.
    result = _ghost_on_axis0(np.array([[5.0, 5.0], [5.0, 20.0]]))
    assert np.isclose(result.pe_ratio, (5 + 5 + 5 + 20) / 4 / 100)  # 0.0875
    assert np.isclose(result.pe_top_ratio, 20.0 / 100.0)  # 0.20
    assert result.pe_top_ratio > result.pe_ratio


def test_acr_ratio_is_the_pe_minus_ro_difference() -> None:
    # |ghost(PE) - ghost(RO)| = |0.05 - 0.0| = 0.05.
    result = _ghost_on_axis0(np.full((2, 2), 5.0))
    assert np.isclose(result.acr_ratio, 0.05)
    assert np.isclose(result.acr_ghost_pct, abs(result.ghost_pct - result.ro_ghost_pct))


def test_the_masks_are_the_ones_the_ratios_were_measured_on() -> None:
    """The result carries its regions, so a report draws what was sampled.

    Each ghost patch is its signal patch rolled half the FOV, so they are the
    same size. The PE pair is the injected 2x2 block and its source.
    """
    result = _ghost_on_axis0(np.full((2, 2), 5.0))
    assert result.pe_axis == 0
    assert result.radius == 0
    assert result.pe_signal.sum() == result.pe_ghost.sum() == 4
    assert result.ro_signal.sum() == result.ro_ghost.sum()
    expected_ghost = np.zeros((8, 8), dtype=bool)
    expected_ghost[6:8, 2:4] = True
    assert np.array_equal(result.pe_ghost, expected_ghost)


def test_ratios_are_nan_when_the_ghost_region_is_empty() -> None:
    # A phantom filling the FOV leaves no ghost region on either axis. Every ratio
    # must be NaN via its empty-region guard, with no numpy empty-slice or
    # invalid-divide warning (an error here).
    img = np.full((8, 8), 100.0)
    mask = np.ones((8, 8), dtype=bool)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = estimate_ghost(img, mask, 0, valid_mask=ALL_VALID, radius=0)
    assert np.isnan(result.pe_ratio)
    assert np.isnan(result.ro_ratio)
    assert np.isnan(result.pe_top_ratio)
    assert np.isnan(result.acr_ratio)
