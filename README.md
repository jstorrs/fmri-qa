# fmri-qa

Phantom fMRI quality-assurance metrics, following the Glover/fBIRN stability
protocol (Friedman & Glover, 2006). Given a 4-D phantom time series it reports
SNR, SFNR, the Weisskoff radius of decorrelation (RDC), drift, temporal
fluctuation, and two Nyquist-ghost measures (fBIRN percent ghost and the
ACR/AAPM ghosting ratio), and can render a one-page PDF report per scan.

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
| **fwPE** / **fwRO** | spatial smoothness of the noise field (AFNI 3dFWHMx): Gaussian FWHM of the detrended fluctuations over the phantom along the phase-encode and readout axes, in mm (voxels if the voxel size is unknown) |

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

The phase-encode axis (used to place the ghost) is read from the NIfTI header
`dim_info`; if that is missing it falls back to estimating the axis from where
the Nyquist ghost lands. Override with `--pe-axis`.

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

## Install

The project uses [uv](https://docs.astral.sh/uv/) and Python 3.13:

```bash
uv sync
```

The QA metrics and CLI need only the core dependencies installed above. The
exploratory notebooks (DICOM conversion, BIDS, and interactive viewers) pull in
a heavier stack — install it with the `notebooks` extra:

```bash
uv sync --extra notebooks
```

## Command line

```bash
uv run fmri-qa [options] scan.nii.gz [more.nii.gz ...]
```

```
# detrend=poly  trim_sec=5.0  center=image  roi_size=21
scan                                      PE       SNR      SFNR      RDC   drift%   ghost%     ghT%      RO%    ACRg%   outl%   tcOut  spcOut   clip  clipPre    motn    scl%    shr%    com   fwPE   fwRO
-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
FBIRN_QA_fMRI_flip77_13.nii.gz           col     467.3     452.0   10.953    0.303    4.092    6.643    4.059    0.033   0.211    2.48    5.19      0        0   0.017   0.198   0.015  0.007   2.19   2.72
ABCD_QA_fMRI_16.nii.gz                   col      76.7      75.3   13.355    0.682    5.074   10.084    3.192    1.882   0.077    3.30    5.86      0       68   0.025   0.268   0.034  0.094   1.53   2.17
```

Options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--trim-sec` | `5.0` | seconds of initial (non-steady-state) volumes to drop |
| `--pe-axis` | header | override the phase-encode axis (`0`/`1`/`2`) |
| `--detrend` | `poly` | detrending method (`poly` or `spline`) |
| `--center` | `image` | localization mode (`image` or `phantom`) |
| `--roi-size` | `21` | summary/Weisskoff ROI side, in voxels |
| `--json` | — | emit the metrics as JSON on stdout instead of the text table |
| `--pdf` | — | write a PDF report to this file |
| `--pdf-tier` | `dashboard` | `dashboard` (condensed overview) or `physics` (adds a stability page) per scan |
| `--pdf-cover` | — | prepend a cover page listing the scans in the packet |
| `--pdf-appendix` | — | append a provenance page (per-scan metadata + version) |

`--version` prints the version and exits.

Multiple scans are summarized in one table and, with `--pdf`, combined into a
single PDF (one page per scan by default). A bad file is reported to stderr and
the batch continues; the process exits non-zero if any file failed.

With `--json`, stdout carries a single JSON document — `{"config": {...},
"scans": [...]}`, one record per scan with the same fields as the table columns
as raw numbers — while the banner, any errors, and the PDF notice go to stderr,
so `fmri-qa --json scan.nii.gz | jq` stays clean:

```bash
uv run fmri-qa --json data/*_fMRI_*.nii.gz > qa.json
```

### PDF report

```bash
uv run fmri-qa --pdf qa.pdf data/*_fMRI_*.nii.gz
```

Each page carries the metadata and metrics, the four summary images (signal,
SFNR, fluctuation noise, static spatial noise) with the phantom mask and ROI
overlaid, the Weisskoff plot, the ROI signal with its fitted trend, and the
residual time course, spectrum, per-frame outlier fraction, per-frame in-plane
motion (translation and scale/shear strain), and the directional PSF curves (PE
and RO). `--pdf-tier physics` follows that dashboard overview with a full-size
stability page.

Several scans combine into one branded packet: `--pdf-cover` prepends a cover
with the scan inventory and `--pdf-appendix` appends a provenance page, and a
running footer carries page numbers once the packet spans pages. The cover
title, logo, footer text, fonts, and colours all come from a `report.Theme`, so
a group brands every packet it issues from one object (see the library section).

## Library

```python
import fmriqc as q

scan = q.QAScan.from_nifti("scan.nii.gz")
result = q.run_qa(scan)              # QAResult: images, geom, roi, metrics
m = result.metrics
print(m.snr, m.sfnr, m.rdc, m.drift_pct)
```

The pipeline is a linear chain of small functions, each usable on its own:

```
QAScan → preprocess → QAImages → detect_phantom → resolve_roi
       → {weisskoff, snr, sfnr, ghost_ratio, acr_ghosting_ratio}
```

`preprocess` trims the series, selects the slice, detrends per voxel, and
returns a `QAImages` holding the center slice plus its fluctuations; the summary
images (mean, MIP, static noise, fluctuation noise, trend) are derived
properties. The full multi-slice volume can be discarded once `QAImages` exists.
PDF rendering lives in the `fmriqc/report/` subpackage (format-agnostic
`summary` text and `panels` figures, composed by a `formats` driver; imported
only when `--pdf` is used).
