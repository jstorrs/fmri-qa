// Types for the unit tests (test/unit/vite-build-info.test.ts); the build itself reads the .mjs.
import type { Plugin } from 'vite';

export interface Commit {
  sha: string;
  date: string;
  modified: boolean;
}
export interface BuildInfo {
  version: string;
  commit: Commit | null;
}

export declare const REPOSITORY: string;
export declare const SITE: string;
export declare const APP: string;
export declare const MARKER: string;
export declare const projectVersion: (pyproject?: string) => string;
export declare const readCommit: () => Commit | null;
export declare const renderBuildInfo: (info: BuildInfo) => string;
export declare const injectBuildInfo: (html: string, info: BuildInfo) => string;
export declare const buildInfo: () => Plugin;
