"""Per-metric vocabulary: the label, definition, method and display recipe.

One `MetricDoc` per reported metric is the single source for what a metric is
called, how its value is shown, what it means and how it is computed. Values
are read off the artifact's flat `Measurements`, so a report needs nothing
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


Unit = str | Callable[[Measurements], str]


@dataclass(frozen=True, slots=True)
class MetricDoc:
    """A reported metric's stable identity, meaning, and display recipe.

    `name` is the `Measurements` field holding the value; `decimals` and `unit`
    say how to show it. A `unit` is a fixed string, or a function of the
    measurements for metrics whose unit depends on the data (mm vs voxels).
    """

    label: str
    definition: str
    method: str
    name: MetricName
    decimals: int
    unit: Unit = ""

    def value(self, m: Measurements) -> float:
        """Return the raw measured value."""
        value: float = getattr(m, self.name)
        return value

    def number(self, m: Measurements) -> str:
        """Round the value to this metric's decimals, without its unit."""
        return f"{self.value(m):.{self.decimals}f}"

    def unit_for(self, m: Measurements) -> str:
        """Return the unit text for these measurements; empty if dimensionless."""
        return self.unit(m) if callable(self.unit) else self.unit


def _displacement_unit(m: Measurements) -> str:
    """Return ``"mm"`` when the voxel size is known, else ``"vox"``."""
    return m.displacement_unit


def _fwhm_unit(m: Measurements) -> str:
    """Return ``"mm"`` when the voxel size is known, else ``"vox"``."""
    return m.fwhm_unit


# The reported metrics, in display order. The tile label, decimals and unit here
# are the ones the metric tiles use, so the tiles and the definitions list agree.
METRIC_DOCS: tuple[MetricDoc, ...] = (
    MetricDoc(
        "SNR",
        "Image signal-to-noise: ROI mean signal over the static spatial noise.",
        "FBIRN: static noise from the odd/even difference image over the ROI.",
        name="snr",
        decimals=1,
    ),
    MetricDoc(
        "SFNR",
        "Signal-to-fluctuation-noise: ROI average of the voxelwise temporal SNR.",
        "FBIRN/Glover: per voxel, temporal mean / detrended temporal SD; then the "
        "ROI mean of those ratios (not the ratio of the ROI-mean series).",
        name="sfnr",
        decimals=1,
    ),
    MetricDoc(
        "RDC",
        "Radius of decorrelation: single-voxel CV over the full-ROI CV "
        "(ideal = ROI width).",
        "Weisskoff: measured CV vs ROI width against the ideal 1/width line; "
        "RDC = pooled single-voxel CV / ROI-mean CV at the full ROI.",
        name="rdc",
        decimals=2,
    ),
    MetricDoc(
        "ghost",
        "Nyquist (N/2) ghost along the phase-encode axis, region mean.",
        "Phantom rolled half the FOV along PE; ghost-region mean over the mean of "
        "the matched signal region it was rolled from.",
        name="ghost_pct",
        decimals=2,
        unit="%",
    ),
    MetricDoc(
        "ghostT",
        "Peak N/2 ghost: the brightest 10% of ghost voxels (>= ghost).",
        "Greve / bxh fmriqa_ghostiness; surfaces a localized bright ghost.",
        name="ghost_top_pct",
        decimals=2,
        unit="%",
    ),
    MetricDoc(
        "RO",
        "Readout-axis ghost baseline (background-relative).",
        "The N/2 construction along the readout axis; the ACRg baseline.",
        name="ro_ghost_pct",
        decimals=2,
        unit="%",
    ),
    MetricDoc(
        "ACRg",
        "ACR ghosting ratio: PE ghost against the readout baseline.",
        "|ghost - RO|, the ACR phantom-QA ghosting figure in region-matched form.",
        name="acr_ghost_pct",
        decimals=2,
        unit="%",
    ),
    MetricDoc(
        "drift",
        "Slow signal drift across the run.",
        "FBIRN: peak-to-trough of the fitted trend over the mean signal.",
        name="drift_pct",
        decimals=3,
        unit="%",
    ),
    MetricDoc(
        "fluct",
        "Percent temporal fluctuation of the ROI-mean time course.",
        "FBIRN/Glover: SD of the detrended ROI-mean series over the ROI mean "
        "signal (the ROI-mean form SFNR does not use).",
        name="percent_fluctuation",
        decimals=3,
        unit="%",
    ),
    MetricDoc(
        "outl",
        "Worst single-frame outlier-voxel fraction.",
        "AFNI 3dToutcount; qthr tunes a length-dependent threshold, "
        "not an expected per-frame outlier fraction.",
        name="outlier_max_pct",
        decimals=2,
        unit="%",
    ),
    MetricDoc(
        "tcOut",
        "Time-domain spike score of the ROI-mean residual.",
        "cran: max|residual| over its MAD; a transient volume stands high.",
        name="tc_outlier",
        decimals=1,
    ),
    MetricDoc(
        "spec",
        "Spectral spike score of the residual (dominant periodic artifact).",
        "cran: max FFT magnitude (DC dropped) over its MAD.",
        name="spec_outlier",
        decimals=1,
    ),
    MetricDoc(
        "motn",
        "Peak in-plane phantom translation vs the temporal mean.",
        "3dvolreg-style registration with rotation dropped (a rigid phantom).",
        name="max_translation",
        decimals=2,
        unit=_displacement_unit,
    ),
    MetricDoc(
        "com",
        "Peak whole-slice center-of-mass shift.",
        "Circular intensity centroid (bxh volmeasures); first-moment instability.",
        name="max_com_displacement",
        decimals=2,
        unit=_displacement_unit,
    ),
    MetricDoc(
        "fwhm",
        "Spatial smoothness of the noise field (combined PE/RO).",
        "AFNI 3dFWHMx Classic estimate; the RDC smoothness confound.",
        name="fwhm",
        decimals=2,
        unit=_fwhm_unit,
    ),
)
