// Injected before page scripts (see hooksSource in browsers.mjs). Test-only; never part of the build.
// Adapted from dicom-util's e2e/init-hooks.js at fe0d59e, keeping only what this page needs: it records every
// `securitypolicyviolation` the page's document sees, from before any page script runs, in window.__cspViolations.
// (The worker reports its own through the page: window.__fmriqa.diagnostics().violations.)
(() => {
  window.__e2eKeepOutputs = true; // the page keeps the last conversion's bytes for window.__fmriqa.output
  window.__cspViolations = [];
  document.addEventListener('securitypolicyviolation', (e) => {
    window.__cspViolations.push(`${e.effectiveDirective} ${e.blockedURI} ${e.sourceFile}:${e.lineNumber}`);
  });
})();
