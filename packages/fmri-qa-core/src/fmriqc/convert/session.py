"""One import: a DICOM directory in, named QA-ready NIfTI out.

The conversion runs into a staging directory this module creates and owns, and
the results are moved into place only once every one of them has a name and no
name lands on a file that already exists. Two things fall out of that order, and
both are the reason for it:

* **What was produced is read from the filesystem, not from dcm2niix's log.**
  Staging starts empty, so whatever is in it afterwards is exactly this run's
  output — no parsing of `Convert 20 DICOM as ...` lines, and no confusion with
  files a previous import left in the destination.
* **A destination collision costs nothing.** The names depend on the DICOM
  content, so they cannot be checked before converting the way
  `cli.destinations` checks `--artifact` paths. Checking them before the *move*
  is the next best thing: the import refuses with every conflict named and the
  destination exactly as it was.

Staging is created inside the destination so the move is a rename within one
filesystem rather than a copy, and is removed whether or not the import
succeeds.
"""

import json
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from ..exceptions import ConversionError, InvalidChoiceError
from ..load.paths import NIFTI_SUFFIXES, nifti_stem, sidecar_path
from ..types import ANONYMIZE_MODES, NAME_STYLES, Anonymize, NameStyle, Sidecar
from . import naming
from .dcm2niix import DEFAULT_TEMPLATE, build_args, find_dcm2niix, run, version


@dataclass(frozen=True, slots=True)
class ImportedSeries:
    """One converted series, as filed.

    `renamed_from` is dcm2niix's own stem when the series was renamed and None
    when it kept that stem — which is how a caller reports the two cases
    `naming.plan` leaves alone (an uninformative sidecar, a name two series
    would share) without re-deriving why.
    """

    path: Path  # the NIfTI, under its final name
    series: int | None  # SeriesNumber, as the sidecar gave it
    description: str | None  # SeriesDescription, unsanitized
    acquired: str | None  # the sidecar's AcquisitionDateTime / AcquisitionTime
    renamed_from: str | None


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Everything one import produced, and what dcm2niix said while producing it."""

    series: tuple[ImportedSeries, ...]
    binary: Path
    tool_version: str | None
    log: str


def _read_sidecar(path: Path) -> Sidecar | None:
    """The BIDS sidecar beside `path`, or None if it is missing or unreadable.

    An unreadable sidecar is not fatal: it costs the series its QA name (the
    dcm2niix one is kept) but not its conversion, and the NIfTI is still
    analyzable — with a warning from `load.metadata`, whose job that is.
    """
    beside = sidecar_path(path)
    try:
        parsed = json.loads(beside.read_text())
    except (OSError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _refiled(name: str, stem: str, target: str) -> str:
    """`name` with its leading `stem` swapped for `target`.

    A slice rather than `str.replace`, which would also rewrite a later
    occurrence: `_companions` matches on `stem + "."`, so the stem is always a
    prefix and this is exact.
    """
    return target + name[len(stem) :]


def _companions(staging: Path, stem: str) -> list[Path]:
    """Every staged file belonging to `stem` — the NIfTI, its sidecar, and any more.

    Matched on `stem + "."` rather than a suffix list so nothing dcm2niix writes
    is left behind in staging and deleted: the trailing dot is what keeps stem
    `2` from also claiming `22.json`.
    """
    return sorted(p for p in staging.iterdir() if p.name.startswith(f"{stem}."))


def import_dicom(
    source: Path | str,
    destination: Path | str,
    *,
    binary: str | Path | None = None,
    names: NameStyle = "qa",
    template: str = DEFAULT_TEMPLATE,
    compress: bool = True,
    anonymize: Anonymize = "pii",
    depth: int = 5,
    extra: Sequence[str] = (),
    force: bool = False,
) -> ImportResult:
    """Convert every DICOM series under `source` into NIfTI under `destination`.

    `destination` is created if it does not exist. With `names="qa"` each series
    is filed under the name `convert.naming` builds from its sidecar; with
    `names="dcm2niix"` it keeps whatever `template` produced.

    Raises:
        InvalidChoiceError: If `names` is not one of `NAME_STYLES` or
            `anonymize` is not one of `ANONYMIZE_MODES`.
        ConversionError: If `source` is not a directory, if no dcm2niix can be
            found or it exits non-zero, or if the import would overwrite files
            already in `destination` and `force` is not set. In the last case
            nothing has been moved and the destination is untouched.
    """
    # Guarded up front so an untyped caller still gets the named error, then
    # matched exhaustively: `assert_never` is unreachable for a `NameStyle`, so
    # adding a style to that Literal makes this a type error rather than a
    # silent fall-through at runtime.
    if names not in NAME_STYLES:
        raise InvalidChoiceError("names", names, NAME_STYLES)
    # `anonymize` is only ever looked up in `dcm2niix._BA`, a `dict[Anonymize,
    # str]` total over the Literal -- there is no `match`/`assert_never` here to
    # make it a type error later, so this guard is the only thing standing
    # between an untyped caller and a bare `KeyError`.
    if anonymize not in ANONYMIZE_MODES:
        raise InvalidChoiceError("anonymize", anonymize, ANONYMIZE_MODES)
    source = Path(source)
    if not source.is_dir():
        raise ConversionError("source", f"{source} is not a directory")
    executable = find_dcm2niix(binary)

    destination = Path(destination)
    fresh = not destination.exists()
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConversionError(
            "destination", f"cannot create {destination}: {exc}"
        ) from exc
    # Inside the destination, so `Path.replace` below is a rename on one
    # filesystem; dot-prefixed so a crashed run leaves nothing a `*.nii.gz`
    # glob would pick up.
    staging = Path(tempfile.mkdtemp(prefix=".fmri-qa-import-", dir=destination))
    try:
        log = run(
            executable,
            build_args(
                source,
                staging,
                template=template,
                compress=compress,
                anonymize=anonymize,
                depth=depth,
                extra=extra,
            ),
        )
        converted = _file_series(staging, destination, names, force)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        # A refused import leaves nothing behind, including the directory it
        # had to create to stage into. Only one this call made, and only while
        # still empty: a destination the caller already had stays, and so does
        # one holding a successful import's files.
        if fresh and destination.is_dir() and not any(destination.iterdir()):
            destination.rmdir()
    return ImportResult(
        series=converted,
        binary=executable,
        tool_version=version(log),
        log=log,
    )


def _file_series(
    staging: Path, destination: Path, names: NameStyle, force: bool
) -> tuple[ImportedSeries, ...]:
    """Name everything in `staging` and move it into `destination`."""
    produced = sorted(
        path for path in staging.iterdir() if path.name.endswith(NIFTI_SUFFIXES)
    )
    sidecars = {nifti_stem(path): _read_sidecar(path) for path in produced}
    match names:
        case "qa":
            chosen = naming.plan(sidecars)
        case "dcm2niix":
            chosen = {stem: stem for stem in sidecars}
        case _:
            assert_never(names)
    _refuse_existing(staging, destination, chosen, force)

    filed = []
    for path in produced:
        stem = nifti_stem(path)
        target = chosen[stem]
        for companion in _companions(staging, stem):
            companion.replace(destination / _refiled(companion.name, stem, target))
        filed.append(
            _describe(
                destination / _refiled(path.name, stem, target),
                sidecars[stem] or {},
                renamed_from=stem if target != stem else None,
            )
        )
    return tuple(sorted(filed, key=lambda entry: entry.path.name))


def _refuse_existing(
    staging: Path, destination: Path, chosen: dict[str, str], force: bool
) -> None:
    """Refuse the whole import if any file it would write already exists.

    Checked across every file of every series before a single one moves, so the
    destination is either updated completely or not at all — a half-moved import
    is the state that is hardest to reason about afterwards, and the one a
    physicist would have to unpick by hand.
    """
    if force:
        return
    clashes = sorted(
        _refiled(companion.name, stem, target)
        for stem, target in chosen.items()
        for companion in _companions(staging, stem)
        if (destination / _refiled(companion.name, stem, target)).exists()
    )
    if clashes:
        raise ConversionError(
            "destination",
            f"{destination} already holds {', '.join(clashes)}; "
            "import into an empty directory, or pass --force to overwrite",
        )


def _describe(
    path: Path, sidecar: Sidecar, *, renamed_from: str | None
) -> ImportedSeries:
    """One filed series, with the sidecar fields worth showing in a listing."""
    number = sidecar.get("SeriesNumber")
    description = sidecar.get("SeriesDescription")
    stamp = sidecar.get("AcquisitionDateTime") or sidecar.get("AcquisitionTime")
    return ImportedSeries(
        path=path,
        series=number if isinstance(number, int) else None,
        description=description if isinstance(description, str) else None,
        acquired=stamp if isinstance(stamp, str) else None,
        renamed_from=renamed_from,
    )
