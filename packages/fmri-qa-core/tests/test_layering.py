"""The stack: `load < prep < metrics < pipeline < analysis`, checked mechanically.

`style/architecture.md` ("Layered Subpackages") states the rule -- dependencies
point down the stack, a lower layer never imports a higher one -- and warns that
such a rule "erodes one convenient import at a time," so it has to be checked
mechanically rather than trusted to code review. `fmri-qa-report/tests/
test_layering.py` checks the *outer* seam, that presentation never reaches back
into calculation; this is its sibling for the seams *inside* calculation.
"""

import ast
from pathlib import Path

import fmriqc

# Rank of each top-level module/subpackage in the stack, low to high. A module
# may import anything at its own rank or below; importing a strictly higher
# rank is the violation this test exists to catch.
RANKS = {
    "types": 0,
    "exceptions": 0,
    "_arrays": 0,
    "load": 1,
    "prep": 2,
    "validation": 2,
    "metrics": 3,
    "pipeline": 4,
    "hilo": 4,
    "analysis": 5,
    "cli": 6,
}

_SOURCE_ROOT = Path(fmriqc.__file__).parent


def _modules() -> list[Path]:
    """Every source file in the core package."""
    return sorted(_SOURCE_ROOT.rglob("*.py"))


def _rel_parts(path: Path) -> tuple[str, ...]:
    """A file's module path below the package root, as a tuple of parts.

    `__init__` is kept as a literal trailing part rather than collapsed away.
    That is what makes `node.level` resolve the same way (`rel[:-level]`) for
    a package's `__init__.py` as for an ordinary module: Python itself treats
    one dot in an `__init__.py` as "this package," which is exactly what a
    trailing `__init__` component produces once it is sliced off.
    """
    return path.relative_to(_SOURCE_ROOT).with_suffix("").parts


def _layer(parts: tuple[str, ...]) -> int | None:
    """The rank of `parts`, or `None` if its first element is not in `RANKS`."""
    return RANKS.get(parts[0]) if parts else None


def _import_targets(tree: ast.Module, rel: tuple[str, ...]) -> set[tuple[str, ...]]:
    """Every module `tree` (the source file at `rel`) imports, as resolved parts.

    Covers both forms the core sources use: the relative imports (`node.level >
    0`) everything but `cli/` writes internally, and the absolute `fmriqc...`
    imports `cli/` uses instead (`import fmriqc as q`, `from fmriqc.load.paths
    import ...`).
    """
    targets: set[tuple[str, ...]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "fmriqc" or alias.name.startswith("fmriqc."):
                    targets.add(tuple(alias.name.split(".")[1:]))
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                base = rel[: -node.level]
                module_parts = node.module.split(".") if node.module else ()
                targets.add(base + tuple(module_parts))
            elif node.module and (
                node.module == "fmriqc" or node.module.startswith("fmriqc.")
            ):
                targets.add(tuple(node.module.split(".")[1:]))
    return targets


def test_the_core_package_has_source_to_check() -> None:
    """Guard the guard: an empty scan must not pass silently."""
    assert len(_modules()) >= 20


def test_layers_never_import_upward() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _modules():
        rel = _rel_parts(path)
        source_layer = _layer(rel)
        if source_layer is None:
            continue  # `__init__.py` / `__main__.py`: the aggregator, not a layer.
        tree = ast.parse(path.read_text())
        for target in _import_targets(tree, rel):
            target_layer = _layer(target)
            if target_layer is None or target_layer <= source_layer:
                continue
            offenders.setdefault(path.relative_to(_SOURCE_ROOT).as_posix(), []).append(
                f"fmriqc.{'.'.join(target)} (rank {target_layer}) "
                f"from rank {source_layer}"
            )
    assert not offenders, f"a lower layer must never import a higher one: {offenders}"


def test_every_top_level_module_is_ranked() -> None:
    """Guard the guard again: an unranked module is an unchecked one.

    `_layer` answers `None` for anything outside `RANKS`, and the scan skips
    what it cannot rank -- so a new top-level module added without an entry
    here would be exempt from the rule rather than held to it, silently. Only
    the package aggregators are legitimately unranked.
    """
    exempt = {"__init__", "__main__"}
    top_level = {
        entry.stem if entry.is_file() else entry.name
        for entry in _SOURCE_ROOT.iterdir()
        if (entry.is_file() and entry.suffix == ".py")
        or (entry.is_dir() and (entry / "__init__.py").is_file())
    }
    unranked = top_level - exempt - set(RANKS)
    assert not unranked, (
        f"{sorted(unranked)} sit outside RANKS, so the layering scan skips "
        f"them; give each one its rank in the stack"
    )


def test_the_check_would_catch_an_upward_import() -> None:
    """A negative control, so the scan cannot pass by failing to see anything."""
    tree = ast.parse("from ..metrics.ghost import GHOST_RADIUS\n")
    rel = ("load", "paths")  # load/paths.py, rank 1
    assert _import_targets(tree, rel) == {("metrics", "ghost")}
    assert RANKS["load"] < RANKS["metrics"]
