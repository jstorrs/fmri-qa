# User guide

## What is calculated, and how

Phantom fMRI quality-assurance metrics, following the Glover/FBIRN stability
protocol. Given a 4-D phantom time series, `fmri-qa` measures how stable the
scanner was during the acquisition and publishes the result as a single netCDF-4
file that a report, a spreadsheet, or a trend database can read.

These pages document the calculation, which belongs to `fmri-qa-core`. Reading the
scan and writing the file belong to `fmri-qa-io`, and the `fmri-qa` command to
`fmri-qa-cli`. Each analysis has a page covering what it is for, the computation
with its equations and settings, a figure, and a table of what it adds to the
artifact, under the names you will find in the file.

```{toctree}
:maxdepth: 2

analyses/index
artifact
```

- **"What does this number mean?"**: find it in the
  [analysis index](analyses/index.md), which lists every measurement against the
  page that publishes it.
- **"How do I open this file?"**: [the analysis artifact](artifact.md) has the
  MATLAB, R, Python and `ncdump` recipes, the dimensions and coordinates, and
  the rule that separates a NaN from an absent value.
- **"Can I trust this figure?"**: every figure on these pages is rendered when
  the documentation is built, by running the installed pipeline on a synthetic
  phantom (`docs/phantom.py`). A figure that stopped matching the package would
  fail the build instead of going stale.

## Rendering the result

`fmri-qa-report` is the presentation half of fmri-qa. It renders one
{doc}`analysis artifact <artifact>` into a single self-contained HTML page that
opens by double-click, with no network and no companion file.

The artifact is its only input. `fmri-qa-core` computed and stored every number,
curve, mask and image the report draws, so a report can be rendered on another
machine, long after the scan, with no acquisition data. An artifact read from
disk renders the same as a fresh one. Nothing here recomputes a metric.

Inside, content is separate from format. `summary` and `content` build the text,
`panels` draws the matplotlib figures, and `formats/` holds one driver per output
format. HTML is the only format today. Another would be a new driver reusing the
same content and panels.

```{toctree}
:maxdepth: 2

fmri-qa-report
report-page
report-library
```

- **"How do I turn a `.qa.nc` into a page?"**: {doc}`fmri-qa-report`.
- **"Can I put this on our website, or attach it to a QA record?"**:
  {doc}`report-page` says what the file contains, what it needs from the
  browser, and what an embedding site's Content-Security-Policy has to allow.
- **"Can I render one from my own code, in our colors?"**:
  {doc}`report-library`.

## DICOM in, reports out

`fmri-qa-launcher` is the application shell of fmri-qa. In one step, it takes a
directory of DICOM files and writes one folder per series. Each folder holds the
converted scan, its {doc}`analysis artifact <artifact>` and a self-contained HTML
report.

It computes and draws nothing itself. Conversion belongs to `fmri-qa-io`,
analysis to `fmri-qa-core` and rendering to `fmri-qa-report`. Settings default
to core's, so the numbers match a `fmri-qa` run by hand. This package adds the
sequence (import, then analyze, archive, render and publish each series) and
guarantees a series appears in the output folder only once all its files are
finished. It adds no third-party dependency. The desktop panel uses the
standard library's `tkinter`.

### Two entry points

- **`fmri-qa-run`** is the console command. Given a DICOM directory and an
  output directory it runs once and reports on stdout and stderr; given
  neither, it opens the desktop panel.
- **`fmri-qa-panel`** opens the panel directly. It is installed as a GUI script,
  so on Windows it runs under `pythonw` with no console window. `fmri-qa-run`
  stays a console program because its output contract needs one.

### The single-file executable

`make bundle` builds `fmri-qa-run` as one executable, with the interpreter,
all five packages and dcm2niix inside, for a machine with no Python. It is
built with PyInstaller from an environment resolved from `uv.lock`, into
`dist/bundle`. PyInstaller does not cross-compile, so the executable only runs
on the platform it was built on. On Windows, where there is no `make`,
`scripts/bundle.ps1` runs the same commands. Run with no arguments, the
executable opens the panel like the installed command.

```{toctree}
:maxdepth: 2

fmri-qa-run
panel
run-output
```

- **"How do I run it from a terminal or a script?"**: {doc}`fmri-qa-run`.
- **"How do I run it without a terminal?"**: {doc}`panel`.
- **"What ends up in the output folder, and what if a run is interrupted?"**:
  {doc}`run-output`.
