import { Inflate } from 'fflate';
import * as dicomParser from 'dicom-parser';
import { charsetFor, decodeText } from './charset';
import type { Charset } from './charset';
import { sniffDicom } from './sniff';
import { hasZipMagic } from './zipdir';
import type { DicomKind } from './sniff';
import type { HeaderOutcome, Instance, Source as InstanceSource, WindowLevel } from './types';

/** Bytes read from the front of each file in the first pass. */
export const HEADER_BYTES = 64 * 1024;
/** Second pass, for files whose header runs past {@link HEADER_BYTES}. */
export const ESCALATED_BYTES = 1024 * 1024;
/** Third pass: files up to this size may be read whole to find their header; larger ones never are. */
export const WHOLE_FILE_MAX = 64 * 1024 * 1024;
/** Most inflated bytes of a deflated dataset that are ever held (we only need the header). */
export const INFLATE_CAP = 4 * 1024 * 1024;

const UNDEFINED_LENGTH = 0xffffffff;
const DICOMDIR_SOP_CLASS = '1.2.840.10008.1.3.10';
const IMPLICIT_LE = '1.2.840.10008.1.2';
export const EXPLICIT_LE = '1.2.840.10008.1.2.1';
export const DEFLATED_LE = '1.2.840.10008.1.2.1.99';

/** dicom-parser tag keys: `x` + 8 lower-case hex digits. */
const T = {
  pixelData: 'x7fe00010',
  mediaStorageSopClass: 'x00020002',
  transferSyntax: 'x00020010',
  specificCharacterSet: 'x00080005',
  studyDate: 'x00080020',
  studyTime: 'x00080030',
  sopInstanceUid: 'x00080018',
  accessionNumber: 'x00080050',
  modality: 'x00080060',
  studyDescription: 'x00081030',
  seriesDescription: 'x0008103e',
  patientName: 'x00100010',
  patientId: 'x00100020',
  studyUid: 'x0020000d',
  seriesUid: 'x0020000e',
  seriesNumber: 'x00200011',
  instanceNumber: 'x00200013',
  echoNumbers: 'x00180086',
  numberOfFrames: 'x00280008',
  windowCenter: 'x00281050',
  windowWidth: 'x00281051',
} as const;

const NOT_DICOM: HeaderOutcome = { kind: 'skipped', reason: 'not-dicom' };
const NEEDS_MORE: HeaderOutcome = { kind: 'needs-more' };

/**
 * Highest tag we read from the dataset (PixelData excluded). dicom-parser
 * records an element only after walking past every earlier one and tags
 * ascend, so once any top-level element beyond this tag has been recorded
 * (before FFFE,0000 items/delimiters), everything wanted has been seen, with
 * or without PixelData and whatever follows (private blocks, SR content,
 * 64-bit VRs dicom-parser cannot parse).
 */
const LAST_WANTED = Object.entries(T)
  .filter(([name]) => name !== 'pixelData')
  .map(([, tag]) => tag as string)
  .reduce((a, b) => (a > b ? a : b));

/** A raw (headerless) file must carry at least one of these, else it is noise. */
const RAW_IDENTITY_TAGS = ['x00080016', 'x00080018', 'x0020000d', 'x0020000e', 'x00080060'];

// ---------------------------------------------------------------------------
// Reading elements out of a parsed dataset

/**
 * A parsed dataset: element table plus the byte array its `dataOffset`s refer to.
 * That array is NOT always the input: for Deflated Explicit VR LE it is the
 * inflated dataset, while file meta (group 0002) elements keep offsets into the input.
 * So meta and dataset are read as separate Datasets.
 */
export interface Dataset {
  readonly bytes: Uint8Array;
  readonly elements: Readonly<Record<string, dicomParser.Element | undefined>>;
}

/**
 * dicom-parser does not bounds-check the value of an element cut off by the end
 * of the buffer (implicit VR returns silently, explicit throws "buffer overrun"
 * but keeps the element). Such an element, or one of undefined length, has no
 * usable value.
 */
export const rawValue = (src: Dataset, tag: string): Uint8Array | null => {
  const el = src.elements[tag];
  if (el === undefined || el.length === UNDEFINED_LENGTH) return null;
  const end = el.dataOffset + el.length;
  return end <= src.bytes.length ? src.bytes.subarray(el.dataOffset, end) : null;
};

const isPadding = (b: number): boolean => b === 0x20 || b === 0x00;

const trimPadding = (b: Uint8Array): Uint8Array => {
  let end = b.length;
  while (end > 0 && isPadding(b[end - 1]!)) end--;
  return b.subarray(0, end);
};

const latin1 = new TextDecoder('latin1');

/** Code-like value (UI, CS, DA, TM, IS, DS): ASCII, surrounding spaces/NULs dropped. Absent or blank -> null. */
const code = (src: Dataset, tag: string): string | null => {
  const v = rawValue(src, tag);
  if (v === null) return null;
  const s = latin1.decode(v).replace(/^[\s\0]+|[\s\0]+$/g, '');
  return s === '' ? null : s;
};

/** Free text (PN, LO, SH, ST) in the dataset's charset: trailing padding dropped, `^` kept. Absent -> ''. */
const text = (src: Dataset, tag: string, charset: Charset): string => {
  const v = rawValue(src, tag);
  return v === null ? '' : decodeText(trimPadding(v), charset);
};

/**
 * PN: only the first component group (before the first `=`) is kept, falling
 * back to the first non-empty one, so `Yamada^Tarou=山田^太郎` is `Yamada^Tarou`
 * and ideographic / phonetic groups (and any ISO 2022 escapes in them) never
 * leak. The split is on raw bytes, before decoding. Trailing `^` separators
 * are dropped (`Doe^Jane^^^` is `Doe^Jane`; `^^^^` is empty).
 */
const personName = (src: Dataset, tag: string, charset: Charset): string => {
  const v = rawValue(src, tag);
  if (v === null) return '';
  const groups: Uint8Array[] = [];
  let start = 0;
  for (let i = 0; i <= v.length; i++) {
    if (i === v.length || v[i] === 0x3d) {
      groups.push(v.subarray(start, i));
      start = i + 1;
    }
  }
  for (const g of groups) {
    const name = decodeText(trimPadding(g), charset).replace(/[\^ \0]+$/, '');
    if (name !== '') return name;
  }
  return '';
};

const NUMBER = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/;

/** First value of a `\` list as a finite number (IS/DS grammar). Anything else -> null, never NaN. */
const firstNumber = (src: Dataset, tag: string): number | null => {
  const first = code(src, tag)?.split('\\')[0]?.trim();
  if (first === undefined || !NUMBER.test(first)) return null;
  const n = Number(first);
  return Number.isFinite(n) ? n : null;
};

const firstInteger = (src: Dataset, tag: string): number | null => {
  const n = firstNumber(src, tag);
  return n !== null && Number.isSafeInteger(n) ? n : null;
};

/** Far above any real multi-frame object (cine and tomosynthesis run to thousands); beyond it the tag is corrupt. */
const MAX_FRAMES = 100_000;

/** A frame count such as NumberOfFrames (IS): a whole number 1..MAX_FRAMES, else 1 (absent, 0, negative, fractional, garbage, absurd). */
export const frameCount = (src: Dataset, tag: string): number => {
  const s = code(src, tag)?.trim();
  if (s === undefined || !/^\+?\d+$/.test(s)) return 1;
  const n = Number(s);
  return n >= 1 && n <= MAX_FRAMES ? n : 1;
};

/** DA: exactly 8 digits (`YYYYMMDD`); the legacy `YYYY.MM.DD` form and anything else -> null. */
const date = (src: Dataset, tag: string): string | null => {
  const s = code(src, tag);
  return s !== null && /^\d{8}$/.test(s) ? s : null;
};

/** TM: `HH[MM[SS[.ffffff]]]`; anything else -> null. */
const time = (src: Dataset, tag: string): string | null => {
  const s = code(src, tag);
  return s !== null && /^\d{2}(?:\d{2}(?:\d{2}(?:\.\d{1,6})?)?)?$/.test(s) ? s : null;
};

const windowLevel = (src: Dataset): WindowLevel | null => {
  const center = firstNumber(src, T.windowCenter);
  const width = firstNumber(src, T.windowWidth);
  // DICOM requires WindowWidth >= 1 (consumers divide by width - 1).
  return center !== null && width !== null && width >= 1 ? { center, width } : null;
};

// ---------------------------------------------------------------------------
// Driving dicom-parser

const INFLATE_CHUNK = 16 * 1024;

/**
 * Inflate raw deflate data from `input`, stopping once `cap` output bytes exist
 * or the input runs out. Input is pushed in small chunks so that a deflate bomb
 * costs at most `INFLATE_CHUNK` x ~1000 bytes of transient output before we
 * stop. A cut or corrupt stream is not an error: whatever was produced is kept.
 * Returns null if nothing was produced; `capped` says output hit the cap (the
 * result is then exactly `cap` bytes).
 */
export const boundedInflate = (
  input: Uint8Array,
  cap: number = INFLATE_CAP,
): { readonly bytes: Uint8Array; readonly capped: boolean } | null => {
  const chunks: Uint8Array[] = [];
  let total = 0;
  const inflate = new Inflate((chunk) => {
    chunks.push(chunk);
    total += chunk.length;
  });
  try {
    for (let at = 0; at < input.length && total < cap; at += INFLATE_CHUNK) {
      const end = Math.min(at + INFLATE_CHUNK, input.length);
      inflate.push(input.subarray(at, end), end === input.length);
    }
  } catch {
    // corrupt or cut stream: keep what was produced
  }
  if (total === 0) return null;
  const out = new Uint8Array(Math.min(total, cap));
  let at = 0;
  for (const c of chunks) {
    if (at >= out.length) break;
    const part = c.subarray(0, out.length - at);
    out.set(part, at);
    at += part.length;
  }
  return { bytes: out, capped: total >= cap };
};

/**
 * `inflater` receives the WHOLE input and the offset where the deflated data
 * starts (end of file meta; undefined when the transfer syntax was supplied
 * rather than read), and must return ONLY the inflated dataset (the parser then
 * reads it from index 0). dicom-parser's d.ts types the callback as returning
 * void but uses the return value, hence the cast. Passing it also stops
 * dicom-parser from reaching `require('zlib')`.
 */
const makeInflater =
  (state: { capped: boolean }): NonNullable<dicomParser.ParseDicomOptions['inflater']> =>
  (arr, position) => {
    const r = boundedInflate(arr.subarray(position || 0));
    if (r === null) throw new Error('nothing could be inflated');
    state.capped = r.capped;
    return r.bytes as unknown as void;
  };

const isFailureWithDataSet = (e: unknown): e is { dataSet: dicomParser.DataSet } =>
  typeof e === 'object' && e !== null && 'dataSet' in e && typeof (e as { dataSet: unknown }).dataSet === 'object';

const asSource = (ds: dicomParser.DataSet): Dataset => ({ bytes: ds.byteArray, elements: ds.elements });

/** Group 0002 elements, read by dicom-parser's own meta reader, plus where the dataset starts. Null if unreadable. */
interface Meta extends Dataset {
  readonly position: number;
}
const readMeta = (bytes: Uint8Array): Meta | null => {
  try {
    const ds = dicomParser.readPart10Header(bytes);
    return { ...asSource(ds), position: (ds as unknown as { position: number }).position };
  } catch {
    return null;
  }
};

/** The transfer syntax as dicom-parser compares it: the value up to the first NUL, spaces kept. */
const transferSyntaxAsParsed = (meta: Meta): string | null => {
  const v = rawValue(meta, T.transferSyntax);
  return v === null ? null : latin1.decode(v).split('\0')[0]!;
};

interface DataSetRead {
  readonly source: Dataset | null;
  /** The (deflated) dataset was cut at INFLATE_CAP: more input would not help. */
  readonly capped: boolean;
}

/**
 * The dataset up to (and including the header of) PixelData. `suppliedSyntax`
 * is given for headerless data (no meta header in `bytes`); null for Part 10.
 * On a parse error the partial dataset attached to dicom-parser's exception is
 * used; null source if there is none (corrupt meta, failed inflate, ...).
 */
const readDataSet = (bytes: Uint8Array, suppliedSyntax: string | null): DataSetRead => {
  const state = { capped: false };
  const options: dicomParser.ParseDicomOptions = {
    untilTag: T.pixelData,
    inflater: makeInflater(state),
    ...(suppliedSyntax !== null && { TransferSyntaxUID: suppliedSyntax }),
  };
  try {
    return { source: asSource(dicomParser.parseDicom(bytes, options)), capped: state.capped };
  } catch (e) {
    return { source: isFailureWithDataSet(e) ? asSource(e.dataSet) : null, capped: state.capped };
  }
};

/** Complete once any top-level element after everything we read has been recorded. See {@link LAST_WANTED}. */
const headerComplete = (data: Dataset): boolean =>
  Object.keys(data.elements).some((k) => k > LAST_WANTED && k < 'xfffe0000');

export const withPreamble = (bytes: Uint8Array): Uint8Array => {
  const out = new Uint8Array(132 + bytes.length);
  out.set([0x44, 0x49, 0x43, 0x4d], 128);
  out.set(bytes, 132);
  return out;
};

// ---------------------------------------------------------------------------
// The boundary

/**
 * The only place raw DICOM bytes become an {@link Instance}. Pure and total
 * (never throws); `opts.source` is only carried through.
 *
 * `bytes` is a prefix of the file when `truncated`, else the whole file. When
 * truncated and the header may extend past the prefix the result is
 * `needs-more`; call again with a longer prefix (see {@link readOutcome}).
 *
 * - Not DICOM: skipped / not-dicom. Headerless data must sniff as a plausible
 *   dataset AND carry one of the identity tags, else it is noise (never escalated).
 *   A headerless file starting with the meta group is parsed as Part 10.
 * - Part 10 with an unreadable meta header or no dataset: not-dicom (needs-more
 *   if truncated and deflated, since the prefix may end before any output).
 * - MediaStorageSOPClassUID = Media Storage Directory: skipped / dicomdir.
 * - Truncated and the header may continue (see {@link headerComplete}): needs-more.
 * - Otherwise a missing Study or Series Instance UID: rejected.
 * - Text is decoded per SpecificCharacterSet and stripped of trailing padding;
 *   absent text is ''. Numbers are strictly parsed (else null); DA must be 8
 *   digits; the window needs both center and width >= 1.
 */
export const parseHeader = (
  bytes: Uint8Array,
  opts: { readonly source: InstanceSource; readonly relPath: string; readonly truncated: boolean },
): HeaderOutcome => {
  const kind = sniffDicom(bytes);
  if (kind === 'not-dicom') return NOT_DICOM;
  if (kind === 'raw-meta') return parseHeader(withPreamble(bytes), opts);

  let meta: Meta | null = null;
  let transferSyntax: string | null = null;
  let read: DataSetRead;
  if (kind === 'part10') {
    meta = readMeta(bytes);
    if (meta === null) return NOT_DICOM;
    if (code(meta, T.mediaStorageSopClass) === DICOMDIR_SOP_CLASS) return { kind: 'skipped', reason: 'dicomdir' };
    transferSyntax = code(meta, T.transferSyntax);
    // A padded UID (`1.2.840.10008.1.2 `) would defeat dicom-parser's exact comparisons:
    // parse the dataset part as headerless data with the trimmed syntax instead.
    read =
      transferSyntax !== null && transferSyntax !== transferSyntaxAsParsed(meta)
        ? readDataSet(bytes.subarray(meta.position), transferSyntax)
        : readDataSet(bytes, null);
  } else {
    read = readDataSet(bytes, kind === 'raw-explicit-le' ? EXPLICIT_LE : IMPLICIT_LE);
  }

  const data = read.source;
  if (data === null) return opts.truncated && transferSyntax === DEFLATED_LE ? NEEDS_MORE : NOT_DICOM;
  if (meta === null && !RAW_IDENTITY_TAGS.some((t) => data.elements[t] !== undefined)) return NOT_DICOM;
  // When the inflated output was capped, more input would inflate to the same bytes: use what we have.
  if (opts.truncated && !read.capped && !headerComplete(data)) return NEEDS_MORE;

  const studyUid = code(data, T.studyUid);
  const seriesUid = code(data, T.seriesUid);
  if (studyUid === null || seriesUid === null) {
    const missing = [studyUid === null && 'StudyInstanceUID', seriesUid === null && 'SeriesInstanceUID'].filter(
      (m): m is string => m !== false,
    );
    return { kind: 'rejected', reason: `missing ${missing.join(' and ')}` };
  }

  const charset = charsetFor(code(data, T.specificCharacterSet));
  const instance: Instance = {
    source: opts.source,
    relPath: opts.relPath,
    sopInstanceUid: code(data, T.sopInstanceUid),
    transferSyntax,
    patient: { id: text(data, T.patientId, charset), name: personName(data, T.patientName, charset) },
    study: {
      uid: studyUid,
      date: date(data, T.studyDate),
      time: time(data, T.studyTime),
      description: text(data, T.studyDescription, charset),
      accessionNumber: text(data, T.accessionNumber, charset),
    },
    series: {
      uid: seriesUid,
      number: firstInteger(data, T.seriesNumber),
      description: text(data, T.seriesDescription, charset),
      modality: code(data, T.modality) ?? '',
    },
    instanceNumber: firstInteger(data, T.instanceNumber),
    echoNumber: firstInteger(data, T.echoNumbers),
    frames: frameCount(data, T.numberOfFrames),
    window: windowLevel(data),
  };
  return { kind: 'instance', instance };
};

/**
 * The dataset up to PixelData, for readers that need elements {@link parseHeader}
 * does not (overlay planes, ...). Same layout dispatch as parseHeader, without its
 * identity, DICOMDIR and needs-more checks; keep the two in step. Null when the
 * bytes are not DICOM or no dataset could be read. `transferSyntax` is the
 * syntax the dataset was parsed with: from the meta header for Part 10 (null if
 * absent), the sniffed one for headerless data. A Deflated Explicit VR LE
 * dataset is inflated only up to {@link INFLATE_CAP} (4 MiB) and elements past
 * that are missing: a caller holding the inflated bytes should pass those
 * instead (e.g. inflateDeflatedFile's Part 10 output, its meta header rewritten
 * to Explicit VR LE, or the bare dataset). Pure and total.
 */
export const parseDataset = (
  bytes: Uint8Array,
): { readonly source: Dataset; readonly transferSyntax: string | null } | null => {
  const kind = sniffDicom(bytes);
  if (kind === 'not-dicom') return null;
  if (kind === 'raw-meta') return parseDataset(withPreamble(bytes));
  if (kind === 'part10') {
    const meta = readMeta(bytes);
    if (meta === null) return null;
    const transferSyntax = code(meta, T.transferSyntax);
    const read =
      transferSyntax !== null && transferSyntax !== transferSyntaxAsParsed(meta)
        ? readDataSet(bytes.subarray(meta.position), transferSyntax)
        : readDataSet(bytes, null);
    return read.source === null ? null : { source: read.source, transferSyntax };
  }
  const transferSyntax = kind === 'raw-explicit-le' ? EXPLICIT_LE : IMPLICIT_LE;
  const read = readDataSet(bytes, transferSyntax);
  return read.source === null ? null : { source: read.source, transferSyntax };
};

/** Shown for a non-DICOM file that starts like a ZIP archive: only files named `.zip` are opened as archives. */
export const ZIP_NOT_OPENED = 'looks like a ZIP archive (only files named .zip are opened)';

const mib = (n: number): string => `${n / (1024 * 1024)} MB`;

/**
 * The bounded multi-pass read policy. `readPrefix(n)` returns the first `n`
 * bytes of the source (the shell backs it with `source.readPrefix(n)`, adding a
 * memory budget); core never touches file contents.
 *
 * Passes: {@link HEADER_BYTES}, then {@link ESCALATED_BYTES}, then the whole
 * file only if it is at most {@link WHOLE_FILE_MAX}; a pass is skipped when the
 * previous one already covered the file. Each pass runs only if the previous
 * said `needs-more`. If the header is still not found, the outcome is
 * `rejected` ("header not found in first N MB"), so no file is ever read whole
 * above the cap.
 *
 * Never rejects. If a read fails the outcome is `skipped/unreadable` with the
 * error message. (A later pass only runs after `needs-more`, which is never a
 * usable result, so there is no earlier outcome worth keeping.)
 */
export const readOutcome = async (
  source: InstanceSource,
  relPath: string,
  readPrefix: (length: number) => Promise<Uint8Array>,
): Promise<HeaderOutcome> => {
  const size = source.size;
  const passes = [HEADER_BYTES, ESCALATED_BYTES, ...(size <= WHOLE_FILE_MAX ? [size] : [])]
    .map((n) => Math.min(n, size))
    .filter((n, i, all) => i === 0 || n > all[i - 1]!);
  for (const length of passes) {
    let bytes: Uint8Array;
    try {
      bytes = await readPrefix(length);
    } catch (e) {
      return { kind: 'skipped', reason: 'unreadable', detail: e instanceof Error ? e.message : String(e) };
    }
    const out = parseHeader(bytes, { source, relPath, truncated: length < size });
    if (out.kind === 'skipped' && out.reason === 'not-dicom' && hasZipMagic(bytes)) return { ...out, detail: ZIP_NOT_OPENED };
    if (out.kind !== 'needs-more') return out;
  }
  return { kind: 'rejected', reason: `header not found in first ${mib(passes.at(-1)!)}` };
};
