"""Move a `QAArtifact` to and from a single `.qa.nc` file.

The on-disk form is one netCDF-4 file: every array is a variable under its
dotted path (`curves.weisskoff.cv`, `images.ghost.pe_ghost`), declared over
named, shared dimensions, and everything that is not an array -- settings,
provenance, the scalar measurements, the labels -- rides in a JSON document
stored as the global attribute `document`. Every scalar measurement is
published as an attribute of its own beside it, so a number can be had without
decoding JSON at all. The file opens in MATLAB with no toolbox, in R through
CRAN's `ncdf4`, at a shell through `ncdump`, and in Python through
netCDF4-python or xarray, and one image can be pulled out without materializing
the rest. `netcdf` holds that layout and the
reasoning behind it.

The mapping is written out explicitly, section by section, rather than derived
by reflection over the dataclasses: the layout is a published contract pinned by
`ARTIFACT_SCHEMA_VERSION`, and adding a field should be a deliberate edit here,
not a silent change of file format. Bumping that version is likewise deliberate,
and comes with a migration: an artifact outlives the build that wrote it, so
older layouts are brought forward on read (`migrate`) rather than refused.

Moving to netCDF did *not* bump the schema version. The version pins the
document -- which fields exist and what they mean -- and no field changed; only
the envelope did, exactly as when the `.npz` document member became `uint8`. So
every `.qa.npz` an earlier build wrote still loads, and `npz` is kept for
precisely that: a file's container is decided by sniffing its leading bytes
(HDF5's `\\x89HDF\\r\\n\\x1a\\n` against a zip's `PK\\x03\\x04`), never by its
suffix, because the CLI writes whatever name the user asked for and a stored
schema version cannot be consulted until the container it lives in has been
opened. Nothing writes an `.npz` any more.

The JSON document uses Python's `NaN`/`Infinity` tokens. A NaN measurement is
meaningful -- it says an estimator could not resolve the value, which is distinct
from the `null` that says the quantity does not apply -- so it is preserved
rather than flattened.

`ls` this package to find a concern:

* `decompose` -- artifact -> (JSON document, named arrays)
* `compose`   -- (JSON document, named arrays) -> artifact
* `netcdf`    -- the netCDF-4 file those two travel in: dimensions, variables,
                 attributes, and the units a reader is told
* `npz`       -- the retired NumPy-archive container, read-only
* `migrate`   -- an older document's layout, brought forward on read
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from numpy.typing import NDArray

from ...exceptions import InvalidArtifactError
from ..artifact import QAArtifact
from ..validation import validate_artifact, validate_document
from . import netcdf, npz
from .compose import compose
from .decompose import decompose
from .migrate import migrated

__all__ = ["load_artifact", "save_artifact"]

# How far a sniff has to read to tell the two containers apart: each module
# publishes the bytes its own container starts with, so the signature and the
# reader that understands it stay in one file.
_MAGIC_BYTES = max(len(netcdf.MAGIC), len(npz.MAGIC))


def save_artifact(artifact: QAArtifact, path: str | Path) -> Path:
    """Write `artifact` to `path` as a netCDF-4 file. Returns the path.

    Missing parent directories are created. The file name is used exactly as
    given, including a name that carries no suffix at all.

    The write is atomic: the file goes to a temporary beside the destination and
    is moved into place only once it is whole. A QA archive is read months later
    by something that never saw the run that wrote it, and a truncated netCDF
    file looks exactly like a complete one until it is opened -- so an
    interrupted write must leave the destination untouched, not half-written.

    The artifact is held to the reader's contract before anything is written:
    a write that succeeds is one `load_artifact` will accept. Otherwise a value
    no analysis needs -- a malformed sidecar field, say -- survives calculation
    and saving and fails only when a report opens the file, and if a valid
    artifact already stood at `path` it has been replaced by then. The whole
    file is laid out before anything is opened, so an artifact the container
    cannot hold is refused on the same terms and just as early, and the only
    file this function writes is the temporary it then renames.

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
        content = netcdf.encode(document, arrays)
    except (ValueError, TypeError, KeyError) as exc:
        raise InvalidArtifactError(
            out, f"refusing to write an artifact that would not read back: {exc}"
        ) from exc
    out.parent.mkdir(parents=True, exist_ok=True)
    # In the destination's own directory: a move is only atomic within a single
    # filesystem, and the system temporary directory is often on another.
    fd, name = tempfile.mkstemp(dir=out.parent, prefix=f".{out.name}.", suffix=".tmp")
    # The netCDF writer opens the path itself, so the descriptor `mkstemp`
    # returns is closed immediately; what it is wanted for is the unique name it
    # reserved, and the writer overwrites the empty file it left behind.
    os.close(fd)
    tmp = Path(name)
    try:
        netcdf.write(content, tmp)
        with tmp.open("r+b") as fh:
            # The rename below is only as durable as the bytes it renames: without
            # this, both the file data and the directory's rename record can still
            # be sitting in a page cache that a power loss or crash never flushes,
            # and the survivor is a zero-length or truncated file wearing the final
            # name -- exactly the half-written archive atomicity was meant to rule
            # out, just moved from "mid-write" to "mid-write, then a clean-looking
            # rename over it."
            os.fsync(fh.fileno())
        # Only after the writer has closed the file: Windows refuses to rename
        # one that is still open, and HDF5 holds it open until the Dataset is
        # closed.
        tmp.replace(out)
    finally:
        # A no-op once the move succeeded; the cleanup that matters is the one
        # after a failure, which must not leave debris beside the archive.
        tmp.unlink(missing_ok=True)
    return out


def _read_container(path: Path) -> tuple[str, dict[str, NDArray[Any]]]:
    """The JSON text and the arrays, from whichever container the file is.

    Decided by the leading bytes rather than the suffix: `--artifact` writes the
    name the user asked for, so the suffix is a convention and not a fact, and
    the schema version that might otherwise settle it lives *inside* a document
    that cannot be read until the container holding it has been opened.
    """
    with path.open("rb") as fh:
        magic = fh.read(_MAGIC_BYTES)
    if magic.startswith(netcdf.MAGIC):
        return netcdf.read(path)
    if magic.startswith(npz.MAGIC):
        return npz.read(path)
    raise InvalidArtifactError(path, "not an fmriqc artifact archive")


def load_artifact(path: str | Path) -> QAArtifact:
    """Read a `QAArtifact` back from a file written by `save_artifact`.

    Both containers are read: the netCDF-4 file written now, and the `.npz`
    every build before it wrote. A file written under an older schema is
    migrated forward on read (see `migrate`), with a warning; only a version
    this build has no route from -- or one from a newer build, which it cannot
    know the layout of -- is refused.

    Raises:
        InvalidArtifactError: If the file is not a readable artifact, is
            malformed, or carries a `schema_version` this build cannot reach.
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
        # Each container reader answers a file it cannot read with an
        # `InvalidArtifactError` of its own, so what is left here is the file
        # never opening at all (`OSError`: missing, a directory, unreadable) and
        # the JSON refusing to parse.
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
