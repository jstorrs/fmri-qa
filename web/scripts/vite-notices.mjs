// The third-party notices (web/THIRD_PARTY_NOTICES.md, written by scripts/web_notices.py at the repo root), in the page:
//  - `noticesBlock()` (page): the file as one inert, gzipped, base64 block (`#notices-data`), like the dcm2niix wasm
//    (scripts/vite-dcm2niix.mjs). It is about 350 KB of text, so it is unpacked only when "About & licences" is opened
//    (src/shell/about.ts). Before anything is bundled it runs `scripts/web_notices.py --check`, so no build, `make web`
//    or a bare `npm run build`, ships notices that are stale or missing.
//  - `bundledPackages()` (page and every worker build): the npm packages with code in the output must be exactly
//    web/package.json's `dependencies`, the set scripts/web_notices.py writes a notice for. A package that slips in
//    through a new import fails the build instead of shipping without its licence.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const WEB = fileURLToPath(new URL('../', import.meta.url));
const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const NOTICES = `${WEB}THIRD_PARTY_NOTICES.md`;

/** The `id` of the page's block; src/shell/about.ts reads it. */
export const NOTICES_BLOCK_ID = 'notices-data';

export const noticesBlock = () => ({
  name: 'notices-block',
  apply: 'build',
  buildStart() {
    try {
      // --no-sync: a build never changes the venv or reaches the network; the check reads only local files.
      execFileSync('uv', ['run', '--no-sync', 'python', 'scripts/web_notices.py', '--check'], {
        cwd: ROOT,
        stdio: ['ignore', 'inherit', 'pipe'],
        timeout: 120_000,
      });
    } catch (e) {
      throw new Error(`notices-block: \`uv run python scripts/web_notices.py --check\` failed: ${String(e.stderr ?? e).trim()}`);
    }
  },
  transformIndexHtml: {
    order: 'post',
    handler: () => [
      {
        tag: 'script',
        attrs: { type: 'application/octet-stream', id: NOTICES_BLOCK_ID, 'data-gz': '1' },
        children: gzipSync(readFileSync(NOTICES), { level: 9 }).toString('base64'),
        injectTo: 'body',
      },
    ],
  },
});

/**
 * `@scope/name` or `name` of the package a module id lives in, or null outside node_modules. A nested dependency
 * (`node_modules/a/node_modules/b/...`) is `b`'s: the last `node_modules/` segment is the package the code is from.
 */
export const packageOf = (id) => {
  const at = id.lastIndexOf('/node_modules/');
  if (at < 0) return null;
  const match = /^((?:@[^/]+\/)?[^/]+)\//.exec(id.slice(at + '/node_modules/'.length));
  return match ? match[1] : null;
};

/**
 * Returns `{ page, worker }`: two plugins sharing one record of the packages seen. Vite builds each worker while it
 * bundles the page, so by the page's `generateBundle` every worker's output has been seen. Only modules that render
 * code count, so a package imported only for its types does not.
 */
export const bundledPackages = () => {
  const seen = new Set();
  const record = (bundle) => {
    for (const file of Object.values(bundle)) {
      if (file.type !== 'chunk') continue;
      for (const [id, module] of Object.entries(file.modules)) {
        const name = packageOf(id);
        if (name && module.renderedLength > 0) seen.add(name);
      }
    }
  };
  const worker = { name: 'bundled-packages-worker', apply: 'build', generateBundle: (_, bundle) => record(bundle) };
  const page = {
    name: 'bundled-packages',
    apply: 'build',
    enforce: 'post',
    generateBundle(_, bundle) {
      record(bundle);
      const declared = new Set(Object.keys(JSON.parse(readFileSync(`${WEB}package.json`, 'utf8')).dependencies));
      const extra = [...seen].filter((n) => !declared.has(n)).sort();
      const unused = [...declared].filter((n) => !seen.has(n)).sort();
      if (extra.length > 0 || unused.length > 0) {
        throw new Error(
          `bundled-packages: the page's npm packages must be web/package.json's dependencies (scripts/web_notices.py ` +
            `writes their notices). In the bundle but not a dependency: ${extra.join(', ') || 'none'}. ` +
            `A dependency with no code in the bundle: ${unused.join(', ') || 'none'}.`,
        );
      }
    },
  };
  return { page, worker };
};
