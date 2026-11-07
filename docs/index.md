# fmri-qa

Phantom fMRI quality-assurance metrics, following the Glover/FBIRN stability
protocol (Friedman & Glover, 2006). Given a 4-D phantom time series, `fmri-qa`
measures how stable the scanner was during the acquisition: SNR, SFNR, the
Weisskoff radius of decorrelation, drift, temporal fluctuation and Nyquist
ghosting. It publishes the result as a single netCDF-4 file that a report, a
spreadsheet, or a trend database can read.

To try it without installing anything, [open fmri-qa in your
browser](https://jstorrs.github.io/fmri-qa/app/). It is a single HTML file:
give it DICOM, choose the series, and it converts them with dcm2niix and
analyzes each one on your machine, sending nothing anywhere. You can save the file and
run it offline. The source is [on GitHub](https://github.com/jstorrs/fmri-qa).

```{toctree}
:hidden:

user-guide/index
api/index
```

## The packages

- **[fmri-qa-core](user-guide/index.md#what-is-calculated-and-how)**: what is
  calculated and how. Each analysis has a page with its equations, a figure from
  running the pipeline on a synthetic phantom, and what it adds to the analysis
  artifact. Another page covers the artifact file itself. Core is pure
  calculation and reads no files, so it can run in a browser.
- **fmri-qa-io** and **fmri-qa-cli**: the file boundary and the commands.
  `fmri-qa-io` reads scans, saves and loads the artifact file, and imports DICOM.
  `fmri-qa-cli` is the `fmri-qa`, `fmri-qa-hilo`, `fmri-qa-import` and
  `fmri-qa-report` commands over core, io and report. `fmri-qa`,
  `fmri-qa-hilo` and `fmri-qa-import` have no user-guide section of their own;
  `fmri-qa-report` has one, below. The {doc}`Python API </api/index>` is
  documented, and the repository's `README.md` covers the commands.
- **[fmri-qa-report](user-guide/index.md#rendering-the-result)**: how an
  artifact becomes a single self-contained HTML page. It covers the command
  (installed by `fmri-qa-cli`), what the page shows and needs from a browser,
  and rendering one from Python.
- **[fmri-qa-launcher](user-guide/index.md#dicom-in-reports-out)**: the whole
  pipeline in one step, from a DICOM directory to one report folder per series.
  It covers the `fmri-qa-run` command, the desktop panel, and what a run writes.

## Where to start

- **"How do I run QA on a phantom series?"**:
  {doc}`the command line </user-guide/fmri-qa-run>`, or
  {doc}`the desktop panel </user-guide/panel>` without a terminal.
- **"What does this number mean?"**: find it in
  {doc}`/user-guide/analyses/index`, which lists every measurement against the
  page that publishes it.
- **"How do I open a `.qa.nc` file?"**: {doc}`/user-guide/artifact` has the
  MATLAB, R and Python recipes, and the dimensions and coordinates of the file.
- **"How do I make a report from one?"**: {doc}`/user-guide/fmri-qa-report`.
- **"Can I put a report on our website?"**: {doc}`/user-guide/report-page`
  says what the file contains and what an embedding site's
  Content-Security-Policy has to allow.
- **"Calling it from Python?"**: {doc}`/api/index` lists the public API of each
  package, and the building blocks beneath it.

Installing, importing DICOM on its own with `fmri-qa-import`, and the `fmri-qa`
command line are covered in the repository's `README.md`.
