"""The dcm2niix command line: the flags that are not a matter of taste.

Covers `convert.dcm2niix`: pinned flags, argument order, passthrough handling
and warnings, the version banner, and finding a binary. Nothing here converts a
series.
"""

import shutil
import sys
from itertools import pairwise
from pathlib import Path

import pytest

import fmriqc as q
from fmriqc.convert.dcm2niix import PINNED, build_args, find_dcm2niix, run, version


def test_every_conversion_pins_the_flags_that_keep_a_series_checkable() -> None:
    """`-l o` above all: see `convert.dcm2niix` for what `-l y` costs.

    Asserted as adjacent pairs, since `-l` and its value only matter together.
    """
    args = build_args(Path("in"), Path("out"))
    pairs = set(pairwise(args))

    assert {("-l", "o"), ("-g", "i"), ("-b", "y"), ("-w", "2")} <= pairs
    assert args[: len(PINNED)] == list(PINNED)


def test_the_source_directory_is_the_last_argument() -> None:
    """dcm2niix takes its input folder positionally, after every option."""
    assert build_args(Path("study"), Path("out"))[-1] == "study"


def test_anonymizing_defaults_to_keeping_the_dates_the_name_needs() -> None:
    """`-ba o` strips the patient and keeps the dates; `-ba y` would drop both.

    dcm2niix defaults to `y`. QA names use the series' acquisition date, so we
    depart from it.
    """
    assert "-ba" in build_args(Path("in"), Path("out"))
    for mode, flag in (("pii", "o"), ("all", "y"), ("none", "n")):
        args = build_args(Path("in"), Path("out"), anonymize=mode)
        assert args[args.index("-ba") + 1] == flag


def test_passthrough_arguments_come_after_everything_chosen_here() -> None:
    """Last wins in dcm2niix, so an escape hatch must come last."""
    args = build_args(Path("in"), Path("out"), extra=["-i", "y"])

    assert args[-3:] == ["-i", "y", "in"]


def test_a_passthrough_that_rescales_the_integers_does_not_pass_quietly() -> None:
    """`-l y` disarms the saturation check without breaking anything visibly.

    It leaves an integer NIfTI, so `QAScan.stored_integer` stays True and the
    storage warning never fires, and a clipped acquisition reads as clean.
    Overriding the pin is allowed, but not silently.
    """
    with pytest.warns(UserWarning, match="saturation check"):
        build_args(Path("in"), Path("out"), extra=["-l", "y"])


def test_pinning_is_not_re_warned_when_the_passthrough_agrees_with_it() -> None:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        build_args(Path("in"), Path("out"), extra=["-l", "o", "-i", "y"])


def test_the_version_is_read_out_of_dcm2niix_s_own_banner() -> None:
    banner = "Chris Rorden's dcm2niiX version v1.0.20260724 (JP2:OpenJPEG) GCC10"

    assert version(banner) == "v1.0.20260724"
    assert version("no banner here") is None


def test_the_bundled_binary_is_what_an_unconfigured_import_runs() -> None:
    """dcm2niix is a dependency, so `fmri-qa-import DIR` needs nothing else.

    Not skipped when the binary is absent: the dependency guarantees it.
    """
    assert find_dcm2niix().name.startswith("dcm2niix")


def test_having_no_dcm2niix_at_all_says_how_to_get_one(monkeypatch) -> None:
    """The message is the only recovery help, so it names all three routes."""
    monkeypatch.setitem(sys.modules, "dcm2niix", None)  # import raises ImportError
    monkeypatch.setattr(shutil, "which", lambda _name: None)

    with pytest.raises(q.ConversionError) as excinfo:
        find_dcm2niix()

    message = str(excinfo.value)
    assert "reinstall fmri-qa-core" in message
    assert "PATH" in message
    assert "--dcm2niix" in message


def test_a_binary_that_vanishes_between_finding_and_running_is_reported(
    tmp_path,
) -> None:
    """`run` is reachable with a path `find_dcm2niix` never vetted."""
    with pytest.raises(q.ConversionError, match="could not run"):
        run(tmp_path / "gone", ["-o", str(tmp_path)])


def test_naming_a_dcm2niix_that_cannot_be_run_is_reported_not_fallen_past(
    tmp_path,
) -> None:
    """An explicit --dcm2niix must not be silently replaced by another binary."""
    not_executable = tmp_path / "dcm2niix"
    not_executable.write_text("")

    with pytest.raises(q.ConversionError) as excinfo:
        find_dcm2niix(not_executable)
    assert excinfo.value.stage == "dcm2niix"
