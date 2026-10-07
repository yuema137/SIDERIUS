"""Compose JSON preflight evidence with the real tuner and prompt renderers.

The existing tuner harness stubs provider calls, training and storage. Its
preflight response here is produced by a bounded classifier-only child, never
by a model or GPU worker. This exercises the evidence path that independent
schema and prompt unit tests cannot establish.
"""

from __future__ import annotations

import pytest

from agent.prompts import get_planner_user_prompt
from agent.schemas.hyperparam_tuning import ExperimentRecord
from agent.schemas.preflight import StaticPreflightEvidence
from agent.skills.evaluate_vram_skill.evidence import (
    preflight_memory_fields,
    render_static_refusal,
)
from nodes.ml_hyperparameter_tune_agent.feedback import _collect_disallowed_patterns
from tests.unit.agent.evaluate_vram_skill.test_static_preflight_evidence_transport import (
    classified_roundtrip,
    structural_result,
)
from tests.unit.agent.tune_ml_hyperparam_agent.test_physical_rejection_capture import (
    _make_input,
    _setup,
    agent_with_scripted_skill,
)
from workflows.model_exploration import _render_physical_rejection

pytestmark = pytest.mark.usefixtures("synthetic_run_authorities")


def _assert_static_exhaustion_summary(summary: str) -> None:
    assert "static" in summary.lower()
    assert "too heavy" not in summary
    assert "Model too large" not in summary
    assert "Reduce parameter count" not in summary
    assert "reduce model size" not in summary


@pytest.mark.parametrize("kind", ["vram", "compute", "both"])
@pytest.mark.parametrize("diagnostics", [None, "truncated"])
def test_static_refusal_retains_cause_in_tuner_record_and_both_prompts(
    tmp_path, agent_with_scripted_skill, kind, diagnostics
):
    inspection = structural_result(kind)
    if diagnostics is not None:
        inspection["memory_killer"] = "[dropped: exceeded the rich-field budget]"
    _, adapted = classified_roundtrip(tmp_path, inspection)
    agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, [adapted])
    try:
        output = agent.run(
            _make_input(tmp_path, max_rounds=1).model_copy(update={"formal_vram_budget_gb": 5.0})
        )
    finally:
        cleanup()
    assert counter["i"] == 1
    assert len(output.physical_rejections) == 1
    assert output.gate_exhaustion is not None
    _assert_static_exhaustion_summary(output.gate_exhaustion.summary_message)
    rejection = output.physical_rejections[0]
    expected_cap = {
        "vram": "vram",
        "compute": "compute_intensity",
        "both": "vram+compute_intensity",
    }[kind]
    assert rejection.binding_cap == expected_cap
    assert (
        rejection.static_preflight_evidence.model_dump(mode="json")
        == inspection["static_preflight_evidence"]
    )
    assert rejection.estimated_gb == inspection["estimated_gb"]
    assert not rejection.dominant_layer
    assert rejection.dominant_fraction == 0.0

    record = next(item for item in saved if item["status"] == "skipped_oom_risk")
    # Persisted input is still valid under the public record schema.
    typed = ExperimentRecord.model_validate(record)
    assert typed.memory.static_preflight_evidence == rejection.static_preflight_evidence
    assert typed.memory.preflight_outcome == "STATIC_PREFLIGHT_REFUSAL"
    assert "80%" not in typed.memory.conclusion
    planner = get_planner_user_prompt([record], force_model="punet")
    proposer = _render_physical_rejection(rejection, n_rejections=1)
    for prompt in (planner, proposer):
        assert "inference B=3" in prompt
        assert "not a measured GPU peak or CUDA OOM" in prompt
        assert "consumed 0%" not in prompt
    if kind == "compute":
        assert "120 exceeds the rule limit 100" in proposer
        assert "structural estimate" not in proposer


@pytest.mark.parametrize("kind", ["vram", "compute", "both"])
def test_static_refusal_after_success_does_not_claim_model_is_too_large(
    tmp_path, agent_with_scripted_skill, kind
):
    passed_dir = tmp_path / "passed"
    refused_dir = tmp_path / "refused"
    passed_dir.mkdir()
    refused_dir.mkdir()
    _, passed = classified_roundtrip(passed_dir, structural_result("pass"))
    _, refused = classified_roundtrip(refused_dir, structural_result(kind))
    agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, [passed, refused])
    try:
        output = agent.run(
            _make_input(tmp_path, max_rounds=2).model_copy(update={"formal_vram_budget_gb": 5.0})
        )
    finally:
        cleanup()
    assert counter["i"] == 2
    assert [item["status"] for item in saved] == ["success", "skipped_oom_risk"]
    assert output.gate_exhaustion is not None
    _assert_static_exhaustion_summary(output.gate_exhaustion.summary_message)
    assert len(output.physical_rejections) == 1


def test_passing_preflight_evidence_reaches_record_without_replacing_legacy_estimate(
    tmp_path, agent_with_scripted_skill
):
    inspection = structural_result("pass")
    _, adapted = classified_roundtrip(tmp_path, inspection)
    agent, saved, counter, cleanup = _setup(agent_with_scripted_skill, [adapted])
    try:
        output = agent.run(
            _make_input(tmp_path, max_rounds=1).model_copy(update={"formal_vram_budget_gb": 5.0})
        )
    finally:
        cleanup()
    assert counter["i"] == 1
    assert output.physical_rejections == []
    records = [item for item in saved if item.get("memory", {}).get("static_preflight_evidence")]
    assert len(records) == 1, [item["status"] for item in saved]
    record = ExperimentRecord.model_validate(records[0])
    assert (
        record.memory.static_preflight_evidence.model_dump(mode="json")
        == inspection["static_preflight_evidence"]
    )
    assert record.memory.preflight_outcome == "COMPLETED_MEASUREMENT"
    assert record.memory.vram_estimate_gb == 1.25
    assert record.memory.vram_budget_gb == 5.0
    planner = get_planner_user_prompt([records[0]], force_model="punet")
    assert '"version": "static-preflight-v2"' in planner
    assert '"vram_estimate_bytes": 4294967296' in planner


def test_large_static_estimate_cannot_blacklist_an_architectural_class(tmp_path):
    inspection = structural_result("vram")
    inspection["estimated_gb"] = 20.0
    inspection["static_preflight_evidence"]["phases"][0]["vram_estimate_bytes"] = 20 * 1024**3
    inspection["verdict"] = render_static_refusal(
        StaticPreflightEvidence.model_validate(inspection["static_preflight_evidence"])
    )
    _, adapted = classified_roundtrip(tmp_path, inspection)
    record = {
        "status": "skipped_oom_risk",
        "model_type": "synthetic_dense_attention",
        "model_config": {},
        "memory": {**preflight_memory_fields(adapted), "vram_estimate_gb": 20.0},
    }
    budgets = {"vram_budget_gb": 5.0, "time_budget_minutes": None}
    assert _collect_disallowed_patterns([record], **budgets) == []

    # The same ratio used to ban the whole class. Preserve the explicitly
    # historical unversioned route rather than silently rewriting old records.
    legacy = {**record, "memory": {"vram_estimate_gb": 20.0}}
    assert _collect_disallowed_patterns([legacy], **budgets) == ["dense_attention_over_T"]


def test_actual_resolver_wrapper_refusal_reaches_tuner_and_next_prompts(
    tmp_path, monkeypatch, agent_with_scripted_skill
):
    from tests.unit.agent.evaluate_vram_skill.test_wrapper_contract import actual_inference_refusal

    inspection = actual_inference_refusal(monkeypatch)
    probe, adapted = classified_roundtrip(tmp_path, inspection)
    assert not probe.has_capacity_authority
    agent, saved, _, cleanup = _setup(agent_with_scripted_skill, [adapted])
    try:
        output = agent.run(
            _make_input(tmp_path, max_rounds=1).model_copy(update={"formal_vram_budget_gb": 5.0})
        )
    finally:
        cleanup()
    record = next(item for item in saved if item["status"] == "skipped_oom_risk")
    typed = ExperimentRecord.model_validate(record)
    decision = typed.memory.static_preflight_evidence.phases[1]
    assert decision.phase == "inference"
    assert decision.batch_size == 3
    assert decision.vram_estimate_bytes == 8_589_934_722
    assert decision.vram_cap_bytes == 5_368_709_120
    assert typed.memory.vram_estimate_gb == 8.0
    assert typed.memory.preflight_outcome == "STATIC_PREFLIGHT_REFUSAL"
    planner = get_planner_user_prompt([record], force_model="punet")
    proposer = _render_physical_rejection(output.physical_rejections[0], n_rejections=1)
    for message in (planner, proposer, output.gate_exhaustion.summary_message):
        assert "inference B=3" in message
        assert "8,589,934,722 bytes" in message
        assert "5,368,709,120 bytes" in message
        assert "not a measured GPU peak or CUDA OOM" in message
        assert "too heavy" not in message
