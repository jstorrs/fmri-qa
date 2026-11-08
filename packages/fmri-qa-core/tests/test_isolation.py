"""Core reads no files: it imports no file format, no IO package, no process.

`fmri-qa-core` runs under Pyodide in a browser page, handed decoded scans, so
it must stand up on numpy, scipy and scikit-image alone. Decoding NIfTI is
`fmriqa_io`'s, and so are the analysis-file container and the DICOM converter. This
checks the rule three ways: statically, over every import in every source file
(function-local ones included); at runtime, by importing every module in a
fresh interpreter; and in the installed distribution's declared requirements.
"""

import ast
import subprocess
import sys
from importlib.metadata import requires
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

import fmriqa

_SOURCE_ROOT = Path(fmriqa.__file__).parent

# Top-level packages core must never import, at any depth of a source file.
_FORBIDDEN = frozenset(
    {
        "nibabel",
        "netCDF4",
        "dcm2niix",
        "subprocess",
        "fmriqa_io",
        "fmriqa_cli",
        "fmriqa_report",
        "fmriqa_launcher",
    }
)

# The third-party libraries a full import of core must not have loaded.
_FORBIDDEN_AT_RUNTIME = ("nibabel", "netCDF4", "dcm2niix")

# Run in a fresh interpreter: this process has io and nibabel loaded by other
# tests. Resolves every public name, then imports every submodule, so a
# function-local or lazy import behind either is executed too.
_PROBE = f"""
import importlib
import pkgutil
import sys

import fmriqa

{{extra}}
for name in fmriqa.__all__:
    getattr(fmriqa, name)
for module in pkgutil.walk_packages(fmriqa.__path__, "fmriqa."):
    importlib.import_module(module.name)
forbidden = {_FORBIDDEN_AT_RUNTIME!r}
print(sorted(m for m in forbidden if m in sys.modules))
"""


def _imported_roots(tree: ast.Module) -> set[str]:
    """The top-level package of every absolute import anywhere in `tree`."""
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def _run_probe(extra: str = "") -> str:
    """Run `_PROBE` with `extra` after `import fmriqa`; return the loaded list."""
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _PROBE.format(extra=extra)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _names(lines: list[str]) -> set[str]:
    """The canonical distribution names in requirement `lines`."""
    return {canonicalize_name(Requirement(line).name) for line in lines}


def test_core_source_imports_nothing_forbidden() -> None:
    paths = sorted(_SOURCE_ROOT.rglob("*.py"))
    assert len(paths) >= 20  # an empty scan must not pass silently
    offenders = {
        path.relative_to(_SOURCE_ROOT).as_posix(): sorted(found)
        for path in paths
        if (found := _imported_roots(ast.parse(path.read_text())) & _FORBIDDEN)
    }
    assert not offenders, f"core must not import these: {offenders}"


def test_the_scan_sees_a_function_local_import() -> None:
    """Negative control: an import inside a function body is still found."""
    tree = ast.parse("def f():\n    from nibabel import load\n    import subprocess\n")
    assert _imported_roots(tree) & _FORBIDDEN == {"nibabel", "subprocess"}


def test_importing_all_of_core_loads_no_file_format() -> None:
    assert _run_probe() == "[]"


def test_the_probe_would_see_a_loaded_file_format() -> None:
    """Negative control, so the probe cannot pass by failing to see anything.

    A stub module stands in for nibabel, which a core-only install lacks.
    """
    planted = "import types\nsys.modules['nibabel'] = types.ModuleType('nibabel')"
    assert _run_probe(planted) == "['nibabel']"


def test_core_declares_only_the_numeric_stack() -> None:
    declared = _names(requires("fmri-qa-core") or [])
    assert declared == {"numpy", "scipy", "scikit-image"}


def test_declared_names_are_compared_canonically() -> None:
    """Negative control: metadata spellings reduce to the names compared above."""
    assert _names(["scikit_image>=0.25", "nibabel>=5.3.2"]) == {
        "scikit-image",
        "nibabel",
    }
