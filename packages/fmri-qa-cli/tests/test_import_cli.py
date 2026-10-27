"""The `import` command: what it prints, what it exits with, and where it writes.

Drives `cli.import_main` over the stub dcm2niix (the `fake_dcm2niix` fixture),
checking its report, its refusals without a traceback, its default output
directory and its warnings.
"""

import pytest

import fmriqa_cli as cli
from fmriqa_io import ConversionError
from fmriqa_io.convert.session import import_dicom

# A sidecar with every field the name is built from, as dcm2niix writes them.
FULL_SIDECAR = {
    "AcquisitionDateTime": "2026-09-09T14:30:12.500000",
    "AcquisitionTime": "14:30:12.500000",
    "SeriesNumber": 2,
    "SeriesDescription": "QA_EPI_ISO",
    "ProtocolName": "ep2d_bold_qa",
}


def test_import_main_lists_every_series_it_wrote(tmp_path, fake_dcm2niix, capsys):
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    out = tmp_path / "nifti"

    rc = cli.import_main([str(tmp_path), "-o", str(out), "--dcm2niix", str(binary)])

    printed = capsys.readouterr().out
    assert rc == 0
    assert "20260909_143012_s002_QA_EPI_ISO.nii.gz" in printed
    assert "v1.0.20260724" in printed  # which dcm2niix did the work
    assert f"fmri-qa {out}/*.nii.gz" in printed  # the paste-able next step


def test_import_main_names_the_series_that_kept_dcm2niix_s_name(
    tmp_path, fake_dcm2niix, capsys
):
    """An unrenamed file in an otherwise uniform listing reads as a bug.

    It is a decision `naming.plan` made, so the command says which files and why.
    """
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR, "9_odd": {}})

    cli.import_main(
        [str(tmp_path), "-o", str(tmp_path / "nifti"), "--dcm2niix", str(binary)]
    )

    assert "1 of 2 series kept dcm2niix's name" in capsys.readouterr().err


def test_import_main_says_nothing_about_names_it_was_told_to_keep(
    tmp_path, fake_dcm2niix, capsys
):
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})

    cli.import_main(
        [
            str(tmp_path),
            "-o",
            str(tmp_path / "nifti"),
            "--dcm2niix",
            str(binary),
            "--names",
            "dcm2niix",
        ]
    )

    assert "kept dcm2niix's name" not in capsys.readouterr().err


def test_import_main_reports_a_bad_source_without_a_traceback(tmp_path, capsys):
    rc = cli.import_main([str(tmp_path / "nowhere"), "-o", str(tmp_path / "out")])

    assert rc == 1
    assert "ERROR" in capsys.readouterr().err


def test_import_main_reports_a_destination_that_cannot_be_made_without_a_traceback(
    tmp_path, fake_dcm2niix, capsys
):
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    blocked = tmp_path / "out"
    blocked.write_text("not a directory")

    rc = cli.import_main([str(tmp_path), "-o", str(blocked), "--dcm2niix", str(binary)])

    err = capsys.readouterr().err
    assert rc == 1
    assert "ERROR" in err
    assert "Traceback" not in err


def test_import_main_fails_when_a_directory_holds_no_dicom(
    tmp_path, fake_dcm2niix, capsys
):
    """An empty conversion is a failed import, not a successful empty one."""
    binary = fake_dcm2niix({})

    rc = cli.import_main(
        [str(tmp_path), "-o", str(tmp_path / "nifti"), "--dcm2niix", str(binary)]
    )

    assert rc == 1
    assert "no DICOM series converted" in capsys.readouterr().err


def test_import_main_defaults_its_output_to_a_directory_named_for_the_source(
    tmp_path, fake_dcm2niix, monkeypatch, capsys
):
    """The one-argument call has to put a session somewhere predictable."""
    study = tmp_path / "QA_20260909"
    study.mkdir()
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    monkeypatch.chdir(tmp_path)

    rc = cli.import_main([str(study), "--dcm2niix", str(binary)])

    assert rc == 0
    assert (tmp_path / "QA_20260909_nifti").is_dir()
    assert "QA_20260909_nifti" in capsys.readouterr().out


def test_import_main_warns_when_a_passthrough_disarms_the_saturation_check(
    tmp_path, fake_dcm2niix, capsys
):
    """The warning has to reach the operator, not just the warnings filter."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})

    cli.import_main(
        [
            str(tmp_path),
            "-o",
            str(tmp_path / "nifti"),
            "--dcm2niix",
            str(binary),
            "--dcm2niix-arg=-l",
            "--dcm2niix-arg=y",
        ]
    )

    assert "saturation check" in capsys.readouterr().err


def test_import_main_version_prints_and_exits(capsys) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.import_main(["--version"])

    assert excinfo.value.code == 0
    assert capsys.readouterr().out.startswith("fmri-qa-import ")


def test_log_shows_what_the_converter_actually_said(
    tmp_path, fake_dcm2niix, capsys
) -> None:
    """dcm2niix's own diagnostics are the ones that name a DICOM problem."""
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR})
    argv = [str(tmp_path), "-o", str(tmp_path / "nifti"), "--dcm2niix", str(binary)]

    cli.import_main(argv)
    assert "Chris Rorden" not in capsys.readouterr().err

    cli.import_main([*argv, "--force", "--log"])
    assert "Chris Rorden" in capsys.readouterr().err


def test_a_destination_the_caller_already_had_survives_a_failed_import(
    tmp_path, fake_dcm2niix
) -> None:
    """Only a directory this call created is cleaned up, and only while empty."""
    out = tmp_path / "nifti"
    out.mkdir()
    binary = fake_dcm2niix({"2_QA": FULL_SIDECAR}, returncode=2)

    with pytest.raises(ConversionError):
        import_dicom(tmp_path, out, binary=binary)

    assert out.is_dir()


@pytest.mark.parametrize(
    ("extra", "suffix", "glob"),
    [([], ".nii.gz", "*.nii.gz"), (["--no-compress"], ".nii", "*.nii")],
)
def test_import_main_globs_the_nifti_suffix_not_the_last_two_dots(
    tmp_path, fake_dcm2niix, capsys, extra, suffix, glob
):
    """A dot inside the stem must not leak into the paste-able glob."""
    binary = fake_dcm2niix({"a_1.5mm": FULL_SIDECAR}, suffix=suffix)
    out = tmp_path / "nifti"

    cli.import_main(
        [
            str(tmp_path),
            "-o",
            str(out),
            "--dcm2niix",
            str(binary),
            "--names",
            "dcm2niix",
            *extra,
        ]
    )

    printed = capsys.readouterr().out
    assert f"fmri-qa {out}/{glob}\n" in printed, printed
