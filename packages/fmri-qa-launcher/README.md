# fmri-qa-launcher

The application shell for [fmri-qa](../../README.md): a one-step "DICOM
directory in, one report directory per series out" pipeline built on top of
[`fmri-qa-core`](../fmri-qa-core) (conversion and analysis) and
[`fmri-qa-report`](../fmri-qa-report) (rendering). It adds no third-party
dependency of its own.

## What's here

The functional core is done; a command line and a desktop panel, both built
on top of it, are still to come.

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

This package adds no third-party dependency of its own.
