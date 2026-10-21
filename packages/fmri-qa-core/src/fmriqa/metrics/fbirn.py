"""Core FBIRN ROI stability metrics: SNR, SFNR, drift, fluctuation, Weisskoff/RDC.

Every statistic reads the preprocessed `QAImages` over a resolved `ROI`.
ROI-averaging the per-voxel fluctuations equals detrending the ROI-mean time
course (detrending commutes with the spatial mean), so the Weisskoff and drift
measures can reuse the pipeline's per-voxel residual.
"""

from dataclasses import dataclass

import numpy as np

from .._arrays import ArrayValue
from ..prep.geometry import ROI
from ..prep.images import QAImages
from ..types import FloatArray, IntArray

__all__ = [
    "WeisskoffResult",
    "drift_percent",
    "percent_fluctuation",
    "sfnr",
    "snr",
    "weisskoff",
]


@dataclass(frozen=True, eq=False, slots=True)
class WeisskoffResult(ArrayValue):
    """Weisskoff/RDC analysis over a range of ROI sizes.

    `cv` is the ROI-averaged CV and `cv1` the single-voxel CV pooled within each
    ROI size; `rdc_curve = cv1 / cv` is the effective decorrelation factor at
    each size (ideal = ROI width). The last entry of each curve is the full ROI,
    so `cv1_pooled` and `rdc` are read off the curves, not stored beside them
    where they could disagree.
    """

    roi_sizes: IntArray
    cv: FloatArray
    cv1: FloatArray

    @property
    def cv1_pooled(self) -> float:
        """Single-voxel CV pooled over the full ROI (the last `cv1` entry)."""
        return float(self.cv1[-1])

    @property
    def rdc(self) -> float:
        """Radius of decorrelation at the full ROI: `cv1_pooled / cv[-1]`."""
        return float(self.cv1_pooled / self.cv[-1])

    @property
    def rdc_curve(self) -> FloatArray:
        """RDC at each ROI size: pooled single-voxel CV / ROI-averaged CV."""
        return self.cv1 / self.cv


def _relative_to_signal(value: float, *, signal: float) -> float:
    """Return `value / signal`, or NaN if the ROI mean signal is exactly zero.

    A zero ROI mean signal means background or a suppressed reconstruction, so
    the estimator could not resolve the quantity. NaN also avoids the
    `RuntimeWarning` numpy's division would raise.
    """
    if signal == 0.0:
        return float("nan")
    return float(value / signal)


def _roi_cv(*, fluctuations: FloatArray, mean_image: FloatArray, roi: ROI) -> float:
    """Compute the CV over an ROI.

    The CV is the RMS of the ROI-mean fluctuation over the ROI-mean signal.
    ROI-averaging the per-voxel `fluctuations` equals detrending the ROI-mean
    time series, and that series' temporal mean is the ROI mean of `mean_image`.

    NaN when the ROI mean signal is exactly zero.
    """
    roi_fluct = roi.mean(fluctuations)
    roi_signal = roi.mean(mean_image)
    return _relative_to_signal(np.std(roi_fluct, mean=0), signal=roi_signal)


def _roi_cv1(
    *,
    fluctuation_noise: FloatArray,
    mean_image: FloatArray,
    roi: ROI,
) -> float:
    """Compute the pooled single-voxel CV: RMS(noise) / ROI mean signal.

    NaN when the ROI mean signal is exactly zero.
    """
    s = fluctuation_noise[roi.index]
    roi_signal = roi.mean(mean_image)
    return _relative_to_signal(np.sqrt(np.mean(s**2)), signal=roi_signal)


def weisskoff(images: QAImages, roi: ROI) -> WeisskoffResult:
    """Compute the Weisskoff curves and radius of decorrelation for an ROI.

    For each ROI size, `cv` is the CV of the ROI-mean fluctuation and `cv1` is
    the single-voxel CV pooled within the ROI; `rdc_curve = cv1 / cv`.
    The result's `cv1_pooled` and `rdc` are the full-ROI values of those curves.
    """
    # Derived images are properties, so read each once, not per ROI size.
    fluctuations, mean_image = images.fluctuations, images.mean_image
    noise = images.fluctuation_noise
    # Every integer width 1..roi.size, per the FBIRN/Glover Weisskoff protocol
    # (Friedman & Glover 2006). cv[-1] is at the full ROI the pooled cv1 spans.
    roi_sizes = np.arange(1, roi.size + 1)
    cv = np.array(
        [
            _roi_cv(
                fluctuations=fluctuations,
                mean_image=mean_image,
                roi=ROI(center=roi.center, size=int(k)),
            )
            for k in roi_sizes
        ]
    )
    cv1 = np.array(
        [
            _roi_cv1(
                fluctuation_noise=noise,
                mean_image=mean_image,
                roi=ROI(center=roi.center, size=int(k)),
            )
            for k in roi_sizes
        ]
    )
    return WeisskoffResult(roi_sizes=roi_sizes, cv=cv, cv1=cv1)


def snr(images: QAImages, roi: ROI) -> float:
    """Compute the FBIRN SNR over a resolved ROI (Friedman & Glover 2006).

    Signal is the mean of the temporal-mean image over the ROI. Static spatial
    noise is the ROI variance of the (odd-sum minus even-sum) difference image;
    SNR = signal / sqrt(variance / n_frames). The difference uses frame sums,
    not means, to match the FBIRN definition.

    The difference uses an even number of frames. With an odd count the two
    subsets differ by one frame, so the difference carries a whole frame of
    signal, and its spatial variation across the ROI, not noise, dominates the
    variance (a phantom shaded 25% across the FOV reads 25% low). Frame parity
    follows the warm-up trim (`AnalysisSettings.trim_sec`), so a one-volume
    change in the trim would change the score. The trailing frame is dropped
    from the difference only; the signal still averages the full series. NaN for
    a series too short for one odd/even pair, and NaN when the difference image
    has no variance across the ROI (no static noise to measure against, so the
    ratio is undefined, not infinite).
    """
    idx = roi.index
    cs = images.center_slice
    n_frames = cs.shape[-1] - cs.shape[-1] % 2  # balanced odd/even subsets
    if n_frames == 0:
        return float("nan")
    paired = cs[..., :n_frames]
    diff = paired[..., 1::2].sum(axis=-1) - paired[..., 0::2].sum(axis=-1)
    signal = roi.mean(images.mean_image)
    var_summary = float(diff[idx].var())
    if var_summary == 0.0:
        return float("nan")
    return float(signal / np.sqrt(var_summary / n_frames))


def sfnr(images: QAImages, roi: ROI) -> float:
    """Compute the FBIRN signal-to-fluctuation-noise ratio over a resolved ROI.

    After Friedman & Glover 2006.

    Mean over the ROI of the voxelwise SFNR image (temporal-mean signal divided
    by temporal fluctuation noise).

    NaN if any ROI voxel has no fluctuation noise at all, since its own ratio is
    undefined and an average cannot be better defined than what it averages. The
    per-voxel SFNR image in `analysis.build` is different. It is drawn, not
    reduced, and floors the divisor so a noiseless voxel renders instead of
    blanking the map.
    """
    idx = roi.index
    noise = images.fluctuation_noise[idx]
    if not np.all(noise):
        return float("nan")
    return float((images.mean_image[idx] / noise).mean())


def drift_percent(images: QAImages, roi: ROI) -> float:
    """Compute the peak-to-peak ROI-mean trend, as % of the ROI mean signal.

    NaN when the ROI mean signal is exactly zero.
    """
    trend_roi = roi.mean(images.trend)
    signal = roi.mean(images.mean_image)
    return _relative_to_signal(
        100.0 * (trend_roi.max() - trend_roi.min()), signal=signal
    )


def percent_fluctuation(images: QAImages, roi: ROI) -> float:
    """Compute the SD of the ROI-mean residual, as % of ROI mean signal.

    NaN when the ROI mean signal is exactly zero.
    """
    return 100.0 * _roi_cv(
        fluctuations=images.fluctuations, mean_image=images.mean_image, roi=roi
    )
