"""Value-object behavior: the derived properties on the result dataclasses."""

from dataclasses import fields

import numpy as np
import pytest

from fmriqa import ROI, ClipRail, MotionResult, QAImages, SaturationResult
from fmriqa.prep.geometry import _roi_indexes
from fmriqa.prep.scale import VoxelSize


def test_roi_index_matches_roi_indexes() -> None:
    roi = ROI(center=np.array([5, 7]), size=3)
    assert roi.index == _roi_indexes(np.array([5, 7]), 3)


def test_saturation_result_derived_flags() -> None:
    hit = SaturationResult(
        rail=ClipRail(ceiling=4095.0, bits=12, worst_volume=5, worst_count=4),
        n_clipped_pre=3,
        n_clipped_kept=2,
    )
    assert hit.n_clipped == 5
    assert hit.suspected and hit.clipped and hit.clipped_kept

    clean = SaturationResult(
        rail=None,
        n_clipped_pre=0,
        n_clipped_kept=0,
    )
    assert not clean.suspected and not clean.clipped and not clean.clipped_kept


def test_saturation_ceiling_and_bits_are_present_or_absent_together() -> None:
    """The rail's level and its bit depth are one detection, not two fields.

    A `ceiling` with a `bits` of None, or the reverse, was a state the dataclass
    allowed and only `detect_saturation` kept from arising. Behind one optional
    `rail` the pair cannot come apart, and neither can the worst-clipped volume,
    which is meaningless without a rail. The convenience properties read off the
    rail, so the artifact's flat `clip_ceiling`/`clip_bits` contract is
    unchanged.
    """
    names = {f.name for f in fields(SaturationResult)}
    assert names == {"rail", "n_clipped_pre", "n_clipped_kept"}

    clean = SaturationResult(rail=None, n_clipped_pre=0, n_clipped_kept=0)
    assert clean.ceiling is None and clean.bits is None

    hit = SaturationResult(
        rail=ClipRail(ceiling=4095.0, bits=12, worst_volume=5, worst_count=4),
        n_clipped_pre=0,
        n_clipped_kept=4,
    )
    assert hit.ceiling == 4095.0 and hit.bits == 12


def test_saturation_clipped_but_not_kept_when_only_warmup_clips() -> None:
    warmup_only = SaturationResult(
        rail=ClipRail(ceiling=4095.0, bits=12, worst_volume=0, worst_count=7),
        n_clipped_pre=7,
        n_clipped_kept=0,
    )
    assert warmup_only.clipped and not warmup_only.clipped_kept


def test_motion_result_derived_views() -> None:
    params = np.zeros((3, 5))
    params[1] = [1.0, 0.0, 0.02, 0.0, 0.0]  # 1 voxel translation, 2% scale on axis 0
    motion = MotionResult(params=params, voxel=VoxelSize((2.0, 2.0)))
    assert np.allclose(motion.translation, params[:, 0:2])
    assert np.isclose(motion.max_scale_pct, 2.0)
    # displacement scales by `voxel`: a 1-voxel move at 2 mm/voxel is 2 mm
    assert np.isclose(motion.displacement[1], 2.0)
    # max_translation is the peak of displacement, so it shares its unit
    assert np.isclose(motion.max_translation, 2.0)


def test_motion_result_max_translation_is_voxels_without_a_known_voxel_size() -> None:
    params = np.zeros((3, 5))
    params[1] = [1.0, 0.0, 0.0, 0.0, 0.0]  # 1 voxel translation
    motion = MotionResult(params=params)
    assert np.isclose(motion.max_translation, 1.0)


def test_qaimages_derived_images_are_consistent() -> None:
    rng = np.random.default_rng(0)
    center_slice = rng.normal(loc=100.0, scale=5.0, size=(8, 8, 30))
    fluctuations = center_slice - center_slice.mean(axis=-1, keepdims=True)
    images = QAImages(center_slice=center_slice, fluctuations=fluctuations, tr=2.0)

    assert np.allclose(images.mean_image, center_slice.mean(axis=-1))
    assert np.allclose(images.mip, center_slice.max(axis=-1))
    # trend + fluctuations reconstructs the signal
    assert np.allclose(images.trend + images.fluctuations, center_slice)
    assert images.valid_mask.shape == (8, 8)
    assert images.valid_mask.all()  # no nulled edges in this synthetic slice


def test_qaimages_finds_a_nulled_edge_under_a_nonzero_intercept() -> None:
    """A stored zero reads back as the intercept, and is still a dead line.

    `get_fdata` returns `stored * slope + inter`, so a Siemens-nulled row in a
    scan with `scl_inter = 10` arrives as 10s, not zeros. Testing the edge
    against 0.0 would let that constant line into every ROI average and ghost
    statistic.
    """
    inter = 10.0
    center_slice = np.full((8, 8, 6), 100.0)
    center_slice[0, :, :] = inter  # the nulled top row, after header scaling
    images = QAImages(
        center_slice=center_slice,
        fluctuations=np.zeros_like(center_slice),
        tr=2.0,
        zero_value=inter,
    )

    assert not images.valid_mask[0, :].any()
    assert images.valid_mask[1:, :].all()  # the other three edges survive


def test_qaimages_owns_immutable_arrays_and_caches() -> None:
    data = np.random.default_rng(2).normal(size=(8, 8, 20))
    residual = data - data.mean(axis=-1, keepdims=True)
    images = QAImages(data, residual, tr=2)
    expected = images.mean_image.copy()
    data[:] = 0
    residual[:] = 0
    assert np.array_equal(images.mean_image, expected)
    assert np.array_equal(images.center_slice.mean(axis=-1), expected)
    assert images.fluctuations.any()
    for array in (
        images.center_slice,
        images.fluctuations,
        images.mean_image,
        images.mip,
        images.trend,
        images.valid_mask,
        images.static_noise,
        images.fluctuation_noise,
    ):
        with pytest.raises(ValueError, match="read-only"):
            array.flat[0] = 0
