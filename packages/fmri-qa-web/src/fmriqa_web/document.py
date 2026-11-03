"""What the page checks itself against, and the `--json` envelope it writes."""

from collections.abc import Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version

from fmriqa import AnalysisSettings
from fmriqa.analysis.record import JSON_SCHEMA_VERSION, record_document
from fmriqa.convert import dcm2niix

from .series import SeriesFailure, SeriesReport

__all__ = ["Recorded", "Unrecorded", "batch_document", "contract"]

_DISTRIBUTIONS = ("fmri-qa-core", "fmri-qa-io", "fmri-qa-report", "fmri-qa-web")


@dataclass(frozen=True, slots=True)
class Recorded:
    """What `batch_document` reads of a series that analyzed: its stem and record."""

    stem: str
    record: dict[str, object]


@dataclass(frozen=True, slots=True)
class Unrecorded:
    """What `batch_document` reads of a series that failed: its stem and reason."""

    stem: str
    reason: str


def batch_document(
    results: Sequence[SeriesReport | SeriesFailure | Recorded | Unrecorded],
    settings: AnalysisSettings | None = None,
) -> dict[str, object]:
    """Wrap a batch's results in the envelope `fmri-qa --json` writes.

    Every series is `requested`; reports give `scans`, failures `errors`, in
    the entry shape `fmriqa_cli.qa` writes. The scan and its source are both
    `<stem>.nii.gz`: the page has no path. `Recorded` and `Unrecorded` are
    the same two cases without what the envelope ignores (a page, warnings),
    for results that crossed a JSON boundary.

    `settings` (default `AnalysisSettings()`) is only echoed into the
    envelope's `config`. It must be the settings the records were computed
    under; nothing here checks that.
    """
    scans = [r.record for r in results if isinstance(r, SeriesReport | Recorded)]
    errors = [
        {"scan": f"{r.stem}.nii.gz", "source": f"{r.stem}.nii.gz", "error": r.reason}
        for r in results
        if isinstance(r, SeriesFailure | Unrecorded)
    ]
    return record_document(
        settings if settings is not None else AnalysisSettings(),
        [f"{r.stem}.nii.gz" for r in results],
        scans,
        errors,
    )


def contract() -> dict[str, object]:
    """Return what the page must agree with Python on.

    The dcm2niix flags (the defaults `import_dicom` uses) the WASM converter
    must run with, the `--json` schema version, and the installed version of
    each distribution ("unknown" from a bare source tree).
    """
    return {
        "dcm2niix_flags": dcm2niix.flags(),
        "json_schema_version": JSON_SCHEMA_VERSION,
        "versions": {name: _version(name) for name in _DISTRIBUTIONS},
    }


def _version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unknown"
