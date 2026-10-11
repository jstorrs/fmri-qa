"""Outlier fractions and MAD-normalized spike scores.

The `_spike_ratio` kernel is pinned against hand-computed peak/robust-spread
values. `outlier_fraction` is checked on a clean run, a single injected spike,
and the constant-voxel exclusion rule. `spike_scores` is checked for wiring onto
the ROI-mean residual and its DC-dropped spectrum.
"""

import numpy as np
import pytest

from fmriqc.metrics.artifacts import (
    MAD_SCALE,
    _spike_ratio,
    outlier_fraction,
    spike_scores,
)
from fmriqc.prep.geometry import ROI
from fmriqc.prep.images import QAImages


def test_spike_ratio_is_peak_over_robust_spread() -> None:
    # median 0, MAD = 1.4826 * median(|x|) = 1.4826, peak 1 -> 1 / 1.4826.
    assert np.isclose(_spike_ratio(np.array([-1.0, -1.0, 1.0, 1.0])), 1.0 / MAD_SCALE)
    # median 1, |x - 1| = [2,2,2,0,0,0,19] -> MAD = 1.4826*2, peak 20.
    assert np.isclose(
        _spike_ratio(np.array([-1.0, -1.0, -1.0, 1.0, 1.0, 1.0, 20.0])),
        20.0 / (MAD_SCALE * 2.0),
    )


def test_spike_ratio_is_nan_without_spread() -> None:
    assert np.isnan(_spike_ratio(np.array([0.0, 0.0, 0.0, 10.0])))  # MAD == 0
    assert np.isnan(_spike_ratio(np.array([])))  # empty


def test_outlier_fraction_clean_run_flags_nothing() -> None:
    # Alternating +/-1 residual sits far below the 3dToutcount threshold, so no
    # voxel flags any frame.
    fluct = np.tile([1.0, -1.0], 10) * np.ones((4, 4, 1))
    res = outlier_fraction(fluct, np.ones((4, 4), dtype=bool))
    assert res.n_voxels == 16
    assert res.max_fraction == 0.0
    assert res.qthr == 0.001


@pytest.mark.parametrize(
    ("n_frames", "qthr", "expected_fraction"),
    [(20, 0.001, 0.75), (200, 0.001, 0.25), (200, 0.01, 0.75)],
)
def test_outlier_fraction_threshold_depends_on_length_and_qthr(
    n_frames: int, qthr: float, expected_fraction: float
) -> None:
    # All nonconstant voxels have median |residual| = 1. At qthr=0.001,
    # a +/-5.2 spike exceeds the threshold for 20 frames but not 200;
    # an 8.0 spike flags in both, and the constant voxel stays in the denominator.
    fluct = np.tile([1.0, -1.0], n_frames // 2) * np.ones((2, 2, 1))
    fluct[:, :, 7] = [[5.2, -5.2], [8.0, 0.0]]
    fluct[1, 1, :] = 0.0
    result = outlier_fraction(fluct, np.ones((2, 2), dtype=bool), qthr=qthr)

    expected = np.zeros(n_frames)
    expected[7] = expected_fraction
    np.testing.assert_array_equal(result.fraction, expected)
    assert result.n_voxels == 4
    assert result.qthr == qthr
    assert result.max_fraction == expected_fraction
    assert result.worst_volume == 7


def test_outlier_fraction_flags_the_spiked_frame() -> None:
    fluct = np.tile([1.0, -1.0], 10) * np.ones((4, 4, 1))
    fluct[:, :, 7] = 100.0  # one grossly outlying volume across every voxel
    res = outlier_fraction(fluct, np.ones((4, 4), dtype=bool))
    assert res.fraction[7] == 1.0  # all 16 voxels flag frame 7
    assert res.worst_volume == 7
    assert np.count_nonzero(res.fraction) == 1


def test_outlier_fraction_ignores_constant_voxels() -> None:
    # A voxel that never varies (MAD == 0) is dropped from the flag count but not
    # the denominator, so the spiked frame flags 15 of 16 voxels.
    fluct = np.tile([1.0, -1.0], 10) * np.ones((4, 4, 1))
    fluct[:, :, 7] = 100.0
    fluct[0, 0, :] = 0.0  # constant voxel
    res = outlier_fraction(fluct, np.ones((4, 4), dtype=bool))
    assert np.isclose(res.fraction[7], 15.0 / 16.0)


def test_spike_scores_read_the_roi_mean_residual_and_drop_dc() -> None:
    # Identical voxels, so the ROI-mean residual equals the per-voxel series and
    # the scores must match the kernel applied to that series / its DC-dropped FFT.
    r = np.array([1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 1.0, -1.0, 12.0])
    fluct = np.ones((4, 4, 1)) * r
    images = QAImages(center_slice=np.ones((4, 4, r.size)), fluctuations=fluct, tr=2.0)
    roi = ROI(center=np.array([1, 1]), size=4)  # full 4x4

    scores = spike_scores(images, roi)
    assert np.isclose(scores.tc_outlier, _spike_ratio(r))
    spec = np.abs(np.fft.rfft(r))[1:]  # DC bin dropped, as spike_scores does
    assert np.isclose(scores.spec_outlier, _spike_ratio(spec))
