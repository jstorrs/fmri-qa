"""The seam: the report half may read the analysis, and nothing else.

Presentation depends on the *published analysis*, not on the pipeline that
produced it, and it does no file IO: an analysis in memory in, a string out.
Reading the analysis file and writing the page belong to the applications, so
the report depends on `fmri-qa-core` and matplotlib only. That is easy to
erode one convenient import at a time, so this file checks it mechanically.
Every `fmriqa` import in the report package must land in `fmriqa.analysis` (the
analysis) or `fmriqa.types` (the shared array/option vocabulary). An import of
`fmriqa.metrics`, `fmriqa.pipeline`, `fmriqa.prep` or `fmriqa.load`, of the
`fmriqa` package as a whole (which pulls all of them), or of anything from
`fmriqa_io` fails this test.

That scan reads import *text*, which is necessary but not sufficient. An
allowed import can still pull in a forbidden module through the `__init__.py`
of the package it lands in. So the seam is checked twice: statically, over
every source file, and at runtime, by importing every report module in a fresh
interpreter and looking at what ended up in `sys.modules`: no `fmriqa_io`, no
`fmriqa.pipeline`, `metrics`, `prep` or `load`, and none of the libraries they
bring (scipy, scikit-image, nibabel, netCDF4). The runtime check of
the `fmri-qa-report` command is in the fmri-qa-cli tests.
"""

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import fmriqa_report

# The only calculation-side modules presentation is allowed to reach for.
# `fmriqa_io` is not among them: it is where files are read and written.
ALLOWED = frozenset({"fmriqa.analysis", "fmriqa.types"})

_SOURCE_ROOT = Path(fmriqa_report.__file__).parent

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
            found |= {node.module}
    return found


def test_the_report_package_has_source_to_check() -> None:
    """Guard the guard: an empty scan must not pass silently."""
    assert len(_modules()) >= 8


def test_report_imports_only_the_analysis_and_the_shared_vocabulary() -> None:
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


def test_the_check_would_catch_any_io_import() -> None:
    """The same control for `fmriqa_io`, whose name `fmriqa` alone would miss."""
    tree = ast.parse(
        "import fmriqa_io\n"
        "from fmriqa_io import load_analysis\n"
        "from fmriqa_io.rename import atomic_file\n"
    )
    assert _fmriqa_imports(tree) - ALLOWED == {
        "fmriqa_io",
        "fmriqa_io.rename",
    }


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


# Everything the report must not load, by top-level package or dotted prefix: the
# IO layer, the calculation layers behind the analysis, and their libraries.
_FORBIDDEN = (
    "fmriqa_io",
    "fmriqa.pipeline",
    "fmriqa.metrics",
    "fmriqa.prep",
    "fmriqa.load",
    "scipy",
    "skimage",
    "nibabel",
    "netCDF4",
)

_FORBIDDEN_PROBE = f"""
import importlib
import json
import pkgutil
import sys
import fmriqa_report
for info in pkgutil.walk_packages(fmriqa_report.__path__, "fmriqa_report."):
    importlib.import_module(info.name)
for name in sys.argv[1:]:
    importlib.import_module(name)
forbidden = {_FORBIDDEN!r}
print(json.dumps({{
    "report": sorted(m for m in sys.modules if m.split(".")[0] == "fmriqa_report"),
    "forbidden": sorted(
        m for m in sys.modules
        if any(m == f or m.startswith(f + ".") for f in forbidden)
    ),
}}))
"""


def _probe(*extra: str, path: Path | None = None) -> dict[str, list[str]]:
    """Import every report module in a fresh interpreter; report what got loaded.

    `path`, if given, is put first on the interpreter's module search path.
    """
    env = dict(os.environ)
    if path is not None:
        env["PYTHONPATH"] = os.pathsep.join(
            [str(path), *filter(None, [env.get("PYTHONPATH")])]
        )
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _FORBIDDEN_PROBE, *extra],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return json.loads(result.stdout)


def _module_name(path: Path) -> str:
    """Return the dotted module a report source file defines."""
    parts = path.relative_to(_SOURCE_ROOT.parent).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def test_importing_every_report_module_loads_no_forbidden_module() -> None:
    """The runtime half: no module, however deep, reaches IO or the pipeline."""
    probed = _probe()

    expected = {_module_name(path) for path in _modules()}
    assert expected >= {
        "fmriqa_report.formats.html.run",
        "fmriqa_report.panels.images",
    }
    assert expected <= set(probed["report"]), "the probe did not import every module"
    assert probed["forbidden"] == []


def test_the_runtime_probe_would_see_a_forbidden_module(tmp_path: Path) -> None:
    """A negative control: the probe reports `fmriqa_io` when something loads it.

    A stub package stands in, so this needs no `fmri-qa-io` installed.
    """
    stub = tmp_path / "fmriqa_io"
    stub.mkdir()
    (stub / "__init__.py").write_text("")
    (stub / "rename.py").write_text("")

    probed = _probe("fmriqa_io.rename", path=tmp_path)

    assert "fmriqa_io.rename" in probed["forbidden"]
