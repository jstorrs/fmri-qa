"""A single-page QA report rendered from a `fmriqc.analysis.QAArtifact`.

This is the *presentation* half of fmri-qa. Its only input is the artifact the
calculation half publishes — settings, provenance, measurements, curves, and the
fBIRN images, all precomputed — so nothing here recomputes a metric or reaches
into the `load`/`prep`/`metrics`/`pipeline` layers. An artifact read back from
disk renders exactly like one just computed.

Inside, the report is split into format-agnostic *content* and a *format
driver*: `summary` builds the header text, `content` the per-metric vocabulary,
`panels` the matplotlib figures, and `formats.html` composes them into one
self-contained page. `write_run_page` / `render_run_page` are re-exported here,
resolved lazily so importing this package never pulls matplotlib in unused.

Panels build `matplotlib.figure.Figure` objects directly and render them with
`fig.savefig(..., format="svg")`, so no `pyplot` state and no particular
backend is needed; importing this package never touches the process's
matplotlib backend.
"""

from typing import TYPE_CHECKING

from .summary import package_version
from .theme import DEFAULT_THEME, Theme

if TYPE_CHECKING:
    # Kept verbatim (not the lazy `__getattr__` below) so mypy and pyright
    # resolve both names statically; never executed at runtime.
    from .formats.html import render_run_page, write_run_page

__all__ = [
    "DEFAULT_THEME",
    "Theme",
    "package_version",
    "render_run_page",
    "write_run_page",
]

# The current driver's public names, resolved only when a caller needs one.
_LAZY = frozenset({"render_run_page", "write_run_page"})


def __getattr__(name: str) -> object:
    """Resolve report entry points without importing their driver eagerly.

    Caches the result as a module global (assigning into `globals()`), so this
    runs at most once per name -- every later access is a plain attribute
    lookup, same as an eager re-export.
    """
    if name in _LAZY:
        from .formats import html

        value = getattr(html, name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the public names, matching what an eager module would show."""
    return sorted(__all__)
