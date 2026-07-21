"""Frozen dataclass value objects for the QA pipeline.

Immutable containers for scan metadata, the preprocessed images, and every
metric result. Derived quantities are properties computed from the stored
fields, so there is no redundant state to keep in sync. The raw-array
primitives the properties call live in `imaging` (the leaf layer), which keeps
this module free of any dependency on the operation modules.
"""

import warnings
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .constants import SIGMA_TO_FWHM, DetrendMethod
from .imaging import (
    _geomean,
    edge_valid_mask,
    fluctuation_noise,
    odd_even_difference,
    roi_indexes,
)


@dataclass(frozen=True)
class ScanMeta:
    """Human-readable acquisition metadata for the report header.

    Geometry (`voxel_mm`, `matrix`, `tr`) comes from the NIfTI header and is
    always present. The rest comes from the BIDS JSON sidecar written alongside
    the NIfTI (dcm2niix) and is `None` when no sidecar is found. `voxel_mm` is
    (row, col, slice-spacing) from the header zooms; `slice_thickness` is the
    excited slab from the sidecar (the zoom is spacing, which includes any gap).
    `pe_dir` is the DICOM row/col direction.
    """

    voxel_mm: tuple[float, float, float]
    matrix: tuple[int, int]
    tr: float
    te: float | None = None  # s
    flip_angle: float | None = None  # degrees
    slice_thickness: float | None = None  # mm
    pe_dir: str | None = None  # "row" / "col"
    coil: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    field_strength: float | None = None  # tesla
    software: str | None = None
    datetime: str | None = None  # acquisition date and/or time
    series: str | None = None


@dataclass(frozen=True, eq=False)
class QAImages:
    """The center slice and its detrended fluctuations, plus derived FBIRN images.

    Produced by `preprocess` before phantom detection. Only the center slice is
    retained — the full multi-slice 4-D volume can be discarded once this exists,
    and everything downstream (phantom geometry, Weisskoff, ghost, drift) reads
    from here. `fluctuations` is the per-voxel detrended residual, so ROI-averaging
    it equals detrending the ROI mean (detrending is a fixed linear operator that
    commutes with the spatial mean); `trend = center_slice - fluctuations` is the
    fitted low-frequency drift needed for drift/SFNR summaries. The summary images
    are derived properties so there is no redundant state to keep in sync.
    """

    center_slice: NDArray  # (X, Y, T) trimmed center slice (raw signal)
    fluctuations: NDArray  # (X, Y, T) detrended residuals
    tr: float
    pe_axis: int | None = None
    detrend_method: DetrendMethod = "poly"
    detrend_order: int | None = None  # poly degree / spline interior-knot count

    @property
    def trend(self) -> NDArray:
        """(X, Y, T) fitted low-frequency trend: signal minus fluctuations."""
        return self.center_slice - self.fluctuations

    @property
    def mean_image(self) -> NDArray:
        """(X, Y) temporal mean (FBIRN signal image)."""
        return self.center_slice.mean(axis=-1)

    @property
    def mip(self) -> NDArray:
        """(X, Y) max over time — phantom-segmentation target."""
        return self.center_slice.max(axis=-1)

    @property
    def valid_mask(self) -> NDArray:
        """(X, Y) real-data mask: True except on entirely-zeroed image edges.

        Detected from the time-MIP so a voxel that is ever nonzero counts as
        valid (see `edge_valid_mask`).
        """
        return edge_valid_mask(self.mip)

    @property
    def static_noise(self) -> NDArray:
        """(X, Y) odd/even difference (FBIRN static spatial noise)."""
        return odd_even_difference(self.center_slice)

    @property
    def fluctuation_noise(self) -> NDArray:
        """(X, Y) temporal RMS of the fluctuations."""
        return fluctuation_noise(self.fluctuations)


@dataclass(frozen=True, eq=False)
class PhantomGeometry:
    """Phantom location, computed by `detect_phantom` from `QAImages`."""

    phantom_mask: NDArray  # (X, Y) bool
    roi_center: NDArray  # (row, col) in array-index order — detected phantom center


@dataclass(frozen=True, eq=False)
class ROI:
    """A resolved square ROI: center (row, col, array order) and side length.

    Produced once by `resolve_roi` and threaded into the ROI-based statistics so
    the localization is computed a single time.
    """

    center: NDArray
    size: int

    @property
    def index(self) -> tuple[slice, slice]:
        """The (rows, cols) slice pair for indexing an image."""
        return roi_indexes(self.center, self.size)


@dataclass(frozen=True, eq=False)
class WeisskoffResult:
    """Weisskoff/RDC analysis over a range of ROI sizes.

    `cv` is the ROI-averaged CV and `cv1` the single-voxel CV pooled within each
    ROI size; `rdc_curve = cv1 / cv` is the effective decorrelation factor at
    each size (ideal = ROI width). `rdc` is the scalar value at the full ROI.
    """

    roi_sizes: NDArray
    cv: NDArray
    cv1: NDArray
    cv1_pooled: float
    rdc: float

    @property
    def rdc_curve(self) -> NDArray:
        """RDC at each ROI size: pooled single-voxel CV / ROI-averaged CV."""
        return self.cv1 / self.cv


@dataclass(frozen=True)
class SaturationResult:
    """ADC-saturation (signal-clipping) check for one scan.

    The clip ceiling is sequence-dependent and not recorded, so it is inferred:
    a clipped magnitude image piles up on a hardware `2**n - 1` rail. `ceiling`
    is that rail (in image units) when the series maximum sits on one, else
    `None` -- a maximum that is not a `2**n - 1` value means no clipping.
    """

    ceiling: float | None  # clip level (image units); None if max is not a 2**n-1 rail
    bits: int | None  # n such that the stored ceiling is 2**n - 1
    n_clipped_pre: int  # clipped samples in the dropped warm-up volumes
    n_clipped_kept: int  # clipped samples in the analyzed volumes (bias the metrics)
    worst_volume: int | None  # volume index (full series) with the most clipped samples
    worst_count: int  # clipped samples in that worst volume

    @property
    def n_clipped(self) -> int:
        """Total voxel*time samples pinned at the ceiling, across the full series."""
        return self.n_clipped_pre + self.n_clipped_kept

    @property
    def suspected(self) -> bool:
        """True if the series maximum sits exactly on a 2**n-1 hardware rail."""
        return self.ceiling is not None

    @property
    def clipped(self) -> bool:
        """True if any sample reaches that rail, anywhere in the series."""
        return self.n_clipped > 0

    @property
    def clipped_kept(self) -> bool:
        """True if clipping falls in the analyzed data, where it biases the metrics.

        Clips confined to the dropped warm-up volumes (`clipped and not
        clipped_kept`) don't affect the statistics — and are expected for
        sequences that deliberately acquire through the approach to steady state.
        """
        return self.n_clipped_kept > 0


@dataclass(frozen=True)
class OutlierResult:
    """Per-TR outlier-voxel fraction (AFNI 3dToutcount) over the phantom mask.

    `fraction[t]` is the share of masked voxels whose detrended residual is a
    statistical outlier at frame `t` -- a temporal-stability trace that spikes on
    a bad volume. `qthr` is the per-voxel chance level, so a clean run hovers
    near `qthr` and a spike stands well above it.
    """

    fraction: NDArray  # (n_t,) outlier-voxel fraction per frame
    n_voxels: int  # masked voxels (the fraction denominator)
    qthr: float  # per-voxel tail probability (expected chance fraction)

    @property
    def max_fraction(self) -> float:
        """Worst single-frame outlier fraction."""
        return float(self.fraction.max())

    @property
    def mean_fraction(self) -> float:
        """Mean outlier fraction across frames."""
        return float(self.fraction.mean())

    @property
    def worst_volume(self) -> int:
        """Frame index (within the analyzed series) with the most outliers."""
        return int(np.argmax(self.fraction))


@dataclass(frozen=True)
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


@dataclass(frozen=True)
class MotionResult:
    """Per-volume in-plane deformation of the phantom (thermal-drift model).

    A phantom is rigid and stationary, so between volumes it cannot rotate; what
    gradient heating *does* produce is a slow translation plus a scaling/shear of
    the image as the gradient calibration drifts. This is 3dvolreg's per-volume
    registration with the rotation degrees of freedom removed: each frame is
    aligned to the temporal-mean image under a 2-D affine restricted to
    translation + symmetric strain (anisotropic scale + shear) -- 5 parameters,
    no rotation.

    `params` is (n_t, 5); each row is that frame's fit relative to the reference
    (an all-zero row = perfectly aligned):

      0 dr, 1 dc  -- translation along array axes 0/1 (voxels)
      2 sr, 3 sc  -- fractional scaling along axes 0/1 (image grows where > 0)
      4 shear     -- symmetric off-diagonal strain (dimensionless)
    """

    params: NDArray  # (n_t, 5): dr, dc, sr, sc, shear
    voxel_mm: tuple[float, float] | None = None  # in-plane (axis0, axis1) mm/voxel

    @property
    def translation(self) -> NDArray:
        """(n_t, 2) per-volume translation along the two in-plane axes (voxels)."""
        return self.params[:, 0:2]

    @property
    def scale_pct(self) -> NDArray:
        """(n_t, 2) per-volume fractional scaling along each axis, as percent."""
        return 100.0 * self.params[:, 2:4]

    @property
    def shear_pct(self) -> NDArray:
        """(n_t,) per-volume symmetric shear, as percent."""
        return 100.0 * self.params[:, 4]

    @property
    def displacement(self) -> NDArray:
        """(n_t,) translation magnitude per volume, in mm if `voxel_mm` is known.

        Falls back to voxels when the in-plane voxel size is unavailable.
        """
        d = self.params[:, 0:2]
        if self.voxel_mm is not None:
            d = d * np.asarray(self.voxel_mm)
        return np.hypot(d[:, 0], d[:, 1])

    @property
    def max_translation(self) -> float:
        """Peak per-volume translation magnitude (voxels)."""
        return float(np.max(np.hypot(self.params[:, 0], self.params[:, 1])))

    @property
    def max_scale_pct(self) -> float:
        """Peak absolute scaling across both axes (percent)."""
        return float(np.max(np.abs(self.scale_pct)))

    @property
    def max_shear_pct(self) -> float:
        """Peak absolute shear (percent)."""
        return float(np.max(np.abs(self.shear_pct)))


@dataclass(frozen=True)
class CenterOfMassResult:
    """Per-volume intensity-weighted center of mass of the phantom (bxh volmeasures).

    `com` is (n_t, 2): each frame's intensity centroid along in-plane axes 0/1, in
    voxels within `[0, N)`, computed with a *circular* mean so a phantom sitting
    against a wrapped image edge yields the true centroid instead of aliasing to
    mid-FOV (MRI images are periodic under FFT reconstruction). The circular mean
    also makes a uniform background and the 180-degree Nyquist ghost self-cancel,
    so the centroid needs no phantom mask -- only missing data (a Siemens zeroed
    edge) is healed first (see `estimate_center_of_mass`). A rigid, stable phantom
    holds a fixed centroid; a slow ramp or a sudden jump in the trace flags drift,
    a spike, or gross instability the ROI-only GSQAP summaries miss. A cheap
    first-moment complement to `MotionResult` (registration-based deformation).

    `shape` is the in-plane array size `(N0, N1)` — the wrap periods, so
    displacements respect the periodic boundary; `voxel_mm` lets lengths be
    reported in mm.
    """

    com: NDArray  # (n_t, 2) per-frame circular COM (voxels, [0, N))
    shape: tuple[int, int]  # in-plane (N0, N1): the axis wrap periods
    voxel_mm: tuple[float, float] | None = None

    @property
    def reference(self) -> NDArray:
        """(2,) temporal-mean centroid: the circular mean of the per-frame COM."""
        n = np.asarray(self.shape, dtype=float)
        theta = self.com * (2.0 * np.pi / n)
        with warnings.catch_warnings():  # all-NaN axis -> NaN, not a warning
            warnings.simplefilter("ignore", RuntimeWarning)
            mean_theta = np.arctan2(
                np.nanmean(np.sin(theta), axis=0), np.nanmean(np.cos(theta), axis=0)
            )
        return (mean_theta % (2.0 * np.pi)) * n / (2.0 * np.pi)

    @property
    def deviation(self) -> NDArray:
        """(n_t, 2) signed per-frame displacement from the reference (voxels).

        Wrapped into `(-N/2, N/2]` per axis, so a centroid that crosses the
        periodic boundary yields a small displacement, not a full-FOV jump.
        """
        n = np.asarray(self.shape, dtype=float)
        d = self.com - self.reference
        return (d + n / 2.0) % n - n / 2.0

    @property
    def displacement(self) -> NDArray:
        """(n_t,) centroid displacement per volume (mm if known, else voxels)."""
        d = self.deviation
        if self.voxel_mm is not None:
            d = d * np.asarray(self.voxel_mm)
        return np.hypot(d[:, 0], d[:, 1])

    @property
    def max_displacement(self) -> float:
        """Peak per-volume centroid displacement (voxels); NaN if never resolved."""
        d = np.hypot(self.deviation[:, 0], self.deviation[:, 1])
        return float(np.nanmax(d)) if np.isfinite(d).any() else float("nan")


@dataclass(frozen=True)
class SmoothnessResult:
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
    lags: NDArray  # (n_lag,) integer voxel lags 0..L
    acf: NDArray  # (2, n_lag): per-axis autocorrelation
    voxel_mm: tuple[float, float] | None = None
    pe_axis: int | None = None  # array axis of the phase-encode direction

    # -- per-axis helpers ---------------------------------------------------- #
    def _mm_per(self, axis: int) -> float:
        """mm per voxel along `axis` (1.0 when the voxel size is unknown)."""
        return self.voxel_mm[axis] if self.voxel_mm is not None else 1.0

    def fwhm_axis(self, axis: int) -> float:
        """FWHM along an array `axis`, in mm if the voxel size is known, else voxels."""
        return self.fwhm_vox[axis] * self._mm_per(axis)

    def displacement(self, axis: int) -> NDArray:
        """Lag axis for `axis` as a length (mm if voxel size is known, else voxels)."""
        return self.lags * self._mm_per(axis)

    def psf_empirical(self, axis: int) -> NDArray:
        """Empirical PSF profile along `axis`: the squared noise autocorrelation.

        For white noise convolved with a PSF, the normalized spatial
        autocorrelation is the autocorrelation of the PSF; for a Gaussian PSF that
        equals `PSF**2`, so squaring the measured `acf` recovers the point-spread
        profile implied by the data at each sampled lag.
        """
        return self.acf[axis] ** 2

    def psf_model(self, x: NDArray, axis: int) -> NDArray:
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
        return _geomean(np.asarray(self.fwhm_vox))

    @property
    def fwhm_combined_mm(self) -> float | None:
        """Geometric-mean FWHM in mm (AFNI `ccomb`); None without voxel sizes."""
        mm = self.fwhm_mm
        return _geomean(np.asarray(mm)) if mm is not None else None

    @property
    def fwhm(self) -> float:
        """Combined FWHM in mm if the voxel size is known, else in voxels."""
        mm = self.fwhm_combined_mm
        return mm if mm is not None else self.fwhm_combined_vox


@dataclass(frozen=True)
class QAMetrics:
    """Settled scalar QA metrics for one scan."""

    snr: float
    sfnr: float
    rdc: float
    ghost_pct: float  # fBIRN percent ghost along PE: 100 * (mean ghost / mean signal)
    ghost_top_pct: float  # PE percent ghost of the brightest 10% of ghost voxels
    ro_ghost_pct: float  # same along the readout axis: background-relative baseline
    acr_ghost_pct: float  # ACR/AAPM-equivalent percent-signal-ghosting: |PE% - RO%|
    pe_axis: int | None  # phase-encode axis actually used for the ghost masks
    drift_pct: float
    percent_fluctuation: float
    weisskoff: WeisskoffResult
    saturation: SaturationResult
    outliers: OutlierResult
    spikes: SpikeResult
    motion: MotionResult
    center_of_mass: CenterOfMassResult
    smoothness: SmoothnessResult


@dataclass(frozen=True, eq=False)
class QAResult:
    """Full QA output: the intermediate objects plus the scalar metrics.

    Returned by `run_qa`. `metrics` holds the scalars; `images`/`geom`/`roi` are
    retained so a report can render the images, curves, and time series; `meta`
    carries the acquisition metadata (from the scan) for the report header.
    """

    images: QAImages
    geom: PhantomGeometry
    roi: ROI
    metrics: QAMetrics
    meta: ScanMeta | None = None
