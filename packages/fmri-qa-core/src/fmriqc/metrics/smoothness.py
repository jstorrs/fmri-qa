"""Directional spatial smoothness of the noise field (AFNI 3dFWHMx + PSF).

The Gaussian FWHM of the detrended fluctuation field along each in-plane axis,
from the variance of first differences (AFNI's Classic estimator), plus the
empirical spatial autocorrelation for the point-spread curves. This is the
correlation-length confound the Weisskoff RDC is measured against.
"""

import warnings
from dataclasses import dataclass

import numpy as np

from .._arrays import ArrayValue
from ..prep.imaging import geomean, normalize_voxel_mm
from ..types import BoolArray, FloatArray, IntArray

# Gaussian FWHM per standard deviation: sqrt(8 ln 2) (AFNI 3dFWHMx uses 2.35482).
SIGMA_TO_FWHM = float(np.sqrt(8.0 * np.log(2.0)))
# Lags (voxels) over which the directional noise autocorrelation / PSF is sampled.
SMOOTHNESS_MAX_LAG = 10


@dataclass(frozen=True, eq=False)
class SmoothnessResult(ArrayValue):
    """Directional spatial smoothness of the noise field (AFNI 3dFWHMx + PSF).

    The Gaussian FWHM of the detrended fluctuation (noise) field, estimated per
    in-plane axis from the variance of first differences (AFNI's Classic
    `mri_estimate_FWHM_1dif`): for a smoothed white-noise field the forward
    first-difference variance relates to the voxel variance by
    `arg = 1 - 0.5*var_diff/var`, giving `sigma = sqrt(-1/(4 ln arg))` and
    `FWHM = sqrt(8 ln 2)*sigma`. Estimated on each fluctuation frame over the
    phantom mask, then aggregated across frames by geometric mean (AFNI `-geom`).
    A larger FWHM means a smoother noise field -- the spatial-correlation confound
    the guide warns the Weisskoff RDC is measured against.

    The axes are resolved to physical directions with `pe_axis`: `fwhm_pe` is the
    FWHM along the phase-encode axis, `fwhm_ro` along the readout axis. `acf` is
    the empirical spatial autocorrelation of the noise field at each lag in
    `lags` (voxels), per axis; because the noise is a point-spread function (PSF)
    convolved with white noise, the normalized autocorrelation is `PSF^2` under
    the Gaussian random-field model, so `psf_empirical` (= `acf**2`) and the
    Gaussian `psf_model` from the measured FWHM give the directional point-spread
    profile -- PE/RO asymmetry is anisotropic reconstruction smoothing.

    `fwhm_vox` is (axis 0, axis 1) in voxels; `voxel_mm` carries the in-plane
    voxel size so lengths can be reported in mm. A NaN FWHM means the estimator
    could not resolve smoothness on that axis (too little correlation, or too few
    in-mask pairs).
    """

    fwhm_vox: tuple[float, float]
    lags: IntArray  # (n_lag,) integer voxel lags 0..L
    acf: FloatArray  # (2, n_lag): per-axis autocorrelation
    voxel_mm: tuple[float, float] | None = None
    pe_axis: int | None = None  # array axis of the phase-encode direction

    # -- per-axis helpers ---------------------------------------------------- #
    def _mm_per(self, axis: int) -> float:
        """mm per voxel along `axis` (1.0 when the voxel size is unknown)."""
        return self.voxel_mm[axis] if self.voxel_mm is not None else 1.0

    def fwhm_axis(self, axis: int) -> float:
        """FWHM along an array `axis`, in mm if the voxel size is known, else voxels."""
        return self.fwhm_vox[axis] * self._mm_per(axis)

    def displacement(self, axis: int) -> FloatArray:
        """Lag axis for `axis` as a length (mm if voxel size is known, else voxels)."""
        return np.asarray(self.lags * self._mm_per(axis), dtype=np.float64)

    def psf_empirical(self, axis: int) -> FloatArray:
        """Empirical PSF profile along `axis`: the squared noise autocorrelation.

        For white noise convolved with a PSF, the normalized spatial
        autocorrelation is the autocorrelation of the PSF; for a Gaussian PSF that
        equals `PSF**2`, so squaring the measured `acf` recovers the point-spread
        profile implied by the data at each sampled lag.
        """
        return np.asarray(self.acf[axis] ** 2, dtype=np.float64)

    def psf_model(self, x: FloatArray, axis: int) -> FloatArray:
        """Gaussian PSF profile along `axis` at displacement `x` (same units as `x`).

        The Gaussian whose FWHM is `fwhm_axis(axis)`; pass `x` from `displacement`
        so the model shares the empirical PSF's units.
        """
        sigma = self.fwhm_axis(axis) / SIGMA_TO_FWHM
        return np.exp(-0.5 * (np.asarray(x, dtype=float) / sigma) ** 2)

    # -- directional (PE / RO) ---------------------------------------------- #
    @property
    def ro_axis(self) -> int | None:
        """Readout array axis (the in-plane axis that is not the PE axis)."""
        return None if self.pe_axis is None else 1 - self.pe_axis

    @property
    def fwhm_pe(self) -> float | None:
        """FWHM along the phase-encode axis (mm/voxels); None if `pe_axis` unknown."""
        return None if self.pe_axis is None else self.fwhm_axis(self.pe_axis)

    @property
    def fwhm_ro(self) -> float | None:
        """FWHM along the readout axis (mm/voxels); None if `pe_axis` unknown."""
        a = self.ro_axis
        return None if a is None else self.fwhm_axis(a)

    # -- combined (AFNI ccomb) ---------------------------------------------- #
    @property
    def fwhm_mm(self) -> tuple[float, float] | None:
        """(axis 0, axis 1) FWHM in mm, or None if voxel sizes are unknown."""
        if self.voxel_mm is None:
            return None
        return (
            self.fwhm_vox[0] * self.voxel_mm[0],
            self.fwhm_vox[1] * self.voxel_mm[1],
        )

    @property
    def fwhm_combined_vox(self) -> float:
        """Geometric mean of the per-axis FWHM over the resolved axes (voxels)."""
        return geomean(np.asarray(self.fwhm_vox))

    @property
    def fwhm_combined_mm(self) -> float | None:
        """Geometric-mean FWHM in mm (AFNI `ccomb`); None without voxel sizes."""
        mm = self.fwhm_mm
        return geomean(np.asarray(mm)) if mm is not None else None

    @property
    def fwhm(self) -> float:
        """Combined FWHM in mm if the voxel size is known, else in voxels."""
        mm = self.fwhm_combined_mm
        return mm if mm is not None else self.fwhm_combined_vox


def _fwhm_1dif(image: FloatArray, mask: BoolArray) -> FloatArray:
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


def _acf_1d(image: FloatArray, mask: BoolArray, axis: int, max_lag: int) -> FloatArray:
    """Normalized spatial autocorrelation of `image` along `axis`, lags 0..max_lag.

    Follows AFNI `mri_estimate_ACF`: center by the in-mask mean and normalize by
    the in-mask variance, so `rho[d]` is the correlation of the noise field with
    itself `d` voxels apart along `axis`, over neighbor pairs that are *both* in
    `mask`. `rho[0]` is 1 by construction; a lag with too few in-mask pairs (or a
    constant frame) is NaN. A mask holding fewer than two voxels — which the
    working mask is whenever every voxel is constant over time — has neither a
    mean nor a variance to normalize by, so every lag is NaN.
    """
    rho = np.full(max_lag + 1, np.nan)
    rho[0] = 1.0
    vals = image[mask]
    if vals.size < 2:
        return rho
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


def _directional_acf(scaled: FloatArray, mask: BoolArray, max_lag: int) -> FloatArray:
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
    fluctuations: FloatArray,
    mask: BoolArray,
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
    fwhm_vox = (geomean(per[:, 0]), geomean(per[:, 1]))

    lag = min(max_lag, *(d - 1 for d in work_mask.shape[:2]))
    lags = np.arange(lag + 1)
    acf = _directional_acf(scaled, work_mask, lag)

    vm = normalize_voxel_mm(voxel_mm)
    return SmoothnessResult(
        fwhm_vox=fwhm_vox, lags=lags, acf=acf, voxel_mm=vm, pe_axis=pe_axis
    )
