# The desktop panel

The panel runs the same pipeline as the {doc}`command line <fmri-qa-run>` from a
single window titled "fMRI QA". It is opened with `fmri-qa-panel`, or with
`fmri-qa-run` given no arguments, and it requires `tkinter` and a graphical
display. `fmri-qa-run` reports on stderr when either is missing.
`fmri-qa-panel` may have no console. Without a display it therefore exits with
status `2` and no message, and without `tkinter` it fails with Python's import
error (status `1`).

## The form

- **DICOM folder** and **Output folder** each have a text field and a
  "Browse..." button, with the description from the command line beneath.
- **Open the report when done** is checked by default, unlike `--open`. When a
  run publishes anything, the report opens in a browser, or the output folder
  opens if several series were published.
- **Show advanced options** is unchecked by default. It reveals Trim, Detrend
  method, ROI center and ROI size, each at its default value and worded as in
  `fmri-qa-run --help`. A note states that changing them changes the results and
  that every report records the settings used.

The panel has no field for `--anonymize` or `--dcm2niix`. It retains the dates
and removes the patient identifiers (`pii`), and it uses the bundled dcm2niix,
or one found on `PATH` when none is bundled.

## Running

**Run**, or Enter in a field, validates the form. If any entry is invalid (a
blank folder, a DICOM folder that does not exist, an output folder identical to
the DICOM folder, a trim that is negative or not a number, or an ROI size that
is not a positive whole number), a dialog lists every problem and nothing is
started. Otherwise the form is disabled and the run proceeds in the background,
so the window remains responsive.

The progress bar is indeterminate during the import, while the number of series
is unknown, and then advances in three steps per series: analysis, report, and
publication. The status line shows the current stage, and the log records each
stage with the same lines that `fmri-qa-run` writes to stderr.

When the run ends, the status line states the outcome: the number of series
published, or that every series already had results. The log adds one line per
series (published, skipped because its results exist, or failed, with the
reason) and one per warning. The bar stops at the fraction of series published.
**Open results**, beside Run, is enabled whenever anything was published, and it
opens what "Open the report when done" would have opened.

## Failed runs

A run that cannot complete, because the output folder could not be created or
written to, or because the import failed or found no series, is reported on the
status line and in the log, and then in an error dialog, so that the message
remains after the dialog is dismissed. An unexpected error also writes its full
traceback to the log, from which it can be copied for whoever supports the
panel. In either case the form is enabled again.

## Closing the window

- **While idle**, the window closes immediately.
- **During a run**, the first request to close asks the run to stop and says so
  on the status line. A run stops only between series. It completes the series
  in progress, or the import if that is still running, and the window then
  closes.
- **A second request** closes the window immediately. The run still stops at
  the same point, in the background, before the program exits, so that nothing
  partially written remains in the output folder.
