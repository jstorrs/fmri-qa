"""Exceptions raised by fmriqa_io.

Each one subclasses `fmriqa.exceptions.FmriqaError`, so the hierarchy keeps one
root: catching `FmriqaError` still catches anything either package raises (see
style/exceptions.md).
"""

from typing import Literal

from fmriqa.exceptions import FmriqaError

# The step of an import that can refuse.
ConversionStage = Literal["dcm2niix", "source", "destination"]


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
