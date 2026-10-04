# Implementation status vs. `notes/`

How the `fmriqc` pipeline (`packages/fmri-qa-core/src/fmriqc/`) lines up with
the methods described in the other `notes/` files. Read this alongside
`fMRI_QA_Implementation_Guide.md` (the Glover 2005 / Friedman & Glover 2006
GSQAP rubric the rest are measured against).

**Summary:** the implementation is a faithful GSQAP **core (conformance
Levels A + B)** — every scalar metric matches the guide, and detrending matches
AFNI `3dDetrend` exactly. Much of the AFNI robustness/temporal-QA layer is now
also in place (`3dToutcount` outlier fraction, saturation, 3dvolreg-style motion,
`3dFWHMx` Classic-FWHM smoothness, bxh-volmeasures center-of-mass, cran
MAD-normalized spike scores, Greve/bxh top-10% localized ghost); the remaining
gaps are the ACF-model half of `3dFWHMx` and Level C (longitudinal trending).
`3dDespike` and a robust
fluctuation SD were considered and deliberately declined for a QA tool (see
"Deliberate non-goals").

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
  principled (readout axis gives a background-relative baseline). The whole
  family — PE, RO, top-10%, ACR — comes off one build of the region-matched
  masks (`estimate_ghost` → `GhostResult`), which the artifact publishes, so the
  regions a report draws are the regions the numbers were sampled on.

---

## Calibrated defaults — FBIRN-correct, and scale for non-FBIRN

These are *not* deviations: on the canonical FBIRN protocol (200 volumes,
TR 2.0 s) they reproduce the exact FBIRN choices, and only diverge for
off-protocol acquisitions, by design.

1. **Detrend order scales with run length.** GSQAP prescribes a fixed
   `-polort 2`. We compute `degree = round(nt·TR / 200 s)` (`Detrender.for_series`). The
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

**Lower / larger scope**

1. **Level C — longitudinal QA.** Guide's target is "B+C". We cover A+B (single
   scan + batch table); no logging DB, trend plots, or ±k·SD control-limit
   flagging.
2. **Background/air QA** (cran `max_bg_perc`) and **`@radial_correlate`**
   structured-artifact detection — future directions.
3. **FFT spectrum normalization.** The report's `plot_spectrum`
   (`fmriqc_report.panels.timeseries`) plots raw magnitude; `bxh` normalizes to
   percent-of-mean (`·100/m`) for cross-scan comparability. Cosmetic.
4. **Acceptance thresholds.** The report is descriptive: metric tiles show
   measured values only, with no pass/warn/fail colouring, and the report states
   that no acceptance thresholds are applied. Pass/warn/fail limits, evaluated
   against `Measurements`, would colour the tiles and give each metric an
   acceptance window with its provenance. The FBIRN correctness bar sets the
   default limits.

---

## Deliberate non-goals (considered, decided against)

- **`3dDespike` data-editing pre-step — not implemented, by design.** 3dDespike
  edits the series (robust baseline + tanh spike-shrink) so spikes don't corrupt a
  *downstream GLM* — a preprocessing goal. For QA the goal is the opposite: detect
  and characterize a spike, not conceal it. Editing the data would make SFNR look
  good while hiding the fault. Spikes are instead surfaced in dedicated channels
  (`tcOut`/`spcOut` spike scores, `3dToutcount` outlier fraction) and left in the
  data, so the FBIRN metrics still degrade honestly on a bad run.
- **Robust fluctuation SD — not adopted; classic (FBIRN) SD kept.** SFNR /
  %fluctuation / RDC stay on the ordinary SD of the detrended residual, so they
  reproduce FBIRN reference numbers (the correctness bar). A spike inflating them
  is treated as real instability and read against the spike channels (high %fluct +
  high `tcOut` = spike-driven; high %fluct + low `tcOut` = broadly noisy). Measured:
  the trend choice does *not* affect this — the spike lands in the residual and the
  SD swallows it regardless; only a robust SD estimator would change it, and that
  would break the FBIRN bar.
- **Robust detrend (Huber-IRLS / L1 on the Legendre basis) — deferred.** Verified a
  no-op on clean FBIRN data (≡ OLS to 4 sig figs), and for our low-order *global*
  Legendre fit the OLS trend-drag from even a 20σ spike is ~0.03σ, so there is
  little to gain. Its payoff grows only with detrend order / run length
  (off-protocol). Revisit if a long-run or high-leverage case shows trend-drag
  mattering; it would slot in as an opt-in `detrend="poly-robust"` method.

**Done since first review**

- **Temporal outlier fraction (`3dToutcount`)** (was High gap #1): the notes'
  top phantom check. `outlier_fraction` computes the per-frame outlier-voxel
  fraction over the phantom mask — per-voxel `sigma = sqrt(π/2)·MAD`, outlier if
  `|r| > Q⁻¹(qthr/N)·sigma`, `qthr = 0.001` — on the pipeline's Legendre-
  detrended fluctuations (afni_proc.py detrend-before-classify; our fit is L2
  vs. AFNI's L1). Surfaced as the `outl%` column, a metric tile, and a per-frame
  trace plot. Validated: clean data sits at the `qthr` chance level.
- **Saturation / clipping check** (was a gap): `detect_saturation` infers the
  `2**n - 1` rail and counts the pile-up over the full untrimmed series, split
  into analyzed (`clip`) vs. dropped warm-up (`clipPre`) volumes; surfaced as
  two CLI columns and a report note.
- **In-plane phantom motion / deformation** (3dvolreg-style): `estimate_motion`
  registers each volume to the temporal-mean image under a rotation-free 2-D
  affine — translation + symmetric strain (anisotropic scale + shear), the only
  degrees of freedom a rigid phantom has under gradient heating — by
  forward-additive Lucas-Kanade over the phantom mask. Surfaced as the
  `motn`/`scl%`/`shr%` columns, a metric tile, and a per-frame translation/strain
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
  encode / readout FWHM in mm), a combined-FWHM metric tile (AFNI `ccomb`), and
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
  is a small shift, not a full-FOV jump. Surfaced as the `com` CLI column, a metric
  tile, and a per-frame center-of-mass trace. Diagnostic only — the analyzed
  series is untouched. Validated: a synthetic zeroed row biases the raw centroid
  0.38 vox and the healing restores it exactly; an 8% N/2 ghost moves it 0.00
  vox; on real data (all three scans carry a genuine Siemens nulled edge, pedestal
  11–13) FBIRN sits at ≈ 0.007 vox (steady) and ABCD at ≈ 0.094 vox (its thermal
  drift).
- **cran MAD-normalized spike scores** (was High gap #2): `cran-fmriqa`'s
  `tc_outlier` / `spec_outlier`. `spike_scores` takes the detrended ROI-mean
  residual — the ROI mean of the pipeline's per-voxel fluctuations, i.e. the same
  series the report already plots (detrending commutes with the spatial mean) —
  and reports two unitless peak-over-spread ratios (`_spike_ratio`): `tc_outlier
  = max|residual| / MAD` in the time domain (a transient volume the SD-based
  summaries average away) and `spec_outlier = max(FFT magnitude) / MAD` on the
  DC-dropped residual spectrum (a dominant periodic artifact). The denominator is
  R's `mad()` (`1.4826·median|x − median x|`, matched to `scipy` `scale='normal'`
  to 1e-6), so a clean phantom sits at a few and a spike stands well above.
  Surfaced as the `tcOut`/`spcOut` CLI columns, two metric tiles, and inline in the
  existing residual/spectrum plot titles (same series). Diagnostic only.
  Validated: matches a manual recompute exactly; an injected one-frame spike
  drives `tcOut` 2.5 → 19.3 and an injected sinusoid drives `spec` 5.2 → 37.5;
  empty/constant series return NaN. On clean real data FBIRN sits at
  tcOut 2.5 / spec 5.2, ABCD at 3.3 / 5.9.
- **Top-10% localized ghost (Greve / bxh `fmriqa_ghostiness`)** (was Medium
  gap #1): a companion to the PE mean ghost that averages only the brightest 10%
  of ghost-region voxels (`GhostResult.pe_top_ratio`, `GHOST_TOP_FRACTION =
  0.10`), on the **same** region-matched masks as the mean ghost — so it shares the
  scale, is always ≥ the mean ghost, and a concentrated bright ghost the region
  mean dilutes still shows. Surfaced as the `ghT%` CLI column and a `ghostT` metric
  tile. Validated: matches an explicit top-k sort exactly and never drops below
  the mean ghost; a localized ghost injected into a few ghost voxels moves `ghT%`
  ~10× more than `ghost%` (FBIRN 4.1→6.6, ABCD 5.1→10.1 at rest); an empty ghost
  region returns NaN.

---

## Suggested order of work

Highest leverage, fits the existing linear-chain architecture (operates on
`QAImages.center_slice` / `fluctuations`):

1. Level C — longitudinal trending (logging DB + control-limit flags), the last
   substantive item toward the guide's "B+C" target; the single-scan metric set
   is now broad.

(Done: `3dToutcount`-style per-TR outlier fraction; saturation/clipping check;
cran `tc_outlier`/`spec_outlier` spike scores; Greve/bxh top-10% localized ghost.
Declined for QA: `3dDespike` data-editing and a robust fluctuation SD — see
"Deliberate non-goals".)
