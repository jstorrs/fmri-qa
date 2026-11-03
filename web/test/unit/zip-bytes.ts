/** Test-only ZIP writer with knobs for malformed and unusual archives (flags, extras, ZIP64, comments). */
import { deflateRawSync } from 'node:zlib';
import { crc32 } from '../../src/core/crc32';

export const u16 = (n: number): number[] => [n & 255, (n >>> 8) & 255];
export const u32 = (n: number): number[] => [n & 255, (n >>> 8) & 255, (n >>> 16) & 255, (n >>> 24) & 255];
export const u64 = (n: number): number[] => [...u32(n % 0x1_0000_0000), ...u32(Math.floor(n / 0x1_0000_0000))];

export const cat = (...parts: ArrayLike<number>[]): Uint8Array<ArrayBuffer> => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
};

const text = (s: string | Uint8Array): Uint8Array => (typeof s === 'string' ? new TextEncoder().encode(s) : s);

/** An extra-field block: id, size, data. */
export const extraField = (id: number, data: ArrayLike<number>): Uint8Array => cat(u16(id), u16(data.length), data);

/** MS-DOS date/time words. */
export const dos = (y: number, mo: number, d: number, h = 0, mi = 0, s = 0): { date: number; time: number } => ({
  date: ((y - 1980) << 9) | (mo << 5) | d,
  time: (h << 11) | (mi << 5) | (s >> 1),
});

export interface Spec {
  /** A string is UTF-8 encoded; bytes are written as given (for CP437 tests). */
  readonly name: string | Uint8Array;
  readonly data?: Uint8Array;
  /** Default 8 (deflate) when there is data, else 0. */
  readonly method?: number;
  readonly flags?: number;
  /** General-purpose flag bit 3: the local header carries zero CRC and sizes, and a data descriptor follows the data. */
  readonly dataDescriptor?: boolean;
  /** Extra field of the central record (the local header gets `localExtra`). */
  readonly extra?: Uint8Array;
  readonly localExtra?: Uint8Array;
  readonly date?: number;
  readonly time?: number;
  /** Override what the central directory says (the local header and the data stay true). */
  readonly central?: { readonly crc?: number; readonly csize?: number; readonly size?: number; readonly nameBytes?: Uint8Array };
}

export interface Options {
  readonly comment?: Uint8Array;
  /** Write every size and offset as ZIP64 (0xFFFFFFFF + extra field), plus the EOCD64 record and locator. */
  readonly zip64?: boolean;
}

export interface Built {
  readonly bytes: Uint8Array<ArrayBuffer>;
  /** Local header offset of each entry. */
  readonly offsets: readonly number[];
  readonly cdOffset: number;
  readonly cdSize: number;
}

/** One central-directory record. */
export const centralRecord = (r: {
  nameBytes: Uint8Array;
  flags?: number;
  method?: number;
  date?: number;
  time?: number;
  crc?: number;
  csize: number;
  size: number;
  offset: number;
  extra?: Uint8Array;
  zip64?: boolean;
}): Uint8Array<ArrayBuffer> => {
  const extra = r.extra ?? new Uint8Array(0);
  const z64 = r.zip64 ? extraField(0x0001, [...u64(r.size), ...u64(r.csize), ...u64(r.offset)]) : new Uint8Array(0);
  const f = (n: number): number => (r.zip64 ? 0xffffffff : n);
  return cat(
    u32(0x02014b50), u16(0x031e), u16(r.method === 0 ? 10 : 20), u16(r.flags ?? 0), u16(r.method ?? 0),
    u16(r.time ?? 0), u16(r.date ?? 0x21), u32(r.crc ?? 0), u32(f(r.csize)), u32(f(r.size)),
    u16(r.nameBytes.length), u16(z64.length + extra.length), u16(0), u16(0), u16(0), u32(0), u32(f(r.offset)),
    r.nameBytes, z64, extra,
  );
};

export const eocd = (count: number, cdSize: number, cdOffset: number, comment: Uint8Array = new Uint8Array(0)): Uint8Array<ArrayBuffer> =>
  cat(u32(0x06054b50), u16(0), u16(0), u16(count), u16(count), u32(cdSize), u32(cdOffset), u16(comment.length), comment);

export const eocd64 = (count: number, cdSize: number, cdOffset: number): Uint8Array<ArrayBuffer> =>
  cat(u32(0x06064b50), u64(44), u16(45), u16(45), u32(0), u32(0), u64(count), u64(count), u64(cdSize), u64(cdOffset));

export const locator64 = (eocd64Offset: number): Uint8Array<ArrayBuffer> => cat(u32(0x07064b50), u32(0), u64(eocd64Offset), u32(1));

export const buildZip = (specs: readonly Spec[], opts: Options = {}): Built => {
  const parts: Uint8Array[] = [];
  const offsets: number[] = [];
  const records: Uint8Array[] = [];
  let at = 0;
  for (const s of specs) {
    const data = s.data ?? new Uint8Array(0);
    const method = s.method ?? (data.length > 0 ? 8 : 0);
    const stored = method === 8 ? deflateRawSync(data) : data;
    const nameBytes = text(s.name);
    const crc = crc32(data);
    const localExtra = s.localExtra ?? new Uint8Array(0);
    const dd = s.dataDescriptor === true;
    const flags = (s.flags ?? 0) | (dd ? 8 : 0);
    const local = cat(
      u32(0x04034b50), u16(20), u16(flags), u16(method), u16(s.time ?? 0), u16(s.date ?? 0x21),
      u32(dd ? 0 : crc), u32(dd ? 0 : stored.length), u32(dd ? 0 : data.length), u16(nameBytes.length), u16(localExtra.length), nameBytes, localExtra, stored,
      dd ? cat(u32(0x08074b50), u32(crc), u32(stored.length), u32(data.length)) : [],
    );
    offsets.push(at);
    records.push(
      centralRecord({
        nameBytes: s.central?.nameBytes ?? nameBytes,
        flags,
        method,
        date: s.date,
        time: s.time,
        crc: s.central?.crc ?? crc,
        csize: s.central?.csize ?? stored.length,
        size: s.central?.size ?? data.length,
        offset: at,
        extra: s.extra,
        zip64: opts.zip64,
      }),
    );
    parts.push(local);
    at += local.length;
  }
  const cd = cat(...records);
  const cdOffset = at;
  const tail: Uint8Array[] = [cd];
  if (opts.zip64) {
    const at64 = cdOffset + cd.length;
    tail.push(eocd64(specs.length, cd.length, cdOffset), locator64(at64), cat(u32(0x06054b50), u16(0), u16(0), u16(0xffff), u16(0xffff), u32(0xffffffff), u32(0xffffffff), u16(opts.comment?.length ?? 0), opts.comment ?? []));
  } else tail.push(eocd(specs.length, cd.length, cdOffset, opts.comment));
  return { bytes: cat(...parts, ...tail), offsets, cdOffset, cdSize: cd.length };
};

/** A deterministic PRNG (xorshift32) for repeatable "random" bytes. */
export const prng = (seed: number) => {
  let x = seed | 0 || 1;
  return (): number => {
    x ^= x << 13;
    x ^= x >>> 17;
    x ^= x << 5;
    return (x >>> 0) / 0x1_0000_0000;
  };
};

export const randomBytes = (n: number, seed: number): Uint8Array<ArrayBuffer> => {
  const r = prng(seed);
  const out = new Uint8Array(n);
  for (let i = 0; i < n; i++) out[i] = Math.floor(r() * 256);
  return out;
};
