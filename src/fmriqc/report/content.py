"""Per-metric vocabulary: the label, definition, method, and value formatter.

One `MetricDoc` per reported metric is the single source for what a metric is
called, how its value is formatted, what it means, and how it is computed. The
header tiles (`metric_tiles`) and the physics characterization/methods pages
(`characterization_rows`, `method_rows`) all read this catalog, so a metric's
name and formatting can't drift between the dashboard and the physics report.

The prose is condensed from `notes/` and the metric modules; see those for the
full derivations.
"""

from collections.abc import Callable
from dataclasses import dataclass

import fmriqc as q


@dataclass(frozen=True, slots=True)
class MetricDoc:
    """What one reported metric is called, means, how it's computed and formatted."""

    label: str
    definition: str
    method: str
    fmt: Callable[[q.QAMetrics], str]


def _fwhm_label(m: q.QAMetrics) -> str:
    """Combined FWHM tile text: mm when the voxel size is known, else voxels."""
    s = m.smoothness
    unit = "mm" if s.voxel_mm is not None else "vox"
    return f"{s.fwhm:.2f}{unit}"


# The reported metrics, in display order. The tile label and value formatter here
# are the ones the header tiles use, so the tiles and the physics tables agree.
METRIC_DOCS: tuple[MetricDoc, ...] = (
    MetricDoc(
        "SNR",
        "Image signal-to-noise: ROI mean signal over the static spatial noise.",
        "fBIRN: static noise from the odd/even difference image over the ROI.",
        lambda m: f"{m.snr:.1f}",
    ),
    MetricDoc(
        "SFNR",
        "Signal-to-fluctuation-noise: temporal stability of the ROI mean.",
        "fBIRN/Glover: ROI mean over the SD of the detrended time series.",
        lambda m: f"{m.sfnr:.1f}",
    ),
    MetricDoc(
        "RDC",
        "Radius of decorrelation: ROI width where averaging stops reducing CV.",
        "Weisskoff: measured CV vs ROI width against the ideal 1/width line.",
        lambda m: f"{m.rdc:.2f}",
    ),
    MetricDoc(
        "ghost",
        "Nyquist (N/2) ghost along the phase-encode axis, region mean.",
        "Signal rolled half the FOV along PE; ghost-region mean over phantom mean.",
        lambda m: f"{m.ghost_pct:.2f}%",
    ),
    MetricDoc(
        "ghostT",
        "Peak N/2 ghost: the brightest 10% of ghost voxels (>= ghost).",
        "Greve / bxh fmriqa_ghostiness; surfaces a localized bright ghost.",
        lambda m: f"{m.ghost_top_pct:.2f}%",
    ),
    MetricDoc(
        "RO",
        "Readout-axis ghost baseline (background-relative).",
        "The N/2 construction along the readout axis; the ACRg baseline.",
        lambda m: f"{m.ro_ghost_pct:.2f}%",
    ),
    MetricDoc(
        "ACRg",
        "ACR ghosting ratio: PE ghost above the readout baseline.",
        "ghost - RO, the ACR phantom-QA ghosting figure.",
        lambda m: f"{m.acr_ghost_pct:.2f}%",
    ),
    MetricDoc(
        "drift",
        "Slow signal drift across the run.",
        "fBIRN: peak-to-trough of the fitted trend over the mean signal.",
        lambda m: f"{m.drift_pct:.3f}%",
    ),
    MetricDoc(
        "fluct",
        "Percent temporal fluctuation of the ROI mean.",
        "fBIRN/Glover: residual SD over the mean signal.",
        lambda m: f"{m.percent_fluctuation:.3f}%",
    ),
    MetricDoc(
        "outl",
        "Worst single-frame outlier-voxel fraction.",
        "AFNI 3dToutcount; a clean run sits near the per-voxel chance level.",
        lambda m: f"{100.0 * m.outliers.max_fraction:.2f}%",
    ),
    MetricDoc(
        "tcOut",
        "Time-domain spike score of the ROI-mean residual.",
        "cran: max|residual| over its MAD; a transient volume stands high.",
        lambda m: f"{m.spikes.tc_outlier:.1f}",
    ),
    MetricDoc(
        "spec",
        "Spectral spike score of the residual (dominant periodic artifact).",
        "cran: max FFT magnitude (DC dropped) over its MAD.",
        lambda m: f"{m.spikes.spec_outlier:.1f}",
    ),
    MetricDoc(
        "motn",
        "Peak in-plane phantom translation vs the temporal mean (voxels).",
        "3dvolreg-style registration with rotation dropped (a rigid phantom).",
        lambda m: f"{m.motion.max_translation:.2f}",
    ),
    MetricDoc(
        "com",
        "Peak whole-slice center-of-mass shift (voxels).",
        "Circular intensity centroid (bxh volmeasures); first-moment instability.",
        lambda m: f"{m.center_of_mass.max_displacement:.2f}",
    ),
    MetricDoc(
        "fwhm",
        "Spatial smoothness of the noise field (combined PE/RO).",
        "AFNI 3dFWHMx Classic estimate; the RDC smoothness confound.",
        _fwhm_label,
    ),
)


def metric_tiles(m: q.QAMetrics) -> list[tuple[str, str]]:
    """(label, value) pairs for the header metric tiles, in display order."""
    return [(d.label, d.fmt(m)) for d in METRIC_DOCS]


def characterization_rows(m: q.QAMetrics) -> list[tuple[MetricDoc, str]]:
    """(doc, formatted value) per metric for the physics characterization table."""
    return [(d, d.fmt(m)) for d in METRIC_DOCS]
