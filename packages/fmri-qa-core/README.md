# fmri-qa-core

The calculation half of [fmri-qa](../../README.md): phantom fMRI quality-assurance
metrics (SNR, SFNR, RDC/Weisskoff, Nyquist ghost, spikes, motion, smoothness) and
the **analysis artifact** they are published in.

```python
import fmriqc as q

scan = q.QAScan.from_nifti("qa.nii.gz")
artifact = q.analyze(scan, name="qa.nii.gz")
q.save_artifact(artifact, "qa.nc")
```

A `QAArtifact` carries the run's settings, provenance, scalar measurements,
stability curves, and the four FBIRN summary images. That is everything a report
or a trend database needs, and nothing only the pipeline needs. It saves as a
netCDF-4 file, written through `netCDF4`, which wraps the Unidata C library the
other readers use. MATLAB's `ncread`/`ncinfo`/`ncdisp`/`ncreadatt` are built in
and need no toolbox. R reads one through `ncdf4` on CRAN, Python through
netCDF4-python or xarray, and `ncdump` comes with the netCDF tools. Artifacts
written by earlier builds as `.qa.npz` still load. Rendering an artifact into a
report is the job of the separate [`fmri-qa-report`](../fmri-qa-report)
distribution. This package depends on nothing that draws.

## What it calculates

The workspace's [user guide](../../docs/user-guide/index.md) has a page per
analysis: what it is for, the computation with its equations, a figure from
running this package on a synthetic phantom, and the netCDF names it adds. It
also has [`artifact.md`](../../docs/user-guide/artifact.md) on the file itself.
Build the HTML from the workspace root with `make sync-docs && make docs`. The
site lands in `build/site`.

## Commands

- `fmri-qa SCAN... [--artifact PATH]`: the metrics table (or `--json`), and
  optionally the saved artifact.
- `fmri-qa-import SOURCE [-o DIR]`: DICOM directory to QA-ready NIfTI with dcm2niix.
- `fmri-qa-hilo HIGH LOW`: high/low flip-angle thermal/instability separation.
