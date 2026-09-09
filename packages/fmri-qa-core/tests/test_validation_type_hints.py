"""The artifact validator's field types survive stringized annotations.

`dataclasses.fields(cls).type` is the live type object only as long as nothing
in a class's defining module writes `from __future__ import annotations` (PEP
563) -- the moment it does, every annotation on that class becomes a plain
*string*, and reading `field.type` raw would make `_matches` compare a value
against the string `"int"` instead of `int` and reject everything. This
module's own `from __future__ import annotations` reproduces that exact
condition for `_Example` below without touching the real artifact records, so
this pins `_resolved_annotations` (`analysis.validation`, built on
`typing.get_type_hints`) against the regression a stylistic change elsewhere
in the package could otherwise reintroduce silently.
"""

from __future__ import annotations

from dataclasses import dataclass

from fmriqc.analysis.validation import _matches, _resolved_annotations
from fmriqc.types import PeAxis


@dataclass(frozen=True, slots=True)
class _Example:
    """A stand-in record with the same annotation shapes as the real ones."""

    count: int
    label: str | None
    axis: PeAxis | None


def test_resolved_annotations_recover_real_types_from_a_stringized_module() -> None:
    hints = _resolved_annotations(_Example)

    assert hints["count"] is int  # not the string "int"
    assert _matches(3, hints["count"])
    assert not _matches(3.5, hints["count"])

    # `str | None` is `types.UnionType` at runtime, whether or not the module
    # that wrote it stringizes annotations; the resolved hint must round-trip
    # to the same thing `_matches` already knows how to handle.
    assert _matches(None, hints["label"])
    assert _matches("x", hints["label"])
    assert not _matches(3, hints["label"])


def test_matches_accepts_both_spellings_of_an_optional_annotation() -> None:
    """An optional `Literal` is a `typing.Union`, not a `types.UnionType`.

    `str | None` evaluates to `types.UnionType`, but a `typing` special form on
    the left -- `PeAxis | None`, i.e. `Literal[0, 1] | None` -- evaluates to
    `typing.Optional[...]`, whose origin is `typing.Union` instead. The two mean
    the same thing, and a validator that knows only the first silently rejects
    *every* value of such a field, including the valid ones: the failure is a
    saved artifact refusing to be written, attributed to a field that is
    perfectly well-formed. `Measurements.pe_axis` and
    `AnalysisSettings.pe_axis_override` are both this shape.
    """
    hints = _resolved_annotations(_Example)

    assert _matches(0, hints["axis"])
    assert _matches(1, hints["axis"])
    assert _matches(None, hints["axis"])
    # Outside the closed set -- including the through-plane axis a sidecar can
    # name, which is what the artifact validator relies on this to refuse.
    assert not _matches(2, hints["axis"])
    assert not _matches(-1, hints["axis"])
    # `True == 1`, so a membership test would have let a bool through here.
    assert not _matches(True, hints["axis"])
