"""Preprocessing and the single-scan QA pipeline, with its result objects.

`preprocess` turns a raw `QAScan` into the `QAImages` every metric reads from.
`run_qa` runs the whole analysis (saturation, phantom detection, motion and
centroid, the FBIRN ROI metrics, ghost ratios and smoothness) and returns one
`QAResult`. The metric modules do the real work. This module is the glue, so it
also holds the `QAMetrics` and `QAResult` objects that gather their output.
`run_qa` stores the `AnalysisSettings` it was given in `QAResult.settings`. That
record is defined in `settings`, not here, so the artifact types can carry it
without loading this module.
"""

from dataclasses import dataclass, replace

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
from .metrics.ghost import GhostResult, estimate_ghost, estimate_pe_axis
from .metrics.motion import MotionResult, estimate_motion
from .metrics.saturation import SaturationResult, detect_saturation
from .metrics.smoothness import SmoothnessResult, estimate_smoothness
from .prep.detrend import Detrender
from .prep.geometry import (
    ROI,
    PhantomGeometry,
    detect_phantom,
    resolve_roi,
    roi_fits,
)
from .prep.images import QAImages
from .prep.imaging import select_slice, trim_count, trim_initial
from .prep.scale import UNKNOWN_VOXEL_SIZE, VoxelSize
from .settings import AnalysisSettings
from .types import PeAxis, RoiCenter
from .validation import validate_qa_run
from .warn import warn


@dataclass(frozen=True, slots=True)
class QAMetrics:
    """Settled scalar QA metrics for one scan."""

    snr: float
    sfnr: float
    rdc: float
    # The whole ghost family off one set of masks, or None when no PE axis
    # resolved. Every ghost statistic is defined relative to an axis.
    ghost: GhostResult | None
    drift_pct: float
    percent_fluctuation: float
    weisskoff: WeisskoffResult
    # None when the scan was not stored as integers, so no rail could be sought
    # (see `metrics.saturation`). That differs from a result saying nothing
    # clipped.
    saturation: SaturationResult | None
    outliers: OutlierResult
    spikes: SpikeResult
    motion: MotionResult
    center_of_mass: CenterOfMassResult
    smoothness: SmoothnessResult

    @property
    def pe_axis(self) -> PeAxis | None:
        """The phase-encode axis the ghost masks were actually built on.

        Read off `ghost` instead of stored beside it. A second copy could only
        agree with `ghost.pe_axis` or be a bug, and would allow the state
        "resolved an axis but measured no ghost". None means there is no ghost
        result.
        """
        return None if self.ghost is None else self.ghost.pe_axis


@dataclass(frozen=True, eq=False, slots=True)
class QAResult:
    """Full QA output: the intermediate objects plus the scalar metrics.

    Returned by `run_qa`. `metrics` holds the scalars. `images`, `geom` and
    `roi` are kept so a report can render the images, curves and time series.
    `settings` is the request the run answered, with the detrend order it
    resolved. `meta` is the scan's acquisition metadata, for the report header.
    """

    images: QAImages
    geom: PhantomGeometry
    roi: ROI
    metrics: QAMetrics
    settings: AnalysisSettings
    meta: ScanMeta | None = None


def preprocess(scan: QAScan, settings: AnalysisSettings | None = None) -> QAImages:
    """Trim, select the QA slice, and compute the FBIRN summary images.

    Returns `QAImages` (center slice, detrended fluctuations and derived summary
    images). The caller can discard `scan.data` afterwards. It reads three
    fields of the request: `trim_sec`, `detrend` ("poly" or "spline") and
    `center`. `center="image"` picks the middle slice (Glover), and
    `center="phantom"` picks the largest phantom cross-section. It takes the
    whole record because that is the one definition of every analysis default.
    """
    settings = AnalysisSettings() if settings is None else settings
    data = trim_initial(scan.data, tr=scan.tr, trim_sec=settings.trim_sec)
    z = select_slice(data, settings.center)
    center_slice = data[:, :, z, :]
    detrender = Detrender.for_series(center_slice, scan.tr, settings.detrend)
    fluctuations = detrender(center_slice)
    return QAImages(
        center_slice=center_slice,
        fluctuations=fluctuations,
        tr=float(scan.tr),
        # Recorded here because everything downstream indexes the trimmed
        # series, and once `scan.data` is dropped nothing else can say which
        # acquired volume frame 0 was.
        n_trimmed=trim_count(tr=scan.tr, trim_sec=settings.trim_sec),
        # The value a stored zero reads back as, so a nulled image edge can be
        # recognized under a nonzero intercept (see `edge_valid_mask`).
        zero_value=float(scan.inter),
        detrender=detrender,
        # Which plane this is, for the same reason as the trim.
        slice_index=z,
        n_slices=int(data.shape[2]),
    )


def run_qa(scan: QAScan, settings: AnalysisSettings | None = None) -> QAResult:
    """Run the single-slice QA pipeline on a scan.

    Stages, in order: validate, full-series saturation, preprocess, detect
    phantom, resolve ROI, FBIRN statistics, ghost family, outliers, spikes,
    motion, center of mass, smoothness.

    `settings` is the request. The result carries it back with the detrend order
    the run resolved. Its fields:
    `pe_axis_override`: None takes the axis from the scan's metadata, and failing
    that estimates it from the ghost regions of the analyzed slice (the only
    place that estimate is made). If neither axis resolves, the run continues
    with `metrics.ghost` None and a warning, since every ghost statistic is
    defined relative to an axis.
    `detrend` selects the detrending method ("poly" or "spline").
    `center` localizes both the QA slice and the ROI: "image" (middle slice and
    image-center ROI, Glover) or "phantom" (largest slice and detected center).
    `roi_size` is the fixed side of the summary and Weisskoff ROI (FBIRN's
    `FBIRN_ROI_SIZE` unless asked otherwise).
    """
    settings = AnalysisSettings() if settings is None else settings
    named_pe = validate_qa_run(scan, settings)

    saturation = _detect_full_series_saturation(scan, settings.trim_sec)

    images = preprocess(scan, settings)
    geom = detect_phantom(images)

    voxel = VoxelSize.in_plane(scan.meta.voxel_mm) if scan.meta else UNKNOWN_VOXEL_SIZE
    motion = _estimate_phantom_motion(images, geom, voxel)
    com = _estimate_intensity_centroid(images, voxel)

    roi = resolve_roi(images, geom, settings.roi_size, settings.center)
    _warn_if_roi_does_not_fit(geom, roi, settings.center)

    wk = weisskoff(images, roi)
    resolved_pe = (
        named_pe
        if named_pe is not None
        else estimate_pe_axis(
            images.mean_image, geom.phantom_mask, valid_mask=images.valid_mask
        )
    )
    ghost = _build_ghost_family(resolved_pe, images, geom)

    # Directional spatial smoothness (AFNI 3dFWHMx): the Gaussian FWHM of the
    # detrended noise field along PE and RO, plus the point-spread curves. This
    # is the correlation-length confound the Weisskoff RDC is measured against.
    # Computed here so `resolved_pe` labels the directions.
    smoothness = estimate_smoothness(
        images.fluctuations, geom.phantom_mask, voxel=voxel, pe_axis=resolved_pe
    )

    metrics = QAMetrics(
        snr=snr(images, roi),
        sfnr=sfnr(images, roi),
        rdc=wk.rdc,
        ghost=ghost,
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
    return QAResult(
        images=images,
        geom=geom,
        roi=roi,
        metrics=metrics,
        # `detrend_order` is the one field only the run can fill.
        # `pe_axis_override` stays what the caller asked for, not the axis used.
        settings=replace(
            settings,
            detrend_order=(
                None if images.detrender is None else images.detrender.order
            ),
        ),
        meta=scan.meta,
    )


def _detect_full_series_saturation(
    scan: QAScan, trim_sec: float
) -> SaturationResult | None:
    """Detect saturation (clipped voxels) on the untrimmed acquired series.

    Clipping is worst in the warm-up volumes that preprocessing drops. The count
    is split at the same trim boundary, so clips outside the analyzed data are
    reported apart from clips that bias the metrics.

    None when the scan was not stored as the scanner's integers, since the rail
    comes from the ADC's integer range (see `metrics.saturation`).
    `QAScan.from_nifti` has already warned.
    """
    return detect_saturation(
        scan.data,
        slope=scan.slope,
        inter=scan.inter,
        trim=trim_count(tr=scan.tr, trim_sec=trim_sec),
        stored_integer=scan.stored_integer,
    )


def _estimate_phantom_motion(
    images: QAImages, geom: PhantomGeometry, voxel: VoxelSize
) -> MotionResult:
    """3dvolreg-style per-volume registration of the phantom to its temporal mean.

    The model has no rotation (translation, scale and shear only) and is a
    diagnostic of gradient-heating deformation. The analyzed series is NOT
    resampled from this fit, so the FBIRN metrics stay measured on the acquired
    data.
    """
    return estimate_motion(images.center_slice, geom.phantom_mask, voxel=voxel)


def _estimate_intensity_centroid(
    images: QAImages, voxel: VoxelSize
) -> CenterOfMassResult:
    """Per-volume intensity centroid (bxh volmeasures), a cheap first-moment trace.

    The centroid is circular, so a phantom against a wrapped edge does not alias
    and a uniform background and the 180-degree Nyquist ghost cancel. No phantom
    mask is used, since it would break that cancellation. The valid mask only
    fills in missing data (a Siemens zeroed edge).
    """
    return estimate_center_of_mass(
        images.center_slice, valid_mask=images.valid_mask, voxel=voxel
    )


def _warn_if_roi_does_not_fit(
    geom: PhantomGeometry, roi: ROI, center: RoiCenter
) -> None:
    """Warn when the resolved ROI is not fully inside the phantom mask.

    Names the mode the run did not use. The two localizations disagree only on
    an off-center phantom, and then one can fit an ROI the other cannot.
    """
    if roi_fits(geom.phantom_mask, roi):
        return
    other: RoiCenter = "phantom" if center == "image" else "image"
    warn(
        f"{roi.size}x{roi.size} ROI ({center} center) is not fully inside the "
        f"phantom; reduce roi_size or try center={other!r}.",
    )


def _build_ghost_family(
    pe_axis: PeAxis | None, images: QAImages, geom: PhantomGeometry
) -> GhostResult | None:
    """Build PE/readout percent ghost, the top-10% companion, and ACR difference.

    Every ghost statistic is defined relative to an axis. With none resolved the
    result is None, not a default axis, which would publish four numbers sampled
    from wherever it happened to point. Otherwise the whole family comes off one
    build of the region-matched masks, which the result carries so the artifact
    can publish the sampled regions.
    """
    if pe_axis is None:
        warn(
            "no phase-encode axis: absent from the header and the Nyquist ghost "
            "resolves neither in-plane axis, so the ghost metrics are undefined. "
            "Pass --pe-axis (AnalysisSettings.pe_axis_override) if the "
            "acquisition's direction is known.",
        )
        return None
    return estimate_ghost(
        images.mean_image, geom.phantom_mask, pe_axis, valid_mask=images.valid_mask
    )
