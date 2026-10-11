"""In-plane phantom registration (estimate_motion).

Checks the estimator on a static series (no spurious motion) and on a series
with one shifted frame (the recovered translation magnitude matches the
injected shift, and that frame is flagged as the worst).
"""

import numpy as np
import pytest
from scipy.ndimage import affine_transform
from scipy.ndimage import shift as ndi_shift

from fmriqc.metrics.motion import estimate_motion
from fmriqc.prep.scale import VoxelSize


def _blob(n: int = 24) -> np.ndarray:
    """A smooth Gaussian phantom (well-defined gradients for Lucas-Kanade)."""
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    r2 = (xx - n / 2) ** 2 + (yy - n / 2) ** 2
    return np.exp(-r2 / (2.0 * (n / 6.0) ** 2))


def test_estimate_motion_reports_no_motion_for_a_static_series() -> None:
    blob = _blob()
    series = np.repeat(blob[:, :, None], 20, axis=2)
    mask = blob > 0.1

    res = estimate_motion(series, mask)
    assert res.converged.all()
    assert res.max_translation < 1e-3
    assert res.max_scale_pct < 1e-1
    assert res.max_shear_pct < 1e-1


def test_estimate_motion_recovers_a_known_translation() -> None:
    blob = _blob()
    series = np.repeat(blob[:, :, None], 40, axis=2)
    dr, dc = 0.7, -0.4
    series[:, :, 10] = ndi_shift(blob, [dr, dc], order=1, mode="nearest")
    mask = blob > 0.1

    res = estimate_motion(series, mask)
    assert res.converged.all()
    # frame 10 is the only moved volume, so it is the worst and its recovered
    # translation magnitude matches the injected shift (to interpolation error).
    assert int(np.argmax(np.hypot(res.params[:, 0], res.params[:, 1]))) == 10
    assert np.isclose(res.max_translation, np.hypot(dr, dc), atol=0.1)
    static = np.delete(np.hypot(res.params[:, 0], res.params[:, 1]), 10)
    assert static.max() < 0.05  # every other frame stays put


def test_estimate_motion_reports_max_translation_in_mm_when_voxel_size_is_known() -> (
    None
):
    blob = _blob()
    series = np.repeat(blob[:, :, None], 20, axis=2)
    dr, dc = 0.7, -0.4
    series[:, :, 10] = ndi_shift(blob, [dr, dc], order=1, mode="nearest")

    res = estimate_motion(series, blob > 0.1, voxel=VoxelSize((2.0, 2.0)))
    assert res.converged.all()
    assert np.isclose(res.max_translation, 2.0 * np.hypot(dr, dc), atol=0.2)


@pytest.mark.parametrize("strain", [(0.02, -0.01, 0), (0, 0, 0.015)])
def test_motion_recovers_known_scale_and_shear(strain) -> None:
    blob = _blob(48)
    sr, sc, shear = strain
    warp = np.array([[1 + sr, shear], [shear, 1 + sc]])
    inverse = np.linalg.inv(warp)
    center = np.array(blob.shape) / 2
    series = np.repeat(blob[:, :, None], 40, axis=2)
    series[:, :, 10] = affine_transform(
        blob, inverse, offset=center - inverse @ center, order=1, mode="nearest"
    )
    result = estimate_motion(series, blob > 0.1)
    assert result.converged.all()
    # Relative to the temporal mean, with a small interpolation tolerance.
    assert np.allclose(result.params[10, 2:], np.array(strain) * 39 / 40, atol=0.001)


@pytest.mark.parametrize(
    "mask", [np.ones((8, 8), dtype=bool), np.zeros((8, 8), dtype=bool)]
)
def test_unidentifiable_motion_is_undefined(mask) -> None:
    with pytest.warns(UserWarning, match="motion fit failed"):
        result = estimate_motion(np.ones((8, 8, 4)), mask)
    assert not result.converged.any()
    assert np.isnan(result.params).all()
    assert np.isnan(result.max_translation)
    assert np.isnan(result.max_scale_pct)
    assert np.isnan(result.max_shear_pct)


def test_motion_iteration_limit_does_not_publish_a_partial_fit() -> None:
    blob = _blob()
    series = np.repeat(blob[:, :, None], 20, axis=2)
    series[:, :, 10] = ndi_shift(blob, [0.7, -0.4], order=1, mode="nearest")
    with pytest.warns(UserWarning, match="did not converge"):
        result = estimate_motion(series, blob > 0.1, max_iter=1)
    assert not result.converged[10]
    assert np.isnan(result.translation[10]).all()
    assert np.isnan(result.max_translation)
