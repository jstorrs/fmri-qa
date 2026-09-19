"""``atomic_file``: a sibling temporary path, moved into place on success."""

import os
import stat
import sys

import pytest

from fmriqc_report.atomic import atomic_file


def test_atomic_file_writes_through_the_temporary_and_replaces_the_target(
    tmp_path,
) -> None:
    target = tmp_path / "out.txt"

    with atomic_file(target) as temporary:
        assert temporary.parent == tmp_path
        assert temporary.name.startswith(".out.txt.")
        assert temporary.name.endswith(".tmp")
        temporary.write_text("payload", encoding="utf-8")

    assert target.read_text(encoding="utf-8") == "payload"
    assert not list(tmp_path.glob(".out.txt.*"))


def test_atomic_file_leaves_an_existing_target_unchanged_on_failure(tmp_path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("previous", encoding="utf-8")

    with pytest.raises(RuntimeError, match="boom"), atomic_file(target) as temporary:
        temporary.write_text("partial", encoding="utf-8")
        raise RuntimeError("boom")

    assert target.read_text(encoding="utf-8") == "previous"
    assert [path.name for path in tmp_path.iterdir()] == ["out.txt"]


def test_atomic_file_leaves_no_target_when_none_existed_before_a_failure(
    tmp_path,
) -> None:
    target = tmp_path / "out.txt"

    with pytest.raises(RuntimeError, match="boom"), atomic_file(target):
        raise RuntimeError("boom")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_atomic_file_output_respects_the_umask(tmp_path) -> None:
    target = tmp_path / "out.txt"
    old_umask = os.umask(0o022)
    try:
        with atomic_file(target) as temporary:
            temporary.write_text("payload", encoding="utf-8")
    finally:
        os.umask(old_umask)

    assert stat.S_IMODE(target.stat().st_mode) == 0o644
