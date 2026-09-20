"""Atomic writes of a single file, honouring the umask.

Every format driver that publishes a finished artifact — a run page — wants
the same two guarantees: a reader never observes a partial write, and the file
left behind carries ordinary permissions rather than the `0600` `tempfile`
default. `tempfile.mkstemp` creates its result `0600` regardless of the process
umask, because it is designed for a private scratch file, not for something
meant to be read back by someone else. A report is exactly the opposite case,
so this module creates its own uniquely named sibling path with the kernel's
ordinary umask-filtered permissions instead.
"""

import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fmriqc.rename import replace_patiently

__all__ = ["atomic_file"]


@contextmanager
def atomic_file(target: Path) -> Iterator[Path]:
    """Yield a sibling temporary path to write, then move it onto ``target``.

    The temporary file is created with ``os.O_CREAT | os.O_EXCL`` so its name
    can never collide with a concurrent writer, and with mode ``0o666`` so the
    kernel — not this function — applies the process umask; reading the umask
    directly (``os.umask``) is not thread-safe and is deliberately avoided.
    The caller writes through the yielded path; on a clean exit it is moved
    onto ``target`` by a rename, so a reader never sees a partial file. The
    rename is :func:`fmriqc.rename.replace_patiently`: a page closed a moment
    ago is what a sync client or virus scanner opens next, and while either
    holds it the rename is refused. Any exception, including one raised while
    writing, skips the rename and leaves an existing ``target`` untouched; the
    temporary file is always removed. ``target``'s parent directory must
    already exist.
    """
    temporary = target.parent / f".{target.name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
    os.close(fd)
    try:
        yield temporary
        replace_patiently(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
