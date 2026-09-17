"""The `QAArtifact` value objects: the calculation half's published output.

An artifact is everything a reader — a report, a plot, a spreadsheet, a trend
database — needs about one analyzed series, and *nothing* that only the
calculation needs. The heavy inputs (the 4-D series, the trimmed center slice,
the per-voxel fluctuations) stay behind in `pipeline.QAResult`; what crosses the
seam is small, self-describing, and serializable (see `serialize`).

Five sections, in the order a reader consumes them:

* `AnalysisSettings` -- the knobs the run was asked for, plus what they resolved to
  (`settings.AnalysisSettings`, since both `run_qa` and this artifact speak it;
  the one thing here that is not defined here)
* `Provenance`       -- where the data came from and what produced this artifact
* `Measurements`     -- the settled scalars (the numbers a table or a threshold reads)
* `Curves`           -- the 1-D traces a stability plot draws
* `ArtifactImages`   -- the four fBIRN summary images plus the overlays drawn on them

Nothing here imports the metric, prep, or load layers: an artifact is inert data.
`build` projects a `QAResult` into one; `serialize` moves it to and from disk.
"""

from dataclasses import dataclass

from .._arrays import ArrayValue
from ..settings import AnalysisSettings
from ..types import BoolArray, FloatArray, LengthUnit, PeAxis, PeLabel

# Bumped whenever the on-disk layout changes incompatibly (see `serialize`).
# 2: added the `phantom_fraction` / `roi_inside_phantom` localization diagnostics.
# 3: added `phantom_mask_ok`, the verdict on `phantom_fraction`.
# 4: added `Provenance.n_trimmed`, the warm-up volumes dropped before analysis.
# 5: added `Provenance.slice_index`/`n_slices` (the plane analyzed) and
#    `Measurements.phantom_contrast` (the second half of the mask verdict);
#    `AnalysisSettings.roi_size` is the side requested, no longer the clamped one.
# 6: added `Measurements.displacement_unit`; `max_translation` and
#    `max_com_displacement` are now mm when the voxel size is known (previously
#    always voxels), the same convention `fwhm`/`fwhm_unit` already used.
# 7: the whole clipping block is now optional -- `n_clipped_kept`,
#    `n_clipped_pre`, `clipped_kept` and `clipped_any` are None together when
#    the series did not arrive as integers and the rail test could not be run.
ARTIFACT_SCHEMA_VERSION = 7


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where the analyzed series came from, and what produced the artifact.

    The first block identifies the run (`scan` is the display name, `source` the
    path it was read from, `created` an ISO-8601 UTC timestamp, `core_version`
    the calculating package's version). `tr` and `n_frames` describe the
    *analyzed* series — after the warm-up trim — so a reader can state the
    duration without the data, and `n_trimmed` is how many volumes that trim
    dropped: every frame index in the artifact (`Measurements.outlier_worst_frame`,
    `Curves.time`) counts from the trimmed series, and this is what maps one back
    to an acquired volume number. `slice_index` (0-based) and `n_slices` say
    which plane of the volume the images and every metric describe — the
    middle one under `center="image"`, the largest phantom cross-section under
    `center="phantom"` — without which two artifacts of one series cannot be
    told apart. `None` on any of these means *not recorded* — an artifact
    migrated from a schema that predates the field, where the trim or the slice
    choice happened but nothing wrote it down. `scan`, `source`, `created`,
    `core_version`, `tr`, and `n_frames` identify the run and are required — a
    validated artifact cannot exist without them. The rest is acquisition
    metadata copied from the BIDS sidecar and NIfTI header, every field of it
    optional because a scan without a sidecar still analyzes.
    """

    scan: str
    source: str
    created: str
    core_version: str
    tr: float
    n_frames: int
    n_trimmed: int | None = None  # warm-up volumes dropped; None = not recorded
    slice_index: int | None = None  # plane analyzed, 0-based; None = not recorded
    n_slices: int | None = None  # planes in the volume; None = not recorded
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
    do not carry. `phantom_mask_ok` is the verdict on the segmentation — that
    `phantom_fraction` is a share a phantom can cover *and* that
    `phantom_contrast` (mean inside the mask over mean outside it; infinite
    over an exactly-zero background) stands clear of noise — settled here so
    that every consumer agrees on it: the bounds live with the segmentation,
    which a reader in another distribution cannot import. The two numbers are
    kept beside the verdict so a report can say *which* test a bad mask failed.

    Both verdicts are `None` — and the fraction and contrast NaN — in an
    artifact migrated from a schema that predates them (see `serialize`).
    `analyze` never produces that; it means "not recorded", which is neither a
    pass nor a failure, and a reader that treats it as either is drawing a
    conclusion the data does not support.

    The clipping block answers three ways, not two. `clipped_any` False means
    the rail test ran and found no pile-up; `clipped_any` **None** means it could
    not run at all, because the series did not reach the analysis as the
    scanner's integer samples and an ADC rail is an integer artifact (see
    `metrics.saturation`). The other three clipping fields are None with it, and
    `clip_ceiling`/`clip_bits` are None in that case too -- though they are also
    None on a determinable series with no rail, so `clipped_any` is the field to
    test first. A reader that treats None as "clean" is reporting a scanner
    verified against a check that never happened. An artifact from schema <= 6
    always answers True or False here, because the build that wrote it always
    answered; that False means "found no rail", not "the storage was checked".

    `displacement_unit` governs both `max_translation` and
    `max_com_displacement`: one field, not two, because both estimators are
    handed the same in-plane `VoxelSize` by `run_qa` and so are always in the
    same unit for any artifact this build produces — a second field could only
    ever agree with the first, or drift from it by a bug. A migrated artifact
    is the one place they can legitimately differ from `fwhm_unit`: schema <= 5
    always published these two peaks in voxels regardless of whether the voxel
    size was known, so a migrated artifact's `displacement_unit` is "vox" even
    when its `fwhm_unit` is "mm" (see `serialize.migrate`).
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
    pe_axis: PeAxis | None
    pe_label: PeLabel
    # transient artifacts
    outlier_max_pct: float
    outlier_worst_frame: int
    tc_outlier: float
    spec_outlier: float
    # ADC saturation / clipping; all None together = the check could not be run
    clip_ceiling: float | None
    clip_bits: int | None
    n_clipped_kept: int | None
    n_clipped_pre: int | None
    clipped_kept: bool | None  # clipping reached the analyzed data (biases metrics)
    clipped_any: bool | None  # clipping anywhere, incl. the dropped warm-up volumes
    # phantom stability
    max_translation: float  # in `displacement_unit`
    max_scale_pct: float
    max_shear_pct: float
    max_com_displacement: float  # in `displacement_unit`
    displacement_unit: LengthUnit  # "mm" when the voxel size is known, else "vox"
    # spatial smoothness
    fwhm: float  # combined (AFNI ccomb), in `fwhm_unit`
    fwhm_pe: float | None
    fwhm_ro: float | None
    fwhm_unit: LengthUnit  # "mm" when the voxel size is known, else "vox"
    # localization sanity (see the class docstring); None = not recorded
    phantom_fraction: float  # share of the frame the phantom mask covers, [0, 1]
    phantom_contrast: float  # mask interior over background; inf = zero background
    phantom_mask_ok: bool | None  # a phantom: plausible share, real contrast
    roi_inside_phantom: bool | None  # the ROI lies wholly within the phantom


@dataclass(frozen=True, eq=False, slots=True)
class WeisskoffCurve(ArrayValue):
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
class PsfCurves(ArrayValue):
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
class Curves(ArrayValue):
    """The 1-D traces: everything a stability plot draws, per analyzed frame.

    `time` is the shared abscissa in seconds; the ROI series, outlier fraction,
    motion, and centroid traces are all indexed by it. The residual spectrum is
    stored already DC-dropped (`spectrum_hz` starts at the first nonzero bin) so
    a plot needs no windowing knowledge. The Weisskoff and PSF curves have their
    own abscissas and sit in their own objects. A failed or unconverged motion
    fit is an all-NaN frame in translation, scale, and shear; any failed frame
    makes the run's peak motion measurements NaN. This status survives storage
    without changing the archive layout.
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
class GhostRegions(ArrayValue):
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
class ArtifactImages(ArrayValue):
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
