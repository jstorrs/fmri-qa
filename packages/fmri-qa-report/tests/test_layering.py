"""The seam: the report half may read the artifact, and nothing else.

Presentation depends on the *published artifact*, not on the pipeline that
produced it. That is easy to erode one convenient import at a time, so this
file checks it mechanically. Every `fmriqc` import in the report package must
land in `fmriqc.analysis` (the artifact), `fmriqc.types` (the shared
array/option vocabulary), `fmriqc.rename` (how a finished file is moved into
place) or `fmriqc.path_arguments` (wildcards and same-file checks on path
arguments). An import of `fmriqc.metrics`, `fmriqc.pipeline`, `fmriqc.prep` or
`fmriqc.load`, or of the `fmriqc` package as a whole (which pulls all of them),
fails this test.

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

import fmriqc_report

# The only calculation-side modules presentation is allowed to reach for.
#
# `fmriqc.rename` has nothing to do with the artifact, but it is a leaf over the
# standard library, so it cannot bring any calculation code in behind it (the
# runtime half of this test would catch it if that changed). It carries a
# policy, how long to outwait a sync client holding a just-written file, that
# the artifact's writer and the page's writer must agree on. A second copy kept
# in step by hand is worse.
#
# `fmriqc.path_arguments` is the same kind of leaf: standard library only. It
# carries a shell quirk (an unexpanded wildcard) and an overwrite guard that the
# report must apply the same way as the other commands.
ALLOWED = frozenset(
    {"fmriqc.analysis", "fmriqc.types", "fmriqc.rename", "fmriqc.path_arguments"}
)

_SOURCE_ROOT = Path(fmriqc_report.__file__).parent

# The calculation stack, and the third-party libraries only it needs. Rendering
# a report reaches none of these. `fmriqc.load` and `fmriqc.prep` are listed
# too: the artifact carries everything a reader wants already resolved, so
# reading touches none of those layers.
_CALCULATION_ONLY = (
    "fmriqc.pipeline",
    "fmriqc.metrics",
    "fmriqc.prep",
    "fmriqc.load",
    "skimage",
    "scipy",
    "nibabel",
    "netCDF4",
)

# The format-agnostic public surface must stay importable without the drawing
# stack. The package resolves its driver lazily so that `import fmriqc_report`
# never pays for unused matplotlib. Each target runs in its own new interpreter
# so a previous probe cannot hide a dependency imported by another target.
_DRIVER_ONLY = ("matplotlib",)
_REPORT_IMPORT_TARGETS = (
    "fmriqc_report",
    "fmriqc_report.content",
    "fmriqc_report.theme",
    "fmriqc_report.summary",
    "fmriqc_report.panels",
)

# Run in a fresh interpreter. Only a process that has imported nothing else can
# say what `import fmriqc_report.cli` costs; this one already has the whole
# stack loaded by other tests.
_PROBE = f"""
import sys
import fmriqc_report.cli
calculation = {_CALCULATION_ONLY!r}
loaded = sorted(
    m for m in sys.modules if any(m == c or m.startswith(c + ".") for c in calculation)
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


def _from_fmriqc(module: str) -> bool:
    """Return True if a dotted module name names the calculation package."""
    return module.split(".", maxsplit=1)[0] == "fmriqc"


def _fmriqc_imports(tree: ast.Module) -> set[str]:
    """Return the `fmriqc*` modules a parsed source file imports."""
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


def test_presentation_never_imports_the_launcher() -> None:
    """The application shell depends on the report, never the other way around."""
    offenders = [
        path.relative_to(_SOURCE_ROOT).as_posix()
        for path in _modules()
        if "fmriqc_launcher" in path.read_text()
    ]
    assert not offenders, (
        f"the report half must never import fmriqc_launcher: {offenders}"
    )


def test_importing_the_report_cli_does_not_load_the_calculation_stack() -> None:
    """The seam at runtime, which the static scan above cannot see.

    `fmriqc.analysis` is an allowed import, but what it *executes* is another
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
