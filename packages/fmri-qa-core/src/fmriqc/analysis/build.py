"""Project a finished `QAResult` into the publishable `QAArtifact`.

This is the seam itself: everything a downstream reader could want is *resolved
here*, once, while the full images and the metric result objects are still in
hand. Derived properties are settled into plain fields, the ROI time series and
the residual spectrum are extracted, the ghost sampling regions and the phantom
outline are materialized, and the PSF model is sampled — so no consumer has to
re-derive analysis quantities from raw arrays, and none of them needs the
`metrics`/`prep`/`load` layers to read a result.

`analyze` is the one-call front door: series in, artifact out.
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
    """Run the QA pipeline on one series and publish the artifact.

    The calculation half's entry point: `scan` in, `QAArtifact` out, with the
    heavy intermediates discarded. `settings` is the analysis request, whose own
    fields carry the defaults; `name` and `source` are recorded as provenance —
    the display name and the path the series was read from.
    """
    return build_artifact(run_qa(scan, settings), name=name, source=source)


def build_artifact(result: QAResult, *, name: str = "", source: str = "") -> QAArtifact:
    """Project a computed `QAResult` into a `QAArtifact`.

    Separate from `analyze` so an existing result — one already in hand from
    `run_qa`, with its images still live — can be published without recomputing.
    The settings published are the ones the result carries, which `run_qa` wrote
    from the request it was handed: there is nothing to pass and nothing to
    disagree with it.
    """
    return QAArtifact(
        settings=result.settings,
        provenance=_provenance(result, name=name, source=source),
        measurements=_measurements(result, result.settings),
        curves=_curves(result),
        images=_images(result),
    )


def _provenance(result: QAResult, *, name: str, source: str) -> Provenance:
    """Identity, timestamp, and the acquisition metadata, flattened."""
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
    # Every sidecar field is spelled out, because the artifact's acquisition
    # block is a published contract and a new field should be a deliberate
    # addition here -- but the nine identifying fields above are not repeated to
    # say so. `replace` carries them, which is the one reading of this code that
    # cannot drift from `base`: re-listing them was nine chances to drop one.
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
    """The phase-encode direction to display: "row", "col", or "?".

    One rule, and the axis is the whole of it: the label names the axis the
    ghost masks were built on, whatever settled it -- the sidecar, the header,
    an explicit `--pe-axis`, or the Nyquist-ghost estimate. "?" is the answer
    when nothing did.

    This used to consult `meta.pe_dir` first, back when that carried the
    sidecar's own DICOM row/col wording and could therefore name a *different*
    axis than the run used; the special case, and the `--pe-axis` exception
    carved out of it, existed to manage that disagreement. `load.metadata.
    _pe_direction` now derives `pe_dir` from the resolved axis, so the two
    branches had become the same answer and only one is left. `PE_ROWCOL` is
    keyed by `PeAxis` and total, so an axis indexes straight into a `PeLabel`
    with no lookup default standing in for a case that cannot arise.
    """
    axis = result.metrics.pe_axis
    return "?" if axis is None else PE_ROWCOL[axis]


def _measurements(result: QAResult, settings: AnalysisSettings) -> Measurements:
    """Settle every reported scalar, resolving the metric objects' properties."""
    m = result.metrics
    sat, sm, ghost = m.saturation, m.smoothness, m.ghost
    # The four ghost percentages stand or fall together: with no PE axis there is
    # no ghost result, and each of them is NaN -- an estimator that could not
    # resolve the quantity, which is what the artifact's NaN means.
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
        # The clipping block stands or falls together: with no integer samples
        # there was no rail to seek, and every one of these is None -- "not
        # determinable", which is not the same answer as "nothing clipped".
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
        roi_inside_phantom=roi_fits(result.geom.phantom_mask, result.roi.index),
    )


def _roi_series(arr: FloatArray, roi: ROI) -> FloatArray:
    """ROI-mean time series of a 3-D (X, Y, T) array."""
    return np.asarray(arr[roi.index].mean(axis=(0, 1)), dtype=np.float64)


def _curves(result: QAResult) -> Curves:
    """Extract every 1-D trace a stability plot draws."""
    images, roi, m = result.images, result.roi, result.metrics
    n = images.center_slice.shape[-1]
    time = np.asarray(np.arange(n) * images.tr, dtype=np.float64)
    residual = _roi_series(images.fluctuations, roi)
    # DC dropped here rather than at plot time: the zero-frequency bin is the
    # residual's mean (~0 by construction) and would otherwise dwarf the axis.
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
    """The measured CV curve with its ideal reference line resolved."""
    wk = result.metrics.weisskoff
    sizes = np.asarray(wk.roi_sizes, dtype=np.float64)
    return WeisskoffCurve(
        roi_sizes=sizes,
        cv=np.asarray(wk.cv, dtype=np.float64),
        # Anchored at the pooled single-voxel CV, so the width where the measured
        # plateau meets this line is the reported RDC (see `plot_weisskoff`).
        cv_ideal=np.asarray(wk.cv1_pooled / sizes, dtype=np.float64),
        rdc=np.asarray(wk.rdc_curve, dtype=np.float64),
    )


def _psf_curves(s: SmoothnessResult) -> PsfCurves:
    """Sample the directional PSF: empirical points plus the Gaussian model.

    The plotting range is fixed here — a few FWHM, but at least three voxels so a
    PSF narrower than the voxel grid is not squashed — because it depends on the
    measured smoothness, which is analysis, not layout.
    """
    dirs: tuple[tuple[str, PeAxis], tuple[str, PeAxis]]
    if s.pe_axis is not None:
        dirs = (("PE", s.pe_axis), ("RO", readout_axis(s.pe_axis)))
    else:  # no PE axis resolved -- fall back to raw array axes
        dirs = (("axis0", 0), ("axis1", 1))
    mm_per = [s.voxel.per_axis(a) for _, a in dirs]
    fwhm = [s.fwhm_axis(a) for _, a in dirs]
    # An unresolvable axis yields a NaN FWHM; fall back to the voxel-scale floor
    # so the range stays finite and the empirical points remain plottable.
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
    """The closed convex outline of a mask as an (N, 2) polygon in (x, y) order.

    Materialized here so a renderer can stroke the phantom boundary without any
    computational geometry. `imshow` maps column -> x and row -> y, so the mask's
    (row, col) pixels are emitted as (col, row). A mask too small to have a hull
    yields an empty polygon.

    Too small is not only a matter of count: a mask that is a single row or
    column has no area either, however many pixels it holds, and Qhull refuses
    it ("initial simplex is flat"). That is a degenerate segmentation, not a bad
    scan, and it arrives after the whole analysis has run — so it yields the same
    empty polygon rather than losing the artifact to a geometry library's error.
    """
    ys, xs = np.nonzero(mask)
    if xs.size < 3:
        return np.zeros((0, 2), dtype=np.float64)
    pts = np.column_stack([xs, ys]).astype(np.float64)
    # Deferred: scipy.spatial costs over a second to import and this is its only
    # use in the package, so a bare --version/--help never pays for it.
    from scipy.spatial import ConvexHull, QhullError

    try:
        verts = ConvexHull(pts).vertices
    except QhullError:  # collinear: pixels but no area to enclose
        return np.zeros((0, 2), dtype=np.float64)
    loop = np.append(verts, verts[0])  # close the polygon
    return np.asarray(pts[loop], dtype=np.float64)


def _ghost_regions(result: QAResult) -> GhostRegions | None:
    """The region-matched signal/ghost masks per in-plane axis, or None.

    Copied off the `GhostResult` the run measured on, not rebuilt here: the
    published regions are the ones the percentages were averaged over, by
    construction rather than by two call sites agreeing. None when no axis
    resolved — nothing was sampled, so there is nothing to draw.
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
    """The four fBIRN summary images plus the geometry drawn over them."""
    images, geom, roi = result.images, result.geom, result.roi
    fluctuation_noise = images.fluctuation_noise
    # Per-voxel SFNR inside the phantom; the epsilon keeps the ratio finite where
    # a masked-in voxel has no temporal noise at all.
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
