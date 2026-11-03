/**
 * Where a `fetch` inside the Pyodide worker goes. Pure: the worker's shim (src/shell/pyodide.worker.ts) serves the
 * route this picks. Pyodide is loaded with `indexURL` and `packageBaseUrl` both `ASSET_BASE`, so every file it wants is
 * requested as `ASSET_BASE + <file name>`. `.invalid` never resolves (RFC 2606), so a request that slipped past the shim
 * could not reach anything either. Nothing else is ever fetched, `data:` and `blob:` included: the page's CSP has no
 * `connect-src`, so the browser's own fetch is never called.
 */

export const ASSET_BASE = 'https://pyodide.invalid/';

export type FetchRoute = { readonly kind: 'asset'; readonly name: string } | { readonly kind: 'refused' };

const REFUSED: FetchRoute = { kind: 'refused' };

/**
 * Route `url`: an embedded asset by name, or refused (anything else, including a name `files` does not hold). `files`
 * is read at the moment of the request, so a map emptied after the boot refuses every later fetch.
 */
export const routeFetch = (url: string, files: { has(name: string): boolean }): FetchRoute => {
  if (!url.startsWith(ASSET_BASE)) return REFUSED;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return REFUSED;
  }
  if (parsed.search !== '' || parsed.hash !== '') return REFUSED;
  let name: string;
  try {
    name = decodeURIComponent(parsed.pathname.slice(1));
  } catch {
    return REFUSED;
  }
  return files.has(name) ? { kind: 'asset', name } : REFUSED;
};

const TYPES: Readonly<Record<string, string>> = {
  wasm: 'application/wasm', // WebAssembly.instantiateStreaming refuses any other type
  json: 'application/json',
  zip: 'application/zip',
  whl: 'application/zip',
};

/** The Content-Type the shim serves an asset with. */
export const contentType = (name: string): string => TYPES[name.slice(name.lastIndexOf('.') + 1)] ?? 'application/octet-stream';
