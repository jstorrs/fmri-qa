# fmri-qa

Phantom fMRI quality-assurance metrics, following the Glover/fBIRN stability
protocol (Friedman & Glover, 2006). Given a 4-D phantom time series it reports
SNR, SFNR, the Weisskoff radius of decorrelation (RDC), drift, temporal
fluctuation, and two Nyquist-ghost measures (fBIRN percent ghost and the
ACR/AAPM ghosting ratio), and can render a PDF report per scan.

## Two halves

The project ships as two installable packages, split at the widest seam in it —
calculating a result, and presenting one:

| Package | Import | Does | Needs |
| --- | --- | --- | --- |
| **`fmri-qa-core`** | `fmriqc` | the metrics, the pipeline, and the **analysis artifact** they are published as | numpy, scipy, nibabel, scikit-image, netCDF4 |
| **`fmri-qa-report`** | `fmriqc_report` | plots and multi-page PDF packets, built from an artifact | matplotlib, reportlab, svglib (+ core) |

A `QAArtifact` is the only thing that crosses: the run's settings, provenance,
scalar measurements, stability curves, and the four fBIRN summary images —
everything a report needs, and none of the heavy inputs. It saves to a single
netCDF-4 file, so calculation and reporting are separate steps:

```bash
uv run fmri-qa scan.nii.gz --artifact qa.nc      # calculate once
uv run fmri-qa-report qa.nc --pdf report.pdf     # render as often as you like
```

Install the core alone where you only want numbers (a trend database, a console
script, a cron job) and skip the drawing stack entirely. See
[`notes/analysis_report_split.md`](notes/analysis_report_split.md) for the
rationale and the artifact's layout.

## What it measures

Eight analyses run over a scan. Each has a page describing what it is for, the
computation and its equations, a figure drawn by running the pipeline over a
synthetic phantom, and the exact netCDF names it contributes to the artifact:

| Analysis | In one line |
| --- | --- |
| [fBIRN stability](packages/fmri-qa-core/docs/analyses/stability.md) | SNR, SFNR, drift and fluctuation over a fixed ROI, the Weisskoff RDC, and the trim + detrending every other analysis shares |
| [Phantom localization](packages/fmri-qa-core/docs/analyses/localization.md) | the slice, the phantom mask and its outline, the summary ROI — and the verdicts that say whether either landed correctly |
| [Nyquist ghosting](packages/fmri-qa-core/docs/analyses/ghosting.md) | the N/2 ghost against the tissue that produced it: fBIRN percent ghost, its localized top-10% companion, the readout baseline, and the ACR/AAPM difference |
| [ADC saturation](packages/fmri-qa-core/docs/analyses/saturation.md) | whether the receiver clipped on its `2ⁿ−1` rail, counted separately before and after the warm-up trim — with a third answer for "not determinable" |
| [Outliers and spikes](packages/fmri-qa-core/docs/analyses/outliers.md) | the per-frame outlier-voxel fraction (AFNI `3dToutcount`) and two MAD-normalized spike scores, in time and in frequency |
| [Motion and deformation](packages/fmri-qa-core/docs/analyses/motion.md) | a `3dvolreg`-style rotation-free registration for the translation, scale and shear gradient heating produces, plus a mask-free centroid trace |
| [Smoothness and point spread](packages/fmri-qa-core/docs/analyses/smoothness.md) | the directional FWHM of the noise field (AFNI `3dFWHMx`) and the empirical point-spread curves, the confound the RDC is read against |
| [Thermal vs. instability noise](packages/fmri-qa-core/docs/analyses/hilo.md) | `fmri-qa-hilo`: a high/low flip-angle pair split into additive and multiplicative noise (Greve) |

[The analysis artifact](packages/fmri-qa-core/docs/artifact.md) documents the
file those numbers are published in — its dimensions and coordinates, the
global attributes that carry every scalar in it, and how to read one from MATLAB,
R, Python or `ncdump`. The [documentation index](packages/fmri-qa-core/docs/index.md)
builds into browsable HTML with `make sync-docs && make docs`.

## Install

The project uses [uv](https://docs.astral.sh/uv/) and Python 3.13. The repo is a
uv workspace holding both packages; syncing all of it gives the full development
environment:

```bash
uv sync --all-packages
```

Downstream, install whichever half you need — `fmri-qa-report` pulls in
`fmri-qa-core`, so installing it gives you the core's commands too:

```bash
pip install fmri-qa-core      # metrics and artifacts only
pip install fmri-qa-report    # + plots and PDF packets
```

`fmri-qa-import` needs a dcm2niix, and `fmri-qa-core` depends on one: the
install above carries a bundled binary, so the importer runs with nothing else
set up. To run a different build — a newer dcm2niix, or one with vendor patches
— name it, because the bundled binary is preferred over whatever is on `PATH`:

```bash
fmri-qa-import STUDY_DIR --dcm2niix /opt/vendor/bin/dcm2niix
```

Published work using the package should cite the software metadata in
[`CITATION.cff`](CITATION.cff). User-facing changes are recorded in
[`CHANGELOG.md`](CHANGELOG.md).

Two stacks are heavier than either published distribution and stay out of the
default sync, each as its own workspace dependency group. The exploratory
notebooks (DICOM conversion, BIDS, and interactive viewers) are development
tooling; so is the Sphinx build for the analysis documentation:

```bash
make sync-notebooks    # uv sync --all-packages --all-extras --group notebooks
make sync-docs         # uv sync --all-packages --all-extras --group docs
make docs              # build the analysis pages into docs/_build/html
```

## Importing DICOM

```bash
uv run fmri-qa-import /path/to/dicom/dir -o session_nifti
```

```
# dcm2niix v1.0.20260724 (.../site-packages/dcm2niix/dcm2niix)
series  acquired             file
     2  2026-09-09 14:30:12  20260909_143012_s002_QA_EPI_ISO.nii.gz
    11  2026-09-09 14:55:33  20260909_145533_s011_QA_EPI_32ch_rep.nii.gz
# 2 series -> session_nifti
# analyze with:  fmri-qa session_nifti/*.nii.gz
```

This runs [dcm2niix](https://github.com/rordenlab/dcm2niix) and adds the two
things that are easy to get wrong: the flags that keep a series *checkable*, and
names that read and sort.

### Why convert rather than read DICOM

`fmri-qa` analyzes NIfTI, and its DICOM support is this command. That is a
deliberate boundary, not a missing feature. Reading DICOM directly would mean
owning the vendor complexity of turning it into a series — Siemens mosaics and
CSA headers, GE private tags, Philips' two rescale conventions, enhanced
multi-frame against classic, and the grouping of frames into volumes across
echoes, coils and dynamics. dcm2niix does that for every vendor and keeps doing
it as scanners change; duplicating it here would be a permanent second job.

The phase-encode direction shows how far that already goes. `fmri-qa` reads
`PhaseEncodingDirection` from the sidecar — which is not a DICOM tag. No tag
carries the BIDS axis-and-polarity answer; dcm2niix derives it from vendor
private data. So the loader already runs on dcm2niix's conclusions, and reading
DICOM here would not drop a dependency, only reimplement one.

### The flags it pins

dcm2niix has some thirty options and most are matters of taste. Four are not —
and they are *defaults*, which is the problem, because dcm2niix reads
`~/.dcm2nii.ini` before its own defaults. A file written months ago by another
tool can change what a QA conversion produces without appearing on anyone's
command line.

| Flag | Why it is not optional |
| --- | --- |
| `-l o` | keep the stored integers exactly as the scanner sent them |
| `-g i` | ignore `~/.dcm2nii.ini`, so the other three are actually in force |
| `-b y` | write the BIDS sidecar — TR, voxel size and phase-encode direction come from it |
| `-w 2` | add a suffix on a name conflict rather than overwrite |

`-l o` is the one that matters most, and the reason this is a command rather
than a line in this README telling you to run dcm2niix yourself: it is what
keeps the [ADC-saturation
check](packages/fmri-qa-core/docs/analyses/saturation.md) able to answer at all.

### The names it builds

A QA archive is browsed by date, series number, series description and time, and
dcm2niix's `-f` template cannot produce those four:

- `%t` is the **study** date and time, identical for every series in a session,
  so it cannot say when a series ran. There is no series-time token.
- `%s` is **not zero-padded**, so `..._11_...` sorts before `..._2_...` — a
  listing that looks ordered and is not.
- `%d` keeps the protocol's punctuation, so `QA EPI 32ch (rep)` becomes a name
  that needs quoting in a shell.

All four fields are in the BIDS sidecar, so the name is built from that instead:
`<date>_<time>_s<NNN>_<description>`. Time leads the series number because it is
the more reliable order — series numbers restart between studies, so a directory
holding several sessions sorts right by time and only accidentally by series.

Every field is optional, since each is a DICOM tag some export omits: a partial
sidecar gives a shorter name rather than no name. A series whose sidecar names
nothing keeps the name dcm2niix gave it, and so does a series whose name would
collide with another's — a multi-echo or magnitude/phase series agrees on all
four fields and differs only in dcm2niix's postfix, so renaming both to the one
name they share would silently keep whichever moved last. The command says which
files those were.

Prefer dcm2niix's own naming? `--names dcm2niix` keeps it, and `--filename`
takes any `-f` template.

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

The import is all-or-nothing: it converts into a staging directory and moves the
result into place only once every file has a name and none would overwrite
something already there. The names come out of the DICOM, so they cannot be
checked before converting — checking them before the *move* is what keeps a
refused import from leaving half a session behind.

`--dcm2niix-arg` is an escape hatch, passed after everything the command chose
so it wins; a value starting with `-` needs the `=` form
(`--dcm2niix-arg=-i --dcm2niix-arg=y`). Overriding `-l` warns, because that
particular override disarms the saturation check rather than breaking anything
visibly.

## Command line

```bash
uv run fmri-qa [options] scan.nii.gz [more.nii.gz ...]
```

```
# detrend=poly  trim_sec=5.0  center=image  roi_size=21
scan                                      PE      loc       SNR      SFNR      RDC   drift%   ghost%     ghT%      RO%    ACRg%   outl%   tcOut  spcOut   clip  clipPre    motn    scl%    shr%    com   fwPE   fwRO
--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
FBIRN_QA_fMRI_flip77_13.nii.gz           col       ok     467.3     452.0   10.953    0.303    4.092    6.643    4.059    0.033   0.211    2.48    5.19      0        0   0.017   0.198   0.015  0.007   2.19   2.72
ABCD_QA_fMRI_16.nii.gz                   col       ok      76.7      75.3   13.355    0.682    5.074   10.084    3.192    1.882   0.077    3.30    5.86      0       68   0.025   0.268   0.034  0.094   1.53   2.17
```

Every column is defined on the analysis page that publishes it — see [what it
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

Multiple scans are summarized in one table. A bad file is reported to stderr and
the batch continues; the process exits non-zero if any file failed.

Wildcards work the same way on every platform: a POSIX shell expands them
before `fmri-qa` starts, and where the shell does not — PowerShell and cmd —
the command expands them itself, so the lines in this README can be pasted as
written.

A second command takes a *pair* of scans that differ only in flip angle and
separates thermal from instability noise (see [thermal vs. instability
noise](packages/fmri-qa-core/docs/analyses/hilo.md)):

```bash
uv run fmri-qa-hilo HIGH_flip.nii.gz LOW_flip.nii.gz
```

Pass the high-flip scan first. `--trim-sec`, `--detrend`, and `--erode` mirror
the main command. This is a pair-level diagnostic, kept apart from the per-scan
batch table, and it writes no artifact.

### Saving an artifact

`--artifact PATH` writes the complete analysis result — settings, provenance,
every measurement and curve, and the summary images — as a compressed
netCDF-4 file. With a single scan `PATH` is the output file; with several it is a
directory taking one `<scan>.qa.nc` per scan. A `PATH` that is already a
directory is filed into either way, so `mkdir results` and `--artifact results`
does what it looks like:

```bash
uv run fmri-qa data/*_fMRI_*.nii.gz --artifact artifacts/
```

An existing file at the destination is replaced, atomically. An output that
names one of the run's own inputs (the scan, its sidecar, or, for
`fmri-qa-report --pdf`, an artifact) is refused before anything is read, since
replacing it would destroy the data the output describes.

**Reading an artifact elsewhere** — MATLAB, R, Python/xarray and `ncdump` all
open one without a package they have to go looking for, and an artifact from an
older build (including the `.qa.npz` archives earlier versions wrote) still
loads. [The analysis artifact](packages/fmri-qa-core/docs/artifact.md) has the
layout, the recipes, and the version rules.

### JSON on stdout

With `--json`, stdout carries a single versioned JSON document —
`{"schema_version": 5, "config": {...}, "requested": [...], "scans": [...],
"errors": [...]}`, one record per scan
with the table's columns as raw numbers. A metric that cannot be computed for a
scan is JSON `null` (for example, a ghost ratio with no clear ghost region),
never a non-standard `NaN` or `Infinity` token. Each record leads with
`phantom_fraction`, `phantom_mask_ok`, and `roi_inside_phantom` — the table's
`loc` column — which say whether the phantom mask and the summary ROI landed
where they must (a mask passes when it covers a plausible share of the frame
*and* stands clear of the background it was cut from, so a segmentation of
noise fails even at an ordinary size); when either failed, every mask-based
number in that record was measured on background.

A record also carries a little the table has no room for, because a row filed in
a trend database outlives the terminal it was printed to: `source` and
`datetime` key and date it, `tr`, `n_frames` and `n_trimmed` say what series the
numbers describe, and `outlier_worst_frame` names the worst outlier volume —
counted from the analyzed series, so adding `n_trimmed` gives the acquired
volume number. `requested` lists every input path given, and `errors` one entry
(`scan`, `source`, `error`) per input that failed to load, analyze, or save, so
a consumer holding only the document can tell a scan that failed from one that
was never asked for. The banner, any errors, and any save notices go to stderr,
so `fmri-qa --json scan.nii.gz | jq` stays clean:

```bash
uv run fmri-qa --json data/*_fMRI_*.nii.gz > qa.json
```

## PDF report

Reporting reads artifacts, never scans:

```bash
uv run fmri-qa data/*_fMRI_*.nii.gz --artifact artifacts/
uv run fmri-qa-report artifacts/*.qa.nc --pdf qa.pdf
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--pdf` | required | write the PDF report to this file |
| `--tier` | `dashboard` | `dashboard` (condensed overview) or `physics` (adds stability, characterization, and methods pages) per scan |
| `--cover` | — | prepend a cover page listing the scans in the packet |
| `--appendix` | — | append a provenance page (per-scan metadata + version) |

An artifact that cannot be read is reported on stderr, skipped, and the run
exits non-zero — but the packet is still written, and it says what it is
missing: the cover counts the scans against those requested and lists the
omitted ones with the reason, the appendix carries a row for each, every scan
page's footer reads INCOMPLETE PACKET, and the PDF's subject metadata counts
them. A page handed on alone must not read as the whole.

Each page carries the metadata and metrics, the four summary images (signal,
SFNR, fluctuation noise, static spatial noise) with the phantom mask and ROI
overlaid, the Weisskoff plot, the ROI signal with its fitted trend, and the
residual time course, spectrum, per-frame outlier fraction, per-frame in-plane
motion (translation and scale/shear strain, with the count of any frames whose
fit did not resolve), and the directional PSF curves (PE and RO). `--tier
physics` follows that dashboard overview with a full-size stability page, a
per-metric characterization table (value + definition), and a methods page
describing how each metric is computed.

Several scans combine into one branded packet: `--cover` prepends a cover with
the scan inventory and `--appendix` appends a provenance page, and a running
footer carries page numbers once the packet spans pages. The cover
title, logo, footer text, fonts, and colours all come from a `report.Theme`, so
a group brands every packet it issues from one object (see the library section).

## Library

### Calculating

```python
import fmriqc as q

scan = q.QAScan.from_nifti("scan.nii.gz")
artifact = q.analyze(scan, name="scan.nii.gz")
m = artifact.measurements
print(m.snr, m.sfnr, m.rdc, m.drift_pct)

q.save_artifact(artifact, "qa.nc")
```

`analyze` is the front door, but the pipeline underneath is a linear chain of
small functions, each usable on its own:

```
QAScan → preprocess → QAImages → detect_phantom → resolve_roi
       → {weisskoff, snr, sfnr, estimate_ghost}
       → QAResult → build_artifact → QAArtifact
```

`preprocess` trims the series, selects the slice, detrends per voxel, and
returns a `QAImages` holding the center slice plus its fluctuations; the summary
images (mean, MIP, static noise, fluctuation noise, trend) are derived
properties. The full multi-slice volume can be discarded once `QAImages` exists.
`QAImages` owns read-only copies of its arrays, so changing the input cannot
invalidate these cached summaries. Artifact arrays likewise own read-only
copies; make an explicit array copy when writable working data is needed.
`run_qa` gathers the metrics into a `QAResult` — the pipeline's working output,
with the images still attached and the settings it was asked for written on it
— and `build_artifact` projects that into the `QAArtifact` everything
downstream reads. The artifact has five sections
(`settings`, `provenance`, `measurements`, `curves`, `images`) and is fully
resolved: a consumer never recomputes a metric.

### Reporting

```python
from pathlib import Path

import fmriqc as q
import fmriqc_report as report

artifact = q.load_artifact("qa.nc")

theme = report.Theme(
    font_title="Times-Bold",
    panel_accent="#1a4d7a",
    logo=Path("group-logo.png"),
    footer="Acme MR Physics · confidential",
    cover_title="Acme Phantom QA",
)
report.write_report(
    [("run-1", artifact)],
    "packet.pdf",
    tier="physics",
    theme=theme,
    cover=True,
    appendix=True,
)
```

Inside `fmriqc_report`, content is separated from format: `summary` (metadata
text), `content` (the per-metric catalog), and `panels` (the figures) know
nothing about PDFs, while `theme` supplies one `Theme` object driving both the
page furniture and the matplotlib panels, and a `formats` driver composes them
by walking the `document` block model (cover, tiered scan sections, appendix).
A group brands every packet it issues from that one `Theme`.

Large scan inventories and provenance appendices continue onto additional
pages. PDF output is written atomically: a rendering failure leaves any
existing destination file unchanged and makes the CLI exit non-zero.

## License

fmri-qa is available under the [MIT License](LICENSE).
