// Writes which build this page is, and where to find a newer one, into the footer of dist/fmri-qa.html.
// The page is a file people keep and pass on, so it says its version, the commit it was built from and that
// commit's date, and links to the published site (the latest build) and the repository. The date is the
// commit's, not the clock's, so two builds of one commit are the same page.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const REPOSITORY = 'https://github.com/jstorrs/fmri-qa';
export const SITE = 'https://jstorrs.github.io/fmri-qa/';
/** The latest build of this page on the site (scripts/pages_site.py puts it there). */
export const APP = `${SITE}app/`;
/** Where index.html wants the footer line. */
export const MARKER = '<!--build-info-->';

const WEB_PYPROJECT = fileURLToPath(new URL('../../packages/fmri-qa-web/pyproject.toml', import.meta.url));

/** The page's version: fmri-qa-web's, the distribution whose Python the page runs. */
export const projectVersion = (pyproject = readFileSync(WEB_PYPROJECT, 'utf8')) => {
  // The [project] table runs to the next table header, a line starting with `[`.
  const table = /^\[project\][ \t]*$([\s\S]*?)(?=^\[|(?![\s\S]))/m.exec(pyproject)?.[1] ?? '';
  const match = /^version\s*=\s*"([^"]+)"/m.exec(table);
  if (!match) throw new Error('build-info: no [project] version in packages/fmri-qa-web/pyproject.toml');
  return match[1];
};

const git = (...args) => execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();

/**
 * The commit the page is built from: `{ sha, date, modified }`, or null outside a git checkout. `modified` is
 * true when tracked files differ from that commit, so a local build with edits does not pass for the commit.
 */
export const readCommit = () => {
  try {
    const [sha, date] = git('show', '-s', '--format=%H %cs', 'HEAD').split(' ');
    const modified = git('status', '--porcelain', '--untracked-files=no') !== '';
    return { sha, date, modified };
  } catch {
    return null;
  }
};

const escape = (text) =>
  String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

// Following a link must not lose the work on the page, so each opens in a new tab.
const link = (href, text) => `<a href="${escape(href)}" target="_blank" rel="noopener noreferrer">${escape(text)}</a>`;

const bare = (url) => url.replace(/^https:\/\//, '');

/** The footer line, as HTML. */
export const renderBuildInfo = ({ version, commit }) => {
  let built;
  if (commit === null) built = 'built outside a git checkout';
  else {
    const short = commit.sha.slice(0, 7);
    const edits = commit.modified ? ', with local changes' : '';
    built = `built from ${link(`${REPOSITORY}/commit/${commit.sha}`, short)} (${escape(commit.date)}${edits})`;
  }
  return (
    `<p id="build-info" data-version="${escape(version)}" data-commit="${escape(commit?.sha ?? '')}">` +
    `fmri-qa ${escape(version)}, ${built}. ` +
    `The latest version is at ${link(APP, bare(APP))}, with the ${link(SITE, 'documentation')}; ` +
    `the source is on ${link(REPOSITORY, 'GitHub')}.</p>`
  );
};

/** Put the footer line in place of MARKER, which must be there exactly once. */
export const injectBuildInfo = (html, info) => {
  const parts = html.split(MARKER);
  if (parts.length !== 2) throw new Error(`build-info: index.html must hold ${MARKER} exactly once, not ${parts.length - 1} times`);
  return parts.join(renderBuildInfo(info));
};

/** The Vite plugin. The version and commit are read once per build. */
export const buildInfo = () => {
  let info;
  return {
    name: 'build-info',
    transformIndexHtml(html) {
      info ??= { version: projectVersion(), commit: readCommit() };
      return injectBuildInfo(html, info);
    },
  };
};
