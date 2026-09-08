# Changelog

Notable user-facing changes to fmri-qa are recorded here. The project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and will adopt semantic
versioning when the first stable public interface is released.

## Unreleased

### Added

- `Provenance.slice_index` / `n_slices` record which plane of the volume the
  artifact describes, and `Measurements.phantom_contrast` the mask's
  interior-over-background ratio beside the verdict reached from it. Artifact
  schema version 5; an older archive reads them back as unknown. The report's
  acquisition line shows the slice, and its BAD PHANTOM MASK note names the
  contrast so a reader can see which test the mask failed. `fmri-qa --json`
  records carry `slice_index` and `phantom_contrast`; JSON schema version 4.
- **The whole Nyquist-ghost family from one set of masks.** `estimate_ghost`
  builds the region-matched signal/ghost masks once per in-plane axis and
  returns a `GhostResult` carrying the masks and every ratio measured on them;
  `QAMetrics.ghost` holds it, and the artifact's ghost regions are copied from
  it rather than rebuilt. The four percentages a table shows are unchanged.
- The BIDS sidecar is optional. A NIfTI exported without one (a scanner export
  that never went through dcm2niix) now analyzes with a warning and empty
  acquisition metadata instead of being refused.
- The TR is taken from the sidecar `RepetitionTime` when it is there, and
  otherwise from the header pixdim converted by the header's declared time
  unit; a disagreement between the two warns and names both values.
- `Provenance.n_trimmed` records how many warm-up volumes the analysis dropped,
  so `outlier_worst_frame` and the curve time axis map back to acquired volume
  numbers. Artifact schema version 4; older archives read it back as unknown.
- `fmri-qa --json` records now carry `source`, `datetime`, `tr`, `n_frames`,
  `n_trimmed`, `outlier_worst_frame`, the combined `fwhm`, and `fwhm_unit`.
  JSON schema version 3.
- `fmri-qa` and `fmri-qa-hilo` print each warning the analysis raised on
  stderr as `<scan>: warning: <message>`, attributed to the scan that raised it,
  instead of Python's default line naming a source file inside the package.
- Both distributions ship the MIT license text, and CI asserts it is installed
  with each wheel.

- **The analysis artifact.** `QAArtifact` publishes one analyzed series — its
  settings, provenance, scalar measurements, stability curves, and the four
  fBIRN summary images — fully resolved, so no consumer recomputes a metric.
  `analyze(scan)` produces one; `save_artifact`/`load_artifact` move it through
  a single versioned `.npz`.
- `fmri-qa --artifact PATH` saves the artifact for each analyzed scan (a file
  for one scan, a directory of `<scan>.qa.npz` for a batch).
- `fmri-qa-report ARTIFACT... --pdf FILE`, the new reporting command.
- Structured validation for scan data, analysis parameters, and high/low pairs.
- A versioned, standards-compliant JSON output contract.
- Atomic PDF writes and pagination for packet cover and provenance sections.
- Build-artifact smoke tests in CI.
- MIT licensing and distributable package-license metadata.
- Localization diagnostics in the artifact. `Measurements` now carries
  `phantom_fraction` (the share of the frame the phantom mask covers) and
  `roi_inside_phantom`, so a stored artifact says whether the segmentation and
  the summary ROI held — the difference between "the estimator declined" and
  "the analysis was measuring background". A report calls either failure out on
  the acquisition line, `fmri-qa` in a `loc` column, and `--json` in three
  fields (`phantom_fraction`, `phantom_mask_ok`, `roi_inside_phantom`) so a
  trend database can tell a measurement from a measurement of air. Artifact
  schema version 3; JSON schema version 2.
- Artifacts written under an older schema are migrated forward on read, with a
  warning, instead of being refused: a QA archive outlives the build that wrote
  it. Fields the older schema did not carry come back as "not recorded" — `None`
  for the localization verdicts, which `fmri-qa` shows as `loc ?` and a report
  as a quiet note — never as a fabricated pass. Only an artifact from a *newer*
  build, whose layout this one cannot know, is still refused.
- `python -m fmriqc_report`, matching `python -m fmriqc`.

### Fixed

- The phantom verdict (`phantom_mask_ok`, the table's `loc` column, the
  report's BAD PHANTOM MASK note) now applies the same test slice selection
  does: the mask must cover a plausible share of the frame *and* stand at
  least 4x above the background it was cut from. A scan holding no phantom
  segments to roughly half the frame, so the share test alone passed it, and
  a run could warn that no slice held a phantom and then save an artifact
  recording the mask as good. `PhantomGeometry` carries the measured
  `contrast`, and the warning names which test failed.
- `fmri-qa --artifact` and `fmri-qa-report --pdf` refuse an output path that
  names one of the run's inputs — the scan, its sidecar, or an artifact — and
  exit 1 before reading anything. Both writers move a finished file over the
  destination, so an output aliasing an input used to succeed and leave an
  archive where the NIfTI was, or a PDF where the archive was. Relative
  spellings, symlinks, and hard links of the same file are all caught.
- Preserve NIfTI proxy scaling for clipping detection and nulled-edge masks.
  Convert meter/micron voxel sizes to millimeters; unknown spatial units retain
  the millimeter assumption with an explicit warning.
- Validate artifact scalar types, settings, array shapes, coordinates, masks,
  and ROI bounds on load; malformed archives raise `InvalidArtifactError`.
- Preprocessed images own read-only arrays so the full input volume can be
  freed and caller mutations cannot invalidate cached summaries. Published
  artifact arrays also own read-only copies.
- Singular, non-finite, and unconverged motion fits now warn and publish NaN
  traces and peak metrics. `MotionResult.converged` identifies usable frames;
  motion plots label unresolved frames. Existing artifact layouts remain readable.
- Reject polynomial and spline detrending with no residual degrees of freedom.

- **A TR stored in milliseconds was read as seconds.** The loader took pixdim
  without its unit, so a header in msec gave a TR of 2000 s: no warm-up volumes
  were trimmed and the detrend order, which follows the run duration, exceeded
  the frame count, so the fit absorbed the noise and every stability metric was
  measured on a residual of nothing. The unit is converted now, the sidecar
  value is preferred, and `detrend_fn` refuses an order the frames cannot
  determine rather than returning zeros that look like a very stable scanner.
- **The LICENSE never reached a built package.** `license-files` pointed
  outside the package root, which the wheel dropped and the sdist recorded as
  a `../../` path.
- A directional FWHM the run could not name (no phase-encode axis resolved)
  was printed under `fwPE`/`fwRO` as the combined FWHM, a number that answers a
  different question. The table shows `?` and `--json` emits `null`.
- A phantom mask that is a single row or column crashed `analyze` after the
  whole analysis had run, from inside the convex-hull step; it now yields the
  empty outline the artifact already allowed for.
- `fmri-qa-hilo` raised a bare `ZeroDivisionError` on a zero low-flip mean.
- The ROI-fit warning suggested `center='image'` even when that was the mode in
  use; it names the other mode now.
- `save_artifact` wrote the destination in place, so an interrupted write left
  a truncated `.npz` in the archive. It writes a temporary file beside the
  destination and moves it into place. A malformed document that failed inside
  a schema migration escaped as a bare `KeyError` instead of
  `InvalidArtifactError`.
- A vendor-nulled image edge went undetected when the NIfTI carried a nonzero
  `scl_inter`, since a stored zero reads back as the intercept.
- `snr` and `sfnr` now return NaN, rather than infinity with a NumPy warning,
  when the static-noise variance or a ROI voxel's fluctuation noise is zero.
  The core test run went from 164 runtime warnings to none.

- **Phantom segmentation on an exactly-zero background.** The intensity
  quantiles seeding the watershed used strict comparisons, so an image whose air
  is exactly 0 — a background-suppressed or mask-multiplied reconstruction —
  seeded no background at all and the whole frame was labelled phantom. Every
  mask-based metric then read background silently: the ROI-fit guard passed
  vacuously, the N/2 ghost region eroded to nothing (NaN ghost percentages), and
  SFNR divided by a noiseless floor. The seeds are now inclusive, and
  `detect_phantom` warns when a mask comes out degenerate either way.
- **`--center phantom` selecting a slice with no phantom in it.** The mode took
  the slice with the largest *segmented* area, but segmenting a slice of pure
  air still labels about half the frame — more than a real cross-section — so a
  prescription running past the end of the phantom analyzed background instead.
  A slice now counts only if what its mask selected stands clear of the
  background it was separated from; if no slice does, the middle slice is used
  and a warning says so.
- **SNR biased low on an odd number of analyzed frames.** The static-noise
  difference image sums the odd frames against the even ones; with an odd frame
  count the two subsets differ by one, so the difference carried a whole frame of
  *signal* and its spatial variation across the ROI — not noise — set the
  denominator. A phantom shaded 25% across the FOV read 25% low, and because
  parity follows `--trim-sec`, the same series scored differently for a
  one-volume change in the warm-up trim. The difference is now formed over
  balanced subsets; the signal still averages the full series.
- **A phase-encode axis reported when none was measured.** The estimate picks
  the axis whose Nyquist ghost region is brighter, but an axis the ratio could
  not be measured on scores NaN — and every comparison against NaN is False, so
  `max` returned whichever axis it looked at first. An image with no measurable
  ghost (a collapsed segmentation, a phantom spanning the FOV) therefore always
  reported "axis 0", with four ghost percentages sampled from wherever that
  pointed, and an axis measurable on only one side could be resolved to the
  other. Only measurable axes are candidates now, and when neither is,
  `estimate_pe_axis` returns `None`: the run continues with the ghost metrics
  undefined and a warning, the artifact records no axis, and a report labels the
  direction "?" and draws no ghost regions.
- **`fmri-qa --artifact` silently discarding a scan.** A batch names each
  artifact after the scan's stem, so inputs sharing a file name across
  directories (`a/scan.nii.gz`, `b/scan.nii.gz`) overwrote one another and a
  later report packet was quietly missing scans. Such a batch is now refused
  before any analysis runs.
- `fmri-qa-report --pdf` creates the destination directory instead of failing on
  the name of the atomic write's temporary file.

### Changed

- `run_qa` writes the settings it was called with onto `QAResult.settings`
  (with the detrend order it resolved), and `build_artifact(result)` publishes
  those; its `settings` parameter is gone. It used to fill in defaults when
  none were passed, so a result computed with no trim, phantom centering, or
  a forced PE axis could be published as the default run. `AnalysisSettings`
  lives in `fmriqc.pipeline` (still exported from `fmriqc`), and its
  `roi_size` is now the side *requested*; the side analyzed is
  `images.roi.size`, as it always was.
- The phase-encode axis is estimated from the Nyquist ghost in one place, the
  pipeline. `QAScan.from_nifti` no longer estimates it (its `estimate_pe`
  parameter is gone) and only reports what the sidecar and header say, so the
  load layer no longer depends on the metrics layer.
- `Measurements.fwhm_unit`, `Measurements.pe_label`, and `PsfCurves.unit` are
  closed sets (`LengthUnit`, `PeLabel` in `fmriqc.types`), and `load_artifact`
  refuses a stored value outside them. `FBIRN_ROI_SIZE` lives in
  `fmriqc.types`, shared by the ROI resolver and the artifact's default.
- `QAImages` caches its derived summary images instead of recomputing each
  full-slice reduction on every access.
- The `notebooks` extra is no longer published with `fmri-qa-core`; the
  notebook stack is a root dependency group taken with `make sync-notebooks`.
- pre-commit runs the locked `ruff` through `uv run`, so the hook and
  `make check` cannot disagree on formatting. The style guides describe the
  tooling this repository actually has.

- **The project is now two distributions.** `fmri-qa-core` (import `fmriqc`)
  holds the calculation half and depends on nothing that draws; `fmri-qa-report`
  (import `fmriqc_report`) holds the plots and PDF packets and consumes only a
  `QAArtifact`. Installing `fmri-qa-report` brings both. The single `fmri-qa`
  distribution is gone; see `notes/analysis_report_split.md`.
- A report header now shows the phase-encode direction that was actually used.
  It previously preferred the sidecar's DICOM direction even when `--pe-axis`
  overrode the axis, so the header could disagree with the metrics table.
- Phase encoding is explicitly limited to the in-plane axes supported by the
  single-slice metrics.
- The svglib image-alignment workaround now probes compatibility before use, and
  is installed on the first render rather than at import: it mutates a
  third-party class process-wide, and an unrecognized svglib should fail the
  render that needs it rather than `import fmriqc_report`.
- `fmri-qa-report` declares its dependency on `cycler`, which its `Theme` imports
  directly and which had until now arrived only as a matplotlib transitive.

### Removed

- `MissingSidecarError`: a missing sidecar is a warning now, not an error.
- `ghost_top_ratio`, `acr_ghosting_ratio`, and `phase_encode_axis`; their
  measurements come from `GhostResult`, and `QAMetrics` carries that result
  instead of four loose percentages.

- `fmri-qa --pdf`, `--pdf-tier`, `--pdf-cover`, and `--pdf-appendix`. Rendering
  moved to `fmri-qa-report`, whose equivalents are `--pdf`, `--tier`, `--cover`,
  and `--appendix`; producing a report is now two commands.
