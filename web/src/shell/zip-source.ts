/**
 * ZIP archives as sources of files. The archive stays a `File` on disk: the central directory is read with two ranged
 * slices, and each entry is read on demand from its own slice (stored entries as-is, deflated ones through
 * `DecompressionStream('deflate-raw')`). Nothing is ever unpacked as a whole.
 */
import { crc32 } from '../core/crc32';
import type { Source } from '../core/types';
import { LOCAL_HEADER_BYTES, METHOD_DEFLATE, METHOD_STORE, localDataOffset, readZipDirectory } from '../core/zipdir';
import type { ZipDirectory, ZipEntryInfo } from '../core/zipdir';

/** The part of `Blob` the reader uses; tests wrap a real Blob to record which ranges are read. */
export interface ArchiveBlob {
  readonly size: number;
  slice(start: number, end: number): Blob;
}

/** Compressed bytes are fed to the inflater this many at a time, so a bomb costs at most this x ~1000 of transient output. */
export const PUSH_BYTES = 16 * 1024;
/** A prefix of n bytes reads at most `PREFIX_SLACK_FACTOR * n + PREFIX_SLACK_BYTES` compressed bytes (deflate expands by at most a little over 1x in practice). */
const PREFIX_SLACK_FACTOR = 2;
const PREFIX_SLACK_BYTES = 64 * 1024;

let inflateSupported: boolean | undefined;
/** `DecompressionStream('deflate-raw')` exists here (Chrome 103+, Firefox 113+, Safari 16.4+). */
export const canInflate = (): boolean =>
  (inflateSupported ??= (() => {
    try {
      new DecompressionStream('deflate-raw');
      return true;
    } catch {
      return false;
    }
  })());

export const NO_INFLATE_REASON = 'this browser cannot decompress ZIP entries (no DecompressionStream for deflate-raw)';

const bytesOf = async (blob: Blob): Promise<Uint8Array<ArrayBuffer>> => new Uint8Array(await blob.arrayBuffer());

/**
 * Passes bytes through while checking them against the central directory: the total must be exactly `size` (an
 * overrun errors at once, a shortfall at the end) and the CRC-32, folded in per chunk, must match when the stream
 * ends. `label` names the entry in the message.
 */
const verified = (size: number, crc: number, label: string): TransformStream<Uint8Array, Uint8Array> => {
  let seen = 0;
  let sum = 0;
  return new TransformStream({
    transform(chunk, controller) {
      seen += chunk.length;
      if (seen > size) throw new Error(`${label} is larger than its declared size (${size} bytes)`);
      sum = crc32(chunk, sum);
      controller.enqueue(chunk);
    },
    flush() {
      if (seen !== size) throw new Error(`${label} is ${seen} bytes, not the declared ${size}`);
      if (sum !== crc) throw new Error(`CRC-32 mismatch in ${label} (the archive is damaged)`);
    },
  });
};

/** A deflate stream cannot expand by more than about 1032:1; a declared size beyond that is a lie, not data. */
const MAX_DEFLATE_RATIO = 1040;

class ZipEntrySource implements Source {
  readonly name: string;
  readonly size: number;
  readonly lastModified: number;
  #start: Promise<number> | undefined;

  constructor(
    private readonly archive: ArchiveBlob,
    private readonly entry: ZipEntryInfo,
  ) {
    this.name = entry.name.slice(entry.name.lastIndexOf('/') + 1);
    this.size = entry.size;
    this.lastModified = entry.lastModified;
  }

  /** Offset of the data: the 30-byte local header is read once, on first use (its lengths may differ from the central directory's). */
  #dataStart(): Promise<number> {
    this.#start ??= this.#readLocalHeader().catch((e: unknown) => {
      this.#start = undefined; // do not cache a failure
      throw e;
    });
    return this.#start;
  }

  async #readLocalHeader(): Promise<number> {
    const { method, encrypted, localHeaderOffset, compressedSize, size, name } = this.entry;
    if (encrypted) throw new Error('entry is encrypted');
    if (method === METHOD_DEFLATE && !canInflate()) throw new Error(NO_INFLATE_REASON);
    if (method !== METHOD_STORE && method !== METHOD_DEFLATE) throw new Error(`unsupported compression method ${method}`);
    if (method === METHOD_STORE && compressedSize !== size) throw new Error('stored entry has inconsistent sizes');
    if (method === METHOD_DEFLATE && size > compressedSize * MAX_DEFLATE_RATIO + 1024) throw new Error('entry size is impossible for its compressed size (damaged archive)');
    const head = await bytesOf(this.archive.slice(localHeaderOffset, Math.min(localHeaderOffset + LOCAL_HEADER_BYTES, this.archive.size)));
    const at = localDataOffset(head, localHeaderOffset);
    if (!at.ok) throw new Error(`${at.error} (${name})`);
    if (at.value + compressedSize > this.archive.size) throw new Error('entry data extends past the end of the archive (truncated?)');
    return at.value;
  }

  async #raw(from = 0, to = this.entry.compressedSize): Promise<Blob> {
    const start = await this.#dataStart();
    return this.archive.slice(start + from, start + to);
  }

  async readPrefix(n: number): Promise<Uint8Array> {
    const want = Math.min(n, this.size);
    if (want <= 0) {
      await this.#dataStart(); // still validates the entry
      return new Uint8Array(0);
    }
    if (this.entry.method === METHOD_STORE) return bytesOf(await this.#raw(0, want));
    const start = await this.#dataStart();
    const cap = Math.min(this.entry.compressedSize, PREFIX_SLACK_FACTOR * want + PREFIX_SLACK_BYTES);
    return inflatePrefix((a, b) => this.archive.slice(start + a, start + b), cap, want);
  }

  /** The whole entry in one preallocated buffer, filled chunk by chunk (size and CRC-32 are checked by {@link verified}). */
  async bytes(): Promise<ArrayBuffer> {
    const reader = (await this.#open()).getReader();
    const out = new Uint8Array(this.size);
    let at = 0;
    try {
      for (;;) {
        const r = await reader.read();
        if (r.done) break;
        out.set(r.value, at);
        at += r.value.length;
      }
    } finally {
      reader.releaseLock();
    }
    return out.buffer;
  }

  /** The entry's content, verified on the way. Stored data is the raw slice; deflated data is inflated first. */
  async #open(): Promise<ReadableStream<Uint8Array>> {
    const raw = (await this.#raw()).stream();
    const check = verified(this.size, this.entry.crc32, `entry ${this.entry.name}`);
    return this.entry.method === METHOD_STORE ? raw.pipeThrough(check) : raw.pipeThrough(new DecompressionStream('deflate-raw')).pipeThrough(check);
  }

  stream(): ReadableStream<Uint8Array> {
    let inner: ReadableStreamDefaultReader<Uint8Array> | undefined;
    return new ReadableStream<Uint8Array>({
      pull: async (controller) => {
        inner ??= (await this.#open()).getReader();
        const r = await inner.read();
        if (r.done) controller.close();
        else controller.enqueue(r.value);
      },
      cancel: (reason) => inner?.cancel(reason),
    });
  }
}

/**
 * The first `want` bytes of a raw-deflate stream whose compressed bytes are `slice(a, b)` for `0 <= a < b <= cap`.
 * Compressed input is pushed in {@link PUSH_BYTES} pieces and reading stops (and the rest is never read) once `want`
 * bytes are out. Never a short result: if the input runs out, the stream is damaged, or reading the archive fails
 * (the file changed, the drive went away), it rejects, and a failed read aborts the decompressor so the reader
 * side rejects with that same error instead of waiting for input that will never come.
 */
const inflatePrefix = async (slice: (from: number, to: number) => Blob, cap: number, want: number): Promise<Uint8Array> => {
  const ds = new DecompressionStream('deflate-raw');
  const writer = ds.writable.getWriter();
  const reader = ds.readable.getReader();
  let stop = false;
  let feedError: { readonly error: unknown } | undefined;
  const feed = (async () => {
    try {
      for (let at = 0; at < cap && !stop; at += PUSH_BYTES) await writer.write(await bytesOf(slice(at, Math.min(at + PUSH_BYTES, cap))));
      if (!stop) await writer.close();
    } catch (error) {
      if (stop) return; // we cancelled; the failure is ours
      feedError = { error };
      await writer.abort(error).catch(() => undefined);
    }
  })();
  const out = new Uint8Array(want);
  let total = 0;
  try {
    while (total < want) {
      const r = await reader.read();
      if (r.done) throw new Error(`entry ends after ${total} bytes (${want} expected; the entry is damaged or truncated)`);
      const part = r.value.subarray(0, want - total);
      out.set(part, total);
      total += part.length;
    }
  } catch (e) {
    throw feedError ? feedError.error : e;
  } finally {
    stop = true;
    await reader.cancel().catch(() => undefined);
    await feed;
  }
  return out;
};

/** One entry of an archive as a {@link Source}. The entry must be a supported one (not encrypted; stored or deflated), else reads fail. */
export const zipEntrySource = (archive: ArchiveBlob, entry: ZipEntryInfo): Source => new ZipEntrySource(archive, entry);

/** The archive's entries, read with two ranged slices (the tail, then the central directory). Never throws. */
export const readArchive = (file: ArchiveBlob): Promise<ZipDirectory> =>
  readZipDirectory(file.size, (start, end) => bytesOf(file.slice(start, end)));
