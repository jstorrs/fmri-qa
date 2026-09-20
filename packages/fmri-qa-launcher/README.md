# fmri-qa-launcher

The application shell for [fmri-qa](../../README.md): a one-step "DICOM
directory in, one report directory per series out" pipeline built on top of
[`fmri-qa-core`](../fmri-qa-core) (conversion and analysis) and
[`fmri-qa-report`](../fmri-qa-report) (rendering). It adds no third-party
dependency of its own.

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
constants a future desktop panel's fields will):

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

With neither `DICOM_DIR` nor `OUTPUT_DIR` given, `fmri-qa-run` opens a desktop
panel instead -- not built yet, so today this prints a message explaining
that and exits `2`. Giving exactly one of the two directories, or any option
without both, is a usage error for the same reason: the panel (once it
exists) takes no command-line options of its own.

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
- `session.run_session` -- the pipeline itself: import a DICOM directory,
  then for each series analyze it, save its `.qa.nc` artifact, render a
  self-contained HTML report, and publish all four files (the converted scan,
  its sidecar, the archive, the report) together under one directory named
  for the series. Work happens in a hidden staging directory first, so a
  reader of the output directory only ever sees a series that is completely
  finished -- never one with a report still rendering, or a report for a run
  that then failed.
- **Refusal, not replacement.** A series whose name already exists in the
  output directory is left untouched and reported as refused; nothing here
  ever overwrites what an earlier run produced.
- **Skip and report.** A failure in one series (an unreadable sidecar, too
  few volumes to analyze) never stops the run -- it becomes a per-series
  failure outcome, and every other series is still attempted.
- `cli.main` -- the `fmri-qa-run` command line above.
- `results.open_results` -- what `--open` calls: pick a single report or the
  output directory, and open it. Kept apart from `session` so a future
  desktop panel's "open results" action can import it without pulling in
  `fmriqc`'s analysis stack or `fmriqc_report`'s renderer.
- A desktop panel, built on the same `request`/`session` core, is still to
  come.

This package adds no third-party dependency of its own.
