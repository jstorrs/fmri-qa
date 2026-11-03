/**
 * "Convert selected": each selected series goes through dcm2niix, one at a time, each in its own fresh worker. The
 * result of every series is a list item in `#conversions` (what the e2e test reads): `data-series` is the series UID,
 * `data-status` is `running`, `ok`, `failed` or `cancelled`, and `data-files` / `data-sizes` are JSON arrays of the
 * output names (sorted) and their byte sizes. Step 6 replaces this with the run table; the output bytes are kept
 * (until the next conversion) only when `keepOutputs` is set, which the e2e test does.
 */
import { CONTRACT_FLAGS } from '../core/convert-args';
import { friendlyError, isWasmCrash } from '../core/dcm2niix';
import type { OutputFile } from '../core/dcm2niix';
import type { SeriesNode } from '../core/types';
import { convertSeries } from './convert';
import { abortError, isAbortError } from './dcm2niix-run';
import { dcm2niixWasm } from './dcm2niix-wasm';
import type { IntakeArea } from './intake-ui';
import { formatSize } from './ui/format';
import { h } from './ui/h';

export interface Conversions {
  /** The bytes of an output of the last conversion, or undefined (only kept when `keepOutputs` is set). */
  output(seriesUid: string, name: string): ArrayBuffer | undefined;
}

export const label = (s: SeriesNode): string => `#${s.number ?? '–'} ${s.description || '(no description)'}`;
/** dcm2niix's own warnings and errors, files the runner left out, and the raw text of a wasm crash. */
const SHOWN = /^(warning|error|skipped)\b/i;
const shown = (line: string): boolean => SHOWN.test(line) || isWasmCrash(line);

export type SeriesOutcome =
  | { readonly status: 'ok'; readonly text: string; readonly files: readonly OutputFile[]; readonly messages: readonly string[] }
  | { readonly status: 'failed' | 'cancelled'; readonly text: string; readonly files: readonly []; readonly messages: readonly string[] };

/** Convert one series; never throws. `messages` holds what dcm2niix and the runner said that the user should see, on every outcome. */
export const runOne = async (
  s: SeriesNode,
  flags: readonly string[],
  wasm: ArrayBuffer,
  signal: AbortSignal,
  convert: typeof convertSeries = convertSeries,
): Promise<SeriesOutcome> => {
  const lines: string[] = [];
  const messages = (): string[] => lines.filter(shown);
  try {
    if (signal.aborted) throw abortError();
    const result = await convert(s, flags, { wasm, signal, log: (line) => lines.push(line) });
    if (result.exitCode !== 0) throw new Error(`dcm2niix exited with code ${result.exitCode}`);
    if (result.outputs.length === 0) throw new Error('dcm2niix wrote no files');
    const text = result.outputs.map((f) => `${f.name} (${formatSize(f.buf.byteLength)})`).join(', ');
    return { status: 'ok', text, files: result.outputs, messages: messages() };
  } catch (e) {
    if (isAbortError(e)) return { status: 'cancelled', text: 'cancelled', files: [], messages: messages() };
    return { status: 'failed', text: `failed: ${friendlyError(e instanceof Error ? e.message : String(e))}`, files: [], messages: messages() };
  }
};

/** `keepOutputs`: keep the last conversion's bytes in memory (the e2e test reads them); otherwise only names and sizes are shown. */
export const mountConversions = (area: IntakeArea, options: { readonly keepOutputs?: boolean; readonly flags?: readonly string[] } = {}): Conversions => {
  const flags = options.flags ?? CONTRACT_FLAGS;
  const button = document.getElementById('convert') as HTMLButtonElement;
  const list = document.getElementById('conversions') as HTMLElement;
  let outputs = new Map<string, ArrayBuffer>();

  const refresh = (): void => {
    button.disabled = area.phase() !== 'ready' || area.selected().length === 0;
  };
  area.onChange(refresh);
  refresh();

  const convertOne = async (s: SeriesNode, wasm: ArrayBuffer, signal: AbortSignal): Promise<void> => {
    const messages = h('ul', { class: 'messages' });
    const row = h('li', { data: { series: s.uid, status: 'running' } }, `${label(s)}: converting…`, messages);
    list.append(row);
    const r = await runOne(s, flags, wasm, signal);
    for (const line of r.messages) {
      messages.append(h('li', {}, line));
      area.log(`${label(s)}: ${line}`);
    }
    const sorted = [...r.files].sort((a, b) => (a.name < b.name ? -1 : 1));
    if (options.keepOutputs) for (const f of sorted) outputs.set(`${s.uid}/${f.name}`, f.buf);
    row.dataset['status'] = r.status;
    row.dataset['files'] = JSON.stringify(sorted.map((f) => f.name));
    row.dataset['sizes'] = JSON.stringify(sorted.map((f) => f.buf.byteLength));
    row.firstChild!.textContent = `${label(s)}: ${r.text}`;
  };

  button.addEventListener('click', () => {
    const series = area.selected();
    if (series.length === 0) return;
    list.replaceChildren();
    outputs = new Map();
    void area
      .runExclusive('Converting…', async (signal) => {
        const wasm = await dcm2niixWasm();
        for (const [i, s] of series.entries()) {
          area.progress.update({ done: i, total: series.length, text: `Converting ${i + 1} / ${series.length}: ${label(s)}` });
          await convertOne(s, wasm, signal);
        }
      })
      .catch((e: unknown) => area.log(`Conversion stopped: ${e instanceof Error ? e.message : String(e)}`));
  });

  return { output: (seriesUid, name) => outputs.get(`${seriesUid}/${name}`) };
};
