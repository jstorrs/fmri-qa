"""Where to look at a finished run: one report, or the folder of them.

A leaf module: it needs only `RunResult`'s shape (`published`/`output_dir`),
so the panel can present an "open results" button by importing this and
nothing else -- no `argparse`, no `fmriqc`, no `fmriqc_report`.
"""

import webbrowser
from collections.abc import Callable

from .outcome import RunResult

__all__ = ["Opener", "open_results"]

# Injectable so a test never launches a real browser; the default is the one
# `cli.main` uses in production.
#: Callable that opens a URL and reports whether it succeeded; ``webbrowser.open`` in
#: production.
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
