// Step 8: dist/fmri-qa.html carries the third-party notices. Opening "About & licences" unpacks them from the page
// (src/shell/about.ts) and shows web/THIRD_PARTY_NOTICES.md as written, with nothing fetched and no CSP violation.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { after, before, describe, test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { hooksSource, launch, selectedBrowsers } from './browsers.mjs';

const WEB = fileURLToPath(new URL('../', import.meta.url));
const PAGE_URL = pathToFileURL(`${WEB}dist/fmri-qa.html`).href;
const NOTICES = fs.readFileSync(`${WEB}THIRD_PARTY_NOTICES.md`, 'utf8');
const HEADINGS = ['## Pyodide ', '## CPython ', '## dcm2niix ', '## numpy '];

for (const name of selectedBrowsers()) {
  describe(name, () => {
    let browser;
    let page;
    before(async () => {
      browser = await launch(name);
      page = await browser.newPage();
      await page.addInitScript(hooksSource());
    });
    after(() => browser?.close());

    test('"About & licences" shows the notices, with no network and no CSP violation', { timeout: 120_000 }, async () => {
      await page.goto(PAGE_URL);
      // Lazy: nothing is unpacked until the section is opened.
      const before = await page.evaluate(() => ({
        block: document.getElementById('notices-data') !== null,
        text: document.getElementById('notices').textContent,
        notices: document.getElementById('about').dataset.notices ?? null,
      }));
      assert.deepEqual(before, { block: true, text: '', notices: null });
      await page.click('#about > summary');
      await page.waitFor(() => document.getElementById('about').dataset.notices !== undefined);
      const state = await page.evaluate(() => ({
        notices: document.getElementById('about').dataset.notices,
        text: document.getElementById('notices').textContent,
        blockLeft: document.getElementById('notices-data') !== null,
        pageViolations: window.__cspViolations,
        workerViolations: window.__fmriqa.diagnostics().violations,
      }));
      assert.equal(state.notices, 'shown', state.text);
      for (const heading of HEADINGS) assert.ok(state.text.includes(`\n${heading}`), `no "${heading}" heading`);
      assert.equal(state.text, NOTICES);
      assert.equal(state.blockLeft, false, 'the inert block was not removed once read');
      assert.deepEqual(state.pageViolations, []);
      assert.deepEqual(state.workerViolations, []);
      assert.deepEqual(page.pageErrors, []);
      assert.deepEqual(page.requests.filter((u) => !/^(file|data|blob):/.test(u)), []);
    });
  });
}
