// Browser adapter for e2e: one small page API over puppeteer-core (chrome, firefox) and playwright-core (webkit).
// Trimmed from dicom-util's e2e/browsers.mjs at fe0d59e: no dialogs, mouse, keyboard or viewport helpers, which this page
// does not need yet; the browser locations and environment overrides are the same (see e2e/README.md there).
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const BROWSER_NAMES = ['chrome', 'firefox', 'webkit'];
const CACHE = path.join(os.homedir(), '.cache', 'dicom-util', 'browsers');

/** E2E_BROWSERS, comma-separated; chrome and firefox by default (WebKit is opt-in, see web/README.md). */
export const selectedBrowsers = () => {
  const names = (process.env.E2E_BROWSERS ?? 'chrome,firefox').split(',').map((s) => s.trim()).filter(Boolean);
  for (const n of names) if (!BROWSER_NAMES.includes(n)) throw new Error(`Unknown browser "${n}" in E2E_BROWSERS`);
  return names;
};

const must = (p, hint) => {
  if (!p || !fs.existsSync(p)) throw new Error(`Executable not found: ${p ?? '(unset)'}. ${hint} See web/README.md.`);
  return p;
};

const findFirefox = () => {
  if (process.env.FIREFOX_PATH) return process.env.FIREFOX_PATH;
  const root = path.join(CACHE, 'firefox');
  const builds = fs.existsSync(root) ? fs.readdirSync(root).sort((a, b) => b.localeCompare(a, undefined, { numeric: true })) : [];
  return builds.length ? path.join(root, builds[0], 'firefox', 'firefox') : undefined;
};

/** Source for the init script: e2e/init-hooks.js. */
export const hooksSource = () => fs.readFileSync(fileURLToPath(new URL('./init-hooks.js', import.meta.url)), 'utf8');

/** Wrap a puppeteer page. `bidiGap`: the Firefox driver, which cannot evaluate in a worker (see evaluateInWorker). */
const puppeteerPage = (page, bidiGap) => {
  const pageErrors = [];
  const requests = [];
  const console = [];
  page.on('pageerror', (e) => pageErrors.push(String(e)));
  page.on('request', (r) => requests.push(r.url()));
  page.on('console', (m) => console.push(m.text()));
  // Puppeteer reports neither worker network requests nor worker uncaught errors; see dicom-util's e2e/README.md.
  return {
    pageErrors,
    requests,
    console,
    addInitScript: (source) => page.evaluateOnNewDocument(source),
    goto: (url) => page.goto(url, { timeout: 120000 }),
    waitFor: (fn, arg, timeout = 30000) => page.waitForFunction(fn, { timeout, polling: 500 }, arg),
    evaluate: (fn, arg) => page.evaluate(fn, arg),
    evaluateInWorker: (fn) => evaluateInWorker(page.workers(), fn, bidiGap),
    close: () => page.close(),
  };
};

/**
 * Run `fn` in the page's first dedicated worker. Resolves `{ value }`; throws when no worker is listed. Resolves null
 * only when `bidiGap` is set (puppeteer's Firefox driver over WebDriver BiDi, Firefox 159), which lists the worker but
 * then cannot find its realm ("no such frame"). Anywhere else that error is thrown, so a lost worker fails the test.
 */
const evaluateInWorker = async (workers, fn, bidiGap = false) => {
  if (workers.length === 0) throw new Error('no dedicated worker is listed for the page');
  try {
    return { value: await workers[0].evaluate(fn) };
  } catch (e) {
    if (bidiGap && /no such frame/i.test(String(e))) return null;
    throw e;
  }
};

/** Wrap a playwright page. */
const playwrightPage = (page) => {
  const pageErrors = [];
  const requests = [];
  const console = [];
  page.on('pageerror', (e) => pageErrors.push(String(e)));
  // Context-level 'request' also covers dedicated-worker requests (where supported by the engine).
  page.context().on('request', (r) => requests.push(r.url()));
  page.on('console', (m) => console.push(m.text()));
  return {
    pageErrors,
    requests,
    console,
    addInitScript: (source) => page.addInitScript({ content: source }),
    goto: (url) => page.goto(url, { timeout: 120000 }),
    waitFor: (fn, arg, timeout = 30000) => page.waitForFunction(fn, arg, { timeout, polling: 500 }),
    evaluate: (fn, arg) => page.evaluate(fn, arg),
    evaluateInWorker: (fn) => evaluateInWorker(page.workers(), fn),
    close: () => page.close(),
  };
};

/** Launch a browser by name. Returns { name, version, newPage(), close() }. */
export const launch = async (name) => {
  if (name === 'chrome' || name === 'firefox') {
    const { default: puppeteer } = await import('puppeteer-core');
    const browser = await puppeteer.launch(
      name === 'chrome'
        ? {
            executablePath: must(process.env.CHROME_PATH || '/usr/bin/google-chrome', 'Set CHROME_PATH.'),
            headless: true,
            args: ['--no-sandbox'],
            protocolTimeout: 600000,
          }
        : { browser: 'firefox', executablePath: must(findFirefox(), 'Install Firefox or set FIREFOX_PATH.'), headless: true, protocolTimeout: 600000 },
    );
    try {
      return { name, version: await browser.version(), newPage: async () => puppeteerPage(await browser.newPage(), name === 'firefox'), close: () => browser.close() };
    } catch (e) {
      await browser.close();
      throw e;
    }
  }
  if (name === 'webkit') {
    // playwright-core reads PLAYWRIGHT_BROWSERS_PATH at import time, so set it before the import below.
    process.env.PLAYWRIGHT_BROWSERS_PATH ||= path.join(CACHE, 'playwright');
    const libs = process.env.WEBKIT_LD_LIBRARY_PATH || path.join(CACHE, 'libs');
    const LD_LIBRARY_PATH = [fs.existsSync(libs) ? libs : '', process.env.LD_LIBRARY_PATH ?? ''].filter(Boolean).join(':');
    const { webkit } = await import('playwright-core');
    must(webkit.executablePath(), 'Run: PLAYWRIGHT_BROWSERS_PATH=... npx playwright-core install webkit.');
    const browser = await webkit.launch({ headless: true, env: { ...process.env, LD_LIBRARY_PATH } });
    try {
      return { name, version: browser.version(), newPage: async () => playwrightPage(await browser.newPage()), close: () => browser.close() };
    } catch (e) {
      await browser.close();
      throw e;
    }
  }
  throw new Error(`Unknown browser "${name}"`);
};
