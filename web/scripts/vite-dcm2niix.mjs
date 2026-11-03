// dcm2niix's WebAssembly, delivered without a fetch. Three pieces:
//  - `dcm2niixVersion()`: the version string in the wasm's banner, for the `__DCM2NIIX_VERSION__` define.
//  - `dcm2niixWasmBlock()` (page): the wasm goes into the page as one inert, gzipped, base64 block (like the Pyodide
//    assets, scripts/vite-pyodide.mjs). The page decodes it and hands the bytes to each dcm2niix worker, which gives them
//    to the Emscripten glue as `wasmBinary`. Nothing is fetched, so the page's CSP needs no `connect-src` and no `data:`.
//  - `classicDcm2niixGlue()` (worker build): the glue names its wasm with `new URL("dcm2niix.jpeg.wasm", import.meta.url)`.
//    Vite takes that for an asset and inlines the wasm as a `data:` URL, a second copy that nothing may fetch. The rewrite
//    runs first and leaves a plain string.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const DIST = fileURLToPath(new URL('../node_modules/@niivue/dcm2niix/dist/', import.meta.url));
const WASM_FILE = 'dcm2niix.jpeg.wasm';

/** The `id` of the page's block; src/shell/dcm2niix-wasm.ts reads it. */
export const WASM_BLOCK_ID = 'dcm2niix-wasm';

const readWasm = () => readFileSync(`${DIST}${WASM_FILE}`);

/** The dcm2niix the wasm build reports (its banner string), so the version in a report cannot drift from the dependency. */
export const dcm2niixVersion = () => {
  const match = /dcm2niix (v\d+\.\d+\.\d{8}\w*)/.exec(readWasm().toString('latin1'));
  if (!match) throw new Error(`No "dcm2niix vX.Y.YYYYMMDD" banner found in ${WASM_FILE}; update the pattern in scripts/vite-dcm2niix.mjs.`);
  return match[1];
};

export const dcm2niixWasmBlock = () => ({
  name: 'dcm2niix-wasm-block',
  apply: 'build',
  transformIndexHtml: {
    order: 'post',
    handler: () => [
      {
        tag: 'script',
        attrs: { type: 'application/octet-stream', id: WASM_BLOCK_ID, 'data-gz': '1' },
        children: gzipSync(readWasm(), { level: 9 }).toString('base64'),
        injectTo: 'body',
      },
    ],
  },
});

/**
 * Worker build: replace the glue's `import.meta.url` uses (reviewed: the wasm URL, and three others: one Node-only, one
 * `_scriptName` that the worker branch reads but only to locate files, which `wasmBinary` makes unnecessary). None is
 * reached in a browser with `wasmBinary` set.
 */
export const classicDcm2niixGlue = () => {
  let transformed = false;
  return {
    name: 'classic-dcm2niix-glue',
    enforce: 'pre',
    transform(code, id) {
      if (!id.endsWith('/node_modules/@niivue/dcm2niix/dist/dcm2niix.jpeg.js')) return null;
      const assetUrl = `new URL("${WASM_FILE}",import.meta.url).href`;
      const uses = code.split('import.meta.url').length - 1;
      if (uses !== 4 || code.split(assetUrl).length - 1 !== 1) throw new Error(`dcm2niix.jpeg.js no longer has the 4 uses of import.meta.url (one of them the wasm URL) reviewed in scripts/vite-dcm2niix.mjs; found ${uses}`);
      if (code.split('import.meta').length - 1 !== uses) throw new Error('dcm2niix.jpeg.js uses import.meta beyond import.meta.url');
      transformed = true;
      // The wasm URL is only a name: with `wasmBinary` set the glue never fetches it. The other three are not reached (see above).
      return { code: code.replace(assetUrl, JSON.stringify(WASM_FILE)).replaceAll('import.meta.url', '"https://dcm2niix.invalid/dcm2niix.jpeg.js"'), map: null };
    },
    buildEnd(error) {
      // The worker plugins list is shared by every worker build; only the dcm2niix worker's build must have loaded the glue.
      const isDcm2niixWorker = [...this.getModuleIds()].some((id) => id.endsWith('/src/shell/dcm2niix.worker.ts'));
      if (!error && isDcm2niixWorker && !transformed) throw new Error('classic-dcm2niix-glue: the dcm2niix worker build never loaded the glue');
    },
  };
};
