/// <reference lib="webworker" />
/**
 * The Pyodide worker: a classic (iife) worker from a blob URL (`?worker&inline`), long-lived, one per page.
 *
 * `boot` carries every embedded asset as base64. The worker decodes them, serves them to Pyodide through a `fetch` shim
 * that refuses everything else, starts Pyodide, loads the Pyodide packages from the vendored lock file, unpacks nibabel
 * and the workspace wheels into site-packages (no resolver: scripts/web_vendor.py checked their requirements), imports
 * `fmriqa_web.bridge` and posts `ready` with `contract_json()`. Then each `call` runs one bridge function; its JSON
 * string is posted verbatim. See web/README.md, "Boot path", for how pyodide.asm.mjs is loaded.
 */
import './classic-worker-probe'; // first: before Pyodide's module body probes the worker type
import { loadPyodide, type PyodideAPI } from 'pyodide';
// Bundled into this worker, rewritten for a classic script (scripts/vite-pyodide.mjs, classicPyodideAsm).
import createPyodideModule from 'pyodide/pyodide.asm.mjs';
import type { PyCallable, PyProxy } from 'pyodide/ffi';
import { decodeBase64, type AssetKind, type EncodedAsset } from '../core/assets';
import { ASSET_BASE, contentType, routeFetch } from '../core/asset-fetch';
import { isToWorker, type BootStage, type FromWorker, type ToWorker } from './pyodide-protocol';

declare const self: DedicatedWorkerGlobalScope;

const post = (message: FromWorker): void => self.postMessage(message);

const errorMessage = (e: unknown, id?: number): FromWorker => {
  const base = { type: 'error' as const, message: e instanceof Error ? e.message : String(e) };
  const stack = e instanceof Error && e.stack ? { stack: e.stack } : {};
  return { ...base, ...stack, ...(id === undefined ? {} : { id }) };
};

self.addEventListener('securitypolicyviolation', (e) => {
  const v = e as SecurityPolicyViolationEvent;
  post({ type: 'violation', directive: v.effectiveDirective, blocked: v.blockedURI });
});

/** Gunzip without a Blob: WebKit cannot read a Blob inside a worker on file:// (NotReadableError). */
const gunzip = async (bytes: Uint8Array<ArrayBuffer>): Promise<Uint8Array<ArrayBuffer>> => {
  const source = new ReadableStream<Uint8Array<ArrayBuffer>>({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
  return new Uint8Array(await new Response(source.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer());
};

interface DecodedAsset {
  readonly name: string;
  readonly kind: AssetKind;
}

/**
 * Decode every asset. This is the only holder of the base64 text (tens of megabytes): the boot gets only the names,
 * kinds and bytes, so the strings can be collected once this returns.
 */
const decodeAssets = async (
  encoded: readonly EncodedAsset[],
): Promise<{ assets: DecodedAsset[]; files: Map<string, Uint8Array<ArrayBuffer>> }> => {
  const files = new Map<string, Uint8Array<ArrayBuffer>>();
  for (const asset of encoded) {
    const raw = decodeBase64(asset.base64) as Uint8Array<ArrayBuffer>;
    files.set(asset.name, asset.gzip ? await gunzip(raw) : raw);
  }
  return { assets: encoded.map(({ name, kind }) => ({ name, kind })), files };
};

/**
 * Serve `files` by name to every fetch in this worker; refuse (and report) anything else. `files` is read on each
 * request, so once the boot empties it every fetch is refused and reported.
 */
const installFetchShim = (files: ReadonlyMap<string, Uint8Array<ArrayBuffer>>): void => {
  self.fetch = async (input: RequestInfo | URL): Promise<Response> => {
    const url = input instanceof Request ? input.url : String(input);
    const route = routeFetch(url, files);
    const bytes = route.kind === 'asset' ? files.get(route.name) : undefined;
    if (route.kind === 'refused' || bytes === undefined) {
      post({ type: 'refused', url });
      throw new TypeError(`offline page: refusing to fetch ${url}`);
    }
    return new Response(bytes, { status: 200, headers: { 'Content-Type': contentType(route.name) } });
  };
};

/** Python that imports what the first call needs, so it is warm: fmriqa's root is lazy (PEP 562). */
const WARM_UP = `
import fmriqa_web.bridge
import fmriqa
fmriqa.analyze
fmriqa.AnalysisSettings
`;

/** A distribution name normalized as PEP 503 does (`Lazy_Loader` and `lazy-loader` are one name). */
const normalize = (name: string): string => name.toLowerCase().replace(/[-_.]+/g, '-');

/** Load every package in `names`; throw naming each that did not load (`loadPackage` itself never rejects). */
const loadPackages = async (pyodide: PyodideAPI, names: readonly string[]): Promise<void> => {
  const errors: string[] = [];
  await pyodide.loadPackage([...names], { messageCallback: () => {}, errorCallback: (m) => errors.push(m) });
  // `loadedPackages` keys are distribution names as the wheel spells them (`Pillow`, `lazy_loader`): compare normalized.
  const loaded = new Set(Object.keys(pyodide.loadedPackages).map(normalize));
  const missing = names.filter((name) => !loaded.has(normalize(name)));
  if (missing.length > 0 || errors.length > 0) {
    throw new Error(`Pyodide packages did not load: ${missing.join(', ') || '(none missing)'}. ${errors.join(' ')}`);
  }
};

let bridge: PyProxy | undefined;
let py: PyodideAPI | undefined;

const boot = async (decoding: ReturnType<typeof decodeAssets>): Promise<void> => {
  const t0 = performance.now();
  const stage = (name: BootStage): void => post({ type: 'stage', name, elapsedMs: performance.now() - t0 });

  const { assets, files } = await decoding;
  const take = (name: string): Uint8Array<ArrayBuffer> => {
    const bytes = files.get(name);
    if (!bytes) throw new Error(`${name} is missing from this page`);
    return bytes;
  };
  const lockText = new TextDecoder().decode(take('pyodide-lock.json'));
  installFetchShim(files);
  stage('decode');

  const pyodide = await loadPyodide({
    indexURL: ASSET_BASE,
    packageBaseUrl: ASSET_BASE,
    lockFileContents: lockText,
    createPyodideModule,
    // Before any Python import: matplotlib must never look for a display backend.
    env: { MPLBACKEND: 'Agg', HOME: '/home/pyodide' },
    // `analyze_json(nifti, null, stem)` must see None, not `jsnull`.
    convertNullToNone: true,
  });
  stage('runtime');

  // Every Pyodide package the page carries, by its lock-file name (the vendored set is the closure fmri-qa needs).
  const lock = JSON.parse(lockText) as { packages: Record<string, { file_name: string }> };
  const byFile = new Map(Object.entries(lock.packages).map(([name, p]) => [p.file_name, name]));
  const packageNames = assets
    .filter((a) => a.kind === 'pyodide-package')
    .map((a) => {
      const name = byFile.get(a.name);
      if (name === undefined) throw new Error(`${a.name} is not in pyodide-lock.json`);
      return name;
    });
  await loadPackages(pyodide, packageNames);
  stage('packages');

  // Into site-packages, where loadPackage puts the Pyodide packages: the default (the working directory) is importable
  // only while it stays the working directory, and importlib.metadata would find the wheels' versions only there.
  const sitePackages = pyodide.runPython("import sysconfig; sysconfig.get_path('purelib')") as unknown;
  if (typeof sitePackages !== 'string') throw new Error('Pyodide reported no site-packages directory');
  for (const asset of assets) if (asset.kind === 'wheel') pyodide.unpackArchive(take(asset.name), 'whl', { extractDir: sitePackages });
  stage('wheels');

  pyodide.runPython(WARM_UP);
  const module = pyodide.pyimport('fmriqa_web.bridge');
  const contract = (module['contract_json'] as PyCallable)() as unknown;
  if (typeof contract !== 'string') throw new Error(`contract_json returned ${typeof contract}`);
  stage('import');

  files.clear(); // the boot is the only reader; the shim refuses every later fetch
  [py, bridge] = [pyodide, module];
  stage('ready');
  post({ type: 'ready', contract });
};

const call = (message: Extract<ToWorker, { type: 'call' }>): void => {
  const [pyodide, module] = [py, bridge];
  if (!pyodide || !module) {
    post({ type: 'error', id: message.id, message: 'Python is not ready' });
    return;
  }
  const args: unknown[] = [];
  try {
    for (const a of message.args) args.push(pyodide.toPy(a));
    const value = (module[message.fn] as PyCallable)(...args) as unknown;
    if (typeof value !== 'string') throw new Error(`${message.fn} returned ${typeof value}, not a string`);
    post({ type: 'result', id: message.id, value });
  } catch (e) {
    post(errorMessage(e, message.id));
  } finally {
    for (const a of args) if (a instanceof pyodide.ffi.PyProxy) a.destroy();
  }
};

/** The `id` of a message that failed the guard, when it has a usable one, so only that call fails. */
const idOf = (x: unknown): number | undefined => {
  const id = typeof x === 'object' && x !== null ? (x as Record<string, unknown>)['id'] : undefined;
  return Number.isSafeInteger(id) ? (id as number) : undefined;
};

let booted = false;
self.addEventListener('message', (e: MessageEvent<unknown>) => {
  const message = e.data;
  if (!isToWorker(message)) {
    post(errorMessage(new Error('the Python worker received a message it does not understand'), idOf(message)));
    return;
  }
  if (message.type === 'call') {
    call(message);
    return;
  }
  if (booted) {
    post({ type: 'error', message: 'the Python worker was booted twice' });
    return;
  }
  booted = true;
  boot(decodeAssets(message.assets)).catch((err: unknown) => post(errorMessage(err)));
});
