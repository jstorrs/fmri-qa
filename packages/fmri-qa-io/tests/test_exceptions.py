"""fmri-qa-io's exceptions: one root with core's, and the import's refusals."""

from pathlib import Path

import pytest

from fmriqa.exceptions import FmriqaError, InvalidChoiceError
from fmriqa_io import ConversionError, import_dicom


def test_a_conversion_error_is_an_fmriqa_error_and_a_runtime_error() -> None:
    """Catching `FmriqaError` still catches what io raises."""
    error = ConversionError("source", "not a directory")
    assert isinstance(error, FmriqaError)
    assert isinstance(error, RuntimeError)
    assert error.stage == "source"
    assert error.reason == "not a directory"


def test_import_dicom_rejects_unknown_name_style(tmp_path: Path) -> None:
    destination = tmp_path / "out"
    with pytest.raises(InvalidChoiceError, match="names"):
        import_dicom(tmp_path, destination, names="QA")  # type: ignore[arg-type]
    assert not destination.exists()


def test_import_dicom_rejects_unknown_anonymize_mode(tmp_path: Path) -> None:
    destination = tmp_path / "out"
    with pytest.raises(InvalidChoiceError, match="anonymize"):
        import_dicom(tmp_path, destination, anonymize="y")  # type: ignore[arg-type]
    assert not destination.exists()
