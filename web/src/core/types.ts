/**
 * Branded, tree-unique series identity: JSON of (patient group key, study UID,
 * series UID), which is injective whatever characters the parts contain.
 * Construct only via {@link seriesKey}.
 */
export type SeriesKey = string & { readonly __brand: 'SeriesKey' };

export const seriesKey = (patientGroupKey: string, studyUid: string, seriesUid: string): SeriesKey =>
  JSON.stringify([patientGroupKey, studyUid, seriesUid]) as SeriesKey;

export interface WindowLevel {
  readonly center: number;
  readonly width: number;
}

/**
 * Where an instance's bytes come from: a plain file, or an entry of a ZIP archive. The interface is declared here (a
 * port) and implemented in the shell (`src/shell/source.ts`, `zip-source.ts`); core only reads `size` (and the
 * metadata) and passes the handle along, so it stays free of IO and of any browser type.
 */
export interface Source {
  /** Base name (for a ZIP entry, the last path segment). */
  readonly name: string;
  /** Uncompressed size in bytes. */
  readonly size: number;
  readonly lastModified: number;
  /** The first `min(n, size)` bytes. */
  readPrefix(n: number): Promise<Uint8Array>;
  /** The whole content. A ZIP entry is checked against its CRC-32 and declared size. */
  bytes(): Promise<ArrayBuffer>;
  /** The whole content as a stream. A ZIP entry is checked against its declared size and CRC-32 (errors at the end). */
  stream(): ReadableStream<Uint8Array>;
}

export interface Instance {
  readonly source: Source;
  readonly relPath: string;
  readonly sopInstanceUid: string | null;
  readonly transferSyntax: string | null;
  readonly patient: { readonly id: string; readonly name: string };
  readonly study: {
    readonly uid: string;
    readonly date: string | null;
    readonly time: string | null;
    readonly description: string;
    readonly accessionNumber: string;
  };
  readonly series: {
    readonly uid: string;
    readonly number: number | null;
    readonly description: string;
    readonly modality: string;
  };
  readonly instanceNumber: number | null;
  readonly echoNumber: number | null;
  /** NumberOfFrames; 1 when absent or invalid. */
  readonly frames: number;
  readonly window: WindowLevel | null;
}

export type HeaderOutcome =
  | { readonly kind: 'instance'; readonly instance: Instance }
  | { readonly kind: 'skipped'; readonly reason: 'dicomdir' }
  /** `detail` (`readOutcome` only) says when the file looks like something else, e.g. a ZIP archive that was not opened. */
  | { readonly kind: 'skipped'; readonly reason: 'not-dicom'; readonly detail?: string }
  /** A read failed (`readOutcome` only); `detail` is the error message. */
  | { readonly kind: 'skipped'; readonly reason: 'unreadable'; readonly detail?: string }
  | { readonly kind: 'needs-more' } // only when truncated === true: the header may continue past the bytes given
  | { readonly kind: 'rejected'; readonly reason: string }; // DICOM but no Study/SeriesInstanceUID, or no header within the read cap

export interface SeriesNode {
  readonly key: SeriesKey;
  readonly uid: string;
  readonly number: number | null;
  readonly description: string;
  readonly modality: string;
  /** Sorted: InstanceNumber, EchoNumber, relPath (missing last). */
  readonly instances: readonly Instance[];
  /** Sum of `source.size`. */
  readonly bytes: number;
  /** Window of the first sorted instance that has one. */
  readonly window: WindowLevel | null;
}

export interface StudyNode {
  readonly uid: string;
  readonly date: string | null;
  readonly time: string | null;
  readonly description: string;
  readonly accessionNumber: string;
  readonly series: readonly SeriesNode[];
}

export interface PatientNode {
  /**
   * Identity of the patient in the tree: the trimmed PatientID, or, for a blank
   * PatientID, the trimmed PatientName. Opaque; unique per patient.
   */
  readonly groupKey: string;
  /** Trimmed PatientID, or 'UNKNOWN' when blank. */
  readonly id: string;
  readonly name: string;
  readonly studies: readonly StudyNode[];
}

export interface TreeResult {
  readonly patients: readonly PatientNode[];
  /** Instances dropped because their SOPInstanceUID repeated within a series. */
  readonly duplicates: readonly Instance[];
}
