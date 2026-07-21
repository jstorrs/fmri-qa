# Implementation status vs. `notes/`

How the `fmriqc` pipeline (`src/fmriqc/`) lines up with the methods described in
the other `notes/` files. Read this alongside `fMRI_QA_Implementation_Guide.md`
(the Glover 2005 / Friedman & Glover 2006 GSQAP rubric the rest are measured
against).

**Summary:** the implementation is a faithful GSQAP **core (conformance
Levels A + B)** — every scalar metric matches the guide, and detrending matches
AFNI `3dDetrend` exactly. Much of the AFNI robustness/temporal-QA layer is now
also in place (`3dToutcount` outlier fraction, saturation, 3dvolreg-style motion,
`3dFWHMx` Classic-FWHM smoothness, bxh-volmeasures center-of-mass); the remaining
gaps are `3dDespike`, the ACF-model half of `3dFWHMx`, and Level C (longitudinal
trending).

**Design principle:** FBIRN is a specific, rigid protocol and its QA is adapted
to it. On FBIRN-protocol data the pipeline must reproduce FBIRN results — that
is the correctness bar, not a deviation to be flagged. Parameter defaults that
*scale* with the acquisition are calibrated so the canonical FBIRN protocol
lands on the FBIRN-correct value; the scaling only takes over for non-FBIRN
data, where reasonable innovation is fine.

Last reviewed: 2026-07-21.

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

Beyond the guide, the pipeline also computes an **ADC-saturation check**
(`detect_saturation` → `QAMetrics.saturation`, `clip`/`clipPre` columns): the
AFNI `4095_warn` idea (`AFNI_qa_ideas.md`) generalized to an unknown ceiling by
inferring the hardware `2**n - 1` rail from the series maximum and counting the
pile-up on it, over the full untrimmed series. The count is split at the trim
boundary — clips in the analyzed volumes (bias the metrics) vs. clips confined
to the dropped warm-up volumes (don't reach the stats, and are expected for
transition-acquiring sequences like ABCD).

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
3. **No motion _correction_.** GSQAP does not motion-correct the phantom series;
   resampling it (a `bxh` `3dvolreg` extension) is not part of the FBIRN
   protocol, so the metrics stay measured on the acquired data — FBIRN-correct,
   not a gap. We do, separately, _measure_ the per-volume in-plane deformation
   as a diagnostic (see "Done since first review"), without altering the
   analyzed series.

---

## Gaps — prescribed in the notes, not yet implemented

Ranked by value for phantom QA.

**High**

1. **Despiking (`3dDespike`).** No spike handling before the noise metrics — a
   single spike inflates fluctuation / SFNR / RDC. Full algorithm (basis
   `2·corder+3`, `fsig = sqrt(π/2)·median|e|`, tanh smash c1=2.5 / c2=4.0) in
   `AFNI_detrend_despike.md`. Could be an optional pre-step.
2. **Scalar spike scores.** Match `cran-fmriqa`: `tc_outlier = max|detrended ROI
   series| / MAD` and `spec_outlier = max(FFT mag) / MAD`. ~2 lines each; the
   residual series and its spectrum already exist in `report.py`.

**Medium**

3. **Ghost "top-10% voxels" statistic.** Our ghost uses the region *mean*; the
   Greve / `fmriqa_ghostiness.c` method also reports the top-10% ghost voxels
   (catches localized ghosts a mean dilutes).

**Lower / larger scope**

4. **Level C — longitudinal QA.** Guide's target is "B+C". We cover A+B (single
   scan + batch table); no logging DB, trend plots, or ±k·SD control-limit
   flagging.
5. **Background/air QA** (cran `max_bg_perc`) and **`@radial_correlate`**
   structured-artifact detection — future directions.
6. **FFT spectrum normalization.** `report.py._plot_spectrum` plots raw
   magnitude; `bxh` normalizes to percent-of-mean (`·100/m`) for cross-scan
   comparability. Cosmetic.

**Done since first review**

- **Temporal outlier fraction (`3dToutcount`)** (was High gap #1): the notes'
  top phantom check. `outlier_fraction` computes the per-frame outlier-voxel
  fraction over the phantom mask — per-voxel `sigma = sqrt(π/2)·MAD`, outlier if
  `|r| > Q⁻¹(qthr/N)·sigma`, `qthr = 0.001` — on the pipeline's Legendre-
  detrended fluctuations (afni_proc.py detrend-before-classify; our fit is L2
  vs. AFNI's L1). Surfaced as the `outl%` column, a PDF tile, and a per-frame
  trace plot. Validated: clean data sits at the `qthr` chance level.
- **Saturation / clipping check** (was a gap): `detect_saturation` infers the
  `2**n - 1` rail and counts the pile-up over the full untrimmed series, split
  into analyzed (`clip`) vs. dropped warm-up (`clipPre`) volumes; surfaced as
  two CLI columns and a PDF annotation.
- **In-plane phantom motion / deformation** (3dvolreg-style): `estimate_motion`
  registers each volume to the temporal-mean image under a rotation-free 2-D
  affine — translation + symmetric strain (anisotropic scale + shear), the only
  degrees of freedom a rigid phantom has under gradient heating — by
  forward-additive Lucas-Kanade over the phantom mask. Surfaced as the
  `motn`/`scl%`/`shr%` columns, a PDF tile, and a per-frame translation/strain
  trace; a slow monotonic strain ramp is the thermal-drift signature (visible on
  ABCD). Diagnostic only — the analyzed series is not resampled, so this stays
  FBIRN-correct.
- **Spatial smoothness / FWHM (`3dFWHMx`)** (was Medium gap #4): the RDC
  smoothness confound the guide warns about. `estimate_smoothness` recovers the
  per-axis Gaussian FWHM of the noise field from the variance of its forward
  first differences (AFNI's Classic `mri_estimate_FWHM_1dif`,
  `FWHM = sqrt(8 ln 2)·σ`), on the pipeline's detrended fluctuations with AFNI's
  `-unif` per-voxel median/MAD standardization, per frame over the phantom mask,
  aggregated across frames by geometric mean (`-geom`). Resolved to physical
  directions with the PE axis: surfaced as the `fwPE`/`fwRO` columns (phase-
  encode / readout FWHM in mm), a combined-FWHM PDF tile (AFNI `ccomb`), and
  directional **point-spread curves** — the empirical PSF (squared spatial
  autocorrelation of the noise field, the Gaussian-model point spread from AFNI's
  empirical ACF) overlaid on the Gaussian PSF from the Classic FWHM, per PE/RO,
  so anisotropic or non-Gaussian reconstruction smoothing is visible. The ACF
  mixed-model "effective FWHM" (the modern `3dFWHMx` default) is left as a
  follow-up; the Classic estimator is the exact, direct RDC complement the note
  calls for.
- **Thermal vs. instability split (hi/lo flip)** (was Lower gap #5): Greve's
  high/low flip-angle separation (`bxh-fmriqa-hilo.md`). Because thermal
  (additive) noise variance is signal-independent while instability
  (multiplicative) variance scales with signal², two runs differing only in flip
  angle separate the two: with `M = (mean_hi/mean_lo)²`,
  `thermal_var = (M·var_lo − var_hi)/(M − 1)` and `instability_var = var_hi −
  thermal_var` (Greve's `var_hi − var_lo` fallback when that goes negative),
  giving `ThermalFSNR`/`InstabilityFSNR`. `run_hilo` reduces each scan to a
  temporal-mean map and a temporal-SD-of-detrended-residual map over the whole
  volume, pools them over the **shared** eroded phantom core (intersection of the
  two `3dAutomask -erode 5`-style masks, so both means cover identical voxels),
  and calls the pure-algebra `separate_noise`. This is the first **pair**-level
  analysis, so it is exposed as a separate `fmri-qa-hilo HIGH LOW` command rather
  than a batch-table column. Validated on the FBIRN flip77/flip10 pair: the
  signal ratio (5.55) matches sin(77°)/sin(10°) = 5.6, and the near-equal
  hi/lo variances correctly report a stable scanner (instability ≈ 4% of the
  high-flip variance). The single-scan pipeline (and the FBIRN correctness bar)
  is untouched — the data was always present; only the pair architecture was new.
- **Per-volume center of mass (bxh `fmriqa_volmeasures`)**: the volmeasures
  center-of-mass trace, as a cheap first-moment motion/instability diagnostic
  alongside the registration-based `estimate_motion`. `estimate_center_of_mass`
  takes each frame's intensity centroid along both in-plane axes with a
  **circular mean** (map each coordinate to `2π·x/N`, average the
  intensity-weighted unit vectors, map the angle back to `[0, N)`), consistent
  with MRI periodicity. The circular mean buys three things that remove the need
  to segment the phantom (which would in fact *harm* it, by breaking the
  full-period symmetry): a phantom straddling a wrapped edge gives the true
  centroid, not a mid-FOV alias; a **uniform background contributes zero net
  vector** (`Σ_x exp(i2πx/N)=0`), where a linear COM would be dragged to image
  center and forced to mask; and the **Nyquist ghost**, at exactly half-FOV =
  180°, is anti-parallel to its source along PE (cancels) and co-located along RO
  (reinforces), so it cannot shift the centroid. The one thing that *does* break
  the background cancellation — **missing data**, e.g. a Siemens-nulled edge
  row/col — is *healed* rather than masked: the background pedestal (lowest valid
  magnitude) is subtracted so the floor sits at ~0 and the invalid voxels
  (`edge_valid_mask`) are then zeroed, so the gap matches the now-zero background
  instead of punching a hole in the periodic ring (pedestal subtraction also kills
  the background DC term outright). Deviations are reported relative to the
  temporal-mean centroid with the same circular wrapping, so a boundary crossing
  is a small shift, not a full-FOV jump. Surfaced as the `com` CLI column, a PDF
  tile, and a per-frame center-of-mass trace. Diagnostic only — the analyzed
  series is untouched. Validated: a synthetic zeroed row biases the raw centroid
  0.38 vox and the healing restores it exactly; an 8% N/2 ghost moves it 0.00
  vox; on real data (all three scans carry a genuine Siemens nulled edge, pedestal
  11–13) FBIRN sits at ≈ 0.007 vox (steady) and ABCD at ≈ 0.094 vox (its thermal
  drift).

---

## Suggested order of work

Highest leverage, fits the existing linear-chain architecture (operates on
`QAImages.center_slice` / `fluctuations`):

1. The two cheap `cran` spike scores (`tc_outlier`, `spec_outlier`).
2. Optional despike pre-step.

(Done: `3dToutcount`-style per-TR outlier fraction; saturation/clipping check.)
