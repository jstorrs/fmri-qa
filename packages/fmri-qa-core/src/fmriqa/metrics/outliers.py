"""Temporal and spectral artifact detection: outlier fractions and spike scores.

Flags for a single bad volume or a dominant periodic artifact, as opposed to the
stability summaries in `fbirn`: the per-TR outlier-voxel fraction over the
phantom (AFNI 3dToutcount), and the cran-fmriqa MAD-normalized temporal and
spectral spike scores over the ROI mean.
"""

from dataclasses import dataclass

import numpy as np

from .._arrays import ArrayValue
from ..prep.geometry import ROI
from ..prep.images import QAImages
from ..types import BoolArray, FloatArray

__all__ = [
    "MAD_SCALE",
    "OUTLIER_QTHR",
    "OutlierResult",
    "SpikeResult",
    "outlier_fraction",
    "spike_scores",
]

# R `mad()` default scale constant. It makes the MAD a consistent estimator of
# the SD for normal data. cran-fmriqa's spike scores divide by this MAD.
#: Factor that scales the median absolute deviation to the standard deviation of
#: normal data (R ``mad()``).
MAD_SCALE = 1.4826

# Used as qthr / n_t in the normal upper-tail quantile. It is not an expected
# per-frame outlier fraction.
#: Outlier threshold tuning parameter (the 3dToutcount default), not an expected
#: per-frame outlier fraction.
OUTLIER_QTHR = 0.001


@dataclass(frozen=True, eq=False, slots=True)
class OutlierResult(ArrayValue):
    """Per-TR outlier-voxel fraction (AFNI 3dToutcount) over the phantom mask.

    `fraction[t]` is the share of masked voxels whose detrended residual is an
    outlier at frame `t`, a trace that spikes on a bad volume. `qthr` tunes the
    threshold through `Q^-1(qthr / n_t)`. It is not an expected per-frame
    outlier fraction.
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

    Two unitless peak-over-spread ratios on the detrended ROI-mean time course,
    with R's `mad()` (`MAD_SCALE * median|x - median x|`) as the spread. A clean
    phantom sits near what a Gaussian gives (a few), and a transient stands well
    above it:

    * `tc_outlier` is `max|residual| / MAD(residual)` in the time domain. It is
      large when a single volume spikes (an RF or gradient transient that
      SD-based summaries average away).
    * `spec_outlier` is `max(magnitude) / MAD(magnitude)` of the residual's FFT
      (DC dropped). It is large when one narrow frequency dominates (a periodic
      artifact such as vibration, a bad interleave, or physiological-like
      pickup).

    Both use the series and spectrum the report plots (`spike_scores`). NaN if
    the series is empty or has no spread.
    """

    tc_outlier: float  # max|detrended ROI-mean residual| / MAD
    spec_outlier: float  # max(residual-spectrum magnitude) / MAD


def outlier_fraction(
    fluctuations: FloatArray, mask: BoolArray, qthr: float = OUTLIER_QTHR
) -> OutlierResult:
    """Compute the per-TR outlier-voxel fraction over `mask` (3dToutcount).

    For each masked voxel the robust spread of its detrended residual is
    `sigma = sqrt(pi/2) * MAD` (MAD = ``median |residual|``). A frame is an
    outlier for that voxel when ``|residual| > alpha * sigma``, with
    `alpha = Q^-1(qthr / n_t)` the normal upper-tail quantile. `qthr` tunes this
    length-dependent threshold; it is not an expected per-frame fraction.
    `fraction[t]` is the share of masked voxels flagged at frame `t`. Constant
    voxels (`MAD = 0`) never flag.

    `fluctuations` is the per-voxel detrended residual (3dToutcount detrends
    first). Pass `QAImages.fluctuations` for the pipeline's Legendre detrend, as
    afni_proc.py recommends. Its trend fit is L1 where ours is L2, a minor
    difference for a stable phantom.
    """
    resid = fluctuations[mask]  # (n_vox, n_t)
    n_vox, n_t = resid.shape
    # Empty mask: report NaN, not a divide by zero (as the sibling metrics do).
    if n_vox == 0:
        return OutlierResult(fraction=np.full(n_t, np.nan), n_voxels=0, qthr=qthr)
    mad = np.median(np.abs(resid), axis=1)  # (n_vox,)
    # Imported here to keep scipy.special's compiled stack off the --version,
    # --help and analysis-only import paths. This is its only use in the package.
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
    """Compute the peak-over-spread ratio `max|x| / mad(x)` (see `MAD_SCALE`).

    The kernel of both cran-fmriqa spike scores: the largest absolute value
    against the robust spread of the whole series. NaN if `x` is empty or has
    zero spread (a constant series).
    """
    if x.size == 0:
        return float("nan")
    mad = MAD_SCALE * float(np.median(np.abs(x - np.median(x))))
    return float(np.max(np.abs(x)) / mad) if mad > 0 else float("nan")


def spike_scores(images: QAImages, roi: ROI) -> SpikeResult:
    """Compute cran-fmriqa MAD-normalized spike scores over the ROI.

    `tc_outlier` works in the time domain and `spec_outlier` on the FFT
    magnitude with the DC bin dropped (as cran and the report's spectrum do). The
    residual is the ROI mean of the per-voxel fluctuations, which equals the
    detrended ROI-mean time course because detrending commutes with the spatial
    mean.
    """
    resid = roi.mean(images.fluctuations)
    spec = np.abs(np.fft.rfft(resid))[1:]  # magnitude, DC bin dropped (as cran does)
    return SpikeResult(tc_outlier=_spike_ratio(resid), spec_outlier=_spike_ratio(spec))
