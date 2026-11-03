import { readFileSync } from 'node:fs';
import { deflateRawSync, inflateRawSync } from 'node:zlib';
import * as dicomParser from 'dicom-parser';
import { describe, expect, test } from 'vitest';
import { INFLATE_PUSH_BYTES, InflateCapError, inflateCapped, inflateDeflatedFile, transferSyntaxOf } from '../../src/core/deflate';
import { DEFLATED_LE, EXPLICIT_LE, parseHeader } from '../../src/core/header';
import { fileSource } from '../../src/shell/source';

const dfl = new Uint8Array(readFileSync(new URL('../fixtures/tree/pydicom/dfl.dcm', import.meta.url)));
const plain = new Uint8Array(readFileSync(new URL('../fixtures/tree/pydicom/mr_1_small.dcm', import.meta.url)));
/** Byte equality (vitest's toEqual is very slow on large typed arrays). */
const same = (a: Uint8Array, b: Uint8Array): boolean => Buffer.compare(a, b) === 0;
const source = fileSource(new File([new Uint8Array(1)], 'f'));

describe('transferSyntaxOf', () => {
  test('reads the syntax from the meta header', () => {
    expect(transferSyntaxOf(dfl)).toBe(DEFLATED_LE);
    expect(transferSyntaxOf(plain)).not.toBe(DEFLATED_LE);
    expect(transferSyntaxOf(new Uint8Array(300))).toBeNull();
    expect(transferSyntaxOf(new Uint8Array(10))).toBeNull();
  });
});

describe('inflateDeflatedFile (image_dfl fixture)', () => {
  const out = inflateDeflatedFile(dfl);

  test('the fixture really is deflated, and the result is explicit VR LE', () => {
    expect(parseHeader(dfl, { source, relPath: 'a', truncated: false })).toMatchObject({ kind: 'instance', instance: { transferSyntax: DEFLATED_LE } });
    const r = parseHeader(out, { source, relPath: 'a', truncated: false });
    expect(r).toMatchObject({ kind: 'instance', instance: { transferSyntax: EXPLICIT_LE } });
    const original = parseHeader(dfl, { source, relPath: 'a', truncated: false });
    if (r.kind === 'instance' && original.kind === 'instance') {
      expect(r.instance.series).toEqual(original.instance.series);
      expect(r.instance.study).toEqual(original.instance.study);
      expect(r.instance.patient).toEqual(original.instance.patient);
    }
    expect(transferSyntaxOf(out)).toBe(EXPLICIT_LE);
  });

  test('group length is exact and the dataset is the inflated original, byte for byte', () => {
    const ds = dicomParser.parseDicom(out);
    expect(ds.string('x00020010')).toBe(EXPLICIT_LE);
    const metaEnd = 132 + 12 + new DataView(dfl.buffer, dfl.byteOffset).getUint32(140, true);
    const inflated = new Uint8Array(inflateRawSync(dfl.subarray(metaEnd)));
    expect(132 + 12 + ds.uint32('x00020000')!).toBe(out.length - inflated.length);
    expect(same(out.subarray(out.length - inflated.length), inflated)).toBe(true);
  });

  test('pixel data length matches Rows x Columns x bytes per sample', () => {
    const ds = dicomParser.parseDicom(out);
    const expected = ds.uint16('x00280010')! * ds.uint16('x00280011')! * (ds.uint16('x00280100')! / 8) * (ds.uint16('x00280002') ?? 1);
    expect(ds.elements['x7fe00010']!.length).toBe(expected);
  });
});

describe('inflateDeflatedFile errors', () => {
  test('rejects files that are not deflated Part 10', () => {
    expect(() => inflateDeflatedFile(plain)).toThrow(/Deflated/);
    expect(() => inflateDeflatedFile(new Uint8Array(500))).toThrow(/Deflated/);
  });

  test('a truncated stream is an error, not a short result', () => {
    expect(() => inflateDeflatedFile(dfl.subarray(0, dfl.length - 40))).toThrow(/corrupt or truncated/);
  });

  test('refuses to inflate beyond the cap', () => {
    expect(() => inflateDeflatedFile(dfl, 100)).toThrow(InflateCapError);
    expect(() => inflateDeflatedFile(dfl, 100)).toThrow(/more than/);
  });
});

describe('inflateCapped', () => {
  test('stops a high-ratio stream soon after the cap instead of inflating it all first', () => {
    const bomb = new Uint8Array(deflateRawSync(new Uint8Array(96 * 1024 * 1024), { level: 9 }));
    expect(bomb.length).toBeLessThan(400 * 1024);
    const cap = 1024 * 1024;
    const seen: number[] = [];
    expect(() => inflateCapped(bomb, cap, (n) => seen.push(n))).toThrow(/more than/);
    const produced = seen.reduce((a, b) => a + b, 0);
    // One input piece of ~1000:1 data is at most ~INFLATE_PUSH_BYTES * 1032 bytes; the whole bomb would be 96 MB.
    expect(produced).toBeLessThan(cap + INFLATE_PUSH_BYTES * 1100);
    expect(produced).toBeLessThan(96 * 1024 * 1024);
  }, 30_000);

  test('returns every chunk of a normal stream, in order', () => {
    const data = new Uint8Array(300_000).map((_, i) => (i * 7) & 0xff);
    const chunks = inflateCapped(new Uint8Array(deflateRawSync(data)), 1 << 30);
    const out = new Uint8Array(chunks.reduce((n, c) => n + c.length, 0));
    let at = 0;
    for (const c of chunks) (out.set(c, at), (at += c.length));
    expect(same(out, data)).toBe(true);
  });
});

describe('meta header variants', () => {
  const metaEnd = 132 + 12 + new DataView(dfl.buffer, dfl.byteOffset).getUint32(140, true);
  const expectedOut = inflateDeflatedFile(dfl);

  test('no (0002,0000): the meta end is found by walking group 0002', () => {
    const noGroupLength = new Uint8Array([...dfl.subarray(0, 132), ...dfl.subarray(144)]);
    expect(transferSyntaxOf(noGroupLength)).toBe(DEFLATED_LE);
    const out = inflateDeflatedFile(noGroupLength);
    expect(same(out, expectedOut)).toBe(true); // a group length is regenerated, so the result is identical
    expect(parseHeader(out, { source, relPath: 'a', truncated: false })).toMatchObject({ kind: 'instance', instance: { transferSyntax: EXPLICIT_LE } });
  });

  test('raw meta (no preamble): rewritten as a Part 10 file', () => {
    const rawMeta = dfl.subarray(132);
    const out = inflateDeflatedFile(rawMeta);
    expect(same(out, expectedOut)).toBe(true);
    const noGroupLengthRaw = new Uint8Array([...dfl.subarray(144, metaEnd), ...dfl.subarray(metaEnd)]);
    expect(same(inflateDeflatedFile(noGroupLengthRaw), expectedOut)).toBe(true);
  });

  test('a stream that is not a meta header is still rejected', () => {
    expect(() => inflateDeflatedFile(new Uint8Array([...dfl.subarray(0, 132), 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]))).toThrow(/Deflated/);
  });
});
