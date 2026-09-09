"""Circular center-of-mass: locates the phantom and respects the periodic FOV."""

import numpy as np

from fmriqc.metrics.center_of_mass import CenterOfMassResult, estimate_center_of_mass


def _block_slice(center: tuple[int, int], n: int = 16, t: int = 6) -> np.ndarray:
    """(n, n, t) slice: a bright 3x3 block at `center` (wrapping) on a flat floor."""
    cs = np.full((n, n, t), 10.0)  # uniform background pedestal
    r, c = center
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            cs[(r + dr) % n, (c + dc) % n, :] = 1000.0
    return cs


def test_com_locates_a_central_phantom() -> None:
    res = estimate_center_of_mass(_block_slice((8, 5)))
    assert np.allclose(res.com[:, 0], 8.0, atol=0.5)
    assert np.allclose(res.com[:, 1], 5.0, atol=0.5)


def test_com_handles_a_phantom_wrapped_across_the_edge() -> None:
    # a block centered on row 0 straddles the wrapped boundary (rows 15, 0, 1)
    res = estimate_center_of_mass(_block_slice((0, 8)))
    # circular COM stays near 0 (mod 16), not aliased to mid-FOV (~8)
    wrapped = (res.com[:, 0] + 8) % 16 - 8  # into (-8, 8]
    assert np.allclose(wrapped, 0.0, atol=0.5)


def test_uniform_field_has_no_defined_centroid() -> None:
    # a flat field is all pedestal: no above-floor signal -> NaN, not mid-FOV bias
    res = estimate_center_of_mass(np.full((16, 16, 4), 42.0))
    assert np.isnan(res.com).all()


def test_deviation_and_displacement_are_zero_for_a_static_centroid() -> None:
    com = np.tile([4.0, 9.0], (5, 1))  # same centroid every frame
    res = CenterOfMassResult(com=com, shape=(16, 16))
    assert np.allclose(res.deviation, 0.0)
    assert np.allclose(res.displacement, 0.0)
    assert np.isclose(res.max_displacement, 0.0)


def test_max_displacement_is_mm_when_voxel_mm_is_known() -> None:
    # Symmetric about the axis-0 wrap period's midpoint (8 of 16), so the
    # circular reference lands exactly on 8.0 and each frame's deviation is
    # exactly the offset it was placed at -- a clean 1-voxel peak deviation,
    # 2 mm at 2 mm/voxel.
    com = np.array([[7.0, 8.0], [9.0, 8.0]])
    res = CenterOfMassResult(com=com, shape=(16, 16), voxel_mm=(2.0, 2.0))
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
