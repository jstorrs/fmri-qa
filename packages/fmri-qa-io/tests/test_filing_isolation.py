"""`fmriqa_io.convert.filing` stays importable in a browser: strings only.

A page running dcm2niix as WASM has a list of filenames and sidecar bytes, and
needs the names `import_dicom` would file them under. Pyodide has no dcm2niix
and no subprocess, so the naming module may import only the standard library
modules it uses, `fmriqa` and the pure path helpers. This checks the rule
statically, over the module's imports, and at runtime, in a fresh interpreter.
"""

import ast
import subprocess
import sys
from pathlib import Path

import fmriqa_io.convert.filing as filing

_SOURCE = Path(filing.__file__)

# Top-level packages the module may import absolutely.
_ALLOWED_ROOTS = frozenset({"collections", "dataclasses", "json", "typing", "fmriqa"})

# Relative imports allowed: `..paths` is `pathlib` string logic only.
_ALLOWED_RELATIVE = frozenset({"..paths"})

_FORBIDDEN_AT_RUNTIME = (
    "netCDF4",
    "dcm2niix",
    "subprocess",
    "shutil",
    "tempfile",
    "fmriqa_io.convert.session",
    "fmriqa_io.convert.dcm2niix",
    "fmriqa_io.artifact",
    "fmriqa_io.load",
    "fmriqa_io.rename",
)

# Run in a fresh interpreter: this process has the rest of io loaded by other
# tests. `subprocess` is checked here as well, unlike in the decoder's probe:
# the pure path is stdlib plus `fmriqa`, which do not import it.
_PROBE = f"""
import sys
import fmriqa_io.convert.filing
{{extra}}
forbidden = {_FORBIDDEN_AT_RUNTIME!r}
print(sorted(
    m for m in sys.modules if any(m == f or m.startswith(f + ".") for f in forbidden)
))
"""


def _imports(tree: ast.Module) -> set[str]:
    """Every import in `tree` outside the allowlists, as written."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {
                alias.name
                for alias in node.names
                if alias.name.split(".")[0] not in _ALLOWED_ROOTS
            }
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            if node.level == 0:
                if module.split(".")[0] not in _ALLOWED_ROOTS:
                    found.add(module)
            elif module not in _ALLOWED_RELATIVE:
                found.add(module)
    return found


def _run_probe(extra: str = "") -> str:
    """Run `_PROBE` with `extra` after the import; return the loaded list."""
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _PROBE.format(extra=extra)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_filing_imports_only_the_allowlist() -> None:
    assert _SOURCE.is_file()
    offenders = sorted(_imports(ast.parse(_SOURCE.read_text())))
    assert not offenders, f"fmriqa_io.convert.filing may not import these: {offenders}"


def test_the_scan_would_catch_a_forbidden_import() -> None:
    """Negative control: a process, the converter, and the session."""
    tree = ast.parse(
        "import subprocess\n"
        "import numpy\n"
        "from pathlib import Path\n"
        "def f():\n"
        "    from .session import import_dicom\n"
        "    from ..paths import nifti_stem\n"
        "from fmriqa.types import Sidecar\n"
    )
    assert _imports(tree) == {"subprocess", "numpy", "pathlib", ".session"}


def test_importing_filing_loads_no_process_or_file_bound_module() -> None:
    assert _run_probe() == "[]"


def test_the_probe_would_see_a_forbidden_module() -> None:
    """Negative control, so the probe cannot pass by failing to see anything."""
    assert _run_probe("import fmriqa_io.convert.session").startswith(
        "['fmriqa_io.convert.dcm2niix', 'fmriqa_io.convert.session'"
    )
