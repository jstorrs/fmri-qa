# Implementation status vs. `notes/`

How the `fmriqc` pipeline (`src/fmriqc/`) lines up with the methods described in
the other `notes/` files. Read this alongside `fMRI_QA_Implementation_Guide.md`
(the Glover 2005 / Friedman & Glover 2006 GSQAP rubric the rest are measured
against).

**Summary:** the implementation is a faithful GSQAP **core (conformance
Levels A + B)** — every scalar metric matches the guide, and detrending matches
AFNI `3dDetrend` exactly. The gaps are the AFNI robustness/temporal-QA layer
(`3dToutcount`, `3dDespike`, `3dFWHMx`) and Level C (longitudinal trending),
none of which is implemented.

Last reviewed: 2026-07-20.

---

## Aligned — matches the notes

| Metric / step | Notes spec | Implementation | Notes |
| --- | --- | --- | --- |
| **SNR** | `mean(ROI) / sqrt(var(DIFF_ROI)/N)`, `DIFF = sum(odd)−sum(even)` | `snr()` — frame *sums*, `/n_frames` | exact GSQAP |
| **SFNR** | ROI mean of the voxelwise `signal/TFN` *map* (not ratio of ROI means) | `sfnr()` averages the map | correct subtlety |
| **% fluctuation** | `100·SD(resid)/mean(raw series)` | `percent_fluctuation()` | |
| **Drift** | GSQAP `drift_fit = 100·(max(fit)−min(fit))/mean` | `drift_percent()` — uses fitted `trend`, not raw min/max | picks the correct variant (bxh/cran also report a non-GSQAP raw one; we don't) |
| **Weisskoff CV** | widths 1..21, `CV = SD(resid)/mean(ROI series)` | `weisskoff()`, denominator = ROI mean signal | matches guide/cran (bxh's `mean(fit)` is the outlier) |
| **Detrend method** | `3dDetrend` = Legendre, `x∈[−1,1]`, LS projection | `poly_residuals()` = `legvander` on `linspace(-1,1,nt)` | exact |
| **ROI / slice** | 21×21 centered, middle slice | `FBIRN_ROI_SIZE=21`, `center="image"` | |

Two deliberate **refinements** over the literal spec (both documented in-code):

- **RDC uses a pooled single-voxel CV** (`cv1_pooled / cv[-1]`) rather than the
  raw `CV(1)/CV(Nmax)` — more robust to intensity non-uniformity than a
  single-voxel anchor.
- **ACR-equivalent ghost** (`acr_ghost_pct = |PE% − RO%|`) is a region-matched
  synthesis of the fBIRN and ACR/AAPM definitions; not literal in any note but
  principled (readout axis gives a background-relative baseline).

---

## Deliberate deviations — worth knowing

1. **Detrend order is adaptive, not fixed 2.** GSQAP-lineage notes (`guide`,
   `bxh`, `hilo`) prescribe a fixed `-polort 2`; cran uses 3. We compute
   `degree = round(nt·TR / 200 s)` (`poly_degree`). A canonical 200-vol / TR-2 s
   run lands on ~2 by coincidence but it drifts for other durations — closer to
   afni_proc.py's `1 + floor(sec/150)` philosophy than to GSQAP's fixed 2. Fine,
   but not a literal FIRST-BIRN match.
2. **Trim is time-based (5 s), spec is volume-based (first 2).** `guide`/`cran`
   drop exactly 2 volumes; `bxh` uses `2:`/`3:`. Different parameterization.
3. **No motion correction.** `bxh` runs `3dvolreg`; omitted here as intentional
   for a static phantom.

---

## Gaps — prescribed in the notes, not yet implemented

Ranked by value for phantom QA.

**High**

1. **Temporal outlier fraction (`3dToutcount`).** The #1 phantom check in
   `AFNI_procpy_best_practices.md` / `AFNI_qa_ideas.md`. Per-voxel median/L1
   detrend → `sigma = sqrt(π/2)·MAD` → outlier if `|r| > Q⁻¹(0.001/N)·sigma` →
   per-TR fraction. Catches transient instabilities the summary metrics average
   away. Full spec in `AFNI_outliers.md`.
2. **Despiking (`3dDespike`).** No spike handling before the noise metrics — a
   single spike inflates fluctuation / SFNR / RDC. Full algorithm (basis
   `2·corder+3`, `fsig = sqrt(π/2)·median|e|`, tanh smash c1=2.5 / c2=4.0) in
   `AFNI_detrend_despike.md`. Could be an optional pre-step.
3. **Scalar spike scores.** Match `cran-fmriqa`: `tc_outlier = max|detrended ROI
   series| / MAD` and `spec_outlier = max(FFT mag) / MAD`. ~2 lines each; the
   residual series and its spectrum already exist in `report.py`.

**Medium**

4. **Spatial smoothness / FWHM (`3dFWHMx`).** Absent. The guide warns RDC is
   confounded by smoothness; an FWHM (Classic first-difference
   `FWHM = 2.35482·σ`, or the ACF mixed model) would complement RDC. Spec in
   `3dFWHMx_algorithms.md`.
5. **Saturation / 4095 clipping check.** Recommended in both AFNI-ideas notes,
   trivial (`any(data == 4095)` per volume), absent.
6. **Ghost "top-10% voxels" statistic.** Our ghost uses the region *mean*; the
   Greve / `fmriqa_ghostiness.c` method also reports the top-10% ghost voxels
   (catches localized ghosts a mean dilutes).

**Lower / larger scope**

7. **Level C — longitudinal QA.** Guide's target is "B+C". We cover A+B (single
   scan + batch table); no logging DB, trend plots, or ±k·SD control-limit
   flagging.
8. **Background/air QA** (cran `max_bg_perc`), **`@radial_correlate`**
   structured-artifact detection, **hi/lo flip thermal-vs-instability split**
   (`bxh-fmriqa-hilo.md`, needs 2 scans) — genuinely out of the current
   single-scan scope; future directions.
9. **FFT spectrum normalization.** `report.py._plot_spectrum` plots raw
   magnitude; `bxh` normalizes to percent-of-mean (`·100/m`) for cross-scan
   comparability. Cosmetic.

---

## Suggested order of work

Highest leverage, fits the existing linear-chain architecture (operates on
`QAImages.center_slice` / `fluctuations`):

1. `3dToutcount`-style per-TR outlier fraction.
2. The two cheap `cran` spike scores (`tc_outlier`, `spec_outlier`).
3. Optional despike pre-step.
