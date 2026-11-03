# Vendored from dicom-util

Files copied from the sibling app `/home/claude/dicom-util` (not a dependency: copied, so this repo builds alone) at
commit `fe0d59eef4122fa2ceae0e426ed6321db357adb1`. They are kept as close to verbatim as possible so a later sync is a diff. Every deviation is in the last
column; "none" means byte-identical. To check: `diff` each file against the same path in dicom-util.

Left out on purpose: export, presets, viewer, template, layout, naming, qa-naming, nifti-naming, profiles, palette,
overlay, view, settle (and their tests), `app.ts`, `main.ts`, `zip.ts`, `ui/export-text.ts`, `ui/plan-memo.ts` and the
stylesheets. The dcm2niix arguments come from Python (`src/core/convert-args.ts`, `test/unit/convert-args.test.ts`, `test/unit/conversions.test.ts`, new), not from `profiles.ts`.
The test fixtures are the subset these unit tests read (`test/fixtures/zips/`, `tree/incoming/mprage_run1/`,
`tree/mueller/379736/`, `tree/pydicom/{dfl,mr_1_small}.dcm`); dicom-util's `test/fixtures/README.md` describes them.

| This repo (under `web/`) | dicom-util path | Change |
|---|---|---|
| `src/core/charset.ts` | `src/core/charset.ts` | none |
| `src/core/cp437.ts` | `src/core/cp437.ts` | none |
| `src/core/crc32.ts` | `src/core/crc32.ts` | none |
| `src/core/dcm2niix.ts` | `src/core/dcm2niix.ts` | none |
| `src/core/deflate.ts` | `src/core/deflate.ts` | none |
| `src/core/header.ts` | `src/core/header.ts` | none |
| `src/core/selection.ts` | `src/core/selection.ts` | none |
| `src/core/sniff.ts` | `src/core/sniff.ts` | none |
| `src/core/tree.ts` | `src/core/tree.ts` | none |
| `src/core/types.ts` | `src/core/types.ts` | none |
| `src/core/zipdir.ts` | `src/core/zipdir.ts` | none |
| `src/shell/archive.ts` | `src/shell/archive.ts` | none |
| `src/shell/budget.ts` | `src/shell/budget.ts` | none |
| `src/shell/convert.ts` | `src/shell/convert.ts` | Kept `batchedLog` and `convertSeries` (now exported, takes `wasm`). Removed `convertPlanned`, `PlannedHooks` and the `export-plan` import (export is not copied). |
| `src/shell/dcm2niix-protocol.ts` | `src/shell/dcm2niix-protocol.ts` | `RunMessage` and `isToWorker` gain `wasm: ArrayBuffer` (the module bytes; see README, "dcm2niix's wasm"). |
| `src/shell/dcm2niix-run.ts` | `src/shell/dcm2niix-run.ts` | `RunOptions.wasm` (required); each run posts its own `wasm.slice(0)` copy and transfers it. |
| `src/shell/dcm2niix.worker.ts` | `src/shell/dcm2niix.worker.ts` | Creates the module inside `run` with `wasmBinary: wasm` (was at load, fetching the wasm itself); uses `IN_DIR`, `OUT_DIR` and `dcm2niixArgv` from `core/convert-args.ts` instead of the literals `/in`, `/out` and `-o`. |
| `src/shell/download.ts` | `src/shell/download.ts` | none |
| `src/shell/intake.ts` | `src/shell/intake.ts` | none |
| `src/shell/phase.ts` | `src/shell/phase.ts` | none |
| `src/shell/scan.ts` | `src/shell/scan.ts` | none |
| `src/shell/source.ts` | `src/shell/source.ts` | none |
| `src/shell/ui/errors.ts` | `src/shell/ui/errors.ts` | none |
| `src/shell/ui/format.ts` | `src/shell/ui/format.ts` | none |
| `src/shell/ui/h.ts` | `src/shell/ui/h.ts` | none |
| `src/shell/ui/log.ts` | `src/shell/ui/log.ts` | none |
| `src/shell/ui/outcome.ts` | `src/shell/ui/outcome.ts` | none |
| `src/shell/ui/progress.ts` | `src/shell/ui/progress.ts` | none |
| `src/shell/ui/tree.ts` | `src/shell/ui/tree.ts` | Removed the series-action registry (`SeriesAction`, `registerSeriesAction`), the `dirs` parameter and the action slot: they need `core/layout.ts` (export). The `log` parameter of `buildTreeView` is now unused and kept, to stay diffable. |
| `src/shell/zip-sink.ts` | `src/shell/zip-sink.ts` | none |
| `src/shell/zip-source.ts` | `src/shell/zip-source.ts` | none |
| `src/types/app-version.d.ts` | `src/types/app-version.d.ts` | Only the `__DCM2NIIX_VERSION__` declaration (`__APP_VERSION__` is not used here). |
| `src/types/dcm2niix-glue.d.ts` | `src/types/dcm2niix-glue.d.ts` | `Dcm2niixOptions.wasmBinary` added. |
| `test/fixtures/tree/incoming/mprage_run1/035187.dcm` | `test/fixtures/tree/incoming/mprage_run1/035187.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/05ba42.dcm` | `test/fixtures/tree/incoming/mprage_run1/05ba42.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/0b081e.dcm` | `test/fixtures/tree/incoming/mprage_run1/0b081e.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/128a8d.dcm` | `test/fixtures/tree/incoming/mprage_run1/128a8d.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/16e52c.dcm` | `test/fixtures/tree/incoming/mprage_run1/16e52c.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/19ab19.dcm` | `test/fixtures/tree/incoming/mprage_run1/19ab19.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/354a29.dcm` | `test/fixtures/tree/incoming/mprage_run1/354a29.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/3eeccc.dcm` | `test/fixtures/tree/incoming/mprage_run1/3eeccc.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/46be8c.dcm` | `test/fixtures/tree/incoming/mprage_run1/46be8c.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/5aea54.dcm` | `test/fixtures/tree/incoming/mprage_run1/5aea54.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/878487.dcm` | `test/fixtures/tree/incoming/mprage_run1/878487.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/879203.dcm` | `test/fixtures/tree/incoming/mprage_run1/879203.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/8e89e7.dcm` | `test/fixtures/tree/incoming/mprage_run1/8e89e7.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/987de8.dcm` | `test/fixtures/tree/incoming/mprage_run1/987de8.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/bd2feb.dcm` | `test/fixtures/tree/incoming/mprage_run1/bd2feb.dcm` | none |
| `test/fixtures/tree/incoming/mprage_run1/c47bb1.dcm` | `test/fixtures/tree/incoming/mprage_run1/c47bb1.dcm` | none |
| `test/fixtures/tree/mueller/379736/907408/f21810/119fa0.dcm` | `test/fixtures/tree/mueller/379736/907408/f21810/119fa0.dcm` | none |
| `test/fixtures/tree/mueller/379736/907408/f21810/506788.dcm` | `test/fixtures/tree/mueller/379736/907408/f21810/506788.dcm` | none |
| `test/fixtures/tree/mueller/379736/907408/f21810/dacd63.dcm` | `test/fixtures/tree/mueller/379736/907408/f21810/dacd63.dcm` | none |
| `test/fixtures/tree/mueller/379736/907408/f21810/f7d52a.dcm` | `test/fixtures/tree/mueller/379736/907408/f21810/f7d52a.dcm` | none |
| `test/fixtures/tree/pydicom/dfl.dcm` | `test/fixtures/tree/pydicom/dfl.dcm` | none |
| `test/fixtures/tree/pydicom/mr_1_small.dcm` | `test/fixtures/tree/pydicom/mr_1_small.dcm` | none |
| `test/fixtures/zips/export.manifest.json` | `test/fixtures/zips/export.manifest.json` | none |
| `test/fixtures/zips/export.zip` | `test/fixtures/zips/export.zip` | none |
| `test/unit/archive.test.ts` | `test/unit/archive.test.ts` | none |
| `test/unit/budget.test.ts` | `test/unit/budget.test.ts` | none |
| `test/unit/charset.test.ts` | `test/unit/charset.test.ts` | none |
| `test/unit/crc32.test.ts` | `test/unit/crc32.test.ts` | none |
| `test/unit/dcm2niix-run.test.ts` | `test/unit/dcm2niix-run.test.ts` | Passes `wasm`; asserts it is sent as a copy and transferred. |
| `test/unit/dcm2niix.test.ts` | `test/unit/dcm2niix.test.ts` | `isToWorker` cases carry `wasm`, plus the missing and wrong-type cases. |
| `test/unit/deflate.test.ts` | `test/unit/deflate.test.ts` | none |
| `test/unit/dicom-bytes.ts` | `test/unit/dicom-bytes.ts` | none |
| `test/unit/errors.test.ts` | `test/unit/errors.test.ts` | none |
| `test/unit/format.test.ts` | `test/unit/format.test.ts` | none |
| `test/unit/header.test.ts` | `test/unit/header.test.ts` | none |
| `test/unit/helpers.ts` | `test/unit/helpers.ts` | none |
| `test/unit/intake.test.ts` | `test/unit/intake.test.ts` | none |
| `test/unit/phase.test.ts` | `test/unit/phase.test.ts` | none |
| `test/unit/selection.test.ts` | `test/unit/selection.test.ts` | none |
| `test/unit/sniff.test.ts` | `test/unit/sniff.test.ts` | none |
| `test/unit/tree.test.ts` | `test/unit/tree.test.ts` | none |
| `test/unit/zip-bytes.ts` | `test/unit/zip-bytes.ts` | none |
| `test/unit/zip-sink.test.ts` | `test/unit/zip-sink.test.ts` | none |
| `test/unit/zip-source.test.ts` | `test/unit/zip-source.test.ts` | none |
| `test/unit/zipdir.test.ts` | `test/unit/zipdir.test.ts` | none |

## Written here, not copied

`src/core/convert-args.ts`, `src/shell/gunzip.ts` (moved out of `pyodide.worker.ts`), `src/shell/dcm2niix-wasm.ts`,
`src/shell/intake-ui.ts` (the open/scan/tree wiring of dicom-util's `src/main.ts`, trimmed), `src/shell/conversions.ts`,
`scripts/vite-dcm2niix.mjs`, `e2e/intake.test.mjs`. `e2e/browsers.mjs` and `e2e/init-hooks.js` are trimmed adaptations of
dicom-util's, as their headers say.

## Dependencies

Same exact pins as dicom-util's `package.json`: `@niivue/dcm2niix` 1.3.20260724, `dicom-parser` 1.8.21, `fflate` 0.8.3,
`client-zip` 2.5.1.
