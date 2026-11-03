import { describe, expect, test } from 'vitest';
import contract from '../../src/generated/contract.json';
import { CONTRACT_FLAGS, IN_DIR, OUT_DIR, dcm2niixArgv, parseFlags } from '../../src/core/convert-args';

describe('dcm2niixArgv', () => {
  test('is the contract flags, then -o /out, then /in', () => {
    expect(dcm2niixArgv(CONTRACT_FLAGS)).toEqual([...contract.dcm2niix_flags, '-o', '/out', '/in']);
    expect([OUT_DIR, IN_DIR]).toEqual(['/out', '/in']);
  });

  test('keeps the integer-output and omit-identifiers flags the analysis depends on', () => {
    const argv = dcm2niixArgv(CONTRACT_FLAGS);
    const pair = (flag: string): string | undefined => argv[argv.indexOf(flag) + 1];
    expect(pair('-l'), `argv ${JSON.stringify(argv)}`).toBe('o');
    expect(pair('-b'), `argv ${JSON.stringify(argv)}`).toBe('y');
    expect(pair('-ba'), `argv ${JSON.stringify(argv)}`).toBe('o');
  });

  test('does not change its input', () => {
    const flags = ['-z', 'y'];
    dcm2niixArgv(flags);
    expect(flags).toEqual(['-z', 'y']);
  });
});

describe('parseFlags', () => {
  test('accepts the contract list as it is', () => {
    expect(parseFlags(contract.dcm2niix_flags)).toEqual(contract.dcm2niix_flags);
  });

  test.each([[undefined], ['-z y'], [['-z', 1]], [{ 0: '-z' }]])('rejects %j', (bad) => {
    expect(() => parseFlags(bad)).toThrow('dcm2niix_flags is not a list of strings');
  });

  test('rejects -o, which the page sets itself', () => {
    expect(() => parseFlags(['-z', 'y', '-o', '/tmp'])).toThrow('sets -o');
  });
});
