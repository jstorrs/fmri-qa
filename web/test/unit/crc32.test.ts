import { crc32 as reference } from 'node:zlib';
import { describe, expect, test } from 'vitest';
import { crc32 } from '../../src/core/crc32';
import { randomBytes } from './zip-bytes';

describe('crc32', () => {
  test('known vectors', () => {
    expect(crc32(new TextEncoder().encode('123456789'))).toBe(0xcbf43926);
    expect(crc32(new Uint8Array(0))).toBe(0);
    expect(crc32(new TextEncoder().encode('The quick brown fox jumps over the lazy dog'))).toBe(0x414fa339);
  });

  test('agrees with zlib for every length up to 70 and at every alignment (slice-by-8 head and tail paths)', () => {
    const base = randomBytes(200, 1);
    for (let offset = 0; offset < 8; offset++) {
      for (let len = 0; len <= 70; len++) {
        const view = base.subarray(offset, offset + len);
        expect(crc32(view), `offset ${offset} length ${len}`).toBe(reference(view));
      }
    }
  });

  test('agrees with zlib on larger inputs, and chunked updates equal one pass', () => {
    const big = randomBytes(1_000_003, 2);
    expect(crc32(big)).toBe(reference(big));
    let running = 0;
    for (let at = 0; at < big.length; at += 77_777) running = crc32(big.subarray(at, at + 77_777), running);
    expect(running).toBe(reference(big));
  });

  test('values with the high bit set come back unsigned', () => {
    const v = crc32(new Uint8Array([0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff]));
    expect(v).toBeGreaterThanOrEqual(0);
    expect(v).toBe(reference(new Uint8Array(18).fill(0xff)));
  });
});
