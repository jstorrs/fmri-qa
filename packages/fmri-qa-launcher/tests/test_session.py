"""`run_session`: the functional core, exercised end to end over a stub converter.

Only `test_one_series_is_imported_analyzed_and_published` renders a real
report (~8 s); every other test that needs an outcome for a *published*
series monkeypatches `write_run_page` with `_fast_render`, a few
milliseconds' stand-in that still leaves a file behind for `Published.report`
to point at.
"""

import os
import stat
import sys
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

import fmriqc
from fmriqc.convert import naming
from fmriqc.settings import AnalysisSettings
from fmriqc_launcher.exceptions import SessionError
from fmriqc_launcher.progress import Progress, Stage
from fmriqc_launcher.request import RunRequest
from fmriqc_launcher.session import (
    Failed,
    Published,
    Refused,
    _assign_companions,
    run_session,
)

PreparedSeries = Callable[..., tuple[Path, dict[str, object]]]
StubDcm2niix = Callable[..., Path]

_SETTINGS = AnalysisSettings(roi_size=9)


def _sidecar(
    base: dict[str, object], series_number: int, description: str
) -> dict[str, object]:
    """`base` (from `prepared_series`) plus the naming fields `naming.qa_stem` reads."""
    return {
        **base,
        "SeriesNumber": series_number,
        "AcquisitionDateTime": f"2026-09-09T14:{10 + series_number:02d}:12.500000",
        "SeriesDescription": description,
    }


def _fast_render(artifact: object, path: Path, **_kwargs: object) -> Path:
    """A stand-in for `write_run_page` that skips the ~8 s matplotlib render."""
    target = Path(path)
    target.write_text("<html><body>stub report</body></html>", encoding="utf-8")
    return target


def _warn_then_render(artifact: object, path: Path, **_kwargs: object) -> Path:
    """`_fast_render`, but warns first -- proves a render warning is not captured."""
    warnings.warn("a stub warning from the render step", stacklevel=2)
    return _fast_render(artifact, path)


def _fail_render(_artifact: object, _path: Path, **_kwargs: object) -> Path:
    """A render that always fails -- pairs an analysis warning with a later failure."""
    raise RuntimeError("stub render failure")


def _warning_wrapper(
    real: Callable[..., object],
) -> Callable[..., object]:
    """Wrap `real` (`fmriqc.analyze`) to warn first -- for the warnings contract.

    `session.py` calls `fmriqc.analyze(...)` as an attribute of the `fmriqc`
    module, so the warning has to come from there, not from a fake render:
    `_publish_series` only captures warnings around `from_nifti`/`analyze`
    now, exactly as `fmriqc.cli.qa` does.
    """

    def wrapper(*args: object, **kwargs: object) -> object:
        warnings.warn("a stub warning from the analysis", stacklevel=2)
        return real(*args, **kwargs)

    return wrapper


def test_assign_companions_gives_a_dotted_prefix_file_to_the_longer_stem() -> None:
    """`scan.rep.json` belongs to `scan.rep`, not to `scan`, its shorter prefix."""
    assigned = _assign_companions(
        file_names=["scan.json", "scan.rep.json"],
        series_names=["scan", "scan.rep"],
    )
    assert assigned == {"scan.json": "scan", "scan.rep.json": "scan.rep"}


def test_assign_companions_drops_a_file_matching_no_series() -> None:
    assigned = _assign_companions(
        file_names=["scan.json", "unrelated.txt"], series_names=["scan"]
    )
    assert assigned == {"scan.json": "scan"}


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_one_series_is_imported_analyzed_and_published(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
) -> None:
    nifti, base = prepared_series(name="scan")
    sidecar = _sidecar(base, series_number=1, description="QA_EPI")
    name = naming.qa_stem(sidecar)
    assert name is not None
    converter = stub_dcm2niix({"stem1": (nifti, sidecar)})

    output_dir = tmp_path / "output"
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=output_dir,
        settings=_SETTINGS,
        dcm2niix=converter,
    )

    events: list[Progress] = []
    old_umask = os.umask(0o022)
    try:
        result = run_session(request, progress=events.append)
    finally:
        os.umask(old_umask)

    assert result.complete
    assert not result.cancelled
    assert len(result.outcomes) == 1
    published = result.outcomes[0]
    assert isinstance(published, Published)
    assert published.name == name

    series_dir = output_dir / name
    assert (series_dir / f"{name}.nii.gz").is_file()
    assert (series_dir / f"{name}.json").is_file()
    assert (series_dir / f"{name}.qa.nc").is_file()
    assert (series_dir / f"{name}.html").is_file()
    assert published.scan == series_dir / f"{name}.nii.gz"
    assert published.sidecar == series_dir / f"{name}.json"
    assert published.artifact == series_dir / f"{name}.qa.nc"
    assert published.report == series_dir / f"{name}.html"

    # The published series directory honours the umask -- 0o755, not
    # `tempfile.mkdtemp`'s unconditional 0o700.
    assert stat.S_IMODE(series_dir.stat().st_mode) == 0o755

    # No staging directory survives a successful run.
    assert [p.name for p in output_dir.iterdir()] == [name]

    reloaded = fmriqc.load_artifact(published.artifact)
    assert reloaded.provenance.source == str(series_dir / f"{name}.nii.gz")
    assert ".fmri-qa-run." not in reloaded.provenance.source
    assert Path(reloaded.provenance.source).is_absolute()

    assert [e.stage for e in events] == [
        Stage.IMPORT,
        Stage.ANALYZE,
        Stage.REPORT,
        Stage.PUBLISH,
    ]
    for event in events[1:]:
        assert (event.index, event.total, event.series) == (1, 1, name)

    assert result.published == (published,)
    assert result.reports == (published.report,)


def test_a_series_whose_name_already_exists_is_refused_untouched(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("fmriqc_launcher.session.write_run_page", _fast_render)
    nifti, base = prepared_series(name="scan")
    sidecar = _sidecar(base, series_number=1, description="QA_EPI")
    name = naming.qa_stem(sidecar)
    assert name is not None
    converter = stub_dcm2niix({"stem1": (nifti, sidecar)})

    output_dir = tmp_path / "output"
    existing = output_dir / name
    existing.mkdir(parents=True)
    marker = existing / "keep-me.txt"
    marker.write_text("do not touch")

    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=output_dir,
        settings=_SETTINGS,
        dcm2niix=converter,
    )
    result = run_session(request)

    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert isinstance(outcome, Refused)
    assert outcome.name == name
    assert outcome.existing == existing
    assert marker.read_text() == "do not touch"
    assert [p.name for p in existing.iterdir()] == ["keep-me.txt"]
    assert not result.complete


def test_one_series_failing_does_not_stop_the_other(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("fmriqc_launcher.session.write_run_page", _fast_render)
    healthy_nifti, healthy_base = prepared_series(name="healthy", t=40)
    healthy_sidecar = _sidecar(healthy_base, series_number=1, description="Healthy")
    broken_nifti, broken_base = prepared_series(name="broken", t=2)
    broken_sidecar = _sidecar(broken_base, series_number=2, description="Broken")

    healthy_name = naming.qa_stem(healthy_sidecar)
    broken_name = naming.qa_stem(broken_sidecar)
    assert healthy_name is not None
    assert broken_name is not None

    converter = stub_dcm2niix(
        {
            "stem1": (healthy_nifti, healthy_sidecar),
            "stem2": (broken_nifti, broken_sidecar),
        }
    )
    output_dir = tmp_path / "output"
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=output_dir,
        settings=_SETTINGS,
        dcm2niix=converter,
    )

    result = run_session(request)

    by_name = {o.name: o for o in result.outcomes}
    assert set(by_name) == {healthy_name, broken_name}
    healthy_outcome = by_name[healthy_name]
    broken_outcome = by_name[broken_name]
    assert isinstance(healthy_outcome, Published)
    assert isinstance(broken_outcome, Failed)
    assert "expected at least 4 frame" in broken_outcome.reason
    assert not result.complete

    assert (output_dir / healthy_name).is_dir()
    assert not (output_dir / broken_name).exists()
    assert [p.name for p in output_dir.iterdir()] == [healthy_name]


def test_cancelling_between_series_stops_before_the_next_one(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("fmriqc_launcher.session.write_run_page", _fast_render)
    first_nifti, first_base = prepared_series(name="first", t=40, seed=1)
    first_sidecar = _sidecar(first_base, series_number=1, description="First")
    second_nifti, second_base = prepared_series(name="second", t=40, seed=2)
    second_sidecar = _sidecar(second_base, series_number=2, description="Second")

    first_name = naming.qa_stem(first_sidecar)
    second_name = naming.qa_stem(second_sidecar)
    assert first_name is not None
    assert second_name is not None

    converter = stub_dcm2niix(
        {
            "stem1": (first_nifti, first_sidecar),
            "stem2": (second_nifti, second_sidecar),
        }
    )
    output_dir = tmp_path / "output"
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=output_dir,
        settings=_SETTINGS,
        dcm2niix=converter,
    )

    calls = iter([True, False])
    result = run_session(request, should_continue=lambda: next(calls, False))

    assert result.cancelled
    assert not result.complete
    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert isinstance(outcome, Published)
    assert outcome.name == first_name
    assert (output_dir / first_name).is_dir()
    assert not (output_dir / second_name).exists()
    assert [p.name for p in output_dir.iterdir()] == [first_name]


def test_a_converter_that_produces_nothing_is_a_session_error(
    tmp_path: Path, dicom_dir: Path
) -> None:
    empty_script = tmp_path / "empty-dcm2niix"
    empty_script.write_text(
        f'#!{sys.executable}\nprint("Chris Rorden\'s dcm2niiX version v1.0.20260724")\n'
    )
    empty_script.chmod(empty_script.stat().st_mode | stat.S_IEXEC)

    output_dir = tmp_path / "output"
    request = RunRequest(
        dicom_dir=dicom_dir, output_dir=output_dir, dcm2niix=empty_script
    )
    with pytest.raises(SessionError, match="produced no series"):
        run_session(request)

    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []


def test_a_converter_that_exits_non_zero_is_a_session_error(
    tmp_path: Path, dicom_dir: Path
) -> None:
    failing_script = tmp_path / "failing-dcm2niix"
    failing_script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        'print("dcm2niiX failed", file=sys.stderr)\n'
        "sys.exit(1)\n"
    )
    failing_script.chmod(failing_script.stat().st_mode | stat.S_IEXEC)

    output_dir = tmp_path / "output"
    request = RunRequest(
        dicom_dir=dicom_dir, output_dir=output_dir, dcm2niix=failing_script
    )
    with pytest.raises(SessionError, match="could not import"):
        run_session(request)

    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []


def test_an_output_directory_that_cannot_be_created_is_a_session_error(
    tmp_path: Path, dicom_dir: Path
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a plain file, not a directory")
    output_dir = blocker / "sub"  # its parent is a file: mkdir must fail

    request = RunRequest(dicom_dir=dicom_dir, output_dir=output_dir)
    with pytest.raises(SessionError, match="cannot create"):
        run_session(request)


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="POSIX permission bits, and root ignores them",
)
def test_a_staging_directory_that_cannot_be_created_is_a_session_error(
    tmp_path: Path, dicom_dir: Path
) -> None:
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output_dir.chmod(0o555)  # exists already, so the first mkdir is a no-op
    try:
        request = RunRequest(dicom_dir=dicom_dir, output_dir=output_dir)
        with pytest.raises(SessionError, match="cannot create a staging directory"):
            run_session(request)
    finally:
        output_dir.chmod(0o755)


def test_a_target_that_appears_mid_run_fails_that_series(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A race the code defends against: the target exists by the time of publish."""
    nifti, base = prepared_series(name="scan")
    sidecar = _sidecar(base, series_number=1, description="QA_EPI")
    name = naming.qa_stem(sidecar)
    assert name is not None
    converter = stub_dcm2niix({"stem1": (nifti, sidecar)})
    output_dir = tmp_path / "output"

    def _render_then_collide(artifact: object, path: Path, **_kwargs: object) -> Path:
        target = Path(path)
        target.write_text("<html></html>", encoding="utf-8")
        (output_dir / name).mkdir(parents=True)
        return target

    monkeypatch.setattr("fmriqc_launcher.session.write_run_page", _render_then_collide)
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=output_dir,
        settings=_SETTINGS,
        dcm2niix=converter,
    )
    result = run_session(request)

    assert len(result.outcomes) == 1
    outcome = result.outcomes[0]
    assert isinstance(outcome, Failed)
    assert "was created while this run was in progress" in outcome.reason


def test_two_series_with_a_dotted_prefix_pair_each_publish_their_own_files(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`scan.rep.json` must land beside `scan.rep`, not get stolen by `scan`.

    Sidecars here carry none of `naming.qa_stem`'s fields, so `import_dicom`
    keeps each series' original dcm2niix stem verbatim -- "scan" and
    "scan.rep" -- reproducing the dotted-prefix collision `_assign_companions`
    exists to resolve.
    """
    monkeypatch.setattr("fmriqc_launcher.session.write_run_page", _fast_render)
    scan_nifti, scan_base = prepared_series(name="scan")
    rep_nifti, rep_base = prepared_series(name="scan.rep", seed=1)
    converter = stub_dcm2niix(
        {"scan": (scan_nifti, scan_base), "scan.rep": (rep_nifti, rep_base)}
    )

    output_dir = tmp_path / "output"
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=output_dir,
        settings=_SETTINGS,
        dcm2niix=converter,
    )
    result = run_session(request)

    by_name = {o.name: o for o in result.outcomes}
    assert set(by_name) == {"scan", "scan.rep"}
    assert isinstance(by_name["scan"], Published)
    assert isinstance(by_name["scan.rep"], Published)

    assert sorted(p.name for p in (output_dir / "scan").iterdir()) == [
        "scan.html",
        "scan.json",
        "scan.nii.gz",
        "scan.qa.nc",
    ]
    assert sorted(p.name for p in (output_dir / "scan.rep").iterdir()) == [
        "scan.rep.html",
        "scan.rep.json",
        "scan.rep.nii.gz",
        "scan.rep.qa.nc",
    ]


def test_a_progress_callback_that_raises_propagates_and_fails_no_series(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
) -> None:
    """A broken callback is the caller's bug, not this series' -- see `run_session`."""
    nifti, base = prepared_series(name="scan")
    sidecar = _sidecar(base, series_number=1, description="QA_EPI")
    name = naming.qa_stem(sidecar)
    assert name is not None
    converter = stub_dcm2niix({"stem1": (nifti, sidecar)})
    output_dir = tmp_path / "output"

    def _raise_at_analyze(event: Progress) -> None:
        if event.stage is Stage.ANALYZE:
            raise RuntimeError("callback queue is closed")

    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=output_dir,
        settings=_SETTINGS,
        dcm2niix=converter,
    )
    with pytest.raises(RuntimeError, match="callback queue is closed"):
        run_session(request, progress=_raise_at_analyze)

    # No `Failed` outcome was ever produced (the exception escaped before one
    # could be built), no staging directory survived, and no series directory
    # exists either -- the run never reached publish.
    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []


def test_a_warning_during_analysis_lands_on_the_published_outcome(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("fmriqc_launcher.session.write_run_page", _fast_render)
    real = fmriqc.analyze
    monkeypatch.setattr(fmriqc, "analyze", _warning_wrapper(real))
    nifti, base = prepared_series(name="scan")
    sidecar = _sidecar(base, series_number=1, description="QA_EPI")
    name = naming.qa_stem(sidecar)
    assert name is not None
    converter = stub_dcm2niix({"stem1": (nifti, sidecar)})

    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=tmp_path / "output",
        settings=_SETTINGS,
        dcm2niix=converter,
    )
    result = run_session(request)

    outcome = result.outcomes[0]
    assert isinstance(outcome, Published)
    assert any("stub warning from the analysis" in w for w in outcome.warnings)


def test_a_warning_during_render_is_not_captured(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only analysis is captured now, exactly as `fmriqc.cli.qa` does.

    `simplefilter("always")` over save/render used to revive warnings a
    library silences on purpose -- netCDF4's first-import numpy notice --
    and present them as findings about the physicist's scan. A render that
    warns is proof the fix holds: the warning still fires (`pytest.warns`
    around the whole call), but nothing lands on the outcome.
    """
    monkeypatch.setattr("fmriqc_launcher.session.write_run_page", _warn_then_render)
    nifti, base = prepared_series(name="scan")
    sidecar = _sidecar(base, series_number=1, description="QA_EPI")
    name = naming.qa_stem(sidecar)
    assert name is not None
    converter = stub_dcm2niix({"stem1": (nifti, sidecar)})

    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=tmp_path / "output",
        dcm2niix=converter,
    )
    with pytest.warns(UserWarning, match="stub warning from the render step"):
        result = run_session(request)

    outcome = result.outcomes[0]
    assert isinstance(outcome, Published)
    # This phantom's own analysis warns too (its motion fit never converges,
    # by construction -- see `prepared_series`), so the assertion that
    # matters is that the *render's* warning specifically never lands here,
    # not that the tuple is empty.
    assert not any("stub warning from the render step" in w for w in outcome.warnings)


def test_a_failure_staging_a_series_is_a_failed_outcome(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-analysis stage (moving the NIfTI and its companions) is guarded too."""

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full while staging")

    monkeypatch.setattr("fmriqc_launcher.session._move_companions", _raise)
    nifti, base = prepared_series(name="scan")
    sidecar = _sidecar(base, series_number=1, description="QA_EPI")
    name = naming.qa_stem(sidecar)
    assert name is not None
    converter = stub_dcm2niix({"stem1": (nifti, sidecar)})

    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=tmp_path / "output",
        settings=_SETTINGS,
        dcm2niix=converter,
    )
    result = run_session(request)

    outcome = result.outcomes[0]
    assert isinstance(outcome, Failed)
    assert "disk full while staging" in outcome.reason


def test_a_warning_during_analysis_lands_on_the_failed_outcome(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A warning during analysis, then a *later* stage (render) fails: both survive."""
    monkeypatch.setattr("fmriqc_launcher.session.write_run_page", _fail_render)
    real = fmriqc.analyze
    monkeypatch.setattr(fmriqc, "analyze", _warning_wrapper(real))
    nifti, base = prepared_series(name="scan")
    sidecar = _sidecar(base, series_number=1, description="QA_EPI")
    name = naming.qa_stem(sidecar)
    assert name is not None
    converter = stub_dcm2niix({"stem1": (nifti, sidecar)})

    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=tmp_path / "output",
        settings=_SETTINGS,
        dcm2niix=converter,
    )
    result = run_session(request)

    outcome = result.outcomes[0]
    assert isinstance(outcome, Failed)
    assert "stub render failure" in outcome.reason
    assert any("stub warning from the analysis" in w for w in outcome.warnings)


def test_a_failure_saving_the_artifact_is_a_failed_outcome_with_its_warnings(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`save_artifact` failing is `Failed`, carrying the analysis warnings, nothing
    staged left over.
    """
    real = fmriqc.analyze
    monkeypatch.setattr(fmriqc, "analyze", _warning_wrapper(real))

    def _failing_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full while saving the artifact")

    monkeypatch.setattr(fmriqc, "save_artifact", _failing_save)
    nifti, base = prepared_series(name="scan")
    sidecar = _sidecar(base, series_number=1, description="QA_EPI")
    name = naming.qa_stem(sidecar)
    assert name is not None
    converter = stub_dcm2niix({"stem1": (nifti, sidecar)})

    output_dir = tmp_path / "output"
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=output_dir,
        settings=_SETTINGS,
        dcm2niix=converter,
    )
    result = run_session(request)

    outcome = result.outcomes[0]
    assert isinstance(outcome, Failed)
    assert "disk full while saving the artifact" in outcome.reason
    assert any("stub warning from the analysis" in w for w in outcome.warnings)
    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []
