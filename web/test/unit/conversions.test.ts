import { describe, expect, test, vi } from 'vitest';
import type { SeriesNode } from '../../src/core/types';
import { runOne } from '../../src/shell/conversions';
import type { RunResult } from '../../src/shell/dcm2niix-run';

// The real worker is an inline blob worker bundled by Vite; runOne is given a fake `convert`.
vi.mock('../../src/shell/dcm2niix.worker.ts?worker&inline', () => ({ default: class {} }));

const series = { uid: '1.2.3', number: 2, description: 'QA_EPI', instances: [] } as unknown as SeriesNode;
const wasm = new ArrayBuffer(4);
const signal = new AbortController().signal;
const ok = (outputs: string[]): RunResult => ({ exitCode: 0, outputs: outputs.map((name) => ({ name, buf: new ArrayBuffer(3) })), log: [] });

describe('runOne', () => {
  test('keeps warnings and Skipped lines on success, and drops the rest', async () => {
    const r = await runOne(series, ['-z', 'y'], wasm, signal, async (_s, _a, o) => {
      o.log('Chris Rorden\'s dcm2niiX version');
      o.log('Warning: Patient Position not specified');
      o.log('Skipped d/x.dcm: not a deflated file');
      return ok(['a.json', 'a.nii.gz']);
    });
    expect(r.messages).toEqual(['Warning: Patient Position not specified', 'Skipped d/x.dcm: not a deflated file']);
    expect(r.status === 'ok' && r.files.map((f) => f.name)).toEqual(['a.json', 'a.nii.gz']);
  });

  test('keeps what was logged before a rejection, wasm crash text included, and maps the error', async () => {
    const r = await runOne(series, [], wasm, signal, async (_s, _a, o) => {
      o.log('Skipped d/x.dcm: bad');
      o.log('RuntimeError: memory access out of bounds');
      throw new Error('RuntimeError: memory access out of bounds');
    });
    expect(r).toMatchObject({ status: 'failed', reason: 'dcm2niix crashed, probably out of memory (the series may be too large)' });
    expect(r.messages).toEqual(['Skipped d/x.dcm: bad', 'RuntimeError: memory access out of bounds']);
  });

  test('a non-zero exit code fails, keeping the messages', async () => {
    const r = await runOne(series, [], wasm, signal, async (_s, _a, o) => {
      o.log('Error: no DICOM images');
      return { ...ok([]), exitCode: 2 };
    });
    expect(r).toMatchObject({ status: 'failed', reason: 'dcm2niix exited with code 2', messages: ['Error: no DICOM images'] });
  });

  test('no output files fails', async () => {
    expect(await runOne(series, [], wasm, signal, async () => ok([]))).toMatchObject({ status: 'failed', reason: 'dcm2niix wrote no files' });
  });

  test('an aborted signal is cancelled without converting', async () => {
    const ctl = new AbortController();
    ctl.abort();
    const convert = vi.fn();
    expect(await runOne(series, [], wasm, ctl.signal, convert)).toMatchObject({ status: 'cancelled' });
    expect(convert).not.toHaveBeenCalled();
  });
});
