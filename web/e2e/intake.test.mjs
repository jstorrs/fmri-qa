// Step 5: dist/fmri-qa.html takes DICOM (files, a .zip), shows the Patient > Study > Series tree, and converts a
// selected series with dcm2niix WASM to the same outputs native dcm2niix writes. Python boots in the background the whole
// time; the last test waits for it and checks that nothing in the whole flow was blocked or fetched.
// The conversion is the first part of a run (e2e/run.test.mjs has the rest): each test reads the names dcm2niix gave
// from the run table, cancels the run, then checks the files through its downloads, under the dcm2niix or the QA name
// (the run names them as soon as Python is ready). The fixtures are the repo's own, read from their paths.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, before, describe, test } from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { gunzipSync } from 'node:zlib';
import { zipSync } from 'fflate';
import { hooksSource, launch, selectedBrowsers } from './browsers.mjs';

const WEB = fileURLToPath(new URL('../', import.meta.url));
const ROOT = path.resolve(WEB, '..');
const PAGE_URL = pathToFileURL(`${WEB}dist/fmri-qa.html`).href;
const FIXTURES = `${ROOT}/packages/fmri-qa-io/tests/fixtures/`;
const QA = `${FIXTURES}dicom-qa/`;
const TWO = `${FIXTURES}dicom/`;
const CONTRACT = JSON.parse(fs.readFileSync(`${WEB}src/generated/contract.json`, 'utf8'));
const [QA_STEM] = JSON.parse(fs.readFileSync(`${WEB}test/fixtures/expected.json`, 'utf8'))['packages/fmri-qa-io/tests/fixtures/dicom-qa'].map((r) => r.stem);
const BOOT_TIMEOUT_MS = 180_000;
// NIfTI-1 datatype codes that are integers: uint8 2, int16 4, int32 8, int8 256, uint16 512, uint32 768, int64 1024, uint64 1280.
const INTEGER_DATATYPES = new Set([2, 4, 8, 256, 512, 768, 1024, 1280]);

const files = (dir) =>
  fs
    .readdirSync(dir, { recursive: true, withFileTypes: true })
    .filter((e) => e.isFile())
    .map((e) => path.join(e.parentPath, e.name))
    .sort();
const qaFiles = files(QA);
assert.equal(qaFiles.length, 36, 'dicom-qa should hold 36 files');
const twoFiles = files(TWO); // 8 .dcm files and generate.py, which is not DICOM
assert.equal(twoFiles.filter((f) => f.endsWith('.dcm')).length, 8);

const scratch = fs.mkdtempSync(path.join(os.tmpdir(), 'fmriqa-intake-'));
const zipPath = `${scratch}/dicom-qa.zip`;
// Native dcm2niix on the same series, through fmriqa_io: the names and bytes the browser must reproduce.
const native = {};

before(() => {
  fs.writeFileSync(zipPath, zipSync(Object.fromEntries(qaFiles.map((f) => [path.relative(QA, f), new Uint8Array(fs.readFileSync(f))]))));
  const out = `${scratch}/native`;
  execFileSync(
    'uv',
    ['run', 'python', '-I', '-c', 'import sys; from fmriqa_io import import_dicom; import_dicom(sys.argv[1], sys.argv[2], names="dcm2niix")', QA, out],
    { cwd: ROOT, stdio: 'inherit' },
  );
  for (const name of fs.readdirSync(out).sort()) if (fs.statSync(`${out}/${name}`).isFile()) native[name] = fs.readFileSync(`${out}/${name}`);
  assert.deepEqual(Object.keys(native).map((n) => n.replace(/^.*?\./, '.')), ['.json', '.nii.gz'], `native output: ${Object.keys(native)}`);
});
after(() => fs.rmSync(scratch, { recursive: true, force: true }));

for (const name of selectedBrowsers()) {
  describe(name, () => {
    let browser;
    let page;

    const counts = () => page.evaluate(() => ({ ...document.getElementById('counts').dataset, state: document.body.dataset.state }));
    const open = async (inputFiles, instances) => {
      await page.setFiles('#open-files', inputFiles);
      await page.waitFor(
        (n) => document.body.dataset.state === 'ready' && document.getElementById('counts').dataset.countInstances === String(n),
        instances,
        60_000,
      );
    };
    const seriesRows = () =>
      page.evaluate(() =>
        [...document.querySelectorAll('#tree-host [data-series-key]')].map((r) => ({
          uid: JSON.parse(r.dataset.seriesKey)[2],
          text: r.textContent,
          checked: r.querySelector('input').checked,
        })),
      );
    /** Start a run and wait until every series is converted (or failed); the run goes on to Python afterwards. */
    const convert = async () => {
      await page.click('#run');
      await page.waitFor(
        () => {
          const rows = [...document.querySelectorAll('#results-body tr')];
          return rows.length > 0 && rows.every((r) => r.dataset.status !== 'queued' && r.dataset.status !== 'converting');
        },
        undefined,
        60_000,
      );
      return page.evaluate(() =>
        [...document.querySelectorAll('#results-body tr')].map((tr) => ({
          kind: tr.className,
          series: tr.dataset.series,
          status: tr.dataset.status,
          dcm2niixFiles: tr.dataset.dcm2niixFiles,
          actions: [...tr.querySelectorAll('button[data-action]')].map((b) => b.dataset.action),
          text: tr.textContent,
        })),
      );
    };
    /** Click a download button and return the file it saved. */
    const download = async (selector) => {
      const before = await page.evaluate(() => window.__downloads.length);
      await page.click(selector);
      await page.waitFor((n) => window.__downloads.length > n, before, 10_000);
      const d = await page.evaluate(() => window.__downloads.at(-1));
      assert.equal(d.error, undefined, `download failed: ${d.error}`);
      return { name: d.name, bytes: Buffer.from(d.b64, 'base64') };
    };
    /** Cancel the run if it is still going (waiting for Python, most likely), and wait for the page to be ready again. */
    const stopRun = async () => {
      await page.evaluate(() => document.body.dataset.state === 'working' && document.getElementById('cancel').click());
      await page.waitFor(() => document.body.dataset.state === 'ready', undefined, 120_000);
    };

    /** Convert the single series of the opened set; its outputs must be native dcm2niix's, byte for byte once gunzipped. */
    const assertQaConversion = async (uid) => {
      const [row] = await seriesRows();
      assert.ok(!row.checked);
      await page.click('#tree-host [data-series-key] input');
      assert.deepEqual(await page.evaluate(() => ({ ...document.getElementById('summary').dataset })), { countSeries: '1', countFiles: '36' });
      const results = await convert();
      assert.equal(results.length, 1, 'exactly one NIfTI');
      const [r] = results;
      assert.equal(r.kind, 'result', r.text);
      assert.notEqual(r.status, 'failed', r.text);
      assert.equal(r.series, uid);
      assert.deepEqual(r.actions.filter((a) => a === 'nifti' || a === 'sidecar'), ['nifti', 'sidecar'], 'one .nii.gz and one .json');
      const names = Object.keys(native);
      assert.deepEqual(JSON.parse(r.dcm2niixFiles), names, 'the names native dcm2niix gives');
      assert.match(names.find((n) => n.endsWith('.nii.gz')), /^\d+_2_QA_EPI_ISO\.nii\.gz$/);
      await stopRun(); // the table no longer changes under the clicks below

      const niiName = names.find((n) => n.endsWith('.nii.gz'));
      const niiFile = await download('#results-body tr.result button[data-action="nifti"]');
      assert.ok([niiName, `${QA_STEM}.nii.gz`].includes(niiFile.name), `downloaded as ${niiFile.name}`);
      const nii = gunzipSync(niiFile.bytes);
      const dv = new DataView(nii.buffer, nii.byteOffset, nii.byteLength);
      assert.equal(dv.getInt32(0, true), 348);
      const datatype = dv.getInt16(70, true);
      assert.ok(INTEGER_DATATYPES.has(datatype), `datatype ${datatype} should be an integer type (-l o)`);
      const slope = dv.getFloat32(112, true);
      assert.equal(slope, 1, `scl_slope ${slope}`);
      assert.deepEqual([dv.getInt16(42, true), dv.getInt16(44, true), dv.getInt16(46, true), dv.getInt16(48, true)], [48, 48, 3, 12], 'dim');
      assert.ok(nii.equals(gunzipSync(native[niiName])), 'the wasm NIfTI differs from native dcm2niix\'s');

      const jsonName = names.find((n) => n.endsWith('.json'));
      const jsonFile = await download('#results-body tr.result button[data-action="sidecar"]');
      assert.ok([jsonName, `${QA_STEM}.json`].includes(jsonFile.name), `downloaded as ${jsonFile.name}`);
      const sidecarBytes = jsonFile.bytes;
      const sidecar = JSON.parse(sidecarBytes.toString('utf8'));
      assert.ok(!('PatientName' in sidecar) && !('PatientID' in sidecar), 'sidecar must not hold patient identifiers (-ba o)');
      const nativeSidecar = JSON.parse(native[jsonName].toString('utf8'));
      assert.deepEqual(sidecar, nativeSidecar, 'the wasm sidecar differs from native dcm2niix\'s');
      assert.ok(sidecarBytes.equals(native[jsonName]), 'the wasm sidecar bytes differ from native dcm2niix\'s');
    };

    before(async () => {
      browser = await launch(name);
      page = await browser.newPage();
      await page.addInitScript(hooksSource());
      await page.goto(PAGE_URL);
    });
    after(() => browser?.close());

    test('the contract flags include -l o -b y and -ba o', () => {
      const pair = (flag) => CONTRACT.dcm2niix_flags[CONTRACT.dcm2niix_flags.indexOf(flag) + 1];
      assert.deepEqual([pair('-l'), pair('-b'), pair('-ba')], ['o', 'y', 'o']);
    });

    test('the QA series (36 files): the tree shows 1 patient, 1 study, 1 series; convert gives native outputs', { timeout: 240_000 }, async () => {
      await open(qaFiles, 36);
      assert.deepEqual(await counts(), {
        countPatients: '1', countStudies: '1', countSeries: '1', countInstances: '36', countSkipped: '0', countRejected: '0', countDuplicates: '0', state: 'ready',
      });
      const rows = await seriesRows();
      assert.equal(rows.length, 1);
      assert.match(rows[0].text, /QA_EPI_ISO/);
      assert.equal(await page.evaluate(() => document.getElementById('run').disabled), true, 'nothing selected yet');
      await assertQaConversion(rows[0].uid);
    });

    test('the two-series set: 2 series, 8 files, and the non-DICOM file is skipped', { timeout: 60_000 }, async () => {
      await open(twoFiles, 8);
      const c = await counts();
      assert.deepEqual([c.countPatients, c.countSeries, c.countInstances, c.countSkipped, c.countRejected], ['1', '2', '8', '1', '0']);
      assert.equal((await seriesRows()).length, 2);
      await page.click('#select-all');
      assert.deepEqual(await page.evaluate(() => ({ ...document.getElementById('summary').dataset })), { countSeries: '2', countFiles: '8' });
      await page.click('#select-none');
      assert.equal(await page.evaluate(() => document.getElementById('run').disabled), true);
    });

    test('a .zip of the QA series gives the same series and the same conversion', { timeout: 240_000 }, async () => {
      await open([zipPath], 36);
      const c = await counts();
      assert.deepEqual([c.countPatients, c.countStudies, c.countSeries, c.countInstances], ['1', '1', '1', '36']);
      const [row] = await seriesRows();
      await assertQaConversion(row.uid);
    });

    test('Python boots in the background; nothing was blocked, refused or fetched during the whole flow', { timeout: BOOT_TIMEOUT_MS + 60_000 }, async () => {
      await page.waitFor(() => document.body.dataset.python !== 'booting', undefined, BOOT_TIMEOUT_MS);
      const state = await page.evaluate(() => ({
        python: document.body.dataset.python,
        error: document.getElementById('python-error').textContent,
        diagnostics: window.__fmriqa.diagnostics(),
        pageViolations: window.__cspViolations,
      }));
      assert.equal(state.python, 'ready', `boot failed: ${state.error}`);
      assert.deepEqual(state.diagnostics.refused, [], 'the fetch shim refused requests');
      assert.deepEqual(state.diagnostics.violations, [], 'CSP violations in the Pyodide worker');
      assert.deepEqual(state.pageViolations, [], 'CSP violations in the page');
      assert.deepEqual(page.pageErrors, []);
      if (name !== 'firefox') assert.ok(page.requests.includes(PAGE_URL), `page request not captured: ${page.requests}`);
      assert.deepEqual(page.requests.filter((u) => !/^(file|data|blob):/.test(u)), []);
    });
  });
}
