"""Value-object behavior: the derived properties on the result dataclasses."""

import numpy as np

from fmriqc.imaging import roi_indexes
from fmriqc.types import ROI, MotionResult, QAImages, SaturationResult


def test_roi_index_matches_roi_indexes() -> None:
    roi = ROI(center=np.array([5, 7]), size=3)
    assert roi.index == roi_indexes(np.array([5, 7]), 3)


def test_saturation_result_derived_flags() -> None:
    hit = SaturationResult(
        ceiling=4095.0,
        bits=12,
        n_clipped_pre=3,
        n_clipped_kept=2,
        worst_volume=5,
        worst_count=4,
    )
    assert hit.n_clipped == 5
    assert hit.suspected and hit.clipped and hit.clipped_kept

    clean = SaturationResult(
        ceiling=None,
        bits=None,
        n_clipped_pre=0,
        n_clipped_kept=0,
        worst_volume=None,
        worst_count=0,
    )
    assert not clean.suspected and not clean.clipped and not clean.clipped_kept


def test_saturation_clipped_but_not_kept_when_only_warmup_clips() -> None:
    warmup_only = SaturationResult(
        ceiling=4095.0,
        bits=12,
        n_clipped_pre=7,
        n_clipped_kept=0,
        worst_volume=0,
        worst_count=7,
    )
    assert warmup_only.clipped and not warmup_only.clipped_kept


def test_motion_result_derived_views() -> None:
    params = np.zeros((3, 5))
    params[1] = [1.0, 0.0, 0.02, 0.0, 0.0]  # 1 voxel translation, 2% scale on axis 0
    motion = MotionResult(params=params, voxel_mm=(2.0, 2.0))
    assert np.allclose(motion.translation, params[:, 0:2])
    assert np.isclose(motion.max_translation, 1.0)
    assert np.isclose(motion.max_scale_pct, 2.0)
    # displacement uses voxel_mm: a 1-voxel move at 2 mm/voxel is 2 mm
    assert np.isclose(motion.displacement[1], 2.0)


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
    assert images.valid_mask.all()  # no zeroed edges in this synthetic slice
