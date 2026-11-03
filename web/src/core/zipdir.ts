/**
 * ZIP central-directory parser. Pure: it never touches a File; the caller supplies byte ranges (see {@link readZipDirectory}).
 *
 * Reads only the end of the archive (the End Of Central Directory record, the ZIP64 records when present) and the
 * central directory, so an archive of any size is listed without being loaded. Total: nothing here throws to the
 * caller; a malformed archive is a result with an `error`.
 */
import { decodeCp437 } from './cp437';
import { crc32 } from './crc32';

/** The most the EOCD record can take at the end of a file: 22 fixed bytes plus a comment of up to 65,535. */
export const EOCD_SEARCH_BYTES = 65_535 + 22;
/** Fixed sizes of the ZIP64 end-of-directory locator and record (without its extensible data). */
const LOCATOR_BYTES = 20;
const EOCD64_BYTES = 56;
/** What to read from the end of an archive: the EOCD search window plus room for the ZIP64 locator and record before it. */
export const TAIL_BYTES = EOCD_SEARCH_BYTES + LOCATOR_BYTES + EOCD64_BYTES;
/** A central directory larger than this is refused rather than read into memory. */
export const MAX_DIRECTORY_BYTES = 512 * 1024 * 1024;
/** More entries than this are refused (each costs an object, a scan input and a source; 2 million is far beyond any DICOM export). */
export const MAX_ENTRIES = 2_000_000;
/** Fixed part of a local file header. */
export const LOCAL_HEADER_BYTES = 30;

export const METHOD_STORE = 0;
export const METHOD_DEFLATE = 8;

const EOCD_SIG = 0x06054b50;
const EOCD64_SIG = 0x06064b50;
const LOCATOR_SIG = 0x07064b50;
const CEN_SIG = 0x02014b50;
const LOC_SIG = 0x04034b50;
const CEN_FIXED = 46;

export interface ZipEntryInfo {
  /** Display path: '/'-separated, never absolute, no `.`/`..` segments, no control characters, no trailing slash. */
  readonly name: string;
  /** Compression method as stored (0 = store, 8 = deflate; anything else is unsupported). */
  readonly method: number;
  readonly compressedSize: number;
  /** Uncompressed size. */
  readonly size: number;
  /** Offset of the local file header from the start of the archive. */
  readonly localHeaderOffset: number;
  readonly crc32: number;
  /** General-purpose flag bit 0 (or bit 6, strong encryption). */
  readonly encrypted: boolean;
  readonly isDir: boolean;
  /** Milliseconds since the epoch, DOS date/time read as local time. */
  readonly lastModified: number;
}

export type ZipResult<T> = { readonly ok: true; readonly value: T } | { readonly ok: false; readonly error: string };

export type ZipDirectory = { readonly ok: true; readonly entries: readonly ZipEntryInfo[] } | { readonly ok: false; readonly error: string };

/** Where the central directory is, or where to find the ZIP64 record that says. */
export type EndOfDirectory =
  | { readonly zip64: false; readonly cdOffset: number; readonly cdSize: number; readonly count: number }
  | { readonly zip64: true; readonly recordOffset: number };

export interface DirectoryLocation {
  readonly cdOffset: number;
  readonly cdSize: number;
  readonly count: number;
}

/** Reads `[start, end)` of the archive; must return exactly that many bytes. */
export type ReadRange = (start: number, end: number) => Promise<Uint8Array>;

class ZipError extends Error {}

const fail = (message: string): never => {
  throw new ZipError(message);
};

const attempt = <T>(f: () => T): ZipResult<T> => {
  try {
    return { ok: true, value: f() };
  } catch (e) {
    // A RangeError from a DataView read means the input ended early.
    return { ok: false, error: e instanceof ZipError ? e.message : e instanceof RangeError ? 'truncated data' : `unexpected error: ${String(e)}` };
  }
};

const view = (b: Uint8Array): DataView => new DataView(b.buffer, b.byteOffset, b.byteLength);

/** 8 bytes little-endian as a number; anything past 2^53 is not addressable. */
const u64 = (dv: DataView, at: number): number => {
  const lo = dv.getUint32(at, true);
  const hi = dv.getUint32(at + 4, true);
  return hi > 0x1fffff ? fail('a 64-bit value is too large') : hi * 0x1_0000_0000 + lo;
};

/** `PK\x03\x04` (a file) or `PK\x05\x06` (an empty archive). The only ways a ZIP can start. */
export const hasZipMagic = (b: Uint8Array): boolean =>
  b.length >= 4 && b[0] === 0x50 && b[1] === 0x4b && ((b[2] === 3 && b[3] === 4) || (b[2] === 5 && b[3] === 6));

// ---- End of central directory ---------------------------------------------

/**
 * Find the EOCD record in `tail` (the last bytes of an archive of `size` bytes). Looks back at most
 * {@link EOCD_SEARCH_BYTES}. Several byte patterns may look like a record (a comment can hold a whole ZIP), so
 * candidates are ranked, nearest the end first within a rank: consistent (the directory it describes ends exactly at
 * the record, or a ZIP64 locator sits right before it) and with a comment that reaches the end of the file; then
 * consistent only (trailing junk); then comment-reaches-the-end only; then any whose comment fits. With a ZIP64
 * locator in front of it, the result says where the ZIP64 record is.
 */
export const findEnd = (tail: Uint8Array, size: number): ZipResult<EndOfDirectory> =>
  attempt(() => {
    if (tail.length > size) fail('tail is longer than the archive');
    if (tail.length < 22) return fail('too small to be a ZIP archive');
    const dv = view(tail);
    const tailStart = size - tail.length;
    const ranked: number[] = [-1, -1, -1, -1]; // best candidate per rank (the first found scanning backwards)
    for (let p = tail.length - 22; p >= Math.max(0, tail.length - EOCD_SEARCH_BYTES); p--) {
      if (tail[p] !== 0x50 || dv.getUint32(p, true) !== EOCD_SIG) continue;
      const end = p + 22 + dv.getUint16(p + 20, true);
      if (end > tail.length) continue;
      const exact = end === tail.length;
      const locator = p >= LOCATOR_BYTES && dv.getUint32(p - LOCATOR_BYTES, true) === LOCATOR_SIG;
      const consistent = locator || tailStart + p === dv.getUint32(p + 16, true) + dv.getUint32(p + 12, true);
      const rank = consistent ? (exact ? 0 : 1) : exact ? 2 : 3;
      if (ranked[rank]! < 0) ranked[rank] = p;
      if (rank === 0) break;
    }
    const at = ranked.find((p) => p >= 0) ?? -1;
    if (at < 0) return fail('no end-of-central-directory record (not a ZIP archive, or truncated)');

    if (at >= LOCATOR_BYTES && dv.getUint32(at - LOCATOR_BYTES, true) === LOCATOR_SIG) {
      const l = at - LOCATOR_BYTES;
      if (dv.getUint32(l + 16, true) > 1) fail('multi-part archives are not supported');
      return { zip64: true, recordOffset: u64(dv, l + 8) } as const;
    }
    if (dv.getUint16(at + 4, true) !== 0 || dv.getUint16(at + 6, true) !== 0) fail('multi-part archives are not supported');
    const count = dv.getUint16(at + 10, true);
    if (dv.getUint16(at + 8, true) !== count) fail('multi-part archives are not supported');
    return { zip64: false, cdOffset: dv.getUint32(at + 16, true), cdSize: dv.getUint32(at + 12, true), count } as const;
  });

/** The ZIP64 end-of-central-directory record (at least {@link EOCD64_BYTES} bytes). */
export const parseEocd64 = (record: Uint8Array): ZipResult<DirectoryLocation> =>
  attempt(() => {
    if (record.length < EOCD64_BYTES) fail('truncated ZIP64 end-of-central-directory record');
    const dv = view(record);
    if (dv.getUint32(0, true) !== EOCD64_SIG) fail('ZIP64 end-of-central-directory record not found at its stated offset');
    if (dv.getUint32(16, true) !== 0 || dv.getUint32(20, true) !== 0) fail('multi-part archives are not supported');
    const count = u64(dv, 32);
    if (u64(dv, 24) !== count) fail('multi-part archives are not supported');
    return { count, cdSize: u64(dv, 40), cdOffset: u64(dv, 48) };
  });

// ---- Central directory ----------------------------------------------------

const utf8 = new TextDecoder('utf-8');

/** Extra-field walk; stops quietly at a field that overruns the block (some writers pad with junk). */
const extraFields = function* (extra: Uint8Array): Generator<{ id: number; data: Uint8Array }> {
  const dv = view(extra);
  for (let p = 0; p + 4 <= extra.length; ) {
    const id = dv.getUint16(p, true);
    const len = dv.getUint16(p + 2, true);
    if (p + 4 + len > extra.length) return;
    yield { id, data: extra.subarray(p + 4, p + 4 + len) };
    p += 4 + len;
  }
};

/**
 * Make an entry name safe to show as a path: '\' becomes '/', control characters become '_', and empty, `.` and `..`
 * segments, a leading '/', and a drive letter are dropped. (Names are only ever display text here, never file system
 * paths, but a path like `../../x` should not look like one.)
 */
export const normalizeEntryName = (raw: string): string =>
  raw
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001f\u007f]/g, '_')
    .replace(/\\/g, '/')
    .split('/')
    .map((seg, i) => (i === 0 ? seg.replace(/^[A-Za-z]:/, '') : seg))
    .filter((seg) => seg !== '' && seg !== '.' && seg !== '..')
    .join('/');

/** MS-DOS date and time (local, 2-second resolution) as epoch milliseconds; invalid fields fall back to 1980-01-01. */
export const dosToMillis = (date: number, time: number): number => {
  const year = 1980 + (date >> 9);
  const month = (date >> 5) & 15;
  const day = date & 31;
  const hour = time >> 11;
  const minute = (time >> 5) & 63;
  const second = (time & 31) * 2;
  const valid = month >= 1 && month <= 12 && day >= 1 && hour < 24 && minute < 60 && second < 60;
  return valid ? new Date(year, month - 1, day, hour, minute, second).getTime() : new Date(1980, 0, 1).getTime();
};

const parseEntry = (cd: Uint8Array, dv: DataView, pos: number): { entry: ZipEntryInfo; next: number } => {
  const flags = dv.getUint16(pos + 8, true);
  const method = dv.getUint16(pos + 10, true);
  const nameLen = dv.getUint16(pos + 28, true);
  const extraLen = dv.getUint16(pos + 30, true);
  const commentLen = dv.getUint16(pos + 32, true);
  const nameAt = pos + CEN_FIXED;
  const next = nameAt + nameLen + extraLen + commentLen;
  if (next > cd.length) fail('truncated central directory');
  const nameBytes = cd.subarray(nameAt, nameAt + nameLen);
  const extra = cd.subarray(nameAt + nameLen, nameAt + nameLen + extraLen);

  let compressedSize = dv.getUint32(pos + 20, true);
  let size = dv.getUint32(pos + 24, true);
  let localHeaderOffset = dv.getUint32(pos + 42, true);
  let unicodeName: string | null = null;
  for (const { id, data } of extraFields(extra)) {
    if (id === 0x0001) {
      // ZIP64: only the fields whose 32-bit value is 0xFFFFFFFF are present, in this order.
      const d = view(data);
      let at = 0;
      const next64 = (): number => {
        if (at + 8 > data.length) return fail('bad ZIP64 extra field');
        const v = u64(d, at);
        at += 8;
        return v;
      };
      if (size === 0xffffffff) size = next64();
      if (compressedSize === 0xffffffff) compressedSize = next64();
      if (localHeaderOffset === 0xffffffff) localHeaderOffset = next64();
    } else if (id === 0x7075 && data.length >= 5 && data[0] === 1) {
      // Info-ZIP Unicode Path: valid only while the header's own name still matches the CRC it was made from.
      if (view(data).getUint32(1, true) === crc32(nameBytes)) unicodeName = utf8.decode(data.subarray(5));
    }
  }

  const decoded = unicodeName ?? (flags & 0x800 ? utf8.decode(nameBytes) : decodeCp437(nameBytes));
  const name = normalizeEntryName(decoded);
  return {
    next,
    entry: {
      name,
      method,
      compressedSize,
      size,
      localHeaderOffset,
      crc32: dv.getUint32(pos + 16, true),
      encrypted: (flags & 0x1) !== 0 || (flags & 0x40) !== 0,
      isDir: name === '' || /[\\/]$/.test(decoded),
      lastModified: dosToMillis(dv.getUint16(pos + 14, true), dv.getUint16(pos + 12, true)),
    },
  };
};

/**
 * Entries of a central directory (`cd` is exactly its bytes). Parses while the entry signature matches, so an
 * archive whose count field wrapped (older writers) still lists everything; fewer entries than declared is an error.
 */
export const parseCentralDirectory = (cd: Uint8Array, declaredCount: number, maxEntries = MAX_ENTRIES): ZipResult<readonly ZipEntryInfo[]> =>
  attempt(() => {
    if (declaredCount > maxEntries) fail(`too many entries (${declaredCount.toLocaleString('en-US')}; the limit is ${maxEntries.toLocaleString('en-US')})`);
    if (declaredCount * CEN_FIXED > cd.length) fail('central directory is smaller than its entry count implies');
    const dv = view(cd);
    const entries: ZipEntryInfo[] = [];
    for (let pos = 0; pos + 4 <= cd.length && dv.getUint32(pos, true) === CEN_SIG; ) {
      if (pos + CEN_FIXED > cd.length) fail('truncated central directory');
      if (entries.length >= maxEntries) fail(`too many entries (the limit is ${maxEntries.toLocaleString('en-US')})`);
      const { entry, next } = parseEntry(cd, dv, pos);
      entries.push(entry);
      pos = next;
    }
    if (entries.length < declaredCount) fail(`central directory lists ${entries.length} of ${declaredCount} entries`);
    return entries;
  });

// ---- Local header ---------------------------------------------------------

/** Where an entry's data starts, from its 30-byte local header (whose name and extra lengths may differ from the central ones). */
export const localDataOffset = (header: Uint8Array, localHeaderOffset: number): ZipResult<number> =>
  attempt(() => {
    if (header.length < LOCAL_HEADER_BYTES) fail('truncated local file header');
    const dv = view(header);
    if (dv.getUint32(0, true) !== LOC_SIG) fail('no local file header at the entry offset');
    return localHeaderOffset + LOCAL_HEADER_BYTES + dv.getUint16(26, true) + dv.getUint16(28, true);
  });

// ---- Driver ---------------------------------------------------------------

const checked = async (read: ReadRange, start: number, end: number): Promise<Uint8Array> => {
  const bytes = await read(start, end);
  return bytes.length === end - start ? bytes : fail('short read');
};

const unwrap = <T>(r: ZipResult<T>): T => (r.ok ? r.value : fail(r.error));

/**
 * List an archive of `size` bytes using ranged reads only: the tail (EOCD and ZIP64 records), then the central
 * directory, from the tail if it lies inside it, else with a second read. Never throws.
 */
export const readZipDirectory = async (size: number, read: ReadRange): Promise<ZipDirectory> => {
  try {
    if (!Number.isSafeInteger(size) || size < 22) return { ok: false, error: 'too small to be a ZIP archive' };
    const tailStart = Math.max(0, size - TAIL_BYTES);
    const tail = await checked(read, tailStart, size);
    const end = unwrap(findEnd(tail, size));
    let where: DirectoryLocation;
    if (end.zip64) {
      const at = end.recordOffset;
      if (at + EOCD64_BYTES > size) fail('ZIP64 end-of-central-directory record lies beyond the end of the file');
      const record = at >= tailStart ? tail.subarray(at - tailStart, at - tailStart + EOCD64_BYTES) : await checked(read, at, at + EOCD64_BYTES);
      where = unwrap(parseEocd64(record));
    } else where = end;
    if (where.count > MAX_ENTRIES) fail(`too many entries (${where.count.toLocaleString('en-US')}; the limit is ${MAX_ENTRIES.toLocaleString('en-US')})`);
    if (where.cdSize > MAX_DIRECTORY_BYTES) fail(`central directory is too large (${where.cdSize} bytes)`);
    if (where.cdOffset + where.cdSize > size) fail('central directory lies beyond the end of the file');
    const cd =
      where.cdOffset >= tailStart
        ? tail.subarray(where.cdOffset - tailStart, where.cdOffset - tailStart + where.cdSize)
        : await checked(read, where.cdOffset, where.cdOffset + where.cdSize);
    return { ok: true, entries: unwrap(parseCentralDirectory(cd, where.count)) };
  } catch (e) {
    return { ok: false, error: e instanceof ZipError ? e.message : e instanceof Error ? e.message : String(e) };
  }
};
