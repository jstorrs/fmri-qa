/** Pure pieces of the dcm2niix conversion: input names, errors and safe entry names. Arguments live in `profiles.ts`, output naming in `nifti-naming.ts`. */

/** `0000.dcm`, `0001.dcm`, ... padded to max(4, digits(n)). Names carry no patient data and cannot collide. */
export const inputNames = (n: number): string[] => {
  const width = Math.max(4, String(Math.max(0, n)).length);
  return Array.from({ length: n }, (_, i) => String(i).padStart(width, '0') + '.dcm');
};

/**
 * An input file could not be read or prepared. `relPath` (the path in the opened folder or archive, which can name
 * the patient) is kept apart from the generic reason so it can go to the log and never to a report.
 */
export class InputReadError extends Error {
  constructor(
    readonly relPath: string,
    message: string,
    options?: ErrorOptions,
  ) {
    super(message, options);
    this.name = 'InputReadError';
  }
}

export interface OutputFile {
  readonly name: string;
  readonly buf: ArrayBuffer;
}

/** One path component: no separators, no control characters, no `..`, no leading dots or spaces, never empty. */
export const safeEntryName = (name: string): string => {
  // eslint-disable-next-line no-control-regex
  const cleaned = name.replace(/[\u0000-\u001f\u007f\\/]+/g, '_').trim().replace(/\.{2,}/g, '.').replace(/^[.\s]+/, '').trim();
  return cleaned === '' ? 'output' : cleaned;
};

/**
 * What the user sees when the wasm module dies. Out-of-memory in the 2 GB heap surfaces as a WebAssembly
 * RuntimeError, an Emscripten `Aborted(...)`, or "memory access out of bounds"; the raw text is not helpful.
 */
export const CRASH_MESSAGE = 'dcm2niix crashed, probably out of memory (the series may be too large)';
export const isWasmCrash = (message: string): boolean =>
  /RuntimeError|Aborted\(|memory access out of bounds|out of memory|Cannot enlarge memory/i.test(message);
export const friendlyError = (message: string): string => (isWasmCrash(message) ? CRASH_MESSAGE : message);
