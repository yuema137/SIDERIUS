"""#139: real attempt producers retain selected ordering, including raised planning.

Only external skills/providers are faked: resolution, phase dispatch, error
construction, validation and save all run. Losing any transport hop makes the
literal provenance assertions fail; leaking the carrier makes attempt two fail.
These are deterministic wiring witnesses, not claims of real data traversal.
"""

import json
from copy import deepcopy
from importlib import import_module
from unittest.mock import patch

import pytest

from agent.schemas.hyperparam_tuning import ExperimentRecord, HyperparamTuningInput
from agent.schemas.ordering import ResolvedOrdering
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.evaluation_metric import (
    NotScoreableError,
    NotScoreableResult,
    ScoreabilityFailure,
    ScoreabilityVerdict,
)
from execute_tools.metric_order import MetricOrder
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.result_interpretation_agent import tuning_output_to_model_run_summary
from tests.helpers.scoring_stubs import stub_scoring
from workflows.run_one_iteration import write_manifest
from workflows.task_composition import (
    bind_run_task_composition,
    build_task_composition_ref,
    compose_run_task_bindings,
)

from .test_ordering_formal_branch import FORMAL_PLAN_RESPONSE, QUICKSTART_MANIFEST
from .test_tuning_agent import FAKE_REFLECT_RESPONSE, _mock_run_skill, _synth_reference

_RECORDS = import_module("nodes.ml_hyperparameter_tune_agent.records")
_PLANNING = import_module("nodes.ml_hyperparameter_tune_agent.planning")
_FIELDS = {
    "proposed_order_strategy",
    "proposed_file_order",
    "ordering_proposal_rejected",
    "ordering_proposal_rejection_reason",
    "override_order_strategy",
    "override_file_order",
    "resolved_order_strategy",
    "resolved_file_order",
    "ordering_resolution_source",
}


@pytest.fixture
def run_failure(tmp_path):
    """Run production orchestration with one named deterministic fault."""

    def run(*, phase, payload=None, trial=False, attempts=1):
        saved, before, dispatched = [], [], []
        emit = _RECORDS._emit_record

        def capture(sandbox, record, **kwargs):
            before.append(deepcopy(record))
            emit(sandbox, record, **kwargs)

        def skill(name, sandbox, **params):
            dispatched.append(name)
            if name == "training_skill" and trial:
                config_path = tmp_path / "configs" / f"trial_config_{params['exp_id']}.json"
                assert json.loads(config_path.read_text())["mode"] == "trial"
            if name == phase:
                if isinstance(payload, Exception):
                    raise payload
                return payload
            return _mock_run_skill(name, sandbox, **params)

        with (
            patch("nodes.ml_hyperparameter_tune_agent.LLMBridge") as bridge,
            patch("nodes.ml_hyperparameter_tune_agent.TidmadSandbox") as sandbox_type,
            patch("nodes.ml_hyperparameter_tune_agent.runtime._run_skill", side_effect=skill),
            patch(
                "nodes.ml_hyperparameter_tune_agent.load_reference_scores",
                return_value=_synth_reference(),
            ),
            patch("nodes.ml_hyperparameter_tune_agent.time.sleep"),
            patch(
                "nodes.ml_hyperparameter_tune_agent.execution.wall_time_preflight_applicable",
                return_value=True,
            ),
            patch(
                "nodes.ml_hyperparameter_tune_agent.execution._run_time_preflight",
                return_value=payload if phase == "time_preflight" else None,
            ),
            patch.object(_RECORDS, "_emit_record", side_effect=capture),
        ):
            brain = bridge.return_value
            plan = {
                **deepcopy(FORMAL_PLAN_RESPONSE),
                "is_trial": trial,
                "order_strategy": "sequential",
                "file_order": [2, 0, 1, 3] if trial else [0, 0],
            }
            brain.plan.side_effect = [plan] + [RuntimeError("before resolution")] * (attempts - 1)
            brain.reflect.return_value = FAKE_REFLECT_RESPONSE
            if phase == "reflection":
                brain.reflect.side_effect = RuntimeError("after execution")
            sandbox = sandbox_type.return_value
            sandbox.get_summary.side_effect = lambda: list(saved)
            sandbox.save_record.side_effect = lambda record: saved.append(deepcopy(record))
            for name in ("configs", "data", "denoised"):
                (tmp_path / name).mkdir(exist_ok=True)
            sandbox.dirs = {name: str(tmp_path / name) for name in ("configs", "data", "denoised")}
            sandbox.base_dir = str(tmp_path / "denoised")
            stub_scoring(sandbox, [1.75] * 4, 1.75)
            composition = compose_run_task_bindings(str(QUICKSTART_MANIFEST))
            agent_input = HyperparamTuningInput(
                planner_strategy="native-timing-v1",
                model_type="quickstart_reference_mlp",
                run_name="error_ordering",
                max_rounds=2 if trial else 1,
                attempts_per_round=attempts,
                attempts_per_formal_round=attempts,
                max_fail_rounds=1,
                is_trial=True,
                health_gate_enabled=False,
                order_strategy_override="sequential",
                file_order_override=[3, 1, 0, 2],
                task_composition_ref=build_task_composition_ref(composition),
                llm_provider="gemini",
                llm_model_id="test-model",
                progress_bar=False,
                trial_time_budget_minutes=1.0 if phase == "time_preflight" else None,
                formal_time_budget_minutes=1.0 if phase == "time_preflight" else None,
                trial_time_admission_source="forecast",
                formal_time_admission_source="forecast",
                storage=StorageConfig(
                    backend="local",
                    local=LocalStorageConfig(workspace=str(tmp_path), run_name="error_ordering"),
                ),
            )
            with bind_run_task_composition(composition, physical_data_root=str(tmp_path / "data")):
                if phase == "preparation":
                    with patch.object(
                        _PLANNING, "TrialConfig", side_effect=RuntimeError("after resolution")
                    ):
                        output = HyperparamTuningAgent().run(agent_input)
                else:
                    output = HyperparamTuningAgent().run(agent_input)
        assert saved, "fault did not reach production save"
        return saved, before, dispatched, output

    return run


def assert_selected(record):
    typed = ExperimentRecord.model_validate(record)
    assert typed.proposed_order_strategy == "sequential"
    assert typed.proposed_file_order == [0, 0]
    assert typed.ordering_proposal_rejected is True
    assert "duplicate" in typed.ordering_proposal_rejection_reason
    assert typed.override_order_strategy == "sequential"
    assert typed.override_file_order == [3, 1, 0, 2]
    assert typed.resolved_order_strategy == "sequential"
    assert typed.resolved_file_order == [3, 1, 0, 2]
    assert typed.ordering_resolution_source == "operator_override"


@pytest.mark.parametrize("phase", ["training_skill", "inference_skill"])
@pytest.mark.parametrize(
    "payload,suffix",
    [
        ({"status": "error", "message": "ordinary child failure"}, ""),
        ({"status": "error", "message": "CUDA out of memory"}, "_oom"),
        ({"status": "oom_host_ram", "message": "host allocation failed"}, ""),
    ],
)
def test_phase_failures_preserve_selection_and_existing_payload(
    run_failure, phase, payload, suffix
):
    """Each failure branch must carry ordering without altering its error payload."""
    saved, before, dispatched, _ = run_failure(phase=phase, payload=payload)
    assert len(saved) == 1
    assert phase in dispatched
    assert saved[0]["status"] == f"error_{phase.removesuffix('_skill')}{suffix}"
    assert_selected(saved[0])
    assert {key: saved[0][key] for key in before[0]} == before[0]
    assert not (_FIELDS & before[0].keys()), "builder must not duplicate mapping"


def test_malformed_training_result_retains_selection(run_failure):
    """Typed-result refusal reaches the training error producer, not success."""
    saved, _, _, _ = run_failure(
        phase="training_skill",
        payload={"status": "success", "results": {"training_history": "malformed"}},
    )
    assert saved[0]["status"] == "error_training"
    assert_selected(saved[0])


def test_trial_failure_retains_its_proposal_and_override(run_failure):
    """Trial planning uses the same error stamp even without a rejected proposal."""
    saved, _, _, _ = run_failure(
        phase="training_skill", trial=True, payload={"status": "error", "message": "trial failure"}
    )
    ordering = ResolvedOrdering.from_record(ExperimentRecord.model_validate(saved[0]))
    assert saved[0]["status"] == "error_training"
    assert ordering.proposed_file_order == [2, 0, 1, 3]
    assert ordering.proposal_rejected is False
    assert ordering.resolved_file_order == [3, 1, 0, 2]
    assert ordering.resolution_source == "operator_override"


@pytest.mark.parametrize("phase", ["training", "inference"])
@pytest.mark.parametrize("reason", ["insufficient_headroom", "measurement_unavailable"])
def test_real_admission_producer_preserves_selection_and_refused_phase(run_failure, phase, reason):
    saved, _, dispatched, output = run_failure(
        phase=f"{phase}_skill",
        payload={
            "status": "skipped_resource_admission",
            "message": "synthetic refusal",
            "admission": {"reason_code": reason},
        },
    )
    assert len(saved) == 1
    assert_selected(saved[0])
    assert saved[0]["ordering_observation"] == {
        "selection_state": "selected",
        "refused_before_phase": phase,
    }
    assert saved[0]["status"] == (
        "skipped_resource_admission"
        if reason == "insufficient_headroom"
        else "skipped_infrastructure_failure"
    )
    assert "denoising_score_skill" not in dispatched
    assert ("inference_skill" in dispatched) == (phase == "inference")
    summary = tuning_output_to_model_run_summary(output, order=MetricOrder(output.metric_spec))
    assert summary.round_ordering[0].ordering_observation.refused_before_phase == phase


def test_measured_time_rejection_is_not_claimed_to_precede_training(run_failure):
    saved, _, dispatched, _ = run_failure(
        phase="training_skill", payload={"status": "rejected_time_risk", "message": "measured"}
    )
    assert_selected(saved[0])
    assert "training_skill" in dispatched
    assert "inference_skill" not in dispatched
    assert saved[0]["ordering_observation"] == {
        "selection_state": "selected",
        "refused_before_phase": None,
    }


def test_preflight_skip_preserves_selection_without_claiming_execution(run_failure):
    """A real preflight emission retains selection and explicitly records refusal."""
    saved, _, dispatched, _ = run_failure(
        phase="evaluate_vram_skill", payload={"status": "schema_violation", "violations": []}
    )
    assert saved[0]["status"] == "skipped_schema_violation"
    assert "training_skill" not in dispatched
    assert_selected(saved[0])
    assert saved[0]["ordering_observation"] == {
        "selection_state": "selected",
        "refused_before_phase": "preflight",
    }


@pytest.mark.parametrize("refused", [False, True])
def test_scoring_exception_and_refusal_retain_selection(run_failure, refused):
    """The real scoring catch must retain both selection and structured refusal."""
    refusal = NotScoreableResult(
        metric_id="quickstart_accuracy",
        direction="higher",
        verdict=ScoreabilityVerdict(
            contract_id="test_payload",
            failures=[ScoreabilityFailure(requirement="payload", detail="missing")],
        ),
    )
    error = NotScoreableError(refusal) if refused else RuntimeError("scoring failed")
    saved, _, dispatched, _ = run_failure(phase="denoising_score_skill", payload=error)
    assert "denoising_score_skill" in dispatched
    assert saved[0]["status"] == "error_scoring"
    assert_selected(saved[0])
    if refused:
        assert saved[0]["failure_type"] == "not_scoreable"
        assert saved[0]["metric_refusal"] == refusal.model_dump(mode="json")


@pytest.mark.parametrize("phase", ["preparation", "reflection"])
def test_outer_error_capture_is_attempt_local(run_failure, phase):
    """Capture before prepare returns; reset before the next unresolved attempt."""
    saved, _, dispatched, _ = run_failure(phase=phase, attempts=2)
    assert len(saved) == 2
    assert all(record["record_type"] == "attempt_failure" for record in saved)
    assert [record["attempt_index"] for record in saved] == [1, 2]
    assert all(record["counts_toward_completed_rounds"] is False for record in saved)
    assert all(record["counts_toward_attempt_budget"] is True for record in saved)
    assert_selected(saved[0])
    assert saved[1].get("resolved_order_strategy") is None, "prior attempt ordering leaked"
    assert saved[1]["ordering_observation"]["selection_state"] == "unresolved"
    assert saved[1]["override_file_order"] == [3, 1, 0, 2]
    assert saved[1]["failure_reason"] == "before resolution"
    if phase == "preparation":
        assert "training_skill" not in dispatched
        assert saved[0]["failure_reason"] == "after resolution"
    else:
        assert "denoising_score_skill" in dispatched
        assert saved[0]["failure_reason"] == "after execution"


def test_saved_failures_reach_both_real_ordering_readers(run_failure, tmp_path):
    """Saved errors must not become historical shuffle in either live reader."""
    saved, _, _, output = run_failure(phase="preparation", attempts=2)
    assert output.metric_spec is not None
    assert [record.exp_id for record in output.all_records] == [r["exp_id"] for r in saved]
    summary = tuning_output_to_model_run_summary(output, order=MetricOrder(output.metric_spec))
    selected, absent = summary.round_ordering
    assert selected.resolved_order_strategy == "sequential"
    assert selected.resolved_file_order == [3, 1, 0, 2]
    assert selected.resolution_source == "operator_override"
    assert selected.proposal_rejected is True
    assert absent.resolution_source == "unresolved"
    manifest = write_manifest(str(tmp_path), "error_ordering", [output])
    selected_manifest, absent_manifest = manifest["ordering_by_experiment"]
    assert selected_manifest["resolved_order_strategy"] == "sequential"
    assert selected_manifest["resolved_file_order"] == [3, 1, 0, 2]
    assert selected_manifest["ordering_resolution_source"] == "operator_override"
    assert {key: selected_manifest[key] for key in _FIELDS} == {
        key: saved[0][key] for key in _FIELDS
    }
    assert absent_manifest["ordering_resolution_source"] == "unresolved"


def test_mode_collapse_keeps_completed_record_ordering(run_failure):
    """Moving the mapping must not drop ordering on the other completed status."""
    saved, _, _, _ = run_failure(
        phase="denoising_score_skill",
        payload={
            "status": "success",
            "results": {
                "denoising_score": float("nan"),
            },
        },
    )
    assert saved[0]["status"] == "failed_mode_collapse"
    assert_selected(saved[0])
