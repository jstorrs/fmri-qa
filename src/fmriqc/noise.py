"""ROI-based FBIRN noise metrics: SNR, SFNR, drift, Weisskoff/RDC, spikes, outliers.

Every statistic here reads from the preprocessed `QAImages` over a resolved
`ROI`. ROI-averaging the per-voxel fluctuations equals detrending the ROI-mean
time course (detrending commutes with the spatial mean), which is what lets the
Weisskoff and drift measures reuse the pipeline's per-voxel residual.
"""

import numpy as np
from numpy.typing import NDArray
from scipy.special import erfcinv

from .constants import MAD_SCALE, OUTLIER_QTHR
from .imaging import roi_indexes
from .types import ROI, OutlierResult, QAImages, SpikeResult, WeisskoffResult


def outlier_fraction(
    fluctuations: NDArray, mask: NDArray, qthr: float = OUTLIER_QTHR
) -> OutlierResult:
    """Per-TR outlier-voxel fraction over `mask`, following AFNI 3dToutcount.

    For each masked voxel the robust spread of its detrended residual is
    `sigma = sqrt(pi/2) * MAD` (MAD = median |residual|); a frame is an outlier
    for that voxel when `|residual| > alpha * sigma`, with
    `alpha = Q^-1(qthr / n_t)` the normal upper-tail quantile that makes a clean
    voxel flag a frame with probability `qthr`. `fraction[t]` is the share of
    masked voxels flagged at frame `t`. Constant voxels (`MAD = 0`) never flag.

    `fluctuations` is the per-voxel *detrended* residual (3dToutcount detrends
    first); passing `QAImages.fluctuations` reuses the pipeline's Legendre
    detrend, as afni_proc.py recommends before outlier classification (its trend
    fit is L1 vs. our L2 -- a minor difference for a stable phantom).
    """
    resid = fluctuations[mask]  # (n_vox, n_t)
    n_vox, n_t = resid.shape
    mad = np.median(np.abs(resid), axis=1)  # (n_vox,)
    alpha = float(np.sqrt(2.0) * erfcinv(2.0 * qthr / n_t))  # Q^-1(qthr / n_t)
    thr = alpha * np.sqrt(np.pi / 2.0) * mad  # per-voxel outlier threshold
    is_out = (np.abs(resid) > thr[:, None]) & (mad > 0)[:, None]
    return OutlierResult(
        fraction=is_out.sum(axis=0) / n_vox,
        n_voxels=int(n_vox),
        qthr=qthr,
    )


def _spike_ratio(x: NDArray) -> float:
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

    Both are `_spike_ratio` (peak / robust spread) of the detrended ROI-mean
    residual series -- `tc_outlier` in the time domain, `spec_outlier` on its FFT
    magnitude with the DC bin dropped (matching cran, and the report's residual
    spectrum). The residual is the ROI mean of the pipeline's per-voxel
    fluctuations, i.e. the detrended ROI-mean time course (detrending commutes
    with the spatial mean).
    """
    resid = images.fluctuations[*roi.index].mean(axis=(0, 1))
    spec = np.abs(np.fft.rfft(resid))[1:]  # magnitude, DC bin dropped (as cran does)
    return SpikeResult(tc_outlier=_spike_ratio(resid), spec_outlier=_spike_ratio(spec))


def _roi_cv(
    fluctuations: NDArray, mean_image: NDArray, roi_center: NDArray, k: int
) -> float:
    """CV over a k x k ROI: RMS of the ROI-mean fluctuation / ROI-mean signal.

    ROI-averaging the per-voxel `fluctuations` equals detrending the ROI-mean
    timeseries (detrending commutes with the spatial mean), and the temporal
    mean of that timeseries is the ROI mean of `mean_image`.
    """
    roi = roi_indexes(roi_center, k)
    roi_fluct = fluctuations[*roi].mean(axis=(0, 1))
    return float(np.std(roi_fluct, mean=0) / mean_image[*roi].mean())


def _roi_cv1(
    fluctuation_noise: NDArray, mean_image: NDArray, roi_center: NDArray, k: int
) -> float:
    """Single-voxel CV pooled over a k x k ROI: RMS(noise) / ROI mean signal."""
    roi = roi_indexes(roi_center, k)
    s = fluctuation_noise[*roi]
    return float(np.sqrt(np.mean(s**2)) / mean_image[*roi].mean())


def weisskoff(images: QAImages, roi: ROI) -> WeisskoffResult:
    """Weisskoff plot + radius of decorrelation over a resolved ROI.

    For each ROI size, `cv` is the CV of the ROI-mean fluctuation and `cv1` is
    the single-voxel CV pooled within the ROI; `rdc_curve = cv1 / cv`.
    `cv1_pooled` is the pooled CV over the full ROI and `rdc = cv1_pooled/cv[-1]`.
    """
    # derived images are properties; read each once rather than per ROI size
    fluctuations, mean_image = images.fluctuations, images.mean_image
    noise = images.fluctuation_noise
    # every integer width 1..roi.size, per the fBIRN/Glover Weisskoff protocol
    # (Friedman & Glover 2006); cv[-1] is at the full ROI the pooled cv1 spans
    roi_sizes = np.arange(1, roi.size + 1)
    cv = np.array(
        [_roi_cv(fluctuations, mean_image, roi.center, int(k)) for k in roi_sizes]
    )
    cv1 = np.array([_roi_cv1(noise, mean_image, roi.center, int(k)) for k in roi_sizes])

    idx = roi.index
    s = noise[*idx]
    cv1_pooled = float(np.sqrt(np.mean(s**2)) / mean_image[*idx].mean())

    return WeisskoffResult(
        roi_sizes=roi_sizes,
        cv=cv,
        cv1=cv1,
        cv1_pooled=cv1_pooled,
        rdc=cv1_pooled / cv[-1],
    )


def snr(images: QAImages, roi: ROI) -> float:
    """fBIRN signal-to-noise ratio over a resolved ROI (Glover 2006).

    Signal is the mean of the temporal-mean image over the ROI. Static spatial
    noise is the ROI variance of the (odd-sum minus even-sum) difference image;
    SNR = signal / sqrt(variance / n_frames). The difference uses frame *sums*,
    not means, so the normalization matches the fBIRN definition.
    """
    idx = roi.index
    cs = images.center_slice
    n_frames = cs.shape[-1]
    diff = cs[..., 1::2].sum(axis=-1) - cs[..., 0::2].sum(axis=-1)
    signal = images.mean_image[*idx].mean()
    var_summary = diff[*idx].var()
    return float(signal / np.sqrt(var_summary / n_frames))


def sfnr(images: QAImages, roi: ROI) -> float:
    """fBIRN signal-to-fluctuation-noise ratio over a resolved ROI (Glover 2006).

    Mean over the ROI of the voxelwise SFNR image (temporal-mean signal divided
    by temporal fluctuation noise).
    """
    idx = roi.index
    sfnr_image = images.mean_image[*idx] / images.fluctuation_noise[*idx]
    return float(sfnr_image.mean())


def drift_percent(images: QAImages, roi: ROI) -> float:
    """Peak-to-peak of the ROI-mean fitted trend, as % of the ROI mean signal."""
    idx = roi.index
    trend_roi = images.trend[*idx].mean(axis=(0, 1))
    signal = images.mean_image[*idx].mean()
    return float(100.0 * (trend_roi.max() - trend_roi.min()) / signal)


def percent_fluctuation(images: QAImages, roi: ROI) -> float:
    """SD of the ROI-mean residual, as % of the ROI mean signal (fBIRN)."""
    idx = roi.index
    resid_roi = images.fluctuations[*idx].mean(axis=(0, 1))
    signal = images.mean_image[*idx].mean()
    return float(100.0 * np.std(resid_roi, mean=0) / signal)
