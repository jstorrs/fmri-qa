import { describe, expect, test } from 'vitest';
import { BURST_MS, claimRejections, describe as describeValue, mountGlobalErrors } from '../../src/shell/ui/errors';

describe('mountGlobalErrors', () => {
  const setup = () => {
    const target = new EventTarget();
    const logs: string[] = [];
    const notes: string[] = [];
    let t = 1000;
    const stop = mountGlobalErrors(target, { log: (m) => logs.push(m), notify: (m, k) => notes.push(`${k}:${m}`) }, () => t);
    const fire = (type: string, props: object) => {
      const ev = new Event(type, { cancelable: true });
      Object.assign(ev, props);
      target.dispatchEvent(ev);
      return ev;
    };
    return { logs, notes, stop, fire, advance: (ms: number) => (t += ms) };
  };

  test('logs every error, notifies once per burst, never prevents default', () => {
    const s = setup();
    const a = s.fire('error', { error: new Error('boom') });
    s.fire('unhandledrejection', { reason: 'nope' });
    expect(a.defaultPrevented).toBe(false);
    expect(s.logs).toEqual(['Unexpected error: boom', 'Unhandled promise rejection: nope']);
    expect(s.notes).toHaveLength(1);
    expect(s.notes[0]).toMatch(/^error:/);
    s.advance(BURST_MS);
    s.fire('error', { message: 'later' });
    expect(s.notes).toHaveLength(2);
  });

  test('notifies again when the outcome line no longer shows the notice', () => {
    const target = new EventTarget();
    let line = '';
    let count = 0;
    mountGlobalErrors(target, { log: () => undefined, notify: (m) => ((line = m), count++), current: () => line }, () => 1000);
    const fire = () => target.dispatchEvent(new Event('error'));
    fire();
    fire();
    expect(count).toBe(1);
    line = '';
    fire();
    expect(count).toBe(2);
  });

  test('claimed rejections are prevented and not reported, only while claimed; errors are never claimed', () => {
    const s = setup();
    class Mine extends Error {}
    const withdraw = claimRejections((r) => r instanceof Mine);
    const broken = claimRejections(() => {
      throw new Error('bad predicate');
    });
    const claimed = s.fire('unhandledrejection', { reason: new Mine('m') });
    const other = s.fire('unhandledrejection', { reason: new Error('o') });
    const error = s.fire('error', { error: new Mine('e') });
    expect([claimed.defaultPrevented, other.defaultPrevented, error.defaultPrevented]).toEqual([true, false, false]);
    expect(s.logs).toEqual(['Unhandled promise rejection: o', 'Unexpected error: e']);
    withdraw();
    broken();
    expect(s.fire('unhandledrejection', { reason: new Mine('later') }).defaultPrevented).toBe(false);
    expect(s.logs).toHaveLength(3);
  });

  test('stop removes the listeners', () => {
    const s = setup();
    s.stop();
    s.fire('error', { error: new Error('x') });
    expect(s.logs).toEqual([]);
  });
});

describe('describe', () => {
  test('falls back to unknown', () => {
    expect(describeValue(new Error(''))).toBe('unknown');
    expect(describeValue('  ')).toBe('unknown');
    expect(describeValue(undefined)).toBe('undefined');
    expect(describeValue({ toString: () => { throw new Error('x'); } })).toBe('unknown');
    expect(describeValue(Object.create(null))).toBe('unknown');
    expect(describeValue(new Error('boom'))).toBe('boom');
  });
});
