"""Preprocessing and the full single-scan QA pipeline, plus its result objects.

`preprocess` turns a raw `QAScan` into the `QAImages` every metric reads from;
`run_qa` orchestrates the whole analysis — saturation, phantom detection,
motion/centroid, the FBIRN ROI metrics, ghost ratios, and smoothness — into one
`QAResult`. The heavy lifting lives in the operation modules; this is the glue,
so it is also the natural home for the aggregate `QAMetrics`/`QAResult` value
objects that gather every metric's output.
"""

import warnings
from dataclasses import dataclass

from .load.metadata import ScanMeta
from .load.scan import QAScan
from .metrics.artifacts import (
    OutlierResult,
    SpikeResult,
    outlier_fraction,
    spike_scores,
)
from .metrics.center_of_mass import CenterOfMassResult, estimate_center_of_mass
from .metrics.fbirn import (
    WeisskoffResult,
    drift_percent,
    percent_fluctuation,
    sfnr,
    snr,
    weisskoff,
)
from .metrics.ghost import (
    acr_ghosting_ratio,
    estimate_pe_axis,
    ghost_ratio,
    ghost_top_ratio,
)
from .metrics.motion import MotionResult, estimate_motion
from .metrics.saturation import SaturationResult, detect_saturation
from .metrics.smoothness import SmoothnessResult, estimate_smoothness
from .prep.detrend import detrend_fn
from .prep.geometry import (
    FBIRN_ROI_SIZE,
    ROI,
    PhantomGeometry,
    detect_phantom,
    resolve_roi,
    roi_fits,
)
from .prep.images import QAImages
from .prep.imaging import extract_center_slice, trim_count, trim_initial
from .types import DetrendMethod, RoiCenter
from .validation import validate_qa_run


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


def preprocess(
    scan: QAScan,
    trim_sec: float = 5.0,
    detrend: DetrendMethod = "poly",
    center: RoiCenter = "image",
) -> QAImages:
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
    detrend: DetrendMethod = "poly",
    center: RoiCenter = "image",
    roi_size: int = FBIRN_ROI_SIZE,
) -> QAResult:
    """Full pipeline: scan -> preprocess -> phantom -> Weisskoff/RDC + ghost ratio.

    `pe_axis=None` takes the axis from the scan's header, and failing that
    estimates it from the ghost regions; if the ghost resolves neither axis the
    run continues with the ghost metrics undefined (NaN) and a warning, since
    every one of them is defined relative to an axis.
    `detrend` selects the detrending method ("poly" or "spline").
    `center` localizes both the QA slice and the ROI: "image" (middle slice +
    image-center ROI, Glover) or "phantom" (largest slice + detected center).
    `roi_size` is the fixed summary/Weisskoff ROI side (default 21, fBIRN).
    """
    validate_qa_run(scan, trim_sec=trim_sec, roi_size=roi_size, pe_axis=pe_axis)

    # Saturation is checked on the full untrimmed series: clipping is worst in
    # the high-signal warm-up volumes that preprocessing drops. The count is
    # split at the same trim boundary so clips outside the analyzed data (which
    # don't bias the metrics) are reported apart from clips that do.
    saturation = detect_saturation(
        scan.data, scan.slope, scan.inter, trim=trim_count(scan.tr, trim_sec)
    )

    images = preprocess(scan, trim_sec=trim_sec, detrend=detrend, center=center)
    geom = detect_phantom(images)

    # 3dvolreg-style per-volume registration of the phantom to its temporal mean,
    # under a rotation-free (translation + scale + shear) model -- a diagnostic
    # of gradient-heating deformation. The analyzed series is NOT resampled from
    # this fit, so the FBIRN metrics stay measured on the acquired data.
    voxel_mm = scan.meta.voxel_mm[:2] if scan.meta else None
    motion = estimate_motion(images.center_slice, geom.phantom_mask, voxel_mm=voxel_mm)
    # Per-volume intensity centroid (bxh volmeasures), circular so a phantom
    # against a wrapped edge does not alias and -- crucially -- so a uniform
    # background and the 180-degree Nyquist ghost self-cancel; no phantom mask is
    # used (it would break that cancellation). The valid mask only heals missing
    # data (a Siemens zeroed edge). A cheap first-moment trace alongside `motion`.
    com = estimate_center_of_mass(
        images.center_slice, images.valid_mask, voxel_mm=voxel_mm
    )

    roi = resolve_roi(images, geom, roi_size, center)
    if not roi_fits(geom.phantom_mask, roi.index):
        # Name the mode the run did *not* use: the two localizations disagree
        # only on an off-center phantom, which is exactly when one of them can
        # rescue an ROI the other cannot fit.
        other: RoiCenter = "phantom" if center == "image" else "image"
        warnings.warn(
            f"{roi.size}x{roi.size} ROI ({center} center) is not fully inside the "
            f"phantom; reduce roi_size or try center={other!r}.",
            stacklevel=2,
        )

    wk = weisskoff(images, roi)
    mean_image = images.mean_image
    valid_mask = images.valid_mask
    if pe_axis is None:
        pe_axis = images.pe_axis
    if pe_axis is None:
        pe_axis = estimate_pe_axis(mean_image, geom.phantom_mask, valid_mask=valid_mask)
    # Every ghost statistic is defined *relative to an axis*, so with none
    # resolved there is nothing to report and the four resolve to NaN. Saying so
    # is the point: the alternative is naming an axis nothing measured and
    # publishing four numbers sampled from wherever it happened to point.
    if pe_axis is None:
        warnings.warn(
            "no phase-encode axis: absent from the header and the Nyquist ghost "
            "resolves neither in-plane axis, so the ghost metrics are undefined. "
            "Pass pe_axis explicitly if the acquisition's direction is known.",
            stacklevel=2,
        )
        pe_ratio = ro_ratio = pe_top_ratio = acr_ratio = float("nan")
    else:
        # Region-matched percent ghost on each in-plane axis: pe_ratio feeds
        # ghost%, ro_ratio feeds RO% (the readout-axis background-relative
        # baseline). The ACR-equivalent |PE - RO| comes from
        # `acr_ghosting_ratio`, which owns that metric's definition (matched
        # signal/ghost ROIs per direction).
        pe_ratio = ghost_ratio(
            mean_image, geom.phantom_mask, pe_axis=pe_axis, valid_mask=valid_mask
        )
        ro_ratio = ghost_ratio(
            mean_image, geom.phantom_mask, pe_axis=1 - pe_axis, valid_mask=valid_mask
        )
        # Localized-ghost companion to the PE mean ratio: the brightest 10% of
        # ghost voxels (Greve / bxh fmriqa_ghostiness), on the same
        # region-matched scale.
        pe_top_ratio = ghost_top_ratio(
            mean_image, geom.phantom_mask, pe_axis=pe_axis, valid_mask=valid_mask
        )
        acr_ratio = acr_ghosting_ratio(
            mean_image, geom.phantom_mask, pe_axis=pe_axis, valid_mask=valid_mask
        )

    # Directional spatial smoothness (AFNI 3dFWHMx): the Gaussian FWHM of the
    # detrended noise field along PE and RO, plus the point-spread curves -- the
    # correlation-length confound the guide warns the Weisskoff RDC is measured
    # against. Computed here so the resolved `pe_axis` labels the directions.
    smoothness = estimate_smoothness(
        images.fluctuations, geom.phantom_mask, voxel_mm=voxel_mm, pe_axis=pe_axis
    )

    metrics = QAMetrics(
        snr=snr(images, roi),
        sfnr=sfnr(images, roi),
        rdc=wk.rdc,
        ghost_pct=100.0 * pe_ratio,
        ghost_top_pct=100.0 * pe_top_ratio,
        ro_ghost_pct=100.0 * ro_ratio,
        acr_ghost_pct=100.0 * acr_ratio,
        pe_axis=pe_axis,
        drift_pct=drift_percent(images, roi),
        percent_fluctuation=percent_fluctuation(images, roi),
        weisskoff=wk,
        saturation=saturation,
        outliers=outlier_fraction(images.fluctuations, geom.phantom_mask),
        spikes=spike_scores(images, roi),
        motion=motion,
        center_of_mass=com,
        smoothness=smoothness,
    )
    return QAResult(images=images, geom=geom, roi=roi, metrics=metrics, meta=scan.meta)
