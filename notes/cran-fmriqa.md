# `cran-fmriqa` vs FBIRN/GSQAP (Glover 2005; Friedman & Glover 2006)

## Overview
`cran-fmriqa` (R package `fmriqa`) implements a stability-phantom QA workflow that is largely aligned with the GSQAP/FBIRN protocol, operating on NIfTI fMRI time series (typically a single phantom slice) and producing the standard mean/DIFF/TFN/SFNR images plus summary stability metrics.

Key entry point: `cran-fmriqa/R/run_fmriqa.R`.

---

## What GSQAP/FBIRN components are implemented

**Inputs / protocol handling**
- Uses a phantom fMRI time series and analyzes a single slice (default: middle slice) (`cran-fmriqa/R/run_fmriqa.R:117`, `cran-fmriqa/R/run_fmriqa.R:146`).
- Skips initial volumes (default `skip=2`, matching “discard first two”) (`cran-fmriqa/R/run_fmriqa.R:47`, `cran-fmriqa/R/run_fmriqa.R:125`).
- Default ROI width is 21 pixels/voxels (GSQAP default) (`cran-fmriqa/R/run_fmriqa.R:47`).

**Computed images (GSQAP-style)**
- Mean/signal image: voxelwise mean over analyzed volumes (`cran-fmriqa/R/run_fmriqa.R:157`).
- Temporal fluctuation noise (TFN): voxelwise SD of detrended residuals (`cran-fmriqa/R/run_fmriqa.R:149`, `cran-fmriqa/R/run_fmriqa.R:155`).
- SFNR map: mean/TFN (`cran-fmriqa/R/run_fmriqa.R:158`).
- Static spatial noise (odd-even) DIFF image: `sum(odd) - sum(even)` (`cran-fmriqa/R/run_fmriqa.R:160`).

**Summary metrics (GSQAP-style)**
- ROI SFNR: mean SFNR within ROI (`cran-fmriqa/R/run_fmriqa.R:234`).
- ROI SNR (DIFF-based): `signal_mean / sqrt(var(DIFF_ROI)/N_used)` (`cran-fmriqa/R/run_fmriqa.R:241`).
- Percent fluctuation: `100 * SD(residuals) / mean(signal)` for ROI mean time course (`cran-fmriqa/R/run_fmriqa.R:252`).
- Drift from fit curve (GSQAP definition): `drift_fit = 100*(max(fit)-min(fit))/mean(signal)` (`cran-fmriqa/R/run_fmriqa.R:253`).
- FFT spectrum of detrended ROI residuals (DC-suppressed by omission) with frequency axis in Hz (`cran-fmriqa/R/run_fmriqa.R:257`, `cran-fmriqa/R/run_fmriqa.R:266`).
- Weisskoff-style CV curve and RDC: CV for ROI widths 1..`roi_width` and `RDC = CV(1)/CV(Nmax)` (`cran-fmriqa/R/run_fmriqa.R:282`, `cran-fmriqa/R/run_fmriqa.R:304`).

---

## Notable differences from the published GSQAP/FBIRN description

- **Detrending order default differs**: GSQAP/FBIRN describes 2nd-order polynomial detrending; `fmriqa` defaults to **3rd-order** (`poly_det_ord=3`) (`cran-fmriqa/R/run_fmriqa.R:47`, see also `cran-fmriqa/NEWS.md:15`). This affects TFN/SFNR, percent fluctuation, drift_fit, RDC, and the FFT residual spectrum.
- **ROI placement differs by default**: GSQAP/FBIRN uses a centered ROI; `fmriqa` by default places ROI at an automatically detected object “center of gravity” derived from edge detection + flood fill, unless `x_pos/y_pos` are supplied (`cran-fmriqa/R/run_fmriqa.R:180`, `cran-fmriqa/R/run_fmriqa.R:207`).
- **Drift reporting includes two variants**:
  - `drift_fit` (fit-based; closest to GSQAP definition) and
  - `drift` (raw max-min over time, not the GSQAP definition) (`cran-fmriqa/R/run_fmriqa.R:252`).
- **RDC implementation is the “ratio” form**: `RDC = CV(1)/CV(Nmax)` (as described in the paper). It does not additionally report the “graphical intercept” width interpretation.

---

## Innovations / extensions beyond GSQAP

- **Robust “outlier” scores (MAD-normalized)**:
  - `tc_outlier`: maximum absolute detrended slice mean time course value divided by MAD (`cran-fmriqa/R/run_fmriqa.R:277`).
  - `spec_outlier`: maximum FFT magnitude divided by MAD (`cran-fmriqa/R/run_fmriqa.R:261`).
  These provide simple, unitless anomaly indicators not specified in GSQAP.

- **Background (air) QA metrics**:
  - Automatic object/background separation and a **max background percent** metric (`max_bg_perc`) computed after shrinking away from the object and smoothing the background (`cran-fmriqa/R/run_fmriqa.R:189`).
  - Background mean image and a background drift plot (`cran-fmriqa/R/run_fmriqa.R:201`, `cran-fmriqa/R/run_fmriqa.R:422`).
  This is an extension beyond the GSQAP’s DIFF/TFN/SFNR focus and is useful for detecting ghosting/leakage or reconstruction artifacts in “background” regions.

- **Optional k-space spike visualization** (`spike_detect=TRUE`):
  - Computes time-differences, transforms to k-space via FFT, then shows a max-projection “k-space slice differences” map (`cran-fmriqa/R/run_fmriqa.R:357`).
  This is a pragmatic addition for diagnosing RF spikes and related artifacts.

- **Workflow tooling for longitudinal use**:
  - `run_fmriqa_glob()` for batch processing and `combine_res_glob()` for aggregating CSV outputs (`cran-fmriqa/R/run_fmriqa.R:575`), enabling straightforward trending outside the package.

- **Performance-oriented implementation detail**:
  - Detrending uses `RcppEigen::fastLmPure` residuals (`cran-fmriqa/R/run_fmriqa.R:606`), which is a practical speed/robustness choice vs naive R regression loops.

---

## Gaps relative to the two documents’ full QA scope

- **No geometry phantom workflow** (monthly 3D fiducial measurement) from the Glover (2005) procedure.
- **No RF gain / resonant frequency extraction**: the papers highlight tracking receiver/transmit gains and center frequency when available; `fmriqa` operates on NIfTI and does not implement header-based hardware trending.
- **No formal spectral-peak significance testing** (the 2006 paper discusses peak P-values using neighborhood noise estimates); `fmriqa` provides spectrum and a robust “spec_outlier” but not statistical peak tests.

---

## Practical implications for comparison studies

- If you are benchmarking against GSQAP/FBIRN reference outputs, set `poly_det_ord=2` and (if needed) force ROI placement to the image center via `x_pos/y_pos`, otherwise results will differ systematically.
- Prefer `drift_fit` (fit-based) when comparing to the GSQAP “drift” definition.
