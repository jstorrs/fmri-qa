"""Move a `QAArtifact` to and from a single `.npz` file.

The on-disk form is one compressed NumPy archive: every array is a member under
its dotted path (`curves.weisskoff.cv`, `images.ghost.pe_ghost`), and everything
that is not an array — settings, provenance, the scalar measurements, the
labels — rides in a JSON document stored as the `__document__` member. So the
file is inspectable with nothing but `numpy` and `json`, and an array can be
pulled out without materializing the rest.

That member holds the document's UTF-8 bytes as a `uint8` array, not a NumPy
`<U` string. Both are lossless — `json.dumps` escapes every non-ASCII character
to an ASCII `\\uXXXX` sequence, so the text is ASCII either way — but `<U` is
UCS-4 and spends four bytes on each of those ASCII characters. More to the
point, the readers a
site is likely to have reach numeric dtypes only: npy-matlab maps exactly
`u1 u2 u4 u8 i1 i2 i4 i8 f4 f8 b1` and errors on `<U`, and RcppCNPy is numeric
too. As `uint8` the document is an array they can already read, and MATLAB's
`char()` turns it straight into text because the bytes are ASCII. Archives
written before this still carry `<U`; `load_artifact` reads both.

The mapping is written out explicitly, section by section, rather than derived
by reflection over the dataclasses: the layout is a published contract pinned by
`ARTIFACT_SCHEMA_VERSION`, and adding a field should be a deliberate edit here,
not a silent change of file format. Bumping that version is likewise deliberate,
and comes with a migration: an artifact outlives the build that wrote it, so
older layouts are brought forward on read (`migrate`) rather than refused.

The JSON document uses Python's `NaN`/`Infinity` tokens. A NaN measurement is
meaningful — it says an estimator could not resolve the value, which is distinct
from the `null` that says the quantity does not apply — so it is preserved
rather than flattened.

`ls` this package to find a concern:

* `decompose` -- artifact -> (JSON document, named arrays)
* `compose`   -- (JSON document, named arrays) -> artifact
* `migrate`   -- an older document's layout, brought forward on read
"""

import json
import os
import tempfile
from pathlib import Path
from zipfile import BadZipFile

import numpy as np

from ...exceptions import InvalidArtifactError
from ...types import ByteArray
from ..artifact import QAArtifact
from ..validation import validate_artifact, validate_document
from .compose import compose
from .decompose import Member, decompose
from .migrate import migrated

__all__ = ["load_artifact", "save_artifact"]

# The JSON member carrying everything that is not an array.
_DOCUMENT = "__document__"


def save_artifact(artifact: QAArtifact, path: str | Path) -> Path:
    """Write `artifact` to `path` as a compressed `.npz`. Returns the path.

    Missing parent directories are created. The file name is used exactly as
    given (NumPy's own `savez` would append `.npz` to a name lacking it).

    The write is atomic: the archive goes to a temporary file beside the
    destination and is moved into place only once it is whole. A QA archive is
    read months later by something that never saw the run that wrote it, and a
    truncated `.npz` looks exactly like a complete one until it is opened — so
    an interrupted write must leave the destination untouched, not half-written.

    The artifact is held to the reader's contract before anything is written:
    a write that succeeds is one `load_artifact` will accept. Otherwise a value
    no analysis needs — a malformed sidecar field, say — survives calculation
    and saving and fails only when a report opens the file, and if a valid
    archive already stood at `path` it has been replaced by then.

    Raises:
        InvalidArtifactError: If the artifact would not read back; nothing is
            written, and an existing file at `path` is left as it was.
    """
    out = Path(path)
    document, arrays = decompose(artifact)
    try:
        validate_artifact(artifact)
        # Through JSON and back, because that is what the reader will see: the
        # in-memory document still holds numpy scalars where the file will hold
        # plain numbers, and the type check is written against the file.
        validate_document(json.loads(json.dumps(document)))
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidArtifactError(
            out, f"refusing to write an artifact that would not read back: {exc}"
        ) from exc
    out.parent.mkdir(parents=True, exist_ok=True)
    # `json.dumps` defaults to ensure_ascii=True, and that default is load-bearing
    # here rather than incidental: it escapes every non-ASCII character, so the
    # bytes below are ASCII whatever a scanner or a file name put in the document,
    # and a consumer can take them as text without knowing an encoding. Turning it
    # off would also make this line *raise* on a path Python holds as a lone
    # surrogate -- what a Windows file name with an undecodable byte becomes.
    text = json.dumps(document).encode("utf-8")
    # The document's own dtype is neither of `Member`'s two: it is the JSON
    # text, not a measured array.
    payload: dict[str, Member | ByteArray] = {
        _DOCUMENT: np.frombuffer(text, dtype=np.uint8),
        **arrays,
    }
    # In the destination's own directory: a move is only atomic within a single
    # filesystem, and the system temporary directory is often on another.
    fd, name = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as fh:
            # savez_compressed takes member names as **kwargs, which collides with
            # its own keyword-only `allow_pickle` for a checker: a `dict[str, ...]`
            # splat could in principle carry that name. Our keys are dotted paths,
            # never it.
            np.savez_compressed(fh, **payload)  # type: ignore[arg-type]
            # The rename below is only as durable as the bytes it renames: without
            # this, both the file data and the directory's rename record can still
            # be sitting in a page cache that a power loss or crash never flushes,
            # and the survivor is a zero-length or truncated file wearing the final
            # name -- exactly the half-written archive atomicity was meant to rule
            # out, just moved from "mid-write" to "mid-write, then a clean-looking
            # rename over it."
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(out)
    finally:
        # A no-op once the move succeeded; the cleanup that matters is the one
        # after a failure, which must not leave debris beside the archive.
        tmp.unlink(missing_ok=True)
    return out


def _document_text(member: np.ndarray) -> str:
    """The JSON text of the `__document__` member, in either stored form.

    Read before the schema version is known -- the version is *inside* this
    document -- so the two forms are told apart by dtype rather than by version:
    `uint8` is the UTF-8 bytes written now, and a NumPy `<U` string is what
    every archive written before that carries.
    """
    if member.dtype == np.uint8:
        return bytes(member).decode("utf-8")
    return str(member)


def load_artifact(path: str | Path) -> QAArtifact:
    """Read a `QAArtifact` back from an `.npz` written by `save_artifact`.

    A file written under an older schema is migrated forward on read (see
    `_migrated`), with a warning; only a version this build has no route from —
    or one from a newer build, which it cannot know the layout of — is refused.

    Raises:
        InvalidArtifactError: If the file is not a readable artifact archive, is
            malformed, or carries a `schema_version` this build cannot reach.
    """
    src = Path(path)
    try:
        with np.load(src, allow_pickle=False) as archive:
            names = list(archive.files)
            if _DOCUMENT not in names:
                raise InvalidArtifactError(src, "not an fmriqc artifact archive")
            document = json.loads(_document_text(archive[_DOCUMENT]))
            if not isinstance(document, dict):
                raise InvalidArtifactError(
                    src, "malformed artifact: expected a JSON object"
                )
            arrays = {name: archive[name] for name in names if name != _DOCUMENT}
    except InvalidArtifactError:
        raise
    except (OSError, ValueError, TypeError, EOFError, BadZipFile) as exc:
        raise InvalidArtifactError(src, str(exc)) from exc

    try:
        # Migration reads the stored document too, so a document that is missing
        # what its own schema carried fails here; that is malformedness, and
        # belongs under the same guard as composing the current layout.
        document = migrated(document, src)
        validate_document(document)
        artifact = compose(document, arrays)
        validate_artifact(artifact)
        return artifact
    except InvalidArtifactError:
        raise
    except (
        KeyError,
        TypeError,
        ValueError,
        IndexError,
        AttributeError,
        OverflowError,
    ) as exc:
        raise InvalidArtifactError(src, f"malformed artifact: {exc}") from exc
