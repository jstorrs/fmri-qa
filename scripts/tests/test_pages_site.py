"""The GitHub Pages site: the documentation with the browser page under app/.

Each test assembles a site from a hand-written documentation tree and page
under `tmp_path`.
"""

from pathlib import Path

import pytest
from check_site_links import broken_links
from pages_site import assemble, build_info, main

PAGE = (
    "<html><body><footer>"
    '<p id="build-info" data-version="0.1.0" '
    'data-commit="8ec80a3929eecf334b2a200c34e3c14a37ebc700">fmri-qa 0.1.0</p>'
    "</footer></body></html>"
)


def _inputs(root: Path, page: str = PAGE) -> tuple[Path, Path]:
    docs = root / "docs"
    (docs / "_static").mkdir(parents=True)
    (docs / "index.html").write_text("<html><body>docs</body></html>", encoding="utf-8")
    (docs / "_static" / "x.css").write_text("", encoding="utf-8")
    page_path = root / "fmri-qa.html"
    page_path.write_text(page, encoding="utf-8")
    return docs, page_path


def test_the_docs_are_the_root_and_the_page_is_under_app(tmp_path: Path) -> None:
    docs, page = _inputs(tmp_path)
    out = tmp_path / "out"
    assemble(docs, page, out)
    assert (out / "index.html").read_text(
        encoding="utf-8"
    ) == "<html><body>docs</body></html>"
    assert (out / "_static" / "x.css").is_file()
    assert (out / "app" / "fmri-qa.html").read_text(encoding="utf-8") == PAGE
    landing = (out / "app" / "index.html").read_text(encoding="utf-8")
    assert "fmri-qa 0.1.0, built from 8ec80a3." in landing
    assert '<a href="fmri-qa.html" download="fmri-qa.html">' in landing
    assert '<a href="https://github.com/jstorrs/fmri-qa">' in landing
    assert broken_links(out) == []


def test_a_page_without_the_footer_line_is_refused(tmp_path: Path) -> None:
    docs, page = _inputs(tmp_path, "<html><body></body></html>")
    with pytest.raises(ValueError, match="build-info"):
        assemble(docs, page, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_docs_that_already_have_app_are_refused(tmp_path: Path) -> None:
    docs, page = _inputs(tmp_path)
    (docs / "app").mkdir()
    with pytest.raises(ValueError, match="app/"):
        assemble(docs, page, tmp_path / "out")


def test_build_info_unescapes_and_allows_no_commit() -> None:
    assert build_info('<p id="build-info" data-version="1&amp;2" data-commit="">') == (
        "1&2",
        "",
    )


def test_main_refuses_an_existing_output(tmp_path: Path) -> None:
    docs, page = _inputs(tmp_path)
    (tmp_path / "out").mkdir()
    with pytest.raises(SystemExit, match="already exists"):
        main([str(docs), str(page), str(tmp_path / "out")])
