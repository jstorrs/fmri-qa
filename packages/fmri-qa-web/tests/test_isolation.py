"""`fmriqa_web` stays importable in a browser: no file, no process, no netCDF4.

The page runs this package under Pyodide, which has no netCDF4 or dcm2niix
build and no subprocess. The package may import only the standard library
modules it uses and the browser-safe parts of the workspace. This checks the
rule statically, over every import in its sources, and at runtime, in a fresh
interpreter.
"""

import ast
import subprocess
import sys
from importlib.metadata import requires
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

import fmriqa_web
from fmriqa_io.testing import write_phantom

_ROOT = Path(fmriqa_web.__file__).parent

# Absolute modules the package may import, by dotted prefix. `fmriqa` and the
# report's HTML driver load lazily or are browser-safe; `fmriqa_io` only
# through `decode`, `convert.filing` and `paths`.
_ALLOWED = (
    "collections",
    "dataclasses",
    "importlib.metadata",
    "json",
    "typing",
    "warnings",
    "fmriqa",
    "fmriqa_io.decode",
    "fmriqa_io.convert.filing",
    "fmriqa_io.paths",
    "fmriqa_report.formats.html",
)

_FORBIDDEN_AT_RUNTIME = (
    "netCDF4",
    "dcm2niix",
    "fmriqa_cli",
    "fmriqa_launcher",
    "fmriqa_io.analysis_file",
    "fmriqa_io.load",
    "fmriqa_io.rename",
    "fmriqa_io.convert.session",
    "fmriqa_io.convert.dcm2niix",
)

# numpy and matplotlib import `subprocess` themselves, so it is checked by the
# static scan alone. The probe runs the whole path (decode, analyze, render and
# naming) on a real phantom, so a lazy import on it is caught too. argv[1] is the
# phantom NIfTI the parent wrote.
_PROBE = """
import importlib, pkgutil, sys
import fmriqa_web
for info in pkgutil.iter_modules(fmriqa_web.__path__):
    importlib.import_module("fmriqa_web." + info.name)
fmriqa_web.contract()
with open(sys.argv[1], "rb") as f:
    nifti = f.read()
result = fmriqa_web.analyze_series(nifti, None, stem="p")
assert isinstance(result, fmriqa_web.SeriesReport), result
assert fmriqa_web.name_outputs({"a.nii.gz": b"", "a.json": b"{}"}) == {
    "a.nii.gz": "a.nii.gz",
    "a.json": "a.json",
}
# EXTRA
forbidden = FORBIDDEN
print(sorted(
    m for m in sys.modules if any(m == f or m.startswith(f + ".") for f in forbidden)
))
"""


def _allowed(module: str) -> bool:
    return any(module == a or module.startswith(a + ".") for a in _ALLOWED)


def _offenders(tree: ast.Module) -> set[str]:
    """Every absolute import in `tree` outside the allowlist; relative ones are fine."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names if not _allowed(a.name)}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            module = node.module or ""
            # `from fmriqa_io.convert import filing` names a module, not a name.
            names = [f"{module}.{a.name}" for a in node.names]
            if not _allowed(module) and not all(_allowed(n) for n in names):
                found.add(module)
    return found


def _script(extra: str) -> str:
    return _PROBE.replace("# EXTRA", extra).replace(
        "FORBIDDEN", repr(_FORBIDDEN_AT_RUNTIME)
    )


def _run_probe(phantom: Path, extra: str = "") -> str:
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _script(extra), str(phantom)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_every_source_imports_only_the_allowlist() -> None:
    sources = sorted(_ROOT.rglob("*.py"))
    assert len(sources) >= 6
    offenders = {
        path.name: sorted(_offenders(ast.parse(path.read_text()))) for path in sources
    }
    assert not any(offenders.values()), f"fmriqa_web may not import: {offenders}"


def test_the_scan_would_catch_a_forbidden_import() -> None:
    """Negative control: a process, the analysis file, the launcher, a lazy one."""
    tree = ast.parse(
        "import subprocess\n"
        "import json\n"
        "from fmriqa_io.analysis_file import save_analysis\n"
        "from fmriqa_io.convert import filing\n"
        "from fmriqa_io.convert import session\n"
        "from fmriqa_launcher import session\n"
        "from .series import x\n"
        "def f():\n"
        "    import tempfile\n"
        "from fmriqa.types import Sidecar\n"
    )
    assert _offenders(tree) == {
        "subprocess",
        "fmriqa_io.analysis_file",
        "fmriqa_io.convert",
        "fmriqa_launcher",
        "tempfile",
    }


@pytest.fixture(scope="module")
def phantom_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return write_phantom(tmp_path_factory.mktemp("probe"), t=8)


def test_analyzing_and_naming_load_nothing_file_bound(phantom_file: Path) -> None:
    assert _run_probe(phantom_file) == "[]"


def test_the_probe_would_see_a_forbidden_module(phantom_file: Path) -> None:
    """Negative control, so the probe cannot pass by failing to see anything."""
    assert "fmriqa_io.convert.session" in _run_probe(
        phantom_file, "import fmriqa_io.convert.session"
    )


def test_the_package_declares_only_the_workspace_libraries() -> None:
    declared = {
        canonicalize_name(Requirement(r).name) for r in requires("fmri-qa-web") or []
    }
    assert declared == {"fmri-qa-core", "fmri-qa-io", "fmri-qa-report"}
