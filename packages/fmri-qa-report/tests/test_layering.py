"""The seam: the report half may read the artifact, and nothing else.

The whole point of the split is that presentation depends on the *published
artifact*, not on the pipeline that produced it. That is easy to state and easy
to erode one convenient import at a time, so it is checked mechanically here:
every `fmriqc` import in the report package must land in `fmriqc.analysis` (the
artifact) or `fmriqc.types` (the shared array/option vocabulary). An import of
`fmriqc.metrics`, `fmriqc.pipeline`, `fmriqc.prep`, or `fmriqc.load` — or of the
`fmriqc` package as a whole, which pulls all of them — fails this test.

That scan reads import *text*, which is necessary but not sufficient: an
allowed import can still drag a forbidden module in behind it, through the
`__init__.py` of the package it lands in. So the seam is checked twice here —
once statically, over every source file, and once at runtime, by importing the
report CLI in a fresh interpreter and looking at what actually ended up in
`sys.modules`.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

import fmriqc_report

# The only calculation-side modules presentation is allowed to reach for.
ALLOWED = frozenset({"fmriqc.analysis", "fmriqc.types"})

_SOURCE_ROOT = Path(fmriqc_report.__file__).parent

# The calculation stack, and the third-party libraries only it needs. Rendering
# a report reaches none of these: `fmriqc.load` and `fmriqc.prep` are in the
# list too, because the artifact carries everything a reader wants already
# resolved, so not even a cheap leaf of those layers is touched at read time.
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

# The format-agnostic public surface must stay importable without the current
# PDF driver's dependencies. Each target runs in its own new interpreter so a
# previous probe cannot hide a dependency imported by another target.
_PDF_ONLY = ("reportlab", "svglib")
_REPORT_IMPORT_TARGETS = (
    "fmriqc_report",
    "fmriqc_report.content",
    "fmriqc_report.theme",
    "fmriqc_report.summary",
    "fmriqc_report.panels",
)

# Run in a fresh interpreter: only a process that has imported nothing else can
# say what `import fmriqc_report.cli` costs. This one already has the whole
# stack loaded from the other tests in the suite.
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
pdf = {_PDF_ONLY!r}
loaded = sorted(
    m for m in sys.modules if any(m == p or m.startswith(p + ".") for p in pdf)
)
print(loaded)
"""


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


def test_presentation_never_imports_the_launcher() -> None:
    """The application shell depends on `fmriqc_report`, never the other way around."""
    offenders = [
        path.relative_to(_SOURCE_ROOT).as_posix()
        for path in _modules()
        if "fmriqc_launcher" in path.read_text()
    ]
    assert not offenders, (
        f"the report half must never import fmriqc_launcher: {offenders}"
    )


def test_importing_the_report_cli_does_not_load_the_calculation_stack() -> None:
    """The seam at runtime, which the static scan above cannot speak to.

    `fmriqc.analysis` is an allowed import, but what it *executes* is another
    question: its `__init__` could pull the pipeline in behind the artifact and
    the scan would still pass. Only a fresh interpreter's `sys.modules` settles
    it, so that is what this asks.
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
def test_format_agnostic_report_modules_do_not_load_the_pdf_driver(module: str) -> None:
    """The content surface imports without ReportLab or svglib."""
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _REPORT_IMPORT_PROBE, module],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", (
        f"importing {module} loaded the PDF driver: {result.stdout}\n{result.stderr}"
    )
