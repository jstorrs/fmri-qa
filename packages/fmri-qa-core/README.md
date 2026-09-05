# fmri-qa-core

The calculation half of [fmri-qa](../../README.md): phantom fMRI quality-assurance
metrics (SNR, SFNR, RDC/Weisskoff, Nyquist ghost, spikes, motion, smoothness) and
the **analysis artifact** they are published in.

```python
import fmriqc as q

scan = q.QAScan.from_nifti("qa.nii.gz")
artifact = q.analyze(scan, name="qa.nii.gz")
q.save_artifact(artifact, "qa.npz")
```

A `QAArtifact` carries the run's settings, provenance, scalar measurements,
stability curves, and the four fBIRN summary images — everything a report or a
trend database needs, and nothing that only the pipeline needs. Rendering one
into a PDF is the separate [`fmri-qa-report`](../fmri-qa-report) distribution's
job; this package depends on nothing that draws.

## Commands

- `fmri-qa SCAN... [--artifact PATH]` — the metrics table (or `--json`), and
  optionally the saved artifact.
- `fmri-qa-hilo HIGH LOW` — high/low flip-angle thermal/instability separation.
