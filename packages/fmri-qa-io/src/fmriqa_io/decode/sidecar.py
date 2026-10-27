"""Parse the BIDS JSON sidecar's text into the mapping core reads.

The sidecar is optional (a scanner export never went through dcm2niix), and its
absence is the caller's to report. A sidecar that is present but unreadable
fails loudly, since we would be misreading real metadata. What the fields mean
is core's (`fmriqa.load.metadata`, `pe_axis`, `repetition_time`).
"""

import json

from fmriqa.exceptions import InvalidScanError
from fmriqa.types import Sidecar

__all__ = [
    "parse_sidecar",
]


def parse_sidecar(raw: bytes | str, *, source: str) -> Sidecar:
    """Parse a BIDS JSON sidecar into a mapping of its fields.

    `source` identifies the sidecar in an error, since there may be no file.

    Raises
    ------
    InvalidScanError
        If `raw` is not parseable as a JSON object.
    """
    # `ValueError` covers malformed JSON and bytes that are not valid UTF-8.
    try:
        parsed: object = json.loads(raw)
    except ValueError as e:
        raise InvalidScanError(
            "BIDS JSON sidecar", source, f"could not be parsed: {e}"
        ) from e
    if not isinstance(parsed, dict):
        raise InvalidScanError(
            "BIDS JSON sidecar",
            source,
            "expected a JSON object of acquisition metadata",
        )
    # A JSON object's keys are always strings. Rebuilding the dict tells the
    # type checkers so, since `json.loads` is typed as returning anything.
    return {str(key): value for key, value in parsed.items()}
