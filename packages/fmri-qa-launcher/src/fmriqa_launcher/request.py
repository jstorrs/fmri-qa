"""The one typed request a run is built from, and how a form's raw text becomes one.

`RunRequest` is the launcher's parse-don't-validate boundary. Every field of
one is known good, so `session.run_session` re-checks nothing before spending
eight seconds per series on it. `FormValues` holds the raw strings from the
form's widgets, and `parse_form` turns them into a `RunRequest`. It collects
every problem instead of stopping at the first, so a panel can show them all
at once.

The label and help constants are shared by `cli` (`help=`) and `panel` (field
labels), so the CLI's `--help` and the panel agree.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from fmriqa.convert.dcm2niix import DEFAULT_ANONYMIZE
from fmriqa.exceptions import InvalidScanError
from fmriqa.settings import AnalysisSettings
from fmriqa.types import (
    ANONYMIZE_MODES,
    DETREND_METHODS,
    ROI_CENTER_MODES,
    Anonymize,
    DetrendMethod,
    RoiCenter,
)

from .exceptions import RequestError

__all__ = [
    "ANONYMIZE_CHOICES",
    "ANONYMIZE_HELP",
    "ANONYMIZE_LABEL",
    "CENTER_CHOICES",
    "CENTER_HELP",
    "CENTER_LABEL",
    "DEFAULT_ANONYMIZE",
    "DEFAULT_SETTINGS",
    "DETREND_CHOICES",
    "DETREND_HELP",
    "DETREND_LABEL",
    "DICOM_DIR_HELP",
    "DICOM_DIR_LABEL",
    "DICOM_DIR_PANEL_LABEL",
    "OPEN_REPORT_HELP",
    "OPEN_REPORT_LABEL",
    "OUTPUT_DIR_HELP",
    "OUTPUT_DIR_LABEL",
    "OUTPUT_DIR_PANEL_LABEL",
    "ROI_SIZE_HELP",
    "ROI_SIZE_LABEL",
    "TRIM_SEC_HELP",
    "TRIM_SEC_LABEL",
    "FormValues",
    "RunRequest",
    "parse_form",
]

# `fmriqa`'s own defaults. Every default a form shows and every domain it
# checks comes from this one instance.
#: The `~fmriqa.AnalysisSettings` defaults every form shows and validates against.
DEFAULT_SETTINGS: AnalysisSettings = AnalysisSettings()

# Aliases of `fmriqa`'s closed option sets. `anonymize` has no `FormValues`
# field (the panel can't ask for it), but `--anonymize` needs its domain and
# wording here too.
#: Detrend methods the form offers.
DETREND_CHOICES: tuple[DetrendMethod, ...] = DETREND_METHODS
#: ROI centering modes the form offers.
CENTER_CHOICES: tuple[RoiCenter, ...] = ROI_CENTER_MODES
#: Anonymization levels the ``--anonymize`` flag offers.
ANONYMIZE_CHOICES: tuple[Anonymize, ...] = ANONYMIZE_MODES

#: Label of the DICOM directory field in the CLI and in problem messages.
DICOM_DIR_LABEL = "DICOM directory"
#: Help text of the DICOM directory field.
DICOM_DIR_HELP = "Directory of DICOM files (searched recursively)."
# The panel says "folder", as its Browse dialogs do. `DICOM_DIR_LABEL` stays
# "directory" because the CLI help and `parse_form`'s problem messages use it,
# and the panel shows those messages verbatim.
#: Label of the DICOM directory field in the panel.
DICOM_DIR_PANEL_LABEL = "DICOM folder"

#: Label of the output directory field in the CLI and in problem messages.
OUTPUT_DIR_LABEL = "Output directory"
#: Help text of the output directory field.
OUTPUT_DIR_HELP = (
    "Where to write one folder per series -- the converted scan, its sidecar, "
    "the QA artifact, and the report. Created if missing; an existing series "
    "folder is never overwritten."
)
#: Label of the output directory field in the panel.
OUTPUT_DIR_PANEL_LABEL = "Output folder"

#: Label of the trim field.
TRIM_SEC_LABEL = "Trim"
#: Help text of the trim field.
TRIM_SEC_HELP = (
    "Seconds of initial (non-steady-state) volumes to drop (default: "
    f"{DEFAULT_SETTINGS.trim_sec:g})."
)

#: Label of the detrend method field.
DETREND_LABEL = "Detrend method"
#: Help text of the detrend method field.
DETREND_HELP = f"Detrending method (default: {DEFAULT_SETTINGS.detrend})."

#: Label of the ROI center field.
CENTER_LABEL = "ROI center"
#: Help text of the ROI center field.
CENTER_HELP = (
    "Slice + ROI localization: 'image' (middle slice + image center, Glover) "
    f"or 'phantom' (largest slice + detected center). Default: "
    f"{DEFAULT_SETTINGS.center}."
)

#: Label of the ROI size field.
ROI_SIZE_LABEL = "ROI size"
#: Help text of the ROI size field.
ROI_SIZE_HELP = (
    f"Fixed summary/Weisskoff ROI side in voxels (default: "
    f"{DEFAULT_SETTINGS.roi_size})."
)

#: Label of the anonymize field.
ANONYMIZE_LABEL = "Anonymize"
#: Help text of the anonymize field.
ANONYMIZE_HELP = (
    "Sidecar content: 'pii' strips the patient and keeps the dates (default, "
    "and what 'qa' names need), 'all' strips the dates too, 'none' keeps "
    "everything."
)

#: Label of the open-the-report checkbox.
OPEN_REPORT_LABEL = "Open the report when done"
#: Help text of the open-the-report checkbox.
OPEN_REPORT_HELP = (
    "Open the report in a browser once the run finishes -- the one report, if "
    "exactly one series was published, else the output folder (a browser can "
    "list the series folders)."
)


def _choices(choices: tuple[str, ...]) -> str:
    """Join `choices` with commas for a "must be one of ..." problem message."""
    return ", ".join(choices)


def _directory_problems(dicom_dir: Path, output_dir: Path) -> list[str]:
    """List directory problems for an already-normalized pair of paths.

    Both paths must already have been through `expanduser()` and `resolve()`.
    `RunRequest.__post_init__` calls this; `parse_form` reaches it through a
    `RunRequest`, so a bad float doesn't hide a directory problem.
    """
    problems: list[str] = []
    if not dicom_dir.is_dir():
        problems.append(f"{DICOM_DIR_LABEL}: {dicom_dir} is not an existing directory")
    if output_dir == dicom_dir:
        problems.append(
            f"{OUTPUT_DIR_LABEL} must not be the same directory as the "
            f"{DICOM_DIR_LABEL} ({output_dir})"
        )
    elif output_dir.exists() and not output_dir.is_dir():
        problems.append(
            f"{OUTPUT_DIR_LABEL}: {output_dir} exists and is not a directory"
        )
    return problems


@dataclass(frozen=True, slots=True)
class RunRequest:
    """Everything one run needs, past its own directory and anonymize checks.

    Build one directly or through `parse_form`. `session.run_session` checks
    none of this again. `dcm2niix` is not checked here: a missing or
    non-executable one surfaces when `run_session` runs it, as a `SessionError`
    (`find_dcm2niix`'s complaint, by way of `fmriqa.import_dicom`). `settings`
    and `anonymize` default to `fmriqa`'s own defaults.
    """

    dicom_dir: Path
    output_dir: Path
    settings: AnalysisSettings = DEFAULT_SETTINGS
    anonymize: Anonymize = DEFAULT_ANONYMIZE
    # The converter as the user named it; None = bundled, else PATH. A string
    # because `Path("./dcm2niix")` drops the `./` that tells `find_dcm2niix`
    # to run that file instead of searching PATH.
    dcm2niix: str | None = None
    open_report: bool = False

    def __post_init__(self) -> None:
        """Resolve paths, then refuse unusable directories or an unknown `anonymize`."""
        # `resolve()` collapses `.`/`..` and follows symlinks, so the
        # same-directory check below can compare with `==`.
        object.__setattr__(self, "dicom_dir", self.dicom_dir.expanduser().resolve())
        object.__setattr__(self, "output_dir", self.output_dir.expanduser().resolve())
        if self.dcm2niix is not None:
            # Only the tilde: anchoring a bare name at the current directory
            # would stop `find_dcm2niix` searching PATH. Expand the string,
            # since a round trip through Path drops a `./`.
            expanded = os.path.expanduser(self.dcm2niix)  # noqa: PTH111  (keeps ./)
            object.__setattr__(self, "dcm2niix", expanded)

        problems = _directory_problems(self.dicom_dir, self.output_dir)
        if self.anonymize not in ANONYMIZE_CHOICES:
            problems.append(
                f"{ANONYMIZE_LABEL} must be one of {_choices(ANONYMIZE_CHOICES)}; "
                f"got {self.anonymize!r}"
            )
        if problems:
            raise RequestError(problems)


@dataclass(frozen=True, slots=True)
class FormValues:
    """Raw text as a widget holds it, not yet parsed."""

    dicom_dir: str = ""
    output_dir: str = ""
    trim_sec: str = f"{DEFAULT_SETTINGS.trim_sec:g}"
    detrend: str = DEFAULT_SETTINGS.detrend
    center: str = DEFAULT_SETTINGS.center
    roi_size: str = str(DEFAULT_SETTINGS.roi_size)
    open_report: bool = False


def _require_path(text: str, label: str, problems: list[str]) -> Path | None:
    """Strip `text` into a `Path`, or return None with a problem if it is blank.

    Only surrounding whitespace is stripped here. `RunRequest.__post_init__`
    handles `~` and relative paths, so directly built requests (as in the CLI)
    get the same treatment.
    """
    stripped = text.strip()
    if not stripped:
        problems.append(f"{label} is required")
        return None
    return Path(stripped)


def _parse_trim_sec(text: str, problems: list[str]) -> float | None:
    try:
        return float(text)
    except ValueError:
        problems.append(f"{TRIM_SEC_LABEL} must be a number of seconds, got {text!r}")
        return None


def _parse_roi_size(text: str, problems: list[str]) -> int | None:
    try:
        return int(text)
    except ValueError:
        problems.append(
            f"{ROI_SIZE_LABEL} must be a whole number of voxels, got {text!r}"
        )
        return None


def _parse_detrend(text: str, problems: list[str]) -> DetrendMethod | None:
    if text not in DETREND_CHOICES:
        problems.append(
            f"{DETREND_LABEL} must be one of {_choices(DETREND_CHOICES)}; got {text!r}"
        )
        return None
    return text


def _parse_center(text: str, problems: list[str]) -> RoiCenter | None:
    if text not in CENTER_CHOICES:
        problems.append(
            f"{CENTER_LABEL} must be one of {_choices(CENTER_CHOICES)}; got {text!r}"
        )
        return None
    return text


def _translate_settings_problem(exc: InvalidScanError) -> str:
    """Reword what `AnalysisSettings` refused in plain language.

    `exc.field` names the failed constructor argument. A form can only reach
    `trim_sec` and `roi_size`; the fallback covers any other `InvalidScanError`.
    """
    if exc.field == "trim_sec":
        return f"{TRIM_SEC_LABEL} must be zero seconds or more; got {exc.value!r}"
    if exc.field == "roi_size":
        return f"{ROI_SIZE_LABEL} must be a positive whole number; got {exc.value!r}"
    return str(exc)


def _build_settings(
    trim_sec: float | None,
    detrend: DetrendMethod | None,
    center: RoiCenter | None,
    roi_size: int | None,
    problems: list[str],
) -> AnalysisSettings | None:
    """Build `AnalysisSettings` from converted values, or None with a problem.

    None if an earlier conversion failed or `AnalysisSettings.__post_init__`
    refuses the combination.
    """
    if trim_sec is None or detrend is None or center is None or roi_size is None:
        return None
    try:
        return AnalysisSettings(
            trim_sec=trim_sec, detrend=detrend, center=center, roi_size=roi_size
        )
    except InvalidScanError as exc:
        problems.append(_translate_settings_problem(exc))
        return None


def parse_form(values: FormValues) -> RunRequest:
    """Convert a form's raw text into a `RunRequest`, or raise every problem at once.

    Every field is converted independently, so a bad float does not stop the
    choice fields from being checked. `RunRequest`'s directory and anonymize
    checks also run, against `DEFAULT_SETTINGS` if the settings fields could
    not be converted. The `RunRequest` built for those checks is returned when
    nothing else went wrong.

    Raises
    ------
    RequestError
        If anything above was wrong. `problems` lists every reason found.
    """
    problems: list[str] = []
    dicom_dir = _require_path(values.dicom_dir, DICOM_DIR_LABEL, problems)
    output_dir = _require_path(values.output_dir, OUTPUT_DIR_LABEL, problems)
    trim_sec = _parse_trim_sec(values.trim_sec, problems)
    detrend = _parse_detrend(values.detrend, problems)
    center = _parse_center(values.center, problems)
    roi_size = _parse_roi_size(values.roi_size, problems)
    settings = _build_settings(trim_sec, detrend, center, roi_size, problems)

    if dicom_dir is not None and output_dir is not None:
        try:
            request = RunRequest(
                dicom_dir=dicom_dir,
                output_dir=output_dir,
                settings=settings if settings is not None else DEFAULT_SETTINGS,
                open_report=values.open_report,
            )
        except RequestError as exc:
            problems.extend(exc.problems)
        else:
            if not problems:
                return request

    raise RequestError(problems)
