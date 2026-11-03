/** pyodide.asm.mjs ships no types. Its default export is what `loadPyodide`'s `createPyodideModule` option takes. */
declare module 'pyodide/pyodide.asm.mjs' {
  import type { loadPyodide } from 'pyodide';
  const createPyodideModule: NonNullable<NonNullable<Parameters<typeof loadPyodide>[0]>['createPyodideModule']>;
  export default createPyodideModule;
}
