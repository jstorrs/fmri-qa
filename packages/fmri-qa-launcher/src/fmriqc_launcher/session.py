"""The functional core: one DICOM directory in, one report per series out.

`run_session` is the whole pipeline -- import, analyze, save the artifact,
render the report -- run once per series inside a staging directory,
publishing each series only once every one of its files exists. Nothing is
ever half-published: a series either lands in `output_dir` complete, or it
never appears there at all, whatever failed along the way. That is why
staging exists at all rather than writing straight into `output_dir` -- a
report that takes eight seconds to render is eight seconds in which a reader
could otherwise see a scan with no report yet, or a report for a run that then
fails.

Staging is the system's temporary directory, not `output_dir`. An output
directory is often a watched one -- OneDrive, a lab share with a sync client --
and everything written into it is something the watcher uploads: dcm2niix's raw
output, a scan under the name it had before it was filed, every `.tmp` on its
way to being renamed. None of that is a result, and a watcher busy with it is
also what refuses the next rename (see `fmriqc.rename`). So `output_dir`
receives finished files only, once each. They arrive by a copy, since staging
is on another filesystem, and a copy is not atomic -- so it is made into a
hidden sibling of the series directory and *that* is renamed into place, which
keeps the guarantee above at the cost of one rename the watcher can still
contest (see `_publish`).

The heavy imports below (`fmriqc`'s analysis stack, `fmriqc_report`'s HTML
renderer) sit at module top rather than behind a lazy `__getattr__`, unlike
the package `__init__`: this module *is* the thing that needs them, so nothing
is gained by delaying the cost within it -- see `__init__.py`'s docstring for
where the laziness actually lives.
"""

import logging
import os
import secrets
import shutil
import tempfile
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import fmriqc
from fmriqc.convert.session import ImportedSeries
from fmriqc.exceptions import ConversionError
from fmriqc.load.paths import nifti_stem
from fmriqc.rename import replace_patiently
from fmriqc_report.formats.html import write_run_page

from .exceptions import SessionError
from .outcome import Failed, Published, Refused, RunResult, SeriesOutcome
from .progress import (
    CleanupNotice,
    CleanupNoticeCallback,
    Progress,
    ProgressCallback,
    Stage,
)
from .request import RunRequest

__all__ = ["run_session"]

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _PlannedSeries:
    """One series `_run_in_staging` has decided to attempt.

    `series` is what the converter filed in staging's import directory; its
    name is `target.name`. `index`/`total` are what `Progress` reports.
    """

    series: ImportedSeries
    target: Path
    index: int
    total: int


def _silent(_progress: Progress) -> None:
    """Report nothing, as the default progress callback."""


def _always() -> bool:
    """Return True always: the default check for a run never asked to cancel."""
    return True


def run_session(
    request: RunRequest,
    *,
    progress: ProgressCallback = _silent,
    notice: CleanupNoticeCallback | None = None,
    should_continue: Callable[[], bool] = _always,
) -> RunResult:
    """Run one import-analyze-report-publish pass over `request`.

    `output_dir` is created if missing. Work happens inside a staging directory
    under the system's temporary directory (`fmri-qa-run.<token>`, removed whether
    or not the run succeeds -- or, where something else holds a file in it open,
    logged by name as left behind), so a reader of `output_dir` only ever sees
    series that are completely finished, and a sync client watching it only ever
    sees finished files. A series whose name already exists in `output_dir` is
    refused rather than overwritten and costs nothing; `should_continue` is polled
    between the remaining series (never in the middle of one) so a cancel takes
    effect at the next safe point rather than tearing a render in half.
    `index`/`total` on the `Progress` this reports count the series that are
    actually attempted -- refused series are found for free while checking names and
    are never counted or reported on.

    `progress` and `should_continue` are called from inside the per-series
    work but outside the guard that turns a library/IO failure into a
    `Failed` outcome: an exception either one raises is a bug in the caller,
    not in the series, so it propagates out of this function unchanged
    (staging is still removed either way -- see below).

    `notice` receives cleanup leftovers, including while an error unwinds;
    by default only diagnostic logging records them. Ordinary exceptions from
    this best-effort callback are logged and suppressed to preserve the run's
    result or original error. `KeyboardInterrupt` and `SystemExit` propagate.

    Raises
    ------
    SessionError
        If `output_dir` cannot be created or written to, no staging directory
        can be made, the DICOM import fails outright (no converter, an
        unreadable source, dcm2niix exiting non-zero, an `OSError` while filing
        its output), or the import produces no series at all. A failure specific
        to *one* series never raises -- it becomes a `Failed` outcome and the
        run continues with the next series.
    """
    try:
        request.output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SessionError(f"cannot create {request.output_dir}: {exc}") from exc

    _require_writable(request.output_dir, notice)

    # `mkdtemp`'s `0700` is wanted here: what sits in staging is a scan on a
    # machine's shared temporary directory. Nothing published inherits it --
    # `_publish` makes its own directory and its own files, under the umask.
    try:
        staging = Path(tempfile.mkdtemp(prefix="fmri-qa-run."))
    except OSError as exc:
        raise SessionError(f"cannot create a staging directory: {exc}") from exc
    try:
        return _run_in_staging(request, staging, progress, should_continue, notice)
    finally:
        _discard(staging, notice)


def _require_writable(output_dir: Path, notice: CleanupNoticeCallback | None) -> None:
    """Refuse an `output_dir` nothing can be published into, before any work.

    Staging lives outside `output_dir`, so the first write into `output_dir`
    is the first publish, minutes of analysis later, and an unwritable one
    would fail every series there in turn. Making an empty directory asks the
    same question up front, of the same operation publishing will perform.

    Only making it decides. Removing it is cleanup, and in a watched directory
    cleanup can be refused for the reason a rename can (see `fmriqc.rename`):
    the watcher has opened what was just made. That is no evidence against
    writing here -- the `mkdir` has just proved the opposite -- so it must not
    stop the run; it is logged by name like any other leftover.
    """
    probe = output_dir / f".fmri-qa-probe.{secrets.token_hex(8)}"
    try:
        probe.mkdir()
    except OSError as exc:
        raise SessionError(f"cannot write to {output_dir}: {exc}") from exc
    _discard(probe, notice)


def _discard(directory: Path, notice: CleanupNoticeCallback | None) -> None:
    """Remove `directory` and what is in it, saying so by name if that fails.

    `ignore_errors` is what lets this run while an exception unwinds, and it is
    also what would make a failure silent. Whatever holds a file open refuses
    an unlink as it refuses a rename (see `fmriqc.rename`), and what is left is
    a directory with a random name that nothing will ever remove -- holding a
    scan, if it is staging. Nothing finished is ever in one, so say that it is
    safe to delete.
    """
    shutil.rmtree(directory, ignore_errors=True)
    if directory.exists():
        _LOG.warning(
            "could not remove the working directory %s; it holds nothing "
            "finished and can be deleted",
            directory,
        )
        if notice is not None:
            try:
                notice(
                    CleanupNotice(
                        directory,
                        "could not remove working directory; "
                        "it holds nothing finished and can be deleted",
                    )
                )
            except Exception:  # noqa: BLE001 - best-effort reporting must not mask a run error
                _LOG.exception("cleanup notice callback failed for %s", directory)


def _run_in_staging(
    request: RunRequest,
    staging: Path,
    progress: ProgressCallback,
    should_continue: Callable[[], bool],
    notice: CleanupNoticeCallback | None,
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
        # Names staging too: it is on a disk the user did not choose, and when
        # that one is full dcm2niix's own complaint need not say where.
        raise SessionError(
            f"could not import {request.dicom_dir} into {import_dir}: {exc}"
        ) from exc
    if not result.series:
        raise SessionError(f"{request.dicom_dir} produced no series to import")

    plan = [
        (series, request.output_dir / nifti_stem(series.path))
        for series in result.series
    ]
    refused = {target for _, target in plan if target.exists()}
    total = len(plan) - len(refused)

    outcomes: list[SeriesOutcome] = []
    cancelled = False
    index = 0
    for series, target in plan:
        name = target.name
        if target in refused:
            outcomes.append(Refused(name, target))
            continue
        if target.exists():
            # Created by another run since the snapshot above: refused for
            # nothing, and no longer part of what the progress bar counts.
            total -= 1
            outcomes.append(Refused(name, target))
            continue
        if not should_continue():
            cancelled = True
            break
        index += 1
        planned = _PlannedSeries(series, target, index, total)
        outcomes.append(_publish_series(request, staging, planned, progress, notice))
    return RunResult(request.output_dir, tuple(outcomes), cancelled=cancelled)


def _move_files(work_dir: Path, files: Sequence[Path]) -> None:
    """Move each of `files` into `work_dir`, keeping its name."""
    for file in files:
        replace_patiently(file, work_dir / file.name)


def _failed(name: str, exc: Exception, noted: tuple[str, ...] = ()) -> Failed:
    """Log `exc` and build its `Failed` outcome, with the warnings before it."""
    reason = str(exc) or type(exc).__name__
    _LOG.warning("series %s failed: %s", name, reason)
    return Failed(name, reason=reason, warnings=noted)


def _publish_series(
    request: RunRequest,
    staging: Path,
    planned: _PlannedSeries,
    progress: ProgressCallback,
    notice: CleanupNoticeCallback | None,
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
    name = planned.target.name
    work_dir = staging / name
    scan_path = work_dir / planned.series.path.name
    artifact_path = work_dir / f"{name}.qa.nc"
    report_path = work_dir / f"{name}.html"

    try:
        work_dir.mkdir()
        _move_files(work_dir, planned.series.files)
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
        _publish(work_dir, planned.target, notice)
    except Exception as exc:  # noqa: BLE001 - one series' failure, reported and skipped
        return _failed(name, exc, noted)
    # Publishing is a copy, not a move, so without this staging would hold
    # every series the run has finished until the run ended -- on a temporary
    # directory that is often small, RAM-backed, or under a quota, while the
    # output directory the user chose has room to spare.
    _discard(work_dir, notice)

    sidecar_name = f"{name}.json"
    has_sidecar = any(file.name == sidecar_name for file in planned.series.files)
    return Published(
        name=name,
        directory=planned.target,
        scan=planned.target / scan_path.name,
        sidecar=planned.target / sidecar_name if has_sidecar else None,
        artifact=planned.target / artifact_path.name,
        report=planned.target / report_path.name,
        warnings=noted,
    )


def _publish(
    work_dir: Path, target: Path, notice: CleanupNoticeCallback | None = None
) -> None:
    """Copy a finished `work_dir` out of staging and into place as `target`.

    In two steps, because the copy crosses filesystems and so cannot be the
    atomic one: the files are copied into a hidden sibling of `target`, and the
    sibling is renamed. Copying straight into `target` would be one step and
    could not be refused by a sync client -- and would leave, for as long as a
    30 MB scan takes to copy and for ever after a crash, a series directory
    that looks published and is not. That one is the worse failure: the next
    run finds the name taken and refuses it, so a half-copied series blocks its
    own repair. A refused rename only fails the series, loudly, and the
    sibling is removed with it.

    What neither step can cover is a process that is killed outright during
    the copy -- no `finally` runs, and the sibling stays: a directory named
    `.<series>.<token>.partial`, which a sync client will have uploaded. It is
    never mistaken for a series and never blocks one, and no later run removes
    it, since one run cannot tell a dead run's sibling from a live run's. It
    is safe to delete by hand.

    `work_dir` holds files only, which is all the pipeline puts there; a
    directory in it fails the series rather than being silently left out.

    `target`'s existence is checked on both sides of the rename. Before,
    because a rename onto an existing directory must never be attempted (and
    before the copy, which would be wasted). After, because
    `replace_patiently` can spend seconds waiting, another run can publish
    `target` in that window, and Windows reports a rename onto an existing
    directory as the very `PermissionError` being waited out (sometimes as
    `FileExistsError`) -- so without the second look, the one collision this
    guard exists to name would surface as "access is denied".
    """
    taken = f"{target} was created while this run was in progress"
    if target.exists():
        raise SessionError(taken)
    partial = target.with_name(f".{target.name}.{secrets.token_hex(8)}.partial")
    try:
        partial.mkdir()
        for path in sorted(work_dir.iterdir()):
            _copy_durably(path, partial / path.name)
        try:
            replace_patiently(partial, target)
        except OSError as exc:
            if target.exists():
                raise SessionError(taken) from exc
            raise
    finally:
        # Renamed away on success, so this finds nothing; after any failure it
        # is what keeps a half-copied series out of `output_dir`.
        if partial.exists():
            _discard(partial, notice)


def _copy_durably(source: Path, destination: Path) -> None:
    """Copy one file, syncing its contents before returning.

    `save_artifact` syncs what it writes before renaming it, so that a crash
    soon after cannot leave a truncated file under a finished name. The rename
    that matters is the one in `output_dir`, of these copies, so they are
    synced the same way. Like `save_artifact`, this syncs the file and not the
    directory holding it, which is as far as the guarantee goes. Created
    exclusively and with default permissions, so a published file answers to
    the umask and not to staging's `0700`.
    """
    with source.open("rb") as read, destination.open("xb") as write:
        shutil.copyfileobj(read, write)
        write.flush()
        os.fsync(write.fileno())


def _messages(caught: list[warnings.WarningMessage]) -> tuple[str, ...]:
    """Collect the text of every warning recorded by `catch_warnings`."""
    return tuple(str(w.message) for w in caught)
