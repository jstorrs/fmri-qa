# fmri-qa in the browser

One self-contained HTML file, `web/dist/fmri-qa.html`, that a user saves and double-clicks. It opens from `file://`
with no network and no install, and runs fmri-qa under [Pyodide](https://pyodide.org) 314.0.7 (CPython 3.14.2 in
WebAssembly). This step (step 4) proves the boot only: the page starts Python in a worker, imports `fmriqa_web`, shows
the boot stages, and answers bridge calls. DICOM intake, conversion, the series list, downloads and notices come later.

## Build

From the repo root:

| Command | What it does |
|---|---|
| `make web-vendor` | `npm ci` in `web/` (only when `package-lock.json` is newer than the install), then `uv run python scripts/web_vendor.py`: fills the gitignored `web/vendor/` (about 56 MB, downloaded once and cached) and writes `web/vendor/manifest.json` |
| `make web-check` | the same `npm ci` if needed, then `tsc --noEmit` for the app and the tests, then the vitest unit tests (`test/unit/`) |
| `make web` | `make web-vendor`, then `vite build` to `web/dist/fmri-qa.html` |
| `make web-e2e` | `make web`, then `node --test e2e/**/*.test.mjs` in Chrome and Firefox (`E2E_BROWSERS=chrome,firefox,webkit` to choose) |

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

Page size: 67.1 MB (49.4 MB gzipped).

## WebKit

`E2E_BROWSERS=webkit` passes every boot test, the same as Chrome and Firefox. It needed two fixes, both described under
"Boot path": gunzip without a `Blob`, and pyodide.asm.mjs bundled into the worker instead of loaded from a `blob:` URL.
It runs in Playwright's WebKit build on Linux, which is not Safari on macOS, so that remains untested. It is left out of
the default `E2E_BROWSERS` only to keep `make web-e2e` at two browsers, as this step's acceptance asks.

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
