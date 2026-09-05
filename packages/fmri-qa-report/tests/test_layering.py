"""The seam: the report half may read the artifact, and nothing else.

The whole point of the split is that presentation depends on the *published
artifact*, not on the pipeline that produced it. That is easy to state and easy
to erode one convenient import at a time, so it is checked mechanically here:
every `fmriqc` import in the report package must land in `fmriqc.analysis` (the
artifact) or `fmriqc.types` (the shared array/option vocabulary). An import of
`fmriqc.metrics`, `fmriqc.pipeline`, `fmriqc.prep`, or `fmriqc.load` — or of the
`fmriqc` package as a whole, which pulls all of them — fails this test.
"""

import ast
from pathlib import Path

import fmriqc_report

# The only calculation-side modules presentation is allowed to reach for.
ALLOWED = frozenset({"fmriqc.analysis", "fmriqc.types"})

_SOURCE_ROOT = Path(fmriqc_report.__file__).parent


def _modules() -> list[Path]:
    """Every source file in the report package."""
    return sorted(_SOURCE_ROOT.rglob("*.py"))


def _from_fmriqc(module: str) -> bool:
    """True if a dotted module name names the calculation package."""
    return module.split(".", maxsplit=1)[0] == "fmriqc"


def _fmriqc_imports(tree: ast.Module) -> set[str]:
    """The `fmriqc*` modules a parsed source file imports."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names if _from_fmriqc(a.name)}
        # `level > 0` is a relative import inside fmriqc_report itself.
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and _from_fmriqc(node.module)
        ):
            found.add(node.module)
    return found


def test_the_report_package_has_source_to_check() -> None:
    """Guard the guard: an empty scan must not pass silently."""
    assert len(_modules()) >= 8


def test_report_imports_only_the_artifact_and_the_shared_vocabulary() -> None:
    offenders = {}
    for path in _modules():
        imported = _fmriqc_imports(ast.parse(path.read_text()))
        if extra := imported - ALLOWED:
            offenders[path.relative_to(_SOURCE_ROOT).as_posix()] = sorted(extra)
    assert not offenders, (
        f"the report half must depend only on {sorted(ALLOWED)}; found {offenders}"
    )


def test_the_check_would_catch_a_pipeline_import() -> None:
    """A negative control, so the scan cannot pass by failing to see anything."""
    tree = ast.parse("import fmriqc\nfrom fmriqc.pipeline import run_qa\n")
    assert _fmriqc_imports(tree) - ALLOWED == {"fmriqc", "fmriqc.pipeline"}
