"""Core FBIRN ROI metrics against hand-computed known answers.

Each test builds a `QAImages` directly from a constructed center slice and
fluctuation field (no file I/O, no pipeline), over a full-image ROI, so the
expected SNR/SFNR/drift/fluctuation/RDC follow in closed form from the Glover
definitions and a regression in the formula (a wrong normalization, mean-vs-sum,
or axis) changes the number.
"""

import numpy as np

from fmriqc.metrics.fbirn import (
    drift_percent,
    percent_fluctuation,
    sfnr,
    snr,
    weisskoff,
)
from fmriqc.prep.geometry import ROI
from fmriqc.prep.images import QAImages


def _images(center_slice: np.ndarray, fluctuations: np.ndarray) -> QAImages:
    """A minimal `QAImages` over an (X, Y, T) slice and its residual field."""
    return QAImages(
        center_slice=np.asarray(center_slice, dtype=float),
        fluctuations=np.asarray(fluctuations, dtype=float),
        tr=2.0,
    )


def _full_roi(n: int) -> ROI:
    """An ROI covering the whole n x n image.

    `roi_indexes` places the block at `center - (n - 1) // 2`, so centering on
    `(n - 1) // 2` makes it start at 0 and span the full image (0:n, 0:n).
    """
    c = (n - 1) // 2
    return ROI(center=np.array([c, c]), size=n)


def test_snr_matches_the_glover_static_noise_formula() -> None:
    # 4x4 slice, 8 frames. Signal 100 everywhere; a static, per-voxel odd/even
    # imbalance d = +/-2 (top half +2, bottom half -2) is the only structure.
    # frame t = 100 + d on even t, 100 - d on odd t, so the temporal mean is 100
    # and the (sum-odd - sum-even) difference image is exactly -8*d.
    m = np.full((4, 4), 100.0)
    d = np.where(np.arange(4)[:, None] < 2, 2.0, -2.0) * np.ones((4, 4))
    sign = np.where(np.arange(8) % 2 == 0, 1.0, -1.0)  # + on even t, - on odd t
    fluct = d[:, :, None] * sign
    images = _images(m[:, :, None] + fluct, fluct)

    # var(diff)/N = var(-8d)/8 = 64*var(d)/8 = 64*4/8 = 32; SNR = 100/sqrt(32).
    assert np.isclose(snr(images, _full_roi(4)), 100.0 / np.sqrt(32.0))


def _shaded_snr_series(n_frames: int) -> np.ndarray:
    """The SNR test's series over a strongly shaded phantom, `n_frames` long.

    Signal is a steep ramp across the FOV (a caricature of receive shading) with
    ROI mean 100; the only temporal structure is the same static odd/even
    imbalance `d = +/-2`. Over an even frame count the ramp cancels exactly out
    of the (odd-sum - even-sum) difference, leaving -T*d, so the SNR is the same
    100/sqrt(32) the unshaded case gives -- shading is signal, not noise.
    """
    ramp = np.linspace(50.0, 150.0, 4)[:, None] * np.ones((4, 4))  # ROI mean 100
    d = np.where(np.arange(4)[:, None] < 2, 2.0, -2.0) * np.ones((4, 4))
    sign = np.where(np.arange(n_frames) % 2 == 0, 1.0, -1.0)
    return ramp[:, :, None] + d[:, :, None] * sign


def test_snr_is_unchanged_by_an_odd_trailing_frame() -> None:
    """The static-noise difference is formed over balanced odd/even subsets.

    An odd frame count leaves the two sums one frame apart, so the difference
    carries a whole frame of *signal* -- and its spatial variation across the
    ROI, not the noise, then sets the denominator. The shaded phantom here reads
    ~35% low that way. Parity is a function of `--trim-sec`, so without this the
    same series scores differently for a one-volume change in the warm-up trim.
    """
    even = _shaded_snr_series(8)
    odd = _shaded_snr_series(9)  # one extra frame, same phantom

    expected = 100.0 / np.sqrt(32.0)  # the closed form of the 8-frame case
    assert np.isclose(snr(_images(even, even - 100.0), _full_roi(4)), expected)
    assert np.isclose(snr(_images(odd, odd - 100.0), _full_roi(4)), expected)


def test_snr_is_undefined_without_a_complete_frame_pair() -> None:
    """A single frame has no odd/even pair to difference: NaN, not a number."""
    one = np.full((4, 4, 1), 100.0)
    assert np.isnan(snr(_images(one, np.zeros_like(one)), _full_roi(4)))


def test_sfnr_is_the_roi_mean_of_signal_over_fluctuation_noise() -> None:
    # Signal 100, per-voxel temporal fluctuation of RMS 2 (alternating +/-2), so
    # the voxelwise SFNR image is a uniform 100/2 and its ROI mean is 50.
    m = np.full((4, 4), 100.0)
    sign = np.where(np.arange(8) % 2 == 0, 1.0, -1.0)
    fluct = 2.0 * np.ones((4, 4))[:, :, None] * sign
    images = _images(m[:, :, None] + fluct, fluct)

    assert np.isclose(sfnr(images, _full_roi(4)), 50.0)


def test_drift_percent_is_peak_to_peak_of_the_fitted_trend() -> None:
    # trend = center_slice - fluctuations. A centered ramp t-3.5 over 8 frames has
    # peak-to-peak 7 and temporal mean 0, so the mean image stays 100 and the
    # drift is 100 * 7 / 100 = 7 percent.
    ramp = np.arange(8, dtype=float) - 3.5
    center = 100.0 + np.zeros((4, 4))[:, :, None] + ramp
    fluct = np.zeros((4, 4, 8))
    images = _images(center, fluct)

    assert np.isclose(drift_percent(images, _full_roi(4)), 7.0)


def test_percent_fluctuation_is_residual_sd_over_signal() -> None:
    # ROI-mean residual alternates +/-3 (SD about zero = 3) on a 100 signal, so
    # the percent fluctuation is 100 * 3 / 100 = 3.
    m = np.full((4, 4), 100.0)
    sign = np.where(np.arange(8) % 2 == 0, 1.0, -1.0)
    fluct = 3.0 * np.ones((4, 4))[:, :, None] * sign
    images = _images(m[:, :, None] + fluct, fluct)

    assert np.isclose(percent_fluctuation(images, _full_roi(4)), 3.0)


def test_rdc_is_one_when_every_voxel_shares_the_same_fluctuation() -> None:
    # Perfectly correlated voxels: ROI-averaging removes no variance, so the
    # ROI-mean CV equals the pooled single-voxel CV and RDC = 1 at every size.
    m = np.full((4, 4), 100.0)
    shared = np.where(np.arange(8) % 2 == 0, 1.0, -1.0)  # identical across voxels
    fluct = np.ones((4, 4))[:, :, None] * shared
    images = _images(m[:, :, None] + fluct, fluct)

    wk = weisskoff(images, _full_roi(4))
    assert np.array_equal(wk.roi_sizes, np.arange(1, 5))
    assert np.isclose(wk.rdc, 1.0)
    assert np.allclose(wk.rdc_curve, 1.0)


def test_rdc_exceeds_one_when_voxels_are_independent() -> None:
    # Independent per-voxel noise: averaging over the ROI shrinks the ROI-mean CV
    # while the pooled single-voxel CV stays put, so RDC climbs above 1 and the
    # curve rises with ROI size (the Weisskoff decorrelation the plot measures).
    rng = np.random.default_rng(0)
    m = np.full((16, 16), 100.0)
    fluct = rng.normal(scale=5.0, size=(16, 16, 200))
    fluct -= fluct.mean(axis=-1, keepdims=True)  # zero temporal mean
    images = _images(m[:, :, None] + fluct, fluct)

    wk = weisskoff(images, _full_roi(16))
    assert wk.rdc > 1.0
    assert wk.rdc_curve[-1] > wk.rdc_curve[0]
