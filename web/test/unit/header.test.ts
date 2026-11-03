import { createDeflateRaw, deflateRawSync, inflateRawSync } from 'node:zlib';
import * as dicomParser from 'dicom-parser';
import { describe, expect, it } from 'vitest';
import {
  ESCALATED_BYTES,
  HEADER_BYTES,
  INFLATE_CAP,
  boundedInflate,
  parseHeader,
  readOutcome,
} from '../../src/core/header';
import type { HeaderOutcome, Instance } from '../../src/core/types';
import {
  DEFLATED_LE,
  EXPLICIT_LE,
  IMPLICIT_LE,
  baseElements,
  concat,
  el,
  part10,
  pixelData,
  sequence,
  u16,
  u32,
} from './dicom-bytes';
import { fileSource } from '../../src/shell/source';

const source = fileSource(new File([new Uint8Array(1)], 'f'));

/** Deterministic pseudo-random (incompressible) bytes. */
const prng = (n: number, seed: number): Uint8Array<ArrayBuffer> => {
  let x = seed * 2654435761 + 1;
  return Uint8Array.from({ length: n }, () => {
    x ^= x << 13;
    x ^= x >>> 17;
    x ^= x << 5;
    return (x >>> 0) & 0xff;
  });
};
const parse = (bytes: Uint8Array, truncated = false): HeaderOutcome =>
  parseHeader(bytes, { source, relPath: 'a/b.dcm', truncated });

const instanceOf = (o: HeaderOutcome): Instance => {
  if (o.kind !== 'instance') throw new Error(`expected instance, got ${JSON.stringify(o)}`);
  return o.instance;
};

/** baseElements plus extra elements appended after it; a repeated tag replaces the earlier one in dicom-parser's table. */
const withExtra = (...extra: Uint8Array[]): Uint8Array => part10(concat(baseElements(false, extra), pixelData(8, 8)));

describe('parseHeader: happy path', () => {
  it('reads every field of a Part 10 explicit VR file', () => {
    const i = instanceOf(parse(part10(concat(baseElements(), pixelData(8, 8)))));
    expect(i).toEqual({
      source,
      relPath: 'a/b.dcm',
      sopInstanceUid: '1.2.3.4.5',
      transferSyntax: '1.2.840.10008.1.2.1',
      patient: { id: 'PAT001', name: 'Doe^Jane' },
      study: { uid: '1.2.3.1', date: '20260101', time: '093000', description: 'Brain MRI', accessionNumber: '' },
      series: { uid: '1.2.3.1.1', number: 3, description: 'T1 MPRAGE', modality: 'MR' },
      instanceNumber: 7,
      echoNumber: null,
      frames: 1,
      window: null,
    });
    expect(i.source).toBe(source);
  });

  it('parses a raw explicit VR dataset (no preamble); transferSyntax is null', () => {
    const i = instanceOf(parse(concat(baseElements(false), pixelData(8, 8))));
    expect(i.transferSyntax).toBeNull();
    expect(i.patient.name).toBe('Doe^Jane');
    expect(i.series.number).toBe(3);
  });

  it('parses a raw implicit VR dataset', () => {
    const i = instanceOf(parse(concat(baseElements(true), pixelData(8, 8, true))));
    expect(i.transferSyntax).toBeNull();
    expect(i.study.uid).toBe('1.2.3.1');
    expect(i.patient.id).toBe('PAT001');
    expect(i.instanceNumber).toBe(7);
  });

  it('parses a Part 10 implicit VR file', () => {
    const i = instanceOf(parse(part10(concat(baseElements(true), pixelData(8, 8, true)), { transferSyntax: IMPLICIT_LE })));
    expect(i.transferSyntax).toBe(IMPLICIT_LE);
    expect(i.series.description).toBe('T1 MPRAGE');
  });

  it('parses a deflated file (inflater gets the input and the end of the meta header)', () => {
    const dataset = concat(baseElements(), pixelData(8, 8));
    const header = part10(new Uint8Array(0), { transferSyntax: DEFLATED_LE });
    const deflated = concat(header, new Uint8Array(deflateRawSync(dataset)));
    const i = instanceOf(parse(deflated));
    expect(i.transferSyntax).toBe(DEFLATED_LE);
    expect(i.patient).toEqual({ id: 'PAT001', name: 'Doe^Jane' });
    expect(i.series.uid).toBe('1.2.3.1.1');
  });

  it('works when the dataset has no PixelData at all', () => {
    expect(parse(part10(baseElements())).kind).toBe('instance');
  });
});

describe('parseHeader: normalisation', () => {
  it('trims trailing space and NUL padding, keeps ^, maps blank to empty string', () => {
    const i = instanceOf(
      parse(
        part10(
          concat(
            el([8, 0x18], 'UI', '1.2.3.4.5\0'),
            el([8, 0x1030], 'LO', '   '),
            el([8, 0x103e], 'LO', 'T1  '),
            el([0x10, 0x10], 'PN', 'Doe^Jane^^^ '),
            el([0x10, 0x20], 'LO', ''),
            el([0x20, 0x0d], 'UI', '1.2.3.1'),
            el([0x20, 0x0e], 'UI', '1.2.3.1.1'),
          ),
        ),
      ),
    );
    expect(i.sopInstanceUid).toBe('1.2.3.4.5');
    expect(i.study.description).toBe('');
    expect(i.series.description).toBe('T1');
    expect(i.patient).toEqual({ id: '', name: 'Doe^Jane' });
    expect(i.series.modality).toBe('');
  });

  it('absent optional fields are null / empty', () => {
    const i = instanceOf(parse(part10(concat(el([0x20, 0x0d], 'UI', '1.1'), el([0x20, 0x0e], 'UI', '1.2')))));
    expect(i).toMatchObject({
      sopInstanceUid: null,
      patient: { id: '', name: '' },
      study: { date: null, time: null, description: '', accessionNumber: '' },
      series: { number: null, description: '', modality: '' },
      instanceNumber: null,
      echoNumber: null,
      frames: 1,
      window: null,
    });
  });

  it('DA must be exactly 8 digits; TM must be HH[MM[SS[.f]]]', () => {
    const dt = (d: string, t: string) => instanceOf(parse(withExtra(el([8, 0x20], 'DA', d), el([8, 0x30], 'TM', t))));
    // baseElements already has 0008,0020; a duplicate later in the stream replaces the table entry.
    expect(dt('20260315', '1530').study).toMatchObject({ date: '20260315', time: '1530' });
    expect(dt('2026.03.15', '15:30').study).toMatchObject({ date: null, time: null });
    expect(dt('2026031', '153000.123456').study).toMatchObject({ date: null, time: '153000.123456' });
    expect(dt('abcdefgh', '').study).toMatchObject({ date: null, time: null });
    expect(dt('202603150', 'xx').study).toMatchObject({ date: null, time: null });
  });

  it('numbers: strict IS/DS grammar, space padded; junk is null, never NaN', () => {
    const nums = (series: string, inst: string, echo?: string) =>
      instanceOf(
        parse(
          withExtra(
            el([0x20, 0x11], 'IS', series),
            el([0x20, 0x13], 'IS', inst),
            ...(echo === undefined ? [] : [el([0x18, 0x86], 'IS', echo)]),
          ),
        ),
      );
    expect(nums(' 12 ', '+5')).toMatchObject({ series: { number: 12 }, instanceNumber: 5 });
    expect(nums('-3', '007', '2')).toMatchObject({ series: { number: -3 }, instanceNumber: 7, echoNumber: 2 });
    expect(nums('2\\3', '1\\2', '2\\1').echoNumber).toBe(2); // first value of a list
    expect(nums('abc', '')).toMatchObject({ series: { number: null }, instanceNumber: null });
    expect(nums('1x', '0x10', 'NaN')).toMatchObject({ series: { number: null }, instanceNumber: null, echoNumber: null });
    expect(nums('3.5', 'Infinity')).toMatchObject({ series: { number: null }, instanceNumber: null }); // not integers
    expect(nums('3.0', '1e1')).toMatchObject({ series: { number: 3 }, instanceNumber: 10 }); // integral DS-style
  });

  it('NumberOfFrames: whole number 1..100000; absent or invalid is 1', () => {
    const frames = (v?: string) =>
      instanceOf(parse(v === undefined ? withExtra() : withExtra(el([0x28, 0x08], 'IS', v)))).frames;
    expect(frames()).toBe(1);
    expect(frames('24')).toBe(24);
    expect(frames(' 8 ')).toBe(8);
    expect(frames('100000')).toBe(100_000);
    for (const bad of ['0', '-3', '2.5', '1e1', 'abc', '', '3\\4', '100001', '999999999']) expect(frames(bad)).toBe(1);
  });

  it('window: first value of each list, both finite or null', () => {
    const win = (c?: string, w?: string) =>
      instanceOf(
        parse(
          withExtra(
            ...(c === undefined ? [] : [el([0x28, 0x1050], 'DS', c)]),
            ...(w === undefined ? [] : [el([0x28, 0x1051], 'DS', w)]),
          ),
        ),
      ).window;
    expect(win('40', '400')).toEqual({ center: 40, width: 400 });
    expect(win(' 40.5\\100 ', '4e2\\800')).toEqual({ center: 40.5, width: 400 });
    expect(win('-600', '1500')).toEqual({ center: -600, width: 1500 });
    expect(win('40')).toBeNull();
    expect(win(undefined, '400')).toBeNull();
    expect(win('abc', '400')).toBeNull();
    expect(win('40', 'NaN')).toBeNull();
    expect(win('1e999', '400')).toBeNull(); // overflows to Infinity
  });
});

describe('parseHeader: character sets', () => {
  const named = (spec: string | null, nameBytes: Uint8Array): Instance =>
    instanceOf(
      parse(
        part10(
          concat(
            ...(spec === null ? [] : [el([8, 5], 'CS', spec)]),
            el([0x10, 0x10], 'PN', nameBytes),
            el([0x20, 0x0d], 'UI', '1.1'),
            el([0x20, 0x0e], 'UI', '1.2'),
          ),
        ),
      ),
    );

  it('ISO_IR 192 decodes UTF-8', () => {
    expect(named('ISO_IR 192', new TextEncoder().encode('Müller^Jürgen')).patient.name).toBe('Müller^Jürgen');
  });

  it('ISO_IR 100 and the default decode Latin-1', () => {
    const latin = Uint8Array.from([0x4d, 0xfc, 0x6c, 0x6c, 0x65, 0x72, 0x5e, 0x4a]); // Müller^J
    expect(named('ISO_IR 100', latin).patient.name).toBe('Müller^J');
    expect(named(null, latin).patient.name).toBe('Müller^J');
  });

  it('absent SpecificCharacterSet: valid UTF-8 is read as UTF-8, otherwise Latin-1', () => {
    expect(named(null, new TextEncoder().encode('Müller^Jürgen')).patient.name).toBe('Müller^Jürgen');
    expect(named(null, Uint8Array.from([0x4d, 0xfc, 0x6c])).patient.name).toBe('Mül');
    expect(named('', Uint8Array.from([0x4d, 0xfc, 0x6c])).patient.name).toBe('Mül');
  });

  it('single-byte ISO 2022 terms decode like their ISO_IR forms', () => {
    expect(named('ISO 2022 IR 144', Uint8Array.from([0xb8, 0xd2, 0xd0, 0xdd])).patient.name).toBe('Иван');
    expect(named('ISO_IR 126', Uint8Array.from([0xe1, 0xe2])).patient.name).toBe('αβ');
    expect(named('GBK', Uint8Array.from([0xd6, 0xd0])).patient.name).toBe('中');
  });

  it('ISO_IR 144 decodes Cyrillic; multi-valued uses the first non-empty term', () => {
    const cyr = Uint8Array.from([0xb8, 0xd2, 0xd0, 0xdd]);
    expect(named('ISO_IR 144', cyr).patient.name).toBe('Иван');
    expect(named('ISO_IR 144\\ISO_IR 100', cyr).patient.name).toBe('Иван');
  });

  it('AccessionNumber is decoded with the dataset charset', () => {
    const acc = (spec: string | null, bytes: Uint8Array | string): string =>
      instanceOf(
        parse(
          part10(
            concat(
              ...(spec === null ? [] : [el([8, 5], 'CS', spec)]),
              el([8, 0x50], 'SH', bytes),
              el([0x20, 0x0d], 'UI', '1.1'),
              el([0x20, 0x0e], 'UI', '1.2'),
            ),
          ),
        ),
      ).study.accessionNumber;
    expect(acc(null, 'ACC-0042 ')).toBe('ACC-0042');
    expect(acc('ISO_IR 192', new TextEncoder().encode('Zürich1'))).toBe('Zürich1'); // 8 bytes
    expect(acc('ISO_IR 144', Uint8Array.from([0xb8, 0xd2, 0xd0, 0xdd]))).toBe('Иван');
    expect(acc('ISO_IR 100', Uint8Array.from([0x4d, 0xfc, 0x6c, 0x6c]))).toBe('Müll');
    expect(acc(null, '')).toBe('');
  });

  it('absent AccessionNumber is an empty string', () => {
    expect(instanceOf(parse(part10(concat(baseElements(), pixelData(8, 8))))).study.accessionNumber).toBe('');
  });

  it('UTF-8 with an odd-length name keeps multibyte characters whole (padding is a trailing space)', () => {
    expect(named('ISO_IR 192', new TextEncoder().encode('Jürgen')).patient.name).toBe('Jürgen'); // 7 bytes + pad
  });
});

describe('parseHeader: outcomes other than instance', () => {
  it('non-DICOM input is skipped', () => {
    expect(parse(new TextEncoder().encode('hello world, plain text file'))).toEqual({ kind: 'skipped', reason: 'not-dicom' });
    expect(parse(new Uint8Array())).toEqual({ kind: 'skipped', reason: 'not-dicom' });
    expect(parse(Uint8Array.from([0, 5, 0x16, 7, 0, 2, 0, 0, 0, 0]), true)).toEqual({ kind: 'skipped', reason: 'not-dicom' });
  });

  it('DICOMDIR (by MediaStorageSOPClassUID) is skipped as dicomdir, even when truncated', () => {
    const dir = part10(baseElements(), { sopClass: '1.2.840.10008.1.3.10' });
    expect(parse(dir)).toEqual({ kind: 'skipped', reason: 'dicomdir' });
    expect(parse(dir, true)).toEqual({ kind: 'skipped', reason: 'dicomdir' });
  });

  it('truncated with no dataset at all (no transfer syntax in the meta header): not-dicom, not needs-more', () => {
    const noSyntax = concat(new Uint8Array(128), new TextEncoder().encode('DICM'), el([2, 2], 'UI', '1.2.3'), baseElements());
    expect(parse(noSyntax, true)).toEqual({ kind: 'skipped', reason: 'not-dicom' });
    expect(parse(noSyntax, false)).toEqual({ kind: 'skipped', reason: 'not-dicom' });
  });

  it('Part 10 with an unreadable meta header or empty dataset is not-dicom', () => {
    const preambleOnly = concat(new Uint8Array(128), new TextEncoder().encode('DICM'));
    expect(parse(preambleOnly)).toEqual({ kind: 'skipped', reason: 'not-dicom' });
    expect(parse(part10(new Uint8Array(0)))).toEqual({ kind: 'skipped', reason: 'not-dicom' }); // meta only
  });

  it('missing Study or Series UID: rejected (whole file)', () => {
    const noSeries = part10(concat(el([0x10, 0x10], 'PN', 'A^B'), el([0x20, 0x0d], 'UI', '1.1'), pixelData(8, 8)));
    expect(parse(noSeries)).toEqual({ kind: 'rejected', reason: 'missing SeriesInstanceUID' });
    const none = part10(concat(el([0x10, 0x10], 'PN', 'A^B'), pixelData(8, 8)));
    expect(parse(none)).toEqual({ kind: 'rejected', reason: 'missing StudyInstanceUID and SeriesInstanceUID' });
    const blank = part10(concat(el([0x20, 0x0d], 'UI', '1.1'), el([0x20, 0x0e], 'UI', '  '), pixelData(8, 8)));
    expect(parse(blank).kind).toBe('rejected');
  });

  it('truncated: PixelData reached means the header is complete, even if UIDs are missing', () => {
    const noSeries = part10(concat(el([0x20, 0x0d], 'UI', '1.1'), pixelData(100000, 0)));
    expect(parse(noSeries, true)).toEqual({ kind: 'rejected', reason: 'missing SeriesInstanceUID' });
    expect(parse(part10(concat(baseElements(), pixelData(100000, 10))), true).kind).toBe('instance');
  });

  it('truncated: header cut before PixelData is needs-more, never an instance or rejection', () => {
    // SeriesInstanceUID lies past the cut.
    const full = part10(concat(baseElements(), pixelData(8, 8)));
    const cutEarly = full.subarray(0, 132 + 80 + 60); // inside the header
    expect(parse(cutEarly, true)).toEqual({ kind: 'needs-more' });
    // Cut after the UIDs but before later optional fields: still needs the whole file.
    const cutLate = part10(baseElements());
    expect(parse(cutLate, true)).toEqual({ kind: 'needs-more' });
  });

  it.each([
    ['explicit', false],
    ['implicit', true],
  ])('a %s element cut mid-value is treated as absent and does not throw', (_name, implicit) => {
    const ts = implicit ? IMPLICIT_LE : undefined;
    const full = part10(concat(baseElements(implicit), pixelData(8, 8, implicit)), ts ? { transferSyntax: ts } : {});
    for (let cut = 0; cut <= full.length; cut++) {
      const slice = full.subarray(0, cut);
      for (const truncated of [true, false]) {
        const out = parse(slice, truncated);
        if (out.kind === 'instance') {
          // never invents or truncates values
          expect(out.instance.study.uid === '1.2.3.1').toBe(true);
          expect(out.instance.series.uid).toBe('1.2.3.1.1');
          expect(out.instance.patient.name === '' || out.instance.patient.name === 'Doe^Jane').toBe(true);
        }
        if (!truncated) expect(out.kind).not.toBe('needs-more');
      }
    }
  });

  it.each([false, true])('(implicit=%s) an element whose value runs past the buffer is not read', (implicit) => {
    const uids = concat(el([0x20, 0x0d], 'UI', '1.1', implicit), el([0x20, 0x0e], 'UI', '1.2', implicit));
    const cutName = el([0x10, 0x10], 'PN', 'Doe^Jane', implicit).subarray(0, 8 + 3); // 8-byte header, 3 of 8 value bytes
    const bytes = concat(uids, cutName);
    const out = parse(part10(bytes, implicit ? { transferSyntax: IMPLICIT_LE } : {}), false);
    expect(out.kind === 'instance' ? [out.instance.series.uid, out.instance.patient.name] : null).toEqual(['1.2', '']);
  });

  it('corrupt deflate stream: not-dicom, or needs-more when truncated; never throws', () => {
    const header = part10(new Uint8Array(0), { transferSyntax: DEFLATED_LE });
    const bad = concat(header, Uint8Array.from([0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff]));
    expect(parse(bad)).toEqual({ kind: 'skipped', reason: 'not-dicom' });
    expect(parse(bad, true)).toEqual({ kind: 'needs-more' });
  });

  it('a deflate stream cut after the header still gives an instance when truncated', () => {
    const dataset = concat(baseElements(), pixelData(100000, 100000));
    dataset.set(prng(100000, 7), dataset.length - 100000); // incompressible pixel data
    const stream = new Uint8Array(deflateRawSync(dataset));
    const head = part10(new Uint8Array(0), { transferSyntax: DEFLATED_LE });
    const cut = concat(head, stream.subarray(0, stream.length >> 1));
    expect(instanceOf(parse(cut, true)).series.uid).toBe('1.2.3.1.1');
    expect(parse(cut, false).kind).toBe('instance'); // a cut file is still read as far as it goes
  });

  it('a deflate stream cut before the header ends needs more (whether or not any block was inflated)', () => {
    const dataset = concat(baseElements(), el([9, 0x10], 'OB', prng(100000, 3)), pixelData(8, 8));
    const stream = new Uint8Array(deflateRawSync(dataset));
    const head = part10(new Uint8Array(0), { transferSyntax: DEFLATED_LE });
    // fflate emits whole blocks only: 300 bytes inflate to nothing, half the stream to a partial dataset.
    expect(parse(concat(head, stream.subarray(0, 300)), true)).toEqual({ kind: 'needs-more' });
    expect(parse(concat(head, stream.subarray(0, stream.length >> 1)), true)).toEqual({ kind: 'needs-more' });
    expect(parse(concat(head, stream.subarray(0, 300)), false)).toEqual({ kind: 'skipped', reason: 'not-dicom' });
  });

  it('is total: arbitrary junk behind a DICM or raw-looking prefix never throws', () => {
    let seed = 12345;
    const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff) & 0xff;
    for (let n = 0; n < 200; n++) {
      const junk = Uint8Array.from({ length: 40 + (n % 70) }, rnd);
      for (const prefix of [part10(new Uint8Array(0)), Uint8Array.from([8, 0, 0x18, 0, 0x55, 0x49, 4, 0]), Uint8Array.from([8, 0, 5, 0])]) {
        for (const truncated of [true, false]) {
          expect(() => parse(concat(prefix, junk), truncated)).not.toThrow();
        }
      }
    }
  });
});

describe('readOutcome (read policy)', () => {
  const run = async (bytes: Uint8Array<ArrayBuffer>) => {
    const f = fileSource(new File([bytes], 'x'));
    const reads: number[] = [];
    const out = await readOutcome(f, 'x', async (n) => {
      reads.push(n);
      return bytes.subarray(0, n);
    });
    return { out, reads };
  };

  it('a small file is read once, whole', async () => {
    const bytes = part10(concat(baseElements(), pixelData(8, 8)));
    const { out, reads } = await run(bytes);
    expect(out.kind).toBe('instance');
    expect(reads).toEqual([bytes.length]);
  });

  it('a large file whose header fits in the prefix is read once, truncated', async () => {
    const bytes = part10(concat(baseElements(), pixelData(200000, 200000)));
    const { out, reads } = await run(bytes);
    expect(out.kind).toBe('instance');
    expect(reads).toEqual([HEADER_BYTES]);
  });

  it('a large file with a big header is retried whole', async () => {
    const bytes = part10(concat(el([9, 0x10], 'OB', new Uint8Array(80000)), baseElements(), pixelData(8, 8)));
    const { out, reads } = await run(bytes);
    expect(out.kind).toBe('instance');
    expect(reads).toEqual([HEADER_BYTES, bytes.length]);
  });

  it('a large non-DICOM file is not retried', async () => {
    const { out, reads } = await run(new Uint8Array(HEADER_BYTES + 10));
    expect(out).toEqual({ kind: 'skipped', reason: 'not-dicom' });
    expect(reads).toEqual([HEADER_BYTES]);
  });
});

const MIB = 1024 * 1024;

/** Runs the full read policy over `bytes`, as if the file were `size` bytes long, recording each read. */
const run = async (bytes: Uint8Array, size = bytes.length) => {
  const f = { ...fileSource(new File([], 'x')), size };
  const reads: number[] = [];
  const out = await readOutcome(f, 'x', async (n) => {
    reads.push(n);
    return bytes.subarray(0, n);
  });
  return { out, reads };
};

describe('header completeness: bounded reads', () => {
  it('a private 0029 block over 64 KB after the wanted tags: one 64 KB read', async () => {
    const bytes = part10(concat(baseElements(), el([0x29, 0x10], 'OB', new Uint8Array(80000)), pixelData(8, 8)));
    expect(bytes.length).toBeGreaterThan(HEADER_BYTES);
    const { out, reads } = await run(bytes);
    expect(out.kind).toBe('instance');
    expect(reads).toEqual([HEADER_BYTES]);
  });

  it('an OV element (64-bit VR dicom-parser does not know): one 64 KB read', async () => {
    const ov = el([0x7fe0, 0x0001], 'OV', new Uint8Array(16));
    const bytes = part10(concat(baseElements(), ov, pixelData(200000, 200000)));
    const { out, reads } = await run(bytes);
    expect(out.kind).toBe('instance');
    expect(reads).toEqual([HEADER_BYTES]);
  });

  it('an SR whose (0040,A730) content sequence exceeds 64 KB: one 64 KB read', async () => {
    const item = concat(el([0x40, 0xa010], 'CS', 'CONTAINS'), el([0x40, 0xa160], 'UT', new Uint8Array(1000).fill(0x61)));
    const content = sequence([0x40, 0xa730], Array.from({ length: 90 }, () => item), false, false);
    const sr = part10(concat(baseElements(), el([0x40, 0xa040], 'CS', 'CONTAINER'), content));
    expect(sr.length).toBeGreaterThan(HEADER_BYTES);
    const first = await run(sr);
    expect(first.out.kind).toBe('instance');
    expect(first.reads).toEqual([HEADER_BYTES]);
    // When the sequence is the first element past the wanted tags and dicom-parser fails inside it, it is
    // never recorded: one escalation (still bounded) is the price.
    const bare = part10(concat(baseElements(), content));
    const second = await run(bare);
    expect(second.out.kind).toBe('instance');
    expect(second.reads).toEqual([HEADER_BYTES, bare.length]);
  });

  it('escalates 64 KB -> 1 MB -> whole file, only as far as needed', async () => {
    const tail = (privateBytes: number) => part10(concat(el([9, 0x10], 'OB', new Uint8Array(privateBytes)), baseElements(), pixelData(8, 8)));
    const small = tail(80000); // header ends before 1 MB
    expect((await run(small)).reads).toEqual([HEADER_BYTES, small.length]); // 1 MB covers the file
    const big = tail(2 * MIB); // header ends past 1 MB
    const r = await run(big);
    expect(r.out.kind).toBe('instance');
    expect(r.reads).toEqual([HEADER_BYTES, ESCALATED_BYTES, big.length]);
  });

  it('a file over the whole-file cap whose header never ends is never read whole', async () => {
    const bytes = part10(concat(el([9, 0x10], 'OB', new Uint8Array(3 * MIB)), baseElements()));
    const { out, reads } = await run(bytes, 100 * MIB);
    expect(out).toEqual({ kind: 'rejected', reason: 'header not found in first 1 MB' });
    expect(reads).toEqual([HEADER_BYTES, ESCALATED_BYTES]);
  });

  it('a file over the cap whose header ends within 1 MB resolves', async () => {
    const bytes = part10(concat(el([9, 0x10], 'OB', new Uint8Array(200000)), baseElements(), pixelData(8, 8)));
    const { out, reads } = await run(bytes, 100 * MIB);
    expect(out.kind).toBe('instance');
    expect(reads).toEqual([HEADER_BYTES, ESCALATED_BYTES]);
  });

  it('truncated: a missing UID asks for more unless a later top-level tag was recorded', () => {
    const noSeries = (...later: Uint8Array[]) =>
      part10(concat(el([0x20, 0x0d], 'UI', '1.1'), el([0x10, 0x10], 'PN', 'A^B'), ...later));
    expect(parse(noSeries(), true)).toEqual({ kind: 'needs-more' });
    expect(parse(noSeries(el([0x29, 0x10], 'OB', new Uint8Array(100))), true)).toEqual({
      kind: 'rejected',
      reason: 'missing SeriesInstanceUID',
    });
  });

  it('a headerless file with no identity tags is noise: not-dicom, never escalated', async () => {
    const lookalike = concat(el([8, 5], 'CS', 'ISO_IR 100'), el([8, 8], 'CS', 'ORIGINAL'), el([0x10, 0x10], 'PN', 'A^B'));
    expect(parse(lookalike, true)).toEqual({ kind: 'skipped', reason: 'not-dicom' });
    expect(parse(lookalike, false)).toEqual({ kind: 'skipped', reason: 'not-dicom' });
    // int16 noise starting 08 00 in a file over 64 KB: one read, not-dicom
    let x = 99;
    const noise = Uint8Array.from({ length: 70000 }, () => ((x = (x * 1103515245 + 12345) & 0x7fffffff) >> 16) & 0xff);
    noise.set([8, 0]);
    const { out, reads } = await run(noise);
    expect(out).toEqual({ kind: 'skipped', reason: 'not-dicom' });
    expect(reads).toEqual([HEADER_BYTES]);
  });
});

describe('nested tags never count as top-level', () => {
  it('a SeriesInstanceUID inside (0008,1115) does not satisfy the missing top-level one', () => {
    const nested = sequence([8, 0x1115], [concat(el([0x20, 0x0d], 'UI', '9.9'), el([0x20, 0x0e], 'UI', '9.8'))]);
    const bytes = part10(concat(nested, el([0x20, 0x0d], 'UI', '1.1'), pixelData(8, 8)));
    expect(parse(bytes)).toEqual({ kind: 'rejected', reason: 'missing SeriesInstanceUID' });
  });

  it('PixelData nested in a sequence before the wanted tags does not complete a truncated header', () => {
    const nested = sequence([8, 0x1115], [concat(el([0x28, 0x10], 'US', new Uint8Array(2)), pixelData(4, 4))]);
    const bytes = part10(concat(nested, el([0x20, 0x0d], 'UI', '1.1')));
    expect(parse(bytes, true)).toEqual({ kind: 'needs-more' });
  });

  it('an icon sequence (0088,0200) holding PixelData, cut inside, completes via the sequence element itself', () => {
    // The nested PixelData is irrelevant; (0088,0200) is a top-level element past every wanted tag.
    const icon = sequence([0x88, 0x200], [concat(el([0x28, 0x10], 'US', new Uint8Array(2)), pixelData(4, 4))]);
    const full = part10(concat(baseElements(), icon));
    const cut = full.subarray(0, full.length - 16); // inside the item, after the nested PixelData header
    expect(instanceOf(parse(cut, true)).series.uid).toBe('1.2.3.1.1');
    // ...whereas without the sequence element recorded (cut before it ends nothing past the wanted tags) it would ask for more
    expect(parse(part10(baseElements()), true)).toEqual({ kind: 'needs-more' });
  });
});

describe('deflated files: bounded inflate', () => {
  it('boundedInflate returns everything for a small stream, and a prefix of the output when capped', () => {
    const data = prng(50000, 5);
    const stream = new Uint8Array(deflateRawSync(data));
    expect(boundedInflate(stream)).toEqual({ bytes: data, capped: false });
    const capped = boundedInflate(stream, 1000)!;
    expect(capped.capped).toBe(true);
    expect(capped.bytes).toEqual(data.subarray(0, 1000));
  });

  it('boundedInflate keeps what a cut or corrupt stream produced, null if nothing', () => {
    const data = prng(100000, 6);
    const stream = new Uint8Array(deflateRawSync(data));
    const half = boundedInflate(stream.subarray(0, stream.length >> 1))!;
    expect(half.capped).toBe(false);
    expect(half.bytes.length).toBeGreaterThan(0);
    expect(half.bytes).toEqual(data.subarray(0, half.bytes.length));
    expect(boundedInflate(Uint8Array.from([0xff, 0xff, 0xff, 0xff]))).toBeNull();
    expect(boundedInflate(new Uint8Array())).toBeNull();
  });

  it('a deflate bomb (256 MB zero OB) inflates to at most the cap, and the header still parses', async () => {
    const head = concat(baseElements(), u16(0x29), u16(0x10), new TextEncoder().encode('OB'), u16(0), u32(256 * MIB));
    const stream = await new Promise<Uint8Array>((resolve, reject) => {
      const d = createDeflateRaw({ level: 1 });
      const out: Buffer[] = [];
      d.on('data', (c: Buffer) => out.push(c));
      d.on('end', () => resolve(new Uint8Array(Buffer.concat(out))));
      d.on('error', reject);
      d.write(head);
      const zeros = Buffer.alloc(MIB);
      for (let i = 0; i < 256; i++) d.write(zeros);
      d.end();
    });
    expect(stream.length).toBeLessThan(2 * MIB);

    const r = boundedInflate(stream)!;
    expect(r.capped).toBe(true);
    expect(r.bytes.length).toBe(INFLATE_CAP);

    const file = concat(part10(new Uint8Array(0), { transferSyntax: DEFLATED_LE }), stream);
    expect(instanceOf(parse(file, false)).series.uid).toBe('1.2.3.1.1');
    expect(instanceOf(parse(file, true)).series.uid).toBe('1.2.3.1.1');
  });
});

describe('PN and window', () => {
  const name = (value: string | Uint8Array, spec: string | null = 'ISO_IR 192'): string =>
    instanceOf(
      parse(
        part10(
          concat(
            ...(spec === null ? [] : [el([8, 5], 'CS', spec)]),
            el([0x10, 0x10], 'PN', value),
            el([0x20, 0x0d], 'UI', '1.1'),
            el([0x20, 0x0e], 'UI', '1.2'),
          ),
        ),
      ),
    ).patient.name;

  it('keeps the first component group, dropping ideographic and phonetic groups', () => {
    expect(name('Yamada^Tarou=山田^太郎=やまだ^たろう')).toBe('Yamada^Tarou');
    expect(name('=山田^太郎')).toBe('山田^太郎');
    expect(name('^^^=Yamada^Tarou')).toBe('Yamada^Tarou');
  });

  it('does not leak ISO 2022 escape bytes from later groups', () => {
    const esc = Uint8Array.from([0x1b, 0x24, 0x42, 0x3b, 0x33, 0x45, 0x44, 0x1b, 0x28, 0x42]);
    const raw = concat(new TextEncoder().encode('Yamada^Tarou='), esc);
    expect(name(raw, '\\ISO 2022 IR 87')).toBe('Yamada^Tarou');
  });

  it('strips trailing separators', () => {
    expect(name('Doe^Jane^^^')).toBe('Doe^Jane');
    expect(name('Doe^Jane^^^ ')).toBe('Doe^Jane');
    expect(name('^^^^')).toBe('');
    expect(name('')).toBe('');
    expect(name('^Jane')).toBe('^Jane');
  });

  it('window width below 1 is not a window', () => {
    const win = (c: string, w: string) => instanceOf(parse(withExtra(el([0x28, 0x1050], 'DS', c), el([0x28, 0x1051], 'DS', w)))).window;
    expect(win('40', '1')).toEqual({ center: 40, width: 1 });
    expect(win('40', '0.5')).toBeNull();
    expect(win('40', '0')).toBeNull();
    expect(win('40', '-100')).toBeNull();
  });
});

describe('transfer syntax and meta oddities', () => {
  it('a space-padded transfer syntax UID is trimmed and the dataset parsed with the trimmed syntax', () => {
    const padded = part10(concat(baseElements(true), pixelData(8, 8, true)), { transferSyntax: `${IMPLICIT_LE} ` });
    const i = instanceOf(parse(padded));
    expect(i.transferSyntax).toBe(IMPLICIT_LE);
    expect(i.patient).toEqual({ id: 'PAT001', name: 'Doe^Jane' });
    expect(i.series.number).toBe(3);
  });

  it('a space-padded explicit syntax is unaffected', () => {
    const i = instanceOf(parse(part10(concat(baseElements(), pixelData(8, 8)), { transferSyntax: `${EXPLICIT_LE} ` })));
    expect(i.transferSyntax).toBe(EXPLICIT_LE);
    expect(i.series.uid).toBe('1.2.3.1.1');
  });

  it('a space-padded deflated syntax inflates the dataset part', () => {
    const deflated = new Uint8Array(deflateRawSync(concat(baseElements(), pixelData(8, 8))));
    const file = concat(part10(new Uint8Array(0), { transferSyntax: `${DEFLATED_LE} ` }), deflated);
    const i = instanceOf(parse(file));
    expect(i.transferSyntax).toBe(DEFLATED_LE);
    expect(i.series.uid).toBe('1.2.3.1.1');
  });

  it.each([
    ['implicit', true, IMPLICIT_LE],
    ['explicit', false, EXPLICIT_LE],
  ])('a headerless file starting with the meta group honours (0002,0010) (%s dataset)', (_n, implicit, ts) => {
    const meta = concat(el([2, 2], 'UI', '1.2.840.10008.5.1.4.1.1.4'), el([2, 0x10], 'UI', ts));
    const bytes = concat(meta, baseElements(implicit), pixelData(8, 8, implicit));
    const i = instanceOf(parse(bytes));
    expect(i.transferSyntax).toBe(ts);
    expect(i.patient).toEqual({ id: 'PAT001', name: 'Doe^Jane' });
    expect(i.study.uid).toBe('1.2.3.1');
  });

  it('a headerless meta-first DICOMDIR is skipped', () => {
    const meta = concat(el([2, 2], 'UI', '1.2.840.10008.1.3.10'), el([2, 0x10], 'UI', EXPLICIT_LE));
    expect(parse(concat(meta, baseElements()))).toEqual({ kind: 'skipped', reason: 'dicomdir' });
  });
});

describe('readOutcome: a non-DICOM file that is really a ZIP archive', () => {
  it('is not-dicom with a detail saying only .zip files are opened', async () => {
    const zipLike = new Uint8Array([0x50, 0x4b, 3, 4, ...new Uint8Array(200)]);
    const out = await readOutcome(fileSource(new File([zipLike], 'data.bin')), 'data.bin', async (n) => zipLike.subarray(0, n));
    expect(out).toEqual({ kind: 'skipped', reason: 'not-dicom', detail: 'looks like a ZIP archive (only files named .zip are opened)' });
    const plain = new TextEncoder().encode('just some text, not a zip');
    expect(await readOutcome(fileSource(new File([plain], 'a.txt')), 'a.txt', async (n) => plain.subarray(0, n))).toEqual({ kind: 'skipped', reason: 'not-dicom' });
  });
});

describe('readOutcome never rejects', () => {
  const big = part10(concat(el([9, 0x10], 'OB', new Uint8Array(80000)), baseElements(), pixelData(8, 8)));
  const f = fileSource(new File([big], 'x'));

  it('a failed first read is unreadable with the error message', async () => {
    const out = await readOutcome(f, 'x', async () => {
      throw new Error('NotReadableError: gone');
    });
    expect(out).toEqual({ kind: 'skipped', reason: 'unreadable', detail: 'NotReadableError: gone' });
  });

  it('a failed second read is unreadable (the first pass only said needs-more)', async () => {
    let calls = 0;
    const out = await readOutcome(f, 'x', async (n) => {
      if (++calls === 2) throw new Error('second');
      return big.subarray(0, n);
    });
    expect(calls).toBe(2);
    expect(out).toEqual({ kind: 'skipped', reason: 'unreadable', detail: 'second' });
  });

  it('a synchronous throw or a non-Error rejection is also contained', async () => {
    expect(await readOutcome(f, 'x', () => { throw 'plain string'; })).toEqual({ kind: 'skipped', reason: 'unreadable', detail: 'plain string' });
    expect((await readOutcome(f, 'x', () => Promise.reject(undefined))).kind).toBe('skipped');
  });

  it('a first-pass result that is already final is returned even if later reads would fail', async () => {
    const small = part10(concat(baseElements(), pixelData(8, 8)));
    let calls = 0;
    const out = await readOutcome(fileSource(new File([small], 'x')), 'x', async (n) => {
      calls++;
      return small.subarray(0, n);
    });
    expect(out.kind).toBe('instance');
    expect(calls).toBe(1);
  });
});

/** Pins the dicom-parser 1.8.21 behaviours header.ts is written around; a failure here means re-audit header.ts. */
describe('dicom-parser behaviours relied on', () => {
  const opts = (implicit: boolean) => ({
    untilTag: 'x7fe00010',
    TransferSyntaxUID: implicit ? IMPLICIT_LE : '1.2.840.10008.1.2.1',
  });
  const dataset = (implicit: boolean) => concat(baseElements(implicit), pixelData(8, 8, implicit));
  // The first element (0008,0018, 10 value bytes) has an 8-byte header in both encodings.
  const CUT_IN_VALUE = 12;
  const CUT_IN_HEADER = 4;

  const partial = (fn: () => unknown): dicomParser.DataSet => {
    try {
      fn();
    } catch (e) {
      return (e as { dataSet: dicomParser.DataSet }).dataSet;
    }
    throw new Error('expected parseDicom to throw');
  };

  it.each([false, true])('untilTag (implicit=%s) stops after reading the tag header; the element is included', (implicit) => {
    const bytes = concat(dataset(implicit).subarray(0, -8), new Uint8Array(1000));
    const px = dicomParser.parseDicom(bytes, opts(implicit)).elements['x7fe00010'];
    expect(px).toMatchObject({ tag: 'x7fe00010' });
    expect(px!.dataOffset).toBe(bytes.length - 1000);
  });

  it('explicit: a value cut by the end of the buffer throws "buffer overrun" with the cut element recorded', () => {
    const bytes = dataset(false).subarray(0, CUT_IN_VALUE);
    const ds = partial(() => dicomParser.parseDicom(bytes, opts(false)));
    const el0 = ds.elements['x00080018']!;
    expect(el0.dataOffset + el0.length).toBeGreaterThan(bytes.length);
  });

  it('implicit: a value cut by the end of the buffer does NOT throw; the cut element is recorded', () => {
    const bytes = dataset(true).subarray(0, CUT_IN_VALUE);
    const el0 = dicomParser.parseDicom(bytes, opts(true)).elements['x00080018']!;
    expect(el0.dataOffset + el0.length).toBeGreaterThan(bytes.length);
  });

  it.each([false, true])('(implicit=%s) a cut inside an element header throws with the earlier elements attached', (implicit) => {
    const bytes = dataset(implicit).subarray(0, 18 + CUT_IN_HEADER);
    const ds = partial(() => dicomParser.parseDicom(bytes, opts(implicit)));
    expect(Object.keys(ds.elements)).toEqual(['x00080018']);
  });

  it('deflated: inflater gets the whole input and the end of the meta header; its return value is the dataset only', () => {
    const header = part10(new Uint8Array(0), { transferSyntax: DEFLATED_LE });
    const input = concat(header, new Uint8Array(deflateRawSync(baseElements())));
    const calls: number[][] = [];
    const inflater = (arr: Uint8Array, position: number): Uint8Array => {
      calls.push([arr.length, position]);
      return new Uint8Array(inflateRawSync(arr.subarray(position)));
    };
    const ds = dicomParser.parseDicom(input, { inflater: inflater as unknown as () => void });
    expect(calls).toEqual([[input.length, header.length]]);
    expect(ds.byteArray.length).toBe(baseElements().length);
    expect(Object.keys(ds.elements)).toContain('x00020010'); // meta elements are merged in (offsets into the input)
  });
  it('does not know OV/SV/UV: the element is recorded with length 0 and the stream desynchronises', () => {
    const bytes = concat(baseElements(), el([0x7fe0, 1], 'OV', new Uint8Array(16)), pixelData(8, 8));
    const ds = dicomParser.parseDicom(bytes, { untilTag: 'x7fe00010', TransferSyntaxUID: EXPLICIT_LE });
    expect(ds.elements['x7fe00001']).toMatchObject({ tag: 'x7fe00001', vr: 'OV', length: 0 }); // reads the reserved bytes as the length
    expect(ds.elements['x7fe00010']).toBeUndefined(); // the real PixelData is never found
  });

  it('compares the transfer syntax exactly: a space-padded implicit UID is parsed as explicit (garbage)', () => {
    const padded = part10(concat(baseElements(true), pixelData(8, 8, true)), { transferSyntax: `${IMPLICIT_LE} ` });
    expect(() => dicomParser.parseDicom(padded, { untilTag: 'x7fe00010' })).toThrow();
  });
});
