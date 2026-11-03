import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { buildTree } from '../../src/core/tree';
import { expandArchives } from '../../src/shell/archive';
import { scan } from '../../src/shell/scan';
import { buildZip, cat, eocd, randomBytes } from './zip-bytes';
import type { Spec } from './zip-bytes';

const picked = (relPath: string, bytes: Uint8Array<ArrayBuffer>) => ({ file: new File([bytes], relPath.slice(relPath.lastIndexOf('/') + 1)), relPath });
const zip = (relPath: string, specs: Spec[]) => picked(relPath, buildZip(specs).bytes);
const dat = new TextEncoder().encode('some bytes some bytes some bytes');
const fixtureZip = readFileSync(new URL('../fixtures/zips/export.zip', import.meta.url));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe('expandArchives', () => {
  test('plain files pass through unchanged and in order', async () => {
    const a = picked('d/a.dcm', new Uint8Array([1]));
    const b = picked('d/b.txt', new Uint8Array([2, 3]));
    const out = await expandArchives([a, b]);
    expect(out.inputs.map((i) => [i.relPath, i.source.name, i.source.size])).toEqual([
      ['d/a.dcm', 'a.dcm', 1],
      ['d/b.txt', 'b.txt', 2],
    ]);
    expect(out.skipped).toEqual([]);
    expect(out.archives).toEqual([]);
  });

  test('an archive is replaced by its entries, with relPath = archive path + entry path; directories are ignored', async () => {
    const z = zip('in/export.zip', [{ name: 'DICOM/' }, { name: 'DICOM/IM0001', data: dat }, { name: 'DICOM/sub/IM0002', data: dat, method: 0 }]);
    const after = picked('in/z.dcm', new Uint8Array([9]));
    const out = await expandArchives([z, after]);
    expect(out.inputs.map((i) => i.relPath)).toEqual(['in/export.zip/DICOM/IM0001', 'in/export.zip/DICOM/sub/IM0002', 'in/z.dcm']);
    expect(out.inputs[0]!.source).toMatchObject({ name: 'IM0001', size: dat.length });
    expect(out.archives).toEqual([{ relPath: 'in/export.zip', entries: 2 }]);
    expect(out.skipped).toEqual([]);
    expect(new Uint8Array(await out.inputs[0]!.source.bytes())).toEqual(dat);
  });

  test('the extension is matched without regard to case, and a file with another name is not opened', async () => {
    const bytes = buildZip([{ name: 'x', data: dat }]).bytes;
    const out = await expandArchives([picked('A.ZIP', bytes), picked('archive.bin', bytes)]);
    expect(out.inputs.map((i) => i.relPath)).toEqual(['A.ZIP/x', 'archive.bin']);
  });

  test('a .zip file without the ZIP signature is an ordinary file', async () => {
    const out = await expandArchives([picked('notes.zip', new TextEncoder().encode('just text')), picked('empty.zip', new Uint8Array(0))]);
    expect(out.inputs.map((i) => i.relPath)).toEqual(['notes.zip', 'empty.zip']);
    expect(out.skipped).toEqual([]);
  });

  test('nested archives, encrypted entries and unsupported methods are skipped with reasons; the rest is kept', async () => {
    const z = zip('a.zip', [
      { name: 'ok', data: dat },
      { name: 'inner/more.ZIP', data: dat },
      { name: 'secret', data: dat, flags: 1 },
      { name: 'bz', data: dat, method: 12 },
      { name: 'aes', data: dat, method: 99, flags: 1 },
    ]);
    const out = await expandArchives([z]);
    expect(out.inputs.map((i) => i.relPath)).toEqual(['a.zip/ok']);
    expect(out.skipped.map((s) => [s.relPath, s.reason])).toEqual([
      ['a.zip/inner/more.ZIP', 'nested-zip'],
      ['a.zip/secret', 'encrypted'],
      ['a.zip/bz', 'unsupported-method'],
      ['a.zip/aes', 'encrypted'],
    ]);
    expect(out.skipped.every((s) => (s.detail ?? '').length > 0)).toBe(true);
    expect(out.archives).toEqual([{ relPath: 'a.zip', entries: 5 }]);
  });

  test('an empty archive has no inputs and is reported with 0 entries', async () => {
    const out = await expandArchives([picked('e.zip', eocd(0, 0, 0))]);
    expect(out.inputs).toEqual([]);
    expect(out.archives).toEqual([{ relPath: 'e.zip', entries: 0 }]);
  });

  test('a corrupt or truncated archive becomes one unreadable item with detail; other files go on', async () => {
    const good = buildZip([{ name: 'x', data: dat }]).bytes;
    const bad1 = picked('junk.zip', cat([0x50, 0x4b, 3, 4], randomBytes(3000, 1)));
    const bad2 = picked('cut.zip', good.slice(0, good.length - 30));
    const other = picked('f.dcm', new Uint8Array([1]));
    const out = await expandArchives([bad1, bad2, other]);
    expect(out.inputs.map((i) => i.relPath)).toEqual(['f.dcm']);
    expect(out.skipped.map((s) => [s.relPath, s.reason])).toEqual([
      ['junk.zip', 'unreadable'],
      ['cut.zip', 'unreadable'],
    ]);
    expect(out.skipped[0]!.detail).toMatch(/cannot read ZIP archive: .+/);
  });

  test('a failing signature read is unreadable', async () => {
    const f = picked('x.zip', new Uint8Array(10));
    Object.defineProperty(f.file, 'slice', { value: () => ({ arrayBuffer: () => Promise.reject(new Error('NotReadableError')) }) });
    const out = await expandArchives([f]);
    expect(out.skipped).toEqual([{ relPath: 'x.zip', reason: 'unreadable', detail: 'NotReadableError' }]);
  });

  test('onFound reports the running number of inputs; an aborted signal stops early', async () => {
    const seen: number[] = [];
    await expandArchives([zip('a.zip', [{ name: 'x', data: dat }, { name: 'y', data: dat }]), picked('b', new Uint8Array(1))], { onFound: (n) => seen.push(n) });
    expect(seen).toEqual([1, 2, 3]);

    const ctl = new AbortController();
    const out = await expandArchives([zip('a.zip', [{ name: 'x', data: dat }]), picked('b', new Uint8Array(1))], {
      signal: ctl.signal,
      onFound: () => ctl.abort(),
    });
    expect(out.inputs.map((i) => i.relPath)).toEqual(['a.zip/x']);
  });

  test('without DecompressionStream, deflated entries are unreadable (with a reason) and stored ones still work', async () => {
    vi.stubGlobal('DecompressionStream', undefined);
    vi.resetModules();
    const { expandArchives: expand } = await import('../../src/shell/archive');
    const out = await expand([zip('a.zip', [{ name: 'stored', data: dat, method: 0 }, { name: 'deflated', data: dat, method: 8 }])]);
    expect(out.inputs.map((i) => i.relPath)).toEqual(['a.zip/stored']);
    expect(out.skipped).toEqual([{ relPath: 'a.zip/deflated', reason: 'unreadable', detail: expect.stringContaining('DecompressionStream') }]);
  });
});

describe('scan: a ZIP that was not opened because of its name', () => {
  test('is a not-dicom skip with a detail', async () => {
    const bytes = buildZip([{ name: 'x', data: dat }]).bytes;
    const out = await expandArchives([picked('d/archive.bin', bytes)]);
    const res = await scan(out.inputs, { signal: new AbortController().signal, onProgress: () => undefined });
    expect(res!.skipped).toEqual([{ relPath: 'd/archive.bin', reason: 'not-dicom', detail: 'looks like a ZIP archive (only files named .zip are opened)' }]);
  });
});

describe('scan over the fixture archive', () => {
  test('21 DICOM entries (stored and deflated) form 3 series; README and the nested archive are skipped', async () => {
    const out = await expandArchives([{ file: new File([fixtureZip], 'export.zip'), relPath: 'export.zip' }]);
    expect(out.archives).toEqual([{ relPath: 'export.zip', entries: 23 }]);
    expect(out.skipped.map((s) => [s.relPath, s.reason])).toEqual([['export.zip/nested/inner.zip', 'nested-zip']]);
    const res = await scan(out.inputs, { signal: new AbortController().signal, onProgress: () => undefined });
    expect(res).not.toBeNull();
    expect(res!.instances).toHaveLength(21);
    expect(res!.skipped.map((s) => [s.relPath, s.reason])).toEqual([['export.zip/README.txt', 'not-dicom']]);
    expect(res!.rejected).toEqual([]);
    const { patients, duplicates } = buildTree(res!.instances);
    expect(duplicates).toEqual([]);
    expect(patients.map((p) => [p.id, p.studies[0]!.series[0]!.instances.length]).sort()).toEqual([
      ['PAT001', 16],
      ['PAT002', 4],
      ['UNKNOWN', 1],
    ]);
    expect(res!.instances.some((i) => i.relPath === 'export.zip/DICOM/Müller_Jürgen/IM0001')).toBe(true);
  });
});
