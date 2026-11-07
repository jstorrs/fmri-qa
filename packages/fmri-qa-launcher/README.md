# fmri-qa-launcher

The application shell for [fmri-qa](../../README.md): a one-step pipeline that
takes a DICOM directory and writes one report directory per series. It is built
on [`fmri-qa-core`](../fmri-qa-core) (analysis),
[`fmri-qa-io`](../fmri-qa-io) (files and conversion) and
[`fmri-qa-report`](../fmri-qa-report) (rendering), and borrows two argument
parsers from [`fmri-qa-cli`](../fmri-qa-cli). It adds no third-party dependency
of its own.

```console
$ fmri-qa-run DICOM_DIR OUTPUT_DIR [options]
```

`fmri-qa-run` imports every series under `DICOM_DIR`, analyzes each, and writes
one folder per series under `OUTPUT_DIR` with the converted scan, its sidecar,
the `.qa.nc` analysis file and a self-contained HTML report. With no arguments,
or as `fmri-qa-panel`, it opens a desktop panel that does the same. The user
guide documents [the command](https://jstorrs.github.io/fmri-qa/user-guide/fmri-qa-run.html), including
its options, output and exit codes, [the panel](https://jstorrs.github.io/fmri-qa/user-guide/panel.html)
and [what a run writes](https://jstorrs.github.io/fmri-qa/user-guide/run-output.html).

`--help` and the panel's advanced-options fields read their wording from the same
constants. `fmri-qa-panel` is a `gui-scripts` entry point, so on Windows it runs
under `pythonw` with no console window.

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
  series analyzes it, saves its `.qa.nc` analysis file, renders a self-contained HTML
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
