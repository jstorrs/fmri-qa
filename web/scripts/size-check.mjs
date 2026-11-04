// Fails the build when dist/fmri-qa.html is over the size budget, and says where the bytes are.
// Sizes are bytes of the file as saved, so base64 text counts at full length. MB is 1 000 000 bytes
// (not 2^20), the unit web/README.md uses. Run by `npm run build` after `vite build`.
import { readFileSync, realpathSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const MB = 1_000_000;
/** The budget. Raise it here and in web/README.md ("Limits") together. */
export const BUDGET_BYTES = 72 * MB;

const PAGE = fileURLToPath(new URL('../dist/fmri-qa.html', import.meta.url));
const SCRIPT = /<script\b([^>]*)>([\s\S]*?)<\/script>/g;
const attr = (attrs, name) => new RegExp(`\\s${name}(?:="([^"]*)")?(?=\\s|$)`).exec(` ${attrs}`)?.[1];
const bytes = (text) => Buffer.byteLength(text, 'utf8');

/**
 * The page's scripts as `{ label, kind, bytes }`, each block counting its whole tag. Inert
 * `application/octet-stream` blocks are labelled by `data-name` (Pyodide assets) or `id` (dcm2niix-wasm,
 * notices-data); every other script is JS and is summed into one "JS" row.
 */
export const parseAssets = (html) => {
  const assets = [];
  let js = 0;
  for (const [tag, attrs] of html.matchAll(SCRIPT)) {
    if (attr(attrs, 'type') !== 'application/octet-stream') {
      js += bytes(tag);
      continue;
    }
    const label = attr(attrs, 'data-name') ?? attr(attrs, 'id');
    if (!label) throw new Error(`size-check: an octet-stream block has neither data-name nor id: <script${attrs}>`);
    assets.push({ label, kind: attr(attrs, 'data-kind') ?? 'embedded', bytes: bytes(tag) });
  }
  assets.push({ label: 'JS', kind: 'js', bytes: js });
  return assets;
};

/** `{ ok, total, limit, headroom }`; headroom is negative when over. */
export const checkBudget = (total, limit = BUDGET_BYTES) => ({ ok: total <= limit, total, limit, headroom: limit - total });

const mb = (n) => `${(n / MB).toFixed(2)} MB`;

/** The report as lines: the assets largest first, the rest of the page (HTML, CSS), the total and the headroom. */
export const formatReport = (assets, verdict) => {
  const listed = assets.reduce((sum, a) => sum + a.bytes, 0);
  const rows = [...assets, { label: 'markup and styles', kind: 'rest', bytes: verdict.total - listed }];
  const width = Math.max(...rows.map((r) => r.label.length));
  const lines = rows.sort((a, b) => b.bytes - a.bytes).map((r) => `  ${r.label.padEnd(width)}  ${mb(r.bytes).padStart(10)}`);
  const status = verdict.ok ? `${mb(verdict.headroom)} under` : `${mb(-verdict.headroom)} OVER`;
  return [
    'fmri-qa.html size',
    ...lines,
    `  total ${mb(verdict.total)} of ${mb(verdict.limit)} (${verdict.total} of ${verdict.limit} bytes): ${status}`,
  ];
};

const main = () => {
  const html = readFileSync(PAGE, 'utf8');
  const verdict = checkBudget(bytes(html));
  console.log(formatReport(parseAssets(html), verdict).join('\n'));
  if (!verdict.ok) {
    console.error(`size-check: the page is over its ${mb(verdict.limit)} budget; trim it or raise BUDGET_BYTES with a reason.`);
    process.exit(1);
  }
};

// Compare real paths: import.meta.url is resolved, argv[1] may run through a symlink.
if (process.argv[1] !== undefined && realpathSync(process.argv[1]) === fileURLToPath(import.meta.url)) main();
