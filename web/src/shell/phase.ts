/** App phase machine (pure). `body[data-state]` mirrors the phase. */
export type Phase = 'loading' | 'empty' | 'scanning' | 'ready' | 'working';
/** Leaving `scanning` without a new tree (cancel, nothing found, failure). `hasPrevious`: the set shown before is put back. */
export interface AbandonEvent {
  readonly type: 'abandon';
  readonly hasPrevious: boolean;
}
export type PhaseEvent = 'loaded' | 'open' | 'scan-done' | 'work-begin' | 'work-end' | AbandonEvent;

/** The next phase, or null when the event is not allowed in `phase` (callers ignore or reject it). */
export const nextPhase = (phase: Phase, event: PhaseEvent): Phase | null => {
  if (typeof event === 'object') return phase === 'scanning' ? (event.hasPrevious ? 'ready' : 'empty') : null;
  switch (event) {
    case 'loaded':
      return phase === 'loading' ? 'empty' : null;
    case 'open': // a new set may replace anything except while a task (ZIP, convert) runs
      return phase === 'empty' || phase === 'ready' || phase === 'scanning' ? 'scanning' : null;
    case 'scan-done':
      return phase === 'scanning' ? 'ready' : null;
    case 'work-begin':
      return phase === 'ready' ? 'working' : null;
    case 'work-end':
      return phase === 'working' ? 'ready' : null;
  }
};
