"""Exception hierarchy for fmriqa_launcher.

Catch `LauncherError` to catch anything the package raises; new subclasses
won't break that catch. Unlike `fmriqa.exceptions`, no stdlib exception fits:
a run fails at the level of a request or the whole session, not a bad argument
or missing file. So `Exception` alone is the base, per style/exceptions.md.
"""

from collections.abc import Sequence


class LauncherError(Exception):
    """Base exception for fmriqa_launcher.

    Catch this to catch any error the package raises.
    """


class RequestError(LauncherError):
    """The run request could not be built from what the user supplied.

    For example a missing folder, an unparseable number or an option outside
    its domain. `problems` holds every reason found so a form can show them
    all at once; `str(exc)` joins them with "; ".
    """

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


class SessionError(LauncherError):
    """The launcher could not run at all, independent of any one request.

    For example no converter on the machine, an unreadable DICOM source, an
    unwritable output directory, or a run that converted nothing. It carries
    only the message; a caller has nothing else to branch on.
    """


class PanelUnavailableError(LauncherError):
    """The desktop panel could not open: `tkinter` has no display to attach to.

    `panel.run_panel` raises this instead of `tkinter.TclError`.
    `cli._launch_panel` reports it like a missing `tkinter` module, and
    `panel.main` returns exit code 2, so neither names a `tkinter` type.
    """
