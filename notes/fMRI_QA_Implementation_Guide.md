# fMRI QA Implementation Guide (FBIRN/GSQAP + Geometry Phantom)

This guide is a **conformance checklist** and **evaluation rubric** for determining whether an fMRI QA tool implements the measurements/analyses described in:

- `Glover - 2005 - FBIRN Stability phantom QA procedures.pdf`
- `Friedman and Glover - 2006 - Report on a multicenter fMRI quality assurance pro.pdf`

It focuses on **phantom-based fMRI temporal stability QA** (GSQAP/FBIRN) and the **monthly geometry phantom** check.

---

## 1) Conformance Levels (what “implements it” means)

Define a target level for a software package and evaluate against the corresponding checklist:

- **Level A — Core stability metrics**: SNR, SFNR, percent fluctuation, drift; required preprocessing/ROI rules; standard plots.
- **Level B — Diagnostic stability metrics**: FFT spectrum of residuals; Weisskoff analysis + RDC/“correlation diameter”; required computed maps; optional header-based gain/frequency.
- **Level C — Longitudinal QA support**: time-stamped logging, trend plots, control limits, annotations for service/upgrades, automated flagging.
- **Level D — Geometry QA**: 3D geometry phantom workflow + measurement reporting.

If your goal is a close match to the published FIRST-BIRN practice, target **Level B + C**.

---

## 2) Inputs and acquisition requirements (what software must accept)

### 2.1 Stability phantom acquisition (weekly)

**Required**
- Accept a **time series** of fMRI-like images acquired with the **same head coil and sequence** used for human fMRI (EPI or spiral GRE), with the phantom scanned in **straight axial** orientation.
- Support **200 time points/volumes** (the publications use 200; analysis uses 198 after discarding 2).
- Support analysis from the **middle/central slice** (FBIRN procedure focuses on a single central slice; GSQAP describes “middle slice through the phantom”).

**Recommended**
- Support both central-slice-only workflows and full-3D (all slices) storage while still reproducing the published **central-slice** calculations.
- Record protocol parameters in the output: TR, TE, flip, matrix size, bandwidth, number of volumes, slice thickness/gap.

**Implementation check**
- Confirm the software either (a) explicitly requires 200 volumes or (b) supports arbitrary length but matches the published outputs when `N=200`.
- Confirm it can reproduce results when only one slice is provided (2D+time).

### 2.2 Geometry phantom acquisition (monthly)

**Required**
- Accept a **3D SPGR/FLASH** (or equivalent) high-resolution scan of a 3D geometry phantom with fiducials on **15 mm centers** (Data Spectrum MRI/3D-GEO/P described in the procedure).

**Implementation check**
- Confirm the tool’s geometry workflow is separate from the weekly stability workflow and produces geometric accuracy measurements (not SNR/SFNR).

---

## 3) Preprocessing rules (must match publications)

### 3.1 Volume handling

**Required**
- Discard the **first two** acquired volumes before analysis.
  - Published rationale: allow NMR equilibrium / eddy-current equilibrium.

**Evaluation**
- Verify the tool reports “volumes used” and that it uses `N_used = N_total - 2` by default.

### 3.2 ROI definition

The papers/procedure use a centered square ROI on the phantom image:

- FBIRN procedure: **20×20 pixels** (example) for some outputs.
- GSQAP paper: **21×21 voxels** as the standard ROI.

**Required**
- Provide a **centered square ROI** mechanism and report its size and location.

**Recommended**
- Default to **21×21** for GSQAP compatibility, and allow configuration to 20×20 for legacy FBIRN comparisons.

**Evaluation**
- Confirm ROI is placed at the **image center** unless the user overrides.
- Confirm ROI location is stable and reproducible (i.e., not dependent on GUI dragging unless saved).

### 3.3 Detrending

**Required**
- Use a **2nd-order polynomial detrend** for temporal fluctuation calculations:
  - For ROI time series (percent fluctuation, drift, spectrum).
  - For voxelwise time series when computing the temporal fluctuation noise (SD) image.

**Evaluation**
- Confirm the polynomial order is configurable but defaults to **2**.
- Confirm the drift is computed from the **fit curve**, not the raw time series.

---

## 4) Required computed images and metrics (stability phantom)

This section is organized as “what to compute” + “how to validate implementation.”

### 4.1 Signal (mean) image

**Definition**
- Signal image = voxelwise mean across the analyzed time points (198 volumes).

**Required output**
- Signal/mean image saved or displayable.

**Evaluation**
- Confirm mean is computed after discarding the first 2 volumes.

### 4.2 Temporal fluctuation noise (SD of detrended residuals) image

**Definition (GSQAP)**
1. For each voxel, take its time series across the 198 volumes.
2. Fit a 2nd-order polynomial in time and subtract the fit.
3. Compute the SD of the residuals.

**Required output**
- SD (fluctuation noise) image saved or displayable.

**Evaluation**
- Verify detrending is applied **before** SD.
- Verify SD is over residuals, not over raw data.

### 4.3 SFNR image and summary SFNR

**Definition**
- SFNR image = `SignalImage / FluctuationNoiseImage` voxelwise.
- Summary SFNR = mean SFNR in the centered ROI (typically 21×21).

**Required output**
- SFNR image + summary SFNR scalar.

**Evaluation**
- Confirm the summary SFNR is computed as an ROI mean of the SFNR map (not the ratio of ROI means unless explicitly documented).

### 4.4 Static spatial noise image (odd-even difference) and summary SNR

Two equivalent published forms appear:

- GSQAP paper: `DIFF = sum(odd volumes) − sum(even volumes)`
- FBIRN procedure: `NoiseAvg = mean(even volumes) − mean(odd volumes)`

These differ by a constant scaling factor; either is acceptable if the SNR formula is consistent.

**Definition (GSQAP SNR summary)**
- Compute DIFF (odd-even summed difference).
- In centered ROI:
  - `signal_summary = mean(SignalImage_ROI)`
  - `variance_summary = var(DIFF_ROI)`
  - `SNR = signal_summary / sqrt(variance_summary / N_used)`

**Required output**
- DIFF/noise image (featureless if stable) + summary SNR scalar.

**Evaluation**
- Confirm the tool’s reported SNR matches the above definition (or clearly documents a mathematically equivalent scaling if using mean-difference instead of sum-difference).
- Confirm `N_used` is the number of analyzed volumes (e.g., 198).

### 4.5 ROI mean time series, percent fluctuation, and drift

**Definition**
1. Form the ROI-mean time series: average intensity within centered ROI for each volume.
2. Fit a 2nd-order polynomial to this ROI-mean series.
3. Residuals = series − fit.

**Percent fluctuation**
- `100 * SD(residuals) / mean(series)`

**Drift**
- `100 * (max(fit) − min(fit)) / mean(series)`

**Required output**
- ROI-mean time series plot with polynomial fit.
- Percent fluctuation scalar.
- Drift scalar.

**Evaluation**
- Confirm drift is computed from the fit curve (max/min of polynomial values over time).
- Confirm percent fluctuation uses SD of detrended residuals and mean of the *raw* ROI series (as described).

### 4.6 FFT spectrum of detrended ROI residuals

**Definition**
- Apply FFT to the detrended ROI residual time series and display the magnitude spectrum (DC suppressed).

**Required (Level B)**
- Magnitude spectrum plot and frequency axis in Hz (requires TR).

**Recommended**
- Peak highlighting and basic peak metadata (frequency, magnitude).
- If statistical peak testing is implemented, document the method and assumptions (the paper references a P-value approach using local neighborhood estimates).

**Evaluation**
- Confirm detrending is done before FFT.
- Confirm the tool does not “helpfully” smooth the residuals unless explicitly requested and documented.

### 4.7 Weisskoff analysis and RDC / “correlation diameter”

**Goal**
Detect loss of voxel independence / spatial correlation caused by scanner instabilities or reconstruction smoothing.

**Weisskoff/GSQAP procedure**
- For ROI widths `N = 1..Nmax` (typically `Nmax = 21`):
  - Compute ROI-mean time series for the centered `N×N` ROI.
  - Detrend with a 2nd-order polynomial and compute SD of residuals.
  - Compute `CV(N) = SD(residuals) / mean(ROI series)` (often plotted as `100*CV(N)`).
- Plot log(CV) vs log(N) (or CV vs ROI width on log-log axes).
- Compare to theoretical uncorrelated scaling: `CV_theory(N) = CV(1) / N`.

**RDC definition used in GSQAP paper**
- `RDC = CV(1) / CV(Nmax)` (with `Nmax = 21`)
- Graphical “intercept” interpretation: project the plateau at `CV(Nmax)` to the theoretical line and read the corresponding ROI width.

**Required (Level B)**
- Weisskoff plot and a reported RDC measure (and how it was computed).

**Required warning**
- Report that RDC is **sensitive to spatial smoothness** (e.g., apodization/reconstruction filtering); RDC values are not directly comparable across sites unless smoothness is controlled/recorded.

**Evaluation**
- Confirm CV is based on detrended residual SD, not raw SD.
- Confirm the tool reports `Nmax` used and matches the publication default (21) unless configured otherwise.

### 4.8 Optional: header-based stability indicators (if available)

**Desired fields**
- RF transmit gain, RF receive gain, and resonant/center frequency.

**Required (only if advertised)**
- If the tool claims these, it must:
  - Extract from input headers (DICOM or vendor-specific) or accept as user-provided metadata.
  - Log values per run and show longitudinal trends.

**Evaluation**
- Confirm values are stored with time stamps and can be trended.

---

## 5) Expected ranges / qualitative benchmarks (for sanity checks)

These are **not pass/fail limits**, but useful implementation sanity checks (from the multicenter report):

- **3T**: SNR and SFNR are often on the order of **~200** (varies by vendor, coil, reconstruction smoothing).
- **Percent fluctuation**: stable scanners commonly average **<0.2%**; **~0.10%** is a typical lower level in the reported data.
- **Drift**: stable scanners commonly average **~1% or less**; around **~0.4%** is described as “about as good as one can get.”
- **SNR vs SFNR**: typically close; large discrepancies can indicate low-spatial-frequency structure/phase instability.

**Evaluation**
- Ensure the tool does not hard-code these values as thresholds without site-specific validation; treat them as reference points only.

---

## 6) Longitudinal QA features (how to evaluate support)

**Recommended (Level C)**
- Time-stamped results storage (CSV/JSON/DB) including:
  - scanner/site identifier, field strength, sequence, coil, TR/TE, ROI size, volumes used
  - SNR, SFNR, percent fluctuation, drift, RDC
  - links/paths to generated plots and maps
- Trend plotting with:
  - moving averages (paper illustrates centered moving average)
  - control limits (e.g., ±k SD) and flagging of outliers
- Operator annotations:
  - service events, software upgrades, coil swaps, room temperature/humidity notes

**Evaluation**
- Verify you can reproduce “step changes” corresponding to known hardware events.
- Verify flagging does not depend on manual inspection only (provide at least simple statistical alerts).

---

## 7) Geometry phantom workflow (monthly)

### 7.1 Acquisition and reformat

**Required**
- Ingest a 3D dataset and support reformatting to axial/sagittal/coronal midline planes (or accept already reformatted images).

### 7.2 Measurements

**Minimum requirement (matches procedure)**
- On each midline plane (axial/sagittal/coronal), record **≥8 distance measurements** between fiducial holes at specified orientations/angles, using the known **15 mm grid** as ground truth.

**Recommended (for automation)**
- Automated fiducial detection and measurement with:
  - mean error, max error, and directional error summaries
  - a distortion map or residual plot if possible

**Evaluation**
- Confirm the tool clearly reports whether measurements are manual or automated.
- Confirm output is in **mm** (or pixels + pixel spacing), and includes pixel spacing used for conversion.

---

## 8) Practical evaluation procedure (repeatable test plan)

Use this as a consistent audit process for a candidate QA tool.

1. **Protocol conformance**
   - Confirm it supports (or can be configured to match) the published scan parameters and volume handling.
2. **Detrending correctness**
   - Verify 2nd-order polynomial detrending is applied where required (voxelwise SD image and ROI residual-based metrics).
3. **Metric-by-metric verification**
   - For each metric (SNR, SFNR, fluctuation, drift, FFT, Weisskoff/RDC), confirm:
     - it exists
     - the definition matches the formulas above
     - it reports ROI size, volumes used, and any configurable deviations from defaults
4. **Artifact visibility**
   - Confirm outputs include the diagnostic plots/maps needed to identify:
     - periodic noise (FFT peaks)
     - nonstationarity/spikes (ROI time series)
     - spatial structure in DIFF/noise image
5. **Longitudinal capability**
   - Confirm results can be stored and trended with annotations.
6. **Geometry capability (if required)**
   - Confirm it can produce the monthly measurement table and retains historical geometry metrics.

---

## 9) Scoring template (copy/paste)

Use the following to score a tool (mark ✅/⚠️/❌ and add notes).

**Stability phantom (weekly)**
- Volumes: discards first 2 by default
- ROI: centered square ROI (default 21×21; configurable)
- Detrending: 2nd-order polynomial (ROI series + voxelwise for SD image)
- Maps: mean image, SD(residuals) image, DIFF/noise image, SFNR image
- Metrics: SNR summary, SFNR summary, percent fluctuation, drift
- FFT: detrended residual spectrum with Hz axis (Level B)
- Weisskoff: CV vs ROI size + RDC reported and defined (Level B)
- Metadata: logs TR/TE, coil, sequence; optional gain/frequency if available

**Longitudinal (Level C)**
- Time-stamped results export (CSV/JSON)
- Trend plots + control limits + flagging
- Annotation of service/upgrades and environment notes

**Geometry (monthly, Level D)**
- 3D reformat support
- ≥8 measurements per midline plane
- Reports in mm with pixel spacing provenance

