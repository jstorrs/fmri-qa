"""File-path conventions for a NIfTI series and the files that sit beside it.

The stem and sidecar rules are BIDS/dcm2niix's: `sub-01_task-qa_bold.nii.gz`
keeps its metadata in `sub-01_task-qa_bold.json`. Both the loader and the
command line need them, so they are defined once here rather than each
stripping `.nii.gz` its own way.
"""

from pathlib import Path

# Longest suffix first, so `.nii.gz` is not mistaken for a bare `.gz`.
NIFTI_SUFFIXES = (".nii.gz", ".nii")


def nifti_stem(path: str | Path) -> str:
    """The file name with its NIfTI suffix removed (`scan.nii.gz` -> `scan`).

    A name without a NIfTI suffix loses its last suffix instead, as `Path.stem`
    would, so a caller always gets *something* to name an output after.
    """
    name = Path(path).name
    for suffix in NIFTI_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def sidecar_path(path: str | Path) -> Path:
    """Where the BIDS JSON sidecar of the NIfTI at `path` sits: beside it, `.json`."""
    return Path(path).with_name(nifti_stem(path) + ".json")


def same_file(a: str | Path, b: str | Path) -> bool:
    """Whether two paths name one file — through relative forms and links alike.

    An output that names one of its own inputs destroys that input the moment
    the writer moves its finished file into place, and the spelling of the two
    paths says nothing about whether that will happen (`./scan.nii.gz` and an
    absolute path, a symlink and its target, two hard links). Existing files are
    compared by identity; a path that does not exist yet can only be compared
    by where it would be created.
    """
    first, second = Path(a), Path(b)
    try:
        return first.samefile(second)
    except OSError:
        return first.resolve() == second.resolve()
