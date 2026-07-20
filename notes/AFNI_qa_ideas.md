# AFNI QA ideas (static phantom focus)

This is a short list of QA checks inspired by what AFNI’s `afni_proc.py` pipeline wires in for QC (especially in `afni/src/python_scripts/afnipy/db_mod.py`), adapted to a **static phantom** setting (assume no subject motion).

## Saturation checks (clipping / ceiling effects)

- **4095 saturation warning**: run `3dTto1D -method 4095_warn` on each run to flag values consistent with hitting a fixed maximum (common for some acquisition/scaling paths).
  - Why: clipping distorts voxel distributions and can inflate outlier fractions or corrupt downstream QA metrics.
  - Output idea: aggregate warnings into a single text report (like `afni_proc.py` does with `out.4095_all.txt` and `out.4095_warn.txt`).

## Artifact checks (systematic scanner/data issues)

- **GTKYD (“get to know your data”) dataset-consistency checks**:
  - Run `gtkyd_check.py` and summarize outliers with `gen_ss_review_table.py ... -report_outliers` for basic header/attribute inconsistencies across inputs (e.g., varying datatype, orientation, space).
  - Why: mismatched metadata can create processing artifacts and misleading QA results even when the phantom is stable.

- **Local-correlation spatial artifact check (`@radial_correlate`)**:
  - Compute per-voxel correlation with a local spherical average and look for large clusters of very high correlations.
  - Why: helps detect structured scanner artifacts (AFNI notes this can be useful for issues like coils degrading) that won’t necessarily appear as simple temporal spikes.

## Outlier-fraction monitoring (temporal QC, not motion)

- **Per-TR outlier fraction**: use `3dToutcount -automask -fraction` and review `outcount.r*.1D` / `outcount_rall.1D`.
  - Align detrending used for outlier detection with your baseline drift model (e.g., `-polort` with `-legendre`) so “outliers” are defined relative to expected drift.
  - Treat elevated outlier fractions as a QA finding (potential hardware/acquisition issue), not necessarily something to censor away.

## Pre-steady-state handling

- **Flag or remove early TRs**:
  - Monitor TR 0 outlier fraction as a pre-steady-state indicator (afni_proc.py has an explicit warning threshold concept).
  - If you need stable QA summaries, explicitly drop the first few TRs before computing metrics.

## How to use this list

- Run the saturation + artifact checks first to rule out gross acquisition problems.
- Then interpret temporal outlier metrics (like `3dToutcount` fractions) in that context, since saturation/artifacts can masquerade as “spikes” or “bad TRs.”
