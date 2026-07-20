# AFNI outlier detection (high-level reimplementation spec)

This document specifies the outlier detection and reporting behavior of AFNI’s `3dToutcount` as implemented in:

- `AFNI_methods.md` (repo notes about how `3dToutcount` is invoked)
- `afni/src/3dToutcount.c`

The core regression solver used by `3dToutcount` for `-polort > 0` is AFNI’s L1 solver:

- `afni/src/cl1.c` (`cl1_solve`, least absolute deviations; used here without constraints)

The specification below is algorithmic (math + steps), not AFNI I/O-specific.

---

## Summary

For each voxel time series, `3dToutcount` computes a robust “trend” (median or L1 polynomial/Legendre fit), computes a robust scale estimate from the median absolute deviation (MAD) of residuals, then flags timepoints whose residual is unusually large relative to a Gaussian tail cutoff. It then aggregates flags across voxels to produce an outlier count (or fraction) per timepoint.

---

## Notation

- Let the dataset have `N` timepoints (AFNI variable `nvals`).
- For each voxel `v`, its time series is `y_v[t]` for `t = 0..N-1`.
- `Q(x)` is the upper-tail probability for a standard normal: `Q(x) = P(Z > x)` for `Z ~ N(0,1)`.
  - In AFNI code: `qg(x) = 0.5*erfc(x/sqrt(2))`.
  - `Q^{-1}(p)` is the inverse tail function (AFNI `qginv(p)`).
- `median(·)` is the sample median.

---

## Voxel selection (masking / clipping)

The algorithm is applied only to a subset of voxels; others are ignored entirely.

### 1) `-mask mset`

- A byte mask is constructed from mask dataset sub-brick 0 by including **all nonzero voxels** (AFNI uses `THD_makemask(mask_dset, 0, 1.0, -1.0)` which means “all nonzero values”).
- The mask dataset must have the same voxel count as the input dataset.
- If the mask has ≤ 5 selected voxels, the program errors.

### 2) `-autoclip` / `-automask`

- If no explicit `-mask` is provided and `-autoclip` (or synonym `-automask`) is set, an intensity-based automask is computed from the input dataset (`THD_automask(dset)`).
- `-autoclip/-automask` cannot be combined with `-mask`.

### 3) No mask option

- If neither `-mask` nor `-autoclip/-automask` is given, all voxels are processed.

Define `V_pass` as the set of voxels that pass the mask/clipping step, and `npass = |V_pass|`. For `-fraction`, `npass` is the denominator (even if some voxels later have MAD=0 or fail the L1 fit).

---

## Per-voxel outlier definition

The following steps are performed independently for each voxel `v ∈ V_pass`.

### Step A: compute a trend and residuals

`3dToutcount` supports two detrending modes controlled by `-polort` and `-legendre`.

#### Mode A0: `-polort 0` (default)

- Trend is the time series median:
  - `trend = median_t(y[t])`
- Residuals:
  - `r[t] = y[t] - trend`

#### Mode A1: `-polort p` with `p > 0`

The trend is an **L1 regression fit** (least absolute deviations) against `p+1` basis functions.

##### Time coordinate

Let:

- `tmid = (N-1)/2`
- `u(t) = (t - tmid) * (2/N)`  (approximately ranges over `[-1, 1]`)

##### Basis functions

Always include a constant basis:

- `b_0(t) = 1`

For degrees `j = 1..p`:

- Without `-legendre` (default for `p ≤ 3`):
  - `b_j(t) = u(t)^j`
- With `-legendre`:
  - `b_j(t) = P_j(u(t))` (Legendre polynomial of degree `j`)

##### Fit objective

Find coefficients `c_0..c_p` minimizing L1 error:

- `min_c Σ_t | y[t] - Σ_{j=0..p} c_j b_j(t) |`

AFNI computes this via `cl1_solve(N, p+1, z=y, A=b, y_out=c, cony=0)`.

##### Residuals

- `trend[t] = Σ_{j=0..p} c_j b_j(t)`
- `r[t] = y[t] - trend[t]`

##### Parameter constraints

- `p` must be ≥ 0.
- If `p > 3`, `-legendre` is required by the program.

If the L1 solver fails for a voxel, that voxel contributes **no outliers** (but still counts in `npass` for fraction output).

### Step B: robust scale via MAD

Compute a “MAD-like” scale from the residuals:

- `MAD = median_t(|r[t]|)`

If `MAD <= 0`, the voxel contributes no outliers.

Define the robust sigma estimate (Gaussian consistency factor):

- `sigma = sqrt(pi/2) * MAD`

### Step C: Gaussian tail threshold

Let `qthr` be the user parameter (default `qthr = 0.001`, option `-qthr qthr` with `0 < qthr < 0.999`).

Compute the tail cutoff:

- `alpha = Q^{-1}(qthr / N)`

An outlier is any timepoint satisfying:

- `|r[t]| > alpha * sigma`

In the implementation, this is equivalently written as:

- Precompute `alph = Q^{-1}(qthr/N) * sqrt(pi/2)`
- Test `|r[t]| > alph * MAD`

This choice sets the expected number of flagged timepoints per voxel (under iid Gaussian residuals) to approximately `qthr` since each timepoint has tail probability `qthr/N`.

---

## Aggregation across voxels (per-timepoint outputs)

Maintain an integer counter array `count[t]` initialized to 0.

For each voxel `v ∈ V_pass`, for each timepoint `t`:

- If `t` is an outlier for voxel `v`, increment `count[t]`.

### `-fraction`

If `-fraction` is enabled, output is:

- `frac[t] = count[t] / npass`

`npass` is the number of voxels passing the mask/clipping stage (not the number of voxels with `MAD > 0`).

---

## Output formatting (`stdout`)

### Without `-range`

For each `t = 0..N-1`, print one line:

- Counts: `printf("%6d\n", count[t])`
- Fractions: `printf("%0.5f\n", count[t] / npass)`

### With `-range`

Compute a “reference line” value from the outlier-count time series:

1. Let `cmed = median_t(count[t])`.
2. Let `cmad = median_t(|count[t] - cmed|)` (MAD across time).
3. Define `ctop = int(cmed + 3.5*cmad + 0.499)` (rounded to nearest integer).

Then for each `t`, print two columns:

- Counts: `printf("%6d %d\n", count[t], ctop)`
- Fractions: `printf("%0.5f %d\n", count[t] / npass, ctop)`

---

## Optional: `-save ppp` (per-voxel outlier “Q” dataset)

If `-save` is provided, `3dToutcount` can write a float-valued 3D+time dataset where each voxel/timepoint stores a quantity derived from the Gaussian tail probability.

For a voxel with `MAD > 0`, define:

- `z[t] = |r[t]| / sigma = |r[t]| / (sqrt(pi/2) * MAD)`

If timepoint `t` is an outlier for that voxel, then:

- `Qval[t] = -log10( Q(z[t]) )`

Otherwise:

- `Qval[t] = 0`

The implementation writes the output dataset only if **at least one outlier exists anywhere** (global outlier count `cc > 0`); otherwise no dataset is written.

For voxels with no outliers, the saved series remains all zeros.

---

## Reimplementation checklist (behavioral compatibility)

- Use `alpha = Q^{-1}(qthr/N)` with `Q` as the standard-normal upper-tail function, and threshold `|r| > alpha * sqrt(pi/2) * MAD`.
- For `-polort 0`, use the **median** trend (not the mean).
- For `-polort > 0`, use **L1** regression against basis functions built on `u(t) = (t-(N-1)/2)*(2/N)`, and support both power basis (`u^j`) and Legendre basis (`P_j(u)`).
- For `-fraction`, divide by the number of voxels passing the mask/clipping stage (`npass`).
- For `-range`, compute `ctop = int(median(count)+3.5*MAD(count)+0.499)` and print a second column with `ctop` for every timepoint.
