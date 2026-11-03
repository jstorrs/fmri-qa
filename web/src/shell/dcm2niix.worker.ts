import Module from '@dcm2niix-glue';
import type { Dcm2niixFS } from '@dcm2niix-glue';
import { IN_DIR, OUT_DIR, dcm2niixArgv } from '../core/convert-args';
import { friendlyError, isWasmCrash } from '../core/dcm2niix';
import { isToWorker } from './dcm2niix-protocol';
import type { FromWorker, LogStream, WorkerFile } from './dcm2niix-protocol';

// One conversion per worker: the runner creates a fresh worker per call and terminates it afterwards. The glue only
// runs `main` when `callMain` is called (it never auto-runs), so `noInitialRun` is not needed.
const scope = self as unknown as { postMessage(m: FromWorker, transfer: Transferable[]): void; onmessage: ((e: MessageEvent) => void) | null };
const post = (m: FromWorker, transfer: Transferable[] = []): void => scope.postMessage(m, transfer);
const say = (stream: LogStream) => (line: string): void => post({ type: 'log', line, stream });

const messageOf = (e: unknown): string => (e instanceof Error ? e.message : String(e));

let started = false;

/** FS.readFile returns a fresh, exactly sized array (not a view of the wasm heap), so its buffer can be transferred. */
const exactBuffer = (bytes: Uint8Array): ArrayBuffer =>
  bytes.byteOffset === 0 && bytes.byteLength === bytes.buffer.byteLength ? (bytes.buffer as ArrayBuffer) : (bytes.slice().buffer as ArrayBuffer);

/** Regular files under `dir`, as paths relative to `root` (`sub/name`), skipping dotfiles. */
const listFiles = (fs: Dcm2niixFS, root: string, dir = ''): string[] =>
  fs
    .readdir(dir === '' ? root : `${root}/${dir}`)
    .filter((n) => !n.startsWith('.'))
    .flatMap((n) => {
      const rel = dir === '' ? n : `${dir}/${n}`;
      return fs.isDir(fs.stat(`${root}/${rel}`).mode) ? listFiles(fs, root, rel) : [rel];
    });

const run = async (args: readonly string[], inputs: WorkerFile[], wasm: ArrayBuffer): Promise<void> => {
  const mod = await Module({ print: say('stdout'), printErr: say('stderr'), wasmBinary: wasm });
  const fs = mod.FS;
  fs.mkdir(IN_DIR);
  fs.mkdir(OUT_DIR);
  const names: string[] = [];
  // Hand each buffer to the FS (canOwn: no second copy) and drop our reference as we go.
  for (let f = inputs.shift(); f !== undefined; f = inputs.shift()) {
    fs.writeFile(`${IN_DIR}/${f.name}`, new Uint8Array(f.buf), { canOwn: true });
    names.push(f.name);
  }

  let exitCode: number;
  try {
    exitCode = mod.callMain(dcm2niixArgv(args));
  } catch (e) {
    const status = typeof e === 'object' && e !== null && 'status' in e ? (e as { status: unknown }).status : undefined;
    if (typeof status !== 'number') throw e;
    exitCode = status;
  }
  for (const n of names) fs.unlink(`${IN_DIR}/${n}`); // free the inputs before the outputs are copied out

  const outputs: WorkerFile[] = listFiles(fs, OUT_DIR).map((name) => {
    const buf = exactBuffer(fs.readFile(`${OUT_DIR}/${name}`));
    fs.unlink(`${OUT_DIR}/${name}`);
    return { name, buf };
  });
  post({ type: 'done', exitCode, outputs }, outputs.map((o) => o.buf));
};

scope.onmessage = (e: MessageEvent) => {
  const msg: unknown = e.data;
  if (!isToWorker(msg)) return post({ type: 'error', message: 'Unexpected message sent to the dcm2niix worker.' });
  if (started) return post({ type: 'error', message: 'This dcm2niix worker was already used.' });
  started = true;
  // `msg.inputs` is emptied by `run`, so nothing here keeps the input buffers alive.
  run(msg.args, msg.inputs as WorkerFile[], msg.wasm).catch((err: unknown) => {
    const raw = messageOf(err);
    if (isWasmCrash(raw)) say('stderr')(raw); // keep the raw text in the log
    post({ type: 'error', message: friendlyError(raw) });
  });
};
