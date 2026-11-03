"""The names dcm2niix's outputs are filed under, from filenames and sidecar bytes."""

from collections.abc import Mapping

from fmriqa.types import Sidecar
from fmriqa_io.convert import filing
from fmriqa_io.paths import NIFTI_SUFFIXES, nifti_stem

from .exceptions import NameCollisionError

__all__ = ["name_outputs"]


def name_outputs(files: Mapping[str, bytes]) -> dict[str, str]:
    """Map each dcm2niix output filename to the name `import_dicom` files it under.

    `files` holds every output the browser got, bare filenames to bytes. Only
    the bytes of `<stem>.json`, for a NIfTI `<stem>.nii[.gz]` also present, are
    read; pass empty bytes for anything else. A sidecar that is not UTF-8 or
    not a JSON object counts as none, so its series keeps the dcm2niix name.
    A file belonging to no NIfTI is left out of the result: leave it alone.

    Raises
    ------
    NameCollisionError
        If two inputs would be filed under one name, or one would take the
        name of a file left out.
    ValueError
        If a filename is not bare (see `filing.plan_names`).
    """
    stems = {nifti_stem(name) for name in files if name.endswith(NIFTI_SUFFIXES)}
    sidecars = {stem: _sidecar(files.get(f"{stem}.json")) for stem in sorted(stems)}
    filed = filing.plan_names(list(files), sidecars, "qa")

    # Stricter than `import_dicom`, which only refuses a destination that
    # exists. The page keeps files it leaves out under their own names, so a
    # filed name equal to one would overwrite it in the zip it writes.
    sources: dict[str, list[str]] = {n: [n] for n in files if n not in filed}
    for old, placed in filed.items():
        sources.setdefault(placed.name, []).append(old)
    if collisions := {n: tuple(s) for n, s in sources.items() if len(s) > 1}:
        raise NameCollisionError(collisions)
    return {old: placed.name for old, placed in filed.items()}


def _sidecar(data: bytes | None) -> Sidecar | None:
    if data is None:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return filing.sidecar_or_none(text)
