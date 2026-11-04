// Step 6: dist/fmri-qa.html runs selected series through dcm2niix WASM, names them with Python's names_json and
// analyzes each with analyze_json, and the stems, records and failures equal a native run's
// (test/fixtures/expected.json, written by scripts/web_expected.py). The report shows in an inert sandboxed iframe, and
// every file downloads under its QA name. Nothing in the whole flow is blocked, refused or fetched, as far as the page
// and the Pyodide worker can see: a CSP violation inside the srcdoc preview is not observed.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, describe, test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { hooksSource, launch, selectedBrowsers } from './browsers.mjs';

const WEB = fileURLToPath(new URL('../', import.meta.url));
const ROOT = path.resolve(WEB, '..');
const PAGE_URL = pathToFileURL(`${WEB}dist/fmri-qa.html`).href;
const EXPECTED = JSON.parse(fs.readFileSync(`${WEB}test/fixtures/expected.json`, 'utf8'));
const CONTRACT = JSON.parse(fs.readFileSync(`${WEB}src/generated/contract.json`, 'utf8'));
const QA = 'packages/fmri-qa-io/tests/fixtures/dicom-qa';
const SHORT = 'packages/fmri-qa-io/tests/fixtures/dicom';
/** The boot takes ~50-60 s (web/README.md); a run waits for it, then analyzes (~15 s a series). */
const BOOT_TIMEOUT_MS = 180_000;
const RTOL = 1e-9;

const files = (dir) =>
  fs
    .readdirSync(`${ROOT}/${dir}`, { recursive: true, withFileTypes: true })
    .filter((e) => e.isFile())
    .map((e) => path.join(e.parentPath, e.name))
    .sort();

/** `actual` equals `expected` with numbers within RTOL; everything else, null included, exactly. */
const assertClose = (actual, expected, where = 'record') => {
  if (typeof expected === 'number') {
    assert.equal(typeof actual, 'number', `${where}: ${JSON.stringify(actual)}, expected ${expected}`);
    const ok = actual === expected || Math.abs(actual - expected) <= RTOL * Math.abs(expected);
    assert.ok(ok, `${where}: ${actual}, expected ${expected} (relative difference ${Math.abs(actual - expected) / Math.abs(expected)})`);
  } else if (Array.isArray(expected)) {
    assert.ok(Array.isArray(actual) && actual.length === expected.length, `${where}: ${JSON.stringify(actual)}`);
    expected.forEach((e, i) => assertClose(actual[i], e, `${where}[${i}]`));
  } else if (expected !== null && typeof expected === 'object') {
    assert.ok(actual !== null && typeof actual === 'object' && !Array.isArray(actual), `${where}: ${JSON.stringify(actual)}`);
    assert.deepEqual(Object.keys(actual).sort(), Object.keys(expected).sort(), `${where}: keys`);
    for (const k of Object.keys(expected)) assertClose(actual[k], expected[k], `${where}.${k}`);
  } else assert.strictEqual(actual, expected, where);
};
const escapeHtml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

for (const name of selectedBrowsers()) {
  describe(name, () => {
    let browser;
    let page;

    before(async () => {
      browser = await launch(name);
      page = await browser.newPage();
      await page.addInitScript(hooksSource());
      await page.goto(PAGE_URL);
    });
    after(() => browser?.close());

    /** Open `dir`, select every series, run, and wait for the run to end; the rows of the table. */
    const runStudy = async (dir, instances) => {
      await page.setFiles('#open-files', files(dir));
      await page.waitFor(
        (n) => document.body.dataset.state === 'ready' && document.getElementById('counts').dataset.countInstances === String(n),
        instances,
        60_000,
      );
      await page.click('#select-all');
      await page.click('#run');
      await page.waitFor(() => document.body.dataset.state === 'ready', undefined, BOOT_TIMEOUT_MS + 120_000);
      return page.evaluate(() =>
        [...document.querySelectorAll('#results-body tr')].map((tr) => ({
          ...tr.dataset,
          kind: tr.className,
          warnings: [...tr.querySelectorAll('td:nth-child(3) li')].map((li) => li.textContent),
          actions: [...tr.querySelectorAll('button[data-action]')].map((b) => b.dataset.action),
          text: tr.textContent,
        })),
      );
    };
    /** Click each download of the row for `stem`; the saved files by name. */
    const downloads = async (stem, actions) => {
      const saved = {};
      for (const action of actions) {
        const before = await page.evaluate(() => window.__downloads.length);
        await page.click(`#results-body tr[data-stem="${stem}"] button[data-action="${action}"]`);
        await page.waitFor((n) => window.__downloads.length > n, before, 10_000);
        const d = await page.evaluate(() => window.__downloads.at(-1));
        assert.equal(d.error, undefined, `${action}: ${d.error}`);
        saved[d.name] = Buffer.from(d.b64, 'base64');
      }
      return saved;
    };

    test('the QA study gives the native stem and record, an inert preview and every download', { timeout: BOOT_TIMEOUT_MS + 180_000 }, async () => {
      const t0 = Date.now();
      const rows = await runStudy(QA, 36);
      console.log(`${name}: the QA run took ${Date.now() - t0} ms, the Python boot included`);
      const expected = EXPECTED[QA];
      assert.deepEqual(rows.map((r) => [r.kind, r.stem, r.status]).sort(), expected.map((e) => ['result', e.stem, 'done']).sort(), JSON.stringify(rows));
      const [want] = expected;
      const row = rows.find((r) => r.stem === want.stem);
      assert.deepEqual(row.warnings, want.warnings);
      assert.deepEqual(row.actions, ['preview', 'nifti', 'sidecar', 'html', 'record']);

      const saved = await downloads(want.stem, ['nifti', 'sidecar', 'html', 'record']);
      assert.deepEqual(Object.keys(saved).sort(), [...want.files, `${want.stem}.html`, `${want.stem}.qa.json`].sort());

      // The one-scan document `fmri-qa --json` prints, in Python's own text: a whole float keeps its ".0".
      const documentText = saved[`${want.stem}.qa.json`].toString('utf8');
      const document = JSON.parse(documentText);
      assert.equal(document.schema_version, CONTRACT.json_schema_version);
      assert.deepEqual(document.requested, [`${want.stem}.nii.gz`]);
      assert.equal(document.scans.length, 1);
      assertClose(document.scans[0], want.record, 'scans[0]');
      assert.deepEqual(document.errors, []);
      assert.match(documentText, /\n {6}"tr": 2\.0,\n/);
      assert.ok(documentText.endsWith('}\n'));

      const html = saved[`${want.stem}.html`].toString('utf8');
      assert.match(html, /^<!DOCTYPE html>/i);
      assert.equal(html.match(/<title>([^<]*)<\/title>/)?.[1], `${escapeHtml(want.stem)} · fMRI QA`, 'the page title is the stem');
      assert.ok(!/<script/i.test(html), 'the report holds no script');

      await page.click(`#results-body tr[data-stem="${want.stem}"] button[data-action="preview"]`);
      const frame = await page.evaluate(() => {
        const f = document.getElementById('preview');
        return { hidden: f.hidden, sandbox: f.getAttribute('sandbox'), tokens: f.sandbox.length, stem: f.dataset.stem, srcdoc: f.srcdoc.length };
      });
      assert.deepEqual(frame, { hidden: false, sandbox: '', tokens: 0, stem: want.stem, srcdoc: html.length });
    });

    test('the two-volume study: both series fail with the native frame-count reason, and their files download', { timeout: 180_000 }, async () => {
      const rows = await runStudy(SHORT, 8);
      const expected = EXPECTED[SHORT];
      assert.deepEqual(rows.map((r) => r.stem).sort(), expected.map((e) => e.stem).sort(), JSON.stringify(rows));
      for (const want of expected) {
        const row = rows.find((r) => r.stem === want.stem);
        assert.deepEqual([row.kind, row.status, row.stage, row.reason], ['result', 'failed', want.stage, want.reason], row.text);
        assert.match(want.reason, /frame count 2/);
        assert.deepEqual(row.warnings, want.warnings);
        assert.deepEqual(row.actions, ['nifti', 'sidecar'], 'no preview, report or record for a failure');
        assert.deepEqual(Object.keys(await downloads(want.stem, row.actions)).sort(), want.files);
      }
    });

    test('nothing was blocked, refused or fetched during the whole flow', async () => {
      const state = await page.evaluate(() => ({
        python: document.body.dataset.python,
        diagnostics: window.__fmriqa.diagnostics(),
        pageViolations: window.__cspViolations,
      }));
      assert.equal(state.python, 'ready');
      assert.deepEqual(state.diagnostics.refused, [], 'the fetch shim refused requests');
      assert.deepEqual(state.diagnostics.violations, [], 'CSP violations in the Pyodide worker');
      assert.deepEqual(state.pageViolations, [], 'CSP violations in the page');
      assert.deepEqual(page.pageErrors, []);
      if (name !== 'firefox') assert.ok(page.requests.includes(PAGE_URL), `page request not captured: ${page.requests}`);
      assert.deepEqual(page.requests.filter((u) => !/^(file|data|blob):/.test(u)), []);
    });
  });
}
