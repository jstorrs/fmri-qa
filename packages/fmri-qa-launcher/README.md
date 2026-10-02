# fmri-qa-launcher

The application shell for [fmri-qa](../../README.md): a one-step "DICOM
directory in, one report directory per series out" pipeline built on top of
[`fmri-qa-core`](../fmri-qa-core) (conversion and analysis) and
[`fmri-qa-report`](../fmri-qa-report) (rendering). It adds no third-party
dependency of its own.

The pages in [`docs/`](docs/index.md) cover the command line, the panel, and
what a run writes. Build them from the workspace root with `make sync-docs &&
make docs`; they land under `build/site/launcher`.

## `fmri-qa-run`

```
fmri-qa-run DICOM_DIR OUTPUT_DIR [options]
```

Imports every series it finds under `DICOM_DIR`, analyzes each, and writes
one folder per series under `OUTPUT_DIR`, named for the series, holding four
files: the converted scan, its sidecar (when dcm2niix produced one), the
`.qa.nc` analysis archive, and a self-contained HTML report. `OUTPUT_DIR` is
created if it does not exist. A series whose folder already exists there is
never overwritten -- it is refused and reported, at no cost beyond the import
it shared with the rest of the run.

Options (each documented in full by `--help`, which reads from the same
constants the desktop panel's advanced-options fields do):

- `--trim-sec SECONDS` -- initial volumes to drop as non-steady-state.
- `--detrend {poly,spline}` -- detrending method.
- `--center {image,phantom}` -- slice and ROI localization.
- `--roi-size N` -- fixed summary/Weisskoff ROI side, in voxels.
- `--anonymize {pii,all,none}` -- what the published sidecar keeps.
- `--dcm2niix PATH` -- use this dcm2niix executable instead of the bundled
  one.
- `--open` -- once the run finishes, open the report in a browser if exactly
  one series was published, else the output directory (so a browser can list
  the series folders).
- `--version` -- print the installed version and exit.

With neither `DICOM_DIR` nor `OUTPUT_DIR` given, `fmri-qa-run` opens the
desktop panel described below. If `tkinter` has no display to attach to (no
`$DISPLAY`), or this Python was built without `tkinter` at all, it prints a
message explaining that and exits `2` instead. Giving exactly one of the two
directories, or any option without both, is a usage error for the same
reason: the panel takes no command-line options of its own.

## The desktop panel

Start it with `fmri-qa-run` and no arguments, or directly with
`fmri-qa-panel` (a `gui-scripts` entry point -- on Windows this runs under
`pythonw`, with no console window at all). One window, titled "fMRI QA":

- **DICOM folder** / **Output folder** -- a text field plus a "Browse…"
  button (`tkinter.filedialog.askdirectory`) for each.
- **Open the report when done** -- checked by default in the panel (unlike
  `fmri-qa-run`'s own `--open`, which defaults off): once a run finishes with
  something published, its report (or the output folder, for several series)
  opens in a browser automatically. An "Open results" button next to Run
  does the same thing on demand, and is enabled whenever anything was
  published.
- **Show advanced options** -- collapsed by default; expanding it shows an
  "Advanced options" frame with Trim, Detrend method, ROI center, and ROI
  size, each with the same wording `--help` uses, and a note that these
  change the numbers and are recorded in every report.
- **Run** reads the form, shows every problem at once in a pop-up if
  anything is wrong (a bad number, a missing directory), and otherwise
  starts the run on a background thread so the window stays responsive. A
  progress bar and a status line track the run stage by stage; a scrolling
  log records the same detail `fmri-qa-run` sends to stderr, plus the finish
  summary (how many series published, and one line per refusal, failure, or
  warning).
- **Closing the window** while a run is in progress asks it to stop after
  the series in progress finishes (never mid-series; or after import itself
  finishes, if closed before any series has started), and says so on the
  status line. Closing a second time, before that happens, closes the window
  immediately instead of waiting -- the run itself still finishes unwinding
  in the background, so nothing partial is ever written to the output
  folder. Closing while idle closes immediately. Either way, a crash is
  always reported on the status line and in the log before any dialog, so
  the detail survives dismissing it.

### stdout / stderr / exit codes

- **stdout** carries only the path of each published report's HTML file, one
  per line -- nothing else, so the command composes (e.g. piped into a
  viewer that opens each in turn).
- **stderr** carries everything else: one line of progress per stage of each
  series, one line per refused series, one line per failed series and its
  reason, one line per warning a series raised along the way, and a final
  summary line (`# N of M series published to OUTPUT_DIR`).
- **Exit code** is `0` when every series found was published; `1` when any
  series was refused or failed, when the DICOM directory produced no series
  to import, or when the run could not start at all (a bad request, a
  converter that could not run); `2` for a command-line usage error.

## What's here

- `request.RunRequest` -- the parse-don't-validate boundary: build one (or
  get one from `request.parse_form`, given a form's raw text) and every field
  is already known good. `request.parse_form` converts a `request.FormValues`
  -- the strings a text field or a dropdown holds, unparsed -- collecting
  every problem it finds into one `exceptions.RequestError` rather than
  stopping at the first, so a submission with several mistakes is reported
  with all of them at once.
- `outcome.Published` / `Refused` / `Failed` / `RunResult` -- what a run
  reports: one outcome per series, and the run's result. Plain frozen values
  with no dependency beyond the standard library, so everything that only
  presents a run imports them without `fmriqc`'s analysis stack.
- `session.run_session` -- the pipeline itself: import a DICOM directory,
  then for each series analyze it, save its `.qa.nc` artifact, render a
  self-contained HTML report, and publish all four files (the converted scan,
  its sidecar, the archive, the report) together under one directory named
  for the series. Work happens in a staging directory under the system's
  temporary directory first, and a finished series is copied out and renamed
  into place, so a reader of the output directory only ever sees a series
  that is completely finished -- never one with a report still rendering, or
  a report for a run that then failed -- and a sync client watching it
  (OneDrive, a lab share) is handed finished files only, never the
  converter's raw output or a file on its way to being renamed. Those files
  arrive in a hidden `.<series>.<token>.partial` directory that is renamed
  to the series name once complete; a run killed outright mid-copy can leave
  one behind, which is safe to delete. The temporary directory needs room
  for the converted session plus one series being worked on, and is wherever
  `TMPDIR` (or `TEMP` on Windows) says -- worth setting where `/tmp` is small
  or RAM-backed.
- **Refusal, not replacement.** A series whose name already exists in the
  output directory is left untouched and reported as refused; nothing here
  ever overwrites what an earlier run produced.
- **Skip and report.** A failure in one series (an unreadable sidecar, too
  few volumes to analyze) never stops the run -- it becomes a per-series
  failure outcome, and every other series is still attempted.
- `cli.main` -- the `fmri-qa-run` command line above.
- `results.open_results` -- what `--open` (and the panel's "Open when done" /
  "Open results") calls: pick a single report or the output directory, and
  open it. Imports only `outcome`, so it loads without `fmriqc`'s analysis stack or
  `fmriqc_report`'s renderer.
- `worker.BackgroundRun` -- runs `session.run_session` on its own
  non-daemon thread, delivering `Progress` events and one terminal
  `Finished`/`Crashed` event through a queue a caller polls. No `tkinter`
  import; this is what lets the panel stay responsive during a run.
- `panel_state.bar_state` / `panel_state.summarize` -- the panel's pure
  decisions: where the progress bar sits for a given `Progress`, and what to
  tell a physicist once a run has finished. No `tkinter` import either.
- `panel.Panel` / `panel.run_panel` / `panel.main` -- the desktop panel
  described above. The only module here that imports `tkinter`; almost
  everything it decides comes from `request`/`worker`/`panel_state` above
  it. `run_panel` builds the window and runs its event loop (what
  `cli._launch_panel` calls); `main` is the `fmri-qa-panel` gui-script entry
  point, which has no console to report a missing display to and so returns
  a plain exit code instead.

This package adds no third-party dependency of its own.
