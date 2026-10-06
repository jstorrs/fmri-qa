# The desktop panel

The panel runs the same pipeline as the {doc}`command line <fmri-qa-run>`,
from one window titled "fMRI QA". Open it with `fmri-qa-panel`, or with
`fmri-qa-run` and no arguments. It needs `tkinter` and a graphical display;
`fmri-qa-run` explains on stderr when either is missing. `fmri-qa-panel`,
which may have no console to explain on, exits `2` without a message when
there is no display, and fails with Python's own import error (exit `1`) when
this Python has no `tkinter`.

## The form

- **DICOM folder** and **Output folder** — a text field and a "Browse..."
  button each, with the command line's description of the directory beneath.
- **Open the report when done** — checked by default, unlike the command
  line's `--open`: once a run publishes anything, its report opens in a
  browser, or the output folder when several series were published.
- **Show advanced options** — unchecked by default. Checking it shows the
  analysis settings: Trim, Detrend method, ROI center and ROI size, each
  starting at its default and described in the words `fmri-qa-run --help`
  uses, under a note that changing them changes the numbers and that every
  report records the settings used.

The panel has no field for `--anonymize` or `--dcm2niix`: a run from it keeps
the dates and strips the patient (`pii`), and uses the bundled dcm2niix, or
one on `PATH` if there is none.

## Running

**Run**, or Enter in a field, reads the form. If anything is wrong — a
folder left blank, a DICOM folder that does not exist, an output folder that
is the DICOM folder, a trim that is negative or not a number, an ROI size
that is not a positive whole number — a pop-up lists every problem
at once, and nothing starts. Otherwise the form is disabled and the run
starts in the background, so the window stays responsive.

While it runs, the progress bar pulses through the import, when the number
of series is not yet known, then fills in three steps per series: analysis,
report and publish. The status line under it shows the stage in progress, and
the log below records each stage line, the same lines `fmri-qa-run` writes to
stderr.

When the run ends, the status line gives the outcome — how many series were
published, or that every series already had results — and the log adds one
line per series (published, skipped because its results already exist, or
failed and why) and one per warning. The bar comes to rest at the share of
series that were published. **Open results**, beside Run, is enabled whenever
anything was published, and opens what "Open the report when done" would.

## When a run fails

A run that cannot finish at all — the output folder could not be created or
written to, or the import failed or found no series — is reported on the status
line and in the log first, then in an error pop-up, so the message is still
there after the pop-up is dismissed. An unexpected error also puts its full
traceback in the log, to copy to whoever supports the panel. Either way the
form is enabled again for another run.

## Closing the window

- **While idle**, the window closes at once.
- **During a run**, the first close asks the run to stop and says so on the
  status line. A run stops only between series, never in the middle of one:
  it finishes the series in progress, or, if it is still importing, the
  import, and then the window closes.
- **A second close** closes the window at once, without waiting. The run
  still stops at the same point, in the background, before the program
  exits, so nothing half-written is left in the output folder.
