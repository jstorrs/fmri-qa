# fmri-qa in the browser

One self-contained HTML file, `web/dist/fmri-qa.html`, that a user saves and double-clicks. It opens from `file://`
with no network and no install, and runs fmri-qa under [Pyodide](https://pyodide.org) 314.0.7 (CPython 3.14.2 in
WebAssembly). The page starts Python in a worker in the background, imports `fmriqa_web`, shows the boot stages and
answers bridge calls (step 4). Meanwhile it takes DICOM, shows the series tree and converts a selection with dcm2niix
WebAssembly (step 5, "Intake and conversion" below), then names and analyzes each series in Python, with a report preview
and per-file downloads (step 6, "Runs" below). It carries the licences of everything it bundles under "About & licences"
(step 8, "Notices" below).

## Build

From the repo root:

| Command | What it does |
|---|---|
| `make web-vendor` | `npm ci` in `web/` (only when `package-lock.json` is newer than the install), then `uv run python scripts/web_vendor.py`: fills the gitignored `web/vendor/` (about 56 MB, downloaded once and cached) and writes `web/vendor/manifest.json` |
| `make web-check` | the same `npm ci` if needed, then `tsc --noEmit` for the app and the tests, then the vitest unit tests (`test/unit/`) |
| `make web-notices` | `make web-vendor`, then `uv run python scripts/web_notices.py`: rewrites the committed `web/THIRD_PARTY_NOTICES.md` ("Notices" below) |
| `make web` | `make web-vendor`, then `vite build` to `web/dist/fmri-qa.html`; the build first runs `scripts/web_notices.py --check` and fails if the notices are stale, and `scripts/size-check.mjs` then fails it over 72 MB ("Limits" below) |
| `make web-e2e` | `make web`, then `node --test e2e/**/*.test.mjs` (`boot.test.mjs`, `intake.test.mjs`, `run.test.mjs`, `about.test.mjs`) in Chrome and Firefox (`E2E_BROWSERS=chrome,firefox,webkit` to choose) |

`scripts/web_vendor.py` collects:

- Pyodide's runtime files (`pyodide.asm.wasm`, `python_stdlib.zip`, `pyodide-lock.json`) from the `pyodide` npm
  package, whose version `package.json` pins;
- the dependency closure, in that lock file, of the Pyodide packages the wheels require directly (`numpy`, `scipy`,
  `scikit-image`, `packaging`, `matplotlib`, `cycler`), from `cdn.jsdelivr.net/pyodide/v314.0.7/full/`, each checked
  against the lock's sha256;
- nibabel, which Pyodide does not ship: the wheel and sha256 the root `uv.lock` pins;
- the four workspace wheels (`fmri-qa-core`, `-io`, `-report`, `-web`), built with `uv build`.

The page unpacks the wheels without a resolver, so the script fails unless every wheel's `Requires-Dist`, with its
markers evaluated as Pyodide would (`sys_platform == "emscripten"`, Python 3.14), is met by a vendored wheel or a
package in the closure. The manifest lists every asset in boot order with its sha256, kind and whether the page stores
it gzipped, and the four workspace versions, which the e2e test compares with `contract_json()`'s.

`scripts/vite-pyodide.mjs` puts each manifest asset in the page as an inert
`<script type="application/octet-stream" data-name data-kind [data-gz]>` of base64 (gzipped first for the wasm and the
lock file), after checking its sha256. A missing manifest fails the build with the command to run.

Integrity is checked at build time only: each download against the sha256 in `pyodide-lock.json` or `uv.lock`, and
every file again against the manifest when it is embedded. The page does not re-check the bytes at run time: they are
part of the same file as the code that would check them.

The e2e browsers are dicom-util's (`~/.cache/dicom-util/browsers`, same overrides: `CHROME_PATH`, `FIREFOX_PATH`,
`PLAYWRIGHT_BROWSERS_PATH`, `WEBKIT_LD_LIBRARY_PATH`; see dicom-util's `e2e/README.md` to install them).

## Boot path

1. `src/shell/python.ts` (main thread) reads the inert blocks' text, parses each into an `EncodedAsset`
   (`src/core/assets.ts`), removes the elements, and posts them all in one `boot` message to the worker (cloned:
   strings cannot be transferred).
2. The worker (`src/shell/pyodide.worker.ts`) is a **classic** worker made from a `blob:` URL by Vite's
   `?worker&inline` with `worker.format: 'iife'`. An ES-module blob worker fails on `file://` in Chrome
   (dicom-util's PLAN.md).
3. It decodes every asset (`Uint8Array.fromBase64` where present, else an `atob` loop) and gunzips with
   `DecompressionStream`, fed from a `ReadableStream`. It does not use a `Blob`, because WebKit cannot read a Blob inside
   a worker on `file://` (`The I/O read operation failed`).
4. It replaces `fetch` with a shim (`src/core/asset-fetch.ts`) that serves an asset for
   `https://pyodide.invalid/<file name>` and refuses everything else, `data:` and `blob:` included, reporting each
   refusal to the page. It looks names up in the live asset map, which the boot empties once it is done, so every
   later fetch is refused and reported too. Pyodide is started with `indexURL` and `packageBaseUrl` both `https://pyodide.invalid/`. With them it
   requests only `pyodide.asm.wasm`, `python_stdlib.zip` and the package wheels by file name. No other URL form was
   requested in any browser (the e2e test fails on a refusal).
5. `loadPyodide` gets `lockFileContents` (the vendored lock), `createPyodideModule` (below), `env.MPLBACKEND = "Agg"`
   (set before any Python import) and `convertNullToNone: true`, so JS `null` reaches `analyze_json` as `None`, not
   `jsnull`.
6. `loadPackage` loads every vendored Pyodide package by its lock-file name. It never rejects, so the worker fails the
   `packages` stage itself, naming every package missing from `loadedPackages` and each message `errorCallback`
   collected. `unpackArchive(…, "whl", {extractDir})` unpacks nibabel and the four workspace wheels into site-packages
   (`sysconfig.get_path("purelib")`), where `loadPackage` puts the others. The default is the working directory,
   which is importable only through `sys.path[0] == ""`; an `os.chdir` would break both imports and
   `importlib.metadata` versions. The worker then imports `fmriqa_web.bridge` and touches `fmriqa.analyze` (fmriqa's root
   is lazy), so the first call is warm. It calls `contract_json()` and posts `ready`.
7. `call {id, fn, args}` runs one of the four bridge functions, with each argument converted by `pyodide.toPy`
   (`Uint8Array` to `memoryview`). It returns the JSON string verbatim. A Python exception rejects that call only, and so
   does a malformed call that carries an `id`.
8. The base64 text is held only by the decoding helper. Once it returns, the boot keeps each asset's name, kind and bytes.

The page has three end states, in `body[data-python]`. `ready` means the boot finished. `failed` means the boot did not
reach `ready`. `crashed` means Python was ready and then the worker died or broke the protocol: an uncaught worker
error, an unreadable message, or an `error` with no call `id`. On either failure every pending call is rejected, later
calls are refused, and the worker is terminated. A `new Worker` that throws also ends in `failed`, with its message.

### How pyodide.asm.mjs is loaded, and why

**It is bundled into the worker at build time.** `classicPyodideAsm` in `scripts/vite-pyodide.mjs` rewrites
`node_modules/pyodide/pyodide.asm.mjs` before Vite's own plugins run. Its three `import.meta.url` uses become the string
`https://pyodide.invalid/pyodide.asm.mjs`. The plugin fails the build if that count changes, or if the worker build never
loaded the file, which would mean the rewrite was silently skipped. None of the three is reached in a browser with the
settings `loadPyodide` passes: one is Node-only, one names the script for `locateFile` (which Pyodide supplies), and
one is a wasm fallback that `locateFile` overrides. The worker imports the module's default export and passes it to
`loadPyodide` as `createPyodideModule`. `pyodide.mjs` itself (the ESM loader) is bundled into the iife worker
unchanged, and has no `import.meta`. The worker script is emitted with `"use strict"`.

What was tried first, measured with the page's CSP:

| In a classic blob worker on file:// | Chrome 149 | Firefox 159 | WebKit 27.2 (Playwright) |
|---|---|---|---|
| `await import(blobUrl)` of pyodide.asm.mjs | works (boot in ~49 s) | works (~54 s) | **fails**: "Cross-origin script load denied by Cross-Origin Resource Sharing policy" |
| `importScripts(blobUrl)` (the classic-script fallback) | works | works | **fails**: "NetworkError: Load failed" ("Not allowed to load local resource: blob:null/…") |
| bundled into the worker (adopted) | works | works | works |

Bundling works in every browser with no script loaded at run time. It also means the CSP needs no `blob:` for scripts
inside the worker. The cost is about 0.6 MB of page size: the 1.25 MB module becomes plain JS in the worker's string
instead of gzipped base64.

Vite would make an iife worker's `import.meta.url` work by itself, so the rewrite is not what keeps `import.meta` out
of the worker. It runs first for two other reasons:

- Vite would take `new URL("pyodide.asm.wasm", import.meta.url)` for an asset and inline the 9.6 MB wasm a second
  time. The build grew to 79.9 MB.
- The script URL becomes a fixed URL beside `indexURL`, not the worker's `blob:` URL.

`noInlinedWasm` (in `scripts/vite-pyodide.mjs`) fails the build on any `data:application/wasm` in the output.

### The classic-worker probe

Pyodide 314 refuses to run in a classic worker. Both `pyodide.mjs` and the copy inside `pyodide.asm.mjs` call
`importScripts("data:text/javascript,")` and throw "Classic web workers are not supported" if it loads. The refusal
exists because the loader expects to `import()` its scripts. Here Pyodide loads no script at run time:
pyodide.asm.mjs is bundled. `src/shell/classic-worker-probe.ts` is imported first
in the worker, before Pyodide's module body runs. It answers that one probe URL the way a module worker would (it throws)
and passes every other `importScripts` call on. Without the shim the boot still succeeds, but only by accident: the CSP
blocks the probe's `data:` URL, which gives the same answer and raises a `securitypolicyviolation`
(`script-src-elem data`) on every boot. **This depends on a Pyodide internal.** `test/unit/classic-probe.test.ts` fails fast if either file stops calling
`importScripts` exactly once, with exactly `CLASSIC_WORKER_PROBE` (`src/core/classic-probe.ts`). The e2e test catches
any other change, because the boot fails or a violation appears.

## CSP

```
default-src 'none'; script-src 'unsafe-inline' 'wasm-unsafe-eval' blob:; worker-src blob:;
img-src data: blob:; style-src 'unsafe-inline'
```

This held in Chrome, Firefox and WebKit. It is the policy in the brief minus `connect-src blob: data:`. Nothing calls the
browser's own `fetch`: the worker's shim serves every request from memory and refuses the rest, `data:` and `blob:`
included. With no `connect-src`, `default-src 'none'` blocks any connection outright. Nothing needed `'unsafe-eval'`. Pyodide's `eval` uses are
Emscripten's `EM_ASM`/`EM_JS` in side modules and `emscripten_run_script`, which none of the loaded packages reached.
They would show as a violation. The e2e test checks for none in the page (an init script listens from before any page
script) and in the worker (it forwards its own `securitypolicyviolation` events). Two harness tests then raise one
deliberately: an `<img>` in the page, and an `importScripts` of an https URL run inside the worker through the driver.
Each asserts the violation was recorded, so an empty list really means none. The driver can run code in the worker
in Chrome (puppeteer) and WebKit (Playwright). Puppeteer's Firefox driver (WebDriver BiDi) lists the worker, but evaluating in it fails
with "no such frame", so the worker test is skipped there, and only there (elsewhere a missing worker or that error fails it); the worker path is unproven in Firefox. `'unsafe-inline'` is for the single-file build's inline module script. `blob:` in `script-src`
and `worker-src` is for the inline worker. `'wasm-unsafe-eval'` is for compiling the interpreter and the packages'
shared libraries.

## Intake and conversion

Copied from dicom-util (the sibling app) and kept near-verbatim; `VENDORED.md` lists every file, its
source commit and each deviation. Python is not involved in this step: it boots in the background and is not needed to
open or convert.

- **Intake** (`src/shell/intake.ts`, `archive.ts`, `zip-source.ts`, `scan.ts`): "Open folder" (the directory picker where
  there is one, else a `webkitdirectory` input), "Open files" (DICOM and `.zip`), and drag and drop. A `.zip` is replaced
  by its entries, one level deep, read lazily. Headers are parsed on the main thread (WebKit cannot read a `File` in a
  worker on file://). `src/shell/intake-ui.ts` is the wiring, from dicom-util's `main.ts` without its export, viewer,
  restore-previous-set and folder-listing parts.
- **Tree** (`src/core/tree.ts`, `src/shell/ui/tree.ts`): Patient, Study, Series with checkboxes, counts (`#counts` data
  attributes), the skipped/rejected/duplicate lists, and the selection summary (`#summary`).
- **Conversion** (`src/shell/conversions.ts`, `runOne`): one series in a fresh dcm2niix worker; the first part of a run
  (below). dcm2niix's warnings, errors and skipped-file lines go to the log on every outcome.
- **dcm2niix arguments** come from Python: `src/core/convert-args.ts` takes `dcm2niix_flags` from
  `src/generated/contract.json` and adds `-o /out /in`, the paths of the worker's in-memory filesystem. The flags
  include `-l o -b y` (integer NIfTI, BIDS sidecar) and `-ba o` (omit patient identifiers, keep dates).
- **Memory.** The Pyodide worker lives for the whole session. Each conversion runs in a fresh dcm2niix worker, one at a
  time, terminated afterwards (as in dicom-util), so a wasm abort in dcm2niix (an out-of-memory in its 2 GB heap) does not affect Python. The browser may still share
  renderer memory between the workers. Files are read on the main thread, one at a time, and transferred to the worker.

### dcm2niix's wasm: embedded, handed over as bytes

`scripts/vite-dcm2niix.mjs` puts `dcm2niix.jpeg.wasm` (984 KB) in the page as one inert gzipped base64 block,
`<script type="application/octet-stream" id="dcm2niix-wasm" data-gz="1">` (it has no `data-name`, so the Pyodide
asset reader ignores it). On the first conversion the page decodes and gunzips it (`src/shell/dcm2niix-wasm.ts`) and sends
each dcm2niix worker its own copy in the `run` message; the worker passes it to the Emscripten glue as `wasmBinary`.
The glue then fetches nothing. dicom-util lets Vite inline the wasm as a `data:` URL that the glue `fetch`es; here that
fetch would be blocked by the CSP (no `connect-src`, so `default-src 'none'`), and `noInlinedWasm` would fail the build
on the `data:application/wasm`.

The glue still names its wasm with `new URL("dcm2niix.jpeg.wasm", import.meta.url)`, which makes Vite emit the inlined
copy. `classicDcm2niixGlue` (a worker-build plugin, like `classicPyodideAsm`) rewrites that one use to a plain string,
and the three other `import.meta.url` uses to a fixed URL (one is Node-only; one, `_scriptName`, is read on the worker branch but only to locate files, which `wasmBinary` makes unnecessary, as with Pyodide's); the build fails if the glue's count of uses changes. The
`@dcm2niix-glue` alias and the `__DCM2NIIX_VERSION__` define (read from the wasm's banner) are as in dicom-util.

**CSP: unchanged.** `noInlinedWasm` is unchanged too. A successful conversion is the proof that nothing was fetched:
with a fetch, the CSP would block it and the conversion would fail. The dcm2niix worker does not forward
`securitypolicyviolation` events (the Pyodide worker does), so the e2e test checks the page and the Pyodide worker, and
the conversions themselves.

The e2e test (`e2e/intake.test.mjs`) opens the repo fixtures `packages/fmri-qa-io/tests/fixtures/dicom-qa/` (36 files,
1 series) and `dicom/` (2 series, 8 DICOM files and one `generate.py` that is skipped as not DICOM) through the file
input, and a `.zip` of `dicom-qa` built in the test. It runs the QA series and requires the outputs to be exactly
one `.nii.gz` and one `.json` whose dcm2niix names (the row's `data-dcm2niix-files`), decompressed NIfTI bytes and
sidecar equal what native dcm2niix writes for the same series (`fmriqa_io.import_dicom(..., names="dcm2niix")`, run in
the test's setup with `uv run python`). It then cancels the run and reads the files through the run table's download
buttons (the init script captures `a[download]` blob downloads into `window.__downloads`), under the dcm2niix name or
the QA one (the run names them as soon as Python is ready). It checks the datatype is an integer type, `scl_slope` is 1, and the sidecar has no `PatientName` or
`PatientID`. Its last test waits for Python to be ready and checks that the page and the Pyodide worker saw no CSP
violation or refused fetch and that no request left `file:`, `data:` and `blob:`.

## Runs

"Run QA on selected" runs the selected series. The state is a pure reducer, `src/core/run.ts` (unit-tested in
`test/unit/run.test.ts`). `src/shell/drive.ts` is the sequence, with no DOM (unit-tested with a fake Python in
`test/unit/drive.test.ts`), and `src/shell/run.ts` wires it to the page.

1. Each series is converted in turn (`runOne`). A series is `queued`, `converting`, then `converted`, `failed` or
   `cancelled`. A converted series gives one result per NIfTI: the `.nii.gz` with its `<stem>.json` sidecar and any other
   `<stem>.*` file as a companion, grouped as `fmriqa_io`'s `filing.plan_names` does. A file that belongs to no NIfTI
   is dropped, as the native import drops it.
2. **dcm2niix's `-w 2` suffix.** Native dcm2niix converts a study in one go, and when a series' NIfTI name is taken it
   writes the first free of `<stem>a` .. `<stem>y`, and fails the series when none is ("Too many NIFTI images with the
   name"; `nii_createFilename` in `console/nii_dicom_batch.cpp`, which checks only for an existing NIfTI; its loop
   assigns `<stem>z` last without checking it, so `z` is never used). Each of the
   page's workers starts with an empty `/out`, so the run applies the same rule as each series converts, against the
   NIfTIs of the series before it, renaming the NIfTI and every file of its stem together. Each row keeps the names
   dcm2niix gave (`data-dcm2niix-files`). Which of two clashing series gets the suffix follows the page's (tree) order,
   which need not be dcm2niix's.
3. Once Python is ready, one `names_json` call names every output of the run. Only the sidecars' bytes are sent; every
   other file goes as empty bytes. A Python that did not start and a `names_json` that raised (a `NameCollisionError`,
   as the native import refuses) each fail every result of the run, which keeps its dcm2niix names.
4. Each result is then analyzed with `analyze_json`, one at a time. A result is `naming`, `waiting-for-python`,
   `analyzing`, then `done` or `failed`. A failure is either Python's own (`data-stage` says where) or anything else: a
   rejected call, which is how a crashed worker shows, fails that result with the reason.

The page is `working` for the whole run, so nothing else can be opened meanwhile. Cancel aborts the conversion in
progress (dcm2niix can stop) and lets an analysis in progress finish (Python cannot) and keep its report; nothing new
starts, queued series are cancelled and the results not yet analyzing fail as cancelled. An unexpected error ends the
run the same way, with its reason in place of "cancelled". A new run replaces the old one, and so does opening
new DICOM: the results, their bytes and the preview are cleared as the open starts.

**The table** (`src/shell/ui/results.ts`, rebuilt on every change, giving the focused button back) has one row per
result, `#results-body tr.result[data-series][data-stem][data-status][data-dcm2niix-files]` with `data-reason` and
`data-stage` on a failure, and one `tr.job` row for a series that gave no NIfTI. What can be downloaded, from a result's
row (`button[data-action]`), is exactly: the NIfTI (`nifti`), the sidecar when there is one (`sidecar`), each companion
(`companion`), under their current names whatever happened to Python, and once done the report page
(`html`, `<stem>.html`) and the record (`record`, `<stem>.qa.json`), plus, once the result has settled, the whole folder
(`zip`, `<stem>.zip`, below). Single files go through `src/shell/download.ts`.

**The record file.** JSON from Python is never re-serialized in JS, which would turn `2.0` into `2`. `analyze_json`
therefore also returns `record_document_json`: the document `fmri-qa --json` prints for that one scan
(`schema_version`, `config`, `requested`, `scans`, `errors`; indent 2 and a closing newline), and the page saves that
string as `<stem>.qa.json`.

**ZIPs.** Once the run has settled, a row's Zip and "Download all (.zip)" (`#download-all`, enabled when the run has
settled and has at least one result; both use `aria-disabled`, so a button keeps its focus while a ZIP is written) write a ZIP through `src/shell/zip-sink.ts`'s `saveZip`: streamed through the save
dialog where the browser has one, else built as a Blob. The page is `working` meanwhile; the progress bar counts the
bytes and Cancel stops the write. The layouts are `src/core/bundle.ts`:

- `<stem>.zip`, one result: `<stem>/` holding `<stem>.nii.gz`, `<stem>.json` when there is a sidecar, any companions,
  and once done `<stem>.html` and `<stem>.qa.json`. That is the launcher's series directory without `.qa.nc`. A result
  that failed has its NIfTI, sidecar and companions, under their current names: the QA name, or dcm2niix's when naming
  never ran.
- `fmri-qa-YYYYMMDD-HHMM.zip` (local time of the click), the run: `fmri-qa.json` at the top, then every result's folder
  in run order. Two results with one stem (possible after a naming fallback) cannot share a folder: the first keeps
  `<stem>/`, the next takes the lowest `<stem>-2/`, `<stem>-3/`, ... that no stem already is; the files inside keep
  their names. No folder is named `fmri-qa.json`.

Every entry is stamped with the time of the click; the bytes are the single downloads' (text as UTF-8), stored
uncompressed (client-zip does not compress; `.nii.gz` already is).

**fmri-qa.json** is the batch envelope `fmri-qa --json` prints (indent 2, a closing newline), written by Python's
`document_json`. The page never builds or re-serializes a record: `analyze_json` also returns `result_json`, the result
without its page or warnings (`kind`, `stem` and `record`, or `kind`, `stem`, `stage` and `reason`), and the page keeps
that string verbatim per result and hands the list back. A result that failed where Python never saw it (Python did not
start or crashed, Cancel, naming failed) is handed over as `{"kind": "error", "stem", "reason"}` with the page's reason,
strings only; it is `requested` and listed in `errors` like Python's own failures. A series that gave no NIfTI has no stem
and is left out of the envelope (its row shows why). `requested` lists `<stem>.nii.gz` per result, so two results with
one stem are listed twice, as Python would. When Python has not started, failed to start, or fails the call, the run's
ZIP is still written, with every folder and no `fmri-qa.json`, and the outcome line says why.

**The preview** is `<iframe id="preview" sandbox="" srcdoc>`: no `allow-scripts`, no `allow-same-origin`, so the report
runs no script and has an opaque origin. It inherits the page's CSP, which its inline styles and `data:` images fit. A
violation inside it would not be seen by the e2e tests: the page's listener does not hear the iframe's document.

`e2e/run.test.mjs` runs both fixtures from `file://` and compares the page with `test/fixtures/expected.json`, which
`scripts/web_expected.py` writes from a native run (`import_dicom` with native dcm2niix, then `name_outputs` and
`analyze_series`, as `packages/fmri-qa-web/tests/test_launcher_parity.py` checks against the launcher).
`packages/fmri-qa-web/tests/test_expected.py` fails when the file is stale, comparing numbers within a relative 1e-9 so
that a different CPU's last bit does not (regenerate it with `uv run python scripts/web_expected.py`). `dicom-qa/` must
give the native stem and record (numbers within a relative 1e-9, everything else exact, null included; in the
`.qa.json`, `scans[0]` and the schema version), a `<title>` naming the stem, no `<script` in the report, the inert
preview and every download under its QA name. Both series of `dicom/`, two volumes each, must fail at `analyze` with the
native frame-count reason. For each fixture, a row's ZIP and the run's ZIP are unzipped in node and must hold exactly
the layout's entries (read in order from the central directory, so a duplicate name fails) with the single downloads' bytes (NIfTI, sidecar, report, `.qa.json`), and `fmri-qa.json` the
contract's schema version, every result in `requested`, the native records in `scans` (within 1e-9) or the native
reasons in `errors`. In Chrome they must be written through a fake save dialog (`e2e/init-hooks.js`, `fakePicker`), in
Firefox, which has none, through the Blob path. Rows are matched by `data-stem`. The no-violation, no-refusal and no-request checks cover the
whole flow, in the page and the Pyodide worker (not inside the preview, as above).

## Notices

`web/THIRD_PARTY_NOTICES.md` holds the licence texts of everything in the page: Pyodide (MPL-2.0, with the two files
the build modifies, each change described exactly), CPython, the libraries in `pyodide.asm.wasm`, Emscripten, every wheel,
fmri-qa itself, dcm2niix and the npm packages. `scripts/web_notices.py` writes it from what is bundled:

- each wheel's section from the wheel itself: every licence file it ships, each text once, and its licence metadata;
- the hand-kept texts in `web/notices/` for what the wheels and npm packages do not ship. These are the runtime
  (Pyodide's MPL text, CPython, the libraries Pyodide links, Emscripten), dcm2niix (from dicom-util's notices), and
  per-wheel supplements for libraries Pyodide's builds link in (scipy's OpenBLAS, Pillow's image libraries,
  matplotlib's Agg, qhull, FreeType and fonts). Each starts with the version it was verified for; a supplement also
  names the Pyodide and Emscripten whose build it describes, so a Pyodide upgrade fails every one until it is checked
  again. `web/notices/README.md` records how each was verified. The script fails, naming the component, when a bundled
  version no longer matches, when anything bundled has no licence text, or on a file in `web/notices/` it does not read;
- the npm packages' own LICENSE files. The build (`scripts/vite-notices.mjs`) fails unless the npm packages with code
  in the page, read from the bundler's module list for the page and both workers, are exactly `package.json`'s
  `dependencies`.

The file is committed and reviewed like code. The build only checks it: `scripts/vite-notices.mjs` runs
`scripts/web_notices.py --check` before bundling, so `make web` and a bare `npm run build` both fail if it is stale.
After changing the vendored set or the npm dependencies, run `make web-notices`, check that the diff is right, and
commit it. `packages/fmri-qa-web/tests/test_notices.py` checks the same in `pytest`; it skips when `web/vendor/` or
`web/node_modules/` is missing. `scripts/tests/test_web_notices_pins.py` needs neither: it checks that the committed file
has a heading for each npm dependency at its pinned version, and states the `pyodide.asm.mjs` replacement that
`vite.config.mjs` applies.

The page embeds the file as one inert, gzipped, base64 block (`#notices-data`). It is about 350 KB as text and 73 KB
gzipped, over the size at which it would be inlined plainly. `src/shell/about.ts` unpacks it with `DecompressionStream`
the first time "About & licences" is opened, so the CSP needs nothing new. `e2e/about.test.mjs` checks that nothing is
unpacked before then, opens the section in Chrome and Firefox and checks the text is the file's.

**If you pass `fmri-qa.html` on, keep the "About & licences" footer, or ship `THIRD_PARTY_NOTICES.md` next to it.**
Many of the bundled licences require their notices to go with every copy.

setuptools is left out of the page (`EXCLUDED` in `scripts/web_vendor.py`, also removed from the vendored lock).
Pyodide's lock lists it under networkx, but nothing bundled needs it, and it vendors autocommand, which is LGPL-3.0.

## Boot timings

Measured by `make web-e2e` on the development machine (headless, `file://`). Each stage is milliseconds since the
worker began the boot, reported when the stage ends:

| Browser | decode | runtime | packages | wheels | import (= ready) | `analyze_json`, 32x32x3x40 phantom |
|---|---|---|---|---|---|---|
| Chrome 149 | 409 | 12 886 | 29 302 | 29 951 | 55 801 | 13.4 s |
| Firefox 159 | 537 | 10 304 | 23 858 | 24 719 | 54 641 | 16.0 s |
| WebKit 27.2 (Playwright) | 368 | 8 657 | 21 022 | 21 750 | 46 615 | 13.6 s |

From `goto` to `ready`, the wall-clock time was 61 s in Chrome, 57 s in Firefox and 59 s in WebKit. Earlier runs
varied by a few seconds; for example, Chrome reached `ready` at 48.1 s on another run. That includes parsing
the 67 MB page. The `analyze_json` time is the first call, which includes the first report render (matplotlib). The SNR
matched native CPython within the test's 1e-9 relative tolerance in all three browsers.

Most of the time goes to the `import` stage, which imports fmriqa, scipy, scikit-image, nibabel and matplotlib inside
Pyodide, and to `packages`, which unpacks about 50 MB of wheels. Decoding the embedded base64 takes under a second.

Page size: 67.7 MB (49.8 MB gzipped); step 5 added 0.6 MB (the wasm, gzipped, is about 0.4 MB of that).

## WebKit

`E2E_BROWSERS=webkit make web-e2e` passes every boot test and every intake test (12 of 12, step 5), the same as Chrome and
Firefox: the dcm2niix conversion of the QA series, from files and from a .zip, gives native dcm2niix's bytes there too. It needed two fixes, both described under
"Boot path": gunzip without a `Blob`, and pyodide.asm.mjs bundled into the worker instead of loaded from a `blob:` URL.
It runs in Playwright's WebKit build on Linux, which is not Safari on macOS, so that remains untested. It is left out of
the default `E2E_BROWSERS` only to keep `make web-e2e` at two browsers, as this step's acceptance asks.

## Limits

**Memory.** Series are processed one at a time, so the page holds one series' DICOM, NIfTI and report at once, not the
whole study. dcm2niix runs in a fresh worker per series (a 2 GB WebAssembly heap) and Python runs in its own worker
(Pyodide's heap grows as needed, up to the 32-bit WebAssembly limit). The browser may still share renderer memory between
them. Files are read on the main thread, one at a time, and transferred. Downloads: where the browser has a save dialog
(`showSaveFilePicker`) the ZIP is streamed to disk and memory stays flat. Elsewhere (Firefox, Safari) it is built as a
Blob in memory, and `zip-sink.ts` asks first when the archive is predicted to exceed 2 GB (`BLOB_WARN_BYTES`, 2 x 1024^3
bytes) because the whole archive is buffered and needs about that much free disk space when saving.

**Out of memory.** A wasm abort cannot be caught and resumed. If dcm2niix runs out of memory, that series' result fails
with "dcm2niix crashed, probably out of memory (the series may be too large)" and the other series are unaffected (its
worker is terminated). If Python's worker dies, the page says "Python stopped. Reload the page to start it again." and
the results so far stay on screen until the reload. Memory use is not measured; see "Known gaps".

**Size budget.** `dist/fmri-qa.html` must be at most 72 MB, where MB is 1 000 000 bytes (every size in this file is in
that unit). `web/scripts/size-check.mjs` runs after `vite build` in `npm run build`, so `make web` fails over the budget.
It prints each embedded asset (the `<script type="application/octet-stream">` blocks: every Pyodide asset by name,
`dcm2niix-wasm`, `notices-data`, and the JS), the total and the headroom. The page is 66.84 MB, 5.16 MB under. The unit tests
for its parsing and arithmetic are `test/unit/size-check.test.ts`. The budget is `BUDGET_BYTES` in the script; raise it
there and here together, with a reason.

**Browsers.** Chrome and Firefox are tested on every `make web-e2e` and in CI: locally Chrome 149 and Firefox 159; in CI the
runner's current Chrome (unpinned) and Firefox `FIREFOX_BUILD` (pinned). WebKit is opt-in
(`E2E_BROWSERS=webkit`, see "WebKit"): it passes in Playwright's Linux build, which is not Safari on macOS, so Safari is
untested. An older browser than those, or a real hospital machine, has not been tried.

**CI.** The `web` job in `.github/workflows/ci.yml` runs `make web-check`, `make web`, the notices and script tests with
`web/vendor` present, and the e2e tests in Chrome (the runner's) and Firefox (installed with
`npx browsers install firefox@<build> --path ~/.cache/dicom-util/browsers` from `web/`, which is puppeteer's
downloader, and cached). It uploads the page as an artifact on a tag.

## Known gaps

- **Driver gaps** (as in dicom-util): puppeteer reports no requests from a worker, and its Firefox driver reports no
  `file://` requests. The "only file:, data: and blob:" check is therefore vacuous for http(s) in Firefox. The fetch
  shim's refusal report covers the worker in every browser.
- The boot takes about a minute, and memory use is not measured. Neither has been tried on a real hospital machine or an
  older browser.
- matplotlib and its dependencies (about 13 MB) come only from networkx's lock-file dependency (see
  `notes/pyodide-spike/README.md`). fmri-qa-report needs matplotlib anyway, so the closure keeps it.
- The page cannot be developed with `vite dev`, because the dev server has no embedded assets. It says so and fails the
  boot. Use `make web`.
