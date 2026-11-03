/** Messages between the main thread and the dcm2niix worker. Pure types plus two guards; no DOM. */

export interface WorkerFile {
  readonly name: string;
  readonly buf: ArrayBuffer;
}

/** Main thread to worker. `args` exclude `-o` and the input directory: the worker appends `-o /out /in`. */
export interface RunMessage {
  readonly type: 'run';
  readonly args: readonly string[];
  readonly inputs: readonly WorkerFile[];
  /** dcm2niix.wasm, handed to the glue as `wasmBinary` (the page's CSP allows no fetch). */
  readonly wasm: ArrayBuffer;
}
export type ToWorker = RunMessage;

export type LogStream = 'stdout' | 'stderr';

export type FromWorker =
  | { readonly type: 'log'; readonly line: string; readonly stream: LogStream }
  | { readonly type: 'done'; readonly exitCode: number; readonly outputs: readonly WorkerFile[] }
  | { readonly type: 'error'; readonly message: string };

const isRecord = (x: unknown): x is Record<string, unknown> => typeof x === 'object' && x !== null;
const isWorkerFile = (x: unknown): x is WorkerFile =>
  isRecord(x) && typeof x['name'] === 'string' && x['buf'] instanceof ArrayBuffer;
const isStringArray = (x: unknown): x is string[] => Array.isArray(x) && x.every((a) => typeof a === 'string');

export const isToWorker = (x: unknown): x is ToWorker =>
  isRecord(x) &&
  x['type'] === 'run' &&
  isStringArray(x['args']) &&
  x['wasm'] instanceof ArrayBuffer &&
  Array.isArray(x['inputs']) &&
  x['inputs'].every(isWorkerFile);

export const isFromWorker = (x: unknown): x is FromWorker => {
  if (!isRecord(x)) return false;
  switch (x['type']) {
    case 'log':
      return typeof x['line'] === 'string' && (x['stream'] === 'stdout' || x['stream'] === 'stderr');
    case 'done':
      return typeof x['exitCode'] === 'number' && Array.isArray(x['outputs']) && x['outputs'].every(isWorkerFile);
    case 'error':
      return typeof x['message'] === 'string';
    default:
      return false;
  }
};
