/**
 * The main thread's side of the Pyodide worker: reads the embedded assets out of the page, boots the worker with them,
 * and turns `call`s into promises of the bridge's JSON strings.
 */
import { parseEncodedAsset, type EncodedAsset } from '../core/assets';
import { isFromWorker, type BootStage, type BridgeFn, type FromWorker, type ToWorker } from './pyodide-protocol';
import PyodideWorker from './pyodide.worker.ts?worker&inline';

export type BootEvent =
  | { readonly type: 'stage'; readonly name: BootStage; readonly elapsedMs: number }
  | { readonly type: 'ready'; readonly contract: string }
  /** The boot did not reach `ready`. */
  | { readonly type: 'failed'; readonly message: string }
  /** Python was ready, then the worker died or broke the protocol. Every pending and later call is rejected. */
  | { readonly type: 'crashed'; readonly message: string }
  | { readonly type: 'refused'; readonly url: string }
  | { readonly type: 'violation'; readonly directive: string; readonly blocked: string };

export interface Python {
  /** Resolves with `contract_json()` once Python is ready; rejects when the boot fails. */
  readonly ready: Promise<string>;
  /** Run one bridge function; resolves with its JSON string, verbatim. */
  call(fn: BridgeFn, args: readonly unknown[]): Promise<string>;
}

/**
 * Take the inert asset blocks out of the page (scripts/vite-pyodide.mjs writes them) and parse them. Each element is
 * removed: its text has been copied into the boot message, and the page must not hold tens of megabytes twice.
 */
const takeAssets = (): EncodedAsset[] => {
  const blocks = [...document.querySelectorAll<HTMLScriptElement>('script[type="application/octet-stream"][data-name]')];
  if (blocks.length === 0) throw new Error('This page has no embedded Python. Build it with `make web`.');
  return blocks.map((el) => {
    const asset = parseEncodedAsset(el.dataset, el.textContent ?? '');
    el.remove();
    return asset;
  });
};

type Pending = { readonly resolve: (v: string) => void; readonly reject: (e: Error) => void };

export const startPython = (onEvent: (event: BootEvent) => void): Python => {
  const pending = new Map<number, Pending>();
  let nextId = 0;
  /** booting until `ready`; dead after any fatal event, with the reason every later call is rejected with. */
  let state: { readonly kind: 'booting' | 'ready' } | { readonly kind: 'dead'; readonly reason: Error } = { kind: 'booting' };
  let resolveReady!: (contract: string) => void;
  let rejectReady!: (e: Error) => void;
  const ready = new Promise<string>((resolve, reject) => {
    resolveReady = resolve;
    rejectReady = reject;
  });

  let worker: Worker | undefined;
  /** The worker cannot be relied on any more: report it once, reject everything waiting, stop the worker. */
  const fatal = (message: string): void => {
    if (state.kind === 'dead') return;
    const reason = new Error(message);
    onEvent({ type: state.kind === 'ready' ? 'crashed' : 'failed', message });
    state = { kind: 'dead', reason };
    rejectReady(reason);
    for (const p of pending.values()) p.reject(reason);
    pending.clear();
    worker?.terminate();
  };

  const settle = (id: number, outcome: { value: string } | { error: Error }): void => {
    const p = pending.get(id);
    if (!p) {
      fatal(`The Python worker answered call ${id}, which the page is not waiting for.`);
      return;
    }
    pending.delete(id);
    if ('value' in outcome) p.resolve(outcome.value);
    else p.reject(outcome.error);
  };

  const handle = (message: FromWorker): void => {
    switch (message.type) {
      case 'stage':
      case 'refused':
      case 'violation':
        onEvent(message);
        return;
      case 'ready':
        if (state.kind !== 'booting') {
          fatal('The Python worker reported ready twice.');
          return;
        }
        state = { kind: 'ready' };
        onEvent(message);
        resolveReady(message.contract);
        return;
      case 'result':
        settle(message.id, { value: message.value });
        return;
      case 'error':
        if (message.id === undefined) fatal(message.message);
        else settle(message.id, { error: new Error(message.message) });
        return;
    }
  };

  try {
    worker = new PyodideWorker();
    worker.addEventListener('error', (e) => fatal(`The Python worker failed: ${e.message || 'unknown error'}`));
    worker.addEventListener('messageerror', () => fatal('The page could not read a message from the Python worker.'));
    worker.addEventListener('message', (e: MessageEvent<unknown>) => {
      const message: unknown = e.data;
      if (isFromWorker(message)) handle(message);
      else fatal('The Python worker sent a message the page does not understand.');
    });
    // Cloned, not transferred: strings cannot be transferred, and the page has already dropped its copy.
    const boot: ToWorker = { type: 'boot', assets: takeAssets() };
    worker.postMessage(boot);
  } catch (e) {
    fatal(`The Python worker could not start: ${e instanceof Error ? e.message : String(e)}`);
  }

  const call = async (fn: BridgeFn, args: readonly unknown[]): Promise<string> => {
    await ready;
    if (state.kind === 'dead') throw state.reason;
    const id = nextId++;
    const message: ToWorker = { type: 'call', id, fn, args };
    return new Promise<string>((resolve, reject) => {
      worker!.postMessage(message); // ready resolved, so the worker exists; a DataCloneError rejects this call only
      pending.set(id, { resolve, reject });
    });
  };
  return { ready, call };
};
