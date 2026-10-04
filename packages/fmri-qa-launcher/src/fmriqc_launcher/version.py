"""The installed distribution's version.

Mirrors `fmriqc.version`: the answer comes from installed package metadata and
needs nothing else this package will grow, so it stays its own leaf module.
"""

from importlib.metadata import PackageNotFoundError, version


def launcher_version() -> str:
    """Read the installed `fmri-qa-launcher` version; "unknown" from a bare tree."""
    try:
        return version("fmri-qa-launcher")
    except PackageNotFoundError:
        return "unknown"
