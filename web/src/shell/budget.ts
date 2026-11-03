/**
 * Byte budget for concurrent reads. Reads of at most `freeBytes` (header-sized) are never held up. Larger reads
 * wait (FIFO) until they fit under `limit` together with what is in flight; a single read bigger than the limit
 * runs alone.
 */
export interface ByteBudget {
  run<T>(bytes: number, task: () => Promise<T>): Promise<T>;
}

export const createByteBudget = (limit: number, freeBytes: number): ByteBudget => {
  let used = 0;
  const queue: { bytes: number; start: () => void }[] = [];
  const fits = (bytes: number): boolean => used === 0 || used + bytes <= limit;
  const pump = (): void => {
    for (let next = queue[0]; next && fits(next.bytes); next = queue[0]) {
      queue.shift();
      used += next.bytes;
      next.start();
    }
  };
  return {
    async run(bytes, task) {
      if (bytes <= freeBytes) return task();
      await new Promise<void>((start) => {
        queue.push({ bytes, start });
        pump();
      });
      try {
        return await task();
      } finally {
        used -= bytes;
        pump();
      }
    },
  };
};
