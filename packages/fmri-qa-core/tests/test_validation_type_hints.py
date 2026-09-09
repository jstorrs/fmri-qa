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


@dataclass(frozen=True, slots=True)
class _Example:
    """A stand-in record with the same annotation shapes as the real ones."""

    count: int
    label: str | None


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
