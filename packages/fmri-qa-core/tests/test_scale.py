"""The in-plane voxel size: the unit it implies, and the lengths it scales."""

import numpy as np

from fmriqc.prep.scale import UNKNOWN_VOXEL_SIZE, VoxelSize


def test_unit_follows_from_whether_the_size_is_known() -> None:
    """One definition of "mm when the voxel size is known, else vox".

    The artifact publishes this twice (`fwhm_unit`, `displacement_unit`) and the
    PSF curves label with it a third time. All read it from here, so a length
    and its unit cannot disagree.
    """
    assert VoxelSize((3.0, 3.0)).unit == "mm"
    assert VoxelSize().unit == "vox"
    assert UNKNOWN_VOXEL_SIZE.unit == "vox"
    assert UNKNOWN_VOXEL_SIZE.mm is None


def test_in_plane_drops_the_through_plane_element() -> None:
    """A header's voxel size is a triple; the single-slice metrics measure in two.

    `in_plane` is the one place the row/col pair is taken, so no caller slices
    the triple itself and picks up the slice spacing.
    """
    assert VoxelSize.in_plane((2.0, 4.0, 6.0)) == VoxelSize((2.0, 4.0))


def test_a_numpy_voxel_size_is_stored_as_plain_floats() -> None:
    """The header hands these over as numpy scalars; the stored pair is floats.

    A result that kept them raw would publish a numpy type where its annotation
    promises `float`, which passes every in-process check and fails only when
    the artifact is serialized.
    """
    size = VoxelSize(tuple(np.array([3.0, 3.5])))  # type: ignore[arg-type]

    assert size.mm is not None
    assert [type(v) for v in size.mm] == [float, float]
    assert size.mm == (3.0, 3.5)


def test_per_axis_falls_back_to_a_unit_scale_rather_than_a_guessed_size() -> None:
    """An unknown size scales by 1.0, which leaves a length in voxels.

    The 1.0 is the factor that leaves the number alone, and `unit` says so.
    """
    known = VoxelSize((2.0, 4.0))
    assert (known.per_axis(0), known.per_axis(1)) == (2.0, 4.0)
    assert (VoxelSize().per_axis(0), VoxelSize().per_axis(1)) == (1.0, 1.0)


def test_magnitude_scales_each_axis_before_combining_them() -> None:
    """Anisotropic voxels give a true length, not a hypotenuse of voxel counts.

    A one-voxel step along each axis is 2 mm and 4 mm, so the diagonal is
    hypot(2, 4), not hypot(1, 1) scaled by anything.
    """
    steps = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])

    assert np.allclose(
        VoxelSize((2.0, 4.0)).magnitude(steps), [2.0, 4.0, np.hypot(2.0, 4.0)]
    )
    assert np.allclose(VoxelSize().magnitude(steps), [1.0, 1.0, np.hypot(1.0, 1.0)])


def test_magnitude_keeps_an_undefined_frame_undefined() -> None:
    """A failed motion fit is an all-NaN row, and must stay one.

    `MotionResult.max_translation` takes a plain `np.max` so any failed frame
    makes the run's peak NaN, not a peak over an incomplete series.
    """
    frames = np.array([[1.0, 0.0], [np.nan, np.nan]])

    for size in (VoxelSize((2.0, 2.0)), VoxelSize()):
        magnitudes = size.magnitude(frames)
        assert np.isfinite(magnitudes[0])
        assert np.isnan(magnitudes[1])
        assert np.isnan(np.max(magnitudes))
