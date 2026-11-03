/** Messages between the main thread and the Pyodide worker. Pure types plus two guards; no DOM. */
import { isEncodedAsset, type EncodedAsset } from '../core/assets';

/** The `fmriqa_web.bridge` functions the page calls. Each returns a JSON string, passed on verbatim. */
export type BridgeFn = 'analyze_json' | 'names_json' | 'document_json' | 'contract_json';
export const BRIDGE_FNS: readonly BridgeFn[] = ['analyze_json', 'names_json', 'document_json', 'contract_json'];

/** Boot stages, in order. Each is reported when it ends, with the milliseconds since the boot began. */
export type BootStage = 'decode' | 'runtime' | 'packages' | 'wheels' | 'import' | 'ready';
export const BOOT_STAGES: readonly BootStage[] = ['decode', 'runtime', 'packages', 'wheels', 'import', 'ready'];

/** Main thread to worker. `boot` once, first; `call` after `ready`. `args` are converted with `pyodide.toPy`. */
export type ToWorker =
  | { readonly type: 'boot'; readonly assets: readonly EncodedAsset[] }
  | { readonly type: 'call'; readonly id: number; readonly fn: BridgeFn; readonly args: readonly unknown[] };

export type FromWorker =
  | { readonly type: 'stage'; readonly name: BootStage; readonly elapsedMs: number }
  | { readonly type: 'ready'; readonly contract: string }
  | { readonly type: 'result'; readonly id: number; readonly value: string }
  /** `id` is absent for a boot failure or a message the worker could not read. */
  | { readonly type: 'error'; readonly id?: number; readonly message: string; readonly stack?: string }
  /** The fetch shim refused a request (the boot carries on; Pyodide reports the failure if it needed the file). */
  | { readonly type: 'refused'; readonly url: string }
  /** A `securitypolicyviolation` inside the worker. */
  | { readonly type: 'violation'; readonly directive: string; readonly blocked: string };

const isRecord = (x: unknown): x is Record<string, unknown> => typeof x === 'object' && x !== null;
const isId = (x: unknown): x is number => Number.isSafeInteger(x);
const isFn = (x: unknown): x is BridgeFn => BRIDGE_FNS.includes(x as BridgeFn);
const isStage = (x: unknown): x is BootStage => BOOT_STAGES.includes(x as BootStage);
const isOptionalString = (x: unknown): boolean => x === undefined || typeof x === 'string';

export const isToWorker = (x: unknown): x is ToWorker => {
  if (!isRecord(x)) return false;
  switch (x['type']) {
    case 'boot':
      return Array.isArray(x['assets']) && x['assets'].every(isEncodedAsset);
    case 'call':
      return isId(x['id']) && isFn(x['fn']) && Array.isArray(x['args']);
    default:
      return false;
  }
};

export const isFromWorker = (x: unknown): x is FromWorker => {
  if (!isRecord(x)) return false;
  switch (x['type']) {
    case 'stage':
      return isStage(x['name']) && typeof x['elapsedMs'] === 'number';
    case 'ready':
      return typeof x['contract'] === 'string';
    case 'result':
      return isId(x['id']) && typeof x['value'] === 'string';
    case 'error':
      return (x['id'] === undefined || isId(x['id'])) && typeof x['message'] === 'string' && isOptionalString(x['stack']);
    case 'refused':
      return typeof x['url'] === 'string';
    case 'violation':
      return typeof x['directive'] === 'string' && typeof x['blocked'] === 'string';
    default:
      return false;
  }
};
