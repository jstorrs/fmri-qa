# User guide

## Running an analysis

fmri-qa takes a phantom fMRI series in DICOM format and produces a report
together with its numerical results. It can be run in three ways:

- **{doc}`In the browser <browser>`**, with no installation. This suits a first
  trial, or a computer on which software cannot be installed.
- **{doc}`From the desktop panel <panel>`**, a window that processes a DICOM
  folder into one report folder per series.
- **{doc}`With fmri-qa-run <fmri-qa-run>`**, which performs the same run from a
  terminal or a script.

The panel and the commands require {doc}`installation <install>`.

```{toctree}
:maxdepth: 1

install
browser
panel
fmri-qa-run
run-output
```

## Interpreting the results

The report is a single HTML page per series. It presents the headline
measurements, any localization or clipping warning, the settings, the figures,
and the definition of each metric. It applies no pass or fail thresholds. Each
analysis is documented on a page of its own, which states its purpose, method
and equations and includes a figure computed from a synthetic phantom.

```{toctree}
:maxdepth: 2

report-page
analyses/index
```

The [list of analyses](analyses/index.md) names every measurement and links to
the page that defines it. The figures on those pages are generated when the
documentation is built, by running the pipeline on a synthetic phantom. A figure
that no longer agreed with the code would cause the build to fail.

## Individual stages and longitudinal tracking

`fmri-qa-run` converts, analyzes and reports in a single step. Each stage is
also available as a separate command, for retaining the results over time or for
constructing a custom workflow:

```{toctree}
:maxdepth: 1

fmri-qa-import
fmri-qa
fmri-qa-report
analysis-file
```

- **{doc}`fmri-qa-import`** converts DICOM to NIfTI with dcm2niix settings that
  preserve the validity of the QA checks, and assigns names that sort
  chronologically.
- **{doc}`fmri-qa`** analyzes NIfTI scans and produces a table, JSON for a trend
  database, or analysis files. `fmri-qa-hilo` is described on the same page.
- **{doc}`fmri-qa-report`** renders an analysis file as a report.
- **{doc}`The analysis file <analysis-file>`** (`.qa.nc`) contains every number,
  curve and image, and can be opened in MATLAB, R and Python.

## Use from Python

```{toctree}
:maxdepth: 1

report-library
developers
```

- **{doc}`report-library`** describes how to render a report from user code,
  with custom colors.
- **{doc}`developers`** covers the packages, calculation from Python, building
  the project, and the design notes.
