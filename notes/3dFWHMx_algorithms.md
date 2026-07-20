# 3dFWHMx algorithms (AFNI)

This note describes the **two smoothness estimation paths** implemented by AFNI’s `3dFWHMx`, based on the code in:
- `afni/src/3dFWHMx.c` (CLI + orchestration)
- `afni/src/mri_fwhm.c` (Classic FWHM estimators, ACF estimation + ACF model fitting)
- `afni/src/thd_detrend.c` (the `-detrend` preprocessing used by `3dFWHMx`)

Terminology used below:
- A 3D+time dataset is a sequence of **sub-bricks** (timepoints) `iv=0..N-1`.
- A **mask** is a byte array over voxels; a voxel is used if `mask[ii]!=0`.
- Voxel sizes are `dx,dy,dz` (mm).

---

## Shared preprocessing (applies to both Classic and ACF paths)

### Input + mask preparation (`afni/src/3dFWHMx.c`)

1) Load dataset, possibly removing “all-zero” bricks (`THD_remove_allzero`).
2) Build the working mask:
   - `-mask mset`: `THD_makemask(mset, subbrick=0, thr=0.5, …)` then require `>=16` mask voxels.
   - `-automask`: `THD_automask(inset)` then require `>=16` mask voxels.
   - otherwise: start with all voxels in-mask.
3) If the dataset has more than 3 sub-bricks, voxels that are **constant over time** are removed from the mask (`THD_voxel_is_constant`).

### Optional normalization / detrending controls

`3dFWHMx` passes two flags into the smoothness routines: `demed` and `unif`.

#### `-demed` (median removal across time; robust centering)
Implemented in `THD_estimate_FWHM_all` / `THD_estimate_ACF` (`afni/src/mri_fwhm.c`):
- Compute a per-voxel median across time (`THD_median_brick`), subtract it from each sub-brick before estimating smoothness.

#### `-unif` (median removal + per-voxel scaling by MAD across time; robust standardization)
Implemented in `THD_estimate_FWHM_all` / `THD_estimate_ACF` (`afni/src/mri_fwhm.c`):
- Compute per-voxel median + MAD across time (`THD_medmad_bricks`).
- Subtract median.
- Multiply by `1/MAD` (only where `MAD>0`).

#### `-detrend [q]` (time-series model removal + variance normalization; “3dDespike-like”)
Orchestrated in `afni/src/3dFWHMx.c` using routines in `afni/src/thd_detrend.c`:

1) Choose `corder=q`:
   - `-detrend` with no number sets `q = NT/30` (integer).
   - If `q==0`, it is treated as `-demed` in the CLI logic.
   - If `2*q+3 >= NT`, it errors.
2) Build `nref = 2*q+3` reference functions (`THD_build_trigref`):
   - `ref[0](t) = 1`
   - `ref[1](t) = (t - tmid) * (2/NT)`
   - `ref[2](t) = (t - tmid)^2 * (2/NT)^2`
   - For each `k=1..q`: `sin(2πkt/NT)` and `cos(2πkt/NT)`
3) For each voxel time series, fit the linear model by least squares (`meth=2`), subtract the fitted time series, and **scale residuals by 1/stddev(residuals)** (`scl=1`) via `THD_detrend_dataset`.
4) After detrending, `3dFWHMx.c` forces `unif=1` and `demed=0`, so the later smoothness routines will also apply the `-unif` median/MAD scaling step on the detrended dataset.

---

## “Old / Classic” method: Gaussian smoothness from local differences

`3dFWHMx` always computes per-subbrick “Classic” Gaussian FWHM values using `THD_estimate_FWHM_all(dset, mask, demed, unif)` (`afni/src/mri_fwhm.c`). What has changed over time is primarily **what gets printed to stdout** (see “Outputs” below).

### Per-subbrick loop + optional `-unif`/`-demed` (`THD_estimate_FWHM_all`)

For each sub-brick `iv`:
1) Convert the brick to float and apply brick scaling factors.
2) If `demed`: subtract the per-voxel median across time.
3) If `unif`: multiply by per-voxel `1/MAD` across time.
4) Estimate Gaussian FWHM using a selected estimator function pointer `fester(im, mask)`.

The default estimator is `mri_estimate_FWHM_1dif` (see below), but “semi-secret” CLI options in `3dFWHMx.c` can change `fester` to alternate estimators.

### Default Classic estimator: 1st-neighbor differences (`mri_estimate_FWHM_1dif`)

Code: `afni/src/mri_fwhm.c`, function `mri_estimate_FWHM_1dif(MRI_IMAGE *im, byte *mask)`.

For each axis (x/y/z), the algorithm:
1) Computes the variance of voxel values inside the mask:
   - `var = sample_variance( f[i] )` over all in-mask voxels.
2) Computes the sample variance of **forward first differences** along that axis:
   - x differences: `dfdx = f[x+1,y,z] - f[x,y,z]` for valid pairs.
   - y differences: `dfdy = f[x,y+1,z] - f[x,y,z]`
   - z differences: `dfdz = f[x,y,z+1] - f[x,y,z]`
   - By default, a neighbor pair is used only if *both* voxels are in the mask. The `-compat` option toggles a legacy behavior via `FHWM_1dif_dontcheckplus(1)` that allows using neighbor voxels even if the neighbor is not in-mask.
3) Uses the model described in the comments:
   - Neighbor correlation is treated as `arg = exp(-Δ^2/(4σ^2))`, where `Δ` is voxel spacing for that axis.
   - For a smoothed white-noise field, the first-difference variance relates to `var` via `arg = 1 - 0.5*(var_diff/var)`.
4) Solves for σ and converts to FWHM:
   - `FWHM = sqrt(8 ln 2) * σ = 2.35482 * σ`
   - Implemented as:
     - `arg = 1 - 0.5*(var_diff/var)`
     - `FWHM = 2.35482 * sqrt( -1 / (4 * ln(arg)) ) * Δ`
5) If insufficient data or the intermediate quantities are invalid (e.g., `arg<=0` or `arg>=1`), the axis FWHM is left as a negative “error flag”.

### Alternate Classic estimators (still “Classic” Gaussian FWHM)

These are switched by `3dFWHMx.c` options and are implemented in `afni/src/mri_fwhm.c`:

- `-2dif`: `mri_estimate_FWHM_12dif`
  - Computes variance of 1-step differences (`vx1`) and 2-step differences (`vx2` where the 2-step term is `(x+1) - (x-1)`).
  - Uses the ratio `r=vx2/vx1` to solve for the implied neighbor correlation `x=exp(-Δ^2/(4σ^2))` by solving `(1-x^4)/(1-x) = r`, then converts `x→σ→FWHM`.

- `-2difMAD`: `mri_estimate_FWHM_12dif_MAD`
  - Same basic idea as `-2dif`, but the “variances” are estimated robustly using the MAD of the difference arrays (with a fallback to mean absolute deviation ratios if the MAD-based solve fails).

- `-1difMOM [stdev_fac]`: `mri_FWHM_1dif_mom12`
  - Computes standardized first differences `df = (neighbor_diff) / sqrt(2*var)`.
  - Uses the 1st and 2nd moments of `|df|` to estimate a distribution over an intermediate smoothness parameter (`tau` in the comments), then heuristically biases the estimate toward larger FWHM by subtracting a multiple of the estimated SD of `tau` (controlled by `mom12_stdev_fac`, default 1.0).

### Sub-brick aggregation (Classic)

In `afni/src/3dFWHMx.c`, the per-subbrick per-axis results are aggregated into:
- `cx,cy,cz`: either geometric mean (`-geom`, default) or arithmetic mean (`-arith`) across sub-bricks.
- `ccomb`: a combined single number computed as the geometric mean (over positive axes) or arithmetic mean (over positive axes), depending on `-geom/-arith`.

---

## “New” method: empirical ACF + mixed-model fit + “effective FWHM”

In the `afni/src/3dFWHMx.c` in this repo, ACF calculation is effectively “always on” (`do_acf` defaults to `-1` and there is no CLI option that sets it to 0), and the Classic values are primarily retained for reference, for `-out`, and for setting default ACF radius.

The ACF method is computed via:
1) Estimating an empirical spatial autocorrelation function over many offsets (`THD_estimate_ACF` → `mri_estimate_ACF`), and
2) Fitting a 3-parameter mixed model and extracting an “effective” FWHM (`ACF_cluster_to_modelE`).

### ACF radius selection (`afni/src/3dFWHMx.c`)

If the user does not provide a radius explicitly after `-acf/-ACF`, then:
- `acf_rad = 2.999 * ccomb` (where `ccomb` is the Classic combined FWHM computed earlier).
- A minimum radius is enforced: `acf_rad >= 3.999 * cbrt(dx*dy*dz)`.

### Offset set (cluster) used for ACF estimation (`get_ACF_cluster`)

Code: `afni/src/mri_fwhm.c`.

1) Create a “ball” of integer offsets within the given radius (`MCW_spheremask(dx,dy,dz,radius)`).
2) If too many offsets are produced, subsample:
   - Keep the central `NCLU_BASE=111` points.
   - Then keep every `dp`-th point from the remaining list such that the final size is about `NCLU_GOAL=666`.
3) For 2D datasets (`nz==1`), offsets with nonzero `k` are skipped.
4) Offsets are sorted by radius (`MCW_radsort_cluster`).

### Empirical ACF estimation for one 3D brick (`mri_estimate_ACF`)

Code: `afni/src/mri_fwhm.c`, function `mri_estimate_ACF(MRI_IMAGE *im, byte *mask, MCW_cluster *clout)`.

For a single 3D image:
1) Compute the global mean `fbar` and sample variance `fvar` across in-mask voxels.
2) For each in-mask voxel `p`, and for each offset `o` in the cluster:
   - Let `q = p + o` (only if in-bounds and also in-mask).
   - Accumulate the centered cross-product `(f[q]-fbar)*(f[p]-fbar)` for that offset.
3) For each offset, normalize the accumulated cross-products by `fvar` and by `(n_pairs-1)`:
   - `ACF[o] = sum_crossprod[o] / ( fvar * (n_pairs[o]-1) )`
   - Offset 0 is forced to `ACF[0]=1`.

This produces an empirical ACF value for each discrete offset/radius.

### ACF across a 3D+time dataset (`THD_estimate_ACF`)

Code: `afni/src/mri_fwhm.c`, function `THD_estimate_ACF(THD_3dim_dataset *dset, …)`.

For each sub-brick:
1) Convert to float and apply brick scaling factors.
2) Optionally apply the same `-demed/-unif` processing as in the Classic pipeline.
3) Compute an ACF curve (`mri_estimate_ACF`) using the shared offset cluster.

The final empirical ACF is the **average** of the per-subbrick ACF curves over sub-bricks that successfully produced an estimate.

### Mixed-model fit and “effective FWHM” (`ACF_cluster_to_modelE`)

Code: `afni/src/mri_fwhm.c`.

1) Convert the offset list to `(r, ACF(r))` samples, where `r` is the Euclidean distance in mm computed from `dx,dy,dz` and the integer offset.
2) Sort by `r` and **collapse** near-duplicate radii (within 1%) by averaging ACF values.
3) Fit the model
   - `ACF_model(r) = a*exp(-r^2/(2*b^2)) + (1-a)*exp(-r/c)`
   - Constraints: `0.006 ≤ a ≤ 0.994`, `b>0`, `c>0` (implemented via bounded optimization).
   - Objective function is a plain sum of squared residuals over sampled radii.
   - Optimizer is `powell_newuoa_constrained` (Powell/NEWUOA-style method).
4) After fitting, define an “effective FWHM” `d` from the fitted model:
   - Find `r_half` where `ACF_model(r_half) = 0.5` by interpolation.
   - Set `d = 2 * r_half`.
5) A “Gaussian_NEWmodel” curve is generated as `exp(-r^2/(2*sigma^2))`, where `sigma = FWHM_TO_SIGMA(d)`.

The returned parameter tuple is `(a,b,c,d)` as a `float_quad`.

Failure modes visible in the code:
- If the sampled ACF values never drop below 0.5 (within the computed/sampleable radii), `ACF_cluster_to_modelE` aborts with an error and returns all `-1` values.
- If the bounded Powell/NEWUOA optimization fails, it aborts similarly.

---

## Outputs (what you can observe from 3dFWHMx)

### Stdout

With the ACF path (default `do_acf=-1` in `afni/src/3dFWHMx.c`), stdout always prints 2 numeric lines:
1) “old-style” Classic FWHM line:
   - If `-ShowMeClassicFWHM` is **not** used, this line is forced to `0 0 0 0`.
   - If `-ShowMeClassicFWHM` is used, it prints `cx cy cz ccomb`.
2) ACF line: `a b c d` where `d` is the “effective FWHM”.

Using `-ACF` (uppercase) also prints comment lines beginning with `#`; using `-acf` (lowercase) suppresses those comment lines (controlled by the sign of `do_acf`).

### `-out ttt` (Classic per-subbrick results)

`-out` writes the full per-subbrick Classic FWHM array returned by `THD_estimate_FWHM_all` via `mri_write_ascii(outfile, outim)`.

Important implication for legacy wrappers: even if stdout suppresses Classic values, the Classic per-volume values are still available via `-out`.

### ACF 1D file + plot

If `-acf [anam]` is used (or defaults), `ACF_cluster_to_modelE` creates a 1D structure that `3dFWHMx.c` can write via `mri_write_1D(acf_fname, acf_im)`:
- Default columns (4): `radius`, `empirical_ACF`, `mixed_model`, `gaussian_NEWmodel`
- If `-addcol5` is used, a 5th column is appended: `gaussian_OLDmodel` using the Classic `ccomb` value (`exp(-r^2/(2*sigma_old^2))`).

`3dFWHMx.c` also runs `1dplot` to emit a PNG graph alongside the 1D file.
