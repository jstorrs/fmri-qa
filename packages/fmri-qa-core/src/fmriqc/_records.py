"""Annotation-driven helpers for the frozen records the artifact publishes.

Two things every scalar record needs from its own annotations: reading them
reliably (`resolved_annotations`), and holding a float field to a float
(`coerce_float_fields`). A whole number handed to a `float` field -- `trim_sec=5`,
an all-int `voxel_mm` -- would otherwise be stored as an `int`, published in the
archive as NC_INT rather than NC_DOUBLE, and, mixed into a tuple, refused at
save as a vector of two kinds. Converting it once at construction means a frozen
record holds the type its annotation names, and nothing downstream has to ask.

A leaf over the standard library only, so any record module can call it.
"""

from dataclasses import fields
from functools import cache
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

# The two spellings an optional field's annotation can arrive in. `int | None`
# evaluates to a `types.UnionType`, but `Literal[0, 1] | None` -- a `typing`
# special form on the left -- evaluates to `typing.Optional[...]`, whose origin
# is `typing.Union`. They mean the same thing and a reader of annotations must
# accept both, or the field it cannot read is silently mishandled for every value.
UNIONS = (UnionType, Union)

type _FloatKind = Literal["scalar", "tuple"]


@cache
def resolved_annotations(cls: type) -> dict[str, Any]:
    """Field annotations for `cls`, resolved rather than read off `field.type`.

    `dataclasses.fields(cls).type` is whatever sits in `__annotations__` --
    the live type object today, since none of the record modules use `from
    __future__ import annotations` (PEP 563). But nothing enforces that: the
    day one of them adopts it as a stylistic change, every annotation on that
    class becomes a plain *string*, and a reader comparing against `float`
    would see the string `"float"` instead and misread every field -- for a
    reason nobody would guess from the call site. `get_type_hints` evaluates
    annotations in the class's own defining module regardless of how they're
    stored, so its readers are correct either way. The record classes are
    fixed, and this resolution runs on every record built and every artifact
    loaded or saved, so it's cached rather than repeated.
    """
    return get_type_hints(cls)


def _float_kind(annotation: Any) -> _FloatKind | None:
    """Whether `annotation` is a float, a tuple of floats, or neither.

    `None` in a union is looked through, so `float | None` is a float field;
    a tuple counts only when every element is `float` (`tuple[float, ...]` or
    a fixed-length `tuple[float, float]`).
    """
    if get_origin(annotation) in UNIONS:
        choices = [a for a in get_args(annotation) if a is not type(None)]
        return _float_kind(choices[0]) if len(choices) == 1 else None
    if annotation is float:
        return "scalar"
    if get_origin(annotation) is tuple:
        args = [a for a in get_args(annotation) if a is not Ellipsis]
        if args and all(a is float for a in args):
            return "tuple"
    return None


@cache
def _float_fields(cls: type) -> tuple[tuple[str, _FloatKind], ...]:
    """Every field of `cls` annotated as a float or a tuple of floats."""
    annotations = resolved_annotations(cls)
    found: list[tuple[str, _FloatKind]] = []
    for field in fields(cls):
        kind = _float_kind(annotations[field.name])
        if kind is not None:
            found.append((field.name, kind))
    return tuple(found)


def _as_float(value: object) -> object:
    """`value` as a float if it is exactly an `int`; anything else unchanged.

    `type(...) is int` and not `isinstance`: a bool is an int to Python but not
    a number to the archive, and is left for `validate_document` to refuse.
    """
    return float(value) if type(value) is int else value


def coerce_float_fields(record: object) -> None:
    """Replace every plain `int` in a float field of `record` with its float.

    Called in a frozen record's `__post_init__` before any check that reads a
    float field, so those checks and every reader after them see the field's
    own type. Inside a tuple each element is converted, and the tuple is
    rebuilt only if one was. Floats, bools, numpy scalars and None are left
    exactly as they are.
    """
    cls: type = type(record)
    for name, kind in _float_fields(cls):
        value = getattr(record, name)
        if kind == "scalar" and type(value) is int:
            object.__setattr__(record, name, float(value))
        elif (
            kind == "tuple"
            and isinstance(value, tuple)
            and any(type(v) is int for v in value)
        ):
            object.__setattr__(record, name, tuple(_as_float(v) for v in value))
