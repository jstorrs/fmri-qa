import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import { viteSingleFile } from 'vite-plugin-singlefile';
import { buildInfo } from './scripts/vite-build-info.mjs';
import { classicDcm2niixGlue, dcm2niixVersion, dcm2niixWasmBlock } from './scripts/vite-dcm2niix.mjs';
import { bundledPackages, noticesBlock } from './scripts/vite-notices.mjs';
import { classicPyodideAsm, noInlinedWasm, pyodideAssets } from './scripts/vite-pyodide.mjs';

/**
 * Pyodide's and dcm2niix's own files draw warnings that are known and harmless here: Node-only branches import `node:*` modules (Vite
 * stubs them; the branches never run in a browser), and Emscripten's EM_ASM and `emscripten_run_script` paths use
 * direct `eval` (never reached: the page's CSP has no 'unsafe-eval', and e2e/boot.test.mjs fails on a violation).
 * Only those, from node_modules/pyodide and node_modules/@niivue/dcm2niix, are dropped, so a new warning still shows.
 */
const PYODIDE_FILE = /\/node_modules\/(pyodide|@niivue\/dcm2niix)\//;
const quietPyodide = (level, log, handler) => {
  const fromPyodide = PYODIDE_FILE.test(log.id ?? '') || PYODIDE_FILE.test(log.message);
  const known = log.code === 'EVAL' || log.code === 'COMMONJS_VARIABLE_IN_ESM' || /externalized for browser compatibility/.test(log.message);
  if (level === 'warn' && fromPyodide && known) return;
  handler(level, log);
};

/** The page is shipped as dist/fmri-qa.html, the name a user sees in their downloads. */
const PAGE = 'fmri-qa.html';
const pageName = () => ({
  name: 'page-name',
  apply: 'build',
  enforce: 'post',
  generateBundle(_, bundle) {
    const page = bundle['index.html'];
    if (!page) throw new Error('page-name: no index.html in the bundle');
    delete bundle['index.html'];
    this.emitFile({ type: 'asset', fileName: PAGE, source: page.source });
  },
});

const packages = bundledPackages(); // one record across the page build and its worker builds

export default defineConfig({
  define: { __DCM2NIIX_VERSION__: JSON.stringify(dcm2niixVersion()) },
  plugins: [buildInfo(), viteSingleFile(), pyodideAssets(), dcm2niixWasmBlock(), noticesBlock(), noInlinedWasm(), packages.page, pageName()],
  build: {
    modulePreload: { polyfill: false }, // useless in a single-file build
    rolldownOptions: { onLog: quietPyodide }, // Vite routes the worker build's logs through this one too
  },
  resolve: {
    alias: {
      '@dcm2niix-glue': fileURLToPath(new URL('./node_modules/@niivue/dcm2niix/dist/dcm2niix.jpeg.js', import.meta.url)),
    },
  },
  // The Pyodide and dcm2niix workers are classic: ES-module blob workers fail on file:// in Chrome (web/README.md, "Boot path").
  // Must match ASSET_BASE in src/core/asset-fetch.ts.
  worker: {
    format: 'iife',
    plugins: () => [classicPyodideAsm('https://pyodide.invalid/pyodide.asm.mjs'), classicDcm2niixGlue(), packages.worker],
    rolldownOptions: { output: { strict: true } }, // "use strict" at the top of the worker script
  },
  test: { include: ['test/unit/**/*.test.ts'], environment: 'node', testTimeout: 30_000 },
});
