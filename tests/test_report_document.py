"""The report document model: tier -> parts composition and its invariants."""

import pytest

from fmriqc import report


def test_dashboard_is_a_strict_prefix_of_physics() -> None:
    # The design guarantee: physics renders the dashboard parts, then adds more.
    dashboard = report.parts_for("dashboard")
    physics = report.parts_for("physics")
    assert physics[: len(dashboard)] == dashboard
    assert len(physics) > len(dashboard)


def test_every_tier_composes_to_that_tiers_parts() -> None:
    items = [("a", object()), ("b", object())]  # results are opaque to compose
    for tier in report.TIERS:
        sections = report.compose(items, tier)  # type: ignore[arg-type]
        assert [s.title for s in sections] == ["a", "b"]
        assert all(s.parts == report.parts_for(tier) for s in sections)


def test_parts_for_rejects_an_unknown_tier() -> None:
    with pytest.raises(ValueError, match="unknown tier"):
        report.parts_for("commissioning")  # type: ignore[arg-type]
