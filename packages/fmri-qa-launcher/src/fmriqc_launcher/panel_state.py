"""Pure decisions the panel's widgets present, with no `tkinter` import.

`bar_state` maps a `Progress` to a bar position and `final_bar` maps a
finished `RunResult` to the bar's resting position. `summarize` builds the
headline and per-outcome detail lines. `stopping_message` says when a close
request takes effect. `exit_code` maps the terminal event to a process exit
code. They live here so they can be tested without a display: every `if` about
what happened belongs here, and `panel.py` only decides how to show it.
"""

from dataclasses import dataclass

from .outcome import Published, Refused, RunResult
from .progress import Progress, Stage
from .worker import Crashed, Finished

__all__ = [
    "CRASHED_BAR",
    "BarState",
    "Determinate",
    "Indeterminate",
    "Summary",
    "bar_state",
    "exit_code",
    "final_bar",
    "stopping_message",
    "summarize",
]


@dataclass(frozen=True, slots=True)
class Indeterminate:
    """The bar should pulse: how many series there are is not known yet."""


@dataclass(frozen=True, slots=True)
class Determinate:
    """The bar should show `value` out of `maximum`.

    `maximum` is never 0: `bar_state`, `final_bar` and `CRASHED_BAR` all
    guarantee at least 1, so `panel.py` can pass it straight to
    `ttk.Progressbar.configure`.
    """

    value: int
    maximum: int


#: Where the progress bar sits: `Indeterminate` (pulsing) or `Determinate`.
type BarState = Indeterminate | Determinate

# Each series has three stages that mark progress (analyze, report, publish),
# one "tick" each. Import reports no series count, so it has no place on a
# determinate bar (see `bar_state`).
_TICKS_PER_SERIES = 3

# Where a stage's own line lands within a series' three ticks. A stage starting
# credits the previous one: ANALYZE 0, REPORT 1, PUBLISH 2. Nothing reports the
# third tick; the next series' ANALYZE implies it. `bar_state` special-cases
# PUBLISH on the last series to reach the maximum, so the bar completes when
# the run does.
_STAGE_OFFSET: dict[Stage, int] = {
    Stage.ANALYZE: 0,
    Stage.REPORT: 1,
    Stage.PUBLISH: 2,
}

# Where the bar sits after a crash before any `RunResult`. A crash can strike
# mid series with files staged, so the bar is empty rather than guessing a
# fraction from the last `Progress`.
#: Bar state after a crash that produced no `~fmriqc_launcher.RunResult`: empty.
CRASHED_BAR: BarState = Determinate(value=0, maximum=1)


def bar_state(progress: Progress) -> BarState:
    """Choose where the progress bar should sit for `progress`.

    Indeterminate for `Stage.IMPORT`, since dcm2niix has not yet said how many
    series there are. Otherwise determinate, out of `3 * progress.total`
    (three ticks per series). `progress.index` is 1-based, so completed series
    contribute `3 * (index - 1)` ticks plus the current stage's offset. The
    bar reaches its maximum on the last series' `PUBLISH` line, credited as if
    publishing were done, since no later event reports the true `3 * total`.
    """
    if progress.stage is Stage.IMPORT:
        return Indeterminate()
    maximum = max(_TICKS_PER_SERIES * progress.total, 1)
    is_last_publish = (
        progress.stage is Stage.PUBLISH and progress.index == progress.total
    )
    if is_last_publish:
        return Determinate(value=maximum, maximum=maximum)
    value = _TICKS_PER_SERIES * (progress.index - 1) + _STAGE_OFFSET[progress.stage]
    return Determinate(value=value, maximum=maximum)


def final_bar(result: RunResult) -> BarState:
    """Choose where the bar should come to rest once a run has finished.

    `value` is how many series were published and `maximum` is how many the
    run found, `Refused` ones included even though they are never attempted.
    So the bar is full only when every series was published. `maximum` is never
    0: a run that found none rests on an empty bar, `Determinate(0, 1)`. This is
    one choice among several defensible ones, such as leaving the bar where the
    last `Progress` put it. The proportion published is what someone glancing
    back at it wants to know.
    """
    total = len(result.outcomes)
    published = len(result.published)
    return Determinate(value=published, maximum=max(total, 1))


@dataclass(frozen=True, slots=True)
class Summary:
    """What to tell a physicist once a run has finished.

    `headline` is one line for the status label. `details` is one line per
    outcome (and per warning) for the log, in the order `RunResult.outcomes`
    lists them. `offer_open` says whether an "open results" action makes
    sense.
    """

    headline: str
    details: tuple[str, ...]
    offer_open: bool


def _outcome_lines(result: RunResult) -> tuple[str, ...]:
    """List one line per outcome, and per warning it carries, in outcome order."""
    lines: list[str] = []
    for outcome in result.outcomes:
        if isinstance(outcome, Published):
            lines.append(f"Published {outcome.name}")
            warnings = outcome.warnings
        elif isinstance(outcome, Refused):
            lines.append(
                f"Skipped {outcome.name}: results already exist in {outcome.existing}"
            )
            warnings = ()
        else:
            lines.append(f"Failed {outcome.name}: {outcome.reason}")
            warnings = outcome.warnings
        lines.extend(f"Warning ({outcome.name}): {warning}" for warning in warnings)
    return tuple(lines)


def _all_refused(result: RunResult) -> bool:
    """Return True if `result` found series and every one was refused."""
    return bool(result.outcomes) and all(
        isinstance(o, Refused) for o in result.outcomes
    )


def _headline(result: RunResult) -> str:
    """Summarize `result` in one line for the status label.

    A cancelled run never shows "N of M": `RunResult.outcomes` holds only the
    series it reached (`session.run_session` breaks the loop on cancel), so a
    denominator would imply the run meant to do only those.
    """
    published = len(result.published)
    if result.cancelled:
        if published == 0:
            return "Stopped early before anything was published"
        return f"Stopped early: {published} series published"
    if published > 0:
        return f"{published} of {len(result.outcomes)} series published"
    if _all_refused(result):
        return (
            f"All {len(result.outcomes)} series already have results "
            "in the output folder"
        )
    return "Nothing was published"


def summarize(result: RunResult) -> Summary:
    """Build the finish summary a panel shows once a run has ended."""
    return Summary(
        headline=_headline(result),
        details=_outcome_lines(result),
        offer_open=bool(result.published),
    )


def stopping_message(last: Progress | None) -> str:
    """Compose what the status line says once closing asks the run to stop.

    `should_continue` (see `session.run_session`) is polled only between
    series, never mid-import and never mid-series, so the wording depends on
    where the run is. Before the first series is known (`last` is None or
    still `Stage.IMPORT`) there is no checkpoint to stop at, so closing takes
    effect once import finishes. Once at least one series is under way, the
    ordinary "stops between series" wording applies. In both cases a second
    close request destroys the window immediately (see
    `panel.Panel._on_close`), and the message says so.
    """
    if last is None or last.stage is Stage.IMPORT:
        return "Stopping once the import finishes... (close again to quit now)"
    return "Stopping after the current series... (close again to quit now)"


def exit_code(event: Finished | Crashed) -> int:
    """Map a run's terminal event to the process exit code.

    0 only for a `Finished` event whose `RunResult.complete` is true; 1 for a
    `Crashed` event or an incomplete `Finished` one.
    """
    if isinstance(event, Crashed):
        return 1
    return 0 if event.result.complete else 1
