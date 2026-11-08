"""The browser's path agrees with the launcher's, on a real DICOM study.

dcm2niix converts `dicom-qa` natively with its own names. `name_outputs` and
`analyze_series` then run on those files' bytes, as the page does, and the
result is compared with `fmriqa_launcher.run_session` on the same study.
"""

from pathlib import Path

import pytest

import fmriqa_io
from fmriqa.analysis.record import metric_record
from fmriqa_io.convert.dcm2niix import find_dcm2niix
from fmriqa_launcher import Published, RunRequest, run_session
from fmriqa_web import SeriesReport, analyze_series, name_outputs

STUDY = Path(fmriqa_io.__file__).parents[2] / "tests" / "fixtures" / "dicom-qa"
STEM = "20260909_143012_s002_QA_EPI_ISO"


def test_the_browser_path_matches_the_launcher(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    fmriqa_io.import_dicom(STUDY, raw, binary=find_dcm2niix(), names="dcm2niix")
    files = {path.name: path.read_bytes() for path in sorted(raw.iterdir())}

    filed = name_outputs(files)
    renamed = {filed[name]: data for name, data in files.items()}
    assert sorted(renamed) == [f"{STEM}.json", f"{STEM}.nii.gz"]
    browser = analyze_series(
        renamed[f"{STEM}.nii.gz"], renamed[f"{STEM}.json"], stem=STEM
    )

    launched = run_session(RunRequest(dicom_dir=STUDY, output_dir=tmp_path / "out"))
    (outcome,) = launched.outcomes
    assert isinstance(outcome, Published)
    assert outcome.name == STEM
    native = metric_record(fmriqa_io.load_analysis(outcome.analysis))

    assert isinstance(browser, SeriesReport)
    assert browser.stem == outcome.name
    # Neither warns on this study. What is captured, and what the launcher's
    # texts embed (its staging path), is pinned in test_series.py.
    assert browser.warnings == ()
    assert outcome.warnings == ()
    # `source` is the one place the two differ: the launcher records the path it
    # published to, and the page has no path, so it records the file name.
    assert native["source"] == str(outcome.scan)
    assert browser.record["source"] == f"{STEM}.nii.gz"
    assert {**browser.record, "source": None} == {**native, "source": None}
    assert browser.record["snr"] == pytest.approx(352.88890511929037, rel=1e-9)
