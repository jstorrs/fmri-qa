"""What stage a run is in, and the one line a shell can show for it.

A leaf module: no `fmriqc`/`fmriqc_report` import at all, so it costs nothing
to keep eager in `__init__` (see that module's docstring). `Progress` is a
plain value handed to a caller-supplied callback -- `session.run_session`
never decides how progress is displayed, only what happened.
"""

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import assert_never


class Stage(StrEnum):
    """The four steps one series passes through, in order."""

    IMPORT = "import"
    ANALYZE = "analyze"
    REPORT = "report"
    PUBLISH = "publish"


@dataclass(frozen=True, slots=True)
class Progress:
    """One point in a run: which stage, and — past import — which series.

    `index`/`total` are 1-based and count the series a run actually attempts
    (a series refused up front because its name already exists in the output
    directory never reaches analysis, so it is never counted here either —
    see `session.run_session`). Both stay 0 while `stage` is `IMPORT`: dcm2niix
    has not yet said how many series it found, and import is one step for the
    whole DICOM directory, not one per series.
    """

    stage: Stage
    index: int = 0
    total: int = 0
    series: str = ""


def describe(progress: Progress) -> str:
    """Describe `progress` as a one-line, human-readable summary.

    Import names no series -- there is none to name yet -- so its line reads
    differently from the other three, which all share one "N of M: name" shape.
    """
    match progress.stage:
        case Stage.IMPORT:
            return "Importing DICOM series"
        case Stage.ANALYZE:
            return f"Analyzing {progress.index} of {progress.total}: {progress.series}"
        case Stage.REPORT:
            return (
                f"Rendering report {progress.index} of {progress.total}: "
                f"{progress.series}"
            )
        case Stage.PUBLISH:
            return f"Publishing {progress.index} of {progress.total}: {progress.series}"
        case _:
            assert_never(progress.stage)


#: Callable that receives each `Progress` update as a run advances.
type ProgressCallback = Callable[[Progress], None]


@dataclass(frozen=True, slots=True)
class CleanupNotice:
    """A working directory left behind; `message` explains what to do with `path`."""

    path: Path
    message: str


type CleanupNoticeCallback = Callable[[CleanupNotice], None]
