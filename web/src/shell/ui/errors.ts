import type { OutcomeKind } from './outcome';

const NOTICE = 'Something went wrong inside the page. Your files are unchanged. Details are under Messages.';

/** Further errors within this long of the one that was shown are only logged. */
export const BURST_MS = 5000;

interface Sink {
  log(message: string): void;
  notify(message: string, kind: OutcomeKind): void;
  /** What the visible outcome line currently shows. */
  current?(): string;
}

/** Never throws; an empty or unprintable value becomes 'unknown'. */
export const describe = (v: unknown): string => {
  try {
    const text = v instanceof Error ? v.message : String(v);
    return text.trim() === '' ? 'unknown' : text;
  } catch {
    return 'unknown';
  }
};

/** Rejections a feature expects and handles itself (see {@link claimRejections}). */
const claimed = new Set<(reason: unknown) => boolean>();

/**
 * Treat unhandled rejections whose reason matches `isMine` as handled: not reported, and their default (the console
 * error, a page error under e2e) prevented. For the viewer, whose image loads Cornerstone leaves unhandled (PLAN.md).
 * Checked inside {@link mountGlobalErrors}'s own listener, so it does not depend on listener order (Chrome runs a
 * window's listeners in the order added, capture or not). Returns a function that withdraws the claim.
 */
export const claimRejections = (isMine: (reason: unknown) => boolean): (() => void) => {
  const own = (reason: unknown): boolean => isMine(reason); // a fresh entry, so claiming twice needs two withdrawals
  claimed.add(own);
  return () => void claimed.delete(own);
};

const isClaimed = (reason: unknown): boolean => {
  for (const isMine of claimed)
    try {
      if (isMine(reason)) return true;
    } catch {
      /* a broken predicate claims nothing */
    }
  return false;
};

/**
 * Surface uncaught errors and unhandled promise rejections: every one goes to the log, and the first of a burst also
 * shows a visible error line. Never calls `preventDefault` (so they stay page errors: the console, and e2e failures),
 * except for rejections claimed with {@link claimRejections}. Returns a function that removes the listeners.
 */
export const mountGlobalErrors = (target: EventTarget, sink: Sink, now: () => number = () => performance.now()): (() => void) => {
  let lastShown = -Infinity;
  const report = (what: string, detail: string): void => {
    sink.log(`${what}: ${detail}`);
    const t = now();
    // Within a burst the notice is not repeated, unless something (e.g. a job starting) has cleared it since.
    if (t - lastShown < BURST_MS && (sink.current === undefined || sink.current() === NOTICE)) return;
    lastShown = t;
    sink.notify(NOTICE, 'error');
  };
  const onError = (e: Event): void => {
    const ev = e as ErrorEvent;
    report('Unexpected error', describe(ev.error ?? ev.message ?? 'unknown'));
  };
  const onRejection = (e: Event): void => {
    const { reason } = e as PromiseRejectionEvent;
    if (isClaimed(reason)) e.preventDefault();
    else report('Unhandled promise rejection', describe(reason));
  };
  target.addEventListener('error', onError);
  target.addEventListener('unhandledrejection', onRejection);
  return () => {
    target.removeEventListener('error', onError);
    target.removeEventListener('unhandledrejection', onRejection);
  };
};
