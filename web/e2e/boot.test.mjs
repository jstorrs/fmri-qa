// Step 4's proof: dist/fmri-qa.html, opened from file:// with nothing else, boots Pyodide in its worker, imports
// fmriqa_web, and analyzes a series to the same SNR as native CPython. `make web-e2e` builds the page first.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import { after, before, describe, test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { hooksSource, launch, selectedBrowsers } from './browsers.mjs';

const WEB = fileURLToPath(new URL('../', import.meta.url));
const PAGE = `${WEB}dist/fmri-qa.html`;
const PAGE_URL = pathToFileURL(PAGE).href;
const FIXTURE = `${WEB}test/fixtures/boot/`;
const readJson = (path) => JSON.parse(fs.readFileSync(path, 'utf8'));
const CONTRACT = readJson(`${WEB}src/generated/contract.json`);
const MANIFEST = readJson(`${WEB}vendor/manifest.json`);
/** The boot measured ~50-60 s per browser on the development machine (web/README.md); the limit leaves room for a slow CI. */
const BOOT_TIMEOUT_MS = 180_000;
const STEM = 'phantom';

describe('build output', () => {
  test('dist holds only fmri-qa.html', () => {
    assert.deepEqual(fs.readdirSync(`${WEB}dist`), ['fmri-qa.html']);
  });

  test('every manifest asset is embedded once', () => {
    const html = fs.readFileSync(PAGE, 'latin1');
    for (const { name } of MANIFEST.assets) assert.equal(html.split(`data-name="${name}"`).length - 1, 1, name);
  });
});

for (const name of selectedBrowsers()) {
  describe(name, () => {
    let browser;
    let page;
    const fixture = {};

    before(async () => {
      // Native: the same series through `analyze_json` under CPython (web/scripts/make_boot_fixture.py).
      execFileSync('uv', ['run', 'python', 'web/scripts/make_boot_fixture.py', FIXTURE], { cwd: `${WEB}..`, stdio: 'inherit' });
      fixture.nifti = fs.readFileSync(`${FIXTURE}${STEM}.nii.gz`).toString('base64');
      fixture.sidecar = fs.readFileSync(`${FIXTURE}${STEM}.json`).toString('base64');
      fixture.native = readJson(`${FIXTURE}native.json`);
      browser = await launch(name);
      page = await browser.newPage();
      await page.addInitScript(hooksSource());
    });
    after(() => browser?.close());

    test('boots Python from file:// with no network and no CSP violation', { timeout: BOOT_TIMEOUT_MS + 60_000 }, async () => {
      const t0 = Date.now();
      await page.goto(PAGE_URL);
      await page.waitFor(() => document.body.dataset.python !== 'booting', undefined, BOOT_TIMEOUT_MS);
      const state = await page.evaluate(() => ({
        python: document.body.dataset.python,
        error: document.getElementById('python-error').textContent,
        contract: document.getElementById('python-contract').textContent,
        stages: [...document.querySelectorAll('#python-stages li')].map((li) => [li.dataset.stage, Number(li.dataset.elapsedMs)]),
        diagnostics: window.__fmriqa.diagnostics(),
        pageViolations: window.__cspViolations,
      }));
      console.log(`${name} ${browser.version}: ready after ${Date.now() - t0} ms wall; stages (ms since boot) ${JSON.stringify(state.stages)}`);
      assert.equal(state.python, 'ready', `boot failed: ${state.error}`);
      assert.deepEqual(state.stages.map(([stage]) => stage), ['decode', 'runtime', 'packages', 'wheels', 'import', 'ready']);

      const contract = JSON.parse(state.contract);
      assert.deepEqual(contract.dcm2niix_flags, CONTRACT.dcm2niix_flags);
      assert.equal(contract.json_schema_version, CONTRACT.json_schema_version);
      assert.deepEqual(contract.versions, MANIFEST.versions);

      assert.deepEqual(state.diagnostics.refused, [], 'the fetch shim refused requests');
      assert.deepEqual(state.diagnostics.violations, [], 'CSP violations in the worker');
      assert.deepEqual(state.pageViolations, [], 'CSP violations in the page');
      assert.deepEqual(page.pageErrors, []);
      // Known gap (as in dicom-util's smoke test): puppeteer's Firefox driver reports no file:// requests, so the scheme
      // check is vacuous for http(s) there. It does report some data: requests; fail loudly if that changes.
      if (name === 'firefox') {
        assert.ok(page.requests.every((u) => u.startsWith('data:')), `firefox now reports other requests; drop this skip: ${page.requests}`);
      } else assert.ok(page.requests.includes(PAGE_URL), `page request not captured: ${page.requests}`);
      assert.deepEqual(page.requests.filter((u) => !/^(file|data|blob):/.test(u)), []);
    });

    const analyze = (withSidecar) =>
      page.evaluate(
        async ({ nifti, sidecar, stem }) => {
          const bytes = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
          return window.__fmriqa.call('analyze_json', [bytes(nifti), sidecar === null ? null : bytes(sidecar), stem]);
        },
        { nifti: fixture.nifti, sidecar: withSidecar ? fixture.sidecar : null, stem: STEM },
      );

    test('analyze_json gives the native SNR', { timeout: 120_000 }, async () => {
      const t0 = Date.now();
      const text = await analyze(true);
      const result = JSON.parse(text);
      console.log(`${name}: analyze_json took ${Date.now() - t0} ms`);
      assert.equal(result.kind, 'report', `not a report: ${text.slice(0, 500)}`);
      assert.equal(result.stem, STEM);
      assert.match(result.html, /^<!DOCTYPE html>/i);
      assert.deepEqual(result.warnings, fixture.native.warnings);
      const [browserSnr, nativeSnr] = [result.record.snr, fixture.native.record.snr];
      assert.equal(typeof nativeSnr, 'number');
      const rel = Math.abs(browserSnr - nativeSnr) / Math.abs(nativeSnr);
      assert.ok(rel <= 1e-9, `snr ${browserSnr} in ${name}, ${nativeSnr} native (relative difference ${rel})`);
    });

    test('analyze_json takes a null sidecar as None', { timeout: 120_000 }, async () => {
      const result = JSON.parse(await analyze(false));
      assert.equal(result.kind, 'report', JSON.stringify(result).slice(0, 500));
    });

    // Last: it raises a violation on purpose. Proves the page-side listener is live, so the empty list above means none.
    test('harness: a page CSP violation is recorded', async () => {
      await page.evaluate(() => {
        new Image().src = 'https://example.invalid/x.png';
      });
      await page.waitFor(() => window.__cspViolations.length > 0, undefined, 10_000);
      assert.match((await page.evaluate(() => window.__cspViolations))[0], /^img-src /);
    });

    // Proves the worker's listener and its `violation` message are live, so the empty worker list above means none.
    test('harness: a worker CSP violation reaches the page', async (t) => {
      const ran = await page.evaluateInWorker(() => {
        try {
          importScripts('https://example.invalid/x.js'); // script-src allows no https: URL
        } catch {
          /* the violation event is what is measured */
        }
        return true;
      });
      if (ran === null) {
        t.skip(`${name}: puppeteer's Firefox (BiDi) driver cannot run code in a worker; the worker path is unproven here`);
        return;
      }
      await page.waitFor(() => window.__fmriqa.diagnostics().violations.length > 0, undefined, 10_000);
      assert.match((await page.evaluate(() => window.__fmriqa.diagnostics().violations))[0], /^script-src(-elem)? https:\/\/example\.invalid/);
    });
  });
}
