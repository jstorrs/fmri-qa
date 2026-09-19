"""High/low flip-angle noise separation: the pure variance algebra."""

import warnings

import numpy as np
import pytest
from scipy import ndimage

from fmriqc.hilo import separate_noise
from fmriqc.hilo.mask import HILO_ERODE, phantom_core_mask


@pytest.mark.parametrize(("radius", "noisy"), [(8, False), (8, True), (12, True)])
def test_phantom_core_mask_stays_inside_the_sphere(radius: int, noisy: bool) -> None:
    z, y, x = np.mgrid[:32, :32, :32]
    sphere = (x - 16) ** 2 + (y - 16) ** 2 + (z - 16) ** 2 < radius**2
    volume = np.where(sphere, 1000.0, 0.0)
    if noisy:
        rng = np.random.default_rng(0)
        volume += np.abs(rng.normal(scale=8.0, size=volume.shape))
    else:
        assert np.quantile(volume, 0.1) == np.quantile(volume, 0.9)

    core = phantom_core_mask(volume)

    assert core.any()
    assert not core[~sphere].any()
    if not noisy:
        assert np.array_equal(
            core, ndimage.binary_erosion(sphere, iterations=HILO_ERODE)
        )


@pytest.mark.parametrize("value", [0.0, 5.0])
def test_phantom_core_mask_is_empty_for_a_constant_volume(value: float) -> None:
    assert not phantom_core_mask(np.full((32, 32, 32), value)).any()


def test_separate_noise_recovers_the_planted_variances() -> None:
    # build var_high/var_low from a known thermal + instability split, then invert
    mean_high, mean_low = 200.0, 100.0
    m = (mean_high / mean_low) ** 2  # == 4
    thermal, instability0 = 10.0, 5.0
    var_low = thermal + instability0  # 15
    var_high = thermal + m * instability0  # 30
    res = separate_noise(
        mean_high=mean_high, mean_low=mean_low, var_high=var_high, var_low=var_low
    )
    assert not res.fell_back
    assert np.isclose(res.thermal_var, thermal)
    assert np.isclose(res.instability_var, m * instability0)
    assert np.isclose(res.m, m)


def test_separate_noise_falls_back_when_instability_goes_negative() -> None:
    # measurement noise makes the solved instability variance negative
    res = separate_noise(mean_high=200.0, mean_low=100.0, var_high=10.0, var_low=15.0)
    assert res.fell_back
    assert np.isclose(res.thermal_var, 15.0)  # falls back to var_low
    assert np.isclose(res.instability_var, 10.0 - 15.0)


def test_hilo_fsnr_properties_handle_degenerate_variance() -> None:
    res = separate_noise(mean_high=200.0, mean_low=100.0, var_high=30.0, var_low=15.0)
    assert np.isclose(res.thermal_fsnr, 200.0 / np.sqrt(res.thermal_var))
    # a non-positive thermal variance yields NaN, not a crash
    degenerate = separate_noise(
        mean_high=100.0, mean_low=100.001, var_high=1.0, var_low=1.0
    )
    assert np.isnan(degenerate.thermal_fsnr) or np.isfinite(degenerate.thermal_fsnr)


def test_separate_noise_is_nan_when_signal_does_not_change_with_flip() -> None:
    # Equal high/low signal (m == 1, e.g. the same scan twice) makes the split
    # divide by m - 1 == 0; it must return NaN variances, not divide by zero.
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # no zero-division warning may escape
        res = separate_noise(
            mean_high=100.0, mean_low=100.0, var_high=20.0, var_low=10.0
        )
    assert np.isnan(res.thermal_var)
    assert np.isnan(res.instability_var)
    assert not res.fell_back
    # a zero low-flip signal is likewise undefined (m -> inf)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        zero = separate_noise(
            mean_high=100.0, mean_low=0.0, var_high=20.0, var_low=10.0
        )
    assert np.isnan(zero.thermal_var)


def test_m_is_infinite_when_the_low_flip_signal_is_zero() -> None:
    """No low-flip signal means no ratio, reported as infinity rather than raised.

    `M` is printed by `fmri-qa-hilo` outside the block that turns an analysis
    failure into a clean message, so a `ZeroDivisionError` here would surface as
    a traceback on a scan the rest of the run already handled.
    """
    zero = separate_noise(mean_high=100.0, mean_low=0.0, var_high=20.0, var_low=10.0)
    assert zero.m == float("inf")


def test_instability_fraction_is_share_of_high_variance() -> None:
    res = separate_noise(mean_high=200.0, mean_low=100.0, var_high=30.0, var_low=15.0)
    assert np.isclose(res.instability_fraction, res.instability_var / res.var_high)
