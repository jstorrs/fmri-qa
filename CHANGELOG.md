# Changelog

Notable user-facing changes to fmri-qa are recorded here. The project follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and will adopt semantic
versioning when the first stable public interface is released.

## Unreleased

### Added

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
- `python -m fmriqc_report`, matching `python -m fmriqc`.

### Fixed

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
- **`fmri-qa --artifact` silently discarding a scan.** A batch names each
  artifact after the scan's stem, so inputs sharing a file name across
  directories (`a/scan.nii.gz`, `b/scan.nii.gz`) overwrote one another and a
  later report packet was quietly missing scans. Such a batch is now refused
  before any analysis runs.
- `fmri-qa-report --pdf` creates the destination directory instead of failing on
  the name of the atomic write's temporary file.

### Changed

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

- `fmri-qa --pdf`, `--pdf-tier`, `--pdf-cover`, and `--pdf-appendix`. Rendering
  moved to `fmri-qa-report`, whose equivalents are `--pdf`, `--tier`, `--cover`,
  and `--appendix`; producing a report is now two commands.
