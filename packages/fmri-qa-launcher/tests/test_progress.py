"""`describe`: one line per stage, and the one thing import must never say."""

from fmriqc_launcher.progress import Progress, Stage, describe


def test_import_mentions_no_series_name_even_if_one_is_set() -> None:
    """Import is one step for the whole directory; a stray `series` is ignored."""
    line = describe(Progress(Stage.IMPORT, series="should-not-appear"))
    assert "should-not-appear" not in line


def test_analyze_names_the_series_and_its_position() -> None:
    line = describe(Progress(Stage.ANALYZE, index=2, total=7, series="scan"))
    assert line == "Analyzing 2 of 7: scan"


def test_report_names_the_series_and_its_position() -> None:
    line = describe(Progress(Stage.REPORT, index=1, total=3, series="scan"))
    assert "1 of 3" in line
    assert "scan" in line


def test_publish_names_the_series_and_its_position() -> None:
    line = describe(Progress(Stage.PUBLISH, index=3, total=3, series="scan"))
    assert "3 of 3" in line
    assert "scan" in line
