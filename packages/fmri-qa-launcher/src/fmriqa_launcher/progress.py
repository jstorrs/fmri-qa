"""What stage a run is in, and the one line a shell can show for it.

A leaf module with no `fmriqa`/`fmriqa_report` import, so it is free to keep
eager in `__init__` (see that module's docstring). `Progress` is a plain value
handed to a caller's callback; `session.run_session` never decides how to
display it.
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
    """One point in a run: which stage, and, past import, which series.

    `index`/`total` are 1-based and count the series a run attempts. A series
    refused up front because its name already exists in the output directory is
    not counted (see `session.run_session`). Both stay 0 during `IMPORT`, which
    is one step for the whole DICOM directory before dcm2niix reports a count.
    """

    stage: Stage
    index: int = 0
    total: int = 0
    series: str = ""


def describe(progress: Progress) -> str:
    """Describe `progress` as a one-line, human-readable summary.

    Import names no series yet, so its line differs from the other three,
    which share an "N of M: name" shape.
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
