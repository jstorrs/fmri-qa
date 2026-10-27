# fmri-qa-launcher

The application shell for [fmri-qa](../../README.md): a one-step pipeline that
takes a DICOM directory and writes one report directory per series. It is built
on [`fmri-qa-core`](../fmri-qa-core) (analysis),
[`fmri-qa-io`](../fmri-qa-io) (files and conversion) and
[`fmri-qa-report`](../fmri-qa-report) (rendering), and borrows two argument
parsers from [`fmri-qa-cli`](../fmri-qa-cli). It adds no third-party dependency
of its own.

The workspace's [user guide](../../docs/user-guide/index.md) covers the command
line, the panel, and what a run writes. Build it from the workspace root with
`make sync-docs && make docs`. It lands under `build/site`.

## `fmri-qa-run`

```
fmri-qa-run DICOM_DIR OUTPUT_DIR [options]
```

Imports every series under `DICOM_DIR`, analyzes each, and writes one folder per
series under `OUTPUT_DIR`, named for the series. Each folder holds the converted
scan, its sidecar (when dcm2niix produced one), the `.qa.nc` analysis artifact,
and a self-contained HTML report. `OUTPUT_DIR` is created if it does not exist. A
series whose folder already exists is never overwritten. It is refused and
reported, at no cost beyond the import it shared with the rest of the run.

Options (`--help` documents each in full and reads from the same constants as the
desktop panel's advanced-options fields):

- `--trim-sec SECONDS`: initial volumes to drop as non-steady-state.
- `--detrend {poly,spline}`: detrending method.
- `--center {image,phantom}`: slice and ROI localization.
- `--roi-size N`: fixed summary/Weisskoff ROI side, in voxels.
- `--anonymize {pii,all,none}`: what the published sidecar keeps.
- `--dcm2niix PATH`: use this dcm2niix executable instead of the bundled one.
- `--open`: once the run finishes, open the report in a browser if exactly one
  series was published, else the output directory (so a browser can list the
  series folders).
- `--version`: print the installed version and exit.

With neither `DICOM_DIR` nor `OUTPUT_DIR`, `fmri-qa-run` opens the desktop panel
described below. If `tkinter` has no display (no `$DISPLAY`) or this Python was
built without `tkinter`, it prints a message and exits `2`. Giving only one
directory, or any option without both, is a usage error, since the panel takes no
command-line options.

## The desktop panel

Start it with `fmri-qa-run` and no arguments, or with `fmri-qa-panel`. That is a
`gui-scripts` entry point, so on Windows it runs under `pythonw` with no console
window. The panel is one window, titled "fMRI QA":

- **DICOM folder** / **Output folder**: a text field and a "Browse…" button
  (`tkinter.filedialog.askdirectory`) for each.
- **Open the report when done**: checked by default (unlike `--open`, which
  defaults off). When a run publishes anything, its report (or the output folder,
  for several series) opens in a browser. An "Open results" button next to Run
  does the same on demand and is enabled whenever anything was published.
- **Show advanced options**: collapsed by default. It shows Trim, Detrend method,
  ROI center, and ROI size, worded as in `--help`, with a note that these change
  the numbers and are recorded in every report.
- **Run** reads the form. If anything is wrong (a bad number, a missing
  directory), a pop-up shows every problem at once. Otherwise it starts the run
  on a background thread so the window stays responsive. A progress bar and
  status line track each stage. A scrolling log records what `fmri-qa-run` sends
  to stderr, plus the finish summary (how many series published, and one line per
  refusal, failure, or warning). Cleanup warnings name any temporary directories
  left behind. They do not change the progress bar or the run result.
- **Closing the window** during a run asks it to stop after the series in
  progress finishes, and says so on the status line. It never stops mid-series.
  If no series has started, it stops after the import. Closing again before that
  closes the window immediately, and the run finishes unwinding in the background,
  so nothing partial is written to the output folder. Closing while idle closes
  immediately. A crash is always reported on the status line and in the log before
  any dialog, so the detail survives dismissing it.

### stdout / stderr / exit codes

- **stdout** carries only the path of each published report's HTML file, one per
  line, so the command composes (for example, piped into a viewer).
- **stderr** carries everything else: one progress line per stage of each series,
  one per refused series, one per failed series and its reason, one per warning,
  cleanup warnings naming leftover temporary directories (including after an
  error), and a final summary line (`# N of M series published to OUTPUT_DIR`).
- **Exit code** is `0` when every series found was published. It is `1` when any
  series was refused or failed, when the DICOM directory had no series to import,
  or when the run could not start (a bad request, a converter that could not
  run). It is `2` for a usage error. Cleanup warnings do not change it.

## What's here

- `request.RunRequest`: the parse-don't-validate boundary. Build one, or get one
  from `request.parse_form`, and every field is known good. `request.parse_form`
  converts a `request.FormValues` (the unparsed strings from a text field or
  dropdown). It collects every problem into one `exceptions.RequestError`, so a
  submission with several mistakes reports all of them at once.
- `outcome.Published` / `Refused` / `Failed` / `RunResult`: one outcome per
  series, plus the run's result. They are plain frozen values using only the
  standard library, so code that presents a run can import them without
  `fmriqa`'s analysis stack.
- `session.run_session`: the pipeline. It imports a DICOM directory, then for each
  series analyzes it, saves its `.qa.nc` artifact, renders a self-contained HTML
  report, and publishes all four files together under a directory named for the
  series. Work happens first in a staging directory under the system temporary
  directory. A finished series is copied out and renamed into place, so a reader
  of the output directory only sees finished series: never a report still
  rendering, or a report for a run that then failed. A sync client (OneDrive, a
  lab share) gets finished files only, never the converter's raw output or a file
  mid-rename. The files arrive in a hidden `.<series>.<token>.partial` directory
  that is renamed to the series name once complete. A run killed mid-copy can
  leave one behind, which is safe to delete. A refused cleanup also leaves one and
  reports its path to stderr or the panel log. The temporary directory needs room
  for the converted session plus one series in progress. It is wherever `TMPDIR`
  (or `TEMP` on Windows) says, so set it where `/tmp` is small or RAM-backed.
- **Refusal, not replacement.** A series whose name already exists in the output
  directory is left untouched and reported as refused.
- **Skip and report.** A failure in one series (an unreadable sidecar, too few
  volumes to analyze) never stops the run. It becomes a per-series failure
  outcome, and every other series is still attempted.
- `cli.main`: the `fmri-qa-run` command line above.
- `results.open_results`: what `--open` (and the panel's "Open the report when
  done" / "Open results") calls. It picks a single report or the output directory
  and opens it. It imports only `outcome`, so it loads without `fmriqa`'s analysis
  stack or `fmriqa_report`'s renderer.
- `worker.BackgroundRun`: runs `session.run_session` on its own non-daemon thread
  and delivers `Progress` and `CleanupNotice` events, then one terminal
  `Finished`/`Crashed` event, through a queue a caller polls. Running on a background thread is what keeps
  the panel responsive during a run. Separately, the module imports no `tkinter`.
- `panel_state.bar_state` / `panel_state.summarize`: the panel's pure decisions,
  namely where the progress bar sits for a given `Progress`, and what to tell a
  physicist once a run has finished. No `tkinter` import either.
- `panel.Panel` / `panel.run_panel` / `panel.main`: the desktop panel above. It is
  the only module here that imports `tkinter`. Nearly everything it decides comes
  from `request`, `worker` and `panel_state`. `run_panel` builds the window and
  runs its event loop (what `cli._launch_panel` calls). `main` is the
  `fmri-qa-panel` entry point. It has no console to report a missing display to,
  so it returns a plain exit code.

This package adds no third-party dependency of its own.
