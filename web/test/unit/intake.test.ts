import { describe, expect, it } from 'vitest';
import { ENTRY_CONCURRENCY, MAX_DEPTH, joinPath, limiter, pickedFromFiles, walkEntries, walkHandle } from '../../src/shell/intake';
import type { DirEntryLike, DirHandleLike, EntryLike, FileEntryLike, FileHandleLike } from '../../src/shell/intake';

const file = (name: string): File => new File([name], name);

const fileEntry = (name: string, fail = false): FileEntryLike => ({
  isFile: true,
  isDirectory: false,
  name,
  file: (ok, err) => (fail ? err(new Error('boom')) : ok(file(name))),
});

/** A directory whose reader hands out `children` in batches of `batchSize`, then empty batches. */
const dirEntry = (name: string, children: EntryLike[], batchSize = 2, failAfter = Infinity) => {
  const calls = { n: 0 };
  const entry: DirEntryLike = {
    isFile: false,
    isDirectory: true,
    name,
    createReader: () => {
      let pos = 0;
      return {
        readEntries: (ok, err) => {
          calls.n++;
          if (pos >= failAfter) return err(new Error('read failed'));
          const batch = children.slice(pos, pos + batchSize);
          pos += batch.length;
          ok(batch);
        },
      };
    },
  };
  return { entry, calls };
};

describe('joinPath', () => {
  it('omits the separator for an empty prefix', () => {
    expect(joinPath('', 'a')).toBe('a');
    expect(joinPath('a/b', 'c')).toBe('a/b/c');
  });
});

describe('pickedFromFiles', () => {
  it('uses webkitRelativePath when set, else name', () => {
    const withRel = Object.assign(file('x.dcm'), {}) as File;
    Object.defineProperty(withRel, 'webkitRelativePath', { value: 'root/sub/x.dcm' });
    const flat = file('y.dcm');
    expect(pickedFromFiles([withRel, flat]).map((p) => p.relPath)).toEqual(['root/sub/x.dcm', 'y.dcm']);
  });
});

describe('walkEntries', () => {
  it('reads every batch until an empty one and builds relative paths', async () => {
    const sub = dirEntry('sub', [fileEntry('c')]);
    const children: EntryLike[] = [fileEntry('a'), fileEntry('b'), sub.entry, fileEntry('d'), fileEntry('e')];
    const top = dirEntry('root', children, 2);
    const out = await walkEntries([top.entry, fileEntry('loose.dcm')]);
    expect(out.errors).toBe(0);
    expect(out.files.map((f) => f.relPath).sort()).toEqual(
      ['loose.dcm', 'root/a', 'root/b', 'root/d', 'root/e', 'root/sub/c'].sort(),
    );
    // 5 children in batches of 2 -> 3 non-empty batches + the terminating empty one.
    expect(top.calls.n).toBe(4);
    expect(sub.calls.n).toBe(2);
  });

  it('counts and ignores failing entries', async () => {
    const top = dirEntry('d', [fileEntry('ok'), fileEntry('bad', true), fileEntry('ok2')]);
    const out = await walkEntries([top.entry]);
    expect(out.errors).toBe(1);
    expect(out.error).toBe('boom');
    expect(out.files.map((f) => f.relPath)).toEqual(['d/ok', 'd/ok2']);
  });

  it('keeps entries read before a reader failure and counts the failure', async () => {
    const top = dirEntry('d', [fileEntry('a'), fileEntry('b'), fileEntry('c')], 2, 2);
    const out = await walkEntries([top.entry]);
    expect(out.errors).toBe(1);
    expect(out.files.map((f) => f.relPath)).toEqual(['d/a', 'd/b']);
  });

  it('handles an empty directory', async () => {
    expect(await walkEntries([dirEntry('e', []).entry])).toEqual({ files: [], errors: 0 });
  });
});

const fh = (name: string, fail = false): FileHandleLike => ({
  kind: 'file',
  name,
  getFile: () => (fail ? Promise.reject(new Error('nope')) : Promise.resolve(file(name))),
});

describe('walkHandle', () => {
  const dh = (name: string, kids: (FileHandleLike | DirHandleLike)[]): DirHandleLike => ({
    kind: 'directory',
    name,
    values: async function* () {
      yield* kids;
    },
  });

  it('recurses, prefixes with the root name and counts errors', async () => {
    const out = await walkHandle(dh('root', [fh('a'), dh('sub', [fh('b'), fh('x', true)])]));
    expect(out.files.map((f) => f.relPath)).toEqual(['root/a', 'root/sub/b']);
    expect(out.errors).toBe(1);
  });
});

const bigFile = new File(['x'], 'f');
const N = 200_000;

describe('large inputs (no spread into call arguments)', () => {
  it('walkEntries: one readEntries batch of 200k entries', async () => {
    const kids: EntryLike[] = Array.from({ length: N }, (_, i) => ({
      isFile: true as const,
      isDirectory: false as const,
      name: `f${i}`,
      file: (ok: (f: File) => void) => ok(bigFile),
    }));
    const top = dirEntry('d', kids, N);
    const out = await walkEntries([top.entry]);
    expect(out.errors).toBe(0);
    expect(out.files).toHaveLength(N);
    expect(out.files[N - 1]!.relPath).toBe(`d/f${N - 1}`);
  }, 30_000);

  it('walkHandle: a 200k-file subtree', async () => {
    const files: FileHandleLike[] = Array.from({ length: N }, (_, i) => ({ kind: 'file', name: `f${i}`, getFile: () => Promise.resolve(bigFile) }));
    const sub: DirHandleLike = { kind: 'directory', name: 'sub', values: async function* () { yield* files; } };
    const root: DirHandleLike = { kind: 'directory', name: 'root', values: async function* () { yield sub; } };
    const out = await walkHandle(root);
    expect(out.errors).toBe(0);
    expect(out.files).toHaveLength(N);
  });
});

describe('walker options', () => {
  it('reports found counts', async () => {
    const seen: number[] = [];
    await walkEntries([dirEntry('d', [fileEntry('a'), fileEntry('b'), fileEntry('c')]).entry], { onFound: (n) => seen.push(n) });
    expect(seen).toEqual([1, 2, 3]);
  });

  it('stops on abort', async () => {
    const ctl = new AbortController();
    ctl.abort();
    expect((await walkEntries([fileEntry('a')], { signal: ctl.signal })).files).toEqual([]);
  });

  it('counts entries nested deeper than MAX_DEPTH as errors', async () => {
    let entry: EntryLike = fileEntry('leaf');
    for (let i = 0; i < MAX_DEPTH + 2; i++) entry = dirEntry(`d${i}`, [entry]).entry;
    const out = await walkEntries([entry]);
    expect(out.files).toEqual([]);
    expect(out.errors).toBe(1);
    expect(out.error).toMatch(/deeper/);
  });

  it('walkHandle caps depth too', async () => {
    let inner: DirHandleLike = { kind: 'directory', name: 'leafdir', values: async function* () { yield fh('x'); } };
    for (let i = 0; i < MAX_DEPTH + 2; i++) {
      const child = inner;
      inner = { kind: 'directory', name: `d${i}`, values: async function* () { yield child; } };
    }
    const out = await walkHandle(inner);
    expect(out.files).toEqual([]);
    expect(out.errors).toBe(1);
  });

  it('reports the root failure as the error', async () => {
    const root: DirHandleLike = { kind: 'directory', name: 'r', values: () => { throw new Error('denied'); } };
    expect(await walkHandle(root)).toEqual({ files: [], errors: 1, error: 'denied' });
  });

  it('limits concurrent entry callbacks', async () => {
    let active = 0;
    let peak = 0;
    const kids: FileEntryLike[] = Array.from({ length: 500 }, (_, i) => ({
      isFile: true,
      isDirectory: false,
      name: `f${i}`,
      file: (ok) => {
        active++;
        peak = Math.max(peak, active);
        setTimeout(() => {
          active--;
          ok(bigFile);
        }, 0);
      },
    }));
    await walkEntries([dirEntry('d', kids, 500).entry]);
    expect(peak).toBeLessThanOrEqual(ENTRY_CONCURRENCY);
    expect(peak).toBeGreaterThan(1);
  });
});

describe('limiter', () => {
  it('never exceeds n and runs everything', async () => {
    const limit = limiter(3);
    let active = 0;
    let peak = 0;
    const results = await Promise.all(
      Array.from({ length: 20 }, (_, i) =>
        limit(async () => {
          peak = Math.max(peak, ++active);
          await new Promise((r) => setTimeout(r, 1));
          active--;
          return i;
        }),
      ),
    );
    expect(peak).toBe(3);
    expect(results).toEqual(Array.from({ length: 20 }, (_, i) => i));
  });
});

describe('abort mid-walk', () => {
  it('stops calling file() for entries queued before the abort', async () => {
    const ctl = new AbortController();
    let calls = 0;
    const kids: FileEntryLike[] = Array.from({ length: 5000 }, (_, i) => ({
      isFile: true,
      isDirectory: false,
      name: `f${i}`,
      file: (ok) => {
        if (++calls === 100) ctl.abort();
        setTimeout(() => ok(bigFile), 0);
      },
    }));
    await walkEntries([dirEntry('d', kids, 5000).entry], { signal: ctl.signal });
    expect(calls).toBeLessThan(100 + ENTRY_CONCURRENCY + 1);
  });

  it('stops reading batches after an abort', async () => {
    const ctl = new AbortController();
    let reads = 0;
    const entry: DirEntryLike = {
      isFile: false,
      isDirectory: true,
      name: 'd',
      createReader: () => ({
        readEntries: (ok) => {
          if (++reads === 5) ctl.abort();
          ok([fileEntry(`f${reads}`)]);
        },
      }),
    };
    await walkEntries([entry], { signal: ctl.signal });
    expect(reads).toBe(5);
  });
});
