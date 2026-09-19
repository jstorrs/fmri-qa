"""The one typed request a run is built from, and how a form's raw text becomes one.

`RunRequest` is the parse-don't-validate boundary for the whole launcher: build
one and every field is already known good, so `session.run_session` re-checks
nothing before spending eight seconds per series on it. `FormValues` is the
other side of that boundary -- exactly the strings a text field or a dropdown
holds, before anything has looked at them -- and `parse_form` is the one
function that turns one into the other, collecting every problem it finds
rather than stopping at the first, so a panel can show a physicist everything
wrong with a submission at once.

The label/help constants defined alongside each option are read by two things
that do not exist yet: an `argparse` flag (`help=`) and a `tkinter` widget (its
label). Defining the wording once here, next to the domain it describes, is
what keeps a future CLI's `--help` and a future panel's field labels saying the
same thing.
"""

from dataclasses import dataclass
from pathlib import Path

from fmriqc.exceptions import InvalidScanError
from fmriqc.settings import AnalysisSettings
from fmriqc.types import (
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
    "DEFAULT_SETTINGS",
    "DETREND_CHOICES",
    "DETREND_HELP",
    "DETREND_LABEL",
    "DICOM_DIR_HELP",
    "DICOM_DIR_LABEL",
    "OPEN_REPORT_HELP",
    "OPEN_REPORT_LABEL",
    "OUTPUT_DIR_HELP",
    "OUTPUT_DIR_LABEL",
    "ROI_SIZE_HELP",
    "ROI_SIZE_LABEL",
    "TRIM_SEC_HELP",
    "TRIM_SEC_LABEL",
    "FormValues",
    "RunRequest",
    "parse_form",
]

# `fmriqc`'s own defaults, restated nowhere else: every default a form shows
# and every domain a form is checked against reads from this one instance.
DEFAULT_SETTINGS: AnalysisSettings = AnalysisSettings()

# Aliases of `fmriqc`'s closed option sets, under the names this form speaks.
# `anonymize` has no field on `FormValues` (the panel this run supports has no
# way to ask for it yet -- see the module docstring), but a later `argparse`
# flag needs its domain and wording now, in one place, same as the others.
DETREND_CHOICES: tuple[DetrendMethod, ...] = DETREND_METHODS
CENTER_CHOICES: tuple[RoiCenter, ...] = ROI_CENTER_MODES
ANONYMIZE_CHOICES: tuple[Anonymize, ...] = ANONYMIZE_MODES

DICOM_DIR_LABEL = "DICOM directory"
DICOM_DIR_HELP = "Directory of DICOM files (searched recursively)."

OUTPUT_DIR_LABEL = "Output directory"
OUTPUT_DIR_HELP = (
    "Where to write one folder per series -- the converted scan, its sidecar, "
    "the QA archive, and the report. Created if missing; an existing series "
    "folder is never overwritten."
)

TRIM_SEC_LABEL = "Trim"
TRIM_SEC_HELP = (
    "Seconds of initial (non-steady-state) volumes to drop (default: "
    f"{DEFAULT_SETTINGS.trim_sec:g})."
)

DETREND_LABEL = "Detrend method"
DETREND_HELP = f"Detrending method (default: {DEFAULT_SETTINGS.detrend})."

CENTER_LABEL = "ROI center"
CENTER_HELP = (
    "Slice + ROI localization: 'image' (middle slice + image center, Glover) "
    f"or 'phantom' (largest slice + detected center). Default: "
    f"{DEFAULT_SETTINGS.center}."
)

ROI_SIZE_LABEL = "ROI size"
ROI_SIZE_HELP = (
    f"Fixed summary/Weisskoff ROI side in voxels (default: "
    f"{DEFAULT_SETTINGS.roi_size})."
)

ANONYMIZE_LABEL = "Anonymize"
ANONYMIZE_HELP = (
    "Sidecar content: 'pii' strips the patient and keeps the dates (default, "
    "and what 'qa' names need), 'all' strips the dates too, 'none' keeps "
    "everything."
)

OPEN_REPORT_LABEL = "Open report when done"
OPEN_REPORT_HELP = "Open the last series' report in a browser once the run finishes."


def _choices(choices: tuple[str, ...]) -> str:
    """Choices, comma-joined, for a "must be one of ..." problem message."""
    return ", ".join(choices)


def _directory_problems(dicom_dir: Path, output_dir: Path) -> list[str]:
    """Directory-existence and same-directory problems for an already-normalized pair.

    Pure over `dicom_dir`/`output_dir` once each has been through
    `expanduser()`/`resolve()`: `RunRequest.__post_init__` calls this after
    normalizing its own fields, and `parse_form` calls it the same way (via a
    `RunRequest` it builds for exactly this check) so a submission with a bad
    float still reports a directory problem alongside it, not instead of it.
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

    Built either directly or through `parse_form`; `session.run_session` takes
    one and checks none of this again. `dcm2niix` is not checked here even
    when given -- a nonexistent or non-executable one only surfaces once
    `run_session` tries to run it, as a `SessionError` (`find_dcm2niix`'s own
    complaint, by way of `fmriqc.import_dicom`). `settings` and `anonymize`
    default to `fmriqc`'s own defaults, restated nowhere else.
    """

    dicom_dir: Path
    output_dir: Path
    settings: AnalysisSettings = DEFAULT_SETTINGS
    anonymize: Anonymize = "pii"
    dcm2niix: Path | None = None  # a specific converter; None = bundled, else PATH
    open_report: bool = False

    def __post_init__(self) -> None:
        # `resolve()` rather than `absolute()`: both anchor a relative path at
        # the current directory, but only `resolve()` also collapses `.`/`..`
        # and follows symlinks, which is what lets the same-directory check
        # below compare two different spellings of one path with a plain
        # `==` instead of resolving both sides again itself.
        object.__setattr__(self, "dicom_dir", self.dicom_dir.expanduser().resolve())
        object.__setattr__(self, "output_dir", self.output_dir.expanduser().resolve())
        if self.dcm2niix is not None:
            # Only the tilde: `find_dcm2niix` looks a bare name up on PATH, and
            # anchoring it at the current directory would defeat that.
            object.__setattr__(self, "dcm2niix", self.dcm2niix.expanduser())

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
    """Raw text, exactly as a widget holds it -- nothing here is parsed yet."""

    dicom_dir: str = ""
    output_dir: str = ""
    trim_sec: str = f"{DEFAULT_SETTINGS.trim_sec:g}"
    detrend: str = DEFAULT_SETTINGS.detrend
    center: str = DEFAULT_SETTINGS.center
    roi_size: str = str(DEFAULT_SETTINGS.roi_size)
    open_report: bool = False


def _require_path(text: str, label: str, problems: list[str]) -> Path | None:
    """`text`, stripped, as a `Path`, or None with a problem appended if that's blank.

    Only the whitespace a form field routinely picks up from a paste or a
    trailing space is stripped here; `~` and relative-path normalization are
    `RunRequest.__post_init__`'s job, so a directly constructed request (the
    argparse front end will build one that way) gets the same treatment.
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
    """A plain-language rewording of what `AnalysisSettings` refused.

    `exc.field` names the constructor argument that failed; `trim_sec` and
    `roi_size` are the only two a form built from `FormValues` can ever
    reach (the third, `detrend_order`, is never set from a form), but the
    fallback keeps this total over whatever `InvalidScanError` might carry.
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
    """`AnalysisSettings` from already-converted values, or None with a problem.

    None whenever a conversion upstream already failed (nothing to build from)
    or `AnalysisSettings.__post_init__` itself refuses the combination.
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

    Every field is converted independently -- a bad float does not stop the
    choice fields from being checked too -- and `RunRequest`'s own directory
    and anonymize checks run as well (against `DEFAULT_SETTINGS` when the
    settings fields could not be converted, just to reach that check), so a
    submission with several mistakes is reported with all of them, not just
    the first `parse_form` happens to notice. The `RunRequest` built to reach
    those checks is returned as-is when nothing else went wrong -- built once,
    not rebuilt identically for the return.

    Raises:
        RequestError: If anything above was wrong. `problems` lists every
            reason found.
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
