/**
 * The run table, rebuilt from the run on every change. A series that gave no NIfTI is one row
 * (`tr.job[data-series][data-status]`); each NIfTI of a converted series is one row
 * (`tr.result[data-series][data-stem][data-status][data-dcm2niix-files]`, plus `data-reason` and, for Python's own
 * failure, `data-stage`; `data-dcm2niix-files` is a JSON array of the names dcm2niix gave its files). Its downloads
 * are `button[data-action]`: `nifti`, `sidecar`, `companion` (one each), and once done `html` and `record`, plus
 * `preview`. These attributes are what the e2e tests read.
 */
import type { OutputFile } from '../../core/dcm2niix';
import type { Job, Report, Result, Run } from '../../core/run';
import { h } from './h';

export interface ResultActions {
  preview(report: Report): void;
  download(name: string, blob: Blob): void;
}

const JOB_STATUS: Record<Job['status'], string> = {
  queued: 'Queued',
  converting: 'Converting…',
  converted: 'Converted',
  failed: 'Conversion failed',
  cancelled: 'Cancelled',
};
const RESULT_STATUS: Record<Result['status'], string> = {
  naming: 'Naming (waits for Python)',
  'waiting-for-python': 'Waiting to analyze',
  analyzing: 'Analyzing…',
  done: 'Done',
  failed: 'Failed',
};

const list = (lines: readonly string[]): HTMLElement | null => (lines.length === 0 ? null : h('ul', {}, ...lines.map((l) => h('li', {}, l))));

const jobRow = (job: Job): HTMLTableRowElement => {
  const reason = job.status === 'failed' ? job.reason : job.status === 'converted' ? 'dcm2niix wrote no NIfTI' : null;
  return h(
    'tr',
    { class: 'job', data: { series: job.series.uid, status: job.status, reason: reason ?? undefined } },
    h('td', { class: 'name' }, job.series.label),
    h('td', { class: 'status' }, JOB_STATUS[job.status]),
    h('td', {}, reason, 'messages' in job ? list(job.messages) : null),
    h('td'),
  );
};

const resultRow = (job: Job, r: Result, actions: ResultActions): HTMLTableRowElement => {
  const button = (key: string, text: string, label: string, onClick: () => void): HTMLButtonElement =>
    h('button', { attrs: { type: 'button', title: label, 'aria-label': label }, data: { action: key }, on: { click: onClick } }, text);
  const save = (key: string, name: string, blob: () => Blob): HTMLButtonElement =>
    button(key, name.slice(r.stem.length) || name, `Download ${name}`, () => actions.download(name, blob()));
  const file = (key: string, f: OutputFile): HTMLButtonElement => save(key, f.name, () => new Blob([f.buf]));

  const cause = r.status === 'failed' ? r.cause : null;
  const reason = cause === null ? null : cause.kind === 'failure' ? `${cause.stage} failed: ${cause.reason}` : cause.reason;
  const warnings = r.status === 'done' ? r.report.warnings : cause?.kind === 'failure' ? cause.warnings : [];
  const report = r.status === 'done' ? r.report : null;
  return h(
    'tr',
    {
      class: 'result',
      data: {
        series: job.series.uid,
        stem: r.stem,
        status: r.status,
        dcm2niixFiles: JSON.stringify(r.dcm2niix),
        reason: cause?.reason,
        stage: cause?.kind === 'failure' ? cause.stage : undefined,
      },
    },
    h('td', { class: 'name' }, r.stem),
    h('td', { class: 'status' }, RESULT_STATUS[r.status]),
    h('td', {}, reason, list(warnings)),
    h(
      'td',
      { class: 'actions' },
      report && button('preview', 'Preview', `Preview the report for ${r.stem}`, () => actions.preview(report)),
      file('nifti', r.files.nifti),
      r.files.sidecar && file('sidecar', r.files.sidecar),
      ...r.files.companions.map((f) => file('companion', f)),
      report && save('html', `${r.stem}.html`, () => new Blob([report.html], { type: 'text/html' })),
      report && save('record', `${r.stem}.qa.json`, () => new Blob([report.documentText], { type: 'application/json' })),
    ),
  );
};

/** A button by its row's series and dcm2niix files, its action and its text: what survives a redraw. */
const buttonKey = (b: HTMLButtonElement): string => {
  const row = b.closest('tr');
  return JSON.stringify([row?.dataset['series'], row?.dataset['dcm2niixFiles'], b.dataset['action'], b.textContent]);
};

export const renderResults = (body: HTMLElement, run: Run, actions: ResultActions): void => {
  // The table is rebuilt on every event, so a focused button the redraw removed is given back, for the keyboard.
  const active = document.activeElement;
  const focused = active instanceof HTMLButtonElement && body.contains(active) ? buttonKey(active) : null;
  body.replaceChildren(
    ...run.jobs.flatMap((job) =>
      job.status === 'converted' && job.results.length > 0 ? job.results.map((r) => resultRow(job, r, actions)) : [jobRow(job)],
    ),
  );
  const lost = document.activeElement === null || document.activeElement === document.body;
  if (focused === null || !lost) return;
  for (const b of body.querySelectorAll('button')) if (buttonKey(b) === focused) return b.focus({ preventScroll: true });
};
