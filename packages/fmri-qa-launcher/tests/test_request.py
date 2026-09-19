"""`RunRequest`/`FormValues`/`parse_form`: the boundary raw text crosses once."""

from pathlib import Path

import pytest

from fmriqc.exceptions import InvalidScanError
from fmriqc.settings import AnalysisSettings
from fmriqc_launcher.exceptions import RequestError
from fmriqc_launcher.request import (
    DEFAULT_SETTINGS,
    FormValues,
    RunRequest,
    _translate_settings_problem,
    parse_form,
)


def test_default_settings_match_analysis_settings_defaults() -> None:
    assert AnalysisSettings() == DEFAULT_SETTINGS


def test_parse_form_on_defaults_yields_default_settings(tmp_path: Path) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    output_dir = tmp_path / "output"

    request = parse_form(
        FormValues(dicom_dir=str(dicom_dir), output_dir=str(output_dir))
    )

    assert request.dicom_dir == dicom_dir
    assert request.output_dir == output_dir
    assert request.settings == DEFAULT_SETTINGS
    assert request.open_report is False


def test_parse_form_carries_open_report_through(tmp_path: Path) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    request = parse_form(
        FormValues(
            dicom_dir=str(dicom_dir),
            output_dir=str(tmp_path / "output"),
            open_report=True,
        )
    )
    assert request.open_report is True


def test_a_dicom_dir_that_is_not_a_directory_is_refused(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "not_a_dir"
    not_a_dir.write_text("plain file")

    with pytest.raises(RequestError) as excinfo:
        RunRequest(dicom_dir=not_a_dir, output_dir=tmp_path / "output")

    assert any(
        "not an existing directory" in problem for problem in excinfo.value.problems
    )


def test_output_dir_the_same_as_dicom_dir_is_refused(tmp_path: Path) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()

    # A path that resolves to the same directory without being spelled
    # identically -- `Path.resolve()` is what `RunRequest` compares by.
    detour = dicom_dir / "sub" / ".."

    with pytest.raises(RequestError) as excinfo:
        RunRequest(dicom_dir=dicom_dir, output_dir=detour, settings=DEFAULT_SETTINGS)

    assert any("same directory" in problem for problem in excinfo.value.problems)


def test_output_dir_that_exists_and_is_a_file_is_refused(tmp_path: Path) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    output_dir = tmp_path / "output"
    output_dir.write_text("plain file")

    with pytest.raises(RequestError) as excinfo:
        RunRequest(dicom_dir=dicom_dir, output_dir=output_dir)

    assert any("is not a directory" in problem for problem in excinfo.value.problems)


def test_an_unknown_anonymize_mode_is_refused(tmp_path: Path) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()

    with pytest.raises(RequestError) as excinfo:
        RunRequest(
            dicom_dir=dicom_dir,
            output_dir=tmp_path / "output",
            anonymize="everything",  # type: ignore[arg-type]
        )

    assert any("Anonymize" in problem for problem in excinfo.value.problems)


def test_a_non_directory_dicom_dir_reports_every_other_problem_too(
    tmp_path: Path,
) -> None:
    not_a_dir = tmp_path / "not_a_dir"
    not_a_dir.write_text("plain file")

    with pytest.raises(RequestError) as excinfo:
        RunRequest(
            dicom_dir=not_a_dir,
            output_dir=tmp_path / "output",
            anonymize="nope",  # type: ignore[arg-type]
        )

    problems = excinfo.value.problems
    assert len(problems) == 2
    assert any("not an existing directory" in p for p in problems)
    assert any("Anonymize" in p for p in problems)


def test_parse_form_reports_every_problem_at_once() -> None:
    with pytest.raises(RequestError) as excinfo:
        parse_form(
            FormValues(
                dicom_dir="",
                output_dir="",
                trim_sec="abc",
                detrend="nonsense",
                center="nowhere",
                roi_size="not-a-number",
            )
        )

    problems = excinfo.value.problems
    assert len(problems) == 6
    assert any("DICOM directory is required" in p for p in problems)
    assert any("Output directory is required" in p for p in problems)
    assert any("Trim must be a number of seconds, got 'abc'" in p for p in problems)
    assert any("Detrend method must be one of" in p for p in problems)
    assert any("ROI center must be one of" in p for p in problems)
    assert any("ROI size must be a whole number of voxels" in p for p in problems)


def test_parse_form_reports_a_bad_float(tmp_path: Path) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()

    with pytest.raises(RequestError) as excinfo:
        parse_form(
            FormValues(
                dicom_dir=str(dicom_dir),
                output_dir=str(tmp_path / "output"),
                trim_sec="not-a-number",
            )
        )

    assert excinfo.value.problems == (
        "Trim must be a number of seconds, got 'not-a-number'",
    )


def test_parse_form_reports_a_bad_choice(tmp_path: Path) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()

    with pytest.raises(RequestError) as excinfo:
        parse_form(
            FormValues(
                dicom_dir=str(dicom_dir),
                output_dir=str(tmp_path / "output"),
                detrend="fourier",
            )
        )

    assert len(excinfo.value.problems) == 1
    assert "Detrend method must be one of" in excinfo.value.problems[0]


def test_parse_form_reports_an_out_of_range_roi_size(tmp_path: Path) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()

    with pytest.raises(RequestError) as excinfo:
        parse_form(
            FormValues(
                dicom_dir=str(dicom_dir),
                output_dir=str(tmp_path / "output"),
                roi_size="0",
            )
        )

    assert len(excinfo.value.problems) == 1
    assert "positive whole number" in excinfo.value.problems[0]


def test_parse_form_reports_output_equal_to_input(tmp_path: Path) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()

    with pytest.raises(RequestError) as excinfo:
        parse_form(FormValues(dicom_dir=str(dicom_dir), output_dir=str(dicom_dir)))

    assert len(excinfo.value.problems) == 1
    assert "same directory" in excinfo.value.problems[0]


def test_parse_form_reports_a_negative_trim(tmp_path: Path) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()

    with pytest.raises(RequestError) as excinfo:
        parse_form(
            FormValues(
                dicom_dir=str(dicom_dir),
                output_dir=str(tmp_path / "output"),
                trim_sec="-1",
            )
        )

    assert len(excinfo.value.problems) == 1
    assert "zero seconds or more" in excinfo.value.problems[0]


def test_translate_settings_problem_covers_every_field() -> None:
    trim = _translate_settings_problem(InvalidScanError("trim_sec", -5.0, "..."))
    assert "zero seconds or more" in trim

    roi = _translate_settings_problem(InvalidScanError("roi_size", -1, "..."))
    assert "positive whole number" in roi

    other = InvalidScanError("detrend_order", -1, "expected >= 0")
    assert _translate_settings_problem(other) == str(other)


def test_run_request_expands_a_tilde_dicom_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    dicom_dir = home / "data"
    dicom_dir.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))

    request = RunRequest(dicom_dir=Path("~/data"), output_dir=tmp_path / "output")

    assert request.dicom_dir == dicom_dir.resolve()
    assert request.dicom_dir.is_absolute()


def test_run_request_expands_a_tilde_dcm2niix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    binary = home / "dcm2niix"
    binary.write_text("stub")
    monkeypatch.setenv("HOME", str(home))
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()

    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=tmp_path / "output",
        dcm2niix=Path("~/dcm2niix"),
    )

    assert request.dcm2niix == binary


def test_run_request_leaves_a_bare_dcm2niix_name_for_path_lookup(
    tmp_path: Path,
) -> None:
    """`find_dcm2niix` resolves a bare name on PATH; anchoring it would break that."""
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()

    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=tmp_path / "output",
        dcm2niix=Path("dcm2niix"),
    )

    assert request.dcm2niix == Path("dcm2niix")


def test_run_request_makes_a_relative_dicom_dir_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    monkeypatch.chdir(tmp_path)

    request = RunRequest(dicom_dir=Path("dicom"), output_dir=Path("output"))

    assert request.dicom_dir == dicom_dir.resolve()
    assert request.dicom_dir.is_absolute()
    assert request.output_dir == (tmp_path / "output").resolve()
    assert request.output_dir.is_absolute()


def test_parse_form_strips_surrounding_whitespace_from_folder_fields(
    tmp_path: Path,
) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    output_dir = tmp_path / "output"

    request = parse_form(
        FormValues(dicom_dir=f"  {dicom_dir}  \n", output_dir=f"\t{output_dir} ")
    )

    assert request.dicom_dir == dicom_dir.resolve()
    assert request.output_dir == output_dir.resolve()


def test_parse_form_combines_a_conversion_problem_with_a_directory_problem(
    tmp_path: Path,
) -> None:
    """A bad float must not hide the same-directory problem, or vice versa."""
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()

    with pytest.raises(RequestError) as excinfo:
        parse_form(
            FormValues(
                dicom_dir=str(dicom_dir),
                output_dir=str(dicom_dir),
                trim_sec="abc",
            )
        )

    problems = excinfo.value.problems
    assert len(problems) == 2
    assert any("Trim must be a number of seconds" in p for p in problems)
    assert any("same directory" in p for p in problems)
