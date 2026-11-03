import { afterEach, describe, expect, test, vi } from 'vitest';
import { BLOB_WARN_BYTES, askForFile, saveZip, streamToBlob } from '../../src/shell/zip-sink';
import type { Activation, SavePicker, ZipFiles } from '../../src/shell/zip-sink';

const domError = (name: string): DOMException => new DOMException('', name);
const tiny = (): ZipFiles => [{ name: 'a.txt', input: new Uint8Array([1, 2, 3]), lastModified: new Date(2026, 0, 1) }];

interface Env {
  notes: string[];
  downloads: string[];
  writable: { aborted: unknown[]; chunks: number };
}

/** Browser globals for saveZip: a picker (or none), the activation state, a confirm answer and an anchor to click. */
const stubBrowser = (opts: {
  picker?: (writable: WritableStream<Uint8Array>) => SavePicker | undefined;
  active?: boolean;
  confirm?: boolean;
  /** Writes succeed until this says so, then fail (so the work behind the stream is running when the disk errors). */
  failWhen?: () => boolean;
}): Env => {
  const env: Env = { notes: [], downloads: [], writable: { aborted: [], chunks: 0 } };
  const writable = new WritableStream<Uint8Array>({
    async write() {
      env.writable.chunks++;
      if (opts.failWhen?.()) throw new Error('disk full');
      await new Promise((r) => setTimeout(r, 5)); // a slow disk
    },
  });
  const realAbort = writable.abort.bind(writable);
  writable.abort = (reason?: unknown) => {
    env.writable.aborted.push(reason); // a stream already errored by a failed write never reaches the sink's own abort
    return realAbort(reason);
  };
  vi.stubGlobal('window', { showSaveFilePicker: opts.picker?.(writable) });
  vi.stubGlobal('navigator', { userActivation: opts.active === undefined ? undefined : ({ isActive: opts.active } satisfies Activation) });
  vi.stubGlobal('confirm', () => opts.confirm ?? true);
  vi.stubGlobal('document', {
    createElement: () => ({
      click() {
        env.downloads.push('clicked');
      },
      remove() {},
    }),
    body: { append() {} },
  });
  return env;
};

const pickerOf = (result: (w: WritableStream<Uint8Array>) => Promise<unknown>): ((w: WritableStream<Uint8Array>) => SavePicker) =>
  (w) => (async () => ({ createWritable: () => result(w) })) as unknown as SavePicker;
const working = pickerOf(async (w) => w);
const throwing = (name: string) => (): SavePicker => async () => {
  throw domError(name);
};

afterEach(() => vi.unstubAllGlobals());

describe('askForFile', () => {
  const note = (): void => undefined;
  test('no picker: unavailable', async () => {
    expect(await askForFile(undefined, undefined, 'x.zip', note)).toBe('unavailable');
  });
  test('decision table for refusals', async () => {
    vi.stubGlobal('window', {});
    const refuse = (name: string): SavePicker => async () => {
      throw domError(name);
    };
    const notes: string[] = [];
    const n = (m: string): void => void notes.push(m);
    expect(await askForFile(refuse('AbortError'), { isActive: true }, 'x.zip', n)).toBe('cancelled');
    expect(await askForFile(refuse('SecurityError'), { isActive: true }, 'x.zip', n)).toBe('unavailable');
    expect(await askForFile(refuse('SecurityError'), undefined, 'x.zip', n)).toBe('unavailable'); // no activation API: cannot tell
    expect(await askForFile(refuse('NotAllowedError'), { isActive: false }, 'x.zip', n)).toBe('unavailable');
    expect(await askForFile(refuse('SecurityError'), { isActive: false }, 'x.zip', n)).toBe('expired');
    expect(notes.map((m) => (/expired/.test(m) ? 'expired' : /unavailable/.test(m) ? 'unavailable' : '?'))).toEqual(['unavailable', 'unavailable', 'unavailable', 'expired']);
    await expect(askForFile(refuse('TypeError'), { isActive: true }, 'x.zip', n)).rejects.toMatchObject({ name: 'TypeError' });
  });
});

describe('saveZip', () => {
  const run = (over: Partial<Parameters<typeof saveZip>[0]> = {}, notes: string[] = []) =>
    saveZip({ name: 'x.zip', files: tiny, predictedBytes: 10, signal: new AbortController().signal, onBytes: () => undefined, note: (m) => notes.push(m), ...over });

  test('through the picker', async () => {
    const env = stubBrowser({ picker: working, active: true });
    expect(await run()).toBe('saved');
    expect(env.writable.chunks).toBeGreaterThan(0);
    expect(env.downloads).toEqual([]);
  });

  test('a dismissed dialog is cancelled and reads nothing', async () => {
    stubBrowser({ picker: throwing('AbortError'), active: true });
    const files = vi.fn(tiny);
    expect(await run({ files })).toBe('cancelled');
    expect(files).not.toHaveBeenCalled();
  });

  test('SecurityError while the activation is alive: note, then the blob path', async () => {
    const env = stubBrowser({ picker: throwing('SecurityError'), active: true });
    const notes: string[] = [];
    expect(await run({}, notes)).toBe('saved');
    expect(notes).toEqual(['Save dialog unavailable (SecurityError); downloading instead.']);
    expect(env.downloads).toEqual(['clicked']);
  });

  test('SecurityError after the activation expired: nothing is read and nothing downloads', async () => {
    const env = stubBrowser({ picker: throwing('SecurityError'), active: false });
    const files = vi.fn(tiny);
    const notes: string[] = [];
    expect(await run({ files }, notes)).toBe('expired');
    expect(files).not.toHaveBeenCalled();
    expect(env.downloads).toEqual([]);
    expect(notes).toHaveLength(1);
    expect(notes[0]).toMatch(/expired/);
  });

  test('no picker at all goes to the blob path', async () => {
    const env = stubBrowser({});
    expect(await run()).toBe('saved');
    expect(env.downloads).toEqual(['clicked']);
  });

  test('declining the blob-path warning is cancelled and reads nothing', async () => {
    const env = stubBrowser({ confirm: false });
    const files = vi.fn(tiny);
    expect(await run({ files, predictedBytes: BLOB_WARN_BYTES + 1 })).toBe('cancelled');
    expect(files).not.toHaveBeenCalled();
    expect(env.downloads).toEqual([]);
  });

  test('accepting the blob-path warning downloads', async () => {
    const env = stubBrowser({ confirm: true });
    expect(await run({ predictedBytes: BLOB_WARN_BYTES + 1 })).toBe('saved');
    expect(env.downloads).toEqual(['clicked']);
  });

  /** A source whose second entry waits (like a running conversion) until the signal it was given aborts. */
  const slowSource = (): { files: (signal: AbortSignal) => ZipFiles; state: { aborted: boolean; started: boolean } } => {
    const state = { aborted: false, started: false };
    async function* entries(signal: AbortSignal): AsyncGenerator<{ name: string; input: Uint8Array; lastModified: Date }> {
      yield { name: 'a.bin', input: new Uint8Array(64 * 1024), lastModified: new Date() };
      state.started = true;
      await new Promise<never>((_, reject) => {
        const stop = (): void => {
          state.aborted = true;
          reject(domError('AbortError'));
        };
        if (signal.aborted) stop(); // like runDcm2niix: an already aborted signal stops it at once
        else signal.addEventListener('abort', stop);
      });
    }
    return { files: entries, state };
  };

  test('a write failure aborts the writable and the work behind the stream, and rejects promptly', async () => {
    const { files, state } = slowSource();
    const env = stubBrowser({ picker: working, active: true, failWhen: () => state.started });
    const started = Date.now();
    await expect(run({ files })).rejects.toThrow('disk full');
    expect(Date.now() - started).toBeLessThan(2000);
    expect(env.writable.aborted).toHaveLength(1);
    expect(state.aborted).toBe(true);
  });

  test('the caller aborting reaches the work behind the stream', async () => {
    stubBrowser({ picker: working, active: true });
    const ctl = new AbortController();
    const { files, state } = slowSource();
    const saving = run({ files, signal: ctl.signal });
    saving.catch(() => undefined);
    await vi.waitFor(() => expect(state.started).toBe(true));
    ctl.abort();
    await expect(saving).rejects.toMatchObject({ name: 'AbortError' });
    expect(state.aborted).toBe(true);
  });

  test('a blob-path failure aborts the work too', async () => {
    stubBrowser({});
    const { files, state } = slowSource();
    const ctl = new AbortController();
    const saving = run({ files, signal: ctl.signal });
    saving.catch(() => undefined);
    await vi.waitFor(() => expect(state.started).toBe(true));
    ctl.abort();
    await expect(saving).rejects.toMatchObject({ name: 'AbortError' });
    expect(state.aborted).toBe(true);
  });
});

describe('streamToBlob', () => {
  const streamOf = (chunks: Uint8Array[]): ReadableStream<Uint8Array> =>
    new ReadableStream({
      pull(controller) {
        const next = chunks.shift();
        if (next === undefined) controller.close();
        else controller.enqueue(next);
      },
    });

  test('folds chunks into intermediate Blobs every foldBytes; bytes and order are the stream\'s', async () => {
    const chunks = Array.from({ length: 10 }, (_, i) => new Uint8Array([i * 2, i * 2 + 1, 100 + i])); // 3 bytes each
    const made: number[] = [];
    const blob = await streamToBlob(streamOf(chunks.map((c) => c.slice())), 7, (parts) => {
      made.push(parts.length);
      return new Blob(parts);
    });
    // 3 bytes per chunk, folded at >= 7: three chunks (9 bytes) per fold, the last fold of one chunk, then the final Blob of the folds.
    expect(made).toEqual([3, 3, 3, 1, 4]);
    expect(new Uint8Array(await blob.arrayBuffer())).toEqual(new Uint8Array(chunks.flatMap((c) => [...c])));
  });

  test('an empty stream gives an empty Blob; an error rejects', async () => {
    expect((await streamToBlob(streamOf([]))).size).toBe(0);
    const failing = new ReadableStream<Uint8Array>({ pull: () => Promise.reject(new Error('boom')) });
    await expect(streamToBlob(failing)).rejects.toThrow('boom');
  });
});
