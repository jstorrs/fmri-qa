/**
 * How to decode DICOM text (PN, LO, SH, ST). All but `auto` are TextDecoder labels.
 * `auto` is for datasets with no SpecificCharacterSet: strict UTF-8 if the
 * bytes are valid UTF-8, else Latin-1.
 */
export type Charset =
  | 'auto'
  | 'latin1'
  | 'utf-8'
  | 'iso-8859-2'
  | 'iso-8859-3'
  | 'iso-8859-4'
  | 'iso-8859-5'
  | 'iso-8859-6'
  | 'iso-8859-7'
  | 'iso-8859-8'
  | 'iso-8859-15'
  | 'windows-1254'
  | 'windows-874'
  | 'gb18030'
  | 'gbk';

/** For unknown or unsupported terms: the DICOM default repertoire is ASCII; Latin-1 is its safe 8-bit superset. */
export const DEFAULT_CHARSET: Charset = 'latin1';

/** Defined terms of (0008,0005) SpecificCharacterSet, upper-cased and trimmed. */
const BY_TERM: Readonly<Record<string, Charset>> = {
  'ISO_IR 6': 'latin1',
  'ISO_IR 100': 'latin1',
  'ISO_IR 101': 'iso-8859-2',
  'ISO_IR 109': 'iso-8859-3',
  'ISO_IR 110': 'iso-8859-4',
  'ISO_IR 144': 'iso-8859-5',
  'ISO_IR 127': 'iso-8859-6',
  'ISO_IR 126': 'iso-8859-7',
  'ISO_IR 138': 'iso-8859-8',
  'ISO_IR 148': 'windows-1254',
  'ISO_IR 166': 'windows-874',
  'ISO_IR 192': 'utf-8',
  'ISO_IR 203': 'iso-8859-15',
  GB18030: 'gb18030',
  GBK: 'gbk',
  // Single-byte ISO 2022 forms: same repertoires; the escape sequences that
  // would select them are not interpreted (see charsetFor).
  'ISO 2022 IR 6': 'latin1',
  'ISO 2022 IR 100': 'latin1',
  'ISO 2022 IR 101': 'iso-8859-2',
  'ISO 2022 IR 144': 'iso-8859-5',
  'ISO 2022 IR 127': 'iso-8859-6',
  'ISO 2022 IR 126': 'iso-8859-7',
  'ISO 2022 IR 138': 'iso-8859-8',
  'ISO 2022 IR 148': 'windows-1254',
};

/**
 * Charset for a raw (0008,0005) value, or null when the attribute is absent.
 * An absent or blank value gives `auto`.
 *
 * Multi-valued attributes (`\`-separated): the FIRST NON-EMPTY value wins.
 * Limitation: ISO 2022 code extension (escape sequences switching sets
 * mid-string, e.g. `ISO 2022 IR 87` Japanese, or a second value that extends
 * the first) is NOT interpreted. Multi-byte ISO 2022 terms and any unknown term
 * fall back to {@link DEFAULT_CHARSET}.
 */
export const charsetFor = (specificCharacterSet: string | null): Charset => {
  const first = (specificCharacterSet ?? '')
    .split('\\')
    .map((v) => v.replace(/^[\s\0]+|[\s\0]+$/g, '').toUpperCase())
    .find((v) => v !== '');
  if (first === undefined) return 'auto';
  return (Object.hasOwn(BY_TERM, first) ? BY_TERM[first] : undefined) ?? DEFAULT_CHARSET;
};

const decoders = new Map<string, TextDecoder>();
const decoder = (label: string, fatal: boolean): TextDecoder => {
  const key = `${label}/${fatal}`;
  let d = decoders.get(key);
  if (d === undefined) {
    d = new TextDecoder(label, { fatal });
    decoders.set(key, d);
  }
  return d;
};

/**
 * Decode raw element bytes. Never throws: malformed sequences become U+FFFD.
 * 'latin1' is the WHATWG label for windows-1252 (a superset of ISO 8859-1
 * that differs only in 0x80-0x9F).
 */
export const decodeText = (bytes: Uint8Array, charset: Charset): string => {
  if (charset !== 'auto') return decoder(charset, false).decode(bytes);
  try {
    return decoder('utf-8', true).decode(bytes);
  } catch {
    return decoder('latin1', false).decode(bytes);
  }
};
