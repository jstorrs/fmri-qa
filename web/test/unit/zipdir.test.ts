import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';
import { crc32 } from '../../src/core/crc32';
import {
  EOCD_SEARCH_BYTES,
  MAX_DIRECTORY_BYTES,
  MAX_ENTRIES,
  TAIL_BYTES,
  dosToMillis,
  findEnd,
  hasZipMagic,
  localDataOffset,
  normalizeEntryName,
  parseCentralDirectory,
  parseEocd64,
  readZipDirectory,
} from '../../src/core/zipdir';
import type { ReadRange, ZipEntryInfo } from '../../src/core/zipdir';
import { buildZip, cat, centralRecord, dos, eocd, eocd64, extraField, locator64, prng, randomBytes, u16, u32, u64 } from './zip-bytes';

/** Serve ranges of an in-memory archive and record them. */
const reader = (bytes: Uint8Array) => {
  const reads: [number, number][] = [];
  const read: ReadRange = async (start, end) => {
    reads.push([start, end]);
    return bytes.slice(start, end);
  };
  return { read, reads };
};

/** A huge archive that exists only as a few byte segments; everything else reads as zeros. */
const sparse = (segments: { start: number; bytes: Uint8Array }[], log: [number, number][] = []): ReadRange => async (start, end) => {
  log.push([start, end]);
  const out = new Uint8Array(end - start);
  for (const s of segments) {
    const from = Math.max(start, s.start);
    const to = Math.min(end, s.start + s.bytes.length);
    if (from < to) out.set(s.bytes.subarray(from - s.start, to - s.start), from - start);
  }
  return out;
};

const list = async (bytes: Uint8Array) => readZipDirectory(bytes.length, reader(bytes).read);

const entriesOf = async (bytes: Uint8Array): Promise<readonly ZipEntryInfo[]> => {
  const r = await list(bytes);
  if (!r.ok) throw new Error(r.error);
  return r.entries;
};

const hello = new TextEncoder().encode('hello hello hello hello hello');

describe('stored and deflated entries', () => {
  test('fields of each entry', async () => {
    const built = buildZip([
      { name: 'a.txt', data: hello, method: 0 },
      { name: 'dir/b.txt', data: hello, method: 8 },
      { name: 'empty', data: new Uint8Array(0) },
    ]);
    const e = await entriesOf(built.bytes);
    expect(e).toHaveLength(3);
    expect(e[0]).toMatchObject({
      name: 'a.txt',
      method: 0,
      size: hello.length,
      compressedSize: hello.length,
      localHeaderOffset: built.offsets[0],
      crc32: crc32(hello),
      encrypted: false,
      isDir: false,
    });
    expect(e[1]).toMatchObject({ name: 'dir/b.txt', method: 8, size: hello.length, localHeaderOffset: built.offsets[1], crc32: crc32(hello) });
    expect(e[1]!.compressedSize).toBeGreaterThan(0);
    expect(e[2]).toMatchObject({ name: 'empty', method: 0, size: 0, isDir: false });
  });

  test('an empty archive (only the EOCD) has no entries', async () => {
    expect(await entriesOf(eocd(0, 0, 0))).toEqual([]);
  });

  test('the committed fixture archive agrees with its manifest', async () => {
    const dir = new URL('../fixtures/zips/', import.meta.url);
    const manifest = JSON.parse(readFileSync(new URL('export.manifest.json', dir), 'utf8')) as { entries: { name: string; method: string }[] };
    const e = await entriesOf(readFileSync(new URL('export.zip', dir)));
    expect(e.map((x) => (x.isDir ? `${x.name}/` : x.name))).toEqual(manifest.entries.map((x) => x.name));
    expect(e.map((x) => (x.isDir ? 'dir' : x.method === 0 ? 'stored' : 'deflated'))).toEqual(manifest.entries.map((x) => x.method));
    expect(e.some((x) => x.name === 'DICOM/Müller_Jürgen/IM0001')).toBe(true);
  });

  test('a short archive is read with one ranged read (the central directory lies inside the tail)', async () => {
    const built = buildZip([{ name: 'a', data: hello }]);
    const { read, reads } = reader(built.bytes);
    expect((await readZipDirectory(built.bytes.length, read)).ok).toBe(true);
    expect(reads).toEqual([[0, built.bytes.length]]);
  });

  test('a large directory needs a second ranged read, and the tail is never more than TAIL_BYTES', async () => {
    const specs = Array.from({ length: 2500 }, (_, i) => ({ name: `d/entry-${i}.dcm`, data: new Uint8Array(0) }));
    const built = buildZip(specs);
    expect(built.cdSize).toBeGreaterThan(TAIL_BYTES);
    const { read, reads } = reader(built.bytes);
    const r = await readZipDirectory(built.bytes.length, read);
    expect(r.ok && r.entries.length).toBe(2500);
    expect(reads).toEqual([
      [built.bytes.length - TAIL_BYTES, built.bytes.length],
      [built.cdOffset, built.cdOffset + built.cdSize],
    ]);
  });

  test('100,000 entries', async () => {
    const records = Array.from({ length: 100_000 }, (_, i) =>
      centralRecord({ nameBytes: new TextEncoder().encode(`DICOM/${i % 977}/IM${i}`), csize: 100, size: 200, offset: i * 150 }),
    );
    const cd = cat(...records);
    const bytes = cat(new Uint8Array(150 * 100_000), cd, eocd(0xffff, cd.length, 150 * 100_000)); // the 16-bit count wrapped (older writers)
    const e = await entriesOf(bytes);
    expect(e).toHaveLength(100_000);
    expect(e[99_999]).toMatchObject({ name: 'DICOM/' + (99_999 % 977) + '/IM99999', localHeaderOffset: 99_999 * 150 });
  });
});

describe('entry names', () => {
  test('UTF-8 when flag bit 11 is set', async () => {
    const [e] = await entriesOf(buildZip([{ name: 'Müller/日本.dcm', flags: 0x800 }]).bytes);
    expect(e!.name).toBe('Müller/日本.dcm');
  });

  test('CP437 otherwise (the ZIP default): bytes 0x81 0x84 0x94 0xE1 are ü ä ö ß', async () => {
    const [e] = await entriesOf(buildZip([{ name: new Uint8Array([0x81, 0x84, 0x94, 0xe1, 0x2f, 0x41]) }]).bytes);
    expect(e!.name).toBe('üäöß/A');
  });

  test('the whole CP437 upper half decodes (spot checks)', async () => {
    const all = Uint8Array.from({ length: 128 }, (_, i) => 0x80 + i);
    const [e] = await entriesOf(buildZip([{ name: all }]).bytes);
    expect(e!.name).toHaveLength(128);
    expect([...e!.name].slice(0, 3)).toEqual(['Ç', 'ü', 'é']);
    expect(e!.name[127]).toBe('\u00a0');
    expect(e!.name[0x9b - 0x80]).toBe('¢');
    expect(e!.name[0xe3 - 0x80]).toBe('π');
  });

  test('an Info-ZIP Unicode Path extra field (0x7075) wins when its CRC matches the header name', async () => {
    const raw = new Uint8Array([0x81, 0x2e, 0x74]); // cp437 "ü.t"
    const good = extraField(0x7075, cat([1], u32(crc32(raw)), new TextEncoder().encode('ü-unicode.t')));
    const [e] = await entriesOf(buildZip([{ name: raw, extra: good }]).bytes);
    expect(e!.name).toBe('ü-unicode.t');
  });

  test('a stale 0x7075 field (CRC of another name) is ignored', async () => {
    const raw = new Uint8Array([0x81, 0x2e, 0x74]);
    const stale = extraField(0x7075, cat([1], u32(crc32(new Uint8Array([1, 2, 3]))), new TextEncoder().encode('wrong')));
    const [e] = await entriesOf(buildZip([{ name: raw, extra: stale }]).bytes);
    expect(e!.name).toBe('ü.t');
  });

  test('normalizeEntryName: no absolute paths, drive letters, "." or ".." segments, backslashes or control characters', () => {
    expect(normalizeEntryName('../../etc/passwd')).toBe('etc/passwd');
    expect(normalizeEntryName('/abs/path/x')).toBe('abs/path/x');
    expect(normalizeEntryName('C:\\Windows\\x.dcm')).toBe('Windows/x.dcm');
    expect(normalizeEntryName('a/./b//c/')).toBe('a/b/c');
    expect(normalizeEntryName('a/../b')).toBe('a/b'); // dropped, not resolved: display text only
    expect(normalizeEntryName('bad\u0000name\n.dcm')).toBe('bad_name_.dcm');
    expect(normalizeEntryName('..')).toBe('');
    expect(normalizeEntryName('plain')).toBe('plain');
  });

  test('hostile names come out normalized from a real directory', async () => {
    const e = await entriesOf(buildZip([{ name: '../../evil.dcm' }, { name: '/etc/x' }, { name: 'a\\b\\c.dcm' }]).bytes);
    expect(e.map((x) => x.name)).toEqual(['evil.dcm', 'etc/x', 'a/b/c.dcm']);
  });
});

describe('flags and methods', () => {
  test('encrypted: bit 0 (and bit 6, strong encryption)', async () => {
    const e = await entriesOf(buildZip([{ name: 'a', flags: 1 }, { name: 'b', flags: 0x40 }, { name: 'c', flags: 0x800 }]).bytes);
    expect(e.map((x) => x.encrypted)).toEqual([true, true, false]);
  });

  test('other methods are reported as they are (the caller decides): bzip2 12, AES 99', async () => {
    const e = await entriesOf(buildZip([{ name: 'a', method: 12, data: hello }, { name: 'b', method: 99, data: hello }]).bytes);
    expect(e.map((x) => x.method)).toEqual([12, 99]);
  });

  test('directories: trailing slash (or backslash), and names that normalize to nothing', async () => {
    const e = await entriesOf(buildZip([{ name: 'DICOM/' }, { name: 'a\\b\\' }, { name: '../' }, { name: 'file' }]).bytes);
    expect(e.map((x) => [x.name, x.isDir])).toEqual([
      ['DICOM', true],
      ['a/b', true],
      ['', true],
      ['file', false],
    ]);
  });

  test('DOS date and time', async () => {
    const { date, time } = dos(2026, 3, 14, 15, 9, 26);
    const [e] = await entriesOf(buildZip([{ name: 'a', date, time }]).bytes);
    expect(e!.lastModified).toBe(new Date(2026, 2, 14, 15, 9, 26).getTime());
    expect(dosToMillis(0, 0)).toBe(new Date(1980, 0, 1).getTime()); // month 0, day 0: invalid
    expect(dosToMillis(dos(2026, 1, 1).date, 31 << 11)).toBe(new Date(1980, 0, 1).getTime()); // hour 31
  });
});

describe('ZIP64', () => {
  test('a real archive written with ZIP64 records and extra fields lists correctly', async () => {
    const built = buildZip([{ name: 'a', data: hello, method: 0 }, { name: 'b', data: hello }], { zip64: true });
    const e = await entriesOf(built.bytes);
    expect(e.map((x) => [x.name, x.size, x.localHeaderOffset])).toEqual([
      ['a', hello.length, built.offsets[0]],
      ['b', hello.length, built.offsets[1]],
    ]);
  });

  test('findEnd on tail bytes alone: EOCD with a ZIP64 locator points at the record', () => {
    const recordAt = 5_000_000_100;
    const tail = cat(locator64(recordAt), cat(u32(0x06054b50), u16(0), u16(0), u16(0xffff), u16(0xffff), u32(0xffffffff), u32(0xffffffff), u16(0)));
    expect(findEnd(tail, 6_000_000_000)).toEqual({ ok: true, value: { zip64: true, recordOffset: recordAt } });
  });

  test('parseEocd64 reads 64-bit count, size and offset', () => {
    expect(parseEocd64(eocd64(70_000, 6_000_000, 5_000_000_000))).toEqual({ ok: true, value: { count: 70_000, cdSize: 6_000_000, cdOffset: 5_000_000_000 } });
    expect(parseEocd64(new Uint8Array(56)).ok).toBe(false);
  });

  test('a 6 GB archive described by its tail only (sparse: no real data exists anywhere)', async () => {
    const size = 6_000_000_000;
    const big = 4_500_000_000;
    // Entry 0 lives past 4 GB: its size, compressed size and local-header offset only fit in the ZIP64 extra field.
    const cd = cat(
      centralRecord({ nameBytes: new TextEncoder().encode('big/IM0001'), csize: big, size: big + 7, offset: 4_700_000_000, zip64: true, crc: 0xdeadbeef, method: 8 }),
      centralRecord({ nameBytes: new TextEncoder().encode('small'), csize: 10, size: 10, offset: 12 }),
    );
    const eocd32 = cat(u32(0x06054b50), u16(0), u16(0), u16(0xffff), u16(0xffff), u32(0xffffffff), u32(0xffffffff), u16(0));
    const cdOffset = size - (cd.length + 56 + 20 + eocd32.length);
    const recordAt = cdOffset + cd.length;
    const tail = cat(eocd64(2, cd.length, cdOffset), locator64(recordAt), eocd32);
    const reads: [number, number][] = [];
    const read = sparse([{ start: cdOffset, bytes: cat(cd, tail) }], reads);
    const r = await readZipDirectory(size, read);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.entries[0]).toMatchObject({ name: 'big/IM0001', compressedSize: big, size: big + 7, localHeaderOffset: 4_700_000_000, crc32: 0xdeadbeef, method: 8 });
    expect(r.entries[1]).toMatchObject({ name: 'small', size: 10, localHeaderOffset: 12 });
    expect(reads.every(([a, b]) => b - a <= TAIL_BYTES)).toBe(true);
    expect(reads).toHaveLength(1); // the tail holds the locator, the ZIP64 record and the directory
  });

  test('a ZIP64 record far from the tail needs its own read', async () => {
    const size = 7_000_000_000;
    const recordAt = 3_000_000_000; // extensible data between the record and the locator
    const cdOffset = 3_000_000_100;
    const cd = centralRecord({ nameBytes: new TextEncoder().encode('x'), csize: 1, size: 1, offset: 0 });
    const record = eocd64(1, cd.length, cdOffset);
    const eocdBytes = cat(u32(0x06054b50), u16(0), u16(0), u16(0xffff), u16(0xffff), u32(0xffffffff), u32(0xffffffff), u16(0));
    const tail = cat(locator64(recordAt), eocdBytes);
    const reads: [number, number][] = [];
    const read = sparse(
      [
        { start: size - tail.length, bytes: tail },
        { start: recordAt, bytes: record },
        { start: cdOffset, bytes: cd },
      ],
      reads,
    );
    const r = await readZipDirectory(size, read);
    expect(r.ok && r.entries.map((e) => e.name)).toEqual(['x']);
    expect(reads).toEqual([
      [size - TAIL_BYTES, size],
      [recordAt, recordAt + 56],
      [cdOffset, cdOffset + cd.length],
    ]);
  });

  test('absurd 64-bit values are errors, not wrong numbers', () => {
    const rec = eocd64(1, 1, 1);
    rec.set([0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x7f], 48); // offset ~ 2^63
    expect(parseEocd64(rec).ok).toBe(false);
  });
});

describe('entry count limit', () => {
  test('a declared count above the limit is refused before the directory is read', async () => {
    const reads: [number, number][] = [];
    const bytes = cat(new Uint8Array(100), eocd(0, 0, 0));
    const z64 = cat(new Uint8Array(1000), eocd64(MAX_ENTRIES + 1, 46, 0), locator64(1000), cat(u32(0x06054b50), u16(0), u16(0), u16(0xffff), u16(0xffff), u32(0xffffffff), u32(0xffffffff), u16(0)));
    const r = await readZipDirectory(z64.length, async (a, b) => (reads.push([a, b]), z64.slice(a, b)));
    expect(r).toEqual({ ok: false, error: expect.stringMatching(/too many entries \(2,000,001; the limit is 2,000,000\)/) });
    expect(reads).toHaveLength(1); // the tail (which holds the ZIP64 record), not the directory
    expect((await list(bytes)).ok).toBe(true);
  });

  test('more entries in the directory than the limit are refused (wrapped count)', () => {
    const cd = cat(...Array.from({ length: 6 }, (_, i) => centralRecord({ nameBytes: new TextEncoder().encode(`e${i}`), csize: 1, size: 1, offset: 0 })));
    expect(parseCentralDirectory(cd, 0, 10)).toMatchObject({ ok: true });
    expect(parseCentralDirectory(cd, 0, 5)).toEqual({ ok: false, error: expect.stringMatching(/too many entries/) });
  });
});

describe('partial ZIP64 saturation', () => {
  /** A central record with raw 32-bit fields and an arbitrary extra block (name "a"). */
  const rec = (csize: number, size: number, offset: number, extra: Uint8Array) =>
    cat(
      u32(0x02014b50), u16(0x031e), u16(45), u16(0), u16(8), u16(0), u16(0x21), u32(0x1234), u32(csize), u32(size),
      u16(1), u16(extra.length), u16(0), u16(0), u16(0), u32(0), u32(offset), [0x61], extra,
    );
  const entry = (r: Uint8Array) => {
    const out = parseCentralDirectory(r, 1);
    if (!out.ok) throw new Error(out.error);
    return out.value[0]!;
  };
  const SAT = 0xffffffff;

  test('only the offset saturated: the one 8-byte value is the offset', () => {
    expect(entry(rec(100, 200, SAT, extraField(1, u64(5_000_000_000))))).toMatchObject({ compressedSize: 100, size: 200, localHeaderOffset: 5_000_000_000 });
  });

  test('compressed size and offset saturated: values come in the order csize, offset (size is not there)', () => {
    expect(entry(rec(SAT, 200, SAT, extraField(1, [...u64(4_400_000_000), ...u64(5_000_000_000)])))).toMatchObject({
      compressedSize: 4_400_000_000,
      size: 200,
      localHeaderOffset: 5_000_000_000,
    });
  });

  test('size and offset saturated: the order is size, offset', () => {
    expect(entry(rec(100, SAT, SAT, extraField(1, [...u64(4_500_000_000), ...u64(5_000_000_000)])))).toMatchObject({
      compressedSize: 100,
      size: 4_500_000_000,
      localHeaderOffset: 5_000_000_000,
    });
  });

  test('all three saturated: size, compressed size, offset', () => {
    expect(entry(rec(SAT, SAT, SAT, extraField(1, [...u64(4_500_000_000), ...u64(4_400_000_000), ...u64(5_000_000_000)])))).toMatchObject({
      size: 4_500_000_000,
      compressedSize: 4_400_000_000,
      localHeaderOffset: 5_000_000_000,
    });
  });

  test('only the size saturated', () => {
    expect(entry(rec(100, SAT, 7, extraField(1, u64(4_500_000_000))))).toMatchObject({ compressedSize: 100, size: 4_500_000_000, localHeaderOffset: 7 });
  });

  test('a ZIP64 field that is not saturated is not consumed, and the field is found after other extra fields', () => {
    const extra = cat(extraField(0x7075, [9, 9, 9, 9, 9]), extraField(1, u64(5_000_000_000)));
    expect(entry(rec(100, 200, SAT, extra))).toMatchObject({ size: 200, localHeaderOffset: 5_000_000_000 });
  });

  test('a saturated field with no ZIP64 extra is taken literally', () => {
    expect(entry(rec(100, SAT, 7, new Uint8Array(0)))).toMatchObject({ size: SAT, localHeaderOffset: 7 });
  });
});

describe('comments', () => {
  test('a trailing comment', async () => {
    const e = await entriesOf(buildZip([{ name: 'a', data: hello }], { comment: new TextEncoder().encode('made by a test') }).bytes);
    expect(e.map((x) => x.name)).toEqual(['a']);
  });

  test('a maximum-length comment that contains a decoy EOCD signature', async () => {
    const comment = new Uint8Array(65_535);
    comment.set(eocd(7, 99, 12345), 100); // a fake record inside the comment, with a comment length that does not reach the end
    const built = buildZip([{ name: 'a', data: hello }, { name: 'b' }], { comment });
    expect(built.bytes.length - (built.cdOffset + built.cdSize)).toBe(22 + 65_535);
    const e = await entriesOf(built.bytes);
    expect(e.map((x) => x.name)).toEqual(['a', 'b']);
  });

  test('a fake record inside the comment whose own comment reaches the end of the file does not win over the real one', async () => {
    const fakeTail = new Uint8Array(10);
    const fake = cat(u32(0x06054b50), u16(0), u16(0), u16(1), u16(1), u32(46), u32(0), u16(fakeTail.length), fakeTail);
    const built = buildZip([{ name: 'real.dcm', data: hello }], { comment: fake });
    const e = await entriesOf(built.bytes);
    expect(e.map((x) => x.name)).toEqual(['real.dcm']);
  });

  test('with no consistent record at all, the nearest one that fits is still used (directory followed by other records)', async () => {
    const built = buildZip([{ name: 'a', data: hello }]);
    // A 12-byte record between the directory and the EOCD (like a digital signature): cdOffset + cdSize no longer meets the EOCD.
    const head = built.bytes.subarray(0, built.cdOffset + built.cdSize);
    const withGap = cat(head, new Uint8Array(12), eocd(1, built.cdSize, built.cdOffset));
    expect((await entriesOf(withGap)).map((x) => x.name)).toEqual(['a']);
  });

  test('the search window is 65,557 bytes: a record with a longer trailer is not found', async () => {
    const built = buildZip([{ name: 'a' }]);
    const junk = new Uint8Array(EOCD_SEARCH_BYTES + 5);
    const r = await list(cat(built.bytes, junk));
    expect(r.ok).toBe(false);
  });

  test('trailing junk after a complete record is tolerated (the nearest fitting record is used)', async () => {
    const built = buildZip([{ name: 'a' }]);
    expect((await entriesOf(cat(built.bytes, new Uint8Array(100)))).map((x) => x.name)).toEqual(['a']);
  });
});

describe('malformed input never throws', () => {
  const good = buildZip([{ name: 'a.dcm', data: hello }, { name: 'b.dcm', data: hello, method: 0 }]);

  test.each([
    ['empty', new Uint8Array(0)],
    ['3 bytes', new Uint8Array([1, 2, 3])],
    ['21 bytes', new Uint8Array(21)],
    ['zeros', new Uint8Array(5000)],
    ['text', new TextEncoder().encode('PK\x03\x04 but really just a sentence about ZIP files, long enough to be scanned.')],
    ['random', randomBytes(4000, 1)],
  ])('%s is an error result', async (_, bytes) => {
    const r = await list(bytes);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.error.length).toBeGreaterThan(0);
  });

  test('truncated archive: the end is gone', async () => {
    expect((await list(good.bytes.subarray(0, good.bytes.length - 10))).ok).toBe(false);
    expect((await list(good.bytes.subarray(0, 40))).ok).toBe(false);
  });

  test('the central directory lies beyond the file', async () => {
    expect((await list(cat(good.bytes.subarray(0, good.cdOffset), eocd(2, good.cdSize + 500, good.cdOffset)))).ok).toBe(false);
    expect((await list(cat(good.bytes.subarray(0, good.cdOffset), eocd(2, good.cdSize, good.cdOffset + 5000)))).ok).toBe(false);
  });

  test('wrong entry count and corrupt entry signature', async () => {
    const cd = good.bytes.subarray(good.cdOffset, good.cdOffset + good.cdSize);
    const head = good.bytes.subarray(0, good.cdOffset);
    expect((await list(cat(head, cd, eocd(5, cd.length, good.cdOffset)))).ok).toBe(false); // claims 5, has 2
    const bad = cd.slice();
    bad[0] = 0;
    expect((await list(cat(head, bad, eocd(2, bad.length, good.cdOffset)))).ok).toBe(false);
    // The 16-bit count may be smaller than the real number (wrapped): everything present is listed.
    expect((await entriesOf(cat(head, cd, eocd(1, cd.length, good.cdOffset)))).length).toBe(2);
  });

  test('an entry whose name runs past the directory', async () => {
    const rec = centralRecord({ nameBytes: new TextEncoder().encode('abcdef'), csize: 1, size: 1, offset: 0 });
    rec.set(u16(500), 28);
    expect((await list(cat(rec, eocd(1, rec.length, 0)))).ok).toBe(false);
  });

  test('a ZIP64 extra field that is too short', async () => {
    const rec = centralRecord({ nameBytes: new TextEncoder().encode('a'), csize: 1, size: 1, offset: 0, extra: extraField(0x0001, [1, 2, 3]) });
    rec.set(u32(0xffffffff), 24); // size says "see the extra field"
    expect((await list(cat(rec, eocd(1, rec.length, 0)))).ok).toBe(false);
  });

  test('multi-part archives are refused', async () => {
    const e = eocd(1, 0, 0);
    e.set(u16(1), 4); // this disk = 1
    expect((await list(e)).ok).toBe(false);
  });

  test('a ZIP64 locator that points outside the file, or at something else', async () => {
    const loc = locator64(9_000_000_000);
    const eocd32 = cat(u32(0x06054b50), u16(0), u16(0), u16(0xffff), u16(0xffff), u32(0xffffffff), u32(0xffffffff), u16(0));
    expect((await list(cat(new Uint8Array(100), loc, eocd32))).ok).toBe(false);
    expect((await list(cat(new Uint8Array(100), locator64(10), eocd32))).ok).toBe(false); // offset 10: not a record
  });

  test('an enormous declared directory is refused without reading it', async () => {
    const reads: number[] = [];
    const bytes = cat(new Uint8Array(100), eocd(1, MAX_DIRECTORY_BYTES + 1, 0));
    const r = await readZipDirectory(bytes.length, async (a, b) => (reads.push(b - a), bytes.slice(a, b)));
    expect(r.ok).toBe(false);
    expect(reads).toHaveLength(1);
  });

  test('a reader that throws, returns too little, or a non-integer size', async () => {
    expect((await readZipDirectory(100, async () => Promise.reject(new Error('disk gone')))).ok).toBe(false);
    expect((await readZipDirectory(100, async () => new Uint8Array(3))).ok).toBe(false);
    expect((await readZipDirectory(Number.NaN, async () => new Uint8Array(0))).ok).toBe(false);
    expect((await readZipDirectory(-5, async () => new Uint8Array(0))).ok).toBe(false);
  });

  test('fuzz: byte flips and cuts of valid archives (plain and ZIP64) always give a result', async () => {
    const r = prng(42);
    const bases = [good.bytes, buildZip([{ name: 'x', data: hello }, { name: 'y/z', data: hello, method: 0 }], { zip64: true, comment: new TextEncoder().encode('c') }).bytes];
    let errors = 0;
    let oks = 0;
    for (let i = 0; i < 4000; i++) {
      const base = bases[i % bases.length]!;
      const bytes = base.slice(0, r() < 0.3 ? Math.floor(r() * base.length) : base.length);
      const flips = 1 + Math.floor(r() * 4);
      for (let k = 0; k < flips && bytes.length > 0; k++) bytes[Math.floor(r() * bytes.length)] = Math.floor(r() * 256);
      const res = await list(bytes); // must not throw or reject
      if (res.ok) oks++;
      else errors++;
    }
    expect(errors).toBeGreaterThan(100);
    expect(oks).toBeGreaterThan(100);
  });

  test('fuzz: the sync parsers are total over random bytes', () => {
    const r = prng(7);
    for (let i = 0; i < 2000; i++) {
      const bytes = Uint8Array.from({ length: Math.floor(r() * 200) }, () => Math.floor(r() * 256));
      expect(typeof findEnd(bytes, bytes.length + Math.floor(r() * 5)).ok).toBe('boolean');
      expect(typeof parseCentralDirectory(bytes, Math.floor(r() * 4)).ok).toBe('boolean');
      expect(typeof parseEocd64(bytes).ok).toBe('boolean');
      expect(typeof localDataOffset(bytes, 0).ok).toBe('boolean');
    }
  });
});

describe('helpers', () => {
  test('hasZipMagic: file or empty-archive signature only', () => {
    expect(hasZipMagic(new Uint8Array([0x50, 0x4b, 3, 4]))).toBe(true);
    expect(hasZipMagic(new Uint8Array([0x50, 0x4b, 5, 6]))).toBe(true);
    expect(hasZipMagic(new Uint8Array([0x50, 0x4b, 7, 8]))).toBe(false); // spanned-archive marker
    expect(hasZipMagic(new Uint8Array([0x50, 0x4b, 3]))).toBe(false);
    expect(hasZipMagic(new TextEncoder().encode('DICM'))).toBe(false);
  });

  test('localDataOffset uses the local name and extra lengths, which may differ from the central ones', () => {
    const header = cat(u32(0x04034b50), u16(20), u16(0), u16(0), u16(0), u16(0), u32(0), u32(0), u32(0), u16(7), u16(11));
    expect(localDataOffset(header, 1000)).toEqual({ ok: true, value: 1000 + 30 + 7 + 11 });
    expect(localDataOffset(header.subarray(0, 29), 0).ok).toBe(false);
    expect(localDataOffset(cat([0, 0, 0, 0], header.subarray(4)), 0).ok).toBe(false);
  });
});
