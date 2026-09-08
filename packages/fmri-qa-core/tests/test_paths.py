"""The file-path conventions shared by the loader and the command line.

`same_file` is what stands between an output flag and the input it would
replace, so its cases are the spellings a shell produces: a relative form, a
symlink, a hard link, and a destination that does not exist yet.
"""

import os
from pathlib import Path

import pytest

from fmriqc.load.paths import nifti_stem, same_file, sidecar_path


@pytest.mark.parametrize(
    ("name", "stem"),
    [
        ("scan.nii.gz", "scan"),
        ("scan.nii", "scan"),
        ("sub-01_task-qa_bold.nii.gz", "sub-01_task-qa_bold"),
        ("scan.qa.npz", "scan.qa"),  # not a NIfTI name: the last suffix goes
        ("scan", "scan"),
    ],
)
def test_nifti_stem_strips_the_nifti_suffix(name: str, stem: str) -> None:
    assert nifti_stem(Path("some") / "dir" / name) == stem


def test_sidecar_sits_beside_the_nifti() -> None:
    assert sidecar_path("data/run1.nii.gz") == Path("data/run1.json")


def test_same_file_sees_through_a_relative_spelling(tmp_path, monkeypatch) -> None:
    (tmp_path / "scan.nii.gz").write_bytes(b"x")
    monkeypatch.chdir(tmp_path)
    assert same_file("scan.nii.gz", tmp_path / "scan.nii.gz")
    assert same_file(Path("sub") / ".." / "scan.nii.gz", "./scan.nii.gz")


def test_same_file_sees_through_links(tmp_path) -> None:
    target = tmp_path / "scan.nii.gz"
    target.write_bytes(b"x")
    (tmp_path / "soft").symlink_to(target)
    os.link(target, tmp_path / "hard")
    assert same_file(tmp_path / "soft", target)
    assert same_file(tmp_path / "hard", target)


def test_same_file_compares_a_destination_that_does_not_exist_yet(tmp_path) -> None:
    """A future output has no identity yet; where it would land is what counts."""
    (tmp_path / "in").write_bytes(b"x")
    assert same_file(tmp_path / "sub" / ".." / "in", tmp_path / "in")
    assert not same_file(tmp_path / "out", tmp_path / "in")
    assert not same_file(tmp_path / "out", tmp_path / "other-missing")
