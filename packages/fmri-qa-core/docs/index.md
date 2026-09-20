# fmri-qa: what is calculated, and how

Phantom fMRI quality-assurance metrics, following the Glover/fBIRN stability
protocol. Given a 4-D phantom time series, `fmri-qa` measures how stable the
scanner was while it acquired it, and publishes the result as a single netCDF-4
file that a report, a spreadsheet, or a trend database reads.

These pages document the calculation. There is one page per analysis: what it
is for, the computation with its equations and settings, a figure, and a table
of exactly what it contributes to the artifact under the names a reader will
find in the file. The repository's `README.md` covers the workflow instead —
installing, importing DICOM, the command line, and the HTML report.

```{toctree}
:maxdepth: 2

analyses/index
artifact
```

## Where to start

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
