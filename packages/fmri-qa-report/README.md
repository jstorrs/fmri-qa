# fmri-qa-report

The presentation half of [fmri-qa](../../README.md): plots and multi-page PDF
packets rendered from a `fmriqc.analysis.QAArtifact`.

```console
$ fmri-qa scan.nii.gz --artifact qa.nc
$ fmri-qa-report qa.nc --pdf report.pdf --tier physics
```

The artifact is the only input. Every number, curve, mask, and image it draws is
precomputed by [`fmri-qa-core`](../fmri-qa-core), so a report can be produced on
another machine, long after the acquisition, with no access to the series — and
an artifact read back from disk renders exactly like one just computed.

Inside, content is split from format: `summary` and `content` build the text,
`panels` the matplotlib figures, and `formats/` holds one driver per output
format. Adding a format is a new file in `formats/`.

## Web summary schema

`fmriqc_report.web_summary.build_web_summary` is the pure boundary for a
static web report's `summary.json`. The command that writes a web report loads
each artifact and computes the SHA-256 digest of its exact bytes; it then passes
`RenderedRun(digest, artifact, input_names)` values to this module. This module
does no loading, hashing, or file I/O.

The root is schema version 1 and always has this shape:

```json
{
  "schema_version": 1,
  "report_version": "0.1.0",
  "counts": {
    "requested_inputs": 2,
    "unique_rendered_runs": 1,
    "duplicate_inputs": 0,
    "omitted_inputs": 1
  },
  "runs": [
    {
      "artifact_sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
      "report_url": "runs/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef/index.html",
      "title": "scan.nii.gz",
      "input_names": ["scan.qa.nc"],
      "provenance": {
        "source": "scan.nii.gz",
        "scan": "scan.nii.gz",
        "acquired_at": null,
        "analyzed_at": "2026-01-02T03:04:05+00:00",
        "core_version": "0.1.0",
        "artifact_model_schema_version": 7,
        "device": {
          "manufacturer": null, "model": null, "serial": null,
          "coil": null, "field_strength": null, "software": null
        },
        "acquisition": {
          "series": null, "tr": {"value": 2.0, "availability": "available"},
          "te": null, "flip_angle": null, "matrix": null, "voxel_mm": null,
          "slice_thickness": null, "pe_dir": null, "n_frames": 100,
          "n_trimmed": null, "slice_index": null, "n_slices": null
        }
      },
      "settings": {
        "trim_sec": {"value": 5.0, "availability": "available"},
        "detrend": "poly", "center": "image", "roi_size": 21,
        "pe_axis_override": null, "detrend_order": 2
      },
      "metrics": {
        "snr": {"value": 125.4, "unit": "1", "availability": "available"}
      },
      "localization": {
        "fraction": {"value": 0.2, "availability": "available"},
        "contrast": {"value": null, "availability": "positive_infinity"},
        "phantom_mask_ok": {"value": true, "availability": "available"},
        "roi_inside_phantom": {"value": true, "availability": "available"}
      },
      "clipping": {
        "availability": "available", "ceiling": null, "bits": null,
        "kept_count": 0, "pre_count": 0, "kept": false, "any": false
      }
    }
  ],
  "omitted_inputs": [{"input_name": "broken.qa.nc", "reason": "not an artifact"}]
}
```

Every run has these 15 metric keys, each shaped as
`{ "value", "unit", "availability" }`: `snr`, `sfnr`, `rdc`, `ghost_pct`,
`ghost_top_pct`, `ro_ghost_pct`, `acr_ghost_pct`, `drift_pct`,
`percent_fluctuation`, `outlier_max_pct`, `tc_outlier`, `spec_outlier`,
`max_translation`, `max_com_displacement`, and `fwhm`. The example shows one
only to stay small. Device fields are always `manufacturer`, `model`, `serial`,
`coil`, `field_strength`, and `software`. Acquisition fields are always
`series`, `tr`, `te`, `flip_angle`, `matrix`, `voxel_mm`, `slice_thickness`,
`pe_dir`, `n_frames`, `n_trimmed`, `slice_index`, and `n_slices`. Settings
always carries all six `AnalysisSettings` fields. `acquired_at` is the raw
possibly-partial artifact date/time, and absent metadata stays `null`.

Every float is a `{ "value", "availability" }` record (or `null` when the
artifact field itself is absent). A finite number has `available`; non-finite
numbers use `nan`, `positive_infinity`, or `negative_infinity` with a null
value. This makes `web_summary_json` strict JSON (`allow_nan=False`) without
losing the distinction. Localization verdicts use `not_recorded` when their
artifact value is `null`; they do not invent pass/fail thresholds. Clipping is
`not_determinable` only when `any` is null. A determinable no-rail result is
`available` with null `ceiling` and `bits` and zero counts.

`artifact_model_schema_version` is the schema of the artifact as loaded (after
any core migration), not the version of the file before loading. The digest
route is stable under input reordering and names exact artifact bytes only; it
does not identify an acquisition, session, or logical analysis. Duplicate run
digests are rejected. `requested_inputs` counts every supplied request;
`duplicate_inputs` counts extra successful requests represented by a unique
run; `omitted_inputs` counts each failed request.

Schema versions are append-only contracts: a consumer dispatches on the root
`schema_version`, and an incompatible wire change increments it. A version 1
reader must reject a newer version it does not understand rather than guessing.
