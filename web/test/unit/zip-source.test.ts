import { readFileSync } from 'node:fs';
import { deflateRawSync } from 'node:zlib';
import { describe, expect, test } from 'vitest';
import { crc32 } from '../../src/core/crc32';
import type { ZipEntryInfo } from '../../src/core/zipdir';
import { scan } from '../../src/shell/scan';
import { PUSH_BYTES, canInflate, readArchive, zipEntrySource } from '../../src/shell/zip-source';
import type { ArchiveBlob } from '../../src/shell/zip-source';
import { buildZip, extraField, randomBytes } from './zip-bytes';
import type { Spec } from './zip-bytes';

/** A Blob wrapper that records every range sliced from it. */
const spy = (bytes: Uint8Array<ArrayBuffer>) => {
  const blob = new Blob([bytes]);
  const slices: [number, number][] = [];
  const archive: ArchiveBlob = {
    size: blob.size,
    slice: (start, end) => {
      slices.push([start, end]);
      return blob.slice(start, end);
    },
  };
  return { archive, slices, requested: () => slices.reduce((n, [a, b]) => n + (b - a), 0) };
};

const open = async (specs: Spec[], index = 0) => {
  const built = buildZip(specs);
  const s = spy(built.bytes);
  const dir = await readArchive(s.archive);
  if (!dir.ok) throw new Error(dir.error);
  s.slices.length = 0;
  const entry = dir.entries[index]!;
  return { ...s, entry, built, source: zipEntrySource(s.archive, entry) };
};

const text = new TextEncoder().encode('0123456789'.repeat(100));
const same = (a: Uint8Array | ArrayBuffer, b: Uint8Array): boolean => Buffer.from(a instanceof ArrayBuffer ? new Uint8Array(a) : a).equals(b);
const drain = async (stream: ReadableStream<Uint8Array>): Promise<Uint8Array> => new Uint8Array(await new Response(stream).arrayBuffer());

describe('stored entries', () => {
  test('are exact slices of the archive: header (30 bytes) once, then only the requested range', async () => {
    const { source, slices, built } = await open([{ name: 'pad', data: randomBytes(500, 1) }, { name: 'a', data: text, method: 0 }], 1);
    const at = built.offsets[1]!;
    expect(source.size).toBe(text.length);
    expect(source.name).toBe('a');

    expect(same(await source.readPrefix(64), text.subarray(0, 64))).toBe(true);
    const dataStart = at + 30 + 1;
    expect(slices).toEqual([
      [at, at + 30],
      [dataStart, dataStart + 64],
    ]);

    expect(same(await source.readPrefix(10_000), text)).toBe(true); // more than there is: clamped
    expect(slices.slice(2)).toEqual([[dataStart, dataStart + text.length]]); // the local header is not read again
  });

  test('the local header may have other lengths than the central one', async () => {
    const { source } = await open([{ name: 'a', data: text, method: 0, localExtra: extraField(0xcafe, new Uint8Array(40)) }]);
    expect(same(await source.bytes(), text)).toBe(true);
  });

  test('bytes() and stream()', async () => {
    const { source } = await open([{ name: 'a', data: text, method: 0 }]);
    expect(same(await source.bytes(), text)).toBe(true);
    expect(same(await drain(source.stream()), text)).toBe(true);
  });

  test('an empty entry', async () => {
    const { source } = await open([{ name: 'a' }]);
    expect((await source.readPrefix(10)).length).toBe(0);
    expect((await source.bytes()).byteLength).toBe(0);
    expect((await drain(source.stream())).length).toBe(0);
  });
});

describe('deflated entries', () => {
  test('bytes(), stream() and readPrefix() return the original', async () => {
    const data = randomBytes(300_000, 2);
    const { source } = await open([{ name: 'a', data }]);
    expect(same(await source.bytes(), data)).toBe(true);
    expect(same(await drain(source.stream()), data)).toBe(true);
    expect(same(await source.readPrefix(70_000), data.subarray(0, 70_000))).toBe(true);
    expect(same(await source.readPrefix(10_000_000), data)).toBe(true); // clamped to the entry size
  });

  test('readPrefix does not read the whole entry: compressed bytes read stay within a small multiple of the prefix', async () => {
    const data = randomBytes(3_000_000, 3); // incompressible: ~3 MB compressed
    const { source, entry, requested, slices } = await open([{ name: 'a', data }]);
    expect(entry.compressedSize).toBeGreaterThan(2_900_000);
    expect(same(await source.readPrefix(65_536), data.subarray(0, 65_536))).toBe(true);
    const limit = 30 + 2 * 65_536 + 64 * 1024 + PUSH_BYTES; // header + cap (+ one piece in flight)
    expect(requested()).toBeLessThanOrEqual(limit);
    expect(requested()).toBeLessThan(entry.compressedSize / 10);
    expect(slices.every(([a, b]) => b - a <= PUSH_BYTES || b - a === 30)).toBe(true);

    slices.length = 0;
    expect(same(await source.readPrefix(1_048_576), data.subarray(0, 1_048_576))).toBe(true);
    expect(requested()).toBeLessThanOrEqual(2 * 1_048_576 + 64 * 1024 + PUSH_BYTES);
  }, 20_000);

  test('a deflate bomb costs a prefix, not its size', async () => {
    const huge = 192 * 1024 * 1024;
    const zeros = Buffer.alloc(huge);
    const packed = deflateRawSync(zeros);
    expect(packed.length).toBeLessThan(huge / 500);
    // Build the archive by hand: the central directory declares the true (huge) size.
    const built = buildZip([{ name: 'bomb', data: new Uint8Array(1), method: 0 }]);
    const s = spy(built.bytes);
    const dir = await readArchive(s.archive);
    if (!dir.ok) throw new Error(dir.error);
    const asBomb: ZipEntryInfo = { ...dir.entries[0]!, method: 8, size: huge, compressedSize: packed.length };
    // Swap the data: a Blob of [local header | bomb].
    const head = built.bytes.slice(0, 30 + 4);
    const blob = new Blob([head, packed]);
    const slices: [number, number][] = [];
    const archive: ArchiveBlob = { size: blob.size, slice: (a, b) => (slices.push([a, b]), blob.slice(a, b)) };
    const src = zipEntrySource(archive, asBomb);
    const t0 = performance.now();
    const prefix = await src.readPrefix(65_536);
    expect(prefix.length).toBe(65_536);
    expect(prefix.every((b) => b === 0)).toBe(true);
    expect(performance.now() - t0).toBeLessThan(5000);
    expect(slices.reduce((n, [a, b]) => n + b - a, 0)).toBeLessThanOrEqual(30 + packed.length);
    // The full read refuses to go past the declared size when it is lying low.
    const liar = zipEntrySource(archive, { ...asBomb, size: 1000 });
    await expect(liar.bytes()).rejects.toThrow(/larger than its declared size/);
  }, 20_000);

  test('an archive cut off inside the entry data is refused up front', async () => {
    const data = randomBytes(5000, 4);
    const { built, entry } = await open([{ name: 'a', data }]);
    const cut = built.bytes.slice(0, built.offsets[0]! + 30 + 1 + 2000); // data cut short, directory gone
    const blob = new Blob([cut]);
    const src = zipEntrySource({ size: blob.size, slice: (a, b) => blob.slice(a, b) }, entry);
    await expect(src.bytes()).rejects.toThrow(/past the end/);
    await expect(src.readPrefix(10)).rejects.toThrow(/past the end/);
  });

  test('a truncated deflate stream (the directory says it is shorter than it is): a prefix inside it works, one past it and bytes() reject', async () => {
    const data = randomBytes(5000, 4);
    const { source } = await open([{ name: 'a', data, central: { csize: 2000 } }]);
    expect(same(await source.readPrefix(100), data.subarray(0, 100))).toBe(true);
    await expect(source.readPrefix(4000)).rejects.toBeDefined();
    await expect(source.readPrefix(5000)).rejects.toBeDefined();
    await expect(source.bytes()).rejects.toBeDefined();
  });

  test('corrupt deflate data is an error', async () => {
    const data = randomBytes(5000, 6);
    const { built, entry } = await open([{ name: 'a', data }]);
    const bad = built.bytes.slice();
    for (let i = 0; i < 40; i++) bad[built.offsets[0]! + 36 + i] = ~bad[built.offsets[0]! + 36 + i]! & 0xff;
    const blob = new Blob([bad]);
    const src = zipEntrySource({ size: blob.size, slice: (a, b) => blob.slice(a, b) }, entry);
    await expect(src.bytes()).rejects.toBeDefined();
  });
});

describe('integrity', () => {
  test.each([0, 8])('method %i: a wrong CRC-32 fails bytes() and stream(), naming the entry; a prefix does not check it', async (method) => {
    const { source } = await open([{ name: 'dir/a', data: text, method, central: { crc: crc32(text) ^ 1 } }]);
    await expect(source.bytes()).rejects.toThrow(/CRC-32 mismatch in entry dir\/a/);
    await expect(drain(source.stream())).rejects.toThrow(/CRC-32 mismatch in entry dir\/a/);
    expect((await source.readPrefix(20)).length).toBe(20);
  });

  test('a stored entry whose sizes disagree is refused', async () => {
    const { source } = await open([{ name: 'a', data: text, method: 0, central: { size: text.length - 1 } }]);
    await expect(source.bytes()).rejects.toThrow(/inconsistent sizes/);
  });

  test('a deflated entry that is shorter or longer than declared is refused (all read paths)', async () => {
    const shortOne = await open([{ name: 'a', data: text, method: 8, central: { size: text.length + 5 } }]);
    await expect(shortOne.source.bytes()).rejects.toThrow(/not the declared/);
    await expect(drain(shortOne.source.stream())).rejects.toThrow(/not the declared/);
    await expect(shortOne.source.readPrefix(text.length + 5)).rejects.toThrow(/ends after \d+ bytes/);
    const longOne = await open([{ name: 'a', data: text, method: 8, central: { size: 10 } }]);
    await expect(longOne.source.bytes()).rejects.toThrow(/larger than its declared size/);
    await expect(drain(longOne.source.stream())).rejects.toThrow(/larger than its declared size/);
  });

  test('no local header where the directory says: a clear error, and a later call retries', async () => {
    const built = buildZip([{ name: 'a', data: text, method: 0 }]);
    const dir = await readArchive(spy(built.bytes).archive);
    if (!dir.ok) throw new Error(dir.error);
    const bad = built.bytes.slice();
    bad[0] = 0;
    let blob = new Blob([bad]);
    const archive: ArchiveBlob = { size: bad.length, slice: (a, b) => blob.slice(a, b) };
    const src = zipEntrySource(archive, dir.entries[0]!);
    await expect(src.readPrefix(5)).rejects.toThrow(/no local file header/);
    blob = new Blob([built.bytes]); // the failure was not cached
    expect(same(await src.readPrefix(5), text.subarray(0, 5))).toBe(true);
  });

  test('encrypted and unsupported entries cannot be read', async () => {
    const enc = await open([{ name: 'a', data: text, flags: 1 }]);
    await expect(enc.source.bytes()).rejects.toThrow(/encrypted/);
    const bz = await open([{ name: 'a', data: text, method: 12 }]);
    await expect(bz.source.readPrefix(5)).rejects.toThrow(/method 12/);
  });

  test('canInflate is true here', () => expect(canInflate()).toBe(true));
});

describe('stream()', () => {
  test('cancelling after the first chunk: the stream ends and no further slice of the archive is requested', async () => {
    const data = randomBytes(2_000_000, 8);
    const { source, slices } = await open([{ name: 'a', data }]);
    const reader = source.stream().getReader();
    expect((await reader.read()).done).toBe(false);
    await reader.cancel();
    const after = slices.length;
    expect((await reader.read()).done).toBe(true);
    await new Promise((r) => setTimeout(r, 50));
    expect(slices.length).toBe(after);
  });

  test('cancelling before the first read requests nothing', async () => {
    const { source, slices } = await open([{ name: 'a', data: text }]);
    await source.stream().cancel();
    expect(slices).toEqual([]);
  });
});

describe('reads that fail while an entry is being read', () => {
  /** An archive whose slices fail (`arrayBuffer` rejects, `stream` errors) from the `failFrom`-th slice() call on. */
  const flaky = async (data: Uint8Array<ArrayBuffer>, method: number) => {
    const built = buildZip([{ name: 'a', data, method }]);
    const blob = new Blob([built.bytes]);
    let calls = 0;
    let failFrom = Infinity;
    const fail = () => new DOMException('file changed', 'NotReadableError');
    const archive: ArchiveBlob = {
      size: blob.size,
      slice: (a, b) => {
        if (++calls < failFrom) return blob.slice(a, b);
        return {
          arrayBuffer: () => Promise.reject(fail()),
          stream: () => new ReadableStream({ start: (c) => c.error(fail()) }),
        } as unknown as Blob;
      },
    };
    const dir = await readArchive(archive);
    if (!dir.ok) throw new Error(dir.error);
    const source = zipEntrySource(archive, dir.entries[0]!);
    return {
      source,
      /** The n-th slice() call from now on (1 = the local header) fails. */
      failAt: (n: number) => {
        calls = 0;
        failFrom = n;
      },
    };
  };
  const settles = <T>(p: Promise<T>) => Promise.race([p.then(() => 'resolved', (e: unknown) => e), new Promise((r) => setTimeout(() => r('HUNG'), 3000))]);

  test('deflated prefix: a failing first data piece rejects (does not hang, is not a short result)', async () => {
    const { source, failAt } = await flaky(randomBytes(300_000, 9), 8);
    failAt(2); // the local header (call 1) reads fine, the first data piece fails
    const r = await settles(source.readPrefix(65_536));
    expect(r).toMatchObject({ name: 'NotReadableError' });
  });

  test('deflated prefix: a failing later piece rejects too', async () => {
    const { source, failAt } = await flaky(randomBytes(300_000, 9), 8);
    failAt(4);
    expect(await settles(source.readPrefix(65_536))).toMatchObject({ name: 'NotReadableError' });
  });

  test('stored prefix, bytes() and stream() reject with the read error', async () => {
    const { source, failAt } = await flaky(randomBytes(10_000, 9), 0);
    failAt(2);
    expect(await settles(source.readPrefix(100))).toMatchObject({ name: 'NotReadableError' });
    expect(await settles(source.bytes())).toMatchObject({ name: 'NotReadableError' });
    expect(await settles(drain(source.stream()))).toMatchObject({ name: 'NotReadableError' });
  });

  test.each([2, 4])('scan reports the entry as unreadable with the read error (piece %i fails)', async (n) => {
    const { source, failAt } = await flaky(randomBytes(300_000, 9), 8);
    failAt(n);
    const res = await scan([{ source, relPath: 'x.zip/a' }], { signal: new AbortController().signal, onProgress: () => undefined });
    expect(res!.instances).toEqual([]);
    expect(res!.skipped).toEqual([{ relPath: 'x.zip/a', reason: 'unreadable', detail: 'file changed' }]);
  });
});

describe('prefix reads of damaged deflate data', () => {
  test('corruption inside the capped window rejects instead of returning a short prefix', async () => {
    const data = randomBytes(2_000_000, 9);
    const built = buildZip([{ name: 'a', data }]);
    const bad = built.bytes.slice();
    for (let i = 0; i < 4000; i++) bad[31 + 30_000 + i] = 0xff;
    const good = new Blob([built.bytes]);
    const dir = await readArchive({ size: good.size, slice: (a, b) => good.slice(a, b) });
    if (!dir.ok) throw new Error(dir.error);
    const blob = new Blob([bad]);
    const src = zipEntrySource({ size: blob.size, slice: (a, b) => blob.slice(a, b) }, dir.entries[0]!);
    await expect(src.readPrefix(65_536)).rejects.toBeDefined();
    await expect(src.readPrefix(1_048_576)).rejects.toBeDefined();
    await expect(src.bytes()).rejects.toBeDefined();
  });

  test('data that ends (cleanly) before the requested prefix, with the input cut at our own cap, rejects', async () => {
    // The directory claims 3 MB but the deflate stream holds 100 KB: any prefix past 100 KB is an error, never 100 KB.
    const data = randomBytes(100_000, 3);
    const { entry, built } = await open([{ name: 'a', data }]);
    const blob = new Blob([built.bytes]);
    const lie: typeof entry = { ...entry, size: 3_000_000 };
    const src = zipEntrySource({ size: blob.size, slice: (a, b) => blob.slice(a, b) }, lie);
    expect(same(await src.readPrefix(50_000), data.subarray(0, 50_000))).toBe(true);
    await expect(src.readPrefix(200_000)).rejects.toThrow(/ends after 100000 bytes/);
  });
});

describe('data descriptors (flag bit 3: zero CRC and sizes in the local header)', () => {
  const data = randomBytes(200_000, 12);
  for (const method of [0, 8]) {
    test(`method ${method}: readPrefix, bytes and stream use the central directory's sizes`, async () => {
      const { source } = await open([{ name: 'a', data, method, dataDescriptor: true }]);
      expect(same(await source.readPrefix(70_000), data.subarray(0, 70_000))).toBe(true);
      expect(same(await source.bytes(), data)).toBe(true);
      expect(same(await drain(source.stream()), data)).toBe(true);
    });
  }
});

describe('the committed fixture archive', () => {
  test('every DICOM entry equals its tree file (CRC-verified through bytes())', async () => {
    const dir = new URL('../fixtures/', import.meta.url);
    const manifest = JSON.parse(readFileSync(new URL('zips/export.manifest.json', dir), 'utf8')) as { entries: { name: string; method: string; source: string | null }[] };
    const bytes = readFileSync(new URL('zips/export.zip', dir));
    const blob = new Blob([bytes]);
    const archive: ArchiveBlob = { size: blob.size, slice: (a, b) => blob.slice(a, b) };
    const listing = await readArchive(archive);
    if (!listing.ok) throw new Error(listing.error);
    let checked = 0;
    for (const e of listing.entries.filter((x) => !x.isDir)) {
      const m = manifest.entries.find((x) => x.name === e.name || x.name === `${e.name}`)!;
      expect(m, e.name).toBeDefined();
      if (m.source === null) continue;
      const src = zipEntrySource(archive, e);
      const want = readFileSync(new URL(`tree/${m.source}`, dir));
      expect(Buffer.from(await src.bytes()).equals(want), e.name).toBe(true);
      expect(Buffer.from(await src.readPrefix(100)).equals(want.subarray(0, 100)), e.name).toBe(true);
      expect(Buffer.from(await drain(src.stream())).equals(want), e.name).toBe(true);
      checked++;
    }
    expect(checked).toBe(21);
  });
});
