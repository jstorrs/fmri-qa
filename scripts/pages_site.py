"""Put the documentation site and the browser page together as the GitHub Pages site.

The documentation (`make docs`, build/site) is the site's root. The page
(`make web`, web/dist/fmri-qa.html) goes under `app/`, where its footer says
the latest version is (web/scripts/vite-build-info.mjs): `app/fmri-qa.html` is
the page itself, and `app/index.html` a short page that names that build and
offers to open or save it, with links to the documentation and the source.

Usage: python scripts/pages_site.py DOCS_SITE PAGE OUT
"""

import html
import re
import shutil
import sys
from pathlib import Path

APP = "app"
# The source, as the page's footer names it (web/scripts/vite-build-info.mjs).
REPOSITORY = "https://github.com/jstorrs/fmri-qa"
PAGE_NAME = "fmri-qa.html"

# The footer line the build writes, which starts
# <p id="build-info" data-version=".." data-commit="..">
_BUILD_INFO = re.compile(
    r'<p id="build-info" data-version="([^"]*)" data-commit="([^"]*)">'
)


def build_info(page: str) -> tuple[str, str]:
    """Return the page's (version, commit) from its footer.

    Raises ValueError when the page has no footer line, which means it was not
    built by `make web`.
    """
    match = _BUILD_INFO.search(page)
    if match is None:
        raise ValueError(
            'the page has no <p id="build-info">; build it with `make web`'
        )
    return html.unescape(match[1]), html.unescape(match[2])


def app_index(version: str, commit: str, size: int) -> str:
    """Return the `app/` landing page: which build is here, and how to open or save it.

    `size` is the page's size in bytes.
    """
    built = f", built from {commit[:7]}" if commit else ""
    name = html.escape(f"fmri-qa {version}{built}")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>fmri-qa in the browser</title>
<style>
body {{
  font: 16px/1.5 system-ui, sans-serif;
  max-width: 40rem; margin: 2rem auto; padding: 0 16px;
}}
</style>
</head>
<body>
<h1>fmri-qa in the browser</h1>
<p>{name}. The tool is one HTML file of {size / 1_000_000:.0f} MB.
It runs in your browser, offline, and sends nothing anywhere.</p>
<ul>
<li><a href="{PAGE_NAME}">Open it here</a></li>
<li><a href="{PAGE_NAME}" download="{PAGE_NAME}">Save it</a>
  to run from your own disk, with no network</li>
<li><a href="../">Documentation</a></li>
<li><a href="{REPOSITORY}">Source code on GitHub</a></li>
</ul>
</body>
</html>
"""


def assemble(docs: Path, page: Path, out: Path) -> None:
    """Write the site to `out`, which must not exist yet."""
    if not (docs / "index.html").is_file():
        raise ValueError(
            f"{docs}: no index.html; build the documentation with `make docs`"
        )
    if (docs / APP).exists():
        raise ValueError(f"{docs}: already has {APP}/, where the page goes")
    version, commit = build_info(page.read_text(encoding="utf-8"))
    shutil.copytree(docs, out)
    (out / APP).mkdir()
    shutil.copyfile(page, out / APP / PAGE_NAME)
    (out / APP / "index.html").write_text(
        app_index(version, commit, page.stat().st_size), encoding="utf-8"
    )


def main(argv: list[str]) -> None:
    """Assemble the site; exit non-zero, saying why, if it cannot."""
    if len(argv) != 3:
        sys.exit(__doc__)
    docs, page, out = map(Path, argv)
    if out.exists():
        sys.exit(f"{out}: already exists")
    try:
        assemble(docs, page, out)
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main(sys.argv[1:])
