"""Schema round-trip + infrastructure tests for ``StubLLMBridge`` (B2a).

The stub bridge replaces ``LLMBridge`` for 0-cost chain smokes. Two
classes of guarantee must hold:

  1. **Schema round-trip** — every label's synthetic response must be
     accepted by the production schema the real response would feed
     into. If a stub drifts from the schema, a smoke run crashes
     mid-chain on ``ValidationError`` exactly the failure mode the
     stubs exist to prevent.
  2. **Infrastructure** — the stub must (a) skip ``OpenAI()``
     construction so it works without an API key, (b) no-op
     ``_record_usage`` so synthetic calls never appear in
     ``token_usage.jsonl``, (c) raise loudly on unknown labels rather
     than returning a silent sentinel, and (d) keep
     ``set_run_context`` / ``emit_marker`` working unchanged so the
     smoke harness still observes the run-context state machine.

B2a covers 5 of the 14 production labels (tuner.{planner,reflector} +
interpretation.{per_model, synthesis, dedup}). B2b will add 8 more
labels (proposer + implementor + validator) and a corresponding test
block in this file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.llm_bridge import (
    LLMBridge,
    StubLLMBridge,
    _synth_stub_model_name,
)
from agent.schemas.hyperparam_tuning import ExperimentPlan
from agent.schemas.telemetry import LLMBridgeContextError


# ===================================================================
# Schema round-trip tests — one per B2a label
# ===================================================================

def test_tuner_planner_validates_against_experimentplan():
    """``tuner.planner`` synthetic dict must round-trip through ``ExperimentPlan``.

    Uses the LLM-facing aliases (``model_config`` / ``train_config`` /
    ``loss_config``) — Pydantic's ``populate_by_name=True`` is the
    contract that lets the LLM emit either alias or field-name keys.
    """
    bridge = StubLLMBridge()
    raw = bridge._synthesise_json("tuner.planner")

    plan = ExperimentPlan.model_validate(raw)

    # Slug must come from the canonical helper so proposer.proposing +
    # implementor.code in B2b agree on the plugin filename.
    assert plan.model_type == _synth_stub_model_name(0, "a")
    assert plan.is_trial is True
    assert plan.trial_strategy == "snapshot"
    assert 0.01 <= plan.trial_portion <= 1.0
    assert plan.train_validation_align is True


def test_tuner_planner_threads_iter_into_slug():
    """When ``set_run_context`` has bound an iter, the planner's model_type
    must reflect that iter so the cross-stub slug matches the chain's
    current iter directory."""
    bridge = StubLLMBridge()
    bridge._iter = 7
    raw = bridge._synthesise_json("tuner.planner")
    plan = ExperimentPlan.model_validate(raw)
    assert plan.model_type == _synth_stub_model_name(7, "a")
    assert plan.model_type == "stub_arch_007_a"


def test_tuner_reflector_returns_required_memory_keys():
    """The tuner agent reads four keys verbatim from the reflector JSON.

    See ``nodes/ml_hyperparameter_tune_agent.py`` ``reflection.get(...)``
    callsites — missing keys would surface as ``None`` in the saved
    record's ``memory`` block.
    """
    bridge = StubLLMBridge()
    raw = bridge._synthesise_json("tuner.reflector")
    for key in ("conclusion", "key_factor", "discovery", "memory_update"):
        assert key in raw, f"reflector missing required key: {key!r}"
        assert isinstance(raw[key], str)
        assert raw[key]  # non-empty


def test_interpretation_per_model_has_all_8_fields():
    """Per-model synth must populate every field in PER_MODEL_SYSTEM_PROMPT.

    The Knowledge Accumulator's ``model_knowledge_cache`` entry plus
    ``compress_model_summary`` reads from these fields; missing keys
    would degrade the synthesis prompt to ``N/A`` placeholders.
    """
    bridge = StubLLMBridge()
    raw = bridge._synthesise_json("interpretation.per_model")
    expected_fields = {
        "key_findings",
        "bottlenecks",
        "best_config_analysis",
        "score_trend",
        "per_file_analysis",
        "data_sensitivity",
        "efficiency_assessment",
        "strategy_assessment",
    }
    assert expected_fields.issubset(raw.keys()), (
        f"missing keys: {expected_fields - raw.keys()}"
    )
    assert isinstance(raw["key_findings"], list)
    assert isinstance(raw["bottlenecks"], list)
    # The scalar string fields must be non-empty so downstream prompt
    # rendering does not fall back to "N/A".
    for f in (
        "best_config_analysis", "score_trend", "per_file_analysis",
        "data_sensitivity", "efficiency_assessment", "strategy_assessment",
    ):
        assert isinstance(raw[f], str) and raw[f], f"empty scalar field: {f!r}"


def test_interpretation_synthesis_has_callsite_keys():
    """Cross-model synthesis: callsite reads ``key_findings`` /
    ``bottlenecks`` / ``take_home_message`` (line 953-955 in
    ``result_interpretation_agent.py``). All three must be present."""
    bridge = StubLLMBridge()
    raw = bridge._synthesise_json("interpretation.synthesis")
    assert isinstance(raw.get("key_findings"), list)
    assert isinstance(raw.get("bottlenecks"), list)
    assert isinstance(raw.get("take_home_message"), str)
    assert raw["take_home_message"]  # non-empty


def test_interpretation_dedup_returns_false_default():
    """Dedup synth must return a non-duplicate verdict so the vocabulary
    pass keeps every newly promoted term. A spurious ``True`` would cause
    silent merges that lose vocabulary diversity in the chain."""
    bridge = StubLLMBridge()
    raw = bridge._synthesise_json("interpretation.dedup")
    assert raw["is_duplicate"] is False
    assert raw["duplicate_of"] is None
    assert isinstance(raw["rationale"], str) and raw["rationale"]


# ===================================================================
# Entry-point routing tests — confirm parent methods land in synth dispatch
# ===================================================================

def test_plan_method_routes_to_synthesiser():
    """The inherited ``plan()`` calls ``self.generate(label="tuner.planner")``
    which calls ``self._chat_json(...)``. The stub's ``_chat_json``
    override must dispatch to ``_synth_tuner_planner`` and return an
    ``ExperimentPlan``-validatable dict."""
    bridge = StubLLMBridge()
    raw = bridge.plan(memory_history=[])
    plan = ExperimentPlan.model_validate(raw)
    assert plan.model_type == _synth_stub_model_name(0, "a")


def test_reflect_method_routes_to_synthesiser():
    """The inherited ``reflect()`` calls ``self._chat_json(label=
    "tuner.reflector")`` directly. The stub's override must dispatch."""
    bridge = StubLLMBridge()
    raw = bridge.reflect("exp_001", "stub hypothesis", {"final_loss": 0.5})
    assert raw["conclusion"]
    assert raw["memory_update"]


def test_generate_with_known_label_routes_to_synthesiser():
    """``generate(label="interpretation.dedup")`` must dispatch to dedup synth."""
    bridge = StubLLMBridge()
    raw = bridge.generate(
        "system", "user", label="interpretation.dedup",
    )
    assert raw["is_duplicate"] is False


# ===================================================================
# Infrastructure tests — must hold for every B2a + B2b label
# ===================================================================

def test_does_not_construct_openai_client():
    """The stub must work with no API key and no network. Both client
    attributes must be ``None`` so any inherited code that grabs
    ``self.client`` fails fast (NoneType) rather than silently masking
    a bug or hitting a real endpoint."""
    bridge = StubLLMBridge()
    assert bridge.client is None
    assert bridge.reflect_client is None
    assert bridge.provider == "stub"
    assert bridge.reflect_provider == "stub"


def test_record_usage_is_no_op():
    """Synthetic calls must never write rows to ``token_usage.jsonl``.

    Defence-in-depth: the synth paths above don't call ``_record_usage``,
    but if a future override or inherited helper reaches the writer it
    must short-circuit. Calling with a bound run-context proves the
    no-op fires before any I/O attempt.
    """
    bridge = StubLLMBridge()
    # No bind needed: parent's _record_usage already short-circuits when
    # _token_usage_path is None. We still want to confirm the OVERRIDE
    # itself returns silently regardless of arguments — pass a path-like
    # state to ensure we are not just inheriting parent's no-op branch.
    bridge._token_usage_path = Path("/tmp/should_never_be_written")
    bridge._run_id = "stub_run"
    bridge._run_name = "stub_run"
    bridge._iter = 0
    bridge._record_usage(
        response=None, label="any.label",
        system_prompt="x", user_prompt="y",
        model_name="m", provider="p",
    )
    assert not bridge._token_usage_path.exists(), (
        "stub bridge wrote a row to token_usage.jsonl — defensive override "
        "of _record_usage failed"
    )


def test_unknown_json_label_raises_not_implemented():
    """Drift detection: an unregistered label must not silently return."""
    bridge = StubLLMBridge()
    with pytest.raises(NotImplementedError) as excinfo:
        bridge._synthesise_json("nonexistent.label")
    assert "nonexistent.label" in str(excinfo.value)
    # Error message must list the known labels so the operator can spot
    # typos in the calling code.
    for known in ("tuner.planner", "interpretation.synthesis"):
        assert known in str(excinfo.value)


def test_unknown_text_label_raises_not_implemented():
    """B2a registers no text labels; any text label must raise.

    B2b will register ``proposer.legacy_reasoning`` and
    ``implementor.reasoning``; this test will tighten in B2b to check
    those are present.
    """
    bridge = StubLLMBridge()
    with pytest.raises(NotImplementedError):
        bridge._synthesise_text("proposer.legacy_reasoning")


def test_tool_call_raises_not_implemented():
    """No production label routes through ``tool_call`` today. The stub
    must refuse loudly so a future site that adds one cannot silently
    fall through to a sentinel response."""
    bridge = StubLLMBridge()
    with pytest.raises(NotImplementedError) as excinfo:
        bridge.tool_call(
            "system", "user", tools=[],
            label="validator.code_review",
        )
    assert "tool_call" in str(excinfo.value)


def test_set_run_context_works_after_init(tmp_path: Path):
    """``set_run_context`` is inherited; the stub must support it so the
    smoke harness can bind a workspace + iter exactly as a real run."""
    bridge = StubLLMBridge()
    bridge.set_run_context(
        workspace=tmp_path, iter=0,
        run_name="stub_smoke", run_id="stub_smoke-x-1",
    )
    assert bridge._iter == 0
    assert bridge._run_id == "stub_smoke-x-1"
    assert bridge._token_usage_path == tmp_path / "token_usage.jsonl"


def test_emit_marker_still_writes(tmp_path: Path):
    """``emit_marker`` is intentionally inherited (not overridden) so the
    Stability-Filter skip rows still flow into ``token_usage.jsonl`` in
    stub-mode runs. Without this the smoke harness cannot count skips.
    """
    bridge = StubLLMBridge()
    bridge.set_run_context(
        workspace=tmp_path, iter=0,
        run_name="stub_smoke", run_id="stub_smoke-y-1",
    )
    bridge.emit_marker(
        label="interpretation.per_model_skipped",
        extra={"reason": "stable", "model_type": "stub_arch"},
    )
    log = tmp_path / "token_usage.jsonl"
    assert log.exists()
    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["label"] == "interpretation.per_model_skipped"
    assert rows[0]["tokens"]["prompt"] is None  # marker has zeroed token counts


def test_is_subclass_of_llm_bridge():
    """Wiring contract: ``isinstance(stub, LLMBridge)`` must hold so
    callers that type-check (``isinstance(bridge, LLMBridge)``) treat
    the stub as a drop-in replacement."""
    bridge = StubLLMBridge()
    assert isinstance(bridge, LLMBridge)
