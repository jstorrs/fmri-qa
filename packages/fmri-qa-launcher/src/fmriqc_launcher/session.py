"""The functional core: one DICOM directory in, one report per series out.

`run_session` is the whole pipeline: import, analyze, save the artifact,
render the report. It runs once per series in a staging directory and
publishes a series only once all its files exist. A series lands in
`output_dir` complete or never appears there, whatever failed. This matters
because a report takes about eight seconds to render, long enough for a reader
to see a scan with no report, or a report for a run that then fails.

Staging is the system's temporary directory, not `output_dir`, which is often
watched (OneDrive, a lab share with a sync client). A watcher uploads
everything written there: dcm2niix's raw output, a scan under its pre-filing
name, every `.tmp` before its rename. None of that is a result, and a busy
watcher also refuses the next rename (see `fmriqc.rename`). So `output_dir`
receives finished files only, once each. Staging is on another filesystem, so
they arrive by copy, which is not atomic. The copy goes into a hidden sibling
of the series directory, and that is renamed into place. This keeps the
guarantee above at the cost of one rename the watcher can still contest (see
`_publish`).

The heavy imports below (`fmriqc`'s analysis stack, `fmriqc_report`'s HTML
renderer) are at module top, unlike the package `__init__`, which loads them
lazily through `__getattr__`. This module needs them, so delaying gains
nothing. See `__init__.py`'s docstring.
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
    """One series `_run_in_staging` will attempt.

    `series` is what the converter filed in staging's import directory, and
    its name is `target.name`. `index`/`total` are what `Progress` reports.
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

    `output_dir` is created if missing. Work happens in a staging directory
    under the system's temporary directory (`fmri-qa-run.<token>`), removed
    whether or not the run succeeds. Files in it still held open by something
    else are logged by name as left behind. A reader of `output_dir` sees only
    finished series, and a sync client only finished files. A series whose name
    already exists in `output_dir` is refused rather than overwritten, and
    that costs nothing.
    `should_continue` is polled between series, never mid-series, so a cancel
    takes effect at the next safe point instead of tearing a render in half.
    `index`/`total` on the reported `Progress` count only the series attempted;
    refused series are found for free while checking names and are never
    reported.

    `progress` and `should_continue` are called inside the per-series work but
    outside the guard that turns a library or IO failure into a `Failed`
    outcome. An exception from either is a caller bug, so it propagates
    unchanged (staging is still removed).

    `notice` receives cleanup leftovers, including while an error unwinds; by
    default only logging records them. Ordinary exceptions from this
    best-effort callback are logged and suppressed so the run's result or
    original error survives. `KeyboardInterrupt` and `SystemExit` propagate.

    Raises
    ------
    SessionError
        If `output_dir` cannot be created or written to, no staging directory
        can be made, the DICOM import fails outright (no converter, an
        unreadable source, dcm2niix exiting non-zero, an `OSError` while filing
        its output), or the import produces no series at all. A failure in
        one series never raises: it becomes a `Failed` outcome and the run
        continues.
    """
    try:
        request.output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SessionError(f"cannot create {request.output_dir}: {exc}") from exc

    _require_writable(request.output_dir, notice)

    # Keep `mkdtemp`'s `0700`: staging holds a scan in a shared temporary
    # directory. Nothing published inherits it; `_publish` uses the umask.
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

    Staging lives outside `output_dir`, so the first write there is the first
    publish, minutes of analysis later, and an unwritable directory would fail
    every series in turn. Making an empty directory asks the same question up
    front with the operation publishing will use.

    Only the `mkdir` decides. In a watched directory removing the probe can be
    refused for the reason a rename can (see `fmriqc.rename`), but the `mkdir`
    already proved the directory writable, so that must not stop the run. It
    is logged by name like any other leftover.
    """
    probe = output_dir / f".fmri-qa-probe.{secrets.token_hex(8)}"
    try:
        probe.mkdir()
    except OSError as exc:
        raise SessionError(f"cannot write to {output_dir}: {exc}") from exc
    _discard(probe, notice)


def _discard(directory: Path, notice: CleanupNoticeCallback | None) -> None:
    """Remove `directory` and what is in it, saying so by name if that fails.

    `ignore_errors` lets this run while an exception unwinds but would make a
    failure silent. Whatever holds a file open refuses an unlink as it refuses
    a rename (see `fmriqc.rename`), leaving a randomly named directory that
    nothing removes, holding a scan if it is staging. Nothing finished is ever
    in one, so the notice says it is safe to delete.
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
        # Name staging too. It is on a disk the user did not choose, and when
        # that disk is full dcm2niix's own complaint may not say where.
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
            # Created by another run since the snapshot above. Refuse it and
            # drop it from the progress bar's count.
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
    """Log `exc` and build its `Failed` outcome, with the warnings noted so far."""
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
    """Analyze, report and publish one planned series; `Failed` on any error.

    Warnings the analysis raises about the scan (a missing spatial unit, an
    unreadable sidecar, a motion fit that did not converge) are captured, not
    printed, and carried on whichever outcome this returns. The core stays
    silent and a shell decides how to show them. Only loading and analyzing
    are captured, as in `fmriqc.cli.qa`: `simplefilter("always")` revives
    warnings a library silences on purpose, so saving or rendering under it
    would present, say, netCDF4's first-import numpy notice as a finding about
    the scan. `warnings.catch_warnings` is process-global, not thread-local,
    so a caller running `run_session` on a worker thread must not rely on
    filters it sets in another thread meanwhile.

    `progress` is called before each stage's guarded step, never inside it, so
    a `progress` that raises is a caller bug and does not fail the series. See
    `run_session`'s docstring.
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
            # Use the published path: it goes into the artifact's provenance
            # and the report's "Source" row, and the staging path vanishes.
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
    # Publishing copies, so discard now or staging holds every finished
    # series until the run ends. Temporary directories are often small,
    # RAM-backed or under a quota.
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

    The copy crosses filesystems, so it cannot be atomic. The files go into a
    hidden sibling of `target`, and the sibling is renamed. Copying straight
    into `target` would give a sync client no rename to refuse, and would leave
    a series directory that looks published and is not, for as long as a 30 MB
    scan takes to copy and forever after a crash. The next run would then find
    the name taken and refuse it, so a half-copied series would block its own
    repair. A refused rename only fails the series, loudly, and the sibling is
    removed with it.

    A process killed outright during the copy runs no `finally`, so the
    sibling stays as `.<series>.<token>.partial`, which a sync client will
    have uploaded. It is never mistaken for a series and never blocks one. No
    later run removes it, since a run cannot tell a dead run's sibling from a
    live run's. It is safe to delete by hand.

    `work_dir` holds files only, which is all the pipeline puts there. A
    directory in it fails the series rather than being silently left out.

    `target`'s existence is checked before and after the rename. The first
    check avoids a wasted copy and a rename onto an existing directory. The
    second is needed because `replace_patiently` can wait seconds, another run
    can publish `target` in that window, and Windows reports a rename onto an
    existing directory as the same `PermissionError` being waited out
    (sometimes `FileExistsError`). Without it the collision would surface as
    "access is denied".
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
        # On success the sibling is already renamed away. After any failure,
        # this keeps a half-copied series out of `output_dir`.
        if partial.exists():
            _discard(partial, notice)


def _copy_durably(source: Path, destination: Path) -> None:
    """Copy one file, syncing its contents before returning.

    Like `save_artifact`, this syncs the file before it can be renamed, so a
    crash soon after cannot leave a truncated file under a finished name. It
    does not sync the directory, so the guarantee goes no further. The file is
    created exclusively with default permissions, so it follows the umask, not
    staging's `0700`.
    """
    with source.open("rb") as read, destination.open("xb") as write:
        shutil.copyfileobj(read, write)
        write.flush()
        os.fsync(write.fileno())


def _messages(caught: list[warnings.WarningMessage]) -> tuple[str, ...]:
    """Collect the text of every warning recorded by `catch_warnings`."""
    return tuple(str(w.message) for w in caught)
