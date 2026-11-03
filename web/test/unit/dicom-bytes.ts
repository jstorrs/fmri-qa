/** Minimal DICOM byte builders for tests. Little endian only. */

const enc = new TextEncoder();

export const concat = (...parts: Uint8Array[]): Uint8Array<ArrayBuffer> => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) {
    out.set(p, at);
    at += p.length;
  }
  return out;
};

export const u16 = (n: number): Uint8Array<ArrayBuffer> => new Uint8Array([n & 0xff, (n >> 8) & 0xff]);
export const u32 = (n: number): Uint8Array<ArrayBuffer> => concat(u16(n & 0xffff), u16(n >>> 16));

/** Even-length value: strings are padded with a space (NUL for UI), as DICOM requires. */
const valueBytes = (vr: string, value: string | Uint8Array): Uint8Array => {
  const raw = typeof value === 'string' ? enc.encode(value) : value;
  return raw.length % 2 === 0 ? raw : concat(raw, new Uint8Array([vr === 'UI' ? 0 : 0x20]));
};

const LONG_VRS = new Set(['OB', 'OW', 'OD', 'OF', 'OL', 'OV', 'SV', 'UV', 'SQ', 'UC', 'UR', 'UT', 'UN']);

export type Tag = readonly [group: number, element: number];

/** One element. `implicit` omits the VR (Implicit VR LE). */
export const el = (tag: Tag, vr: string, value: string | Uint8Array, implicit = false): Uint8Array<ArrayBuffer> => {
  const v = valueBytes(vr, value);
  const head = concat(u16(tag[0]), u16(tag[1]));
  if (implicit) return concat(head, u32(v.length), v);
  const vrBytes = enc.encode(vr);
  return LONG_VRS.has(vr)
    ? concat(head, vrBytes, u16(0), u32(v.length), v)
    : concat(head, vrBytes, u16(v.length), v);
};

/** Pixel data element header declaring `length` bytes, followed by only `present` of them. */
export const pixelData = (length: number, present = 0, implicit = false): Uint8Array<ArrayBuffer> => {
  const head = concat(u16(0x7fe0), u16(0x0010));
  const body = new Uint8Array(present);
  return implicit ? concat(head, u32(length), body) : concat(head, enc.encode('OW'), u16(0), u32(length), body);
};

export const EXPLICIT_LE = '1.2.840.10008.1.2.1';
export const IMPLICIT_LE = '1.2.840.10008.1.2';
export const DEFLATED_LE = '1.2.840.10008.1.2.1.99';

/** Preamble + DICM + file meta header (0002,0002) and (0002,0010); `data` follows verbatim. */
export const part10 = (
  data: Uint8Array,
  opts: { transferSyntax?: string; sopClass?: string } = {},
): Uint8Array<ArrayBuffer> =>
  concat(
    new Uint8Array(128),
    enc.encode('DICM'),
    el([2, 2], 'UI', opts.sopClass ?? '1.2.840.10008.5.1.4.1.1.4'),
    el([2, 3], 'UI', '1.2.3.4'),
    el([2, 0x10], 'UI', opts.transferSyntax ?? EXPLICIT_LE),
    data,
  );

/** A complete, valid header (all fields the parser reads) as explicit or implicit elements. */
export const baseElements = (implicit = false, extra: Uint8Array[] = []): Uint8Array<ArrayBuffer> =>
  concat(
    el([8, 0x18], 'UI', '1.2.3.4.5', implicit),
    el([8, 0x20], 'DA', '20260101', implicit),
    el([8, 0x30], 'TM', '093000', implicit),
    el([8, 0x60], 'CS', 'MR', implicit),
    el([8, 0x1030], 'LO', 'Brain MRI', implicit),
    el([8, 0x103e], 'LO', 'T1 MPRAGE', implicit),
    el([0x10, 0x10], 'PN', 'Doe^Jane', implicit),
    el([0x10, 0x20], 'LO', 'PAT001', implicit),
    el([0x20, 0x0d], 'UI', '1.2.3.1', implicit),
    el([0x20, 0x0e], 'UI', '1.2.3.1.1', implicit),
    el([0x20, 0x11], 'IS', '3', implicit),
    el([0x20, 0x13], 'IS', '7', implicit),
    ...extra,
  );

/**
 * A sequence element with one item per entry of `items` (each the concatenated
 * elements of that item). Undefined-length sequence and items by default, with
 * delimiters; otherwise defined lengths.
 */
export const sequence = (tag: Tag, items: Uint8Array[], implicit = false, undefinedLength = true): Uint8Array => {
  const head = concat(u16(tag[0]), u16(tag[1]));
  const item = (content: Uint8Array): Uint8Array =>
    undefinedLength
      ? concat(u16(0xfffe), u16(0xe000), u32(0xffffffff), content, u16(0xfffe), u16(0xe00d), u32(0))
      : concat(u16(0xfffe), u16(0xe000), u32(content.length), content);
  const body = concat(...items.map(item), ...(undefinedLength ? [concat(u16(0xfffe), u16(0xe0dd), u32(0))] : []));
  const length = undefinedLength ? 0xffffffff : body.length;
  return implicit
    ? concat(head, u32(length), body)
    : concat(head, enc.encode('SQ'), u16(0), u32(length), body);
};
