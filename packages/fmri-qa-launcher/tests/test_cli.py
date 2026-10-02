"""`fmri-qa-run`, exercised over a stub converter and a fast fake render.

Only `test_the_published_run_matches_a_direct_analyze` (the equivalence claim
that matters) pays for a real analysis; the other end-to-end tests
monkeypatch `fmriqc_launcher.session.write_run_page` with `_fast_render`, the
same stand-in `tests/test_session.py` uses. What the command prints for each
kind of outcome is pinned by calling `_print_outcomes` on a hand-built
`RunResult`, with no run at all.
"""

import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

import fmriqc
from fmriqc.convert import naming
from fmriqc.convert.dcm2niix import find_dcm2niix
from fmriqc.settings import AnalysisSettings
from fmriqc_launcher import cli
from fmriqc_launcher.outcome import Failed, Published, Refused, RunResult
from fmriqc_launcher.results import open_results

PreparedSeries = Callable[..., tuple[Path, dict[str, object]]]
StubDcm2niix = Callable[..., Path]


def _fast_render(artifact: object, path: Path, **_kwargs: object) -> Path:
    """A stand-in for `write_run_page` that skips the ~8 s matplotlib render."""
    target = Path(path)
    target.write_text("<html><body>stub report</body></html>", encoding="utf-8")
    return target


def _sidecar(
    base: dict[str, object], series_number: int, description: str
) -> dict[str, object]:
    return {
        **base,
        "SeriesNumber": series_number,
        "AcquisitionDateTime": f"2026-09-09T14:{10 + series_number:02d}:12.500000",
        "SeriesDescription": description,
    }


def test_help_renders(capsys: pytest.CaptureFixture[str]) -> None:
    """`-h`, which argparse %-formats every help string it is given."""
    with pytest.raises(SystemExit) as info:
        cli.main(["-h"])
    assert info.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_version_flag_prints_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0
    assert "fmri-qa-run" in capsys.readouterr().out


def test_one_positional_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main([str(tmp_path / "dicom")])
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert "DICOM directory" in err
    assert "Output directory" in err


def test_a_flag_with_no_directories_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["--roi-size", "5"])
    assert info.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_no_flags_builds_the_default_analysis_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Structural pin: no flags builds exactly `fmriqc.AnalysisSettings()`."""
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    output_dir = tmp_path / "output"
    captured: dict[str, object] = {}

    def _fake_run_session(request: object, **_kwargs: object) -> RunResult:
        captured["request"] = request
        return RunResult(output_dir, ())

    import fmriqc_launcher.session as session_module

    monkeypatch.setattr(session_module, "run_session", _fake_run_session)

    rc = cli.main([str(dicom_dir), str(output_dir)])

    assert rc == 1  # no series at all is not a complete run
    request = captured["request"]
    assert request.settings == fmriqc.AnalysisSettings()  # type: ignore[attr-defined]
    assert request.anonymize == "pii"  # type: ignore[attr-defined]
    assert request.dcm2niix is None  # type: ignore[attr-defined]
    assert request.open_report is False  # type: ignore[attr-defined]


def test_each_flag_lands_in_the_right_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    output_dir = tmp_path / "output"
    converter = tmp_path / "dcm2niix"
    converter.write_text("stub")
    captured: dict[str, object] = {}

    def _fake_run_session(request: object, **_kwargs: object) -> RunResult:
        captured["request"] = request
        return RunResult(output_dir, ())

    import fmriqc_launcher.session as session_module

    monkeypatch.setattr(session_module, "run_session", _fake_run_session)

    rc = cli.main(
        [
            str(dicom_dir),
            str(output_dir),
            "--trim-sec",
            "3",
            "--detrend",
            "spline",
            "--center",
            "phantom",
            "--roi-size",
            "11",
            "--anonymize",
            "all",
            "--dcm2niix",
            str(converter),
            "--open",
        ]
    )

    assert rc == 1
    request = captured["request"]
    settings = request.settings  # type: ignore[attr-defined]
    assert settings == AnalysisSettings(
        trim_sec=3.0, detrend="spline", center="phantom", roi_size=11
    )
    assert request.anonymize == "all"  # type: ignore[attr-defined]
    assert request.dcm2niix == str(converter)  # type: ignore[attr-defined]
    assert request.open_report is True  # type: ignore[attr-defined]


def test_a_dot_slash_dcm2niix_runs_the_file_here_not_one_on_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--dcm2niix ./dcm2niix` reaches `find_dcm2niix` with its `./` intact."""
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    output_dir = tmp_path / "output"
    here = tmp_path / "here"
    here.mkdir()
    converter = here / "dcm2niix"
    converter.write_text("#!/bin/sh\n")
    converter.chmod(converter.stat().st_mode | stat.S_IXUSR)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(here)
    monkeypatch.setenv("PATH", str(elsewhere))
    captured: dict[str, object] = {}

    def _fake_run_session(request: object, **_kwargs: object) -> RunResult:
        captured["request"] = request
        return RunResult(output_dir, ())

    import fmriqc_launcher.session as session_module

    monkeypatch.setattr(session_module, "run_session", _fake_run_session)

    cli.main([str(dicom_dir), str(output_dir), "--dcm2niix", "./dcm2niix"])

    named = captured["request"].dcm2niix  # type: ignore[attr-defined]
    assert Path(find_dcm2niix(named)).resolve() == converter.resolve()


@pytest.mark.parametrize(
    "argv",
    [
        ["--trim-sec", "-1"],
        ["--roi-size", "0"],
        ["--detrend", "nope"],
    ],
)
def test_bad_flag_values_are_usage_errors(
    tmp_path: Path, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    dicom_dir = tmp_path / "dicom"
    dicom_dir.mkdir()
    with pytest.raises(SystemExit) as info:
        cli.main([str(dicom_dir), str(tmp_path / "output"), *argv])
    assert info.value.code == 2
    assert "error:" in capsys.readouterr().err


def test_the_published_run_matches_a_direct_analyze(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
) -> None:
    """The claim that matters: `fmri-qa-run` matches a direct `fmriqc.analyze`."""
    nifti, base = prepared_series(name="scan")
    sidecar = _sidecar(base, series_number=1, description="QA_EPI")
    converter = stub_dcm2niix({"stem1": (nifti, sidecar)})
    output_dir = tmp_path / "output"

    rc = cli.main([str(dicom_dir), str(output_dir), "--dcm2niix", str(converter)])
    assert rc == 0

    name = naming.qa_stem(sidecar)
    assert name is not None
    published_nifti = output_dir / name / f"{name}.nii.gz"
    published_artifact = output_dir / name / f"{name}.qa.nc"

    reloaded = fmriqc.load_artifact(published_artifact)
    direct = fmriqc.analyze(
        fmriqc.QAScan.from_nifti(published_nifti), fmriqc.AnalysisSettings()
    )

    assert reloaded.settings == direct.settings
    assert reloaded.measurements.snr == direct.measurements.snr
    assert reloaded.measurements.sfnr == direct.measurements.sfnr
    assert reloaded.measurements.rdc == direct.measurements.rdc


def test_clean_run_exits_zero_and_prints_the_report_path(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("fmriqc_launcher.session.write_run_page", _fast_render)
    nifti, base = prepared_series(name="scan")
    sidecar = _sidecar(base, series_number=1, description="QA_EPI")
    name = naming.qa_stem(sidecar)
    assert name is not None
    converter = stub_dcm2niix({"stem1": (nifti, sidecar)})
    output_dir = tmp_path / "output"

    rc = cli.main([str(dicom_dir), str(output_dir), "--dcm2niix", str(converter)])

    captured = capsys.readouterr()
    assert rc == 0
    report = output_dir / name / f"{name}.html"
    assert captured.out.strip() == str(report)
    assert "Importing DICOM series" in captured.err
    assert f"# 1 of 1 series published to {output_dir}" in captured.err


def test_a_converter_producing_nothing_is_reported_without_a_traceback(
    tmp_path: Path, dicom_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    empty_script = tmp_path / "empty-dcm2niix"
    empty_script.write_text(
        f'#!{sys.executable}\nprint("Chris Rorden\'s dcm2niiX version v1.0.20260724")\n'
    )
    empty_script.chmod(empty_script.stat().st_mode | stat.S_IEXEC)

    rc = cli.main(
        [str(dicom_dir), str(tmp_path / "output"), "--dcm2niix", str(empty_script)]
    )

    captured = capsys.readouterr()
    assert rc == 1
    assert "ERROR:" in captured.err
    assert "Traceback" not in captured.err


def test_a_missing_dicom_directory_prints_every_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Missing directory *and* output-equals-input both get their own ERROR: line."""
    missing = tmp_path / "does-not-exist"
    rc = cli.main([str(missing), str(missing)])

    captured = capsys.readouterr()
    assert rc == 1
    error_lines = [
        line for line in captured.err.splitlines() if line.startswith("ERROR:")
    ]
    assert len(error_lines) == 2
    assert any("not an existing directory" in line for line in error_lines)
    assert any("same directory" in line for line in error_lines)
    assert "Traceback" not in captured.err


def _published(
    output_dir: Path, name: str, warnings: tuple[str, ...] = ()
) -> Published:
    directory = output_dir / name
    return Published(
        name=name,
        directory=directory,
        scan=directory / f"{name}.nii.gz",
        sidecar=None,
        artifact=directory / f"{name}.qa.nc",
        report=directory / f"{name}.html",
        warnings=warnings,
    )


def test_open_flag_opens_the_report_and_exits_zero_for_a_complete_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "output"
    result = RunResult(output_dir, (_published(output_dir, "a"),))
    monkeypatch.setattr(
        "fmriqc_launcher.session.run_session", lambda _request, progress: result
    )
    opened: list[RunResult] = []
    monkeypatch.setattr("fmriqc_launcher.cli.open_results", opened.append)

    rc = cli.main([str(tmp_path), str(output_dir), "--open"])

    assert rc == 0
    assert opened == [result]


def test_a_refused_series_exits_one_and_is_not_opened_without_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_dir = tmp_path / "output"
    result = RunResult(output_dir, (Refused(name="a", existing=output_dir / "a"),))
    monkeypatch.setattr(
        "fmriqc_launcher.session.run_session", lambda _request, progress: result
    )
    opened: list[RunResult] = []
    monkeypatch.setattr("fmriqc_launcher.cli.open_results", opened.append)

    rc = cli.main([str(tmp_path), str(output_dir)])

    assert rc == 1
    assert opened == []


def test_a_published_series_prints_its_report_path_and_tally(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "output"
    published = _published(output_dir, "scan")

    cli._print_outcomes(RunResult(output_dir, (published,)), output_dir)

    captured = capsys.readouterr()
    assert captured.out == f"{output_dir / 'scan' / 'scan.html'}\n"
    assert captured.err == f"# 1 of 1 series published to {output_dir}\n"


def test_a_published_series_prints_each_warning_on_stderr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "output"
    published = _published(output_dir, "scan", warnings=("first", "second"))

    cli._print_outcomes(RunResult(output_dir, (published,)), output_dir)

    captured = capsys.readouterr()
    assert captured.out == f"{published.report}\n"
    assert captured.err == (
        "WARNING: scan: first\n"
        "WARNING: scan: second\n"
        f"# 1 of 1 series published to {output_dir}\n"
    )


def test_a_refused_series_names_the_existing_directory_on_stderr_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "output"
    existing = output_dir / "scan"

    cli._print_outcomes(
        RunResult(output_dir, (Refused(name="scan", existing=existing),)), output_dir
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        f"refusing to replace existing results: {existing}\n"
        f"# 0 of 1 series published to {output_dir}\n"
    )


def test_a_failed_series_prints_its_reason_then_its_warnings_on_stderr_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "output"
    failed = Failed(
        name="scan",
        reason="stub render failure",
        warnings=("a stub warning from the analysis",),
    )

    cli._print_outcomes(RunResult(output_dir, (failed,)), output_dir)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "ERROR: scan: stub render failure\n"
        "WARNING: scan: a stub warning from the analysis\n"
        f"# 0 of 1 series published to {output_dir}\n"
    )


def test_outcomes_print_in_run_order_and_only_reports_reach_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_dir = tmp_path / "output"
    first = _published(output_dir, "a")
    second = _published(output_dir, "c")
    result = RunResult(
        output_dir,
        (first, Failed(name="b", reason="boom"), second),
    )

    cli._print_outcomes(result, output_dir)

    captured = capsys.readouterr()
    assert captured.out == f"{first.report}\n{second.report}\n"
    assert captured.err == (
        f"ERROR: b: boom\n# 2 of 3 series published to {output_dir}\n"
    )


def test_open_results_opens_the_folder_for_several_series(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    published = (
        Published(
            name="a",
            directory=output_dir / "a",
            scan=output_dir / "a" / "a.nii.gz",
            sidecar=None,
            artifact=output_dir / "a" / "a.qa.nc",
            report=output_dir / "a" / "a.html",
        ),
        Published(
            name="b",
            directory=output_dir / "b",
            scan=output_dir / "b" / "b.nii.gz",
            sidecar=None,
            artifact=output_dir / "b" / "b.qa.nc",
            report=output_dir / "b" / "b.html",
        ),
    )
    result = RunResult(output_dir, published)
    opened: list[str] = []
    uri = open_results(result, opener=lambda u: (opened.append(u), True)[1])
    assert uri == output_dir.as_uri()
    assert opened == [output_dir.as_uri()]


def test_open_results_opens_the_one_report_for_a_single_series(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    report = output_dir / "a" / "a.html"
    published = (
        Published(
            name="a",
            directory=output_dir / "a",
            scan=output_dir / "a" / "a.nii.gz",
            sidecar=None,
            artifact=output_dir / "a" / "a.qa.nc",
            report=report,
        ),
    )
    result = RunResult(output_dir, published)
    opened: list[str] = []
    uri = open_results(result, opener=lambda u: (opened.append(u), True)[1])
    assert uri == report.as_uri()
    assert opened == [report.as_uri()]


def test_open_results_opens_nothing_when_nothing_was_published(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    result = RunResult(output_dir, (Refused(name="a", existing=output_dir / "a"),))
    called = False

    def _opener(_uri: str) -> bool:
        nonlocal called
        called = True
        return True

    assert open_results(result, opener=_opener) is None
    assert called is False


def test_one_failed_series_does_not_stop_the_report_of_another(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("fmriqc_launcher.session.write_run_page", _fast_render)
    healthy_nifti, healthy_base = prepared_series(name="healthy", t=40)
    healthy_sidecar = _sidecar(healthy_base, series_number=2, description="Healthy")
    broken_nifti, broken_base = prepared_series(name="broken", t=2)
    broken_sidecar = _sidecar(broken_base, series_number=1, description="Broken")
    converter = stub_dcm2niix(
        {
            "stem1": (broken_nifti, broken_sidecar),
            "stem2": (healthy_nifti, healthy_sidecar),
        }
    )
    healthy_name = naming.qa_stem(healthy_sidecar)
    assert healthy_name is not None
    output_dir = tmp_path / "output"

    rc = cli.main([str(dicom_dir), str(output_dir), "--dcm2niix", str(converter)])

    captured = capsys.readouterr()
    assert rc == 1
    report = output_dir / healthy_name / f"{healthy_name}.html"
    assert captured.out.strip() == str(report)
    assert "ERROR:" in captured.err and "expected at least 4 frame" in captured.err


def test_launch_panel_runs_the_panels_run_panel_when_importable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_launch_panel` calls `panel.run_panel`, the entry point `cli.py` drives."""

    class _FakePanel:
        @staticmethod
        def run_panel() -> int:
            return 0

    monkeypatch.setattr("fmriqc_launcher.cli.import_module", lambda _name: _FakePanel())
    assert cli._launch_panel() == 0


@pytest.mark.parametrize("missing_name", ["tkinter", "tkinter.ttk", "_tkinter"])
def test_zero_arguments_reports_the_missing_panel_by_a_failed_tkinter_import(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    missing_name: str,
) -> None:
    """An `ImportError` naming `tkinter`/`_tkinter` (however deep) is "no tkinter"."""

    def _raise(_name: str) -> None:
        raise ImportError("no such module", name=missing_name)

    monkeypatch.setattr("fmriqc_launcher.cli.import_module", _raise)
    rc = cli.main([])
    captured = capsys.readouterr()
    assert rc == 2
    assert "tkinter" in captured.err
    assert "fmri-qa-run" in captured.err


def test_an_import_error_unrelated_to_tkinter_is_a_real_bug_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`panel.py` failing to import `numpy` (say) is a packaging bug, not "no tkinter".

    Reporting this as "install tkinter" would send a physicist chasing the
    wrong fix entirely -- it must propagate and say what actually failed.
    """

    def _raise(_name: str) -> None:
        raise ImportError("no module named 'numpy'", name="numpy")

    monkeypatch.setattr("fmriqc_launcher.cli.import_module", _raise)
    with pytest.raises(ImportError, match="numpy"):
        cli._launch_panel()


def test_an_import_error_with_no_name_at_all_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare `raise ImportError(...)`, naming nothing, is not "no tkinter"."""

    def _raise(_name: str) -> None:
        raise ImportError("something else broke")

    monkeypatch.setattr("fmriqc_launcher.cli.import_module", _raise)
    with pytest.raises(ImportError, match="something else broke"):
        cli._launch_panel()


def test_zero_arguments_with_no_display_reports_the_display_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`run_panel` raising `PanelUnavailableError` (no display) is reported plainly."""
    from fmriqc_launcher.exceptions import PanelUnavailableError

    class _FakePanel:
        @staticmethod
        def run_panel() -> int:
            raise PanelUnavailableError(
                "no display name and no $DISPLAY environment variable"
            )

    monkeypatch.setattr("fmriqc_launcher.cli.import_module", lambda _name: _FakePanel())
    rc = cli.main([])
    captured = capsys.readouterr()
    assert rc == 2
    assert "display" in captured.err
    assert "fmri-qa-run" in captured.err


_FORBIDDEN = ("scipy", "matplotlib", "tkinter")

_LOADED = (
    "loaded = sorted(\n"
    "    m for m in sys.modules\n"
    "    if any(m == f or m.startswith(f + '.') for f in forbidden)\n"
    ")\n"
    "print(loaded)\n"
)

_IMPORT_PROBE = f"""
import sys
import fmriqc_launcher.cli
forbidden = {_FORBIDDEN!r}
{_LOADED}"""

_HELP_PROBE = f"""
import contextlib
import io
import sys
import fmriqc_launcher.cli
try:
    with contextlib.redirect_stdout(io.StringIO()):
        fmriqc_launcher.cli.main(["-h"])
except SystemExit:
    pass
forbidden = {_FORBIDDEN!r}
{_LOADED}"""


def test_importing_the_cli_does_not_load_the_heavy_stack() -> None:
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", result.stdout + result.stderr


def test_running_help_does_not_load_the_heavy_stack() -> None:
    result = subprocess.run(  # noqa: S603 - fixed literal script, not untrusted input
        [sys.executable, "-c", _HELP_PROBE],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "[]", result.stdout + result.stderr


def test_module_entry_point_version_works() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "fmriqc_launcher", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "fmri-qa-run" in result.stdout
