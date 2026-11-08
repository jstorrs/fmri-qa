# fmri-qa-report

The presentation half of [fmri-qa](../../README.md): a single self-contained
offline HTML report rendered from a `fmriqa.analysis.QAAnalysis`, or from the
`.qa.nc` file that holds one.

```console
$ fmri-qa scan.nii.gz --analysis-file qa.nc
$ fmri-qa-report qa.nc --html report.html
```

The `fmri-qa` and `fmri-qa-report` commands come from
[`fmri-qa-cli`](../fmri-qa-cli), a separate install that depends on this
package. This package is a library and ships no commands.

The analysis file is the only input. [`fmri-qa-core`](../fmri-qa-core) precomputes
every number, curve, mask, and image the report draws. A report can therefore be
produced on another machine, long after the acquisition, with no access to the
series. An analysis file read back from disk renders the same as one just computed.

It depends on `fmri-qa-core` for the `QAAnalysis` types, plus matplotlib to
draw. `render_run_page(analysis)` takes an analysis file in memory and returns the
page as a string. It reads and writes no file: the application loads the
analysis file and writes the page (`fmriqa_io` does both). It never runs the
pipeline and never reads a scan.

Inside, content is separate from format. `summary` and `content` build the text,
`panels` builds the matplotlib figures, and `formats/` holds one driver per
output format. To add a format, add a subpackage beside `formats/html`.

The command `fmri-qa-report ANALYSIS_FILE --html FILE` renders one analysis file into a
single self-contained HTML file, with the stylesheet inlined and every figure
embedded as a `data:` URI. It opens by double-click with no network and no
sibling file, so it is safe to email, attach to a QA record, or drop into an
existing website.
It carries no JavaScript, so an embedding site's Content-Security-Policy only
needs `style-src 'unsafe-inline'` (or a hash) and `img-src data:`. Clicking a
figure enlarges it to fill the viewport, and clicking it again closes it. This
uses CSS alone. Dark mode follows the reader's OS setting, and figures stay on a
white plate so plotted data keeps its colors. The page is print-ready. `--html`
takes one analysis file. A wildcard pattern that matches several is a usage error.

The user guide covers [the command](https://jstorrs.github.io/fmri-qa/user-guide/fmri-qa-report.html),
[the page](https://jstorrs.github.io/fmri-qa/user-guide/report-page.html) and
[rendering from Python](https://jstorrs.github.io/fmri-qa/user-guide/report-library.html).
