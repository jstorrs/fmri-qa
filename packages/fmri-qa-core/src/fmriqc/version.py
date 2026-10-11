"""The installed distribution's version.

A leaf module below every layer. `Provenance.core_version` stamps each artifact
with the build that computed it, and `fmri-qa --version` prints it. The version
comes from installed package metadata, so it needs nothing this package
computes with. Kept beside `analyze`, which reaches the whole metrics stack,
printing a version would import numpy, scipy, scikit-image and nibabel. Here it
imports only `importlib.metadata`.
"""

from importlib.metadata import PackageNotFoundError, version


def core_version() -> str:
    """Read the installed `fmri-qa-core` version; "unknown" from a source tree."""
    try:
        return version("fmri-qa-core")
    except PackageNotFoundError:
        return "unknown"
