# For developers

This page is for calling fmri-qa from Python, or working on it. Running QA needs
none of it.

## The packages

fmri-qa is five installable Python distributions, plus a private sixth for the
browser page. Calculation reads no files, file IO is separate, and the
applications sit on top.

| Package | Import | Does | Needs |
| --- | --- | --- | --- |
| `fmri-qa-core` | `fmriqa` | the metrics, the pipeline, and the analysis file they produce. Pure calculation: it reads no files | numpy, scipy, scikit-image |
| `fmri-qa-io` | `fmriqa_io` | scans (`load_scan`), the analysis file's netCDF-4 file (`save_artifact`, `load_artifact`), and DICOM import through dcm2niix (`import_dicom`) | core, nibabel, numpy; netCDF4 and dcm2niix outside a browser |
| `fmri-qa-cli` | `fmriqa_cli` | the `fmri-qa`, `fmri-qa-hilo`, `fmri-qa-import` and `fmri-qa-report` commands | core, io, report |
| `fmri-qa-report` | `fmriqa_report` | the figures and the HTML report, rendered from an analysis file. A library: its command is in `fmri-qa-cli` | core, matplotlib |
| `fmri-qa-launcher` | `fmriqa_launcher` | `fmri-qa-run` and the desktop panel | cli, core, io, report; the standard library's `tkinter` for the panel |
| `fmri-qa-web` (private) | `fmriqa_web` | the browser page's Python: bytes in, file names, report and record out | core, io, report |

Each installs the packages it needs. To use the numbers in your own code (a trend
database, a scheduled job), install `fmri-qa-core` and `fmri-qa-io` without the
commands. Until the packages are on PyPI, install from GitHub by the package's
subdirectory. This brings `fmri-qa-core` with it:

```console
$ uv pip install "fmri-qa-io @ git+https://github.com/jstorrs/fmri-qa#subdirectory=packages/fmri-qa-io"
```

Only a `QAArtifact` passes from calculating to presenting. It holds the run's
settings, provenance, measurements, curves and summary images: everything a
report needs, and none of the scan data. It saves to one netCDF-4 file, so a
report can be rendered later, elsewhere, with no access to the scan.

## Calculating from Python

```python
import fmriqa
import fmriqa_io

scan = fmriqa_io.load_scan("scan.nii.gz")
artifact = fmriqa.analyze(scan, name="scan.nii.gz")
m = artifact.measurements
print(m.snr, m.sfnr, m.rdc, m.drift_pct)

fmriqa_io.save_artifact(artifact, "qa.nc")
```

`analyze` is the entry point. Beneath it the pipeline is a chain of small
functions, each usable on its own:

```text
QAScan → preprocess → QAImages → detect_phantom → resolve_roi
       → {weisskoff, snr, sfnr, estimate_ghost}
       → QAResult → build_artifact → QAArtifact
```

- `preprocess` trims the series, selects the slice and detrends each voxel. It
  returns a `QAImages` holding the slice and its fluctuations, with the summary
  images (mean, maximum intensity projection, static noise, fluctuation noise,
  trend) as derived properties. The full volume can be discarded once it exists.
- `run_qa` gathers the metrics into a `QAResult`, the pipeline's working output,
  with the images attached and the requested settings recorded.
- `build_artifact` turns that into the `QAArtifact` everything downstream reads.
  Its five sections are `settings`, `provenance`, `measurements`, `curves` and
  `images`. Every value is computed, so a reader never recomputes a metric.

`QAImages` and the analysis file hold read-only copies of their arrays, so changing an
input cannot change a cached result. Copy an array when you need to write to it.

{doc}`report-library` covers rendering a report from Python. The
{doc}`API reference </api/index>` lists every public name.

## Working on fmri-qa

The repository is a [uv](https://docs.astral.sh/uv/) workspace holding all the
packages, on Python 3.13:

```console
$ uv sync --all-packages     # the development environment
$ make check                 # format, lint, type checks, tests, and the docs
$ make sync-docs && make docs   # this site, into build/site
```

The exploratory notebooks (DICOM conversion, BIDS, viewers) and the Sphinx build
are dependency groups of their own, outside the default sync:
`make sync-notebooks` and `make sync-docs`. The repository's `style/` directory
holds the coding and documentation guides.

The browser page is built with `make web`, and `make pages` builds this site
with the page under `app/`. `web/README.md` covers the page: how it boots
Python, its tests, its size budget and how it is published.

## The single-file executable

`make bundle` builds `fmri-qa-run` as one executable with the interpreter, all
five packages and dcm2niix inside, for a machine with no Python. It uses
PyInstaller, from an environment resolved from `uv.lock`, into `dist/bundle`.
PyInstaller does not cross-compile, so build it on the platform it will run on.
On Windows, where there is no `make`, `scripts/bundle.ps1` runs the same
commands. Run with no arguments, the executable opens the panel.

## Design notes

**Why core reads no files.** Calculation is kept apart from IO so it can run in a
browser: it needs nothing native and touches no file, so it loads under
[Pyodide](https://pyodide.org). `fmriqa_io.scan_from_bytes` decodes the bytes a
browser was given into the `QAScan` core takes. The repository's
[`notes/pyodide-spike/README.md`](https://github.com/jstorrs/fmri-qa/blob/main/notes/pyodide-spike/README.md)
records the experiment behind this, and
[`notes/analysis_report_split.md`](https://github.com/jstorrs/fmri-qa/blob/main/notes/analysis_report_split.md)
the split between analysis and report.

**Why netCDF-4.** A QA archive outlives the Python environment that wrote it, and
the site reading it may have none. MATLAB's `ncread`, `ncinfo`, `ncdisp` and
`ncreadatt` need no toolbox, R's `ncdf4` is on CRAN, `ncdump` ships with the
netCDF tools, and xarray opens one in a call. A NumPy `.npz` needs npy-matlab in
MATLAB and gives R only numeric arrays. Version 4, rather than the classic
format, gives per-variable compression, a per-variable checksum, and
zero-length dimensions ({doc}`analysis-file` has the details). Everything is in the
root group, because `xr.open_dataset` reads only the root group and Octave's
group support is uneven. The dotted variable names (`images.sfnr`) break CF's
naming advice, on purpose: the dotted path is the name these pages use, so a
reader who sees it in `ncdisp` can look it up here.

**The report.** Inside `fmriqa_report`, content is separate from format.
`summary` (metadata text) and `content` (the per-metric text) build the words,
`panels` draws the matplotlib figures, and `formats/` holds one driver per
output format. HTML is the only one today. `theme` supplies the `Theme` the
figures are drawn with. The package writes no file: `render_run_page` returns the
page as a string, and the commands write it with
`fmriqa_io.rename.write_text_atomically`.

**The launcher.** `fmri-qa-launcher` computes and draws nothing itself. It
sequences the import, then analysis, archive, rendering and publishing of each
series, and makes sure a series appears in the output folder only once all its
files are finished ({doc}`run-output`). It adds no third-party dependency.
`fmri-qa-panel` is installed as a GUI script, so on Windows it runs under
`pythonw` with no console window. `fmri-qa-run` stays a console program because
its stdout lists the published reports.
