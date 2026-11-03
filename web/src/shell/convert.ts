/**
 * Run dcm2niix on one series of the tree. Logs; never notifies (the caller decides what the user is told).
 */
import { DEFLATED_LE } from '../core/header';
import type { SeriesNode } from '../core/types';
import { MAX_LOG_LINES, runDcm2niix } from './dcm2niix-run';
import type { RunResult } from './dcm2niix-run';

/** The dcm2niix the bundled wasm reports (read from it at build time, see vite.config.mjs); named in the conversion report. */
export const DCM2NIIX_VERSION: string = __DCM2NIIX_VERSION__;

const LOG_FLUSH_MS = 150;

/**
 * Forward lines to the log without flooding the DOM: the first line goes out at once (so the version line shows as
 * soon as dcm2niix starts), later ones in batches every {@link LOG_FLUSH_MS}. `flush()` emits whatever is pending.
 */
export const batchedLog = (emit: (line: string) => void) => {
  let pending: string[] = [];
  let timer: ReturnType<typeof setTimeout> | undefined;
  const emitPending = (): void => {
    const lines = pending;
    pending = [];
    if (lines.length > MAX_LOG_LINES) emit(`… ${lines.length - MAX_LOG_LINES} earlier dcm2niix lines omitted`);
    for (const l of lines.slice(-MAX_LOG_LINES)) emit(l);
  };
  const flush = (): void => {
    clearTimeout(timer);
    timer = undefined;
    emitPending();
  };
  return {
    push: (line: string): void => {
      if (timer === undefined) {
        emit(line);
        timer = setTimeout(flush, LOG_FLUSH_MS);
      } else pending.push(line);
    },
    flush,
  };
};

export interface ConvertOptions {
  /** dcm2niix.wasm (see `RunOptions.wasm`). */
  readonly wasm: ArrayBuffer;
  readonly signal: AbortSignal;
  /** Every line for the log: dcm2niix's own output (batched) and skipped files. */
  readonly log: (line: string) => void;
  /** After each file is read on the main thread. */
  readonly onReadProgress?: (done: number, total: number) => void;
  /** All bytes are read and the worker has been started. */
  readonly onRunning?: () => void;
}

/** Convert `series` with dcm2niix `args` (no `-o` or input directory). Rejects on failure; an AbortError on cancel. */
export const convertSeries = async (series: SeriesNode, args: readonly string[], opts: ConvertOptions): Promise<RunResult> => {
  const lines = batchedLog(opts.log);
  try {
    const inputs = series.instances.map((i) => ({ source: i.source, relPath: i.relPath, deflated: i.transferSyntax === DEFLATED_LE }));
    return await runDcm2niix(inputs, args, {
      wasm: opts.wasm,
      signal: opts.signal,
      onLog: lines.push,
      onSkip: (file, reason) => opts.log(`Skipped ${file}: ${reason}`),
      onReadProgress: opts.onReadProgress,
      onRunning: opts.onRunning,
    });
  } finally {
    lines.flush();
  }
};
