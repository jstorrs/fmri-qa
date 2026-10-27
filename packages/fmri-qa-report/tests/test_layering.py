"""The seam: the report half may read the artifact, and nothing else.

Presentation depends on the *published artifact*, not on the pipeline that
produced it. That is easy to erode one convenient import at a time, so this
file checks it mechanically. Every `fmriqa` import in the report package must
land in `fmriqa.analysis` (the artifact), `fmriqa.types` (the shared
array/option vocabulary), and every `fmriqa_io` import in `fmriqa_io.artifact`
(the artifact file), `fmriqa_io.rename` (how a finished file is moved into
place), `fmriqa_io.path_arguments` (wildcards and same-file checks on path
arguments) or the lazy `fmriqa_io` root, for a name it re-exports. An import of
`fmriqa.metrics`, `fmriqa.pipeline`, `fmriqa.prep` or `fmriqa.load`, of the
`fmriqa` package as a whole (which pulls all of them), or of any other
`fmriqa_io` submodule fails this test.

That scan reads import *text*, which is necessary but not sufficient. An
allowed import can still pull in a forbidden module through the `__init__.py`
of the package it lands in. So the seam is checked twice: statically, over
every source file, and at runtime, by importing the report CLI in a fresh
interpreter and looking at what ended up in `sys.modules`.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import fmriqa_io
import fmriqa_report

# The only calculation-side modules presentation is allowed to reach for.
#
# `fmriqa_io.rename` has nothing to do with the artifact, but it is a leaf over the
# standard library, so it cannot bring any calculation code in behind it (the
# runtime half of this test would catch it if that changed). It carries a
# policy, how long to outwait a sync client holding a just-written file, that
# the artifact's writer and the page's writer must agree on. A second copy kept
# in step by hand is worse.
#
# `fmriqa_io.path_arguments` is the same kind of leaf: standard library only. It
# carries a shell quirk (an unexpanded wildcard) and an overwrite guard that the
# report must apply the same way as the other commands.
#
# `fmriqa_io.artifact` is the artifact file, the one thing the report reads. The
# `fmriqa_io` root is lazy and imports nothing until a name is used. Only its
# re-exported names count as the root: `from fmriqa_io import testing` is scanned
# as `fmriqa_io.testing` (see `_fmriqa_imports`).
ALLOWED = frozenset(
    {
        "fmriqa.analysis",
        "fmriqa.types",
        "fmriqa_io",
        "fmriqa_io.artifact",
        "fmriqa_io.rename",
        "fmriqa_io.path_arguments",
    }
)

# The `fmriqa_io` submodules importing the report CLI may load: the artifact
# file and the two stdlib-only leaves described above. Any other (NIfTI
# decoding, DICOM import) is the calculation side's input, not the report's.
# The root is allowed too; the probe never looks at it.
_IO_ALLOWED = (
    "fmriqa_io.artifact",
    "fmriqa_io.rename",
    "fmriqa_io.path_arguments",
)

_SOURCE_ROOT = Path(fmriqa_report.__file__).parent

# The calculation stack, and the third-party libraries only it needs. Rendering
# a report reaches none of these. `fmriqa.load` and `fmriqa.prep` are listed
# too: the artifact carries everything a reader wants already resolved, so
# reading touches none of those layers.
_CALCULATION_ONLY = (
    "fmriqa.pipeline",
    "fmriqa.metrics",
    "fmriqa.prep",
    "fmriqa.load",
    "skimage",
    "scipy",
    "nibabel",
    "netCDF4",
)

# The format-agnostic public surface must stay importable without the drawing
# stack. The package resolves its driver lazily so that `import fmriqa_report`
# never pays for unused matplotlib. Each target runs in its own new interpreter
# so a previous probe cannot hide a dependency imported by another target.
_DRIVER_ONLY = ("matplotlib",)
_REPORT_IMPORT_TARGETS = (
    "fmriqa_report",
    "fmriqa_report.content",
    "fmriqa_report.theme",
    "fmriqa_report.summary",
    "fmriqa_report.panels",
)

# Run in a fresh interpreter. Only a process that has imported nothing else can
# say what `import fmriqa_report.cli` costs; this one already has the whole
# stack loaded by other tests.
_PROBE = f"""
import sys
import fmriqa_report.cli
calculation = {_CALCULATION_ONLY!r}
loaded = sorted(
    m for m in sys.modules if any(m == c or m.startswith(c + ".") for c in calculation)
)
print(loaded)
"""

_IO_PROBE = f"""
import sys
import fmriqa_report.cli
{{extra}}
allowed = {_IO_ALLOWED!r}
loaded = sorted(
    m
    for m in sys.modules
    if m.startswith("fmriqa_io.")
    and not any(m == a or m.startswith(a + ".") for a in allowed)
)
print(loaded)
"""

_REPORT_IMPORT_PROBE = f"""
import importlib
import sys
importlib.import_module(sys.argv[1])
driver = {_DRIVER_ONLY!r}
loaded = sorted(
    m for m in sys.modules if any(m == d or m.startswith(d + ".") for d in driver)
)
print(loaded)
"""


def _modules() -> list[Path]:
    """List every source file in the report package."""
    return sorted(_SOURCE_ROOT.rglob("*.py"))


def _from_fmriqa(module: str) -> bool:
    """Return True if a dotted module name names the calculation or IO package."""
    return module.split(".", maxsplit=1)[0] in {"fmriqa", "fmriqa_io"}


def _fmriqa_imports(tree: ast.Module) -> set[str]:
    """Return the `fmriqa` and `fmriqa_io` modules a parsed source file imports."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names if _from_fmriqa(a.name)}
        # `level > 0` is a relative import inside fmriqa_report itself.
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and _from_fmriqa(node.module)
        ):
            found |= {_from_name(node.module, a.name) for a in node.names}
    return found


def _from_name(module: str, name: str) -> str:
    """Return the module `from module import name` reaches.

    A name from the `fmriqa_io` root that the root does not re-export is a
    submodule, so it is scanned as one. Otherwise `from fmriqa_io import testing`
    would pass as an import of the allowed root.
    """
    if module == "fmriqa_io" and name not in fmriqa_io.__all__:
        return f"{module}.{name}"
    return module


def test_the_report_package_has_source_to_check() -> None:
    """Guard the guard: an empty scan must not pass silently."""
    assert len(_modules()) >= 8


def test_report_imports_only_the_artifact_and_the_shared_vocabulary() -> None:
    offenders = {}
    for path in _modules():
        imported = _fmriqa_imports(ast.parse(path.read_text()))
        if extra := imported - ALLOWED:
            offenders[path.relative_to(_SOURCE_ROOT).as_posix()] = sorted(extra)
    assert not offenders, (
        f"the report half must depend only on {sorted(ALLOWED)}; found {offenders}"
    )


def test_the_check_would_catch_a_pipeline_import() -> None:
    """A negative control, so the scan cannot pass by failing to see anything."""
    tree = ast.parse("import fmriqa\nfrom fmriqa.pipeline import run_qa\n")
    assert _fmriqa_imports(tree) - ALLOWED == {"fmriqa", "fmriqa.pipeline"}


def test_the_check_would_catch_an_io_import_beyond_the_artifact_file() -> None:
    """The same control for `fmriqa_io`, whose name `fmriqa` alone would miss."""
    tree = ast.parse("from fmriqa_io.testing import write_phantom\n")
    assert _fmriqa_imports(tree) - ALLOWED == {"fmriqa_io.testing"}


def test_the_check_sees_a_submodule_imported_from_the_io_root() -> None:
    """The lazy root is allowed for its re-exports, not as a way around the scan."""
    tree = ast.parse("from fmriqa_io import load_artifact, testing\n")
    assert _fmriqa_imports(tree) - ALLOWED == {"fmriqa_io.testing"}


def test_presentation_never_imports_the_launcher() -> None:
    """The application shell depends on the report, never the other way around."""
    offenders = [
        path.relative_to(_SOURCE_ROOT).as_posix()
        for path in _modules()
        if "fmriqa_launcher" in path.read_text()
    ]
    assert not offenders, (
        f"the report half must never import fmriqa_launcher: {offenders}"
    )


def test_importing_the_report_cli_does_not_load_the_calculation_stack() -> None:
    """The seam at runtime, which the static scan above cannot see.

    `fmriqa.analysis` is an allowed import, but what it *executes* is another
    question. Its `__init__` could pull the pipeline in behind the artifact and
    the scan would still pass. Only a fresh interpreter's `sys.modules` settles
    it.
    """
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", (
        f"importing the report CLI loaded the calculation stack: {result.stdout}\n"
        f"{result.stderr}"
    )


@pytest.mark.parametrize("module", _REPORT_IMPORT_TARGETS)
def test_format_agnostic_report_modules_do_not_load_the_drawing_stack(
    module: str,
) -> None:
    """The content surface imports without matplotlib."""
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _REPORT_IMPORT_PROBE, module],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", (
        f"importing {module} loaded the drawing stack: {result.stdout}\n{result.stderr}"
    )


def _io_probe(extra: str = "") -> str:
    """Run `_IO_PROBE`, with `extra` imported after the report CLI; return its list."""
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _IO_PROBE.format(extra=extra)],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_importing_the_report_cli_loads_only_the_artifact_file_from_io() -> None:
    """Of `fmriqa_io`, the report CLI loads the artifact file and two leaves."""
    output = _io_probe()
    assert output == "[]", (
        f"importing the report CLI loaded more of fmriqa_io: {output}"
    )


def test_the_io_probe_would_catch_another_io_module() -> None:
    """A negative control, so the probe cannot pass by failing to see anything."""
    assert _io_probe("import fmriqa_io.testing") == "['fmriqa_io.testing']"
