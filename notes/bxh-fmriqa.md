# `bxh-fmriqa` vs FBIRN/GSQAP (Glover 2005; Friedman & Glover 2006)

## Overview
`bxh-fmriqa` is a **toolchain** (C/C++ programs + Perl wrappers) extracted from a larger BXH/XCEDE-based imaging project. It contains:

- A close implementation of the **FBIRN/GSQAP stability phantom** calculations (mean/DIFF/SD/SFNR + ROI drift/fluctuation + FFT + Weisskoff/RDC).
- A broader **run-level QA report generator** with additional metrics (volume means, center-of-mass, outlier counts, smoothness/FWHM, spike metrics, and ghosting metrics), often via **AFNI** tools.
- HTML/plot/reporting and XCEDE-style event output to support longitudinal QA review.

Key entry points:
- `bxh-fmriqa/fmriqa_phantomqa.c` (core GSQAP-like computations)
- `bxh-fmriqa/fmriqa_phantomqa.pl` (wrapper that runs the program and generates plots/HTML)
- `bxh-fmriqa/fmriqa_generate.pl` (broader QA report generator)
- Additional C/C++ utilities: `fmriqa_spikiness.cpp`, `fmriqa_ghostiness.c`, `fmriqa_volmeasures.cpp`, etc.

---

## What GSQAP/FBIRN components are implemented (stability phantom)

### Volume handling / TR
- Default time selection drops initial volumes and enforces an **even** number of time points for odd-even calculations:
  - `fmriqa_phantomqa.c` defaults to `2:` for even-length runs, `3:` for odd-length runs, then requires divisible-by-2 timepoint count (`bxh-fmriqa/fmriqa_phantomqa.c:~196` and `bxh-fmriqa/fmriqa_phantomqa.c:~200`).
- Uses TR from `<acquisitiondata><tr>` (ms) or time-dimension spacing; supports overriding via `--forcetr` (`bxh-fmriqa/fmriqa_phantomqa.c:~280`).

### Central slice + ROI
- Computes on a **single selected slice** (default: middle slice) (`bxh-fmriqa/fmriqa_phantomqa.c:~159`).
- Default ROI is centered square, but size differs from GSQAP:
  - Defaults to **15×15** for most matrices, **30×30** for 128×128 unless overridden (`bxh-fmriqa/fmriqa_phantomqa.c:~300`).
- Supports providing a full mask via `--maskfile` instead of the centered ROI mask (`bxh-fmriqa/fmriqa_phantomqa.c:~325`).

### Mean / DIFF / SD(residual) / SFNR images
`fmriqa_phantomqa.c` reproduces the GSQAP image set for the selected slice:
- Odd/even cumulative sums and DIFF image (`Iodd - Ieven`) (`bxh-fmriqa/fmriqa_phantomqa.c:~340`).
- Mean image `Iave = (Iodd + Ieven) / N` (`bxh-fmriqa/fmriqa_phantomqa.c:~372`).
- Temporal fluctuation noise image: voxelwise SD of residuals after **2nd-order polynomial fit** (via GSL) (`bxh-fmriqa/fmriqa_phantomqa.c:~394`).
- SFNR image: `mean / (sd + eps)` (`bxh-fmriqa/fmriqa_phantomqa.c:~443`).
- Writes these images as `_ave`, `_nave` (DIFF), `_std`, `_sfnr` when not in `--summaryonly` mode (`bxh-fmriqa/fmriqa_phantomqa.c:~530`).

### SNR and SFNR summary values (ROI/mask)
- Computes SNR from ROI/mask mean and DIFF variance:
  - `snr = meanI / sqrt(var(DIFF_ROI) / N)` (`bxh-fmriqa/fmriqa_phantomqa.c:~640`).
- Computes SFNR summary as mean SFNR within ROI/mask (`bxh-fmriqa/fmriqa_phantomqa.c:~622`).

### Percent fluctuation, drift, driftfit (ROI time series)
- Uses ROI-mean time series and **2nd-order polynomial fit**:
  - `std` = SD of detrended residuals
  - `percent fluc` = `100 * std / mean(ROI_mean_ts)`
  - `drift` = `100 * (max(raw ROI ts) - min(raw ROI ts)) / mean`
  - `driftfit` = `100 * (max(fit) - min(fit)) / mean`
  (`bxh-fmriqa/fmriqa_phantomqa.c:~674`).
- Emits the raw and fitted series for plotting (`bxh-fmriqa/fmriqa_phantomqa.c:~758`).

### FFT residual spectrum (ROI residuals)
- Computes FFT of detrended ROI residuals (real FFT via GSL) and prints a frequency vs magnitude table (`bxh-fmriqa/fmriqa_phantomqa.c:~790`).
- **Notable extension**: spectrum magnitude is scaled as a **percent of mean signal** (`* 100/m`) (`bxh-fmriqa/fmriqa_phantomqa.c:~835`), matching the “normalized spectrum” improvement discussed in the 2006 paper.

### Weisskoff analysis + RDC
- Computes Weisskoff CV curve for ROI widths 1..R, with 2nd-order detrend at each ROI size:
  - `F(r) = 100 * SD(residuals) / mean(fit)` and ideal `F(1)/r`
  - `RDC = F(1) / F(R)` (`bxh-fmriqa/fmriqa_phantomqa.c:~870`).
- Emits measured and theoretical curves for plotting.

---

## Differences from `cran-fmriqa` (R package) and from “pure” GSQAP

### Compared to GSQAP paper defaults
- **ROI size default** differs (15/30 vs 21) and is matrix-dependent in `bxh-fmriqa`.
- **Timepoint skipping** is more defensive: defaults to skipping 2 or 3 to guarantee an even number of volumes for odd-even DIFF calculations.
- FFT spectrum is already **normalized by mean** (percent units), whereas the paper describes this as a future improvement.

### Compared to `cran-fmriqa`
- `bxh-fmriqa` uses **2nd-order detrending** in the GSQAP computations; `cran-fmriqa` defaults to 3rd order unless configured.
- `bxh-fmriqa` is **not NIfTI-first**: primary I/O is BXH/XCEDE-wrapped data, with converters used in wrappers; `cran-fmriqa` reads NIfTI directly.
- `bxh-fmriqa` emphasizes a multi-tool pipeline (AFNI + compiled tools + HTML reports), while `cran-fmriqa` is mostly self-contained and returns a single table + plots.

---

## Innovations / extensions beyond GSQAP/FBIRN

The directory implements a wider QA concept than the original phantom stability report:

### AFNI-integrated pipelines (wrapper-level)
`fmriqa_phantomqa.pl` describes multiple “input data types” including AFNI-based preprocessing:
- Motion correction (`3dvolreg`) + detrending (`3dDetrend -polort 2`) + mask generation (`3dAutomask`) for AFNI-derived measures.
- FWHM smoothness measures using AFNI `3dFWHMx`.
This extends GSQAP from “phantom stability under fMRI protocol” to “stability + preprocessing-aware diagnostics.”

### Smoothness/FWHM tracking
Explicit FWHM reporting (AFNI `3dFWHMx`) is an important extension because GSQAP metrics (especially RDC, and even SNR/SFNR) can be confounded by effective spatial smoothness.

### Ghosting/“ghostiness” metric
`fmriqa_ghostiness.c` builds a phase-encode-direction ghost mask by shifting the mask by half-FOV and reports ghost-region statistics (including top-10% ghost voxels). The wrapper text links this to Greve et al. (2011) as a scanner instability quantification method (`bxh-fmriqa/fmriqa_steps.txt`).

### Spikiness metrics (beyond simple spectra)
`fmriqa_spikiness.cpp` implements voxel/slice “spikiness” measures with multiple detrending/fit strategies (mean, L1 linear, AFNI-like model) and multiple outputs (per-voxel z-scores, slice summaries, jackknife z-scores). This targets transient spikes that can be missed by average SNR/SFNR.

### Per-volume QA measures and motion proxies
`fmriqa_volmeasures.cpp` computes per-volume mean/min/max/stddev and **center-of-mass** (optionally under a mask), enabling detection of drift, jumps, or gross motion/instability patterns not captured by GSQAP ROI-only summaries.

### Additional utilities used by report generator
`fmriqa_generate.pl` (see `bxh-fmriqa/fmriqa_steps.txt`) adds:
- Clipping/overflow checks (data type saturation)
- Volume means and “mean volume difference”
- Mask generation via histogram minima
- High-pass detrending (60s period) for some plots
- Running differences of masked/detrended means
- Outlier counts via AFNI `3dToutcount`
- Spectrum plots (raw) and SFNR visualization for mid-slice voxels

### High/low flip-angle phantom QA
`fmriqa_hilo.pl` implements a separate phantom QA protocol (Greve/MGH) producing metrics such as ThermalFSNR and InstabilityFSNR, based on high- vs low-flip scans. This is outside the original GSQAP scope and is a clear extension.

---

## Practical implications for evaluation/benchmarking

- To compare `bxh-fmriqa` “GSQAP-like” outputs to GSQAP/FBIRN benchmarks, control:
  - ROI size (`--roisize`) to match 21×21 if desired
  - Time selection (`--timeselect`) to match “discard first 2” exactly (and keep an even count)
- Prefer `driftfit` when matching the GSQAP drift definition; `drift` is also reported (raw min/max), which is not the GSQAP drift definition.
- Expect additional measures (FWHM, ghostiness, spikiness, volume measures) to provide richer diagnostics than GSQAP alone, at the cost of extra dependencies (AFNI, GSL) and a more complex pipeline.

