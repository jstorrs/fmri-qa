"""One `warn` for the whole package, attributed to the caller's own code.

A warning is only useful if it names a line the user can change. A fixed frame
offset can't do that, because the same helper is reached through different
entry points (`run_qa` directly, or via `analyze`). Instead this skips every
frame whose file lives in this package, so the warning points at the first
frame outside it, however deep the call.

`fmriqa_io` reaches these warnings too (loading an old artifact migrates it), so
its frames are skipped as well when it is loaded. It is named only as a string:
core never imports io.
"""

import os
import sys
import warnings
from pathlib import Path

# The packages whose frames a warning skips. Looked up at call time, since
# `fmriqa_io` may be imported after this module, or not at all.
_SKIPPED_PACKAGES = ("fmriqa", "fmriqa_io")


def _skipped_prefixes() -> tuple[str, ...]:
    """Return the directory of each loaded package in `_SKIPPED_PACKAGES`."""
    # The trailing separator keeps a prefix from also matching a sibling that
    # shares this parent directory in site-packages: `fmriqa` would otherwise
    # match `fmriqa_io` and `fmriqa_cli`, and the report and the launcher, whose
    # frames are the caller's.
    return tuple(
        str(Path(module.__file__).parent) + os.sep
        for name in _SKIPPED_PACKAGES
        if (module := sys.modules.get(name)) is not None and module.__file__
    )


def warn(message: str) -> None:
    """Issue `message` as a `UserWarning`, reported at the caller's code."""
    warnings.warn(message, UserWarning, skip_file_prefixes=_skipped_prefixes())
