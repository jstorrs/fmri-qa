# Splitting calculation from presentation: the analysis artifact

Status: implemented.

Update (2026-10-27): the layout has grown since this note was written. Core is
now pure calculation and reads no files, so it can run in a browser under
Pyodide. File formats and IO moved to a new `fmri-qa-io`, and the commands to
`fmri-qa-cli`. That makes five distributions; see the table under "The
packages". The calculation/presentation reasoning below still holds.

This document records why fmri-qa is split into separate distributions, what
crosses the boundary between calculation and presentation, and the rules that
keep the boundary from eroding.

## Motivation

The two halves of a QA tool have almost nothing in common except a result.

*Calculation* reads a 4-D series, segments a phantom, and computes physics. It
is numeric, slow, needs the acquisition on disk, and changes when the physics
changes. *Presentation* draws curves and lays out pages. It is typographic,
fast, needs no acquisition at all, and changes when someone wants a different
report.

Keeping them apart pays on every axis:

- **Deployment.** A trend database, a scanner-console script, or a nightly
  cron job wants the numbers. Installing the calculation half does not install
  matplotlib, a drawing stack none of them calls.
- **Coupling.** Analysis decisions are made once, in the analysis, and
  published as fields. Plotting code does not re-derive ROI time series, ghost
  masks, the SFNR image, the phantom convex hull, or the PSF model, so it cannot
  silently disagree with the metric that reported the number.
- **Time.** Re-rendering a report with a different theme or a fixed typo does
  not re-run the pipeline, and does not need the original NIfTI on that
  machine.

## The seam: `QAArtifact`

One value object crosses the boundary. It is produced by
`fmriqa.analysis.analyze(scan, settings)` and it is the *only* thing the report
half accepts.

| Section | What it holds |
|---|---|
| `AnalysisSettings` | the knobs the run was asked for (written by `run_qa` onto its result, so the artifact cannot publish a default the run did not use), plus the resolved detrend order |
| `Provenance` | scan name, source, timestamp, computing version, TR, the frame count and the warm-up volumes dropped before it, the plane of the volume analyzed, and the sidecar acquisition metadata |
| `Measurements` | every reported scalar, flat — no metric result object survives |
| `Curves` | the 1-D traces: ROI signal/trend/residual, outliers, spectrum, motion, COM, Weisskoff, PSF |
| `ArtifactImages` | the four FBIRN images (signal, SFNR, fluctuation noise, static noise) plus phantom mask, convex hull, invalid edge, ROI box, ghost regions |

Two rules decide what belongs in it:

1. **Everything a consumer could need is resolved at build time.** Derived
   properties become plain fields; the ROI series are extracted; the spectrum is
   computed and DC-dropped; the ghost masks and the phantom hull are
   materialized; the PSF model is sampled over a range the *analysis* chooses.
   A consumer that has to compute something has found a gap in the artifact.
2. **Nothing else is carried.** The 4-D series, the trimmed center slice, and
   the per-voxel fluctuations stay behind in `pipeline.QAResult`. They are large,
   and no report has ever needed a voxel it could not get from a summary image.

`QAResult` is the pipeline's working output and `run_qa` returns it;
`build_artifact` projects it. `analyze` is the front door
that does both.

## Serialized form

The artifact is saved as one netCDF-4 file (`<scan>.qa.nc`) carrying
`ARTIFACT_SCHEMA_VERSION`, which a reader checks and refuses by name on a
mismatch. The layout, the reasons for netCDF, and the NaN-versus-`null`
convention are in
[`docs/user-guide/artifact.md`](../docs/user-guide/artifact.md).

## The packages

| Distribution | Import | Role | Dependencies |
|---|---|---|---|
| `fmri-qa-core` | `fmriqa` | Calculation: scan value objects, prep, metrics, pipeline, the artifact and its schema (compose, decompose, migrate), the pure sidecar and DICOM-naming rules. No drawing stack, and no file IO. | numpy, scipy, scikit-image |
| `fmri-qa-io` | `fmriqa_io` | Files: `load_scan`, `scan_from_bytes`, the netCDF-4 artifact container (`save_artifact`, `load_artifact`), DICOM import through dcm2niix. | fmri-qa-core, nibabel, numpy, netCDF4 and dcm2niix (not under Pyodide) |
| `fmri-qa-cli` | `fmriqa_cli` | The `fmri-qa`, `fmri-qa-hilo`, `fmri-qa-import` and `fmri-qa-report` commands. | fmri-qa-core, fmri-qa-io, fmri-qa-report |
| `fmri-qa-report` | `fmriqa_report` | One artifact rendered as one self-contained HTML page. | fmri-qa-core, numpy, matplotlib, cycler |
| `fmri-qa-launcher` | `fmriqa_launcher` | The one-step DICOM-to-report command (`fmri-qa-run`) and the desktop panel (`fmri-qa-panel`). | fmri-qa-cli, fmri-qa-core, fmri-qa-io, fmri-qa-report; tkinter from the standard library |

The dependency points one way: report depends on core, core knows nothing of
report or io, and the launcher sits on top of all of them. Within that, the report half
may import only `fmriqa.analysis` (the artifact) and `fmriqa.types` (the shared
array/option vocabulary) -- never `load`, `prep`, `metrics`, or `pipeline`, never
the `fmriqa` package as a whole, which would pull all of them, and nothing from
`fmriqa_io`. The report takes an artifact in memory and returns a string. The
applications load the artifact and write the page.

A rule like that erodes one convenient import at a time, so layering tests check
it mechanically:

- `packages/fmri-qa-report/tests/test_layering.py` parses every report source
  file and fails on an import outside the allowlist.
- `packages/fmri-qa-core/tests/test_layering.py` checks the ordering of the
  stack inside calculation: a lower layer never imports a higher one.

## Using it

```console
$ fmri-qa scan.nii.gz --artifact qa.nc    # calculate once
$ fmri-qa-report qa.nc --html qa.html    # render as often as you like
```

## Consequences worth knowing

- **Producing a report is two commands**, or one with `fmri-qa-run`.
- **The report states one phase-encode axis.** The artifact resolves a single
  `pe_label`, so a `--pe-axis` override shows in the header and the table and
  the report cannot differ.
- **The report is testable without any acquisition.** Its tests build an
  artifact in memory and never touch a NIfTI, which is evidence that the seam
  holds.

## Follow-ups

- The deferred acceptance-threshold subsystem (the "Acceptance thresholds" gap
  in `IMPLEMENTATION_STATUS.md`) has an obvious home: thresholds are evaluated
  against `Measurements`, and could be carried in the artifact as a `Verdicts`
  section.
- Trending across artifacts -- reading a directory of `.qa.nc` files into a
  table -- needs nothing from either package that is not already public.
