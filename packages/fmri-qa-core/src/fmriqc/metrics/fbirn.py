"""Core FBIRN ROI stability metrics: SNR, SFNR, drift, fluctuation, Weisskoff/RDC.

Every statistic here reads from the preprocessed `QAImages` over a resolved
`ROI`. ROI-averaging the per-voxel fluctuations equals detrending the ROI-mean
time course (detrending commutes with the spatial mean), which is what lets the
Weisskoff and drift measures reuse the pipeline's per-voxel residual.
"""

from dataclasses import dataclass

import numpy as np

from .._arrays import ArrayValue
from ..prep.geometry import ROI
from ..prep.images import QAImages
from ..prep.imaging import roi_indexes
from ..types import FloatArray, IntArray


@dataclass(frozen=True, eq=False, slots=True)
class WeisskoffResult(ArrayValue):
    """Weisskoff/RDC analysis over a range of ROI sizes.

    `cv` is the ROI-averaged CV and `cv1` the single-voxel CV pooled within each
    ROI size; `rdc_curve = cv1 / cv` is the effective decorrelation factor at
    each size (ideal = ROI width). `rdc` is the scalar value at the full ROI.
    """

    roi_sizes: IntArray
    cv: FloatArray
    cv1: FloatArray
    cv1_pooled: float
    rdc: float

    @property
    def rdc_curve(self) -> FloatArray:
        """RDC at each ROI size: pooled single-voxel CV / ROI-averaged CV."""
        return self.cv1 / self.cv


def _roi_cv(
    fluctuations: FloatArray, mean_image: FloatArray, roi_center: IntArray, k: int
) -> float:
    """CV over a k x k ROI: RMS of the ROI-mean fluctuation / ROI-mean signal.

    ROI-averaging the per-voxel `fluctuations` equals detrending the ROI-mean
    timeseries (detrending commutes with the spatial mean), and the temporal
    mean of that timeseries is the ROI mean of `mean_image`.

    NaN if the ROI mean signal is exactly zero -- background or a suppressed
    reconstruction -- rather than the `RuntimeWarning`-raising division numpy
    would otherwise perform: the estimator could not resolve the quantity, the
    same as its siblings, not an accident of the ROI landing on nothing.
    """
    roi = roi_indexes(roi_center, k)
    roi_fluct = fluctuations[*roi].mean(axis=(0, 1))
    roi_signal = mean_image[*roi].mean()
    if roi_signal == 0.0:
        return float("nan")
    return float(np.std(roi_fluct, mean=0) / roi_signal)


def _roi_cv1(
    fluctuation_noise: FloatArray, mean_image: FloatArray, roi_center: IntArray, k: int
) -> float:
    """Single-voxel CV pooled over a k x k ROI: RMS(noise) / ROI mean signal.

    NaN on a zero ROI mean signal, for the same reason as `_roi_cv`: the
    estimator could not resolve the quantity, not a warning-worthy accident.
    """
    roi = roi_indexes(roi_center, k)
    s = fluctuation_noise[*roi]
    roi_signal = mean_image[*roi].mean()
    if roi_signal == 0.0:
        return float("nan")
    return float(np.sqrt(np.mean(s**2)) / roi_signal)


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
    # cv1[-1] is _roi_cv1 at k = roi.size, which is exactly the pooled CV over
    # the full ROI: reuse it rather than recomputing the same ratio inline,
    # which would bypass the helper's zero-signal guard and re-open the warning
    # this function exists to avoid.
    cv1_pooled = float(cv1[-1])

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

    Which is why the difference is formed over an *even* number of frames. With
    an odd count the two subsets differ by one frame, so the difference carries
    a whole frame of signal, and that frame's spatial variation across the ROI —
    not noise — dominates the variance: a phantom shaded 25% across the FOV reads
    25% low. Frame parity is set by `--trim-sec`, so the same series would score
    differently for a one-volume change in the warm-up trim. The trailing frame
    is dropped from the difference only; the signal still averages the full
    series. NaN for a series too short to hold one odd/even pair, and NaN when
    the difference image has no variance across the ROI at all: there is no
    static noise to measure the signal against, so the ratio is undefined rather
    than infinite — the same answer the sibling metrics give for a quantity they
    cannot resolve.
    """
    idx = roi.index
    cs = images.center_slice
    n_frames = cs.shape[-1] - cs.shape[-1] % 2  # balanced odd/even subsets
    if n_frames == 0:
        return float("nan")
    paired = cs[..., :n_frames]
    diff = paired[..., 1::2].sum(axis=-1) - paired[..., 0::2].sum(axis=-1)
    signal = images.mean_image[*idx].mean()
    var_summary = float(diff[*idx].var())
    if var_summary == 0.0:
        return float("nan")
    return float(signal / np.sqrt(var_summary / n_frames))


def sfnr(images: QAImages, roi: ROI) -> float:
    """fBIRN signal-to-fluctuation-noise ratio over a resolved ROI (Glover 2006).

    Mean over the ROI of the voxelwise SFNR image (temporal-mean signal divided
    by temporal fluctuation noise).

    NaN if any ROI voxel has no fluctuation noise at all: its own ratio is
    undefined, and an average over the ROI cannot be more defined than the
    voxels it averages. (The per-voxel SFNR *image* in `analysis.build` is a
    different question — it is drawn, not reduced, and floors the divisor so a
    noiseless voxel renders instead of blanking the map.)
    """
    idx = roi.index
    noise = images.fluctuation_noise[*idx]
    if not np.all(noise):
        return float("nan")
    return float((images.mean_image[*idx] / noise).mean())


def drift_percent(images: QAImages, roi: ROI) -> float:
    """Peak-to-peak of the ROI-mean fitted trend, as % of the ROI mean signal.

    NaN if the ROI mean signal is exactly zero (background, or a suppressed
    reconstruction): a percentage of nothing is undefined, and the estimator
    could not resolve the quantity, rather than the divide-by-zero numpy would
    otherwise warn about.
    """
    idx = roi.index
    trend_roi = images.trend[*idx].mean(axis=(0, 1))
    signal = images.mean_image[*idx].mean()
    if signal == 0.0:
        return float("nan")
    return float(100.0 * (trend_roi.max() - trend_roi.min()) / signal)


def percent_fluctuation(images: QAImages, roi: ROI) -> float:
    """SD of the ROI-mean residual, as % of the ROI mean signal (fBIRN).

    NaN on a zero ROI mean signal, for the same reason as `drift_percent`: the
    estimator could not resolve the quantity, not a warning-worthy accident.
    """
    idx = roi.index
    resid_roi = images.fluctuations[*idx].mean(axis=(0, 1))
    signal = images.mean_image[*idx].mean()
    if signal == 0.0:
        return float("nan")
    return float(100.0 * np.std(resid_roi, mean=0) / signal)
