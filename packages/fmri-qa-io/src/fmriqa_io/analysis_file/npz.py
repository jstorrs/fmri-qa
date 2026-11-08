"""Read the retired `.npz` container: every analysis file written before netCDF.

The reader half of the layout this package used to write: one compressed NumPy
archive, each array a member under its dotted path and the JSON document in a
member named `__document__`. Nothing writes it any more (see `netcdf` for what
replaced it and why), and this module has no writer, following "support reading
old versions, write the new one only" from style/stability.md. It is kept
because an analysis file outlives the build that wrote it. A trend database filled
over months is a directory of these files, and they must keep opening.

A file's container is decided by its leading bytes, not its name (see
`fmriqa_io.analysis_file`), so a renamed `.qa.npz` still reads here, and a file
written under any name reads as what it is.
"""

from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from fmriqa.exceptions import InvalidAnalysisFileError

# What an `.npz` starts with, and so how `analysis` recognizes one. The archive
# is a zip, and a zip opens on its local file header's signature.
MAGIC: Final = b"PK\x03\x04"

# The JSON member carrying everything that was not an array.
_DOCUMENT = "__document__"


def read(path: Path) -> tuple[str, dict[str, NDArray[Any]]]:
    """Read the JSON text and every stored array from an `.npz` analysis file.

    Raises
    ------
    InvalidAnalysisFileError
        If the file is not a readable NumPy archive, or carries no
        `__document__` member.
    """
    try:
        with np.load(path, allow_pickle=False) as archive:
            names = list(archive.files)
            if _DOCUMENT not in names:
                raise InvalidAnalysisFileError(path, "not an fmri-qa analysis file")
            text = _document_text(archive[_DOCUMENT])
            arrays = {name: archive[name] for name in names if name != _DOCUMENT}
    except InvalidAnalysisFileError:
        raise
    except Exception as exc:
        # Broad on purpose, and only around the library calls. A damaged archive
        # comes back as `BadZipFile`, but a fuzzed one also reaches `zlib.error`
        # from the inflater, `NotImplementedError` and `tokenize.TokenError` from
        # the `.npy` header parser, and `EOFError` from a truncated member.
        # They all mean the same thing here.
        raise InvalidAnalysisFileError(
            path, f"unreadable NumPy archive: {exc}"
        ) from exc
    return text, arrays


def _document_text(member: NDArray[Any]) -> str:
    """Decode the JSON text of the `__document__` member, in either stored form.

    This is read before the schema version is known, since the version is
    inside this document. So the two forms are told apart by dtype, not by
    version. `uint8` is the UTF-8 bytes the last builds to write an `.npz` used,
    and a NumPy `<U` string is what every earlier archive carries.
    """
    if member.dtype == np.uint8:
        return bytes(member).decode("utf-8")
    return str(member)
