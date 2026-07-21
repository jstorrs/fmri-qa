"""Detrending removes the low-frequency trend it is meant to and keeps the rest."""

import numpy as np
from hypothesis import given
from hypothesis import strategies as st

from fmriqc.prep.detrend import detrend_fn, poly_residuals, spline_residuals
from fmriqc.prep.imaging import trim_count


def test_poly_residuals_removes_constant() -> None:
    y = np.full(50, 7.0)
    assert np.allclose(poly_residuals(y, 1), 0.0, atol=1e-9)


def test_poly_residuals_removes_linear_trend() -> None:
    t = np.linspace(-1.0, 1.0, 50)
    y = 3.0 + 2.0 * t
    assert np.allclose(poly_residuals(y, 1), 0.0, atol=1e-8)


def test_poly_residuals_leaves_high_frequency_signal() -> None:
    t = np.linspace(-1.0, 1.0, 200)
    y = np.sin(25.0 * t)  # oscillates faster than a degree-2 fit can follow
    assert np.std(poly_residuals(y, 2)) > 0.5


def test_poly_residuals_preserves_shape_nd() -> None:
    y = np.random.default_rng(0).normal(size=(4, 5, 30))
    assert poly_residuals(y, 3).shape == y.shape


def test_spline_residuals_removes_constant() -> None:
    y = np.full(60, -4.0)
    assert np.allclose(spline_residuals(y, 2), 0.0, atol=1e-6)


def test_detrend_fn_returns_operator_and_order() -> None:
    cs = np.random.default_rng(0).normal(size=(4, 4, 80))
    op, order = detrend_fn(cs, tr=2.0, method="poly")
    assert order >= 0
    assert op(cs).shape == cs.shape


@given(
    a=st.floats(-100, 100, allow_nan=False, allow_infinity=False),
    b=st.floats(-100, 100, allow_nan=False, allow_infinity=False),
)
def test_poly_degree1_removes_any_affine_trend(a: float, b: float) -> None:
    t = np.linspace(-1.0, 1.0, 64)
    y = a + b * t
    scale = 1.0 + abs(a) + abs(b)
    assert np.max(np.abs(poly_residuals(y, 1))) < 1e-8 * scale


@given(
    tr=st.floats(0.1, 5.0, allow_nan=False),
    trim_sec=st.floats(0.0, 60.0, allow_nan=False),
)
def test_trim_count_is_nonnegative_rounded_ratio(tr: float, trim_sec: float) -> None:
    assert trim_count(tr, trim_sec) == max(round(trim_sec / tr), 0)
