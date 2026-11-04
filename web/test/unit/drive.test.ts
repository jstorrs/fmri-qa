import { describe, expect, test, vi } from 'vitest';
import { CANCELLED, isRunning, startRun, step } from '../../src/core/run';
import type { Conversion, Job, Result, Run, RunEvent } from '../../src/core/run';
import { drive } from '../../src/shell/drive';
import type { Drive } from '../../src/shell/drive';
import type { BridgeFn } from '../../src/shell/pyodide-protocol';

const deferred = <T>() => {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};
const enc = (s: string): ArrayBuffer => new TextEncoder().encode(s).buffer as ArrayBuffer;
const converted = (s: string): Conversion => ({
  status: 'ok',
  files: [
    { name: `${s}.nii.gz`, buf: enc('nifti') },
    { name: `${s}.json`, buf: enc('{}') },
  ],
  messages: [],
});
const report = (stem: string): string =>
  JSON.stringify({ kind: 'report', stem, html: '<html>', record: {}, warnings: [], record_document_json: `{"stem": "${stem}"}\n` });
/** names_json gives every file `qa_` in front; analyze_json reports. */
const answer = (fn: BridgeFn, args: readonly unknown[]): string => {
  if (fn === 'names_json') return JSON.stringify(Object.fromEntries([...(args[0] as Map<string, Uint8Array>).keys()].map((n) => [n, `qa_${n}`])));
  if (fn === 'analyze_json') return report(args[2] as string);
  throw new Error(`unexpected ${fn}`);
};

/** A drive over series 'A' and 'B' with fakes; `over` replaces any of them. */
const setup = (over: Partial<Drive<string>> = {}) => {
  const ctl = new AbortController();
  let run: Run = startRun(['A', 'B'].map((s) => ({ uid: s, label: s })));
  const texts: string[] = [];
  const d: Drive<string> = {
    series: ['A', 'B'],
    label: (s) => s,
    wasm: async () => new ArrayBuffer(1),
    runOne: async (s) => converted(s),
    python: { ready: Promise.resolve('{}'), call: vi.fn(async (fn: BridgeFn, args: readonly unknown[]) => answer(fn, args)) },
    dispatch: (e: RunEvent) => {
      run = step(run, e);
    },
    run: () => run,
    progress: (u) => texts.push(u.text),
    log: () => {},
    signal: ctl.signal,
    ...over,
  };
  return { d, ctl, texts, run: () => run };
};
const results = (r: Run): Result[] => r.jobs.flatMap((j: Job) => (j.status === 'converted' ? j.results : []));
const summary = (r: Run) => results(r).map((x) => [x.stem, x.status, x.status === 'failed' ? x.cause.kind === 'error' && x.cause.reason : null]);

describe('drive', () => {
  test('converts each series, names them all in one call, then analyzes each in turn', async () => {
    const { d, run } = setup();
    await drive(d);
    expect(summary(run())).toEqual([
      ['qa_A', 'done', null],
      ['qa_B', 'done', null],
    ]);
    const call = vi.mocked(d.python.call);
    expect(call.mock.calls.map(([fn]) => fn)).toEqual(['names_json', 'analyze_json', 'analyze_json']);
    // Only the sidecars' bytes go to names_json.
    const files = call.mock.calls[0]![1][0] as Map<string, Uint8Array>;
    expect([...files].map(([n, b]) => [n, b.length])).toEqual([
      ['A.nii.gz', 0],
      ['A.json', 2],
      ['B.nii.gz', 0],
      ['B.json', 2],
    ]);
    expect(call.mock.calls[1]![1][2]).toBe('qa_A');
    expect(isRunning(run())).toBe(false);
  });

  test('cancel while waiting for Python: every result fails as cancelled, and Python is never called', async () => {
    const { d, ctl, texts, run } = setup({ python: { ready: new Promise<string>(() => {}), call: vi.fn() } });
    const done = drive(d);
    await vi.waitFor(() => expect(texts).toContain('Waiting for Python to start…'));
    ctl.abort();
    await done;
    expect(summary(run())).toEqual([
      ['A', 'failed', CANCELLED],
      ['B', 'failed', CANCELLED],
    ]);
    expect(d.python.call).not.toHaveBeenCalled();
  });

  test('cancel during names_json: the late names change nothing, and nothing is analyzed', async () => {
    const names = deferred<string>();
    const call = vi.fn(async (fn: BridgeFn) => (fn === 'names_json' ? names.promise : 'unreachable'));
    const { d, ctl, run } = setup({ python: { ready: Promise.resolve('{}'), call } });
    const done = drive(d);
    await vi.waitFor(() => expect(call).toHaveBeenCalledTimes(1));
    ctl.abort();
    names.resolve('{"A.nii.gz": "qa_A.nii.gz"}');
    await done;
    expect(summary(run())).toEqual([
      ['A', 'failed', CANCELLED],
      ['B', 'failed', CANCELLED],
    ]);
    expect(call).toHaveBeenCalledTimes(1);
  });

  test('cancel during an analysis: it finishes and is kept as done; the rest fail as cancelled', async () => {
    const first = deferred<string>();
    const call = vi.fn(async (fn: BridgeFn, args: readonly unknown[]) => (fn === 'analyze_json' ? first.promise : answer(fn, args)));
    const { d, ctl, texts, run } = setup({ python: { ready: Promise.resolve('{}'), call } });
    const done = drive(d);
    await vi.waitFor(() => expect(call).toHaveBeenCalledTimes(2));
    ctl.abort();
    // The stop on abort must leave the result in flight alone.
    expect(summary(run())).toEqual([
      ['qa_A', 'analyzing', null],
      ['qa_B', 'failed', CANCELLED],
    ]);
    expect(texts.at(-1)).toBe('Cancelling: finishing qa_A…');
    first.resolve(report('qa_A'));
    await done;
    expect(summary(run())).toEqual([
      ['qa_A', 'done', null],
      ['qa_B', 'failed', CANCELLED],
    ]);
    expect(texts.at(-1)).toBe('Cancelled; qa_A finished.');
    expect(call).toHaveBeenCalledTimes(2);
  });

  test('a boot failure fails every result with "Python did not start"', async () => {
    const ready = Promise.reject(new Error('boom'));
    ready.catch(() => {}); // observed by drive later; not an unhandled rejection meanwhile
    const { d, run } = setup({ python: { ready, call: vi.fn() } });
    await drive(d);
    expect(summary(run())).toEqual([
      ['A', 'failed', 'Python did not start: boom'],
      ['B', 'failed', 'Python did not start: boom'],
    ]);
  });

  test('a worker that crashed after naming rejects every later call: each result fails with the reason', async () => {
    const call = vi.fn(async (fn: BridgeFn, args: readonly unknown[]) => {
      if (fn === 'analyze_json') throw new Error('The Python worker failed: out of memory');
      return answer(fn, args);
    });
    const { d, run } = setup({ python: { ready: Promise.resolve('{}'), call } });
    await drive(d);
    expect(summary(run())).toEqual([
      ['qa_A', 'failed', 'Python failed: The Python worker failed: out of memory'],
      ['qa_B', 'failed', 'Python failed: The Python worker failed: out of memory'],
    ]);
    expect(call).toHaveBeenCalledTimes(3);
  });

  test('a series that converts after Cancel is settled at the end; the next is cancelled', async () => {
    const conversion = deferred<Conversion>();
    const runOne = vi.fn(async () => conversion.promise);
    const { d, ctl, run } = setup({ runOne });
    const done = drive(d);
    await vi.waitFor(() => expect(runOne).toHaveBeenCalledTimes(1));
    ctl.abort();
    conversion.resolve(converted('A')); // dcm2niix finished just as Cancel came
    await done;
    expect(run().jobs.map((j) => j.status)).toEqual(['converted', 'cancelled']);
    expect(summary(run())).toEqual([['A', 'failed', CANCELLED]]);
    expect(isRunning(run())).toBe(false);
    expect(runOne).toHaveBeenCalledTimes(1);
  });

  test('an unexpected error rejects, and fails what is left with its reason', async () => {
    const { d, run } = setup({ wasm: () => Promise.reject(new Error('no wasm')) });
    await expect(drive(d)).rejects.toThrow('no wasm');
    expect(run().jobs).toMatchObject([
      { status: 'failed', reason: 'The run stopped: no wasm' },
      { status: 'failed', reason: 'The run stopped: no wasm' },
    ]);
  });
});
