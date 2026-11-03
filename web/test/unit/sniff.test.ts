import { describe, expect, it } from 'vitest';
import { sniffDicom } from '../../src/core/sniff';
import { baseElements, concat, el, part10 } from './dicom-bytes';

const bytes = (...b: number[]): Uint8Array => Uint8Array.from(b);
const ascii = (s: string): Uint8Array => new TextEncoder().encode(s);

/** Deterministic noise of 16-bit-ish samples whose first two bytes are `first`. */
const noise = (n: number, first: number[], seed = 1): Uint8Array => {
  let x = seed;
  const out = Uint8Array.from({ length: n }, () => ((x = (x * 1103515245 + 12345) & 0x7fffffff) >> 16) & 0xff);
  out.set(first, 0);
  return out;
};

describe('sniffDicom', () => {
  it('recognises DICM at offset 128', () => {
    expect(sniffDicom(part10(baseElements()))).toBe('part10');
    expect(sniffDicom(concat(new Uint8Array(128), ascii('DICM')))).toBe('part10');
  });

  it('requires DICM exactly at 128', () => {
    expect(sniffDicom(concat(new Uint8Array(127), ascii('DICM'), new Uint8Array(8)))).toBe('not-dicom');
  });

  it('raw explicit VR: starts at group 0008 and the first elements walk cleanly', () => {
    expect(sniffDicom(baseElements(false))).toBe('raw-explicit-le');
  });

  it('raw implicit VR', () => {
    expect(sniffDicom(baseElements(true))).toBe('raw-implicit-le');
  });

  it('raw with a meta header: starts with group 0002, dataset syntax is not guessed', () => {
    const meta = concat(el([2, 2], 'UI', '1.2.840.10008.5.1.4.1.1.4'), el([2, 0x10], 'UI', '1.2.840.10008.1.2'));
    expect(sniffDicom(concat(meta, baseElements(true)))).toBe('raw-meta');
    expect(sniffDicom(concat(meta, baseElements(false)))).toBe('raw-meta');
  });

  it('an element with an undefined length (sequence) ends the walk as plausible', () => {
    const sq = concat(bytes(8, 0, 0x15, 0x11, 0x53, 0x51, 0, 0, 0xff, 0xff, 0xff, 0xff), new Uint8Array(8));
    expect(sniffDicom(sq)).toBe('raw-explicit-le');
  });

  it('rejects everything else', () => {
    expect(sniffDicom(new Uint8Array())).toBe('not-dicom');
    expect(sniffDicom(bytes(0x08, 0, 0x18, 0))).toBe('not-dicom'); // too short
    expect(sniffDicom(ascii('This is a readme file.\n'))).toBe('not-dicom');
    expect(sniffDicom(bytes(0x00, 0x05, 0x16, 0x07, 0, 2, 0, 0, 0, 0))).toBe('not-dicom'); // AppleDouble
    expect(sniffDicom(bytes(0x09, 0, 0x01, 0, 0x4f, 0x42, 0, 0))).toBe('not-dicom'); // odd group
    expect(sniffDicom(bytes(0x12, 0, 0x01, 0, 0x4f, 0x42, 0, 0))).toBe('not-dicom'); // group > 8
    expect(sniffDicom(bytes(0x10, 0, 0x10, 0, 0x50, 0x4e, 0, 0))).toBe('not-dicom'); // group 0010 first
    expect(sniffDicom(new Uint8Array(200))).toBe('not-dicom'); // zeros, no DICM
  });

  it('rejects a bogus VR, an odd length, a length that does not fit, descending tags', () => {
    const good = el([8, 0x16], 'UI', '1.2.3.4');
    expect(sniffDicom(concat(good, baseElements()))).toBe('raw-explicit-le'); // control: ascending
    expect(sniffDicom(bytes(8, 0, 5, 0, 0x5a, 0x5a, 2, 0, 0x41, 0x42))).toBe('not-dicom'); // VR 'ZZ'
    expect(sniffDicom(bytes(8, 0, 5, 0, 0x43, 0x53, 3, 0, 0x41, 0x42, 0x43, 0))).toBe('not-dicom'); // odd length
    expect(sniffDicom(bytes(8, 0, 5, 0, 0x43, 0x53, 100, 0, 0x41, 0x42))).toBe('not-dicom'); // does not fit
    expect(sniffDicom(concat(el([8, 0x60], 'CS', 'MR'), el([8, 0x18], 'UI', '1.2')))).toBe('not-dicom'); // descending
    expect(sniffDicom(concat(el([8, 0x18], 'UI', '1.2'), el([8, 0x18], 'UI', '1.2')))).toBe('not-dicom'); // not strictly ascending
  });

  it('int16-like noise starting with a plausible group is not DICOM', () => {
    for (let seed = 1; seed <= 300; seed++) {
      expect(sniffDicom(noise(4096, [0x08, 0x00], seed))).toBe('not-dicom');
      expect(sniffDicom(noise(4096, [0x02, 0x00], seed))).toBe('not-dicom');
    }
  });
});
