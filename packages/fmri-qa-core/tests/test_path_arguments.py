"""Path arguments as a command line delivers them.

`same_file` stops an output flag from replacing its input. The cases are the
spellings a shell produces: a relative path, a symlink, a hard link, and a
destination that does not exist yet.
"""

import os
from pathlib import Path

from fmriqa.path_arguments import same_file


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
    """A future output has no identity yet, so compare where it would land."""
    (tmp_path / "in").write_bytes(b"x")
    assert same_file(tmp_path / "sub" / ".." / "in", tmp_path / "in")
    assert not same_file(tmp_path / "out", tmp_path / "in")
    assert not same_file(tmp_path / "out", tmp_path / "other-missing")
