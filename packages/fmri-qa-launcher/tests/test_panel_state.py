"""The panel's pure presentation decisions.

Covers `bar_state`, `final_bar`, `summarize`, `stopping_message` and `exit_code`.
"""

from pathlib import Path

from fmriqa_launcher.outcome import Failed, Published, Refused, RunResult
from fmriqa_launcher.panel_state import (
    CRASHED_BAR,
    Determinate,
    Indeterminate,
    bar_state,
    exit_code,
    final_bar,
    stopping_message,
    summarize,
)
from fmriqa_launcher.progress import Progress, Stage
from fmriqa_launcher.worker import Crashed, Finished

# -- bar_state ------------------------------------------------------------


def test_import_is_indeterminate_regardless_of_series() -> None:
    assert bar_state(Progress(Stage.IMPORT)) == Indeterminate()


def test_first_series_analyze_starts_at_zero() -> None:
    state = bar_state(Progress(Stage.ANALYZE, index=1, total=3, series="a"))
    assert state == Determinate(value=0, maximum=9)


def test_first_series_report_is_one_tick_in() -> None:
    state = bar_state(Progress(Stage.REPORT, index=1, total=3, series="a"))
    assert state == Determinate(value=1, maximum=9)


def test_first_series_publish_is_two_ticks_in() -> None:
    state = bar_state(Progress(Stage.PUBLISH, index=1, total=3, series="a"))
    assert state == Determinate(value=2, maximum=9)


def test_middle_series_analyze_is_credited_for_the_ones_before_it() -> None:
    state = bar_state(Progress(Stage.ANALYZE, index=2, total=3, series="b"))
    assert state == Determinate(value=3, maximum=9)


def test_last_series_publish_reaches_the_maximum() -> None:
    state = bar_state(Progress(Stage.PUBLISH, index=3, total=3, series="c"))
    assert state == Determinate(value=9, maximum=9)


def test_only_the_last_series_publish_reaches_the_maximum() -> None:
    """A middle series' publish stays short of the maximum; more work remains."""
    state = bar_state(Progress(Stage.PUBLISH, index=2, total=3, series="b"))
    assert state != Determinate(value=9, maximum=9)
    assert state.maximum == 9
    assert state.value < state.maximum


def test_a_single_series_run_reaches_the_maximum_only_at_publish() -> None:
    assert bar_state(
        Progress(Stage.ANALYZE, index=1, total=1, series="a")
    ) == Determinate(value=0, maximum=3)
    assert bar_state(
        Progress(Stage.REPORT, index=1, total=1, series="a")
    ) == Determinate(value=1, maximum=3)
    assert bar_state(
        Progress(Stage.PUBLISH, index=1, total=1, series="a")
    ) == Determinate(value=3, maximum=3)


# -- summarize --------------------------------------------------------------


def _published(
    name: str, output_dir: Path, warnings: tuple[str, ...] = ()
) -> Published:
    return Published(
        name=name,
        directory=output_dir / name,
        scan=output_dir / name / f"{name}.nii.gz",
        sidecar=None,
        artifact=output_dir / name / f"{name}.qa.nc",
        report=output_dir / name / f"{name}.html",
        warnings=warnings,
    )


def test_all_published_gives_a_clean_headline_and_no_offer_to_open_is_withheld(
    tmp_path: Path,
) -> None:
    result = RunResult(tmp_path, (_published("a", tmp_path), _published("b", tmp_path)))
    summary = summarize(result)
    assert summary.headline == "2 of 2 series published"
    assert summary.details == ("Published a", "Published b")
    assert summary.offer_open is True


def test_mixed_outcomes_with_warnings_list_every_detail_line(tmp_path: Path) -> None:
    result = RunResult(
        tmp_path,
        (
            _published("a", tmp_path, warnings=("a spatial unit was missing",)),
            Refused(name="b", existing=tmp_path / "b"),
            Failed(
                name="c",
                reason="too few volumes",
                warnings=("a motion fit did not converge",),
            ),
        ),
    )
    summary = summarize(result)
    assert summary.headline == "1 of 3 series published"
    assert summary.details == (
        "Published a",
        "Warning (a): a spatial unit was missing",
        f"Skipped b: results already exist in {tmp_path / 'b'}",
        "Failed c: too few volumes",
        "Warning (c): a motion fit did not converge",
    )
    assert summary.offer_open is True


def test_cancelled_run_reports_stopped_early_with_no_denominator(
    tmp_path: Path,
) -> None:
    """A run cancelled after 2 of 10 series must not claim "2 of 2".

    `RunResult.outcomes` holds only the series a cancelled run reached
    (`run_session` breaks the loop without padding), so the headline must not
    imply those two were the whole run.
    """
    result = RunResult(
        tmp_path, (_published("a", tmp_path), _published("b", tmp_path)), cancelled=True
    )
    summary = summarize(result)
    assert summary.headline == "Stopped early: 2 series published"
    assert "10" not in summary.headline
    assert "of" not in summary.headline
    assert summary.offer_open is True


def test_cancelled_run_with_nothing_published_yet(tmp_path: Path) -> None:
    result = RunResult(tmp_path, (), cancelled=True)
    summary = summarize(result)
    assert summary.headline == "Stopped early before anything was published"
    assert summary.offer_open is False


def test_nothing_published_offers_no_open(tmp_path: Path) -> None:
    result = RunResult(tmp_path, (Refused(name="a", existing=tmp_path / "a"),))
    summary = summarize(result)
    assert summary.headline == "All 1 series already have results in the output folder"
    assert summary.offer_open is False


def test_all_refused_across_several_series_names_the_count(tmp_path: Path) -> None:
    result = RunResult(
        tmp_path,
        (
            Refused(name="a", existing=tmp_path / "a"),
            Refused(name="b", existing=tmp_path / "b"),
        ),
    )
    summary = summarize(result)
    assert summary.headline == "All 2 series already have results in the output folder"


def test_a_mix_of_refused_and_failed_with_nothing_published(tmp_path: Path) -> None:
    """Not every outcome is Refused, so this is not the "all refused" case."""
    result = RunResult(
        tmp_path,
        (
            Refused(name="a", existing=tmp_path / "a"),
            Failed(name="b", reason="too few volumes"),
        ),
    )
    summary = summarize(result)
    assert summary.headline == "Nothing was published"


def test_an_empty_run_reports_nothing_published(tmp_path: Path) -> None:
    result = RunResult(tmp_path, ())
    summary = summarize(result)
    assert summary.headline == "Nothing was published"
    assert summary.details == ()
    assert summary.offer_open is False


# -- final_bar --------------------------------------------------------------


def test_final_bar_is_full_when_everything_published(tmp_path: Path) -> None:
    result = RunResult(tmp_path, (_published("a", tmp_path), _published("b", tmp_path)))
    state = final_bar(result)
    assert state == Determinate(value=2, maximum=2)


def test_final_bar_is_proportional_for_a_mixed_result(tmp_path: Path) -> None:
    result = RunResult(
        tmp_path,
        (
            _published("a", tmp_path),
            Refused(name="b", existing=tmp_path / "b"),
            Failed(name="c", reason="too few volumes"),
        ),
    )
    state = final_bar(result)
    assert state == Determinate(value=1, maximum=3)


def test_final_bar_is_empty_when_nothing_published(tmp_path: Path) -> None:
    result = RunResult(tmp_path, (Refused(name="a", existing=tmp_path / "a"),))
    assert final_bar(result) == Determinate(value=0, maximum=1)


def test_final_bar_is_empty_for_a_run_that_found_no_series_at_all(
    tmp_path: Path,
) -> None:
    result = RunResult(tmp_path, ())
    assert final_bar(result) == Determinate(value=0, maximum=1)


def test_crashed_bar_is_empty() -> None:
    assert Determinate(value=0, maximum=1) == CRASHED_BAR


# -- stopping_message ---------------------------------------------------


def test_stopping_message_with_no_progress_yet_mentions_import() -> None:
    message = stopping_message(None)
    assert "import" in message
    assert "close again" in message


def test_stopping_message_during_import_mentions_import() -> None:
    message = stopping_message(Progress(Stage.IMPORT))
    assert "import" in message
    assert "close again" in message


def test_stopping_message_between_series_mentions_the_current_series() -> None:
    message = stopping_message(Progress(Stage.ANALYZE, index=1, total=3, series="a"))
    assert "current series" in message
    assert "close again" in message


# -- exit_code ----------------------------------------------------------


def test_exit_code_is_zero_for_a_complete_run(tmp_path: Path) -> None:
    result = RunResult(tmp_path, (_published("a", tmp_path),))
    assert exit_code(Finished(result)) == 0


def test_exit_code_is_one_for_an_incomplete_run(tmp_path: Path) -> None:
    result = RunResult(tmp_path, (Refused(name="a", existing=tmp_path / "a"),))
    assert exit_code(Finished(result)) == 1


def test_exit_code_is_one_for_a_crash() -> None:
    assert exit_code(Crashed("boom")) == 1
