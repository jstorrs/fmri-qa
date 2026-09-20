"""The functional core: one DICOM directory in, one report per series out.

`run_session` is the whole pipeline -- import, analyze, save the artifact,
render the report -- run once per series inside a hidden staging directory,
publishing each series only once every one of its files exists. Nothing is
ever half-published: a series either lands in `output_dir` complete, or it
never appears there at all, whatever failed along the way. That is why
staging exists at all rather than writing straight into `output_dir` -- a
report that takes eight seconds to render is eight seconds in which a reader
could otherwise see a scan with no report yet, or a report for a run that then
fails.

The heavy imports below (`fmriqc`'s analysis stack, `fmriqc_report`'s HTML
renderer) sit at module top rather than behind a lazy `__getattr__`, unlike
the package `__init__`: this module *is* the thing that needs them, so nothing
is gained by delaying the cost within it -- see `__init__.py`'s docstring for
where the laziness actually lives.
"""

import logging
import secrets
import shutil
import warnings
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import fmriqc
from fmriqc.exceptions import ConversionError
from fmriqc.load.paths import nifti_stem
from fmriqc_report.formats.html import write_run_page

from .exceptions import SessionError
from .progress import Progress, ProgressCallback, Stage
from .request import RunRequest

__all__ = [
    "Failed",
    "Published",
    "Refused",
    "RunResult",
    "SeriesOutcome",
    "run_session",
]

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Published:
    """One series filed under `output_dir / name`, with all four of its files."""

    name: str
    directory: Path
    scan: Path
    sidecar: Path | None
    artifact: Path
    report: Path
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Refused:
    """A series whose name already exists in `output_dir`.

    Never overwritten -- see `run_session`'s docstring -- so a refused series
    is one the converter did import into staging, but whose analysis, render,
    and publish are all skipped: this costs it no analysis time and no render
    time, only the import it shared with every other series in the run.
    """

    name: str
    existing: Path


@dataclass(frozen=True, slots=True)
class Failed:
    """A series that raised somewhere between import and publish.

    `reason` is `str(exc)`, or the exception's type name when that string is
    empty. Whatever this series produced in staging is discarded with the rest
    of it; nothing partial ever reaches `output_dir`.
    """

    name: str
    reason: str
    warnings: tuple[str, ...] = ()


type SeriesOutcome = Published | Refused | Failed


@dataclass(frozen=True, slots=True)
class RunResult:
    """Every series a run touched, in the order it found them."""

    output_dir: Path
    outcomes: tuple[SeriesOutcome, ...]
    cancelled: bool = False

    @property
    def published(self) -> tuple[Published, ...]:
        """The series that made it all the way to `output_dir`."""
        return tuple(o for o in self.outcomes if isinstance(o, Published))

    @property
    def reports(self) -> tuple[Path, ...]:
        """The report of every published series, in the same order."""
        return tuple(o.report for o in self.published)

    @property
    def complete(self) -> bool:
        """Whether every series found was published and nothing was cancelled.

        False for a run that found nothing at all: a report of "0 of 0,
        complete" is not a run a caller should treat as a success.
        """
        return (
            bool(self.outcomes)
            and not self.cancelled
            and all(isinstance(o, Published) for o in self.outcomes)
        )


@dataclass(frozen=True, slots=True)
class _PlannedSeries:
    """One series `_run_in_staging` has decided to attempt.

    `imported_path` is where the converter left this series' NIfTI inside
    staging's import directory; `companions` are the other files there filed
    under this series' name (its sidecar, most often) -- see
    `_assign_companions`. `index`/`total` are what `Progress` reports.
    """

    imported_path: Path
    name: str
    target: Path
    companions: tuple[str, ...]
    index: int
    total: int


def _silent(_progress: Progress) -> None:
    """The default progress callback: report nothing."""


def _always() -> bool:
    """The default continuation check: a run that is never asked to cancel."""
    return True


def run_session(
    request: RunRequest,
    *,
    progress: ProgressCallback = _silent,
    should_continue: Callable[[], bool] = _always,
) -> RunResult:
    """Run one import-analyze-report-publish pass over `request`.

    `output_dir` is created if missing. Work happens inside a hidden staging
    directory beside it (`.fmri-qa-run.<token>`, removed whether or not the
    run succeeds), so a reader of `output_dir` only ever sees series that are
    completely finished. A series whose name already exists in `output_dir`
    is refused rather than overwritten and costs nothing; `should_continue` is
    polled between the remaining series (never in the middle of one) so a
    cancel takes effect at the next safe point rather than tearing a render in
    half. `index`/`total` on the `Progress` this reports count the series that
    are actually attempted -- refused series are found for free while
    checking names and are never counted or reported on.

    `progress` and `should_continue` are called from inside the per-series
    work but outside the guard that turns a library/IO failure into a
    `Failed` outcome: an exception either one raises is a bug in the caller,
    not in the series, so it propagates out of this function unchanged
    (staging is still removed either way -- see below).

    Raises:
        SessionError: If `output_dir` cannot be created, the DICOM import
            fails outright (no converter, an unreadable source, dcm2niix
            exiting non-zero, an `OSError` while filing its output), or the
            import produces no series at all. A failure specific to *one*
            series never raises -- it becomes a `Failed` outcome and the run
            continues with the next series.
    """
    try:
        request.output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SessionError(f"cannot create {request.output_dir}: {exc}") from exc

    # Inside `output_dir`, so publishing a series is a same-filesystem rename;
    # `secrets.token_hex` and a plain `Path.mkdir()` rather than
    # `tempfile.mkdtemp`, which forces `0700` regardless of the process umask
    # -- the directory twin of what `fmriqc_report.atomic` does for a file.
    staging = request.output_dir / f".fmri-qa-run.{secrets.token_hex(8)}"
    try:
        staging.mkdir()
    except OSError as exc:
        raise SessionError(
            f"cannot create a staging directory under {request.output_dir}: {exc}"
        ) from exc
    try:
        return _run_in_staging(request, staging, progress, should_continue)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _assign_companions(
    file_names: Iterable[str], series_names: Sequence[str]
) -> dict[str, str]:
    """Map each of `file_names` to the longest name in `series_names` it is filed under.

    Mirrors `fmriqc.convert.session._plan_files`'s rule, for the same reason:
    with series names `X` and `X.rep`, `X.rep.json` must be claimed by
    `X.rep`, not by the shorter `X` that is also a prefix of its name. Checking
    the longest candidate first is what makes that so. A file matching no
    series name at all is left out of the result.
    """
    stems = sorted(series_names, key=len, reverse=True)
    assigned: dict[str, str] = {}
    for file_name in file_names:
        owner = next((stem for stem in stems if file_name.startswith(f"{stem}.")), None)
        if owner is not None:
            assigned[file_name] = owner
    return assigned


def _run_in_staging(
    request: RunRequest,
    staging: Path,
    progress: ProgressCallback,
    should_continue: Callable[[], bool],
) -> RunResult:
    """Import into `staging`, then analyze, report and publish each series."""
    progress(Progress(Stage.IMPORT))
    import_dir = staging / "import"
    try:
        result = fmriqc.import_dicom(
            request.dicom_dir,
            import_dir,
            binary=request.dcm2niix,
            names="qa",
            compress=True,
            anonymize=request.anonymize,
        )
    except (ConversionError, OSError) as exc:
        raise SessionError(f"could not import {request.dicom_dir}: {exc}") from exc
    if not result.series:
        raise SessionError(f"{request.dicom_dir} produced no series to import")

    series_entries = [
        (series.path, nifti_stem(series.path)) for series in result.series
    ]
    names = [name for _, name in series_entries]

    # Every companion (sidecar, or a second echo's own NIfTI's sidecar) is
    # assigned to its series once, up front, over every file the import
    # produced -- not filed one series at a time as each is published, which
    # is what let a shorter stem steal a longer one's file (see
    # `_assign_companions`).
    nifti_names = {path.name for path, _ in series_entries}
    companion_files = [
        p.name for p in import_dir.iterdir() if p.name not in nifti_names
    ]
    companion_owner = _assign_companions(companion_files, names)
    companions_by_name: dict[str, list[str]] = {name: [] for name in names}
    for file_name, owner in companion_owner.items():
        companions_by_name[owner].append(file_name)

    plan = [
        (imported_path, name, request.output_dir / name)
        for imported_path, name in series_entries
    ]
    total = sum(1 for _, _, target in plan if not target.exists())

    outcomes: list[SeriesOutcome] = []
    cancelled = False
    index = 0
    for imported_path, name, target in plan:
        if target.exists():
            outcomes.append(Refused(name, target))
            continue
        if not should_continue():
            cancelled = True
            break
        index += 1
        planned = _PlannedSeries(
            imported_path=imported_path,
            name=name,
            target=target,
            companions=tuple(companions_by_name[name]),
            index=index,
            total=total,
        )
        outcomes.append(_publish_series(request, staging, planned, progress))
    return RunResult(request.output_dir, tuple(outcomes), cancelled=cancelled)


def _move_companions(
    source_dir: Path, work_dir: Path, imported_name: str, companions: Sequence[str]
) -> None:
    """Move the NIfTI `imported_name` and its assigned `companions` into `work_dir`."""
    for file_name in (imported_name, *companions):
        (source_dir / file_name).replace(work_dir / file_name)


def _failed(name: str, exc: Exception, noted: tuple[str, ...] = ()) -> Failed:
    """A logged `Failed` outcome for `exc`, carrying whatever warnings preceded it."""
    reason = str(exc) or type(exc).__name__
    _LOG.warning("series %s failed: %s", name, reason)
    return Failed(name, reason=reason, warnings=noted)


def _publish_series(
    request: RunRequest,
    staging: Path,
    planned: _PlannedSeries,
    progress: ProgressCallback,
) -> SeriesOutcome:
    """Analyze, report, and publish one planned series; `Failed` on any error.

    Every warning the analysis raises about the scan (a missing spatial unit,
    an unreadable sidecar, a motion fit that did not converge) is captured
    rather than left to print, and carried on whichever outcome this returns
    -- the core stays silent; a shell decides whether and how to show them.
    Only loading and analyzing are captured, exactly as `fmriqc.cli.qa` does:
    `simplefilter("always")` also revives warnings a library silences on
    purpose, and saving or rendering under it would present, say, netCDF4's
    first-import numpy notice as a finding about the physicist's scan.
    `warnings.catch_warnings` is process-global state, not thread-local -- a
    caller running `run_session` on a worker thread must not rely on warnings
    filters it sets in any other thread meanwhile.

    `progress` is called before the guarded step for each stage, never inside
    it, so a `progress` that raises is a bug in the caller, not a reason to
    fail this series -- see `run_session`'s docstring.
    """
    name = planned.name
    work_dir = staging / name
    scan_path = work_dir / planned.imported_path.name
    artifact_path = work_dir / f"{name}.qa.nc"
    report_path = work_dir / f"{name}.html"

    try:
        work_dir.mkdir()
        _move_companions(
            planned.imported_path.parent,
            work_dir,
            scan_path.name,
            planned.companions,
        )
    except Exception as exc:  # noqa: BLE001 - one series' failure, reported and skipped
        return _failed(name, exc)

    progress(Progress(Stage.ANALYZE, planned.index, planned.total, name))
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            scan = fmriqc.QAScan.from_nifti(scan_path)
            # The published path, not the staging one: this is what the
            # artifact's provenance and the report's "Source" row show, and a
            # staging path that vanishes the moment this run finishes would be
            # a broken answer to "where did this come from".
            artifact = fmriqc.analyze(
                scan,
                request.settings,
                name=scan_path.name,
                source=str(planned.target / scan_path.name),
            )
        except Exception as exc:  # noqa: BLE001 - one series' failure, reported and skipped
            return _failed(name, exc, _messages(caught))
    noted = _messages(caught)

    try:
        fmriqc.save_artifact(artifact, artifact_path)
    except Exception as exc:  # noqa: BLE001 - one series' failure, reported and skipped
        return _failed(name, exc, noted)

    progress(Progress(Stage.REPORT, planned.index, planned.total, name))
    try:
        write_run_page(artifact, report_path, title=name)
    except Exception as exc:  # noqa: BLE001 - one series' failure, reported and skipped
        return _failed(name, exc, noted)

    progress(Progress(Stage.PUBLISH, planned.index, planned.total, name))
    try:
        if planned.target.exists():
            raise SessionError(
                f"{planned.target} was created while this run was in progress"
            )
        work_dir.replace(planned.target)
    except Exception as exc:  # noqa: BLE001 - one series' failure, reported and skipped
        return _failed(name, exc, noted)

    sidecar = planned.target / f"{name}.json"
    return Published(
        name=name,
        directory=planned.target,
        scan=planned.target / scan_path.name,
        sidecar=sidecar if sidecar.exists() else None,
        artifact=planned.target / artifact_path.name,
        report=planned.target / report_path.name,
        warnings=noted,
    )


def _messages(caught: list[warnings.WarningMessage]) -> tuple[str, ...]:
    """The text of every warning `warnings.catch_warnings(record=True)` caught."""
    return tuple(str(w.message) for w in caught)
