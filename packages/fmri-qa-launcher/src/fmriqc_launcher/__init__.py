"""The application shell over fmri-qa: DICOM directory in, report directory out.

This package is the one-step pipeline built on top of the calculation half
(`fmriqc`) and the presentation half (`fmriqc_report`) — a command line and a
desktop panel, both still to come, that turn a DICOM directory into one report
directory per series without asking the caller to wire the two libraries
together itself. Only the exception hierarchy and the installed version are
here so far.
"""

import logging

from .exceptions import LauncherError, RequestError, SessionError
from .version import launcher_version

logging.getLogger(__name__).addHandler(logging.NullHandler())

__all__ = [
    "LauncherError",
    "RequestError",
    "SessionError",
    "launcher_version",
]
