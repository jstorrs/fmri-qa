/**
 * The intake area: open DICOM (folder, files, .zip archives, drag and drop), scan the headers, show the Patient > Study >
 * Series tree and keep the selection. Adapted from the wiring in dicom-util's src/main.ts (web/VENDORED.md): no
 * "listing" notice, no restore of the previous set, no export or viewer hooks.
 */
import { selectAll, selectNone } from '../core/selection';
import type { Selection } from '../core/selection';
import { buildTree } from '../core/tree';
import type { Instance, PatientNode, SeriesKey, SeriesNode } from '../core/types';
import { expandArchives } from './archive';
import { grabDropped, hasDirectoryPicker, pickDirectoryHandle, pickedFromFiles, readDropped, walkHandle } from './intake';
import type { Intake, WalkOptions } from './intake';
import { nextPhase } from './phase';
import type { Phase } from './phase';
import { scan } from './scan';
import type { RejectedFile, SkippedFile } from './scan';
import { mountGlobalErrors } from './ui/errors';
import { formatSize, plural } from './ui/format';
import { mountLog } from './ui/log';
import type { Log } from './ui/log';
import { mountOutcome } from './ui/outcome';
import type { Outcome } from './ui/outcome';
import { mountProgress } from './ui/progress';
import type { Progress } from './ui/progress';
import { buildSkipped, buildTreeView } from './ui/tree';
import type { TreeView } from './ui/tree';

interface State {
  phase: Phase;
  patients: readonly PatientNode[];
  duplicates: readonly Instance[];
  skipped: readonly SkippedFile[];
  rejected: readonly RejectedFile[];
  instanceCount: number;
  series: ReadonlyMap<SeriesKey, SeriesNode>;
  selection: Selection;
}

const emptyState = (phase: Phase): State => ({
  phase,
  patients: [],
  duplicates: [],
  skipped: [],
  rejected: [],
  instanceCount: 0,
  series: new Map(),
  selection: selectNone(),
});

const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} is missing from the page`);
  return el as T;
};

export interface IntakeArea {
  readonly log: Log;
  readonly progress: Progress;
  /** Show and announce the outcome of the last task (cleared when the next one starts). */
  readonly notify: Outcome['notify'];
  /** The selected series, in tree order. */
  selected(): SeriesNode[];
  /** Called after the phase or the selection changed. */
  onChange(cb: () => void): void;
  phase(): Phase;
  /**
   * Run a long task with the page in `working`: the tree and the open buttons are inert, drops are ignored, and Cancel
   * aborts `signal`. Rejects if the page is not `ready`.
   */
  runExclusive(label: string, task: (signal: AbortSignal) => Promise<void>): Promise<void>;
}

const FOUND_EVERY_MS = 100;

export const mountIntake = (): IntakeArea => {
  const log = mountLog($<HTMLDetailsElement>('log'), $('log-list'));
  const progress = mountProgress($<HTMLProgressElement>('progress'), $('progress-text'), $<HTMLButtonElement>('cancel'), $('status'));
  const outcome = mountOutcome($('outcome'));
  mountGlobalErrors(window, { log, notify: outcome.notify, current: () => $('outcome').textContent ?? '' });

  let state = emptyState('empty');
  let view: TreeView | null = null;
  let generation = 0;
  let abort: AbortController | null = null;
  const listeners = new Set<() => void>();
  const changed = (): void => {
    for (const cb of listeners)
      try {
        cb();
      } catch (e) {
        log(`Handler failed: ${e instanceof Error ? e.message : String(e)}`);
      }
  };

  const renderCounts = (s: State): void => {
    const studies = s.patients.reduce((n, p) => n + p.studies.length, 0);
    const c: Record<string, number> = {
      patients: s.patients.length,
      studies,
      series: s.series.size,
      instances: s.instanceCount,
      skipped: s.skipped.length,
      rejected: s.rejected.length,
      duplicates: s.duplicates.length,
    };
    const el = $('counts');
    for (const [k, v] of Object.entries(c)) el.dataset[`count${k[0]!.toUpperCase()}${k.slice(1)}`] = String(v);
    el.textContent =
      `${plural(c['patients']!, 'patient')}, ${plural(studies, 'study', 'studies')}, ${plural(c['series']!, 'series', 'series')}, ${plural(c['instances']!, 'DICOM file')}` +
      (c['skipped']! + c['rejected']! + c['duplicates']! > 0 ? ` · ${c['skipped']} skipped, ${c['rejected']} rejected, ${c['duplicates']} duplicate` : '');
  };

  const selectedTotals = (s: State) => {
    let series = 0;
    let files = 0;
    let bytes = 0;
    for (const k of s.selection) {
      const n = s.series.get(k);
      if (!n) continue;
      series++;
      files += n.instances.length;
      bytes += n.bytes;
    }
    return { series, files, bytes };
  };

  const renderSummary = (s: State): void => {
    const t = selectedTotals(s);
    const el = $('summary');
    el.dataset['countSeries'] = String(t.series);
    el.dataset['countFiles'] = String(t.files);
    el.textContent = `${plural(t.series, 'series', 'series')}, ${plural(t.files, 'file')}, ${formatSize(t.bytes)} selected`;
  };

  /** Mirror the phase into the DOM. Never touches the tree. */
  const applyPhase = (phase: Phase): void => {
    document.body.dataset['state'] = phase;
    const working = phase === 'working';
    $('tree-host').inert = working;
    for (const b of document.querySelectorAll<HTMLButtonElement>('[data-action^="open-"], #select-all, #select-none')) b.disabled = working;
  };

  const setPhase = (phase: Phase): void => {
    state = { ...state, phase };
    applyPhase(phase);
    changed();
  };

  /** Rebuild the tree DOM from `s`. Selection-only changes use `view.sync` instead. */
  const render = (s: State): void => {
    state = s;
    $('tree-host').replaceChildren();
    $('skipped-host').replaceChildren();
    view = null;
    if (s.phase === 'ready' || s.phase === 'working') {
      view = buildTreeView(s.patients, s.selection, (f) => setSelection(f(state.selection)), log);
      $('tree-host').append(view.el);
      const skipped = buildSkipped(s.skipped, s.rejected, s.duplicates);
      if (skipped) $('skipped-host').append(skipped);
      renderCounts(s);
      renderSummary(s);
    }
    applyPhase(s.phase);
    changed();
  };

  const setSelection = (selection: Selection): void => {
    state = { ...state, selection };
    view?.sync(selection);
    renderSummary(state);
    changed();
  };

  // ---- opening a set ---------------------------------------------------------

  /** Leave `scanning` without a new tree. */
  const abandon = (): void => {
    progress.end();
    render(emptyState(nextPhase(state.phase, { type: 'abandon', hasPrevious: false }) ?? 'empty'));
  };

  const cancel = (): void => {
    abort?.abort();
    generation++;
    abandon();
  };

  const open = async (read: (opts: WalkOptions) => Promise<Intake>): Promise<void> => {
    const next = nextPhase(state.phase, 'open');
    if (next === null) return; // a task is running
    outcome.clear();
    abort?.abort();
    const mine = new AbortController();
    abort = mine;
    const gen = ++generation;
    const current = (): boolean => gen === generation;
    const signal = mine.signal;
    render(emptyState(next));
    progress.start('Reading files…', { onCancel: cancel });
    try {
      let lastShown = 0;
      const onFound = (n: number): void => {
        const now = performance.now();
        if (!current() || now - lastShown < FOUND_EVERY_MS) return;
        lastShown = now;
        progress.update({ done: 0, total: 0, text: `Reading files… ${n.toLocaleString('en-US')} files` });
      };
      const intake = await read({ signal, onFound });
      if (!current()) return;
      if (intake.files.length === 0) {
        log(intake.error !== undefined ? `Could not read: ${intake.error}` : 'No files found.');
        abandon();
        return;
      }
      if (intake.errors > 0) log(`${plural(intake.errors, 'entry', 'entries')} could not be read and were skipped (first: ${intake.error ?? 'unknown'}).`);
      // ZIP archives become their entries (one level, read lazily). Plain files pass through.
      const expanded = await expandArchives(intake.files, { signal, onFound });
      if (!current() || signal.aborted) return;
      for (const a of expanded.archives) log(`${a.relPath}: ${plural(a.entries, 'entry', 'entries')}`);
      progress.start(`0 / ${expanded.inputs.length.toLocaleString('en-US')} files scanned`, { onCancel: cancel });
      const res = await scan(expanded.inputs, {
        signal,
        onProgress: (p) =>
          current() &&
          progress.update({
            done: p.scanned,
            total: p.total,
            text: `${p.scanned.toLocaleString('en-US')} / ${p.total.toLocaleString('en-US')} files scanned · ${p.instances.toLocaleString('en-US')} DICOM instances`,
          }),
      });
      if (!res || !current()) return;
      const { patients, duplicates } = buildTree(res.instances);
      const series = new Map<SeriesKey, SeriesNode>();
      for (const p of patients) for (const st of p.studies) for (const se of st.series) series.set(se.key, se);
      render({
        phase: nextPhase(state.phase, 'scan-done') ?? 'ready',
        patients,
        duplicates,
        skipped: [...expanded.skipped, ...res.skipped],
        rejected: res.rejected,
        instanceCount: [...series.values()].reduce((n, x) => n + x.instances.length, 0),
        series,
        selection: selectNone(),
      });
      progress.end(`Scan finished: ${plural(series.size, 'series', 'series')} found.`);
    } catch (e) {
      if (!current()) return;
      log(`Could not open: ${e instanceof Error ? e.message : String(e)}`);
      abandon();
    }
  };

  // ---- intake wiring ---------------------------------------------------------

  const folderInput = $<HTMLInputElement>('open-folder');
  const filesInput = $<HTMLInputElement>('open-files');
  for (const input of [folderInput, filesInput]) {
    input.addEventListener('change', () => {
      const files = pickedFromFiles(input.files ?? []);
      input.value = ''; // allow re-selecting the same folder
      if (files.length === 0) return;
      if (nextPhase(state.phase, 'open') === null) {
        log('The files arrived while a task was running, so they were not opened. Open them again when the task ends.');
        return;
      }
      void open(() => Promise.resolve({ files, errors: 0 }));
    });
  }
  for (const b of document.querySelectorAll<HTMLButtonElement>('[data-action="open-files"]')) b.addEventListener('click', () => filesInput.click());

  // The directory picker where available (no "Upload N files?" prompt), else the webkitdirectory input. The picker
  // runs before `open`, so cancelling it keeps the current set.
  let pickerFailed = false;
  const openFolder = async (): Promise<void> => {
    // Synchronous click: the input chooser needs the user activation, which an awaited picker would have used up.
    if (!hasDirectoryPicker() || pickerFailed) return folderInput.click();
    let handle;
    try {
      handle = await pickDirectoryHandle();
    } catch (e) {
      pickerFailed = true;
      log(`Folder picker unavailable (${e instanceof Error ? e.message : String(e)}). Click Open folder again to use the file chooser.`);
      return;
    }
    if (handle) void open((o) => walkHandle(handle, o));
  };
  for (const b of document.querySelectorAll<HTMLButtonElement>('[data-action="open-folder"]')) b.addEventListener('click', () => void openFolder());

  let dragDepth = 0;
  const hasFiles = (e: DragEvent): boolean => Array.from(e.dataTransfer?.types ?? []).includes('Files');
  const dropsAllowed = (): boolean => nextPhase(state.phase, 'open') !== null;
  document.addEventListener('dragenter', (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    if (!dropsAllowed()) return;
    dragDepth++;
    document.body.classList.add('dragging');
  });
  document.addEventListener('dragover', (e) => {
    if (hasFiles(e)) e.preventDefault();
  });
  document.addEventListener('dragleave', () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) document.body.classList.remove('dragging');
  });
  document.addEventListener('drop', (e) => {
    e.preventDefault();
    dragDepth = 0;
    document.body.classList.remove('dragging');
    if (!e.dataTransfer || !hasFiles(e) || !dropsAllowed()) return;
    const grabbed = grabDropped(e.dataTransfer); // synchronous: the DataTransfer is dead after the first await
    if (grabbed.entries.length + grabbed.loose.length === 0) {
      log('Nothing to open in that drop.'); // keeps the current set
      return;
    }
    void open((o) => readDropped(grabbed, o));
  });

  $('select-all').addEventListener('click', () => setSelection(selectAll(state.patients)));
  $('select-none').addEventListener('click', () => setSelection(selectNone()));

  const runExclusive: IntakeArea['runExclusive'] = async (label, task) => {
    const next = nextPhase(state.phase, 'work-begin');
    if (next === null) throw new Error(`Cannot start "${label}" while the page is ${state.phase}`);
    const gen = generation;
    outcome.clear();
    const ctl = new AbortController();
    setPhase(next); // no render: the tree DOM stays as it is
    progress.start(label, { onCancel: () => ctl.abort() });
    try {
      await task(ctl.signal);
    } finally {
      progress.end();
      if (gen === generation) {
        const back = nextPhase(state.phase, 'work-end');
        if (back !== null) setPhase(back);
      }
    }
  };

  render(state);
  return {
    log,
    progress,
    notify: outcome.notify,
    selected: () => [...state.series.values()].filter((s) => state.selection.has(s.key)),
    onChange: (cb) => void listeners.add(cb),
    phase: () => state.phase,
    runExclusive,
  };
};
