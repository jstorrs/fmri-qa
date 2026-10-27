r"""Move a `QAArtifact` to and from a single `.qa.nc` file.

The on-disk form is one netCDF-4 file. Every array is a variable under its
dotted path (`curves.weisskoff.cv`, `images.ghost.pe_ghost`) over named, shared
dimensions. Everything else (settings, provenance, scalar measurements, labels)
is a JSON document in the global attribute `document`, and every scalar
measurement is also an attribute of its own, so a number can be read without
decoding JSON. The file opens in MATLAB with no toolbox, in R through `ncdf4`, at
a shell through `ncdump`, and in Python through netCDF4-python or xarray, and one
image can be read without loading the rest. `netcdf` holds the layout and the
reasoning behind it.

The document and arrays themselves are the schema, and that stays in
`fmriqa.analysis.serialize` (`decompose`, `compose`, `migrate`), pure and
usable without a filesystem. This package is only the container they travel in.

Moving to netCDF did not bump the schema version. The version pins the document
(which fields exist and what they mean), and only the envelope changed, as when
the `.npz` document member became `uint8`. Every `.qa.npz` an earlier build wrote
still loads, which is what `npz` is for. The container is decided by sniffing
leading bytes (HDF5's `\x89HDF\r\n\x1a\n` against a zip's `PK\x03\x04`), never
by suffix, since the CLI writes whatever name the user asked for and the schema
version cannot be read until the container is open. Nothing writes an `.npz` any
more.

`ls` this package to find a concern:

* `netcdf` -- the netCDF-4 file: dimensions, variables, attributes and the
              units a reader is told
* `npz`    -- the retired NumPy-archive container, read-only
"""

import json
from pathlib import Path
from typing import Any

from numpy.typing import NDArray

from fmriqa.analysis.artifact import QAArtifact
from fmriqa.analysis.serialize.compose import compose
from fmriqa.analysis.serialize.decompose import decompose
from fmriqa.analysis.serialize.migrate import migrated
from fmriqa.analysis.validation import validate_artifact, validate_document
from fmriqa.exceptions import InvalidArtifactError

from ..rename import atomic_file
from . import netcdf, npz

__all__ = ["load_artifact", "save_artifact"]

# How far a sniff has to read to tell the two containers apart. Each module
# publishes the bytes its own container starts with, so the signature and the
# reader that understands it stay in one file.
_MAGIC_BYTES = max(len(netcdf.MAGIC), len(npz.MAGIC))

# How a malformed artifact or document fails in decompose, compose, validate or
# encode: a missing key, a field of the wrong shape or type, a closed-set string
# from outside its set, an int too large for its container. One set serves both
# directions, because a member added to one side alone would let the other
# raise past its guard, and `load_artifact` promises only `InvalidArtifactError`.
_MALFORMED = (
    AttributeError,
    IndexError,
    KeyError,
    OverflowError,
    TypeError,
    ValueError,
)


def save_artifact(artifact: QAArtifact, path: str | Path) -> Path:
    """Write `artifact` to `path` as a netCDF-4 file and return the path.

    Missing parent directories are created. The file name is used as given,
    including a name with no suffix.

    The write is atomic: the file goes to a temporary beside the destination and
    is moved into place only once it is whole. A truncated netCDF file looks
    complete until it is opened, and the archive is read months later by
    something that never saw the run, so an interrupted write must leave the
    destination untouched.

    The artifact is checked against the reader's contract before anything is
    written, so a write that succeeds is one `load_artifact` will accept.
    Otherwise a bad value (a malformed sidecar field, say) would survive saving,
    fail only when a report opens the file, and replace any valid artifact
    already at `path`. The whole file is laid out before anything is opened, so
    an artifact the container cannot hold is refused just as early.

    Raises
    ------
    InvalidArtifactError
        If the artifact would not read back. Nothing is written, and an existing
        file at `path` is left as it was.
    """
    out = Path(path)
    try:
        document, arrays = decompose(artifact)
        validate_artifact(artifact)
        # Round-trip through JSON once, because that is what the reader will
        # see. The in-memory document still holds numpy scalars where the file
        # will hold plain numbers, and the type check is written against the
        # file. The file publishes the same parsed form as attributes.
        text = json.dumps(document)
        stored = json.loads(text)
        validate_document(stored)
        content = netcdf.encode(text, stored, arrays)
    except _MALFORMED as exc:
        raise InvalidArtifactError(
            out, f"refusing to write an artifact that would not read back: {exc}"
        ) from exc
    out.parent.mkdir(parents=True, exist_ok=True)
    with atomic_file(out) as temporary:
        netcdf.write(content, temporary)
    return out


def _read_container(path: Path) -> tuple[str, dict[str, NDArray[Any]]]:
    """Read the JSON text and arrays from whichever container the file is.

    Decided by the leading bytes, not the suffix. `--artifact` writes the name
    the user asked for, so the suffix is only a convention. The schema version
    that might otherwise settle it is inside a document that cannot be read
    until the container holding it has been opened.
    """
    with path.open("rb") as fh:
        magic = fh.read(_MAGIC_BYTES)
    if magic.startswith(netcdf.MAGIC):
        return netcdf.read(path)
    if magic.startswith(npz.MAGIC):
        return npz.read(path)
    raise InvalidArtifactError(path, "not an fmri-qa artifact archive")


def load_artifact(path: str | Path) -> QAArtifact:
    """Read a `QAArtifact` back from a file written by `save_artifact`.

    Both containers are read: the netCDF-4 file written now, and the `.npz`
    every build before it wrote. A file written under an older schema is
    migrated forward on read (see `migrate`), with a warning. Only a version
    this build has no route from, or one from a newer build whose layout it
    cannot know, is refused.

    Raises
    ------
    InvalidArtifactError
        If the file is not a readable artifact, is malformed, or carries a
        `schema_version` this build cannot reach.
    """
    src = Path(path)
    try:
        text, arrays = _read_container(src)
        document = json.loads(text)
        if not isinstance(document, dict):
            raise InvalidArtifactError(
                src, "malformed artifact: expected a JSON object"
            )
    except InvalidArtifactError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        # Each container reader answers a file it cannot read with its own
        # `InvalidArtifactError`. What is left here is the file never opening
        # (`OSError`: missing, a directory, unreadable) and the JSON failing to
        # parse.
        raise InvalidArtifactError(src, str(exc)) from exc

    try:
        # Migration reads the stored document too, so a document missing what
        # its own schema carried fails here. That is malformedness and belongs
        # under the same guard as composing the current layout.
        document = migrated(document, src)
        validate_document(document)
        artifact = compose(document, arrays)
        validate_artifact(artifact)
        return artifact
    except InvalidArtifactError:
        raise
    except _MALFORMED as exc:
        raise InvalidArtifactError(src, f"malformed artifact: {exc}") from exc
