"""The shipped phantom: deterministic, and `phantom_scan` describes what it writes."""

import numpy as np

from fmriqa.testing import PHANTOM_SIGNAL, phantom_scan, synthetic_series


def test_the_series_is_float64_in_the_requested_shape() -> None:
    series = synthetic_series(n=16, z=2, t=5)
    assert series.shape == (16, 16, 2, 5)
    assert series.dtype == np.float64


def test_a_seed_gives_the_same_series_and_another_seed_a_different_one() -> None:
    assert np.array_equal(synthetic_series(seed=3), synthetic_series(seed=3))
    assert not np.array_equal(synthetic_series(seed=3), synthetic_series(seed=4))


def test_the_disk_stands_above_the_floor() -> None:
    series = synthetic_series()
    assert series[16, 16].mean() > 0.9 * PHANTOM_SIGNAL
    assert series[0, 0].mean() < 0.05 * PHANTOM_SIGNAL


def test_smoothing_blurs_and_zero_leaves_the_series_alone() -> None:
    sharp = synthetic_series()
    assert np.array_equal(sharp, synthetic_series(smoothing=0.0))
    assert not np.array_equal(sharp, synthetic_series(smoothing=0.8))


def test_the_scan_carries_the_acquisition_a_file_would() -> None:
    scan = phantom_scan(n=16, z=2, t=5, flip=60.0)
    assert scan.data.shape == (16, 16, 2, 5)
    assert np.array_equal(scan.data, np.floor(scan.data))  # stored as integers
    assert (scan.tr, scan.pe_axis, scan.stored_integer) == (2.0, 1, True)
    assert scan.meta is not None
    assert (scan.meta.matrix, scan.meta.flip_angle, scan.meta.pe_dir) == (
        (16, 16),
        60.0,
        "col",
    )
