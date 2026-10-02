"""Pure decisions the panel's widgets present -- no `tkinter` import at all.

`bar_state` turns a `Progress` into where the progress bar should sit;
`final_bar` turns a finished `RunResult` into where it should come to rest;
`summarize` turns a finished `RunResult` into the one-line headline and the
per-outcome detail lines a physicist reads; `stopping_message` turns "a close
was requested" into the one line that tells the truth about when it takes
effect; `exit_code` turns the run's terminal event into the process exit
code. Keeping all of these here, rather than in `panel.py`, is what lets them
be tested without a display: every `if` about *what happened* belongs in
this module, and `panel.py` is left with only *how to show it*.
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

    `maximum` is never 0: every constructor below (`bar_state`, `final_bar`,
    `CRASHED_BAR`) guarantees at least 1, which is what lets `panel.py` hand
    `maximum` straight to `ttk.Progressbar.configure` without a defensive
    `max(..., 1)` of its own.
    """

    value: int
    maximum: int


type BarState = Indeterminate | Determinate

# One series passes through three stages that mark visible progress --
# analyze, report, publish -- each worth one "tick" on the bar; import
# reports no series count yet, so it has no place on a determinate bar (see
# `bar_state`). Naming this a constant, rather than a bare `3`, is what makes
# `maximum = _TICKS_PER_SERIES * total` read as a rule instead of a number.
_TICKS_PER_SERIES = 3

# Where a stage's *own* line lands within a series' three ticks: analysis
# starting counts for nothing yet (offset 0 -- the tick it earns is credited
# once the report starts, i.e. once analysis is known to have finished),
# rendering starting means analysis is done (1 tick), and publishing starting
# means the report is done (2 ticks). The third tick -- reaching `total *
# _TICKS_PER_SERIES` -- is never reported by a stage at all: it is implied by
# the *next* series' ANALYZE, or, for the last series, never explicitly
# reached mid-run. `bar_state` special-cases PUBLISH on the last series to
# reach the maximum, so the bar completes exactly when the run does.
_STAGE_OFFSET: dict[Stage, int] = {
    Stage.ANALYZE: 0,
    Stage.REPORT: 1,
    Stage.PUBLISH: 2,
}

# Where the bar sits once a run has crashed before producing a `RunResult` at
# all: nothing is known to have completed reliably (a crash can strike mid
# series, after some but not all of its files were staged), so the honest
# answer is "empty" rather than guessing a partial fraction from wherever the
# last `Progress` happened to land.
CRASHED_BAR: BarState = Determinate(value=0, maximum=1)


def bar_state(progress: Progress) -> BarState:
    """Where the progress bar should sit for `progress`.

    Indeterminate for `Stage.IMPORT` -- dcm2niix has not yet said how many
    series there are, so there is nothing to be a fraction of. Otherwise
    determinate, out of `3 * progress.total` (three visible ticks per
    series: analyze, report, publish); `progress.index` is 1-based, so the
    series already completed contribute `3 * (index - 1)` ticks, plus the
    current stage's own offset. The bar reaches its maximum only once: on the
    last series' `PUBLISH` line, which is credited as if publishing were
    already done -- there is no later event in a successful run that could
    report the true `3 * total`, since publish is the last stage reported at
    all.
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
    """Where the bar should come to rest once a run has finished.

    Full when every series the run attempted was published. Otherwise the
    proportion of attempted series that were: `value` is how many published,
    `maximum` is how many were attempted (never 0 -- a run that attempted
    none at all rests on an empty bar, `Determinate(0, 1)`, rather than a
    bar with nothing to be a fraction of). This is a deliberate choice among
    several defensible ones (e.g. leaving the bar wherever the last
    `Progress` left it) -- proportion-published is what a physicist skimming
    the bar after stepping away actually wants to know: how much of the work
    that was attempted came out the other end.
    """
    total = len(result.outcomes)
    published = len(result.published)
    return Determinate(value=published, maximum=max(total, 1))


@dataclass(frozen=True, slots=True)
class Summary:
    """What to tell a physicist once a run has finished.

    `headline` is one line for the status label; `details` is one line per
    outcome (and per warning) for the log, in the order `RunResult.outcomes`
    found them; `offer_open` says whether an "open results" action makes
    sense at all.
    """

    headline: str
    details: tuple[str, ...]
    offer_open: bool


def _outcome_lines(result: RunResult) -> tuple[str, ...]:
    """One line per outcome, and per warning it carries, in outcome order."""
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
    """Whether `result` found series at all, and every one was refused."""
    return bool(result.outcomes) and all(
        isinstance(o, Refused) for o in result.outcomes
    )


def _headline(result: RunResult) -> str:
    """The one-line summary of `result` for the status label.

    A cancelled run never shows "N of M": `RunResult.outcomes` only holds the
    series a cancelled run actually reached (`session.run_session` breaks the
    loop on cancel rather than padding it out with the series never
    attempted), so a denominator here would silently claim the run only ever
    meant to do the ones it reached.
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
    """The finish summary a panel shows once a run has ended."""
    return Summary(
        headline=_headline(result),
        details=_outcome_lines(result),
        offer_open=bool(result.published),
    )


def stopping_message(last: Progress | None) -> str:
    """What the status line should say once closing has asked the run to stop.

    `should_continue` (see `session.run_session`) is only polled between
    series, never mid-import and never mid-series, so what "stopping" means
    depends on where the run currently is: before the first series is even
    known (`last` is None, or its stage is still `Stage.IMPORT`), there is no
    between-series checkpoint yet to stop *at* -- the truthful thing to say
    is that closing takes effect once import itself finishes. Once at least
    one series is under way, the ordinary "stops between series" wording
    applies. Either way, a second close request destroys the window
    immediately (see `panel.Panel._on_close`), which is worth saying so a
    physicist who does not want to wait is not left guessing.
    """
    if last is None or last.stage is Stage.IMPORT:
        return "Stopping once the import finishes... (close again to quit now)"
    return "Stopping after the current series... (close again to quit now)"


def exit_code(event: Finished | Crashed) -> int:
    """The process exit code for a run's terminal event.

    0 only for a `Finished` event whose `RunResult.complete` is true (every
    series found was published and nothing was cancelled); 1 for a `Crashed`
    event or an incomplete `Finished` one.
    """
    if isinstance(event, Crashed):
        return 1
    return 0 if event.result.complete else 1
