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
| **ACRg %** | ACR/AAPM percent-signal-ghosting: `100 × \|ghost_pe − ghost_freq\| / signal`, over the N/2-shifted phantom masks |

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
scan                                      PE       SNR      SFNR      RDC   drift%   ghost%    ACRg%
----------------------------------------------------------------------------------------------------
FBIRN_QA_fMRI_flip77_13.nii.gz             j     467.3     452.0   10.953    0.303    4.153    0.606
ABCD_QA_fMRI_16.nii.gz                     j      76.7      75.3   13.355    0.682    5.126    2.378
```

Options:

| Flag | Default | Meaning |
| --- | --- | --- |
| `--trim-sec` | `5.0` | seconds of initial (non-steady-state) volumes to drop |
| `--pe-axis` | header | override the phase-encode axis (`0`/`1`/`2`) |
| `--detrend` | `poly` | detrending method (`poly` or `spline`) |
| `--center` | `image` | localization mode (`image` or `phantom`) |
| `--roi-size` | `21` | summary/Weisskoff ROI side, in voxels |
| `--pdf` | — | write a PDF report to this file |
| `--pdf-layout` | `one` | `one` condensed page or `two` pages per scan |

Multiple scans are summarized in one table and, with `--pdf`, combined into a
single PDF (one page per scan by default). A bad file is reported to stderr and
the batch continues; the process exits non-zero if any file failed.

### PDF report

```bash
uv run fmri-qa --pdf qa.pdf data/*_fMRI_*.nii.gz
```

Each page carries the metadata and metrics, the four summary images (signal,
SFNR, fluctuation noise, static spatial noise) with the phantom mask and ROI
overlaid, the Weisskoff plot, the ROI signal with its fitted trend, and the
residual time course and spectrum. `--pdf-layout two` splits these across a
summary page and a stability page.

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
PDF rendering lives in `fmriqc/report.py` (imported only when `--pdf` is used).
