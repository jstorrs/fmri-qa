"""Temporal detrending: Legendre-polynomial and least-squares B-spline fits.

Both remove low-frequency drift along the time axis before the noise metrics are
measured. The fit complexity (poly degree / spline knots) is derived once from
the run length and TR; `detrend_fn` packages a chosen method as a reusable
`f(y) -> residuals` operator plus its order.
"""

from collections.abc import Callable
from typing import assert_never

import numpy as np
from scipy.interpolate import make_lsq_spline

from ..exceptions import InvalidChoiceError, InvalidScanError
from ..types import DETREND_METHODS, DetrendMethod, FloatArray

# Detrend cutoff period (s). Drift slower than this is removed before noise is
# measured. `poly` and `spline` historically used 200 vs 256; kept distinct
# because only `poly` feeds the settled pipeline.
POLY_CUTOFF_S = 200.0
SPLINE_CUTOFF_S = 256.0

# B-spline degree of the `spline` detrender. Named because the fit's coefficient
# count -- `n_nodes + SPLINE_DEGREE + 1`, what `detrend_fn` weighs against the
# frame count -- depends on it.
SPLINE_DEGREE = 2


def spline_nodes(y: FloatArray, tr: float, cutoff_s: float = SPLINE_CUTOFF_S) -> int:
    """Recommended number of interior knots: one spline segment per `cutoff_s`.

    The spline analogue of `poly_degree` — the fit-complexity knob for
    `spline_residuals`, separated so it can be computed once from the header.
    """
    nt = y.shape[-1]
    return int(max(round(nt * tr / cutoff_s) - 1, 0))


def spline_residuals(
    y: FloatArray,
    n_nodes: int,
    degree: int = SPLINE_DEGREE,
) -> FloatArray:
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
    return np.asarray((signals - fitted).T.reshape(y.shape), dtype=np.float64)


def poly_degree(y: FloatArray, tr: float, cutoff_s: float = POLY_CUTOFF_S) -> int:
    n = y.shape[-1]
    return int(np.round(n * tr / cutoff_s))


def poly_residuals(y: FloatArray, degree: int) -> FloatArray:
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
    center_slice: FloatArray, tr: float, method: DetrendMethod = "poly"
) -> tuple[Callable[[FloatArray], FloatArray], int]:
    """Build a detrender `f(y) -> residuals` and its fit order for `method`.

    Complexity (poly degree / spline nodes) is derived once from the timeseries
    length and `tr`, then applied to the full slice and each ROI timeseries. The
    returned order is that complexity, surfaced for the report.

    The order comes from the run *duration*, so a TR in the wrong unit inflates
    it without bound: a header carrying milliseconds makes the fit as many
    coefficients as there are frames, `lstsq` obliges by fitting the noise as
    well as the drift, and every stability metric downstream is then measured on
    a residual of nothing. Refuse the fit rather than return zeros that look
    like a very stable scanner.

    Raises:
        InvalidChoiceError: If `method` is not one of `DETREND_METHODS`.
        InvalidScanError: If the fit has at least as many coefficients as frames,
            leaving no residual degrees of freedom for noise estimation.
    """
    # Guarded up front so an untyped caller still gets the named error, then
    # matched exhaustively: `assert_never` is unreachable for a `DetrendMethod`,
    # so adding a method to that Literal makes this a type error rather than a
    # silent fall-through at runtime.
    if method not in DETREND_METHODS:
        raise InvalidChoiceError("detrend method", method, DETREND_METHODS)
    match method:
        case "poly":
            return _poly_detrender(center_slice, tr)
        case "spline":
            return _spline_detrender(center_slice, tr)
        case _:
            assert_never(method)


def _poly_detrender(
    center_slice: FloatArray, tr: float
) -> tuple[Callable[[FloatArray], FloatArray], int]:
    """The Legendre detrender for this series length, and its degree."""
    n_frames = center_slice.shape[-1]
    degree = poly_degree(center_slice, tr)
    if degree + 1 >= n_frames:
        raise InvalidScanError(
            "detrend order",
            degree,
            f"a Legendre fit of degree {degree} leaves no residual degrees "
            f"of freedom in the {n_frames} analyzed frames, so it would "
            f"absorb the signal it is meant to detrend; the order follows "
            f"from the run duration, so check that the TR of {tr:g} is in "
            f"seconds",
        )
    return (lambda y: poly_residuals(y, degree)), degree


def _spline_detrender(
    center_slice: FloatArray, tr: float
) -> tuple[Callable[[FloatArray], FloatArray], int]:
    """The B-spline detrender for this series length, and its interior-knot count."""
    n_frames = center_slice.shape[-1]
    n_nodes = spline_nodes(center_slice, tr)
    n_coefficients = n_nodes + SPLINE_DEGREE + 1
    if n_coefficients >= n_frames:
        raise InvalidScanError(
            "detrend order",
            n_nodes,
            f"{n_nodes} interior knots make {n_coefficients} spline "
            f"coefficients, leaving no residual degrees of freedom in the "
            f"{n_frames} analyzed frames; the knot count follows from the "
            f"run duration, so "
            f"check that the TR of {tr:g} is in seconds",
        )
    return (lambda y: spline_residuals(y, n_nodes)), n_nodes
