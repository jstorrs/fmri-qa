"""The analysis pages and the netCDF layout, checked against each other.

`docs/analyses/` documents what each analysis contributes to the artifact, under
the exact names a reader sees in the file. That is a claim about the serializer,
and a claim in prose rots silently: a variable added to `_LAYOUT` with no page to
name it is undocumented, a page naming a variable that was renamed sends a reader
looking for something that is not there, and the same name on two pages means
neither owns it. `test_layering.py` makes the same argument for the import
stack -- a rule that erodes one edit at a time has to be checked mechanically.

So every variable in the serializer's `_LAYOUT`, every coordinate in
`_COORDINATES`, and every `Measurements` field must appear in exactly one
analysis page's contribution table, and every `Provenance` field must be named
in `artifact.md`.

Both tables are private to `analysis.serialize.netcdf`, and this imports them
anyway. They are the layout itself -- the published claim these pages are
checked against -- and a public accessor would exist only for this test, which
is a worse trade than a test reaching one module deep into the package it
tests. If a second consumer ever needs them, that is when they become public.

Two spellings are checked, for two different mistakes:

* **The contribution tables** (the first column of the table under "What it
  contributes to the artifact") are the ownership claim, so coverage and
  uniqueness are measured there. A dimension name like `frame` is an ordinary
  English word that appears in half the prose on these pages; only the table
  column can say which page *owns* it.
* **The whole page** is scanned for dotted names in backticks (`curves.x`,
  `images.x`, `measurements.x`, `provenance.x`), which are unambiguous wherever
  they appear, so a stale name in a sentence is caught too. Document-only
  fields (the `roi` box, `outlier_qthr`, the `psf` block) are deliberately
  written without a dotted prefix, since they are not variables.
"""

import re
from dataclasses import fields
from pathlib import Path

import fmriqc
from fmriqc.analysis.artifact import AnalysisSettings, Measurements, Provenance
from fmriqc.analysis.serialize.netcdf import _COORDINATES, _LAYOUT

DOCS = Path(fmriqc.__file__).parents[2] / "docs"
ANALYSES = DOCS / "analyses"

# The heading whose table is the page's ownership claim.
CONTRIBUTION_HEADING = "## What it contributes to the artifact"

# A dotted name in backticks, anywhere on a page. The four prefixes are the ones
# that name something the artifact actually holds.
DOTTED = re.compile(
    r"`(curves|images|measurements|provenance|settings)\.([A-Za-z0-9_.]+)`"
)

# A backticked name in a table cell.
CELL_NAME = re.compile(r"`([A-Za-z0-9_.]+)`")


def _pages() -> list[Path]:
    """Every analysis page, index excluded."""
    return sorted(p for p in ANALYSES.glob("*.md") if p.name != "index.md")


def _contribution_names(page: Path) -> list[str]:
    """The backticked names in the first column of `page`'s contribution table.

    An analysis that contributes nothing to the artifact (the hi/lo flip-angle
    pair) has the heading and no table, and yields nothing.
    """
    body = page.read_text().split(CONTRIBUTION_HEADING, 1)
    if len(body) != 2:
        return []
    names = []
    for line in body[1].split("\n"):
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        first_cell = line.split("|")[1]
        names.extend(CELL_NAME.findall(first_cell))
    return names


def _owners() -> dict[str, list[str]]:
    """Which page(s) claim each name, keyed by name."""
    owners: dict[str, list[str]] = {}
    for page in _pages():
        for name in _contribution_names(page):
            owners.setdefault(name, []).append(page.name)
    return owners


def _expected() -> dict[str, set[str]]:
    """Every name the artifact publishes, grouped by what kind of name it is."""
    return {
        "variable": set(_LAYOUT),
        "coordinate": set(_COORDINATES),
        "measurement": {f"measurements.{f.name}" for f in fields(Measurements)},
    }


def test_the_analysis_pages_are_there_to_check() -> None:
    """Guard the guard: an empty scan must not pass silently."""
    pages = _pages()
    assert len(pages) >= 8, f"expected one page per analysis, found {len(pages)}"
    assert (DOCS / "artifact.md").is_file()
    tabled = [p.name for p in pages if _contribution_names(p)]
    assert len(tabled) >= 7, f"only {tabled} carry a contribution table"


def test_every_published_name_is_documented_exactly_once() -> None:
    owners = _owners()
    missing: dict[str, list[str]] = {}
    duplicated: dict[str, list[str]] = {}
    for kind, names in _expected().items():
        for name in sorted(names):
            pages = owners.get(name, [])
            if not pages:
                missing.setdefault(kind, []).append(name)
            elif len(pages) > 1:
                duplicated[name] = pages
    assert not missing, f"published but documented on no analysis page: {missing}"
    assert not duplicated, f"claimed by more than one analysis page: {duplicated}"


def test_no_page_claims_a_name_the_artifact_does_not_publish() -> None:
    known = set().union(*_expected().values())
    unknown = {name: pages for name, pages in _owners().items() if name not in known}
    assert not unknown, (
        f"named in a contribution table but absent from the netCDF layout: {unknown}"
    )


def test_pages_never_spell_a_name_that_does_not_exist() -> None:
    """Every dotted name in backticks, table or prose, must be a real one."""
    known = set().union(*_expected().values())
    known |= {f"provenance.{f.name}" for f in fields(Provenance)}
    known |= {f"settings.{f.name}" for f in fields(AnalysisSettings)}
    offenders: dict[str, list[str]] = {}
    for page in [*_pages(), DOCS / "artifact.md"]:
        text = page.read_text()
        for section, rest in DOTTED.findall(text):
            name = f"{section}.{rest}"
            if name not in known:
                offenders.setdefault(page.name, []).append(name)
    assert not offenders, f"named in the docs but not in the artifact: {offenders}"


def test_every_setting_is_named_in_the_artifact_page() -> None:
    text = (DOCS / "artifact.md").read_text()
    undocumented = [
        f.name for f in fields(AnalysisSettings) if f"`settings.{f.name}`" not in text
    ]
    assert not undocumented, f"settings missing from artifact.md: {undocumented}"


def test_every_provenance_field_is_named_in_the_artifact_page() -> None:
    text = (DOCS / "artifact.md").read_text()
    undocumented = [
        f.name for f in fields(Provenance) if f"`provenance.{f.name}`" not in text
    ]
    assert not undocumented, (
        f"provenance fields missing from artifact.md: {undocumented}"
    )


def test_the_check_would_notice_an_undocumented_variable() -> None:
    """A negative control, so coverage cannot pass by measuring nothing."""
    owners = _owners()
    assert "curves.weisskoff.cv" in owners
    assert "curves.weisskoff.cv_ideal" in owners  # not swallowed as a prefix match
    assert "images.does.not.exist" not in owners
