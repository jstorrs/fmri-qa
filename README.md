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
| **`fmri-qa-core`** | `fmriqc` | the metrics, the pipeline, and the **analysis artifact** they are published as | numpy, scipy, nibabel, scikit-image |
| **`fmri-qa-report`** | `fmriqc_report` | plots and multi-page PDF packets, built from an artifact | matplotlib, reportlab, svglib (+ core) |

A `QAArtifact` is the only thing that crosses: the run's settings, provenance,
scalar measurements, stability curves, and the four fBIRN summary images —
everything a report needs, and none of the heavy inputs. It saves to a single
`.npz`, so calculation and reporting are separate steps:

```bash
uv run fmri-qa scan.nii.gz --artifact qa.npz      # calculate once
uv run fmri-qa-report qa.npz --pdf report.pdf     # render as often as you like
```

Install the core alone where you only want numbers (a trend database, a console
script, a cron job) and skip the drawing stack entirely. See
[`notes/analysis_report_split.md`](notes/analysis_report_split.md) for the
rationale and the artifact's layout.

## Metrics

All scalar metrics are measured over a fixed square ROI (default 21×21, the
fBIRN size) on a single slice.

| Metric | Definition |
| --- | --- |
| **SNR** | ROI mean signal / `sqrt(var(odd-sum − even-sum) / n_frames)` |
| **SFNR** | ROI mean of the voxelwise `signal / temporal-fluctuation-noise` |
| **RDC** | Weisskoff radius of decorrelation: `cv1_pooled / cv[full ROI]` |
| **drift %** | peak-to-peak of the ROI-mean fitted trend, as % of mean signal |
| **fluctuation %** | SD of the ROI-mean residual, as % of mean signal |
| **ghost %** | fBIRN percent ghost: `100 × mean ghost region / mean signal region` |
| **ghT %** | PE percent ghost of the brightest 10% of ghost voxels (Greve / bxh ghostiness): a localized companion to `ghost %` on the same scale, so a bright ghost the region mean dilutes still shows (always `≥ ghost %`) |
| **RO %** | the same region-matched percent ghost measured along the readout axis — the background-relative baseline the ACR difference is taken against |
| **ACRg %** | ACR/AAPM percent-signal-ghosting: `100 × \|ghost_pe − ghost_freq\| / signal`, over the N/2-shifted phantom masks (i.e. `\|ghost % − RO %\|`) |
| **outl %** | worst-frame outlier-voxel fraction (AFNI 3dToutcount): `100 × max_t (outlier voxels / phantom voxels)`; a clean run sits near the 0.1% chance level |
| **tcOut** / **spcOut** | MAD-normalized spike scores of the ROI-mean residual — peak / robust-spread in the time domain (a transient volume) and on its DC-dropped FFT magnitude (a dominant periodic artifact); unitless, a clean phantom sits low (a few) and a spike stands well above |
| **clip** / **clipPre** | ADC-saturation counts: voxel·time samples pinned at the inferred `2ⁿ−1` rail, in the analyzed data (`clip`) vs. the dropped warm-up volumes (`clipPre`); `0` when none |
| **motn** | peak per-volume in-plane translation of the phantom vs. its temporal mean (voxels), from a 3dvolreg-style registration |
| **scl %** / **shr %** | peak per-volume scaling and shear strain of the phantom (percent) — the gradient-heating deformation the rotation-free motion model isolates |
| **com** | peak per-volume shift of the whole-slice intensity centroid from its temporal mean (circular COM, bxh volmeasures), in voxels — a cheap first-moment jump/drift trace complementing `motn` |
| **fwPE** / **fwRO** | spatial smoothness of the noise field (AFNI 3dFWHMx): Gaussian FWHM of the detrended fluctuations over the phantom along the phase-encode and readout axes, in mm (voxels if the voxel size is unknown); `?` in the table and `null` in the JSON when no phase-encode axis resolved and neither direction has a name |

Drift is removed before the noise metrics are measured, using either a Legendre
polynomial (`--detrend poly`, default) or a least-squares B-spline
(`--detrend spline`); in both cases the fit complexity is set from the run
duration.

## Localization

The `--center` mode controls both slice and ROI placement:

- **`image`** (default, Glover) — the geometric middle slice with a fixed
  21×21 ROI at the image-matrix center. Assumes the phantom is centered in the
  FOV.
- **`phantom`** — the slice with the largest phantom cross-section, with the ROI
  at the detected phantom center. More robust to a mispositioned phantom, but
  non-standard.

The phase-encode axis (used to place the ghost) comes from the BIDS JSON
sidecar `PhaseEncodingDirection` (or `InPlanePhaseEncodingDirectionDICOM`)
where one is present; failing that, from the NIfTI header `dim_info`; and only
if both are missing, from estimating the axis on the analyzed slice by where the
Nyquist ghost lands. `--pe-axis` overrides all three.

The current metrics operate on one image slice, so phase encoding must be
in-plane (NIfTI axis `0`/`i` or `1`/`j`). Through-plane (`2`/`k`) acquisitions
are rejected with an input error rather than being analyzed on the wrong plane.

## Saturation

The clip ceiling of the reconstruction is sequence-dependent and not recorded,
so it is inferred. A clipped magnitude image piles up on a hardware `2ⁿ−1` rail
(a 12-bit ADC gives 4095), so if the series maximum sits exactly on such a rail
the run may be saturated; a maximum that is *not* a `2ⁿ−1` value means no
clipping. The pile-up on that rail is then counted — but split at the trim
boundary: `clip` counts samples in the analyzed volumes (which bias the
metrics; a trailing `!` flags any), while `clipPre` counts samples confined to
the dropped warm-up volumes. The full, untrimmed series is checked because
clipping is worst in those high-signal warm-up volumes — but clipping there
doesn't reach the statistics, and is expected for sequences (e.g. ABCD) that
deliberately acquire through the approach to steady state. A lone sample on the
rail is likely just a bright voxel; a pile-up across a volume is real
saturation.

## Outliers

The `outl %` metric is a per-frame temporal-stability check, following AFNI's
`3dToutcount`. For each phantom voxel the robust spread of its detrended
residual is `σ = √(π/2)·MAD`, and a frame counts as an outlier for that voxel
when `|residual| > α·σ`, with `α = Q⁻¹(qthr / n_frames)` chosen so a clean voxel
flags a frame with probability `qthr` (0.001). The per-frame outlier fraction is
then the share of phantom voxels flagged; a stable run hovers near the 0.1%
chance level, and a frame standing well above it marks a bad volume. The
detrended residuals are the pipeline's Legendre-detrended fluctuations (as
afni_proc.py recommends detrending before outlier classification); the full
per-frame trace is plotted in the PDF report and `outl %` reports its worst
frame.

## Motion

The `motn` / `scl %` / `shr %` metrics come from a 3dvolreg-style per-volume
registration of the phantom to its temporal-mean image, following AFNI's
`3dvolreg` but with a model tailored to a rigid phantom. A stationary phantom
cannot rotate, so the rotation degrees of freedom are dropped; what gradient
heating *does* produce is a slow translation plus a scaling and shear of the
image as the gradient calibration drifts. The registration therefore fits a 2-D
affine restricted to translation + symmetric strain (anisotropic scale + shear)
— five parameters, no rotation — per frame, by forward-additive Lucas-Kanade
over the phantom mask, pivoting the strain at the phantom centroid so
translation and deformation stay separable. `motn` is the peak translation
magnitude (voxels), `scl %` the peak scaling, and `shr %` the peak shear; the
full per-frame translation and strain traces are plotted in the PDF report,
where a slow monotonic strain ramp is the thermal-drift signature. This is a
diagnostic only — the analyzed series is **not** resampled from the fit, so the
FBIRN metrics stay measured on the acquired data.

## Smoothness

The `fwPE` / `fwRO` metrics are the spatial smoothness of the noise field along
the phase-encode and readout axes, following AFNI's `3dFWHMx`. The guide warns
that the Weisskoff RDC is confounded by smoothness — a smoother noise field
decorrelates more slowly and inflates the RDC — so an explicit FWHM complements
it, and splitting it by direction exposes anisotropic reconstruction smoothing
(the PE and RO axes are filtered differently). For each in-plane axis the
Gaussian FWHM is recovered from the variance of the noise field's forward first
differences (the Classic `mri_estimate_FWHM_1dif` estimator): for a smoothed
white-noise field the first-difference variance relates to the voxel variance by
`arg = 1 − 0.5·var_diff/var`, giving `σ = √(−1 / (4·ln arg))` and
`FWHM = √(8 ln 2)·σ`. It is estimated on the pipeline's detrended fluctuations —
each voxel robustly standardized over time (median removed, divided by its MAD,
AFNI's `-unif`, so the estimate reflects correlation length rather than the
spatially varying noise amplitude) — on each frame over the phantom mask, and
aggregated across frames by geometric mean (AFNI `-geom`). The axes are labeled
`PE`/`RO` from the phase-encode direction; `SmoothnessResult.fwhm` also exposes
the combined (geometric-mean) FWHM (AFNI `ccomb`).

### Point-spread curves

The PDF report plots a directional **point-spread function** (PSF) alongside the
FWHM numbers. Because the noise field is a PSF convolved with white noise, its
normalized spatial autocorrelation is the autocorrelation of the PSF, which for a
Gaussian equals `PSF²`; squaring the measured autocorrelation of the noise field
at each lag therefore recovers the empirical point-spread profile. The report
overlays those empirical points on the Gaussian PSF implied by the Classic FWHM,
for both PE and RO — a narrower curve is a sharper direction, and empirical points
falling off the Gaussian flag a non-Gaussian (e.g. long-tailed) point spread.

## Thermal vs. instability noise (high/low flip)

A separate `fmri-qa-hilo` command separates a phantom's noise into its **thermal**
(additive, electronic) and **instability** (multiplicative: drift, gradient
heating, physiological-like fluctuation) components, following Doug Greve's
high/low flip-angle method. It needs two runs of the same acquisition that differ
*only* in flip angle: thermal-noise variance is independent of signal level, while
instability-noise variance scales with signal², so acquiring at a high and a low
flip angle gives two equations that solve for the two components. With the squared
signal ratio `M = (mean_high / mean_low)²`,

```
ThermalVar      = (M · VarLow − VarHigh) / (M − 1)
InstabilityVar  = VarHigh − ThermalVar
```

(falling back to `ThermalVar = VarLow`, `InstabilityVar = VarHigh − VarLow` if the
separation drives the instability variance negative), and
`ThermalFSNR = MeanHigh / √ThermalVar`, `InstabilityFSNR = MeanHigh / √InstabilityVar`.
Each scan is reduced to a temporal-mean map and a temporal-SD-of-detrended-residual
map over the whole volume, and the statistics are pooled over the **shared** eroded
phantom core — the intersection of the two runs' `3dAutomask -erode 5`-style masks,
so both means cover identical voxels. A high `InstabilityFSNR` (small
`InstabilityVar` relative to `VarHigh`) is a stable scanner.

```bash
uv run fmri-qa-hilo HIGH_flip.nii.gz LOW_flip.nii.gz
```

```
# hi/lo flip-angle thermal/instability noise separation (Greve)
# high = FBIRN_QA_fMRI_flip77_14.nii.gz (flip 77)
# low  = FBIRN_QA_fMRI_flip10_15.nii.gz (flip 10)
# core voxels = 20502
ThermalFSNR                639.6224
InstabilityFSNR           3083.9969
MeanHigh                  1023.3249
MeanLow                    184.3902
VarHigh                      2.6697
VarLow                       2.5632
ThermalVar                   2.5596
InstabilityVar               0.1101
M                           30.8000
InstabilityFraction          0.0412
```

Pass the high-flip scan first (a warning fires if the flip angles say otherwise).
`--trim-sec`, `--detrend`, and `--erode` mirror the main command. This is a
pair-level diagnostic, kept apart from the per-scan batch table.

The pair must match in array geometry, frame count, affine, voxel size, TR, and
TE (when recorded); incompatibilities are rejected before either scan is
processed so differently sampled acquisitions cannot be pooled by array index.

## Install

The project uses [uv](https://docs.astral.sh/uv/) and Python 3.13. The repo is a
uv workspace holding both packages; syncing all of it gives the full development
environment:

```bash
uv sync --all-packages
```

Downstream, install whichever half you need — `fmri-qa-report` pulls in
`fmri-qa-core`, so installing it gives you both commands:

```bash
pip install fmri-qa-core      # metrics and artifacts only
pip install fmri-qa-report    # + plots and PDF packets
```

Published work using the package should cite the software metadata in
[`CITATION.cff`](CITATION.cff). User-facing changes are recorded in
[`CHANGELOG.md`](CHANGELOG.md).

The exploratory notebooks (DICOM conversion, BIDS, and interactive viewers) pull
in a heavier stack. It is development tooling, not part of either published
distribution, so it lives in the workspace's `notebooks` dependency group and
stays out of the default sync:

```bash
make sync-notebooks    # uv sync --all-packages --all-extras --group notebooks
```

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

`--artifact PATH` writes the complete analysis result — settings, provenance,
every measurement and curve, and the summary images — as a compressed `.npz`.
With a single scan `PATH` is the output file; with several it is a directory
taking one `<scan>.qa.npz` per scan:

```bash
uv run fmri-qa data/*_fMRI_*.nii.gz --artifact artifacts/
```

The file records the schema it was written under, and a later build reads it:
an older layout is migrated forward on load, with a warning, and any field that
schema did not carry comes back as "not recorded" rather than as a value nothing
measured. Only an artifact from a *newer* build than the one reading it is
refused, since its layout cannot be known.

With `--json`, stdout carries a single versioned JSON document —
`{"schema_version": 3, "config": {...}, "scans": [...]}`, one record per scan
with the table's columns as raw numbers. A metric that cannot be computed for a
scan is JSON `null` (for example, a ghost ratio with no clear ghost region),
never a non-standard `NaN` or `Infinity` token. Each record leads with
`phantom_fraction`, `phantom_mask_ok`, and `roi_inside_phantom` — the table's
`loc` column — which say whether the phantom mask and the summary ROI landed
where they must; when either failed, every mask-based number in that record was
measured on background.

A record also carries a little the table has no room for, because a row filed in
a trend database outlives the terminal it was printed to: `source` and
`datetime` key and date it, `tr`, `n_frames` and `n_trimmed` say what series the
numbers describe, and `outlier_worst_frame` names the worst outlier volume —
counted from the analyzed series, so adding `n_trimmed` gives the acquired
volume number. The banner, any
errors, and any save notices go to stderr, so
`fmri-qa --json scan.nii.gz | jq` stays clean:

```bash
uv run fmri-qa --json data/*_fMRI_*.nii.gz > qa.json
```

## PDF report

Reporting reads artifacts, never scans:

```bash
uv run fmri-qa data/*_fMRI_*.nii.gz --artifact artifacts/
uv run fmri-qa-report artifacts/*.qa.npz --pdf qa.pdf
```

| Flag | Default | Meaning |
| --- | --- | --- |
| `--pdf` | required | write the PDF report to this file |
| `--tier` | `dashboard` | `dashboard` (condensed overview) or `physics` (adds stability, characterization, and methods pages) per scan |
| `--cover` | — | prepend a cover page listing the scans in the packet |
| `--appendix` | — | append a provenance page (per-scan metadata + version) |

Each page carries the metadata and metrics, the four summary images (signal,
SFNR, fluctuation noise, static spatial noise) with the phantom mask and ROI
overlaid, the Weisskoff plot, the ROI signal with its fitted trend, and the
residual time course, spectrum, per-frame outlier fraction, per-frame in-plane
motion (translation and scale/shear strain), and the directional PSF curves (PE
and RO). `--tier physics` follows that dashboard overview with a full-size
stability page, a per-metric characterization table (value + definition), and a
methods page describing how each metric is computed.

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

q.save_artifact(artifact, "qa.npz")
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
`run_qa` gathers the metrics into a `QAResult` — the pipeline's working output,
with the images still attached — and `build_artifact` projects that into the
`QAArtifact` everything downstream reads. The artifact has five sections
(`settings`, `provenance`, `measurements`, `curves`, `images`) and is fully
resolved: a consumer never recomputes a metric.

### Reporting

```python
from pathlib import Path

import fmriqc as q
import fmriqc_report as report

artifact = q.load_artifact("qa.npz")

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
