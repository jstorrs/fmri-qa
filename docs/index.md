# fmri-qa

Phantom fMRI quality-assurance metrics, following the Glover/FBIRN stability
protocol (Friedman & Glover, 2006). Given a 4-D phantom time series, `fmri-qa`
measures how stable the scanner was while it acquired it — SNR, SFNR, the
Weisskoff radius of decorrelation, drift, temporal fluctuation and Nyquist
ghosting — and publishes the result as a single netCDF-4 file that a report, a
spreadsheet, or a trend database reads.

```{toctree}
:hidden:

user-guide/index
```

## The packages

- **[fmri-qa-core](user-guide/index.md#what-is-calculated-and-how)** — what
  is calculated, and how: a page per analysis with its equations, a figure
  rendered by running the pipeline over a synthetic phantom, and exactly what
  it contributes to the analysis artifact, plus a page on the artifact file
  itself.
- **[fmri-qa-report](user-guide/index.md#rendering-the-result)** — how an
  artifact becomes a single self-contained HTML page: the command, what the
  page shows and what it needs from a browser, and rendering one from Python.
- **[fmri-qa-launcher](user-guide/index.md#dicom-in-reports-out)** — the whole
  pipeline in one step, from a DICOM directory to one report folder per
  series: the `fmri-qa-run` command, the desktop panel, and what a run writes.

## Where to start

- **"How do I run QA on a phantom series?"** —
  {doc}`the command line </user-guide/fmri-qa-run>`, or
  {doc}`the desktop panel </user-guide/panel>` without a terminal.
- **"What does this number mean?"** — find it in
  {doc}`/user-guide/analyses/index`; every measurement is listed there against
  the page that publishes it.
- **"How do I open a `.qa.nc` file?"** — {doc}`/user-guide/artifact` has the
  MATLAB, R and Python recipes, and the dimensions and coordinates the file is
  laid out on.
- **"How do I make a report from one?"** — {doc}`/user-guide/fmri-qa-report`.
- **"Can I put a report on our website?"** — {doc}`/user-guide/report-page`
  says what the file contains and what an embedding site's
  Content-Security-Policy has to allow.

Installing, importing DICOM on its own with `fmri-qa-import`, and the `fmri-qa`
command line are covered in the repository's `README.md`.
