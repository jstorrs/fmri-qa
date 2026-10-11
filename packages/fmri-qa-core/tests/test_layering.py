"""The stack: `load < prep < metrics < pipeline < analysis`, checked mechanically.

`style/architecture.md` ("Layered Subpackages") says dependencies point down
the stack and warns that such a rule "erodes one convenient import at a time",
so this checks it mechanically. `fmri-qa-report/tests/test_layering.py` covers
the outer seam (presentation never reaches back into calculation). This covers
the seams inside calculation.
"""

import ast
from pathlib import Path

import fmriqc

# Rank of each top-level module/subpackage in the stack, low to high. A module
# may import its own rank or below; importing a higher rank is the violation.
RANKS = {
    "types": 0,
    "exceptions": 0,
    "_arrays": 0,
    "version": 0,
    "warn": 0,
    "_records": 0,
    "settings": 0,
    # A leaf over the standard library only. `convert` files its series with
    # it, and so does the launcher, from outside this package.
    "rename": 0,
    # A leaf over the standard library only, shared with the report command.
    "path_arguments": 0,
    "load": 1,
    # `convert` sits beside `load`: both get data in, and convert produces the files
    # load reads. It borrows load's path conventions, which a rank below load
    # would forbid.
    "convert": 1,
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

    `__init__` is kept as a trailing part so `node.level` resolves the same way
    (`rel[:-level]`) for a package's `__init__.py` as for any module. Python
    treats one dot in an `__init__.py` as "this package", which is what the
    trailing component gives once sliced off.
    """
    return path.relative_to(_SOURCE_ROOT).with_suffix("").parts


def _layer(parts: tuple[str, ...]) -> int | None:
    """The rank of `parts`, or `None` if its first element is not in `RANKS`."""
    return RANKS.get(parts[0]) if parts else None


def _import_targets(tree: ast.Module, rel: tuple[str, ...]) -> set[tuple[str, ...]]:
    """Every module `tree` (the source file at `rel`) imports, as resolved parts.

    Covers relative imports (`node.level > 0`) everywhere but `cli/`, and the
    absolute `fmriqc...` imports `cli/` uses (`import fmriqc as q`,
    `from fmriqc.load.paths import ...`).
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
    """An empty scan must not pass silently."""
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
    """An unranked module is an unchecked one.

    `_layer` answers `None` outside `RANKS`, and the scan skips what it cannot
    rank, so a new top-level module without an entry would silently escape the
    rule. Only the package aggregators are legitimately unranked.
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
    """Negative control: the scan must not pass by seeing nothing."""
    tree = ast.parse("from ..metrics.ghost import GHOST_RADIUS\n")
    rel = ("load", "paths")  # load/paths.py, rank 1
    assert _import_targets(tree, rel) == {("metrics", "ghost")}
    assert RANKS["load"] < RANKS["metrics"]


def test_calculation_never_imports_the_launcher() -> None:
    """The application shell depends on `fmriqc`, never the other way around."""
    offenders = [
        path.relative_to(_SOURCE_ROOT).as_posix()
        for path in _modules()
        if "fmriqc_launcher" in path.read_text()
    ]
    assert not offenders, (
        f"the calculation half must never import fmriqc_launcher: {offenders}"
    )
