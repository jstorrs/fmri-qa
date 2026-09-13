# Splitting calculation from presentation: the analysis artifact

Status: implemented.

This document records why fmri-qa ships as two distributions, what crosses the
boundary between them, and the rules that keep the boundary from eroding.

## Motivation

The two halves of a QA tool have almost nothing in common except a result.

*Calculation* reads a 4-D series, segments a phantom, and computes physics. It
is numeric, slow, needs the acquisition on disk, and changes when the physics
changes. *Presentation* draws curves and lays out pages. It is typographic,
fast, needs no acquisition at all, and changes when someone wants a different
report.

Fusing them costs on every axis:

- **Deployment.** A trend database, a scanner-console script, or a nightly
  cron job wants the numbers. Installing them dragged in matplotlib, ReportLab,
  and svglib — a drawing stack none of them ever calls.
- **Coupling.** `report/` reached into `QAResult.images.center_slice` to
  re-derive ROI time series, rebuilt the ghost masks the ghost metric had
  already built, recomputed the SFNR image and the phantom convex hull, and
  re-sampled the PSF model. Analysis decisions were being made in plotting code,
  where they could silently disagree with the metric that reported the number.
- **Time.** Re-rendering a packet with a different theme, a different tier, or a
  fixed typo meant re-running the whole pipeline over the original NIfTI — which
  had to still be on that machine.

## The seam: `QAArtifact`

One value object crosses the boundary. It is produced by
`fmriqc.analysis.analyze(scan, settings)` and it is the *only* thing the report
half accepts.

| Section | What it holds |
|---|---|
| `AnalysisSettings` | the knobs the run was asked for (written by `run_qa` onto its result, so the artifact cannot publish a default the run did not use), plus the resolved detrend order |
| `Provenance` | scan name, source, timestamp, computing version, TR, the frame count and the warm-up volumes dropped before it, the plane of the volume analyzed, and the sidecar acquisition metadata |
| `Measurements` | every reported scalar, flat — no metric result object survives |
| `Curves` | the 1-D traces: ROI signal/trend/residual, outliers, spectrum, motion, COM, Weisskoff, PSF |
| `ArtifactImages` | the four fBIRN images (signal, SFNR, fluctuation noise, static noise) plus phantom mask, convex hull, invalid edge, ROI box, ghost regions |

Two rules decide what belongs in it:

1. **Everything a consumer could need is resolved at build time.** Derived
   properties become plain fields; the ROI series are extracted; the spectrum is
   computed and DC-dropped; the ghost masks and the phantom hull are
   materialized; the PSF model is sampled over a range the *analysis* chooses.
   A consumer that has to compute something has found a gap in the artifact.
2. **Nothing else is carried.** The 4-D series, the trimmed center slice, and
   the per-voxel fluctuations stay behind in `pipeline.QAResult`. They are large,
   and no report has ever needed a voxel it could not get from a summary image.

`QAResult` still exists and `run_qa` still returns it: it is the pipeline's
working output, and `build_artifact` projects it. `analyze` is the front door
that does both.

## On disk

`save_artifact` / `load_artifact` move an artifact through a single netCDF-4
file (`<scan>.qa.nc`): every array is a compressed, checksummed variable under
its dotted path (`curves.weisskoff.cv`, `images.ghost.pe_ghost`), declared over
shared named dimensions (`frame`, `frequency`, `row`, `col`, …); everything that
is not an array rides in a JSON document held in the global attribute
`document`; and every scalar measurement is published as an attribute of its own
beside it. The file needs nothing a site does not already have to inspect —
MATLAB's built-in `ncread`/`ncdisp`, R's `ncdf4`, `ncdump`, xarray — and one
array can be pulled out without materializing the rest.

netCDF replaced a compressed `.npz` for exactly that reason: the `.npz` was
readable with `numpy` and `json` and with little else, needing npy-matlab and a
manual unzip in MATLAB and offering R nothing but numeric arrays. The costs are
a ~10 MB `netCDF4` wheel (libhdf5 and libnetcdf, the library those readers use
themselves), HDF5's advisory file locking on network shares, and size: HDF5
spends about 110 KB of fixed metadata on a layout this size, so the test
phantom's artifact is 132 KB against the `.npz`'s 24 KB, and a real
128×128×300 acquisition 436 KB against 230 KB. `load_artifact` reads both
containers, telling them apart by the file's leading bytes rather than its
suffix; nothing writes an `.npz` any more.

`ARTIFACT_SCHEMA_VERSION` pins the layout, and a mismatch is refused by name
rather than misread field by field. The mapping in `analysis/serialize/` is
written out explicitly rather than reflected over the dataclasses: the layout is
a published contract, so adding a field should be a deliberate edit to the file
format, not a side effect of adding an attribute.

The embedded JSON uses Python's `NaN` tokens. This is deliberate: a NaN
measurement says *an estimator could not resolve this*, which is different from
the `null` that says *this quantity does not apply*, and flattening the two
would lose information a physicist reads.

## The two distributions

```
packages/fmri-qa-core     fmriqc         numpy, scipy, nibabel, scikit-image
packages/fmri-qa-report   fmriqc_report  fmri-qa-core, numpy, matplotlib, reportlab, svglib
```

The dependency points one way: report depends on core, core knows nothing of
report. Within that, the report half may import only `fmriqc.analysis` (the
artifact) and `fmriqc.types` (the shared array/option vocabulary) — never
`load`, `prep`, `metrics`, or `pipeline`, and never the `fmriqc` package as a
whole, which would pull all of them.

That is a rule that erodes one convenient import at a time, so it is checked
mechanically: `packages/fmri-qa-report/tests/test_layering.py` parses every
report source file and fails on an import outside the allowlist. CI checks the
other direction against the built wheels — the core wheel is installed alone and
asserted to have no matplotlib and no ReportLab importable.

## Using it

```console
$ fmri-qa scan.nii.gz --artifact qa.nc           # calculate once
$ fmri-qa-report qa.nc --pdf report.pdf          # render as often as you like
```

A batch writes one artifact per scan into a directory, and `fmri-qa-report`
takes several artifacts to build one packet:

```console
$ fmri-qa run-*.nii.gz --artifact artifacts/
$ fmri-qa-report artifacts/*.qa.nc --pdf packet.pdf --tier physics --cover --appendix
```

## Consequences worth knowing

- **`fmri-qa` no longer writes PDFs.** The `--pdf`, `--pdf-tier`, `--pdf-cover`,
  and `--pdf-appendix` flags moved to `fmri-qa-report` as `--pdf`, `--tier`,
  `--cover`, `--appendix`. Producing a report is now two commands.
- **A `--pe-axis` override now shows in the report header.** The header used to
  prefer the sidecar's DICOM direction unconditionally, disagreeing with the
  axis the ghost masks actually used. The artifact resolves one `pe_label`, so
  the table and the report cannot differ.
- **The report is testable without any acquisition.** Its tests build an
  artifact in memory and never touch a NIfTI — which is itself evidence that the
  seam holds.

## Follow-ups

- The deferred acceptance-threshold subsystem (see `report_redesign.md`) now has
  an obvious home: thresholds are evaluated against `Measurements`, and could be
  carried in the artifact as a `Verdicts` section.
- A second format driver (HTML) costs a file in `formats/`, unchanged content
  modules, and no analysis work at all.
- Trending across artifacts — reading a directory of `.qa.nc` files into a table
  — needs nothing from either package that is not already public.
- Coordinate variables for the named dimensions are the obvious remaining
  addition: a reader gets the axes by name today, but not the values along
  them.
