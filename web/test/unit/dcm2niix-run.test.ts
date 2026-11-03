import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { runDcm2niix } from '../../src/shell/dcm2niix-run';
import type { DcmInput, WorkerLike } from '../../src/shell/dcm2niix-run';
import { fileSource } from '../../src/shell/source';

// The real module is an inline blob worker bundled by Vite; the runner only needs a constructor to exist.
vi.mock('../../src/shell/dcm2niix.worker.ts?worker&inline', () => ({ default: class {} }));

class FakeWorker implements WorkerLike {
  onmessage: WorkerLike['onmessage'] = null;
  onerror: WorkerLike['onerror'] = null;
  onmessageerror: WorkerLike['onmessageerror'] = null;
  postMessage = vi.fn();
  terminate = vi.fn();
  send(data: unknown): void {
    this.onmessage?.({ data } as MessageEvent);
  }
}

const file = (n: number): DcmInput => ({ source: fileSource(new File([new Uint8Array(n)], 'x.dcm')), relPath: 'd/x.dcm', deflated: false });
const wasm = new Uint8Array([0, 97, 115, 109]).buffer; // stands in for dcm2niix.wasm
const real = () => new Promise<void>((r) => setImmediate(r));
const done = { type: 'done', exitCode: 0, outputs: [{ name: 'a.nii.gz', buf: new ArrayBuffer(3) }] };

let worker: FakeWorker;
let created: number;
const createWorker = (): WorkerLike => {
  created++;
  return (worker = new FakeWorker());
};

/** Start a run and wait until the worker has been given its message. */
const start = async (opts: { signal?: AbortSignal; inactivityMs?: number; files?: DcmInput[]; onLog?: (l: string) => void; onSkip?: (f: string, r: string) => void } = {}) => {
  const ctl = new AbortController();
  const signal = opts.signal ?? ctl.signal;
  const p = runDcm2niix(opts.files ?? [file(4), file(5)], ['-z', 'y'], { wasm, signal, createWorker, ...opts });
  p.catch(() => undefined);
  for (let i = 0; i < 20 && !worker?.postMessage.mock.calls.length; i++) await real();
  return { p, ctl, signal };
};

beforeEach(() => {
  created = 0;
  worker = undefined as unknown as FakeWorker;
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
});
afterEach(() => {
  expect(vi.getTimerCount()).toBe(0); // the watchdog never outlives the run
  vi.useRealTimers();
});

const notDeflated = (): DcmInput => ({ source: fileSource(new File([new Uint8Array(500)], 'bad.dcm')), relPath: 'in.zip/sub/bad.dcm', deflated: true });

describe('runDcm2niix', () => {
  test('posts the run message with transferred buffers, then resolves on done and terminates once', async () => {
    const lines: string[] = [];
    const { p } = await start({ onLog: (l) => lines.push(l) });
    expect(worker.postMessage).toHaveBeenCalledTimes(1);
    const [msg, transfer] = worker.postMessage.mock.calls[0]!;
    expect(msg).toMatchObject({ type: 'run', args: ['-z', 'y'], inputs: [{ name: '0000.dcm' }, { name: '0001.dcm' }] });
    expect(transfer).toHaveLength(3); // the wasm copy and the two inputs
    expect(new Uint8Array(msg.wasm)).toEqual(new Uint8Array(wasm)); // every run gets its own copy: the caller's bytes stay usable
    expect(msg.wasm).not.toBe(wasm);
    worker.send({ type: 'log', line: 'hello', stream: 'stdout' });
    worker.send(done);
    const r = await p;
    expect(r).toMatchObject({ exitCode: 0, log: ['hello'] });
    expect(r.outputs.map((o) => o.name)).toEqual(['a.nii.gz']);
    expect(lines).toEqual(['hello']);
    expect(worker.terminate).toHaveBeenCalledTimes(1);
    worker.send({ type: 'error', message: 'late' }); // ignored: already settled
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  test('reports read progress and files in order', async () => {
    const progress: [number, number][] = [];
    const ctl = new AbortController();
    const p = runDcm2niix([file(1), file(1), file(1)], [], { wasm, signal: ctl.signal, createWorker, onReadProgress: (d, t) => progress.push([d, t]) });
    for (let i = 0; i < 20 && !worker?.postMessage.mock.calls.length; i++) await real();
    worker.send(done);
    await p;
    expect(progress).toEqual([[1, 3], [2, 3], [3, 3]]);
  });

  test('an error message rejects with its text and terminates once', async () => {
    const { p } = await start();
    worker.send({ type: 'error', message: 'boom' });
    await expect(p).rejects.toThrow('boom');
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  test('an unreadable message rejects', async () => {
    const { p } = await start();
    worker.send({ type: 'nonsense' });
    await expect(p).rejects.toThrow(/unreadable/);
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  test('onerror rejects with a clear message (wasm crashes are mapped) and terminates once', async () => {
    const { p } = await start();
    worker.onerror?.({ message: 'RuntimeError: memory access out of bounds' } as ErrorEvent);
    await expect(p).rejects.toThrow(/crashed, probably out of memory/);
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  test('onmessageerror rejects and terminates once', async () => {
    const { p } = await start();
    worker.onmessageerror?.({} as MessageEvent);
    await expect(p).rejects.toThrow(/could not read/);
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  test('abort before reading finishes: AbortError, no worker is ever created', async () => {
    const ctl = new AbortController();
    ctl.abort();
    await expect(runDcm2niix([file(1)], [], { wasm, signal: ctl.signal, createWorker })).rejects.toMatchObject({ name: 'AbortError' });
    expect(created).toBe(0);
  });

  test('abort between reads stops reading', async () => {
    const ctl = new AbortController();
    const p = runDcm2niix([file(1), file(1)], [], { wasm, signal: ctl.signal, createWorker, onReadProgress: () => ctl.abort() });
    await expect(p).rejects.toMatchObject({ name: 'AbortError' });
    expect(created).toBe(0);
  });

  test('abort after start rejects, terminates once, and removes its listener', async () => {
    const ctl = new AbortController();
    const remove = vi.spyOn(ctl.signal, 'removeEventListener');
    const { p } = await start({ signal: ctl.signal });
    ctl.abort();
    await expect(p).rejects.toMatchObject({ name: 'AbortError' });
    expect(worker.terminate).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function));
    worker.send(done); // a late message changes nothing
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  test('success removes the abort listener too, so a later abort is harmless', async () => {
    const ctl = new AbortController();
    const remove = vi.spyOn(ctl.signal, 'removeEventListener');
    const { p } = await start({ signal: ctl.signal });
    worker.send(done);
    await p;
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function));
    ctl.abort();
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  test('watchdog: not before the inactivity window, then rejects and terminates once', async () => {
    const { p } = await start({ inactivityMs: 60_000 });
    let settled = false;
    p.then(() => (settled = true), () => (settled = true));
    await vi.advanceTimersByTimeAsync(59_999);
    expect(settled).toBe(false);
    expect(worker.terminate).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    await expect(p).rejects.toThrow(/silent/);
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  test('watchdog restarts on every worker message', async () => {
    const { p } = await start({ inactivityMs: 60_000 });
    for (let i = 0; i < 5; i++) {
      vi.advanceTimersByTime(50_000);
      worker.send({ type: 'log', line: `tick ${i}`, stream: 'stdout' });
    }
    worker.send(done);
    await expect(p).resolves.toMatchObject({ exitCode: 0 });
  });

  test('a late message after settling does not re-arm the watchdog (checked by afterEach: no timers left)', async () => {
    const { p } = await start();
    worker.send(done);
    await p;
    worker.send({ type: 'log', line: 'late', stream: 'stdout' });
  });

  test('a deflated file that cannot be rewritten is skipped; the rest are numbered contiguously', async () => {
    const skipped: string[] = [];
    const { p } = await start({ files: [notDeflated(), file(4), file(5)], onSkip: (f) => skipped.push(f) });
    const [msg] = worker.postMessage.mock.calls[0]!;
    expect(msg.inputs.map((i: { name: string }) => i.name)).toEqual(['0000.dcm', '0001.dcm']);
    expect(skipped).toEqual(['in.zip/sub/bad.dcm']);
    worker.send(done);
    await p;
  });

  test('if no file can be prepared the run fails without creating a worker', async () => {
    const ctl = new AbortController();
    await expect(runDcm2niix([notDeflated(), notDeflated()], [], { wasm, signal: ctl.signal, createWorker })).rejects.toThrow(/None of the 2 files/);
    expect(created).toBe(0);
  });

  test('a source that cannot be read (a damaged ZIP entry) fails the run, naming the file; no worker is created', async () => {
    const damaged: DcmInput = {
      source: { ...fileSource(new File([new Uint8Array(4)], 'IM0007')), bytes: () => Promise.reject(new Error('CRC-32 mismatch (the archive is damaged)')) },
      relPath: 'in.zip/IM0007',
      deflated: false,
    };
    const ctl = new AbortController();
    await expect(runDcm2niix([file(3), damaged], [], { wasm, signal: ctl.signal, createWorker })).rejects.toThrow('Cannot read in.zip/IM0007: CRC-32 mismatch');
    expect(created).toBe(0);
  });
});
