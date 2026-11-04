/**
 * "Run QA on selected": wires `drive` (src/shell/drive.ts) to the page. The state is `src/core/run.ts`'s; every event
 * redraws the table. The page is `working` for the whole run, waiting for Python included. A new run replaces the
 * old one and its bytes.
 */
import { CONTRACT_FLAGS } from '../core/convert-args';
import { startRun, step } from '../core/run';
import type { Report, Run, RunEvent } from '../core/run';
import type { SeriesNode } from '../core/types';
import { label, runOne } from './conversions';
import { dcm2niixWasm } from './dcm2niix-wasm';
import { saveBlob } from './download';
import { drive } from './drive';
import type { IntakeArea } from './intake-ui';
import type { Python } from './python';
import { renderResults } from './ui/results';

const $ = <T extends HTMLElement>(id: string): T => {
  const el = document.getElementById(id);
  if (!el) throw new Error(`#${id} is missing from the page`);
  return el as T;
};

export const mountRun = (area: IntakeArea, python: Python, flags: readonly string[] = CONTRACT_FLAGS): void => {
  const button = $<HTMLButtonElement>('run');
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
  const actions = { preview: showPreview, download: saveBlob };
  const show = (): void => {
    section.hidden = run.jobs.length === 0;
    renderResults(body, run, actions);
  };
  const dispatch = (event: RunEvent): void => {
    run = step(run, event);
    show();
  };

  const refresh = (): void => {
    button.disabled = area.phase() !== 'ready' || area.selected().length === 0;
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
