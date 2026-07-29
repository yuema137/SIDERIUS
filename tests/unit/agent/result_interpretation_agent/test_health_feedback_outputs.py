"""Deterministic health-feedback OUTPUT fields on InterpretationOutput.

CB3-b suite (``pr3_healthgate_feedback.md`` §3.6/§3.8/§3.10, §7.1).
Pins two invariants:

* the three structured fields are populated deterministically from
  RoundHealth — regardless of the prompt flag (recording-only, flag
  OFF default) and regardless of interpreter LLM success;
* the §3.10 degraded-merge scenario: a NEW fingerprint produced this
  iteration survives an interpreter LLM failure — merged into the
  output history with a current-iteration occurrence bucket, prior
  history intact, LLM commentary empty.
"""

from unittest.mock import patch

from agent.schemas.health_feedback import (
    CollapseFingerprintHistoryEntry,
    FingerprintOccurrence,
)
from agent.schemas.interpretation import InterpretationInput
from nodes.result_interpretation_agent import (
    ResultInterpretationAgent,
    tuning_output_to_model_run_summary,
)
from tests.unit.agent.result_interpretation_agent.test_interpretation_agent import (
    _llm_dispatch,
)
from tests.unit.agent.result_interpretation_agent.test_round_health_summary import (
    _gate_result,
    _output,
    _record,
)

SIGNATURE = "output_diversity_blocking:n_unique_int8_values=1"


def _collapse_summary():
    """One collapse round (fingerprinted) + one healthy gated round."""
    return tuning_output_to_model_run_summary(
        _output(
            _record(
                "wavenet_iter_002_001",
                status="failed_mode_collapse",
                denoising_score=None,
                gate_action="invalidate_round",
                failure_reason="[output_diversity_blocking] unique=1",
                health_gate_results=[_gate_result()],
            ),
            _record("wavenet_iter_002_002", denoising_score=1.1, health_gate_results=[]),
        )
    )


def _prior_history():
    """Same signature seen once at iteration 1 (within a window-3 span)."""
    return {
        "wavenet": [
            CollapseFingerprintHistoryEntry(
                signature=SIGNATURE,
                check_name="output_diversity_blocking",
                metrics={"n_unique_int8_values": 1},
                human_readable="prior collapse",
                occurrences=[
                    FingerprintOccurrence(
                        iteration=1, count=1, source_exp_ids=["wavenet_iter_001_003"]
                    )
                ],
            )
        ]
    }


def _make_input(tmp_path, **overrides):
    base = dict(
        summaries=[_collapse_summary()],
        storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
        collapse_fingerprint_history=_prior_history(),
        iteration=2,
    )
    base.update(overrides)
    return InterpretationInput(**base)


def _healthy_agent():
    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate.side_effect = _llm_dispatch
        a = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        a.bridge = MockBridge.return_value
        return a


def _failing_agent():
    with patch("nodes.result_interpretation_agent.LLMBridge") as MockBridge:
        MockBridge.return_value.generate.side_effect = RuntimeError("LLM unreachable")
        a = ResultInterpretationAgent(provider="gemini", model_id="test-model")
        a.bridge = MockBridge.return_value
        return a


class TestHealthyPath:
    def test_fields_populated_with_flag_off(self, tmp_path):
        """Recording-only provenance: the flag defaults OFF and the fields
        are populated anyway (§3.1 principle 3 / operator Q2)."""
        inp = _make_input(tmp_path)
        assert inp.enable_structured_health_feedback is False
        output = _healthy_agent().run(inp)
        assert output.per_model_round_health_counts == {
            "wavenet": {"valid": 0, "invalid": 1, "unknown": 1}
        }
        [fp] = output.per_model_collapse_fingerprints["wavenet"]
        assert fp.signature == SIGNATURE

    def test_history_merge_aggregates_across_iterations(self, tmp_path):
        output = _healthy_agent().run(_make_input(tmp_path))
        [entry] = output.collapse_fingerprint_history["wavenet"]
        assert entry.signature == SIGNATURE
        # iteration-1 bucket carried, iteration-2 bucket added by the merge.
        assert [(o.iteration, o.count) for o in entry.occurrences] == [(1, 1), (2, 1)]
        assert entry.occurrences[1].source_exp_ids == ["wavenet_iter_002_001"]

    def test_expired_history_is_dropped(self, tmp_path):
        """window=3 at iteration 5 → the iteration-1 bucket expires; only
        the fresh iteration-5 evidence remains."""
        output = _healthy_agent().run(_make_input(tmp_path, iteration=5))
        [entry] = output.collapse_fingerprint_history["wavenet"]
        assert [(o.iteration, o.count) for o in entry.occurrences] == [(5, 1)]

    def test_stats_cache_carries_health_facts(self, tmp_path):
        output = _healthy_agent().run(_make_input(tmp_path))
        stats = output.model_knowledge_cache["wavenet"]["_stats"]
        assert stats["round_health_counts"] == {"valid": 0, "invalid": 1, "unknown": 1}
        assert stats["collapse_fingerprints"][0]["signature"] == SIGNATURE


class TestDegradedMerge:
    """The §3.10 operator scenario, all five conditions."""

    def test_new_fingerprint_survives_llm_failure(self, tmp_path):
        output = _failing_agent().run(_make_input(tmp_path))
        # 1. is_degraded is set.
        assert output.is_degraded is True
        # 2. The NEW fingerprint is merged with a current-iteration bucket.
        [entry] = output.collapse_fingerprint_history["wavenet"]
        assert (2, 1) in [(o.iteration, o.count) for o in entry.occurrences]
        # 3. Prior history remains intact.
        assert (1, 1) in [(o.iteration, o.count) for o in entry.occurrences]
        # 4. LLM commentary stays empty per the degraded contract.
        assert output.key_findings == []
        assert output.bottlenecks == []
        # 5. The per-iteration deterministic aggregates are recorded too.
        assert output.per_model_round_health_counts["wavenet"]["invalid"] == 1
        [fp] = output.per_model_collapse_fingerprints["wavenet"]
        assert fp.signature == SIGNATURE

    def test_degraded_output_equals_healthy_on_health_fields(self, tmp_path):
        """The structured fields are LLM-independent: healthy and degraded
        runs over the same input produce identical values."""
        healthy = _healthy_agent().run(_make_input(tmp_path / "a"))
        degraded = _failing_agent().run(_make_input(tmp_path / "b"))
        assert healthy.per_model_round_health_counts == degraded.per_model_round_health_counts
        assert healthy.per_model_collapse_fingerprints == degraded.per_model_collapse_fingerprints
        assert healthy.collapse_fingerprint_history == degraded.collapse_fingerprint_history


class TestColdStartAndLegacy:
    def test_cold_start_carries_retained_history(self, tmp_path):
        inp = InterpretationInput(
            cold_start=True,
            storage={"backend": "local", "local": {"workspace": str(tmp_path), "run_name": "r1"}},
            collapse_fingerprint_history=_prior_history(),
            iteration=2,
        )
        output = _healthy_agent().run(inp)
        [entry] = output.collapse_fingerprint_history["wavenet"]
        assert [(o.iteration, o.count) for o in entry.occurrences] == [(1, 1)]

    def test_legacy_digest_without_field_reads_as_empty(self, tmp_path):
        """Missing carry-forward (pre-PR3 digest) resolves to empty via the
        schema default — no error, no invented history."""
        inp = _make_input(tmp_path, collapse_fingerprint_history={})
        output = _healthy_agent().run(inp)
        [entry] = output.collapse_fingerprint_history["wavenet"]
        assert [(o.iteration, o.count) for o in entry.occurrences] == [(2, 1)]
