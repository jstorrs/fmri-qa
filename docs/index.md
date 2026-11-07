# fmri-qa

fmri-qa measures how stable an MRI scanner is during an fMRI acquisition, from
a phantom series. It follows the Glover/FBIRN stability protocol (Friedman &
Glover, 2006) and reports SNR, SFNR, the Weisskoff radius of decorrelation,
drift and fluctuation, with Nyquist ghosting, receiver clipping, outlier volumes
and spikes, gradient-heating motion, and noise smoothness beside them. Each
series gets a self-contained HTML report, and its numbers are saved in a file
that MATLAB, R, Python or a trend database can read.

**[Open fmri-qa in your browser](https://jstorrs.github.io/fmri-qa/app/)** to try
it with nothing to install. Give it DICOM, choose the series, and it converts
and analyzes them on your own computer, sending nothing anywhere. You can save
the page and run it offline. The source is
[on GitHub](https://github.com/jstorrs/fmri-qa).

```{toctree}
:hidden:

user-guide/index
api/index
```

## Where to start

- **"How do I run QA on a phantom series?"**:
  {doc}`in the browser </user-guide/browser>`,
  {doc}`from the desktop panel </user-guide/panel>`, or
  {doc}`from a terminal </user-guide/fmri-qa-run>`. The panel and the commands
  need {doc}`installing </user-guide/install>`.
- **"What does this number mean?"**: {doc}`/user-guide/analyses/index` lists
  every measurement, with a page per analysis giving its method and equations.
- **"What is in the report?"**: {doc}`/user-guide/report-page`.
- **"How do I track the numbers over time?"**: {doc}`/user-guide/fmri-qa`
  writes JSON for a trend database, and {doc}`/user-guide/artifact` shows how to
  open an analysis file in MATLAB, R or Python.
- **"Can I put a report on our website?"**: {doc}`/user-guide/report-page`
  says what the file contains and what an embedding site has to allow.
- **"Calling it from Python?"**: {doc}`/user-guide/developers`, and the
  {doc}`API reference </api/index>`.
