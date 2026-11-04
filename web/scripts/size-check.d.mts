// Types for the unit tests (test/unit/size-check.test.ts); the build runs the .mjs.
export interface Asset {
  label: string;
  kind: string;
  bytes: number;
}
export interface Verdict {
  ok: boolean;
  total: number;
  limit: number;
  headroom: number;
}
export declare const MB: number;
export declare const BUDGET_BYTES: number;
export declare const parseAssets: (html: string) => Asset[];
export declare const checkBudget: (total: number, limit?: number) => Verdict;
export declare const formatReport: (assets: Asset[], verdict: Verdict) => string[];
