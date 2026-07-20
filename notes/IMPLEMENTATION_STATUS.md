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

**Design principle:** FBIRN is a specific, rigid protocol and its QA is adapted
to it. On FBIRN-protocol data the pipeline must reproduce FBIRN results — that
is the correctness bar, not a deviation to be flagged. Parameter defaults that
*scale* with the acquisition are calibrated so the canonical FBIRN protocol
lands on the FBIRN-correct value; the scaling only takes over for non-FBIRN
data, where reasonable innovation is fine.

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

## Calibrated defaults — FBIRN-correct, and scale for non-FBIRN

These are *not* deviations: on the canonical FBIRN protocol (200 volumes,
TR 2.0 s) they reproduce the exact FBIRN choices, and only diverge for
off-protocol acquisitions, by design.

1. **Detrend order scales with run length.** GSQAP prescribes a fixed
   `-polort 2`. We compute `degree = round(nt·TR / 200 s)` (`poly_degree`). The
   200 s cutoff is calibrated so the FBIRN run (198 used × TR 2.0 s = 396 s)
   lands on **degree 2** — the FBIRN value. It only scales up for much longer
   acquisitions; the fixed-2 assumption of the standard is honored where the
   standard applies. (Verified: TR 2.0 s → 2, TR 2.5 s → 2, TR 3.0 s → 3.)
2. **Trim is time-based (5 s) but resolves to the FBIRN 2 volumes.**
   `n = round(trim_sec / TR)`, so the 5.0 s default drops exactly **2 TRs**
   across the plausible FBIRN TR range (2.0–3.0 s), matching `guide`/`cran`'s
   "discard first 2" while staying meaningful in wall-clock seconds for other
   TRs.
3. **No motion correction.** GSQAP does not motion-correct the phantom series;
   `3dvolreg` is a `bxh` extension, not part of the FBIRN protocol. Omitting it
   is FBIRN-correct, not a gap.

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
