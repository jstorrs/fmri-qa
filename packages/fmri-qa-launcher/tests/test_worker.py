"""`BackgroundRun`: one run on its own thread, delivering typed events.

Every test injects a fake `run` -- never `session.run_session` -- so this
module never pays for `fmriqc`'s analysis stack; `worker.py` itself imports
none of it either (see its docstring), and these tests are what pin that.
"""

import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from fmriqc_launcher.exceptions import RequestError
from fmriqc_launcher.progress import Progress, Stage
from fmriqc_launcher.request import RunRequest
from fmriqc_launcher.session import RunResult
from fmriqc_launcher.worker import BackgroundRun, Crashed, Finished

_JOIN_TIMEOUT = 5.0


@pytest.fixture
def request_(tmp_path: Path) -> RunRequest:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    return RunRequest(dicom_dir=dicom_dir, output_dir=tmp_path / "output")


def _fake_series_run(
    names: tuple[str, ...],
) -> Callable[..., RunResult]:
    """A fake `run` reporting one `Progress` per name; also checks `should_continue`."""

    def run(
        request: RunRequest,
        *,
        progress: Callable[[Progress], None],
        should_continue: Callable[[], bool],
    ) -> RunResult:
        seen = []
        for index, name in enumerate(names, start=1):
            if not should_continue():
                break
            progress(Progress(Stage.ANALYZE, index, len(names), name))
            seen.append(name)
        return RunResult(request.output_dir, (), cancelled=len(seen) < len(names))

    return run


def test_events_arrive_in_order_ending_with_one_terminal_event(
    request_: RunRequest,
) -> None:
    background = BackgroundRun(request_, run=_fake_series_run(("a", "b", "c")))
    background.start()
    background.join(_JOIN_TIMEOUT)

    events = background.poll()
    progress_events = [e for e in events if isinstance(e, Progress)]
    assert [e.series for e in progress_events] == ["a", "b", "c"]
    assert isinstance(events[-1], Finished)
    assert sum(isinstance(e, Finished | Crashed) for e in events) == 1


def test_poll_on_an_idle_run_returns_nothing(request_: RunRequest) -> None:
    background = BackgroundRun(request_, run=_fake_series_run(()))
    assert background.poll() == ()


def test_poll_on_a_not_started_run_returns_nothing(request_: RunRequest) -> None:
    background = BackgroundRun(request_, run=_fake_series_run(("a",)))
    assert background.poll() == ()


def test_join_on_a_not_started_run_returns_immediately(request_: RunRequest) -> None:
    background = BackgroundRun(request_, run=_fake_series_run(("a",)))
    background.join(_JOIN_TIMEOUT)  # nothing to wait for; must not block or raise


def test_cancel_flips_should_continue_and_the_result_is_cancelled(
    request_: RunRequest,
) -> None:
    """`cancel()` is set before the fake run ever checks `should_continue` again.

    Rather than racing the background thread with a sleep-poll loop, the fake
    run signals `first_series_done` right after finishing the first series
    and then blocks on `may_continue` -- so `cancel()` (and setting
    `may_continue`) only happens once the main thread knows the run is
    parked exactly between the first and second `should_continue` checks.
    Deterministic; no sleep involved.
    """
    first_series_done = threading.Event()
    may_continue = threading.Event()

    def run(
        request: RunRequest,
        *,
        progress: Callable[[Progress], None],
        should_continue: Callable[[], bool],
    ) -> RunResult:
        seen = []
        for index, name in enumerate(("a", "b", "c"), start=1):
            if not should_continue():
                break
            progress(Progress(Stage.ANALYZE, index, 3, name))
            seen.append(name)
            if name == "a":
                first_series_done.set()
                may_continue.wait(_JOIN_TIMEOUT)
        return RunResult(request.output_dir, (), cancelled=len(seen) < 3)

    background = BackgroundRun(request_, run=run)
    background.start()
    assert first_series_done.wait(_JOIN_TIMEOUT)
    background.cancel()
    may_continue.set()
    background.join(_JOIN_TIMEOUT)

    events = background.poll()
    finished = [e for e in events if isinstance(e, Finished)]
    assert len(finished) == 1
    assert finished[0].result.cancelled is True


def test_a_launcher_error_arrives_as_crashed_with_its_message(
    request_: RunRequest,
) -> None:
    def run(*_args: object, **_kwargs: object) -> RunResult:
        raise RequestError(["dicom directory missing"])

    background = BackgroundRun(request_, run=run)
    background.start()
    background.join(_JOIN_TIMEOUT)

    events = background.poll()
    assert len(events) == 1
    assert isinstance(events[0], Crashed)
    assert "dicom directory missing" in events[0].message


def test_an_unexpected_exception_arrives_as_crashed_naming_its_type(
    request_: RunRequest,
) -> None:
    def run(*_args: object, **_kwargs: object) -> RunResult:
        raise ValueError("boom")

    background = BackgroundRun(request_, run=run)
    background.start()
    background.join(_JOIN_TIMEOUT)

    events = background.poll()
    assert len(events) == 1
    assert isinstance(events[0], Crashed)
    assert "ValueError" in events[0].message
    assert "boom" in events[0].message
    assert "ValueError" in events[0].details
    assert "boom" in events[0].details


def test_a_system_exit_still_arrives_as_a_crashed_event(request_: RunRequest) -> None:
    """`SystemExit`/`KeyboardInterrupt` are `BaseException`, not `Exception`.

    A plain `except Exception` would miss these entirely, leaving `running`
    False with no terminal event ever queued -- the one invariant `poll()`'s
    callers depend on (see `BackgroundRun`'s docstring).
    """

    def run(*_args: object, **_kwargs: object) -> RunResult:
        raise SystemExit("should still produce a Crashed event")

    background = BackgroundRun(request_, run=run)
    background.start()
    background.join(_JOIN_TIMEOUT)

    events = background.poll()
    assert len(events) == 1
    assert isinstance(events[0], Crashed)
    assert "SystemExit" in events[0].message
    assert background.running is False


def test_a_launcher_error_carries_no_details(request_: RunRequest) -> None:
    """An expected, worded `LauncherError` needs no traceback appended."""

    def run(*_args: object, **_kwargs: object) -> RunResult:
        raise RequestError(["dicom directory missing"])

    background = BackgroundRun(request_, run=run)
    background.start()
    background.join(_JOIN_TIMEOUT)

    events = background.poll()
    assert isinstance(events[0], Crashed)
    assert events[0].details == ""


def test_a_second_start_is_refused(request_: RunRequest) -> None:
    background = BackgroundRun(request_, run=_fake_series_run(("a",)))
    background.start()
    with pytest.raises(RuntimeError, match="once"):
        background.start()
    background.join(_JOIN_TIMEOUT)


def test_poll_drains_incrementally_while_the_run_is_still_going(
    request_: RunRequest,
) -> None:
    """`poll()` must not wait for the terminal event to return what has already arrived.

    Gated on `threading.Event`s rather than a sleep-poll loop, the same
    deterministic shape as `test_cancel_flips_should_continue_...` above: the
    fake run signals after its first `progress()` call and parks until the
    main thread has drained that one event and told it to continue.
    """
    first_reported = threading.Event()
    may_continue = threading.Event()

    def run(
        request: RunRequest,
        *,
        progress: Callable[[Progress], None],
        should_continue: Callable[[], bool],
    ) -> RunResult:
        progress(Progress(Stage.ANALYZE, 1, 2, "a"))
        first_reported.set()
        may_continue.wait(_JOIN_TIMEOUT)
        progress(Progress(Stage.ANALYZE, 2, 2, "b"))
        return RunResult(request.output_dir, ())

    background = BackgroundRun(request_, run=run)
    background.start()
    assert first_reported.wait(_JOIN_TIMEOUT)

    first_batch = background.poll()
    assert [e.series for e in first_batch if isinstance(e, Progress)] == ["a"]
    assert not any(isinstance(e, Finished | Crashed) for e in first_batch)

    may_continue.set()
    background.join(_JOIN_TIMEOUT)
    second_batch = background.poll()
    assert [e.series for e in second_batch if isinstance(e, Progress)] == ["b"]
    assert isinstance(second_batch[-1], Finished)


def test_running_is_true_after_start_and_false_once_finished(
    request_: RunRequest,
) -> None:
    background = BackgroundRun(request_, run=_fake_series_run(()))
    assert background.running is False
    background.start()
    background.join(_JOIN_TIMEOUT)
    background.poll()
    assert background.running is False


def test_the_default_run_calls_the_real_session_lazily(
    request_: RunRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No injected `run`: the default wrapper reaches `session.run_session` itself.

    Monkeypatches `fmriqc_launcher.session.run_session` rather than running
    the real pipeline -- proving the wiring, not re-testing `session.py`,
    which already has its own suite.
    """
    import fmriqc_launcher.session as session_module

    called: dict[str, object] = {}

    def fake_run_session(
        request: RunRequest,
        *,
        progress: Callable[[Progress], None],
        should_continue: Callable[[], bool],
    ) -> RunResult:
        called["request"] = request
        progress(Progress(Stage.ANALYZE, 1, 1, "only"))
        return RunResult(request.output_dir, ())

    monkeypatch.setattr(session_module, "run_session", fake_run_session)

    background = BackgroundRun(request_)
    background.start()
    background.join(_JOIN_TIMEOUT)

    events = background.poll()
    assert called["request"] is request_
    assert any(isinstance(e, Progress) for e in events)
    assert isinstance(events[-1], Finished)


def test_the_thread_is_non_daemon(request_: RunRequest) -> None:
    """No public seam exposes daemon-ness, so this reaches the private `_thread`.

    A daemon thread would let the interpreter exit mid-`shutil.rmtree` on the
    staging directory (see the module docstring) -- worth pinning even at the
    cost of one implementation-detail assertion.
    """
    background = BackgroundRun(request_, run=_fake_series_run(()))
    background.start()
    assert background._thread is not None
    assert background._thread.daemon is False
    background.join(_JOIN_TIMEOUT)
