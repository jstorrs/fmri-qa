"""In-plane phantom registration (estimate_motion).

Checks the estimator on a static series (no hallucinated motion) and on a series
with one deliberately shifted frame (the recovered translation magnitude matches
the injected shift, and that frame is flagged as the worst).
"""

import numpy as np
from scipy.ndimage import shift as ndi_shift

from fmriqc.metrics.motion import estimate_motion


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
    # frame 10 is the only moved volume, so it is the worst and its recovered
    # translation magnitude matches the injected shift (to interpolation error).
    assert int(np.argmax(np.hypot(res.params[:, 0], res.params[:, 1]))) == 10
    assert np.isclose(res.max_translation, np.hypot(dr, dc), atol=0.1)
    static = np.delete(np.hypot(res.params[:, 0], res.params[:, 1]), 10)
    assert static.max() < 0.05  # every other frame stays put
