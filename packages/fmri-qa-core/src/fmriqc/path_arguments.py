"""Path arguments as a command line delivers them, for every command.

Wildcard expansion for the shells that do not expand their own, and the check
that an output flag does not name a file the command reads. A leaf over the
standard library only, outside `cli` and `load`, so the report command can use
it without importing the calculation stack or every command behind `cli`.
"""

import glob
import re
from collections.abc import Sequence
from pathlib import Path

# The characters that make an argument a pattern rather than a name.
_WILDCARD = re.compile(r"[*?\[]")


def expand_globs(paths: Sequence[str]) -> list[str]:
    """Expand any wildcard pattern the shell left alone, and return every path.

    A POSIX shell expands a wildcard before the command is started, so `fmri-qa
    data/*.nii.gz` arrives as one argument per scan. PowerShell and cmd do not:
    the same line -- the line `fmri-qa-import` prints for the user to paste --
    arrives as a single literal argument with a `*` still in it, and fails as a
    missing file naming a path no one typed. Expanding here makes one command
    line mean the same thing on every platform.

    An argument naming something that exists is never expanded, so a file whose
    name really does contain a wildcard character is still usable, and on POSIX
    (where the shell already did this) every argument takes that path. A pattern
    matching nothing is passed through as itself, to be reported as the missing
    input it is rather than silently dropped -- which would turn a mistyped
    pattern into a run that quietly analyzed fewer scans than were asked for.
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


def same_file(a: str | Path, b: str | Path) -> bool:
    """Whether two paths name one file — through relative forms and links alike.

    An output that names one of its own inputs, or the `--html` of a report
    that names the artifact it reads, destroys that file the moment the writer
    moves its finished file into place, and the spelling of the two paths says
    nothing about whether that will happen (`./scan.nii.gz` and an absolute
    path, a symlink and its target, two hard links). Existing files are
    compared by identity; a path that does not exist yet can only be compared
    by where it would be created.
    """
    first, second = Path(a), Path(b)
    try:
        return first.samefile(second)
    except OSError:
        return first.resolve() == second.resolve()
