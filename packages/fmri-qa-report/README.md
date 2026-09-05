# fmri-qa-report

The presentation half of [fmri-qa](../../README.md): plots and multi-page PDF
packets rendered from a `fmriqc.analysis.QAArtifact`.

```console
$ fmri-qa scan.nii.gz --artifact qa.npz
$ fmri-qa-report qa.npz --pdf report.pdf --tier physics
```

The artifact is the only input. Every number, curve, mask, and image it draws is
precomputed by [`fmri-qa-core`](../fmri-qa-core), so a report can be produced on
another machine, long after the acquisition, with no access to the series — and
an artifact read back from disk renders exactly like one just computed.

Inside, content is split from format: `summary` and `content` build the text,
`panels` the matplotlib figures, and `formats/` holds one driver per output
format. Adding a format is a new file in `formats/`.
