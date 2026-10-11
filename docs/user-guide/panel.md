# The desktop panel

The panel runs the same pipeline as the {doc}`command line <fmri-qa-run>` from
one window titled "fMRI QA". Open it with `fmri-qa-panel`, or `fmri-qa-run` with
no arguments. It needs `tkinter` and a graphical display. `fmri-qa-run` says on
stderr when either is missing. `fmri-qa-panel` may have no console, so with no
display it exits `2` silently, and with no `tkinter` it fails with Python's
import error (exit `1`).

## The form

- **DICOM folder** and **Output folder**: a text field and a "Browse..." button
  each, with the command line's description beneath.
- **Open the report when done**: checked by default, unlike `--open`. When a run
  publishes anything, its report opens in a browser, or the output folder if
  several series were published.
- **Show advanced options**: unchecked by default. It shows Trim, Detrend method,
  ROI center and ROI size, each at its default and worded as in
  `fmri-qa-run --help`. A note says that changing them changes the numbers and
  that every report records the settings used.

The panel has no field for `--anonymize` or `--dcm2niix`. It keeps the dates and
strips the patient (`pii`), and uses the bundled dcm2niix, or one on `PATH` if
there is none.

## Running

**Run**, or Enter in a field, reads the form. If anything is wrong (a blank
folder, a DICOM folder that does not exist, an output folder that is the DICOM
folder, a negative or non-numeric trim, an ROI size that is not a positive whole
number), a pop-up lists every problem and nothing starts. Otherwise the form is
disabled and the run starts in the background, so the window stays responsive.

The progress bar pulses through the import, while the number of series is
unknown, then fills in three steps per series: analysis, report and publish. The
status line shows the current stage, and the log records each stage line, the
same lines `fmri-qa-run` writes to stderr.

When the run ends, the status line gives the outcome: how many series were
published, or that every series already had results. The log adds one line per
series (published, skipped because its results exist, or failed and why) and one
per warning. The bar stops at the share of series published. **Open results**,
beside Run, is enabled whenever anything was published and opens what "Open the
report when done" would.

## When a run fails

A run that cannot finish (the output folder could not be created or written to, or
the import failed or found no series) is reported on the status line and in the
log, then in an error pop-up, so the message survives dismissing it. An
unexpected error also puts its full traceback in the log, to copy to whoever
supports the panel. Either way the form is enabled again.

## Closing the window

- **While idle**, the window closes at once.
- **During a run**, the first close asks the run to stop and says so on the
  status line. A run stops only between series. It finishes the series in
  progress, or the import if that is still running, and then the window closes.
- **A second close** closes the window at once. The run still stops at the same
  point, in the background, before the program exits, so nothing half-written is
  left in the output folder.
