import { HEADER_BYTES, readOutcome } from '../core/header';
import type { HeaderOutcome, Instance, Source } from '../core/types';
import { createByteBudget } from './budget';
import type { ByteBudget } from './budget';
import type { ScanInput } from './source';

export const BATCH_SIZE = 32;
/** Header reads above 64 KB (escalation to 1 MB or a whole file up to 64 MB) share this much in-flight memory. */
export const READ_BUDGET_BYTES = 256 * 1024 * 1024;

/**
 * Why a file is not in the tree. The last three come from ZIP expansion (`archive.ts`): an entry that is itself a
 * ZIP (one level only), an encrypted entry, or a compression method other than store/deflate.
 */
export type SkipReason = 'not-dicom' | 'dicomdir' | 'unreadable' | 'nested-zip' | 'encrypted' | 'unsupported-method';
export interface SkippedFile {
  readonly relPath: string;
  readonly reason: SkipReason;
  readonly detail?: string;
}
export interface RejectedFile {
  readonly relPath: string;
  readonly reason: string;
}
export interface ScanResult {
  readonly instances: readonly Instance[];
  readonly skipped: readonly SkippedFile[];
  readonly rejected: readonly RejectedFile[];
}
export interface ScanProgress {
  readonly scanned: number;
  readonly total: number;
  readonly instances: number;
}

const readPrefix = (source: Source, budget: ByteBudget) => (n: number) => budget.run(Math.min(n, source.size), () => source.readPrefix(n));

const unreadable = (e: unknown): HeaderOutcome => ({
  kind: 'skipped',
  reason: 'unreadable',
  detail: e instanceof Error ? e.message : String(e),
});

/** Let input events and painting through between batches. */
const yieldToEventLoop = (): Promise<void> => {
  const s = (globalThis as { scheduler?: { yield?: () => Promise<void> } }).scheduler;
  return s?.yield ? s.yield() : new Promise((r) => setTimeout(r, 0));
};

/**
 * Parse headers on the main thread (WebKit cannot read Files in workers on file://). Inputs are files or ZIP entries.
 * Batches run concurrently; returns null if `signal` aborts.
 */
export const scan = async (
  picked: readonly ScanInput[],
  opts: { readonly signal: AbortSignal; readonly onProgress: (p: ScanProgress) => void },
): Promise<ScanResult | null> => {
  const budget = createByteBudget(READ_BUDGET_BYTES, HEADER_BYTES);
  const instances: Instance[] = [];
  const skipped: SkippedFile[] = [];
  const rejected: RejectedFile[] = [];
  const total = picked.length;
  for (let i = 0; i < total; i += BATCH_SIZE) {
    if (opts.signal.aborted) return null;
    const batch = picked.slice(i, i + BATCH_SIZE);
    const outcomes = await Promise.all(batch.map((p) => readOutcome(p.source, p.relPath, readPrefix(p.source, budget)).catch(unreadable)));
    outcomes.forEach((o, j) => {
      const relPath = batch[j]!.relPath;
      switch (o.kind) {
        case 'instance':
          instances.push(o.instance);
          break;
        case 'skipped':
          skipped.push(o.reason === 'unreadable' || o.reason === 'not-dicom' ? { relPath, reason: o.reason, ...(o.detail ? { detail: o.detail } : {}) } : { relPath, reason: o.reason });
          break;
        case 'rejected':
          rejected.push({ relPath, reason: o.reason });
          break;
        case 'needs-more': // readOutcome never returns this; keep the file visible if it ever does
          rejected.push({ relPath, reason: 'incomplete header' });
          break;
      }
    });
    opts.onProgress({ scanned: Math.min(i + BATCH_SIZE, total), total, instances: instances.length });
    await yieldToEventLoop();
  }
  return opts.signal.aborted ? null : { instances, skipped, rejected };
};
