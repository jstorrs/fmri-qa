/**
 * A run: the selected series through dcm2niix, then Python's names, then one analysis per NIfTI. Pure data and a
 * reducer; `src/shell/drive.ts` does the converting and the calling, and reports each step here as an event.
 *
 * Bytes are part of the state: each result's NIfTI, sidecar and companions stay downloadable, under whatever names
 * they have, whatever happens to Python (and, once analyzed, its report page and `.qa.json`). Outputs that belong to
 * no NIfTI are dropped, as the native import drops them. Python's `.qa.json` text is kept verbatim (`documentText`):
 * a JS round trip turns 2.0 into 2.
 */
import type { OutputFile } from './dcm2niix';

export type Stage = 'decode' | 'analyze' | 'render';

/**
 * `analyze_json`'s result for a series that analyzed. `documentText` is its `record_document_json`; `resultText` its
 * `result_json`, the small verbatim string `document_json` takes back for the run's `fmri-qa.json`.
 */
export interface Report {
  readonly kind: 'report';
  readonly stem: string;
  readonly html: string;
  readonly documentText: string;
  readonly resultText: string;
  readonly warnings: readonly string[];
}
/** `analyze_json`'s result for a series that failed at `stage`; `resultText` as for a report. */
export interface Failure {
  readonly kind: 'failure';
  readonly stem: string;
  readonly stage: Stage;
  readonly reason: string;
  readonly resultText: string;
  readonly warnings: readonly string[];
}
export type Analysis = Report | Failure;

/** Why a result failed: Python's own failure, or anything else (no Python, a crash, a cancel). */
export type Cause = Failure | { readonly kind: 'error'; readonly reason: string };

/** One NIfTI and the files that travel with it: `<stem>.json` as `sidecar`, any other `<stem>.*` as a companion. */
export interface Files {
  readonly nifti: OutputFile;
  readonly sidecar: OutputFile | null;
  readonly companions: readonly OutputFile[];
}

interface Named {
  /** The stem of `files`: dcm2niix's until named, then the QA name. */
  readonly stem: string;
  readonly files: Files;
  /** The names dcm2niix gave `files` (after the run's `-w 2` suffixes), sorted. */
  readonly dcm2niix: readonly string[];
}
export type Result = Named &
  (
    | { readonly status: 'naming' } // waiting for names_json
    | { readonly status: 'waiting-for-python' } // named, waiting for its analyze_json
    | { readonly status: 'analyzing' }
    | { readonly status: 'done'; readonly report: Report }
    | { readonly status: 'failed'; readonly cause: Cause }
  );

export interface SeriesRef {
  readonly uid: string;
  readonly label: string;
}

/** What dcm2niix made of one series. */
export type Conversion =
  | { readonly status: 'ok'; readonly files: readonly OutputFile[]; readonly messages: readonly string[] }
  | { readonly status: 'failed'; readonly reason: string; readonly messages: readonly string[] }
  | { readonly status: 'cancelled'; readonly messages: readonly string[] };

/** One selected series. A converted series with no NIfTI has no results. */
export type Job =
  | { readonly status: 'queued' | 'converting'; readonly series: SeriesRef }
  | { readonly status: 'converted'; readonly series: SeriesRef; readonly messages: readonly string[]; readonly results: readonly Result[] }
  | { readonly status: 'failed'; readonly series: SeriesRef; readonly messages: readonly string[]; readonly reason: string }
  | { readonly status: 'cancelled'; readonly series: SeriesRef; readonly messages: readonly string[] };

export interface Run {
  readonly jobs: readonly Job[];
}

export interface ResultKey {
  readonly job: number;
  readonly result: number;
}

/** Why a run stopped early: Cancel, or something that went wrong. */
export type StopCause = { readonly kind: 'cancelled' } | { readonly kind: 'error'; readonly reason: string };

export type RunEvent =
  | { readonly type: 'convert'; readonly job: number }
  | { readonly type: 'converted'; readonly job: number; readonly conversion: Conversion }
  | { readonly type: 'named'; readonly names: Readonly<Record<string, string>> }
  | { readonly type: 'naming-failed'; readonly reason: string }
  | { readonly type: 'analyze'; readonly at: ResultKey }
  | { readonly type: 'analyzed'; readonly at: ResultKey; readonly analysis: Analysis }
  | { readonly type: 'analyze-failed'; readonly at: ResultKey; readonly reason: string }
  /**
   * Nothing new starts: queued series are cancelled (or, on an error, fail with its reason), and results not yet
   * analyzing fail. What runs now (a conversion, an analysis) finishes and is reported as usual.
   */
  | { readonly type: 'stop'; readonly cause: StopCause };

/** The reason a result fails with on Cancel. */
export const CANCELLED = 'Cancelled before analysis.';

export const startRun = (series: readonly SeriesRef[]): Run => ({ jobs: series.map((s) => ({ status: 'queued', series: s })) });

const NIFTI_SUFFIXES = ['.nii.gz', '.nii'] as const;
const niftiSuffix = (name: string): string | undefined => NIFTI_SUFFIXES.find((s) => name.endsWith(s));
/** `scan.nii.gz` -> `scan`. Only for NIfTI names. */
const niftiStem = (name: string): string => name.slice(0, name.length - (niftiSuffix(name) ?? '').length);
const byName = (a: OutputFile, b: OutputFile): number => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0);

/**
 * Group one series' outputs as fmriqa_io's `filing.plan_names` does: a NIfTI belongs to its own stem; any other file
 * to the longest stem it starts with followed by a dot. Files that match none are dropped, as the native import does.
 */
export const groupOutputs = (files: readonly OutputFile[]): Files[] => {
  const niftis = files.filter((f) => niftiSuffix(f.name) !== undefined).sort(byName);
  const longestFirst = [...new Set(niftis.map((f) => niftiStem(f.name)))].sort((a, b) => b.length - a.length);
  const owned = new Map<string, OutputFile[]>();
  for (const f of [...files].sort(byName)) {
    if (niftiSuffix(f.name) !== undefined) continue;
    const stem = longestFirst.find((s) => f.name.startsWith(`${s}.`));
    if (stem !== undefined) owned.set(stem, [...(owned.get(stem) ?? []), f]);
  }
  return niftis.map((nifti) => {
    const stem = niftiStem(nifti.name);
    const mine = owned.get(stem) ?? [];
    owned.delete(stem); // `x.nii` and `x.nii.gz` share a stem: the first takes the companions
    const sidecar = mine.find((f) => f.name === `${stem}.json`) ?? null;
    return { nifti, sidecar, companions: mine.filter((f) => f !== sidecar) };
  });
};

/** Swap the leading `from` of `f`'s name for `to` (a prefix swap, as `filing._refiled` does). */
const swapStem = (f: OutputFile, from: string, to: string): OutputFile => ({ name: to + f.name.slice(from.length), buf: f.buf });
const swapFiles = (files: Files, from: string, to: string): Files => ({
  nifti: swapStem(files.nifti, from, to),
  sidecar: files.sidecar && swapStem(files.sidecar, from, to),
  companions: files.companions.map((f) => swapStem(f, from, to)),
});
const allFiles = (files: Files): OutputFile[] => [files.nifti, ...(files.sidecar ? [files.sidecar] : []), ...files.companions];

/**
 * The stem dcm2niix's `-w 2` (the default, "add suffix") gives a series whose stem a NIfTI already has: the first free
 * of `<stem>a` .. `<stem>y`, or undefined (dcm2niix then fails the series: "Too many NIFTI images with the name").
 * From `nii_createFilename` in console/nii_dicom_batch.cpp: its loop assigns `<stem>z` last and exits without
 * checking it, so `z` is never used. Native dcm2niix converts a study in one go, so it
 * sees every earlier series' NIfTI; each of the page's workers starts with an empty /out, so the run applies it here.
 */
export const dcm2niixSuffix = (stem: string, taken: ReadonlySet<string>): string | undefined => {
  if (!taken.has(stem)) return stem;
  for (let i = 0; i < 25; i++) {
    const next = stem + String.fromCharCode(97 + i);
    if (!taken.has(next)) return next;
  }
  return undefined;
};

const mapResults = (run: Run, fn: (r: Result, key: ResultKey) => Result): Run => ({
  jobs: run.jobs.map((job, j) => (job.status === 'converted' ? { ...job, results: job.results.map((r, i) => fn(r, { job: j, result: i })) } : job)),
});
const at = (key: ResultKey, fn: (r: Result) => Result) => (r: Result, k: ResultKey) => (k.job === key.job && k.result === key.result ? fn(r) : r);
const failed = (r: Result, cause: Cause): Result => ({ stem: r.stem, files: r.files, dcm2niix: r.dcm2niix, status: 'failed', cause });

/** NIfTI stems the series before `job` already hold, as dcm2niix's `niiExists` would see them. */
const stemsBefore = (run: Run, job: number): Set<string> =>
  new Set(
    run.jobs
      .slice(0, job)
      .flatMap((j) => (j.status === 'converted' ? j.results.flatMap((r) => r.dcm2niix.filter((n) => niftiSuffix(n) !== undefined).map(niftiStem)) : [])),
  );

const convert = (run: Run, index: number, job: Job, conversion: Conversion): Job => {
  switch (conversion.status) {
    case 'ok': {
      const taken = stemsBefore(run, index);
      const results: Result[] = [];
      for (const grouped of groupOutputs(conversion.files)) {
        const stem = niftiStem(grouped.nifti.name);
        const free = dcm2niixSuffix(stem, taken);
        if (free === undefined)
          return { status: 'failed', series: job.series, messages: conversion.messages, reason: `Too many NIFTI images with the name ${stem}` };
        taken.add(free);
        const files = swapFiles(grouped, stem, free);
        results.push({ status: 'naming', stem: free, files, dcm2niix: allFiles(files).map((f) => f.name).sort() });
      }
      return { status: 'converted', series: job.series, messages: conversion.messages, results };
    }
    case 'failed':
      return { status: 'failed', series: job.series, messages: conversion.messages, reason: conversion.reason };
    case 'cancelled':
      return { status: 'cancelled', series: job.series, messages: conversion.messages };
  }
};

const rename = (files: Files, names: Readonly<Record<string, string>>): Files => {
  const one = (f: OutputFile): OutputFile => {
    const to = Object.hasOwn(names, f.name) ? names[f.name] : undefined;
    return to === undefined ? f : { name: to, buf: f.buf };
  };
  return { nifti: one(files.nifti), sidecar: files.sidecar && one(files.sidecar), companions: files.companions.map(one) };
};

/** The run after `event`. An event that does not fit the current state (a late answer after a cancel) changes nothing. */
export const step = (run: Run, event: RunEvent): Run => {
  switch (event.type) {
    case 'convert':
      return { jobs: run.jobs.map((job, j) => (j === event.job && job.status === 'queued' ? { status: 'converting', series: job.series } : job)) };
    case 'converted':
      return { jobs: run.jobs.map((job, j) => (j === event.job && job.status === 'converting' ? convert(run, j, job, event.conversion) : job)) };
    case 'named':
      return mapResults(run, (r) => {
        if (r.status !== 'naming') return r;
        const files = rename(r.files, event.names);
        return { status: 'waiting-for-python', stem: niftiStem(files.nifti.name), files, dcm2niix: r.dcm2niix };
      });
    case 'naming-failed':
      return mapResults(run, (r) => (r.status === 'naming' ? failed(r, { kind: 'error', reason: event.reason }) : r));
    case 'analyze':
      return mapResults(
        run,
        at(event.at, (r) => (r.status === 'waiting-for-python' ? { stem: r.stem, files: r.files, dcm2niix: r.dcm2niix, status: 'analyzing' } : r)),
      );
    case 'analyzed': {
      const a = event.analysis;
      return mapResults(
        run,
        at(event.at, (r) => {
          if (r.status !== 'analyzing') return r;
          return a.kind === 'report' ? { stem: r.stem, files: r.files, dcm2niix: r.dcm2niix, status: 'done', report: a } : failed(r, a);
        }),
      );
    }
    case 'analyze-failed':
      return mapResults(run, at(event.at, (r) => (r.status === 'analyzing' ? failed(r, { kind: 'error', reason: event.reason }) : r)));
    case 'stop': {
      const cause = event.cause;
      const reason = cause.kind === 'cancelled' ? CANCELLED : cause.reason;
      const jobs = run.jobs.map((job): Job => {
        if (job.status !== 'queued') return job;
        return cause.kind === 'cancelled'
          ? { status: 'cancelled', series: job.series, messages: [] }
          : { status: 'failed', series: job.series, messages: [], reason: cause.reason };
      });
      return mapResults({ jobs }, (r) => (r.status === 'naming' || r.status === 'waiting-for-python' ? failed(r, { kind: 'error', reason }) : r));
    }
  }
};

const results = (run: Run): { key: ResultKey; result: Result }[] =>
  run.jobs.flatMap((job, j) => (job.status === 'converted' ? job.results.map((result, i) => ({ key: { job: j, result: i }, result })) : []));

/** The next result to analyze, in run order. */
export const nextToAnalyze = (run: Run): { key: ResultKey; result: Result } | undefined =>
  results(run).find((r) => r.result.status === 'waiting-for-python');

/**
 * Every file of the results still waiting for names, by dcm2niix name; or a name two of them share, which
 * `names_json` cannot take as one map. The `-w 2` suffixes make that unlikely; it is refused rather than overwritten.
 */
export const namingInput = (run: Run): { readonly files: ReadonlyMap<string, OutputFile> } | { readonly duplicate: string } => {
  const files = new Map<string, OutputFile>();
  for (const { result } of results(run)) {
    if (result.status !== 'naming') continue;
    for (const f of allFiles(result.files)) {
      if (files.has(f.name)) return { duplicate: f.name };
      files.set(f.name, f);
    }
  }
  return { files };
};

export const isRunning = (run: Run): boolean =>
  run.jobs.some((j) => j.status === 'queued' || j.status === 'converting') ||
  results(run).some((r) => r.result.status !== 'done' && r.result.status !== 'failed');

const isRecord = (x: unknown): x is Record<string, unknown> => typeof x === 'object' && x !== null && !Array.isArray(x);
const isStrings = (x: unknown): x is string[] => Array.isArray(x) && x.every((s) => typeof s === 'string');
const STAGES: readonly Stage[] = ['decode', 'analyze', 'render'];
const isStage = (x: unknown): x is Stage => STAGES.includes(x as Stage);

/** Parse `analyze_json`'s string. Throws on anything that is not one of its two shapes. */
export const parseAnalysis = (text: string): Analysis => {
  const x: unknown = JSON.parse(text);
  if (!isRecord(x) || typeof x['stem'] !== 'string' || !isStrings(x['warnings']) || typeof x['result_json'] !== 'string')
    throw new Error('analyze_json returned an unexpected result');
  const [stem, warnings, resultText] = [x['stem'], x['warnings'], x['result_json']];
  if (x['kind'] === 'report' && typeof x['html'] === 'string' && typeof x['record_document_json'] === 'string')
    return { kind: 'report', stem, html: x['html'], documentText: x['record_document_json'], resultText, warnings };
  if (x['kind'] === 'failure' && isStage(x['stage']) && typeof x['reason'] === 'string')
    return { kind: 'failure', stem, stage: x['stage'], reason: x['reason'], resultText, warnings };
  throw new Error('analyze_json returned an unexpected result');
};

/** Parse `names_json`'s string: dcm2niix name to QA name. Throws on anything else. */
export const parseNames = (text: string): Record<string, string> => {
  const x: unknown = JSON.parse(text);
  if (!isRecord(x) || !Object.values(x).every((v) => typeof v === 'string')) throw new Error('names_json returned an unexpected result');
  return x as Record<string, string>;
};
