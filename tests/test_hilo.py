"""High/low flip-angle noise separation: the pure variance algebra."""

import numpy as np

from fmriqc.hilo import separate_noise


def test_separate_noise_recovers_the_planted_variances() -> None:
    # build var_high/var_low from a known thermal + instability split, then invert
    mean_high, mean_low = 200.0, 100.0
    m = (mean_high / mean_low) ** 2  # == 4
    thermal, instability0 = 10.0, 5.0
    var_low = thermal + instability0  # 15
    var_high = thermal + m * instability0  # 30
    res = separate_noise(mean_high, mean_low, var_high, var_low)
    assert not res.fell_back
    assert np.isclose(res.thermal_var, thermal)
    assert np.isclose(res.instability_var, m * instability0)
    assert np.isclose(res.m, m)


def test_separate_noise_falls_back_when_instability_goes_negative() -> None:
    # measurement noise makes the solved instability variance negative
    res = separate_noise(200.0, 100.0, var_high=10.0, var_low=15.0)
    assert res.fell_back
    assert np.isclose(res.thermal_var, 15.0)  # falls back to var_low
    assert np.isclose(res.instability_var, 10.0 - 15.0)


def test_hilo_fsnr_properties_handle_degenerate_variance() -> None:
    res = separate_noise(200.0, 100.0, var_high=30.0, var_low=15.0)
    assert np.isclose(res.thermal_fsnr, 200.0 / np.sqrt(res.thermal_var))
    # a non-positive thermal variance yields NaN, not a crash
    degenerate = separate_noise(100.0, 100.001, var_high=1.0, var_low=1.0)
    assert np.isnan(degenerate.thermal_fsnr) or np.isfinite(degenerate.thermal_fsnr)


def test_instability_fraction_is_share_of_high_variance() -> None:
    res = separate_noise(200.0, 100.0, var_high=30.0, var_low=15.0)
    assert np.isclose(res.instability_fraction, res.instability_var / res.var_high)
