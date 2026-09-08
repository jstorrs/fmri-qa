"""The report document model: tier -> parts composition and its invariants."""

import pytest

import fmriqc_report as report


def test_dashboard_is_a_strict_prefix_of_physics() -> None:
    # The design guarantee: physics renders the dashboard parts, then adds more.
    dashboard = report.parts_for("dashboard")
    physics = report.parts_for("physics")
    assert physics[: len(dashboard)] == dashboard
    assert len(physics) > len(dashboard)


def test_every_tier_composes_to_that_tiers_parts() -> None:
    items = [("a", object()), ("b", object())]  # artifacts are opaque to compose
    for tier in report.TIERS:
        sections = report.compose(items, tier)  # type: ignore[arg-type]
        assert [s.title for s in sections] == ["a", "b"]
        assert all(s.parts == report.parts_for(tier) for s in sections)


def test_parts_for_rejects_an_unknown_tier() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        report.parts_for("commissioning")  # type: ignore[arg-type]


def test_compose_carries_omitted_scans_onto_the_cover_and_appendix(artifact) -> None:
    """A scan left out of the packet is named in it, with the reason.

    Whoever receives the PDF may never see the terminal that printed the error,
    and a packet of three scans reads as complete unless it says otherwise.
    """
    omitted = [("run-2.qa.npz", "not an fmriqc artifact archive")]
    blocks = report.compose(
        [("run-1", artifact)], "dashboard", cover=True, appendix=True, omitted=omitted
    )
    cover, _, appendix = blocks
    assert isinstance(cover, report.Cover) and isinstance(appendix, report.Appendix)
    assert cover.scans == ("run-1",)
    assert cover.omitted == (("run-2.qa.npz", "not an fmriqc artifact archive"),)
    assert appendix.rows[-1] == (
        "run-2.qa.npz",
        "omitted from this packet: not an fmriqc artifact archive",
    )
