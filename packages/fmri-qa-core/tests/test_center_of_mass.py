"""Circular center-of-mass: locates the phantom and respects the periodic FOV."""

import numpy as np
import pytest

from fmriqc.metrics.center_of_mass import CenterOfMassResult, estimate_center_of_mass
from fmriqc.prep.scale import VoxelSize

ALL_VALID = np.ones((16, 16), dtype=bool)


def _block_slice(center: tuple[int, int], n: int = 16, t: int = 6) -> np.ndarray:
    """(n, n, t) slice: a bright 3x3 block at `center` (wrapping) on a flat floor."""
    cs = np.full((n, n, t), 10.0)  # uniform background pedestal
    r, c = center
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            cs[(r + dr) % n, (c + dc) % n, :] = 1000.0
    return cs


def test_com_locates_a_central_phantom() -> None:
    res = estimate_center_of_mass(_block_slice((8, 5)), valid_mask=ALL_VALID)
    assert np.allclose(res.com[:, 0], 8.0, atol=0.5)
    assert np.allclose(res.com[:, 1], 5.0, atol=0.5)


def test_com_handles_a_phantom_wrapped_across_the_edge() -> None:
    # a block centered on row 0 straddles the wrapped boundary (rows 15, 0, 1)
    res = estimate_center_of_mass(_block_slice((0, 8)), valid_mask=ALL_VALID)
    # circular COM stays near 0 (mod 16), not aliased to mid-FOV (~8)
    wrapped = (res.com[:, 0] + 8) % 16 - 8  # into (-8, 8]
    assert np.allclose(wrapped, 0.0, atol=0.5)


def test_uniform_field_has_no_defined_centroid() -> None:
    # a flat field is all pedestal: no above-floor signal -> NaN, not mid-FOV bias
    res = estimate_center_of_mass(np.full((16, 16, 4), 42.0), valid_mask=ALL_VALID)
    assert np.isnan(res.com).all()


@pytest.mark.parametrize("brightness", [1e-12, 1.0, 1e12])
def test_uniform_positive_frame_does_not_change_resolved_centroids(
    brightness: float,
) -> None:
    cs = _block_slice((8, 5)) * brightness
    baseline = estimate_center_of_mass(cs[..., :5], valid_mask=ALL_VALID)
    cs[..., 5] = 20.0 * brightness  # above the fixed pedestal, but no direction
    res = estimate_center_of_mass(cs, valid_mask=ALL_VALID)

    assert np.isnan(res.com[5]).all()
    np.testing.assert_allclose(res.com[:5], baseline.com)
    np.testing.assert_allclose(res.reference, baseline.reference, atol=1e-12)
    np.testing.assert_allclose(res.displacement[:5], baseline.displacement, atol=1e-12)
    assert np.isnan(res.displacement[5])
    assert np.isclose(res.max_displacement, baseline.max_displacement, atol=1e-12)


@pytest.mark.parametrize("unresolved_axis", [0, 1])
def test_one_axis_cancellation_preserves_the_other_coordinate(
    unresolved_axis: int,
) -> None:
    cs = _block_slice((8, 5))
    cs[..., 5] = 10.0
    cs[:, 4:7, 5] = 1000.0  # uniform along rows; column centroid remains 5
    if unresolved_axis == 1:
        cs = cs.swapaxes(0, 1)
    res = estimate_center_of_mass(cs, valid_mask=ALL_VALID)

    assert np.isnan(res.com[5, unresolved_axis])
    assert np.isclose(res.com[5, 1 - unresolved_axis], 5.0)
    np.testing.assert_allclose(res.reference, res.com[0], atol=1e-12)
    assert np.isnan(res.deviation[5, unresolved_axis])
    assert np.isclose(res.deviation[5, 1 - unresolved_axis], 0.0)
    assert np.isnan(res.displacement[5])
    assert np.isclose(res.max_displacement, 0.0)


def test_all_unresolved_frames_have_no_reference_or_displacement() -> None:
    # Later uniform frames have positive above-pedestal weight, yet no direction.
    cs = np.broadcast_to(np.array([10.0, 20.0, 30.0]), (16, 16, 3)).copy()
    res = estimate_center_of_mass(cs, valid_mask=ALL_VALID)

    assert np.isnan(res.com).all()
    assert np.isnan(res.reference).all()
    assert np.isnan(res.deviation).all()
    assert np.isnan(res.displacement).all()
    assert np.isnan(res.max_displacement)


def test_reference_ignores_missing_coordinates_independently() -> None:
    res = CenterOfMassResult(
        com=np.array([[np.nan, 3.0], [4.0, np.nan], [6.0, 5.0]]), shape=(16, 16)
    )

    np.testing.assert_allclose(res.reference, [5.0, 4.0])
    np.testing.assert_allclose(
        res.deviation, [[np.nan, -1.0], [-1.0, np.nan], [1.0, 1.0]], atol=1e-12
    )
    np.testing.assert_allclose(res.displacement, [np.nan, np.nan, np.sqrt(2.0)])


@pytest.mark.parametrize("offset", [0.0, 1e-13])
def test_temporal_cancellation_has_no_reference_on_the_ambiguous_axis(
    offset: float,
) -> None:
    res = CenterOfMassResult(
        com=np.array([[4.0, 8.0], [12.0 + offset, 8.0]]), shape=(16, 16)
    )

    assert np.isnan(res.reference[0])
    assert np.isclose(res.reference[1], 8.0)
    assert np.isnan(res.deviation[:, 0]).all()
    np.testing.assert_allclose(res.deviation[:, 1], 0.0, atol=1e-12)
    assert np.isnan(res.displacement).all()
    assert np.isnan(res.max_displacement)


def test_deviation_and_displacement_are_zero_for_a_static_centroid() -> None:
    com = np.tile([4.0, 9.0], (5, 1))  # same centroid every frame
    res = CenterOfMassResult(com=com, shape=(16, 16))
    assert np.allclose(res.deviation, 0.0)
    assert np.allclose(res.displacement, 0.0)
    assert np.isclose(res.max_displacement, 0.0)


def test_max_displacement_is_mm_when_the_voxel_size_is_known() -> None:
    # Symmetric about the axis-0 wrap period's midpoint (8 of 16), so the
    # circular reference lands exactly on 8.0 and each frame's deviation is
    # exactly the offset it was placed at -- a clean 1-voxel peak deviation,
    # 2 mm at 2 mm/voxel.
    com = np.array([[7.0, 8.0], [9.0, 8.0]])
    res = CenterOfMassResult(com=com, shape=(16, 16), voxel=VoxelSize((2.0, 2.0)))
    assert np.isclose(res.max_displacement, 2.0)


def test_max_displacement_is_voxels_without_a_known_voxel_size() -> None:
    com = np.array([[7.0, 8.0], [9.0, 8.0]])
    res = CenterOfMassResult(com=com, shape=(16, 16))
    assert np.isclose(res.max_displacement, 1.0)


def test_deviation_wraps_across_the_periodic_boundary() -> None:
    # centroid jumps 15 -> 0: a 1-voxel step across the wrap, not a 15-voxel jump
    com = np.array([[15.0, 8.0], [0.0, 8.0]])
    res = CenterOfMassResult(com=com, shape=(16, 16))
    assert np.max(np.abs(res.deviation[:, 0])) < 1.0
