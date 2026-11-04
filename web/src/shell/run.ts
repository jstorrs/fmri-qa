/**
 * "Run QA on selected": wires `drive` (src/shell/drive.ts) to the page. The state is `src/core/run.ts`'s; every event
 * redraws the table. The page is `working` for the whole run, waiting for Python included. A new run replaces the
 * old one and its bytes.
 *
 * Once the run has settled, a row's Zip and "Download all (.zip)" write the layouts of `src/core/bundle.ts` through
 * `saveZip`, also with the page `working`: the progress bar counts the bytes and Cancel stops the write.
 */
import { documentEntry, documentInputs, runBundle, runResults, seriesBundle } from '../core/bundle';
import type { ZipEntry } from '../core/bundle';
import { CONTRACT_FLAGS } from '../core/convert-args';
import { isRunning, startRun, step } from '../core/run';
import type { Report, Result, Run, RunEvent } from '../core/run';
import type { SeriesNode } from '../core/types';
import { label, runOne } from './conversions';
import { dcm2niixWasm } from './dcm2niix-wasm';
import { saveBlob } from './download';
import { drive } from './drive';
import { envelope, savedText } from './envelope';
import type { Envelope, PythonState } from './envelope';
import type { IntakeArea } from './intake-ui';
import type { Python } from './python';
import { formatSize } from './ui/format';
import type { OutcomeKind } from './ui/outcome';
import { renderResults } from './ui/results';
import { saveZip } from './zip-sink';
import type { ZipFiles } from './zip-sink';

const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} is missing from the page`);
  return el as T;
};

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));
const errName = (e: unknown): string => (e instanceof DOMException || e instanceof Error ? e.name : '');
const sizeOf = (entries: readonly ZipEntry[]): number => entries.reduce((n, e) => n + e.input.byteLength, 0);

export const mountRun = (area: IntakeArea, python: Python, flags: readonly string[] = CONTRACT_FLAGS): void => {
  const button = $<HTMLButtonElement>('run');
  const downloadAll = $<HTMLButtonElement>('download-all');
  const section = $('results');
  const body = $('results-body');
  const preview = $<HTMLIFrameElement>('preview');
  let run: Run = startRun([]);

  const showPreview = (report: Report): void => {
    preview.srcdoc = report.html; // the iframe is sandboxed with no allow-* tokens (index.html): no script runs in it
    preview.title = `Report for ${report.stem}`;
    preview.dataset['stem'] = report.stem;
    preview.hidden = false;
  };
  const clearPreview = (): void => {
    preview.hidden = true;
    preview.removeAttribute('srcdoc');
    delete preview.dataset['stem'];
  };
  let pythonState: PythonState = { kind: 'starting' };
  python.ready.then(
    () => (pythonState = { kind: 'ready' }),
    (e: unknown) => (pythonState = { kind: 'failed', reason: message(e) }),
  );

  const outcome = (text: string, kind: OutcomeKind = 'ok'): void => {
    area.log(text);
    area.notify(text, kind);
  };

  /** Write one ZIP with the page `working`. Call it in the click's task: the save dialog needs its user activation. */
  const writeZip = (name: string, bytes: number, files: () => ZipFiles, saved: () => string): void => {
    void area
      .runExclusive(`Writing ${name}…`, async (signal) => {
        let written = 0;
        const onBytes = (n: number): void => {
          written += n;
          area.progress.update({ done: Math.min(written, bytes), total: bytes, text: `Writing ${name}: ${formatSize(written)} of ${formatSize(bytes)}` });
        };
        try {
          // The picker is saveZip's first await, so the click's user activation is still alive.
          const result = await saveZip({ name, files, predictedBytes: bytes, signal, onBytes, note: area.log });
          if (result === 'cancelled') return outcome('ZIP cancelled.');
          if (result === 'expired') return outcome('Click the button again to choose where to save.');
          outcome(saved());
        } catch (e) {
          if (signal.aborted || errName(e) === 'AbortError') outcome('ZIP cancelled.');
          else outcome(`ZIP failed: ${message(e)}`, 'error');
        }
      })
      .catch((e: unknown) => outcome(`ZIP failed: ${message(e)}`, 'error'));
  };

  const zipSeries = (r: Result): void => {
    const bundle = seriesBundle(r, new Date());
    writeZip(bundle.name, sizeOf(bundle.entries), () => bundle.entries, () => `Saved ${bundle.name}.`);
  };

  const zipAll = (): void => {
    const at = new Date();
    const settled = run;
    // The folders are built once, here; the document goes in front of them once Python has written it.
    const folders = runBundle(settled, null, at);
    let document: Envelope = { missing: 'not asked' };
    // Asked of Python only once the user has chosen where to save; until then nothing is written.
    const files = async function* (): AsyncGenerator<ZipEntry> {
      document = await envelope(pythonState, (inputs) => python.call('document_json', [inputs]), documentInputs(settled));
      if ('text' in document) yield documentEntry(document.text, at);
      yield* folders.entries;
    };
    writeZip(folders.name, sizeOf(folders.entries), files, () => savedText(folders.name, document));
  };
  downloadAll.addEventListener('click', () => {
    if (downloadAll.getAttribute('aria-disabled') !== 'true') zipAll();
  });

  const actions = { preview: showPreview, download: saveBlob, zip: zipSeries };
  /** The page is free (no run, no ZIP being written) and the run has settled. */
  const canZip = (): boolean => area.phase() === 'ready' && !isRunning(run);
  const show = (): void => {
    section.hidden = run.jobs.length === 0;
    // aria-disabled, not disabled, as for a row's Zip: the button keeps its focus while the ZIP is written.
    downloadAll.setAttribute('aria-disabled', String(!canZip() || runResults(run).length === 0));
    renderResults(body, run, actions, canZip());
  };
  const dispatch = (event: RunEvent): void => {
    run = step(run, event);
    show();
  };

  const refresh = (): void => {
    // A new open replaces the results: the old run's bytes go with the set they came from.
    if (area.phase() === 'scanning' && run.jobs.length > 0) {
      run = startRun([]);
      clearPreview();
    }
    button.disabled = area.phase() !== 'ready' || area.selected().length === 0;
    show();
  };
  area.onChange(refresh);
  refresh();

  button.addEventListener('click', () => {
    const series = area.selected();
    if (series.length === 0) return;
    clearPreview();
    run = startRun(series.map((s) => ({ uid: s.uid, label: label(s) })));
    show();
    void area
      .runExclusive('Running…', (signal) =>
        drive<SeriesNode>({
          series,
          label,
          wasm: dcm2niixWasm,
          runOne: (s, wasm, sig) => runOne(s, flags, wasm, sig),
          python,
          dispatch,
          run: () => run,
          progress: area.progress.update,
          log: area.log,
          signal,
        }),
      )
      .catch((e: unknown) => area.log(`The run stopped: ${e instanceof Error ? e.message : String(e)}`));
  });
};
