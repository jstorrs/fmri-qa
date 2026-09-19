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
    "write_report",
]

# The current PDF driver's public names, resolved only when a caller needs one.
_LAZY = frozenset({"add_report_pages", "write_report"})


def __getattr__(name: str) -> object:
    """Resolve PDF entry points without importing their driver eagerly.

    Caches the result as a module global (assigning into `globals()`), so this
    runs at most once per name -- every later access is a plain attribute
    lookup, same as an eager re-export.
    """
    if name not in _LAZY:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .formats import reportlab

    value = getattr(reportlab, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the public names, matching what an eager module would show."""
    return sorted(__all__)
