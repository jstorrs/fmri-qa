/**
 * "About & licences": the third-party notices (web/THIRD_PARTY_NOTICES.md), which the page must carry. They are in the
 * page as one inert, gzipped, base64 block (`#notices-data`, scripts/vite-notices.mjs), unpacked the first time the section
 * is opened; `details[data-notices]` says how far that got (`shown` or `failed`).
 */
import { decodeBase64 } from '../core/assets';
import { gunzip } from './gunzip';

const BLOCK_ID = 'notices-data'; // scripts/vite-notices.mjs: NOTICES_BLOCK_ID

const read = async (): Promise<string> => {
  const block = document.getElementById(BLOCK_ID);
  if (!block) throw new Error('This page has no embedded notices. Build it with `make web`.');
  if (block.dataset['gz'] !== '1') throw new Error('The embedded notices are not gzipped as expected.');
  const text = new TextDecoder().decode(await gunzip(decodeBase64(block.textContent ?? '') as Uint8Array<ArrayBuffer>));
  block.remove();
  return text;
};

export const mountAbout = (details: HTMLDetailsElement, target: HTMLElement): void => {
  let started = false;
  const start = (): void => {
    if (!details.open || started) return;
    started = true;
    target.textContent = 'Unpacking the notices…';
    read().then(
      (text) => {
        target.textContent = text;
        details.dataset['notices'] = 'shown';
      },
      (e: unknown) => {
        started = false; // closing and opening again retries
        target.textContent = `The notices could not be shown: ${e instanceof Error ? e.message : String(e)}`;
        details.dataset['notices'] = 'failed';
      },
    );
  };
  details.addEventListener('toggle', start);
  start(); // already open (a restored page)
};
