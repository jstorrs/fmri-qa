"""Multi-page QA reports rendered from `fmriqc.QAResult` objects.

The report is split into format-agnostic *content* and a pluggable *format
driver*: `summary` builds the header text/tiles, `panels` builds the matplotlib
figures, and `formats` holds one driver per output format that composes them
into a document. `write_report`/`add_report_pages` are the current (ReportLab
PDF) entry points, re-exported here.
"""

import matplotlib

matplotlib.use("Agg")  # headless; no display needed

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
    "parts_for",
    "write_report",
]
