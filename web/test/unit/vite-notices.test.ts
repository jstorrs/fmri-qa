// The build's check that every npm package with code in the page has a notice relies on naming each module's package.
import { describe, expect, test } from 'vitest';
import { packageOf } from '../../scripts/vite-notices.mjs';

describe('packageOf', () => {
  test.each([
    ['/w/node_modules/fflate/esm/browser.js', 'fflate'],
    ['/w/node_modules/@niivue/dcm2niix/dist/dcm2niix.jpeg.js', '@niivue/dcm2niix'],
    ['/w/node_modules/a/node_modules/b/index.js', 'b'],
    ['/w/node_modules/@s/a/node_modules/@t/b/lib/x.js', '@t/b'],
  ])('%s is %s', (id, name) => {
    expect(packageOf(id)).toBe(name);
  });

  test.each(['/w/src/main.ts', '\0rolldown/runtime.js', '__vite-browser-external', '/w/node_modules/'])('%s is no package', (id) => {
    expect(packageOf(id)).toBeNull();
  });
});
