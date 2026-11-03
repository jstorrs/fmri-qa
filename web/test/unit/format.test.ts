import { describe, expect, it } from 'vitest';
import { formatDate, formatName, formatSize, plural } from '../../src/shell/ui/format';

describe('format', () => {
  it('formatName', () => {
    expect(formatName('Doe^Jane')).toBe('Doe, Jane');
    expect(formatName('A^B^C')).toBe('A, B C');
    expect(formatName('Solo')).toBe('Solo');
    expect(formatName('')).toBe('(no name)');
  });
  it('formatDate', () => {
    expect(formatDate('20260101')).toBe('2026-01-01');
    expect(formatDate(null)).toBe('no date');
    expect(formatDate('2026')).toBe('2026');
  });
  it('formatSize', () => {
    expect(formatSize(0)).toBe('0 B');
    expect(formatSize(1536)).toBe('1.5 KB');
    expect(formatSize(5 * 1024 * 1024)).toBe('5.0 MB');
    expect(formatSize(200 * 1024 * 1024)).toBe('200 MB');
    expect(formatSize(3 * 1024 ** 3)).toBe('3.0 GB');
  });
  it('plural', () => {
    expect(plural(1, 'file')).toBe('1 file');
    expect(plural(1200, 'file')).toBe('1,200 files');
    expect(plural(2, 'study', 'studies')).toBe('2 studies');
  });
});
