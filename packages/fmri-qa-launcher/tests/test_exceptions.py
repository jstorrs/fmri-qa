"""The exception contract: every promised error, and its dual catchability."""

from importlib.metadata import PackageNotFoundError

import pytest

from fmriqa_launcher import version as version_module
from fmriqa_launcher.exceptions import LauncherError, RequestError, SessionError
from fmriqa_launcher.version import launcher_version


def test_request_error_keeps_its_problems_and_renders_them_joined() -> None:
    err = RequestError(["missing PatientID", "no image files found"])
    assert err.problems == ("missing PatientID", "no image files found")
    assert str(err) == "missing PatientID; no image files found"


def test_request_error_is_a_launcher_error() -> None:
    with pytest.raises(LauncherError):
        raise RequestError(["bad series"])


def test_session_error_is_a_launcher_error() -> None:
    with pytest.raises(LauncherError):
        raise SessionError("no converter available")


def test_launcher_version_returns_a_non_empty_string() -> None:
    assert launcher_version()


def test_launcher_version_falls_back_when_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(version_module, "version", _raise)
    assert launcher_version() == "unknown"
