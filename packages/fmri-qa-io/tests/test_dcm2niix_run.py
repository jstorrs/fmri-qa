"""Finding and running dcm2niix: the bundled binary, a named one, PATH.

Covers `fmriqa_io.convert.dcm2niix`. The flags it runs with are core's
(`test_dcm2niix_args.py`). Nothing here converts a series.
"""

import shutil
import sys

import pytest

from fmriqa_io import ConversionError
from fmriqa_io.convert.dcm2niix import find_dcm2niix, run


def test_the_bundled_binary_is_what_an_unconfigured_import_runs() -> None:
    """dcm2niix is a dependency, so `fmri-qa-import DIR` needs nothing else.

    Not skipped when the binary is absent: the dependency guarantees it.
    """
    assert find_dcm2niix().name.startswith("dcm2niix")


def test_having_no_dcm2niix_at_all_says_how_to_get_one(monkeypatch) -> None:
    """The message is the only recovery help, so it names all three routes."""
    monkeypatch.setitem(sys.modules, "dcm2niix", None)  # import raises ImportError
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(ConversionError) as excinfo:
        find_dcm2niix()

    message = str(excinfo.value)
    assert "reinstall fmri-qa-io" in message
    assert "PATH" in message
    assert "--dcm2niix" in message


def test_a_binary_that_vanishes_between_finding_and_running_is_reported(
    tmp_path,
) -> None:
    """`run` is reachable with a path `find_dcm2niix` never vetted."""
    with pytest.raises(ConversionError, match="could not run"):
        run(tmp_path / "gone", ["-o", str(tmp_path)])


def test_naming_a_dcm2niix_that_cannot_be_run_is_reported_not_fallen_past(
    tmp_path,
) -> None:
    """An explicit --dcm2niix must not be silently replaced by another binary."""
    not_executable = tmp_path / "dcm2niix"
    not_executable.write_text("")

    with pytest.raises(ConversionError) as excinfo:
        find_dcm2niix(not_executable)
    assert excinfo.value.stage == "dcm2niix"
