import type { PatientNode, SeriesKey, SeriesNode, StudyNode } from './types';

export type Selection = ReadonlySet<SeriesKey>;
export type TriState = 'all' | 'some' | 'none';

export const studyKeys = (s: StudyNode): SeriesKey[] => s.series.map((x) => x.key);
export const patientKeys = (p: PatientNode): SeriesKey[] => p.studies.flatMap(studyKeys);

export const selectNone = (): Selection => new Set();

export const selectAll = (patients: readonly PatientNode[]): Selection =>
  new Set(patients.flatMap(patientKeys));

export const triState = (sel: Selection, keys: readonly SeriesKey[]): TriState => {
  const n = keys.filter((k) => sel.has(k)).length;
  return n === 0 ? 'none' : n === keys.length ? 'all' : 'some';
};

/** All selected -> deselect them all; otherwise select them all. Empty `keys` is a no-op. */
export const toggleKeys = (sel: Selection, keys: readonly SeriesKey[]): Selection => {
  const next = new Set(sel);
  if (triState(sel, keys) === 'all') for (const k of keys) next.delete(k);
  else for (const k of keys) next.add(k);
  return next;
};

export const toggleSeries = (sel: Selection, s: SeriesNode): Selection => toggleKeys(sel, [s.key]);
export const toggleStudy = (sel: Selection, s: StudyNode): Selection => toggleKeys(sel, studyKeys(s));
export const togglePatient = (sel: Selection, p: PatientNode): Selection =>
  toggleKeys(sel, patientKeys(p));
