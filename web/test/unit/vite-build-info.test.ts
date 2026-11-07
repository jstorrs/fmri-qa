// The footer line that says which build the page is and where a newer one is (scripts/vite-build-info.mjs).
import { describe, expect, test } from 'vitest';
import {
  APP,
  injectBuildInfo,
  MARKER,
  projectVersion,
  readCommit,
  renderBuildInfo,
  REPOSITORY,
  SITE,
} from '../../scripts/vite-build-info.mjs';

const SHA = '8ec80a3c0ffee0000000000000000000000000ab';
const COMMIT = { sha: SHA, date: '2026-11-07', modified: false };

const links = (html: string): [string, string][] =>
  [...html.matchAll(/<a href="([^"]*)" target="_blank" rel="noopener noreferrer">([^<]*)<\/a>/g)].map((m) => [m[1]!, m[2]!]);

describe('renderBuildInfo', () => {
  test('names the version, the commit and its date, and links the site and the repository', () => {
    const html = renderBuildInfo({ version: '0.1.0', commit: COMMIT });
    expect(html).toContain('fmri-qa 0.1.0, built from ');
    expect(html).toContain('(2026-11-07)');
    expect(html).toContain(`data-commit="${SHA}"`);
    expect(links(html)).toEqual([
      [`${REPOSITORY}/commit/${SHA}`, '8ec80a3'],
      [APP, 'jstorrs.github.io/fmri-qa/app/'],
      [SITE, 'documentation'],
      [REPOSITORY, 'GitHub'],
    ]);
    // Every link opens in a new tab: following one must not lose the page's work.
    expect(html.match(/<a /g)).toHaveLength(4);
  });

  test('says when the tree had local changes', () => {
    expect(renderBuildInfo({ version: '0.1.0', commit: { ...COMMIT, modified: true } })).toContain(
      '(2026-11-07, with local changes)',
    );
  });

  test('outside a git checkout it still links the site and the repository', () => {
    const html = renderBuildInfo({ version: '0.1.0', commit: null });
    expect(html).toContain('fmri-qa 0.1.0, built outside a git checkout.');
    expect(html).toContain('data-commit=""');
    expect(links(html).map(([href]) => href)).toEqual([APP, SITE, REPOSITORY]);
  });

  test('escapes what it is given', () => {
    const html = renderBuildInfo({ version: '1<2&"3"', commit: null });
    expect(html).toContain('fmri-qa 1&lt;2&amp;&quot;3&quot;,');
    expect(html).not.toContain('1<2');
  });
});

describe('injectBuildInfo', () => {
  test('replaces the marker', () => {
    const out = injectBuildInfo(`<footer>${MARKER}</footer>`, { version: '0.1.0', commit: null });
    expect(out).toMatch(/^<footer><p id="build-info" [^>]*>.*<\/p><\/footer>$/);
  });

  test.each([
    ['missing', '<footer></footer>'],
    ['twice', `${MARKER}${MARKER}`],
  ])('fails when the marker is %s', (_, html) => {
    expect(() => injectBuildInfo(html, { version: '0.1.0', commit: null })).toThrow(/exactly once/);
  });
});

describe('projectVersion', () => {
  test('reads the [project] version', () => {
    expect(projectVersion('[build-system]\nrequires = []\n\n[project]\nname = "x"\nversion = "1.2.3"\n')).toBe('1.2.3');
  });

  test('ignores a version outside [project]', () => {
    expect(() => projectVersion('[tool.x]\nversion = "9"\n\n[project]\nname = "x"\n')).toThrow(/no \[project\] version/);
  });

  test("reads fmri-qa-web's own pyproject.toml", () => {
    expect(projectVersion()).toMatch(/^\d+\.\d+\.\d+/);
  });
});

test('readCommit reads this checkout', () => {
  const commit = readCommit();
  expect(commit).not.toBeNull();
  expect(commit!.sha).toMatch(/^[0-9a-f]{40}$/);
  expect(commit!.date).toMatch(/^\d{4}-\d{2}-\d{2}$/);
});
