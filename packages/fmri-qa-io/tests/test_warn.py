"""A warning core raises on io's behalf still names the caller's line.

Loading an old artifact migrates it, and `fmriqa.warn` reports the migration.
The call passes through `fmriqa_io` on the way, so its frames must be skipped
as well as core's for the warning to land on the line that loaded the file.
"""

import warnings
from pathlib import Path

import fmriqa_io

_V1 = Path(__file__).parent / "fixtures" / "schema_v1.qa.npz"


def test_a_migration_warning_names_the_callers_line() -> None:
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        fmriqa_io.load_artifact(_V1)
    assert record, "loading a v1 artifact should warn that it was migrated"
    assert {w.filename for w in record} == {__file__}
