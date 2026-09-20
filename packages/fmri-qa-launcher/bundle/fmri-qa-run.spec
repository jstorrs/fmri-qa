# -*- mode: python -*-
# PyInstaller spec for the single-file `fmri-qa-run`: the launcher, both
# distributions under it, the interpreter, and dcm2niix in one executable that
# needs nothing installed. Build it with `make bundle`, which runs PyInstaller
# from an isolated environment resolved from uv.lock -- not the shared .venv,
# whose extra tooling the import graph would otherwise drag in.
#
# PyInstaller follows `import` statements. Everything below is something this
# project reaches some other way, stated once here rather than discovered as a
# ModuleNotFoundError on a scanner console.

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_submodules,
    copy_metadata,
)

import dcm2niix

FIRST_PARTY = {
    "fmri-qa-core": "fmriqc",
    "fmri-qa-report": "fmriqc_report",
    "fmri-qa-launcher": "fmriqc_launcher",
}

# All three packages resolve names lazily through `import_module` (PEP 562
# `__getattr__` maps, and `cli._launch_panel` for the Tk panel), which the
# import graph cannot see. Collecting every submodule is total over those maps;
# naming the lazy ones individually would be a list to forget to extend.
hiddenimports = [
    module for package in FIRST_PARTY.values() for module in collect_submodules(package)
]

# The report reads its templates and stylesheet through `importlib.resources`
# (`formats/html/resources.py`), so they must exist as files in the bundle.
datas = collect_data_files("fmriqc_report")

# `--version` and the artifact's provenance are answered by
# `importlib.metadata`, which needs each distribution's dist-info. Without it
# `version()` raises PackageNotFoundError and every version reads "unknown".
for distribution in FIRST_PARTY:
    datas += copy_metadata(distribution)

# `find_dcm2niix` prefers the binary the `dcm2niix` wheel ships, located at
# `dcm2niix.bin` beside the module's `__file__`. Placing it at the same relative
# path keeps that branch the one that answers, so the executable converts DICOM
# on a machine with no dcm2niix. As a *binary* entry it keeps its exec bit.
binaries = [(dcm2niix.bin, "dcm2niix")]

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
    # `fmri-qa-run` has a stdout/stderr contract (report paths out, progress
    # and failures on stderr), so it is a console program even though running
    # it bare opens the panel.
    console=True,
    upx=False,
)
