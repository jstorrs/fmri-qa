# fmri-qa

Phantom fMRI quality-assurance metrics, following the Glover/FBIRN stability
protocol (Friedman & Glover, 2006). Given a 4-D phantom time series, it reports
SNR, SFNR, the Weisskoff radius of decorrelation (RDC), drift, temporal
fluctuation, and two Nyquist-ghost measures (FBIRN percent ghost and the ACR/AAPM
ghosting ratio). It renders a self-contained offline HTML report per scan.

## The packages

The project ships as five installable packages. Core calculates and reads no
files. IO reads and writes them. The command line is a shell over both. Report
presents a result, and the launcher is an application shell on top of all four.

| Package | Import | Does | Needs |
| --- | --- | --- | --- |
| **`fmri-qa-core`** | `fmriqa` | the metrics, the pipeline, and the **analysis artifact** they are published as. Pure calculation: it reads no files | numpy, scipy, scikit-image |
| **`fmri-qa-io`** | `fmriqa_io` | reading and writing files: scans (`load_scan`), the artifact's netCDF-4 file (`save_artifact`, `load_artifact`), and DICOM import through dcm2niix (`import_dicom`) | core, nibabel, numpy; netCDF4 and dcm2niix (not in a browser) |
| **`fmri-qa-cli`** | `fmriqa_cli` | the `fmri-qa`, `fmri-qa-hilo`, `fmri-qa-import` and `fmri-qa-report` commands | core, io + report |
| **`fmri-qa-report`** | `fmriqa_report` | plots and a self-contained offline HTML report, built from an artifact. A library: its command, `fmri-qa-report`, is in `fmri-qa-cli` | core + io, matplotlib |
| **`fmri-qa-launcher`** | `fmriqa_launcher` | one-step DICOM-directory-in, report-directory-out pipeline: a command line and a desktop panel | cli, core, io + report; stdlib `tkinter` for the panel |

Only a `QAArtifact` passes between calculating and presenting. It holds the run's
settings, provenance, scalar measurements, stability curves, and the four FBIRN
summary images: everything a report needs, none of the heavy inputs. It saves to
one netCDF-4 file, so calculation and reporting stay separate steps even when
`fmri-qa-launcher` runs them back to back:

```bash
uv run fmri-qa scan.nii.gz --artifact qa.nc      # calculate once
uv run fmri-qa-report qa.nc --html report.html   # render as often as you like
```

Core is split from IO so that it can run in a browser. It needs nothing native
and touches no file, so it loads under [Pyodide](https://pyodide.org). The aim is
a single offline HTML page a hospital can open to run QA with nothing installed.
`fmriqa_io.scan_from_bytes` decodes the bytes a browser was given into the
`QAScan` core takes.
[`notes/pyodide-spike/README.md`](notes/pyodide-spike/README.md) records the
spike. Install core and IO without the command line if you only want numbers in
your own code (a trend database, a cron job). See
[`notes/analysis_report_split.md`](notes/analysis_report_split.md) for the
rationale and the artifact's layout.

## What it measures

Eight analyses run over a scan. Each has a page with its purpose, the computation
and equations, a figure from a synthetic phantom, and the netCDF names it adds to
the artifact:

| Analysis | In one line |
| --- | --- |
| [FBIRN stability](docs/user-guide/analyses/stability.md) | SNR, SFNR, drift and fluctuation over a fixed ROI, the Weisskoff RDC, and the trim + detrending every other analysis shares |
| [Phantom localization](docs/user-guide/analyses/localization.md) | the slice, the phantom mask and its outline, the summary ROI — and the verdicts that say whether either landed correctly |
| [Nyquist ghosting](docs/user-guide/analyses/ghosting.md) | the N/2 ghost against the tissue that produced it: FBIRN percent ghost, its localized top-10% companion, the readout baseline, and the ACR/AAPM difference |
| [ADC saturation](docs/user-guide/analyses/saturation.md) | whether the receiver clipped on its `2ⁿ−1` rail, counted separately before and after the warm-up trim — with a third answer for "not determinable" |
| [Outliers and spikes](docs/user-guide/analyses/outliers.md) | the per-frame outlier-voxel fraction (AFNI `3dToutcount`) and two MAD-normalized spike scores, in time and in frequency |
| [Motion and deformation](docs/user-guide/analyses/motion.md) | a `3dvolreg`-style rotation-free registration for the translation, scale and shear gradient heating produces, plus a mask-free centroid trace |
| [Smoothness and point spread](docs/user-guide/analyses/smoothness.md) | the directional FWHM of the noise field (AFNI `3dFWHMx`) and the empirical point-spread curves, the confound the RDC is read against |
| [Thermal vs. instability noise](docs/user-guide/analyses/hilo.md) | `fmri-qa-hilo`: a high/low flip-angle pair split into additive and multiplicative noise (Greve) |

[The analysis artifact](docs/user-guide/artifact.md) documents the file: its
dimensions and coordinates, the global attributes that carry every scalar, and
how to read one from MATLAB, R, Python or `ncdump`. `make sync-docs && make docs`
builds the [user guide](docs/user-guide/index.md) and an API reference generated
from the docstrings into `build/site`.

## Install

The project uses [uv](https://docs.astral.sh/uv/) and Python 3.13. The repo is a
uv workspace holding all the packages. Syncing it gives the full development
environment:

```bash
uv sync --all-packages
```

Downstream, install the package you need. Each pulls in the ones it needs from
the table above, and the comments say what it provides:

```bash
pip install fmri-qa-core      # metrics and artifacts; reads no files
pip install fmri-qa-io        # + core: reading scans, artifact files, DICOM import
pip install fmri-qa-cli       # + core, io, report: fmri-qa, fmri-qa-import, fmri-qa-hilo, fmri-qa-report
pip install fmri-qa-report    # + core, io: plots and self-contained HTML reports (a library)
pip install fmri-qa-launcher  # + all four: fmri-qa-run and the desktop panel
```

`fmri-qa-import` needs dcm2niix, and `fmri-qa-io` depends on one (except in a
browser, where no binary can run). The install bundles a binary, so the importer
runs with nothing else set up. To use another build (a newer one, or one with
vendor patches), name it. You have to, because the bundled binary is preferred
over whatever is on `PATH`:

```bash
fmri-qa-import STUDY_DIR --dcm2niix /opt/vendor/bin/dcm2niix
```

Published work using the package should cite the software metadata in
[`CITATION.cff`](CITATION.cff). User-facing changes are recorded in
[`CHANGELOG.md`](CHANGELOG.md).

Two stacks are heavier than any published distribution, so they stay out of the
default sync. Each is its own dependency group because it is development
tooling: the exploratory notebooks (DICOM conversion, BIDS, interactive viewers)
and the Sphinx build:

```bash
make sync-notebooks    # uv sync --all-packages --group notebooks
make sync-docs         # uv sync --all-packages --group docs
make docs              # build the documentation site into build/site
```

## One step: DICOM in, reports out

`fmri-qa-launcher` runs the whole pipeline in one command, from a DICOM directory
to one report directory per series.

```bash
uv run fmri-qa-run DICOM_DIR OUTPUT_DIR
```

For each series under `DICOM_DIR`, it converts, analyzes, and writes a folder
under `OUTPUT_DIR` with four files:

```text
OUTPUT_DIR/
  <series>/
    <series>.nii.gz   # converted scan
    <series>.json     # acquisition sidecar
    <series>.qa.nc    # QA artifact
    <series>.html     # self-contained report -- double-click to open
```

`OUTPUT_DIR` is created if it does not exist. Analysis uses `fmri-qa`'s own
defaults, so the numbers match a `fmri-qa` run by hand. A series whose folder
already exists is refused, so no run overwrites an earlier one. A failure in one
series is reported and the rest still complete.

The command takes the same analysis flags as `fmri-qa` (`--trim-sec`, `--detrend`,
`--center`, `--roi-size`), plus `--anonymize`, `--dcm2niix`, and `--open` to open
the result when the run finishes. `fmri-qa-run -h` lists them with their
defaults.

stdout carries only the path of each published report, one per line. Everything
else (progress, refusals, failures, warnings) goes to stderr. The exit code is
`0` when every series published, `1` if any was refused or failed, and `2` on a
usage error.

With neither directory given, `fmri-qa-run` opens a desktop panel, also available
as `fmri-qa-panel`. It needs `tkinter` and a graphical display. Without either,
it prints a message and exits `2`.

The step-by-step commands below (`fmri-qa-import`, `fmri-qa`, `fmri-qa-report`)
still work on their own, for trending numbers over time or custom workflows.

## Importing DICOM

```bash
uv run fmri-qa-import /path/to/dicom/dir -o session_nifti
```

```text
# dcm2niix v1.0.20260724 (.../site-packages/dcm2niix/dcm2niix)
series  acquired             file
     2  2026-09-09 14:30:12  20260909_143012_s002_QA_EPI_ISO.nii.gz
    11  2026-09-09 14:55:33  20260909_145533_s011_QA_EPI_32ch_rep.nii.gz
# 2 series -> session_nifti
# analyze with:  fmri-qa session_nifti/*.nii.gz
```

This runs [dcm2niix](https://github.com/rordenlab/dcm2niix) and adds two things
that are easy to get wrong: flags that keep a series checkable, and names that
read and sort.

### Why convert rather than read DICOM

`fmri-qa` analyzes NIfTI, and this command is its DICOM support. That is a
deliberate boundary, not a missing feature. Reading DICOM
directly would mean handling every vendor's quirks: Siemens mosaics and CSA
headers, GE private tags, Philips' two rescale conventions, enhanced multi-frame
against classic, and grouping frames into volumes across echoes, coils and
dynamics. dcm2niix does that for every vendor and keeps up as scanners change.

The loader already depends on it. `fmri-qa` reads `PhaseEncodingDirection` from
the sidecar, and that is not a DICOM tag. No tag carries the BIDS
axis-and-polarity answer; dcm2niix derives it from vendor private data. Reading DICOM here would reimplement a dependency, not drop one.

### The flags it pins

dcm2niix has some thirty options, and most are matters of taste. Four are not.
They are also defaults, and dcm2niix reads `~/.dcm2nii.ini` before its own
defaults. A file written months ago by another tool can change a QA conversion
without appearing on anyone's command line.

| Flag | Why it is not optional |
| --- | --- |
| `-l o` | keep the stored integers exactly as the scanner sent them |
| `-g i` | ignore `~/.dcm2nii.ini`, so the other three are actually in force |
| `-b y` | write the BIDS sidecar — TR, voxel size and phase-encode direction come from it |
| `-w 2` | add a suffix on a name conflict rather than overwrite |

`-l o` matters most. It keeps the [ADC-saturation
check](docs/user-guide/analyses/saturation.md) able to answer at all, and it is
why this is a command and not advice to run dcm2niix yourself.

### The names it builds

A QA archive is browsed by date, series number, series description and time.
dcm2niix's `-f` template cannot produce those four:

- `%t` is the **study** date and time, identical for every series in a session,
  so it cannot say when a series ran. There is no series-time token.
- `%s` is **not zero-padded**, so `..._11_...` sorts before `..._2_...`.
- `%d` keeps the protocol's punctuation, so `QA EPI 32ch (rep)` becomes a name
  that needs quoting in a shell.

All four fields are in the BIDS sidecar, so the name is built from that:
`<date>_<time>_s<NNN>_<description>`. Time comes before the series number because
series numbers restart between studies. A directory of several sessions sorts
correctly by time, and by series only by accident.

Every field is optional, since some exports omit each DICOM tag, so a partial
sidecar gives a shorter name rather than no name. A series whose sidecar names nothing keeps
dcm2niix's name. So does a series whose name would collide with another's. A
multi-echo or magnitude/phase series matches on all four fields and differs only
in dcm2niix's postfix, so renaming both to the shared name would silently keep
whichever moved last. The command lists the files left unrenamed.

To keep dcm2niix's naming, use `--names dcm2niix`. `--filename` takes any `-f`
template.

Options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `-o`, `--out` | `./<source name>_nifti` | where to write the NIfTI |
| `--names` | `qa` | `qa` (date/time/series/description) or `dcm2niix` |
| `--filename` | `%t_%s_%d` | dcm2niix `-f` template (the fallback name under `--names qa`) |
| `--anonymize` | `pii` | `pii` strips the patient and keeps the dates, `all` strips the dates too, `none` keeps everything |
| `--no-compress` | — | write `.nii` instead of `.nii.gz` |
| `--depth` | `5` | sub-directory levels of the source to search |
| `--dcm2niix` | bundled, else `PATH` | which dcm2niix to run (name your own build; bundled wins over `PATH`) |
| `--dcm2niix-arg` | — | extra argument, repeatable, passed last so it wins |
| `--force` | — | overwrite files already in the output directory |
| `--log` | — | print everything dcm2niix said |
| `--version` | — | print the version and exit |

The import is all-or-nothing. It converts into a staging directory and moves the
result into place only once every file has a name and none would overwrite
anything. The names come from the DICOM, so they cannot be checked before
converting. Checking them before the move keeps a refused import from leaving
half a session behind. A move that fails partway (a sync client holding a file, a
disk error) is undone the same way. Under `--force`, files being replaced are set
aside until the import succeeds, so a failure restores them instead of leaving a
new scan beside an old sidecar.

`--dcm2niix-arg` is an escape hatch passed after everything the command chose, so
it wins. A value starting with `-` needs the `=` form
(`--dcm2niix-arg=-i --dcm2niix-arg=y`). Overriding `-l` warns, because it disarms
the saturation check without visibly breaking anything.

## Command line

```bash
uv run fmri-qa [options] scan.nii.gz [more.nii.gz ...]
```

```text
# detrend=poly  trim_sec=5.0  center=image  roi_size=21
scan                                      PE      loc       SNR      SFNR      RDC   drift%   ghost%     ghT%      RO%    ACRg%   outl%   tcOut  spcOut   clip  clipPre    motn    scl%    shr%    com   fwPE   fwRO
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
FBIRN_QA_fMRI_flip77_13.nii.gz           col       ok     467.3     452.0   10.953    0.303    4.092    6.643    4.059    0.033   0.211    2.48    5.19      0        0   0.017   0.198   0.015  0.007   2.19   2.72
ABCD_QA_fMRI_16.nii.gz                   col       ok      76.7      75.3   13.355    0.682    5.074   10.084    3.192    1.882   0.077    3.30    5.86      0       68   0.025   0.268   0.034  0.094   1.53   2.17
```

Each analysis page defines the columns it publishes. See [what it
measures](#what-it-measures).

Options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--trim-sec` | `5.0` | seconds of initial (non-steady-state) volumes to drop |
| `--pe-axis` | header | override the in-plane phase-encode axis (`0`/`1`) |
| `--detrend` | `poly` | detrending method (`poly` or `spline`) |
| `--center` | `image` | localization mode (`image` or `phantom`) |
| `--roi-size` | `21` | summary/Weisskoff ROI side, in voxels |
| `--json` | — | emit the metrics as JSON on stdout instead of the text table |
| `--artifact` | — | save the full analysis artifact for later reporting |

`--version` prints the version and exits.

Multiple scans share one table. A bad file is reported to stderr and the batch
continues. The process exits non-zero if any file failed.

Wildcards work the same on every platform. A POSIX shell expands them before
`fmri-qa` starts, and where it does not (PowerShell, cmd) the command expands
them itself, so you can paste the lines here as written.

A second command takes a pair of scans that differ only in flip angle and
separates thermal from instability noise (see [thermal vs. instability
noise](docs/user-guide/analyses/hilo.md)):

```bash
uv run fmri-qa-hilo HIGH_flip.nii.gz LOW_flip.nii.gz
```

Pass the high-flip scan first. `--trim-sec`, `--detrend`, and `--erode` mirror the
main command. This is a pair-level diagnostic, separate from the batch table, and
it writes no artifact.

`--version` prints the version and exits.

### Saving an artifact

`--artifact PATH` writes the complete analysis result (settings, provenance, every
measurement and curve, and the summary images) as a compressed netCDF-4 file.
With one scan, `PATH` is the output file. With several, it is a directory that
gets one `<scan>.qa.nc` per scan. A `PATH` that is already a directory gets the
files inside it either way, so `mkdir results` then `--artifact results` works:

```bash
uv run fmri-qa data/*_fMRI_*.nii.gz --artifact artifacts/
```

An existing file at the destination is replaced atomically. An output that names
one of the run's own inputs (the scan, its sidecar, or, for
`fmri-qa-report --html`, an artifact) is refused before anything is read, because
replacing it would destroy the data it describes.

**Reading an artifact elsewhere.** MATLAB, R, Python/xarray and `ncdump` all open
one without a package they would have to go looking for, and artifacts from older builds (including the
`.qa.npz` archives) still load. [The analysis artifact](docs/user-guide/artifact.md)
has the layout, recipes, and version rules.

### JSON on stdout

With `--json`, stdout carries one versioned JSON document:
`{"schema_version": 6, "config": {...}, "requested": [...], "scans": [...],
"errors": [...]}`. It has one record per scan, with the table's columns as raw
numbers. A metric that cannot be computed is JSON `null` (for example, a ghost
ratio with no clear ghost region), never `NaN` or `Infinity`. Each record leads
with `phantom_fraction`, `phantom_mask_ok`, and `roi_inside_phantom` (the table's
`loc` column), which say whether the phantom mask and summary ROI landed where
they must. A mask passes when it covers a plausible share of the frame and stands
clear of the background it was cut from, so a segmentation of noise fails even at
an ordinary size. When either check fails, every mask-based number in that record
was measured on background.

A record also carries fields the table has no room for, because a row in a trend
database outlives the terminal. `source` and `datetime` key and date it. `tr`,
`n_frames` and `n_trimmed` say what series the numbers describe.
`outlier_worst_frame` is the worst outlier volume, counted from the analyzed
series, so adding `n_trimmed` gives the acquired volume number. `requested` lists
every input path given. `errors` has one entry (`scan`, `source`, `error`) per
input that failed to load, analyze, or save, so a consumer holding only the
document can tell a failed scan from one never asked for. The banner, errors, and
save notices go to stderr, so `fmri-qa --json scan.nii.gz | jq` stays clean:

```bash
uv run fmri-qa --json data/*_fMRI_*.nii.gz > qa.json
```

## HTML report

Reporting reads artifacts, not scans:

```bash
uv run fmri-qa scan.nii.gz --artifact scan.qa.nc
uv run fmri-qa-report scan.qa.nc --html report.html
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--html` | — | required; write the self-contained HTML report to this file |
| `-h`, `--help` | — | show usage and available options |
| `--version` | — | show the report package version |

`--html` takes one artifact. The command expands a wildcard the shell leaves
alone, and a pattern matching several artifacts is a usage error. An unreadable
artifact is reported on stderr, and the command exits non-zero and writes
nothing.

The page opens with the scan's identification, the metric tiles, any localization
or clipping warning, and the acquisition and analysis settings. Fourteen figures
follow in two groups. Image diagnostics: signal, SFNR, fluctuation noise, and
static spatial noise, with the phantom outline and summary ROI drawn where they
apply, plus an N/2 ghost panel showing the phase-encode and readout sampling
regions. Temporal and spatial diagnostics: the Weisskoff curve, the decorrelation
factor by ROI width, the ROI mean signal with its fitted trend, the detrended
residual, its spectrum, the per-frame outlier fraction, per-frame in-plane
motion, whole-slice center-of-mass shift, and the directional PSF curves. A
definitions-and-methods section gives each metric's definition and computation,
and a provenance table closes the page.

It opens by double-click with no network and no sibling file, so you can email
it, attach it to a QA record, or drop it into a website. It contains no
JavaScript, so an embedding site's Content-Security-Policy only needs
`style-src 'unsafe-inline'` (or a hash) and `img-src data:`. Clicking a figure
enlarges it to fill the viewport, and clicking again closes it, using CSS alone.
Dark mode follows the OS setting, and figures stay on a white plate so plotted
data keeps its colors. The page is print-ready.

## Library

### Calculating

```python
import fmriqa as q
import fmriqa_io

scan = fmriqa_io.load_scan("scan.nii.gz")
artifact = q.analyze(scan, name="scan.nii.gz")
m = artifact.measurements
print(m.snr, m.sfnr, m.rdc, m.drift_pct)

fmriqa_io.save_artifact(artifact, "qa.nc")
```

`analyze` is the main entry point. Underneath, the pipeline is a chain of small
functions, each usable on its own:

```text
QAScan → preprocess → QAImages → detect_phantom → resolve_roi
       → {weisskoff, snr, sfnr, estimate_ghost}
       → QAResult → build_artifact → QAArtifact
```

`preprocess` trims the series, selects the slice, detrends per voxel, and returns
a `QAImages` holding the center slice plus its fluctuations. The summary images
(mean, MIP, static noise, fluctuation noise, trend) are derived properties. You
can discard the full multi-slice volume once `QAImages` exists. `QAImages` owns
read-only copies of its arrays, so changing the input cannot invalidate the
cached summaries. Artifact arrays also own read-only copies, so make an explicit
copy when you need writable data. `run_qa` gathers the metrics into a `QAResult`,
the pipeline's working output, with the images attached and the requested
settings written on it. `build_artifact` projects that into the `QAArtifact`
everything downstream reads. The artifact has five sections (`settings`,
`provenance`, `measurements`, `curves`, `images`) and is fully resolved, so a
consumer never recomputes a metric.

### Reporting

```python
import fmriqa_io
import fmriqa_report as report

artifact = fmriqa_io.load_artifact("qa.nc")

report.write_run_page(
    artifact, "report.html", title="run-1", theme=report.Theme(panel_accent="#1a4d7a")
)
```

Inside `fmriqa_report`, content is separate from format. `summary` (metadata
text), `content` (the per-metric catalog), and `panels` (the figures) know nothing
about HTML. `theme` supplies the `Theme` that drives the matplotlib panels, and
`formats.html` composes everything into the self-contained page.

The page is written atomically. A rendering failure leaves any existing file
unchanged and makes the CLI exit non-zero.

## License

fmri-qa is available under the [MIT License](LICENSE).
