"""The file-path conventions shared by the loader and the command line.

The stem and sidecar rules a NIfTI series and its neighbours follow.
"""

from pathlib import Path

import pytest

from fmriqa.load.paths import nifti_stem, sidecar_path


@pytest.mark.parametrize(
    ("name", "stem"),
    [
        ("scan.nii.gz", "scan"),
        ("scan.nii", "scan"),
        ("sub-01_task-qa_bold.nii.gz", "sub-01_task-qa_bold"),
        ("scan.qa.nc", "scan.qa"),  # not a NIfTI name: the last suffix goes
        ("scan", "scan"),
    ],
)
def test_nifti_stem_strips_the_nifti_suffix(name: str, stem: str) -> None:
    assert nifti_stem(Path("some") / "dir" / name) == stem


def test_sidecar_sits_beside_the_nifti() -> None:
    assert sidecar_path("data/run1.nii.gz") == Path("data/run1.json")
