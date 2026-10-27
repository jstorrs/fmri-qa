// Usage: node run_test.mjs [chrome|firefox] [html]
import puppeteer from "puppeteer-core";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const spike = path.resolve(here, "..");
const browser_name = process.argv[2] || "chrome";
const html = path.resolve(process.argv[3] || path.join(spike, "dist/fmriqa-spike.html"));
const native = JSON.parse(fs.readFileSync(path.join(spike, "dist/native.json")));

const browser = browser_name === "firefox"
  ? await puppeteer.launch({ browser: "firefox", executablePath: "/usr/bin/firefox", headless: true, protocol: "webDriverBiDi", userDataDir: process.env.FFPROFILE })
  : await puppeteer.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--no-sandbox"] });
const page = await browser.newPage();
await page.setViewport({ width: 1000, height: 1400 });
const requests = [];
page.on("console", m => console.log("[console]", m.text().slice(0, 300)));
page.on("pageerror", e => console.log("[pageerror]", String(e).slice(0, 500)));
if (browser_name === "chrome") await page.setOfflineMode(true);
await page.setRequestInterception(true);
page.on("request", req => {
  const u = req.url();
  const ok = u.startsWith("data:") || u.startsWith("blob:");
  if (!ok) requests.push(u.slice(0, 200));
  ok ? req.continue() : (u === pageUrl ? req.continue() : req.abort());
});
const pageUrl = "file://" + html;
const t0 = Date.now();
await page.goto(pageUrl, { waitUntil: "load", timeout: 300000 });
const loadMs = Date.now() - t0;
await page.waitForFunction(() => window.__spike && (window.__spike.ready || window.__spike.bootFailed), { timeout: 300000 });
const bootWall = Date.now() - t0;
const st = await page.evaluate(() => ({ phases: window.__spike.phases, err: window.__spike.error, fetches: window.__spike.requests.length, refused: window.__spike.requests.filter(r => r.refused) }));
console.log("page load event ms", loadMs, "ready wall ms", bootWall, JSON.stringify(st));
if (st.err) { console.log(st.err); await browser.close(); process.exit(1); }

const report = { browser: browser_name, loadMs, bootWall, phases: st.phases, runs: {}, nonDataRequests: requests };
let n = 0;
for (const name of ["small", "large"]) {
  const input = await page.$("#file");
  const dir = path.join(process.env.DATA_DIR || path.join(spike, "data"), name);
  await input.uploadFile(path.join(dir, `${name}.nii.gz`), path.join(dir, `${name}.json`));
  n++;
  await page.waitForFunction(k => window.__spike.results.length >= k, { timeout: 600000 }, n);
  const r = await page.evaluate(() => window.__spike.results.at(-1));
  report.runs[name] = r;
  console.log(name, "ok:", r.ok, "python s:", r.seconds?.toFixed(2), "total ms:", r.total_ms?.toFixed(0), "warnings:", JSON.stringify(r.warnings));
  if (!r.ok) { console.log(r.traceback || r.error); continue; }
  let bad = 0, worst = 0;
  for (const [k, v] of Object.entries(native[name].measurements)) {
    const b = r.measurements[k];
    if (typeof v === "number" && typeof b === "number") {
      const rel = Math.abs(v - b) / Math.max(1e-12, Math.abs(v), Math.abs(b));
      const ok = Math.abs(v - b) <= 1e-6 * Math.max(1, Math.abs(v)) ; worst = Math.max(worst, rel);
      if (!ok) { bad++; console.log("  MISMATCH", k, v, b); }
    } else if (JSON.stringify(v) !== JSON.stringify(b)) { bad++; console.log("  MISMATCH", k, v, b); }
  }
  report.runs[name].mismatches = bad; report.runs[name].worstRel = worst;
  console.log(`  ${name}: ${bad} mismatches, worst rel diff ${worst.toExponential(2)}; native ${native[name].seconds.toFixed(2)} s`);
  await page.screenshot({ path: path.join(spike, `dist/screenshot-${browser_name}-${name}.png`), fullPage: true });
}
console.log("non-data/blob requests attempted by page (excluding page itself):", JSON.stringify(requests));
fs.writeFileSync(path.join(spike, `dist/report-${browser_name}.json`), JSON.stringify(report, null, 1));
await browser.close();
