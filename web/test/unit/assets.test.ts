import { describe, expect, test } from 'vitest';
import { decodeBase64, isAssetName, isEncodedAsset, parseEncodedAsset } from '../../src/core/assets';

describe('parseEncodedAsset', () => {
  test('reads a gzipped core file', () => {
    expect(parseEncodedAsset({ name: 'pyodide.asm.wasm', kind: 'pyodide-core', gz: '1' }, 'AAAA')).toEqual({
      name: 'pyodide.asm.wasm',
      kind: 'pyodide-core',
      gzip: true,
      base64: 'AAAA',
    });
  });

  test('reads a wheel stored as-is', () => {
    expect(parseEncodedAsset({ name: 'fmri_qa_web-0.1.0-py3-none-any.whl', kind: 'wheel' }, 'AA==')).toEqual({
      name: 'fmri_qa_web-0.1.0-py3-none-any.whl',
      kind: 'wheel',
      gzip: false,
      base64: 'AA==',
    });
  });

  test.each([
    [{ kind: 'wheel' }, 'bad name: undefined'],
    [{ name: '../x.whl', kind: 'wheel' }, 'bad name: "../x.whl"'],
    [{ name: 'a/b.whl', kind: 'wheel' }, 'bad name: "a/b.whl"'],
    [{ name: 'x.whl', kind: 'sdist' }, 'x.whl has kind "sdist"'],
    [{ name: 'x.whl' }, 'x.whl has kind undefined'],
    [{ name: 'x.whl', kind: 'wheel', gz: 'yes' }, 'x.whl has data-gz="yes"'],
  ])('refuses %j', (data, message) => {
    expect(() => parseEncodedAsset(data, 'AA==')).toThrow(message);
  });

  test('refuses an empty block', () => {
    expect(() => parseEncodedAsset({ name: 'x.whl', kind: 'wheel' }, '')).toThrow('x.whl is empty');
  });
});

describe('isAssetName', () => {
  test.each(['pyodide-lock.json', 'python_stdlib.zip', 'python_dateutil-2.9.0.post0-py2.py3-none-any.whl'])('accepts %s', (n) => {
    expect(isAssetName(n)).toBe(true);
  });
  test.each(['', '.', '..', '.hidden', 'a/b', 'a b', 'a%2Fb', 'a?b', 7])('refuses %j', (n) => {
    expect(isAssetName(n)).toBe(false);
  });
});

describe('isEncodedAsset', () => {
  test('accepts what parseEncodedAsset returns', () => {
    expect(isEncodedAsset(parseEncodedAsset({ name: 'x.whl', kind: 'wheel' }, 'AA=='))).toBe(true);
  });
  test.each([
    null,
    'x',
    { name: 'x.whl', kind: 'wheel', gzip: 'no', base64: 'AA==' },
    { name: 'x.whl', kind: 'wheel', gzip: false },
    { name: '../x', kind: 'wheel', gzip: false, base64: '' },
  ])('refuses %j', (x) => {
    expect(isEncodedAsset(x)).toBe(false);
  });
});

describe('decodeBase64', () => {
  const bytes = Uint8Array.from({ length: 256 }, (_, i) => i);
  const text = Buffer.from(bytes).toString('base64');

  test('decodes every byte value', () => {
    expect(decodeBase64(text)).toEqual(bytes);
  });

  test('decodes with the atob loop where Uint8Array.fromBase64 is missing', () => {
    const holder = Uint8Array as { fromBase64?: unknown };
    const saved = holder.fromBase64;
    delete holder.fromBase64;
    try {
      expect(decodeBase64(text)).toEqual(bytes);
    } finally {
      if (saved !== undefined) holder.fromBase64 = saved;
    }
  });

  test('throws on text that is not base64', () => {
    expect(() => decodeBase64('not base64!')).toThrow();
  });
});
