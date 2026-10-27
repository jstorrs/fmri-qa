"""The dcm2niix command line: the flags that are not a matter of taste.

Covers `convert.dcm2niix`: pinned flags, argument order, passthrough handling
and warnings, and the version banner. Nothing here runs or finds a binary;
fmri-qa-io's `test_dcm2niix_run.py` does.
"""

from itertools import pairwise
from pathlib import Path, PurePosixPath

import pytest

from fmriqa.convert.dcm2niix import PINNED, build_args, flags, version


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


def test_the_flags_are_build_args_without_the_paths() -> None:
    """`flags` is what another converter mirrors, so it must be what runs here.

    The full argument list starts with it, and it names neither directory.
    """
    chosen = flags(anonymize="all", compress=False, depth=2, template="%s")
    args = build_args(
        PurePosixPath("study"),
        "out",
        anonymize="all",
        compress=False,
        depth=2,
        template="%s",
    )

    assert args[: len(chosen)] == chosen
    assert args[len(chosen) :] == ["-o", "out", "study"]
    assert "-o" not in chosen
    assert chosen[: len(PINNED)] == list(PINNED)
    # A converter calling `flags()` bare gets what a bare `build_args` runs.
    assert flags() == build_args("study", "out")[:-3]


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
