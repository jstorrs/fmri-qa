"""Low-level image primitives: masks, ROI indexing, summary images."""

import warnings

import numpy as np
import pytest

import fmriqc as q
from fmriqc.prep.imaging import (
    _clamp_center,
    edge_valid_mask,
    extract_center_slice,
    fluctuation_noise,
    image_center,
    odd_even_difference,
    phantom_area,
    phantom_contrast,
    phantom_plausible,
    roi_indexes,
    segment_phantom,
    trim_initial,
)


def _disk(n: int = 32) -> np.ndarray:
    """A centered boolean disk of radius n/4 — the fixtures' phantom shape."""
    yy, xx = np.mgrid[0:n, 0:n]
    return np.asarray(((xx - n / 2) ** 2 + (yy - n / 2) ** 2) < (n / 4) ** 2)


def _air(shape: tuple[int, ...], seed: int = 0, scale: float = 8.0) -> np.ndarray:
    """A magnitude noise floor — one frame's worth of air, holding no phantom."""
    rng = np.random.default_rng(seed)
    return np.abs(rng.normal(scale=scale, size=shape))


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


def test_detect_phantom_rejects_a_partition_of_noise() -> None:
    """A frame of air segments to a middling share of the frame, and still fails.

    The fraction test alone passed it: the watershed labels roughly half of the
    noise, which is a share a real phantom could cover. What gives it away is
    contrast -- the labelled half stands barely above the rest -- and the
    verdict has to apply the same test slice selection does, or a run warns
    that no slice holds a phantom and then records the one it segmented as good.
    """
    series = _air((32, 32, 8))
    images = q.QAImages(center_slice=series, fluctuations=np.zeros_like(series), tr=2.0)
    with pytest.warns(UserWarning, match="no recognizable phantom"):
        geom = q.detect_phantom(images)
    assert 0.0 < geom.fraction < 0.95  # the share alone would have passed
    assert geom.contrast < 4.0
    assert geom.plausible is False


def test_detect_phantom_accepts_a_phantom_over_an_exactly_zero_background() -> None:
    """A background-suppressed reconstruction has infinite contrast, not none."""
    disk = _disk()
    series = np.where(disk, 1000.0, 0.0)[:, :, None] * np.ones((1, 1, 8))
    images = q.QAImages(center_slice=series, fluctuations=np.zeros_like(series), tr=2.0)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        geom = q.detect_phantom(images)
    assert geom.contrast == np.inf
    assert geom.plausible is True


def test_phantom_contrast_of_a_mask_that_partitions_nothing_is_zero() -> None:
    image = np.full((8, 8), 5.0)
    assert phantom_contrast(image, np.zeros((8, 8), dtype=bool)) == 0.0
    assert phantom_contrast(image, np.ones((8, 8), dtype=bool)) == 0.0


@pytest.mark.parametrize(
    ("fraction", "contrast", "plausible"),
    [
        (0.2, 160.0, True),
        (0.2, 4.0, True),  # the contrast floor is inclusive
        (0.2, 1.7, False),  # air: a partition of noise
        (0.0, 160.0, False),  # collapsed to nothing
        (1.0, 160.0, False),  # collapsed to the whole frame
    ],
)
def test_phantom_plausible_needs_both_share_and_contrast(
    fraction: float, contrast: float, plausible: bool
) -> None:
    assert phantom_plausible(fraction, contrast) is plausible


def test_phantom_area_scores_a_frame_of_air_as_no_phantom() -> None:
    """Segmenting noise yields a mask; it must not count as a cross-section.

    The watershed seeds one quantile of the noise against the other and labels
    roughly half the frame, which is *larger* than a real phantom's share -- so
    area alone would rank an empty slice above the phantom. What separates them
    is contrast: the labelled half of the air stands barely above the rest.
    """
    air = _air((64, 64))
    assert 0.3 < segment_phantom(air).mean() < 0.6  # a mask, and a big one
    assert phantom_area(air) == 0  # but not a phantom


def test_phantom_area_counts_a_real_cross_section() -> None:
    disk = _disk(64)
    image = np.where(disk, 1000.0, 0.0) + _air((64, 64))
    assert phantom_area(image) == disk.sum()


def test_extract_center_slice_prefers_the_phantom_over_a_larger_air_mask() -> None:
    """A prescription running off the end of the phantom must not win the argmax.

    Slices past the phantom hold only air, which segments to ~45% of the frame
    against the cross-section's ~20%: ranking slices by segmented area alone
    selects one of them, and every metric is then measured on background.
    """
    disk = _disk(64)
    air = np.stack([_air((64, 64), seed=s) for s in (1, 2)], axis=-1)
    phantom = np.where(disk, 1000.0, 0.0)[:, :, None] + _air((64, 64, 2), seed=3)
    # (X, Y, Z, T) with the phantom in slice 1 and air either side of it
    data = np.stack([air, phantom, air], axis=2)

    chosen = extract_center_slice(data, center="phantom")

    assert np.array_equal(chosen, data[:, :, 1, :])


def test_extract_center_slice_falls_back_when_no_slice_holds_a_phantom() -> None:
    """An all-air volume has no cross-section to find, and says so.

    Silently returning the largest patch of segmented noise would be the old
    behavior wearing a different mask; the middle slice is the honest answer and
    matches what center='image' would have given.
    """
    data = _air((32, 32, 3, 4))
    with pytest.warns(UserWarning, match="no slice holds a recognizable phantom"):
        chosen = extract_center_slice(data, center="phantom")
    assert np.array_equal(chosen, data[:, :, 1, :])  # the middle slice
