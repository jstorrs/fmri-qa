import { seriesKey } from './types';
import type { Instance, PatientNode, SeriesNode, StudyNode, TreeResult } from './types';

/** PatientID used when a file has an empty one: all such files form one patient. */
export const UNKNOWN_PATIENT = 'UNKNOWN';

type Cmp<T> = (a: T, b: T) => number;

const cmpStr = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);

/** Ascending; null (missing) sorts last. */
const cmpNullable =
  <T>(cmp: (a: T, b: T) => number) =>
  (a: T | null, b: T | null): number =>
    a === null ? (b === null ? 0 : 1) : b === null ? -1 : cmp(a, b);

/** Non-finite numbers (NaN, +-Infinity) count as missing, keeping the order total. */
const cmpNum = (a: number | null, b: number | null): number =>
  cmpNullable<number>((x, y) => x - y)(
    a !== null && Number.isFinite(a) ? a : null,
    b !== null && Number.isFinite(b) ? b : null,
  );
/** '' counts as missing. */
const cmpOptStr = (a: string | null, b: string | null): number =>
  cmpNullable(cmpStr)(a === '' ? null : a, b === '' ? null : b);

const chain =
  <T>(...cmps: Cmp<T>[]): Cmp<T> =>
  (a, b) => {
    for (const c of cmps) {
      const r = c(a, b);
      if (r !== 0) return r;
    }
    return 0;
  };

const cmpInstance: Cmp<Instance> = chain(
  (a, b) => cmpNum(a.instanceNumber, b.instanceNumber),
  (a, b) => cmpNum(a.echoNumber, b.echoNumber),
  (a, b) => cmpStr(a.relPath, b.relPath),
  // relPath is only a basename for flat uploads, so it is not unique.
  (a, b) => cmpOptStr(a.sopInstanceUid, b.sopInstanceUid),
);

const groupBy = <T>(items: readonly T[], key: (t: T) => string): Map<string, T[]> => {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const k = key(item);
    const g = groups.get(k);
    if (g) g.push(item);
    else groups.set(k, [item]);
  }
  return groups;
};

/** Series with the sort-only fields that SeriesNode does not carry. */
interface Built<N> {
  readonly node: N;
  readonly first: Instance;
}

const buildSeries = (groupKey: string, group: readonly Instance[]): Built<SeriesNode> => {
  const instances = [...group].sort(cmpInstance);
  const first = instances[0]!;
  return {
    first,
    node: {
      key: seriesKey(groupKey, first.study.uid, first.series.uid),
      uid: first.series.uid,
      number: first.series.number,
      description: first.series.description,
      modality: first.series.modality,
      instances,
      bytes: instances.reduce((sum, i) => sum + i.source.size, 0),
      window: instances.find((i) => i.window !== null)?.window ?? null,
    },
  };
};

const buildStudy = (groupKey: string, group: readonly Instance[]): Built<StudyNode> => {
  const series = [...groupBy(group, (i) => i.series.uid).values()]
    .map((g) => buildSeries(groupKey, g))
    .sort(
      chain<Built<SeriesNode>>(
        (a, b) => cmpNum(a.node.number, b.node.number),
        (a, b) => cmpStr(a.node.uid, b.node.uid),
      ),
    );
  const first = series[0]!.first;
  return {
    first,
    node: {
      uid: first.study.uid,
      date: first.study.date,
      time: first.study.time,
      description: first.study.description,
      accessionNumber: first.study.accessionNumber,
      series: series.map((s) => s.node),
    },
  };
};

const buildPatient = (group: readonly Instance[]): PatientNode => {
  const groupKey = patientGroupKey(group[0]!);
  const studies = [...groupBy(group, (i) => i.study.uid).values()]
    .map((g) => buildStudy(groupKey, g))
    .sort(
      chain<Built<StudyNode>>(
        (a, b) => cmpOptStr(a.node.date, b.node.date),
        (a, b) => cmpOptStr(a.first.study.time, b.first.study.time),
        (a, b) => cmpStr(a.node.uid, b.node.uid),
      ),
    );
  const first = studies[0]!.first;
  return {
    groupKey,
    id: patientId(first),
    name: first.patient.name,
    studies: studies.map((s) => s.node),
  };
};

const patientId = (i: Instance): string => i.patient.id.trim() || UNKNOWN_PATIENT;

/** Trimmed PatientID; for a blank one, the trimmed PatientName. Injective via JSON. */
const patientGroupKey = (i: Instance): string => {
  const id = i.patient.id.trim();
  return JSON.stringify(id === '' ? ['', i.patient.name.trim()] : [id, '']);
};

/**
 * Group instances into Patient -> Study -> Series.
 *
 * - Patients are keyed by the trimmed PatientID. A blank ID is keyed by the
 *   trimmed PatientName instead (so distinct names stay distinct patients) and
 *   is displayed with id 'UNKNOWN'.
 * - Studies by StudyInstanceUID within a patient, series by SeriesInstanceUID
 *   within a study.
 * - Within a series, a repeated non-null SOPInstanceUID is a duplicate: the
 *   first in input order is kept, the rest go to `duplicates` (input order).
 * - Node metadata (names, dates, descriptions) comes from the first instance
 *   in sort order, so the result does not depend on input order except for
 *   which duplicate wins.
 * - Sorts: instances by InstanceNumber, EchoNumber, relPath; series by number,
 *   UID; studies by date, time, UID; patients by name, group key. Missing
 *   (null, '' or non-finite) sorts last.
 */
export const buildTree = (instances: readonly Instance[]): TreeResult => {
  const duplicates: Instance[] = [];
  const seen = new Set<string>();
  const kept = instances.filter((i) => {
    if (i.sopInstanceUid === null) return true;
    const k = JSON.stringify([patientGroupKey(i), i.study.uid, i.series.uid, i.sopInstanceUid]);
    if (seen.has(k)) {
      duplicates.push(i);
      return false;
    }
    seen.add(k);
    return true;
  });

  // Patient grouping must precede study/series grouping so the same study UID
  // under two PatientIDs yields two separate nodes.
  const patients = [...groupBy(kept, patientGroupKey).values()]
    .map(buildPatient)
    .sort(
      chain<PatientNode>(
        (a, b) => cmpOptStr(a.name, b.name),
        (a, b) => cmpStr(a.groupKey, b.groupKey),
      ),
    );
  return { patients, duplicates };
};
