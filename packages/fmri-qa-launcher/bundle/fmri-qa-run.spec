# -*- mode: python -*-
# PyInstaller spec for the single-file `fmri-qa-run`: the launcher, the
# distributions under it, the interpreter and dcm2niix in one executable that
# needs nothing installed. `make bundle` builds it from an isolated environment
# resolved from uv.lock, because the shared .venv's extra tooling would get
# dragged in by the import graph.
#
# PyInstaller only follows `import` statements. Everything listed below is
# reached another way and would otherwise fail with ModuleNotFoundError on a
# scanner console.

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

import dcm2niix

FIRST_PARTY = {
    "fmri-qa-core": "fmriqa",
    "fmri-qa-io": "fmriqa_io",
    "fmri-qa-cli": "fmriqa_cli",
    "fmri-qa-report": "fmriqa_report",
    "fmri-qa-launcher": "fmriqa_launcher",
}

# Every package resolves names lazily through `import_module` (PEP 562
# `__getattr__` maps, and `cli._launch_panel` for the Tk panel), which the
# import graph cannot see. Collecting every submodule avoids maintaining a list.
hiddenimports = [
    module for package in FIRST_PARTY.values() for module in collect_submodules(package)
]

# The report reads its templates and stylesheet through `importlib.resources`
# (`formats/html/resources.py`), so they must be files in the bundle.
datas = collect_data_files("fmriqa_report")

# `--version` and the analysis's provenance come from `importlib.metadata`,
# which needs each distribution's dist-info. Without it `version()` raises
# PackageNotFoundError and every version reads "unknown".
for distribution in FIRST_PARTY:
    datas += copy_metadata(distribution)

# `find_dcm2niix` prefers the binary the `dcm2niix` wheel ships at
# `dcm2niix.bin` beside the module's `__file__`. The same relative path keeps
# that branch working, so the executable converts DICOM on a machine with no
# dcm2niix. As *binary* entries they keep their exec bit.
#
# Collect every non-Python file in the package directory, not just
# `dcm2niix.bin`: that path is always the extensionless `dcm2niix`, but the
# Windows wheel ships `dcm2niix.exe` (found at run time because CreateProcess
# appends `.exe`) plus the MSVC runtime DLLs it loads from its own directory.
binaries = [
    (str(path), "dcm2niix")
    for path in Path(dcm2niix.__file__).parent.iterdir()
    if path.is_file() and path.suffix != ".py"
]

a = Analysis(
    ["fmri_qa_run.py"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # The report draws on a bare `Figure` and saves SVG (`figures.py`), and
    # matplotlib loads `backend_svg` by name at save time. Left to discover
    # backends, the hook finds none in use, falls back to the first importable
    # GUI one (TkAgg), and the report fails at its first figure.
    hooksconfig={"matplotlib": {"backends": ["svg"]}},
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="fmri-qa-run",
    # A console program despite opening the panel when run bare, because of
    # its stdout/stderr contract: report paths out, progress and failures on
    # stderr.
    console=True,
    upx=False,
)
