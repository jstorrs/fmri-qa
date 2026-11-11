"""Sample the exact Fourier transform of simple shapes, to build k-space phantoms.

An object is a sum of `Component` shapes (disks and axis-aligned rectangles),
each adding a signal `delta` inside its outline. The Fourier transform of every
shape is known in closed form, so `object_spectrum` evaluates the object's
k-space directly on a Cartesian grid, after Guerquin-Kern et al. [1]_.

Why sample analytically: Cartesian sampling of the exact transform followed by
an inverse DFT gives samples of the band-limited object, periodized over the
field of view. Edges and Gibbs
ringing are therefore those a scanner produces, and the image was never drawn
at the resolution it is reconstructed at (no "inverse crime"). The Gibbs tails
wrap periodically across the field of view, as they do on a scanner.

Notes
-----
All lengths are in mm and spatial frequencies in cycles/mm. The continuous
Fourier transform is ``F(k) = ∫ f(r) exp(-2πi k·r) dr``. Array axes are
(y, x), that is (row, column). In both image and k-space the sample at index
``n // 2`` is the origin, so for even ``n`` the most negative sample is kept.

References
----------
.. [1] M. Guerquin-Kern, L. Lejeune, K. P. Pruessmann, M. Unser, "Realistic
   Analytical Phantoms for Parallel Magnetic Resonance Imaging," IEEE Trans.
   Med. Imaging 31(3):626-636, 2012. doi:10.1109/TMI.2011.2174158
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import assert_never

import numpy as np
import numpy.typing as npt
from scipy.special import j1

__all__ = [
    "Component",
    "Disk",
    "Grid",
    "Rect",
    "Sensitivity",
    "Shape",
    "kspace_noise",
    "measure",
    "object_spectrum",
    "reconstruct",
    "spectrum",
]

_Float = npt.NDArray[np.float64]
_Complex = npt.NDArray[np.complex128]


@dataclass(frozen=True, slots=True)
class Grid:
    """A Cartesian sampling grid of the field of view.

    Parameters
    ----------
    matrix : tuple of int
        Samples along (y, x). Positive.
    pixel_mm : tuple of float
        Pixel size along (y, x), in mm. Finite and positive.

    Raises
    ------
    ValueError
        If the matrix is not positive or a pixel size is not finite and positive.
    """

    matrix: tuple[int, int]
    pixel_mm: tuple[float, float]

    def __post_init__(self) -> None:
        """Reject a non-positive matrix or a non-finite or non-positive pixel."""
        if min(self.matrix) <= 0:
            raise ValueError(f"matrix must be positive, got {self.matrix}")
        if not _positive(*self.pixel_mm):
            raise ValueError(
                f"pixel_mm must be finite and positive, got {self.pixel_mm}"
            )

    @property
    def fov_mm(self) -> tuple[float, float]:
        """The field of view along (y, x), in mm."""
        return (
            self.matrix[0] * self.pixel_mm[0],
            self.matrix[1] * self.pixel_mm[1],
        )

    def k(self) -> tuple[_Float, _Float]:
        """Return the k-space sample positions (ky, kx), in cycles/mm."""
        fov_y, fov_x = self.fov_mm
        ny, nx = self.matrix
        ky = (np.arange(ny, dtype=np.float64) - ny // 2) / fov_y
        kx = (np.arange(nx, dtype=np.float64) - nx // 2) / fov_x
        return ky, kx

    def positions_mm(self) -> tuple[_Float, _Float]:
        """Return the image sample positions (y, x), in mm."""
        ny, nx = self.matrix
        dy, dx = self.pixel_mm
        y = (np.arange(ny, dtype=np.float64) - ny // 2) * dy
        x = (np.arange(nx, dtype=np.float64) - nx // 2) * dx
        return y, x


@dataclass(frozen=True, slots=True)
class Disk:
    """A disk.

    Parameters
    ----------
    center_mm : tuple of float
        Center (y, x), in mm.
    radius_mm : float
        Radius, in mm. Finite and positive.

    Raises
    ------
    ValueError
        If the radius is not finite and positive or the center is not finite.
    """

    center_mm: tuple[float, float]
    radius_mm: float

    def __post_init__(self) -> None:
        """Reject a bad radius or center."""
        if not (_positive(self.radius_mm) and math.isfinite(sum(self.center_mm))):
            raise ValueError(
                f"radius_mm must be finite and positive and center_mm finite, "
                f"got {self.radius_mm} and {self.center_mm}"
            )


@dataclass(frozen=True, slots=True)
class Rect:
    """An axis-aligned rectangle.

    Parameters
    ----------
    center_mm : tuple of float
        Center (y, x), in mm.
    half_mm : tuple of float
        Half-widths (y, x), in mm. Finite and positive.

    Raises
    ------
    ValueError
        If a half-width is not finite and positive or the center is not finite.
    """

    center_mm: tuple[float, float]
    half_mm: tuple[float, float]

    def __post_init__(self) -> None:
        """Reject a bad half-width or center."""
        if not (_positive(*self.half_mm) and math.isfinite(sum(self.center_mm))):
            raise ValueError(
                f"half_mm must be finite and positive and center_mm finite, "
                f"got {self.half_mm} and {self.center_mm}"
            )


Shape = Disk | Rect


@dataclass(frozen=True, slots=True)
class Component:
    """Signal `delta` added inside `shape`; an object is a sum of these.

    Parameters
    ----------
    shape : Disk or Rect
        The outline.
    delta : float
        Signal added inside the outline. Negative for an insert.
    """

    shape: Shape
    delta: float


@dataclass(frozen=True, slots=True, eq=False)
class Sensitivity:
    r"""A smooth complex receive sensitivity, as a sum of low-frequency sinusoids.

    .. math::

        S(y, x) = \sum_{a=-h_y}^{h_y} \sum_{b=-h_x}^{h_x}
        s_{a+h_y,\,b+h_x}\,
        \exp\left[2\pi i \left(\frac{a\,y}{2\,\mathrm{FOV}_y}
        + \frac{b\,x}{2\,\mathrm{FOV}_x}\right)\right],
        \quad h = (L - 1) / 2.

    The sinusoids lie on a frequency grid of spacing ``1/(2·FOV)``, and index
    ``h`` of each axis is the zero frequency.

    Parameters
    ----------
    grid : Grid
        The sampling grid; its field of view sets the frequency spacing.
    coefficients : (Ly, Lx) ndarray of complex128
        The weights ``s``, dimensionless. Both sizes odd; all entries finite.
        Copied and made read-only.

    Raises
    ------
    ValueError
        If `coefficients` is not 2-D, a size is not odd, or an entry is not
        finite.

    Notes
    -----
    This is the sinusoidal sensitivity model of Guerquin-Kern et al. [1]_,
    eq. 7 and Fig. 2. Multiplying an object by it shifts its spectrum by the
    sinusoid frequencies (eq. 8), which `measure` uses to stay exact.
    """

    grid: Grid
    coefficients: _Complex

    def __post_init__(self) -> None:
        """Copy the coefficients and reject a bad shape or non-finite entry."""
        values = np.array(self.coefficients, dtype=np.complex128)
        if values.ndim != 2:
            raise ValueError(
                f"coefficients must be 2-D, got {values.ndim}-D shape {values.shape}"
            )
        if (
            min(values.shape) == 0
            or values.shape[0] % 2 == 0
            or values.shape[1] % 2 == 0
        ):
            raise ValueError(
                f"coefficients sizes must be odd and positive, got {values.shape}"
            )
        if not np.isfinite(values).all():
            raise ValueError("coefficients must be finite, got a nan or inf entry")
        values.flags.writeable = False
        object.__setattr__(self, "coefficients", values)

    @classmethod
    def uniform(cls, grid: Grid) -> "Sensitivity":
        """Return the unit sensitivity, S = 1 everywhere."""
        return cls(grid, np.ones((1, 1), dtype=np.complex128))

    @property
    def half(self) -> tuple[int, int]:
        """The highest harmonic index along (y, x), ``h = (L - 1) / 2``."""
        ly, lx = self.coefficients.shape
        return (ly - 1) // 2, (lx - 1) // 2

    def evaluate(self, y_mm: _Float, x_mm: _Float) -> _Complex:
        """Return the sensitivity on the outer grid of two position vectors.

        Parameters
        ----------
        y_mm, x_mm : (Ny,), (Nx,) ndarray of float64
            Positions, in mm.

        Returns
        -------
        (Ny, Nx) ndarray of complex128
            Dimensionless.
        """
        hy, hx = self.half
        fov_y, fov_x = self.grid.fov_mm
        ey = np.exp(2j * np.pi * np.outer(y_mm, np.arange(-hy, hy + 1)) / (2 * fov_y))
        ex = np.exp(2j * np.pi * np.outer(x_mm, np.arange(-hx, hx + 1)) / (2 * fov_x))
        return np.asarray(ey @ self.coefficients @ ex.T, dtype=np.complex128)

    def product(self, other: "Sensitivity") -> "Sensitivity":
        """Return the exact pointwise product with another sensitivity.

        Multiplication of sinusoid sums is convolution of their coefficients.

        Parameters
        ----------
        other : Sensitivity
            On the same grid.

        Returns
        -------
        Sensitivity
            With ``La + Lb - 1`` coefficients along each axis.

        Raises
        ------
        ValueError
            If the grids differ.
        """
        if self.grid != other.grid:
            raise ValueError(f"grids differ: {self.grid} and {other.grid}")
        ly, lx = other.coefficients.shape
        out = np.zeros(
            (
                self.coefficients.shape[0] + ly - 1,
                self.coefficients.shape[1] + lx - 1,
            ),
            dtype=np.complex128,
        )
        for (i, j), weight in np.ndenumerate(self.coefficients):
            out[i : i + ly, j : j + lx] += weight * other.coefficients
        return Sensitivity(self.grid, out)


def _positive(*values: float) -> bool:
    """Return whether every value is finite and greater than zero."""
    return all(math.isfinite(v) and v > 0 for v in values)


def _ramp(k: _Float, center_mm: float) -> _Complex:
    """Return the phase ramp exp(-2πi k c) of a shift along one axis."""
    return np.exp(-2j * np.pi * k * center_mm)


def _jinc(radius_mm: float, ky: _Float, kx: _Float) -> _Float:
    """Return the transform of a centered disk, R·J1(2πR|k|)/|k|, on the grid."""
    arg = 2 * np.pi * radius_mm * np.hypot(ky[:, None], kx[None, :])
    # J1(x)/x tends to 1/2 at x = 0, where the transform is πR².
    ratio = np.divide(j1(arg), arg, out=np.full_like(arg, 0.5), where=arg > 0)
    return 2 * np.pi * radius_mm**2 * ratio


def _centered(shape: Shape, ky: _Float, kx: _Float) -> _Float:
    """Return the transform of `shape` moved to the origin, on the grid."""
    match shape:
        case Disk(radius_mm=radius):
            return _jinc(radius, ky, kx)
        case Rect(half_mm=(a, b)):
            return np.outer(2 * a * np.sinc(2 * a * ky), 2 * b * np.sinc(2 * b * kx))
        case _:
            assert_never(shape)


def spectrum(shape: Shape, ky: _Float, kx: _Float) -> _Complex:
    """Return the Fourier transform of a unit-signal shape on a k-space grid.

    Parameters
    ----------
    shape : Disk or Rect
        The outline.
    ky, kx : (Ny,), (Nx,) ndarray of float64
        Sample positions, in cycles/mm.

    Returns
    -------
    (Ny, Nx) ndarray of complex128
        In mm².
    """
    cy, cx = shape.center_mm
    return _centered(shape, ky, kx) * np.outer(_ramp(ky, cy), _ramp(kx, cx))


def object_spectrum(
    components: Sequence[Component], ky: _Float, kx: _Float
) -> _Complex:
    """Return the Fourier transform of an object on a k-space grid.

    Disks of equal radius share one radial evaluation, and their separable
    phase ramps are summed as a matrix product, so a few hundred small disks
    cost little more than one.

    Parameters
    ----------
    components : sequence of Component
        The shapes and the signal each adds.
    ky, kx : (Ny,), (Nx,) ndarray of float64
        Sample positions, in cycles/mm.

    Returns
    -------
    (Ny, Nx) ndarray of complex128
        In the units of `delta` times mm².
    """
    total = np.zeros((len(ky), len(kx)), dtype=np.complex128)
    by_radius: dict[float, list[tuple[tuple[float, float], float]]] = {}
    for c in components:
        match c.shape:
            case Disk(center_mm=center, radius_mm=radius):
                by_radius.setdefault(radius, []).append((center, c.delta))
            case Rect():
                total += c.delta * spectrum(c.shape, ky, kx)
            case _:
                assert_never(c.shape)
    for radius, members in by_radius.items():
        ey = np.array([_ramp(ky, cy) for (cy, _), _ in members])
        ex = np.array([_ramp(kx, cx) for (_, cx), _ in members])
        delta = np.array([d for _, d in members])
        total += _jinc(radius, ky, kx) * ((ey.T * delta) @ ex)
    return total


def reconstruct(kspace: _Complex, grid: Grid) -> _Complex:
    """Reconstruct a complex image from centered k-space.

    The scaling makes a noise-free result approximate the continuous image at
    the sample positions of `Grid.positions_mm`.

    Parameters
    ----------
    kspace : (Ny, Nx) ndarray of complex128
        K-space sampled at `Grid.k`, in image units times mm².
    grid : Grid
        The sampling grid.

    Returns
    -------
    (Ny, Nx) ndarray of complex128
        Image, in the units of `kspace` per mm². Take the magnitude for display.
    """
    dy, dx = grid.pixel_mm
    image = np.fft.fftshift(np.fft.ifft2(np.fft.ifftshift(kspace)))
    return np.asarray(image / (dy * dx), dtype=np.complex128)


def kspace_noise(grid: Grid, sigma: float, rng: np.random.Generator) -> _Complex:
    """Draw complex white Gaussian k-space noise.

    The std is scaled so that after `reconstruct` the image noise has std
    `sigma` in each of the real and imaginary parts.

    Parameters
    ----------
    grid : Grid
        The sampling grid.
    sigma : float
        Image-space noise std per real or imaginary component, in image units.
    rng : numpy.random.Generator
        Source of randomness.

    Returns
    -------
    (Ny, Nx) ndarray of complex128
        In image units times mm².
    """
    ny, nx = grid.matrix
    dy, dx = grid.pixel_mm
    std = sigma * np.sqrt(ny * nx) * dy * dx
    return rng.normal(0.0, std, grid.matrix) + 1j * rng.normal(0.0, std, grid.matrix)


def measure(components: Sequence[Component], sensitivity: Sensitivity) -> _Complex:
    """Return the k-space of an object weighted by a sensitivity.

    By the modulation theorem, ``FT[S·f](k) = Σ_v s_v F(k - v)``. Every
    ``k - v`` lies on a grid twice as fine as the sampling grid, so the
    object spectrum is evaluated once there and the terms are strided slices.

    Parameters
    ----------
    components : sequence of Component
        The shapes and the signal each adds.
    sensitivity : Sensitivity
        The receive sensitivity; its grid sets the k-space samples.

    Returns
    -------
    (Ny, Nx) ndarray of complex128
        K-space sampled at ``sensitivity.grid.k()``, in the units of `delta`
        times mm².
    """
    grid = sensitivity.grid
    ny, nx = grid.matrix
    hy, hx = sensitivity.half
    fov_y, fov_x = grid.fov_mm
    jy = np.arange(-2 * (ny // 2) - hy, 2 * (ny - 1 - ny // 2) + hy + 1)
    jx = np.arange(-2 * (nx // 2) - hx, 2 * (nx - 1 - nx // 2) + hx + 1)
    fine = object_spectrum(components, jy / (2 * fov_y), jx / (2 * fov_x))
    total = np.zeros((ny, nx), dtype=np.complex128)
    for (ia, ib), weight in np.ndenumerate(sensitivity.coefficients):
        y0, x0 = 2 * hy - ia, 2 * hx - ib
        total += weight * fine[y0 : y0 + 2 * ny - 1 : 2, x0 : x0 + 2 * nx - 1 : 2]
    return total
