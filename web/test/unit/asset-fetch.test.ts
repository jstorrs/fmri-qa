import { describe, expect, test } from 'vitest';
import { ASSET_BASE, contentType, routeFetch } from '../../src/core/asset-fetch';

const NAMES = new Set(['pyodide.asm.wasm', 'python_stdlib.zip', 'numpy-2.4.6-cp314-cp314-pyemscripten_2026_0_wasm32.whl']);

describe('routeFetch', () => {
  // The forms Pyodide 314 was seen requesting in the boot (web/README.md): indexURL + file and packageBaseUrl + file.
  test.each(['pyodide.asm.wasm', 'python_stdlib.zip', 'numpy-2.4.6-cp314-cp314-pyemscripten_2026_0_wasm32.whl'])('serves %s', (name) => {
    expect(routeFetch(ASSET_BASE + name, NAMES)).toEqual({ kind: 'asset', name });
  });

  test('decodes a percent-encoded name', () => {
    expect(routeFetch(`${ASSET_BASE}python%5Fstdlib.zip`, NAMES)).toEqual({ kind: 'asset', name: 'python_stdlib.zip' });
  });

  test('refuses a name once the map no longer holds it (after the boot)', () => {
    const files = new Map([['python_stdlib.zip', new Uint8Array(1)]]);
    expect(routeFetch(`${ASSET_BASE}python_stdlib.zip`, files)).toEqual({ kind: 'asset', name: 'python_stdlib.zip' });
    files.clear();
    expect(routeFetch(`${ASSET_BASE}python_stdlib.zip`, files)).toEqual({ kind: 'refused' });
  });

  test.each([
    'data:application/octet-stream;base64,AA==', // never fetched: the CSP has no connect-src
    'blob:null/0a1b',
    'https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.asm.wasm', // the CDN: never
    'https://pyodide.invalid/unknown.whl', // not embedded
    'https://pyodide.invalid/sub/pyodide.asm.wasm', // a path, not a name
    'https://pyodide.invalid/pyodide.asm.wasm?x=1',
    'https://pyodide.invalid/pyodide.asm.wasm#x',
    'https://pyodide.invalid/%E0%A4%A', // bad percent-encoding
    'http://pyodide.invalid/pyodide.asm.wasm',
    'file:///home/x/pyodide.asm.wasm',
    'pyodide.asm.wasm', // relative
    '',
  ])('refuses %s', (url) => {
    expect(routeFetch(url, NAMES)).toEqual({ kind: 'refused' });
  });
});

describe('contentType', () => {
  test.each([
    ['pyodide.asm.wasm', 'application/wasm'],
    ['pyodide-lock.json', 'application/json'],
    ['python_stdlib.zip', 'application/zip'],
    ['x-1-py3-none-any.whl', 'application/zip'],
    ['README', 'application/octet-stream'],
  ])('%s is %s', (name, type) => {
    expect(contentType(name)).toBe(type);
  });
});
