"""Shared fixtures for the launcher tests.

`prepared_series` writes an analyzable synthetic phantom NIfTI + BIDS sidecar
pair with `fmriqa_io.testing.write_phantom`. The phantom itself is
`fmriqa.testing`'s, the one core and io test against.

`stub_dcm2niix` stands in for the real converter. `fmri-qa-core`'s
`fake_dcm2niix` writes NIfTI files that don't load, which is enough for naming
and staging but not for `analyze`. This stub copies an analyzable
`prepared_series` pair into the `-o` directory under dcm2niix-style stems, so
`import_dicom`'s real staging, naming (`names="qa"`) and filing run and the
result is a series `run_session` can analyze.

`stub_series`, `fast_render` and `warn_during_analysis` are setup shared by
`test_session.py` and `test_cli.py`. They are fixtures because under
`--import-mode=importlib` a test module can't import from conftest or a
sibling test module. This overrides testing.md's "helper functions over
fixtures" preference.
"""

import json
import stat
import sys
import warnings
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

import fmriqa
from fmriqa.convert import naming
from fmriqa_io.testing import write_phantom

PreparedSeries = Callable[..., tuple[Path, dict[str, object]]]
StubDcm2niix = Callable[..., Path]
SeriesSidecar = Callable[[dict[str, object], int, str], dict[str, object]]
StubSeries = Callable[..., tuple[Path, list[str]]]


@pytest.fixture
def prepared_series(tmp_path: Path) -> PreparedSeries:
    """Return a factory writing one analyzable phantom NIfTI + sidecar pair.

    Each call gets its own subdirectory, so the NIfTI can be renamed into a
    stub converter's output without colliding. Returns the NIfTI path and the
    sidecar dict written beside it. The caller adds the `SeriesNumber`,
    `SeriesDescription` and acquisition fields `naming` needs.
    """
    counter = iter(range(10_000))

    def factory(
        name: str = "scan", t: int = 40, seed: int = 0, flip: float = 77.0
    ) -> tuple[Path, dict[str, object]]:
        directory = tmp_path / f"prepared-{next(counter)}"
        directory.mkdir()
        nifti = write_phantom(directory, name, t=t, seed=seed, flip=flip)
        sidecar: dict[str, object] = json.loads(
            (directory / f"{name}.json").read_text()
        )
        return nifti, sidecar

    return factory


@pytest.fixture
def stub_dcm2niix(tmp_path: Path) -> StubDcm2niix:
    """Return a factory building a stub dcm2niix from `{stem: (nifti, sidecar)}`.

    `nifti`/`sidecar` are what `prepared_series` returns, with the naming
    fields (`SeriesNumber`, `AcquisitionDateTime`, `SeriesDescription`, ...)
    merged into `sidecar`. The script reads only the `-o DIR` argument from
    `dcm2niix.build_args` and ignores the rest, like `fmri-qa-core`'s
    `fake_dcm2niix`.
    """

    def build(series: dict[str, tuple[Path, dict[str, object]]]) -> Path:
        script = tmp_path / "stub-dcm2niix"
        payload = {
            stem: (str(nifti), sidecar) for stem, (nifti, sidecar) in series.items()
        }
        script.write_text(
            f"#!{sys.executable}\n"
            "import json\n"
            "import shutil\n"
            "import sys\n"
            "from pathlib import Path\n"
            f"series = {payload!r}\n"
            "args = sys.argv[1:]\n"
            "out = Path(args[args.index('-o') + 1])\n"
            'print("Chris Rorden\'s dcm2niiX version v1.0.20260724 (JP2:OpenJPEG)")\n'
            "for stem, (nifti, sidecar) in series.items():\n"
            "    shutil.copy(nifti, out / f'{stem}.nii.gz')\n"
            "    (out / f'{stem}.json').write_text(json.dumps(sidecar))\n"
            "sys.exit(0)\n"
        )
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return script

    return build


@pytest.fixture
def series_sidecar() -> SeriesSidecar:
    """Return `(base, series_number, description) -> sidecar`.

    `base` is the sidecar `prepared_series` returned; the result adds the
    naming fields `naming.qa_stem` reads.
    """

    def build(
        base: dict[str, object], series_number: int, description: str
    ) -> dict[str, object]:
        return {
            **base,
            "SeriesNumber": series_number,
            "AcquisitionDateTime": f"2026-09-09T14:{10 + series_number:02d}:12.500000",
            "SeriesDescription": description,
        }

    return build


@pytest.fixture
def stub_series(
    prepared_series: PreparedSeries,
    series_sidecar: SeriesSidecar,
    stub_dcm2niix: StubDcm2niix,
) -> StubSeries:
    """Return `build(frames=(40,)) -> (converter, names)` for N analyzable series.

    One series per entry of `frames`, which is its length in volumes. A series
    of 2 can't be analyzed, which is how a test gets a failing one. Series are
    numbered 1..N. `converter` is the stub dcm2niix that produces them and
    `names` holds the `naming.qa_stem` name each is published under, in order.
    """

    def build(frames: Sequence[int] = (40,)) -> tuple[Path, list[str]]:
        series: dict[str, tuple[Path, dict[str, object]]] = {}
        names: list[str] = []
        for number, volumes in enumerate(frames, start=1):
            nifti, base = prepared_series(
                name=f"series{number}", t=volumes, seed=number - 1
            )
            sidecar = series_sidecar(base, number, "QA_EPI")
            name = naming.qa_stem(sidecar)
            assert name is not None, f"no qa_stem for {sidecar}"
            series[f"stem{number}"] = (nifti, sidecar)
            names.append(name)
        return stub_dcm2niix(series), names

    return build


@pytest.fixture
def fast_render(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Path]:
    """Replace `write_run_page` with a stand-in that skips the ~8 s render.

    The stand-in still writes a file for `Published.report` to point at, and
    is returned for a test that wraps it.
    """

    def render(artifact: object, path: Path, **_kwargs: object) -> Path:
        target = Path(path)
        target.write_text("<html><body>stub report</body></html>", encoding="utf-8")
        return target

    monkeypatch.setattr("fmriqa_launcher.session.write_run_page", render)
    return render


@pytest.fixture
def warn_during_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `fmriqa.analyze` warn "a stub warning from the analysis" first.

    `session.py` calls `fmriqa.analyze(...)` as a module attribute, so the
    warning has to come from there. Only warnings around `from_nifti`/`analyze`
    are captured, as in `fmriqa.cli.qa`.
    """
    real = fmriqa.analyze

    def analyze(*args: object, **kwargs: object) -> object:
        warnings.warn("a stub warning from the analysis", stacklevel=2)
        return real(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(fmriqa, "analyze", analyze)


@pytest.fixture
def dicom_dir(tmp_path: Path) -> Path:
    """A dummy non-empty directory standing in for a real DICOM source.

    `stub_dcm2niix` never reads it. Only `import_dicom`'s `source.is_dir()`
    guard does.
    """
    directory = tmp_path / "dicom"
    directory.mkdir()
    (directory / "IM001").write_bytes(b"not a real DICOM file")
    return directory
