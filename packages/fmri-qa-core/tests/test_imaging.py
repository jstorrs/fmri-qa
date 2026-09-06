"""Low-level image primitives: masks, ROI indexing, summary images."""

import warnings

import numpy as np
import pytest

import fmriqc as q
from fmriqc.prep.imaging import (
    _clamp_center,
    edge_valid_mask,
    fluctuation_noise,
    image_center,
    odd_even_difference,
    roi_indexes,
    segment_phantom,
    trim_initial,
)


def _disk(n: int = 32) -> np.ndarray:
    """A centered boolean disk of radius n/4 — the fixtures' phantom shape."""
    yy, xx = np.mgrid[0:n, 0:n]
    return np.asarray(((xx - n / 2) ** 2 + (yy - n / 2) ** 2) < (n / 4) ** 2)


def test_trim_initial_drops_leading_volumes() -> None:
    data = np.arange(4 * 4 * 2 * 10).reshape(4, 4, 2, 10)
    trimmed = trim_initial(data, tr=1.0, trim_sec=3.0)  # drop 3
    assert trimmed.shape == (4, 4, 2, 7)
    assert np.array_equal(trimmed, data[..., 3:])


def test_edge_valid_mask_all_true_when_no_zero_edges() -> None:
    image = np.ones((6, 6))
    assert edge_valid_mask(image).all()


def test_edge_valid_mask_clears_only_the_zeroed_edge() -> None:
    image = np.ones((6, 6))
    image[0, :] = 0.0  # dead top row (a Siemens PE-encoding null)
    mask = edge_valid_mask(image)
    assert not mask[0, :].any()
    assert mask[1:, :].all()  # the other three edges survive


def test_edge_valid_mask_each_edge_independent() -> None:
    image = np.ones((5, 5))
    image[:, -1] = 0.0  # only the last column is dead
    mask = edge_valid_mask(image)
    assert not mask[:, -1].any()
    assert mask[:, :-1].all()


def test_roi_indexes_are_centered_and_not_swapped() -> None:
    rows, cols = roi_indexes(np.array([2, 6]), 3)
    # (n-1)//2 = 1 voxel back from the center, width n
    assert (rows.start, rows.stop) == (1, 4)
    assert (cols.start, cols.stop) == (5, 8)


def test_image_center_is_array_index_midpoint() -> None:
    assert tuple(image_center((10, 20))) == (5, 10)


def test_clamp_center_keeps_roi_on_image() -> None:
    # a corner center must shift inward so a 3x3 ROI stays in a 10x10 image
    clamped = _clamp_center(np.array([0, 9]), 3, (10, 10))
    rows, cols = roi_indexes(clamped, 3)
    assert rows.start >= 0 and cols.start >= 0
    assert rows.stop <= 10 and cols.stop <= 10


def test_odd_even_difference_is_zero_for_constant_series() -> None:
    cs = np.ones((4, 4, 20)) * 3.0
    assert np.allclose(odd_even_difference(cs), 0.0)


def test_fluctuation_noise_is_rms_about_zero() -> None:
    resid = np.zeros((3, 3, 10))
    assert np.allclose(fluctuation_noise(resid), 0.0)
    resid[0, 0, :] = np.array([1.0, -1.0] * 5)  # RMS about 0 is 1.0
    assert np.isclose(fluctuation_noise(resid)[0, 0], 1.0)


def test_segment_phantom_separates_a_disk_from_a_noisy_background() -> None:
    disk = _disk()
    rng = np.random.default_rng(0)
    image = np.where(disk, 1000.0, 0.0) + np.abs(rng.normal(scale=8.0, size=disk.shape))
    assert np.array_equal(segment_phantom(image), disk)


def test_segment_phantom_separates_a_disk_over_an_exactly_zero_background() -> None:
    """The seeds must be inclusive, or an exact-zero background seeds nothing.

    A vendor that background-suppresses or mask-multiplies its reconstruction
    leaves the air at exactly 0. More than a tenth of the frame then sits on the
    minimum, so a strict `image < quantile(image, 0.1)` selects no background
    seed at all and the watershed floods the whole frame as phantom -- which
    passes `roi_fits` vacuously, erodes the N/2 ghost region to nothing, and
    divides SFNR by a noiseless floor, all without raising anything.
    """
    disk = _disk()
    image = np.where(disk, 1000.0, 0.0)  # air is exactly zero
    mask = segment_phantom(image)
    assert np.array_equal(mask, disk)
    assert 0 < mask.mean() < 1  # neither collapsed direction


def test_detect_phantom_warns_when_the_mask_covers_the_whole_frame() -> None:
    """A collapsed segmentation is announced rather than passed on in silence.

    Nothing downstream would catch it: a whole-frame mask satisfies `roi_fits`
    for any ROI, so the pipeline's own ROI guard stays quiet too. A constant
    image is the reliable way to collapse the watershed once the seeds are
    inclusive.
    """
    flat = np.full((16, 16, 8), 5.0)
    images = q.QAImages(center_slice=flat, fluctuations=np.zeros_like(flat), tr=2.0)
    with pytest.warns(UserWarning, match="did not separate phantom from background"):
        geom = q.detect_phantom(images)
    assert geom.fraction == 1.0


def test_detect_phantom_is_quiet_on_a_separable_phantom() -> None:
    disk = _disk()
    rng = np.random.default_rng(0)
    series = np.where(disk, 1000.0, 0.0)[:, :, None] + np.abs(
        rng.normal(scale=8.0, size=(*disk.shape, 8))
    )
    images = q.QAImages(center_slice=series, fluctuations=np.zeros_like(series), tr=2.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning here fails the test
        geom = q.detect_phantom(images)
    assert 0.0 < geom.fraction < 0.95
