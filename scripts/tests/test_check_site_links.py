"""The documentation site's link check, over small hand-written sites.

`make docs` trusts `check_site_links` to fail on a link Sphinx cannot see is
broken, so a checker that quietly passes everything would leave that gap open
with the gate still green. Each test builds a site of a few pages under
`tmp_path` and asks which links it reports.
"""

from pathlib import Path

import pytest
from check_site_links import broken_links, main


def _site(root: Path, pages: dict[str, str]) -> Path:
    """Write each page's body under `root/site`, and return the site root."""
    site = root / "site"
    for name, body in pages.items():
        page = site / name
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return site


def test_a_link_to_a_missing_page_is_reported(tmp_path: Path) -> None:
    site = _site(tmp_path, {"index.html": '<a href="gone.html">x</a>'})
    assert broken_links(site) == ["index.html: gone.html"]


def test_a_link_to_an_existing_page_resolves(tmp_path: Path) -> None:
    site = _site(
        tmp_path,
        {
            "index.html": '<a href="core/page.html">x</a>',
            "core/page.html": '<a href="../index.html">x</a>',
        },
    )
    assert broken_links(site) == []


@pytest.mark.parametrize("href", ["core/", "core", "."])
def test_a_directory_resolves_to_its_index(tmp_path: Path, href: str) -> None:
    site = _site(
        tmp_path,
        {"index.html": f'<a href="{href}">x</a>', "core/index.html": ""},
    )
    assert broken_links(site) == []


def test_a_directory_without_an_index_is_reported(tmp_path: Path) -> None:
    site = _site(
        tmp_path, {"index.html": '<a href="core/">x</a>', "core/page.html": ""}
    )
    assert broken_links(site) == ["index.html: core/"]


def test_a_query_and_a_fragment_are_stripped(tmp_path: Path) -> None:
    site = _site(
        tmp_path,
        {
            "index.html": (
                '<link href="style.css?v=1a2b">'
                '<a href="page.html#section">x</a>'
                '<a href="#top">x</a>'
            ),
            "page.html": "",
            "style.css": "",
        },
    )
    assert broken_links(site) == []


@pytest.mark.parametrize(
    "href", ["mailto:someone@example.org", "https://example.org/x", "//host/x"]
)
def test_an_external_link_is_not_followed(tmp_path: Path, href: str) -> None:
    site = _site(tmp_path, {"index.html": f'<a href="{href}">x</a>'})
    assert broken_links(site) == []


def test_a_percent_encoded_name_resolves(tmp_path: Path) -> None:
    site = _site(
        tmp_path,
        {"index.html": '<img src="a%20figure.png">', "a figure.png": ""},
    )
    assert broken_links(site) == []


def test_a_link_escaping_the_site_is_reported(tmp_path: Path) -> None:
    (tmp_path / "outside.html").write_text("", encoding="utf-8")
    site = _site(tmp_path, {"index.html": '<a href="../outside.html">x</a>'})
    assert broken_links(site) == ["index.html: ../outside.html"]


def test_a_root_absolute_link_is_reported(tmp_path: Path) -> None:
    site = _site(
        tmp_path, {"index.html": '<a href="/index.html">x</a>', "other.html": ""}
    )
    assert broken_links(site) == ["index.html: /index.html"]


def test_main_passes_a_clean_site(tmp_path: Path) -> None:
    site = _site(tmp_path, {"index.html": '<a href="index.html">x</a>'})
    main([str(site)])


def test_main_fails_on_a_broken_link(tmp_path: Path) -> None:
    site = _site(tmp_path, {"index.html": '<a href="gone.html">x</a>'})
    with pytest.raises(SystemExit) as info:
        main([str(site)])
    assert "index.html: gone.html" in str(info.value.code)


def test_main_fails_on_a_site_with_no_pages(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as info:
        main([str(tmp_path)])
    assert "no HTML pages" in str(info.value.code)


@pytest.mark.parametrize("argv", [[], ["a", "b"]])
def test_main_without_one_argument_exits_with_the_usage(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(argv)
    assert "Usage:" in str(info.value.code)
