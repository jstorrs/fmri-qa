"""Writing a file or moving a directory into place, all or nothing.

`atomic_file` stages a single file beside its destination and moves it in.
`replace_patiently` is the move itself, also used directly for a staged
directory.

Every import and every published series ends in a `Path.replace`. Work is
staged beside its destination so the last step is one rename on one filesystem
and a reader never sees a half-written series. On Windows that rename can be
refused for reasons unrelated to the run. A sync client (OneDrive) wants to hash
and upload a freshly written file, and a virus scanner wants to read it. While
either holds it open, renaming it or its directory fails with `WinError 5`
(access denied) or `WinError 32` (sharing violation), both of which reach Python
as `PermissionError`. This showed up as an output directory under OneDrive that
failed once and then couldn't be made to fail again.

The holder lets go within moments, so the fix is to retry. Staging somewhere
unwatched (the launcher uses the system's temporary directory) helps but can't
replace this, because the results still have to land in the watched place by a
rename of just-written files.
"""

import os
import secrets
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

__all__ = ["atomic_file", "replace_patiently"]

# Waits between attempts, about six seconds in all before the error is allowed
# through. The delays double because the holders differ by orders of magnitude:
# a scanner finishes with a sidecar in milliseconds, a sync client hashing a
# 30 MB NIfTI does not.
#
# Used on every platform, not only Windows. Whether an open file blocks a rename
# is a property of the filesystem, not the client: a Linux machine writing to an
# SMB share gets the same refusal from the server. The wait is only paid on a path
# that was about to fail anyway, since an unwritable destination is refused
# earlier (by the import when it makes its staging directory, and by the
# launcher when it probes its output directory).
_DELAYS: tuple[float, ...] = (0.05, 0.1, 0.2, 0.4, 0.8, 1.6, 3.2)


def replace_patiently(
    source: Path,
    target: Path,
    *,
    delays: Sequence[float] = _DELAYS,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """`source.replace(target)`, asked again while something holds the file open.

    Only `PermissionError` is waited out. Any other failure is not the race
    this exists for and propagates at once. When the delays are spent, the last
    attempt's error propagates unchanged, so a genuinely unwritable destination
    fails as before, a few seconds later.
    """
    for delay in delays:
        try:
            source.replace(target)
        except PermissionError:
            sleep(delay)
        else:
            return
    source.replace(target)


@contextmanager
def atomic_file(target: Path) -> Iterator[Path]:
    """Yield a sibling temporary path to write, then move it onto `target`.

    The caller writes through the yielded path, which already exists and is
    empty. On a clean exit the file is flushed to disk and renamed onto
    `target`, so a reader never sees a partial file. Any exception, including
    one raised while writing, skips the rename and leaves an existing `target`
    untouched. The temporary is always removed. `target`'s parent directory
    must already exist.
    """
    # In the destination's own directory: a rename is only atomic within one
    # filesystem, and the system temporary directory is often on another.
    temporary = target.parent / f".{target.name}.{secrets.token_hex(8)}.tmp"
    # Not `tempfile.mkstemp`: it creates the file `0600` whatever the umask,
    # which is wrong for a result someone else is meant to open. Mode `0o666`
    # leaves the permissions to the kernel's umask (reading it with `os.umask`
    # is not thread-safe), and `O_EXCL` keeps the name from colliding with a
    # concurrent writer. Writers may open the path themselves (HDF5 does), so
    # the descriptor is closed at once. Only the reserved name is wanted.
    os.close(os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666))
    try:
        yield temporary
        with temporary.open("r+b") as fh:
            # The rename is only as durable as the bytes it renames. Without
            # this, the file data and the directory's rename record can both
            # sit in a page cache that a power loss or crash never flushes. The
            # survivor is then a zero-length or truncated file with the final
            # name, the half-written file atomicity was meant to rule out.
            os.fsync(fh.fileno())
        # Only after the writer has closed the file: Windows refuses to rename
        # one that is still open. It can also refuse one that something else
        # has opened, and a sync client or scanner opens a just-closed file
        # next. Hence patiently.
        replace_patiently(temporary, target)
    finally:
        # A no-op once the rename succeeded. After a failure this must not
        # leave debris beside the target.
        temporary.unlink(missing_ok=True)
