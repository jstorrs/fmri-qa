# fmri-qa-launcher: DICOM in, reports out

The application shell of fmri-qa. It takes a directory of DICOM files and
writes one folder per series, each holding the converted scan, its
{external+core:doc}`analysis artifact <artifact>` and a self-contained HTML
report, in one step.

It computes nothing and draws nothing itself. Conversion and analysis are
{external+core:doc}`fmri-qa-core <index>`'s, rendering is
{external+report:doc}`fmri-qa-report <index>`'s, and the analysis settings
default to core's own, so the numbers match a `fmri-qa` run by hand. What this
package adds is the sequence around them — import, then analyze, archive,
render and publish each series — and the guarantee that a series appears in
the output folder only once all of its files are finished. It adds no
third-party dependency of its own: the desktop panel is built on `tkinter`,
from the standard library.

## Two entry points

- **`fmri-qa-run`** is the console command. Given a DICOM directory and an
  output directory it runs once and reports on stdout and stderr; given
  neither, it opens the desktop panel.
- **`fmri-qa-panel`** opens the panel directly. It is installed as a GUI
  script rather than a second console one: on Windows it runs under
  `pythonw`, with no console window, while `fmri-qa-run` stays a console
  program because its output contract needs one.

## The single-file executable

`make bundle` builds `fmri-qa-run` as one executable, with the interpreter,
all three packages and dcm2niix inside, for a machine with no Python. It is
built with PyInstaller from an environment resolved from `uv.lock`, into
`dist/bundle`. PyInstaller does not cross-compile, so the executable is for
the platform it was built on; on Windows, where there is no `make`,
`scripts/bundle.ps1` runs the same commands. Run with no arguments, the
executable opens the panel like the installed command does.

```{toctree}
:maxdepth: 2

command-line
panel
output
```

## Where to start

- **"How do I run it from a terminal or a script?"** — {doc}`command-line`.
- **"How do I run it without a terminal?"** — {doc}`panel`.
- **"What ends up in the output folder, and what if a run is interrupted?"**
  — {doc}`output`.
