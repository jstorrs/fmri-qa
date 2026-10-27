# Pyodide feasibility spike (2026-10-27)

Question: can fmri-qa-core run in the browser as a single HTML file that is saved
and double-clicked on a locked-down machine (`file://`, no network, no install),
the way the sql.js-based exar1 viewer is delivered? The user picks a `.nii.gz` and
optional `.json` sidecar with an Open button or drag and drop.

Answer: yes. Built against commit 34ff19d with the core wheel unmodified.

## Results

Headless Chrome 149 and Firefox 158, Pyodide 314.0.7 (Python 3.14.2). Chrome ran
with offline mode on, and every request other than `data:`/`blob:` was aborted.
None was attempted.

| | |
|---|---|
| HTML size | 66.3 MB (49.6 MB gzipped); 53.1 MB without matplotlib (see below) |
| Ready after (page load + boot + packages + imports) | ~43 s Chrome, ~45 s Firefox |
| `from_nifti` + `analyze`, 64x64x28x200 `.nii.gz` | 4.95 s Chrome, 5.5 s Firefox, 2.80 s native CPython |
| Agreement with native | all 36 measurements; worst relative difference 1.6e-11 |

Largest inlined assets (base64 MB): scipy 18.7, scikit-image 12.7, matplotlib 9.3,
`pyodide.asm.wasm` 4.7 (gzipped in page), nibabel 4.4, numpy 4.0, stdlib 3.4.
Per-file figures are in `results/sizes.json`.

Cold start is mostly imports inside Pyodide, not decoding: runtime boot ~9 s,
package load ~14 s, importing fmriqa/scipy/skimage/nibabel ~16 s.

## Findings

- Core needed no changes. netCDF4 and dcm2niix are only imported inside
  functions, so `from_nifti` and `analyze` never reach them.
- Core's wheel cannot be installed with `micropip.install`, because it declares
  netCDF4 and dcm2niix. The spike unpacks the wheel with no dependency resolution.
- matplotlib and its dependencies (~13 MB) come only from Pyodide's lock file
  giving networkx (a scikit-image dependency) a dependency on matplotlib. The
  `--drop-matplotlib` build edits the lock file to cut it and passes the same
  test. That is a hand-edited lock file, not a supported configuration.
- Not measured: memory use, older browsers, a real hospital machine.

## How the page loads offline

Chromium refuses `fetch()` and Workers from `file://`, so everything is inlined as
base64 `<script type="application/octet-stream">` blocks. `pyodide.js` is inlined
as a script; `pyodide.asm.mjs` is imported from a `blob:` URL; the lock file is
passed as `lockFileContents`; and `fetch` is replaced with one that serves the
embedded assets by basename and refuses everything else. Dropped files are
written into Pyodide's in-memory filesystem and loaded with `QAScan.from_nifti`.

## Rebuilding

From the repo root, with the spike copied to a scratch directory `$SPIKE` that
has this `tools/` in it:

    uv run python $SPIKE/tools/fetch_vendor.py $SPIKE   # Pyodide, wheels, nibabel, core wheel
    python3 $SPIKE/tools/build.py $SPIKE [--drop-matplotlib]
    uv run python $SPIKE/tools/make_data.py $SPIKE/data
    uv run python $SPIKE/tools/native.py $SPIKE/data $SPIKE/dist/native.json
    (cd $SPIKE/tools && npm ci) && node $SPIKE/tools/run_test.mjs chrome

`make_data.py` uses `fmriqa_io.testing.write_phantom`, and `native.py` calls
`QAScan.from_nifti`, which will need updating once IO moves to fmri-qa-io;
check out 34ff19d to rerun it as it is. Snap Firefox cannot read `/tmp`;
`run_test.mjs firefox` needs `FFPROFILE` and `DATA_DIR` set to paths outside it.
