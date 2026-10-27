"""`run_session`: the functional core, exercised end to end over a stub converter.

Only `test_one_series_is_imported_analyzed_and_published` renders a real
report (~8 s). Other tests that need a *published* series use the
`fast_render` fixture, which patches `write_run_page` to take a few
milliseconds and still leaves a file for `Published.report`.
"""

import logging
import os
import shutil
import stat
import sys
import tempfile
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

import fmriqa_io
from fmriqa.settings import AnalysisSettings
from fmriqa_launcher.exceptions import SessionError
from fmriqa_launcher.outcome import Failed, Published, Refused
from fmriqa_launcher.progress import CleanupNotice, Progress, Stage
from fmriqa_launcher.request import RunRequest
from fmriqa_launcher.session import _copy_durably, _publish, run_session

PreparedSeries = Callable[..., tuple[Path, dict[str, object]]]
StubDcm2niix = Callable[..., Path]
StubSeries = Callable[..., tuple[Path, list[str]]]

_SETTINGS = AnalysisSettings(roi_size=9)


@pytest.fixture
def staging_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A private stand-in for the system's temporary directory.

    Staging comes from `tempfile.mkdtemp`, so it lands in `tempfile.tempdir`.
    Pointing that here lets a test see what a run made and left, where no
    other process writes.
    """
    root = tmp_path / "system-tmp"
    root.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(root))
    return root


def _fail_render(_artifact: object, _path: Path, **_kwargs: object) -> Path:
    """A render that always fails -- pairs an analysis warning with a later failure."""
    raise RuntimeError("stub render failure")


def _stop(*_args: object, **_kwargs: object) -> None:
    raise SessionError("stopped before any series")


def _never(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("must not be called")


def _held(*_args: object, **_kwargs: object) -> None:
    raise PermissionError(13, "held open by a sync client")


def _rmtree_except(prefix: str) -> Callable[..., None]:
    """`shutil.rmtree`, except that a directory named `prefix*` is left in place."""
    real = shutil.rmtree

    def rmtree(path: Path, **kwargs: object) -> None:
        if not Path(path).name.startswith(prefix):
            real(path, **kwargs)

    return rmtree


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits only")
def test_one_series_is_imported_analyzed_and_published(
    tmp_path: Path,
    dicom_dir: Path,
    stub_series: StubSeries,
    staging_root: Path,
) -> None:
    converter, (name,) = stub_series()

    output_dir = tmp_path / "output"
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=output_dir,
        settings=_SETTINGS,
        dcm2niix=converter,
    )

    events: list[Progress] = []
    notices: list[CleanupNotice] = []
    old_umask = os.umask(0o022)
    try:
        result = run_session(request, progress=events.append, notice=notices.append)
    finally:
        os.umask(old_umask)

    assert result.complete
    assert notices == []
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

    # What is published honors the umask (0o755 and 0o644), not the 0o700 of
    # the `tempfile.mkdtemp` staging directory it was copied from.
    assert stat.S_IMODE(series_dir.stat().st_mode) == 0o755
    for published_file in series_dir.iterdir():
        assert stat.S_IMODE(published_file.stat().st_mode) == 0o644

    # Nothing but the series is left in the output directory, and nothing at
    # all where the work was done.
    assert [p.name for p in output_dir.iterdir()] == [name]
    assert list(staging_root.iterdir()) == []

    reloaded = fmriqa_io.load_artifact(published.artifact)
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


@pytest.mark.usefixtures("fast_render")
def test_a_series_whose_name_already_exists_is_refused_untouched(
    tmp_path: Path,
    dicom_dir: Path,
    stub_series: StubSeries,
) -> None:
    converter, (name,) = stub_series()

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


@pytest.mark.usefixtures("fast_render")
def test_one_series_failing_does_not_stop_the_other(
    tmp_path: Path,
    dicom_dir: Path,
    stub_series: StubSeries,
) -> None:
    converter, (healthy_name, broken_name) = stub_series(frames=(40, 2))
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


@pytest.mark.usefixtures("fast_render")
def test_cancelling_between_series_stops_before_the_next_one(
    tmp_path: Path,
    dicom_dir: Path,
    stub_series: StubSeries,
) -> None:
    converter, (first_name, second_name) = stub_series(frames=(40, 40))
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
def test_an_output_directory_that_cannot_be_written_to_stops_the_run_at_once(
    tmp_path: Path, dicom_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before any work: staging is elsewhere, so publishing would find out last."""

    monkeypatch.setattr("fmriqa_launcher.session._run_in_staging", _never)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    output_dir.chmod(0o555)  # exists already, so the first mkdir is a no-op
    try:
        request = RunRequest(dicom_dir=dicom_dir, output_dir=output_dir)
        with pytest.raises(SessionError, match="cannot write to"):
            run_session(request)
    finally:
        output_dir.chmod(0o755)


def test_the_writability_probe_leaves_nothing_behind(
    tmp_path: Path, dicom_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("fmriqa_launcher.session._run_in_staging", _stop)
    request = RunRequest(dicom_dir=dicom_dir, output_dir=tmp_path / "output")

    with pytest.raises(SessionError, match="stopped before any series"):
        run_session(request)

    assert list((tmp_path / "output").iterdir()) == []


def test_a_probe_that_cannot_be_removed_is_logged_and_does_not_stop_the_run(
    tmp_path: Path,
    dicom_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Making the probe proved the directory writable; failing to remove it cannot.

    A sync client opens what was just made and the removal is refused, the
    race `fmriqa_io.rename` exists for. Treating it as "cannot write" would
    refuse every run into a watched directory.
    """
    monkeypatch.setattr(
        "fmriqa_launcher.session.shutil.rmtree", _rmtree_except(".fmri-qa-probe.")
    )
    monkeypatch.setattr("fmriqa_launcher.session._run_in_staging", _stop)
    request = RunRequest(dicom_dir=dicom_dir, output_dir=tmp_path / "output")

    notices: list[CleanupNotice] = []
    with (
        caplog.at_level(logging.WARNING, logger="fmriqa_launcher.session"),
        pytest.raises(SessionError, match="stopped before any series"),
    ):
        run_session(request, notice=notices.append)

    (probe,) = (tmp_path / "output").iterdir()
    assert str(probe) in caplog.text
    assert "can be deleted" in caplog.text
    assert len(notices) == 1
    assert notices[0].path == probe
    assert "can be deleted" in notices[0].message


def test_a_staging_directory_that_cannot_be_created_is_a_session_error(
    tmp_path: Path, dicom_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _full(*_args: object, **_kwargs: object) -> str:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("fmriqa_launcher.session.tempfile.mkdtemp", _full)
    request = RunRequest(dicom_dir=dicom_dir, output_dir=tmp_path / "output")

    with pytest.raises(SessionError, match="cannot create a staging directory"):
        run_session(request)


def test_a_target_that_appears_mid_run_fails_that_series(
    tmp_path: Path,
    dicom_dir: Path,
    stub_series: StubSeries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A race the code defends against: the target exists by the time of publish."""
    converter, (name,) = stub_series()
    output_dir = tmp_path / "output"

    def _render_then_collide(artifact: object, path: Path, **_kwargs: object) -> Path:
        target = Path(path)
        target.write_text("<html></html>", encoding="utf-8")
        (output_dir / name).mkdir(parents=True)
        return target

    monkeypatch.setattr("fmriqa_launcher.session.write_run_page", _render_then_collide)
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


@pytest.mark.usefixtures("fast_render")
def test_two_series_with_a_dotted_prefix_pair_each_publish_their_own_files(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
    stub_dcm2niix: StubDcm2niix,
) -> None:
    """`scan.rep.json` must land beside `scan.rep`, not get stolen by `scan`.

    These sidecars lack `naming.qa_stem`'s fields, so `import_dicom` keeps the
    original dcm2niix stems ("scan" and "scan.rep"), reproducing the
    dotted-prefix collision the converter's longest-stem rule resolves.
    """
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


def test_a_series_whose_directory_appears_mid_run_is_refused_not_analyzed(
    tmp_path: Path,
    dicom_dir: Path,
    fast_render: Callable[..., Path],
    stub_series: StubSeries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Another run publishing the second name during the first's render is no cost."""
    converter, (first_name, second_name) = stub_series(frames=(40, 40))
    output_dir = tmp_path / "output"

    def render_then_race(artifact: object, path: Path, **kwargs: object) -> Path:
        (output_dir / second_name).mkdir()
        return fast_render(artifact, path, **kwargs)

    monkeypatch.setattr("fmriqa_launcher.session.write_run_page", render_then_race)
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=output_dir,
        settings=_SETTINGS,
        dcm2niix=converter,
    )
    events: list[Progress] = []

    result = run_session(request, progress=events.append)

    by_name = {o.name: o for o in result.outcomes}
    assert isinstance(by_name[first_name], Published)
    assert by_name[second_name] == Refused(second_name, output_dir / second_name)
    assert second_name not in {e.series for e in events}


@pytest.mark.usefixtures("fast_render")
def test_a_series_with_no_sidecar_is_published_without_one(
    tmp_path: Path,
    dicom_dir: Path,
    prepared_series: PreparedSeries,
) -> None:
    nifti, _ = prepared_series(name="scan")
    converter = tmp_path / "bare-dcm2niix"
    converter.write_text(
        f"#!{sys.executable}\n"
        "import shutil, sys\n"
        "from pathlib import Path\n"
        "out = Path(sys.argv[sys.argv.index('-o') + 1])\n"
        'print("Chris Rorden\'s dcm2niiX version v1.0.20260724 (JP2:OpenJPEG)")\n'
        f"shutil.copy({str(nifti)!r}, out / 'scan.nii.gz')\n"
    )
    converter.chmod(0o755)
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=tmp_path / "output",
        settings=_SETTINGS,
        dcm2niix=converter,
    )

    (outcome,) = run_session(request).outcomes

    assert isinstance(outcome, Published)
    assert outcome.sidecar is None
    assert not (outcome.directory / "scan.json").exists()


def test_a_progress_callback_that_raises_propagates_and_fails_no_series(
    tmp_path: Path,
    dicom_dir: Path,
    stub_series: StubSeries,
) -> None:
    """A broken callback is the caller's bug, not this series' -- see `run_session`."""
    converter, _ = stub_series()
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

    # No `Failed` outcome was produced (the exception escaped before one could
    # be built), no staging directory survived, and no series directory
    # exists. The run never reached publish.
    assert output_dir.is_dir()
    assert list(output_dir.iterdir()) == []


@pytest.mark.usefixtures("fast_render", "warn_during_analysis")
def test_a_warning_during_analysis_lands_on_the_published_outcome(
    tmp_path: Path,
    dicom_dir: Path,
    stub_series: StubSeries,
) -> None:
    converter, _ = stub_series()

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
    fast_render: Callable[..., Path],
    stub_series: StubSeries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only analysis is captured, as in `fmriqa_cli.qa`.

    `simplefilter("always")` over save/render used to revive warnings a
    library silences on purpose, such as netCDF4's first-import numpy notice,
    and report them as findings about the scan. Here a render warns: it still
    fires (`pytest.warns` around the call) but nothing lands on the outcome.
    """

    def _warn_then_render(artifact: object, path: Path, **_kwargs: object) -> Path:
        warnings.warn("a stub warning from the render step", stacklevel=2)
        return fast_render(artifact, path)

    monkeypatch.setattr("fmriqa_launcher.session.write_run_page", _warn_then_render)
    converter, _ = stub_series()

    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=tmp_path / "output",
        dcm2niix=converter,
    )
    with pytest.warns(UserWarning, match="stub warning from the render step"):
        result = run_session(request)

    outcome = result.outcomes[0]
    assert isinstance(outcome, Published)
    # This phantom's own analysis warns too (its motion fit never converges
    # by construction; see `prepared_series`). So assert that the *render's*
    # warning never lands here, not that the tuple is empty.
    assert not any("stub warning from the render step" in w for w in outcome.warnings)


def test_a_failure_staging_a_series_is_a_failed_outcome(
    tmp_path: Path,
    dicom_dir: Path,
    stub_series: StubSeries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-analysis stage (moving the NIfTI and its companions) is guarded too."""

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full while staging")

    monkeypatch.setattr("fmriqa_launcher.session._move_files", _raise)
    converter, _ = stub_series()

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


@pytest.mark.usefixtures("warn_during_analysis")
def test_a_warning_during_analysis_lands_on_the_failed_outcome(
    tmp_path: Path,
    dicom_dir: Path,
    stub_series: StubSeries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A warning during analysis, then a *later* stage (render) fails: both survive."""
    monkeypatch.setattr("fmriqa_launcher.session.write_run_page", _fail_render)
    converter, _ = stub_series()

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


@pytest.mark.usefixtures("warn_during_analysis")
def test_a_failure_saving_the_artifact_is_a_failed_outcome_with_its_warnings(
    tmp_path: Path,
    dicom_dir: Path,
    stub_series: StubSeries,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `save_artifact` failure is `Failed`, with the analysis warnings kept.

    Nothing is left over in staging.
    """

    def _failing_save(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full while saving the artifact")

    monkeypatch.setattr(fmriqa_io, "save_artifact", _failing_save)
    converter, _ = stub_series()

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


def test_the_output_directory_holds_no_intermediates_while_a_series_is_worked_on(
    tmp_path: Path,
    dicom_dir: Path,
    fast_render: Callable[..., Path],
    stub_series: StubSeries,
    staging_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What a sync client watching `output_dir` would have been handed to upload.

    Checked from inside the render, the last step before publishing, when the
    import has run, the scan is filed and the artifact is written. The old
    staging-in-`output_dir` design left all of that in `output_dir`; it is now
    in the temporary directory.
    """
    output_dir = tmp_path / "output"
    seen: dict[str, list[str]] = {}

    def _look_then_render(artifact: object, path: Path, **kwargs: object) -> Path:
        seen["output"] = sorted(p.name for p in output_dir.rglob("*"))
        seen["staging"] = sorted(p.name for p in staging_root.rglob("*") if p.is_file())
        return fast_render(artifact, path, **kwargs)

    monkeypatch.setattr("fmriqa_launcher.session.write_run_page", _look_then_render)
    converter, (name,) = stub_series()
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=output_dir,
        settings=_SETTINGS,
        dcm2niix=converter,
    )

    result = run_session(request)

    assert result.complete
    assert seen["output"] == []
    assert seen["staging"] == [f"{name}.json", f"{name}.nii.gz", f"{name}.qa.nc"]
    # And afterwards: the series where it belongs, nothing where it was made.
    assert [p.name for p in output_dir.iterdir()] == [name]
    assert list(staging_root.iterdir()) == []


def test_a_published_series_is_dropped_from_staging_before_the_next_one_starts(
    tmp_path: Path,
    dicom_dir: Path,
    fast_render: Callable[..., Path],
    stub_series: StubSeries,
    staging_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publishing copies where it used to move, so staging has to be emptied by hand.

    Otherwise every finished series sits in the temporary directory until the
    run ends. That disk is small and often RAM-backed; the output directory
    has room to spare.
    """
    staged_at_each_render: list[set[str]] = []

    def _look_then_render(artifact: object, path: Path, **kwargs: object) -> Path:
        staged_at_each_render.append({p.name for p in staging_root.rglob("*.qa.nc")})
        return fast_render(artifact, path, **kwargs)

    monkeypatch.setattr("fmriqa_launcher.session.write_run_page", _look_then_render)
    converter, (first_name, second_name) = stub_series(frames=(40, 40))
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=tmp_path / "output",
        settings=_SETTINGS,
        dcm2niix=converter,
    )

    result = run_session(request)

    assert [o.name for o in result.published] == [first_name, second_name]
    # Each render sees its own series' artifact in staging, and only that one.
    assert staged_at_each_render == [
        {f"{first_name}.qa.nc"},
        {f"{second_name}.qa.nc"},
    ]


def test_publishing_copies_the_work_directory_into_place(tmp_path: Path) -> None:
    work, output = tmp_path / "work", tmp_path / "output"
    work.mkdir()
    output.mkdir()
    (work / "scan.nii.gz").write_bytes(b"scan")
    (work / "scan.html").write_bytes(b"page")

    _publish(work, output / "series")

    assert (output / "series" / "scan.nii.gz").read_bytes() == b"scan"
    assert (output / "series" / "scan.html").read_bytes() == b"page"
    # Only the series: the hidden sibling it was copied into became it.
    assert [p.name for p in output.iterdir()] == ["series"]


def test_a_series_is_never_visible_under_its_name_until_it_is_whole(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The copy is the slow step, so it must not happen under the final name."""
    work, output = tmp_path / "work", tmp_path / "output"
    work.mkdir()
    output.mkdir()
    for file_name in ("a", "b", "c"):
        (work / file_name).write_bytes(b"x")
    seen: list[bool] = []
    copied_into: set[str] = set()

    def _watching(source: Path, destination: Path) -> None:
        seen.append((output / "series").exists())
        copied_into.add(destination.parent.name)
        _copy_durably(source, destination)

    monkeypatch.setattr("fmriqa_launcher.session._copy_durably", _watching)

    _publish(work, output / "series")

    assert seen == [False, False, False]
    # One hidden sibling, in the output directory so the rename that follows
    # stays on one filesystem. It is gone once it has become the series.
    (sibling,) = copied_into
    assert sibling.startswith(".series.")
    assert sibling.endswith(".partial")
    assert [p.name for p in output.iterdir()] == ["series"]
    assert sorted(p.name for p in (output / "series").iterdir()) == ["a", "b", "c"]


def test_a_copy_that_fails_leaves_nothing_in_the_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, output = tmp_path / "work", tmp_path / "output"
    work.mkdir()
    output.mkdir()
    for file_name in ("a", "b"):
        (work / file_name).write_bytes(b"x")

    def _fill_the_disk(source: Path, destination: Path) -> None:
        if source.name == "b":
            raise OSError(28, "No space left on device")
        _copy_durably(source, destination)

    monkeypatch.setattr("fmriqa_launcher.session._copy_durably", _fill_the_disk)

    with pytest.raises(OSError, match="No space left"):
        _publish(work, output / "series")

    assert list(output.iterdir()) == []
    # Staging is untouched, so nothing about the failure cost the work itself.
    assert sorted(p.name for p in work.iterdir()) == ["a", "b"]


def test_a_rename_that_is_refused_leaves_nothing_in_the_output_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, output = tmp_path / "work", tmp_path / "output"
    work.mkdir()
    output.mkdir()
    (work / "a").write_bytes(b"x")

    monkeypatch.setattr("fmriqa_launcher.session.replace_patiently", _held)

    with pytest.raises(PermissionError, match="held open"):
        _publish(work, output / "series")

    assert list(output.iterdir()) == []


def test_copying_durably_copies_the_bytes_and_never_overwrites(tmp_path: Path) -> None:
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"\x00scan\xff" * 100_000)

    _copy_durably(source, destination)
    assert destination.read_bytes() == source.read_bytes()

    with pytest.raises(FileExistsError):
        _copy_durably(source, destination)


def test_copying_durably_syncs_before_it_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rename that follows is only as durable as the bytes it renames."""
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.write_bytes(b"scan")
    synced: list[int] = []
    real = os.fsync

    def _fsync(descriptor: int) -> None:
        synced.append(destination.stat().st_size)
        real(descriptor)

    monkeypatch.setattr("fmriqa_launcher.session.os.fsync", _fsync)

    _copy_durably(source, destination)

    # Once, and with every byte already written through to the file.
    assert synced == [4]


def test_publishing_onto_an_existing_series_is_refused_before_any_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work, target = tmp_path / "work", tmp_path / "series"
    work.mkdir()
    target.mkdir()

    monkeypatch.setattr("fmriqa_launcher.session.replace_patiently", _never)

    with pytest.raises(SessionError, match="created while this run was in progress"):
        _publish(work, target)


@pytest.mark.parametrize("refusal", [PermissionError, FileExistsError])
def test_a_series_published_by_another_run_mid_rename_is_named_as_that(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refusal: type[OSError]
) -> None:
    """Windows reports a rename onto an existing directory as `refusal`.

    `replace_patiently` waits out `PermissionError`, so by the time it gives up
    the other run has long since published and "Access is denied" would be
    misleading.
    """
    work, target = tmp_path / "work", tmp_path / "series"
    work.mkdir()

    def _lose_the_race(_source: Path, destination: Path) -> None:
        destination.mkdir()
        raise refusal(13, "Access is denied")

    monkeypatch.setattr("fmriqa_launcher.session.replace_patiently", _lose_the_race)

    with pytest.raises(SessionError, match="created while this run was in progress"):
        _publish(work, target)
    assert work.exists()


def test_a_staging_directory_that_cannot_be_removed_is_logged_by_name(
    tmp_path: Path,
    dicom_dir: Path,
    staging_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`ignore_errors=True` must not mean a silent residue beside the reports."""

    monkeypatch.setattr("fmriqa_launcher.session._run_in_staging", _stop)
    monkeypatch.setattr(
        "fmriqa_launcher.session.shutil.rmtree", _rmtree_except("fmri-qa-run.")
    )
    request = RunRequest(
        dicom_dir=dicom_dir, output_dir=tmp_path / "output", settings=_SETTINGS
    )

    notices: list[CleanupNotice] = []
    with (
        caplog.at_level(logging.WARNING, logger="fmriqa_launcher.session"),
        pytest.raises(SessionError, match="stopped before any series"),
    ):
        run_session(request, notice=notices.append)

    (left_behind,) = staging_root.glob("fmri-qa-run.*")
    assert str(left_behind) in caplog.text
    assert "can be deleted" in caplog.text
    assert len(notices) == 1
    assert notices[0].path == left_behind
    assert "can be deleted" in notices[0].message
    # Wherever it was left, it was not among the reports.
    assert list((tmp_path / "output").iterdir()) == []


def test_a_staging_directory_that_was_removed_is_not_mentioned(
    tmp_path: Path,
    dicom_dir: Path,
    staging_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("fmriqa_launcher.session._run_in_staging", _stop)
    request = RunRequest(
        dicom_dir=dicom_dir, output_dir=tmp_path / "output", settings=_SETTINGS
    )

    notices: list[CleanupNotice] = []
    with (
        caplog.at_level(logging.WARNING, logger="fmriqa_launcher.session"),
        pytest.raises(SessionError),
    ):
        run_session(request, notice=notices.append)

    assert list(staging_root.iterdir()) == []
    assert "could not remove" not in caplog.text
    assert notices == []


@pytest.mark.usefixtures("fast_render")
@pytest.mark.parametrize("partial", [False, True], ids=["series-work", "partial"])
def test_series_cleanup_notices_reach_the_session_caller(
    tmp_path: Path,
    dicom_dir: Path,
    staging_root: Path,
    stub_series: StubSeries,
    monkeypatch: pytest.MonkeyPatch,
    partial: bool,
) -> None:
    converter, (name,) = stub_series()
    request = RunRequest(
        dicom_dir=dicom_dir,
        output_dir=tmp_path / "output",
        settings=_SETTINGS,
        dcm2niix=converter,
    )
    prefix = f".{name}." if partial else name
    monkeypatch.setattr("fmriqa_launcher.session.shutil.rmtree", _rmtree_except(prefix))
    if partial:
        monkeypatch.setattr("fmriqa_launcher.session._copy_durably", _held)
    notices: list[CleanupNotice] = []
    result = run_session(request, notice=notices.append)

    assert len(notices) == 1
    leftover = notices[0].path
    assert "can be deleted" in notices[0].message
    if partial:
        assert isinstance(result.outcomes[0], Failed)
        assert "held open" in result.outcomes[0].reason
        assert leftover.parent == request.output_dir
        assert leftover.name.startswith(f".{name}.")
        assert leftover.name.endswith(".partial")
        assert leftover.is_dir()
    else:
        assert result.complete
        assert leftover.name == name
        assert leftover.parent.parent == staging_root
        # The later staging cleanup can remove a previously reported leftover.
        assert not leftover.exists()


def test_a_broken_cleanup_callback_preserves_the_original_session_error(
    tmp_path: Path,
    dicom_dir: Path,
    staging_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr("fmriqa_launcher.session._run_in_staging", _stop)
    monkeypatch.setattr(
        "fmriqa_launcher.session.shutil.rmtree", _rmtree_except("fmri-qa-run.")
    )

    def broken(_notice: CleanupNotice) -> None:
        raise RuntimeError("notice sink is closed")

    request = RunRequest(dicom_dir=dicom_dir, output_dir=tmp_path / "output")
    with pytest.raises(SessionError, match="stopped before any series"):
        run_session(request, notice=broken)
    assert "cleanup notice callback failed" in caplog.text
    assert "notice sink is closed" in caplog.text


@pytest.mark.parametrize("exception", [KeyboardInterrupt, SystemExit])
def test_cleanup_callbacks_do_not_swallow_base_exceptions(
    tmp_path: Path,
    dicom_dir: Path,
    staging_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    exception: type[BaseException],
) -> None:
    monkeypatch.setattr("fmriqa_launcher.session._run_in_staging", _stop)
    monkeypatch.setattr(
        "fmriqa_launcher.session.shutil.rmtree", _rmtree_except("fmri-qa-run.")
    )

    def interrupted(_notice: CleanupNotice) -> None:
        raise exception("stop reporting")

    request = RunRequest(dicom_dir=dicom_dir, output_dir=tmp_path / "output")
    with pytest.raises(exception, match="stop reporting"):
        run_session(request, notice=interrupted)


def test_cleanup_leftovers_are_silent_without_a_notice_callback(
    tmp_path: Path,
    dicom_dir: Path,
    staging_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("fmriqa_launcher.session._run_in_staging", _stop)
    monkeypatch.setattr(
        "fmriqa_launcher.session.shutil.rmtree", _rmtree_except("fmri-qa-run.")
    )
    request = RunRequest(dicom_dir=dicom_dir, output_dir=tmp_path / "output")
    with pytest.raises(SessionError, match="stopped before any series"):
        run_session(request)
    assert tuple(staging_root.iterdir())
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""
