# tests/unit/agent/ml_model_proposal_agent/test_proposal_helpers.py
"""
Unit tests for proposal helper functions.

Tests resolve_exploration_mode — the exploration/exploitation resolver —
including the vocabulary stagnation centrifugal force (Concern #1).
"""

import pytest
from nodes.proposal_helpers import resolve_exploration_mode
from agent.schemas.proposal import ReasoningPipelineConfig, ResearchPolicy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pipeline(mode="auto", vocab_stagnation_threshold=0.1):
    policy = ResearchPolicy(vocab_stagnation_threshold=vocab_stagnation_threshold)
    return ReasoningPipelineConfig(exploration_mode=mode, policy=policy)


def _interp(model_types=None, agent_proposed_count=0, vocab_diversity_ratio=None):
    """Build a minimal serialised InterpretationOutput dict for testing."""
    if model_types is None:
        # Seed models only (no agent-proposed models)
        model_types = ["punet", "wavenet"][:agent_proposed_count] + [
            f"proposed_{i}" for i in range(agent_proposed_count)
        ]
    result = {"model_types": model_types}
    if vocab_diversity_ratio is not None:
        result["vocab_diversity_ratio"] = vocab_diversity_ratio
    return result


# ---------------------------------------------------------------------------
# Manual override (exploration_mode != "auto")
# ---------------------------------------------------------------------------

class TestManualOverride:

    def test_explicit_explore_bypasses_all_signals(self):
        interp = _interp(vocab_diversity_ratio=0.0)
        pipeline = _pipeline(mode="explore")
        assert resolve_exploration_mode(interp, pipeline) == "explore"

    def test_explicit_exploit_bypasses_all_signals(self):
        interp = _interp(model_types=[f"m{i}" for i in range(10)])
        pipeline = _pipeline(mode="exploit")
        assert resolve_exploration_mode(interp, pipeline) == "exploit"


# ---------------------------------------------------------------------------
# Evidence-depth signal
# ---------------------------------------------------------------------------

class TestEvidenceDepth:

    def test_fewer_than_5_proposed_models_triggers_explore(self):
        # 3 built-in + 2 proposed = 2 agent-proposed → explore
        interp = _interp(model_types=["punet", "wavenet", "fcnet", "model_a", "model_b"])
        pipeline = _pipeline()
        assert resolve_exploration_mode(interp, pipeline) == "explore"

    def test_exactly_5_proposed_models_triggers_exploit(self):
        interp = _interp(model_types=[f"proposed_{i}" for i in range(5)])
        pipeline = _pipeline()
        assert resolve_exploration_mode(interp, pipeline) == "exploit"

    def test_many_proposed_models_triggers_exploit(self):
        interp = _interp(model_types=[f"m{i}" for i in range(10)])
        pipeline = _pipeline()
        assert resolve_exploration_mode(interp, pipeline) == "exploit"


# ---------------------------------------------------------------------------
# Vocabulary stagnation signal (Concern #1 centrifugal force)
# ---------------------------------------------------------------------------

class TestVocabStagnation:

    def test_stagnating_vocab_forces_explore(self):
        """Diversity ratio below threshold → explore, even with many proposed models."""
        interp = _interp(
            model_types=[f"m{i}" for i in range(10)],   # would normally trigger exploit
            vocab_diversity_ratio=0.05,                  # below default threshold 0.1
        )
        pipeline = _pipeline(vocab_stagnation_threshold=0.1)
        assert resolve_exploration_mode(interp, pipeline) == "explore"

    def test_healthy_vocab_does_not_override(self):
        """Ratio above threshold → stagnation check passes, evidence depth decides."""
        interp = _interp(
            model_types=[f"m{i}" for i in range(10)],
            vocab_diversity_ratio=0.3,   # healthy — above threshold
        )
        pipeline = _pipeline(vocab_stagnation_threshold=0.1)
        assert resolve_exploration_mode(interp, pipeline) == "exploit"

    def test_ratio_at_threshold_boundary(self):
        """Ratio exactly at threshold → NOT stagnating (stagnation requires < threshold)."""
        interp = _interp(
            model_types=[f"m{i}" for i in range(10)],
            vocab_diversity_ratio=0.1,   # exactly at default threshold
        )
        pipeline = _pipeline(vocab_stagnation_threshold=0.1)
        # 0.1 is not < 0.1 → no stagnation trigger → exploit (evidence depth)
        assert resolve_exploration_mode(interp, pipeline) == "exploit"

    def test_stagnation_checked_before_evidence_depth(self):
        """Stagnation is Priority 1 — it fires even when evidence depth would say explore."""
        interp = _interp(
            model_types=["punet"],           # < 5 proposed → evidence depth says explore
            vocab_diversity_ratio=0.05,      # < threshold → stagnation also says explore
        )
        # Both signals agree here, but the stagnation check runs first
        pipeline = _pipeline(vocab_stagnation_threshold=0.1)
        assert resolve_exploration_mode(interp, pipeline) == "explore"

    def test_missing_diversity_ratio_falls_back_to_evidence_depth(self):
        """If vocab_diversity_ratio is absent (legacy / first iteration), skip stagnation check."""
        interp = {"model_types": [f"m{i}" for i in range(10)]}  # no vocab_diversity_ratio
        pipeline = _pipeline(vocab_stagnation_threshold=0.1)
        assert resolve_exploration_mode(interp, pipeline) == "exploit"

    def test_custom_threshold(self):
        """Policy threshold is configurable."""
        interp = _interp(
            model_types=[f"m{i}" for i in range(10)],
            vocab_diversity_ratio=0.25,   # above default (0.1) but below custom (0.3)
        )
        pipeline = _pipeline(vocab_stagnation_threshold=0.3)
        assert resolve_exploration_mode(interp, pipeline) == "explore"
