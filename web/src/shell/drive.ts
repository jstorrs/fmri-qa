/**
 * The sequence of a run, without the DOM: convert each series in turn, then, once Python is ready, name every output
 * with one `names_json` and analyze each NIfTI with `analyze_json`, one at a time. Each step becomes a `RunEvent`
 * through `dispatch`; `src/shell/run.ts` wires it to the page, `test/unit/drive.test.ts` to fakes.
 *
 * Cancel (`signal`) aborts the conversion in progress (dcm2niix can stop) and lets an analysis in progress finish
 * (Python cannot); nothing new starts. Whatever is left unfinished at the end is settled with a `stop`.
 */
import { isRunning, namingInput, nextToAnalyze, parseAnalysis, parseNames } from '../core/run';
import type { Conversion, Run, RunEvent, StopCause } from '../core/run';
import type { Python } from './python';

export interface Drive<S> {
  readonly series: readonly S[];
  readonly label: (s: S) => string;
  /** The dcm2niix wasm, loaded once for the run. */
  readonly wasm: () => Promise<ArrayBuffer>;
  /** Convert one series; never throws (`runOne`). */
  readonly runOne: (s: S, wasm: ArrayBuffer, signal: AbortSignal) => Promise<Conversion>;
  readonly python: Pick<Python, 'ready' | 'call'>;
  readonly dispatch: (event: RunEvent) => void;
  /** The run as `dispatch` left it. */
  readonly run: () => Run;
  readonly progress: (update: { readonly done: number; readonly total: number; readonly text: string }) => void;
  readonly log: (line: string) => void;
  readonly signal: AbortSignal;
}

const abortError = (): DOMException => new DOMException('Run cancelled', 'AbortError');
const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** `promise`, or an AbortError as soon as `signal` aborts. */
const unlessAborted = <T>(promise: Promise<T>, signal: AbortSignal): Promise<T> =>
  new Promise<T>((resolve, reject) => {
    if (signal.aborted) return reject(abortError());
    const onAbort = (): void => reject(abortError());
    signal.addEventListener('abort', onAbort, { once: true });
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', onAbort));
  });

const convertAll = async <S>(d: Drive<S>): Promise<void> => {
  const wasm = await d.wasm();
  for (const [i, s] of d.series.entries()) {
    if (d.signal.aborted) return;
    d.progress({ done: i, total: d.series.length, text: `Converting ${i + 1} / ${d.series.length}: ${d.label(s)}` });
    d.dispatch({ type: 'convert', job: i });
    const conversion = await d.runOne(s, wasm, d.signal);
    for (const line of conversion.messages) d.log(`${d.label(s)}: ${line}`);
    d.dispatch({ type: 'converted', job: i, conversion });
  }
};

const name = async <S>(d: Drive<S>): Promise<void> => {
  if (d.signal.aborted) return;
  const input = namingInput(d.run());
  if ('duplicate' in input) {
    d.dispatch({ type: 'naming-failed', reason: `Two series gave dcm2niix the same file name, ${input.duplicate}, so neither could be named.` });
    return;
  }
  if (input.files.size === 0) return;
  d.progress({ done: 0, total: 0, text: 'Waiting for Python to start…' });
  try {
    await unlessAborted(d.python.ready, d.signal);
  } catch (e) {
    if (!d.signal.aborted) d.dispatch({ type: 'naming-failed', reason: `Python did not start: ${message(e)}` });
    return;
  }
  // names_json reads only the sidecars; every other file goes as empty bytes, which spares copying the NIfTIs.
  const files = new Map([...input.files].map(([n, f]) => [n, n.endsWith('.json') ? new Uint8Array(f.buf) : new Uint8Array(0)]));
  d.progress({ done: 0, total: 0, text: 'Naming the files…' });
  try {
    d.dispatch({ type: 'named', names: parseNames(await d.python.call('names_json', [files])) });
  } catch (e) {
    d.dispatch({ type: 'naming-failed', reason: `The files could not be named: ${message(e)}` });
  }
};

const analyzeAll = async <S>(d: Drive<S>): Promise<void> => {
  for (let next = nextToAnalyze(d.run()), i = 1; next && !d.signal.aborted; next = nextToAnalyze(d.run()), i++) {
    const { key, result } = next;
    d.progress({ done: 0, total: 0, text: `Analyzing ${i}: ${result.stem}` });
    d.dispatch({ type: 'analyze', at: key });
    const finishing = (): void => d.progress({ done: 0, total: 0, text: `Cancelling: finishing ${result.stem}…` });
    d.signal.addEventListener('abort', finishing, { once: true });
    const { nifti, sidecar } = result.files;
    try {
      const text = await d.python.call('analyze_json', [new Uint8Array(nifti.buf), sidecar && new Uint8Array(sidecar.buf), result.stem]);
      d.dispatch({ type: 'analyzed', at: key, analysis: parseAnalysis(text) });
    } catch (e) {
      d.dispatch({ type: 'analyze-failed', at: key, reason: `Python failed: ${message(e)}` });
    } finally {
      d.signal.removeEventListener('abort', finishing);
    }
    if (d.signal.aborted) d.progress({ done: 0, total: 0, text: `Cancelled; ${result.stem} finished.` });
  }
};

/** Run the whole sequence. Rejects only on an unexpected error, after settling the run with it. */
export const drive = async <S>(d: Drive<S>): Promise<void> => {
  // On Cancel, settle at once what can be settled; what is running reports as it finishes.
  const onAbort = (): void => d.dispatch({ type: 'stop', cause: { kind: 'cancelled' } });
  d.signal.addEventListener('abort', onAbort, { once: true });
  let cause: StopCause = { kind: 'cancelled' };
  try {
    await convertAll(d);
    await name(d);
    await analyzeAll(d);
  } catch (e) {
    cause = { kind: 'error', reason: `The run stopped: ${message(e)}` };
    throw e;
  } finally {
    d.signal.removeEventListener('abort', onAbort);
    // A series converted after Cancel, or everything after an unexpected error.
    if (isRunning(d.run())) d.dispatch({ type: 'stop', cause });
  }
};
