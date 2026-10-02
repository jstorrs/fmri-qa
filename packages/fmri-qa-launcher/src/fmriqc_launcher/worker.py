"""One run on its own thread, delivering typed events through a queue.

`panel.py` is the only module that ever knows about `tkinter`; this one does
not import it at all, so `BackgroundRun` and the pure `Event` types below are
fully unit-testable without a display. `run_session` itself is reached only
through `.session`, imported lazily inside the thread target rather than at
module top, so that importing `fmriqc_launcher.worker` stays as cheap as
importing `.request`/`.progress`.

The thread is non-daemon on purpose: a windowed build has no console for a
half-copied series to complain from, and `run_session` already promises
nothing partial is ever left in `output_dir` -- but only if it is allowed to
finish unwinding when the process is asked to exit. The `finally` that matters
is `session._publish`'s, which removes the hidden `.partial` sibling a series
is copied into before it is renamed into place; cut short, that is a partial
scan left in the user's output directory, and uploaded if it is a synced one.
(Staging itself is in the system's temporary directory, and losing the race to
remove that would cost `output_dir` nothing.) A `Crashed` event is how *any* exception,
expected or not, still reaches a caller that has no stderr of its own -- a
windowed executable's `sys.stderr` is `None`, so an error that only ever
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
from .progress import Progress, ProgressCallback
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

    `message` is plain text, safe to show a physicist as-is: for a
    `LauncherError` it already is one (an expected, worded failure), and for
    anything else it is `"{type}: {exc}"`. `details` is empty for a
    `LauncherError` -- there is nothing more useful to add -- and otherwise
    the formatted traceback, carried here (rather than only logged, which
    goes nowhere under `pythonw`'s silent `sys.stderr`) so a panel can append
    it to its log for a physicist to copy to whoever supports them.
    """

    message: str
    details: str = ""


type Event = Progress | Finished | Crashed

type _Runner = Callable[..., "RunResult"]


def _run_session(
    request: RunRequest,
    *,
    progress: ProgressCallback,
    should_continue: Callable[[], bool],
) -> RunResult:
    """The real pipeline, imported only once a run starts. See the module docstring."""
    from .session import run_session

    return run_session(request, progress=progress, should_continue=should_continue)


class BackgroundRun:
    """One `run_session` call on its own thread, polled rather than awaited.

    `start()` launches a non-daemon thread that calls `run` (by default the
    real pipeline) with `progress=queue.put` and a `should_continue` this
    object controls via `cancel()`. `poll()` drains whatever events have
    arrived since the last call without blocking; the thread always ends by
    putting exactly one terminal event, `Finished` or `Crashed`, so a caller
    that keeps draining until it sees one has seen the whole run.
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

        Raises:
            RuntimeError: If called more than once -- a second call would run
                the pipeline twice concurrently against the same request.
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
                should_continue=lambda: not self._cancelled.is_set(),
            )
        except LauncherError as exc:
            self._queue.put(Crashed(str(exc)))
        except BaseException as exc:
            # Every kind of thread exit -- including SystemExit and
            # KeyboardInterrupt, which a plain `except Exception` would miss
            # entirely -- must still leave exactly one terminal event queued
            # (see the class docstring's invariant); the exception is then
            # re-raised so the thread's own exit behaves as it would without
            # this handler, just with the event already delivered.
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
        """Ask the run to stop at the next between-series check point."""
        self._cancelled.set()

    def join(self, timeout: float | None = None) -> None:
        """Block until the terminal event has been put, or `timeout` elapses."""
        if self._thread is not None:
            self._thread.join(timeout)

    @property
    def running(self) -> bool:
        """True from `start()` until the terminal event has been put."""
        return self._thread is not None and not self._finished.is_set()
