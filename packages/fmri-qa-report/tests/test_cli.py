"""The `fmri-qa-report` command line: artifacts on disk in, a PDF or HTML out."""

import inspect
from pathlib import Path

import pytest

import fmriqc as q
from fmriqc_report import cli


def _body(fn) -> list[str]:
    """The lines of `fn`'s source past its docstring, for comparing two copies."""
    source = inspect.getsource(fn)
    lines = source.split('"""')[-1].splitlines()  # past the docstring
    return [line.strip() for line in lines if line.strip()]


@pytest.fixture
def saved(tmp_path, artifact) -> str:
    """The shared artifact written to disk, as the CLI would receive it."""
    return str(q.save_artifact(artifact, tmp_path / "scan.qa.nc"))


def test_main_renders_a_saved_artifact(tmp_path, saved, capsys) -> None:
    pdf = tmp_path / "qa.pdf"
    rc = cli.main([saved, "--pdf", str(pdf)])
    assert rc == 0
    assert "# wrote" in capsys.readouterr().out
    assert pdf.read_bytes().startswith(b"%PDF")


def test_main_builds_a_packet_from_several_artifacts(tmp_path, saved) -> None:
    pdf = tmp_path / "packet.pdf"
    rc = cli.main([saved, saved, "--pdf", str(pdf), "--cover", "--appendix"])
    assert rc == 0  # cover + two dashboard pages + appendix
    assert pdf.read_bytes().startswith(b"%PDF")


def test_main_renders_the_physics_tier(tmp_path, saved) -> None:
    pdf = tmp_path / "physics.pdf"
    rc = cli.main([saved, "--pdf", str(pdf), "--tier", "physics"])
    assert rc == 0
    assert pdf.read_bytes().startswith(b"%PDF")


def test_main_skips_an_unreadable_artifact_but_renders_the_rest(
    tmp_path, saved, capsys
) -> None:
    pdf = tmp_path / "qa.pdf"
    rc = cli.main([str(tmp_path / "missing.nc"), saved, "--pdf", str(pdf)])
    captured = capsys.readouterr()
    assert rc == 1  # a failure makes the run exit non-zero
    assert "ERROR" in captured.err and "Traceback" not in captured.err
    assert pdf.read_bytes().startswith(b"%PDF")  # the readable one still rendered
    # ...and the packet says it is missing one, in its own metadata: a PDF is
    # handed on without this terminal.
    assert "1 of 2 artifact(s) could not be read" in captured.err
    assert b"1 of 2 scans; 1 omitted" in pdf.read_bytes()


def test_main_refuses_a_pdf_that_would_overwrite_an_artifact(
    tmp_path, saved, capsys, monkeypatch
) -> None:
    """`--pdf` naming an input must fail before the artifact is read or replaced.

    The artifacts are loaded first and the PDF is moved over its destination
    last, so without the guard the run succeeds and leaves a PDF where the
    archive was. The relative spelling is the one a shell produces.
    """
    archive = Path(saved)
    before = archive.read_bytes()
    monkeypatch.chdir(tmp_path)
    rc = cli.main([saved, "--pdf", f"./{archive.name}"])
    assert rc == 1
    assert "would overwrite the input" in capsys.readouterr().err
    assert archive.read_bytes() == before


def test_main_fails_when_no_artifact_can_be_read(tmp_path, capsys) -> None:
    rc = cli.main([str(tmp_path / "missing.nc"), "--pdf", str(tmp_path / "qa.pdf")])
    assert rc == 1
    assert "nothing to render" in capsys.readouterr().err
    assert not (tmp_path / "qa.pdf").exists()


def test_main_reports_a_write_failure_without_a_traceback(
    tmp_path, saved, capsys
) -> None:
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")  # a file where a parent dir must go
    rc = cli.main([saved, "--pdf", str(blocked / "qa.pdf")])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ERROR: could not write PDF" in captured.err
    assert "Traceback" not in captured.err
    # the atomic write's temporary file is an implementation detail, not an error
    assert ".tmp" not in captured.err


def test_main_creates_the_pdf_destination_directory(tmp_path, saved) -> None:
    """A missing output directory is created, as `--artifact` already does."""
    pdf = tmp_path / "reports" / "2026-01" / "qa.pdf"
    assert cli.main([saved, "--pdf", str(pdf)]) == 0
    assert pdf.is_file()


def test_main_writes_a_single_file_html_report(tmp_path, saved, capsys) -> None:
    """The one real end-to-end HTML render in this module; every other HTML
    test below stubs `write_run_page` to stay fast."""
    html = tmp_path / "qa.html"
    rc = cli.main([saved, "--html", str(html)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "# wrote" in captured.out
    text = html.read_text(encoding="utf-8")
    assert "data:image/svg+xml;base64," in text
    assert "<style" in text
    assert "<link" not in text
    assert "<script" not in text


def test_html_refuses_more_than_one_artifact(tmp_path, saved, capsys) -> None:
    html = tmp_path / "qa.html"
    with pytest.raises(SystemExit) as info:
        cli.main([saved, saved, "--html", str(html)])
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert "--html renders one artifact to one file" in err
    assert not html.exists()


def test_html_refuses_to_overwrite_an_input(
    tmp_path, saved, capsys, monkeypatch
) -> None:
    archive = Path(saved)
    before = archive.read_bytes()
    monkeypatch.chdir(tmp_path)
    rc = cli.main([saved, "--html", f"./{archive.name}"])
    assert rc == 1
    assert "would overwrite the input" in capsys.readouterr().err
    assert archive.read_bytes() == before


def test_html_and_pdf_refuse_to_share_one_destination(tmp_path, saved, capsys) -> None:
    shared = tmp_path / "qa.out"
    rc = cli.main([saved, "--pdf", str(shared), "--html", f"{tmp_path}/./qa.out"])
    assert rc == 1
    assert "would overwrite each other" in capsys.readouterr().err
    assert not shared.exists()


@pytest.mark.parametrize(
    ("flag", "value"),
    [("--tier", "physics"), ("--cover", None), ("--appendix", None)],
)
def test_html_alone_refuses_a_pdf_only_option(
    tmp_path, saved, capsys, flag, value
) -> None:
    html = tmp_path / "qa.html"
    argv = [saved, "--html", str(html), flag]
    if value is not None:
        argv.append(value)
    with pytest.raises(SystemExit) as info:
        cli.main(argv)
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert flag in err and "only apply to --pdf" in err
    assert not html.exists()


def test_html_with_pdf_still_accepts_pdf_only_options(tmp_path, saved) -> None:
    pdf = tmp_path / "qa.pdf"
    html = tmp_path / "qa.html"
    rc = cli.main(
        [saved, "--pdf", str(pdf), "--html", str(html), "--cover", "--appendix"]
    )
    assert rc == 0
    assert pdf.read_bytes().startswith(b"%PDF")


def test_html_skips_an_unreadable_artifact(tmp_path, capsys) -> None:
    html = tmp_path / "qa.html"
    rc = cli.main([str(tmp_path / "missing.nc"), "--html", str(html)])
    captured = capsys.readouterr()
    assert rc == 1
    assert "ERROR" in captured.err
    assert not html.exists()


def test_html_and_pdf_together_write_both(tmp_path, saved, capsys, monkeypatch) -> None:
    """Stub the expensive HTML render; the PDF path already has its own
    real-render coverage above."""
    written: list[Path] = []

    def fake_write_run_page(artifact, path, *, title=None, **_kw):
        Path(path).write_text("<html><style></style></html>", encoding="utf-8")
        written.append(Path(path))
        return Path(path)

    from fmriqc_report.formats import html as html_module

    monkeypatch.setattr(html_module, "write_run_page", fake_write_run_page)

    pdf = tmp_path / "qa.pdf"
    html = tmp_path / "qa.html"
    rc = cli.main([saved, "--pdf", str(pdf), "--html", str(html)])
    captured = capsys.readouterr()
    assert rc == 0
    assert pdf.read_bytes().startswith(b"%PDF")
    assert html.read_text(encoding="utf-8") == "<html><style></style></html>"
    assert "# wrote" in captured.out
    assert written == [html]


def test_main_titles_a_section_from_the_artifact_provenance(tmp_path, artifact) -> None:
    """The recorded scan name is the section title, whatever the file is called."""
    path = q.save_artifact(artifact, tmp_path / "unrelated-name.nc")
    assert cli._title(q.load_artifact(path), str(path)) == "scan.nii.gz"


def test_main_falls_back_to_the_file_name(tmp_path, bare_artifact) -> None:
    from dataclasses import replace

    anonymous = replace(
        bare_artifact, provenance=replace(bare_artifact.provenance, scan="")
    )
    path = q.save_artifact(anonymous, tmp_path / "run-7.qa.nc")
    assert cli._title(q.load_artifact(path), str(path)) == "run-7.qa.nc"


def test_version_flag_prints_and_exits(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"])
    assert info.value.code == 0
    assert "fmri-qa-report" in capsys.readouterr().out


def test_pdf_or_html_is_required(capsys) -> None:
    with pytest.raises(SystemExit) as info:
        cli.main(["scan.qa.nc"])
    assert info.value.code == 2
    err = capsys.readouterr().err
    assert "error:" in err
    assert "--pdf or --html" in err


def test_help_renders(capsys) -> None:
    """`-h`, which argparse %-formats; see the core suite's twin."""
    with pytest.raises(SystemExit) as info:
        cli.main(["-h"])
    assert info.value.code == 0
    assert "usage:" in capsys.readouterr().out


def test_a_wildcard_argument_is_expanded(tmp_path, artifact, capsys) -> None:
    """PowerShell hands `artifacts/*.qa.nc` over with the `*` still in it."""
    for name in ("first", "second"):
        q.save_artifact(artifact, tmp_path / f"{name}.qa.nc")
    pdf = tmp_path / "qa.pdf"
    rc = cli.main([f"{tmp_path}/*.qa.nc", "--pdf", str(pdf)])
    assert rc == 0
    assert pdf.is_file()


def test_a_wildcard_matching_nothing_is_reported_not_dropped(tmp_path, capsys) -> None:
    """A pattern that names no artifact must fail, not render an empty packet."""
    rc = cli.main([f"{tmp_path}/*.qa.nc", "--pdf", str(tmp_path / "qa.pdf")])
    assert rc == 1
    assert "*.qa.nc" in capsys.readouterr().err


def test_the_two_glob_expanders_have_not_drifted() -> None:
    """The seam forbids sharing the helper, so prove the copies still agree.

    `fmriqc.cli.arguments.expand_globs` is the original; this package may not
    import it (`test_layering`), so it keeps a twin. A fix applied to one and
    not the other is the failure this catches.
    """
    from fmriqc.cli.arguments import expand_globs
    from fmriqc_report.cli import _expand_globs

    assert _body(_expand_globs) == _body(expand_globs)


def test_the_two_same_file_guards_have_not_drifted() -> None:
    """The seam forbids sharing the helper, so prove the copies still agree.

    `fmriqc.load.paths.same_file` is the original; this package may not import
    it (`test_layering`), so it keeps a twin. A fix applied to one and not the
    other is the failure this catches.
    """
    from fmriqc.load.paths import same_file
    from fmriqc_report.cli import _same_file

    assert _body(_same_file) == _body(same_file)
