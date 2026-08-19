"""The interpreter sees per-round HealthGate evidence, provenance-labeled.

CB2 suite (``docs/design/v19_priorities/pr3_healthgate_feedback.md``
§3.5, §7.1). Record fixtures are authored from the REAL persisted
shapes of all three artifact vintages found by the P3-CA audit (§2.5):
pre-gate legacy, commit-5b round-fields-only, and V17-era gated —
including the V17 skip record that carries ``health_gate_results: []``
present-but-empty.

The governing rule pinned throughout: preserve the strongest evidence
actually present; never infer gate execution from missing fields; never
discard explicit gate evidence via a broad status classification.
"""

import pytest
from pydantic import ValidationError

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningOutput
from execute_tools.metric_order import MetricOrder
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.metric_fixtures import shipped_spec

#: Step 09a C3 — the migrated ordering consumers take the run's MetricOrder as a
#: REQUIRED keyword. The shipped TIDMAD spec is `higher`, so every expectation in
#: this file is unchanged; the direction is now stated instead of assumed.
_STEP09A_ORDER = MetricOrder(shipped_spec())


def _gate_result(
    name="output_diversity_blocking",
    metric="n_unique_int8_values",
    unit="count",
    worst=1.0,
):
    """One persisted gate result in the real V17 shape (design §2.5)."""
    return {
        "gate_name": name,
        "execution_status": "failed",
        "check_passed": False,
        "would_invalidate_under_production_policy": True,
        "resolved_action": "invalidate_round",
        "failure_reason": f"{name}: {metric}={worst}",
        "threshold": {"metric": metric, "operator": ">", "value": 25, "unit": unit},
        "aggregation": {},
        "metrics": {"aggregate_statistics": {"minimum": worst, "maximum": worst, "mean": worst}},
        "gate_runtime_seconds": 0.4,
    }


def _record(exp_id: str, **overrides) -> ExperimentRecord:
    """Dict-validated record — ``model_fields_set`` mirrors authored keys,
    exactly like both production paths (design §2.5)."""
    base = {
        "exp_id": exp_id,
        "status": "success",
        "model_type": "wavenet",
        "timestamp": "2026-07-29T00:00:00Z",
        "params": {},
        "denoising_score": 1.0,
    }
    return ExperimentRecord.model_validate({**base, **overrides})


def _output(*records) -> HyperparamTuningOutput:
    return HyperparamTuningOutput(
        run_name="round_health_summary_test",
        model_type="wavenet",
        file_index=6,
        status="completed",
        completed_rounds=len(records),
        total_attempts=len(records),
        started_at="2026-07-29T00:00:00Z",
        finished_at="2026-07-29T01:00:00Z",
        all_records=list(records),
    )


# ---------------------------------------------------------------------------
# Vintage classification through the builder (§7.1 provenance suite)
# ---------------------------------------------------------------------------


def test_gated_collapse_round_carries_evidence_and_fingerprint():
    """V17-era collapse record: full per-gate results → gated provenance,
    condensed outcomes, and a fingerprint built from persisted metrics."""
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                "r1",
                status="failed_mode_collapse",
                denoising_score=None,
                gate_action="invalidate_round",
                failure_reason="[output_diversity_blocking] collapse",
                health_gate_results=[_gate_result()],
            )
        ),
        order=_STEP09A_ORDER,
    )
    [health] = summary.round_health
    assert health.provenance == "gated"
    assert health.exp_id == "r1"
    assert health.gate_action == "invalidate_round"
    assert health.health_validity == "invalid"  # status != success
    assert [o.gate_name for o in health.gate_outcomes] == ["output_diversity_blocking"]
    assert health.fingerprint is not None
    assert health.fingerprint.signature == ("output_diversity_blocking:n_unique_int8_values=1")
    assert health.fingerprint.metrics == {"n_unique_int8_values": 1}


def test_v17_skip_record_empty_list_is_not_evaluated_not_legacy():
    """The real V17 skip shape: ``health_gate_results`` PRESENT and empty
    on a pre-flight status. Routed by status (nothing ran) — and never
    classified legacy by emptiness."""
    summary = tuning_output_to_model_run_summary(
        _output(
            _record("r1", status="skipped_time_risk", denoising_score=None, health_gate_results=[])
        ),
        order=_STEP09A_ORDER,
    )
    [health] = summary.round_health
    assert health.provenance == "gate_not_evaluated"
    assert health.gate_outcomes == []
    assert health.fingerprint is None


def test_current_gated_empty_list_on_executed_round_is_gated():
    """Present-but-empty on an EXECUTED status → current gated era."""
    summary = tuning_output_to_model_run_summary(
        _output(_record("r1", status="success", health_gate_results=[])), order=_STEP09A_ORDER
    )
    [health] = summary.round_health
    assert health.provenance == "gated"
    assert health.gate_outcomes == []
    assert health.fingerprint is None  # healthy: nothing failed


def test_mid_vintage_round_fields_only_preserved_verbatim_no_fingerprint():
    """Real pre-V17 shape: commit-5b round fields, no per-gate results.
    Fields preserved verbatim; no fingerprint invented from prose."""
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                "r1",
                status="failed_mode_collapse",
                denoising_score=None,
                gate_action="invalidate_round",
                failure_reason="[output_diversity_blocking] unique=1",
            )
        ),
        order=_STEP09A_ORDER,
    )
    [health] = summary.round_health
    assert health.provenance == "round_fields_only"
    assert health.gate_action == "invalidate_round"
    assert health.failure_reason == "[output_diversity_blocking] unique=1"
    assert health.gate_outcomes == []
    assert health.fingerprint is None


def test_legacy_executed_record_carries_no_verdict():
    summary = tuning_output_to_model_run_summary(_output(_record("r1")), order=_STEP09A_ORDER)
    [health] = summary.round_health
    assert health.provenance == "legacy"
    assert health.fingerprint is None
    assert health.gate_outcomes == []
    # No gates on record → eligibility cannot be established either way.
    assert health.health_validity == "unknown"


def test_gates_disabled_round_is_valid_by_rule():
    summary = tuning_output_to_model_run_summary(
        _output(_record("r1", health_gate_enabled=False)), order=_STEP09A_ORDER
    )
    [health] = summary.round_health
    assert health.provenance == "gates_disabled"
    assert health.health_validity == "valid"  # DS5 waiver
    assert health.fingerprint is None


def test_attempt_failure_exception_text_is_not_gate_evidence():
    """attempt_failure reuses ``failure_reason`` for the EXCEPTION (§2.5
    field-overload finding). Carried verbatim, but the provenance label
    marks it as not-gate-evaluated so it cannot read as gate evidence."""
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                "r1",
                record_type="attempt_failure",
                status="error",
                denoising_score=None,
                failure_reason="RuntimeError: CUDA out of memory",
                counts_toward_completed_rounds=False,
            )
        ),
        order=_STEP09A_ORDER,
    )
    [health] = summary.round_health
    assert health.provenance == "gate_not_evaluated"
    assert health.failure_reason == "RuntimeError: CUDA out of memory"
    assert health.fingerprint is None
    assert health.gate_outcomes == []


def test_evidence_precedence_error_status_with_persisted_results_is_gated():
    """Governing rule: a (hypothetical) error record that DID persist gate
    results classifies by its evidence — the status rule never discards
    explicit persisted evidence."""
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                "r1",
                status="error_scoring",
                denoising_score=None,
                health_gate_results=[_gate_result()],
                gate_action="invalidate_round",
            )
        ),
        order=_STEP09A_ORDER,
    )
    [health] = summary.round_health
    assert health.provenance == "gated"
    assert health.fingerprint is not None


# ---------------------------------------------------------------------------
# Alignment, backward-compat, round-trip, negatives
# ---------------------------------------------------------------------------


def test_round_health_aligned_with_round_scores_incl_attempt_failures():
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                "r1",
                status="failed_mode_collapse",
                denoising_score=None,
                gate_action="invalidate_round",
                failure_reason="x",
                health_gate_results=[_gate_result()],
            ),
            _record(
                "r2",
                record_type="attempt_failure",
                status="error",
                denoising_score=None,
                counts_toward_completed_rounds=False,
            ),
            _record("r3"),
        ),
        order=_STEP09A_ORDER,
    )
    assert len(summary.round_health) == len(summary.round_scores) == 3
    assert [h.exp_id for h in summary.round_health] == ["r1", "r2", "r3"]
    assert [h.provenance for h in summary.round_health] == [
        "gated",
        "gate_not_evaluated",
        "legacy",
    ]


def test_pre_pr3_summary_fields_unchanged():
    """Backward-compat bar (§11-CB2): every existing ModelRunSummary field
    is byte-identical with round_health present."""
    output = _output(_record("r1", denoising_score=2.5))
    summary = tuning_output_to_model_run_summary(output, order=_STEP09A_ORDER)
    dumped = summary.model_dump()
    new_fields = {"round_health"}
    baseline = {k: v for k, v in dumped.items() if k not in new_fields}
    assert baseline["round_scores"] == [2.5]
    assert baseline["best_denoising_score"] == output.best_denoising_score
    assert baseline["round_ordering"][0]["resolution_source"] == "legacy_default"
    # A summary authored WITHOUT the field still validates (legacy digest).
    from agent.schemas.interpretation import ModelRunSummary

    legacy = ModelRunSummary.model_validate(baseline)
    assert legacy.round_health == []


def test_summary_round_trips_through_json():
    summary = tuning_output_to_model_run_summary(
        _output(
            _record(
                "r1",
                status="failed_mode_collapse",
                denoising_score=None,
                gate_action="invalidate_round",
                failure_reason="x",
                health_gate_results=[_gate_result()],
            )
        ),
        order=_STEP09A_ORDER,
    )
    from agent.schemas.interpretation import ModelRunSummary

    restored = ModelRunSummary.model_validate_json(summary.model_dump_json())
    assert restored.round_health == summary.round_health
    assert restored.round_health[0].fingerprint.signature == (
        "output_diversity_blocking:n_unique_int8_values=1"
    )


def test_malformed_gate_result_is_a_diagnosable_error():
    """A structurally broken health_gate_results entry fails record
    validation loudly — never a silent misclassification downstream."""
    with pytest.raises(ValidationError, match="health_gate_results"):
        _record("r1", health_gate_results=[{"not_a_gate": True}])
