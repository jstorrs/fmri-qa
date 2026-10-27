"""The `QAArtifact` value objects: the calculation half's published output.

An artifact holds what a reader (report, plot, spreadsheet, trend database)
needs about one analyzed series and nothing more. The heavy inputs (the 4-D
series, the trimmed center slice, the per-voxel fluctuations) stay in
`pipeline.QAResult`. What crosses the seam is small, self-describing and
serializable (see `serialize`).

Five sections, in the order a reader consumes them:

* `AnalysisSettings` -- the knobs the run was asked for, plus what they resolved to
  (defined in `settings`, since both `run_qa` and this artifact use it)
* `Provenance`       -- where the data came from and what produced this artifact
* `Measurements`     -- the settled scalars (the numbers a table or a threshold reads)
* `Curves`           -- the 1-D traces a stability plot draws
* `ArtifactImages`   -- the four FBIRN summary images plus the overlays drawn on them

Nothing here imports the metric, prep or load layers. An artifact is inert data.
`build` projects a `QAResult` into one. `serialize` reads and writes it on disk.
"""

import math
from dataclasses import dataclass
from typing import ClassVar

from .._arrays import ArrayValue
from .._records import coerce_float_fields
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
# 7: the whole clipping block is now optional. `n_clipped_kept`,
#    `n_clipped_pre`, `clipped_kept` and `clipped_any` are None together when
#    the series was not stored as integers and the rail test could not be run.
#: On-disk schema version of the QA artifact. Bumped on every incompatible layout
#: change.
ARTIFACT_SCHEMA_VERSION = 7


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where the analyzed series came from, and what produced the artifact.

    `scan` is the display name, `source` the path it was read from, `created` an
    ISO-8601 UTC timestamp, and `core_version` the calculating package's version.
    `tr` and `n_frames` describe the analyzed series, after the warm-up trim.
    `n_trimmed` is how many volumes the trim dropped. Every frame index in the
    artifact (`Measurements.outlier_worst_frame`, `Curves.time`) counts from the
    trimmed series, and `n_trimmed` maps one back to an acquired volume number.
    `slice_index` (0-based) and `n_slices` say which plane the images and every
    metric describe: the middle one under `center="image"`, the largest phantom
    cross-section under `center="phantom"`.

    `None` on `n_trimmed`, `slice_index` or `n_slices` means not recorded. The
    artifact was migrated from a schema that predates the field. `scan`,
    `source`, `created`, `core_version`, `tr` and `n_frames` are required. The
    rest is acquisition metadata from the BIDS sidecar and NIfTI header, all
    optional because a scan without a sidecar still analyzes.

    The constructor raises `ValueError` for a series with no frames, a
    non-positive TR, a slice index outside the volume, or a voxel with no size.
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

    def __post_init__(self) -> None:
        """Refuse a provenance record with out-of-range or inconsistent fields."""
        coerce_float_fields(self)
        _require(self.n_frames > 0, "invalid provenance.n_frames")
        _require(
            self.n_trimmed is None or self.n_trimmed >= 0,
            "invalid provenance.n_trimmed",
        )
        _require(
            self.n_slices is None or self.n_slices > 0, "invalid provenance.n_slices"
        )
        _require(
            self.slice_index is None
            or (
                self.slice_index >= 0
                and (self.n_slices is None or self.slice_index < self.n_slices)
            ),
            "invalid provenance.slice_index",
        )
        _require(math.isfinite(self.tr) and self.tr > 0, "invalid provenance.tr")
        if self.voxel_mm is not None:
            _require(
                all(math.isfinite(v) and v > 0 for v in self.voxel_mm),
                "invalid provenance.voxel_mm",
            )


@dataclass(frozen=True, slots=True)
class Measurements:
    """The settled scalar results for one scan.

    Every value is a number, a bool or a short string, so a table, a JSON record
    and an acceptance threshold read the same fields. Quantities the metric layer
    exposes as properties (peak motion, worst outlier frame, combined FWHM) are
    resolved here once, at build time.

    `pe_label` is the phase-encode direction to display ("row", "col" or "?"): the
    axis the ghost masks were built on, however it was settled (sidecar, header,
    `pe_axis_override` or the ghost estimate), or "?" if none was.

    The localization fields say whether the other numbers can be trusted. A
    collapsed segmentation still yields a mask, and an ROI in background still
    yields an average, so these let a stored artifact distinguish "the estimator
    declined" (NaN with good localization) from "the analysis measured
    background". `phantom_mask_ok` is the verdict on the segmentation:
    `phantom_fraction` is a share a phantom can cover, and `phantom_contrast`
    (mean inside the mask over mean outside; infinite over an exactly-zero
    background) stands clear of noise. It is settled here so every consumer
    agrees, since the bounds live with the segmentation, which a reader in
    another distribution cannot import. The two numbers stay so a report can say
    which test failed.

    Both verdicts are `None`, and the fraction and contrast NaN, in an artifact
    migrated from a schema that predates them (see `serialize`). That means "not
    recorded", neither a pass nor a failure. `analyze` never produces it.

    The clipping block has three answers. `clipped_any` False means the rail test
    ran and found no pile-up. **None** means it could not run, because the series
    was not stored as the scanner's integers and an ADC rail is an integer
    artifact (see `metrics.saturation`). The other three clipping fields are None
    with it. `clip_ceiling` and `clip_bits` are also None for a determinable
    series with no rail, so test `clipped_any` first. Treating None as "clean"
    reports a scanner verified by a check that never ran. An artifact from
    schema <= 6 always answers True or False here, because the build that wrote
    it always answered. That False means "found no rail", not "the storage was
    checked".

    `displacement_unit` covers both `max_translation` and `max_com_displacement`,
    since `run_qa` gives both estimators the same in-plane `VoxelSize`. A migrated
    artifact can differ from `fwhm_unit`: schema <= 5 published these peaks in
    voxels even when the voxel size was known, so `displacement_unit` is "vox"
    beside a `fwhm_unit` of "mm" (see `serialize.migrate`).

    The constructor enforces these pairings with `ValueError`, so
    `replace(m, pe_axis=None)` alone fails; the directional FWHMs must travel
    with the axis.
    """

    # FBIRN ROI stability
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

    def __post_init__(self) -> None:
        """Refuse measurements whose fields disagree or fall out of range."""
        coerce_float_fields(self)
        # `fwhm_pe`/`fwhm_ro` are None exactly when no axis resolved
        # (`SmoothnessResult.fwhm_pe`), in every build since schema 1, and no
        # migration touches them. That is one fact stored twice. `pe_label` is
        # deliberately not held to `pe_axis`: builds before the label was
        # derived from the axis took it from the sidecar's DICOM wording, which
        # could name another axis (a through-plane `k`, a self-contradicting
        # sidecar) or none. Those archives keep what their build recorded.
        _require(
            (self.fwhm_pe is None) == (self.pe_axis is None),
            "measurements.fwhm_pe disagrees with measurements.pe_axis",
        )
        _require(
            (self.fwhm_ro is None) == (self.pe_axis is None),
            "measurements.fwhm_ro disagrees with measurements.pe_axis",
        )
        _require(
            math.isnan(self.phantom_contrast) or self.phantom_contrast >= 0,
            "invalid measurements.phantom_contrast",
        )
        self._check_clipping()

    def _check_clipping(self) -> None:
        """Hold the clipping block to the counts that produced it."""
        # The block is answered as a unit or not at all. A record carrying some
        # of it and not the rest is malformed, however plausible each field
        # looks alone.
        counts = (self.n_clipped_kept, self.n_clipped_pre)
        clipping = (*counts, self.clipped_any, self.clipped_kept)
        _require(
            len({value is None for value in clipping}) == 1,
            "clipping fields disagree about whether the check ran",
        )
        _require(
            all(count is None or count >= 0 for count in counts),
            "invalid clipping counts",
        )
        # `clipped_any`/`clipped_kept` are properties of the counts in
        # `metrics.saturation.SaturationResult`, stored again only because the
        # artifact is flat. The check above guarantees all clipping fields are
        # None or none are. The guard below only narrows the type.
        if self.n_clipped_kept is None or self.n_clipped_pre is None:
            return
        _require(
            self.clipped_kept == (self.n_clipped_kept > 0),
            "measurements.clipped_kept disagrees with measurements.n_clipped_kept",
        )
        _require(
            self.clipped_any == (self.n_clipped_pre + self.n_clipped_kept > 0),
            "measurements.clipped_any disagrees with the clipping counts",
        )


@dataclass(frozen=True, eq=False, slots=True)
class WeisskoffCurve(ArrayValue):
    """The Weisskoff/RDC curves over the sampled ROI widths.

    `cv` is the measured ROI-averaged coefficient of variation. `cv_ideal` is
    the `cv1_pooled / width` reference line the graphical RDC is read against.
    It is precomputed here so a plot draws two series rather than re-deriving the
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

    Two directions, phase-encode first. `labels` names them ("PE"/"RO", or
    "axis0"/"axis1" when no PE axis resolved). `empirical` holds the measured PSF
    at each sampled lag (`displacement`). `model` holds the Gaussian implied by
    the measured FWHM, sampled on `model_x`. The model sampling and the plotting
    range (`xmax`) are fixed here, so a report draws the curve the analysis
    produced, not a re-derivation.
    """

    labels: tuple[str, str]
    fwhm: tuple[float, float]
    unit: LengthUnit  # matches `Measurements.fwhm_unit`
    displacement: FloatArray  # (2, n_lag)
    empirical: FloatArray  # (2, n_lag)
    model_x: FloatArray  # (2, n_model)
    model: FloatArray  # (2, n_model)
    xmax: float

    def __post_init__(self) -> None:
        """Copy the arrays read-only, then coerce the float fields."""
        # Zero-argument `super()` cannot find its class in a slots dataclass,
        # which is a new class object built after this body runs.
        ArrayValue.__post_init__(self)
        coerce_float_fields(self)


@dataclass(frozen=True, eq=False, slots=True)
class Curves(ArrayValue):
    """The 1-D traces: everything a stability plot draws, per analyzed frame.

    `time` is the shared abscissa in seconds. The ROI series, outlier fraction,
    motion and centroid traces are all indexed by it. The residual spectrum is
    stored with DC already dropped (`spectrum_hz` starts at the first nonzero
    bin), so a plot needs no windowing knowledge. The Weisskoff and PSF curves
    have their own abscissas and sit in their own objects. A failed or
    unconverged motion fit is an all-NaN frame in translation, scale and shear.
    Any failed frame makes the run's peak motion measurements NaN. This status
    survives storage without changing the archive layout.
    """

    time: FloatArray  # (T,) seconds
    roi_signal: FloatArray  # (T,) ROI-mean raw signal
    roi_trend: FloatArray  # (T,) fitted low-frequency trend
    roi_residual: FloatArray  # (T,) detrended residual
    outlier_fraction: FloatArray  # (T,) fraction of outlier voxels per frame
    outlier_qthr: float  # threshold tuning parameter, used as qthr / n_frames
    spectrum_hz: FloatArray  # (F,) DC dropped
    spectrum_magnitude: FloatArray  # (F,)
    translation: FloatArray  # (T, 2) voxels
    scale_pct: FloatArray  # (T, 2) percent
    shear_pct: FloatArray  # (T,) percent
    com_deviation: FloatArray  # (T, 2) voxels
    weisskoff: WeisskoffCurve
    psf: PsfCurves

    def __post_init__(self) -> None:
        """Copy the arrays read-only, then coerce the float fields."""
        # Zero-argument `super()` cannot find its class in a slots dataclass,
        # which is a new class object built after this body runs.
        ArrayValue.__post_init__(self)
        coerce_float_fields(self)


@dataclass(frozen=True, slots=True)
class RoiBox:
    """The summary ROI as plain half-open bounds, in array (row, col) order.

    The constructor requires the box to be square with a positive side, so
    `size` is the one side both axes share. Whether the box lies inside the
    image is a fact about the image, which a box alone does not carry.
    `validation` checks that half.
    """

    row0: int
    row1: int
    col0: int
    col1: int

    def __post_init__(self) -> None:
        """Refuse a box unless square, with a positive side and non-negative origin."""
        # The same message the image-shape half uses, so a reader of a refused
        # artifact learns which box is wrong, not which check caught it.
        _require(
            0 <= self.row0 < self.row1
            and 0 <= self.col0 < self.col1
            and self.row1 - self.row0 == self.col1 - self.col0,
            "images.roi must be square and inside the image",
        )

    @property
    def size(self) -> int:
        """The ROI side in voxels."""
        return self.row1 - self.row0


@dataclass(frozen=True, eq=False, slots=True)
class GhostRegions(ArrayValue):
    """The region-matched masks the ghost percentages are averaged over.

    One signal/ghost pair per in-plane axis. The PE pair feeds `ghost_pct` and
    the readout pair feeds the `ro_ghost_pct` baseline. They are carried so an
    overlay shows where the reported numbers were sampled. Absent when no PE
    axis resolved.
    """

    pe_signal: BoolArray
    pe_ghost: BoolArray
    ro_signal: BoolArray
    ro_ghost: BoolArray


@dataclass(frozen=True, eq=False, slots=True)
class ArtifactImages(ArrayValue):
    """The four FBIRN summary images plus the geometry drawn on top of them.

    `signal`, `sfnr`, `fluctuation_noise` and `static_noise` are the FBIRN
    quartet: temporal mean, per-voxel SFNR, temporal noise RMS, and the odd/even
    difference. The rest is annotation. That is the phantom segmentation and its
    convex outline (`phantom_hull`, a closed polygon in plot (x=col, y=row)
    order, so a renderer needs no computational geometry), the zeroed-edge mask
    excluded from every statistic, the ROI box, and the ghost sampling regions.
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
    half accepts. Immutable, self-describing and round-trippable through
    `fmriqa_io.save_artifact`/`load_artifact`. The class constant
    `schema_version` is the layout those two agree on (loading migrates every
    file up to it).
    """

    settings: AnalysisSettings
    provenance: Provenance
    measurements: Measurements
    curves: Curves
    images: ArtifactImages
    schema_version: ClassVar[int] = ARTIFACT_SCHEMA_VERSION
