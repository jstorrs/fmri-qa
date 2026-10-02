"""The desktop panel: one `tkinter` window over `request`/`worker`/`session`.

This is the only module in the package that imports `tkinter` -- `cli.py`
reaches it through `importlib.import_module` precisely so that importing
`fmriqc_launcher.cli` never pulls `tkinter` in (see its docstring), and every
other module here stays free of it so it can be unit-tested without a
display.

Every decision about *what happened* -- where the progress bar sits, what a
finished run means, whether a submission is valid, what the exit code should
be -- lives in `panel_state`/`worker`/`request`; this module only wires
widgets to those functions and manages the one piece of imperative-shell
lifecycle those modules cannot express on their own: the window's own close
sequence. It never writes to stdout or stderr: under `pythonw` (the
gui-script entry point, `fmri-qa-panel`) `sys.stdout`/`sys.stderr` are
`None`, and a `print` would raise -- which is also why `root.mainloop()`
alone is not enough supervision: `tkinter`'s default
`report_callback_exception` calls `traceback.print_exception`, silently a
no-op under `pythonw`, and worse, an exception there ends the `after` chain
that drives `_tick`, freezing the panel mid-run. `_on_callback_exception`
below is installed as a backstop against exactly that.

`Panel` is a plain object built on a `tk.Tk` root a caller supplies, with a
`form_values()` accessor -- this is what lets the display-gated tests in
`tests/test_panel.py` build a real window, read its defaults back, drive it
with a fake background run, and destroy it without ever calling
`mainloop()`. `background=`/`opener=` are injected the same way
`worker.BackgroundRun` takes `run=` and `results.open_results` takes
`opener=`, so those tests never touch a real pipeline, a real thread, or a
real browser.
"""

from __future__ import annotations

import contextlib
import tkinter as tk
import traceback
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from types import TracebackType
from typing import Literal, Protocol

from .exceptions import PanelUnavailableError, RequestError
from .outcome import RunResult
from .panel_state import (
    CRASHED_BAR,
    BarState,
    Indeterminate,
    Summary,
    bar_state,
    exit_code,
    final_bar,
    stopping_message,
    summarize,
)
from .progress import Progress, describe
from .request import (
    CENTER_CHOICES,
    CENTER_HELP,
    CENTER_LABEL,
    DETREND_CHOICES,
    DETREND_HELP,
    DETREND_LABEL,
    DICOM_DIR_HELP,
    DICOM_DIR_PANEL_LABEL,
    OPEN_REPORT_LABEL,
    OUTPUT_DIR_HELP,
    OUTPUT_DIR_PANEL_LABEL,
    ROI_SIZE_HELP,
    ROI_SIZE_LABEL,
    TRIM_SEC_HELP,
    TRIM_SEC_LABEL,
    FormValues,
    RunRequest,
    parse_form,
)
from .results import Opener, open_results
from .worker import BackgroundRun, Crashed, Event, Finished

__all__ = ["Panel", "main", "run_panel"]

_TITLE = "fMRI QA"
_TICK_MS = 150
# An indeterminate bar sweeps once per `maximum` steps, so `maximum` sets the
# bounce speed. It has to be put back on every run: a finished run leaves the
# bar's `maximum` at a handful of ticks, which would turn the next run's
# bounce into a flicker between the two ends.
_PULSE_MAXIMUM = 100
_PULSE_STEP_MS = 10
_MIN_WIDTH = 480
_HINT_PADDING = 24  # room either side of a wrapped hint label within its row
_MIN_WRAPLENGTH = 200
_ADVANCED_NOTE = (
    "Changing these changes the numbers; every report records the settings used."
)


class _BackgroundLike(Protocol):
    """What `Panel` needs from a background run -- exactly `BackgroundRun`'s shape.

    Naming the shape as a `Protocol`, rather than requiring `BackgroundRun`
    itself, is what lets `tests/test_panel.py` inject a fake with no thread
    and no real pipeline behind it (see that module's `_FakeBackground`).
    """

    def start(self) -> None: ...
    def poll(self) -> tuple[Event, ...]: ...
    def cancel(self) -> None: ...
    @property
    def running(self) -> bool: ...


type _BackgroundFactory = Callable[[RunRequest], _BackgroundLike]


@dataclass(frozen=True, slots=True)
class _AdvancedField:
    """One row of the Advanced frame, described data rather than written out by hand.

    Keeping this a list (see `_ADVANCED_FIELDS` below) rather than one
    hand-built row per field is what makes adding a later row -- the
    high/low flip-angle option the brief leaves room for -- a one-line
    addition instead of a new block of widget code.
    """

    key: Literal["trim_sec", "detrend", "center", "roi_size"]
    label: str
    help: str
    kind: Literal["entry", "combobox"]
    choices: tuple[str, ...] = ()


_ADVANCED_FIELDS: tuple[_AdvancedField, ...] = (
    _AdvancedField("trim_sec", TRIM_SEC_LABEL, TRIM_SEC_HELP, "entry"),
    _AdvancedField("detrend", DETREND_LABEL, DETREND_HELP, "combobox", DETREND_CHOICES),
    _AdvancedField("center", CENTER_LABEL, CENTER_HELP, "combobox", CENTER_CHOICES),
    _AdvancedField("roi_size", ROI_SIZE_LABEL, ROI_SIZE_HELP, "entry"),
)

_DEFAULTS = FormValues()


class _Rows:
    """Hands out incrementing grid rows, so a row index is genuinely computed.

    Every row in `_build` comes from `take()` rather than a hand-counted
    literal, which is what keeps a widget's row correct if an earlier one is
    ever inserted or removed -- including the log frame's own row, handed
    back to the caller rather than redeclared as a module constant.
    """

    def __init__(self) -> None:
        self._next = 0

    def take(self, span: int = 1) -> int:
        """The next unused row; `span` reserves that many before the next call."""
        row = self._next
        self._next += span
        return row


class Panel:
    """The one window: built on a caller-supplied `tk.Tk` root.

    Taking `root` as a constructor argument (rather than creating it itself)
    is what lets `tests/test_panel.py` build a real `Panel`, call
    `form_values()`, and destroy the root without ever entering `mainloop()`.
    `background` and `opener` are injected the same way for the same reason:
    a display-gated test can drive a real `Panel` end to end against a fake
    background run and a fake opener, with no thread and no browser.
    """

    def __init__(
        self,
        root: tk.Tk,
        *,
        background: _BackgroundFactory = BackgroundRun,
        opener: Opener = webbrowser.open,
    ) -> None:
        self._root = root
        self._background_factory = background
        self._opener = opener
        self._background: _BackgroundLike | None = None
        self._closing = False
        self._input_widgets: list[ttk.Widget] = []
        self._wrap_labels: list[ttk.Label] = []
        self._last_result: RunResult | None = None
        self._last_progress: Progress | None = None
        self.exit_code = 0
        self._build()

    # -- construction ------------------------------------------------

    def _build(self) -> None:
        root = self._root
        root.title(_TITLE)
        root.resizable(True, True)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Installed once, here: the backstop against an exception in any
        # `after` callback (`_tick`, in practice) silently ending the pump --
        # see the module docstring.
        root.report_callback_exception = self._on_callback_exception

        outer = ttk.Frame(root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        outer.columnconfigure(1, weight=1)

        self._dicom_var = tk.StringVar(value=_DEFAULTS.dicom_dir)
        self._output_var = tk.StringVar(value=_DEFAULTS.output_dir)
        self._open_var = tk.BooleanVar(
            value=True
        )  # panel default: checked (see module docstring)
        self._advanced_visible = tk.BooleanVar(value=False)
        self._status_var = tk.StringVar(value="Ready")
        # Only the entries/comboboxes and the Run button itself trigger Run
        # on <Return> -- not a "Browse..." button, which the root-level
        # binding this replaces used to fire from too (see the module's
        # keyboard-scoping fix).
        self._return_widgets: list[tk.Widget] = []

        rows = _Rows()
        self._dicom_entry = self._build_directory_row(
            outer,
            rows,
            label=DICOM_DIR_PANEL_LABEL,
            help_text=DICOM_DIR_HELP,
            variable=self._dicom_var,
            mustexist=True,
        )
        self._build_directory_row(
            outer,
            rows,
            label=OUTPUT_DIR_PANEL_LABEL,
            help_text=OUTPUT_DIR_HELP,
            variable=self._output_var,
            mustexist=False,
        )

        open_check = ttk.Checkbutton(
            outer, text=OPEN_REPORT_LABEL, variable=self._open_var
        )
        open_check.grid(
            row=rows.take(), column=0, columnspan=3, sticky="w", pady=(4, 4)
        )
        self._input_widgets.append(open_check)

        disclosure = ttk.Checkbutton(
            outer,
            text="Show advanced options",
            variable=self._advanced_visible,
            command=self._toggle_advanced,
        )
        disclosure.grid(row=rows.take(), column=0, columnspan=3, sticky="w")
        self._input_widgets.append(disclosure)

        advanced_row = rows.take()
        self._advanced_frame = self._build_advanced_frame(outer)
        self._advanced_frame.grid(
            row=advanced_row, column=0, columnspan=3, sticky="ew", pady=(4, 4)
        )
        self._advanced_frame.grid_remove()  # collapsed by default

        button_row = rows.take()
        run_button = ttk.Button(
            outer, text="Run", command=self._on_run, default="active"
        )
        run_button.grid(row=button_row, column=0, sticky="w", pady=(8, 4))
        self._run_button = run_button
        self._input_widgets.append(run_button)
        self._return_widgets.append(run_button)

        self._open_button = ttk.Button(
            outer, text="Open results", command=self._on_open, state="disabled"
        )
        self._open_button.grid(row=button_row, column=1, sticky="w", pady=(8, 4))

        self._progress = ttk.Progressbar(outer, orient="horizontal", mode="determinate")
        self._progress.grid(
            row=rows.take(), column=0, columnspan=3, sticky="ew", pady=(0, 4)
        )

        status_label = ttk.Label(outer, textvariable=self._status_var)
        status_label.grid(row=rows.take(), column=0, columnspan=3, sticky="w")

        log_row = rows.take()
        self._log_widget, log_frame = self._build_log(outer)
        log_frame.grid(row=log_row, column=0, columnspan=3, sticky="nsew", pady=(4, 0))
        outer.rowconfigure(log_row, weight=1)

        for widget in self._return_widgets:
            widget.bind("<Return>", self._on_return)
        outer.bind("<Configure>", self._on_container_resized)

        # A label with no wraplength yet reports its *unwrapped* natural
        # width -- the longest hint here runs to several hundred pixels of
        # single-line text -- which would inflate the very first
        # `_fit_window()` below into a needlessly wide window before
        # `<Configure>` ever gets a chance to wrap it back down. Seeding a
        # sane starting wraplength here breaks that chicken-and-egg: the
        # window opens at a sensible width, and `<Configure>` only ever
        # grows the wraplength again if the window ends up wider than this.
        starting_width = _MIN_WIDTH - _HINT_PADDING
        for label in self._wrap_labels:
            label.configure(wraplength=starting_width)

        self._fit_window()
        self._dicom_entry.focus_set()

    def _build_directory_row(
        self,
        parent: ttk.Frame,
        rows: _Rows,
        *,
        label: str,
        help_text: str,
        variable: tk.StringVar,
        mustexist: bool,
    ) -> ttk.Entry:
        row = rows.take(2)  # the field itself, plus its hint on the row below
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w")
        entry = ttk.Entry(parent, textvariable=variable)
        entry.grid(row=row, column=1, sticky="ew", padx=(4, 4))

        def browse() -> None:
            current = variable.get().strip()
            initialdir = current if current and Path(current).is_dir() else None
            chosen = filedialog.askdirectory(
                parent=self._root,
                title=f"Choose the {label.lower()}",
                mustexist=mustexist,
                initialdir=initialdir,
            )
            if chosen:
                variable.set(chosen)

        button = ttk.Button(parent, text="Browse...", command=browse)
        button.grid(row=row, column=2, sticky="e")
        hint = ttk.Label(parent, text=help_text, foreground="#555555")
        hint.grid(row=row + 1, column=0, columnspan=3, sticky="w", pady=(0, 4))
        self._wrap_labels.append(hint)
        self._input_widgets.extend((entry, button))
        self._return_widgets.append(entry)
        return entry

    def _build_advanced_frame(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Advanced options", padding=8)
        frame.columnconfigure(1, weight=1)
        note = ttk.Label(frame, text=_ADVANCED_NOTE, foreground="#555555")
        note.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 6))
        self._wrap_labels.append(note)
        self._advanced_vars: dict[str, tk.StringVar] = {}
        for offset, field in enumerate(_ADVANCED_FIELDS):
            row = 1 + 2 * offset
            default = str(getattr(_DEFAULTS, field.key))
            variable = tk.StringVar(value=default)
            self._advanced_vars[field.key] = variable
            ttk.Label(frame, text=field.label).grid(row=row, column=0, sticky="w")
            widget: ttk.Widget
            if field.kind == "combobox":
                widget = ttk.Combobox(
                    frame, textvariable=variable, state="readonly", values=field.choices
                )
            else:
                widget = ttk.Entry(frame, textvariable=variable)
            widget.grid(row=row, column=1, columnspan=2, sticky="ew", padx=(4, 0))
            hint = ttk.Label(frame, text=field.help, foreground="#555555")
            hint.grid(row=row + 1, column=0, columnspan=3, sticky="w", pady=(0, 4))
            self._wrap_labels.append(hint)
            self._input_widgets.append(widget)
            self._return_widgets.append(widget)
        return frame

    def _build_log(self, parent: ttk.Frame) -> tuple[tk.Text, ttk.Frame]:
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        text = tk.Text(frame, height=8, state="disabled", wrap="word")
        text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        text.configure(yscrollcommand=scrollbar.set)
        return text, frame

    # -- layout ----------------------------------------------------------

    def _fit_window(self) -> None:
        """Size the window from its requested layout, not a fixed literal.

        No `geometry()` picked in advance: at a larger font or a higher Tk
        `scaling` (150% on Windows, say) a fixed size can put the Run button
        or the progress bar below the window's bottom edge with Advanced
        expanded. `update_idletasks()` forces geometry management to run so
        `winfo_reqwidth`/`reqheight` reflect the widgets actually built, and
        `minsize` is set from the same numbers so the window can never be
        resized smaller than its own content demands.
        """
        self._root.update_idletasks()
        width = max(self._root.winfo_reqwidth(), _MIN_WIDTH)
        height = self._root.winfo_reqheight()
        self._root.geometry(f"{width}x{height}")
        self._root.minsize(width, height)

    def _on_container_resized(self, event: tk.Event[tk.Misc]) -> None:
        """Rewrap every hint label to the container's current width.

        A hard-coded `wraplength` wastes space at 100% scaling and is wrong
        at any other -- this derives it from the actual available width
        instead, recomputed on every resize (including the one `_fit_window`
        and `_toggle_advanced` themselves trigger).
        """
        wraplength = max(event.width - _HINT_PADDING, _MIN_WRAPLENGTH)
        for label in self._wrap_labels:
            label.configure(wraplength=wraplength)

    # -- reading the form ---------------------------------------------

    def form_values(self) -> FormValues:
        """The widgets' current values, as a `FormValues` -- unparsed, as held."""
        return FormValues(
            dicom_dir=self._dicom_var.get(),
            output_dir=self._output_var.get(),
            trim_sec=self._advanced_vars["trim_sec"].get(),
            detrend=self._advanced_vars["detrend"].get(),
            center=self._advanced_vars["center"].get(),
            roi_size=self._advanced_vars["roi_size"].get(),
            open_report=bool(self._open_var.get()),
        )

    # -- behaviour ------------------------------------------------------

    def _toggle_advanced(self) -> None:
        if self._advanced_visible.get():
            self._advanced_frame.grid()
        else:
            self._advanced_frame.grid_remove()
        self._fit_window()

    def _on_return(self, _event: object) -> None:
        if not self._run_button.instate(["disabled"]):
            self._on_run()

    def _on_open(self) -> None:
        if self._last_result is None:
            return
        if not self._open_results(self._last_result):
            self._status_var.set("Could not open results")

    def _open_results(self, result: RunResult) -> bool:
        """Open `result`; on an `OSError`, log it and return False instead of raising.

        Shared by the Open button and "open when done"; only the button also
        reports the failure on the status line.
        """
        try:
            open_results(result, opener=self._opener)
        except OSError as exc:
            self._append_log(f"Could not open results: {exc}")
            return False
        return True

    def _set_inputs_enabled(self, enabled: bool) -> None:
        """Enable or disable every input, via the ttk state API rather than `configure`.

        `state(["!disabled"])` (a `ttk.Widget` method, not
        `configure(state=...)`) is enough on its own for every widget kind
        here, including a readonly combobox: "readonly" is set once, at
        construction, and toggling `disabled`/`!disabled` never touches it --
        so there is no separate combobox branch to carry.
        """
        state = ["!disabled"] if enabled else ["disabled"]
        for widget in self._input_widgets:
            widget.state(state)

    def _clear_log(self) -> None:
        self._log_widget.configure(state="normal")
        self._log_widget.delete("1.0", "end")
        self._log_widget.configure(state="disabled")

    def _append_log(self, line: str) -> None:
        self._log_widget.configure(state="normal")
        self._log_widget.insert("end", line + "\n")
        self._log_widget.configure(state="disabled")
        self._log_widget.see("end")

    def _apply_bar_state(self, state: BarState) -> None:
        if isinstance(state, Indeterminate):
            if str(self._progress["mode"]) != "indeterminate":
                self._progress.configure(
                    mode="indeterminate", maximum=_PULSE_MAXIMUM, value=0
                )
                self._progress.start(_PULSE_STEP_MS)
            return
        self._progress.stop()  # stop the animation before resting on a fixed value
        self._progress.configure(
            mode="determinate", maximum=state.maximum, value=state.value
        )

    def _on_run(self) -> None:
        try:
            request = parse_form(self.form_values())
        except RequestError as exc:
            messagebox.showerror(_TITLE, "\n".join(exc.problems), parent=self._root)
            return

        self._set_inputs_enabled(False)
        self._clear_log()
        self._open_button.configure(state="disabled")
        self._last_result = None
        self._last_progress = None
        self._status_var.set("Starting...")
        self._apply_bar_state(Indeterminate())

        self._background = self._background_factory(request)
        self._background.start()
        self._root.after(_TICK_MS, self._tick)

    def _tick(self) -> None:
        background = self._background
        if background is None:
            return
        for event in background.poll():
            terminal = self._handle_event(event)
            if terminal:
                return
        self._root.after(_TICK_MS, self._tick)

    def _handle_event(self, event: Event) -> bool:
        """Apply one `Event`; return True once the run has reached a terminal event."""
        if isinstance(event, Progress):
            self._last_progress = event
            self._append_log(describe(event))
            # A close in progress owns the status line (see `_on_close`):
            # once it has said "stopping...", a later stage line must not
            # paper back over it until the run actually ends.
            if not self._closing:
                self._status_var.set(describe(event))
            self._apply_bar_state(bar_state(event))
            return False
        try:
            if isinstance(event, Finished):
                self._on_finished(event)
            else:
                self._on_crashed(event)
        finally:
            # Unconditional, and last: whatever the handler raised must not
            # leave a window that a close request can no longer dismiss.
            if self._closing:
                self._destroy()
        return True

    def _end_run(
        self,
        *,
        bar: BarState,
        status: str,
        log_lines: tuple[str, ...],
        code: int,
    ) -> None:
        """Put the panel back at rest after a run ends, however it ended.

        Drops the background run, rests the bar on `bar`, shows `status`,
        logs `log_lines`, re-enables the inputs, and records `code` as the
        exit code. Callers that may still have a run in flight cancel it
        first; this only forgets it.
        """
        self._background = None
        self._apply_bar_state(bar)
        self._status_var.set(status)
        for line in log_lines:
            self._append_log(line)
        self._set_inputs_enabled(True)
        self.exit_code = code

    def _on_finished(self, event: Finished) -> None:
        result = event.result
        summary: Summary = summarize(result)
        self._end_run(
            bar=final_bar(result),
            status=summary.headline,
            log_lines=summary.details,
            code=exit_code(event),
        )
        self._last_result = result
        if self._closing or not summary.offer_open:
            return
        self._open_button.configure(state="normal")
        if self._open_var.get():
            self._open_results(result)

    def _on_crashed(self, event: Crashed) -> None:
        crashed = f"Crashed: {event.message}"
        log_lines = (crashed, event.details) if event.details else (crashed,)
        self._end_run(
            bar=CRASHED_BAR, status=crashed, log_lines=log_lines, code=exit_code(event)
        )
        if not self._closing:
            messagebox.showerror(_TITLE, event.message, parent=self._root)

    def _on_callback_exception(
        self,
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        """Handle an exception `tkinter` caught from a callback (`after`, a button...).

        Installed as `root.report_callback_exception` -- see the module
        docstring for why the default handler is not enough. This does not
        try to resume the `after` chain (`_tick` is not rescheduled from
        here): a callback that raised has already left the panel's state
        uncertain, so the safe thing is to stop polling, not to guess that
        the next tick would go any better. It must not itself raise if the
        window is already gone.
        """
        try:
            details = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
            message = f"{exc_type.__name__}: {exc_value}"
            if self._background is not None:
                self._background.cancel()  # do not leave the worker running unobserved
            internal = f"Internal error: {message}"
            self._end_run(
                bar=CRASHED_BAR, status=internal, log_lines=(internal, details), code=1
            )
            messagebox.showerror(_TITLE, message, parent=self._root)
        except tk.TclError:
            pass  # the window is already gone; nothing left to report to

    def _destroy(self) -> None:
        """Destroy the root, tolerating a second call (idempotent by design).

        A second close request, or a terminal event that arrives after the
        window is already gone, must never raise merely for asking twice.
        """
        with contextlib.suppress(tk.TclError):  # already destroyed
            self._root.destroy()

    def _on_close(self) -> None:
        if self._closing:
            # A second close request: stop waiting on the run. The
            # non-daemon worker thread still runs `session._publish`'s
            # `finally` to completion before the process actually exits, so
            # no half-copied series is left in the output directory.
            self._destroy()
            return
        self._closing = True
        if self._background is not None and self._background.running:
            self._background.cancel()
            self._status_var.set(stopping_message(self._last_progress))
            return
        self._destroy()


def run_panel() -> int:
    """Build the panel and run its event loop; return 0, or 1 if the last run failed.

    Raises:
        PanelUnavailableError: If no display is available -- either building
            the `tk.Tk` root or constructing the panel's widgets raised
            `tkinter.TclError`. Never a bare `tkinter.TclError`, so
            `cli._launch_panel` can report this without importing `tkinter`
            itself.
    """
    try:
        root = tk.Tk()
        panel = Panel(root)
    except tk.TclError as exc:
        raise PanelUnavailableError(str(exc)) from exc
    root.mainloop()
    return panel.exit_code


def main() -> int:
    """The `fmri-qa-panel` gui-script entry point.

    Under `pythonw` there is no console to explain a missing display to, so
    `PanelUnavailableError` is reported the only way it can be from there: a
    non-zero exit code, silently.
    """
    try:
        return run_panel()
    except PanelUnavailableError:
        return 2
