"""The shipped phantom: deterministic, and `phantom_scan` describes what it writes."""

import numpy as np
import pytest

import fmriqa as q
from fmriqa.testing import (
    NOISE_SIGMA,
    PHANTOM_SIGNAL,
    VOXEL_MM,
    phantom_scan,
    synthetic_series,
)
from fmriqa.testing.kspace import Component, Disk, Grid, object_spectrum, reconstruct


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
    """Unsmoothed, the frame is the plain reconstruction of the disk's spectrum."""
    grid = Grid((32, 32), (VOXEL_MM, VOXEL_MM))
    disk = Component(Disk((0.0, 0.0), 8 * VOXEL_MM), PHANTOM_SIGNAL)
    plain = np.abs(reconstruct(object_spectrum([disk], *grid.k()), grid))
    sharp = synthetic_series(z=1, t=1, smoothing=0.0, noise=0.0)
    assert np.array_equal(sharp[:, :, 0, 0], plain)
    assert not np.array_equal(sharp, synthetic_series(z=1, t=1, smoothing=0.8))


def test_smoothing_is_a_gaussian_of_that_many_voxels() -> None:
    """One blur std inside the disk edge, a blurred step reads Φ(1) ≈ 0.841.

    At n = 64 the radius is 16 voxels, so the edge is 8 stds of a 2-voxel blur
    from the centre and its far side, which both stay at full signal.
    """
    series = synthetic_series(n=64, z=1, t=1, smoothing=2.0, noise=0.0)
    profile = series[32, :, 0, 0]
    assert profile[32 + 16 - 2] / profile[32] == pytest.approx(0.841, abs=0.02)


@pytest.mark.parametrize("value", [-0.8, float("nan"), float("inf")])
def test_a_negative_or_non_finite_smoothing_is_rejected(value: float) -> None:
    with pytest.raises(ValueError, match=f"smoothing .* got {value}"):
        synthetic_series(smoothing=value)


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_a_negative_or_non_finite_noise_is_rejected(value: float) -> None:
    with pytest.raises(ValueError, match=f"noise .* got {value}"):
        synthetic_series(noise=value)


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


def test_the_ghost_to_signal_ratio_is_the_requested_ghost() -> None:
    """Noise-free, the N/2 image of the disk centre is `ghost` times the centre.

    Smoothing by 2 voxels at n = 64 leaves the disk centre and its N/2 image
    16 voxels (8 blur stds) from any edge and apodizes Nyquist by exp(-2π²) ≈ 3e-9,
    so neither the blur nor Gibbs ringing reaches the two samples compared.
    """
    series = synthetic_series(n=64, z=1, t=1, smoothing=2.0, ghost=0.1, noise=0.0)
    centre, image = series[32, 32, 0, 0], series[32, 0, 0, 0]
    assert image / centre == pytest.approx(0.1, rel=1e-6)


def test_no_ghost_leaves_the_disk_rotationally_symmetric() -> None:
    """Any weighting of axis-1 lines would break the disk's x-y symmetry."""
    series = synthetic_series(n=32, z=1, t=1, noise=0.0)
    np.testing.assert_allclose(series, series.transpose(1, 0, 2, 3), atol=1e-9)


@pytest.mark.parametrize("ghost", [-0.1, float("nan"), float("inf")])
def test_a_negative_or_non_finite_ghost_is_rejected(ghost: float) -> None:
    with pytest.raises(ValueError, match=f"got {ghost}"):
        synthetic_series(ghost=ghost)


def test_a_ghost_on_an_odd_matrix_is_rejected() -> None:
    with pytest.raises(ValueError, match="n=31"):
        synthetic_series(n=31, ghost=0.1)


def test_drift_changes_the_disk_signal_by_the_requested_fraction() -> None:
    """Noise-free, the disk's last frame exceeds its first by `drift` of the mean."""
    series = synthetic_series(t=60, drift=0.05, noise=0.0)
    disk = series[12:20, 12:20].mean(axis=(0, 1, 2))
    assert (disk[-1] - disk[0]) / disk.mean() == pytest.approx(0.05, rel=1e-9)


def test_the_pipeline_reads_the_drift_as_its_drift_percent() -> None:
    """A 120 s run detrends with a line, whose peak-to-peak is the whole drift."""
    scan = q.QAScan(
        data=synthetic_series(t=60, drift=0.05, noise=0.0), tr=2.0, pe_axis=1
    )
    m = q.run_qa(scan, q.AnalysisSettings(roi_size=9, trim_sec=0.0)).metrics
    assert m.drift_pct == pytest.approx(5.0, rel=1e-9)


def test_drift_scales_the_signal_and_not_the_noise() -> None:
    """Gains 0.25 and 1.75 leave the air background where it was.

    Scaling the noise too would put the corners' mean ratio near 7. The four
    8-voxel corners give 256 Rayleigh samples a frame, so each mean has a
    relative standard error near 3% and 15% is about 3.5 SE of their ratio.
    """
    series = synthetic_series(n=64, z=1, t=2, drift=1.5)[:, :, 0]
    corners = np.concatenate(
        [series[:8, :8], series[:8, -8:], series[-8:, :8], series[-8:, -8:]]
    )
    assert corners[..., 1].mean() / corners[..., 0].mean() == pytest.approx(
        1.0, rel=0.15
    )


@pytest.mark.parametrize("drift", [2.0, -2.0, float("nan")])
def test_a_drift_that_zeroes_the_gain_or_is_not_finite_is_rejected(
    drift: float,
) -> None:
    with pytest.raises(ValueError, match=f"got {drift}"):
        synthetic_series(drift=drift)


def test_the_background_is_rayleigh_at_the_noise_sigma() -> None:
    """The air's mean magnitude is NOISE_SIGMA·√(π/2), the Rayleigh mean.

    In the 8-voxel corners of a 64-voxel series the disk's Gibbs ringing stays
    under 0.31, which raises the Rice mean by under (0.31/5)²/4 ≈ 0.1%. Their
    4·64·3·40 samples put the standard error of the mean near 0.3%, so 2% is
    about 6 SE.
    """
    series = synthetic_series(n=64, z=3, t=40)
    corners = np.concatenate(
        [series[:8, :8], series[:8, -8:], series[-8:, :8], series[-8:, -8:]]
    )
    expected = NOISE_SIGMA * np.sqrt(np.pi / 2)
    assert corners.mean() == pytest.approx(expected, rel=0.02)
