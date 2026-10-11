"""Where to look at a finished run: one report, or the folder of them.

A leaf module that needs only `RunResult`'s shape, so the panel can offer an
"open results" button without importing `argparse`, `fmriqc` or
`fmriqc_report`.
"""

import webbrowser
from collections.abc import Callable

from .outcome import RunResult

__all__ = ["Opener", "open_results"]

# Injectable so a test never launches a real browser.
#: Callable that opens a URL and reports whether it succeeded; ``webbrowser.open`` in
#: production.
Opener = Callable[[str], bool]


def open_results(result: RunResult, *, opener: Opener = webbrowser.open) -> str | None:
    """Open `result`'s output with `opener`; return the URI opened, or None.

    One published series opens its report. More than one opens
    `result.output_dir`, so a browser can list the series folders. If nothing
    was published, nothing opens and it returns None.
    """
    published = result.published
    if not published:
        return None
    target = published[0].report if len(published) == 1 else result.output_dir
    uri = target.as_uri()
    opener(uri)
    return uri
