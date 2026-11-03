import { describe, expect, test } from 'vitest';
import { buildTree } from '../../src/core/tree';
import { mk } from './helpers';

describe('buildTree', () => {
  test('empty', () => {
    expect(buildTree([])).toEqual({ patients: [], duplicates: [] });
  });

  test('groups patient / study / series', () => {
    const { patients } = buildTree([
      mk({ name: 'a', series: 'E1' }),
      mk({ name: 'b', series: 'E2', num: 2 }),
      mk({ name: 'c', study: 'S2', series: 'E1' }),
      mk({ name: 'd', pid: 'P2', pname: 'Zed' }),
    ]);
    expect(patients.map((p) => p.id)).toEqual(['P1', 'P2']);
    const p1 = patients[0]!;
    expect(p1.studies.map((s) => s.uid)).toEqual(['S1', 'S2']);
    expect(p1.studies[0]!.series.map((s) => s.uid)).toEqual(['E1', 'E2']);
    expect(p1.studies[0]!.series[0]!.instances.map((i) => i.source.name)).toEqual(['a']);
  });

  test('blank PatientID groups by trimmed PatientName, displayed as UNKNOWN', () => {
    const { patients } = buildTree([
      mk({ name: 'a', pid: '', pname: 'SUBJ01', study: 'S1' }),
      mk({ name: 'b', pid: '  ', pname: ' SUBJ01 ', study: 'S2' }),
      mk({ name: 'c', pid: '', pname: 'SUBJ02', study: 'S3' }),
      mk({ name: 'd', pid: '', pname: '', study: 'S4' }),
    ]);
    expect(patients.map((p) => p.id)).toEqual(['UNKNOWN', 'UNKNOWN', 'UNKNOWN']);
    const withNames = patients.filter((p) => p.name.trim() !== '');
    expect(withNames.map((p) => p.studies.length).sort()).toEqual([1, 2]);
    expect(new Set(patients.map((p) => p.groupKey)).size).toBe(3);
  });

  test('PatientID is trimmed for grouping', () => {
    const { patients } = buildTree([mk({ pid: 'P1', sop: 'a' }), mk({ pid: 'P1 ', sop: 'b' })]);
    expect(patients).toHaveLength(1);
    expect(patients[0]!.id).toBe('P1');
  });

  test('a real patient with ID "UNKNOWN" does not merge with blank-ID patients', () => {
    const { patients } = buildTree([mk({ pid: 'UNKNOWN', sop: 'a' }), mk({ pid: '', sop: 'b' })]);
    expect(patients).toHaveLength(2);
  });

  test('PatientID containing | cannot collide keys', () => {
    const { patients } = buildTree([
      mk({ pid: 'a|b', study: 'c', sop: 'a' }),
      mk({ pid: 'a', study: 'b|c', sop: 'b' }),
    ]);
    const keys = patients.flatMap((p) => p.studies.flatMap((s) => s.series.map((x) => x.key)));
    expect(new Set(keys).size).toBe(2);
  });

  test('same study+series UIDs under different patients stay separate with distinct keys', () => {
    const { patients, duplicates } = buildTree([mk({ pid: 'A', sop: 'x' }), mk({ pid: 'B', sop: 'x' })]);
    expect(patients).toHaveLength(2);
    expect(duplicates).toEqual([]);
    const [ka, kb] = patients.map((p) => p.studies[0]!.series[0]!.key);
    expect(ka).not.toBe(kb);
  });

  test('instance sort: InstanceNumber, echo, relPath; missing last', () => {
    const { patients } = buildTree([
      mk({ name: 'none-b', rel: 'b', inst: null }),
      mk({ name: 'i2', rel: 'z', inst: 2 }),
      mk({ name: 'none-a', rel: 'a', inst: null }),
      mk({ name: 'i1e2', rel: 'y', inst: 1, echo: 2 }),
      mk({ name: 'i1e1', rel: 'x', inst: 1, echo: 1 }),
      mk({ name: 'i1noecho', rel: 'w', inst: 1, echo: null }),
    ]);
    expect(patients[0]!.studies[0]!.series[0]!.instances.map((i) => i.source.name)).toEqual([
      'i1e1',
      'i1e2',
      'i1noecho',
      'i2',
      'none-a',
      'none-b',
    ]);
  });

  test('series sort: number (missing last), then UID', () => {
    const { patients } = buildTree([
      mk({ series: 'E9', num: null }),
      mk({ series: 'E3', num: 5 }),
      mk({ series: 'E2', num: 5 }),
      mk({ series: 'E1', num: 7 }),
    ]);
    expect(patients[0]!.studies[0]!.series.map((s) => s.uid)).toEqual(['E2', 'E3', 'E1', 'E9']);
  });

  test('study sort: date, time, UID; missing last', () => {
    const { patients } = buildTree([
      mk({ study: 'Sd', date: null, time: null }),
      mk({ study: 'Sc', date: '20260102', time: '090000' }),
      mk({ study: 'Sb', date: '20260101', time: '120000' }),
      mk({ study: 'Sa', date: '20260101', time: '110000' }),
      mk({ study: 'S0', date: '20260101', time: null }),
    ]);
    expect(patients[0]!.studies.map((s) => s.uid)).toEqual(['Sa', 'Sb', 'S0', 'Sc', 'Sd']);
  });

  test('study node carries time and accession number from the first instance', () => {
    const { patients } = buildTree([
      mk({ name: 'a', series: 'E2', num: 2, time: '090000', acc: 'late' }),
      mk({ name: 'b', series: 'E1', num: 1, time: '081500', acc: 'ACC1' }),
      mk({ name: 'c', study: 'S2', date: null, time: null }),
    ]);
    const [s1, s2] = patients[0]!.studies;
    expect(s1).toMatchObject({ uid: 'S1', date: '20260101', time: '081500', accessionNumber: 'ACC1' });
    expect(s2).toMatchObject({ uid: 'S2', date: null, time: null, accessionNumber: '' });
  });

  test('patient sort: name, then id', () => {
    const { patients } = buildTree([
      mk({ pid: '2', pname: 'B' }),
      mk({ pid: '9', pname: 'A' }),
      mk({ pid: '1', pname: 'B' }),
    ]);
    expect(patients.map((p) => p.id)).toEqual(['9', '1', '2']);
  });

  test('duplicate SOPInstanceUID in a series: first in input order kept', () => {
    const first = mk({ name: 'first', sop: 'dup', rel: 'z' });
    const second = mk({ name: 'second', sop: 'dup', rel: 'a' });
    const other = mk({ name: 'other', sop: 'dup', series: 'E2', num: 2 });
    const { patients, duplicates } = buildTree([first, second, other]);
    expect(duplicates).toEqual([second]);
    const series = patients[0]!.studies[0]!.series;
    expect(series[0]!.instances).toEqual([first]);
    expect(series[1]!.instances).toEqual([other]);
  });

  test('null SOPInstanceUID is never a duplicate', () => {
    const { patients, duplicates } = buildTree([mk({ sop: null, name: 'a' }), mk({ sop: null, name: 'b' })]);
    expect(duplicates).toEqual([]);
    expect(patients[0]!.studies[0]!.series[0]!.instances).toHaveLength(2);
  });

  test('bytes is the sum of file sizes (duplicates excluded)', () => {
    const { patients } = buildTree([
      mk({ name: 'a', size: 10 }),
      mk({ name: 'b', size: 32 }),
      mk({ name: 'c', size: 1000, sop: 'a' }),
    ]);
    expect(patients[0]!.studies[0]!.series[0]!.bytes).toBe(42);
  });

  test('window comes from the first sorted instance that has one', () => {
    const w1 = { center: 1, width: 2 };
    const w2 = { center: 3, width: 4 };
    const { patients } = buildTree([
      mk({ name: 'c', inst: 3, window: w2 }),
      mk({ name: 'b', inst: 2, window: w1 }),
      mk({ name: 'a', inst: 1, window: null }),
    ]);
    expect(patients[0]!.studies[0]!.series[0]!.window).toBe(w1);
    expect(buildTree([mk()]).patients[0]!.studies[0]!.series[0]!.window).toBeNull();
  });

  test('metadata is independent of input order', () => {
    const a = mk({ name: 'a', inst: 1, desc: 'first' });
    const b = mk({ name: 'b', inst: 2, desc: 'second' });
    const t1 = buildTree([a, b]).patients[0]!.studies[0]!.series[0]!.description;
    const t2 = buildTree([b, a]).patients[0]!.studies[0]!.series[0]!.description;
    expect(t1).toBe('first');
    expect(t2).toBe('first');
  });

  test('does not mutate its input', () => {
    const input = [mk({ name: 'b', inst: 2 }), mk({ name: 'a', inst: 1 })];
    const copy = [...input];
    buildTree(input);
    expect(input).toEqual(copy);
  });

  test('NaN / Infinity / empty string count as missing and sort last', () => {
    const { patients } = buildTree([
      mk({ name: 'nan', inst: NaN, rel: 'a' }),
      mk({ name: 'inf', inst: Infinity, rel: 'b' }),
      mk({ name: 'one', inst: 1, rel: 'c' }),
      mk({ name: 'null', inst: null, rel: 'd' }),
    ]);
    expect(patients[0]!.studies[0]!.series[0]!.instances.map((i) => i.source.name)).toEqual([
      'one',
      'nan',
      'inf',
      'null',
    ]);
    const t = buildTree([
      mk({ study: 'Sa', date: '', sop: 'a' }),
      mk({ study: 'Sb', date: '20260101', sop: 'b' }),
      mk({ pid: 'Q', pname: '', sop: 'c' }),
    ]);
    expect(t.patients.map((p) => p.name)).toEqual(['Doe^Jane', '']);
    expect(t.patients[0]!.studies.map((s) => s.uid)).toEqual(['Sb', 'Sa']);
  });

  test('equal relPaths are ordered by SOP UID', () => {
    const { patients } = buildTree([
      mk({ name: 'x', rel: 'same', sop: 'sop-b' }),
      mk({ name: 'y', rel: 'same', sop: 'sop-a' }),
      mk({ name: 'z', rel: 'same', sop: null }),
    ]);
    expect(patients[0]!.studies[0]!.series[0]!.instances.map((i) => i.source.name)).toEqual(['y', 'x', 'z']);
  });

  test('result is identical for every permutation of the input', () => {
    const base = [
      mk({ name: 'a', inst: NaN, rel: 'r', sop: 's1' }),
      mk({ name: 'b', inst: null, rel: 'r', sop: 's2' }),
      mk({ name: 'c', inst: 2, echo: NaN, rel: 'r', sop: 's3' }),
      mk({ name: 'd', inst: 2, echo: 1, rel: 'r', sop: 's4' }),
      mk({ name: 'e', series: 'E2', num: NaN, sop: 's5' }),
      mk({ name: 'f', series: 'E3', num: null, sop: 's6' }),
    ];
    const perms = (xs: typeof base): (typeof base)[] =>
      xs.length <= 1 ? [xs] : xs.flatMap((x, i) => perms([...xs.slice(0, i), ...xs.slice(i + 1)]).map((p) => [x, ...p]));
    const sig = (xs: typeof base) =>
      buildTree(xs).patients.flatMap((p) =>
        p.studies.flatMap((s) => s.series.map((se) => [se.uid, se.instances.map((i) => i.source.name).join('')])),
      );
    const expected = sig(base);
    for (const p of perms(base)) expect(sig(p)).toEqual(expected);
  });
});
