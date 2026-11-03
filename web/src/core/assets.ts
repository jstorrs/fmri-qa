/**
 * The files the page embeds for Pyodide: what an inert `<script type="application/octet-stream">` block carries
 * (scripts/vite-pyodide.mjs writes them from web/vendor/manifest.json), parsed once into a typed record. Pure.
 */

/** As in web/vendor/manifest.json: Pyodide's runtime, a package from its lock file, or a wheel unpacked as-is. */
export type AssetKind = 'pyodide-core' | 'pyodide-package' | 'wheel';

const KINDS: readonly AssetKind[] = ['pyodide-core', 'pyodide-package', 'wheel'];

/** An embedded asset still in transit: base64 text, gzipped first when `gzip`. */
export interface EncodedAsset {
  /** The bare file name Pyodide requests it by (e.g. `pyodide.asm.wasm`, a wheel's file name). */
  readonly name: string;
  readonly kind: AssetKind;
  readonly gzip: boolean;
  readonly base64: string;
}

/** A bare file name: no directory, no leading dot, nothing a URL would need escaping for. */
const NAME = /^[A-Za-z0-9_+-][A-Za-z0-9._+-]*$/;

export const isAssetName = (x: unknown): x is string => typeof x === 'string' && NAME.test(x);

const isKind = (x: unknown): x is AssetKind => KINDS.includes(x as AssetKind);

/** What an inert block's `data-*` attributes hold (an element's `dataset`). */
export interface AssetAttributes {
  readonly name?: string | undefined;
  readonly kind?: string | undefined;
  readonly gz?: string | undefined;
}

/** Parse one block: its `dataset` and text. Throws naming the block when an attribute is wrong. */
export const parseEncodedAsset = (data: AssetAttributes, text: string): EncodedAsset => {
  const { name, kind, gz } = data;
  if (!isAssetName(name)) throw new Error(`embedded asset with a bad name: ${JSON.stringify(name)}`);
  if (!isKind(kind)) throw new Error(`embedded asset ${name} has kind ${JSON.stringify(kind)}`);
  if (gz !== undefined && gz !== '1') throw new Error(`embedded asset ${name} has data-gz=${JSON.stringify(gz)}`);
  if (text.length === 0) throw new Error(`embedded asset ${name} is empty`);
  return { name, kind, gzip: gz === '1', base64: text };
};

export const isEncodedAsset = (x: unknown): x is EncodedAsset => {
  if (typeof x !== 'object' || x === null) return false;
  const r = x as Record<string, unknown>;
  return isAssetName(r['name']) && isKind(r['kind']) && typeof r['gzip'] === 'boolean' && typeof r['base64'] === 'string';
};

interface Base64Decoder {
  fromBase64?: (s: string) => Uint8Array;
}

/** Decode base64: `Uint8Array.fromBase64` where the browser has it, else an `atob` loop. Throws on bad input. */
export const decodeBase64 = (s: string): Uint8Array => {
  const native = (Uint8Array as Base64Decoder).fromBase64;
  if (native) return native(s);
  const binary = atob(s);
  const out = new Uint8Array(binary.length);
  // A plain loop: Uint8Array.from(binary, mapFn) is several times slower on tens of megabytes.
  for (let i = 0; i < binary.length; i++) out[i] = binary.charCodeAt(i);
  return out;
};
