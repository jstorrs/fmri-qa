# User guide

## What is calculated, and how

Phantom fMRI quality-assurance metrics, following the Glover/fBIRN stability
protocol. Given a 4-D phantom time series, `fmri-qa` measures how stable the
scanner was while it acquired it, and publishes the result as a single netCDF-4
file that a report, a spreadsheet, or a trend database reads.

These pages document the calculation, which is `fmri-qa-core`'s. There is one
page per analysis: what it is for, the computation with its equations and
settings, a figure, and a table of exactly what it contributes to the artifact
under the names a reader will find in the file.

```{toctree}
:maxdepth: 2

analyses/index
artifact
```

- **"What does this number mean?"** — find it in the
  [analysis index](analyses/index.md); every measurement is listed there
  against the page that publishes it.
- **"How do I open this file?"** — [the analysis artifact](artifact.md) has the
  MATLAB, R, Python and `ncdump` recipes, the dimensions and coordinates, and
  the rule that separates a NaN from an absent value.
- **"Can I trust this figure?"** — every figure on these pages is rendered
  while the documentation is built, by running the installed pipeline over a
  synthetic phantom (`docs/phantom.py`). A figure that stopped matching the
  package would fail the build rather than go stale.

## Rendering the result

`fmri-qa-report` is the presentation half of fmri-qa. It renders one
{doc}`analysis artifact <artifact>` into a single self-contained HTML page that
opens by double-click, with no network and no companion file.

The artifact is its only input. Every number, curve, mask and image a report
draws was computed by `fmri-qa-core` and stored in the file, so a report can be
rendered on another machine, long after the scan, with none of the acquisition
data at hand — and an artifact read back from disk renders exactly like one
just computed. Nothing here recomputes a metric.

Inside, content is kept separate from format: `summary` and `content` build the
text, `panels` draws the matplotlib figures, and `formats/` holds one driver
per output format. HTML is the one format today; another would be a new driver
reusing the same content and panels.

```{toctree}
:maxdepth: 2

fmri-qa-report
report-page
report-library
```

- **"How do I turn a `.qa.nc` into a page?"** — {doc}`fmri-qa-report`.
- **"Can I put this on our website, or attach it to a QA record?"** —
  {doc}`report-page` says what the file contains, what it needs from the
  browser, and what an embedding site's Content-Security-Policy has to allow.
- **"Can I render one from my own code, in our colors?"** —
  {doc}`report-library`.

## DICOM in, reports out

`fmri-qa-launcher` is the application shell of fmri-qa. It takes a directory
of DICOM files and writes one folder per series, each holding the converted
scan, its {doc}`analysis artifact <artifact>` and a self-contained HTML
report, in one step.

It computes nothing and draws nothing itself. Conversion and analysis are
`fmri-qa-core`'s, rendering is `fmri-qa-report`'s, and the analysis settings
default to core's own, so the numbers match a `fmri-qa` run by hand. What this
package adds is the sequence around them — import, then analyze, archive,
render and publish each series — and the guarantee that a series appears in
the output folder only once all of its files are finished. It adds no
third-party dependency of its own: the desktop panel is built on `tkinter`,
from the standard library.

### Two entry points

- **`fmri-qa-run`** is the console command. Given a DICOM directory and an
  output directory it runs once and reports on stdout and stderr; given
  neither, it opens the desktop panel.
- **`fmri-qa-panel`** opens the panel directly. It is installed as a GUI
  script rather than a second console one: on Windows it runs under
  `pythonw`, with no console window, while `fmri-qa-run` stays a console
  program because its output contract needs one.

### The single-file executable

`make bundle` builds `fmri-qa-run` as one executable, with the interpreter,
all three packages and dcm2niix inside, for a machine with no Python. It is
built with PyInstaller from an environment resolved from `uv.lock`, into
`dist/bundle`. PyInstaller does not cross-compile, so the executable is for
the platform it was built on; on Windows, where there is no `make`,
`scripts/bundle.ps1` runs the same commands. Run with no arguments, the
executable opens the panel like the installed command does.

```{toctree}
:maxdepth: 2

fmri-qa-run
panel
run-output
```

- **"How do I run it from a terminal or a script?"** — {doc}`fmri-qa-run`.
- **"How do I run it without a terminal?"** — {doc}`panel`.
- **"What ends up in the output folder, and what if a run is interrupted?"**
  — {doc}`run-output`.
