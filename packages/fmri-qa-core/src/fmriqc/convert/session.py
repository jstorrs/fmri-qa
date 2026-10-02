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
* **A move that fails part-way is undone.** Filing is a sequence of renames, and
  the fifth of twelve can be refused -- a sync client holding the file, a disk
  error. `_file_atomically` records the renames it has made and reverses them,
  so the destination is as it was; see there for where that cannot be promised,
  and what is said instead.

Staging is created inside the destination so the move is a rename within one
filesystem rather than a copy, and is removed whether or not the import
succeeds.
"""

import json
import shutil
import tempfile
from collections import Counter
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import assert_never

from ..exceptions import ConversionError, InvalidChoiceError
from ..load.paths import NIFTI_SUFFIXES, nifti_stem, sidecar_path
from ..rename import replace_patiently
from ..types import ANONYMIZE_MODES, NAME_STYLES, Anonymize, NameStyle, Sidecar
from ..warn import warn
from . import naming
from .dcm2niix import (
    DEFAULT_ANONYMIZE,
    DEFAULT_DEPTH,
    DEFAULT_TEMPLATE,
    build_args,
    find_dcm2niix,
    run,
    version,
)

# How `import_dicom` and `fmri-qa-import` name files unless told otherwise.
DEFAULT_NAMES: NameStyle = "qa"


@dataclass(frozen=True, slots=True)
class ImportedSeries:
    """One converted series, as filed.

    `renamed_from` is dcm2niix's own stem when the series was renamed and None
    when it kept that stem — which is how a caller reports the two cases
    `naming.plan` leaves alone (an uninformative sidecar, a name two series
    would share) without re-deriving why. `files` is every file filed for the
    series, so a caller needs no rule of its own for which files belong to it.
    """

    path: Path  # the NIfTI, under its final name
    # Every file filed for this series: `path` first, then the rest by name.
    files: tuple[Path, ...]
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
) -> dict[str, list[tuple[Path, Path]]]:
    """Assign each NIfTI and companion one destination before any file moves.

    Returns each stem's `(staged, target)` moves, keyed by the stem.

    NIfTIs belong to their parsed stem: `x.nii.gz` belongs to `x` even when
    another series has stem `x.nii`. Other files belong to the longest matching
    stem, so `scan.repeat.json` travels with `scan.repeat`, never `scan`.
    """
    stems = sorted(chosen, key=len, reverse=True)
    planned: dict[str, list[tuple[Path, Path]]] = {stem: [] for stem in chosen}
    for path in staged:
        if path.name.endswith(NIFTI_SUFFIXES):
            stem: str | None = nifti_stem(path)
        else:
            stem = next(
                (stem for stem in stems if path.name.startswith(f"{stem}.")), None
            )
        if stem is not None:
            target = destination / _refiled(path.name, stem, chosen[stem])
            planned[stem].append((path, target))
    return planned


def import_dicom(
    source: Path | str,
    destination: Path | str,
    *,
    binary: str | Path | None = None,
    names: NameStyle = DEFAULT_NAMES,
    template: str = DEFAULT_TEMPLATE,
    compress: bool = True,
    anonymize: Anonymize = DEFAULT_ANONYMIZE,
    depth: int = DEFAULT_DEPTH,
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
            destination, if a target is a directory (including a symlink to
            one), if the import would overwrite files already in `destination`
            and `force` is not set, or if a file cannot be moved into
            `destination`. All destination checks happen before any file moves,
            and a move that fails is undone (see `_file_atomically`).
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
    by_stem = _plan_files(staged, destination, chosen)
    planned = [move for moves in by_stem.values() for move in moves]
    _refuse_collisions(planned, destination, force)
    _file_atomically(planned, destination)

    filed = []
    for path in produced:
        stem = nifti_stem(path)
        target = chosen[stem]
        filed.append(
            _describe(
                destination / _refiled(path.name, stem, target),
                [moved for _, moved in by_stem[stem]],
                sidecars[stem] or {},
                renamed_from=stem if target != stem else None,
            )
        )
    return tuple(sorted(filed, key=lambda entry: entry.path.name))


def _refuse_collisions(
    planned: Sequence[tuple[Path, Path]], destination: Path, force: bool
) -> None:
    """Refuse duplicate or directory targets, and existing files unless forced.

    Checked across every file of every series before a single one moves, so a
    refusal costs nothing: the destination is exactly as it was. That is half of
    "updated completely or not at all"; the other half, a move that starts and
    cannot finish, is `_file_atomically`'s.
    """
    counts = Counter(target for _, target in planned)
    duplicates = sorted(path.name for path, count in counts.items() if count > 1)
    if duplicates:
        raise ConversionError(
            "destination",
            f"imported files would share destinations in {destination}: "
            f"{', '.join(duplicates)}; --force cannot resolve this collision",
        )
    directories = sorted(target.name for _, target in planned if target.is_dir())
    if directories:
        raise ConversionError(
            "destination",
            f"{destination} holds directories at import targets: "
            f"{', '.join(directories)}; --force cannot replace directories",
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


def _file_atomically(planned: Sequence[tuple[Path, Path]], destination: Path) -> None:
    """Move every planned file into `destination`, or leave it as it was.

    A half-moved import is the state that is hardest to reason about afterwards,
    and under `--force` it is worse than untidy: a new sidecar left beside the
    *previous* import's scan is a scan described by the wrong series, and
    nothing about either file says so. So every step here is a rename, recorded
    as it is made, and a step that fails has the record reversed.

    It is done in two passes, and the order is the safety. First every target
    that already exists is moved aside -- only ever reached under `--force`
    (`_refuse_collisions` has refused it otherwise), and moved rather than
    overwritten so that it can be put back. Only then is anything filed. A pass
    that fails part-way therefore fails with one vintage of file in
    `destination`: the old ones while setting aside, since nothing new has been
    filed, and the new ones while filing, since everything they collide with is
    already out of the way. Interleaved -- set one aside, file its replacement,
    go on to the next -- a refused set-aside leaves an old scan that never moved
    beside a new sidecar that may not come back out.

    Aside is a hidden directory in `destination`, not the staging directory:
    staging is removed unconditionally when the import ends, and what is set
    aside is the caller's own file until the import has succeeded. Once it has,
    the files set aside are deleted -- that is what `--force` asked for.

    Undoing is itself a sequence of renames and can be refused for the reason
    the move was, so it too is ordered to stop safely: every file this import
    filed is withdrawn, and only if all of them went are the files set aside put
    back. A new file that will not leave never has an old one restored around
    it; what was set aside is *kept*, where nothing will read it as a result,
    and the error says which files are which. Two things this cannot cover: a
    process killed part-way, which leaves the half-moved state with whatever it
    had replaced still set aside; and a file of an earlier import that this one
    does not collide with, which was never this function's to move.

    Raises:
        ConversionError: If a file cannot be moved, saying whether the import
            was undone and, if not completely, exactly what is left.
    """
    replaced: list[tuple[Path, Path]] = []  # (target, where it was set aside)
    filed: list[tuple[Path, Path]] = []  # (staged, target)
    aside: Path | None = None
    doing = f"write to {destination}"
    try:
        colliding = [target for _, target in planned if target.exists()]
        if colliding:
            aside = Path(tempfile.mkdtemp(prefix=".fmri-qa-replaced-", dir=destination))
            for target in colliding:
                doing = f"set the existing {target.name} aside"
                replace_patiently(target, aside / target.name)
                replaced.append((target, aside / target.name))
        for staged, target in planned:
            doing = f"move {target.name} into {destination}"
            replace_patiently(staged, target)
            filed.append((staged, target))
    except OSError as exc:
        ours = _undo(filed)
        kept = replaced if ours else _undo(replaced)
        _remove_if_empty(aside)
        raise ConversionError(
            "destination",
            f"could not {doing}: {exc}; {_aftermath(ours, kept, destination)}",
        ) from exc
    if aside is not None:
        shutil.rmtree(aside, ignore_errors=True)
        # `ignore_errors` must not mean silently: what is in there is the scans
        # `--force` was asked to replace, in a directory nothing else removes.
        if aside.exists():
            warn(
                f"could not remove {aside}; it holds the files this import "
                "replaced and can be deleted",
            )


def _undo(moves: Sequence[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    """Reverse each `(origin, now)` rename, newest first; return any that refused."""
    stuck = []
    for origin, now in reversed(moves):
        try:
            replace_patiently(now, origin)
        except OSError:
            stuck.append((origin, now))
    return stuck


def _remove_if_empty(aside: Path | None) -> None:
    """Remove the set-aside directory once an undo has emptied it.

    Cleanup, made while an error is being raised, in a directory something may
    be holding open -- so it is never allowed to raise. A refusal here would
    replace the statement of what state the destination is in with a bare errno
    naming a hidden directory the caller has never heard of.
    """
    if aside is not None:
        with suppress(OSError):
            if not any(aside.iterdir()):
                aside.rmdir()


def _aftermath(
    ours: Sequence[tuple[Path, Path]],
    kept: Sequence[tuple[Path, Path]],
    destination: Path,
) -> str:
    """The second half of the error: what state the move left `destination` in.

    `ours` are files of this import that could not be withdrawn; `kept` are files
    it had replaced that are still set aside, because they could not be put back
    or because, with `ours` still in place, they were deliberately not.
    """
    if not ours and not kept:
        return f"the import was undone and {destination} is as it was"
    left = []
    if ours:
        names = ", ".join(sorted(target.name for _, target in ours))
        left.append(f"{names} in it are from this import")
    if kept:
        names = ", ".join(sorted(target.name for target, _ in kept))
        left.append(f"the {names} it replaced are kept in {kept[0][1].parent}")
    return (
        f"undoing the import failed too, so {destination} is left changed: "
        + "; ".join(left)
    )


def _describe(
    path: Path, targets: Sequence[Path], sidecar: Sidecar, *, renamed_from: str | None
) -> ImportedSeries:
    """One filed series, with the sidecar fields worth showing in a listing.

    `targets` are the series' files under their final names, in any order and
    including `path`; the ordering of `ImportedSeries.files` is done here.
    """
    stamp = naming.text_field(sidecar, "AcquisitionDateTime") or naming.text_field(
        sidecar, "AcquisitionTime"
    )
    return ImportedSeries(
        path=path,
        files=(path, *sorted(target for target in targets if target != path)),
        series=naming.series_number(sidecar),
        description=naming.text_field(sidecar, "SeriesDescription"),
        acquired=stamp,
        renamed_from=renamed_from,
    )
