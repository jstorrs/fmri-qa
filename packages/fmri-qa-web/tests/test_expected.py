"""The committed `web/test/fixtures/expected.json` matches a native run.

Like `test_launcher_parity.py`, this runs the dcm2niix that `find_dcm2niix`
finds (the bundled one), and does not skip without it.
"""

import json
import math

import pytest
from web_expected import OUTPUT, STUDIES, render

RTOL = 1e-9


def _close(actual: object, expected: object, where: str = "$") -> str | None:
    """Where `actual` differs from `expected`, or None.

    Numbers (of the same type) agree within `RTOL`: BLAS kernels and numpy's
    SIMD paths may change the last bit on another CPU. Keys, their order,
    strings, bools and null must be exact.
    """
    if isinstance(expected, bool) or expected is None or isinstance(expected, str):
        same = type(actual) is type(expected) and actual == expected
        return None if same else f"{where}: {actual!r} != {expected!r}"
    if isinstance(expected, int | float):
        if type(actual) is not type(expected):
            return f"{where}: {actual!r} != {expected!r}"
        assert isinstance(actual, int | float)
        ok = math.isclose(actual, expected, rel_tol=RTOL, abs_tol=0.0)
        return None if ok else f"{where}: {actual!r} != {expected!r}"
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return f"{where}: {actual!r} != {expected!r}"
        diffs = (
            _close(a, e, f"{where}[{i}]")
            for i, (a, e) in enumerate(zip(actual, expected, strict=True))
        )
        return next((d for d in diffs if d), None)
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or list(actual) != list(expected):
            return f"{where}: expected the keys {list(expected)}, got {actual!r}"
        diffs = (_close(actual[k], v, f"{where}.{k}") for k, v in expected.items())
        return next((d for d in diffs if d), None)
    raise TypeError(f"{where}: not JSON: {expected!r}")


def test_the_committed_expectations_are_current() -> None:
    committed = json.loads(OUTPUT.read_text(encoding="utf-8"))
    difference = _close(json.loads(render()), committed)
    assert difference is None, (
        f"web/test/fixtures/expected.json is stale ({difference}); regenerate it "
        "with `uv run python scripts/web_expected.py`"
    )


@pytest.mark.parametrize(
    ("actual", "expected", "same"),
    [
        (1.0 + 1e-12, 1.0, True),
        (1.0 + 1e-6, 1.0, False),
        (0, 0.0, False),
        (None, None, True),
        (False, 0, False),
        ({"b": 1, "a": 2}, {"a": 2, "b": 1}, False),
        (["x"], ["x"], True),
    ],
)
def test_the_comparison_allows_only_last_bits_of_floats(
    actual: object, expected: object, *, same: bool
) -> None:
    assert (_close(actual, expected) is None) is same


def test_one_study_analyzes_and_the_other_is_too_short() -> None:
    document = json.loads(OUTPUT.read_text(encoding="utf-8"))

    assert list(document) == list(STUDIES)
    qa, short = (document[study] for study in STUDIES)
    assert [(r["stem"], r["kind"]) for r in qa] == [
        ("20260909_143012_s002_QA_EPI_ISO", "report")
    ]
    assert [(r["stem"], r["kind"], r["stage"]) for r in short] == [
        ("20260909_143012_s002_QA_EPI_ISO", "failure", "analyze"),
        ("20260909_145533_s011_QA_EPI_32ch_rep", "failure", "analyze"),
    ]
    assert all("frame count 2" in r["reason"] for r in short)
