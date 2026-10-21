"""The high/low result value object and the pure flip-angle algebra that fills it.

`separate_noise` is pure, with no scan I/O or masking, so the flip-angle algebra
behind `HiLoResult` can be tested without `run_hilo`'s pooling over a scan pair.
"""

from dataclasses import dataclass, replace

import numpy as np


@dataclass(frozen=True, slots=True)
class HiLoResult:
    """Thermal vs. instability noise separation from a high/low flip-angle pair.

    Greve's high/low flip-angle QA (bxh's `fmriqa_*` tools): two phantom runs that
    differ only in flip angle separate the noise sources. Thermal (additive)
    variance is independent of signal level, while instability (multiplicative:
    drift, gradient heating, physiological-like fluctuation) variance scales with
    signal squared. With `M = (mean_high / mean_low)**2` and `instability_var`
    the instability variance at the high flip angle,

        var_high = thermal_var + instability_var
        var_low  = thermal_var + instability_var / M

    which solve to `thermal_var = (M*var_low - var_high)/(M - 1)` and
    `instability_var = var_high - thermal_var`. If measurement noise drives
    `instability_var` negative, it falls back to `thermal_var = var_low`,
    `instability_var = var_high - var_low` (`fell_back` records this).

    All statistics are pooled over the shared eroded phantom core. `mean_*` is
    the core-mean of the per-voxel temporal mean. `var_*` is the square of the
    core-mean per-voxel temporal SD of the detrended residual (Greve's
    `ROIstats` on the `stddev` image, then squared). `flip_high` and `flip_low`
    are the sidecar flip angles, kept for the report and the ordering check.
    """

    mean_high: float
    mean_low: float
    var_high: float
    var_low: float
    thermal_var: float
    instability_var: float
    n_voxels: int
    fell_back: bool
    flip_high: float | None = None
    flip_low: float | None = None

    @property
    def m(self) -> float:
        """Squared signal ratio `(mean_high / mean_low)**2`.

        Infinite when the low-flip mean is zero, where the split
        `separate_noise` reads this for is undefined anyway. This keeps a
        degenerate pair a reportable result instead of a traceback, since the CLI
        prints `M` outside the block that catches analysis failures.
        """
        if self.mean_low == 0.0:
            return float("inf")
        return (self.mean_high / self.mean_low) ** 2

    @property
    def thermal_fsnr(self) -> float:
        """Functional SNR of the thermal component: `mean_high / sqrt(thermal_var)`.

        NaN if the separated thermal variance is non-positive, an unphysical
        result meaning the model did not fit (for example, near-equal flip
        signals).
        """
        return (
            float(self.mean_high / np.sqrt(self.thermal_var))
            if self.thermal_var > 0
            else float("nan")
        )

    @property
    def instability_fsnr(self) -> float:
        """Functional SNR of the instability component.

        `mean_high / sqrt(instability_var)`; infinite when no instability is
        detected (`instability_var == 0`), NaN if it is negative.
        """
        if self.instability_var > 0:
            return float(self.mean_high / np.sqrt(self.instability_var))
        return float("inf") if self.instability_var == 0 else float("nan")

    @property
    def instability_fraction(self) -> float:
        """Share of the high-flip variance attributed to instability noise."""
        return (
            self.instability_var / self.var_high if self.var_high > 0 else float("nan")
        )


def separate_noise(
    *,
    mean_high: float,
    mean_low: float,
    var_high: float,
    var_low: float,
    n_voxels: int = 0,
    flip_high: float | None = None,
    flip_low: float | None = None,
) -> HiLoResult:
    """Split thermal from instability variance in pooled high/low statistics.

    The flip-angle noise-separation math of `HiLoResult`. `run_hilo` computes the
    pooled `mean_*` and `var_*` from a scan pair and calls this.
    """
    # Build the unsolved result first and read `m` off it, so the squared signal
    # ratio has one definition (`HiLoResult.m`), not a copy that could drift from
    # the one the report prints.
    undefined = HiLoResult(
        mean_high=mean_high,
        mean_low=mean_low,
        var_high=var_high,
        var_low=var_low,
        thermal_var=float("nan"),
        instability_var=float("nan"),
        n_voxels=n_voxels,
        fell_back=False,
        flip_high=flip_high,
        flip_low=flip_low,
    )
    m = undefined.m
    if not np.isfinite(m) or m == 1.0:
        # Signal unchanged across the two flip angles (m == 1, e.g. the same scan
        # passed twice) or zero low-flip signal. The split divides by (m - 1), so
        # it is undefined. Report NaN variances, which the FSNR properties
        # already fold to NaN.
        return undefined
    thermal_var = (m * var_low - var_high) / (m - 1.0)
    instability_var = var_high - thermal_var
    fell_back = instability_var < 0.0
    if fell_back:  # measurement noise pushed instability negative: Greve fallback
        thermal_var = var_low
        instability_var = var_high - var_low
    return replace(
        undefined,
        thermal_var=thermal_var,
        instability_var=instability_var,
        fell_back=fell_back,
    )
