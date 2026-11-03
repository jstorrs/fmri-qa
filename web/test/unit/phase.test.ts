import { describe, expect, it } from 'vitest';
import { nextPhase } from '../../src/shell/phase';
import type { Phase, PhaseEvent } from '../../src/shell/phase';

const phases: Phase[] = ['loading', 'empty', 'scanning', 'ready', 'working'];
const events: [string, PhaseEvent][] = [
  ['loaded', 'loaded'],
  ['open', 'open'],
  ['scan-done', 'scan-done'],
  ['abandon-with-previous', { type: 'abandon', hasPrevious: true }],
  ['abandon-without', { type: 'abandon', hasPrevious: false }],
  ['work-begin', 'work-begin'],
  ['work-end', 'work-end'],
];

describe('nextPhase', () => {
  it('follows the lifecycle', () => {
    expect(nextPhase('loading', 'loaded')).toBe('empty');
    expect(nextPhase('empty', 'open')).toBe('scanning');
    expect(nextPhase('scanning', 'scan-done')).toBe('ready');
    expect(nextPhase('ready', 'open')).toBe('scanning');
    expect(nextPhase('scanning', 'open')).toBe('scanning');
    expect(nextPhase('scanning', { type: 'abandon', hasPrevious: false })).toBe('empty');
    expect(nextPhase('scanning', { type: 'abandon', hasPrevious: true })).toBe('ready');
    expect(nextPhase('ready', 'work-begin')).toBe('working');
    expect(nextPhase('working', 'work-end')).toBe('ready');
  });

  it('rejects a second task and any open while working', () => {
    expect(nextPhase('working', 'work-begin')).toBeNull();
    expect(nextPhase('working', 'open')).toBeNull();
  });

  it('cannot run a task before a tree is ready', () => {
    for (const p of ['loading', 'empty', 'scanning'] as const) expect(nextPhase(p, 'work-begin')).toBeNull();
  });

  it('allows exactly the listed transitions', () => {
    const allowed = new Set([
      'loading/loaded', 'empty/open', 'ready/open', 'scanning/open', 'scanning/scan-done', 'scanning/abandon-with-previous', 'scanning/abandon-without', 'ready/work-begin', 'working/work-end',
    ]);
    for (const p of phases) for (const [name, e] of events) expect(nextPhase(p, e) !== null).toBe(allowed.has(`${p}/${name}`));
  });
});
