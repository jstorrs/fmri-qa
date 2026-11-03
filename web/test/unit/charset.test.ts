import { describe, expect, it } from 'vitest';
import { charsetFor, decodeText } from '../../src/core/charset';

const bytes = (...b: number[]): Uint8Array => Uint8Array.from(b);
const utf8 = (s: string): Uint8Array => new TextEncoder().encode(s);

describe('charsetFor', () => {
  it.each([
    ['ISO_IR 192', 'utf-8'],
    ['ISO_IR 100', 'latin1'],
    ['ISO_IR 101', 'iso-8859-2'],
    ['ISO_IR 144', 'iso-8859-5'],
    ['ISO_IR 126', 'iso-8859-7'],
    ['ISO_IR 127', 'iso-8859-6'],
    ['ISO_IR 138', 'iso-8859-8'],
    ['ISO_IR 148', 'windows-1254'],
    ['ISO_IR 109', 'iso-8859-3'],
    ['ISO_IR 110', 'iso-8859-4'],
    ['ISO_IR 166', 'windows-874'],
    ['ISO_IR 203', 'iso-8859-15'],
    ['GB18030', 'gb18030'],
    ['GBK', 'gbk'],
    ['ISO 2022 IR 100', 'latin1'],
    ['ISO 2022 IR 101', 'iso-8859-2'],
    ['ISO 2022 IR 126', 'iso-8859-7'],
    ['ISO 2022 IR 127', 'iso-8859-6'],
    ['ISO 2022 IR 138', 'iso-8859-8'],
    ['ISO 2022 IR 144', 'iso-8859-5'],
    ['ISO 2022 IR 148', 'windows-1254'],
  ] as const)('%s -> %s', (term, label) => {
    expect(charsetFor(term)).toBe(label);
  });

  it('absent or blank gives auto (strict UTF-8, else Latin-1)', () => {
    expect(charsetFor(null)).toBe('auto');
    expect(charsetFor('')).toBe('auto');
    expect(charsetFor(' \\ ')).toBe('auto');
  });

  it('defaults to latin1 for ASCII, unknown and unsupported multi-byte terms', () => {
    expect(charsetFor('ISO_IR 6')).toBe('latin1');
    expect(charsetFor('ISO 2022 IR 87')).toBe('latin1');
    expect(charsetFor('ISO_IR 999')).toBe('latin1');
    expect(charsetFor('constructor')).toBe('latin1');
  });

  it('ignores padding and case', () => {
    expect(charsetFor('ISO_IR 192 ')).toBe('utf-8');
    expect(charsetFor('iso_ir 192\0')).toBe('utf-8');
  });

  it('uses the first NON-EMPTY value of a multi-valued attribute (no ISO 2022 escapes)', () => {
    expect(charsetFor('ISO_IR 144\\ISO_IR 100')).toBe('iso-8859-5');
    expect(charsetFor('\\ISO_IR 192')).toBe('utf-8');
    expect(charsetFor('\\ISO 2022 IR 87')).toBe('latin1'); // unsupported -> default
  });
});

describe('decodeText', () => {
  it('decodes UTF-8', () => {
    expect(decodeText(utf8('Müller^Jürgen'), 'utf-8')).toBe('Müller^Jürgen');
  });

  it('decodes Latin-1', () => {
    expect(decodeText(bytes(0x4d, 0xfc, 0x6c, 0x6c, 0x65, 0x72), 'latin1')).toBe('Müller');
  });

  it('decodes ISO 8859-5 (Cyrillic) and GB18030', () => {
    expect(decodeText(bytes(0xb8, 0xd2, 0xd0, 0xdd), 'iso-8859-5')).toBe('Иван');
    expect(decodeText(bytes(0xd6, 0xd0, 0xce, 0xc4), 'gb18030')).toBe('中文');
  });

  it.each([
    ['iso-8859-3', [0xa1], 'Ħ'],
    ['iso-8859-4', [0xa1], 'Ą'],
    ['iso-8859-7', [0xe1, 0xe2], 'αβ'],
    ['iso-8859-6', [0xc7, 0xe4], 'ال'],
    ['iso-8859-8', [0xe0, 0xe1], 'אב'],
    ['windows-1254', [0xd0, 0xfd], 'Ğı'],
    ['windows-874', [0xa1, 0xa2], 'กข'],
    ['iso-8859-15', [0xa4], '€'],
    ['iso-8859-2', [0xb1], 'ą'],
    ['gbk', [0xd6, 0xd0], '中'],
  ] as const)('decodes %s', (charset, raw, text) => {
    expect(decodeText(Uint8Array.from(raw), charset)).toBe(text);
  });

  it('auto: valid UTF-8 is UTF-8, anything else is Latin-1', () => {
    expect(decodeText(utf8('Müller'), 'auto')).toBe('Müller');
    expect(decodeText(bytes(0x4d, 0xfc, 0x6c, 0x6c, 0x65, 0x72), 'auto')).toBe('Müller'); // lone 0xFC is not UTF-8
    expect(decodeText(utf8('plain ASCII'), 'auto')).toBe('plain ASCII');
  });

  it('never throws on malformed input', () => {
    expect(decodeText(bytes(0xff, 0xfe, 0x41), 'utf-8')).toBe('��A');
  });
});
