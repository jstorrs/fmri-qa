# AFNI detrending + despiking (high-level reimplementation spec)

This document specifies the detrending (`3dDetrend`) and despiking (`3dDespike`) behaviors as implemented in:

- `AFNI_methods.md` (repo notes about invoked AFNI programs)
- `afni/src/3dDetrend.c`
- `afni/src/3dDespike.c`

Implementation details referenced indirectly by those programs (for faithful reimplementation):

- `afni/src/mri_lsqfit.c` (ordinary least squares via Cholesky: `startup_lsqfit` / `delayed_lsqfit`)
- `afni/src/cl1.c` (L1 regression solver wrapper: `cl1_solve`, based on a TOMS/Netlib routine)

The specification below is algorithmic (math + steps), not AFNI I/O-specific.

---

## Notation

- Input dataset is a 3D+time series. For a given voxel `v`, its time series is `y[t]` for `t = 0..T-1`.
- Regression/design vectors are `r_j[t]` for `j = 0..(P-1)`, collected into a design matrix `R` of shape `T × P`.

---

## 1) `3dDetrend` (least-squares detrending / projection removal)

### Purpose

Remove user-specified components from each voxel time series via linear least squares. Equivalently: project each `y` onto the span of the regressors and subtract that projection (or optionally output the projection itself).

### Inputs

- Dataset with `T` timepoints.
- A list of regressor sources, any mixture of:
  - `-vector` 1D files (one or more columns)
  - `-expr` expressions evaluated over time
  - `-polort p` Legendre polynomials up to order `p`

### Regressor construction

#### 1. `-vector vvv`

- Read an ASCII 1D file into a matrix of shape `T × K` (timepoints × columns).
- Each column is one regressor `r_j[t]`.
- Sub-vector selectors (e.g., `file.1D[3,5]`) select which columns are included (indexing is 0-based in AFNI’s help text).
- The vector length must be at least `T` (or at least `NZ*T` when `-byslice` is used); if longer, only the first `T` (or `NZ*T`) values are used.

#### 2. `-expr eee` with optional `-del ddd`

- Each `-expr` adds exactly one regressor.
- `eee` may contain **at most one** variable symbol (single letter `a..z`); if more than one symbol is present, it is an error. If no symbol is present, it is treated as a constant expression.
- Let `Δ` be the step size:
  - Default: dataset TR, if present and > 0; otherwise `Δ = 1.0`.
  - `-del ddd` sets the step size for subsequent `-expr` options. If the expression-specific `-del` value is not positive, fall back to the dataset TR / default.
- For time index `t = 0..T-1`, evaluate `eee` with the independent variable value `x = t * Δ`.

#### 3. `-polort p`

- Adds `p+1` regressors, Legendre polynomials of order `k = 0..p`.
- Define the normalized time coordinate (requires `T > 1`):
  - `x_t = -1 + (2*t)/(T-1)` (so `x_t ∈ [-1, 1]`).
- The regressor is `r_k[t] = P_k(x_t)`, where `P_k` is the Legendre polynomial of degree `k`.

#### 4. `-byslice` (optional)

`-byslice` changes *how* `-vector` regressors are interpreted:

- Each `-vector` column must provide `NZ*T` values (interlaced by slice), where `NZ` is the number of slices.
- For a given slice index `z`, the slice-specific regressor is extracted as:
  - `r[t] = vec[z + t*NZ]`, for `t = 0..T-1`.
- Expressions and `-polort` regressors are **not** slice-specific; they are computed once using `t = 0..T-1` and used for all slices.

### Per-voxel fitting and output

For each voxel time series `y`:

1. Fit coefficients `β` by ordinary least squares:
   - `β = argmin_β ||y - Rβ||_2^2`
   - AFNI implementation solves the normal equations using a precomputed Cholesky factorization of `RᵀR`:
     - `RᵀR` is formed from dot products of regressors.
     - A Cholesky factorization is computed once and reused for all voxels (or once per slice when `-byslice` is used, since some regressors become slice-dependent).
   - If `RᵀR` is not positive definite (linearly dependent regressors), the program errors out.
2. Form the fitted trend: `ŷ[t] = (Rβ)[t]`.
3. Output one of:
   - Default: residuals `e[t] = y[t] - ŷ[t]`
   - With `-replace`: fitted trend `ŷ[t]`
4. With `-normalize` (only if dataset is float): L2-normalize the output vector so that `Σ_t out[t]^2 = 1` (if the norm is extremely small, leave unchanged).

---

## 2) `3dDespike` (robust trend fit + nonlinear spike shrinking)

### Purpose

For each voxel time series, fit a “smooth-ish” baseline curve robustly, estimate residual scale robustly, then replace outliers (“spikes”) with values closer to the baseline.

### Supported input types / basic constraints

- Input dataset must be stored as **constant-datum** `short` or `float`.
- Output dataset is always **float**.
- Let `T` be total timepoints, `ignore` be the number of leading timepoints to copy through unchanged:
  - `nuse = T - ignore` must be at least 15; otherwise it errors.

### Masking (default behavior)

Unless `-nomask` is set:

1. Compute a high-intensity mask using `THD_automask(dset)`.
2. Dilate the mask `dilate` times (default `dilate=4`), using AFNI’s 3D mask dilation routine (`THD_mask_dilate` with a 3D neighborhood).
3. Only voxels inside the final mask are processed; voxels outside the mask are not written by the per-voxel loop (they remain at the output dataset’s default fill value, typically 0).

With `-nomask`, all voxels are processed.

### Curve model (basis functions)

Despiking is performed only on the last `nuse` timepoints, indexed `t = 0..nuse-1` (corresponding to original time indices `t+ignore`).

The baseline curve is:

`f(t) = Σ_{j=0..P-1} a_j r_j(t)`

where `P = 2*corder + 3` and the basis functions are:

- `r_0(t) = 1`
- Define:
  - `tmid = (nuse-1)/2`
  - `u(t) = (t - tmid) * (2/nuse)`  (approximately in `[-1, 1]`)
- Polynomial part (fixed order 2 in this code):
  - `r_1(t) = u(t)`
  - `r_2(t) = u(t)^2`
- Trigonometric part (`k = 1..corder`):
  - `ω_k = 2πk/nuse`
  - One sine and one cosine regressor per `k`: `sin(ω_k t)` and `cos(ω_k t)`

### Choosing `corder`

- If `-corder L` is not provided, AFNI chooses:
  - `corder = round(nuse / 30)`
  - In the **OLD** fitting method only, `corder` is capped at 50.
- Validity constraint (always enforced):
  - If `4*corder + 2 > nuse`, it errors (“too big for NT”).

### Fitting method (OLD vs NEW)

The program computes coefficients `a_j` by one of two methods:

#### A) OLD method: L1 regression (least absolute deviations)

- Solve for `a` that minimizes `Σ_t |y[t] - f(t)|`.
- Implemented via `cl1_solve(nuse, P, y, r, a, cony=0)`:
  - No coefficient sign constraints (`cony=0`).
  - Solver tolerance is `1e-4`, with an internal iteration limit proportional to `nuse`.
- If the solver fails (negative return), the voxel is skipped.

#### B) NEW method: quick pre-despike + ordinary least squares

Enabled by:

- `-NEW` (explicit)
- environment variable `AFNI_3dDespike_NEW`
- automatically if `nuse > 500` (this override is applied whenever the OLD method would otherwise be selected)

and optionally:

- `-NEW25` which selects a different pre-despike window (and sets `cut2=3.2` unless overridden by `-cut`)

Steps:

1. Pre-despike the data vector in-place using a sliding-window median/MAD rule:
   - Two variants:
     - `NEW`: window length 9 (`DES_despike9`)
     - `NEW25`: window length 25 (`DES_despike25`), only used when `nuse > 99` (otherwise it falls back to `NEW`)
   - For each timepoint `t`:
     - Compute local median `med_t` over the window centered at `t`, with the window clamped to remain fully in-range.
     - Compute local MAD `mad_t = median(|x - med_t|)` over the same window.
   - Compute a global threshold:
     - `MAD_global = median_t(mad_t)`
     - `thr = 6.789 * MAD_global`
   - Replace any point where `|x[t] - med_t| > thr` with `med_t`.
2. Fit coefficients `a` by least squares on the (pre-despiked) data:
   - AFNI precomputes a pseudo-inverse matrix for the design `R` once (via SVD) and then computes `a` by a matrix-vector multiply per voxel.

Important detail for matching AFNI’s behavior:

- In NEW mode, the curve fit is computed from the *pre-despiked* copy of the time series, but the residuals (next section) and the edits are computed relative to the *original* unmodified time series values.

### Residual scale estimate

After computing the fit `f(t)` (using either fitting method), compute residuals from the unedited time series:

- `e(t) = y(t) - f(t)`
- `abs_e(t) = |e(t)|`

Compute the scale parameter:

- `fsig = sqrt(pi/2) * median_t(abs_e(t))`

If `fsig <= 0`, no despiking edits are applied to the voxel.

### “Spikiness” value `s(t)` (standardized residual)

- `s(t) = e(t) / fsig`

Optionally, `-ssave` stores `|s(t)|` per voxel/timepoint in a byte-valued dataset:

- Stored byte value is approximately `10 * |s(t)|` (clipped to `[0,255]`).
- A per-brick scale factor of `0.1` is attached so that the scaled output approximately recovers `|s(t)|` (up to saturation at ~25.5).

### Editing rules (two modes)

Let `c1` and `c2` be thresholds:

- Defaults: `c1 = 2.5`, `c2 = 4.0`
- With `-cut c1 c2`, these can be set explicitly (must satisfy `c1 ≥ 1.0` and `c2 ≥ c1 + 0.5`).
- With `-NEW25`, AFNI uses defaults `c1=2.5` and `c2=3.2` unless overridden by `-cut`.

#### Mode 1 (default): “smash” edit (tanh shrinkage)

For each `t`:

- If `s(t) > c1`:
  - `s'(t) = c1 + (c2-c1) * tanh((s(t)-c1)/(c2-c1))`
  - Replace the value with: `y_new(t) = f(t) + s'(t) * fsig`
- Else if `s(t) < -c1`:
  - `s'(t) = -c1 + (c2-c1) * tanh((s(t)+c1)/(c2-c1))`
  - Replace: `y_new(t) = f(t) + s'(t) * fsig`
- Else: keep `y_new(t) = y(t)`

AFNI’s implementation clamps the input to `tanh()` to `[-7, 7]` to avoid overflow in the exponential form.

This maps `|s| ∈ [c1, ∞)` into `|s'| ∈ [c1, c2)` smoothly, limiting the magnitude of large deviations without snapping them exactly to the curve.

#### Mode 2 (`-localedit`): nearest-neighbor replacement

For each `t` where `|s(t)| >= c2` (note: `c1` is unused in this mode):

1. Find the nearest later time index `u > t` such that `|s(u)| < c2`.
2. Find the nearest earlier time index `d < t` such that `|s(d)| < c2`.
3. Replace `y(t)` with:
   - If both exist: `0.5 * (y(u) + y(d))`
   - If only one exists: that neighbor’s value
   - If neither exists: `f(t)`

### Output assembly

- The first `ignore` timepoints are copied directly from input to output (as float).
- Timepoints `ignore..T-1` are written from the edited series.
- Only voxels selected for processing (mask or `-nomask`) are written by the algorithm’s main loop.

---

## Reimplementation checklist (behavioral compatibility)

- Match the exact basis functions and scaling in `afni/src/3dDespike.c` (`u(t)` centered at `(nuse-1)/2` and scaled by `2/nuse`; sines/cosines use `2πk/nuse`).
- Treat `-ignore` as a “copy through” prefix for despike (no fitting, no edits on those points).
- Preserve the NEW-mode detail where the curve fit uses a pre-despiked copy but residuals/editing are computed relative to the original series.
- Use the same robust scale estimator for despike: `fsig = sqrt(pi/2) * median(|residual|)`.
- For `afni/src/3dDetrend.c -polort p`, use Legendre polynomials evaluated on `x_t = -1 + 2*t/(T-1)`.
