# Project review

Reviewed on 2026-09-08 at commit `c756d03` (`Fix QA loading, artifact validation, and numerical failure handling`).

The project has a strong foundation: a clear calculation/reporting boundary, explicit artifact schemas and migrations, atomic output writes, extensive tests, and CI that checks both source code and built distributions. The highest-value improvements are protecting source files and making the artifact's settings and quality flags consistently reflect what happened during analysis.

This review covers both packages, their tests, project documentation, packaging, and CI. Findings below are based on source inspection and, where stated, small executable reproductions using synthetic data. No real scanner datasets or external reference implementations were evaluated. Application code was not changed.

## Prioritized findings

### 1. High: output paths can overwrite input data

**Locations:** [core CLI](packages/fmri-qa-core/src/fmriqc/cli.py), `_artifact_path` at line 61 and `main`; [report CLI](packages/fmri-qa-report/src/fmriqc_report/cli.py), `main` at line 69; [artifact writer](packages/fmri-qa-core/src/fmriqc/analysis/serialize.py), line 90; [PDF writer](packages/fmri-qa-report/src/fmriqc_report/formats/reportlab.py), line 717.

Both CLIs accept an output path equal to an input path. Inputs are loaded before the writers atomically replace the destination, so the operation succeeds while destroying its source. The existing batch collision check only compares artifact destinations with each other.

**Confirmed:** On disposable synthetic files, these argument combinations both returned status `0`:

```text
fmri-qa scan.nii.gz --roi-size 9 --artifact scan.nii.gz
fmri-qa-report scan.qa.npz --pdf scan.qa.npz
```

The first replaced the NIfTI with a ZIP/NPZ archive (`PK` signature); the second replaced the archive with a PDF (`%PDF` signature). These examples must only be exercised on disposable copies.

**Suggestion:** Before analysis or rendering, compare all output destinations with all input paths and associated sidecars. Account for relative paths and filesystem aliases. Reject source/output collisions with a clear error. Preserve the existing atomic-write behavior for legitimate destinations; separately document the policy for replacing existing outputs.

**Regression coverage:** Both commands should fail before writing when an output aliases an input, and all source bytes should remain unchanged. Include a batch case where a destination aliases another input.

### 2. High: noise-only data can receive a successful localization flag

**Locations:** [phantom geometry](packages/fmri-qa-core/src/fmriqc/prep/geometry.py), `PhantomGeometry.plausible` at line 47 and `detect_phantom` at line 75; [image preparation](packages/fmri-qa-core/src/fmriqc/prep/imaging.py), `phantom_area` and `extract_center_slice`.

Slice selection checks both mask area and signal/background contrast. The final phantom verdict only checks whether the mask covers between 0% and 95% of the image. Consequently, slice selection can correctly warn that no phantom exists, then the subsequent segmentation can still publish `phantom_mask_ok=True`.

**Confirmed:** With `abs(default_rng(0).normal(size=(32, 32, 1, 40)))`, TR 2 seconds, `trim_sec=0`, `center="phantom"`, and `roi_size=3`, the mask covers approximately 53.9% of the image and the ROI fits inside it. The slice-selection contrast check returns no phantom, but the final mask is considered plausible. This permits an `ok` localization result for an analysis of background noise.

**Impact:** The warning is transient, whereas the saved verdict is what later reports and automated consumers use to assess the measurements.

**Suggestion:** Use a shared localization assessment for slice selection and final segmentation, including the existing contrast criterion. Persist the failure reason when no recognizable phantom is found. Continue producing a diagnostic report if desired, but make its localization verdict reflect that failure.

**Regression coverage:** A noise-only scan must retain a failed localization verdict through analyze → save → load → report. Keep successful cases for a normal phantom and a phantom with an exactly zero background.

### 3. Medium: `build_artifact()` can publish settings that were never used

**Location:** [artifact construction](packages/fmri-qa-core/src/fmriqc/analysis/build.py), lines 79–100.

The public builder accepts a completed `QAResult` and optional settings. If settings are omitted, it fills in defaults for trimming, center selection, and the PE override, even if the result was computed differently. Explicitly supplied settings are also not checked against the result. The result does not retain enough information to reconstruct every requested setting.

**Confirmed:**

```python
result = run_qa(scan, trim_sec=0, center="phantom", roi_size=9, pe_axis=0)
artifact = build_artifact(result)
```

The artifact records `trim_sec=5.0`, `center="image"`, and `pe_axis_override=None`, while `provenance.n_trimmed` correctly records `0`. The ordinary `analyze(scan, settings)` route passes settings through and avoids this particular mismatch.

**Suggestion:** Carry the effective configuration on `QAResult` and have the builder consume it. Alternatively, require the original settings and validate all properties that can be checked. Distinguish requested from resolved ROI size; the builder currently replaces the requested size with the clamped size. Also retain the selected slice index so a saved artifact identifies the actual plane analyzed.

**Regression coverage:** Build artifacts from nondefault `run_qa()` results and verify trimming, localization mode, PE override/label, and selected slice provenance. Reject conflicting supplied settings.

### 4. Medium: the producer can save artifacts that its own reader rejects

**Locations:** [metadata parsing](packages/fmri-qa-core/src/fmriqc/load/metadata.py), lines 137–152; [serialization](packages/fmri-qa-core/src/fmriqc/analysis/serialize.py), `save_artifact` at line 63 and `load_artifact` at line 98.

Most optional sidecar fields are copied directly into typed dataclasses without runtime checks. Saving also skips the scalar and structural validation applied during loading. A malformed field irrelevant to numeric analysis can therefore survive calculation and writing, only to fail when a report opens the result.

**Confirmed:** A synthetic NIfTI with a sidecar containing `"EchoTime": "0.03"` successfully loads, analyzes, and saves. Reloading the resulting archive raises `InvalidArtifactError: ... provenance.te has an invalid type or value`.

**Suggestion:** Parse optional metadata into explicit numeric/text types at the loading boundary. Define whether malformed optional values cause an input error or a warning plus an unknown value. Validate artifacts before replacing an existing destination, using the same contract as the reader, so successful writes are readable by the current implementation. Include appropriate CLI handling for validation failures.

**Regression coverage:** Parameterize malformed metadata types across optional fields; verify early, field-specific diagnostics and a readable round trip for every successfully produced artifact. A failed save must preserve an existing valid archive.

### 5. Medium: the report describes a different SFNR calculation

**Locations:** [report metric catalog](packages/fmri-qa-report/src/fmriqc_report/content.py), lines 45–49; [SFNR implementation](packages/fmri-qa-core/src/fmriqc/metrics/fbirn.py), lines 129–145.

The report defines SFNR as temporal stability of the ROI mean and describes dividing ROI mean signal by the SD of a detrended time series. The implementation instead calculates each voxel's temporal mean divided by that voxel's residual SD, then averages those ratios across the ROI. These operations are not interchangeable: averaging time series first changes the noise through spatial cancellation.

**Suggestion:** Describe the implemented calculation explicitly: “ROI average of voxelwise temporal mean signal / detrended temporal SD.” Keep the distinction from percent fluctuation, which actually uses the ROI-mean residual. Review other catalog descriptions against their implementation in the same way.

**Regression coverage:** Use unequal voxel noise levels to demonstrate the difference between averaging voxelwise ratios and computing a ratio from the ROI-mean series. Check that the physics report's definition and method text describe the implemented order of operations.

## Further improvements

These are development suggestions, not additional confirmed numerical defects.

| Area | Suggested improvement | Reason and starting point |
| --- | --- | --- |
| Numerical validation | Add quantitative reference fixtures with recorded tool versions, parameters, and tolerances. | Existing formula, synthetic, and property tests are useful. However, `test_estimate_smoothness_recovers_the_smoothed_direction` checks directional ordering rather than absolute estimator accuracy. Start with known smoothing widths and a small reference corpus for methods described as AFNI/fBIRN analogues. Document intentional differences. |
| Report validation | Add a few rendered-page comparisons and extracted-text assertions. | `test_a_reloaded_artifact_renders_identically` currently checks page counts and the PDF signature, which cannot establish visual equivalence. Cover missing metadata, long scan titles, unresolved metrics, both report tiers, and raster/overlay alignment. Keep tolerances stable across supported rendering environments. |
| Partial batch results | Record requested, successful, and failed inputs in machine-readable output and PDF packet metadata. | Both CLIs continue after individual failures and return nonzero, which is useful. The JSON `scans` collection and PDF nevertheless contain only successful inputs; a recipient who receives only the output cannot identify omissions. Add an error inventory and mark incomplete packets visibly. |
| Reproducibility | Extend provenance with source identity and the calculation environment. | Paths can be reused, and `core_version()` alone does not distinguish multiple development builds of `0.1.0`. Consider source/sidecar hashes, a build revision, relevant dependency versions, and the selected slice index. Introduce schema changes with the existing migration mechanism. |
| Resource usage | Benchmark peak memory and runtime on representative acquisitions before optimizing. | `QAScan.from_nifti()` materializes the full series through `get_fdata()`, while the ordinary pipeline ultimately analyzes one slice. Full-volume validation and saturation detection still require access to all samples. If memory is material, explore chunked scans of those operations and selective loading for slice analysis while preserving scaling and clipping semantics. |
| Artifact consistency | Extend validation to relationships among redundant fields. | Current validation does valuable type, shape, coordinate, and unit checking. Additional checks could cover clipping flags versus counts, directional FWHM applicability versus PE resolution, and localization diagnostics versus stored regions. Preserve explicit unknown values from older schemas rather than retroactively applying new scientific thresholds. |
| CI portability | Add a small platform/interpreter matrix when expanding supported environments. | CI currently runs Linux with the pinned Python interpreter, while both packages declare Python `>=3.13` and OS independence. Keep the main locked gate, and add targeted installation, numerical, and PDF smoke tests for the additional environments the project intends to support. |

## Verification

Checks used the existing `.venv` with Python 3.13.9. The locked environment was not reinstalled and wheel builds were not repeated.

| Check | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q --cov --cov-report=term-missing --cov-fail-under=90` | **276 passed**, 52 warnings; **96.14%** aggregate coverage with branch tracking enabled; approximately 6 minutes. |
| `.venv/bin/ruff check .` | Passed. |
| `.venv/bin/ruff format --check .` | Passed; 101 files already formatted. |
| `.venv/bin/mypy` | Passed; 44 source files. |
| Pyright with explicit virtual-environment configuration | Passed; 0 errors and 0 warnings. Direct invocation initially failed to discover installed dependencies in this environment. A temporary configuration copied the project's settings and explicitly selected the existing `.venv`; repository configuration was unchanged. |
| Root/package license comparisons | Both package license files match the root license. |
| Focused synthetic reproductions | Confirmed both input-overwrite cases, incorrect builder settings, an unreadable producer-generated artifact, and a noise-only artifact with `phantom_mask_ok=True`, `roi_inside_phantom=True`, and `loc=ok`. |

Passing the existing suite does not cover the reproduced cases above. No persistent regression tests or application fixes were added as part of this review.

## Suggested implementation order

1. Protect input paths and fix the persisted localization verdict.
2. Make configuration provenance authoritative and enforce the artifact contract on write.
3. Correct report terminology and add the focused regression cases above.
4. Add reference datasets, batch failure inventories, and performance measurements according to intended deployment needs.
