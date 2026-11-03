/// <reference lib="webworker" />
/**
 * Pyodide 314 refuses to start in a classic worker: pyodide.mjs (and its copy inside pyodide.asm.mjs) probes with
 * `importScripts("data:text/javascript,")` and throws "Classic web workers are not supported" when the probe loads.
 * This worker has to be classic (an ES-module blob worker fails on file:// in Chrome), and Pyodide loads no script at
 * run time here: pyodide.asm.mjs is bundled into the worker (web/README.md, "Boot path"). So the probe is answered here,
 * as a module worker would answer it, before Pyodide's module body runs: src/shell/pyodide.worker.ts imports this
 * first. Without it the page's CSP happens to block the probe's `data:` URL, which gives the same answer but raises a
 * `securitypolicyviolation` on every boot.
 */
import { CLASSIC_WORKER_PROBE } from '../core/classic-probe';

declare const self: DedicatedWorkerGlobalScope;

const realImportScripts = self.importScripts.bind(self);
self.importScripts = (...urls: (string | URL)[]): void => {
  if (urls.length === 1 && String(urls[0]) === CLASSIC_WORKER_PROBE) throw new TypeError('importScripts is not available to Pyodide');
  realImportScripts(...urls);
};
