"""High/low flip-angle noise separation (thermal vs. instability).

Greve's high/low flip-angle QA: two phantom runs that differ only in flip angle
let thermal (additive) noise be separated from instability (multiplicative)
noise, because their variances scale differently with signal level. `run_hilo`
pools statistics over the shared eroded phantom core; `separate_noise` is the
flip-angle algebra, kept pure so it can be exercised directly.

`ls` this package to find a concern:

* `result`        -- `HiLoResult`, the value object, and `separate_noise`, the
                      pure algebra that fills it
* `mask`          -- `phantom_core_mask`, the eroded phantom-core mask each
                      scan is reduced over, and its `HILO_ERODE` tuning constant
* `stats`         -- per-scan reduction to the mean/SD maps `run_hilo` pools
* `compatibility` -- the geometry/acquisition checks the two scans must satisfy
"""

from ..exceptions import IncompatibleScansError
from ..load.scan import QAScan
from ..settings import AnalysisSettings
from ..types import DetrendMethod
from ..validation import validate_hilo_run
from ..warn import warn
from .compatibility import require_compatible_scans
from .mask import HILO_ERODE, phantom_core_mask
from .result import HiLoResult, separate_noise
from .stats import hilo_stats

__all__ = [
    "HILO_ERODE",
    "HiLoResult",
    "hilo_stats",
    "phantom_core_mask",
    "run_hilo",
    "separate_noise",
]


_DEFAULTS = AnalysisSettings()


def run_hilo(
    high: QAScan,
    low: QAScan,
    trim_sec: float = _DEFAULTS.trim_sec,
    detrend: DetrendMethod = _DEFAULTS.detrend,
    erode: int = HILO_ERODE,
) -> HiLoResult:
    """Separate thermal from instability noise in a high/low flip-angle pair.

    Following Greve's high/low flip-angle method (bxh `fmriqa` tooling): `high` and
    `low` must be the same acquisition except for flip angle (the high-flip run
    first). Each scan is reduced to a temporal-mean map and a
    temporal-SD-of-residual map over the whole volume (`hilo_stats`), and the
    statistics are pooled over the **shared** eroded phantom core — the intersection
    of the two scans' core masks — so `mean_high` and `mean_low` are averaged over
    identical voxels. `separate_noise` then does the flip-angle algebra.

    Raises
    ------
    IncompatibleScansError
        If the two scans differ in geometry, or their phantom cores do not
        overlap.
    """
    validate_hilo_run(high, low, trim_sec=trim_sec, erode=erode)
    require_compatible_scans(high, low)

    fh = high.meta.flip_angle if high.meta else None
    fl = low.meta.flip_angle if low.meta else None
    if fh is not None and fl is not None and fh <= fl:
        warn(
            f"high-flip scan flip angle ({fh:g}) is not greater than the low-flip "
            f"scan ({fl:g}); check the argument order (high first, low second).",
        )

    mean_h, sd_h, core_h = hilo_stats(high, trim_sec, detrend, erode)
    mean_l, sd_l, core_l = hilo_stats(low, trim_sec, detrend, erode)

    core = core_h & core_l
    n = int(core.sum())
    if n == 0:
        raise IncompatibleScansError(
            "phantom core overlap",
            int(core_h.sum()),
            int(core_l.sum()),
            "no shared voxels; check positioning or lower --erode",
        )

    mean_high = float(mean_h[core].mean())
    mean_low = float(mean_l[core].mean())
    var_high = (
        float(sd_h[core].mean()) ** 2
    )  # (core-mean per-voxel SD)**2, per Greve's method
    var_low = float(sd_l[core].mean()) ** 2
    return separate_noise(
        mean_high=mean_high,
        mean_low=mean_low,
        var_high=var_high,
        var_low=var_low,
        n_voxels=n,
        flip_high=fh,
        flip_low=fl,
    )
