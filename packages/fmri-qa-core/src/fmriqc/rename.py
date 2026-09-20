"""Renaming into place on a filesystem something else is watching.

Every import and every published series ends in a `Path.replace`: work is
staged beside its destination so that the last step is one rename on one
filesystem, and a reader never sees a half-written series. On Windows that
rename can be refused for a reason that has nothing to do with the run. A file
that has just been written is a file a sync client (OneDrive) wants to hash and
upload, and a virus scanner wants to read; while either holds it open, renaming
it -- or renaming the directory it sits in -- fails with `WinError 5` (access
denied) or `WinError 32` (sharing violation). Both reach Python as
`PermissionError`. Seen in the field as an output directory under OneDrive that
failed once and then could not be made to fail again, which is what a race
looks like.

The holder lets go within moments, so the answer is to ask again. It is not to
stage somewhere unwatched: a staging directory off the destination's filesystem
turns the final rename into a copy, and the half-written series comes back.
"""

import time
from collections.abc import Callable, Sequence
from pathlib import Path

__all__ = ["replace_patiently"]

# Waits between attempts, about six seconds in all before the error is allowed
# through. Doubling, because the two holders differ by orders of magnitude: a
# scanner is done with a sidecar in milliseconds, a sync client hashing a 30 MB
# NIfTI is not.
#
# The same on every platform, not only Windows. Whether an open file blocks a
# rename is a property of the filesystem, not of the client: a Linux machine
# writing to an SMB share gets the same refusal from the server. And the wait
# is only ever paid on a path that was about to fail anyway -- a destination
# that is genuinely unwritable is refused earlier, when staging is created in it.
_DELAYS: tuple[float, ...] = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2)


def replace_patiently(
    source: Path,
    target: Path,
    *,
    delays: Sequence[float] = _DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """`source.replace(target)`, asked again while something holds the file open.

    Only `PermissionError` is waited out; any other failure is not the race
    this exists for and propagates at once. When the delays are spent the last
    attempt's error propagates unchanged, so a genuinely unwritable destination
    fails as it always did, a few seconds later.
    """
    for delay in delays:
        try:
            source.replace(target)
        except PermissionError:
            sleep(delay)
        else:
            return
    source.replace(target)
