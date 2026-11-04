import { describe, expect, test } from 'vitest';
import type { OutputFile } from '../../src/core/dcm2niix';
import {
  CANCELLED,
  dcm2niixSuffix,
  groupOutputs,
  isRunning,
  namingInput,
  nextToAnalyze,
  parseAnalysis,
  parseNames,
  startRun,
  step,
} from '../../src/core/run';
import type { Analysis, Job, Result, Run, RunEvent } from '../../src/core/run';

const file = (name: string, bytes = 1): OutputFile => ({ name, buf: new ArrayBuffer(bytes) });
const names = (fs: readonly OutputFile[]): string[] => fs.map((f) => f.name);
const run = (...events: RunEvent[]): Run => events.reduce(step, startRun([{ uid: 'A', label: '#2 A' }, { uid: 'B', label: '#11 B' }]));
const ok = (job: number, ...files: string[]): RunEvent => ({ type: 'converted', job, conversion: { status: 'ok', files: files.map((n) => file(n)), messages: [] } });
const converted = (r: Run, job: number): Extract<Job, { status: 'converted' }> => {
  const j = r.jobs[job]!;
  if (j.status !== 'converted') throw new Error(`job ${job} is ${j.status}`);
  return j;
};
const result = (r: Run, job: number, i = 0): Result => converted(r, job).results[i]!;
const fileNames = (r: Result): string[] => [r.files.nifti, ...(r.files.sidecar ? [r.files.sidecar] : []), ...r.files.companions].map((f) => f.name);
const STOP_CANCEL: RunEvent = { type: 'stop', cause: { kind: 'cancelled' } };

const A = '20260909142500_2_A';
const B = '20260909142500_11_B';
/** Both series converted, one NIfTI and sidecar each. */
const bothConverted: RunEvent[] = [
  { type: 'convert', job: 0 },
  ok(0, `${A}.json`, `${A}.nii.gz`),
  { type: 'convert', job: 1 },
  ok(1, `${B}.nii.gz`, `${B}.json`),
];
const NAMES = { [`${A}.nii.gz`]: 'qa_a.nii.gz', [`${A}.json`]: 'qa_a.json', [`${B}.nii.gz`]: 'qa_b.nii.gz', [`${B}.json`]: 'qa_b.json' };
const named: RunEvent[] = [...bothConverted, { type: 'named', names: NAMES }];
const first = { job: 0, result: 0 };
const second = { job: 1, result: 0 };
const report = (stem: string): Analysis => ({ kind: 'report', stem, html: '<html>', documentText: '{"tr": 2.0}\n', resultText: '{}', warnings: ['w'] });
const failure = (stem: string): Analysis => ({
  kind: 'failure',
  stem,
  stage: 'analyze',
  reason: 'invalid frame count 2',
  resultText: '{}',
  warnings: [],
});

describe('groupOutputs', () => {
  test('a NIfTI takes its sidecar and companions; a file of no NIfTI is dropped', () => {
    const results = groupOutputs([file('x.bval'), file('x.json'), file('x.nii.gz'), file('stray.txt'), file('x.bvec')]);
    expect(results).toHaveLength(1);
    expect(results[0]!.nifti.name).toBe('x.nii.gz');
    expect(results[0]!.sidecar?.name).toBe('x.json');
    expect(names(results[0]!.companions)).toEqual(['x.bval', 'x.bvec']);
  });

  test('a file goes to the longest stem it starts with, as plan_names does', () => {
    const results = groupOutputs([file('s.nii.gz'), file('s.repeat.nii.gz'), file('s.repeat.json'), file('s.json')]);
    expect(results.map((r) => [r.nifti.name, r.sidecar?.name])).toEqual([
      ['s.nii.gz', 's.json'],
      ['s.repeat.nii.gz', 's.repeat.json'],
    ]);
  });

  test('no sidecar is null, and an uncompressed .nii counts', () => {
    expect(groupOutputs([file('u.nii')]).map((r) => [r.nifti.name, r.sidecar])).toEqual([['u.nii', null]]);
  });
});

describe("dcm2niix's -w 2 suffix", () => {
  test('a free stem is kept; a taken one gets the first free letter', () => {
    expect(dcm2niixSuffix('s', new Set(['t']))).toBe('s');
    expect(dcm2niixSuffix('s', new Set(['s']))).toBe('sa');
    expect(dcm2niixSuffix('s', new Set(['s', 'sa', 'sb']))).toBe('sc');
  });

  test('after y there is none: dcm2niix never uses z', () => {
    const taken = new Set(['s', ...Array.from({ length: 25 }, (_, i) => `s${String.fromCharCode(97 + i)}`)]);
    expect(taken.has('sy') && !taken.has('sz')).toBe(true);
    expect(dcm2niixSuffix('s', taken)).toBeUndefined();
  });

  test('a later series whose NIfTI clashes with an earlier one is renamed with all its files', () => {
    const r = run({ type: 'convert', job: 0 }, ok(0, 'x.nii.gz', 'x.json'), { type: 'convert', job: 1 }, ok(1, 'x.nii.gz', 'x.json', 'x.bval'));
    expect(fileNames(result(r, 0))).toEqual(['x.nii.gz', 'x.json']);
    expect(result(r, 1).stem).toBe('xa');
    expect(fileNames(result(r, 1))).toEqual(['xa.nii.gz', 'xa.json', 'xa.bval']);
    expect(result(r, 1).dcm2niix).toEqual(['xa.bval', 'xa.json', 'xa.nii.gz']);
    expect('files' in namingInput(r)).toBe(true);
  });

  test('a 26th clash fails the series, as dcm2niix does', () => {
    const many = ['x', ...Array.from({ length: 25 }, (_, i) => `x${String.fromCharCode(97 + i)}`)].map((s) => `${s}.nii.gz`);
    const r = run({ type: 'convert', job: 0 }, ok(0, ...many), { type: 'convert', job: 1 }, ok(1, 'x.nii.gz'));
    expect(r.jobs[1]).toMatchObject({ status: 'failed', reason: 'Too many NIFTI images with the name x' });
  });
});

describe('conversion', () => {
  test('a run starts with every series queued and is running', () => {
    const r = run();
    expect(r.jobs.map((j) => j.status)).toEqual(['queued', 'queued']);
    expect(isRunning(r)).toBe(true);
  });

  test('a converted series has one result per NIfTI, waiting for names under dcm2niix names', () => {
    const r = run(...bothConverted);
    expect(r.jobs.map((j) => j.status)).toEqual(['converted', 'converted']);
    expect(result(r, 0)).toMatchObject({ status: 'naming', stem: A, dcm2niix: [`${A}.json`, `${A}.nii.gz`] });
    expect(result(r, 0).files.sidecar?.name).toBe(`${A}.json`);
  });

  test('a series with no NIfTI is converted with no results', () => {
    const r = run({ type: 'convert', job: 0 }, ok(0, 'stray.txt'));
    expect(converted(r, 0).results).toEqual([]);
  });

  test('a failed or cancelled conversion keeps its reason and messages and has no results', () => {
    const r = run(
      { type: 'convert', job: 0 },
      { type: 'converted', job: 0, conversion: { status: 'failed', reason: 'dcm2niix exited with code 2', messages: ['Error: x'] } },
      { type: 'convert', job: 1 },
      { type: 'converted', job: 1, conversion: { status: 'cancelled', messages: [] } },
    );
    expect(r.jobs[0]).toMatchObject({ status: 'failed', reason: 'dcm2niix exited with code 2', messages: ['Error: x'] });
    expect(r.jobs[1]).toMatchObject({ status: 'cancelled' });
    expect(isRunning(r)).toBe(false);
  });

  test('converted is ignored unless the series is converting', () => {
    expect(run(ok(0, 'x.nii.gz')).jobs[0]!.status).toBe('queued');
  });
});

describe('naming', () => {
  test('namingInput holds every file of every result waiting for names', () => {
    const r = run({ type: 'convert', job: 0 }, ok(0, `${A}.nii.gz`, `${A}.json`, 'stray.txt'));
    const input = namingInput(r);
    expect('files' in input && [...input.files.keys()]).toEqual([`${A}.nii.gz`, `${A}.json`]);
  });

  test('namingInput still refuses a name two results share', () => {
    // Not reachable through dcm2niix's own names, which the suffix keeps apart; a companion of a longer stem can be.
    const r = run({ type: 'convert', job: 0 }, ok(0, 's.nii.gz', 's.r.json'), { type: 'convert', job: 1 }, ok(1, 's.r.nii.gz', 's.r.json'));
    expect(namingInput(r)).toEqual({ duplicate: 's.r.json' });
  });

  test('named renames every file and the stem, keeps the dcm2niix names and queues the result for Python', () => {
    const r = run(...named);
    expect(result(r, 1)).toMatchObject({ status: 'waiting-for-python', stem: 'qa_b', dcm2niix: [`${B}.json`, `${B}.nii.gz`] });
    expect(fileNames(result(r, 1))).toEqual(['qa_b.nii.gz', 'qa_b.json']);
    expect(namingInput(r)).toEqual({ files: new Map() });
  });

  test('a name missing from the map keeps the dcm2niix name', () => {
    const r = run({ type: 'convert', job: 0 }, ok(0, 'x.nii.gz', 'x.json'), { type: 'named', names: { 'x.nii.gz': 'q.nii.gz' } });
    expect([result(r, 0).stem, result(r, 0).files.sidecar?.name]).toEqual(['q', 'x.json']);
  });

  test('naming-failed fails every result waiting for names, which keeps its dcm2niix files', () => {
    const r = run(...bothConverted, { type: 'naming-failed', reason: 'Python did not start: boom' });
    expect(result(r, 0)).toMatchObject({ status: 'failed', stem: A, cause: { kind: 'error', reason: 'Python did not start: boom' } });
    expect(result(r, 0).files.nifti.name).toBe(`${A}.nii.gz`);
    expect(isRunning(r)).toBe(false);
  });

  test('naming-failed leaves results already named alone', () => {
    const r = run(...named, { type: 'naming-failed', reason: 'late' });
    expect([result(r, 0).status, result(r, 1).status]).toEqual(['waiting-for-python', 'waiting-for-python']);
  });
});

describe('analysis', () => {
  test('results are analyzed in run order', () => {
    const r = run(...named);
    expect(nextToAnalyze(r)?.key).toEqual(first);
    const r2 = step(r, { type: 'analyze', at: first });
    expect(result(r2, 0).status).toBe('analyzing');
    expect(nextToAnalyze(r2)?.key).toEqual(second);
  });

  test('a report is done; a Python failure is failed with its stage; the files stay', () => {
    const r = run(
      ...named,
      { type: 'analyze', at: first },
      { type: 'analyzed', at: first, analysis: report('qa_a') },
      { type: 'analyze', at: second },
      { type: 'analyzed', at: second, analysis: failure('qa_b') },
    );
    expect(result(r, 0)).toMatchObject({ status: 'done', report: { documentText: '{"tr": 2.0}\n' } });
    expect(result(r, 1)).toMatchObject({ status: 'failed', cause: { kind: 'failure', stage: 'analyze', reason: 'invalid frame count 2' } });
    expect(result(r, 1).files.nifti.name).toBe('qa_b.nii.gz');
    expect(isRunning(r)).toBe(false);
    expect(nextToAnalyze(r)).toBeUndefined();
  });

  test('a rejected call fails that result only', () => {
    const r = run(...named, { type: 'analyze', at: first }, { type: 'analyze-failed', at: first, reason: 'Python failed: crashed' });
    expect(result(r, 0)).toMatchObject({ status: 'failed', cause: { kind: 'error', reason: 'Python failed: crashed' } });
    expect(result(r, 1).status).toBe('waiting-for-python');
  });

  test('analyze is ignored unless the result is waiting for Python', () => {
    expect(result(run(...bothConverted, { type: 'analyze', at: first }), 0).status).toBe('naming');
    const done = run(...named, { type: 'analyze', at: first }, { type: 'analyzed', at: first, analysis: report('qa_a') }, { type: 'analyze', at: first });
    expect(result(done, 0).status).toBe('done');
  });

  test('analyzed and analyze-failed are ignored unless the result is analyzing', () => {
    expect(result(run(...named, { type: 'analyzed', at: first, analysis: report('qa_a') }), 0).status).toBe('waiting-for-python');
    expect(result(run(...named, { type: 'analyze-failed', at: first, reason: 'x' }), 0).status).toBe('waiting-for-python');
    const done = run(...named, { type: 'analyze', at: first }, { type: 'analyzed', at: first, analysis: report('qa_a') }, { type: 'analyze-failed', at: first, reason: 'x' });
    expect(result(done, 0).status).toBe('done');
  });
});

describe('stop', () => {
  test('Cancel: queued series are cancelled and results not yet analyzing fail; what runs keeps running', () => {
    const r = run({ type: 'convert', job: 0 }, ok(0, 'x.nii.gz', 'y.nii.gz'), { type: 'named', names: {} }, { type: 'analyze', at: first });
    const stopped = step(r, STOP_CANCEL);
    expect(stopped.jobs[1]!.status).toBe('cancelled');
    expect(result(stopped, 0, 0).status).toBe('analyzing');
    expect(result(stopped, 0, 1)).toMatchObject({ status: 'failed', cause: { kind: 'error', reason: CANCELLED } });
    expect(isRunning(stopped)).toBe(true);
    // The analysis in flight still lands as done.
    expect(result(step(stopped, { type: 'analyzed', at: first, analysis: report('x') }), 0, 0).status).toBe('done');
  });

  test('an error: queued series fail with its reason, and so do results not yet analyzing', () => {
    const r = run({ type: 'convert', job: 0 }, ok(0, 'x.nii.gz'), { type: 'stop', cause: { kind: 'error', reason: 'The run stopped: boom' } });
    expect(r.jobs[1]).toMatchObject({ status: 'failed', reason: 'The run stopped: boom' });
    expect(result(r, 0)).toMatchObject({ status: 'failed', cause: { kind: 'error', reason: 'The run stopped: boom' } });
  });

  test('stop leaves done, failed and analyzing results alone', () => {
    const r = run(
      { type: 'convert', job: 0 },
      ok(0, 'a.nii.gz', 'b.nii.gz', 'c.nii.gz'),
      { type: 'named', names: {} },
      { type: 'analyze', at: { job: 0, result: 0 } },
      { type: 'analyzed', at: { job: 0, result: 0 }, analysis: report('a') },
      { type: 'analyze', at: { job: 0, result: 1 } },
      { type: 'analyzed', at: { job: 0, result: 1 }, analysis: failure('b') },
      { type: 'analyze', at: { job: 0, result: 2 } },
    );
    const stopped = step(r, STOP_CANCEL);
    expect(converted(stopped, 0).results).toEqual(converted(r, 0).results);
  });

  test('a series converting when stopped stays converting, and a late name changes nothing', () => {
    const r = run({ type: 'convert', job: 0 }, STOP_CANCEL);
    expect(r.jobs.map((j) => j.status)).toEqual(['converting', 'cancelled']);
    const late = run(...bothConverted, STOP_CANCEL, { type: 'named', names: NAMES });
    expect(result(late, 0)).toMatchObject({ status: 'failed', stem: A });
  });
});

describe('parse', () => {
  test('a report keeps the document text verbatim', () => {
    const text =
      '{"kind": "report", "stem": "s", "html": "<p>", "record": {"tr": 2.0}, "warnings": ["w"], "record_document_json": "{\\n  \\"tr\\": 2.0\\n}\\n", "result_json": "{\\"tr\\": 2.0}"}';
    expect(parseAnalysis(text)).toEqual({
      kind: 'report',
      stem: 's',
      html: '<p>',
      documentText: '{\n  "tr": 2.0\n}\n',
      resultText: '{"tr": 2.0}',
      warnings: ['w'],
    });
  });

  test('a failure keeps stage and reason', () => {
    const text = '{"kind": "failure", "stem": "s", "stage": "analyze", "reason": "short", "warnings": [], "result_json": "{}"}';
    expect(parseAnalysis(text)).toEqual({ kind: 'failure', stem: 's', stage: 'analyze', reason: 'short', resultText: '{}', warnings: [] });
  });

  test.each([
    'not json',
    '[]',
    '{"kind": "report", "stem": "s", "html": "", "warnings": [], "result_json": "{}"}',
    '{"kind": "failure", "stem": "s", "stage": "decode", "reason": "x", "warnings": []}',
    '{"kind": "failure", "stem": "s", "stage": "save", "reason": "x", "warnings": []}',
    '{"kind": "failure", "stem": "s", "stage": "decode", "reason": "x", "warnings": [1]}',
  ])('anything else is refused: %s', (text) => {
    expect(() => parseAnalysis(text)).toThrow();
  });

  test('names_json: an object of strings, nothing else', () => {
    expect(parseNames('{"a.nii.gz": "b.nii.gz"}')).toEqual({ 'a.nii.gz': 'b.nii.gz' });
    expect(() => parseNames('{"a": 1}')).toThrow();
    expect(() => parseNames('["a"]')).toThrow();
  });
});
