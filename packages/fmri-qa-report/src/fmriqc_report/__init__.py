"""Multi-page QA reports rendered from a `fmriqc.analysis.QAArtifact`.

This is the *presentation* half of fmri-qa. Its only input is the artifact the
calculation half publishes — settings, provenance, measurements, curves, and the
fBIRN images, all precomputed — so nothing here recomputes a metric or reaches
into the `load`/`prep`/`metrics`/`pipeline` layers. An artifact read back from
disk renders exactly like one just computed.

Inside, the report is split again into format-agnostic *content* and a pluggable
*format driver*: `summary` builds the header text, `content` the per-metric
vocabulary, `panels` the matplotlib figures, `document` the block/tier model a
driver walks, and `formats` holds one driver per output format that composes
them into a document. `write_report` / `add_report_pages` are the current
(ReportLab PDF) entry points, re-exported here.

Panels build `matplotlib.figure.Figure` objects directly and render them with
`fig.savefig(..., format="svg")`, so no `pyplot` state and no particular
backend is needed; importing this package never touches the process's
matplotlib backend.
"""

from .document import (
    TIERS,
    Appendix,
    Block,
    Cover,
    ScanSection,
    Tier,
    compose,
    parts_for,
)
from .formats.reportlab import add_report_pages, write_report
from .summary import package_version
from .theme import DEFAULT_THEME, Theme

__all__ = [
    "DEFAULT_THEME",
    "TIERS",
    "Appendix",
    "Block",
    "Cover",
    "ScanSection",
    "Theme",
    "Tier",
    "add_report_pages",
    "compose",
    "package_version",
    "parts_for",
    "write_report",
]
