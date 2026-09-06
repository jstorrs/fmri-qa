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
  the acquisition line. Artifact schema version 2.

### Fixed

- **Phantom segmentation on an exactly-zero background.** The intensity
  quantiles seeding the watershed used strict comparisons, so an image whose air
  is exactly 0 — a background-suppressed or mask-multiplied reconstruction —
  seeded no background at all and the whole frame was labelled phantom. Every
  mask-based metric then read background silently: the ROI-fit guard passed
  vacuously, the N/2 ghost region eroded to nothing (NaN ghost percentages), and
  SFNR divided by a noiseless floor. The seeds are now inclusive, and
  `detect_phantom` warns when a mask comes out degenerate either way.
- **`fmri-qa --artifact` silently discarding a scan.** A batch names each
  artifact after the scan's stem, so inputs sharing a file name across
  directories (`a/scan.nii.gz`, `b/scan.nii.gz`) overwrote one another and a
  later report packet was quietly missing scans. Such a batch is now refused
  before any analysis runs.

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

### Removed

- `fmri-qa --pdf`, `--pdf-tier`, `--pdf-cover`, and `--pdf-appendix`. Rendering
  moved to `fmri-qa-report`, whose equivalents are `--pdf`, `--tier`, `--cover`,
  and `--appendix`; producing a report is now two commands.
