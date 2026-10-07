"""The application shell over fmri-qa: DICOM directory in, report directory out.

This package is the one-step pipeline built on top of the calculation half
(`fmriqc`) and the presentation half (`fmriqc_report`) — a command line
(`fmri-qa-run`) and a desktop panel (`fmri-qa-panel`) that turn a DICOM
directory into one report directory per series without asking the caller to
wire the two libraries together itself.

* `exceptions`  -- the hierarchy: `RequestError` for a bad request, `SessionError`
  for a run that could not happen at all, `PanelUnavailableError` for a panel
  with no display to attach to
* `progress`    -- `Stage`/`Progress`/`describe`: what to show while a run works
* `request`     -- `RunRequest`/`FormValues`/`parse_form`: the parse-don't-validate
  boundary a form's raw text crosses to become something `run_session` trusts
* `outcome`     -- `Published`/`Refused`/`Failed`/`SeriesOutcome`/`RunResult`:
  what a run reports, with no dependencies beyond the standard library
* `session`     -- `run_session`: the functional core itself
* `results`     -- `open_results`: where to look at a finished run
* `worker`      -- `BackgroundRun`: `run_session` on its own thread, polled
  through typed `Progress`/`Finished`/`Crashed` events
* `panel_state` -- the desktop panel's pure decisions (`bar_state`,
  `summarize`, `stopping_message`, `exit_code`, ...), kept apart from
  `panel` so they are testable without a display
* `panel`       -- `Panel`/`run_panel`/`main`: the desktop panel itself, the
  only module here that imports `tkinter`
* `cli`         -- `main`: the `fmri-qa-run` command line
* `version`     -- the installed distribution's version

`exceptions`, `outcome`, `progress` and `version` are cheap leaves -- none of them
imports `fmriqc` or `fmriqc_report` at all -- so they stay eager. `request`
imports `fmriqc.settings`/`fmriqc.types` for `AnalysisSettings` and its option
Literals, which pulls in numpy -- so anything that reaches far enough to build
a command line's `--help` already pays for numpy, as `fmri-qa --help` does
today. What stays lazy is `session`'s much heavier stack: the rest of
`fmriqc`'s analysis pipeline and `fmriqc_report`'s HTML renderer bring in
scipy, scikit-image and matplotlib too (roughly 1.8 s against `request`'s
0.15 s). `run_session` sits behind `__getattr__` below (PEP 562), so reaching
only as far as `parse_form` never pays for it. The label/help constants and
`DEFAULT_SETTINGS` are not re-exported here at all -- see `__all__` below.
"""

import logging
from typing import TYPE_CHECKING

from .exceptions import LauncherError, RequestError, SessionError
from .outcome import Failed, Published, Refused, RunResult, SeriesOutcome
from .progress import Progress, ProgressCallback, Stage, describe
from .request import FormValues, RunRequest, parse_form
from .version import launcher_version

if TYPE_CHECKING:
    # For type checkers only; at runtime `__getattr__` imports it on demand.
    from .session import run_session

# A library configures no handlers of its own (see style/logging.md).
logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "Failed",
    "FormValues",
    "LauncherError",
    "Progress",
    "ProgressCallback",
    "Published",
    "Refused",
    "RequestError",
    "RunRequest",
    "RunResult",
    "SeriesOutcome",
    "SessionError",
    "Stage",
    "describe",
    "launcher_version",
    "parse_form",
    "run_session",
]


def __getattr__(name: str) -> object:
    """Import `run_session` on first access: `.session` is the heavy module."""
    if name == "run_session":
        from .session import run_session

        return run_session
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """List the public names, matching what an eager module would show."""
    return sorted(__all__)
