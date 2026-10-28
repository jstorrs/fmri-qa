"""`rename.replace_patiently`: a rename that outwaits whatever holds the file open.

It exists for another process holding a just-written file open (a sync
client, a scanner), which no test can provoke. The tests cover the policy:
`Path.replace` refuses a set number of times, and the delays and sleep are
injected, so no test waits.

`rename.atomic_file`, the write-then-rename built on it, is tested at the end,
followed by `write_text_atomically` over it.
"""

import os
import stat
import sys
from pathlib import Path

import pytest

from fmriqa_io import rename
from fmriqa_io.rename import atomic_file, replace_patiently, write_text_atomically

DELAYS = (0.1, 0.2, 0.4)


def _refuse(
    monkeypatch: pytest.MonkeyPatch, times: int, error: type[OSError]
) -> list[Path]:
    """Make `Path.replace` raise `error` for its first `times` calls; log them all."""
    real = Path.replace
    calls: list[Path] = []

    def replace(self: Path, target: Path) -> Path:
        calls.append(self)
        if len(calls) <= times:
            raise error(13, f"held open, attempt {len(calls)}")
        return real(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    return calls


def test_an_unopposed_rename_happens_once_and_never_sleeps(tmp_path: Path) -> None:
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_text("scan")
    slept: list[float] = []

    replace_patiently(source, target, delays=DELAYS, sleep=slept.append)

    assert target.read_text() == "scan"
    assert not source.exists()
    assert slept == []


def test_a_held_file_is_renamed_once_it_is_let_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_text("scan")
    calls = _refuse(monkeypatch, 2, PermissionError)
    slept: list[float] = []

    replace_patiently(source, target, delays=DELAYS, sleep=slept.append)

    assert target.read_text() == "scan"
    assert len(calls) == 3
    assert slept == [0.1, 0.2]


def test_a_directory_is_renamed_the_same_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publishing renames a whole series directory, not a file."""
    source, target = tmp_path / "work", tmp_path / "series"
    source.mkdir()
    (source / "scan.nii.gz").write_text("scan")
    calls = _refuse(monkeypatch, 1, PermissionError)
    slept: list[float] = []

    replace_patiently(source, target, delays=DELAYS, sleep=slept.append)

    assert (target / "scan.nii.gz").read_text() == "scan"
    assert len(calls) == 2
    assert slept == [0.1]


def test_a_file_never_let_go_fails_with_the_last_attempts_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_text("scan")
    calls = _refuse(monkeypatch, 99, PermissionError)
    slept: list[float] = []

    # The last refusal describes the state the caller is left in, so it escapes.
    with pytest.raises(PermissionError, match=f"attempt {len(DELAYS) + 1}$"):
        replace_patiently(source, target, delays=DELAYS, sleep=slept.append)

    # One attempt per delay, plus a last one after them. Every delay was spent.
    assert len(calls) == len(DELAYS) + 1
    assert slept == list(DELAYS)
    assert source.read_text() == "scan"


def test_any_other_failure_is_not_waited_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_text("scan")
    calls = _refuse(monkeypatch, 99, FileNotFoundError)
    slept: list[float] = []

    with pytest.raises(FileNotFoundError):
        replace_patiently(source, target, delays=DELAYS, sleep=slept.append)

    assert len(calls) == 1
    assert slept == []


def test_with_no_delays_it_is_a_plain_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One attempt, and the error straight through."""
    source, target = tmp_path / "a", tmp_path / "b"
    source.write_text("scan")
    calls = _refuse(monkeypatch, 99, PermissionError)

    def never(_delay: float) -> None:
        raise AssertionError("slept with no delays to spend")

    with pytest.raises(PermissionError):
        replace_patiently(source, target, delays=(), sleep=never)

    assert len(calls) == 1


def test_the_default_is_the_ladder_on_every_platform() -> None:
    """Every test above injects `delays`; this pins what a real caller gets.

    Bound to the constant: long enough to outlast a sync client hashing a scan,
    short enough that an unreleasable destination is reported in seconds.
    """
    defaults = replace_patiently.__kwdefaults__
    assert defaults["delays"] is rename._DELAYS
    assert list(rename._DELAYS) == sorted(rename._DELAYS)
    assert 5 <= sum(rename._DELAYS) <= 10


def test_atomic_file_writes_through_the_temporary_and_replaces_the_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "out.txt"

    with atomic_file(target) as temporary:
        assert temporary.parent == tmp_path
        assert temporary.name.startswith(".out.txt.")
        assert temporary.name.endswith(".tmp")
        temporary.write_text("payload", encoding="utf-8")

    assert target.read_text(encoding="utf-8") == "payload"
    assert not list(tmp_path.glob(".out.txt.*"))


def test_atomic_file_leaves_an_existing_target_unchanged_on_failure(
    tmp_path: Path,
) -> None:
    target = tmp_path / "out.txt"
    target.write_text("previous", encoding="utf-8")

    with pytest.raises(RuntimeError, match="boom"), atomic_file(target) as temporary:
        temporary.write_text("partial", encoding="utf-8")
        raise RuntimeError("boom")

    assert target.read_text(encoding="utf-8") == "previous"
    assert [path.name for path in tmp_path.iterdir()] == ["out.txt"]


def test_atomic_file_leaves_no_target_when_none_existed_before_a_failure(
    tmp_path: Path,
) -> None:
    target = tmp_path / "out.txt"

    with pytest.raises(RuntimeError, match="boom"), atomic_file(target):
        raise RuntimeError("boom")

    assert not target.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_atomic_file_output_respects_the_umask(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    old_umask = os.umask(0o022)
    try:
        with atomic_file(target) as temporary:
            temporary.write_text("payload", encoding="utf-8")
    finally:
        os.umask(old_umask)

    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_write_text_atomically_writes_exactly_one_file(tmp_path: Path) -> None:
    destination = tmp_path / "out" / "report.html"

    result = write_text_atomically(destination, "<p>é</p>")

    assert result == destination
    assert destination.read_text(encoding="utf-8") == "<p>é</p>"
    assert [path for path in tmp_path.rglob("*") if path.is_file()] == [destination]


def test_write_text_atomically_accepts_a_string_path(tmp_path: Path) -> None:
    result = write_text_atomically(str(tmp_path / "out.txt"), "payload")

    assert result == tmp_path / "out.txt"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_write_text_atomically_output_respects_the_umask(tmp_path: Path) -> None:
    destination = tmp_path / "out" / "report.html"
    old_umask = os.umask(0o022)
    try:
        write_text_atomically(destination, "payload")
    finally:
        os.umask(old_umask)

    assert stat.S_IMODE(destination.stat().st_mode) == 0o644


def test_write_text_atomically_is_atomic_when_the_write_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "report.html"
    target.write_text("previous report", encoding="utf-8")
    original_write_text = Path.write_text

    def fail_write_text(self: Path, *args: object, **kwargs: object) -> int:
        if self.name.startswith(".report.html."):
            raise OSError("disk full")
        return original_write_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", fail_write_text)

    with pytest.raises(OSError, match="disk full"):
        write_text_atomically(target, "new report")

    assert target.read_text(encoding="utf-8") == "previous report"
    assert [path.name for path in tmp_path.iterdir()] == ["report.html"]
