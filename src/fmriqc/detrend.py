"""Temporal detrending: Legendre-polynomial and least-squares B-spline fits.

Both remove low-frequency drift along the time axis before the noise metrics are
measured. The fit complexity (poly degree / spline knots) is derived once from
the run length and TR; `detrend_fn` packages a chosen method as a reusable
`f(y) -> residuals` operator plus its order.
"""

from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import make_lsq_spline

from .constants import POLY_CUTOFF_S, SPLINE_CUTOFF_S
from .exceptions import InvalidChoiceError

DETREND_METHODS = ("poly", "spline")


def spline_nodes(y: NDArray, tr: float, cutoff_s: float = SPLINE_CUTOFF_S) -> int:
    """Recommended number of interior knots: one spline segment per `cutoff_s`.

    The spline analogue of `poly_degree` — the fit-complexity knob for
    `spline_residuals`, separated so it can be computed once from the header.
    """
    nt = y.shape[-1]
    return max(round(nt * tr / cutoff_s) - 1, 0)


def spline_residuals(
    y: NDArray[np.float64],
    n_nodes: int,
    degree: int = 2,
) -> NDArray[np.float64]:
    """Detrend along the last axis with a least-squares B-spline (handles N-D).

    A drop-in alternative to `poly_residuals`; `n_nodes` (interior knots, from
    `spline_nodes`) sets the fit complexity the way `degree` does for the poly.
    """
    nt = y.shape[-1]
    x = np.arange(nt, dtype=np.float64)

    # interior knots spread evenly over the fitted (steady-state) span
    t = np.concatenate(
        (
            np.full(degree + 1, 0.0),
            np.linspace(0, nt, n_nodes + 2)[1:-1],
            np.full(degree + 1, nt),
        )
    )

    # Treat all leading-index combinations as separate signals: (nt, n_signals).
    signals = y.reshape(-1, nt).T
    fitted = make_lsq_spline(x, signals, t, k=degree)(x)
    return (signals - fitted).T.reshape(y.shape)


def poly_degree(y: NDArray, tr: float, cutoff_s: float = POLY_CUTOFF_S) -> int:
    n = y.shape[-1]
    return int(np.round(n * tr / cutoff_s))


def poly_residuals(y: NDArray, degree: int) -> NDArray:
    """Detrend along the last axis with Legendre polynomials (handles N-D)."""
    nt = y.shape[-1]
    x = np.linspace(-1.0, 1.0, nt, dtype=float)

    # Design matrix: (nt, degree + 1)
    design = np.polynomial.legendre.legvander(x, degree)

    # Treat all leading-index combinations as separate signals.
    signals = y.reshape(-1, nt).T

    # coefficients: (degree + 1, number_of_signals)
    coefficients, *_ = np.linalg.lstsq(design, signals, rcond=None)

    fitted = (design @ coefficients).T
    return y - fitted.reshape(y.shape)


def detrend_fn(
    center_slice: NDArray, tr: float, method: str = "poly"
) -> tuple[Callable[[NDArray], NDArray], int]:
    """Build a detrender `f(y) -> residuals` and its fit order for `method`.

    Complexity (poly degree / spline nodes) is derived once from the timeseries
    length and `tr`, then applied to the full slice and each ROI timeseries. The
    returned order is that complexity, surfaced for the report.

    Raises:
        InvalidChoiceError: If `method` is not one of `DETREND_METHODS`.
    """
    if method == "poly":
        degree = poly_degree(center_slice, tr)
        return (lambda y: poly_residuals(y, degree)), degree
    if method == "spline":
        n_nodes = spline_nodes(center_slice, tr)
        return (lambda y: spline_residuals(y, n_nodes)), n_nodes
    raise InvalidChoiceError("detrend method", method, DETREND_METHODS)
