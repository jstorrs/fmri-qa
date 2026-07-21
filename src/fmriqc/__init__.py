import json
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, overload

import nibabel as nib
import numpy as np
from numpy.typing import NDArray
from scipy.interpolate import make_lsq_spline
from scipy import ndimage
from scipy.special import erfcinv
from skimage import filters, morphology, segmentation

# Detrend cutoff period (s). Drift slower than this is removed before noise is
# measured. `poly` and `spline` historically used 200 vs 256; kept distinct
# because only `poly` feeds the settled pipeline.
POLY_CUTOFF_S = 200.0
SPLINE_CUTOFF_S = 256.0

# Plausible ADC saturation rails. A clipped magnitude image piles up at a
# hardware 2**n - 1 ceiling; only these n are realistic for MR (12-bit -> 4095).
SATURATION_BITS = range(8, 17)  # 255 .. 65535

# Per-voxel tail probability for the outlier test (3dToutcount default): a clean
# voxel flags a sample this often by chance, so ~qthr is the expected fraction.
OUTLIER_QTHR = 0.001

# Per-volume registration budget (in-plane phantom motion). Phantom drift is
# sub-voxel, so a few Gauss-Newton steps converge; TOL is on the largest
# per-step parameter update (voxels for translation, fraction for strain).
MOTION_MAX_ITER = 12
MOTION_TOL = 1e-4

# Gaussian FWHM per standard deviation: sqrt(8 ln 2) (AFNI 3dFWHMx uses 2.35482).
SIGMA_TO_FWHM = float(np.sqrt(8.0 * np.log(2.0)))
# Lags (voxels) over which the directional noise autocorrelation / PSF is sampled.
SMOOTHNESS_MAX_LAG = 10

# Voxel layers peeled off the phantom to form the hi/lo core mask (AFNI
# 3dAutomask -erode 5) -- excludes edge / partial-volume / ghost-contaminated voxels.
HILO_ERODE = 5

# Fixed summary-ROI side (voxels). Glover/fBIRN uses 21; user-configurable.
FBIRN_ROI_SIZE = 21
# ROI localization mode. "image": middle slice + image-center ROI (Glover).
# "phantom": largest-cross-section slice + detected phantom-center ROI.
ROI_CENTER_MODES = ("image", "phantom")


# --------------------------------------------------------------------------- #
# Core types
# --------------------------------------------------------------------------- #

# DICOM in-plane phase-encode axis -> row/col: NIfTI i (axis 0) is the DICOM
# row direction, j (axis 1) the column direction (verified against dcm2niix
# InPlanePhaseEncodingDirectionDICOM on a Siemens acquisition).
_PE_ROWCOL = {0: "row", 1: "col"}


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
    te: float | None = None            # s
    flip_angle: float | None = None    # degrees
    slice_thickness: float | None = None  # mm
    pe_dir: str | None = None          # "row" / "col"
    coil: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    field_strength: float | None = None  # tesla
    software: str | None = None
    datetime: str | None = None        # acquisition date and/or time
    series: str | None = None


def _load_sidecar(path: str | Path) -> dict:
    """Parse the required BIDS JSON sidecar beside `path` (.nii/.nii.gz -> .json).

    dcm2niix writes this alongside every NIfTI it converts, so a missing sidecar
    means the input did not go through the expected conversion; we refuse it
    rather than silently dropping metadata. Raises `FileNotFoundError` if absent.
    """
    p = Path(path)
    name = p.name
    for ext in (".nii.gz", ".nii"):
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    sidecar = p.with_name(name + ".json")
    if not sidecar.is_file():
        raise FileNotFoundError(
            f"required BIDS JSON sidecar not found: {sidecar} "
            f"(convert the DICOM with dcm2niix so a .json is written alongside "
            f"the NIfTI)"
        )
    with open(sidecar) as f:
        return json.load(f)


def _acq_datetime(sidecar: dict) -> str | None:
    """Acquisition date/time from the sidecar, seconds-precision; None if absent.

    Siemens often anonymizes the date away, leaving only `AcquisitionTime`.
    """
    if dt := sidecar.get("AcquisitionDateTime"):
        return str(dt).split(".")[0].replace("T", " ")
    date, time = sidecar.get("AcquisitionDate"), sidecar.get("AcquisitionTime")
    time = str(time).split(".")[0] if time else None
    return " ".join(x for x in (date, time) if x) or None


def _pe_axis_from_sidecar(sidecar: dict) -> int | None:
    """PE axis (0/1/2) from the sidecar, or None if it carries no PE field.

    `PhaseEncodingDirection` (BIDS i/j/k, with an optional polarity we drop) maps
    straight to the array axis; `InPlanePhaseEncodingDirectionDICOM` (ROW/COL) is
    the DICOM fallback (row = i = axis 0, col = j = axis 1).
    """
    if ped := sidecar.get("PhaseEncodingDirection"):
        return {"i": 0, "j": 1, "k": 2}.get(str(ped)[0])
    if dicom := sidecar.get("InPlanePhaseEncodingDirectionDICOM"):
        return {"ROW": 0, "COL": 1}.get(str(dicom).upper())
    return None


def _pe_direction(pe_axis: int | None, sidecar: dict) -> str | None:
    """DICOM row/col phase-encode direction, preferring the sidecar."""
    if dicom := sidecar.get("InPlanePhaseEncodingDirectionDICOM"):
        return str(dicom).lower()
    if ped := sidecar.get("PhaseEncodingDirection"):
        return _PE_ROWCOL.get({"i": 0, "j": 1}.get(str(ped)[0], -1))
    return _PE_ROWCOL.get(pe_axis) if pe_axis is not None else None


def _scan_meta(img, sidecar: dict, pe_axis: int | None) -> ScanMeta:
    """Assemble `ScanMeta` from the NIfTI header and (optional) BIDS sidecar."""
    zooms = img.header.get_zooms()
    return ScanMeta(
        voxel_mm=(float(zooms[0]), float(zooms[1]), float(zooms[2])),
        matrix=(int(img.shape[0]), int(img.shape[1])),
        tr=float(zooms[3]),
        te=sidecar.get("EchoTime"),
        flip_angle=sidecar.get("FlipAngle"),
        slice_thickness=sidecar.get("SliceThickness"),
        pe_dir=_pe_direction(pe_axis, sidecar),
        coil=sidecar.get("ReceiveCoilName"),
        manufacturer=sidecar.get("Manufacturer"),
        model=sidecar.get("ManufacturersModelName"),
        serial=sidecar.get("DeviceSerialNumber"),
        field_strength=sidecar.get("MagneticFieldStrength"),
        software=sidecar.get("SoftwareVersions"),
        datetime=_acq_datetime(sidecar),
        series=sidecar.get("SeriesDescription"),
    )


@dataclass(frozen=True, eq=False)
class QAScan:
    """A raw QA acquisition plus the header metadata the pipeline needs.

    `pe_axis` is the phase-encode axis as a NIfTI voxel-array index (0/1/2). It
    comes from the sidecar `PhaseEncodingDirection` (authoritative), falling back
    to the header `dim_info` phase field, then — only if both are absent — to the
    Nyquist-ghost estimate (with a warning; `None` if `estimate_pe=False`).
    Polarity is dropped (unneeded here). `meta` holds the human-readable
    acquisition metadata for the report; both are built from the BIDS JSON
    sidecar, which `from_nifti` requires.
    """

    data: NDArray  # (X, Y, Z, T)
    tr: float
    affine: NDArray | None = None
    pe_axis: int | None = None
    meta: ScanMeta | None = None
    # NIfTI scl_slope/scl_inter, so saturation can recover stored integers from
    # `data` (in scaled image units). Default identity: `data` is already stored.
    slope: float = 1.0
    inter: float = 0.0

    @classmethod
    def from_nifti(cls, path: str | Path, estimate_pe: bool = True) -> "QAScan":
        sidecar = _load_sidecar(path)  # required; raises before the data load
        img = nib.load(str(path))
        zooms = img.header.get_zooms()
        data = img.get_fdata()
        slope, inter = img.header.get_slope_inter()  # (None, None) when unscaled

        pe_axis = _pe_axis_from_sidecar(sidecar)
        if pe_axis is None:
            pe_axis = _pe_axis_from_header(img.header)
        if pe_axis is None:
            msg = f"{path}: no phase-encode axis in sidecar or NIfTI dim_info"
            if estimate_pe:
                pe_axis = phase_encode_axis(data)
                msg += f"; falling back to ghost estimate (axis {pe_axis})"
            warnings.warn(msg, stacklevel=2)

        return cls(
            data=data,
            tr=float(zooms[3]),
            affine=img.affine,
            pe_axis=pe_axis,
            meta=_scan_meta(img, sidecar, pe_axis),
            slope=float(slope) if slope else 1.0,
            inter=float(inter) if inter else 0.0,
        )


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
    detrend_method: str = "poly"
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

    ceiling: float | None      # clip level (image units); None if max is not a 2**n-1 rail
    bits: int | None           # n such that the stored ceiling is 2**n - 1
    n_clipped_pre: int         # clipped samples in the dropped warm-up volumes
    n_clipped_kept: int        # clipped samples in the analyzed volumes (bias the metrics)
    worst_volume: int | None   # volume index (full series) with the most clipped samples
    worst_count: int           # clipped samples in that worst volume

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
    n_voxels: int      # masked voxels (the fraction denominator)
    qthr: float        # per-voxel tail probability (expected chance fraction)

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

    com: NDArray                 # (n_t, 2) per-frame circular COM (voxels, [0, N))
    shape: tuple[int, int]       # in-plane (N0, N1): the axis wrap periods
    voxel_mm: tuple[float, float] | None = None

    @property
    def reference(self) -> NDArray:
        """(2,) temporal-mean centroid: the circular mean of the per-frame COM."""
        n = np.asarray(self.shape, dtype=float)
        theta = self.com * (2.0 * np.pi / n)
        with warnings.catch_warnings():  # all-NaN axis -> NaN, not a warning
            warnings.simplefilter("ignore", RuntimeWarning)
            mean_theta = np.arctan2(np.nanmean(np.sin(theta), axis=0),
                                    np.nanmean(np.cos(theta), axis=0))
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
        """(n_t,) centroid displacement magnitude per volume (mm if known, else voxels)."""
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
    lags: NDArray                                # (n_lag,) integer voxel lags 0..L
    acf: NDArray                                 # (2, n_lag): per-axis autocorrelation
    voxel_mm: tuple[float, float] | None = None
    pe_axis: int | None = None                   # array axis of the phase-encode direction

    # -- per-axis helpers ---------------------------------------------------- #
    def _mm_per(self, axis: int) -> float:
        """mm per voxel along `axis` (1.0 when the voxel size is unknown)."""
        return self.voxel_mm[axis] if self.voxel_mm is not None else 1.0

    def fwhm_axis(self, axis: int) -> float:
        """FWHM along an array `axis`, in mm if the voxel size is known, else voxels."""
        return self.fwhm_vox[axis] * self._mm_per(axis)

    def displacement(self, axis: int) -> NDArray:
        """Lag axis for `axis` as a length (mm if the voxel size is known, else voxels)."""
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
        return (self.fwhm_vox[0] * self.voxel_mm[0],
                self.fwhm_vox[1] * self.voxel_mm[1])

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
    ro_ghost_pct: float  # same along the readout axis: background-relative baseline
    acr_ghost_pct: float  # ACR/AAPM-equivalent percent-signal-ghosting: |PE% - RO%|
    pe_axis: int | None  # phase-encode axis actually used for the ghost masks
    drift_pct: float
    percent_fluctuation: float
    weisskoff: WeisskoffResult
    saturation: SaturationResult
    outliers: OutlierResult
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


# --------------------------------------------------------------------------- #
# Preprocessing & phantom geometry
# --------------------------------------------------------------------------- #

def trim_count(tr: float, trim_sec: float) -> int:
    """Number of initial (non-steady-state) volumes dropped for `trim_sec`."""
    return max(int(round(trim_sec / tr)), 0)

def trim_initial(data: NDArray, tr: float, trim_sec: float) -> NDArray:
    return data[..., trim_count(tr, trim_sec):]

def segment_phantom(image: NDArray) -> NDArray:
    # mode="wrap": MRI images are periodic (FFT reconstruction), so the edge
    # filter must wrap rather than pad.
    edges = filters.sobel(image, mode="wrap")
    labels = np.zeros_like(image, dtype=np.uint8)
    labels[image < np.quantile(image, 0.1)] = 1
    labels[image > np.quantile(image, 0.9)] = 2
    return segmentation.watershed(edges, labels) == 2

def extract_center_slice(data: NDArray, center: str = "image") -> NDArray:
    """Select the QA slice from a volume.

    "image": the geometric middle slice (Glover/fBIRN convention).
    "phantom": the slice with the largest phantom cross-section (detected).
    """
    if center == "image":
        z = data.shape[2] // 2
    elif center == "phantom":
        mip = data.max(axis=-1)
        z = int(np.argmax([segment_phantom(s).sum() for s in np.moveaxis(mip, -1, 0)]))
    else:
        raise ValueError(f"unknown center {center!r}; choose from {ROI_CENTER_MODES}")
    return data[:, :, z, :]

def find_phantom_center(phantom_mask: NDArray) -> NDArray:
    dist = ndimage.distance_transform_edt(phantom_mask)
    roi_center = np.unravel_index(np.argmax(dist), dist.shape)
    return np.array(roi_center)

def roi_indexes(roi_center: NDArray, n: int) -> tuple[slice, slice]:
    # roi_center is (row, col) in array-index order; return (rows, cols) so
    # callers index as mask[roi]. Do NOT swap these — the notebooks' swapped
    # version transposes the ROI and only agrees when roi_center[0] == roi_center[1].
    p1 = roi_center - (n - 1) // 2
    p2 = p1 + n
    return slice(p1[0], p2[0]), slice(p1[1], p2[1])

def detect_phantom(images: "QAImages") -> PhantomGeometry:
    """Locate the phantom from the preprocessed images: mask and detected center."""
    phantom_mask = segment_phantom(images.mip)
    return PhantomGeometry(
        phantom_mask=phantom_mask,
        roi_center=find_phantom_center(phantom_mask),
    )


# --------------------------------------------------------------------------- #
# Detrending
# --------------------------------------------------------------------------- #

def spline_nodes(y: NDArray, tr: float, cutoff_s: float = SPLINE_CUTOFF_S) -> int:
    """Recommended number of interior knots: one spline segment per `cutoff_s`.

    The spline analogue of `poly_degree` — the fit-complexity knob for
    `spline_residuals`, separated so it can be computed once from the header.
    """
    nt = y.shape[-1]
    return max(int(round(nt * tr / cutoff_s)) - 1, 0)

def spline_residuals(
    y: NDArray[np.float64],
    n_nodes: int,
    degree: int = 2,
) -> NDArray[np.float64]:
    """Detrend along the last axis with a least-squares B-spline (handles N-D).

    A drop-in alternative to `poly_residuals`; `n_nodes` (interior knots, from
    `spline_nodes`) sets the fit complexity the way `degree` does for the poly.
    """
    nt = y.shape[-1]
    x = np.arange(nt, dtype=np.float64)

    # interior knots spread evenly over the fitted (steady-state) span
    t = np.concatenate((
        np.full(degree + 1, 0.0),
        np.linspace(0, nt, n_nodes + 2)[1:-1],
        np.full(degree + 1, nt),
    ))

    # Treat all leading-index combinations as separate signals: (nt, n_signals).
    signals = y.reshape(-1, nt).T
    fitted = make_lsq_spline(x, signals, t, k=degree)(x)
    return (signals - fitted).T.reshape(y.shape)

def poly_degree(y: NDArray, tr: float, cutoff_s: float = POLY_CUTOFF_S) -> int:
    n = y.shape[-1]
    return int(np.round(n * tr / cutoff_s))

def poly_residuals(y: NDArray, degree: int) -> NDArray:
    """Detrend along the last axis with Legendre polynomials (handles N-D)."""
    nt = y.shape[-1]
    x = np.linspace(-1.0, 1.0, nt, dtype=float)

    # Design matrix: (nt, degree + 1)
    design = np.polynomial.legendre.legvander(x, degree)

    # Treat all leading-index combinations as separate signals.
    signals = y.reshape(-1, nt).T

    # coefficients: (degree + 1, number_of_signals)
    coefficients, *_ = np.linalg.lstsq(design, signals, rcond=None)

    fitted = (design @ coefficients).T
    return y - fitted.reshape(y.shape)

DETREND_METHODS = ("poly", "spline")

def detrend_fn(center_slice: NDArray, tr: float,
               method: str = "poly") -> tuple[Callable[[NDArray], NDArray], int]:
    """Build a detrender `f(y) -> residuals` and its fit order for `method`.

    Complexity (poly degree / spline nodes) is derived once from the timeseries
    length and `tr`, then applied to the full slice and each ROI timeseries. The
    returned order is that complexity, surfaced for the report.
    """
    if method == "poly":
        degree = poly_degree(center_slice, tr)
        return (lambda y: poly_residuals(y, degree)), degree
    if method == "spline":
        n_nodes = spline_nodes(center_slice, tr)
        return (lambda y: spline_residuals(y, n_nodes)), n_nodes
    raise ValueError(f"unknown detrend method {method!r}; choose from {DETREND_METHODS}")


# --------------------------------------------------------------------------- #
# Noise metrics
# --------------------------------------------------------------------------- #

def fluctuation_noise(residuals: NDArray) -> NDArray:
    """Temporal RMS of detrended residuals (std about zero) over the last axis."""
    return np.std(residuals, axis=-1, mean=0)

def outlier_fraction(fluctuations: NDArray, mask: NDArray,
                     qthr: float = OUTLIER_QTHR) -> OutlierResult:
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
    resid = fluctuations[mask]                       # (n_vox, n_t)
    n_vox, n_t = resid.shape
    mad = np.median(np.abs(resid), axis=1)            # (n_vox,)
    alpha = float(np.sqrt(2.0) * erfcinv(2.0 * qthr / n_t))  # Q^-1(qthr / n_t)
    thr = alpha * np.sqrt(np.pi / 2.0) * mad          # per-voxel outlier threshold
    is_out = (np.abs(resid) > thr[:, None]) & (mad > 0)[:, None]
    return OutlierResult(
        fraction=is_out.sum(axis=0) / n_vox,
        n_voxels=int(n_vox),
        qthr=qthr,
    )

def _roi_cv(fluctuations: NDArray, mean_image: NDArray,
            roi_center: NDArray, k: int) -> float:
    """CV over a k x k ROI: RMS of the ROI-mean fluctuation / ROI-mean signal.

    ROI-averaging the per-voxel `fluctuations` equals detrending the ROI-mean
    timeseries (detrending commutes with the spatial mean), and the temporal
    mean of that timeseries is the ROI mean of `mean_image`.
    """
    roi = roi_indexes(roi_center, k)
    roi_fluct = fluctuations[*roi].mean(axis=(0, 1))
    return float(np.std(roi_fluct, mean=0) / mean_image[*roi].mean())

def _roi_cv1(fluctuation_noise: NDArray, mean_image: NDArray,
             roi_center: NDArray, k: int) -> float:
    """Single-voxel CV pooled over a k x k ROI: RMS(noise) / ROI mean signal."""
    roi = roi_indexes(roi_center, k)
    s = fluctuation_noise[*roi]
    return float(np.sqrt(np.mean(s**2)) / mean_image[*roi].mean())

def weisskoff(images: "QAImages", roi: ROI) -> WeisskoffResult:
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
    cv = np.array([
        _roi_cv(fluctuations, mean_image, roi.center, int(k))
        for k in roi_sizes
    ])
    cv1 = np.array([
        _roi_cv1(noise, mean_image, roi.center, int(k))
        for k in roi_sizes
    ])

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

def odd_even_difference(center_slice: NDArray) -> NDArray:
    """|mean(even frames) - mean(odd frames)| — a temporal-stability image."""
    even = center_slice[..., 0::2].mean(axis=-1)
    odd = center_slice[..., 1::2].mean(axis=-1)
    return np.abs(even - odd)

def image_center(shape: tuple[int, ...]) -> NDArray:
    """Geometric center (row, col) of an image, array-index order."""
    return np.array(shape[:2]) // 2

def _clamp_center(center: NDArray, n: int, shape: tuple[int, ...]) -> NDArray:
    """Shift `center` so an n x n ROI (per `roi_indexes`) stays within `shape`."""
    lo = (n - 1) // 2
    hi = n - lo
    return np.array([int(np.clip(center[i], lo, shape[i] - hi)) for i in (0, 1)])

def resolve_roi(images: "QAImages", geom: PhantomGeometry,
                roi_size: int = FBIRN_ROI_SIZE, center: str = "image") -> ROI:
    """Resolve the summary ROI once for a localization mode.

    "image": image-matrix center (Glover). "phantom": detected phantom center.
    The side is the fixed `roi_size` clamped to the image bounds, and the center
    is shifted if needed to keep the ROI on-image; whether it also fits inside the
    phantom is a separate check (see `roi_fits`).
    """
    shape = images.center_slice.shape[:2]
    n = min(roi_size, *shape)
    if center == "image":
        c = image_center(shape)
    elif center == "phantom":
        c = geom.roi_center
    else:
        raise ValueError(f"unknown ROI center {center!r}; choose from {ROI_CENTER_MODES}")
    return ROI(center=_clamp_center(c, n, shape), size=n)

def roi_fits(phantom_mask: NDArray, roi: tuple[slice, slice]) -> bool:
    """True if `roi` is on-image and every voxel of it lies inside the phantom.

    An out-of-bounds ROI (negative/overflowing slice) counts as not fitting —
    `np.all` of the empty selection it would produce is vacuously True otherwise.
    """
    (r, c), (h, w) = roi, phantom_mask.shape[:2]
    if r.start < 0 or c.start < 0 or r.stop > h or c.stop > w:
        return False
    return bool(np.all(phantom_mask[roi]))

def snr(images: "QAImages", roi: ROI) -> float:
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

def sfnr(images: "QAImages", roi: ROI) -> float:
    """fBIRN signal-to-fluctuation-noise ratio over a resolved ROI (Glover 2006).

    Mean over the ROI of the voxelwise SFNR image (temporal-mean signal divided
    by temporal fluctuation noise).
    """
    idx = roi.index
    sfnr_image = images.mean_image[*idx] / images.fluctuation_noise[*idx]
    return float(sfnr_image.mean())

def drift_percent(images: "QAImages", roi: ROI) -> float:
    """Peak-to-peak of the ROI-mean fitted trend, as % of the ROI mean signal."""
    idx = roi.index
    trend_roi = images.trend[*idx].mean(axis=(0, 1))
    signal = images.mean_image[*idx].mean()
    return float(100.0 * (trend_roi.max() - trend_roi.min()) / signal)

def percent_fluctuation(images: "QAImages", roi: ROI) -> float:
    """SD of the ROI-mean residual, as % of the ROI mean signal (fBIRN)."""
    idx = roi.index
    resid_roi = images.fluctuations[*idx].mean(axis=(0, 1))
    signal = images.mean_image[*idx].mean()
    return float(100.0 * np.std(resid_roi, mean=0) / signal)

def edge_valid_mask(image: NDArray) -> NDArray:
    """(X, Y) bool mask of real data, clearing only entirely-zeroed image edges.

    Some vendors (e.g. Siemens) null one outer image row/column to encode the
    phase-encode direction. A fully-zero border carries no signal and must not
    enter ROI averages or ghost statistics, but blanket-trimming one voxel on
    every side needlessly discards valid data on the other three. Each of the
    four edges is tested independently and only the zeroed ones are cleared.

    Pass the time-MIP for the most permissive test: a voxel that is nonzero in
    any frame counts as valid, so only a genuinely dead line is trimmed.
    """
    valid = np.ones(image.shape[:2], dtype=bool)
    if not image[0, :].any():
        valid[0, :] = False
    if not image[-1, :].any():
        valid[-1, :] = False
    if not image[:, 0].any():
        valid[:, 0] = False
    if not image[:, -1].any():
        valid[:, -1] = False
    return valid

def _ghost_masks(phantom_mask: NDArray, pe_axis: int, radius: int,
                 valid_mask: NDArray) -> tuple[NDArray, NDArray]:
    """Region-matched (signal, ghost) masks for a candidate PE axis.

    The ghost is the phantom rolled half the FOV along `pe_axis`; the ghost mask
    keeps the part of it that lands clear of the phantom (eroded, with the dilated
    phantom and any invalid image edge removed). The signal mask is that same
    ghost mask rolled back half the FOV onto the phantom, so the ratio compares
    each ghost patch against the exact tissue that produced it. The phantom/PE-
    ghost overlap zone -- where signal and ghost are superimposed and cannot be
    separated -- is thereby excluded from both masks. `valid_mask` (see
    `edge_valid_mask`) drops the ghost pixels that wrap onto a zeroed edge.
    """
    shift = phantom_mask.shape[pe_axis] // 2
    ghost = np.roll(phantom_mask, shift, axis=pe_axis)

    ghost_mask = (
        morphology.isotropic_erosion(ghost, radius)
        & ~morphology.isotropic_dilation(phantom_mask, radius)
        & valid_mask
    )
    signal_mask = np.roll(ghost_mask, -shift, axis=pe_axis)
    return signal_mask, ghost_mask

def ghost_ratio(
    mean_image: NDArray,
    phantom_mask: NDArray,
    pe_axis: int = 0,
    radius: int = 3,
    valid_mask: NDArray | None = None,
) -> float:
    """fBIRN Nyquist ghost-to-signal ratio (mean ghost / mean signal).

    The fBIRN "percent ghost" is 100x this value. The ghost is located by rolling
    the phantom half the FOV along the phase-encode axis; `pe_axis` and the
    erosion/dilation `radius` are acquisition-dependent and should be verified per
    protocol. `valid_mask` excludes zeroed image edges (see `edge_valid_mask`);
    it defaults to detecting them from `mean_image`.
    """
    if valid_mask is None:
        valid_mask = edge_valid_mask(mean_image)
    signal_mask, ghost_mask = _ghost_masks(phantom_mask, pe_axis, radius, valid_mask)
    return float(mean_image[ghost_mask].mean() / mean_image[signal_mask].mean())

def acr_ghosting_ratio(
    mean_image: NDArray,
    phantom_mask: NDArray,
    pe_axis: int = 0,
    radius: int = 3,
    valid_mask: NDArray | None = None,
) -> float:
    """ACR/AAPM-equivalent ghosting ratio from region-matched percent ghosts.

    The classic ACR/AAPM "percent-signal-ghosting" subtracts a background estimate
    (the frequency axis, which carries no N/2 ghost) from the phase-encode ghost,
    normalized by the central signal: |ghost_pe - ghost_freq| / signal. This builds
    the same contrast in fBIRN region-matched space: `ghost_ratio` is evaluated
    independently along the PE and frequency axes -- each ghost patch normalized by
    the exact tissue that produced it (`_ghost_masks`), with the phantom/ghost
    overlap zone excluded from both -- and the ACR-equivalent is the absolute
    difference of the two ratios.

    Because each direction carries its own matched denominator, the frequency-axis
    ratio is a genuine background-relative-to-signal baseline; subtracting it cancels
    the background exactly as ACR intends, without ACR's single-signal assumption
    (for a uniform phantom the two denominators coincide and this reduces to the
    classic form). 100x this value is the percent-signal-ghosting. `valid_mask`
    excludes zeroed image edges (see `edge_valid_mask`); it defaults to detecting
    them from `mean_image`.
    """
    if valid_mask is None:
        valid_mask = edge_valid_mask(mean_image)
    freq_axis = 1 - pe_axis
    pe = ghost_ratio(mean_image, phantom_mask, pe_axis, radius, valid_mask)
    ro = ghost_ratio(mean_image, phantom_mask, freq_axis, radius, valid_mask)
    return abs(pe - ro)

def _pe_axis_from_header(header) -> int | None:
    """PE axis from the NIfTI `dim_info` phase field, or None if unset/invalid.

    `dim_info` carries no polarity, which we don't need for ghost placement.
    """
    phase = header.get_dim_info()[1]
    return int(phase) if phase in (0, 1, 2) else None

def phase_encode_axis(data: NDArray, radius: int = 3) -> int:
    """Estimate the PE axis from a MIP over time and all slices.

    Collapsing time and slices concentrates the ghost, giving a stronger signal
    than any single slice — the fallback when no sidecar is available.
    """
    mip = data.max(axis=(-2, -1))  # (X, Y): max over Z and T
    return estimate_pe_axis(mip, segment_phantom(mip), radius=radius)

@overload
def estimate_pe_axis(
    mean_image: NDArray, phantom_mask: NDArray, radius: int = ...,
    return_ratios: Literal[False] = ..., *, valid_mask: NDArray | None = ...,
) -> int: ...
@overload
def estimate_pe_axis(
    mean_image: NDArray, phantom_mask: NDArray, radius: int = ...,
    *, return_ratios: Literal[True], valid_mask: NDArray | None = ...,
) -> tuple[int, dict[int, float]]: ...
def estimate_pe_axis(
    mean_image: NDArray,
    phantom_mask: NDArray,
    radius: int = 3,
    return_ratios: bool = False,
    valid_mask: NDArray | None = None,
) -> int | tuple[int, dict[int, float]]:
    """Guess the phase-encode axis from where the Nyquist ghost actually lands.

    Rolling the phantom along the *true* PE axis lines the ghost region up with
    real ghost signal (high mean); along the wrong axis it lands on background
    (low mean). The axis with the larger ghost-to-signal ratio wins.

    Returns the axis index (0 or 1), or `(axis, {axis: ratio})` if
    `return_ratios` is set. NOTE: shares the tuning caveats of `ghost_ratio` —
    verify against the acquisition's known PE direction before trusting it.
    """
    ratios = {
        axis: ghost_ratio(mean_image, phantom_mask, pe_axis=axis, radius=radius,
                          valid_mask=valid_mask)
        for axis in (0, 1)
    }
    best = max(ratios, key=ratios.__getitem__)
    return (best, ratios) if return_ratios else best


# --------------------------------------------------------------------------- #
# Saturation (ADC clipping)
# --------------------------------------------------------------------------- #

def _saturation_bits(stored_max: float) -> int | None:
    """Return n if `stored_max` is a `2**n - 1` rail for a plausible n, else None.

    `stored_max` is the series maximum in stored-integer units; it must round to
    an integer of the form `2**n - 1` (all low bits set) with n in
    `SATURATION_BITS`. A non-integer or off-rail maximum means no clipping.
    """
    k = round(stored_max)
    if abs(stored_max - k) > 1e-4 or k <= 0:
        return None
    if k & (k + 1):  # k+1 not a power of two -> k is not 2**n - 1
        return None
    n = k.bit_length()  # k = 2**n - 1  ->  bit_length is n
    return n if n in SATURATION_BITS else None


def detect_saturation(data: NDArray, slope: float = 1.0, inter: float = 0.0,
                      trim: int = 0) -> SaturationResult:
    """Detect ADC saturation (signal clipped at a `2**n - 1` rail) in a 4-D series.

    The clip ceiling is sequence-dependent and unrecorded, so it is inferred
    from the data: reconstructed magnitude images are stored as unsigned
    integers, so a clipped acquisition piles up on the hardware rail `2**n - 1`
    (12-bit ADC -> 4095 is the classic case). A series maximum that is not a
    `2**n - 1` value means no clipping occurred and the check reports clean.

    `slope`/`inter` recover the stored integer from scaled image units for the
    rail test; the pile-up is then counted in image units, where every clipped
    voxel shares the identical maximum value. The full untrimmed series is
    checked because clipping is worst in the high-signal warm-up volumes -- but
    the count is split at `trim` (the number of initial volumes the analysis
    drops): clips in the first `trim` volumes (`n_clipped_pre`) don't reach the
    statistics, while clips in the kept volumes (`n_clipped_kept`) bias them.
    A lone sample on the rail is likely a bright voxel; a pile-up is saturation.
    """
    ceiling = float(np.max(data))
    bits = _saturation_bits((ceiling - inter) / slope)
    if bits is None:
        return SaturationResult(ceiling=None, bits=None, n_clipped_pre=0,
                                n_clipped_kept=0, worst_volume=None, worst_count=0)
    per_volume = (data == ceiling).reshape(-1, data.shape[-1]).sum(axis=0)
    worst = int(np.argmax(per_volume))
    return SaturationResult(
        ceiling=ceiling,
        bits=bits,
        n_clipped_pre=int(per_volume[:trim].sum()),
        n_clipped_kept=int(per_volume[trim:].sum()),
        worst_volume=worst,
        worst_count=int(per_volume[worst]),
    )


# --------------------------------------------------------------------------- #
# In-plane motion (phantom deformation)
# --------------------------------------------------------------------------- #

def _register_norotate(moving: NDArray, reference: NDArray, rr: NDArray,
                       cc: NDArray, center: NDArray, mask: NDArray,
                       max_iter: int, tol: float) -> NDArray:
    """Register one frame to `reference` under translation + symmetric strain.

    Forward-additive Lucas-Kanade for the 5-parameter warp
    `W(x) = center + U (x - center) + t`, with `U = [[1+sr, h], [h, 1+sc]]`
    symmetric (scale + shear, **no rotation**) and `t = (dr, dc)`. Each step
    warps `moving` by the current parameters, then solves the Gauss-Newton normal
    equations over `mask` for the additive update; the warp Jacobian is linear in
    the (centered) coordinates `rr`/`cc` and independent of the parameters, so the
    additive scheme is exact up to the image interpolation. Returns
    `[dr, dc, sr, sc, h]`, the frame's pose relative to the reference.
    """
    m = mask.ravel()
    ref = reference.ravel()[m]
    rrm, ccm = rr.ravel()[m], cc.ravel()[m]
    p = np.zeros(5)
    for _ in range(max_iter):
        u = np.array([[1.0 + p[2], p[4]], [p[4], 1.0 + p[3]]])
        offset = center - u @ center + p[:2]
        # affine_transform samples moving at u @ o + offset for output pixel o,
        # i.e. it pulls the frame back onto the reference grid under W.
        warped = ndimage.affine_transform(moving, u, offset=offset, order=1,
                                          mode="nearest")
        gr, gc = np.gradient(warped)  # d/axis0, d/axis1 of the warped frame
        gr, gc = gr.ravel()[m], gc.ravel()[m]
        # steepest-descent images = grad(W) . dW/dp for p = [dr, dc, sr, sc, h]
        sd = np.stack([gr, gc, gr * rrm, gc * ccm, gr * ccm + gc * rrm], axis=1)
        err = warped.ravel()[m] - ref
        try:
            dp = np.linalg.solve(sd.T @ sd, sd.T @ err)
        except np.linalg.LinAlgError:
            break
        p = p - dp
        if np.max(np.abs(dp)) < tol:
            break
    return p


def estimate_motion(center_slice: NDArray, mask: NDArray,
                    voxel_mm: tuple[float, float] | None = None,
                    max_iter: int = MOTION_MAX_ITER,
                    tol: float = MOTION_TOL) -> MotionResult:
    """Per-volume in-plane registration of the phantom to its temporal mean.

    3dvolreg-style motion estimation specialized for a rigid phantom: the model
    is a 2-D affine with the rotation dropped -- translation + symmetric strain
    (anisotropic scale + shear) -- because a stationary phantom cannot rotate,
    while gradient heating translates, scales, and shears the image. Each frame
    of `center_slice` (X, Y, T) is aligned to the temporal-mean image by
    forward-additive Lucas-Kanade over `mask` (the phantom), pivoting the strain
    at the phantom centroid so translation and deformation stay separable.
    Returns the per-frame `[dr, dc, sr, sc, shear]`; `voxel_mm` (in-plane, from
    the header) is carried through so displacements can be reported in mm.
    """
    reference = center_slice.mean(axis=-1)
    r_idx, c_idx = np.nonzero(mask)
    center = (np.array([r_idx.mean(), c_idx.mean()]) if r_idx.size
              else np.array(reference.shape[:2], dtype=float) / 2.0)
    rows, cols = np.indices(reference.shape[:2]).astype(float)
    rr, cc = rows - center[0], cols - center[1]

    nt = center_slice.shape[-1]
    params = np.zeros((nt, 5))
    for t in range(nt):
        params[t] = _register_norotate(center_slice[..., t], reference, rr, cc,
                                       center, mask, max_iter, tol)
    vm = (float(voxel_mm[0]), float(voxel_mm[1])) if voxel_mm is not None else None
    return MotionResult(params=params, voxel_mm=vm)


# --------------------------------------------------------------------------- #
# Center of mass (per-volume intensity centroid, circular)
# --------------------------------------------------------------------------- #

def estimate_center_of_mass(center_slice: NDArray,
                            valid_mask: NDArray | None = None,
                            voxel_mm: tuple[float, float] | None = None
                            ) -> CenterOfMassResult:
    """Per-volume intensity-weighted center of mass of the phantom (circular).

    bxh `fmriqa_volmeasures`' center-of-mass trace, specialized to the QA center
    slice: for each frame, the intensity centroid along each in-plane axis via a
    *circular* mean -- every coordinate is mapped to an angle `2*pi*x/N`, the
    intensity-weighted mean unit vector is formed over the **whole periodic grid**,
    and its angle mapped back to `[0, N)`. Three properties follow from the
    circular mean on the periodic FOV (MRI images wrap under FFT reconstruction),
    and together they mean the centroid needs no phantom segmentation -- which
    would in fact *harm* it, by carving the grid into a sub-region and destroying
    the full-period symmetry the first two properties rely on:

    * A phantom straddling a wrapped image edge yields the true centroid instead
      of aliasing to mid-FOV.
    * A **uniform background** contributes *zero* net vector -- a full period of
      unit vectors sums to zero (`sum_x exp(i 2pi x/N) = 0`) -- so a flat noise
      floor does not pull the centroid no matter how many background voxels there
      are. (This is what a linear COM cannot do: there, uniform background drags
      the centroid toward image center, forcing a mask.)
    * The **Nyquist ghost** sits at exactly half-FOV = 180 degrees, so along the
      phase-encode axis each ghost voxel is anti-parallel to its source (it
      cancels, biasing the angle not at all) and along the readout axis it is
      co-located (it reinforces the correct position). Either way the ghost cannot
      shift the centroid.

    The one thing that *does* break the background cancellation is **missing
    data** -- e.g. an outer row/column a vendor (Siemens) nulls to encode the PE
    direction. A nulled line is a hole punched in the otherwise-uniform background
    ring, and relative to a complete floor (which sums to zero) that hole injects
    a residual vector along the axis. It is healed rather than masked out: the
    background pedestal (the lowest *valid* magnitude) is subtracted so the floor
    sits at ~0, and the invalid voxels are then set to 0 -- so the gap matches the
    now-zero background instead of a hole in the ring. `valid_mask` (True = real
    data) defaults to `edge_valid_mask` of the time-MIP, which detects exactly the
    zeroed-edge case; pass one to override. Pedestal subtraction also removes the
    background DC term outright, so the phantom (the dominant above-floor signal)
    sets the resultant more cleanly than symmetry cancellation alone.

    Weights are the per-frame magnitudes above the (fixed) pedestal, so the trace
    tracks where the signal actually sits over time. Complements `estimate_motion`
    (registration-based deformation) with a cheap first-moment centroid.

    `center_slice` is (X, Y, T); `voxel_mm` (in-plane, from the header) is carried
    so displacements can be reported in mm.
    """
    shape = (int(center_slice.shape[0]), int(center_slice.shape[1]))
    nt = center_slice.shape[-1]
    if valid_mask is None:
        valid_mask = edge_valid_mask(center_slice.max(axis=-1))

    # Heal missing data before the circular mean: shift the background floor to ~0
    # by subtracting the lowest valid magnitude, then zero the invalid voxels so a
    # nulled edge matches the now-zero background rather than punching a hole in
    # the periodic ring. The pedestal is a single scalar (constant across frames),
    # so it does not perturb the frame-to-frame centroid tracking.
    valid_vals = center_slice[valid_mask]
    pedestal = float(valid_vals.min()) if valid_vals.size else 0.0
    weights = np.clip(center_slice - pedestal, 0.0, None)
    weights[~valid_mask] = 0.0
    W = weights.reshape(-1, nt)                       # (npix, n_t)

    idx = np.indices(shape).reshape(2, -1)           # (2, npix): full periodic grid
    total = W.sum(axis=0)                             # (n_t,)
    good = total > 0                                  # blank frames -> NaN centroid
    com = np.full((nt, 2), np.nan)
    for axis in (0, 1):
        theta = idx[axis] * (2.0 * np.pi / shape[axis])
        ang = np.arctan2(np.sin(theta) @ W, np.cos(theta) @ W)
        com[good, axis] = (ang[good] % (2.0 * np.pi)) * shape[axis] / (2.0 * np.pi)

    vm = (float(voxel_mm[0]), float(voxel_mm[1])) if voxel_mm is not None else None
    return CenterOfMassResult(com=com, shape=shape, voxel_mm=vm)


# --------------------------------------------------------------------------- #
# Spatial smoothness (FWHM)
# --------------------------------------------------------------------------- #

def _geomean(x: NDArray) -> float:
    """Geometric mean over the positive, finite entries; NaN if there are none."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x) & (x > 0)]
    return float(np.exp(np.mean(np.log(x)))) if x.size else float("nan")


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
        per = np.array([_acf_1d(scaled[..., t], mask, axis, max_lag)
                        for t in range(nt)])
        with warnings.catch_warnings():  # all-NaN lag columns -> NaN, not a warning
            warnings.simplefilter("ignore", RuntimeWarning)
            acf[axis] = np.nanmean(per, axis=0)
    return acf


def estimate_smoothness(fluctuations: NDArray, mask: NDArray,
                        voxel_mm: tuple[float, float] | None = None,
                        pe_axis: int | None = None,
                        max_lag: int = SMOOTHNESS_MAX_LAG) -> SmoothnessResult:
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
    mad = np.median(np.abs(centered), axis=-1)          # (X, Y)
    work_mask = mask & (mad > 0)
    scaled = centered / np.where(mad > 0, mad, 1.0)[..., None]

    nt = scaled.shape[-1]
    per = np.array([_fwhm_1dif(scaled[..., t], work_mask) for t in range(nt)])
    fwhm_vox = (_geomean(per[:, 0]), _geomean(per[:, 1]))

    lag = min(max_lag, *(d - 1 for d in work_mask.shape[:2]))
    lags = np.arange(lag + 1)
    acf = _directional_acf(scaled, work_mask, lag)

    vm = (float(voxel_mm[0]), float(voxel_mm[1])) if voxel_mm is not None else None
    return SmoothnessResult(fwhm_vox=fwhm_vox, lags=lags, acf=acf, voxel_mm=vm,
                            pe_axis=pe_axis)


# --------------------------------------------------------------------------- #
# Preprocessing & orchestration
# --------------------------------------------------------------------------- #

def preprocess(scan: QAScan, trim_sec: float = 5.0, detrend: str = "poly",
               center: str = "image") -> QAImages:
    """Trim, select the QA slice, and compute the FBIRN summary images.

    Returns `QAImages` (center slice, detrended fluctuations, and derived summary
    images); the caller can discard `scan.data` afterwards. `detrend` selects the
    detrending method ("poly"/"spline"); `center` selects the slice — "image" for
    the middle slice (Glover), "phantom" for the largest phantom cross-section.
    """
    data = trim_initial(scan.data, scan.tr, trim_sec)
    center_slice = extract_center_slice(data, center)
    detrend_op, detrend_order = detrend_fn(center_slice, scan.tr, detrend)
    fluctuations = detrend_op(center_slice)
    return QAImages(
        center_slice=center_slice,
        fluctuations=fluctuations,
        tr=float(scan.tr),
        pe_axis=scan.pe_axis,
        detrend_method=detrend,
        detrend_order=detrend_order,
    )

def run_qa(
    scan: QAScan,
    trim_sec: float = 5.0,
    pe_axis: int | None = None,
    detrend: str = "poly",
    center: str = "image",
    roi_size: int = FBIRN_ROI_SIZE,
) -> QAResult:
    """Full pipeline: scan -> preprocess -> phantom -> Weisskoff/RDC + ghost ratio.

    `pe_axis=None` estimates the phase-encode axis from the ghost regions.
    `detrend` selects the detrending method ("poly" or "spline").
    `center` localizes both the QA slice and the ROI: "image" (middle slice +
    image-center ROI, Glover) or "phantom" (largest slice + detected center).
    `roi_size` is the fixed summary/Weisskoff ROI side (default 21, fBIRN).
    """
    # Saturation is checked on the full untrimmed series: clipping is worst in
    # the high-signal warm-up volumes that preprocessing drops. The count is
    # split at the same trim boundary so clips outside the analyzed data (which
    # don't bias the metrics) are reported apart from clips that do.
    saturation = detect_saturation(scan.data, scan.slope, scan.inter,
                                   trim=trim_count(scan.tr, trim_sec))

    images = preprocess(scan, trim_sec=trim_sec, detrend=detrend, center=center)
    geom = detect_phantom(images)

    # 3dvolreg-style per-volume registration of the phantom to its temporal mean,
    # under a rotation-free (translation + scale + shear) model -- a diagnostic
    # of gradient-heating deformation. The analyzed series is NOT resampled from
    # this fit, so the FBIRN metrics stay measured on the acquired data.
    voxel_mm = scan.meta.voxel_mm[:2] if scan.meta else None
    motion = estimate_motion(images.center_slice, geom.phantom_mask,
                             voxel_mm=voxel_mm)
    # Per-volume intensity centroid (bxh volmeasures), circular so a phantom
    # against a wrapped edge does not alias and -- crucially -- so a uniform
    # background and the 180-degree Nyquist ghost self-cancel; no phantom mask is
    # used (it would break that cancellation). The valid mask only heals missing
    # data (a Siemens zeroed edge). A cheap first-moment trace alongside `motion`.
    com = estimate_center_of_mass(images.center_slice, images.valid_mask,
                                  voxel_mm=voxel_mm)

    roi = resolve_roi(images, geom, roi_size, center)
    if not roi_fits(geom.phantom_mask, roi.index):
        warnings.warn(
            f"{roi.size}x{roi.size} ROI ({center} center) is not fully inside the "
            f"phantom; reduce roi_size or try center='image'.",
            stacklevel=2,
        )

    wk = weisskoff(images, roi)
    mean_image = images.mean_image
    valid_mask = images.valid_mask
    if pe_axis is None:
        pe_axis = images.pe_axis
    if pe_axis is None:
        pe_axis = estimate_pe_axis(mean_image, geom.phantom_mask,
                                   valid_mask=valid_mask)
    # Region-matched percent ghost on each in-plane axis; the ACR-equivalent is
    # their difference (see `acr_ghosting_ratio`). Computing both here avoids
    # re-deriving the PE ratio inside `acr_ghosting_ratio`.
    pe_ratio = ghost_ratio(mean_image, geom.phantom_mask, pe_axis=pe_axis,
                           valid_mask=valid_mask)
    ro_ratio = ghost_ratio(mean_image, geom.phantom_mask, pe_axis=1 - pe_axis,
                           valid_mask=valid_mask)

    # Directional spatial smoothness (AFNI 3dFWHMx): the Gaussian FWHM of the
    # detrended noise field along PE and RO, plus the point-spread curves -- the
    # correlation-length confound the guide warns the Weisskoff RDC is measured
    # against. Computed here so the resolved `pe_axis` labels the directions.
    smoothness = estimate_smoothness(images.fluctuations, geom.phantom_mask,
                                     voxel_mm=voxel_mm, pe_axis=pe_axis)

    metrics = QAMetrics(
        snr=snr(images, roi),
        sfnr=sfnr(images, roi),
        rdc=wk.rdc,
        ghost_pct=100.0 * pe_ratio,
        ro_ghost_pct=100.0 * ro_ratio,
        acr_ghost_pct=100.0 * abs(pe_ratio - ro_ratio),
        pe_axis=pe_axis,
        drift_pct=drift_percent(images, roi),
        percent_fluctuation=percent_fluctuation(images, roi),
        weisskoff=wk,
        saturation=saturation,
        outliers=outlier_fraction(images.fluctuations, geom.phantom_mask),
        motion=motion,
        center_of_mass=com,
        smoothness=smoothness,
    )
    return QAResult(images=images, geom=geom, roi=roi, metrics=metrics,
                    meta=scan.meta)


# --------------------------------------------------------------------------- #
# High/low flip-angle noise separation (thermal vs. instability)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class HiLoResult:
    """Thermal vs. instability noise separation from a high/low flip-angle pair.

    Greve's high/low flip-angle QA (`bxh-fmriqa-hilo.md`): two phantom runs that
    differ *only* in flip angle let the two noise sources be separated, because
    thermal (additive) noise variance is independent of signal level while
    instability (multiplicative: drift, gradient heating, physiological-like
    fluctuation) noise variance scales with signal squared. With the squared
    signal ratio `M = (mean_high / mean_low)**2`,

        var_high = thermal_var + M * instability_var0
        var_low  = thermal_var +     instability_var0

    which solve to `thermal_var = (M*var_low - var_high)/(M - 1)` and
    `instability_var = var_high - thermal_var`. If measurement noise drives
    `instability_var` negative, it falls back to `thermal_var = var_low`,
    `instability_var = var_high - var_low` (`fell_back` records this).

    All statistics are pooled over the shared eroded phantom core: `mean_*` is the
    core-mean of the per-voxel temporal mean; `var_*` is the *square* of the
    core-mean per-voxel temporal SD of the detrended residual (the note's
    `ROIstats` on the `stddev` image, then squared). `flip_high`/`flip_low` are
    the sidecar flip angles, carried for the report and the ordering check.
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
        """Squared signal ratio `(mean_high / mean_low)**2`."""
        return (self.mean_high / self.mean_low) ** 2

    @property
    def thermal_fsnr(self) -> float:
        """Functional SNR of the thermal component: `mean_high / sqrt(thermal_var)`.

        NaN if the separated thermal variance is non-positive (an unphysical
        result that means the model did not fit -- e.g. near-equal flip signals).
        """
        return (self.mean_high / np.sqrt(self.thermal_var)
                if self.thermal_var > 0 else float("nan"))

    @property
    def instability_fsnr(self) -> float:
        """Functional SNR of the instability component.

        `mean_high / sqrt(instability_var)`; infinite when no instability is
        detected (`instability_var == 0`), NaN if it is negative.
        """
        if self.instability_var > 0:
            return self.mean_high / np.sqrt(self.instability_var)
        return float("inf") if self.instability_var == 0 else float("nan")

    @property
    def instability_fraction(self) -> float:
        """Share of the high-flip variance attributed to instability noise."""
        return (self.instability_var / self.var_high
                if self.var_high > 0 else float("nan"))


def separate_noise(mean_high: float, mean_low: float,
                   var_high: float, var_low: float,
                   n_voxels: int = 0,
                   flip_high: float | None = None,
                   flip_low: float | None = None) -> HiLoResult:
    """Thermal/instability variance split from pooled hi/lo statistics (pure algebra).

    The flip-angle noise-separation math of `HiLoResult`; `run_hilo` computes the
    pooled `mean_*`/`var_*` from a scan pair and calls this. Kept separate so the
    algebra can be exercised directly.
    """
    m = (mean_high / mean_low) ** 2
    thermal_var = (m * var_low - var_high) / (m - 1.0)
    instability_var = var_high - thermal_var
    fell_back = instability_var < 0.0
    if fell_back:  # measurement noise pushed instability negative -- Greve fallback
        thermal_var = var_low
        instability_var = var_high - var_low
    return HiLoResult(
        mean_high=mean_high, mean_low=mean_low,
        var_high=var_high, var_low=var_low,
        thermal_var=thermal_var, instability_var=instability_var,
        n_voxels=n_voxels, fell_back=fell_back,
        flip_high=flip_high, flip_low=flip_low,
    )


def phantom_core_mask(volume: NDArray, erode: int = HILO_ERODE) -> NDArray:
    """Eroded phantom-core mask of a 3-D image (AFNI `3dAutomask -q -erode` analogue).

    Segments the phantom from the temporal-mean `volume` with the same watershed
    used in-plane (`segment_phantom`, applied to the whole volume — its Sobel /
    quantile / watershed steps are all dimension-agnostic), keeps the largest
    connected component with its interior holes filled, then peels `erode` voxel
    layers so the core excludes edge and partial-volume voxels — matching the
    note's `3dAutomask -q -erode 5`.
    """
    mask = ndimage.binary_fill_holes(segment_phantom(volume))
    labels, n = ndimage.label(mask)
    if n > 1:  # keep the largest connected component only
        sizes = np.bincount(labels.ravel())
        sizes[0] = 0
        mask = labels == int(np.argmax(sizes))
    if erode > 0:
        mask = ndimage.binary_erosion(mask, iterations=erode)
    return mask


def _hilo_stats(scan: QAScan, trim_sec: float, detrend: str,
                erode: int) -> tuple[NDArray, NDArray, NDArray]:
    """(temporal-mean map, temporal-SD-of-residual map, eroded core mask) for a scan.

    The whole 3-D volume is used (not a single slice): thermal/instability
    separation is a global scanner property. The series is trimmed like the rest
    of the pipeline, the mean map is taken on the trimmed signal, and the SD map
    on the per-voxel detrended residual (poly degree scaled to this scan's own run
    length, as elsewhere). The core mask comes from the mean map.
    """
    data = trim_initial(scan.data, scan.tr, trim_sec)   # (X, Y, Z, T)
    mean_map = data.mean(axis=-1)
    detrend_op, _ = detrend_fn(data, scan.tr, detrend)
    sd_map = fluctuation_noise(detrend_op(data))
    return mean_map, sd_map, phantom_core_mask(mean_map, erode)


def run_hilo(high: QAScan, low: QAScan, trim_sec: float = 5.0,
             detrend: str = "poly", erode: int = HILO_ERODE) -> HiLoResult:
    """Separate thermal from instability noise using a high/low flip-angle scan pair.

    Following `bxh-fmriqa-hilo.md`: `high` and `low` must be the same acquisition
    except for flip angle (the high-flip run first). Each scan is reduced to a
    temporal-mean map and a temporal-SD-of-residual map over the whole volume
    (`_hilo_stats`), and the statistics are pooled over the **shared** eroded
    phantom core — the intersection of the two scans' core masks — so `mean_high`
    and `mean_low` are averaged over identical voxels. `separate_noise` then does
    the flip-angle algebra. Raises if the two geometries differ or their cores do
    not overlap.
    """
    fh = high.meta.flip_angle if high.meta else None
    fl = low.meta.flip_angle if low.meta else None
    if fh is not None and fl is not None and fh <= fl:
        warnings.warn(
            f"high-flip scan flip angle ({fh:g}) is not greater than the low-flip "
            f"scan ({fl:g}); check the argument order (high first, low second).",
            stacklevel=2,
        )

    mean_h, sd_h, core_h = _hilo_stats(high, trim_sec, detrend, erode)
    mean_l, sd_l, core_l = _hilo_stats(low, trim_sec, detrend, erode)
    if mean_h.shape != mean_l.shape:
        raise ValueError(
            f"high/low scans have different geometry {mean_h.shape} vs "
            f"{mean_l.shape}; they must be the same acquisition except flip angle."
        )

    core = core_h & core_l
    n = int(core.sum())
    if n == 0:
        raise ValueError(
            "high/low phantom cores do not overlap; cannot pool statistics "
            "(check that both scans image the same phantom, or lower --erode)."
        )

    mean_high = float(mean_h[core].mean())
    mean_low = float(mean_l[core].mean())
    var_high = float(sd_h[core].mean()) ** 2   # (core-mean per-voxel SD)**2, per the note
    var_low = float(sd_l[core].mean()) ** 2
    return separate_noise(mean_high, mean_low, var_high, var_low,
                          n_voxels=n, flip_high=fh, flip_low=fl)
