"""The installed distribution's version.

A leaf of its own, below every layer, because of who asks for it and when.
`Provenance.core_version` stamps each artifact with the build that computed it,
and `fmri-qa --version` prints it — and the second of those must not pay for the
first. The answer comes from installed package metadata and needs nothing this
package computes with, so keeping it beside `analyze` (which reaches the whole
metrics stack) made printing a version string cost numpy, scipy, scikit-image
and nibabel. Here it costs `importlib.metadata`.
"""

from importlib.metadata import PackageNotFoundError, version


def core_version() -> str:
    """Read the installed `fmri-qa-core` version; "unknown" from a source tree."""
    try:
        return version("fmri-qa-core")
    except PackageNotFoundError:
        return "unknown"
