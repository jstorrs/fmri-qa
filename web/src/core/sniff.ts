/**
 * How a byte stream is laid out, judged from its first bytes only.
 * - `part10`: 128-byte preamble + `DICM`, then a file meta header.
 * - `raw-meta`: no preamble, but it starts with the file meta group (0002); the
 *   dataset's transfer syntax is whatever (0002,0010) says.
 * - `raw-explicit-le` / `raw-implicit-le`: a bare dataset starting at group 0008.
 */
export type DicomKind = 'part10' | 'raw-meta' | 'raw-explicit-le' | 'raw-implicit-le' | 'not-dicom';

/** Every VR code in PS3.5 Table 6.2-1. */
const VRS: ReadonlySet<string> = new Set(
  'AE AS AT CS DA DS DT FL FD IS LO LT OB OD OF OL OV OW PN SH SL SQ SS ST SV TM UC UI UL UN UR US UT UV'.split(' '),
);
/** VRs with a 2-byte reserved field and a 4-byte length. */
const LONG_VRS: ReadonlySet<string> = new Set('OB OD OF OL OV OW SQ SV UC UN UR UT UV'.split(' '));

const UNDEFINED_LENGTH = 0xffffffff;
const WALKED_ELEMENTS = 3;

const u16 = (b: Uint8Array, at: number): number => b[at]! | (b[at + 1]! << 8);
const u32 = (b: Uint8Array, at: number): number => (u16(b, at) | (u16(b, at + 2) << 16)) >>> 0;
const vrAt = (b: Uint8Array, at: number): string => String.fromCharCode(b[at]!, b[at + 1]!);

/**
 * Walk the first few top-level elements and check they are a plausible dataset:
 * strictly ascending tags in real groups, (explicit) a standard VR code,
 * even lengths that fit in `b`. An undefined length (sequence, encapsulated
 * data) ends the walk, as does the first non-meta element after a meta group.
 */
const plausible = (b: Uint8Array, explicit: boolean): boolean => {
  let pos = 0;
  let prev = -1;
  const firstGroup = u16(b, 0);
  for (let n = 0; n < WALKED_ELEMENTS; n++) {
    if (pos + 8 > b.length) return n > 0;
    const group = u16(b, pos);
    const tag = group * 0x10000 + u16(b, pos + 2);
    if (group === 0xfffe || group === 0xffff || tag <= prev) return false;
    // After a meta header the dataset follows in a transfer syntax we do not know here.
    if (firstGroup === 0x0002 && group !== 0x0002) return n > 0;
    prev = tag;

    const vr = vrAt(b, pos + 4);
    const isExplicit = explicit || group === 0x0002; // the meta group is always explicit
    let header = 8;
    let length: number;
    if (isExplicit) {
      if (!VRS.has(vr)) return false;
      if (LONG_VRS.has(vr)) {
        if (pos + 12 > b.length || u16(b, pos + 6) !== 0) return false;
        header = 12;
        length = u32(b, pos + 8);
      } else {
        length = u16(b, pos + 6);
      }
      if (length === UNDEFINED_LENGTH) return LONG_VRS.has(vr);
    } else {
      length = u32(b, pos + 4);
      if (length === UNDEFINED_LENGTH) return true;
    }
    if (length % 2 !== 0 || pos + header + length > b.length) return false;
    pos += header + length;
  }
  return true;
};

/**
 * Cheap, pure check on the first bytes. A headerless file is accepted only if
 * it starts with group 0002 (meta) or 0008 and its first elements walk
 * cleanly, so noise, text and resource forks (AppleDouble `00 05 16 07`) are
 * rejected without a further read.
 */
export const sniffDicom = (bytes: Uint8Array): DicomKind => {
  if (bytes.length >= 132 && bytes[128] === 0x44 && bytes[129] === 0x49 && bytes[130] === 0x43 && bytes[131] === 0x4d) {
    return 'part10';
  }
  if (bytes.length < 8) return 'not-dicom';
  const group = u16(bytes, 0);
  if (group === 0x0002) return plausible(bytes, true) ? 'raw-meta' : 'not-dicom';
  if (group !== 0x0008) return 'not-dicom';
  if (plausible(bytes, true)) return 'raw-explicit-le';
  return plausible(bytes, false) ? 'raw-implicit-le' : 'not-dicom';
};
