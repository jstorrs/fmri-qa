"""`rename.replace_patiently`: a rename that outwaits whatever holds the file open.

The refusal it exists for is another process holding a just-written file open
(a sync client, a scanner), which nothing here can provoke. What is tested is
the policy: `Path.replace` is made to refuse a set number of times, and the
delays and the sleep are injected, so no test waits.
"""

from pathlib import Path

import pytest

from fmriqc import rename
from fmriqc.rename import replace_patiently

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

    # The last refusal is the one that describes the state the caller is left
    # in, so it is the one that escapes -- not the first, saved and re-raised.
    with pytest.raises(PermissionError, match=f"attempt {len(DELAYS) + 1}$"):
        replace_patiently(source, target, delays=DELAYS, sleep=slept.append)

    # One attempt per delay and a last one after them; every delay was spent.
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

    Bound to the constant, and the constant a real wait: long enough to outlast
    a sync client hashing a scan, short enough that a destination that will
    never let go is still reported in seconds.
    """
    defaults = replace_patiently.__kwdefaults__
    assert defaults["delays"] is rename._DELAYS
    assert list(rename._DELAYS) == sorted(rename._DELAYS)
    assert 5 <= sum(rename._DELAYS) <= 10
