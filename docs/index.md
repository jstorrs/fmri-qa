# fmri-qa

Phantom fMRI quality-assurance metrics, following the Glover/fBIRN stability
protocol (Friedman & Glover, 2006). Given a 4-D phantom time series, `fmri-qa`
measures how stable the scanner was while it acquired it — SNR, SFNR, the
Weisskoff radius of decorrelation, drift, temporal fluctuation and Nyquist
ghosting — and publishes the result as a single netCDF-4 file that a report, a
spreadsheet, or a trend database reads.

## The packages

- **{external+core:doc}`fmri-qa-core <index>`** — what is calculated, and how:
  a page per analysis with its equations, a figure rendered by running the
  pipeline over a synthetic phantom, and exactly what it contributes to the
  analysis artifact, plus a page on the artifact file itself.
- **{external+report:doc}`fmri-qa-report <index>`** — how an artifact becomes
  a single self-contained HTML page: the command, what the page shows and what
  it needs from a browser, and rendering one from Python.

## Where to start

- **"What does this number mean?"** — find it in
  {external+core:doc}`analyses/index`; every measurement is listed there against
  the page that publishes it.
- **"How do I open a `.qa.nc` file?"** — {external+core:doc}`artifact` has the
  MATLAB, R and Python recipes, and the dimensions and coordinates the file is
  laid out on.
- **"How do I make a report from one?"** — {external+report:doc}`usage`.
- **"Can I put a report on our website?"** — {external+report:doc}`page` says
  what the file contains and what an embedding site's Content-Security-Policy
  has to allow.

Installing, importing DICOM, and the `fmri-qa` command line are covered in the
repository's `README.md`.
