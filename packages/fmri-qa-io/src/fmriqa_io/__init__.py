"""File formats and filesystem IO for fmri-qa.

This package holds what touches files or external programs: NIfTI decoding,
the netCDF artifact container, the dcm2niix runner and atomic file writes.
`fmri-qa-core` stays pure so it can run in the browser under Pyodide.

Import rule: the package root is lazy, so importing one Pyodide-safe submodule
never imports the filesystem-bound ones. Every name in `__all__` is re-exported
through `__getattr__` (PEP 562), which imports a name's owning module on first
access. `_EXPORTS` maps each defining module to its names, and
`test_lazy_imports.py` asserts it flattens to exactly `__all__`.
"""

import logging
from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Plain imports, not the lazy `_EXPORTS` map below, so mypy and pyright
    # resolve every name statically. Never executed at runtime.
    from .artifact import load_artifact, save_artifact
    from .convert.session import ImportedSeries, ImportResult, import_dicom
    from .exceptions import ConversionError

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "ConversionError",
    "ImportResult",
    "ImportedSeries",
    "import_dicom",
    "load_artifact",
    "save_artifact",
]

# Which submodule defines each name in `__all__`, keyed by module path so one
# import serves every name it owns.
_EXPORTS: dict[str, tuple[str, ...]] = {
    ".artifact": ("load_artifact", "save_artifact"),
    ".convert.session": ("ImportResult", "ImportedSeries", "import_dicom"),
    ".exceptions": ("ConversionError",),
}

# Reverse lookup of `_EXPORTS`, for `__getattr__`.
_NAME_TO_MODULE: dict[str, str] = {
    name: module for module, names in _EXPORTS.items() for name in names
}


def __getattr__(name: str) -> object:
    """Resolve `fmriqa_io.<name>` by importing its owning module on first access.

    Caches the result as a module global (assigning into `globals()`), so this
    runs at most once per name. Later accesses are plain attribute lookups, as
    with an eager re-export.
    """
    try:
        module_path = _NAME_TO_MODULE[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    value = getattr(import_module(module_path, __name__), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """List the public names, matching what an eager module would show."""
    return sorted(__all__)
