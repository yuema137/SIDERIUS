"""Composed evaluation scope owns scoring even when a reference artifact exists."""

from types import SimpleNamespace

from nodes.ml_hyperparameter_tune_agent.policy import ScoringRoute, resolve_scoring_route


def test_composed_scope_wins_over_the_legacy_anchor_route() -> None:
    """Catches an opaque task scope being sent to a scorer requiring SampleSet."""
    scopes = SimpleNamespace(evaluation=object())

    assert resolve_scoring_route({"anchors": {}}, scopes) is ScoringRoute.TASK_OWNED


def test_uncomposed_anchor_scoring_keeps_its_legacy_route() -> None:
    """Catches removal of the supported in-process anchor compatibility path."""
    assert resolve_scoring_route({"anchors": {}}, None) is ScoringRoute.ANCHOR_NORMALIZED
