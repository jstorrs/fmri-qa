/**
 * One visible, announced line for the result of the last job ("Saved 12 files …", "ZIP failed: …"). The element is a
 * `role="status"` live region, so setting its text announces it; it is cleared when the next job or open starts.
 */
export type OutcomeKind = 'ok' | 'error';

export interface Outcome {
  notify(message: string, kind: OutcomeKind): void;
  clear(): void;
}

export const mountOutcome = (el: HTMLElement): Outcome => ({
  notify(message, kind) {
    el.textContent = message;
    el.dataset['kind'] = kind;
  },
  clear() {
    el.textContent = '';
    delete el.dataset['kind'];
  },
});
