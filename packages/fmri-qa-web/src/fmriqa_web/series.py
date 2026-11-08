"""Analyze one converted series from bytes, and render its report page.

The page hands over a NIfTI's bytes and its sidecar's and gets back a
`SeriesReport` or a `SeriesFailure`. One series' failure is a value, so a batch
carries on past it, as `fmriqa_launcher.session` does. This mirrors the
launcher's `_publish_series` without its files.
"""

import warnings
from dataclasses import dataclass
from typing import Literal

import fmriqa
from fmriqa import AnalysisSettings
from fmriqa.analysis.record import metric_record
from fmriqa_io.decode import scan_from_bytes
from fmriqa_report.formats.html.run import render_run_page

__all__ = ["SeriesFailure", "SeriesReport", "Stage", "analyze_series"]

type Stage = Literal["decode", "analyze", "render"]


@dataclass(frozen=True, slots=True)
class SeriesReport:
    """A series that analyzed and rendered.

    `html` is the complete report page. `record` is `metric_record` of the
    analysis file, already free of non-finite floats, so it is strict JSON. The
    analysis file itself is not kept: the page has no use for it and it is large.
    `warnings` is the text of every warning decode and analysis raised.
    """

    stem: str
    html: str
    record: dict[str, object]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SeriesFailure:
    """A series that failed at `stage`, with `reason` (`str(exc)`, or its type name)."""

    stem: str
    stage: Stage
    reason: str
    warnings: tuple[str, ...]


def analyze_series(
    nifti: bytes,
    sidecar: bytes | None,
    *,
    stem: str,
    settings: AnalysisSettings | None = None,
) -> SeriesReport | SeriesFailure:
    """Decode, analyze and render one series; a failure is returned, not raised.

    `stem` names the series: the scan is `<stem>.nii.gz` and its sidecar
    `<stem>.json` in warnings, errors, provenance and the page title.
    `sidecar` is None when the series has none. `settings` defaults to
    `AnalysisSettings()`.

    Only decoding and analyzing run under a recording `simplefilter("always")`,
    as in the launcher and `fmriqa_cli.qa`: it revives warnings a library
    silences on purpose, so rendering under it would present, say,
    matplotlib's notices as findings about the scan.
    `warnings.catch_warnings` is process-global, not thread-local.
    """
    scan_name = f"{stem}.nii.gz"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            scan = scan_from_bytes(
                nifti, sidecar, name=scan_name, sidecar_name=f"{stem}.json"
            )
        except Exception as exc:  # noqa: BLE001 - one series' failure, reported as a value
            return _failure(stem, "decode", exc, caught)
        try:
            analysis = fmriqa.analyze(scan, settings, name=scan_name, source=scan_name)
        except Exception as exc:  # noqa: BLE001 - one series' failure, reported as a value
            return _failure(stem, "analyze", exc, caught)
    noted = _messages(caught)

    try:
        html = render_run_page(analysis, title=stem)
    except Exception as exc:  # noqa: BLE001 - one series' failure, reported as a value
        return SeriesFailure(stem, "render", _reason(exc), noted)
    return SeriesReport(stem, html, metric_record(analysis), noted)


def _failure(
    stem: str, stage: Stage, exc: Exception, caught: list[warnings.WarningMessage]
) -> SeriesFailure:
    return SeriesFailure(stem, stage, _reason(exc), _messages(caught))


def _reason(exc: Exception) -> str:
    return str(exc) or type(exc).__name__


def _messages(caught: list[warnings.WarningMessage]) -> tuple[str, ...]:
    """Collect the text of every warning recorded by `catch_warnings`."""
    return tuple(str(w.message) for w in caught)
