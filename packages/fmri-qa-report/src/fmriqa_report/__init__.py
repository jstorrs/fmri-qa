"""A single-page QA report rendered from a `fmriqa.analysis.QAArtifact`.

This is the presentation half of fmri-qa. Its only input is the artifact the
calculation half publishes, with everything precomputed. Nothing here
recomputes a metric or reaches into the `load`/`prep`/`metrics`/`pipeline`
layers, so an artifact read back from disk renders the same as a fresh one.

`summary` builds the header text, `content` the per-metric vocabulary, `panels`
the matplotlib figures, and `formats.html` composes them into one
self-contained page. `write_run_page` / `render_run_page` are re-exported here
and resolved lazily, so importing this package doesn't pull in matplotlib.

Panels build `matplotlib.figure.Figure` objects directly and render them with
`fig.savefig(..., format="svg")`. That needs no `pyplot` state and never
touches the process's matplotlib backend.
"""

from typing import TYPE_CHECKING

from .summary import package_version
from .theme import DEFAULT_THEME, Theme

if TYPE_CHECKING:
    # Not the lazy `__getattr__` below, so mypy and pyright resolve both names
    # statically. Never executed at runtime.
    from .formats.html import render_run_page, write_run_page

__all__ = [
    "DEFAULT_THEME",
    "Theme",
    "package_version",
    "render_run_page",
    "write_run_page",
]

# The current driver's public names, resolved on first use.
_LAZY = frozenset({"render_run_page", "write_run_page"})


def __getattr__(name: str) -> object:
    """Resolve report entry points without importing their driver eagerly.

    Caches the result as a module global, so this runs at most once per name.
    Later access is a plain attribute lookup.
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
