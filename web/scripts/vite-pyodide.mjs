// Embeds Pyodide and the wheels in the built page. scripts/web_vendor.py (at the repo root; `make web-vendor`) fills
// web/vendor/ and lists every file in web/vendor/manifest.json, in boot order. Each one goes into the page as an inert
// `<script type="application/octet-stream" data-name data-kind [data-gz]>` holding base64, gzipped first where the
// manifest says so; src/shell/python.ts reads them out and the worker decodes them. An inert element costs the HTML
// parser a scan of its text, where a JS string literal would be tokenised (dicom-util's PLAN.md, "Viewer").
import { createHash } from 'node:crypto';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const VENDOR = fileURLToPath(new URL('../vendor/', import.meta.url));
const MANIFEST = `${VENDOR}manifest.json`;

/** Read web/vendor/manifest.json; fail the build, naming the command, when it is missing. */
export const readManifest = () => {
  if (!existsSync(MANIFEST)) throw new Error(`${MANIFEST} is missing. Run \`make web-vendor\` at the repo root first.`);
  return JSON.parse(readFileSync(MANIFEST, 'utf8'));
};

/** One asset's block, its bytes checked against the manifest's sha256. */
const block = (asset) => {
  const bytes = readFileSync(VENDOR + asset.file);
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  if (sha256 !== asset.sha256) throw new Error(`web/vendor/${asset.file} has sha256 ${sha256}, the manifest says ${asset.sha256}. Run \`make web-vendor\`.`);
  const attrs = { type: 'application/octet-stream', 'data-name': asset.name, 'data-kind': asset.kind };
  if (asset.gzip) attrs['data-gz'] = '1';
  return { tag: 'script', attrs, children: (asset.gzip ? gzipSync(bytes, { level: 9 }) : bytes).toString('base64'), injectTo: 'body' };
};

export const pyodideAssets = () => ({
  name: 'pyodide-assets',
  apply: 'build',
  buildStart: () => void readManifest(), // fail before bundling, not after
  transformIndexHtml: { order: 'post', handler: () => readManifest().assets.map(block) },
});

/**
 * For the worker build: pyodide.asm.mjs (Pyodide's Emscripten module) is bundled into the classic worker instead of
 * loaded at run time, because WebKit refuses both `import()` and `importScripts()` of a `blob:` URL inside a worker on
 * file:// (web/README.md, "Boot path"). Vite would rewrite the module's `import.meta.url` for an iife worker by itself;
 * this rewrite runs first (`enforce: 'pre'`) for two reasons. Vite would take `new URL('pyodide.asm.wasm',
 * import.meta.url)` for an asset and inline the 9.6 MB wasm a second time (the wasm is embedded once, through the
 * manifest). And the script URL becomes a fixed one beside `indexURL` rather than the worker's `blob:` URL. None of the
 * three uses is reached in a browser with the settings `loadPyodide` passes: one is Node-only (`createRequire`), one
 * names the script (`_scriptName`, only read through `locateFile`, which Pyodide supplies) and one is the wasm fallback
 * that `locateFile` overrides. The build fails if the file was never transformed (the rewrite silently not applied).
 */
export const classicPyodideAsm = (scriptUrl) => {
  let transformed = false;
  return {
    name: 'classic-pyodide-asm',
    enforce: 'pre',
    transform(code, id) {
      if (!id.endsWith('/node_modules/pyodide/pyodide.asm.mjs')) return null;
      const uses = code.split('import.meta.url').length - 1;
      if (uses !== 3) throw new Error(`pyodide.asm.mjs has ${uses} uses of import.meta.url, not the 3 reviewed in scripts/vite-pyodide.mjs`);
      if (code.split('import.meta').length - 1 !== uses) throw new Error('pyodide.asm.mjs uses import.meta beyond import.meta.url');
      transformed = true;
      return { code: code.replaceAll('import.meta.url', JSON.stringify(scriptUrl)), map: null };
    },
    buildEnd(error) {
      if (!error && !transformed) throw new Error('classic-pyodide-asm: the worker build never loaded node_modules/pyodide/pyodide.asm.mjs');
    },
  };
};

/**
 * For the page: fail the build if any wasm was inlined as a `data:` URL. Every wasm reaches the page through the
 * manifest, as base64 in an inert block; a `data:application/wasm` means a copy slipped into a bundle as well.
 */
export const noInlinedWasm = () => ({
  name: 'no-inlined-wasm',
  apply: 'build',
  enforce: 'post',
  generateBundle(_, bundle) {
    for (const file of Object.values(bundle)) {
      const text = file.type === 'chunk' ? file.code : String(file.source);
      if (text.includes('data:application/wasm')) throw new Error(`${file.fileName} has a wasm inlined as a data: URL; see scripts/vite-pyodide.mjs`);
    }
  },
});
