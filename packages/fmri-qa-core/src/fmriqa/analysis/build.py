"""Project a finished `QAResult` into the publishable `QAArtifact`.

This is the seam. Everything a reader could want is resolved here, once, while
the full images and metric results are in hand: derived properties become plain
fields, the ROI series and residual spectrum are extracted, the ghost regions
and phantom outline are materialized, and the PSF model is sampled. No consumer
has to re-derive anything from raw arrays or import `metrics`, `prep` or `load`.

`analyze` is the one-call front door: series in, analysis file out.
"""

from dataclasses import replace
from datetime import UTC, datetime

import numpy as np

from ..load.metadata import ScanMeta
from ..load.pe_axis import PE_ROWCOL
from ..load.scan import QAScan
from ..metrics.smoothness import SmoothnessResult
from ..pipeline import QAResult, run_qa
from ..prep.geometry import ROI, roi_fits
from ..settings import AnalysisSettings
from ..types import BoolArray, FloatArray, PeAxis, PeLabel, readout_axis
from ..version import core_version
from .artifact import (
    ArtifactImages,
    Curves,
    GhostRegions,
    Measurements,
    Provenance,
    PsfCurves,
    QAArtifact,
    RoiBox,
    WeisskoffCurve,
)

# Points used to sample the Gaussian PSF model curve.
_PSF_SAMPLES = 100


def analyze(
    scan: QAScan,
    settings: AnalysisSettings | None = None,
    *,
    name: str = "",
    source: str = "",
) -> QAArtifact:
    """Run the QA pipeline on one series and publish the analysis file.

    `scan` in, `QAArtifact` out, with the heavy intermediates discarded.
    `settings` is the analysis request and carries the defaults. `name` and
    `source` are recorded as provenance: the display name and the path the
    series was read from.
    """
    return build_artifact(run_qa(scan, settings), name=name, source=source)


def build_artifact(result: QAResult, *, name: str = "", source: str = "") -> QAArtifact:
    """Project a computed `QAResult` into a `QAArtifact`.

    Separate from `analyze` so a result already in hand from `run_qa` can be
    published without recomputing. The settings published are the ones the
    result carries.
    """
    return QAArtifact(
        settings=result.settings,
        provenance=_provenance(result, name=name, source=source),
        measurements=_measurements(result),
        curves=_curves(result),
        images=_images(result),
    )


def _provenance(result: QAResult, *, name: str, source: str) -> Provenance:
    """Flatten identity, timestamp and acquisition metadata into `Provenance`."""
    meta: ScanMeta | None = result.meta
    base = Provenance(
        scan=name,
        source=source,
        created=datetime.now(UTC).isoformat(timespec="seconds"),
        core_version=core_version(),
        tr=float(result.images.tr),
        n_frames=int(result.images.center_slice.shape[-1]),
        n_trimmed=int(result.images.n_trimmed),
        slice_index=result.images.slice_index,
        n_slices=result.images.n_slices,
    )
    if meta is None:
        return base
    # Every sidecar field is spelled out because the acquisition block is a
    # published contract. The nine identifying fields are not re-listed:
    # `replace` carries them from `base`, and re-listing them would give nine
    # chances to drop one.
    return replace(
        base,
        voxel_mm=meta.voxel_mm,
        matrix=meta.matrix,
        te=meta.te,
        flip_angle=meta.flip_angle,
        slice_thickness=meta.slice_thickness,
        pe_dir=meta.pe_dir,
        coil=meta.coil,
        manufacturer=meta.manufacturer,
        model=meta.model,
        serial=meta.serial,
        field_strength=meta.field_strength,
        software=meta.software,
        datetime=meta.datetime,
        series=meta.series,
    )


def _pe_label(result: QAResult) -> PeLabel:
    """Resolve the phase-encode direction to display: "row", "col" or "?".

    The label names the axis the ghost masks were built on, however it was
    settled (sidecar, header, `--pe-axis`, or the Nyquist-ghost estimate). "?"
    means none was.

    `load.metadata._pe_direction` derives `pe_dir` from the resolved axis, so
    `meta.pe_dir` is not consulted here. `PE_ROWCOL` is total over `PeAxis`, so
    no lookup default is needed.
    """
    axis = result.metrics.pe_axis
    return "?" if axis is None else PE_ROWCOL[axis]


def _measurements(result: QAResult) -> Measurements:
    """Settle every reported scalar, resolving the metric objects' properties."""
    m = result.metrics
    sat, sm, ghost = m.saturation, m.smoothness, m.ghost
    # With no PE axis there is no ghost result, and all four ghost percentages
    # are NaN (the estimator could not resolve them).
    undefined = float("nan")
    return Measurements(
        snr=m.snr,
        sfnr=m.sfnr,
        rdc=m.rdc,
        drift_pct=m.drift_pct,
        percent_fluctuation=m.percent_fluctuation,
        ghost_pct=ghost.ghost_pct if ghost is not None else undefined,
        ghost_top_pct=ghost.ghost_top_pct if ghost is not None else undefined,
        ro_ghost_pct=ghost.ro_ghost_pct if ghost is not None else undefined,
        acr_ghost_pct=ghost.acr_ghost_pct if ghost is not None else undefined,
        pe_axis=m.pe_axis,
        pe_label=_pe_label(result),
        outlier_max_pct=100.0 * m.outliers.max_fraction,
        outlier_worst_frame=m.outliers.worst_volume,
        tc_outlier=m.spikes.tc_outlier,
        spec_outlier=m.spikes.spec_outlier,
        # With no integer samples there was no rail to seek, so these are all
        # None ("not determinable"), which differs from "nothing clipped".
        clip_ceiling=sat.ceiling if sat is not None else None,
        clip_bits=sat.bits if sat is not None else None,
        n_clipped_kept=sat.n_clipped_kept if sat is not None else None,
        n_clipped_pre=sat.n_clipped_pre if sat is not None else None,
        clipped_kept=sat.clipped_kept if sat is not None else None,
        clipped_any=sat.clipped if sat is not None else None,
        max_translation=m.motion.max_translation,
        max_scale_pct=m.motion.max_scale_pct,
        max_shear_pct=m.motion.max_shear_pct,
        max_com_displacement=m.center_of_mass.max_displacement,
        displacement_unit=m.motion.voxel.unit,
        fwhm=sm.fwhm,
        fwhm_pe=sm.fwhm_pe,
        fwhm_ro=sm.fwhm_ro,
        fwhm_unit=sm.voxel.unit,
        phantom_fraction=result.geom.fraction,
        phantom_contrast=result.geom.contrast,
        phantom_mask_ok=result.geom.plausible,
        roi_inside_phantom=roi_fits(result.geom.phantom_mask, result.roi),
    )


def _roi_series(arr: FloatArray, roi: ROI) -> FloatArray:
    """Compute the ROI-mean time series of a 3-D (X, Y, T) array."""
    return np.asarray(roi.mean(arr), dtype=np.float64)


def _curves(result: QAResult) -> Curves:
    """Extract every 1-D trace a stability plot draws."""
    images, roi, m = result.images, result.roi, result.metrics
    n = images.center_slice.shape[-1]
    time = np.asarray(np.arange(n) * images.tr, dtype=np.float64)
    residual = _roi_series(images.fluctuations, roi)
    # Drop DC here, not at plot time. It is the residual's mean (~0) and would
    # dwarf the axis.
    freqs = np.fft.rfftfreq(residual.size, d=images.tr)
    magnitude = np.abs(np.fft.rfft(residual))
    return Curves(
        time=time,
        roi_signal=_roi_series(images.center_slice, roi),
        roi_trend=_roi_series(images.trend, roi),
        roi_residual=residual,
        outlier_fraction=np.asarray(m.outliers.fraction, dtype=np.float64),
        outlier_qthr=m.outliers.qthr,
        spectrum_hz=np.asarray(freqs[1:], dtype=np.float64),
        spectrum_magnitude=np.asarray(magnitude[1:], dtype=np.float64),
        translation=np.asarray(m.motion.translation, dtype=np.float64),
        scale_pct=np.asarray(m.motion.scale_pct, dtype=np.float64),
        shear_pct=np.asarray(m.motion.shear_pct, dtype=np.float64),
        com_deviation=np.asarray(m.center_of_mass.deviation, dtype=np.float64),
        weisskoff=_weisskoff_curve(result),
        psf=_psf_curves(m.smoothness),
    )


def _weisskoff_curve(result: QAResult) -> WeisskoffCurve:
    """Build the measured CV curve together with its ideal reference line."""
    wk = result.metrics.weisskoff
    sizes = np.asarray(wk.roi_sizes, dtype=np.float64)
    return WeisskoffCurve(
        roi_sizes=sizes,
        cv=np.asarray(wk.cv, dtype=np.float64),
        # Anchored at the pooled single-voxel CV, so the width where the
        # measured plateau meets this line is the reported RDC (see
        # `plot_weisskoff`).
        cv_ideal=np.asarray(wk.cv1_pooled / sizes, dtype=np.float64),
        rdc=np.asarray(wk.rdc_curve, dtype=np.float64),
    )


def _psf_curves(s: SmoothnessResult) -> PsfCurves:
    """Sample the directional PSF: empirical points plus the Gaussian model.

    The plotting range depends on the measured smoothness, so it is fixed here:
    a few FWHM, but at least three voxels so a PSF narrower than the voxel grid
    is not squashed.
    """
    dirs: tuple[tuple[str, PeAxis], tuple[str, PeAxis]]
    if s.pe_axis is not None:
        dirs = (("PE", s.pe_axis), ("RO", readout_axis(s.pe_axis)))
    else:  # no PE axis resolved: fall back to raw array axes
        dirs = (("axis0", 0), ("axis1", 1))
    mm_per = [s.voxel.per_axis(a) for _, a in dirs]
    fwhm = [s.fwhm_axis(a) for _, a in dirs]
    # An unresolvable axis yields a NaN FWHM. Fall back to the voxel-scale floor
    # so the range stays finite and the empirical points stay plottable.
    spans = [
        max(2.6 * f, 3.0 * mm) if np.isfinite(f) else 3.0 * mm
        for f, mm in zip(fwhm, mm_per, strict=True)
    ]
    xmax = float(max(spans))
    model_x = np.tile(np.linspace(0.0, xmax, _PSF_SAMPLES), (2, 1))
    return PsfCurves(
        labels=(dirs[0][0], dirs[1][0]),
        fwhm=(fwhm[0], fwhm[1]),
        unit=s.voxel.unit,
        displacement=np.stack([s.displacement(a) for _, a in dirs]),
        empirical=np.stack([s.psf_empirical(a) for _, a in dirs]),
        model_x=model_x,
        model=np.stack([s.psf_model(model_x[i], a) for i, (_, a) in enumerate(dirs)]),
        xmax=xmax,
    )


def _convex_hull(mask: BoolArray) -> FloatArray:
    """Compute the closed convex hull of a mask as an (N, 2) (x, y) polygon.

    Computed here so a renderer can stroke the phantom boundary without any
    computational geometry. `imshow` maps column to x and row to y, so (row, col)
    pixels are emitted as (col, row). A mask too small to have a hull yields an
    empty polygon. That includes a mask that is a single row or column, which has
    no area however many pixels it holds and which Qhull refuses ("initial
    simplex is flat"). It is a degenerate segmentation that shows up after the
    whole analysis has run, so it gets the empty polygon instead of losing the
    analysis file to a geometry library error.
    """
    ys, xs = np.nonzero(mask)
    if xs.size < 3:
        return np.zeros((0, 2), dtype=np.float64)
    pts = np.column_stack([xs, ys]).astype(np.float64)
    # Imported here: scipy.spatial takes over a second to import, and a bare
    # --version or --help should not pay for it.
    from scipy.spatial import ConvexHull, QhullError

    try:
        verts = ConvexHull(pts).vertices
    except QhullError:  # collinear: pixels but no area to enclose
        return np.zeros((0, 2), dtype=np.float64)
    loop = np.append(verts, verts[0])  # close the polygon
    return np.asarray(pts[loop], dtype=np.float64)


def _ghost_regions(result: QAResult) -> GhostRegions | None:
    """Copy the region-matched signal/ghost masks per axis, or None.

    Copied off the `GhostResult` the run measured on, not rebuilt here, so the
    published regions are the ones the percentages were averaged over. None when
    no axis resolved, since nothing was sampled.
    """
    ghost = result.metrics.ghost
    if ghost is None:
        return None
    return GhostRegions(
        pe_signal=ghost.pe_signal,
        pe_ghost=ghost.pe_ghost,
        ro_signal=ghost.ro_signal,
        ro_ghost=ghost.ro_ghost,
    )


def _images(result: QAResult) -> ArtifactImages:
    """Assemble the four FBIRN summary images plus the geometry drawn over them."""
    images, geom, roi = result.images, result.geom, result.roi
    fluctuation_noise = images.fluctuation_noise
    # Per-voxel SFNR inside the phantom. The epsilon keeps the ratio finite where
    # a masked-in voxel has no temporal noise.
    sfnr = np.where(
        geom.phantom_mask, images.mean_image / (fluctuation_noise + 1e-9), 0.0
    )
    rows, cols = roi.index
    return ArtifactImages(
        signal=images.mean_image,
        sfnr=np.asarray(sfnr, dtype=np.float64),
        fluctuation_noise=fluctuation_noise,
        static_noise=images.static_noise,
        phantom_mask=geom.phantom_mask,
        invalid_mask=~images.valid_mask,
        phantom_hull=_convex_hull(geom.phantom_mask),
        roi=RoiBox(
            row0=int(rows.start),
            row1=int(rows.stop),
            col0=int(cols.start),
            col1=int(cols.stop),
        ),
        ghost=_ghost_regions(result),
    )
