/**
 * The URL Pyodide 314 probes a worker with: `importScripts(CLASSIC_WORKER_PROBE)` loading means a classic worker, which
 * it refuses. src/shell/classic-worker-probe.ts answers it; test/unit/classic-probe.test.ts checks Pyodide still probes
 * with exactly this (web/README.md, "The classic-worker probe"). Pure.
 */
export const CLASSIC_WORKER_PROBE = 'data:text/javascript,';
