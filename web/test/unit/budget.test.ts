import { describe, expect, it } from 'vitest';
import { createByteBudget } from '../../src/shell/budget';

const gate = () => {
  let release!: () => void;
  const p = new Promise<void>((r) => (release = r));
  return { p, release };
};
const tick = () => new Promise((r) => setTimeout(r, 0));

describe('createByteBudget', () => {
  it('never delays reads at or under the free size', async () => {
    const b = createByteBudget(100, 10);
    const g = gate();
    const started: number[] = [];
    const big = b.run(100, () => g.p);
    void b.run(10, async () => void started.push(1));
    await tick();
    expect(started).toEqual([1]);
    g.release();
    await big;
  });

  it('holds reads that would exceed the limit until others finish, FIFO', async () => {
    const b = createByteBudget(100, 10);
    const g1 = gate();
    const g2 = gate();
    const order: string[] = [];
    const a = b.run(60, async () => (order.push('a'), g1.p));
    const c = b.run(60, async () => (order.push('c'), g2.p));
    const d = b.run(30, async () => void order.push('d'));
    await tick();
    expect(order).toEqual(['a']); // c waits (120 > 100); d queues behind c (FIFO)
    g1.release();
    await tick();
    expect(order).toEqual(['a', 'c', 'd']);
    g2.release();
    await Promise.all([a, c, d]);
  });

  it('runs a read bigger than the limit alone', async () => {
    const b = createByteBudget(100, 10);
    const g = gate();
    let small = false;
    const huge = b.run(500, () => g.p);
    const next = b.run(20, async () => void (small = true));
    await tick();
    expect(small).toBe(false);
    g.release();
    await Promise.all([huge, next]);
    expect(small).toBe(true);
  });

  it('releases the budget when a task throws', async () => {
    const b = createByteBudget(100, 10);
    await expect(b.run(100, () => Promise.reject(new Error('x')))).rejects.toThrow('x');
    await expect(b.run(100, async () => 'ok')).resolves.toBe('ok');
  });
});
