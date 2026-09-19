"""Publish a complete, offline HTML site from already-loaded QA artifacts."""

import html
import math
import secrets
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from string import Template

from fmriqc.analysis import Measurements, QAArtifact

from ...content import METRIC_DOCS, MetricDoc
from ...summary import device_line, package_version
from ...web_summary import (
    OmittedInput,
    RenderedRun,
    WebSummary,
    build_web_summary,
    web_summary_json,
)
from . import resources
from .run import SiteContext, write_run_page

__all__ = ["SiteResult", "SiteStatus", "write_site"]


class SiteStatus(StrEnum):
    """The outcome of publishing a requested report inventory."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    FAILED = "failed"


# The index runs table's headline metric columns, selected by name from the
# shared metric catalog so their labels and formatting can never drift from
# what a run page itself shows. A missing name fails loudly at import time.
_HEADLINE_METRIC_NAMES = (
    "snr",
    "sfnr",
    "ghost_pct",
    "drift_pct",
    "percent_fluctuation",
)
_METRIC_DOCS_BY_NAME: dict[str, MetricDoc] = {doc.name: doc for doc in METRIC_DOCS}
_HEADLINE_METRICS: tuple[MetricDoc, ...] = tuple(
    _METRIC_DOCS_BY_NAME[name] for name in _HEADLINE_METRIC_NAMES
)


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

    version = report_version or package_version()
    grouped_runs = _group_runs(runs)
    omissions = list(omitted)
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f".{destination.name}.{secrets.token_hex(8)}"
    staging.mkdir()
    try:
        _write_stylesheet(staging)
        _require_run_template()
        incomplete_before_pages = bool(omissions)
        surviving = _write_pages(
            grouped_runs,
            staging,
            omissions,
            report_version=version,
            incomplete=incomplete_before_pages,
        )
        if not incomplete_before_pages and omissions:
            # Rare: a late omission appears only once every survivor is known,
            # so the whole surviving set is redrawn as incomplete rather than
            # keeping ~600 KB of encoded figures per run in memory to patch in
            # place. The cost is redrawing all fourteen figures for every
            # surviving run a second time, which is fine because the path is
            # rare.
            surviving = _write_pages(
                surviving,
                staging,
                omissions,
                report_version=version,
                incomplete=True,
            )

        sorted_omissions = tuple(
            sorted(
                omissions, key=lambda item: (Path(item.input_name).name, item.reason)
            )
        )
        summary = build_web_summary(version, surviving, sorted_omissions)
        _write_summary(staging, summary)
        _write_index(staging, surviving, sorted_omissions, version)
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
    stylesheet = resources.read_stylesheet()
    assets = staging / "assets"
    assets.mkdir()
    (assets / "report.css").write_text(stylesheet, encoding="utf-8")


def _require_run_template() -> None:
    """Fail publication early when the shared run-page resource is unavailable."""
    resources.read_resource(resources.RUN_TEMPLATE)


def _write_pages(
    runs: tuple[RenderedRun, ...],
    staging: Path,
    omissions: list[OmittedInput],
    *,
    report_version: str,
    incomplete: bool,
) -> tuple[RenderedRun, ...]:
    surviving = []
    for run in runs:
        run_directory = staging / "runs" / run.artifact_sha256
        try:
            write_run_page(
                run.artifact,
                run_directory / "index.html",
                title=_title(run),
                report_version=report_version,
                site=SiteContext("../../index.html", incomplete=incomplete),
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
    report_version: str,
) -> None:
    template = Template(resources.read_resource(resources.INDEX_TEMPLATE))
    page = template.substitute(_index_values(runs, omissions, report_version))
    (staging / "index.html").write_text(page, encoding="utf-8")


def _index_values(
    runs: tuple[RenderedRun, ...],
    omissions: tuple[OmittedInput, ...],
    report_version: str,
) -> dict[str, str]:
    requested = sum(len(run.input_names) for run in runs) + len(omissions)
    duplicates = requested - len(omissions) - len(runs)
    successful_inputs = sum(len(run.input_names) for run in runs)
    status = _status(successful_inputs, len(omissions))
    return {
        "summary": _text(
            f"{requested} requested input(s); {len(runs)} distinct run report(s); "
            f"{duplicates} duplicate input(s); {len(omissions)} omitted input(s)."
        ),
        "idblock": _index_idblock(report_version, len(runs), status),
        "tiles": _index_tiles(requested, len(runs), duplicates, len(omissions)),
        "site_status": _site_status_message(omissions),
        "runs": _run_inventory(runs),
        "omissions": _omission_inventory(omissions),
        "version": _text(report_version),
    }


def _index_idblock(report_version: str, run_count: int, status: SiteStatus) -> str:
    rows: tuple[tuple[str, object], ...] = (
        ("Report version", report_version),
        ("Run reports", run_count),
        ("Status", status.value.capitalize()),
    )
    return "\n".join(
        f"<div><dt>{_text(label)}</dt><dd>{_text(value)}</dd></div>"
        for label, value in rows
    )


def _index_tiles(requested: int, runs: int, duplicates: int, omitted: int) -> str:
    note = (
        '<span class="n"><span class="pill warn">incomplete</span></span>'
        if omitted
        else ""
    )
    tiles = (
        ("Requested inputs", requested, ""),
        ("Distinct run reports", runs, ""),
        ("Duplicate inputs", duplicates, ""),
        ("Omitted inputs", omitted, note),
    )
    return "\n".join(
        f'<div class="tile"><span class="k">{_text(label)}</span>'
        f'<span class="v num">{value}</span>{extra}</div>'
        for label, value, extra in tiles
    )


def _run_inventory(runs: tuple[RenderedRun, ...]) -> str:
    if not runs:
        return '<p class="note">No run reports were rendered.</p>'
    header_cells = "".join(
        f'<th scope="col" class="num">{_text(doc.label)}</th>'
        for doc in _HEADLINE_METRICS
    )
    rows = "\n".join(_run_row(run) for run in runs)
    return (
        '<div class="tablewrap"><table class="runs"><thead><tr>'
        '<th scope="col">Run</th><th scope="col">Acquired</th>'
        '<th scope="col">Scanner</th>'
        f"{header_cells}"
        '<th scope="col">Requested inputs</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


def _run_row(run: RenderedRun) -> str:
    measurements = run.artifact.measurements
    provenance = run.artifact.provenance
    metric_cells = "".join(
        f'<td class="num">{_text(_headline_value(doc, measurements))}</td>'
        for doc in _HEADLINE_METRICS
    )
    names = ", ".join(Path(name).name for name in run.input_names)
    href = f"runs/{_text(run.artifact_sha256)}/index.html"
    return (
        '<tr><th scope="row">'
        f'<a href="{href}">{_text(_title(run))}</a>'
        f"</th><td>{_text(provenance.datetime or 'Unknown')}</td>"
        f"<td>{_text(device_line(provenance) or 'Unknown')}</td>"
        f"{metric_cells}"
        f"<td>{_text(names)}</td></tr>"
    )


def _headline_value(doc: MetricDoc, measurements: Measurements) -> str:
    value = doc.value(measurements)
    return doc.fmt(measurements) if math.isfinite(value) else "—"


def _omission_inventory(omissions: tuple[OmittedInput, ...]) -> str:
    if not omissions:
        return '<p class="note">No requested inputs were omitted.</p>'
    rows = "\n".join(
        f'<tr><th scope="row">{_text(Path(item.input_name).name)}</th>'
        f"<td>{_text(item.reason)}</td></tr>"
        for item in omissions
    )
    return (
        '<div class="tablewrap"><table class="runs">'
        '<thead><tr><th scope="col">Input</th><th scope="col">Reason</th></tr></thead>'
        f"<tbody>{rows}</tbody></table></div>"
    )


def _title(run: RenderedRun) -> str:
    return run.artifact.provenance.scan or Path(run.input_names[0]).name


def _site_status_message(omissions: tuple[OmittedInput, ...]) -> str:
    if not omissions:
        return ""
    return (
        '<p class="note alert"><span class="pill warn">Incomplete</span> '
        "<strong>Site incomplete.</strong> One or more requested inputs were not "
        "rendered.</p>"
    )


def _status(successful_inputs: int, omitted_count: int) -> SiteStatus:
    if successful_inputs == 0:
        return SiteStatus.FAILED
    if omitted_count:
        return SiteStatus.INCOMPLETE
    return SiteStatus.COMPLETE


def _text(value: object) -> str:
    return html.escape(str(value), quote=True)
