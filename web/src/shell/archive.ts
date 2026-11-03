/**
 * ZIP expansion for intake. Every picked file named `*.zip` whose first bytes are a ZIP signature is replaced by its
 * entries, one level deep: an entry becomes a scan input with the path `archive.zip/inside/path`, read lazily from
 * the archive when scanned, converted or exported. Everything else passes through as a plain file.
 */
import { METHOD_DEFLATE, METHOD_STORE, hasZipMagic } from '../core/zipdir';
import type { ZipEntryInfo } from '../core/zipdir';
import type { Picked } from './intake';
import type { SkippedFile } from './scan';
import { fileSource } from './source';
import type { ScanInput } from './source';
import { NO_INFLATE_REASON, canInflate, readArchive, zipEntrySource } from './zip-source';

export interface ArchiveSummary {
  readonly relPath: string;
  /** Files inside (directory entries not counted), including those skipped. */
  readonly entries: number;
}

export interface Expansion {
  /** Plain files and ZIP entries to scan, in input order (an archive's entries in place of the archive). */
  readonly inputs: readonly ScanInput[];
  /** Archives that could not be read and entries that will not be scanned, with the reason. */
  readonly skipped: readonly SkippedFile[];
  readonly archives: readonly ArchiveSummary[];
}

export interface ExpandOptions {
  readonly signal?: AbortSignal;
  /** Running count of inputs found (may be called very often; throttle in the caller). */
  readonly onFound?: (n: number) => void;
}

/** Only files named like this are looked at for a ZIP signature (reading the first bytes of every file would cost a read each). */
const ZIP_NAME = /\.zip$/i;

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** Why an entry is left out, or null if it can be scanned. */
const skipOf = (e: ZipEntryInfo, inflate: boolean): Omit<SkippedFile, 'relPath'> | null => {
  if (ZIP_NAME.test(e.name)) return { reason: 'nested-zip', detail: 'only one level of ZIP archives is opened' };
  if (e.encrypted) return { reason: 'encrypted', detail: 'password-protected entries are not supported' };
  if (e.method !== METHOD_STORE && e.method !== METHOD_DEFLATE) return { reason: 'unsupported-method', detail: `compression method ${e.method} is not supported (only store and deflate)` };
  if (e.method === METHOD_DEFLATE && !inflate) return { reason: 'unreadable', detail: NO_INFLATE_REASON };
  return null;
};

export const expandArchives = async (picked: readonly Picked[], opts: ExpandOptions = {}): Promise<Expansion> => {
  const inputs: ScanInput[] = [];
  const skipped: SkippedFile[] = [];
  const archives: ArchiveSummary[] = [];
  const found = (): void => opts.onFound?.(inputs.length);
  const inflate = canInflate();
  for (const { file, relPath } of picked) {
    if (opts.signal?.aborted) break;
    if (ZIP_NAME.test(file.name)) {
      let isZip: boolean;
      try {
        isZip = hasZipMagic(new Uint8Array(await file.slice(0, 4).arrayBuffer()));
      } catch (e) {
        skipped.push({ relPath, reason: 'unreadable', detail: message(e) });
        continue;
      }
      if (isZip) {
        const dir = await readArchive(file);
        if (!dir.ok) {
          skipped.push({ relPath, reason: 'unreadable', detail: `cannot read ZIP archive: ${dir.error}` });
          continue;
        }
        let entries = 0;
        for (const e of dir.entries) {
          if (opts.signal?.aborted) break;
          if (e.isDir) continue;
          entries++;
          const entryPath = `${relPath}/${e.name}`;
          const skip = skipOf(e, inflate);
          if (skip) skipped.push({ relPath: entryPath, ...skip });
          else {
            inputs.push({ source: zipEntrySource(file, e), relPath: entryPath });
            found();
          }
        }
        archives.push({ relPath, entries });
        continue;
      }
    }
    inputs.push({ source: fileSource(file), relPath });
    found();
  }
  return { inputs, skipped, archives };
};
