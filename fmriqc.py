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

@dataclass(frozen=True, eq=False)
class QAScan:
    """A raw QA acquisition plus the header metadata the pipeline needs.

    `pe_axis` is the phase-encode axis as a NIfTI voxel-array index (0/1/2),
    read from the header `dim_info` phase field. When `dim_info` is missing or
    invalid a warning is emitted and it falls back to the Nyquist-ghost estimate
    (or `None` if `estimate_pe=False`). Polarity is dropped (unneeded here).
    """

    data: NDArray  # (X, Y, Z, T)
    tr: float
    voxel_size: float
    affine: NDArray | None = None
    pe_axis: int | None = None

    @classmethod
    def from_nifti(cls, path: str | Path, estimate_pe: bool = True) -> "QAScan":
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
            voxel_size=float(zooms[0]),
            affine=img.affine,
            pe_axis=pe_axis,
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
    voxel_size: float
    pe_axis: int | None = None
    detrend_method: str = "poly"

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
    """Weisskoff/RDC analysis: the CV-vs-ROI-size curve and its scalar RDC."""

    roi_sizes: NDArray
    cv: NDArray
    cv1_pooled: float
    rdc: float


@dataclass(frozen=True)
class QAMetrics:
    """Settled scalar QA metrics for one scan."""

    snr: float
    sfnr: float
    rdc: float
    ghost_ratio: float
    weisskoff: WeisskoffResult
    # TODO: drift_pct once settled in the notebooks.


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
               method: str = "poly") -> Callable[[NDArray], NDArray]:
    """Build a detrender `f(y) -> residuals` for the chosen `method`.

    Complexity (poly degree / spline nodes) is derived once from the timeseries
    length and `tr`, then applied to the full slice and each ROI timeseries.
    """
    if method == "poly":
        degree = poly_degree(center_slice, tr)
        return lambda y: poly_residuals(y, degree)
    if method == "spline":
        n_nodes = spline_nodes(center_slice, tr)
        return lambda y: spline_residuals(y, n_nodes)
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

def weisskoff(images: "QAImages", roi: ROI) -> WeisskoffResult:
    """Weisskoff plot + radius of decorrelation over a resolved ROI.

    Grows a sub-ROI from 1x1 up to `roi.size` and measures the CV of its (already
    detrended) mean fluctuation. `cv1_pooled` is the single-voxel CV pooled over
    the full ROI; `rdc = cv1_pooled / cv[-1]`.
    """
    # derived images are properties; read each once rather than per ROI size
    fluctuations, mean_image = images.fluctuations, images.mean_image
    # include size so cv[-1] is measured at the ROI the single-voxel CV pools over
    roi_sizes = np.arange(1, roi.size + 1, 2)
    cv = np.array([
        _roi_cv(fluctuations, mean_image, roi.center, int(k))
        for k in roi_sizes
    ])

    idx = roi.index
    s = images.fluctuation_noise[*idx]
    mu = mean_image[*idx]
    cv1_pooled = float(np.sqrt(np.mean(s**2)) / np.mean(mu))

    return WeisskoffResult(
        roi_sizes=roi_sizes,
        cv=cv,
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

def _ghost_masks(phantom_mask: NDArray, pe_axis: int,
                 radius: int) -> tuple[NDArray, NDArray]:
    """Non-overlapping (signal, ghost) masks for a candidate PE axis.

    The ghost is the phantom rolled half the FOV along `pe_axis`. Each mask is
    eroded and has the dilated other region and the image border removed, so the
    two never touch.
    """
    ghost = np.roll(phantom_mask, phantom_mask.shape[pe_axis] // 2, axis=pe_axis)

    canvas = np.ones_like(phantom_mask)
    canvas[(0, -1), :] = 0
    canvas[:, (0, -1)] = 0

    def carve(keep, drop):
        return (
            morphology.isotropic_erosion(keep, radius)
            & ~morphology.isotropic_dilation(drop, radius)
            & canvas
        )

    return carve(phantom_mask, ghost), carve(ghost, phantom_mask)

def ghost_ratio(
    mean_image: NDArray,
    phantom_mask: NDArray,
    pe_axis: int = 0,
    radius: int = 3,
) -> float:
    """Nyquist ghost-to-signal ratio.

    NOTE: still tuning. The ghost is located by rolling the phantom half the FOV
    along the phase-encode axis; `pe_axis` and the erosion/dilation `radius` are
    acquisition-dependent and should be verified per protocol.
    """
    signal_mask, ghost_mask = _ghost_masks(phantom_mask, pe_axis, radius)
    return float(mean_image[ghost_mask].mean() / mean_image[signal_mask].mean())

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
    return_ratios: Literal[False] = ...,
) -> int: ...
@overload
def estimate_pe_axis(
    mean_image: NDArray, phantom_mask: NDArray, radius: int = ...,
    *, return_ratios: Literal[True],
) -> tuple[int, dict[int, float]]: ...
def estimate_pe_axis(
    mean_image: NDArray,
    phantom_mask: NDArray,
    radius: int = 3,
    return_ratios: bool = False,
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
        axis: ghost_ratio(mean_image, phantom_mask, pe_axis=axis, radius=radius)
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
    fluctuations = detrend_fn(center_slice, scan.tr, detrend)(center_slice)
    return QAImages(
        center_slice=center_slice,
        fluctuations=fluctuations,
        tr=float(scan.tr),
        voxel_size=float(scan.voxel_size),
        pe_axis=scan.pe_axis,
        detrend_method=detrend,
    )

def run_qa(
    scan: QAScan,
    trim_sec: float = 5.0,
    pe_axis: int | None = None,
    detrend: str = "poly",
    center: str = "image",
    roi_size: int = FBIRN_ROI_SIZE,
) -> QAMetrics:
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
    if pe_axis is None:
        pe_axis = images.pe_axis
    if pe_axis is None:
        pe_axis = estimate_pe_axis(images.mean_image, geom.phantom_mask)
    gr = ghost_ratio(images.mean_image, geom.phantom_mask, pe_axis=pe_axis)
    return QAMetrics(
        snr=snr(images, roi),
        sfnr=sfnr(images, roi),
        rdc=wk.rdc,
        ghost_ratio=gr,
        weisskoff=wk,
    )
