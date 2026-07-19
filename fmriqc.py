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
from skimage import filters, morphology, segmentation

# Detrend cutoff period (s). Drift slower than this is removed before noise is
# measured. `poly` and `spline` historically used 200 vs 256; kept distinct
# because only `poly` feeds the settled pipeline.
POLY_CUTOFF_S = 200.0
SPLINE_CUTOFF_S = 256.0

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

    `pe_axis` is the phase-encode axis as a NIfTI voxel-array index (0/1/2),
    read from the header `dim_info` phase field. When `dim_info` is missing or
    invalid a warning is emitted and it falls back to the Nyquist-ghost estimate
    (or `None` if `estimate_pe=False`). Polarity is dropped (unneeded here).
    `meta` holds the human-readable acquisition metadata for the report; it is
    built from the BIDS JSON sidecar, which `from_nifti` requires.
    """

    data: NDArray  # (X, Y, Z, T)
    tr: float
    affine: NDArray | None = None
    pe_axis: int | None = None
    meta: ScanMeta | None = None

    @classmethod
    def from_nifti(cls, path: str | Path, estimate_pe: bool = True) -> "QAScan":
        sidecar = _load_sidecar(path)  # required; raises before the data load
        img = nib.load(str(path))
        zooms = img.header.get_zooms()
        data = img.get_fdata()

        pe_axis = _pe_axis_from_header(img.header)
        if pe_axis is None:
            msg = f"{path}: NIfTI dim_info has no valid phase-encode axis"
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

def trim_initial(data: NDArray, tr: float, trim_sec: float) -> NDArray:
    n = max(int(round(trim_sec / tr)), 0)
    return data[..., n:]

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
    images = preprocess(scan, trim_sec=trim_sec, detrend=detrend, center=center)
    geom = detect_phantom(images)

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
    )
    return QAResult(images=images, geom=geom, roi=roi, metrics=metrics,
                    meta=scan.meta)
