"""Directional spatial smoothness of the noise field (AFNI 3dFWHMx + PSF).

The Gaussian FWHM of the detrended fluctuation field along each in-plane axis,
from the variance of first differences (AFNI's Classic estimator), plus the
empirical spatial autocorrelation for the point-spread curves. This is the
correlation-length confound the Weisskoff RDC is measured against.
"""

import warnings

import numpy as np
from numpy.typing import NDArray

from .constants import SIGMA_TO_FWHM, SMOOTHNESS_MAX_LAG
from .imaging import _geomean
from .types import SmoothnessResult


def _fwhm_1dif(image: NDArray, mask: NDArray) -> NDArray:
    """Classic first-difference Gaussian FWHM (voxels) along each in-plane axis.

    AFNI `mri_estimate_FWHM_1dif`: for each axis, the sample variance of forward
    first differences over neighbor pairs that are *both* in `mask` relates to
    the in-mask voxel variance as `arg = 1 - 0.5*var_diff/var`; then
    `sigma = sqrt(-1/(4 ln arg))` and `FWHM = sqrt(8 ln 2)*sigma`, in voxel units
    (multiply by the voxel size for mm). An axis whose `arg` leaves (0, 1) -- too
    little correlation to resolve, or too few in-mask pairs -- yields NaN.
    """
    vals = image[mask]
    out = np.full(2, np.nan)
    if vals.size < 2:
        return out
    var = float(vals.var(ddof=1))
    if var <= 0:
        return out
    for axis in (0, 1):
        lo = [slice(None)] * image.ndim
        hi = [slice(None)] * image.ndim
        lo[axis], hi[axis] = slice(0, -1), slice(1, None)
        pair = mask[tuple(lo)] & mask[tuple(hi)]  # both neighbors in-mask, in-bounds
        if pair.sum() < 2:
            continue
        diff = (image[tuple(hi)] - image[tuple(lo)])[pair]
        arg = 1.0 - 0.5 * float(diff.var(ddof=1)) / var
        if 0.0 < arg < 1.0:
            out[axis] = SIGMA_TO_FWHM * float(np.sqrt(-1.0 / (4.0 * np.log(arg))))
    return out


def _acf_1d(image: NDArray, mask: NDArray, axis: int, max_lag: int) -> NDArray:
    """Normalized spatial autocorrelation of `image` along `axis`, lags 0..max_lag.

    Follows AFNI `mri_estimate_ACF`: center by the in-mask mean and normalize by
    the in-mask variance, so `rho[d]` is the correlation of the noise field with
    itself `d` voxels apart along `axis`, over neighbor pairs that are *both* in
    `mask`. `rho[0]` is 1 by construction; a lag with too few in-mask pairs (or a
    constant frame) is NaN.
    """
    rho = np.full(max_lag + 1, np.nan)
    rho[0] = 1.0
    vals = image[mask]
    fbar = float(vals.mean())
    fvar = float(vals.var())
    if fvar <= 0:
        return rho
    for d in range(1, max_lag + 1):
        lo = [slice(None)] * image.ndim
        hi = [slice(None)] * image.ndim
        lo[axis], hi[axis] = slice(0, -d), slice(d, None)
        pair = mask[tuple(lo)] & mask[tuple(hi)]  # both voxels in-mask, in-bounds
        if pair.sum() < 2:
            continue
        a = image[tuple(lo)][pair] - fbar
        b = image[tuple(hi)][pair] - fbar
        rho[d] = float(np.mean(a * b) / fvar)
    return rho


def _directional_acf(scaled: NDArray, mask: NDArray, max_lag: int) -> NDArray:
    """Per-axis empirical noise autocorrelation, averaged over frames (AFNI ACF).

    `_acf_1d` per frame and axis, then the per-lag mean across frames (AFNI
    averages the per-subbrick ACF). Returns (2, max_lag + 1) for axes 0 and 1.
    """
    nt = scaled.shape[-1]
    acf = np.full((2, max_lag + 1), np.nan)
    for axis in (0, 1):
        per = np.array(
            [_acf_1d(scaled[..., t], mask, axis, max_lag) for t in range(nt)]
        )
        with warnings.catch_warnings():  # all-NaN lag columns -> NaN, not a warning
            warnings.simplefilter("ignore", RuntimeWarning)
            acf[axis] = np.nanmean(per, axis=0)
    return acf


def estimate_smoothness(
    fluctuations: NDArray,
    mask: NDArray,
    voxel_mm: tuple[float, float] | None = None,
    pe_axis: int | None = None,
    max_lag: int = SMOOTHNESS_MAX_LAG,
) -> SmoothnessResult:
    """Directional spatial smoothness of the detrended noise field (AFNI 3dFWHMx).

    Follows `3dFWHMx` run on detrended residuals: each voxel time series is first
    robustly standardized -- subtract its temporal median, divide by its MAD
    (AFNI's `-unif`, which the `-detrend` path forces on) -- so the estimate
    reflects the noise *correlation length* rather than its spatially varying
    amplitude, and voxels that are constant over time (MAD = 0) are dropped from
    the mask. Per in-plane axis, the Classic first-difference FWHM (`_fwhm_1dif`)
    is estimated on each standardized fluctuation frame over the phantom mask and
    aggregated across frames by geometric mean (AFNI `-geom`); the empirical
    spatial autocorrelation (`_directional_acf`) is collected over the same lags
    for the point-spread curves. `pe_axis` labels the axes as phase-encode /
    readout; `voxel_mm` (in-plane, from the header) lets lengths be reported in
    mm. `fluctuations` is (X, Y, T) -- `QAImages.fluctuations`, the same
    Legendre-detrended residual the noise metrics are measured on.
    """
    centered = fluctuations - np.median(fluctuations, axis=-1, keepdims=True)
    mad = np.median(np.abs(centered), axis=-1)  # (X, Y)
    work_mask = mask & (mad > 0)
    scaled = centered / np.where(mad > 0, mad, 1.0)[..., None]

    nt = scaled.shape[-1]
    per = np.array([_fwhm_1dif(scaled[..., t], work_mask) for t in range(nt)])
    fwhm_vox = (_geomean(per[:, 0]), _geomean(per[:, 1]))

    lag = min(max_lag, *(d - 1 for d in work_mask.shape[:2]))
    lags = np.arange(lag + 1)
    acf = _directional_acf(scaled, work_mask, lag)

    vm = (float(voxel_mm[0]), float(voxel_mm[1])) if voxel_mm is not None else None
    return SmoothnessResult(
        fwhm_vox=fwhm_vox, lags=lags, acf=acf, voxel_mm=vm, pe_axis=pe_axis
    )
