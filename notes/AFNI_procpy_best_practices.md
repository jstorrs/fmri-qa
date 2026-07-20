# afni_proc.py best-practices (outliers + detrending) for static phantom QA

This note summarizes what AFNI’s `afni_proc.py` currently encodes as “best practice” for outlier detection and detrending, interpreted for **static phantom** data (assume no motion and therefore no motion correction).

## Sources reviewed

`afni_proc.py` is largely an orchestration front-end; the concrete command construction lives in AFNI’s Python modules:

- Outlier counting/censoring logic: `afni/src/python_scripts/afnipy/db_mod.py` (`make_outlier_commands`)
- Baseline detrending defaults: `afni/src/python_scripts/afnipy/db_mod.py` (`set_proc_polort`) and `afni/src/python_scripts/afnipy/afni_util.py` (`get_default_polort`)

For outlier definition details, `afni_proc.py` relies on `3dToutcount` (see `afni/src/3dToutcount.c`).

---

## 1) Outlier detection best-practices (as implemented by afni_proc.py)

### Core method: `3dToutcount` outlier *fraction* per TR

Default behavior (when `-outlier_count yes`, which is the default) is to compute **outlier fraction per volume** (TR) using:

- `3dToutcount -automask -fraction ... <run_dset> > outcount.r$run.1D`
- `cat outcount.r*.1D > outcount_rall.1D`

Key encoded choices:

- `-automask` is used (not an external mask), meaning the fraction denominator is “automasked” voxels.
- `-fraction` is preferred over raw counts (fractions are comparable across masks/runs).

### Detrend before outlier classification (polort aligned to baseline model)

`afni_proc.py` explicitly detrends inside `3dToutcount` via `-polort`, and its **default** is to match the regression baseline polynomial:

- `-outlier_polort` default: same as `-regress_polort`
- `-regress_polort` default is derived from run duration:
  - `polort_default = 1 + floor(run_length_seconds / 150)`
  - run length uses `TR * NT` (matching AFNI’s 3dDeconvolve convention)

Rationale (implicit in pipeline design): outliers should be defined relative to the same slow baseline drift you intend to treat as nuisance.

### Prefer Legendre polynomials for `3dToutcount`

`afni_proc.py` passes `-legendre` to `3dToutcount` by default:

- `-outlier_legendre yes` (default)

This is treated as best practice because:

- Legendre polynomials are better behaved numerically than raw powers of (scaled) time.
- It permits `-polort > 3` in `3dToutcount` (which AFNI otherwise disallows).

### Optional: censoring based on outlier fraction

If the user requests it, the script turns outlier fractions into a censor vector:

- Option: `-regress_censor_outliers LIMIT` (LIMIT in `[0,1]`)
- Rule: censor TRs where `outlier_fraction(TR) > LIMIT`
- Implementation: creates per-run censor vectors from `outcount.r$run.1D` and combines them into a single censor file (and also combines with any other censor files by multiplication).

To avoid penalizing scanner warm-up TRs:

- `-regress_skip_first_outliers NSKIP` can ignore the first NSKIP TRs of each run in this censoring logic.

For a **phantom QA** pipeline, censoring is often less important than *flagging*; the best-practice in `afni_proc.py` is to make censoring optional and threshold-based.

### Built-in “pre-steady state” warning from TR 0 outliers

`afni_proc.py` includes a specific warning for elevated outliers at TR 0:

- Parameter: `-tcat_preSS_warn_limit LIMIT` (stored default is `0.4`)
- If `outcount.r$run.1D[0] > LIMIT`, it writes a warning suggesting possible pre-steady-state TRs.

For a phantom, this is a direct best-practice signal: **either remove** initial TRs (`-tcat_remove_first_trs`) or **monitor**/flag them via this check.

### Additional QC checks triggered early in the script

While not “outlier fraction” per se, these checks are encoded as QA-oriented best practices and are phantom-relevant:

- **4095 saturation check** (common for certain acquisition scaling / bit-depth limits):
  - `3dTto1D -method 4095_warn -input <run_dset> |& tee -a out.4095_all.txt`
- “GTKYD” (Get To Know Your Data) attribute checks (e.g., varying datatype/orient/space across inputs).

---

## 2) Detrending best-practices (baseline modeling)

### Default baseline polynomial degree

The default detrending degree used by AFNI regression (and therefore reused for outliers by default) is:

- `polort_default = 1 + floor(run_length_seconds / 150)`

This encodes the heuristic: longer runs warrant higher-order baseline models.

### Polynomial detrending vs bandpass-based drift modeling

`afni_proc.py` docs explicitly note combining polynomial baseline modeling with sinusoid-based drift regressors via bandpassing:

- Example shown: `-regress_polort 2 -regress_bandpass 0.01 1`

Interpretation for phantom QA:

- If you want to treat slow scanner drift as nuisance, a modest `polort` may be sufficient.
- If drift has structured frequency content (thermal cycles, etc.), incorporating a bandpass/high-pass model can be more appropriate, but you should ensure that “signal of interest” for QA (e.g., known periodic fluctuations) is not filtered out.

### Using `3dTproject` (projection) as a detrending implementation

For cases with no stimulus regressors (common for phantom time series), `afni_proc.py` supports using `3dTproject` instead of running the full regression in `3dDeconvolve`:

- Option: `-regress_use_tproject yes`
- Script builds `3dTproject -polort 0 -ort <Xmat> ...` to project out the regression design, supporting censoring.

For a motionless phantom QA context, this is often the cleanest expression of “detrend with the chosen baseline model” without extra GLM machinery.

---

## 3) Practical phantom-oriented recommendations (derived from afni_proc.py)

1. **Always compute outlier fractions** with `3dToutcount -automask -fraction`, and review `outcount_rall.1D` for spikes/episodes (this is default in `afni_proc.py`).
2. **Detrend outlier estimation** using `-polort` aligned to your chosen baseline model; keep `-outlier_legendre yes` unless you have a strong reason not to.
3. **Handle early TRs explicitly**:
   - Prefer removing them (`-tcat_remove_first_trs`) if you want stable QA metrics, or
   - At least flag them (`-tcat_preSS_warn_limit`, and if censoring, `-regress_skip_first_outliers`).
4. **Use censoring sparingly** for phantom QA:
   - If you need robust downstream estimates, use `-regress_censor_outliers` with a clearly stated LIMIT.
   - Otherwise, treat elevated outlier fractions as a QA finding rather than something to “fix” by censoring.
5. **Include saturation and artifact checks** (4095 check, and consider `@radial_correlate`) because phantom QA is often about scanner/coils rather than subject motion.
