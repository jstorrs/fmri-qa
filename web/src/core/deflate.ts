import { Inflate } from 'fflate';
import { DEFLATED_LE, EXPLICIT_LE, withPreamble } from './header';
import { sniffDicom } from './sniff';

/**
 * dcm2niix cannot read Deflated Explicit VR Little Endian. This rewrites such a Part 10 file as plain Explicit VR
 * Little Endian: preamble, `DICM` and group 0002 are kept (group length and (0002,0010) updated), and the deflated
 * dataset is replaced by its inflated bytes. Pure; throws `Error` with a user-readable message on any problem.
 */

/** Most inflated bytes accepted for one file; a guard against deflate bombs, far above any real image. */
export const INFLATE_FILE_CAP = 1024 ** 3;
/** Input is fed to the inflater this many bytes at a time, so a bomb overshoots the cap by at most one chunk's output. */
export const INFLATE_PUSH_BYTES = 16 * 1024;

const PREAMBLE_END = 132; // 128-byte preamble + 'DICM'
const GROUP_LENGTH_ELEMENT = 12; // (0002,0000) UL: tag 4 + VR 2 + length 2 + value 4
const LONG_VRS = new Set(['OB', 'OW', 'OD', 'OF', 'OL', 'OV', 'SV', 'UV', 'SQ', 'UC', 'UR', 'UT', 'UN']);

const u16 = (b: Uint8Array, at: number): number => b[at]! | (b[at + 1]! << 8);
const u32 = (b: Uint8Array, at: number): number => (u16(b, at) | (u16(b, at + 2) << 16)) >>> 0;
const ascii = (b: Uint8Array, from: number, to: number): string => String.fromCharCode(...b.subarray(from, to));

const concat = (parts: readonly Uint8Array[]): Uint8Array => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
};

interface MetaElement {
  readonly group: number;
  readonly element: number;
  /** Whole element, header included. */
  readonly bytes: Uint8Array;
  /** Offset of the value inside `bytes`, and its length. */
  readonly valueAt: number;
  readonly valueLength: number;
}

interface Meta {
  /** Elements of group 0002 except (0002,0000), which is always regenerated. */
  readonly elements: readonly MetaElement[];
  /** Offset where the dataset starts. */
  readonly end: number;
}

/** A Part 10 byte stream: as is when it has the preamble, a raw meta-group file gets one, anything else is returned unchanged. */
const asPart10 = (bytes: Uint8Array): Uint8Array =>
  bytes.length >= PREAMBLE_END && ascii(bytes, 128, 132) === 'DICM' ? bytes : sniffDicom(bytes) === 'raw-meta' ? withPreamble(bytes) : bytes;

const readElement = (bytes: Uint8Array, at: number, limit: number): MetaElement | null => {
  if (at + 8 > limit) return null;
  const vr = ascii(bytes, at + 4, at + 6);
  if (!/^[A-Z]{2}$/.test(vr)) return null;
  const long = LONG_VRS.has(vr);
  const valueAt = long ? 12 : 8;
  if (at + valueAt > limit) return null;
  const valueLength = long ? u32(bytes, at + 8) : u16(bytes, at + 6);
  if (at + valueAt + valueLength > limit) return null;
  return { group: u16(bytes, at), element: u16(bytes, at + 2), bytes: bytes.subarray(at, at + valueAt + valueLength), valueAt, valueLength };
};

/**
 * The file meta header of a Part 10 stream. Its end comes from (0002,0000) when that leads and fits; otherwise (as
 * dicom-parser does) from walking Explicit VR LE elements while the group is 0002. Null if malformed.
 */
const readMeta = (bytes: Uint8Array): Meta | null => {
  if (bytes.length < PREAMBLE_END || ascii(bytes, 128, 132) !== 'DICM') return null;
  let at = PREAMBLE_END;
  let declaredEnd: number | null = null;
  if (u16(bytes, at) === 2 && u16(bytes, at + 2) === 0 && bytes.length >= at + GROUP_LENGTH_ELEMENT && ascii(bytes, at + 4, at + 6) === 'UL' && u16(bytes, at + 6) === 4) {
    const end = at + GROUP_LENGTH_ELEMENT + u32(bytes, at + 8);
    if (end <= bytes.length) declaredEnd = end;
    at += GROUP_LENGTH_ELEMENT;
  }
  const limit = declaredEnd ?? bytes.length;
  const elements: MetaElement[] = [];
  while (declaredEnd !== null ? at < declaredEnd : at + 8 <= limit && u16(bytes, at) === 2) {
    const e = readElement(bytes, at, limit);
    if (e === null) return null;
    if (!(e.group === 2 && e.element === 0)) elements.push(e);
    at += e.bytes.length;
  }
  return elements.length > 0 ? { elements, end: at } : null;
};

/** Transfer syntax UID of a Part 10 (or raw-meta) file's meta header, NUL/space padding removed; null if it has none. */
export const transferSyntaxOf = (bytes: Uint8Array): string | null => {
  const ts = readMeta(asPart10(bytes))?.elements.find((e) => e.group === 2 && e.element === 0x10);
  return ts ? ascii(ts.bytes, ts.valueAt, ts.valueAt + ts.valueLength).replace(/[\0 ]+$/, '') : null;
};

/**
 * Inflate a whole raw-deflate stream, pushing the input in {@link INFLATE_PUSH_BYTES} pieces and checking the cap on
 * every output chunk, so a deflate bomb is stopped after at most one piece's worth of output beyond `cap`. Unlike the
 * header scan's `boundedInflate`, truncation and corruption are errors. Returns the output chunks (the caller copies
 * them once into the final file). `observe` sees each chunk's size (for tests).
 */
/** The inflated dataset would exceed the caller's cap (as opposed to a corrupt or truncated stream). */
export class InflateCapError extends Error {}

export const inflateCapped = (input: Uint8Array, cap: number, observe?: (chunkBytes: number) => void): Uint8Array[] => {
  const chunks: Uint8Array[] = [];
  let total = 0;
  const tooBig = (): Error =>
    new InflateCapError(`The deflated dataset inflates to more than ${Math.round(cap / 1024 ** 2)} MB, which is not supported.`);
  const inflate = new Inflate((chunk) => {
    observe?.(chunk.length);
    total += chunk.length;
    if (total > cap) throw tooBig();
    chunks.push(chunk);
  });
  try {
    let at = 0;
    do {
      const end = Math.min(at + INFLATE_PUSH_BYTES, input.length);
      inflate.push(input.subarray(at, end), end === input.length);
      at = end;
    } while (at < input.length);
  } catch (e) {
    if (total > cap) throw tooBig();
    throw new Error(`The deflated dataset is corrupt or truncated (${e instanceof Error ? e.message : String(e)}).`);
  }
  return chunks;
};

const EXPLICIT_LE_VALUE = new TextEncoder().encode(EXPLICIT_LE + '\0'); // UIDs are NUL padded to even length

/** `bytes` as Explicit VR Little Endian. Throws unless it is a Part 10 (or raw-meta) file with the Deflated Explicit VR LE syntax. */
export const inflateDeflatedFile = (input: Uint8Array, cap: number = INFLATE_FILE_CAP): Uint8Array => {
  const bytes = asPart10(input);
  const meta = readMeta(bytes);
  if (meta === null || transferSyntaxOf(bytes) !== DEFLATED_LE)
    throw new Error('Not a Part 10 file with the Deflated Explicit VR Little Endian transfer syntax.');
  const rest = meta.elements.map((e) => {
    if (e.element !== 0x10 || e.group !== 2) return e.bytes;
    // (0002,0010) UI: 8-byte header (short form) with the new even length, then the value.
    const head = new Uint8Array(8);
    head.set(e.bytes.subarray(0, 6));
    head[6] = EXPLICIT_LE_VALUE.length & 0xff;
    head[7] = EXPLICIT_LE_VALUE.length >> 8;
    return concat([head, EXPLICIT_LE_VALUE]);
  });
  const groupLength = rest.reduce((n, p) => n + p.length, 0);
  // (0002,0000) UL 4: tag 0002,0000, 'UL', length 4, value.
  const groupElement = new Uint8Array([2, 0, 0, 0, 0x55, 0x4c, 4, 0, groupLength & 0xff, (groupLength >> 8) & 0xff, (groupLength >> 16) & 0xff, (groupLength >>> 24) & 0xff]);
  const dataset = inflateCapped(bytes.subarray(meta.end), cap);
  return concat([bytes.subarray(0, PREAMBLE_END), groupElement, ...rest, ...dataset]); // the one copy of the dataset
};
