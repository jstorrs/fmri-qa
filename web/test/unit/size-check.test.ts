// The size budget fails the build, so its parsing and arithmetic are pinned here.
import { describe, expect, test } from 'vitest';
import { BUDGET_BYTES, checkBudget, formatReport, MB, parseAssets } from '../../scripts/size-check.mjs';

const octet = (attrs: string, body: string) => `<script type="application/octet-stream" ${attrs}>${body}</script>`;
const tag = (attrs: string, body: string) => `<script${attrs}>${body}</script>`;

describe('parseAssets', () => {
  const html = [
    '<html><head><script type="module" crossorigin>const a = 1;</script></head><body>',
    octet('data-name="numpy.whl" data-kind="pyodide-package"', 'AAAA'),
    octet('id="dcm2niix-wasm" data-gz="1"', 'BBBBBB'),
    octet('id="notices-data" data-gz="1"', 'CC'),
    '<script>let b = 2;</script></body></html>',
  ].join('');

  test('labels each inert block by data-name or id and sums the JS', () => {
    const assets = parseAssets(html);
    expect(assets.map((a) => [a.label, a.kind])).toEqual([
      ['numpy.whl', 'pyodide-package'],
      ['dcm2niix-wasm', 'embedded'],
      ['notices-data', 'embedded'],
      ['JS', 'js'],
    ]);
    const js = tag(' type="module" crossorigin', 'const a = 1;').length + tag('', 'let b = 2;').length;
    expect(assets.at(-1)?.bytes).toBe(js);
  });

  test('counts bytes, not UTF-16 units', () => {
    const [js] = parseAssets(tag('', 'é'));
    expect(js?.bytes).toBe('<script>é</script>'.length + 1);
  });

  test('refuses an inert block it cannot name', () => {
    expect(() => parseAssets(octet('data-gz="1"', 'AA'))).toThrow(/neither data-name nor id/);
  });
});

describe('checkBudget', () => {
  test('the budget is 72 MB of 1 000 000 bytes', () => {
    expect(BUDGET_BYTES).toBe(72_000_000);
  });

  test('exactly the limit passes; one byte over fails', () => {
    expect(checkBudget(BUDGET_BYTES)).toMatchObject({ ok: true, headroom: 0 });
    expect(checkBudget(BUDGET_BYTES + 1)).toMatchObject({ ok: false, headroom: -1 });
  });

  test('reports the headroom', () => {
    expect(checkBudget(66.8 * MB).headroom).toBeCloseTo(5.2 * MB, 0);
  });
});

describe('formatReport', () => {
  test('lists the assets largest first, then the total and the headroom', () => {
    const assets = [
      { label: 'small', kind: 'x', bytes: 1000 },
      { label: 'big', kind: 'x', bytes: 5 * MB },
    ];
    const lines = formatReport(assets, checkBudget(6 * MB));
    expect(lines[1]).toMatch(/^ {2}big\b.*5\.00 MB$/);
    expect(lines.at(-1)).toMatch(/total 6\.00 MB of 72\.00 MB .*: 66\.00 MB under$/);
  });

  test('says OVER when the page is too big', () => {
    expect(formatReport([], checkBudget(BUDGET_BYTES + MB)).at(-1)).toMatch(/1\.00 MB OVER$/);
  });
});
