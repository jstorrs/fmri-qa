"""Preprocessing and the full single-scan QA pipeline, plus its result objects.

`preprocess` turns a raw `QAScan` into the `QAImages` every metric reads from;
`run_qa` orchestrates the whole analysis — saturation, phantom detection,
motion/centroid, the FBIRN ROI metrics, ghost ratios, and smoothness — into one
`QAResult`. The heavy lifting lives in the operation modules; this is the glue,
so it is also the natural home for the aggregate `QAMetrics`/`QAResult` value
objects that gather every metric's output. `run_qa` writes the `AnalysisSettings`
it was asked for into `QAResult.settings`, but that record is defined in
`settings`, not here, so the artifact types can carry it without loading this
module.
"""

import warnings
from dataclasses import dataclass, replace

from ._arrays import readonly
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
from .types import FBIRN_ROI_SIZE, BoolArray, DetrendMethod, PeAxis, RoiCenter
from .validation import validate_qa_run


@dataclass(frozen=True, slots=True)
class QAMetrics:
    """Settled scalar QA metrics for one scan."""

    snr: float
    sfnr: float
    rdc: float
    # The whole ghost family off one set of masks, or None when no PE axis
    # resolved: every ghost statistic is defined relative to an axis.
    ghost: GhostResult | None
    drift_pct: float
    percent_fluctuation: float
    weisskoff: WeisskoffResult
    # None when the scan did not arrive as integers, so no rail could be sought
    # (see `metrics.saturation`); distinct from a result saying nothing clipped.
    saturation: SaturationResult | None
    outliers: OutlierResult
    spikes: SpikeResult
    motion: MotionResult
    center_of_mass: CenterOfMassResult
    smoothness: SmoothnessResult

    @property
    def pe_axis(self) -> PeAxis | None:
        """The phase-encode axis the ghost masks were actually built on.

        Read off `ghost` rather than stored beside it. The axis and the ghost
        family are one fact -- `estimate_ghost` is handed the axis and records
        it, and there is no ghost result at all without one -- so a second copy
        here could only ever agree with `ghost.pe_axis` or be a bug, and
        "resolved an axis but measured no ghost" would be a state the type
        allowed and nothing forbade. Held as a property, the two cannot
        disagree, and None means exactly what the absent ghost means.
        """
        return None if self.ghost is None else self.ghost.pe_axis


@dataclass(frozen=True, eq=False, slots=True)
class QAResult:
    """Full QA output: the intermediate objects plus the scalar metrics.

    Returned by `run_qa`. `metrics` holds the scalars; `images`/`geom`/`roi` are
    retained so a report can render the images, curves, and time series;
    `settings` is the request the run answered, with the detrend order it
    resolved; `meta` carries the acquisition metadata (from the scan) for the
    report header.
    """

    images: QAImages
    geom: PhantomGeometry
    roi: ROI
    metrics: QAMetrics
    settings: AnalysisSettings
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
    data = trim_initial(scan.data, tr=scan.tr, trim_sec=trim_sec)
    z, phantom_mask = select_slice(data, center)
    center_slice = data[:, :, z, :]
    detrender = Detrender.for_series(center_slice, scan.tr, detrend)
    fluctuations = detrender(center_slice)
    images = QAImages(
        center_slice=center_slice,
        fluctuations=fluctuations,
        tr=float(scan.tr),
        # Recorded here because this is where it happens: everything downstream
        # indexes the trimmed series, and once `scan.data` is dropped nothing
        # else can say which acquired volume frame 0 was.
        n_trimmed=trim_count(tr=scan.tr, trim_sec=trim_sec),
        # The value a stored zero reads back as, so a nulled image edge is
        # recognizable under a nonzero intercept (see `edge_valid_mask`).
        zero_value=float(scan.inter),
        detrender=detrender,
        # Which plane this is, for the same reason as the trim: once the volume
        # is dropped nothing else can say.
        slice_index=z,
        n_slices=int(data.shape[2]),
    )
    if phantom_mask is not None:
        _prime_phantom_mask_cache(images, phantom_mask)
    return images


def _prime_phantom_mask_cache(images: QAImages, mask: BoolArray) -> None:
    """Seed `images.phantom_mask` with the mask `select_slice` already segmented.

    `QAImages.phantom_mask` is a `cached_property` defined as
    `segment_phantom(self.mip)` — its one definition, so `detect_phantom` never
    reads a mask that could disagree with `images.mip`. `select_slice`
    (`center="phantom"`) has already run that exact watershed, on that exact
    array — the winning slice's time-MIP, which is what `mip` reduces to for
    this `QAImages` — to rank slices before this object existed. Writing that
    value directly into the property's backing `__dict__` entry is not a
    second definition or injected state, because it is the value the property
    would compute anyway; it just spares the second, identical watershed that
    accessing `.phantom_mask` would otherwise trigger. This is exactly what
    `cached_property.__get__` itself does after computing on first access —
    `QAImages` is a frozen dataclass without `__slots__` for that reason: an
    instance `__dict__` exists for `cached_property` to cache into, and normal
    attribute assignment (blocked by `frozen=True`) is not how it does so
    either.
    """
    images.__dict__["phantom_mask"] = readonly(mask)


def run_qa(
    scan: QAScan,
    trim_sec: float = 5.0,
    pe_axis: PeAxis | None = None,
    detrend: DetrendMethod = "poly",
    center: RoiCenter = "image",
    roi_size: int = FBIRN_ROI_SIZE,
) -> QAResult:
    """Full pipeline: scan -> preprocess -> phantom -> Weisskoff/RDC + ghost ratio.

    `pe_axis=None` takes the axis from the scan's metadata, and failing that
    estimates it from the ghost regions of the analyzed slice — the one place
    that estimate is made. If the ghost resolves neither axis the run continues
    with `metrics.ghost` None and a warning, since every ghost statistic is
    defined relative to an axis.
    `detrend` selects the detrending method ("poly" or "spline").
    `center` localizes both the QA slice and the ROI: "image" (middle slice +
    image-center ROI, Glover) or "phantom" (largest slice + detected center).
    `roi_size` is the fixed summary/Weisskoff ROI side (default 21, fBIRN).
    """
    named_pe = validate_qa_run(
        scan, trim_sec=trim_sec, roi_size=roi_size, pe_axis=pe_axis
    )
    # The request, recorded as it was made: `pe_axis` here is the caller's
    # argument, not the axis the run goes on to measure along.
    requested = AnalysisSettings(
        trim_sec=trim_sec,
        detrend=detrend,
        center=center,
        roi_size=roi_size,
        pe_axis_override=pe_axis,
    )

    saturation = _detect_full_series_saturation(scan, trim_sec)

    images = preprocess(scan, trim_sec=trim_sec, detrend=detrend, center=center)
    geom = detect_phantom(images)

    voxel = VoxelSize.in_plane(scan.meta.voxel_mm) if scan.meta else UNKNOWN_VOXEL_SIZE
    motion = _estimate_phantom_motion(images, geom, voxel)
    com = _estimate_intensity_centroid(images, voxel)

    roi = resolve_roi(images, geom, roi_size, center)
    _warn_if_roi_does_not_fit(geom, roi, center)

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
    # detrended noise field along PE and RO, plus the point-spread curves -- the
    # correlation-length confound the guide warns the Weisskoff RDC is measured
    # against. Computed here so `resolved_pe` labels the directions.
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
        settings=replace(
            requested,
            detrend_order=(
                None if images.detrender is None else images.detrender.order
            ),
        ),
        meta=scan.meta,
    )


def _detect_full_series_saturation(
    scan: QAScan, trim_sec: float
) -> SaturationResult | None:
    """Saturation (clipped voxels), checked on the *untrimmed* acquired series.

    Clipping is worst in the high-signal warm-up volumes that preprocessing
    drops. The count is split at the same trim boundary so clips outside the
    analyzed data (which don't bias the metrics) are reported apart from clips
    that do.

    None when the scan did not arrive as the scanner's integers: the rail is an
    integer artifact of the ADC, so there is nothing to look for and no verdict
    to give (see `metrics.saturation`). `QAScan.from_nifti` has already warned.
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

    A rotation-free (translation + scale + shear) model -- a diagnostic of
    gradient-heating deformation. The analyzed series is NOT resampled from
    this fit, so the FBIRN metrics stay measured on the acquired data.
    """
    return estimate_motion(images.center_slice, geom.phantom_mask, voxel=voxel)


def _estimate_intensity_centroid(
    images: QAImages, voxel: VoxelSize
) -> CenterOfMassResult:
    """Per-volume intensity centroid (bxh volmeasures), a cheap first-moment trace.

    Circular so a phantom against a wrapped edge does not alias and --
    crucially -- so a uniform background and the 180-degree Nyquist ghost
    self-cancel; no phantom mask is used (it would break that cancellation).
    The valid mask only heals missing data (a Siemens zeroed edge).
    """
    return estimate_center_of_mass(
        images.center_slice, valid_mask=images.valid_mask, voxel=voxel
    )


def _warn_if_roi_does_not_fit(
    geom: PhantomGeometry, roi: ROI, center: RoiCenter
) -> None:
    """Warn when the resolved ROI is not fully inside the phantom mask.

    Names the mode the run did *not* use: the two localizations disagree only
    on an off-center phantom, which is exactly when one of them can rescue an
    ROI the other cannot fit.
    """
    if roi_fits(geom.phantom_mask, roi.index):
        return
    other: RoiCenter = "phantom" if center == "image" else "image"
    warnings.warn(
        f"{roi.size}x{roi.size} ROI ({center} center) is not fully inside the "
        f"phantom; reduce roi_size or try center={other!r}.",
        stacklevel=3,  # one frame in from `run_qa`: report at run_qa's caller
    )


def _build_ghost_family(
    pe_axis: PeAxis | None, images: QAImages, geom: PhantomGeometry
) -> GhostResult | None:
    """PE/readout percent ghost, the top-10% companion, and the ACR difference.

    Every ghost statistic is defined *relative to an axis*, so with none
    resolved there is nothing to measure and no result to carry -- None, not a
    default axis. Saying so is the point: the alternative is naming an axis
    nothing measured and publishing four numbers sampled from wherever it
    happened to point. When an axis is resolved, the whole family comes off one
    build of the region-matched masks, which the result carries so the artifact
    can publish the regions the numbers were sampled on.
    """
    if pe_axis is None:
        warnings.warn(
            "no phase-encode axis: absent from the header and the Nyquist ghost "
            "resolves neither in-plane axis, so the ghost metrics are undefined. "
            "Pass pe_axis explicitly if the acquisition's direction is known.",
            stacklevel=3,  # one frame in from `run_qa`: report at run_qa's caller
        )
        return None
    return estimate_ghost(
        images.mean_image, geom.phantom_mask, pe_axis, valid_mask=images.valid_mask
    )
