"""Check that every relative link in a built documentation site resolves.

`sphinx-build -W` fails on a reference it cannot resolve, but it only sees one
project at a time: it cannot see a link into a sibling project written with the
wrong relative prefix, a sibling that was never built, or a broken link back up
to the landing page. This walks the finished site and follows every local link,
which must land on a file inside the site.

Usage: python scripts/check_site_links.py SITE_ROOT
"""

import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

LINK_ATTRIBUTES = {"a": "href", "link": "href", "img": "src", "script": "src"}


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        url = dict(attrs).get(LINK_ATTRIBUTES.get(tag, ""))
        if url:
            self.urls.append(url)


def _resolves(site: Path, page: Path, url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme or parts.netloc or not parts.path:
        return True  # External, mailto:, or a fragment on this page.
    path = unquote(parts.path)
    if path.startswith("/"):
        return False  # Sphinx never writes one, and it breaks under a subpath.
    target = (page.parent / path).resolve()
    if target.is_dir():
        target /= "index.html"
    return target.is_relative_to(site.resolve()) and target.is_file()


def broken_links(site: Path) -> list[str]:
    """Return "page: url" for every local link under `site` that does not resolve."""
    broken = []
    for page in sorted(site.rglob("*.html")):
        parser = _Links()
        parser.feed(page.read_text(encoding="utf-8"))
        broken += [
            f"{page.relative_to(site)}: {url}"
            for url in parser.urls
            if not _resolves(site, page, url)
        ]
    return broken


def main(argv: list[str]) -> None:
    """Check the built site at `argv[0]`; exit non-zero on a bad link.

    Also exits non-zero, printing usage, on a wrong argument count, and when the
    site has no HTML pages.
    """
    if len(argv) != 1:
        sys.exit(__doc__)
    site = Path(argv[0])
    if not any(site.rglob("*.html")):
        sys.exit(f"{site}: no HTML pages to check")
    if broken := broken_links(site):
        sys.exit("links that do not resolve:\n" + "\n".join(broken))


if __name__ == "__main__":
    main(sys.argv[1:])
