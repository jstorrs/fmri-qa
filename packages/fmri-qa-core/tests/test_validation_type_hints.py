"""The analysis validator's field types survive stringized annotations.

With `from __future__ import annotations` (PEP 563), `dataclasses.fields(cls).type`
is a string, so reading it raw would make `_matches` compare a value against
`"int"` instead of `int` and reject everything. This module uses the future
import to reproduce that for `_Example` without touching the real analysis
records. It pins `resolved_annotations` (`fmriqa._records`, built on
`typing.get_type_hints`) against a stylistic change reintroducing the bug.
"""

from __future__ import annotations

from dataclasses import dataclass

from fmriqa._records import resolved_annotations
from fmriqa.analysis.validation import _matches
from fmriqa.types import PeAxis


@dataclass(frozen=True, slots=True)
class _Example:
    """A stand-in record with the same annotation shapes as the real ones."""

    count: int
    label: str | None
    axis: PeAxis | None


def test_resolved_annotations_recover_real_types_from_a_stringized_module() -> None:
    hints = resolved_annotations(_Example)

    assert hints["count"] is int  # not the string "int"
    assert _matches(3, hints["count"])
    assert not _matches(3.5, hints["count"])

    # `str | None` is `types.UnionType` at runtime either way. The resolved hint
    # must round-trip to what `_matches` already handles.
    assert _matches(None, hints["label"])
    assert _matches("x", hints["label"])
    assert not _matches(3, hints["label"])


def test_matches_accepts_both_spellings_of_an_optional_annotation() -> None:
    """An optional `Literal` is a `typing.Union`, not a `types.UnionType`.

    `str | None` is `types.UnionType`, but with a `typing` form on the left, as in
    `PeAxis | None`, it is `typing.Optional[...]` with origin `typing.Union`.
    A validator that knows only the first rejects every value of such a field,
    so a well-formed analysis refuses to save. `Measurements.pe_axis` and
    `AnalysisSettings.pe_axis_override` have this shape.
    """
    hints = resolved_annotations(_Example)

    assert _matches(0, hints["axis"])
    assert _matches(1, hints["axis"])
    assert _matches(None, hints["axis"])
    # Outside the closed set, including the through-plane axis a sidecar can name,
    # which the analysis validator relies on this to refuse.
    assert not _matches(2, hints["axis"])
    assert not _matches(-1, hints["axis"])
    # `True == 1`, so a membership test would have let a bool through here.
    assert not _matches(True, hints["axis"])
