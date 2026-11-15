# For developers

This page is addressed to readers who call fmri-qa from Python or contribute to
it. None of it is needed to run an analysis.

## The packages

fmri-qa consists of five installable Python distributions and a private sixth
for the browser page. Calculation reads no files, file input and output are
kept separate, and the applications are built on both.

| Package | Import | Does | Needs |
| --- | --- | --- | --- |
| `fmri-qa-core` | `fmriqa` | the metrics, the pipeline, and the analysis file they produce. Pure calculation: it reads no files | numpy, scipy, scikit-image |
| `fmri-qa-io` | `fmriqa_io` | scans (`load_scan`), the analysis file's netCDF-4 file (`save_analysis`, `load_analysis`), and DICOM import through dcm2niix (`import_dicom`) | core, nibabel, numpy; netCDF4 and dcm2niix outside a browser |
| `fmri-qa-cli` | `fmriqa_cli` | the `fmri-qa`, `fmri-qa-hilo`, `fmri-qa-import` and `fmri-qa-report` commands | core, io, report |
| `fmri-qa-report` | `fmriqa_report` | the figures and the HTML report, rendered from an analysis file. A library: its command is in `fmri-qa-cli` | core, matplotlib |
| `fmri-qa-launcher` | `fmriqa_launcher` | `fmri-qa-run` and the desktop panel | cli, core, io, report; the standard library's `tkinter` for the panel |
| `fmri-qa-web` (private) | `fmriqa_web` | the browser page's Python: bytes in, file names, report and record out | core, io, report |

Each distribution installs the packages it depends on. To use the results in
other code, such as a trend database or a scheduled job, `fmri-qa-core` and
`fmri-qa-io` can be installed without the commands. Until the packages are
published on PyPI, they are installed from GitHub by subdirectory. The following
command also installs `fmri-qa-core`:

```console
$ uv pip install "fmri-qa-io @ git+https://github.com/jstorrs/fmri-qa#subdirectory=packages/fmri-qa-io"
```

A `QAAnalysis` is the only object that passes from calculation to presentation.
It holds the settings, provenance, measurements, curves and summary images of a
run, which is everything a report needs, and none of the scan data. It is saved
as a single netCDF-4 file, so a report can be rendered later and elsewhere,
without access to the scan.

## Calculating from Python

```python
import fmriqa
import fmriqa_io

scan = fmriqa_io.load_scan("scan.nii.gz")
analysis = fmriqa.analyze(scan, name="scan.nii.gz")
m = analysis.measurements
print(m.snr, m.sfnr, m.rdc, m.drift_pct)

fmriqa_io.save_analysis(analysis, "qa.nc")
```

`analyze` is the entry point. Beneath it, the pipeline is a chain of small
functions, each of which can be used independently:

```text
QAScan → preprocess → QAImages → detect_phantom → resolve_roi
       → {weisskoff, snr, sfnr, estimate_ghost}
       → QAResult → build_analysis → QAAnalysis
```

- `preprocess` trims the series, selects the slice, and detrends each voxel. It
  returns a `QAImages` that holds the slice and its fluctuations, with the
  summary images (mean, maximum-intensity projection, static noise, fluctuation
  noise, trend) as derived properties. The full volume can be discarded once the
  `QAImages` exists.
- `run_qa` collects the metrics into a `QAResult`, the working output of the
  pipeline, with the images attached and the requested settings recorded.
- `build_analysis` converts that result into the `QAAnalysis` that everything
  downstream reads. Its five sections are `settings`, `provenance`,
  `measurements`, `curves` and `images`. Every value is already computed, so a
  reader never recomputes a metric.

`QAImages` and `QAAnalysis` hold read-only copies of their arrays, so modifying
an input cannot alter a cached result. An array must be copied before it is
written to.

{doc}`report-library` describes rendering a report from Python, and the
{doc}`API reference </api/index>` lists every public name.

## Working on fmri-qa

The repository is a [uv](https://docs.astral.sh/uv/) workspace that contains
all the packages and targets Python 3.13:

```console
$ uv sync --all-packages     # the development environment
$ make check                 # format, lint, type checks, tests, and the docs
$ make sync-docs && make docs   # this site, into build/site
```

The exploratory notebooks (DICOM conversion, BIDS, viewers) and the Sphinx build
are separate dependency groups, outside the default synchronization:
`make sync-notebooks` and `make sync-docs`. The `style/` directory of the
repository holds the coding and documentation guides.

The browser page is built with `make web`, and `make pages` builds this site
with the page under `app/`. `web/README.md` documents the page: how it starts
Python, its tests, its size budget, and how it is published.

## The single-file executable

`make bundle` builds `fmri-qa-run` as a single executable that contains the
interpreter, all five packages and dcm2niix, for computers without Python. It
uses PyInstaller, in an environment resolved from `uv.lock`, and writes to
`dist/bundle`. PyInstaller does not cross-compile, so the executable must be
built on the platform on which it will run. On Windows, which lacks `make`,
`scripts/bundle.ps1` runs the same commands. Run without arguments, the
executable opens the panel.

## Design notes

**Calculation without file access.** Calculation is kept apart from input and
output so that it can run in a browser. It requires no native code and accesses
no file, and it therefore loads under [Pyodide](https://pyodide.org).
`fmriqa_io.scan_from_bytes` decodes the bytes supplied to a browser into the
`QAScan` that the core package accepts. The experiment behind this design is
recorded in
[`notes/pyodide-spike/README.md`](https://github.com/jstorrs/fmri-qa/blob/main/notes/pyodide-spike/README.md),
and the division between analysis and report in
[`notes/analysis_report_split.md`](https://github.com/jstorrs/fmri-qa/blob/main/notes/analysis_report_split.md).

**The choice of netCDF-4.** A QA archive outlives the Python environment that
wrote it, and the site that reads it may have no Python at all. MATLAB's
`ncread`, `ncinfo`, `ncdisp` and `ncreadatt` require no toolbox, R's `ncdf4` is
on CRAN, `ncdump` is distributed with the netCDF tools, and xarray opens a file
in one call. A NumPy `.npz`, by contrast, requires npy-matlab in MATLAB and
gives R only numeric arrays. Version 4 was preferred to the classic format for
its per-variable compression, per-variable checksums, and zero-length dimensions
({doc}`analysis-file` gives the details). Everything is stored in the root
group, because `xr.open_dataset` reads only the root group and support for
groups in Octave is uneven. The dotted variable names (`images.sfnr`) depart
from the naming advice of CF intentionally: the dotted path is the name used
throughout this guide, so a reader who encounters it in `ncdisp` can look it up
here.

**The report.** Within `fmriqa_report`, content is separated from format.
`summary` (the metadata text) and `content` (the per-metric text) produce the
wording, `panels` draws the matplotlib figures, and `formats/` holds one driver
per output format, of which HTML is at present the only one. `theme` supplies
the `Theme` with which the figures are drawn. The package writes no file:
`render_run_page` returns the page as a string, and the commands write it with
`fmriqa_io.rename.write_text_atomically`.

**The launcher.** `fmri-qa-launcher` neither computes nor draws anything itself.
It sequences the import and then the analysis, archiving, rendering and
publication of each series, and it ensures that a series appears in the output
folder only when all its files are complete ({doc}`run-output`). It adds no
third-party dependency. `fmri-qa-panel` is installed as a GUI script, so on
Windows it runs under `pythonw` without a console window. `fmri-qa-run` remains
a console program because its standard output lists the published reports.
