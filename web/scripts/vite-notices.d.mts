// Types for the unit tests (test/unit/vite-notices.test.ts); the build itself reads the .mjs.
import type { Plugin } from 'vite';

export declare const NOTICES_BLOCK_ID: string;
export declare const noticesBlock: () => Plugin;
export declare const packageOf: (id: string) => string | null;
export declare const bundledPackages: () => { page: Plugin; worker: Plugin };
