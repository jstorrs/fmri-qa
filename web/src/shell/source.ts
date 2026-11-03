import type { Source } from '../core/types';

/** A file (or other input) to scan, with the path it is shown and sorted under. */
export interface ScanInput {
  readonly source: Source;
  readonly relPath: string;
}

/** A plain file as a {@link Source}. Reads are slices of the File, so nothing is copied until it is asked for. */
export const fileSource = (file: File): Source => ({
  name: file.name,
  size: file.size,
  lastModified: file.lastModified,
  readPrefix: async (n) => new Uint8Array(await file.slice(0, n).arrayBuffer()),
  bytes: () => file.arrayBuffer(),
  stream: () => file.stream(),
});
