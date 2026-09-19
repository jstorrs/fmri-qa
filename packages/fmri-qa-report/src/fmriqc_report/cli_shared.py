"""Small command-line helpers shared without importing either report driver."""

import glob
import re
from collections.abc import Sequence
from pathlib import Path

# The characters that make an argument a pattern rather than a name.
_WILDCARD = re.compile(r"[*?\[]")


def _expand_globs(paths: Sequence[str]) -> list[str]:
    """Every path, with any wildcard pattern that named nothing expanded here.

    PowerShell and cmd do not expand a wildcard before starting the command, so
    `fmri-qa-report artifacts/*.qa.nc` -- the line the README gives -- reaches
    this process with the `*` still in it and fails as a missing artifact.

    A deliberate twin of `fmriqc.cli.arguments.expand_globs` rather than an
    import of it: the report package may reach into `fmriqc.analysis` and
    `fmriqc.types` and nothing else (see `tests/test_layering.py`), and a shell
    quirk on the way into a command line is not knowledge worth widening that
    seam for. Keep the two in step.
    """
    expanded: list[str] = []
    for path in paths:
        if Path(path).exists() or not _WILDCARD.search(path):
            expanded.append(path)
            continue
        # glob.glob, not Path.glob: the pattern is one string that may carry
        # wildcards in its directory components too, and be absolute or
        # relative. Path.glob cannot take that without being taken apart first.
        matched = sorted(glob.glob(path, recursive=True))  # noqa: PTH207
        expanded.extend(matched or [path])
    return expanded
