"""Path arguments as a command line delivers them, for every command.

Wildcard expansion for shells that do not expand their own, and the check that
an output flag does not name a file the command reads. A leaf module over the
standard library, so the report command can use it without importing the
calculation stack or every command behind `fmriqa_cli`.
"""

import glob
import re
from collections.abc import Sequence
from pathlib import Path

# The characters that make an argument a pattern rather than a name.
_WILDCARD = re.compile(r"[*?\[]")


def expand_globs(paths: Sequence[str]) -> list[str]:
    """Expand any wildcard pattern the shell left alone, and return every path.

    A POSIX shell expands a wildcard before starting the command, so `fmri-qa
    data/*.nii.gz` arrives as one argument per scan. PowerShell and cmd don't,
    so the same line (which `fmri-qa-import` prints for the user to paste)
    arrives with a literal `*` and fails as a missing file nobody typed.
    Expanding here makes one command line mean the same everywhere.

    An argument naming something that exists is never expanded, so a file whose
    name contains a wildcard character still works. A pattern matching nothing
    is passed through and reported as a missing input. Dropping it would let a
    mistyped pattern run on fewer scans than were asked for.
    """
    expanded: list[str] = []
    for path in paths:
        if Path(path).exists() or not _WILDCARD.search(path):
            expanded.append(path)
            continue
        # glob.glob, not Path.glob: the pattern is one string that may have
        # wildcards in its directory components and may be absolute or relative.
        # Path.glob can't take that without splitting it first.
        matched = sorted(glob.glob(path, recursive=True))  # noqa: PTH207
        expanded.extend(matched or [path])
    return expanded


def same_file(a: str | Path, b: str | Path) -> bool:
    """Whether two paths name one file, through relative forms and links.

    An output that names one of its inputs, or a report's `--html` that names the
    analysis file it reads, destroys that file when the writer moves its result into
    place. Spelling doesn't reveal it (`./scan.nii.gz` and an absolute path, a
    symlink and its target, two hard links). Existing files are compared by
    identity; a path that doesn't exist yet by where it would be created.
    """
    first, second = Path(a), Path(b)
    try:
        return first.samefile(second)
    except OSError:
        return first.resolve() == second.resolve()
