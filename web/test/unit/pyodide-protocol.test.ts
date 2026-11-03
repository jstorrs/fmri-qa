import { describe, expect, test } from 'vitest';
import { isFromWorker, isToWorker } from '../../src/shell/pyodide-protocol';

const asset = { name: 'x.whl', kind: 'wheel', gzip: false, base64: 'AA==' };

describe('isToWorker', () => {
  test.each([
    { type: 'boot', assets: [asset] },
    { type: 'boot', assets: [] },
    { type: 'call', id: 0, fn: 'analyze_json', args: [new Uint8Array(1), null, 'scan'] },
    { type: 'call', id: 3, fn: 'contract_json', args: [] },
  ])('accepts %j', (m) => {
    expect(isToWorker(m)).toBe(true);
  });

  test.each([
    null,
    { type: 'boot' },
    { type: 'boot', assets: [{ ...asset, kind: 'sdist' }] },
    { type: 'call', id: 0, fn: 'eval', args: [] },
    { type: 'call', id: 1.5, fn: 'contract_json', args: [] },
    { type: 'call', id: 0, fn: 'contract_json' },
    { type: 'stage', name: 'decode', elapsedMs: 1 },
  ])('refuses %j', (m) => {
    expect(isToWorker(m)).toBe(false);
  });
});

describe('isFromWorker', () => {
  test.each([
    { type: 'stage', name: 'runtime', elapsedMs: 9400.5 },
    { type: 'ready', contract: '{}' },
    { type: 'result', id: 2, value: '{"kind": "report"}' },
    { type: 'error', message: 'boot failed' },
    { type: 'error', id: 2, message: 'TypeError', stack: 'at ...' },
    { type: 'refused', url: 'https://example.org/' },
    { type: 'violation', directive: 'script-src-elem', blocked: 'data' },
  ])('accepts %j', (m) => {
    expect(isFromWorker(m)).toBe(true);
  });

  test.each([
    undefined,
    { type: 'stage', name: 'warmup', elapsedMs: 1 },
    { type: 'stage', name: 'decode' },
    { type: 'ready', contract: {} },
    { type: 'result', id: 2, value: { kind: 'report' } },
    { type: 'error', id: 'x', message: 'm' },
    { type: 'error', message: 'm', stack: 3 },
    { type: 'refused' },
    { type: 'violation', directive: 'x' },
    { type: 'boot', assets: [] },
  ])('refuses %j', (m) => {
    expect(isFromWorker(m)).toBe(false);
  });
});
