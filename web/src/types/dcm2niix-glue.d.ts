/** Minimal typing for the Emscripten glue aliased in vite.config.mjs. */
declare module '@dcm2niix-glue' {
  export interface Dcm2niixFS {
    mkdir(path: string): void;
    /** `canOwn`: the FS keeps `data` as the file's contents instead of copying it. */
    writeFile(path: string, data: Uint8Array, opts?: { canOwn?: boolean }): void;
    readFile(path: string): Uint8Array;
    readdir(path: string): string[];
    unlink(path: string): void;
    stat(path: string): { mode: number };
    isDir(mode: number): boolean;
  }
  export interface Dcm2niixModule {
    FS: Dcm2niixFS;
    callMain(args: string[]): number;
  }
  export interface Dcm2niixOptions {
    print?: (text: string) => void;
    printErr?: (text: string) => void;
    /** The compiled module's bytes; with them the glue fetches nothing. */
    wasmBinary?: ArrayBuffer;
  }
  const Module: (options?: Dcm2niixOptions) => Promise<Dcm2niixModule>;
  export default Module;
}
