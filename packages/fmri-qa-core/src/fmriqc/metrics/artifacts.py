"""Temporal and spectral artifact detection: outlier fractions and spike scores.

The anomaly indicators that flag a single bad volume or a dominant periodic
artifact, as opposed to the settled FBIRN stability summaries in `fbirn`: the
per-TR outlier-voxel fraction (AFNI 3dToutcount) over the phantom, and the
cran-fmriqa MAD-normalized temporal/spectral spike scores over the ROI mean.
"""

from dataclasses import dataclass

import numpy as np

from .._arrays import ArrayValue
from ..prep.geometry import ROI
from ..prep.images import QAImages
from ..types import BoolArray, FloatArray

# R `mad()` default scale constant: 1.4826 makes the MAD a consistent estimator
# of the SD for normal data. cran-fmriqa's spike scores divide by this MAD.
MAD_SCALE = 1.4826

# Threshold tuning parameter (3dToutcount default), used as qthr / n_t in the
# normal upper-tail quantile; it is not an expected per-frame outlier fraction.
OUTLIER_QTHR = 0.001


@dataclass(frozen=True, eq=False, slots=True)
class OutlierResult(ArrayValue):
    """Per-TR outlier-voxel fraction (AFNI 3dToutcount) over the phantom mask.

    `fraction[t]` is the share of masked voxels whose detrended residual is a
    statistical outlier at frame `t` -- a temporal-stability trace that spikes on
    a bad volume. `qthr` tunes the threshold through `Q^-1(qthr / n_t)`;
    it is not an expected per-frame outlier fraction.
    """

    fraction: FloatArray  # (n_t,) outlier-voxel fraction per frame
    n_voxels: int  # masked voxels (the fraction denominator)
    qthr: float  # threshold tuning parameter

    @property
    def max_fraction(self) -> float:
        """Worst single-frame outlier fraction."""
        return float(self.fraction.max())

    @property
    def worst_volume(self) -> int:
        """Frame index (within the analyzed series) with the most outliers."""
        return int(np.argmax(self.fraction))


@dataclass(frozen=True, slots=True)
class SpikeResult:
    """MAD-normalized temporal / spectral spike scores (cran-fmriqa).

    Two unitless anomaly indicators of the detrended ROI-mean time course, each a
    peak-over-spread ratio using R's `mad()` (`MAD_SCALE * median|x - median x|`,
    the SD-consistent robust spread) as the denominator so a clean, stationary
    phantom sits near the level a Gaussian would give (a few) and a transient
    stands well above it:

    * `tc_outlier` -- `max|residual| / MAD(residual)` in the *time* domain, large
      when a single volume spikes (an RF/gradient transient the SD-based summaries
      average away).
    * `spec_outlier` -- `max(magnitude) / MAD(magnitude)` of the residual's FFT
      (DC dropped), large when one narrow frequency dominates (a periodic
      artifact -- vibration, a bad interleave, physiological-like pickup).

    Computed on the same ROI-mean residual series and spectrum the report already
    plots (`spike_scores`). NaN if the series is empty or has no spread.
    """

    tc_outlier: float  # max|detrended ROI-mean residual| / MAD
    spec_outlier: float  # max(residual-spectrum magnitude) / MAD


def outlier_fraction(
    fluctuations: FloatArray, mask: BoolArray, qthr: float = OUTLIER_QTHR
) -> OutlierResult:
    """Per-TR outlier-voxel fraction over `mask`, following AFNI 3dToutcount.

    For each masked voxel the robust spread of its detrended residual is
    `sigma = sqrt(pi/2) * MAD` (MAD = median |residual|); a frame is an outlier
    for that voxel when `|residual| > alpha * sigma`, with
    `alpha = Q^-1(qthr / n_t)` the normal upper-tail quantile. `qthr` tunes
    this length-dependent threshold, not an expected per-frame fraction.
    `fraction[t]` is the share of masked voxels flagged at frame `t`.
    Constant voxels (`MAD = 0`) never flag.

    `fluctuations` is the per-voxel *detrended* residual (3dToutcount detrends
    first); passing `QAImages.fluctuations` reuses the pipeline's Legendre
    detrend, as afni_proc.py recommends before outlier classification (its trend
    fit is L1 vs. our L2 -- a minor difference for a stable phantom).
    """
    resid = fluctuations[mask]  # (n_vox, n_t)
    n_vox, n_t = resid.shape
    # Empty mask: report NaN rather than divide by zero (as the sibling metrics do).
    if n_vox == 0:
        return OutlierResult(fraction=np.full(n_t, np.nan), n_voxels=0, qthr=qthr)
    mad = np.median(np.abs(resid), axis=1)  # (n_vox,)
    # Deferred: scipy.special drags in scipy's compiled special-function stack for
    # this one call, and it is the only user in the package -- keep it off the
    # --version/--help/artifact-only import path.
    from scipy.special import erfcinv

    alpha = float(np.sqrt(2.0) * erfcinv(2.0 * qthr / n_t))  # Q^-1(qthr / n_t)
    thr = alpha * np.sqrt(np.pi / 2.0) * mad  # per-voxel outlier threshold
    is_out = (np.abs(resid) > thr[:, None]) & (mad > 0)[:, None]
    return OutlierResult(
        fraction=is_out.sum(axis=0) / n_vox,
        n_voxels=int(n_vox),
        qthr=qthr,
    )


def _spike_ratio(x: FloatArray) -> float:
    """Peak-over-spread ratio `max|x| / mad(x)`, R's `mad` (see `MAD_SCALE`).

    The kernel of both cran-fmriqa spike scores: the largest absolute value
    against the robust spread of the whole series. NaN if `x` is empty or has zero
    spread (a constant series, where the ratio is undefined).
    """
    if x.size == 0:
        return float("nan")
    mad = MAD_SCALE * float(np.median(np.abs(x - np.median(x))))
    return float(np.max(np.abs(x)) / mad) if mad > 0 else float("nan")


def spike_scores(images: QAImages, roi: ROI) -> SpikeResult:
    """cran-fmriqa MAD-normalized temporal/spectral spike scores over the ROI.

    Both are peak over robust (MAD) spread of the detrended ROI-mean
    residual series -- `tc_outlier` in the time domain, `spec_outlier` on its FFT
    magnitude with the DC bin dropped (matching cran, and the report's residual
    spectrum). The residual is the ROI mean of the pipeline's per-voxel
    fluctuations, i.e. the detrended ROI-mean time course (detrending commutes
    with the spatial mean).
    """
    resid = roi.mean(images.fluctuations)
    spec = np.abs(np.fft.rfft(resid))[1:]  # magnitude, DC bin dropped (as cran does)
    return SpikeResult(tc_outlier=_spike_ratio(resid), spec_outlier=_spike_ratio(spec))
