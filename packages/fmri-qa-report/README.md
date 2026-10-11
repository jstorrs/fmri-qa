# fmri-qa-report

The presentation half of [fmri-qa](../../README.md): a single self-contained
offline HTML report rendered from a `fmriqc.analysis.QAArtifact`.

```console
$ fmri-qa scan.nii.gz --artifact qa.nc
$ fmri-qa-report qa.nc --html report.html
```

The artifact is the only input. [`fmri-qa-core`](../fmri-qa-core) precomputes
every number, curve, mask, and image the report draws. A report can therefore be
produced on another machine, long after the acquisition, with no access to the
series. An artifact read back from disk renders the same as one just computed.

Inside, content is separate from format. `summary` and `content` build the text,
`panels` builds the matplotlib figures, and `formats/` holds one driver per
output format. To add a format, add a subpackage beside `formats/html`.

`fmri-qa-report ARTIFACT --html FILE` renders one artifact into a single
self-contained HTML file, with the stylesheet inlined and every figure embedded
as a `data:` URI. It opens by double-click with no network and no sibling file,
so it is safe to email, attach to a QA record, or drop into an existing website.
It carries no JavaScript, so an embedding site's Content-Security-Policy only
needs `style-src 'unsafe-inline'` (or a hash) and `img-src data:`. Clicking a
figure enlarges it to fill the viewport, and clicking it again closes it. This
uses CSS alone. Dark mode follows the reader's OS setting, and figures stay on a
white plate so plotted data keeps its colors. The page is print-ready. `--html`
takes one artifact. A wildcard pattern that matches several is a usage error.

The workspace's [user guide](../../docs/user-guide/index.md) covers the command,
the page, and the Python API. Build it from the workspace root with
`make sync-docs && make docs`. It lands under `build/site`.
