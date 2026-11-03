"""Which name each file dcm2niix wrote is filed under, decided without files.

This is the naming half of an import, apart from the filesystem. Given the
names in a staging directory and the sidecars read from it, `plan_names` says
what every file is called once filed; `fmriqa.convert.naming` holds the QA rule
itself. `session` does the reading and the moving. A page that has only a list
of filenames and sidecar bytes (a browser running dcm2niix as WASM) decodes each
sidecar as UTF-8, parses it with `sidecar_or_none`, and calls `plan_names` to get
the names `import_dicom` would give. This module imports nothing that touches a
file or starts a process, and `tests/test_filing_isolation.py` holds it to that.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import assert_never

from fmriqa.convert import naming
from fmriqa.exceptions import InvalidChoiceError
from fmriqa.types import NAME_STYLES, NameStyle, Sidecar

from ..paths import NIFTI_SUFFIXES, nifti_stem

__all__ = ["Filed", "plan_names", "sidecar_or_none"]


@dataclass(frozen=True, slots=True)
class Filed:
    """Where one input file goes.

    `stem` is dcm2niix's stem of the series the file belongs to (the key into
    `sidecars`), so a caller can group a series' files without re-deriving
    which stem owns which. `name` is the filename it is filed under.
    """

    stem: str
    name: str


def sidecar_or_none(text: str) -> Sidecar | None:
    """Parse a BIDS sidecar's text; None if it is not a JSON object.

    Truncated or invalid JSON, and valid JSON that is not an object (a list, a
    number), all give None: the series then keeps its dcm2niix name rather than
    failing the import. Decoding the bytes to `text` is the caller's.
    """
    try:
        parsed = json.loads(text)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def plan_names(
    names: Sequence[str],
    sidecars: Mapping[str, Sidecar | None],
    style: NameStyle,
) -> dict[str, Filed]:
    """Map each input filename to the `Filed` it is filed under.

    `names` are bare filenames, as dcm2niix wrote them. `sidecars` is keyed by
    dcm2niix's stem (`nifti_stem` of a NIfTI's name) and holds that series'
    parsed sidecar, or None when it has none or it was unreadable. A stem
    missing from `sidecars` is treated as None; keys naming no NIfTI in `names`
    are ignored.

    With `style="qa"` each series' stem is the one `naming.plan` chooses; with
    `"dcm2niix"` every series keeps its own. Either way the stem is swapped for
    the chosen one at the front of the name and the rest, extension and any
    postfix, is kept.

    A NIfTI belongs to its parsed stem: `x.nii.gz` belongs to `x` even when
    another series has stem `x.nii`. Any other file belongs to the longest stem
    it starts with followed by a dot, so `scan.repeat.json` travels with
    `scan.repeat`, never `scan`. A file that matches no stem is omitted from the
    result: the caller leaves it where it is.

    Filed names are not guaranteed unique: two files of different series can land on
    one name. The caller must refuse
    duplicates, as `import_dicom` does before moving anything.

    Raises
    ------
    InvalidChoiceError
        If `style` is not one of `NAME_STYLES`.
    ValueError
        If a name is not a bare filename: it contains a `/` or backslash, or is
        `.` or `..`. Naming it would swap a stem that is not at the front of the path.
    """
    if style not in NAME_STYLES:
        raise InvalidChoiceError("style", style, NAME_STYLES)
    if bad := [n for n in names if "/" in n or "\\" in n or n in {".", ".."}]:
        raise ValueError(f"names must be bare filenames, not paths: {bad}")
    stems = {nifti_stem(name) for name in names if name.endswith(NIFTI_SUFFIXES)}
    known = {stem: sidecars.get(stem) for stem in sorted(stems)}
    match style:
        case "qa":
            chosen = naming.plan(known)
        case "dcm2niix":
            chosen = {stem: stem for stem in known}
        case _:
            assert_never(style)

    longest_first = sorted(chosen, key=len, reverse=True)
    filed: dict[str, Filed] = {}
    for name in names:
        if name.endswith(NIFTI_SUFFIXES):
            stem: str | None = nifti_stem(name)
        else:
            stem = next(
                (stem for stem in longest_first if name.startswith(f"{stem}.")), None
            )
        if stem is not None:
            filed[name] = Filed(stem, _refiled(name, stem, chosen[stem]))
    return filed


def _refiled(name: str, stem: str, target: str) -> str:
    """Swap the leading `stem` of `name` for `target`.

    A slice, not `str.replace`, which would also rewrite a later occurrence.
    `plan_names` matches on `stem + "."`, so the stem is always a prefix.
    """
    return target + name[len(stem) :]
