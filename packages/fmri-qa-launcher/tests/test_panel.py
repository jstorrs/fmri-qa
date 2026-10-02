"""`Panel`, driven against a fake background run -- no real pipeline, no sleeps.

Every test here is gated on whether a real `tk.Tk()` root can be built at
all, not on `$DISPLAY` (unset on Windows/macOS, where a display still
exists) -- see the `root` fixture. `_FakeBackground` implements the same
shape `worker.BackgroundRun` does (`start`/`poll`/`cancel`/`running`) with no
thread behind it at all: a test pushes events onto it directly and calls
`panel._tick()` itself, so these tests are fast and deterministic regardless
of whether a display is actually available in CI.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
from collections.abc import Iterator
from pathlib import Path

import pytest

from fmriqc_launcher import panel as panel_module
from fmriqc_launcher.outcome import Published, Refused, RunResult
from fmriqc_launcher.panel import Panel
from fmriqc_launcher.progress import Progress, Stage
from fmriqc_launcher.request import FormValues, RunRequest
from fmriqc_launcher.results import Opener
from fmriqc_launcher.worker import Crashed, Event, Finished


def _recording_opener(sink: list[str]) -> Opener:
    """An `Opener` that records what it was asked to open and reports success."""

    def opener(uri: str) -> bool:
        sink.append(uri)
        return True

    return opener


@pytest.fixture
def root() -> Iterator[tk.Tk]:
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available to build a tk.Tk root")
    try:
        yield window
    finally:
        with contextlib.suppress(tk.TclError):  # a test may already have destroyed it
            window.destroy()


class _FakeBackground:
    """A `worker.BackgroundRun`-shaped stand-in: no thread, no real pipeline.

    A test drives it by calling `push()` and then `Panel._tick()` directly --
    `start()` only records that it was called, and `poll()` drains exactly
    what `push()` put there, synchronously.
    """

    def __init__(self, request: RunRequest) -> None:
        self.request = request
        self.start_called = False
        self.cancel_called = False
        self._events: list[Event] = []
        self._running = False

    def start(self) -> None:
        self.start_called = True
        self._running = True

    def poll(self) -> tuple[Event, ...]:
        events = tuple(self._events)
        self._events.clear()
        return events

    def cancel(self) -> None:
        self.cancel_called = True

    @property
    def running(self) -> bool:
        return self._running

    def push(self, event: Event) -> None:
        self._events.append(event)
        if isinstance(event, Finished | Crashed):
            self._running = False


class _Factory:
    """Records every `_FakeBackground` a `Panel` creates, in creation order."""

    def __init__(self) -> None:
        self.made: list[_FakeBackground] = []

    def __call__(self, request: RunRequest) -> _FakeBackground:
        fake = _FakeBackground(request)
        self.made.append(fake)
        return fake

    @property
    def last(self) -> _FakeBackground:
        return self.made[-1]


def _valid_form(tmp_path: Path, *, open_report: bool = True) -> FormValues:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    return FormValues(
        dicom_dir=str(dicom_dir),
        output_dir=str(tmp_path / "output"),
        open_report=open_report,
    )


def _set_form(panel: Panel, values: FormValues) -> None:
    panel._dicom_var.set(values.dicom_dir)
    panel._output_var.set(values.output_dir)
    panel._open_var.set(values.open_report)
    panel._advanced_vars["trim_sec"].set(values.trim_sec)
    panel._advanced_vars["detrend"].set(values.detrend)
    panel._advanced_vars["center"].set(values.center)
    panel._advanced_vars["roi_size"].set(values.roi_size)


def _published(name: str, output_dir: Path) -> Published:
    return Published(
        name=name,
        directory=output_dir / name,
        scan=output_dir / name / f"{name}.nii.gz",
        sidecar=None,
        artifact=output_dir / name / f"{name}.qa.nc",
        report=output_dir / name / f"{name}.html",
    )


def test_a_fresh_panel_reads_back_the_default_form_values(root: tk.Tk) -> None:
    panel = Panel(root)
    assert panel.form_values() == FormValues(open_report=True)


def test_a_successful_run_fills_the_bar_and_opens_the_report(
    root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        panel_module.messagebox, "showerror", lambda *a, **_k: errors.append(a)
    )
    opened: list[str] = []
    factory = _Factory()
    panel = Panel(root, background=factory, opener=_recording_opener(opened))

    _set_form(panel, _valid_form(tmp_path, open_report=True))
    panel._on_run()
    assert factory.last.start_called is True

    output_dir = Path(factory.last.request.output_dir)
    result = RunResult(output_dir, (_published("scan", output_dir),))
    factory.last.push(Finished(result))
    panel._tick()

    assert panel._status_var.get() == "1 of 1 series published"
    assert panel._progress["value"] == panel._progress["maximum"]
    assert not panel._run_button.instate(["disabled"])
    assert not panel._open_button.instate(["disabled"])
    assert opened == [output_dir.joinpath("scan", "scan.html").as_uri()]
    assert panel.exit_code == 0
    assert errors == []


def test_a_second_run_bounces_the_bar_over_the_same_range_as_the_first(
    root: tk.Tk, tmp_path: Path
) -> None:
    factory = _Factory()
    panel = Panel(root, background=factory, opener=_recording_opener([]))
    _set_form(panel, _valid_form(tmp_path, open_report=False))

    panel._on_run()
    first_maximum = panel._progress["maximum"]
    output_dir = Path(factory.last.request.output_dir)
    result = RunResult(output_dir, (_published("scan", output_dir),))
    factory.last.push(Finished(result))
    panel._tick()
    assert panel._progress["maximum"] != first_maximum  # the run left its ticks

    panel._on_run()

    assert str(panel._progress["mode"]) == "indeterminate"
    assert panel._progress["maximum"] == first_maximum


def test_an_all_refused_run_reports_a_plain_headline(
    root: tk.Tk, tmp_path: Path
) -> None:
    factory = _Factory()
    panel = Panel(root, background=factory)
    _set_form(panel, _valid_form(tmp_path, open_report=False))
    panel._on_run()

    output_dir = Path(factory.last.request.output_dir)
    result = RunResult(
        output_dir, (Refused(name="scan", existing=output_dir / "scan"),)
    )
    factory.last.push(Finished(result))
    panel._tick()

    assert (
        panel._status_var.get()
        == "All 1 series already have results in the output folder"
    )
    assert panel._open_button.instate(["disabled"])


def test_a_crash_is_reported_on_the_status_line_and_the_log(
    root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel_module.messagebox, "showerror", lambda *a, **k: None)
    factory = _Factory()
    panel = Panel(root, background=factory)
    _set_form(panel, _valid_form(tmp_path))
    panel._on_run()

    factory.last.push(Crashed("no converter is available", "Traceback: boom"))
    panel._tick()

    assert "no converter is available" in panel._status_var.get()
    log = panel._log_widget.get("1.0", "end")
    assert "no converter is available" in log
    assert "Traceback: boom" in log
    assert not panel._run_button.instate(["disabled"])
    assert panel.exit_code == 1


def test_an_invalid_form_shows_one_dialog_listing_every_problem_and_starts_nothing(
    root: tk.Tk, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        panel_module.messagebox,
        "showerror",
        lambda *a, **_k: shown.append(a),
    )
    factory = _Factory()
    panel = Panel(root, background=factory)
    _set_form(panel, FormValues(dicom_dir="", output_dir="", trim_sec="not-a-number"))

    panel._on_run()

    assert len(shown) == 1
    message = str(shown[0][1])
    assert "DICOM directory" in message
    assert "Output directory" in message
    assert "Trim" in message
    assert factory.made == []


def test_closing_mid_run_cancels_and_the_stopping_message_persists(
    root: tk.Tk, tmp_path: Path
) -> None:
    factory = _Factory()
    panel = Panel(root, background=factory)
    _set_form(panel, _valid_form(tmp_path))
    panel._on_run()

    panel._on_close()
    assert factory.last.cancel_called is True
    stopping = panel._status_var.get()
    assert "Stopping" in stopping

    factory.last.push(Progress(Stage.ANALYZE, 1, 2, "scan"))
    panel._tick()
    assert panel._status_var.get() == stopping  # not overwritten by ordinary progress

    assert root.winfo_exists()  # not destroyed yet -- the run has not finished


def test_closing_mid_run_destroys_once_finished_with_no_auto_open(
    root: tk.Tk, tmp_path: Path
) -> None:
    opened: list[str] = []
    factory = _Factory()
    panel = Panel(root, background=factory, opener=_recording_opener(opened))
    _set_form(panel, _valid_form(tmp_path, open_report=True))
    panel._on_run()

    panel._on_close()
    output_dir = Path(factory.last.request.output_dir)
    result = RunResult(output_dir, (_published("scan", output_dir),))
    factory.last.push(Finished(result))
    panel._tick()

    assert opened == []
    with pytest.raises(tk.TclError):
        root.winfo_exists()


def test_closing_mid_run_destroys_once_crashed_with_no_dialog(
    root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        panel_module.messagebox, "showerror", lambda *a, **_k: errors.append(a)
    )
    factory = _Factory()
    panel = Panel(root, background=factory)
    _set_form(panel, _valid_form(tmp_path))
    panel._on_run()

    panel._on_close()
    factory.last.push(Crashed("no converter is available", "Traceback: boom"))
    panel._tick()

    assert errors == []
    with pytest.raises(tk.TclError):
        root.winfo_exists()


def test_a_second_close_destroys_immediately(root: tk.Tk, tmp_path: Path) -> None:
    factory = _Factory()
    panel = Panel(root, background=factory)
    _set_form(panel, _valid_form(tmp_path))
    panel._on_run()

    panel._on_close()  # first close: asks the run to stop
    panel._on_close()  # second close: destroys regardless of the run's state

    with pytest.raises(tk.TclError):
        root.winfo_exists()


def test_a_callback_exception_reenables_inputs_and_records_the_failure(
    root: tk.Tk, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(panel_module.messagebox, "showerror", lambda *a, **k: None)
    factory = _Factory()
    panel = Panel(root, background=factory)
    _set_form(panel, _valid_form(tmp_path))
    panel._on_run()
    assert panel._run_button.instate(["disabled"])

    try:
        raise RuntimeError("a callback blew up")
    except RuntimeError as exc:
        panel._on_callback_exception(RuntimeError, exc, exc.__traceback__)

    assert factory.last.cancel_called is True
    assert not panel._run_button.instate(["disabled"])
    assert "a callback blew up" in panel._status_var.get()
    assert "a callback blew up" in panel._log_widget.get("1.0", "end")


def test_an_opener_raising_oserror_on_the_close_path_still_destroys(
    root: tk.Tk, tmp_path: Path
) -> None:
    def _raising_opener(_uri: str) -> bool:
        raise OSError("no browser configured")

    factory = _Factory()
    panel = Panel(root, background=factory, opener=_raising_opener)
    _set_form(panel, _valid_form(tmp_path, open_report=True))
    panel._on_run()

    panel._on_close()
    output_dir = Path(factory.last.request.output_dir)
    result = RunResult(output_dir, (_published("scan", output_dir),))
    factory.last.push(Finished(result))
    panel._tick()  # must not raise, and must still destroy the window

    with pytest.raises(tk.TclError):
        root.winfo_exists()


def test_the_open_button_reports_an_oserror_without_dying(
    root: tk.Tk, tmp_path: Path
) -> None:
    def _raising_opener(_uri: str) -> bool:
        raise OSError("no browser configured")

    factory = _Factory()
    panel = Panel(root, background=factory, opener=_raising_opener)
    _set_form(panel, _valid_form(tmp_path, open_report=False))
    panel._on_run()
    output_dir = Path(factory.last.request.output_dir)
    result = RunResult(output_dir, (_published("scan", output_dir),))
    factory.last.push(Finished(result))
    panel._tick()

    panel._on_open()  # must not raise

    assert "Could not open results" in panel._status_var.get()
    assert "no browser configured" in panel._log_widget.get("1.0", "end")
