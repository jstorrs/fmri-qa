"""The `QAArtifact` value objects: the calculation half's published output.

An artifact is everything a reader — a report, a plot, a spreadsheet, a trend
database — needs about one analyzed series, and *nothing* that only the
calculation needs. The heavy inputs (the 4-D series, the trimmed center slice,
the per-voxel fluctuations) stay behind in `pipeline.QAResult`; what crosses the
seam is small, self-describing, and serializable (see `serialize`).

Five sections, in the order a reader consumes them:

* `AnalysisSettings` -- the knobs the run was asked for, plus what they resolved to
* `Provenance`       -- where the data came from and what produced this artifact
* `Measurements`     -- the settled scalars (the numbers a table or a threshold reads)
* `Curves`           -- the 1-D traces a stability plot draws
* `ArtifactImages`   -- the four fBIRN summary images plus the overlays drawn on them

Nothing here imports the metric, prep, or load layers: an artifact is inert data.
`build` projects a `QAResult` into one; `serialize` moves it to and from disk.
"""

from dataclasses import dataclass

from ..types import (
    FBIRN_ROI_SIZE,
    BoolArray,
    DetrendMethod,
    FloatArray,
    LengthUnit,
    PeLabel,
    RoiCenter,
)

# Bumped whenever the on-disk layout changes incompatibly (see `serialize`).
# 2: added the `phantom_fraction` / `roi_inside_phantom` localization diagnostics.
# 3: added `phantom_mask_ok`, the verdict on `phantom_fraction`.
ARTIFACT_SCHEMA_VERSION = 3


@dataclass(frozen=True, slots=True)
class AnalysisSettings:
    """The analysis knobs: what the run was asked for, and what that resolved to.

    The first five fields are the request — exactly the parameters `analyze`
    accepts, so re-running with these settings reproduces the artifact.
    `detrend_order` is the *resolved* value (the polynomial degree or the spline
    interior-knot count the detrender chose for this series length), recorded
    because it is a run parameter a reader must be able to report but only the
    pipeline knows.
    """

    trim_sec: float = 5.0
    detrend: DetrendMethod = "poly"
    center: RoiCenter = "image"
    roi_size: int = FBIRN_ROI_SIZE
    pe_axis_override: int | None = None
    detrend_order: int | None = None


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where the analyzed series came from, and what produced the artifact.

    The first block identifies the run (`scan` is the display name, `source` the
    path it was read from, `created` an ISO-8601 UTC timestamp, `core_version`
    the calculating package's version). `tr` and `n_frames` describe the
    *analyzed* series — after the warm-up trim — so a reader can state the
    duration without the data. The rest is acquisition metadata copied from the
    BIDS sidecar and NIfTI header; every field is optional because a scan
    without a sidecar still analyzes.
    """

    scan: str = ""
    source: str = ""
    created: str = ""
    core_version: str = ""
    tr: float = 0.0
    n_frames: int = 0
    voxel_mm: tuple[float, float, float] | None = None
    matrix: tuple[int, int] | None = None
    te: float | None = None  # s
    flip_angle: float | None = None  # degrees
    slice_thickness: float | None = None  # mm
    pe_dir: str | None = None  # DICOM row/col
    coil: str | None = None
    manufacturer: str | None = None
    model: str | None = None
    serial: str | None = None
    field_strength: float | None = None  # tesla
    software: str | None = None
    datetime: str | None = None
    series: str | None = None


@dataclass(frozen=True, slots=True)
class Measurements:
    """The settled scalar results for one scan.

    Flat by design: every value is a number, a bool, or a short string, so a
    table, a JSON record, and an acceptance threshold all read the same fields
    without walking into per-metric result objects. The derived quantities the
    metric layer exposes as properties (peak motion, worst outlier frame, the
    combined FWHM) are resolved here once, at build time.

    `pe_label` is the phase-encode direction as it should be *displayed* ("row",
    "col", or "?"): the sidecar's DICOM direction when the run did not override
    the axis, otherwise the label of the axis actually used.

    The two localization fields say whether the numbers beside them can be
    trusted at all. Every mask-based metric is measured through the phantom
    segmentation and the summary ROI, and both can fail *quietly*: a collapsed
    segmentation still yields a mask, and an ROI sitting in background still
    yields an average. Recording them here means a reader of a stored artifact
    can tell "the estimator declined" (a NaN with good localization) from "the
    analysis was measuring background" — a distinction the metric values alone
    do not carry. `phantom_mask_ok` is the verdict on `phantom_fraction`, settled
    here so that every consumer agrees on it: the bounds live with the
    segmentation, which a reader in another distribution cannot import.

    Both verdicts are `None` — and `phantom_fraction` NaN — in an artifact
    migrated from a schema that predates the check (see `serialize`). `analyze`
    never produces that; it means "not recorded", which is neither a pass nor a
    failure, and a reader that treats it as either is drawing a conclusion the
    data does not support.
    """

    # fBIRN ROI stability
    snr: float
    sfnr: float
    rdc: float
    drift_pct: float
    percent_fluctuation: float
    # Nyquist ghosting
    ghost_pct: float
    ghost_top_pct: float
    ro_ghost_pct: float
    acr_ghost_pct: float
    pe_axis: int | None
    pe_label: PeLabel
    # transient artifacts
    outlier_max_pct: float
    outlier_worst_frame: int
    tc_outlier: float
    spec_outlier: float
    # ADC saturation / clipping
    clip_ceiling: float | None
    clip_bits: int | None
    n_clipped_kept: int
    n_clipped_pre: int
    clipped_kept: bool  # clipping reached the analyzed data (biases the metrics)
    clipped_any: bool  # clipping anywhere, including the dropped warm-up volumes
    # phantom stability
    max_translation: float
    max_scale_pct: float
    max_shear_pct: float
    max_com_displacement: float
    # spatial smoothness
    fwhm: float  # combined (AFNI ccomb), in `fwhm_unit`
    fwhm_pe: float | None
    fwhm_ro: float | None
    fwhm_unit: LengthUnit  # "mm" when the voxel size is known, else "vox"
    # localization sanity (see the class docstring); None = not recorded
    phantom_fraction: float  # share of the frame the phantom mask covers, [0, 1]
    phantom_mask_ok: bool | None  # that share is one a real phantom mask can take
    roi_inside_phantom: bool | None  # the ROI lies wholly within the phantom


@dataclass(frozen=True, eq=False, slots=True)
class WeisskoffCurve:
    """The Weisskoff/RDC curves over the sampled ROI widths.

    `cv` is the measured ROI-averaged coefficient of variation and `cv_ideal`
    the `cv1_pooled / width` reference line the graphical RDC is read against —
    precomputed here so a plot draws two series rather than re-deriving the
    anchor. `rdc` is the per-width decorrelation factor (`cv1 / cv`), whose value
    at the full ROI is `Measurements.rdc`.
    """

    roi_sizes: FloatArray  # (K,) ROI widths in voxels
    cv: FloatArray  # (K,) measured
    cv_ideal: FloatArray  # (K,) cv1_pooled / roi_sizes
    rdc: FloatArray  # (K,) rdc curve


@dataclass(frozen=True, eq=False, slots=True)
class PsfCurves:
    """Directional point-spread profiles of the noise field (AFNI 3dFWHMx).

    Two directions, phase-encode first: `labels` names them ("PE"/"RO", or
    "axis0"/"axis1" when no PE axis resolved). `empirical` holds the measured PSF
    at each sampled lag (`displacement`); `model` holds the Gaussian implied by
    the measured FWHM, sampled on `model_x`. Both the model sampling and the
    plotting range (`xmax`) are fixed here so the curve a report draws is the
    curve the analysis meant, not a re-derivation.
    """

    labels: tuple[str, str]
    fwhm: tuple[float, float]
    unit: LengthUnit  # matches `Measurements.fwhm_unit`
    displacement: FloatArray  # (2, n_lag)
    empirical: FloatArray  # (2, n_lag)
    model_x: FloatArray  # (2, n_model)
    model: FloatArray  # (2, n_model)
    xmax: float


@dataclass(frozen=True, eq=False, slots=True)
class Curves:
    """The 1-D traces: everything a stability plot draws, per analyzed frame.

    `time` is the shared abscissa in seconds; the ROI series, outlier fraction,
    motion, and centroid traces are all indexed by it. The residual spectrum is
    stored already DC-dropped (`spectrum_hz` starts at the first nonzero bin) so
    a plot needs no windowing knowledge. The Weisskoff and PSF curves have their
    own abscissas and sit in their own objects.
    """

    time: FloatArray  # (T,) seconds
    roi_signal: FloatArray  # (T,) ROI-mean raw signal
    roi_trend: FloatArray  # (T,) fitted low-frequency trend
    roi_residual: FloatArray  # (T,) detrended residual
    outlier_fraction: FloatArray  # (T,) fraction of outlier voxels per frame
    outlier_qthr: float  # per-voxel chance level (the reference line)
    spectrum_hz: FloatArray  # (F,) DC dropped
    spectrum_magnitude: FloatArray  # (F,)
    translation: FloatArray  # (T, 2) voxels
    scale_pct: FloatArray  # (T, 2) percent
    shear_pct: FloatArray  # (T,) percent
    com_deviation: FloatArray  # (T, 2) voxels
    weisskoff: WeisskoffCurve
    psf: PsfCurves


@dataclass(frozen=True, slots=True)
class RoiBox:
    """The summary ROI as plain half-open bounds, in array (row, col) order."""

    row0: int
    row1: int
    col0: int
    col1: int

    @property
    def size(self) -> int:
        """The ROI side in voxels."""
        return self.row1 - self.row0


@dataclass(frozen=True, eq=False, slots=True)
class GhostRegions:
    """The region-matched masks the ghost percentages are averaged over.

    One signal/ghost pair per in-plane axis: the PE pair feeds `ghost_pct`, the
    readout pair the `ro_ghost_pct` baseline. Carried so an overlay shows exactly
    where the reported numbers were sampled. Absent when no PE axis resolved.
    """

    pe_signal: BoolArray
    pe_ghost: BoolArray
    ro_signal: BoolArray
    ro_ghost: BoolArray


@dataclass(frozen=True, eq=False, slots=True)
class ArtifactImages:
    """The four fBIRN summary images plus the geometry drawn on top of them.

    `signal`, `sfnr`, `fluctuation_noise`, and `static_noise` are the fBIRN
    quartet — temporal mean, per-voxel SFNR, temporal noise RMS, and the odd/even
    difference. The rest is annotation: the phantom segmentation and its convex
    outline (`phantom_hull`, a closed polygon in plot (x=col, y=row) order, so a
    renderer needs no computational geometry), the zeroed-edge mask excluded from
    every statistic, the ROI box, and the ghost sampling regions.
    """

    signal: FloatArray  # (X, Y) temporal mean
    sfnr: FloatArray  # (X, Y) mean / temporal noise, inside the phantom
    fluctuation_noise: FloatArray  # (X, Y) temporal RMS of the residuals
    static_noise: FloatArray  # (X, Y) odd/even difference
    phantom_mask: BoolArray  # (X, Y)
    invalid_mask: BoolArray  # (X, Y) zeroed image edge, excluded from statistics
    phantom_hull: FloatArray  # (N, 2) closed convex outline, (x, y)
    roi: RoiBox
    ghost: GhostRegions | None


@dataclass(frozen=True, eq=False, slots=True)
class QAArtifact:
    """One analyzed series, as everything downstream needs and nothing more.

    The output of the calculation half (`analyze`) and the only input the report
    half accepts. Immutable, self-describing, and round-trippable through
    `save_artifact`/`load_artifact`; `schema_version` pins the layout those two
    agree on.
    """

    settings: AnalysisSettings
    provenance: Provenance
    measurements: Measurements
    curves: Curves
    images: ArtifactImages
    schema_version: int = ARTIFACT_SCHEMA_VERSION
