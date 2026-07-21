"""Multi-page QA reports rendered from `fmriqc.QAResult` objects.

The report is split into format-agnostic *content* and a pluggable *format
driver*: `summary` builds the header text/tiles, `panels` builds the matplotlib
figures, and `formats` holds one driver per output format that composes them
into a document. `write_report`/`add_report_pages` are the current (ReportLab
PDF) entry points, re-exported here.
"""

import matplotlib

matplotlib.use("Agg")  # headless; no display needed

from .formats.reportlab import add_report_pages, write_report

__all__ = ["add_report_pages", "write_report"]
