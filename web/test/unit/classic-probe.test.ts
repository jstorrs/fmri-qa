// Pyodide's classic-worker probe is an internal. src/shell/classic-worker-probe.ts answers it by its exact URL, so a
// Pyodide upgrade that changes the probe must fail here, fast, not as a boot failure an e2e run away.
import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import { CLASSIC_WORKER_PROBE } from '../../src/core/classic-probe';

const HINT = 'Pyodide changed its classic-worker probe; see web/README.md, "The classic-worker probe".';
const PROBE_CALL = /importScripts\(("[^"]*")\)/g;

describe.each(['pyodide.mjs', 'pyodide.asm.mjs'])('%s', (file) => {
  test('probes with importScripts(CLASSIC_WORKER_PROBE) exactly once', () => {
    const source = readFileSync(new URL(`../../node_modules/pyodide/${file}`, import.meta.url), 'utf8');
    const calls = [...source.matchAll(PROBE_CALL)].map((m) => JSON.parse(m[1]!) as string);
    expect(calls, HINT).toEqual([CLASSIC_WORKER_PROBE]);
    expect(source.split('Classic web workers are not supported').length - 1, HINT).toBe(1);
  });
});
