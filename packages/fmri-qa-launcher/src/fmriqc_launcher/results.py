"""Where to look at a finished run: one report, or the folder of them.

A leaf module, deliberately kept apart from `session` at *import* time: it
only needs `RunResult`'s shape (`published`/`output_dir`), never its heavy
dependencies, so a future `panel` module can present an "open results" button
by importing this and nothing else -- no `argparse`, no `fmriqc`, no
`fmriqc_report`. The `RunResult` import below is `TYPE_CHECKING`-only for
exactly that reason; at runtime this module never touches `.session`.
"""

from __future__ import annotations

import webbrowser
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import RunResult

__all__ = ["Opener", "open_results"]

# Injectable so a test never launches a real browser; the default is the one
# `cli.main` uses in production.
Opener = Callable[[str], bool]


def open_results(result: RunResult, *, opener: Opener = webbrowser.open) -> str | None:
    """Open `result`'s output with `opener`; return the URI opened, or None.

    Exactly one published series opens that series' own report; more than one
    opens `result.output_dir` instead, so a browser can list the series
    folders side by side. Nothing published (every series refused or failed,
    or the run found none at all) opens nothing and returns None.
    """
    published = result.published
    if not published:
        return None
    target = published[0].report if len(published) == 1 else result.output_dir
    uri = target.as_uri()
    opener(uri)
    return uri
