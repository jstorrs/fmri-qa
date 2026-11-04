// Injected before page scripts (see hooksSource in browsers.mjs). Test-only; never part of the build.
// Adapted from dicom-util's e2e/init-hooks.js at fe0d59e, keeping only what this page needs:
// - every `securitypolicyviolation` the page's document sees, from before any page script runs, in window.__cspViolations
//   (the worker reports its own through the page: window.__fmriqa.diagnostics().violations; one inside the srcdoc
//   preview iframe reaches neither, so it is not observed);
// - every a[download] blob download, captured instead of saved, in window.__downloads as {name, b64} (or {name, error}).
(() => {
  window.__cspViolations = [];
  document.addEventListener('securitypolicyviolation', (e) => {
    window.__cspViolations.push(`${e.effectiveDirective} ${e.blockedURI} ${e.sourceFile}:${e.lineNumber}`);
  });

  window.__downloads = [];
  const toB64 = async (blob) => {
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(s);
  };
  // Remember every Blob behind a blob: URL, so the click hook reads it without a fetch (the CSP allows none).
  const blobs = new Map();
  const origCreate = URL.createObjectURL.bind(URL);
  URL.createObjectURL = (obj) => {
    const url = origCreate(obj);
    if (obj instanceof Blob) blobs.set(url, obj);
    return url;
  };
  const origClick = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function () {
    if (!this.hasAttribute('download') || !this.href.startsWith('blob:')) return origClick.call(this);
    const name = this.getAttribute('download');
    const blob = blobs.get(this.href);
    if (!blob) {
      window.__downloads.push({ name, error: 'unknown blob URL' });
      return;
    }
    toB64(blob)
      .then((b64) => window.__downloads.push({ name, b64 }))
      .catch((e) => window.__downloads.push({ name, error: String(e) }));
  };
})();
