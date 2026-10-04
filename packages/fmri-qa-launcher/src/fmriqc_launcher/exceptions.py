"""Exception hierarchy for fmriqc_launcher.

One base class (`LauncherError`) is the error contract: catch it to catch
anything the package raises, and new subclasses can be added without breaking
that catch. Unlike `fmriqc.exceptions`, there is no natural stdlib exception
this hierarchy also belongs to — a launcher run fails at the level of "one
request" or "the whole session," not at the level of a bad argument value or a
missing file — so `Exception` alone is the base, per style/exceptions.md.
"""

from collections.abc import Sequence


class LauncherError(Exception):
    """Base exception for fmriqc_launcher.

    Catch this to catch any error the package raises.
    """


class RequestError(LauncherError):
    """The run request could not be built from what the user supplied.

    A folder that does not exist, a number that does not parse, an option
    outside its domain. ``problems`` carries every reason found, not just the
    first, so a form can show them all at once; `str(exc)` joins them with
    "; " for a readable one-line summary.
    """

    def __init__(self, problems: Sequence[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = tuple(problems)


class SessionError(LauncherError):
    """The launcher could not run at all, independent of any one request.

    Covers whole-run failure modes: no converter is available on the machine,
    the DICOM source cannot be read, the output directory cannot be written
    to, or a run that produced nothing converted. There is no extra field a
    caller could branch on beyond the message, so this carries only that.
    """


class PanelUnavailableError(LauncherError):
    """The desktop panel could not open: `tkinter` has no display to attach to.

    `panel.run_panel` raises this in place of letting `tkinter.TclError`
    escape. `cli._launch_panel` catches it and reports the failure the same
    way it reports a missing `tkinter` module, and `panel.main` catches it
    and returns exit code 2, so neither names a `tkinter` type.
    """
