# tests/unit/agent/ml_model_proposal_agent/test_proposal_helpers.py
"""
Unit tests for proposal helper functions.

Tests resolve_exploration_mode — the exploration/exploitation resolver —
including the vocabulary stagnation centrifugal force (Concern #1).
"""

import pytest

from agent.schemas.proposal import ReasoningPipelineConfig, ResearchPolicy
from nodes.proposal_helpers import resolve_exploration_mode

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
            model_types=[f"m{i}" for i in range(10)],  # would normally trigger exploit
            vocab_diversity_ratio=0.05,  # below default threshold 0.1
        )
        pipeline = _pipeline(vocab_stagnation_threshold=0.1)
        assert resolve_exploration_mode(interp, pipeline) == "explore"

    def test_healthy_vocab_does_not_override(self):
        """Ratio above threshold → stagnation check passes, evidence depth decides."""
        interp = _interp(
            model_types=[f"m{i}" for i in range(10)],
            vocab_diversity_ratio=0.3,  # healthy — above threshold
        )
        pipeline = _pipeline(vocab_stagnation_threshold=0.1)
        assert resolve_exploration_mode(interp, pipeline) == "exploit"

    def test_ratio_at_threshold_boundary(self):
        """Ratio exactly at threshold → NOT stagnating (stagnation requires < threshold)."""
        interp = _interp(
            model_types=[f"m{i}" for i in range(10)],
            vocab_diversity_ratio=0.1,  # exactly at default threshold
        )
        pipeline = _pipeline(vocab_stagnation_threshold=0.1)
        # 0.1 is not < 0.1 → no stagnation trigger → exploit (evidence depth)
        assert resolve_exploration_mode(interp, pipeline) == "exploit"

    def test_stagnation_checked_before_evidence_depth(self):
        """Stagnation is Priority 1 — it fires even when evidence depth would say explore."""
        interp = _interp(
            model_types=["punet"],  # < 5 proposed → evidence depth says explore
            vocab_diversity_ratio=0.05,  # < threshold → stagnation also says explore
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
            vocab_diversity_ratio=0.25,  # above default (0.1) but below custom (0.3)
        )
        pipeline = _pipeline(vocab_stagnation_threshold=0.3)
        assert resolve_exploration_mode(interp, pipeline) == "explore"


# ---------------------------------------------------------------------------
# C6.2-C2 — Proposer stage-output management helpers (Rev 8.6)
# ---------------------------------------------------------------------------

import copy
import json

from nodes.proposal_helpers import (
    _iter_index_from_source,
    apply_string_backstop,
    clamp_comparative_analysis,
    safe_stage_string_truncator,
)


def _entry(
    model_type: str,
    source: str,
    best_score: float,
    *,
    key_mechanism: str = "kx",
    lesson: str = "lx",
) -> dict:
    """Build a minimal ModelComparison-shaped dict for clamp tests."""
    return {
        "model_type": model_type,
        "source": source,
        "best_score": best_score,
        "key_mechanism": key_mechanism,
        "strengths": [],
        "weaknesses": [],
        "lesson_for_next_proposal": lesson,
    }


class TestIterIndexFromSource:
    """The private regex parser feeding the recency arm of the hybrid clamp."""

    def test_seed_maps_to_zero(self):
        assert _iter_index_from_source("seed") == 0

    def test_proposed_iter_n_extracts_n(self):
        assert _iter_index_from_source("proposed_iter_7") == 7

    def test_proposed_iter_large_n(self):
        assert _iter_index_from_source("proposed_iter_123") == 123

    def test_bare_proposed_falls_back(self):
        # Legacy server-side _guess_source returns just "proposed".
        assert _iter_index_from_source("proposed") == -1

    def test_empty_string_falls_back(self):
        assert _iter_index_from_source("") == -1

    def test_none_falls_back(self):
        assert _iter_index_from_source(None) == -1

    def test_non_string_falls_back(self):
        assert _iter_index_from_source(42) == -1
        assert _iter_index_from_source([]) == -1

    def test_malformed_iter_suffix_falls_back(self):
        # Non-digit suffix doesn't match the strict pattern.
        assert _iter_index_from_source("proposed_iter_abc") == -1
        assert _iter_index_from_source("proposed_iter_5x") == -1

    def test_prefix_only_falls_back(self):
        assert _iter_index_from_source("Xproposed_iter_5") == -1


class TestClampComparativeAnalysis:
    """The 3-best + 2-recent hybrid clamp on DiscoveryMemo.comparative_analysis."""

    def test_no_op_when_under_cap(self):
        entries = [
            _entry("a", "proposed_iter_1", 0.5),
            _entry("b", "proposed_iter_2", 0.6),
        ]
        out = clamp_comparative_analysis(entries, top_k=5)
        assert len(out) == 2
        assert [e["model_type"] for e in out] == ["a", "b"]

    def test_no_op_exact_cap(self):
        entries = [_entry(f"m{i}", f"proposed_iter_{i}", 0.1 * i) for i in range(5)]
        out = clamp_comparative_analysis(entries, top_k=5)
        assert len(out) == 5

    def test_iter13_envelope_ratio_3_best_plus_2_recent(self):
        """13 entries -> 5, with the 3 best-score + 2 most-recent present.

        Construct entries where best_score and recency are *anti-correlated*
        so the 3-best and 2-recent sets are disjoint and the hybrid is
        exercised end-to-end.
        """
        entries = []
        for i in range(13):
            # Older iter -> higher best_score. So top-3-by-score = iters 0,1,2,
            # top-2-by-recency = iters 12,11.
            entries.append(_entry(f"m{i:02d}", f"proposed_iter_{i}", 1.0 - i * 0.01))
        out = clamp_comparative_analysis(entries, top_k=5)
        out_mts = [e["model_type"] for e in out]
        assert len(out) == 5
        # Top-3-by-score (iters 0,1,2)
        for expected in ("m00", "m01", "m02"):
            assert expected in out_mts
        # Top-2-by-recency from the remainder (iters 12,11)
        for expected in ("m12", "m11"):
            assert expected in out_mts

    def test_truncate_when_top_k_below_five(self):
        """top_k=3 -> the 3 best-score winners survive (truncate path)."""
        entries = []
        for i in range(8):
            entries.append(_entry(f"m{i}", f"proposed_iter_{i}", 1.0 - i * 0.01))
        out = clamp_comparative_analysis(entries, top_k=3)
        assert len(out) == 3
        # m0/m1/m2 have the top best_scores.
        assert {e["model_type"] for e in out} == {"m0", "m1", "m2"}

    def test_backfill_when_top_k_above_five(self):
        """top_k=10 -> draws 3 best + 2 recent + 5 backfilled by recency."""
        entries = []
        for i in range(13):
            entries.append(_entry(f"m{i:02d}", f"proposed_iter_{i}", 1.0 - i * 0.01))
        out = clamp_comparative_analysis(entries, top_k=10)
        assert len(out) == 10
        out_mts = {e["model_type"] for e in out}
        # 3 best-score (m00/m01/m02) + 2 recent (m12/m11) all present.
        assert {"m00", "m01", "m02", "m12", "m11"}.issubset(out_mts)

    def test_model_type_dedup_best_score_wins(self):
        """If two entries collide on model_type, the best_score winner stays."""
        entries = [
            _entry("alpha", "seed", 0.9),
            _entry("beta", "proposed_iter_1", 0.5),
            _entry("alpha", "proposed_iter_2", 0.4),  # dup model_type, lower score
            _entry("gamma", "proposed_iter_3", 0.6),
            _entry("delta", "proposed_iter_4", 0.7),
            _entry("epsilon", "proposed_iter_5", 0.3),
        ]
        out = clamp_comparative_analysis(entries, top_k=5)
        assert len(out) == 5
        # Exactly one 'alpha' entry, and it's the higher-score one.
        alpha_entries = [e for e in out if e["model_type"] == "alpha"]
        assert len(alpha_entries) == 1
        assert alpha_entries[0]["best_score"] == 0.9

    def test_seed_source_treated_as_iter_zero(self):
        """seed entries get iter=0, so they're never 'recent' against any proposed_iter_N>0."""
        entries = [
            _entry("seed_a", "seed", 0.1),
            _entry("seed_b", "seed", 0.2),
        ] + [_entry(f"p{i}", f"proposed_iter_{i}", 0.05) for i in range(1, 10)]
        out = clamp_comparative_analysis(entries, top_k=5)
        out_mts = [e["model_type"] for e in out]
        # Recency draws come from p9, p8 (highest iter indices), not from seeds.
        assert "p9" in out_mts
        assert "p8" in out_mts

    def test_unparseable_source_falls_to_end(self):
        """Entries with source='proposed' (no iter) get iter=-1 and lose recency draws."""
        entries = [
            _entry("good", "proposed_iter_5", 0.1),
            _entry("bad1", "proposed", 0.05),
            _entry("bad2", "proposed", 0.04),
            _entry("good2", "proposed_iter_4", 0.03),
            _entry("good3", "proposed_iter_3", 0.02),
            _entry("good4", "proposed_iter_2", 0.01),
            _entry("good5", "proposed_iter_1", 0.001),
        ]
        out = clamp_comparative_analysis(entries, top_k=5)
        out_mts = [e["model_type"] for e in out]
        # 'good' (iter=5) is the most recent and must survive the recency draw.
        assert "good" in out_mts

    def test_input_not_mutated(self):
        """Input list is not modified — caller's data is safe."""
        entries = [_entry(f"m{i}", f"proposed_iter_{i}", float(i)) for i in range(10)]
        snapshot = copy.deepcopy(entries)
        _ = clamp_comparative_analysis(entries, top_k=3)
        assert entries == snapshot

    def test_independent_top_k_alters_density(self):
        """Knob sweep: top_k ∈ {2,5,10} produces the expected output sizes."""
        entries = [_entry(f"m{i:02d}", f"proposed_iter_{i}", 1.0 - i * 0.01) for i in range(13)]
        for k in (2, 3, 5, 7, 10):
            out = clamp_comparative_analysis(entries, top_k=k)
            assert len(out) == k, f"top_k={k} expected {k} entries, got {len(out)}"

    def test_missing_best_score_treated_as_negative_infinity(self):
        """An entry missing best_score doesn't crash the sort — it falls last."""
        entries = [_entry(f"m{i}", f"proposed_iter_{i}", float(i)) for i in range(4)] + [
            {"model_type": "noscore", "source": "proposed_iter_99"},  # no best_score
            _entry("filler", "seed", 0.5),
        ]
        out = clamp_comparative_analysis(entries, top_k=5)
        # No exception, output is well-formed and capped at 5.
        assert len(out) == 5


class TestSafeStageStringTruncator:
    """The pure middle-truncator primitive."""

    @pytest.mark.parametrize(
        "s",
        [
            pytest.param("hello world", id="under_cap_short_string"),
            pytest.param("x" * 4000, id="exact_cap_long_string"),
        ],
    )
    def test_passthrough_at_or_under_cap(self, s):
        """Strings at or below max_chars are returned unchanged. Replaces
        two flat tests (under_cap_passes_through, exact_cap_passes_through)."""
        out = safe_stage_string_truncator(s, max_chars=4000)
        assert out == s

    def test_over_cap_middle_truncated(self):
        s = "a" * 6000
        out = safe_stage_string_truncator(s, max_chars=4000)
        assert len(out) <= 4000
        # Marker fingerprint present in the middle of the result.
        assert " chars elided ...]" in out
        # Head + tail are both literal 'a'.
        assert out.startswith("a")
        assert out.endswith("a")

    def test_idempotence_already_marked_string(self):
        """Applying the truncator twice doesn't re-truncate or compound markers."""
        s = "a" * 6000
        once = safe_stage_string_truncator(s, max_chars=4000)
        twice = safe_stage_string_truncator(once, max_chars=4000)
        assert once == twice

    @pytest.mark.parametrize(
        "max_chars, expected",
        [
            pytest.param(39, "raises", id="below_floor_39_raises"),
            pytest.param(0, "raises", id="zero_raises"),
            pytest.param(40, "accepts", id="at_floor_40_accepts"),
        ],
    )
    def test_floor_validation(self, max_chars, expected):
        """Floor contract: max_chars < 40 raises ValueError; max_chars == 40
        is the lowest legal value. Replaces three flat tests
        (value_error_below_floor, value_error_zero, at_floor_works)."""
        s = "a" * 200
        if expected == "raises":
            with pytest.raises(ValueError):
                safe_stage_string_truncator(s, max_chars=max_chars)
        else:
            out = safe_stage_string_truncator(s, max_chars=max_chars)
            assert len(out) <= max_chars

    def test_independent_max_chars_shifts_trigger_point(self):
        """Knob sweep: same input, different max_chars -> different output sizes."""
        s = "x" * 5000
        outputs = {k: safe_stage_string_truncator(s, max_chars=k) for k in (500, 1000, 2000, 4000)}
        for k, out in outputs.items():
            assert len(out) <= k, f"max_chars={k} produced len={len(out)}"
        # Strictly monotonic non-decreasing in cap.
        assert len(outputs[500]) <= len(outputs[1000]) <= len(outputs[2000]) <= len(outputs[4000])


class TestApplyStringBackstop:
    """The recursive walker built on top of safe_stage_string_truncator."""

    @pytest.mark.parametrize(
        "payload",
        [
            pytest.param(
                {"a": "short", "b": [1, 2, 3], "c": {"d": "also short"}},
                id="all_short_strings",
            ),
            pytest.param(
                {
                    "int": 42,
                    "float": 3.14,
                    "bool": True,
                    "none": None,
                    "list": [1, 2.0, False, None],
                },
                id="non_string_scalars",
            ),
            pytest.param({}, id="empty_dict"),
            pytest.param([], id="empty_list"),
        ],
    )
    def test_passthrough_when_nothing_to_truncate(self, payload):
        """Walker returns payload unchanged when no string exceeds max_chars.
        Replaces four flat tests (passthrough_when_all_short,
        non_string_scalars_passthrough, empty_dict_passthrough,
        empty_list_passthrough)."""
        out = apply_string_backstop(payload, max_chars=4000)
        assert out == payload

    def test_nested_dict_strings_get_truncated(self):
        payload = {"outer": {"inner": "y" * 6000}}
        out = apply_string_backstop(payload, max_chars=4000)
        assert isinstance(out, dict)
        assert "outer" in out and "inner" in out["outer"]
        assert len(out["outer"]["inner"]) <= 4000
        assert " chars elided ...]" in out["outer"]["inner"]

    def test_list_of_strings_truncated_elementwise(self):
        payload = ["short", "z" * 6000, "also short"]
        out = apply_string_backstop(payload, max_chars=4000)
        assert len(out) == 3
        assert out[0] == "short"
        assert len(out[1]) <= 4000
        assert out[2] == "also short"

    def test_structural_invariance_keys_and_lengths_preserved(self):
        """Walker preserves dict keys and list lengths regardless of truncation."""
        payload = {
            "k1": "a" * 100,
            "k2": "b" * 10000,
            "k3": [{"deep": "c" * 8000}, "shallow", 7],
        }
        out = apply_string_backstop(payload, max_chars=500)
        # Same keys
        assert set(out.keys()) == set(payload.keys())
        # Same list length
        assert len(out["k3"]) == len(payload["k3"])
        # Same nested keys
        assert set(out["k3"][0].keys()) == set(payload["k3"][0].keys())

    def test_input_not_mutated(self):
        payload = {"k": "v" * 8000, "list": ["a" * 8000, "ok"]}
        snapshot = copy.deepcopy(payload)
        _ = apply_string_backstop(payload, max_chars=500)
        assert payload == snapshot

    def test_independent_max_chars_does_not_alter_json_structure(self):
        """Knob sweep: max_chars shifts elision-trigger point; JSON shape stays."""
        payload = {
            "narrative": "w" * 5000,
            "tags": ["alpha", "beta" * 2000, "gamma"],
            "score": 0.42,
        }
        for cap in (500, 1000, 4000):
            out = apply_string_backstop(payload, max_chars=cap)
            # Structural invariants
            assert set(out.keys()) == {"narrative", "tags", "score"}
            assert isinstance(out["tags"], list)
            assert len(out["tags"]) == 3
            assert out["score"] == 0.42
            # Roundtrips through JSON unchanged in shape
            shape = json.loads(json.dumps(out))
            assert set(shape.keys()) == {"narrative", "tags", "score"}

    def test_long_string_at_floor_cap(self):
        out = apply_string_backstop({"big": "q" * 1000}, max_chars=40)
        assert len(out["big"]) <= 40
