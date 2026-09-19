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
them into a document. `write_report` / `add_report_pages` are the ReportLab PDF
entry points; `write_run_page` / `render_run_page` are the offline single-file
HTML entry points, one page self-contained enough to open from `file://` with
no companion asset. All four are re-exported here, resolved lazily so importing
this package never pulls in a driver's dependencies unused.

Panels build `matplotlib.figure.Figure` objects directly and render them with
`fig.savefig(..., format="svg")`, so no `pyplot` state and no particular
backend is needed; importing this package never touches the process's
matplotlib backend.
"""

from typing import TYPE_CHECKING

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
from .summary import package_version
from .theme import DEFAULT_THEME, Theme

if TYPE_CHECKING:
    # Kept verbatim (not the lazy `__getattr__` below) so mypy and pyright
    # resolve both names statically; never executed at runtime.
    from .formats.html import render_run_page, write_run_page
    from .formats.reportlab import add_report_pages, write_report

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
    "render_run_page",
    "write_report",
    "write_run_page",
]

# The current drivers' public names, resolved only when a caller needs one.
_LAZY_PDF = frozenset({"add_report_pages", "write_report"})
_LAZY_HTML = frozenset({"render_run_page", "write_run_page"})
_LAZY = _LAZY_PDF | _LAZY_HTML


def __getattr__(name: str) -> object:
    """Resolve report entry points without importing their driver eagerly.

    Caches the result as a module global (assigning into `globals()`), so this
    runs at most once per name -- every later access is a plain attribute
    lookup, same as an eager re-export.
    """
    if name in _LAZY_PDF:
        from .formats import reportlab

        value = getattr(reportlab, name)
    elif name in _LAZY_HTML:
        from .formats import html

        value = getattr(html, name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the public names, matching what an eager module would show."""
    return sorted(__all__)
