import DcmWorker from './dcm2niix.worker.ts?worker&inline';
import { inflateDeflatedFile } from '../core/deflate';
import { InputReadError, friendlyError, inputNames } from '../core/dcm2niix';
import type { OutputFile } from '../core/dcm2niix';
import type { Source } from '../core/types';
import { isFromWorker } from './dcm2niix-protocol';
import type { RunMessage, WorkerFile } from './dcm2niix-protocol';

/** The slice of `Worker` the runner uses; tests inject a fake. */
export interface WorkerLike {
  onmessage: ((e: MessageEvent) => void) | null;
  onerror: ((e: ErrorEvent) => void) | null;
  onmessageerror: ((e: MessageEvent) => void) | null;
  postMessage(message: unknown, transfer: Transferable[]): void;
  terminate(): void;
}

/** One file of the series; `deflated` files (Deflated Explicit VR LE) are rewritten as plain explicit LE before sending. */
export interface DcmInput {
  readonly source: Source;
  /** Shown in messages (the path in the opened folder or archive); the source's own name is only its last segment. */
  readonly relPath: string;
  readonly deflated: boolean;
}

export interface RunOptions {
  /** dcm2niix.wasm; each run sends the worker its own copy (the worker's glue owns what it is given). */
  readonly wasm: ArrayBuffer;
  readonly signal: AbortSignal;
  /** Each line dcm2niix prints (stdout and stderr), as it arrives. */
  readonly onLog?: (line: string) => void;
  /** After each file is read on the main thread. */
  readonly onReadProgress?: (done: number, total: number) => void;
  /** A deflated file could not be rewritten and is left out of the conversion. */
  readonly onSkip?: (relPath: string, reason: string) => void;
  /** All bytes are read and the worker has been started. */
  readonly onRunning?: () => void;
  /** Reject when the worker has sent nothing for this long. Default {@link INACTIVITY_MS}. */
  readonly inactivityMs?: number;
  /** Default: a fresh inline blob worker. */
  readonly createWorker?: () => WorkerLike;
}

export interface RunResult {
  readonly exitCode: number;
  readonly outputs: readonly OutputFile[];
  /** Every line printed, in order (capped at the last {@link MAX_LOG_LINES}). */
  readonly log: readonly string[];
}

export const MAX_LOG_LINES = 200;
/** dcm2niix prints nothing while it decodes or gzips, so this is generous; any message from the worker restarts it. */
export const INACTIVITY_MS = 10 * 60_000;

export const abortError = (): DOMException => new DOMException('Conversion cancelled', 'AbortError');
export const isAbortError = (e: unknown): boolean => e instanceof DOMException && e.name === 'AbortError';

const defaultWorker = (): WorkerLike => new DcmWorker();

/** The bytes to send, or why this file cannot be (a deflated file that cannot be rewritten). Read errors still throw. */
const prepare = async ({ source, relPath, deflated }: DcmInput): Promise<{ buf: ArrayBuffer } | { skipped: string }> => {
  let buf: ArrayBuffer;
  try {
    buf = await source.bytes(); // a ZIP entry is inflated and CRC-checked here
  } catch (e) {
    throw new InputReadError(relPath, `Cannot read ${relPath}: ${e instanceof Error ? e.message || e.name : String(e)}`, { cause: e });
  }
  if (!deflated) return { buf };
  const bytes = new Uint8Array(buf);
  try {
    return { buf: inflateDeflatedFile(bytes).buffer as ArrayBuffer };
  } catch (e) {
    return { skipped: e instanceof Error ? e.message : String(e) };
  }
};

/**
 * Read every file on the main thread (WebKit on file:// cannot read File objects inside a worker; ZIP entries are
 * read there too), one at a time so only the bytes themselves are in flight, checking the signal between reads. A file that cannot be prepared is
 * skipped (reported through `onSkip`) so one bad file does not sink the series; if none can be prepared, that is an
 * error.
 */
const readAll = async (files: readonly DcmInput[], opts: RunOptions): Promise<WorkerFile[]> => {
  const bufs: ArrayBuffer[] = [];
  let firstSkip: string | undefined;
  let firstSkipPath: string | undefined;
  for (const [i, input] of files.entries()) {
    if (opts.signal.aborted) throw abortError();
    const r = await prepare(input);
    if ('buf' in r) bufs.push(r.buf);
    else {
      firstSkip ??= `${input.relPath}: ${r.skipped}`;
      firstSkipPath ??= input.relPath;
      opts.onSkip?.(input.relPath, r.skipped);
    }
    opts.onReadProgress?.(i + 1, files.length);
  }
  if (opts.signal.aborted) throw abortError();
  if (files.length > 0 && bufs.length === 0)
    throw new InputReadError(firstSkipPath ?? '', `None of the ${files.length} files could be prepared for dcm2niix (${firstSkip}).`);
  const names = inputNames(bufs.length);
  return bufs.map((buf, i) => ({ name: names[i]!, buf }));
};

/**
 * Convert one series with dcm2niix in a fresh worker. Cancel (the signal) terminates the worker and rejects with an
 * AbortError. The worker is terminated exactly once, before the promise settles, whatever the outcome. The watchdog
 * rejects if the worker is silent for `inactivityMs`.
 */
export const runDcm2niix = async (files: readonly DcmInput[], args: readonly string[], opts: RunOptions): Promise<RunResult> => {
  const inputs = await readAll(files, opts);
  const worker = (opts.createWorker ?? defaultWorker)();
  const log: string[] = [];
  const inactivityMs = opts.inactivityMs ?? INACTIVITY_MS;
  let watchdog: ReturnType<typeof setTimeout> | undefined;
  let onAbort: (() => void) | undefined;
  try {
    return await new Promise<RunResult>((res, rej) => {
      let settled = false;
      const resolve = (r: RunResult): void => {
        settled = true;
        res(r);
      };
      const reject = (e: Error): void => {
        settled = true;
        rej(e);
      };
      const arm = (): void => {
        if (settled) return; // a late message must not restart the watchdog
        clearTimeout(watchdog);
        watchdog = setTimeout(
          () => reject(new Error(`dcm2niix was silent for ${Math.round(inactivityMs / 60_000)} minutes; the conversion was stopped.`)),
          inactivityMs,
        );
      };
      worker.onmessage = (e) => {
        arm();
        const m = e.data;
        if (!isFromWorker(m)) return reject(new Error('The dcm2niix worker sent an unreadable message.'));
        switch (m.type) {
          case 'log':
            log.push(m.line);
            if (log.length > MAX_LOG_LINES) log.shift();
            return opts.onLog?.(m.line);
          case 'done':
            return resolve({ exitCode: m.exitCode, outputs: m.outputs, log });
          case 'error':
            return reject(new Error(m.message));
        }
      };
      worker.onerror = (e) => {
        const detail = e.message ? friendlyError(e.message) : '';
        reject(new Error(`The dcm2niix worker failed to run${detail ? `: ${detail}` : ''}. This browser may be blocking it.`));
      };
      worker.onmessageerror = () => reject(new Error('The dcm2niix worker sent a message this browser could not read.'));
      onAbort = () => reject(abortError());
      opts.signal.addEventListener('abort', onAbort, { once: true });
      if (opts.signal.aborted) return onAbort();
      arm();
      const wasm = opts.wasm.slice(0);
      const msg: RunMessage = { type: 'run', args, inputs, wasm };
      worker.postMessage(msg, [wasm, ...inputs.map((i) => i.buf)]);
      opts.onRunning?.();
    });
  } finally {
    clearTimeout(watchdog);
    if (onAbort) opts.signal.removeEventListener('abort', onAbort);
    worker.terminate();
  }
};
