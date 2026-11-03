/**
 * dcm2niix's WebAssembly, read out of the page. scripts/vite-dcm2niix.mjs embeds it as one inert, gzipped, base64
 * block (`#dcm2niix-wasm`); this decodes it once, on first use, and keeps the bytes. The block is removed once read.
 */
import { decodeBase64 } from '../core/assets';
import { gunzip } from './gunzip';

const BLOCK_ID = 'dcm2niix-wasm'; // scripts/vite-dcm2niix.mjs: WASM_BLOCK_ID

let cached: Promise<ArrayBuffer> | undefined;

const load = async (): Promise<ArrayBuffer> => {
  const block = document.getElementById(BLOCK_ID);
  if (!block) throw new Error('This page has no embedded dcm2niix. Build it with `make web`.');
  if (block.dataset['gz'] !== '1') throw new Error('The embedded dcm2niix is not gzipped as expected.');
  const wasm = await gunzip(decodeBase64(block.textContent ?? '') as Uint8Array<ArrayBuffer>);
  block.remove();
  return wasm.buffer;
};

/** The wasm bytes; do not transfer them (the runner sends each worker a copy). A failure is not cached. */
export const dcm2niixWasm = (): Promise<ArrayBuffer> => {
  cached ??= load().catch((e: unknown) => {
    cached = undefined;
    throw e;
  });
  return cached;
};
