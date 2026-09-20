"""Per-metric vocabulary: the label, definition, method, and value formatter.

One `MetricDoc` per reported metric is the single source for what a metric is
called, how its value is formatted, what it means, and how it is computed. Every
formatter reads the artifact's flat `Measurements`, so a report needs nothing
but the artifact to render a metric. The run page's metric tiles and its
definitions list both read this catalog, so a metric's name and formatting
can't drift between them.

The prose is condensed from `notes/` and the metric modules; see those for the
full derivations. Each `method` names the order of operations the code actually
performs — where two textbook forms differ (SFNR averaged over voxelwise ratios
versus measured on the ROI-mean series, say), the text follows the code, and a
test on the calculation side pins the difference.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from fmriqc.analysis import Measurements

MetricName = Literal[
    "snr",
    "sfnr",
    "rdc",
    "ghost_pct",
    "ghost_top_pct",
    "ro_ghost_pct",
    "acr_ghost_pct",
    "drift_pct",
    "percent_fluctuation",
    "outlier_max_pct",
    "tc_outlier",
    "spec_outlier",
    "max_translation",
    "max_com_displacement",
    "fwhm",
]


@dataclass(frozen=True, slots=True)
class MetricDoc:
    """A reported metric's stable identity, meaning, display, and value."""

    label: str
    definition: str
    method: str
    fmt: Callable[[Measurements], str]
    name: MetricName
    value: Callable[[Measurements], float]


def _fwhm_label(m: Measurements) -> str:
    """Combined FWHM tile text: mm when the voxel size is known, else voxels."""
    return f"{m.fwhm:.2f}{m.fwhm_unit}"


def _motn_label(m: Measurements) -> str:
    """Peak motion tile text: mm when the voxel size is known, else voxels."""
    return f"{m.max_translation:.2f}{m.displacement_unit}"


def _com_label(m: Measurements) -> str:
    """Peak COM-shift tile text: mm when the voxel size is known, else voxels."""
    return f"{m.max_com_displacement:.2f}{m.displacement_unit}"


# The reported metrics, in display order. The tile label and value formatter here
# are the ones the header tiles use, so the tiles and the physics tables agree.
METRIC_DOCS: tuple[MetricDoc, ...] = (
    MetricDoc(
        "SNR",
        "Image signal-to-noise: ROI mean signal over the static spatial noise.",
        "fBIRN: static noise from the odd/even difference image over the ROI.",
        lambda m: f"{m.snr:.1f}",
        name="snr",
        value=lambda m: m.snr,
    ),
    MetricDoc(
        "SFNR",
        "Signal-to-fluctuation-noise: ROI average of the voxelwise temporal SNR.",
        "fBIRN/Glover: per voxel, temporal mean / detrended temporal SD; then the "
        "ROI mean of those ratios (not the ratio of the ROI-mean series).",
        lambda m: f"{m.sfnr:.1f}",
        name="sfnr",
        value=lambda m: m.sfnr,
    ),
    MetricDoc(
        "RDC",
        "Radius of decorrelation: single-voxel CV over the full-ROI CV "
        "(ideal = ROI width).",
        "Weisskoff: measured CV vs ROI width against the ideal 1/width line; "
        "RDC = pooled single-voxel CV / ROI-mean CV at the full ROI.",
        lambda m: f"{m.rdc:.2f}",
        name="rdc",
        value=lambda m: m.rdc,
    ),
    MetricDoc(
        "ghost",
        "Nyquist (N/2) ghost along the phase-encode axis, region mean.",
        "Phantom rolled half the FOV along PE; ghost-region mean over the mean of "
        "the matched signal region it was rolled from.",
        lambda m: f"{m.ghost_pct:.2f}%",
        name="ghost_pct",
        value=lambda m: m.ghost_pct,
    ),
    MetricDoc(
        "ghostT",
        "Peak N/2 ghost: the brightest 10% of ghost voxels (>= ghost).",
        "Greve / bxh fmriqa_ghostiness; surfaces a localized bright ghost.",
        lambda m: f"{m.ghost_top_pct:.2f}%",
        name="ghost_top_pct",
        value=lambda m: m.ghost_top_pct,
    ),
    MetricDoc(
        "RO",
        "Readout-axis ghost baseline (background-relative).",
        "The N/2 construction along the readout axis; the ACRg baseline.",
        lambda m: f"{m.ro_ghost_pct:.2f}%",
        name="ro_ghost_pct",
        value=lambda m: m.ro_ghost_pct,
    ),
    MetricDoc(
        "ACRg",
        "ACR ghosting ratio: PE ghost against the readout baseline.",
        "|ghost - RO|, the ACR phantom-QA ghosting figure in region-matched form.",
        lambda m: f"{m.acr_ghost_pct:.2f}%",
        name="acr_ghost_pct",
        value=lambda m: m.acr_ghost_pct,
    ),
    MetricDoc(
        "drift",
        "Slow signal drift across the run.",
        "fBIRN: peak-to-trough of the fitted trend over the mean signal.",
        lambda m: f"{m.drift_pct:.3f}%",
        name="drift_pct",
        value=lambda m: m.drift_pct,
    ),
    MetricDoc(
        "fluct",
        "Percent temporal fluctuation of the ROI-mean time course.",
        "fBIRN/Glover: SD of the detrended ROI-mean series over the ROI mean "
        "signal (the ROI-mean form SFNR does not use).",
        lambda m: f"{m.percent_fluctuation:.3f}%",
        name="percent_fluctuation",
        value=lambda m: m.percent_fluctuation,
    ),
    MetricDoc(
        "outl",
        "Worst single-frame outlier-voxel fraction.",
        "AFNI 3dToutcount; qthr tunes a length-dependent threshold, "
        "not an expected per-frame outlier fraction.",
        lambda m: f"{m.outlier_max_pct:.2f}%",
        name="outlier_max_pct",
        value=lambda m: m.outlier_max_pct,
    ),
    MetricDoc(
        "tcOut",
        "Time-domain spike score of the ROI-mean residual.",
        "cran: max|residual| over its MAD; a transient volume stands high.",
        lambda m: f"{m.tc_outlier:.1f}",
        name="tc_outlier",
        value=lambda m: m.tc_outlier,
    ),
    MetricDoc(
        "spec",
        "Spectral spike score of the residual (dominant periodic artifact).",
        "cran: max FFT magnitude (DC dropped) over its MAD.",
        lambda m: f"{m.spec_outlier:.1f}",
        name="spec_outlier",
        value=lambda m: m.spec_outlier,
    ),
    MetricDoc(
        "motn",
        "Peak in-plane phantom translation vs the temporal mean.",
        "3dvolreg-style registration with rotation dropped (a rigid phantom).",
        _motn_label,
        name="max_translation",
        value=lambda m: m.max_translation,
    ),
    MetricDoc(
        "com",
        "Peak whole-slice center-of-mass shift.",
        "Circular intensity centroid (bxh volmeasures); first-moment instability.",
        _com_label,
        name="max_com_displacement",
        value=lambda m: m.max_com_displacement,
    ),
    MetricDoc(
        "fwhm",
        "Spatial smoothness of the noise field (combined PE/RO).",
        "AFNI 3dFWHMx Classic estimate; the RDC smoothness confound.",
        _fwhm_label,
        name="fwhm",
        value=lambda m: m.fwhm,
    ),
)
