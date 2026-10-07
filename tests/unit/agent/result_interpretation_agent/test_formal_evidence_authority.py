"""A stored positive verdict cannot replace the selected record's evidence."""

from copy import deepcopy

import pytest

from execute_tools.formal_evidence import FormalResultEvidence
from execute_tools.metric_order import MetricOrder
from execute_tools.scientific_aggregation import partition_for_aggregation
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import accuracy_like_spec
from tests.unit.agent.result_interpretation_agent.test_fscane1_exclusion_is_told import (
    _run,
    _summary,
    _synthesis,
    _verdict,
)
from tests.unit.agent.result_interpretation_agent.test_round_health_summary import (
    _output,
    _record,
)


def _gate(**changes):
    return {
        "gate_name": "required_check",
        "execution_status": "passed",
        "check_passed": True,
        "would_invalidate_under_production_policy": False,
        "resolved_action": "continue",
        **changes,
    }


def _evidence(**changes):
    return {
        "model_type": "wavenet",
        "run_name": "v1",
        "exp_id": "formal_2",
        "status": "success",
        "denoising_score": 7.0,
        "is_trial": False,
        "health_gate_enabled": True,
        "health_gate_results": [_gate()],
        "required_gate_ids": ["required_check"],
        "healthgate_mode": "blocking",
        "result_authority": "scientific",
        **changes,
    }


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({}, None),
        (
            {"health_gate_results": [_gate(execution_status="failed", check_passed=False)]},
            "gate_invalidated",
        ),
        ({"health_gate_results": [_gate(execution_status="error")]}, "formal_validity_unknown"),
        ({"health_gate_results": []}, "formal_validity_unknown"),
        ({"required_gate_ids": None}, "formal_validity_unknown"),
        ({"required_gate_ids": [], "health_gate_results": []}, None),
        (
            {"required_gate_ids": None, "health_gate_enabled": False, "health_gate_results": []},
            None,
        ),
        (
            {
                "health_gate_results": [
                    _gate(execution_status="not_run", check_verdicts={"check": "inapplicable"})
                ]
            },
            None,
        ),
        ({"result_authority": "diagnostic"}, "formal_declaration_mismatch"),
        ({"healthgate_mode": "observe_only"}, "formal_declaration_mismatch"),
        ({"denoising_score": 9.0}, "formal_evidence_mismatch"),
        ({"is_trial": True}, "formal_evidence_mismatch"),
        ({"model_type": "other"}, "formal_evidence_mismatch"),
        ({"run_name": "other-run"}, "formal_evidence_mismatch"),
    ],
)
def test_independent_evidence_controls_fresh_and_actual_cached_results(tmp_path, changes, reason):
    summary = _summary(
        "wavenet",
        best=3.0,
        formal=7.0,
        verdict=_verdict("blocking", "scientific", "valid"),
    )
    summary.formal_evidence = FormalResultEvidence.model_validate(_evidence(**changes))
    control = _summary(
        "punet", best=1.0, formal=2.0, verdict=_verdict("blocking", "scientific", "valid")
    )
    fresh, fresh_prompts = _run(tmp_path / "fresh", [summary, control])
    cached, cached_prompts = _run(
        tmp_path / "cached",
        [],
        cache=fresh.model_knowledge_cache,
        iteration=2,
    )
    stats = fresh.model_knowledge_cache["wavenet"]["_stats"]
    assert stats["formal_score"] == 7.0  # Raw evidence survives exclusion.
    assert stats["formal_evidence"] == summary.formal_evidence.model_dump(mode="json")
    for output, prompts in ((fresh, fresh_prompts), (cached, cached_prompts)):
        scope = output.scientific_aggregation
        assert set(scope["included"]) == ({"wavenet", "punet"} if reason is None else {"punet"})
        assert scope["exclusion_reason_counts"] == ({} if reason is None else {reason: 1})
        synthesis = _synthesis(prompts)
        if reason:
            assert reason in synthesis


@pytest.mark.parametrize("raw", [None, {}, "bad", {"denoising_score": True}])
def test_legacy_or_malformed_cache_cannot_gain_authority(tmp_path, raw):
    summary = _summary(
        "wavenet", best=3.0, formal=7.0, verdict=_verdict("blocking", "scientific", "valid")
    )
    fresh, _ = _run(tmp_path / "fresh", [summary])
    cache = deepcopy(fresh.model_knowledge_cache)
    cache["wavenet"]["_stats"]["formal_evidence"] = raw
    output, _ = _run(tmp_path / "cached", [], cache=cache, iteration=2)
    reason = "formal_evidence_missing" if raw is None else "formal_evidence_malformed"
    assert output.scientific_aggregation["exclusion_reason_counts"] == {reason: 1}
    assert output.model_knowledge_cache["wavenet"]["_stats"]["formal_score"] == 7.0


def test_projection_uses_last_formal_record_not_valid_best_or_trial():
    verdict = _verdict("blocking", "scientific", "valid")
    output = _output(
        _record(
            "formal_1",
            is_trial=False,
            denoising_score=10.0,
            health_gate_enabled=False,
            scientific_authority=verdict,
        ),
        _record(
            "formal_2",
            is_trial=False,
            denoising_score=7.0,
            health_gate_enabled=True,
            health_gate_results=[],
            scientific_authority=verdict,
        ),
        _record(
            "trial_3",
            is_trial=True,
            denoising_score=20.0,
            health_gate_enabled=False,
            scientific_authority=verdict,
        ),
    )
    output.healthgate_mode = "blocking"
    output.result_authority = "scientific"
    output.health_config_sha256 = "a" * 64
    summary = tuning_output_to_model_run_summary(
        output,
        order=MetricOrder(accuracy_like_spec()),
        required_gate_ids=frozenset({"required_check"}),
    )
    assert summary.best_valid_formal_score == 10.0
    assert summary.formal_score == 7.0
    assert summary.formal_evidence.exp_id == "formal_2"
    assert summary.formal_evidence.required_gate_ids == ("required_check",)
    assert summary.formal_evidence.health_config_sha256 == "a" * 64
    assert summary.formal_evidence.healthgate_mode == "blocking"
    assert summary.formal_evidence.result_authority == "scientific"
    scope = partition_for_aggregation([summary])
    assert scope.exclusion_reason_counts == {"formal_validity_unknown": 1}


def test_projection_does_not_relabel_a_misplaced_record_as_the_output_model():
    output = _output(
        _record(
            "foreign_formal",
            model_type="other-model",
            is_trial=False,
            health_gate_enabled=False,
            scientific_authority=_verdict("blocking", "scientific", "valid"),
        )
    )
    summary = tuning_output_to_model_run_summary(output, order=MetricOrder(accuracy_like_spec()))
    assert summary.formal_evidence.model_type == "other-model"
    assert partition_for_aggregation([summary]).exclusion_reason_counts == {
        "formal_evidence_mismatch": 1
    }


@pytest.mark.parametrize("field", ["gate_boolean", "score_boolean"])
def test_malformed_cached_facts_cannot_be_coerced_to_passing_evidence(tmp_path, field):
    summary = _summary(
        "wavenet", best=3.0, formal=1.0, verdict=_verdict("blocking", "scientific", "valid")
    )
    summary.formal_evidence = FormalResultEvidence.model_validate(_evidence(denoising_score=1.0))
    fresh, _ = _run(tmp_path / "fresh", [summary])
    cache = deepcopy(fresh.model_knowledge_cache)
    stats = cache["wavenet"]["_stats"]
    if field == "gate_boolean":
        stats["formal_evidence"]["health_gate_results"][0]["check_passed"] = "true"
        reason = "formal_evidence_malformed"
    else:
        stats["formal_score"] = True
        reason = "formal_evidence_mismatch"
    output, _ = _run(tmp_path / "cached", [], cache=cache, iteration=2)
    assert output.scientific_aggregation["exclusion_reason_counts"] == {reason: 1}


@pytest.mark.parametrize("roster", [None, frozenset(), frozenset({"required_check"})])
def test_direct_protocol_transports_callers_resolved_roster(tmp_path, roster):
    from agent.schemas.protocols.ml_model_tune_to_ml_result_interp import local_all_records
    from agent.schemas.storage import LocalStorageConfig, StorageConfig

    output = _output(_record("formal", is_trial=False, health_gate_enabled=True))
    output.metric_spec = accuracy_like_spec()
    result = local_all_records(
        output,
        StorageConfig(
            backend="local", local=LocalStorageConfig(workspace=str(tmp_path), run_name="v1")
        ),
        required_gate_ids=roster,
    )
    assert result.summaries[0].formal_evidence.required_gate_ids == (
        None if roster is None else tuple(sorted(roster))
    )


@pytest.mark.parametrize(
    ("flags", "expected"),
    [
        ([], None),
        (["--required_gate_ids"], ()),
        (["--required_gate_ids", "required_check"], ("required_check",)),
    ],
)
def test_standalone_cli_transports_explicit_roster_before_provider_work(
    tmp_path, monkeypatch, flags, expected
):
    import importlib
    import sys

    node = importlib.import_module("nodes.result_interpretation_agent.result_interpretation_agent")
    output = _output(_record("formal", is_trial=False, health_gate_enabled=True))
    output.metric_spec = accuracy_like_spec()
    (tmp_path / "run_output_v1.json").write_text(output.model_dump_json())

    class Captured(Exception):
        pass

    class CaptureAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, inp):
            assert inp.summaries[0].formal_evidence.required_gate_ids == expected
            raise Captured

    monkeypatch.setattr(node, "ResultInterpretationAgent", CaptureAgent)
    monkeypatch.setattr(
        sys, "argv", ["interpret", "--workspace", str(tmp_path), "--model_type", "wavenet", *flags]
    )
    with pytest.raises(Captured):
        node.main()
