/**
 * Directory intake. Every path yields `Picked[]`: a File plus the path it should
 * have relative to the chosen root (like `webkitRelativePath`).
 *
 * The walkers are pure over small structural interfaces so they can be tested
 * with fakes; the thin DOM adapters at the bottom do the browser-specific bits.
 */

export interface Picked {
  readonly file: File;
  readonly relPath: string;
}

export interface Intake {
  readonly files: readonly Picked[];
  /** Entries that could not be read and were skipped. */
  readonly errors: number;
  /** Message of the first failure, if any (shown when nothing at all could be read). */
  readonly error?: string;
}

export interface WalkOptions {
  readonly signal?: AbortSignal;
  /** Called with the running count of files found (may be called very often; throttle in the caller). */
  readonly onFound?: (n: number) => void;
}

/** Directories nested deeper than this are not entered; what is below counts as an error. */
export const MAX_DEPTH = 64;
/** Concurrent FileSystemEntry callbacks in flight. */
export const ENTRY_CONCURRENCY = 64;

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** Tracks the error count and the first message. */
const errorTally = () => {
  let errors = 0;
  let first: string | undefined;
  return {
    add(e: unknown): void {
      errors++;
      first ??= message(e);
    },
    result: (files: Picked[]): Intake => (first === undefined ? { files, errors } : { files, errors, error: first }),
  };
};

/** At most `n` tasks run at once; the rest wait in FIFO order (a finishing task hands its slot straight to the next). */
export const limiter = (n: number) => {
  let active = 0;
  const waiting: (() => void)[] = [];
  let head = 0; // index queue: shift() would be O(n) per call with 200k waiters
  return async <T>(task: () => Promise<T>): Promise<T> => {
    if (active >= n) await new Promise<void>((r) => waiting.push(r));
    else active++;
    try {
      return await task();
    } finally {
      const next = waiting[head];
      if (next) {
        waiting[head++] = undefined as never;
        if (head > 1024 && head * 2 > waiting.length) waiting.splice(0, head), (head = 0);
        next(); // slot transferred
      } else active--;
    }
  };
};

export const joinPath = (parent: string, name: string): string => (parent === '' ? name : `${parent}/${name}`);

/** From an `<input type=file>` list: webkitRelativePath when present, else the bare name. */
export const pickedFromFiles = (files: ArrayLike<File>): Picked[] =>
  Array.from(files, (file) => ({ file, relPath: file.webkitRelativePath || file.name }));

// ---- FileSystemEntry walker (drag and drop) -------------------------------

export interface FileEntryLike {
  readonly isFile: true;
  readonly isDirectory: false;
  readonly name: string;
  file(ok: (f: File) => void, err: (e: unknown) => void): void;
}
export interface DirectoryReaderLike {
  readEntries(ok: (batch: readonly EntryLike[]) => void, err: (e: unknown) => void): void;
}
export interface DirEntryLike {
  readonly isFile: false;
  readonly isDirectory: true;
  readonly name: string;
  createReader(): DirectoryReaderLike;
}
export type EntryLike = FileEntryLike | DirEntryLike;

const fileOf = (e: FileEntryLike): Promise<File> => new Promise((ok, err) => e.file(ok, err));
const batchOf = (r: DirectoryReaderLike): Promise<readonly EntryLike[]> =>
  new Promise((ok, err) => r.readEntries(ok, err));

/** readEntries returns batches (Chrome: 100 at a time); loop until an empty one. A failure keeps what was read. */
const readAllEntries = async (
  reader: DirectoryReaderLike,
  limit: ReturnType<typeof limiter>,
  signal?: AbortSignal,
): Promise<{ readonly entries: EntryLike[]; readonly failure?: unknown }> => {
  const entries: EntryLike[] = [];
  try {
    for (;;) {
      // The check runs inside the limited task: everything queued before an abort must not still call into the browser.
      const batch = await limit(() => (signal?.aborted ? Promise.resolve([]) : batchOf(reader)));
      if (batch.length === 0) return { entries };
      for (const e of batch) entries.push(e); // not push(...batch): a huge batch would overflow the argument limit
    }
  } catch (failure) {
    return { entries, failure };
  }
};

/** Recursively collect files under the given roots. Errors on individual entries are counted, not thrown. */
export const walkEntries = async (roots: readonly EntryLike[], opts: WalkOptions = {}): Promise<Intake> => {
  const tally = errorTally();
  const limit = limiter(ENTRY_CONCURRENCY);
  let found = 0;
  const walk = async (entry: EntryLike, prefix: string, depth: number): Promise<Picked[]> => {
    if (opts.signal?.aborted) return [];
    const relPath = joinPath(prefix, entry.name);
    if (depth > MAX_DEPTH) {
      tally.add(new Error(`nested deeper than ${MAX_DEPTH} levels: ${relPath}`));
      return [];
    }
    try {
      if (entry.isFile) {
        const file = await limit(() => (opts.signal?.aborted ? Promise.resolve(null) : fileOf(entry)));
        if (file === null) return [];
        opts.onFound?.(++found);
        return [{ file, relPath }];
      }
      const { entries, failure } = await readAllEntries(entry.createReader(), limit, opts.signal);
      if (failure !== undefined) tally.add(failure);
      const parts = await Promise.all(entries.map((e) => walk(e, relPath, depth + 1)));
      const out: Picked[] = [];
      for (const part of parts) for (const f of part) out.push(f);
      return out;
    } catch (e) {
      tally.add(e);
      return [];
    }
  };
  const parts = await Promise.all(roots.map((r) => walk(r, '', 0)));
  const files: Picked[] = [];
  for (const part of parts) for (const f of part) files.push(f);
  return tally.result(files);
};

// ---- File System Access handle walker (showDirectoryPicker) ---------------

export interface FileHandleLike {
  readonly kind: 'file';
  readonly name: string;
  getFile(): Promise<File>;
}
export interface DirHandleLike {
  readonly kind: 'directory';
  readonly name: string;
  values(): AsyncIterable<FileHandleLike | DirHandleLike>;
}

export const walkHandle = async (root: DirHandleLike, opts: WalkOptions = {}): Promise<Intake> => {
  const tally = errorTally();
  const files: Picked[] = [];
  const walk = async (dir: DirHandleLike, prefix: string, depth: number): Promise<void> => {
    try {
      for await (const h of dir.values()) {
        if (opts.signal?.aborted) return;
        const relPath = joinPath(prefix, h.name);
        try {
          if (h.kind === 'file') {
            files.push({ file: await h.getFile(), relPath });
            opts.onFound?.(files.length);
          } else if (depth + 1 > MAX_DEPTH) {
            tally.add(new Error(`nested deeper than ${MAX_DEPTH} levels: ${relPath}`));
          } else await walk(h, relPath, depth + 1);
        } catch (e) {
          tally.add(e);
        }
      }
    } catch (e) {
      tally.add(e);
    }
  };
  await walk(root, root.name, 0);
  return tally.result(files);
};

// ---- DOM adapters ---------------------------------------------------------

/**
 * Must be called synchronously inside the `drop` handler: the DataTransfer is
 * emptied once the handler yields. Items without entry support fall back to
 * their File.
 */
export const grabDropped = (dt: DataTransfer): { entries: EntryLike[]; loose: Picked[] } => {
  const entries: EntryLike[] = [];
  const loose: Picked[] = [];
  for (const item of Array.from(dt.items)) {
    if (item.kind !== 'file') continue;
    // The DOM's FileSystemEntry types isFile/isDirectory as plain booleans; they are exclusive in practice.
    const entry = item.webkitGetAsEntry() as unknown as EntryLike | null;
    if (entry) entries.push(entry);
    else {
      const file = item.getAsFile();
      if (file) loose.push({ file, relPath: file.name });
    }
  }
  return { entries, loose };
};

export const readDropped = async (grabbed: ReturnType<typeof grabDropped>, opts: WalkOptions = {}): Promise<Intake> => {
  const walked = await walkEntries(grabbed.entries, opts);
  const files = walked.files.slice();
  for (const f of grabbed.loose) files.push(f);
  return { ...walked, files };
};

type DirectoryPicker = () => Promise<DirHandleLike>;
const directoryPicker = (): DirectoryPicker | undefined =>
  (window as unknown as { showDirectoryPicker?: DirectoryPicker }).showDirectoryPicker?.bind(window);

export const hasDirectoryPicker = (): boolean => directoryPicker() !== undefined;

/** Null when the user cancels (AbortError) or there is no picker; other errors propagate. Walk the result with {@link walkHandle}. */
export const pickDirectoryHandle = async (): Promise<DirHandleLike | null> => {
  const picker = directoryPicker();
  if (!picker) return null;
  try {
    return await picker();
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') return null;
    throw e;
  }
};
