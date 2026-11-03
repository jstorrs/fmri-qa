import { describe, expect, test } from 'vitest';
import { CRASH_MESSAGE, friendlyError, inputNames, safeEntryName } from '../../src/core/dcm2niix';
import { isFromWorker, isToWorker } from '../../src/shell/dcm2niix-protocol';

const buf = (...bytes: number[]): ArrayBuffer => new Uint8Array(bytes).buffer;

describe('inputNames', () => {
  test('pads to 4 digits, wider when needed', () => {
    expect(inputNames(0)).toEqual([]);
    expect(inputNames(3)).toEqual(['0000.dcm', '0001.dcm', '0002.dcm']);
    expect(inputNames(9_999).at(-1)).toBe('9998.dcm');
    // width follows the count, like IMnnnn in the ZIP layout
    expect(inputNames(10_000)[0]).toBe('00000.dcm');
    const wide = inputNames(100_001);
    expect(wide[0]).toBe('000000.dcm');
    expect(wide.at(-1)).toBe('100000.dcm');
    expect(new Set(wide).size).toBe(wide.length);
  });
});

describe('safeEntryName', () => {
  test.each([
    ['3_T1.nii.gz', '3_T1.nii.gz'],
    ['../../etc/passwd', '_._etc_passwd'],
    ['a..b', 'a.b'],
    ['a/b\\c', 'a_b_c'],
    ['..', 'output'],
    ['.hidden', 'hidden'],
    ['', 'output'],
    ['a\u0000b', 'a_b'],
    [' ..', 'output'],
    [' .x', 'x'],
    ['. .x', 'x'],
    ['a/ ../b', 'a_ ._b'],
  ])('%j -> %j', (input, out) => expect(safeEntryName(input)).toBe(out));
});

describe('friendlyError', () => {
  test.each(['RuntimeError: memory access out of bounds', 'Aborted(OOM)', 'Aborted(Cannot enlarge memory arrays)', 'RuntimeError: unreachable'])(
    'maps wasm crash %j',
    (raw) => expect(friendlyError(raw)).toBe(CRASH_MESSAGE),
  );
  test('leaves other messages alone', () => expect(friendlyError('Failed to fetch')).toBe('Failed to fetch'));
});

describe('protocol guards', () => {
  test('isToWorker', () => {
    expect(isToWorker({ type: 'run', args: ['-z', 'y'], inputs: [{ name: '0000.dcm', buf: buf(1) }], wasm: buf(4) })).toBe(true);
    expect(isToWorker({ type: 'run', args: [], inputs: [], wasm: buf(4) })).toBe(true);
    expect(isToWorker({ type: 'run', args: [], inputs: [] })).toBe(false); // no wasm
    expect(isToWorker({ type: 'run', args: [], inputs: [], wasm: 'nope' })).toBe(false);
    expect(isToWorker({ type: 'run', args: [1], inputs: [], wasm: buf(4) })).toBe(false);
    expect(isToWorker({ type: 'run', args: [], inputs: [{ name: 'a', buf: 'nope' }], wasm: buf(4) })).toBe(false);
    expect(isToWorker({ type: 'stop' })).toBe(false);
    expect(isToWorker(null)).toBe(false);
  });

  test('isFromWorker', () => {
    expect(isFromWorker({ type: 'log', line: 'x', stream: 'stdout' })).toBe(true);
    expect(isFromWorker({ type: 'log', line: 'x', stream: 'other' })).toBe(false);
    expect(isFromWorker({ type: 'done', exitCode: 0, outputs: [{ name: 'a', buf: buf(1) }] })).toBe(true);
    expect(isFromWorker({ type: 'done', exitCode: '0', outputs: [] })).toBe(false);
    expect(isFromWorker({ type: 'done', exitCode: 0, outputs: [{ name: 'a' }] })).toBe(false);
    expect(isFromWorker({ type: 'error', message: 'boom' })).toBe(true);
    expect(isFromWorker({ type: 'error' })).toBe(false);
    expect(isFromWorker('log')).toBe(false);
    expect(isFromWorker(undefined)).toBe(false);
  });
});
