"""The worker's entry points: the typed API, with strict JSON strings out.

Pyodide hands Python no `bytes`: the worker converts a JS `Uint8Array` with
`pyodide.toPy`, which gives a `memoryview`, and a JS object or Map of them
gives a `dict[str, memoryview]`. These functions accept any `Buffer` (so
`bytes` too) and copy it to `bytes` once, here; the typed API stays on `bytes`.
A JS array of strings via `toPy` is a `list[str]`.

`allow_nan=False` makes a stray NaN a raised `ValueError` here instead of a
document a browser's `JSON.parse` rejects. Records already carry `None` for
non-finite floats (`metric_record`). Strings are returned verbatim, so JS must
pass them on unparsed: a JS round trip turns `2.0` into `2`. For the same
reason a report also carries `record_document_json`, the text the page saves
as `<stem>.qa.json` without parsing it, and every result `result_json`, the
small string the page keeps to hand back to `document_json` for its
`fmri-qa.json`.
"""

import json
from collections.abc import Buffer, Mapping, Sequence
from dataclasses import asdict
from typing import get_args

from . import naming, series
from .document import Recorded, Unrecorded, batch_document, contract
from .exceptions import InvalidResultError

__all__ = ["analyze_json", "contract_json", "document_json", "names_json"]

_STAGES = frozenset(get_args(series.Stage.__value__))


def _dumps(value: object) -> str:
    return json.dumps(value, allow_nan=False)


def _bytes(value: Buffer) -> bytes:
    """Copy `value` to bytes; a non-buffer is a `TypeError`, not zero bytes."""
    if not isinstance(value, Buffer):
        raise TypeError(f"expected bytes or a memoryview, got {type(value).__name__}")
    return bytes(value)


def analyze_json(nifti: Buffer, sidecar: Buffer | None, stem: str) -> str:
    """Analyze one series; `{"kind": "report", ...}` or `{"kind": "failure", ...}`.

    A report adds `record_document_json`, the text of its `<stem>.qa.json`:
    the document `fmri-qa --json` prints for that one scan. Every result adds
    `result_json`: the same result without its page or warnings (`kind`,
    `stem` and `record`, or `kind`, `stem`, `stage` and `reason`), which is
    all `document_json` reads, so the page can keep it for a whole run. A
    series that fails to decode, analyze or render is a `"failure"` result,
    not a raise. Raises to JS only `TypeError` for a `nifti` or `sidecar`
    that is not a buffer.
    """
    result = series.analyze_series(
        _bytes(nifti), None if sidecar is None else _bytes(sidecar), stem=stem
    )
    if isinstance(result, series.SeriesReport):
        compact = {"kind": "report", "stem": result.stem, "record": result.record}
        return _dumps(
            {
                "kind": "report",
                **asdict(result),
                "record_document_json": _document_text(batch_document([result])),
                "result_json": _dumps(compact),
            }
        )
    compact = {
        "kind": "failure",
        "stem": result.stem,
        "stage": result.stage,
        "reason": result.reason,
    }
    return _dumps({"kind": "failure", **asdict(result), "result_json": _dumps(compact)})


def _document_text(document: dict[str, object]) -> str:
    """Return an envelope exactly as `fmri-qa --json` prints it."""
    return json.dumps(document, indent=2, allow_nan=False) + "\n"


def names_json(files: Mapping[str, Buffer]) -> str:
    """Return `name_outputs` as a JSON object, old filename to new.

    Raises to JS `TypeError` for a value that is not a buffer, `ValueError`
    for a name that is not bare, and `NameCollisionError` (a `ValueError`)
    when two files would share a filed name.
    """
    return _dumps(naming.name_outputs({k: _bytes(v) for k, v in files.items()}))


def document_json(results: Sequence[str]) -> str:
    """Return the `--json` envelope for a batch, as `fmri-qa --json` prints it.

    Each item is an `analyze_json` string, its `result_json`, or
    `{"kind": "error", "stem": ..., "reason": ...}` for a series that failed
    where Python never saw it (the page's own reason); an error is listed in
    `errors` as a failure is. The default settings are used, as
    `analyze_json` does. Raises `InvalidResultError` (a `ValueError`) naming
    the first item that is none of these.
    """
    return _document_text(
        batch_document([_parsed(i, text) for i, text in enumerate(results)])
    )


def contract_json() -> str:
    """Return `document.contract()` as JSON. Raises nothing."""
    return _dumps(contract())


def _parsed(index: int, text: str) -> Recorded | Unrecorded:
    """Parse one `analyze_json` string, checking only what the envelope reads."""
    try:
        item = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise InvalidResultError(index, f"not JSON ({exc})") from exc
    if not isinstance(item, dict):
        raise InvalidResultError(
            index, f"expected an object, got {type(item).__name__}"
        )
    stem = item.get("stem")
    if not isinstance(stem, str):
        raise InvalidResultError(index, f"stem must be a string, got {stem!r}")
    match item.get("kind"):
        case "report":
            record = item.get("record")
            if not isinstance(record, dict):
                raise InvalidResultError(
                    index, f"record must be an object, got {record!r}"
                )
            return Recorded(stem, record)
        case "failure" | "error" as kind:
            # A failure is Python's and names its stage; an error is the page's.
            if kind == "failure" and item.get("stage") not in _STAGES:
                raise InvalidResultError(
                    index,
                    f"stage must be one of {sorted(_STAGES)}, "
                    f"got {item.get('stage')!r}",
                )
            reason = item.get("reason")
            if not isinstance(reason, str):
                raise InvalidResultError(
                    index, f"reason must be a string, got {reason!r}"
                )
            return Unrecorded(stem, reason)
        case kind:
            raise InvalidResultError(
                index,
                f"kind must be 'report', 'failure' or 'error', got {kind!r}",
            )
