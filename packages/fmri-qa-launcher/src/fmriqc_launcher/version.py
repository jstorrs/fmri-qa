"""The installed distribution's version.

Mirrors `fmriqc.version`. It reads installed package metadata and needs
nothing else, so it stays a leaf module.
"""

from importlib.metadata import PackageNotFoundError, version


def launcher_version() -> str:
    """Read the installed `fmri-qa-launcher` version; "unknown" from a bare tree."""
    try:
        return version("fmri-qa-launcher")
    except PackageNotFoundError:
        return "unknown"
