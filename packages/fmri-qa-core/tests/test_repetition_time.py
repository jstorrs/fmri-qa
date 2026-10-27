"""`resolve_repetition_time`: the sidecar's TR wins over the header's.

The header value arrives already in seconds, so these are plain values.
fmri-qa-io's `test_load_scan.py` covers the same rules through real files.
"""

import warnings

import pytest

from fmriqa.load.repetition_time import resolve_repetition_time


def test_the_sidecar_wins_when_both_agree() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert resolve_repetition_time(2.0, {"RepetitionTime": 2.0}, source="s") == 2.0


def test_the_header_is_used_without_a_sidecar_value() -> None:
    assert resolve_repetition_time(2.5, {}, source="s") == 2.5


def test_disagreeing_values_warn_and_keep_the_sidecar() -> None:
    with pytest.warns(UserWarning, match=r"^scan\.nii: sidecar RepetitionTime 2 s"):
        tr = resolve_repetition_time(3.0, {"RepetitionTime": 2.0}, source="scan.nii")
    assert tr == 2.0


@pytest.mark.parametrize("value", [0, -2.0, "2000", None, float("nan"), True])
def test_an_unusable_sidecar_value_warns_and_falls_back(value: object) -> None:
    with pytest.warns(UserWarning, match=r"^scan\.nii: ignoring sidecar"):
        tr = resolve_repetition_time(2.0, {"RepetitionTime": value}, source="scan.nii")
    assert tr == 2.0
