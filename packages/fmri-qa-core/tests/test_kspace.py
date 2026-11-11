"""The analytic k-space kernel reproduces known transforms and noise levels."""

import numpy as np
import numpy.typing as npt
import pytest
from scipy.special import j0

from fmriqa.testing import kspace
from fmriqa.testing.kspace import Component, Disk, Grid, Rect, Sensitivity

_Float = npt.NDArray[np.float64]

_GRID = Grid(matrix=(128, 128), pixel_mm=(1.0, 1.0))


def _at(
    shape: kspace.Shape, ky: list[float], kx: list[float]
) -> npt.NDArray[np.complex128]:
    return kspace.spectrum(shape, np.array(ky), np.array(kx))


def _box_integral(center: float, half: float, k: float) -> complex:
    """Integrate exp(-2πi k y) over the box numerically (trapezoid)."""
    y = np.linspace(center - half, center + half, 400_001)
    return complex(np.trapezoid(np.exp(-2j * np.pi * k * y), y))


@pytest.mark.parametrize("center", [(0.0, 0.0), (7.0, -4.0)])
def test_disk_dc_is_its_area(center: tuple[float, float]) -> None:
    f = _at(Disk(center, 12.5), [0.0], [0.0])
    assert abs(f[0, 0]) == pytest.approx(np.pi * 12.5**2, rel=1e-12)


@pytest.mark.parametrize("center", [(0.0, 0.0), (7.0, -4.0)])
def test_rect_dc_is_its_area(center: tuple[float, float]) -> None:
    f = _at(Rect(center, (3.0, 5.0)), [0.0], [0.0])
    assert abs(f[0, 0]) == pytest.approx(4 * 3.0 * 5.0, rel=1e-12)


def test_disk_dc_has_no_nan() -> None:
    ky, kx = _GRID.k()
    with np.errstate(all="raise"):
        f = kspace.spectrum(Disk((0.0, 0.0), 10.0), ky, kx)
    assert np.isfinite(f).all()


def test_rect_spectrum_matches_numeric_integral() -> None:
    shape = Rect((2.0, -3.0), (4.0, 6.0))
    ky, kx = [0.013, 0.071], [0.02, 0.055]
    f = _at(shape, ky, kx)
    for i, y in enumerate(ky):
        for j, x in enumerate(kx):
            expected = _box_integral(2.0, 4.0, y) * _box_integral(-3.0, 6.0, x)
            assert f[i, j] == pytest.approx(expected, rel=1e-6)


def test_disk_spectrum_matches_radial_integral() -> None:
    radius = 9.0
    r: _Float = np.linspace(0.0, radius, 200_001)
    ks = [0.01, 0.045, 0.08]
    f = _at(Disk((0.0, 0.0), radius), [0.0], ks)
    for j, k in enumerate(ks):
        expected = 2 * np.pi * np.trapezoid(j0(2 * np.pi * k * r) * r, r)
        assert f[0, j].real == pytest.approx(expected, rel=1e-6)


def test_shift_multiplies_the_spectrum_by_a_phase_ramp() -> None:
    ky, kx = _GRID.k()
    centered = kspace.spectrum(Disk((0.0, 0.0), 10.0), ky, kx)
    shifted = kspace.spectrum(Disk((5.0, -8.0), 10.0), ky, kx)
    ramp = np.exp(-2j * np.pi * (ky[:, None] * 5.0 + kx[None, :] * -8.0))
    np.testing.assert_allclose(shifted, centered * ramp, atol=1e-9)


def _crossings(profile: _Float, positions: _Float, level: float) -> tuple[float, float]:
    """Return the first rising and last falling `level` crossings, in mm."""

    def at(i: int) -> float:
        frac = (level - profile[i - 1]) / (profile[i] - profile[i - 1])
        return float(positions[i - 1] + frac * (positions[i] - positions[i - 1]))

    above = profile >= level
    rising = int(np.argmax(above & ~np.roll(above, 1)))
    falling = len(above) - 1 - int(np.argmax((above & ~np.roll(above, -1))[::-1]))
    return at(rising), at(falling + 1)


@pytest.mark.parametrize(
    "grid",
    [
        Grid((128, 128), (1.0, 1.0)),
        Grid((127, 129), (0.7, 1.3)),
        Grid((65, 64), (0.5, 0.8)),
        Grid((64, 65), (0.8, 0.5)),
    ],
    ids=["square", "odd anisotropic", "wide pixel", "tall pixel"],
)
def test_reconstructed_rect_edges_sit_at_their_positions(grid: Grid) -> None:
    center, half = (6.3, -4.1), (5.0, 8.0)
    ky, kx = grid.k()
    k = kspace.object_spectrum([Component(Rect(center, half), 1.0)], ky, kx)
    image = kspace.reconstruct(k, grid).real
    y, x = grid.positions_mm()
    dy, dx = grid.pixel_mm
    profiles = (
        (image.sum(axis=1) * dx / (2 * half[1]), y, center[0], half[0], dy),
        (image.sum(axis=0) * dy / (2 * half[0]), x, center[1], half[1], dx),
    )
    for profile, positions, c, h, pixel in profiles:
        first, last = _crossings(profile, positions, 0.5)
        assert first == pytest.approx(c - h, abs=0.1 * pixel)
        assert last == pytest.approx(c + h, abs=0.1 * pixel)


def _half_max_diameter(profile: _Float, pixel_mm: float, level: float) -> float:
    """Return the distance between the outer half-max crossings, in mm."""
    first, last = _crossings(profile, np.arange(len(profile)) * pixel_mm, level)
    return last - first


def test_reconstructed_disk_has_its_diameter_and_level() -> None:
    radius, delta = 24.0, 2.0
    grid = Grid((128, 128), (0.5, 0.8))
    ky, kx = grid.k()
    k = kspace.object_spectrum([Component(Disk((0.0, 0.0), radius), delta)], ky, kx)
    image = np.abs(kspace.reconstruct(k, grid))
    dy, dx = grid.pixel_mm
    assert _half_max_diameter(image[64], dx, delta / 2) == pytest.approx(
        2 * radius, abs=0.05 * dx
    )
    assert _half_max_diameter(image[:, 64], dy, delta / 2) == pytest.approx(
        2 * radius, abs=0.05 * dy
    )
    y, x = grid.positions_mm()
    inside = np.hypot(y[:, None], x[None, :]) < 12.0
    assert image[inside].mean() == pytest.approx(delta, rel=0.01)


def test_noise_has_requested_std_per_component() -> None:
    grid = Grid(matrix=(256, 256), pixel_mm=(0.5, 0.8))
    sigma = 3.0
    image = kspace.reconstruct(
        kspace.kspace_noise(grid, sigma, np.random.default_rng(0)), grid
    )
    assert image.real.std() == pytest.approx(sigma, rel=0.02)
    assert image.imag.std() == pytest.approx(sigma, rel=0.02)


def test_noise_magnitude_is_rayleigh() -> None:
    grid = Grid(matrix=(256, 256), pixel_mm=(0.5, 0.8))
    sigma = 3.0
    image = kspace.reconstruct(
        kspace.kspace_noise(grid, sigma, np.random.default_rng(1)), grid
    )
    assert np.abs(image).mean() == pytest.approx(sigma * np.sqrt(np.pi / 2), rel=0.02)


_BAD = [0.0, -1.0, float("nan"), float("inf")]


@pytest.mark.parametrize(
    "matrix", [(0, 8), (8, -1)], ids=["zero rows", "negative columns"]
)
def test_grid_rejects_non_positive_matrix(matrix: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="matrix"):
        Grid(matrix=matrix, pixel_mm=(1.0, 1.0))


@pytest.mark.parametrize("bad", _BAD)
def test_grid_rejects_bad_pixel(bad: float) -> None:
    with pytest.raises(ValueError, match="pixel_mm"):
        Grid(matrix=(8, 8), pixel_mm=(1.0, bad))


@pytest.mark.parametrize("bad", _BAD)
def test_disk_rejects_bad_radius(bad: float) -> None:
    with pytest.raises(ValueError, match="radius_mm"):
        Disk((0.0, 0.0), bad)


@pytest.mark.parametrize("bad", [*_BAD[1:], 0.0])
def test_rect_rejects_bad_half_width(bad: float) -> None:
    with pytest.raises(ValueError, match="half_mm"):
        Rect((0.0, 0.0), (1.0, bad))


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_shapes_reject_non_finite_center(bad: float) -> None:
    with pytest.raises(ValueError, match="center_mm"):
        Disk((bad, 0.0), 1.0)
    with pytest.raises(ValueError, match="center_mm"):
        Rect((0.0, bad), (1.0, 1.0))


def test_opposite_deltas_cancel() -> None:
    ky, kx = _GRID.k()
    disk = Disk((4.0, 1.0), 10.0)
    k = kspace.object_spectrum([Component(disk, 1.0), Component(disk, -1.0)], ky, kx)
    assert np.abs(k).max() < 1e-9


def test_equal_radius_grouping_matches_summing_individual_spectra() -> None:
    ky, kx = _GRID.k()
    components = [
        Component(Disk((5.0, -3.0), 2.0), 1.0),
        Component(Disk((-7.0, 9.0), 2.0), -0.5),
        Component(Disk((1.0, 1.0), 4.0), 2.0),
        Component(Rect((0.0, 6.0), (3.0, 2.0)), 0.7),
    ]
    expected = sum(c.delta * kspace.spectrum(c.shape, ky, kx) for c in components)
    np.testing.assert_allclose(
        kspace.object_spectrum(components, ky, kx), expected, rtol=1e-12, atol=1e-12
    )


_SENS_GRID = Grid(matrix=(33, 41), pixel_mm=(6.0, 5.0))
_COEFFICIENTS = np.array(
    [
        [0.1 + 0.2j, -0.3j, 0.05, 0.2 - 0.1j, 0.0],
        [0.15, 1.0 + 0.1j, 0.3 - 0.2j, -0.1, 0.08j],
        [-0.2j, 0.12, -0.07 + 0.04j, 0.0, 0.1],
    ],
    dtype=np.complex128,
)


def _sensitivity(coefficients: npt.NDArray[np.complex128]) -> Sensitivity:
    return Sensitivity(_SENS_GRID, coefficients)


_MEASURE_GRIDS = [
    pytest.param(Grid((33, 41), (6.0, 5.0)), id="odd"),
    pytest.param(Grid((32, 40), (6.0, 5.0)), id="even"),
    pytest.param(Grid((32, 41), (6.0, 5.0)), id="even rows, odd columns"),
]


@pytest.mark.parametrize("grid", _MEASURE_GRIDS)
def test_measure_matches_the_naive_modulation_sum(grid: Grid) -> None:
    components = [
        Component(Disk((20.0, -30.0), 25.0), 1.0),
        Component(Rect((-35.0, 25.0), (18.0, 30.0)), 0.6),
    ]
    sens = Sensitivity(grid, _COEFFICIENTS)
    ky, kx = grid.k()
    fov_y, fov_x = grid.fov_mm
    expected = np.zeros(grid.matrix, dtype=np.complex128)
    for (ia, ib), weight in np.ndenumerate(_COEFFICIENTS):
        vy, vx = (ia - 1) / (2 * fov_y), (ib - 2) / (2 * fov_x)
        expected += weight * kspace.object_spectrum(components, ky - vy, kx - vx)
    np.testing.assert_allclose(
        kspace.measure(components, sens), expected, rtol=1e-10, atol=1e-10
    )


@pytest.mark.parametrize("grid", _MEASURE_GRIDS)
def test_measure_with_uniform_sensitivity_is_the_object_spectrum(grid: Grid) -> None:
    components = [Component(Disk((20.0, -30.0), 25.0), 1.0)]
    ky, kx = grid.k()
    np.testing.assert_allclose(
        kspace.measure(components, Sensitivity.uniform(grid)),
        kspace.object_spectrum(components, ky, kx),
        rtol=1e-12,
        atol=1e-12,
    )


def test_measured_image_is_the_object_times_the_sensitivity() -> None:
    grid = Grid(matrix=(99, 121), pixel_mm=(2.0, 1.7))
    obj = [Component(Disk((20.0, -25.0), 60.0), 2.0)]
    sens = Sensitivity(grid, _COEFFICIENTS)
    image = kspace.reconstruct(kspace.measure(obj, sens), grid)
    # The unweighted image carries the same Gibbs ringing, so scaling it by the
    # truth map cancels the ringing and leaves only the modulation to compare.
    plain = kspace.reconstruct(kspace.measure(obj, Sensitivity.uniform(grid)), grid)
    y, x = grid.positions_mm()
    expected = sens.evaluate(y, x) * plain
    inside = np.hypot(y[:, None] - 20.0, x[None, :] + 25.0) < 60.0 - 30.0
    assert inside.sum() > 500
    error = np.abs(image[inside] - expected[inside]).max()
    assert error < 0.01 * np.abs(expected[inside]).max()


def test_evaluate_sums_the_sinusoids_at_a_point() -> None:
    sens = _sensitivity(_COEFFICIENTS)
    y, x = 17.0, -23.0
    fov_y, fov_x = _SENS_GRID.fov_mm
    expected = sum(
        weight
        * np.exp(2j * np.pi * ((ia - 1) * y / (2 * fov_y) + (ib - 2) * x / (2 * fov_x)))
        for (ia, ib), weight in np.ndenumerate(_COEFFICIENTS)
    )
    got = sens.evaluate(np.array([y]), np.array([x]))
    assert got.shape == (1, 1)
    assert got[0, 0] == pytest.approx(complex(expected), rel=1e-12)


def test_product_matches_the_pointwise_product_of_maps() -> None:
    other = np.array(
        [[0.5, 0.2j, -0.1], [0.0, 1.0 - 0.3j, 0.25], [0.1 + 0.1j, -0.4, 0.0]],
        dtype=np.complex128,
    )
    a, b = _sensitivity(_COEFFICIENTS), _sensitivity(other)
    y, x = _SENS_GRID.positions_mm()
    product = a.product(b)
    assert product.coefficients.shape == (5, 7)
    np.testing.assert_allclose(
        product.evaluate(y, x), a.evaluate(y, x) * b.evaluate(y, x), rtol=1e-12
    )


def test_product_with_uniform_is_identity() -> None:
    a = _sensitivity(_COEFFICIENTS)
    product = a.product(Sensitivity.uniform(_SENS_GRID))
    np.testing.assert_array_equal(product.coefficients, _COEFFICIENTS)


def test_product_rejects_different_grids() -> None:
    other = Sensitivity.uniform(Grid((33, 41), (6.0, 5.5)))
    with pytest.raises(ValueError, match="grids differ"):
        _sensitivity(_COEFFICIENTS).product(other)


def test_sensitivity_copies_and_freezes_its_coefficients() -> None:
    source = _COEFFICIENTS.copy()
    sens = _sensitivity(source)
    source[0, 0] = 99.0
    assert sens.coefficients[0, 0] == _COEFFICIENTS[0, 0]
    assert not sens.coefficients.flags.writeable


@pytest.mark.parametrize("shape", [(2, 3), (3, 2)])
def test_sensitivity_rejects_even_size(shape: tuple[int, int]) -> None:
    with pytest.raises(ValueError, match="odd"):
        _sensitivity(np.ones(shape, dtype=np.complex128))


def test_sensitivity_rejects_non_finite_entry() -> None:
    bad = _COEFFICIENTS.copy()
    bad[1, 1] = complex("nan")
    with pytest.raises(ValueError, match="finite"):
        _sensitivity(bad)


def test_sensitivity_rejects_non_2d_array() -> None:
    with pytest.raises(ValueError, match="2-D"):
        _sensitivity(np.ones(3, dtype=np.complex128))
