"""The file name a physicist can read at a glance: date, time, series, description.

Those four fields are what a QA archive is browsed by, and dcm2niix's `-f`
template cannot produce them. Measured against dcm2niix v1.0.20260724:

* `%t` is the **study** date and time, so it is identical for every series in a
  session and cannot say when a series ran. There is no series-time token.
* `%s` is **not zero-padded**, so `..._11_...` sorts before `..._2_...` — the
  listing comes out in an order that looks meaningful and is not, which is worse
  than no order at all.
* `%d` keeps whatever punctuation the scanner protocol had, so a description
  like `QA EPI 32ch (rep)` becomes a name that needs quoting in a shell.

Everything needed is in the BIDS sidecar dcm2niix writes beside each series, so
the name is built from that instead:

    20260909_143012_s002_QA_EPI_ISO.nii.gz
    20260909_145533_s011_QA_EPI_32ch_rep.nii.gz

`AcquisitionDateTime` gives the date and the series' own time — it survives
`-ba o`, dcm2niix's strip-the-patient-keep-the-dates anonymization, which is why
`convert.dcm2niix` asks for that mode and not the `-ba y` default that would
throw the date away. Time leads the series number because it is the more
reliable order: series numbers restart between studies, so a directory holding
several sessions sorts right by time and only accidentally by series.

Every field is optional, because every one of them is a DICOM tag some export
somewhere has omitted. A series whose sidecar says nothing usable keeps the name
dcm2niix gave it, which is at least unique — and so does a series whose name
would collide with another's (`plan`).
"""

import re
from collections import Counter
from collections.abc import Mapping

from ..types import Sidecar

# What a name may contain. Everything else — spaces, parentheses, slashes, the
# `*` a Siemens protocol name can carry — collapses to a single underscore, so
# the result needs no quoting in a shell and no escaping in a glob.
_UNSAFE = re.compile(r"[^A-Za-z0-9]+")

# Longest description kept. Protocol descriptions run long and the informative
# part is at the front; a name is for recognizing a series, not for storing it.
DESCRIPTION_LIMIT = 40


def _sanitize(text: str, limit: int = DESCRIPTION_LIMIT) -> str:
    """Reduce a description to `[A-Za-z0-9_]`, trimmed to `limit`.

    Stripped of underscores at both ends *after* truncation as well as before,
    so a cut that lands on punctuation does not leave a trailing `_`.
    """
    return _UNSAFE.sub("_", text).strip("_")[:limit].strip("_")


def _digits(value: object, count: int) -> str | None:
    """Extract the first `count` digits of `value`, or None if there are fewer.

    The sidecar's times and dates are punctuated (`2026-09-09T14:30:12.500000`)
    and the punctuation varies with the writer, so the digits are taken and the
    separators ignored rather than parsed to a format that must then be right.
    """
    if not isinstance(value, str):
        return None
    found = "".join(ch for ch in value if ch.isdigit())
    return found[:count] if len(found) >= count else None


def series_number(sidecar: Sidecar) -> int | None:
    """Return `SeriesNumber` as an int, or None if absent or not a plain int.

    A JSON boolean is a `SeriesNumber` no export ever means: `isinstance(True,
    int)` is true in Python, so `bool` is excluded explicitly rather than
    trusted to fall out of the `int` check.
    """
    number = sidecar.get("SeriesNumber")
    if isinstance(number, bool) or not isinstance(number, int):
        return None
    return number


def text_field(sidecar: Sidecar, key: str) -> str | None:
    """Return `sidecar[key]` if it is a `str`, else None."""
    value = sidecar.get(key)
    return value if isinstance(value, str) else None


def acquired(sidecar: Sidecar) -> tuple[str | None, str | None]:
    """Return `(YYYYMMDD, HHMMSS)`, with None for a half the sidecar omits.

    `AcquisitionDateTime` carries both and is the preferred source.
    `AcquisitionTime` is the fallback and holds the time alone — notably it is
    what survives `-ba y`, so a fully anonymized import still gets its series
    ordered by time even though it has lost the date.
    """
    stamp = text_field(sidecar, "AcquisitionDateTime")
    if stamp is not None and "T" in stamp:
        date, _, time = stamp.partition("T")
        return _digits(date, 8), _digits(time, 6)
    return None, _digits(text_field(sidecar, "AcquisitionTime"), 6)


def _series_number(sidecar: Sidecar) -> str | None:
    """Format `sNNN` from `SeriesNumber`, zero-padded so a listing sorts by it."""
    number = series_number(sidecar)
    return f"s{number:03d}" if number is not None else None


def _description(sidecar: Sidecar) -> str | None:
    """Return the sanitized series description, else the protocol name."""
    for key in ("SeriesDescription", "ProtocolName"):
        value = text_field(sidecar, key)
        if value is not None and (cleaned := _sanitize(value)):
            return cleaned
    return None


def qa_stem(sidecar: Sidecar) -> str | None:
    """Build the QA file stem for a series; None if its sidecar says nothing.

    Each of the four fields is included when present and skipped when absent, so
    a partial sidecar degrades to a shorter name rather than to no name — an
    export with no dates still gets `s002_QA_EPI_ISO`.
    """
    date, time = acquired(sidecar)
    parts = [date, time, _series_number(sidecar), _description(sidecar)]
    return "_".join(part for part in parts if part) or None


def plan(sidecars: Mapping[str, Sidecar | None]) -> dict[str, str]:
    """Map each dcm2niix stem to the stem to file it under.

    Keyed and valued by stem so the caller can move a series' whole set of files
    — NIfTI, sidecar and anything else dcm2niix wrote beside them — under one
    decision.

    Every final stem is unique. A series keeps its dcm2niix name when its
    sidecar cannot name it or its chosen name collides with another series'
    chosen name, including a retained original name. The whole colliding group
    falls back to its original stems; any collisions those fallbacks introduce
    are resolved the same way. Unambiguous QA names are preserved, independent
    of input order.

    For example, a multi-echo or magnitude/phase series produces several files
    that agree on date, time, series number and description and differ only in
    the postfix dcm2niix appended (`_e2`, `_ph`). Renaming them all to one name
    would silently keep whichever moved last, so the whole colliding group keeps
    the names dcm2niix already guaranteed to be unique.
    Nothing is invented and nothing is lost; the caller reports it.
    """
    chosen = {
        stem: (qa_stem(sidecar) or stem) if sidecar is not None else stem
        for stem, sidecar in sidecars.items()
    }
    while True:
        taken = Counter(chosen.values())
        if len(taken) == len(chosen):
            return chosen
        # Every collision retires at least one rename. Original stems are
        # unique, so falling back can only move toward a collision-free map.
        chosen = {
            stem: stem if taken[name] > 1 else name for stem, name in chosen.items()
        }
