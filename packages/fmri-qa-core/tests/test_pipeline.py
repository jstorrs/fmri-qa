"""End-to-end pipeline through the public `fmriqc` import surface.

Exercises `run_qa` as a caller sees it, on a synthetic phantom built in code (no
file I/O), so the whole functional core runs deterministically.
"""

import numpy as np

import fmriqc as q

# The synthetic phantom fills half the FOV, so its N/2-rolled ghost region erodes
# to empty and the ghost ratio is NaN -- a correct edge outcome (no real ghost),
# handled by the ghost_ratio/ghost_top_ratio empty-region guards without warnings.


def synthetic_scan(seed: int = 0, n: int = 32, z: int = 3, t: int = 40) -> q.QAScan:
    """A bright central disk with seeded temporal noise — a stand-in phantom run."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:n, 0:n]
    disk = ((xx - n / 2) ** 2 + (yy - n / 2) ** 2) < (n / 4) ** 2
    base = np.where(disk, 1000.0, 0.0)
    noise = rng.normal(scale=5.0, size=(n, n, z, t)) * disk[:, :, None, None]
    data = base[:, :, None, None] + noise
    return q.QAScan(data=data, tr=2.0, pe_axis=1)


def test_run_qa_returns_finite_core_metrics() -> None:
    result = q.run_qa(synthetic_scan(), roi_size=9)
    m = result.metrics
    assert isinstance(result, q.QAResult)
    assert m.snr > 0 and np.isfinite(m.snr)
    assert m.sfnr > 0 and np.isfinite(m.sfnr)
    assert np.isfinite(m.rdc)
    assert m.pe_axis == 1  # the axis we passed through, used for the ghost masks


def test_run_qa_is_deterministic() -> None:
    a = q.run_qa(synthetic_scan(seed=1), roi_size=9).metrics
    b = q.run_qa(synthetic_scan(seed=1), roi_size=9).metrics
    assert a.snr == b.snr
    assert a.sfnr == b.sfnr
    assert a.rdc == b.rdc


def test_preprocess_discards_the_full_volume() -> None:
    scan = synthetic_scan()
    images = q.preprocess(scan, trim_sec=4.0)
    # only the center slice survives: (X, Y, T_trimmed), not the 4-D volume
    assert images.center_slice.ndim == 3
    assert images.detrend_method == "poly"


def test_weisskoff_rdc_matches_the_metric() -> None:
    result = q.run_qa(synthetic_scan(), roi_size=9)
    assert result.metrics.rdc == result.metrics.weisskoff.rdc
