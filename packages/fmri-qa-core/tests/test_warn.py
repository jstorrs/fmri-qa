"""A warning names the caller's line, not a line inside the package.

`fmriqa.warn.warn` skips every frame in the package, so the ROI warning must
land on the test's own call through both `run_qa` and `analyze`. fmri-qa-io's
`test_warn.py` checks the same through its loaders.
"""

import warnings

import fmriqa as q
from fmriqa.testing import phantom_scan

_ROI_TOO_BIG = 31  # does not fit the phantom of the 32-voxel `phantom_scan`


def _caught(record: list[warnings.WarningMessage], text: str) -> str:
    """The one recorded warning whose message holds `text`, by filename."""
    matching = [w for w in record if text in str(w.message)]
    assert len(matching) == 1, [str(w.message) for w in record]
    return matching[0].filename


def test_a_warning_names_the_callers_line_through_run_qa() -> None:
    scan = phantom_scan()
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        q.run_qa(scan, q.AnalysisSettings(roi_size=_ROI_TOO_BIG))
    assert _caught(record, "not fully inside the phantom") == __file__


def test_a_warning_names_the_callers_line_through_analyze() -> None:
    scan = phantom_scan()
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        q.analyze(scan, q.AnalysisSettings(roi_size=_ROI_TOO_BIG))
    assert _caught(record, "not fully inside the phantom") == __file__
