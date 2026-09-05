"""Exception hierarchy for fmriqc.

One base class (`FmriqcError`) is the error contract: catch it to catch anything
the package raises, and new subclasses can be added without breaking that catch.
Each subclass also inherits the natural stdlib type (`ValueError`,
`FileNotFoundError`) so code that already catches those keeps working — the dual
base resolves the tension between "one base exception per package" and "use the
standard exception when appropriate" (see style/exceptions.md).
"""

from collections.abc import Sequence
from pathlib import Path


class FmriqcError(Exception):
    """Base exception for fmriqc; catch this to catch any error the package raises."""


class MissingSidecarError(FmriqcError, FileNotFoundError):
    """The required BIDS JSON sidecar was not found beside a NIfTI.

    Also a `FileNotFoundError`, since the underlying condition is a missing file.
    `sidecar` is the path that was looked for.
    """

    def __init__(self, sidecar: Path) -> None:
        super().__init__(
            f"required BIDS JSON sidecar not found: {sidecar} "
            f"(convert the DICOM with dcm2niix so a .json is written alongside "
            f"the NIfTI)"
        )
        self.sidecar = sidecar


class InvalidChoiceError(FmriqcError, ValueError):
    """A parameter was given a value outside its permitted set.

    Also a `ValueError`, the natural stdlib type for a bad argument value.
    Carries the offending `name`/`value` and the permitted `choices` so a caller
    can react programmatically, not only print.
    """

    def __init__(self, name: str, value: object, choices: Sequence[object]) -> None:
        super().__init__(f"unknown {name} {value!r}; choose from {tuple(choices)}")
        self.name = name
        self.value = value
        self.choices = tuple(choices)


class InvalidScanError(FmriqcError, ValueError):
    """A scan or analysis parameter cannot produce valid QA metrics.

    ``field`` identifies the invalid input, ``value`` preserves the value a
    caller may want to inspect, and ``reason`` states the violated contract.
    """

    def __init__(self, field: str, value: object, reason: str) -> None:
        super().__init__(f"invalid {field} {value!r}: {reason}")
        self.field = field
        self.value = value
        self.reason = reason


class IncompatibleScansError(FmriqcError, ValueError):
    """A high/low flip-angle scan pair cannot be combined.

    Raised when the two scans differ in geometry or acquisition settings, or
    when their phantom cores do not overlap. Also a `ValueError`. The mismatched
    ``field`` and the two values are retained for programmatic handling.
    """

    def __init__(
        self,
        field: str,
        high_value: object,
        low_value: object,
        reason: str | None = None,
    ) -> None:
        detail = f"incompatible {field}: high={high_value!r}, low={low_value!r}"
        if reason:
            detail += f"; {reason}"
        super().__init__(detail)
        self.field = field
        self.high_value = high_value
        self.low_value = low_value
        self.reason = reason


class InvalidArtifactError(FmriqcError, ValueError):
    """An analysis artifact on disk cannot be read back.

    Raised by `analysis.load_artifact` for a file that is not an artifact
    archive, is malformed, or was written under a schema version this build does
    not understand. Also a `ValueError`, the natural stdlib type for unusable
    input. `path` is the file that failed and `reason` states what was wrong.
    """

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"cannot read artifact {path}: {reason}")
        self.path = path
        self.reason = reason
