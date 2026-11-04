/**
 * What goes in the two ZIPs, and under which names: pure layouts over a run's results, for `src/shell/run.ts` to stream
 * through `saveZip`.
 *
 * A result's folder is the launcher's series directory without `.qa.nc`: `<stem>/` with the NIfTI, its sidecar and
 * companions under their current names and, once done, `<stem>.html` and `<stem>.qa.json`. The run's ZIP holds every
 * result's folder and, when Python could write it, a top-level `fmri-qa.json`.
 *
 * Every entry is stamped with the one `at` the caller passes (the moment of the click), so a layout depends on its
 * input only. Text is UTF-8, as a single-file download of the same string is.
 */
import type { OutputFile } from './dcm2niix';
import type { Result, Run } from './run';

export interface ZipEntry {
  readonly name: string;
  readonly input: ArrayBuffer | Uint8Array<ArrayBuffer>;
  readonly lastModified: Date;
}
export interface Bundle {
  readonly name: string;
  readonly entries: readonly ZipEntry[];
}

/** The run's `fmri-qa --json` envelope, at the top of the run's ZIP. */
export const DOCUMENT_NAME = 'fmri-qa.json';

const utf8 = (s: string): Uint8Array<ArrayBuffer> => new TextEncoder().encode(s);

/** `r`'s files under `folder/`, in the order its row offers them. */
const folderEntries = (r: Result, folder: string, at: Date): ZipEntry[] => {
  const file = (f: OutputFile): ZipEntry => ({ name: `${folder}/${f.name}`, input: f.buf, lastModified: at });
  const text = (name: string, s: string): ZipEntry => ({ name: `${folder}/${name}`, input: utf8(s), lastModified: at });
  return [
    file(r.files.nifti),
    ...(r.files.sidecar ? [file(r.files.sidecar)] : []),
    ...r.files.companions.map(file),
    ...(r.status === 'done' ? [text(`${r.stem}.html`, r.report.html), text(`${r.stem}.qa.json`, r.report.documentText)] : []),
  ];
};

/** One result as `<stem>.zip`, its folder `<stem>/`. */
export const seriesBundle = (r: Result, at: Date): Bundle => ({ name: `${r.stem}.zip`, entries: folderEntries(r, r.stem, at) });

const two = (n: number): string => String(n).padStart(2, '0');
/** `fmri-qa-YYYYMMDD-HHMM.zip`, in `at`'s local time. */
export const runZipName = (at: Date): string =>
  `fmri-qa-${at.getFullYear()}${two(at.getMonth() + 1)}${two(at.getDate())}-${two(at.getHours())}${two(at.getMinutes())}.zip`;

/**
 * One folder name per stem, in order. The first result with a stem keeps it; a later one with the same stem (after a
 * naming fallback) gets `<stem>-2`, `-3`, ...: the lowest that no stem and no earlier folder already is. No folder is
 * `fmri-qa.json`, so the document never shares a name with one.
 */
export const folderNames = (stems: readonly string[]): string[] => {
  const taken = new Set([DOCUMENT_NAME, ...stems]);
  const used = new Set([DOCUMENT_NAME]);
  return stems.map((stem) => {
    let folder = stem;
    if (used.has(stem)) {
      let n = 2;
      while (taken.has(`${stem}-${n}`)) n++;
      folder = `${stem}-${n}`;
      taken.add(folder);
    }
    used.add(folder);
    return folder;
  });
};

/** Every result of `run`, in run order. A series that gave no NIfTI has none. */
export const runResults = (run: Run): Result[] => run.jobs.flatMap((j) => (j.status === 'converted' ? j.results : []));

/** `document_json`'s text, verbatim, as the run's `fmri-qa.json`. */
export const documentEntry = (document: string, at: Date): ZipEntry => ({ name: DOCUMENT_NAME, input: utf8(document), lastModified: at });

/**
 * The whole run: `document` as `fmri-qa.json` when there is one, then every folder. `runBundle(run, null, at)` is the
 * folders alone, and `documentEntry` the one entry that `document` adds in front of them.
 */
export const runBundle = (run: Run, document: string | null, at: Date): Bundle => {
  const results = runResults(run);
  const folders = folderNames(results.map((r) => r.stem));
  return {
    name: runZipName(at),
    entries: [...(document === null ? [] : [documentEntry(document, at)]), ...results.flatMap((r, i) => folderEntries(r, folders[i]!, at))],
  };
};

/**
 * What `document_json` takes for `run`, one string per result. Python's own `result_json` is passed on verbatim (a JS
 * round trip turns 2.0 into 2). A result that failed where Python never saw it (no Python, a crash, a cancel, naming)
 * becomes `{"kind": "error", "stem", "reason"}` with the page's reason: strings only, so building it here is safe. A
 * result not yet settled is an error too; the page offers the run's ZIP only once the run has settled. A series that
 * gave no NIfTI has no stem and is left out.
 */
export const documentInputs = (run: Run): string[] =>
  runResults(run).map((r) => {
    if (r.status === 'done') return r.report.resultText;
    if (r.status === 'failed' && r.cause.kind === 'failure') return r.cause.resultText;
    const reason = r.status === 'failed' ? r.cause.reason : 'Not analyzed.';
    return JSON.stringify({ kind: 'error', stem: r.stem, reason });
  });
