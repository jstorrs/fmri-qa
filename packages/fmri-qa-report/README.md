# fmri-qa-report

The presentation half of [fmri-qa](../../README.md): a single self-contained
offline HTML report rendered from a `fmriqc.analysis.QAArtifact`.

```console
$ fmri-qa scan.nii.gz --artifact qa.nc
$ fmri-qa-report qa.nc --html report.html
```

The artifact is the only input. Every number, curve, mask, and image it draws is
precomputed by [`fmri-qa-core`](../fmri-qa-core), so a report can be produced on
another machine, long after the acquisition, with no access to the series — and
an artifact read back from disk renders exactly like one just computed.

Inside, content is split from format: `summary` and `content` build the text,
`panels` the matplotlib figures, and `formats/` holds one driver per output
format. Adding a format is a new file in `formats/`.

`fmri-qa-report ARTIFACT --html FILE` renders one artifact into a single
self-contained HTML file — stylesheet inlined, every figure embedded as a
`data:` URI — that opens by double-click with no network and no sibling file,
so it is safe to email, attach to a QA record, or drop as-is into an existing
website. It carries no JavaScript, so an embedding site's
Content-Security-Policy only needs `style-src 'unsafe-inline'` (or a hash) and
`img-src data:`. Clicking a figure enlarges it to fill the viewport, and
clicking it again closes it, through CSS alone, no script involved; dark mode
follows the reader's OS setting (figures stay on a white plate so plotted data
keeps its colors); and the page is print-ready. `--html` takes exactly one
artifact; a wildcard pattern that matches several is a usage error.

The pages in [`docs/`](docs/index.md) cover the command, the page, and the
Python API. Build them from the workspace root with `make sync-docs && make
docs`; they land under `build/site/report`.
