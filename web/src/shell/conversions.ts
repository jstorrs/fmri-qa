/**
 * One series through dcm2niix, in its own fresh worker. `src/shell/run.ts` calls it for each selected series in turn.
 */
import { friendlyError, isWasmCrash } from '../core/dcm2niix';
import type { Conversion } from '../core/run';
import type { SeriesNode } from '../core/types';
import { convertSeries } from './convert';
import { abortError, isAbortError } from './dcm2niix-run';

export const label = (s: SeriesNode): string => `#${s.number ?? '–'} ${s.description || '(no description)'}`;
/** dcm2niix's own warnings and errors, files the runner left out, and the raw text of a wasm crash. */
const SHOWN = /^(warning|error|skipped)\b/i;
const shown = (line: string): boolean => SHOWN.test(line) || isWasmCrash(line);

/** Convert one series; never throws. `messages` holds what dcm2niix and the runner said that the user should see, on every outcome. */
export const runOne = async (
  s: SeriesNode,
  flags: readonly string[],
  wasm: ArrayBuffer,
  signal: AbortSignal,
  convert: typeof convertSeries = convertSeries,
): Promise<Conversion> => {
  const lines: string[] = [];
  const messages = (): string[] => lines.filter(shown);
  try {
    if (signal.aborted) throw abortError();
    const result = await convert(s, flags, { wasm, signal, log: (line) => lines.push(line) });
    if (result.exitCode !== 0) throw new Error(`dcm2niix exited with code ${result.exitCode}`);
    if (result.outputs.length === 0) throw new Error('dcm2niix wrote no files');
    return { status: 'ok', files: result.outputs, messages: messages() };
  } catch (e) {
    if (isAbortError(e)) return { status: 'cancelled', messages: messages() };
    return { status: 'failed', reason: friendlyError(e instanceof Error ? e.message : String(e)), messages: messages() };
  }
};
