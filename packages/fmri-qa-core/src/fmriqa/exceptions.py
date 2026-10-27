"""Exception hierarchy for fmriqa.

`FmriqaError` is the error contract: catch it to catch anything the package
raises, including future subclasses. Each subclass also inherits the natural
stdlib type (`ValueError`) so code that already catches that keeps working (see
style/exceptions.md).
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Literal

# The step of an import that can refuse. Declared here, not with the other
# closed sets in `types`, which imports numpy; this module stays a leaf.
ConversionStage = Literal["dcm2niix", "source", "destination"]


class FmriqaError(Exception):
    """Base exception for fmriqa; catch it to catch any error the package raises."""


class InvalidChoiceError(FmriqaError, ValueError):
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


class InvalidScanError(FmriqaError, ValueError):
    """A scan or analysis parameter cannot produce valid QA metrics.

    ``field`` identifies the invalid input, ``value`` preserves the value a
    caller may want to inspect, and ``reason`` states the violated contract.
    """

    def __init__(self, field: str, value: object, reason: str) -> None:
        super().__init__(f"invalid {field} {value!r}: {reason}")
        self.field = field
        self.value = value
        self.reason = reason


class IncompatibleScansError(FmriqaError, ValueError):
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


class InvalidArtifactError(FmriqaError, ValueError):
    """An analysis artifact on disk cannot be read back, or would not be.

    Raised by `fmriqa_io.load_artifact` for a file that is not an artifact
    archive, is malformed, or was written under a schema version this build does
    not understand; and by `fmriqa_io.save_artifact` for an artifact that fails
    the same contract, before anything is written. Also a `ValueError`, the
    natural stdlib type for unusable input. `path` is the file that failed (or
    would have been written) and `reason` states what was wrong.
    """

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"cannot read artifact {path}: {reason}")
        self.path = path
        self.reason = reason


class ConversionError(FmriqaError, RuntimeError):
    """A DICOM directory could not be converted into QA-ready NIfTI.

    Raised by `convert` for every way an import can refuse: no dcm2niix to run,
    a source that is not a readable directory, a converter that exited non-zero,
    or a destination already holding files the import would overwrite. Also a
    `RuntimeError`, because the failure is in the environment or the external
    tool, not in an argument's value, so `ValueError` would be wrong.

    ``stage`` names the step that refused, one of `ConversionStage`, and
    ``reason`` states what was wrong, so a caller can branch on the stage
    instead of matching the message.
    """

    def __init__(self, stage: ConversionStage, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason
