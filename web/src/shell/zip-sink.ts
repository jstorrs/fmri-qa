/**
 * Where a ZIP goes: client-zip input in, the user's disk out. Through the save picker where there is one (streamed,
 * so memory stays flat), else through a Blob and an anchor click (the whole archive is buffered).
 */
import { makeZip } from 'client-zip';
import { saveBlob } from './download';
import { formatSize } from './ui/format';

/** Above this the blob path needs the whole archive in memory/disk; ask first. */
export const BLOB_WARN_BYTES = 2 * 1024 ** 3;

/** What client-zip's `makeZip` takes. */
export type ZipFiles = Parameters<typeof makeZip>[0];

interface SaveHandle {
  createWritable(): Promise<WritableStream<Uint8Array>>;
}
export type SavePicker = (o: { suggestedName: string; types: { description: string; accept: Record<string, string[]> }[] }) => Promise<SaveHandle>;
/** The slice of `navigator.userActivation` used here. */
export interface Activation {
  readonly isActive: boolean;
}

const errName = (e: unknown): string => (e instanceof DOMException || e instanceof Error ? e.name : '');

export type FileChoice = { handle: SaveHandle } | 'cancelled' | 'unavailable' | 'expired';

/**
 * A file handle, or why there is none: the user cancelled; the picker is missing or unusable here (use a blob); or the
 * picker refused because the click's user activation ran out while the user was answering a question first
 * ('expired': falling back to the in-memory blob path would be a silent downgrade, so the caller asks for a new click).
 */
export const askForFile = async (
  picker: SavePicker | undefined,
  activation: Activation | undefined,
  name: string,
  note: (m: string) => void,
): Promise<FileChoice> => {
  if (typeof picker !== 'function') return 'unavailable';
  try {
    const handle = await picker.call(window, {
      suggestedName: name,
      types: [{ description: 'ZIP archive', accept: { 'application/zip': ['.zip'] } }],
    });
    return { handle };
  } catch (e) {
    const n = errName(e);
    if (n === 'AbortError') return 'cancelled';
    if (n === 'SecurityError' && activation?.isActive === false) {
      note("Save dialog not shown: the click's permission expired while waiting for an answer.");
      return 'expired';
    }
    if (n === 'SecurityError' || n === 'NotAllowedError') {
      note(`Save dialog unavailable (${n}); downloading instead.`);
      return 'unavailable';
    }
    throw e;
  }
};

/** Chunks are folded into an intermediate Blob this often, so the renderer never holds every chunk as a JS array as well as the Blob. */
export const BLOB_FOLD_BYTES = 32 * 1024 ** 2;

/**
 * The whole stream as a Blob. Read by hand rather than through `new Response(stream).blob()`: when the stream errors
 * (the user cancelled), Firefox leaves an extra rejected promise behind that surfaces as an uncaught page error.
 * Every `foldBytes` the chunks so far become one Blob (the browser may keep those on disk), and the result is a Blob
 * of those, so the order and the bytes are the stream's.
 */
export const streamToBlob = async (
  stream: ReadableStream<Uint8Array>,
  foldBytes = BLOB_FOLD_BYTES,
  makeBlob: (parts: BlobPart[]) => Blob = (parts) => new Blob(parts),
): Promise<Blob> => {
  const reader = stream.getReader();
  const folded: Blob[] = [];
  let parts: BlobPart[] = [];
  let pending = 0;
  for (;;) {
    const r = await reader.read();
    if (r.done) break;
    parts.push(r.value as BlobPart);
    pending += r.value.byteLength;
    if (pending >= foldBytes) {
      folded.push(makeBlob(parts));
      parts = [];
      pending = 0;
    }
  }
  if (parts.length > 0) folded.push(makeBlob(parts));
  return makeBlob(folded);
};

const rejectOnAbort = (signal: AbortSignal): Promise<never> =>
  new Promise((_, reject) => {
    const fail = (): void => reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
    if (signal.aborted) fail();
    else signal.addEventListener('abort', fail, { once: true });
  });

/** The ZIP bytes of `files`, counted through `onBytes`. Aborting `signal` errors the stream. */
export const zipStream = (files: ZipFiles, onBytes: (n: number) => void, signal: AbortSignal): ReadableStream<Uint8Array> =>
  makeZip(files).pipeThrough(
    new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        controller.enqueue(chunk);
        onBytes(chunk.byteLength);
      },
    }),
    { signal },
  );

export interface SaveZipOptions {
  /** The file name offered to the user. */
  readonly name: string;
  /**
   * Builds the client-zip input; not called until the user has chosen where to save. The signal it gets aborts when
   * `signal` does and also when saving fails or ends, so work behind the input (a conversion) stops with the save.
   */
  readonly files: (signal: AbortSignal) => ZipFiles;
  /**
   * What the blob path would have to hold: the archive's predicted size, or an estimate when it is unknown (NIfTI
   * output). Above {@link BLOB_WARN_BYTES} the user is asked before the blob path starts.
   */
  readonly predictedBytes: number;
  readonly signal: AbortSignal;
  readonly onBytes: (n: number) => void;
  /** A message for the log, e.g. that the save dialog is unavailable. */
  readonly note: (m: string) => void;
}

/**
 * Save the ZIP. The picker is the first await, so call this while the click's user activation is alive. Returns
 * `'cancelled'` when the user dismisses the dialog or declines the blob-path warning, and `'expired'` when the picker
 * refused because the activation ran out (nothing was read; ask the user to click again). Failures (including abort)
 * are thrown, a partial picker file is dropped where the browser supports it, and the input's signal is aborted.
 */
export const saveZip = async (o: SaveZipOptions): Promise<'saved' | 'cancelled' | 'expired'> => {
  const picker = (window as unknown as { showSaveFilePicker?: SavePicker }).showSaveFilePicker;
  const target = await askForFile(picker, (navigator as { userActivation?: Activation }).userActivation, o.name, o.note);
  if (target === 'cancelled' || target === 'expired') return target;

  // One signal for everything behind the stream: the caller's, plus our own for a failed save (not AbortSignal.any: Safari < 17.4).
  const local = new AbortController();
  const forward = (): void => local.abort(o.signal.reason);
  if (o.signal.aborted) forward();
  else o.signal.addEventListener('abort', forward, { once: true });
  const { signal } = local;
  try {
    if (target === 'unavailable') {
      if (
        o.predictedBytes > BLOB_WARN_BYTES &&
        !confirm(
          `This archive is ${formatSize(o.predictedBytes)}. This browser cannot stream it to disk, so it will buffer the whole archive in memory and needs about that much free disk space when saving. Continue?`,
        )
      )
        return 'cancelled';
      const blob = await Promise.race([streamToBlob(zipStream(o.files(signal), o.onBytes, signal)), rejectOnAbort(signal)]);
      saveBlob(o.name, blob);
      return 'saved';
    }
    const writable = await target.handle.createWritable();
    try {
      await zipStream(o.files(signal), o.onBytes, signal).pipeTo(writable, { signal });
    } catch (e) {
      await writable.abort(e).catch(() => undefined); // drop the partial file where supported
      throw e;
    }
    return 'saved';
  } finally {
    o.signal.removeEventListener('abort', forward);
    local.abort();
  }
};
