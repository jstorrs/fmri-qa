/**
 * The page: boots Python in its worker in the background (the DOM data attributes are what e2e/boot.test.mjs reads) while
 * the user opens DICOM, looks at the series tree and converts a selection with dcm2niix (e2e/intake.test.mjs).
 */
import { mountConversions } from './shell/conversions';
import { mountIntake } from './shell/intake-ui';
import { BRIDGE_FNS, type BridgeFn } from './shell/pyodide-protocol';
import { startPython, type BootEvent } from './shell/python';

const $ = (id: string): HTMLElement => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} is missing from the page`);
  return el;
};

const status = $('python-status');
const stages = $('python-stages');
const diagnostics = { refused: [] as string[], violations: [] as string[] };

const show = (event: BootEvent): void => {
  switch (event.type) {
    case 'stage': {
      status.dataset.stage = event.name;
      status.dataset.elapsedMs = String(Math.round(event.elapsedMs));
      const row = document.createElement('li');
      row.dataset.stage = event.name;
      row.dataset.elapsedMs = String(Math.round(event.elapsedMs));
      row.textContent = `${event.name}: ${(event.elapsedMs / 1000).toFixed(1)} s`;
      stages.append(row);
      return;
    }
    case 'ready':
      $('python-contract').textContent = event.contract;
      status.textContent = 'Python is ready.';
      document.body.dataset.python = 'ready';
      return;
    case 'failed':
      $('python-error').textContent = event.message;
      status.textContent = 'Python failed to start.';
      document.body.dataset.python = 'failed';
      return;
    case 'crashed':
      $('python-error').textContent = event.message;
      status.textContent = 'Python stopped. Reload the page to start it again.';
      document.body.dataset.python = 'crashed';
      return;
    case 'refused':
      diagnostics.refused.push(event.url);
      return;
    case 'violation':
      diagnostics.violations.push(`${event.directive} ${event.blocked}`);
      return;
  }
};

const python = startPython(show);
python.ready.catch(() => {}); // reported through `show`

const conversions = mountConversions(mountIntake(), { keepOutputs: (window as { __e2eKeepOutputs?: boolean }).__e2eKeepOutputs === true });

/** Bytes as base64, for a test to read across the driver. */
const base64 = (buf: ArrayBuffer): string => {
  let binary = '';
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(binary);
};

/** Test-facing: the e2e tests run one bridge call, read the worker's diagnostics and the last conversion's outputs. Not an API of the page. */
const testHooks = {
  call: (fn: BridgeFn, args: readonly unknown[]): Promise<string> => {
    if (!BRIDGE_FNS.includes(fn)) return Promise.reject(new Error(`unknown bridge function ${String(fn)}`));
    return python.call(fn, args);
  },
  diagnostics: () => structuredClone(diagnostics),
  output: (seriesUid: string, name: string): string | null => {
    const buf = conversions.output(seriesUid, name);
    return buf === undefined ? null : base64(buf);
  },
};
declare global {
  interface Window {
    __fmriqa: typeof testHooks;
  }
}
window.__fmriqa = testHooks;
