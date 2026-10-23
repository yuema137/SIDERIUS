"""Workflow-owned ordering around the real native input boundary.

Node effects and existing staging/promotion owners are observed at their seams;
these tests pin invocation order, not registry/file-copy implementation.
"""

from pathlib import Path

import pytest

from tests.unit.workflows import test_model_exploration as workflow_tests
from tests.unit.workflows.test_model_exploration import workflow_env as workflow_env
from workflows import model_exploration, tuner_preparation
from workflows.run_config import WorkflowLaunchConfig


@pytest.mark.parametrize(
    "outcome", ["accepted", "rejected", "protocol_error", "task_error", "abort"]
)
def test_native_input_boundary_preserves_lifecycle_order(
    workflow_env, tmp_path, monkeypatch, outcome
):
    """Reordering/bypassing the builder or promoting rejected input breaks the trace."""
    events = []
    impl = workflow_tests._make_impl_output_with_loss_provenance(tmp_path)
    impl = impl.model_copy(update={"model_type": "gated_tcn"})
    workflow_env["impl"].return_value.run.return_value = impl
    if outcome == "rejected":
        workflow_env["valid"].return_value.run.return_value = workflow_tests._make_validator_output(
            False
        )

    def stage(output, model_name, dest_plugin_dirs, *, dest_loss_dirs):
        assert output is impl and model_name == "gated_tcn"
        assert len(dest_plugin_dirs) == len(dest_loss_dirs) == 2
        assert Path(dest_plugin_dirs[0]).is_relative_to(
            Path(workflow_env["workspace"]) / "n1_order"
        )
        assert not Path(dest_plugin_dirs[1]).is_relative_to(
            Path(workflow_env["workspace"]) / "n1_order"
        )
        events.extend(["stage_tuner", "stage_chain"])

    monkeypatch.setattr(
        model_exploration,
        "_admit_generated_model_construction",
        lambda *_args: events.append("admit"),
    )
    monkeypatch.setattr(
        model_exploration, "_commit_candidate_capabilities", lambda *_args: events.append("commit")
    )
    monkeypatch.setattr(model_exploration, "_register_plugin", stage)
    monkeypatch.setattr(
        model_exploration, "_promote_loss_to_global", lambda *_args: events.append("promote_loss")
    )
    monkeypatch.setattr(
        model_exploration, "_promote_model_to_global", lambda *_args: events.append("promote_model")
    )
    real_builder = tuner_preparation.prepare_native_tuner_input
    real_protocol = tuner_preparation.local_validated_model
    real_task_load = tuner_preparation.load_task_config
    protocol_outputs = []

    def protocol(*args, **kwargs):
        events.append("protocol")
        if outcome == "protocol_error":
            raise ValueError("N1 protocol failure")
        result = real_protocol(*args, **kwargs)
        protocol_outputs.append(result)
        return result

    def task_load():
        events.append("task_load")
        # Advice enrichment must precede this potentially failing operation.
        assert protocol_outputs[-1].human_advice == "N1 tune advice"
        if outcome == "task_error":
            raise ValueError("N1 task failure")
        return real_task_load()

    def builder(**kwargs):
        events.append("builder")
        return real_builder(**kwargs)

    monkeypatch.setattr(tuner_preparation, "local_validated_model", protocol)
    monkeypatch.setattr(tuner_preparation, "load_task_config", task_load)
    monkeypatch.setattr(model_exploration, "prepare_native_tuner_input", builder)
    output = workflow_env["tune"].return_value.run.return_value
    if outcome == "abort":
        output.status = "failed"
        output.termination_reason = "infrastructure_abort"
        output.all_records = []
        output.completed_rounds = 0
        output.best_denoising_score = None
        output.best_formal_denoising_score = None

    def tune(_input):
        events.append("tuner")
        assert _input is protocol_outputs[-1]
        return output

    workflow_env["tune"].return_value.run.side_effect = tune

    def run():
        return workflow_tests.run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_proposal_attempts=1,
                max_impl_attempts=1,
                human_advice_tune="N1 tune advice",
            ),
            workspace=workflow_env["workspace"],
            run_name="n1_order",
        )

    prefix = [
        "admit",
        "commit",
        "stage_tuner",
        "stage_chain",
        "promote_loss",
        "promote_model",
        "builder",
        "protocol",
    ]
    if outcome in ("protocol_error", "task_error"):
        with pytest.raises(ValueError, match=r"N1 (protocol|task) failure"):
            run()
        workflow_env["tune"].assert_not_called()
        assert events == prefix + (["task_load"] if outcome == "task_error" else [])
    else:
        run()
        if outcome == "rejected":
            assert events == []
            workflow_env["tune"].assert_not_called()
        else:
            assert events == prefix + ["task_load", "tuner"] + (
                ["promote_loss"] if outcome == "accepted" else []
            )
