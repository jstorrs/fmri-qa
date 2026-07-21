"""Preprocessing and the full single-scan QA pipeline.

`preprocess` turns a raw `QAScan` into the `QAImages` every metric reads from;
`run_qa` orchestrates the whole analysis — saturation, phantom detection,
motion/centroid, the FBIRN ROI metrics, ghost ratios, and smoothness — into one
`QAResult`. The heavy lifting lives in the operation modules; this is the glue.
"""

import warnings

from .center_of_mass import estimate_center_of_mass
from .constants import FBIRN_ROI_SIZE
from .detrend import detrend_fn
from .geometry import detect_phantom, resolve_roi, roi_fits
from .ghost import estimate_pe_axis, ghost_ratio, ghost_top_ratio
from .imaging import extract_center_slice, trim_count, trim_initial
from .motion import estimate_motion
from .noise import (
    drift_percent,
    outlier_fraction,
    percent_fluctuation,
    sfnr,
    snr,
    spike_scores,
    weisskoff,
)
from .saturation import detect_saturation
from .scan import QAScan
from .smoothness import estimate_smoothness
from .types import QAImages, QAMetrics, QAResult


def preprocess(
    scan: QAScan, trim_sec: float = 5.0, detrend: str = "poly", center: str = "image"
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
        pe_axis = estimate_pe_axis(mean_image, geom.phantom_mask, valid_mask=valid_mask)
    # Region-matched percent ghost on each in-plane axis; the ACR-equivalent is
    # their difference (see `acr_ghosting_ratio`). Computing both here avoids
    # re-deriving the PE ratio inside `acr_ghosting_ratio`.
    pe_ratio = ghost_ratio(
        mean_image, geom.phantom_mask, pe_axis=pe_axis, valid_mask=valid_mask
    )
    ro_ratio = ghost_ratio(
        mean_image, geom.phantom_mask, pe_axis=1 - pe_axis, valid_mask=valid_mask
    )
    # Localized-ghost companion to the PE mean ratio: the brightest 10% of ghost
    # voxels (Greve / bxh fmriqa_ghostiness), on the same region-matched scale.
    pe_top_ratio = ghost_top_ratio(
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
        acr_ghost_pct=100.0 * abs(pe_ratio - ro_ratio),
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
