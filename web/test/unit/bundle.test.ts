import { describe, expect, test } from 'vitest';
import { DOCUMENT_NAME, documentEntry, documentInputs, folderNames, runBundle, runZipName, seriesBundle } from '../../src/core/bundle';
import type { Bundle } from '../../src/core/bundle';
import type { OutputFile } from '../../src/core/dcm2niix';
import type { Files, Job, Report, Result, Run } from '../../src/core/run';

const enc = (s: string): ArrayBuffer => new TextEncoder().encode(s).buffer as ArrayBuffer;
const dec = (b: ArrayBuffer | Uint8Array): string => new TextDecoder().decode(b);
const file = (name: string): OutputFile => ({ name, buf: enc(`bytes of ${name}`) });
const files = (stem: string, extra: readonly string[] = []): Files => ({
  nifti: file(`${stem}.nii.gz`),
  sidecar: file(`${stem}.json`),
  companions: extra.map((e) => file(`${stem}${e}`)),
});
const report = (stem: string): Report => ({
  kind: 'report',
  stem,
  html: '<title>é</title>',
  documentText: '{\n  "tr": 2.0\n}\n',
  resultText: `{"kind": "report", "stem": "${stem}", "record": {"tr": 2.0}}`,
  warnings: [],
});
const done = (stem: string, f = files(stem)): Result => ({ stem, files: f, dcm2niix: [], status: 'done', report: report(stem) });
const pythonFailed = (stem: string): Result => ({
  stem,
  files: files(stem),
  dcm2niix: [],
  status: 'failed',
  cause: {
    kind: 'failure',
    stem,
    stage: 'analyze',
    reason: 'invalid frame count 2',
    resultText: `{"kind": "failure", "stem": "${stem}", "stage": "analyze", "reason": "invalid frame count 2"}`,
    warnings: [],
  },
});
const pageFailed = (stem: string, reason: string): Result => ({ stem, files: files(stem), dcm2niix: [], status: 'failed', cause: { kind: 'error', reason } });
const runOf = (...jobs: Job[]): Run => ({ jobs });
const converted = (...results: Result[]): Job => ({ status: 'converted', series: { uid: 'u', label: 'l' }, messages: [], results });
const names = (b: Bundle): string[] => b.entries.map((e) => e.name);
const AT = new Date(2026, 10, 3, 9, 5, 59);

describe('seriesBundle', () => {
  test('a done result: the launcher series folder without .qa.nc', () => {
    const b = seriesBundle(done('s', files('s', ['.bval', '.bvec'])), AT);
    expect(b.name).toBe('s.zip');
    expect(names(b)).toEqual(['s/s.nii.gz', 's/s.json', 's/s.bval', 's/s.bvec', 's/s.html', 's/s.qa.json']);
    expect(dec(b.entries[0]!.input)).toBe('bytes of s.nii.gz');
    expect(dec(b.entries[4]!.input)).toBe('<title>é</title>');
    expect(dec(b.entries[5]!.input)).toBe('{\n  "tr": 2.0\n}\n');
  });

  test('a failed result keeps its files under its current names, and has no report', () => {
    expect(names(seriesBundle(pythonFailed('qa'), AT))).toEqual(['qa/qa.nii.gz', 'qa/qa.json']);
    const unnamed = pageFailed('dcm2niix_name', 'Python did not start');
    expect(names(seriesBundle(unnamed, AT))).toEqual(['dcm2niix_name/dcm2niix_name.nii.gz', 'dcm2niix_name/dcm2niix_name.json']);
  });

  test('no sidecar, no entry; every entry carries the one time given', () => {
    const b = seriesBundle(done('s', { nifti: file('s.nii.gz'), sidecar: null, companions: [] }), AT);
    expect(names(b)).toEqual(['s/s.nii.gz', 's/s.html', 's/s.qa.json']);
    expect(b.entries.every((e) => e.lastModified === AT)).toBe(true);
  });
});

describe('runZipName', () => {
  test('local time, to the minute, zero-padded', () => {
    expect(runZipName(AT)).toBe('fmri-qa-20261103-0905.zip');
    expect(runZipName(new Date(2027, 0, 1, 23, 0))).toBe('fmri-qa-20270101-2300.zip');
  });
});

describe('folderNames', () => {
  test('distinct stems are kept', () => {
    expect(folderNames(['a', 'b'])).toEqual(['a', 'b']);
  });

  test('a repeated stem takes the lowest free -N, past stems that already hold it', () => {
    expect(folderNames(['a', 'a', 'a'])).toEqual(['a', 'a-2', 'a-3']);
    expect(folderNames(['a', 'a', 'a-2'])).toEqual(['a', 'a-3', 'a-2']);
    expect(folderNames(['a-2', 'a', 'a'])).toEqual(['a-2', 'a', 'a-3']);
  });

  test('no folder is named like the document', () => {
    expect(folderNames([DOCUMENT_NAME])).toEqual([`${DOCUMENT_NAME}-2`]);
  });
});

describe('runBundle', () => {
  const run = runOf(
    { status: 'failed', series: { uid: 'x', label: 'x' }, messages: [], reason: 'no NIfTI' },
    converted(done('a'), pythonFailed('b')),
    converted(pageFailed('c', 'Cancelled before analysis.')),
  );

  test('the document on top, then every folder in run order', () => {
    const b = runBundle(run, '{"scans": [{"tr": 2.0}]}\n', AT);
    expect(b.name).toBe('fmri-qa-20261103-0905.zip');
    expect(names(b)).toEqual([DOCUMENT_NAME, 'a/a.nii.gz', 'a/a.json', 'a/a.html', 'a/a.qa.json', 'b/b.nii.gz', 'b/b.json', 'c/c.nii.gz', 'c/c.json']);
    expect(dec(b.entries[0]!.input)).toBe('{"scans": [{"tr": 2.0}]}\n');
  });

  test('without a document, every folder and no fmri-qa.json', () => {
    expect(names(runBundle(run, null, AT))).toEqual(['a/a.nii.gz', 'a/a.json', 'a/a.html', 'a/a.qa.json', 'b/b.nii.gz', 'b/b.json', 'c/c.nii.gz', 'c/c.json']);
  });

  test('documentEntry is what a document adds in front of the folders', () => {
    const text = '{"tr": 2.0}\n';
    expect(runBundle(run, text, AT).entries).toEqual([documentEntry(text, AT), ...runBundle(run, null, AT).entries]);
  });

  test('two results with one stem: the second folder is suffixed, its files keep their names, every entry is unique', () => {
    const b = runBundle(runOf(converted(done('s')), converted(pythonFailed('s'))), null, AT);
    expect(names(b)).toEqual(['s/s.nii.gz', 's/s.json', 's/s.html', 's/s.qa.json', 's-2/s.nii.gz', 's-2/s.json']);
    expect(new Set(names(b)).size).toBe(b.entries.length);
  });
});

describe('documentInputs', () => {
  test("Python's strings verbatim; the page's failures as errors with its reason; a series with no NIfTI left out", () => {
    const run = runOf(
      { status: 'cancelled', series: { uid: 'x', label: 'x' }, messages: [] },
      converted(done('a'), pythonFailed('b'), pageFailed('c', 'Python did not start: "boom"')),
    );
    const inputs = documentInputs(run);
    expect(inputs[0]).toBe('{"kind": "report", "stem": "a", "record": {"tr": 2.0}}');
    expect(inputs[1]).toBe('{"kind": "failure", "stem": "b", "stage": "analyze", "reason": "invalid frame count 2"}');
    expect(JSON.parse(inputs[2]!)).toEqual({ kind: 'error', stem: 'c', reason: 'Python did not start: "boom"' });
    expect(inputs).toHaveLength(3);
  });

  test('a result not yet settled is an error', () => {
    const waiting: Result = { stem: 'w', files: files('w'), dcm2niix: [], status: 'waiting-for-python' };
    expect(JSON.parse(documentInputs(runOf(converted(waiting)))[0]!)).toEqual({ kind: 'error', stem: 'w', reason: 'Not analyzed.' });
  });
});
