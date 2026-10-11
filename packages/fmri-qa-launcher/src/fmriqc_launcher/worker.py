"""One run on its own thread, delivering typed events through a queue.

Only `panel.py` imports `tkinter`, so this module is testable headless.
`run_session` is imported inside the thread target, so importing this module
stays as cheap as importing `.request` or `.progress`.

The thread is non-daemon so `session._publish`'s `finally` can remove the
hidden `.partial` sibling on exit. Otherwise a partial scan stays in
`output_dir` and may be synced. That `finally` is the one that matters.
Staging is in the system temp directory, so losing the race to remove it
costs `output_dir` nothing.

A `Crashed` event is how any exception, expected or not, still reaches a
caller. Windowed builds have `sys.stderr` as `None`, so an error that only
reached a thread's default excepthook would be lost silently.
"""

import logging
import queue
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass

from .exceptions import LauncherError
from .outcome import RunResult
from .progress import CleanupNotice, CleanupNoticeCallback, Progress, ProgressCallback
from .request import RunRequest

__all__ = ["BackgroundRun", "Crashed", "Event", "Finished"]

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Finished:
    """The run completed (with or without cancellation) and produced `result`."""

    result: RunResult


@dataclass(frozen=True, slots=True)
class Crashed:
    """The run raised before it could produce a `RunResult`.

    `message` is plain text, safe to show a physicist as-is: the worded
    failure for a `LauncherError`, otherwise `"{type}: {exc}"`. `details` is
    the formatted traceback (empty for a `LauncherError`). It travels here
    because logging goes nowhere under `pythonw`'s silent `sys.stderr`; a panel
    can append it to its log for the physicist to pass to support.
    """

    message: str
    details: str = ""


#: Anything a background run posts to its queue.
type Event = Progress | CleanupNotice | Finished | Crashed

type _Runner = Callable[..., "RunResult"]


def _run_session(
    request: RunRequest,
    *,
    progress: ProgressCallback,
    notice: CleanupNoticeCallback,
    should_continue: Callable[[], bool],
) -> RunResult:
    """Run the real pipeline, imported once a run starts. See module docstring."""
    from .session import run_session

    return run_session(
        request, progress=progress, notice=notice, should_continue=should_continue
    )


class BackgroundRun:
    """One `run_session` call on its own thread, polled rather than awaited.

    `start()` launches a non-daemon thread that calls `run` (by default the
    real pipeline) with `progress=queue.put`, `notice=queue.put`, and a
    `should_continue` that `cancel()` controls. `poll()` drains arrived events
    without blocking. The thread always ends with exactly one terminal event,
    `Finished` or `Crashed`, so draining until one appears sees the whole run,
    including cleanup notices from exception unwinding.
    """

    def __init__(self, request: RunRequest, *, run: _Runner | None = None) -> None:
        self._request = request
        self._run: _Runner = run if run is not None else _run_session
        self._queue: queue.SimpleQueue[Event] = queue.SimpleQueue()
        self._cancelled = threading.Event()
        self._finished = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the run on a new non-daemon thread.

        Raises
        ------
        RuntimeError
            If called more than once, since a second call would run the
            pipeline twice concurrently against the same request.
        """
        if self._thread is not None:
            raise RuntimeError("BackgroundRun.start() called more than once")
        self._thread = threading.Thread(target=self._target, daemon=False)
        self._thread.start()

    def _target(self) -> None:
        try:
            result = self._run(
                self._request,
                progress=self._queue.put,
                notice=self._queue.put,
                should_continue=lambda: not self._cancelled.is_set(),
            )
        except LauncherError as exc:
            self._queue.put(Crashed(str(exc)))
        except BaseException as exc:
            # Catch SystemExit and KeyboardInterrupt too: every exit must
            # queue exactly one terminal event. Re-raise so the thread exits
            # as it would without this handler.
            _LOG.exception("background run crashed")
            details = "".join(traceback.format_exception(exc))
            self._queue.put(Crashed(f"{type(exc).__name__}: {exc}", details))
            raise
        else:
            self._queue.put(Finished(result))
        finally:
            self._finished.set()

    def poll(self) -> tuple[Event, ...]:
        """Drain every event that has arrived since the last call, without blocking."""
        events: list[Event] = []
        while True:
            try:
                events.append(self._queue.get_nowait())
            except queue.Empty:
                return tuple(events)

    def cancel(self) -> None:
        """Ask the run to stop at the next between-series checkpoint."""
        self._cancelled.set()

    def join(self, timeout: float | None = None) -> None:
        """Block until the terminal event has been put, or `timeout` elapses."""
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def running(self) -> bool:
        """True from `start()` until the terminal event has been put."""
        return self._thread is not None and not self._finished.is_set()
