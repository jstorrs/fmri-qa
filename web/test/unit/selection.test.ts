import { describe, expect, test } from 'vitest';
import {
  patientKeys,
  selectAll,
  selectNone,
  togglePatient,
  toggleSeries,
  toggleStudy,
  triState,
} from '../../src/core/selection';
import { buildTree } from '../../src/core/tree';
import { mk } from './helpers';

const { patients } = buildTree([
  mk({ study: 'S1', series: 'E1', num: 1 }),
  mk({ study: 'S1', series: 'E2', num: 2 }),
  mk({ study: 'S2', series: 'E1', num: 1, date: '20260202' }),
  mk({ pid: 'P2', pname: 'Zed', study: 'S3', series: 'E1' }),
]);
const p1 = patients[0]!;
const [s1, s2] = p1.studies as [(typeof p1.studies)[0], (typeof p1.studies)[0]];
const a = s1.series[0]!;
const b = s1.series[1]!;

describe('selection', () => {
  test('patients sharing study+series UIDs have independent selection', () => {
    const t = buildTree([mk({ pid: 'A', sop: 'x' }), mk({ pid: 'B', sop: 'x' })]);
    const [pa, pb] = t.patients as [(typeof t.patients)[0], (typeof t.patients)[0]];
    const sel = toggleSeries(selectNone(), pa.studies[0]!.series[0]!);
    expect(triState(sel, patientKeys(pa))).toBe('all');
    expect(triState(sel, patientKeys(pb))).toBe('none');
  });

  test('selectAll / selectNone', () => {
    expect(selectAll(patients).size).toBe(4);
    expect(selectNone().size).toBe(0);
  });

  test('toggleSeries flips and does not mutate', () => {
    const none = selectNone();
    const one = toggleSeries(none, a);
    expect(none.size).toBe(0);
    expect(one.has(a.key)).toBe(true);
    expect(toggleSeries(one, a).size).toBe(0);
  });

  test('toggleStudy: some -> all, all -> none', () => {
    const some = toggleSeries(selectNone(), a);
    const all = toggleStudy(some, s1);
    expect(all.has(a.key) && all.has(b.key)).toBe(true);
    expect(toggleStudy(all, s1).size).toBe(0);
  });

  test('toggleStudy leaves other studies alone', () => {
    const sel = toggleStudy(toggleStudy(selectNone(), s2), s1);
    expect(sel.size).toBe(3);
    const after = toggleStudy(sel, s1);
    expect(after.size).toBe(1);
    expect(after.has(s2.series[0]!.key)).toBe(true);
  });

  test('togglePatient', () => {
    const all = togglePatient(selectNone(), p1);
    expect(all.size).toBe(3);
    expect(togglePatient(all, p1).size).toBe(0);
    expect(togglePatient(toggleSeries(selectNone(), b), p1).size).toBe(3);
  });

  test('triState', () => {
    const keys = patientKeys(p1);
    expect(triState(selectNone(), keys)).toBe('none');
    expect(triState(toggleSeries(selectNone(), a), keys)).toBe('some');
    expect(triState(selectAll(patients), keys)).toBe('all');
    expect(triState(selectAll(patients), [])).toBe('none');
  });
});
