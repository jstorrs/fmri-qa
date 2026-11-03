/**
 * The dcm2niix command line. The flags come from Python (`fmriqa_io`'s `DCM2NIIX_FLAGS`, copied into
 * src/generated/contract.json), so the page converts exactly as the analysis expects; this module only adds the two
 * virtual-filesystem paths the worker uses. Pure.
 */
import contract from '../generated/contract.json';

/** Where the dcm2niix worker puts the input files and reads the outputs from (its in-memory filesystem). */
export const IN_DIR = '/in';
export const OUT_DIR = '/out';

/** Flags that would redirect the paths this page owns. */
const OWNED = new Set(['-o']);

/** Parse the contract's flag list. Throws naming the problem when it is not a list of strings or sets `-o`. */
export const parseFlags = (x: unknown): readonly string[] => {
  if (!Array.isArray(x) || !x.every((f): f is string => typeof f === 'string')) throw new Error(`dcm2niix_flags is not a list of strings: ${JSON.stringify(x)}`);
  const owned = x.find((f) => OWNED.has(f));
  if (owned !== undefined) throw new Error(`dcm2niix_flags sets ${owned}, which the page sets itself`);
  return x;
};

/** The flags Python asked for, checked once at load. */
export const CONTRACT_FLAGS: readonly string[] = parseFlags(contract.dcm2niix_flags);

/** The full argv for `callMain`: the flags, then the output directory and the input directory. */
export const dcm2niixArgv = (flags: readonly string[]): string[] => [...flags, '-o', OUT_DIR, IN_DIR];
