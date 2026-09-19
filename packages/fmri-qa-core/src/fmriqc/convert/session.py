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
from collections import Counter
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
    occurrence: `_plan_files` matches on `stem + "."`, so the stem is always a
    prefix and this is exact.
    """
    return target + name[len(stem) :]


def _plan_files(
    staged: Sequence[Path], destination: Path, chosen: dict[str, str]
) -> list[tuple[Path, Path]]:
    """Assign each NIfTI and companion one destination before any file moves.

    NIfTIs belong to their parsed stem: `x.nii.gz` belongs to `x` even when
    another series has stem `x.nii`. Other files belong to the longest matching
    stem, so `scan.repeat.json` travels with `scan.repeat`, never `scan`.
    """
    stems = sorted(chosen, key=len, reverse=True)
    planned = []
    for path in staged:
        if path.name.endswith(NIFTI_SUFFIXES):
            stem: str | None = nifti_stem(path)
        else:
            stem = next(
                (stem for stem in stems if path.name.startswith(f"{stem}.")), None
            )
        if stem is not None:
            target = destination / _refiled(path.name, stem, chosen[stem])
            planned.append((path, target))
    return planned


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
            found or it exits non-zero, if imported files would share a
            destination, or if the import would overwrite files already in
            `destination` and `force` is not set. Both destination checks
            happen before any file moves.
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
    staged = sorted(staging.iterdir())
    produced = [path for path in staged if path.name.endswith(NIFTI_SUFFIXES)]
    sidecars = {nifti_stem(path): _read_sidecar(path) for path in produced}
    match names:
        case "qa":
            chosen = naming.plan(sidecars)
        case "dcm2niix":
            chosen = {stem: stem for stem in sidecars}
        case _:
            assert_never(names)
    planned = _plan_files(staged, destination, chosen)
    _refuse_collisions(planned, destination, force)
    for source, target_path in planned:
        source.replace(target_path)

    filed = []
    for path in produced:
        stem = nifti_stem(path)
        target = chosen[stem]
        filed.append(
            _describe(
                destination / _refiled(path.name, stem, target),
                sidecars[stem] or {},
                renamed_from=stem if target != stem else None,
            )
        )
    return tuple(sorted(filed, key=lambda entry: entry.path.name))


def _refuse_collisions(
    planned: Sequence[tuple[Path, Path]], destination: Path, force: bool
) -> None:
    """Refuse duplicate destinations, and existing files unless forced.

    Checked across every file of every series before a single one moves, so the
    destination is either updated completely or not at all — a half-moved import
    is the state that is hardest to reason about afterwards, and the one a
    physicist would have to unpick by hand.
    """
    counts = Counter(target for _, target in planned)
    duplicates = sorted(path.name for path, count in counts.items() if count > 1)
    if duplicates:
        raise ConversionError(
            "destination",
            f"imported files would share destinations in {destination}: "
            f"{', '.join(duplicates)}; --force cannot resolve this collision",
        )
    if force:
        return
    clashes = sorted(target.name for _, target in planned if target.exists())
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
    stamp = naming.text_field(sidecar, "AcquisitionDateTime") or naming.text_field(
        sidecar, "AcquisitionTime"
    )
    return ImportedSeries(
        path=path,
        series=naming.series_number(sidecar),
        description=naming.text_field(sidecar, "SeriesDescription"),
        acquired=stamp,
        renamed_from=renamed_from,
    )
