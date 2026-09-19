"""Publish a complete, offline HTML site from already-loaded QA artifacts."""

import html
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from string import Template

from fmriqc.analysis import QAArtifact

from ...summary import package_version
from ...web_summary import (
    OmittedInput,
    RenderedRun,
    WebSummary,
    build_web_summary,
    web_summary_json,
)
from .figures import write_figures
from .run import render_run

__all__ = ["SiteResult", "SiteStatus", "write_site"]


_INDEX_TEMPLATE = "templates/index.html"
_RUN_TEMPLATE = "templates/run.html"
_STYLESHEET = "assets/report.css"


class SiteStatus(StrEnum):
    """The outcome of publishing a requested report inventory."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SiteResult:
    """Paths and request-level results from one published static site."""

    output: Path
    index: Path
    summary: Path
    successful_runs: int
    successful_inputs: int
    omitted_inputs: tuple[OmittedInput, ...]
    status: SiteStatus

    @property
    def omitted_count(self) -> int:
        """Return the number of requested inputs absent from the site."""
        return len(self.omitted_inputs)


def write_site(
    runs: Iterable[RenderedRun],
    output: Path | str,
    *,
    omitted: Iterable[OmittedInput] = (),
    report_version: str | None = None,
) -> SiteResult:
    """Publish a new static report site without replacing an existing target.

    Rendering failures are recorded for each input represented by their digest.
    Shared-resource, summary, and publication failures propagate after staging is
    removed, so a successful destination is always a complete site inventory.
    """
    destination = Path(output)
    _refuse_existing_destination(destination)

    grouped_runs = _group_runs(runs)
    omissions = list(omitted)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    try:
        _write_stylesheet(staging)
        _require_run_template()
        surviving = _write_figures(grouped_runs, staging, omissions)
        incomplete_before_pages = bool(omissions)
        surviving = _write_pages(
            surviving,
            staging,
            omissions,
            report_version=report_version,
            incomplete=incomplete_before_pages,
        )
        if not incomplete_before_pages and omissions:
            surviving = _write_pages(
                surviving,
                staging,
                omissions,
                report_version=report_version,
                incomplete=True,
            )

        sorted_omissions = tuple(
            sorted(
                omissions, key=lambda item: (Path(item.input_name).name, item.reason)
            )
        )
        summary = build_web_summary(
            report_version or package_version(), surviving, sorted_omissions
        )
        _write_summary(staging, summary)
        _write_index(staging, surviving, sorted_omissions)
        _refuse_existing_destination(destination)
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    successful_inputs = sum(len(run.input_names) for run in surviving)
    status = _status(successful_inputs, len(sorted_omissions))
    return SiteResult(
        output=destination,
        index=destination / "index.html",
        summary=destination / "summary.json",
        successful_runs=len(surviving),
        successful_inputs=successful_inputs,
        omitted_inputs=sorted_omissions,
        status=status,
    )


def _refuse_existing_destination(destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(
            f"refusing to replace existing report site: {destination}"
        )


def _group_runs(runs: Iterable[RenderedRun]) -> tuple[RenderedRun, ...]:
    grouped: dict[str, tuple[QAArtifact, list[str]]] = {}
    for run in runs:
        current = grouped.get(run.artifact_sha256)
        if current is None:
            grouped[run.artifact_sha256] = (run.artifact, list(run.input_names))
        else:
            current[1].extend(run.input_names)
    return tuple(
        RenderedRun(digest, artifact, tuple(sorted(input_names)))
        for digest, (artifact, input_names) in sorted(grouped.items())
    )


def _write_stylesheet(staging: Path) -> None:
    stylesheet = files(__package__).joinpath(_STYLESHEET).read_text(encoding="utf-8")
    assets = staging / "assets"
    assets.mkdir()
    (assets / "report.css").write_text(stylesheet, encoding="utf-8")


def _require_run_template() -> None:
    """Fail publication early when the shared run-page resource is unavailable."""
    files(__package__).joinpath(_RUN_TEMPLATE).read_text(encoding="utf-8")


def _write_figures(
    runs: tuple[RenderedRun, ...], staging: Path, omissions: list[OmittedInput]
) -> tuple[RenderedRun, ...]:
    surviving = []
    for run in runs:
        run_directory = staging / "runs" / run.artifact_sha256
        try:
            write_figures(run.artifact, run_directory / "figures")
        except Exception as error:  # noqa: BLE001 - per-run failures are inventory data.
            _remove_run_directory(run_directory)
            _omit_run(run, error, omissions)
        else:
            surviving.append(run)
    return tuple(surviving)


def _write_pages(
    runs: tuple[RenderedRun, ...],
    staging: Path,
    omissions: list[OmittedInput],
    *,
    report_version: str | None,
    incomplete: bool,
) -> tuple[RenderedRun, ...]:
    surviving = []
    for run in runs:
        run_directory = staging / "runs" / run.artifact_sha256
        try:
            render_run(
                run.artifact,
                run_directory,
                title=_title(run),
                report_version=report_version,
                incomplete=incomplete,
            )
        except Exception as error:  # noqa: BLE001 - per-run failures are inventory data.
            _remove_run_directory(run_directory)
            _omit_run(run, error, omissions)
        else:
            surviving.append(run)
    return tuple(surviving)


def _remove_run_directory(run_directory: Path) -> None:
    if run_directory.exists():
        shutil.rmtree(run_directory)


def _omit_run(
    run: RenderedRun, error: Exception, omissions: list[OmittedInput]
) -> None:
    reason = str(error) or type(error).__name__
    omissions.extend(OmittedInput(input_name, reason) for input_name in run.input_names)


def _write_summary(staging: Path, summary: WebSummary) -> None:
    # build_web_summary's result is deliberately JSON-safe; this narrow boundary
    # keeps the strict serializer at the publication edge.
    (staging / "summary.json").write_text(web_summary_json(summary), encoding="utf-8")


def _write_index(
    staging: Path,
    runs: tuple[RenderedRun, ...],
    omissions: tuple[OmittedInput, ...],
) -> None:
    template = Template(files(__package__).joinpath(_INDEX_TEMPLATE).read_text("utf-8"))
    page = template.substitute(_index_values(runs, omissions))
    (staging / "index.html").write_text(page, encoding="utf-8")


def _index_values(
    runs: tuple[RenderedRun, ...], omissions: tuple[OmittedInput, ...]
) -> dict[str, str]:
    requested = sum(len(run.input_names) for run in runs) + len(omissions)
    duplicates = requested - len(omissions) - len(runs)
    return {
        "summary": (
            f"{requested} requested input(s); {len(runs)} distinct run report(s); "
            f"{duplicates} duplicate input(s); {len(omissions)} omitted input(s)."
        ),
        "site_status": _site_status_message(omissions),
        "runs": _run_inventory(runs),
        "omissions": _omission_inventory(omissions),
    }


def _run_inventory(runs: tuple[RenderedRun, ...]) -> str:
    if not runs:
        return "<li>No run reports were rendered.</li>"
    return "\n".join(
        '<li><a href="runs/{digest}/index.html">{title}</a>'
        "<p>Requested inputs: {names}</p></li>".format(
            digest=_attribute(run.artifact_sha256),
            title=_text(_title(run)),
            names=_text(", ".join(Path(name).name for name in run.input_names)),
        )
        for run in runs
    )


def _omission_inventory(omissions: tuple[OmittedInput, ...]) -> str:
    if not omissions:
        return "<li>No requested inputs were omitted.</li>"
    return "\n".join(
        f"<li><strong>{_text(Path(item.input_name).name)}</strong>"
        f"<p>{_text(item.reason)}</p></li>"
        for item in omissions
    )


def _title(run: RenderedRun) -> str:
    return run.artifact.provenance.scan or Path(run.input_names[0]).name


def _site_status_message(omissions: tuple[OmittedInput, ...]) -> str:
    if not omissions:
        return ""
    return (
        '<p class="notice notice-incomplete"><strong>Site incomplete.</strong> '
        "One or more requested inputs were not rendered.</p>"
    )


def _status(successful_inputs: int, omitted_count: int) -> SiteStatus:
    if successful_inputs == 0:
        return SiteStatus.FAILED
    if omitted_count:
        return SiteStatus.INCOMPLETE
    return SiteStatus.COMPLETE


def _text(value: object) -> str:
    return html.escape(str(value), quote=True)


def _attribute(value: object) -> str:
    return html.escape(str(value), quote=True)
