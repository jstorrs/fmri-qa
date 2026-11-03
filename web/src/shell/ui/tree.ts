import { patientKeys, studyKeys, toggleKeys, triState } from '../../core/selection';
import type { Selection } from '../../core/selection';
import type { Instance, PatientNode, SeriesKey, SeriesNode } from '../../core/types';
import type { RejectedFile, SkippedFile } from '../scan';
import { formatDate, formatName, formatSize, plural } from './format';
import { h } from './h';

export interface TreeView {
  readonly el: HTMLElement;
  /** Update checkbox states in place (keeps open/closed state of the groups). */
  sync(sel: Selection): void;
}

type Change = (f: (sel: Selection) => Selection) => void;

interface Group {
  readonly input: HTMLInputElement;
  readonly keys: readonly SeriesKey[];
}

const checkbox = (label: string): HTMLInputElement =>
  h('input', { attrs: { type: 'checkbox', 'aria-label': label } });

export const buildTreeView = (
  patients: readonly PatientNode[],
  sel: Selection,
  onChange: Change,
  log: (message: string) => void,
): TreeView => {
  const singles = new Map<SeriesKey, HTMLInputElement>();
  const groups: Group[] = [];

  const seriesRow = (s: SeriesNode): HTMLElement => {
    const input = checkbox(`Select series ${s.number ?? ''} ${s.description}`);
    input.addEventListener('change', () => onChange((cur) => toggleKeys(cur, [s.key])));
    singles.set(s.key, input);
    return h(
      'div',
      { class: 'row series', data: { seriesKey: s.key } },
      h('label', { class: 'title' }, input, h('span', { class: 'num' }, s.number === null ? '–' : `#${s.number}`), h('span', { class: 'desc' }, s.description || '(no description)')),
      h('span', { class: 'chip' }, s.modality || '?'),
      h('span', { class: 'meta' }, plural(s.instances.length, 'file')),
      h('span', { class: 'meta' }, formatSize(s.bytes)),
    );
  };

  const group = (keys: readonly SeriesKey[], label: string): HTMLInputElement => {
    const input = checkbox(label);
    input.addEventListener('click', (e) => e.stopPropagation());
    input.addEventListener('change', () => onChange((cur) => toggleKeys(cur, keys)));
    groups.push({ input, keys });
    return input;
  };

  const el = h('div', { class: 'tree', attrs: { id: 'tree' } });
  const frag = document.createDocumentFragment();
  for (const p of patients) {
    const pName = formatName(p.name);
    const studies = p.studies.map((st) => {
      const box = group(studyKeys(st), `Select study ${formatDate(st.date)} ${st.description}`);
      return h(
        'details',
        { class: 'study', attrs: { open: true }, data: { studyUid: st.uid } },
        h(
          'summary',
          { class: 'row' },
          box,
          h('span', { class: 'title' }, h('span', { class: 'date' }, formatDate(st.date)), h('span', { class: 'desc' }, st.description || '(no description)')),
          h('span', { class: 'meta' }, plural(st.series.length, 'series', 'series')),
        ),
        ...st.series.map(seriesRow),
      );
    });
    const box = group(patientKeys(p), `Select patient ${pName} (${p.id})`);
    frag.append(
      h(
        'details',
        { class: 'patient', attrs: { open: true }, data: { patientKey: p.groupKey } },
        h(
          'summary',
          { class: 'row' },
          box,
          h('span', { class: 'title' }, h('span', { class: 'name' }, pName), h('span', { class: 'pid' }, p.id)),
          h('span', { class: 'meta' }, plural(p.studies.length, 'study', 'studies')),
        ),
        ...studies,
      ),
    );
  }
  el.append(frag);

  const sync = (s: Selection): void => {
    for (const [k, input] of singles) input.checked = s.has(k);
    for (const g of groups) {
      const t = triState(s, g.keys);
      g.input.checked = t === 'all';
      g.input.indeterminate = t === 'some';
    }
  };
  sync(sel);
  return { el, sync };
};

// ---- Skipped / rejected / duplicates --------------------------------------

export const LIST_CAP = 300;

interface SkipGroup {
  readonly id: string;
  readonly title: string;
  readonly lines: readonly string[];
}

const withDetail = (s: SkippedFile): string => (s.detail ? `${s.relPath} — ${s.detail}` : s.relPath);

export const skipGroups = (
  skipped: readonly SkippedFile[],
  rejected: readonly RejectedFile[],
  duplicates: readonly Instance[],
): SkipGroup[] => {
  const by = (r: SkippedFile['reason']) => skipped.filter((s) => s.reason === r);
  return [
    { id: 'not-dicom', title: 'Not DICOM', lines: by('not-dicom').map(withDetail) },
    { id: 'dicomdir', title: 'DICOMDIR (index files)', lines: by('dicomdir').map((s) => s.relPath) },
    { id: 'unreadable', title: 'Unreadable', lines: by('unreadable').map(withDetail) },
    { id: 'nested-zip', title: 'ZIP archives inside ZIP archives (not opened)', lines: by('nested-zip').map((s) => s.relPath) },
    { id: 'encrypted', title: 'Encrypted ZIP entries (not supported)', lines: by('encrypted').map((s) => s.relPath) },
    { id: 'unsupported-method', title: 'ZIP entries with unsupported compression', lines: by('unsupported-method').map(withDetail) },
    { id: 'rejected', title: 'Rejected (DICOM without usable Study/Series UID)', lines: rejected.map((r) => `${r.relPath} — ${r.reason}`) },
    { id: 'duplicates', title: 'Duplicates (same SOP Instance UID, first one kept)', lines: duplicates.map((d) => d.relPath) },
  ];
};

export const buildSkipped = (
  skipped: readonly SkippedFile[],
  rejected: readonly RejectedFile[],
  duplicates: readonly Instance[],
): HTMLElement | null => {
  const groups = skipGroups(skipped, rejected, duplicates).filter((g) => g.lines.length > 0);
  if (groups.length === 0) return null;
  const total = groups.reduce((n, g) => n + g.lines.length, 0);
  return h(
    'details',
    { class: 'skipped', attrs: { id: 'skipped' }, data: { count: total } },
    h('summary', {}, `Skipped files (${total.toLocaleString('en-US')})`),
    ...groups.map((g) =>
      h(
        'details',
        { class: 'skip-group', data: { group: g.id, count: g.lines.length } },
        h('summary', {}, `${g.title} (${g.lines.length.toLocaleString('en-US')})`),
        h(
          'ul',
          {},
          ...g.lines.slice(0, LIST_CAP).map((l) => h('li', {}, l)),
          g.lines.length > LIST_CAP ? h('li', { class: 'more' }, `+${(g.lines.length - LIST_CAP).toLocaleString('en-US')} more`) : null,
        ),
      ),
    ),
  );
};
