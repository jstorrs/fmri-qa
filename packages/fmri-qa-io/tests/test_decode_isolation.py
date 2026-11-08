"""`fmriqa_io.decode` stays importable in a browser: no files, no native wheels.

A page running under Pyodide decodes the bytes of a dropped scan with
`scan_from_bytes`. Pyodide has no netCDF4 or dcm2niix build and no subprocess,
and the page has no filesystem worth reading, so the decoder may import only
the standard library modules it parses with, numpy, nibabel and `fmriqa`. This
checks the rule statically, over every import in the subpackage, and at
runtime, in a fresh interpreter.
"""

import ast
import subprocess
import sys
from pathlib import Path

import fmriqa_io.decode

_DECODE_ROOT = Path(fmriqa_io.decode.__file__).parent

# Top-level packages the decoder may import. Relative imports must stay inside
# `decode` (see `_imports`).
_ALLOWED_ROOTS = frozenset(
    {
        "collections",
        "dataclasses",
        "gzip",
        "io",
        "json",
        "math",
        "struct",
        "typing",
        "warnings",
        "zlib",
        "numpy",
        "nibabel",
        "fmriqa",
    }
)

# What importing the decoder from the lazy root must leave unloaded.
_FORBIDDEN_AT_RUNTIME = (
    "netCDF4",
    "dcm2niix",
    "fmriqa_io.analysis_file",
    "fmriqa_io.convert",
    "fmriqa_io.load",
    "fmriqa_io.rename",
    "fmriqa_io.paths",
    "fmriqa_io.path_arguments",
    "fmriqa_io.testing",
)

# Run in a fresh interpreter: this process has the rest of io loaded by other
# tests. `subprocess` is not checked here, since numpy and nibabel import it
# themselves; the static scan covers the decoder's own imports.
_PROBE = f"""
import sys
from fmriqa_io import scan_from_bytes
{{extra}}
forbidden = {_FORBIDDEN_AT_RUNTIME!r}
print(sorted(
    m for m in sys.modules if any(m == f or m.startswith(f + ".") for f in forbidden)
))
"""


def _imports(tree: ast.Module) -> set[str]:
    """Every import in `tree` outside the allowlist, as written.

    A relative import is allowed at one level, which is `decode` itself for
    every module in it. Anything further up reaches the rest of `fmriqa_io`.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {
                alias.name
                for alias in node.names
                if alias.name.split(".")[0] not in _ALLOWED_ROOTS
            }
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level > 1:
                found.add("." * node.level + module)
            elif node.level == 0 and module.split(".")[0] not in _ALLOWED_ROOTS:
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


def test_the_decoder_imports_only_the_allowlist() -> None:
    paths = sorted(_DECODE_ROOT.rglob("*.py"))
    assert len(paths) >= 4  # an empty scan must not pass silently
    offenders = {
        path.relative_to(_DECODE_ROOT).as_posix(): sorted(found)
        for path in paths
        if (found := _imports(ast.parse(path.read_text())))
    }
    assert not offenders, f"fmriqa_io.decode may not import these: {offenders}"


def test_the_scan_would_catch_a_forbidden_import() -> None:
    """Negative control: a native wheel, a process, or the rest of io."""
    tree = ast.parse(
        "import netCDF4\n"
        "def f():\n"
        "    import subprocess\n"
        "    from ..paths import sidecar_path\n"
        "    from fmriqa_io.load import load_scan\n"
        "from .nifti import image_from_bytes\n"
    )
    assert _imports(tree) == {"netCDF4", "subprocess", "..paths", "fmriqa_io.load"}


def test_importing_the_decoder_loads_no_file_bound_module() -> None:
    assert _run_probe() == "[]"


def test_the_probe_would_see_a_file_bound_module() -> None:
    """Negative control, so the probe cannot pass by failing to see anything."""
    assert _run_probe("import fmriqa_io.paths") == "['fmriqa_io.paths']"
