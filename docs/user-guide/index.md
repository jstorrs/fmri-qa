# User guide

## Running QA

fmri-qa takes a phantom fMRI series as DICOM and gives back a report and its
numbers. Three ways to run it:

- **{doc}`In the browser <browser>`**, with nothing to install. Good for trying
  it, or for a machine where nothing can be installed.
- **{doc}`The desktop panel <panel>`**, a window that runs a DICOM folder into
  one report folder per series.
- **{doc}`fmri-qa-run`**, the same run from a terminal or a script.

The panel and the commands need {doc}`installing <install>` first.

```{toctree}
:maxdepth: 1

install
browser
panel
fmri-qa-run
run-output
```

## Reading the results

The report is one HTML page per series: the headline numbers, any localization
or clipping warning, the settings, the figures, and how each metric is defined.
It applies no pass or fail thresholds. Each analysis has a page with its
purpose, method and equations, and a figure from a synthetic phantom.

```{toctree}
:maxdepth: 2

report-page
analyses/index
```

- **"What does this number mean?"**: find it in the
  [list of analyses](analyses/index.md), which names every measurement.
- **"Can I trust this figure?"**: every figure on these pages is drawn when the
  documentation is built, by running the pipeline on a synthetic phantom. A
  figure that stopped matching the code would fail the build.

## Step by step, and trending

`fmri-qa-run` converts, analyzes and reports in one go. The steps are also
commands of their own, for keeping the numbers over time or building your own
workflow:

```{toctree}
:maxdepth: 1

fmri-qa-import
fmri-qa
fmri-qa-report
analysis-file
```

- **{doc}`fmri-qa-import`** converts DICOM to NIfTI with QA-safe dcm2niix
  settings and names that sort.
- **{doc}`fmri-qa`** analyzes NIfTI scans into a table, JSON for a trend
  database, or analysis files. `fmri-qa-hilo` is on the same page.
- **{doc}`fmri-qa-report`** renders an analysis file as a report.
- **{doc}`The analysis file <analysis-file>`** (`.qa.nc`) holds every number, curve and
  image, and opens in MATLAB, R and Python.

## From Python

```{toctree}
:maxdepth: 1

report-library
developers
```

- **{doc}`report-library`**: render a report from your own code, in your own
  colors.
- **{doc}`developers`**: the packages, calculating from Python, building the
  project, and the design notes.
