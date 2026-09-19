"""Atomic writes of a single file or a fresh directory, honouring the umask.

Every format driver that publishes a finished artifact — a run page, a PDF
packet, a whole site — wants the same two guarantees: a reader never observes
a partial write, and the file or directory left behind carries ordinary
permissions rather than the `0600`/`0700` `tempfile` defaults. `tempfile.mkstemp`
and `tempfile.mkdtemp` create their result `0600`/`0700` regardless of the
process umask, because they are designed for private scratch files, not for
something meant to be read back by someone else. A report or a published site
is exactly the opposite case, so this module creates its own uniquely named
sibling paths with the kernel's ordinary umask-filtered permissions instead.
"""

import os
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

__all__ = ["atomic_file"]


@contextmanager
def atomic_file(target: Path) -> Iterator[Path]:
    """Yield a sibling temporary path to write, then move it onto ``target``.

    The temporary file is created with ``os.O_CREAT | os.O_EXCL`` so its name
    can never collide with a concurrent writer, and with mode ``0o666`` so the
    kernel — not this function — applies the process umask; reading the umask
    directly (``os.umask``) is not thread-safe and is deliberately avoided.
    The caller writes through the yielded path; on a clean exit it is moved
    onto ``target`` with :meth:`Path.replace`, so a reader never sees a
    partial file. Any exception, including one raised while writing, skips
    the replace and leaves an existing ``target`` untouched; the temporary
    file is always removed. ``target``'s parent directory must already exist.
    """
    temporary = target.parent / f".{target.name}.{secrets.token_hex(8)}.tmp"
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
    os.close(fd)
    try:
        yield temporary
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
