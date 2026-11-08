# fmri-qa-core

The calculation half of [fmri-qa](../../README.md): phantom fMRI quality-assurance
metrics (SNR, SFNR, RDC/Weisskoff, Nyquist ghost, spikes, motion, smoothness) and
the **analysis file** they are published in.

Core is pure calculation. It reads no files, so it depends only on numpy, scipy
and scikit-image and runs under Pyodide in a browser. Loading a scan from disk,
and saving an analysis file, are [`fmri-qa-io`](../fmri-qa-io)'s job. This package
ships a synthetic phantom, so the quick start needs no data:

```python
import fmriqa as q
from fmriqa.testing import phantom_scan

analysis = q.analyze(phantom_scan(), name="phantom")
print(analysis.measurements.snr)
```

With a file on disk, load it with `fmri-qa-io` instead:

```python
import fmriqa as q
import fmriqa_io

scan = fmriqa_io.load_scan("qa.nii.gz")
analysis = q.analyze(scan, name="qa.nii.gz")
fmriqa_io.save_analysis(analysis, "qa.nc")
```

A `QAAnalysis` carries the run's settings, provenance, scalar measurements,
stability curves, and the four FBIRN summary images. That is everything a report
or a trend database needs, and nothing only the pipeline needs.
[`fmri-qa-io`](../fmri-qa-io) saves it as a netCDF-4 file, written through
`netCDF4`, which wraps the Unidata C library the other readers use. MATLAB's
`ncread`/`ncinfo`/`ncdisp`/`ncreadatt` are built in and need no toolbox. R
reads one through `ncdf4` on CRAN, Python through netCDF4-python or xarray, and
`ncdump` comes with the netCDF tools. Analysis files written by earlier builds as
`.qa.npz` still load. Rendering an analysis file into a report is the job of the
separate [`fmri-qa-report`](../fmri-qa-report) distribution. This package
depends on nothing that draws and nothing that reads a file.

## What it calculates

The [user guide](https://jstorrs.github.io/fmri-qa/user-guide/analyses/index.html) has a page per
analysis: what it is for, the computation with its equations, a figure from
running this package on a synthetic phantom, and the netCDF names it adds. [The
analysis file](https://jstorrs.github.io/fmri-qa/user-guide/analysis-file.html) documents the file itself.

## Commands

This package ships no commands. `fmri-qa`, `fmri-qa-import` and `fmri-qa-hilo`
are in [`fmri-qa-cli`](../fmri-qa-cli).
