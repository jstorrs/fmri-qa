# AFNI Programs and Command Lines Used by This Repo

These notes enumerate the **AFNI executables** invoked by the `bxh-fmriqa` toolchain and capture the **exact command-line parameters** (including argument order) as used in the wrappers. The intent is to support future deep-dives into AFNI source code to understand algorithmic details corresponding to these invocations.

This file also documents AFNI usage (or lack thereof) in `cran-fmriqa`.

AFNI help text used for interpretation lives in `AFNI_doc/*` (e.g., `AFNI_doc/3dToutcount.txt`, `AFNI_doc/3dClipLevel.txt`, `AFNI_doc/afni.txt`).

---

## AFNI dataset sub-brick selection used by wrappers (`afniselector`)

Both `bxh-fmriqa/fmriqa_phantomqa.pl` and `bxh-fmriqa/fmriqa_hilo.pl` translate a user `--timeselect` argument into an AFNI sub-brick selector string appended to the dataset path:

- Input `--timeselect` is comma-separated, each item can be:
  - `START:END` → `START..END`
  - `START:` → `START..$`
  - `:END` → `0..END$` (note: as written, includes a trailing `$` in the string)
  - Otherwise the raw token is passed through unchanged
- The resulting AFNI selector is: `[...]` with comma-joined items.

Implementation reference:
- `bxh-fmriqa/fmriqa_phantomqa.pl:475`
- `bxh-fmriqa/fmriqa_hilo.pl:132`

This selector is appended directly to the dataset path, e.g. `somefile.hdr[2..$]` or `somefile.nii[0..10]`.

**Help highlights (AFNI_doc/afni.txt)**
- Sub-brick selector forms include `[i]`, `[i,j,k]`, `[i..j]`, and stepped ranges `[i..j(2)]`; `$` can be used to indicate the last sub-brick (`AFNI_doc/afni.txt:449`).
- Shell quoting is required when using special characters `$()[]<>` in dataset names (`AFNI_doc/afni.txt:489`).
- For space-separated datasets, a selector at the end can be “global” (applies to all inputs) vs “local” (applies to the adjacent dataset) (`AFNI_doc/afni.txt:506`).

**Implied algorithm (as used here)**
- The wrappers rely on AFNI’s dataset-name parsing to select a subset of timepoints/sub-bricks before running downstream computations (e.g., volume registration, copying to a shortened dataset).

**Important note for future AFNI source review**
- The wrappers’ conversion for a `:END` token is `0..END$` (see `bxh-fmriqa/fmriqa_phantomqa.pl:483` and `bxh-fmriqa/fmriqa_hilo.pl:140`). In the AFNI help syntax, `$` is a standalone “last sub-brick” symbol (e.g., `[0..$]` or `[0..$(3)]`), not a suffix on an integer literal. If selector parsing behavior matters, confirm how `0..10$` is interpreted by the AFNI build used with these scripts.

---

## AFNI programs used by `bxh-fmriqa`

### 1) `3dcalc`

Used primarily to **apply sub-brick selection** and copy the selected data to a new dataset (`-expr a*1`).

**Help highlights (AFNI_doc/3dcalc.txt)**
- “voxel-by-voxel arithmetic” on datasets assumed to be on the same grid/orientation.
- Supports sub-brick selection via `[]` after dataset names (examples include `[5..$(3)]`); notes that characters like `$()[]<>` are shell-special and need quoting.

**Implied algorithm (as used here)**
- Read dataset `a` (with an optional sub-brick selector appended).
- For each voxel (and each selected sub-brick), evaluate expression `a*1` (identity copy) and write output dataset; no resampling or registration occurs inside `3dcalc`.

**In `fmriqa_phantomqa.pl` (stability phantom wrapper)**
- Command (exact argv order):
  - `3dcalc -a <niftiprefix>.hdr<afniselector> -expr a*1 -prefix <shortfile>`
- Code reference: `bxh-fmriqa/fmriqa_phantomqa.pl:527`

Notes:
- Input is a `.hdr/.img` pair produced by `bxh2analyze --niftihdr`.
- Output is a `.nii` file named like `XXshortened.nii`.

**In `fmriqa_hilo.pl` (high/low flip-angle QA)**
- Command:
  - `3dcalc -a <tmpprefix>.nii<afniselector> -expr a*1 -prefix <tmpprefix>select.nii`
- Code reference: `bxh-fmriqa/fmriqa_hilo.pl:169`

Notes:
- Input is `.nii` produced by `bxh2analyze --nii`.

---

### 2) `3dvolreg`

Used for **volume registration** (motion correction style) and to output a 1D parameter file.

**Help highlights (AFNI_doc/3dvolreg.txt)**
- Rigid-body (6-parameter) registration: “Registers each 3D sub-brick … to the base brick” and is “limited to rigid body (6 parameter) transformations.”
- Default base is sub-brick 0 unless `-base` is given.
- Output motion parameters are “roll pitch yaw dS dL dP” in the 1D file.
- Interpolation options exist (`-linear`, `-cubic`, `-heptic`, `-Fourier`); if not specified, defaults apply (help notes that the “NEW Default” is heptic).
- `-clipit` is default (clamps output values to the input range) unless `-noclip`.

**Implied algorithm (as used here)**
- Choose base volume = first sub-brick (default).
- For each timepoint volume:
  - Estimate the rigid-body transform (3 rotations + 3 shifts) aligning it to the base.
  - Resample the volume onto the original grid using the program’s default interpolator, with clipping enabled by default.
  - Record 6 motion parameters to the `-1Dfile` output (plus whatever other defaults `3dvolreg` emits into the output dataset header).

**In `fmriqa_phantomqa.pl`**
- Command:
  - `3dvolreg -1Dfile <volregout> -prefix <volregfile> <shortfile>`
- Code reference: `bxh-fmriqa/fmriqa_phantomqa.pl:531`

Output handling:
- Parses `<volregout>` lines as: `roll pitch yaw dS dL dP` and reorders translations into RAS (`dX dY dZ`) before plotting (`bxh-fmriqa/fmriqa_phantomqa.pl:535`).

Notes for AFNI source review:
- No explicit `-base`, `-zpad`, `-Fourier`, `-twopass`, etc. are set here; behavior depends on `3dvolreg` defaults for this AFNI version.

---

### 3) `3dDetrend`

Used for **polynomial detrending** (explicitly `polort 2`) of the registered time series.

**Help highlights (AFNI_doc/3dDetrend.txt)**
- Removes components from voxel time series using “linear least squares”; each voxel is treated independently.
- Detrending is “equivalent to orthogonalizing” time series w.r.t. the basis vectors supplied by options.
- `-polort ppp` “Add Legendre polynomials of order up to and including ppp” to the regressors removed.

**Implied algorithm (as used here)**
- For each voxel time series in the input dataset:
  - Construct a regression design matrix containing Legendre polynomials of degrees 0..2 (because `-polort 2`).
  - Fit via least squares and subtract the fitted polynomial trend from the series.
  - Write the residual time series to the output dataset.

**In `fmriqa_phantomqa.pl`**
- Command:
  - `3dDetrend -polort 2 -prefix <detrendfile> <volregfile>`
- Code reference: `bxh-fmriqa/fmriqa_phantomqa.pl:549`

**In `fmriqa_hilo.pl`**
- Command:
  - `3dDetrend -polort 2 -prefix <tmpprefix>detrend.nii <tmpprefix>select.nii`
- Code reference: `bxh-fmriqa/fmriqa_hilo.pl:175`

---

### 4) `3dTstat`

Used to compute **mean** images (for mask generation) and **standard deviation** images (for variance estimates in hi/lo analysis).

**Help highlights (AFNI_doc/3dTstat.txt)**
- Computes “voxel-wise statistics for a 3D+time dataset.”
- `-mean`: mean of the voxel time series.
- `-stdev`: standard deviation, with a note: “input is detrended by first removing mean+slope.”
- `-stdevNOD` exists to compute standard deviation without that initial mean+slope detrending.

**Implied algorithm (as used here)**
- `-mean`: per-voxel arithmetic mean over time (sub-bricks).
- `-stdev`: per-voxel standard deviation over time, but computed on a linearly detrended series (mean+slope removed) unless `-stdevNOD` is used.
  - Practical implication for later AFNI source reading: in `fmriqa_hilo.pl`, the input to `3dTstat -stdev` is already output from `3dDetrend -polort 2`, so `3dTstat -stdev` applies an additional mean+slope removal step unless that AFNI behavior is changed by defaults.

**In `fmriqa_phantomqa.pl`**
- Mean:
  - `3dTstat -mean -prefix <meanfile> <volregfile>`
- Code reference: `bxh-fmriqa/fmriqa_phantomqa.pl:553`

**In `fmriqa_hilo.pl`**
- Mean:
  - `3dTstat -mean -prefix <tmpprefix>mean.nii <tmpprefix>select.nii`
- Stddev:
  - `3dTstat -stdev -prefix <tmpprefix>stddev.nii <tmpprefix>detrend.nii`
- Code reference: `bxh-fmriqa/fmriqa_hilo.pl:181`, `bxh-fmriqa/fmriqa_hilo.pl:199`

---

### 5) `3dAutomask`

Used to generate a **phantom/object mask** from a mean image, with different morphology options depending on downstream metric.

**Help highlights (AFNI_doc/3dAutomask.txt + AFNI_doc/3dClipLevel.txt)**
- Intended for “EPI 3D+time” or skull-stripped anatomical; output is a “brain-only mask dataset.”
- Method summary:
  - Uses `3dClipLevel` algorithm to find a clipping/threshold level (`AFNI_doc/3dAutomask.txt:11`).
  - Keeps only the largest connected component of supra-threshold voxels, after an erosion/dilation (“peel/unpeel”) step.
  - Outputs a binary mask (1 inside, 0 outside).
- `-dilate nd`: dilate outward nd times; `-erode ne`: erode inward ne times.
- `-q`: quiet (no progress messages).

**Implied algorithm (as used here)**
- Compute an intensity threshold using the `3dClipLevel` algorithm, which iterates:
  - initialize via “variance wizardry”
  - compute median of positive values ≥ current clip
  - update clip to `mfrac * median` (default `mfrac=0.50`)
  - repeat until convergence (`AFNI_doc/3dClipLevel.txt:15`).
- Because `3dAutomask` uses a “gradual clip level” by default (unless `-nograd`), the effective threshold may vary spatially (per-octant clip levels interpolated across the volume) (`AFNI_doc/3dClipLevel.txt:28` and `AFNI_doc/3dAutomask.txt:34`).
- Form an initial supra-threshold mask, apply erosion/dilation cleanup, and keep only the largest connected component.
- Optionally apply additional morphology:
  - For ghost metrics: generate a more permissive mask via `-dilate 4`.
  - For hi/lo QA: restrict to “core” via `-erode 5`.
- Write the resulting binary mask dataset for use as a spatial inclusion mask in other programs (3dFWHMx, 3dToutcount, 3dROIstats, and the repo’s `fmriqa_ghostiness`).

**In `fmriqa_phantomqa.pl`**
- Base mask (quiet):
  - `3dAutomask -q -prefix <maskfile> <meanfile>`
- Dilated mask for ghost metrics:
  - `3dAutomask -q -dilate 4 -prefix <maskfile> <meanfile>`
- Code reference: `bxh-fmriqa/fmriqa_phantomqa.pl:557`, `bxh-fmriqa/fmriqa_phantomqa.pl:584`

**In `fmriqa_hilo.pl`**
- Eroded core mask (quiet):
  - `3dAutomask -q -erode 5 -prefix <tmpprefix>mask.nii <tmpprefix>mean.nii`
- Code reference: `bxh-fmriqa/fmriqa_hilo.pl:187`

Notes for AFNI source review:
- The mask algorithm and the effects of `-dilate`/`-erode` are central to interpreting downstream ROI statistics and ghost metrics.

---

### 6) `3dFWHMx`

Used to estimate image smoothness (FWHM) using a mask. Two slightly different invocations exist in this repo.

**Help highlights (AFNI_doc/3dFWHMx.txt)**
- The program estimates “noise smoothness” via a spatial autocorrelation function (ACF) approach:
  - Computes empirical ACF and fits a mixed model `ACF(r) = a*exp(-r*r/(2*b*b)) + (1-a)*exp(-r/c)`.
  - Help emphasizes the ACF method (and deprecates “classic” Gaussian-only assumptions).
- `-mask mmm`: restrict computation to mask voxels.
- `-demed`: special handling when multiple sub-bricks are present (help indicates median-related processing; exact semantics depend on AFNI version).
- `-out ttt`: write per-sub-brick output to a file.

**Implied algorithm (as used here)**
- Restrict to voxels where mask is nonzero.
- For each sub-brick in the input dataset (note: wrappers often pass a 4D time series):
  - Estimate spatial smoothness of the dataset’s spatial noise structure (per help, via ACF estimation and model fitting in modern AFNI).
  - Write per-sub-brick results to the `-out` file; wrapper code assumes one line per sub-brick.
- Practical implication for future AFNI source review:
  - `fmriqa_phantomqa.pl` parses 3 numbers per line as `fwhmx fwhmy fwhmz` (historically consistent with older “classic” output). The bundled help (AFNI_25.3.03) documents ACF-based outputs and warns about “classic” output changes. When analyzing AFNI source, confirm the output format for the AFNI version that hint files were generated from vs the version expected by the legacy wrapper.

**In `fmriqa_phantomqa.pl` (per-volume FWHM from detrended/registered data)**
- Command:
  - `3dFWHMx -dset <detrendfile> -mask <maskfile> -out <tmpoutfile>`
- Code reference: `bxh-fmriqa/fmriqa_phantomqa.pl:561`

Notes:
- No `-demed` option is used in this wrapper.
- The wrapper expects `<tmpoutfile>` to contain whitespace-separated `fwhmx fwhmy fwhmz` per volume and parses each line (`bxh-fmriqa/fmriqa_phantomqa.pl:565`).

**In `fmriqa_generate.pl` (FWHM on masked data, with de-median)**
- Command (exact argv order):
  - `3dFWHMx -demed -mask <niftiprefix>_mask.hdr -dset <niftiprefix>.hdr -out <tmpoutfile>`
- Code reference: `bxh-fmriqa/fmriqa_generate.pl:1355`

Execution details:
- Runs under `open3` with stdin/stdout/stderr redirected to `/dev/null`; results are read only from `-out <tmpoutfile>` (`bxh-fmriqa/fmriqa_generate.pl:1354`).

---

### 7) `3dToutcount`

Used to compute **outlier voxel counts per volume** (and then converted to outlier percentage by dividing by mask voxel count).

**Help highlights (AFNI_doc/3dToutcount.txt)**
- Purpose: “Calculates number of ‘outliers’ … at each time point” for a 3D+time dataset.
- `-mask mset`: only count voxels within mask.
- Outlier definition (core algorithm):
  - Compute a “trend” and MAD for each voxel time series.
  - MAD is “median absolute deviation” of (time series minus trend).
  - A timepoint is an outlier if it exceeds `alpha * sqrt(PI/2) * MAD` from the trend.
  - `alpha = qginv(0.001/N)` where N is time series length (can be altered via `-qthr q`).
- Detrending option:
  - `-polort nn` detrends each voxel time series with polynomial order nn prior to outlier estimation.
  - Default `nn=0` means “just remove the median.”
  - Detrending is via **L1 regression** (“not L2”).

**Implied algorithm (as used here)**
- For each voxel in the mask:
  - Fit the default “trend” model (with default `-polort 0` unless otherwise specified): robust median removal (and potentially additional default behaviors) using L1-style robustness per help.
  - Compute MAD of residuals.
  - Mark timepoints whose residual magnitude exceeds the alpha-scaled threshold as outliers.
- For each volume (timepoint):
  - Count voxels marked as outliers (or output fraction if `-fraction` were used; not used here).
- In `fmriqa_generate.pl`, the script then converts counts to “percent of mask voxels” externally (AFNI itself can output fraction, but the script uses raw counts and divides by an independently computed mask voxel count).

**In `fmriqa_generate.pl`**
- Command:
  - `3dToutcount -mask <niftiprefix>_mask.hdr <niftiprefix>.hdr`
- Code reference: `bxh-fmriqa/fmriqa_generate.pl:1304`

Pipeline context:
- The dataset passed to `3dToutcount` is a **detrended** 4D dataset `detrendinputfile` that has been converted to an AFNI-readable Analyze/NIfTI header pair via:
  - `bxh2analyze --overwrite -b -s -v --niftihdr --nosform <detrendinputfile> <niftiprefix>`
  - `bxh2analyze --overwrite -b -s -v --niftihdr --nosform <maskfile> <niftiprefix>_mask`
  (References: `bxh-fmriqa/fmriqa_generate.pl:1282`, `bxh-fmriqa/fmriqa_generate.pl:1286`)
- The mask voxel count used to compute percent outliers is computed separately via `fmriqa_count --gt 0 <maskfile>` (not an AFNI tool) (`bxh-fmriqa/fmriqa_generate.pl:1291`).

Execution details:
- Invoked via `open3` with stdin and stderr redirected to `/dev/null` and stdout captured; lines beginning with `++` or `**` are ignored (`bxh-fmriqa/fmriqa_generate.pl:1306`).

---

### 8) `3dROIstats`

Used to compute ROI summary values (mean and stddev) inside a mask.

**Help highlights (AFNI_doc/3dROIstats.txt)**
- Computes statistics “over masked regions”; default statistic is **mean**.
- Output organization:
  - One line per sub-brick of each input dataset.
  - Columns include file and sub-brick identifiers plus per-ROI statistics (e.g., `Mean_1`, `Mean_2`, … for ROI labels 1,2,… in the mask).
- `-mask[n] mset`: use mask dataset; if n is present selects a mask sub-brick (0 default).
- Mask dataset should be BYTE or SHORT unless `-mask_f2short` is used.

**Implied algorithm (as used here)**
- Interpret the mask as labeled ROIs (nonzero integer values); for each ROI label:
  - Compute requested statistics (here, default mean) across the voxels in that ROI for each input sub-brick.
- In `fmriqa_hilo.pl`, the mask is produced by `3dAutomask` and thus is binary (0/1), which implies the ROI of interest is label 1; the script parses tabular output accordingly.

**In `fmriqa_hilo.pl`**
- Commands (shell/backticks form):
  - `3dROIstats -mask <tmpprefix>mask.nii <tmpprefix>mean.nii`
  - `3dROIstats -mask <tmpprefix>mask.nii <tmpprefix>stddev.nii`
- Code reference: `bxh-fmriqa/fmriqa_hilo.pl:205`, `bxh-fmriqa/fmriqa_hilo.pl:209`

Output parsing:
- The script reads line 2 (index `[1]`) and column 3 (index `[2]`) from tab-separated output to obtain a single scalar statistic.

---

## AFNI-related (but not AFNI-invoked) logic in `bxh-fmriqa`

### AFNI 3dDespike references
`bxh-fmriqa/fmriqa_spikiness.cpp` does **not** invoke AFNI, but explicitly references AFNI’s `3dDespike` behavior and fitting approach in its help text and comments (useful for future source review of AFNI’s despiking and robust fitting):

- Mentions “same as returned by Robert Cox’s AFNI 3dDespike” and “AFNI uses algorithm TOMS 552” (`bxh-fmriqa/fmriqa_spikiness.cpp:161`, `bxh-fmriqa/fmriqa_spikiness.cpp:406`).

**Help highlights (AFNI_doc/3dDespike.txt)**
- Outline:
  - L1-fit a “smooth-ish” curve per voxel time series (polynomial + sin/cos components; order controlled by `-corder`).
  - Compute residual MAD and convert to sigma estimate.
  - Compute standardized residual `s=(value-curve)/sigma` and shrink large values using a tanh-based mapping with thresholds `c1` and `c2` (default `c1=2.5`, `c2=4`) (`AFNI_doc/3dDespike.txt:12`).
- Default mask behavior uses a high-intensity mask akin to `3dAutomask -dilate 4 dataset` unless `-nomask` (`AFNI_doc/3dDespike.txt:64`).

**Implied algorithm (relevant to this repo)**
- When `bxh-fmriqa` says “AFNI despike-like,” the intended comparison is a per-voxel robust trend fit plus robust scale (MAD→sigma) and then nonlinear downweighting/replacement of extreme deviations.

---

## AFNI usage in `cran-fmriqa`

No AFNI executables (`3d*`) are invoked by `cran-fmriqa`.

- A repository-wide search for `AFNI`, `afni`, and `3d*` under `cran-fmriqa/` returns no matches.
- `cran-fmriqa`’s optional spike visualization (`spike_detect`) is implemented internally via FFT operations in R (not AFNI).

Primary implementation reference: `cran-fmriqa/R/run_fmriqa.R`.
