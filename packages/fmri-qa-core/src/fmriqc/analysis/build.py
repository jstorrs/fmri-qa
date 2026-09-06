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

from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version

import numpy as np
from scipy.spatial import ConvexHull, QhullError

from ..load.metadata import ScanMeta
from ..load.pe_axis import PE_ROWCOL
from ..load.scan import QAScan
from ..metrics.ghost import GHOST_RADIUS, ghost_masks
from ..metrics.smoothness import SmoothnessResult
from ..pipeline import QAResult, run_qa
from ..prep.geometry import ROI, roi_fits
from ..types import BoolArray, FloatArray, LengthUnit, PeLabel
from .artifact import (
    AnalysisSettings,
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


def core_version() -> str:
    """The installed `fmri-qa-core` version, or "unknown" from a bare source tree."""
    try:
        return version("fmri-qa-core")
    except PackageNotFoundError:
        return "unknown"


def analyze(
    scan: QAScan,
    settings: AnalysisSettings | None = None,
    *,
    name: str = "",
    source: str = "",
) -> QAArtifact:
    """Run the QA pipeline on one series and publish the artifact.

    The calculation half's entry point: `scan` in, `QAArtifact` out, with the
    heavy intermediates discarded. `settings` are the analysis knobs (defaults
    match `run_qa`); `name` and `source` are recorded as provenance — the display
    name and the path the series was read from.
    """
    settings = settings or AnalysisSettings()
    result = run_qa(
        scan,
        trim_sec=settings.trim_sec,
        pe_axis=settings.pe_axis_override,
        detrend=settings.detrend,
        center=settings.center,
        roi_size=settings.roi_size,
    )
    return build_artifact(result, settings, name=name, source=source)


def build_artifact(
    result: QAResult,
    settings: AnalysisSettings | None = None,
    *,
    name: str = "",
    source: str = "",
) -> QAArtifact:
    """Project a computed `QAResult` into a `QAArtifact`.

    Separate from `analyze` so an existing result — one already in hand from
    `run_qa`, with its images still live — can be published without recomputing.
    """
    settings = settings or AnalysisSettings()
    images = result.images
    # The detrend order is only known after preprocessing, so the recorded
    # settings are the requested knobs with that one resolved value filled in.
    resolved = AnalysisSettings(
        trim_sec=settings.trim_sec,
        detrend=images.detrend_method,
        center=settings.center,
        roi_size=result.roi.size,
        pe_axis_override=settings.pe_axis_override,
        detrend_order=images.detrend_order,
    )
    return QAArtifact(
        settings=resolved,
        provenance=_provenance(result, name=name, source=source),
        measurements=_measurements(result, resolved),
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
    )
    if meta is None:
        return base
    # `dataclasses.replace` would be shorter but hides which sidecar fields are
    # carried; the artifact's acquisition block is a published contract, so spell
    # it out and let a new sidecar field be a deliberate addition here.
    return Provenance(
        scan=base.scan,
        source=base.source,
        created=base.created,
        core_version=base.core_version,
        tr=base.tr,
        n_frames=base.n_frames,
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


# The two direction words, narrowed to the set the artifact publishes. Both
# sources hand this module a plain `str`: `PE_ROWCOL` is the single definition
# of the axis -> word map and sits in `load`, below the layer that owns the
# published set, and the sidecar's DICOM direction is whatever the converter
# wrote. Looking the word up here is what makes `pe_label` true of its type.
_PE_LABELS: dict[str, PeLabel] = {"row": "row", "col": "col"}


def _pe_label(result: QAResult, settings: AnalysisSettings) -> PeLabel:
    """The phase-encode direction to display: "row", "col", or "?".

    The sidecar's DICOM direction is authoritative, but only when the run took
    the axis from metadata; an explicit `--pe-axis` override wins, so the label
    always names the axis the ghost masks actually used. A direction that is
    neither word — a sidecar can carry any string — is "?", the same answer as
    no axis at all.
    """
    if settings.pe_axis_override is None and result.meta and result.meta.pe_dir:
        return _PE_LABELS.get(result.meta.pe_dir, "?")
    axis = result.metrics.pe_axis
    return "?" if axis is None else _PE_LABELS.get(PE_ROWCOL.get(axis, ""), "?")


def _measurements(result: QAResult, settings: AnalysisSettings) -> Measurements:
    """Settle every reported scalar, resolving the metric objects' properties."""
    m = result.metrics
    sat, sm = m.saturation, m.smoothness
    return Measurements(
        snr=m.snr,
        sfnr=m.sfnr,
        rdc=m.rdc,
        drift_pct=m.drift_pct,
        percent_fluctuation=m.percent_fluctuation,
        ghost_pct=m.ghost_pct,
        ghost_top_pct=m.ghost_top_pct,
        ro_ghost_pct=m.ro_ghost_pct,
        acr_ghost_pct=m.acr_ghost_pct,
        pe_axis=m.pe_axis,
        pe_label=_pe_label(result, settings),
        outlier_max_pct=100.0 * m.outliers.max_fraction,
        outlier_worst_frame=m.outliers.worst_volume,
        tc_outlier=m.spikes.tc_outlier,
        spec_outlier=m.spikes.spec_outlier,
        clip_ceiling=sat.ceiling,
        clip_bits=sat.bits,
        n_clipped_kept=sat.n_clipped_kept,
        n_clipped_pre=sat.n_clipped_pre,
        clipped_kept=sat.clipped_kept,
        clipped_any=sat.clipped,
        max_translation=m.motion.max_translation,
        max_scale_pct=m.motion.max_scale_pct,
        max_shear_pct=m.motion.max_shear_pct,
        max_com_displacement=m.center_of_mass.max_displacement,
        fwhm=sm.fwhm,
        fwhm_pe=sm.fwhm_pe,
        fwhm_ro=sm.fwhm_ro,
        fwhm_unit="mm" if sm.voxel_mm is not None else "vox",
        phantom_fraction=result.geom.fraction,
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
        # plateau meets this line is the reported RDC (see `_plot_weisskoff`).
        cv_ideal=np.asarray(wk.cv1_pooled / sizes, dtype=np.float64),
        rdc=np.asarray(wk.rdc_curve, dtype=np.float64),
    )


def _psf_curves(s: SmoothnessResult) -> PsfCurves:
    """Sample the directional PSF: empirical points plus the Gaussian model.

    The plotting range is fixed here — a few FWHM, but at least three voxels so a
    PSF narrower than the voxel grid is not squashed — because it depends on the
    measured smoothness, which is analysis, not layout.
    """
    if s.pe_axis is not None:
        # ro_axis == 1 - pe_axis; spell it out so both entries are concrete ints.
        dirs = (("PE", s.pe_axis), ("RO", 1 - s.pe_axis))
    else:  # no PE axis resolved -- fall back to raw array axes
        dirs = (("axis0", 0), ("axis1", 1))
    unit: LengthUnit = "mm" if s.voxel_mm is not None else "vox"
    mm_per = [s.voxel_mm[a] if s.voxel_mm is not None else 1.0 for _, a in dirs]
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
        unit=unit,
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
    try:
        verts = ConvexHull(pts).vertices
    except QhullError:  # collinear: pixels but no area to enclose
        return np.zeros((0, 2), dtype=np.float64)
    loop = np.append(verts, verts[0])  # close the polygon
    return np.asarray(pts[loop], dtype=np.float64)


def _ghost_regions(result: QAResult) -> GhostRegions | None:
    """The region-matched signal/ghost masks per in-plane axis, or None.

    Rebuilds exactly the masks `ghost_ratio` averaged over, using the PE axis the
    run resolved. None when no axis resolved — there is nothing meaningful to
    sample or draw.
    """
    pe_axis = result.metrics.pe_axis
    if pe_axis not in (0, 1):
        return None
    phantom, valid = result.geom.phantom_mask, result.images.valid_mask
    pe_signal, pe_ghost = ghost_masks(phantom, pe_axis, GHOST_RADIUS, valid)
    ro_signal, ro_ghost = ghost_masks(phantom, 1 - pe_axis, GHOST_RADIUS, valid)
    return GhostRegions(
        pe_signal=pe_signal,
        pe_ghost=pe_ghost,
        ro_signal=ro_signal,
        ro_ghost=ro_ghost,
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
