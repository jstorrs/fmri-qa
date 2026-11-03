# fmri-qa-web

The Python half of the [fmri-qa](../../README.md) browser page, and **not
published**: the page vendors its wheel. The page runs dcm2niix as WASM in one
worker and this package under Pyodide in another. Python stays the source of
truth for the file names, the dcm2niix flags and the metrics record.

It takes bytes and returns values: `name_outputs` (the names `import_dicom`
would file dcm2niix's outputs under), `analyze_series` (a series' report page and
metrics record, or why it failed), `batch_document` (the `fmri-qa --json`
envelope) and `contract` (the dcm2niix flags and schema version the page checks
itself against, and the package versions it shows). `fmriqa_web.bridge` wraps
them for the worker: buffers (`pyodide.toPy` memoryviews) in, strict JSON
strings out. It touches no file and starts no process.
