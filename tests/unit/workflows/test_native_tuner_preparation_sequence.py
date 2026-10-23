"""Workflow-owned ordering around the real native input boundary.

Node effects and existing staging/promotion owners are observed at their seams;
these tests pin invocation order, not registry/file-copy implementation.
"""

from pathlib import Path

import pytest

from tests.unit.workflows import test_model_exploration as workflow_tests
from tests.unit.workflows.test_model_exploration import workflow_env as workflow_env
from tests.unit.workflows.test_native_plugin_staging import staging_state as staging_state
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
    monkeypatch.setattr(model_exploration, "stage_native_plugins", stage)
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


def test_workflow_executes_shared_staging_before_promotion_and_tuner(
    workflow_env, tmp_path, monkeypatch, staging_state
):
    """A bypassed owner or chain-selected origin fails before promotion/input construction."""
    from ml_models import loss_models_sandbox, plugin_loader
    from tests.unit.workflows.test_native_plugin_staging import (
        LOSS,
        MODEL,
        make_implementation,
    )
    from workflows.plugin_staging import stage_native_plugins

    implementation = make_implementation(tmp_path)
    source = Path(implementation.model_file_path)
    source.write_text(source.read_text().replace(MODEL, "gated_tcn"))
    implementation = implementation.model_copy(update={"model_type": "gated_tcn"})
    workflow_env["impl"].return_value.run.return_value = implementation
    events, destinations = [], []

    def commit(output):
        # Capability publication can make membership true before staging.
        plugin_loader.register_model_in_memory(output.model_file_path)
        assert plugin_loader._PLUGIN_MODEL_ORIGINS["gated_tcn"][1] == str(source)

    def stage(output, model_name, dest_plugin_dirs, *, dest_loss_dirs):
        assert output is implementation
        assert model_name == "gated_tcn"
        assert len(dest_plugin_dirs) == len(dest_loss_dirs) == 2
        assert Path(dest_plugin_dirs[0]).is_relative_to(
            Path(workflow_env["workspace"]) / "n2_staging"
        )
        assert not Path(dest_plugin_dirs[1]).is_relative_to(
            Path(workflow_env["workspace"]) / "n2_staging"
        )
        stage_native_plugins(output, model_name, dest_plugin_dirs, dest_loss_dirs)
        destinations.extend(dest_plugin_dirs)
        for directory in dest_plugin_dirs:
            assert (Path(directory) / "gated_tcn.py").read_bytes() == source.read_bytes()
            assert (Path(directory) / "gated_tcn/description.md").read_bytes() == Path(
                output.description_file_path
            ).read_bytes()
        for directory in dest_loss_dirs:
            assert (Path(directory) / f"{LOSS}.py").read_bytes() == Path(
                output.loss_provenance.loss_file_path
            ).read_bytes()
        events.append("stage")

    def assert_origin():
        assert len(destinations) == 2
        assert plugin_loader._PLUGIN_MODEL_ORIGINS["gated_tcn"][1] == str(
            Path(destinations[0]) / "gated_tcn.py"
        )
        assert LOSS in loss_models_sandbox.LOSS_REGISTRY

    def promote_loss(*_args):
        assert_origin()
        events.append("promote_loss")

    def promote_model(*_args):
        assert_origin()
        events.append("promote_model")

    builder = model_exploration.prepare_native_tuner_input

    def prepare(**kwargs):
        assert_origin()
        events.append("input")
        return builder(**kwargs)

    output = workflow_env["tune"].return_value.run.return_value

    def tune(_input):
        assert_origin()
        events.append("tuner")
        return output

    monkeypatch.setattr(
        model_exploration, "_admit_generated_model_construction", lambda *_args: None
    )
    monkeypatch.setattr(model_exploration, "_commit_candidate_capabilities", commit)
    monkeypatch.setattr(model_exploration, "stage_native_plugins", stage)
    monkeypatch.setattr(model_exploration, "_promote_loss_to_global", promote_loss)
    monkeypatch.setattr(model_exploration, "_promote_model_to_global", promote_model)
    monkeypatch.setattr(model_exploration, "prepare_native_tuner_input", prepare)
    workflow_env["tune"].return_value.run.side_effect = tune
    workflow_tests.run_workflow(
        launch=WorkflowLaunchConfig(
            data_dir=workflow_env["data_dir"],
            model_types=["punet"],
            source_run_name="v1",
            max_proposal_attempts=1,
            max_impl_attempts=1,
        ),
        workspace=workflow_env["workspace"],
        run_name="n2_staging",
    )
    assert events == ["stage", "promote_loss", "promote_model", "input", "tuner", "promote_loss"]


@pytest.mark.parametrize("bad_seed", [False, True])
def test_shared_startup_keeps_seed_validation_before_lock(workflow_env, monkeypatch, bad_seed):
    """Moving scope/Health preparation must not publish a lock before seed admission."""
    events = []
    real_prepare = model_exploration.prepare_training_run
    real_validate = model_exploration.validate_stamped_invariants
    real_lock = model_exploration.ensure_run_invariants

    def prepare(**kwargs):
        events.append("prepare")
        return real_prepare(**kwargs)

    def validate(*args, **kwargs):
        events.append("seed")
        if bad_seed:
            raise ValueError("invalid seed witness")
        return real_validate(*args, **kwargs)

    def lock(*args):
        events.append("lock")
        return real_lock(*args)

    monkeypatch.setattr(model_exploration, "prepare_training_run", prepare)
    monkeypatch.setattr(model_exploration, "validate_stamped_invariants", validate)
    monkeypatch.setattr(model_exploration, "ensure_run_invariants", lock)

    def run():
        return workflow_tests.run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=workflow_env["data_dir"],
                model_types=["punet"],
                source_run_name="v1",
                max_iterations=0,
            ),
            workspace=workflow_env["workspace"],
            run_name="startup_order",
        )

    if bad_seed:
        with pytest.raises(ValueError, match="invalid seed"):
            run()
        assert events == ["prepare", "seed"]
        assert not (Path(workflow_env["workspace"]) / "run_invariants_lock.json").exists()
    else:
        run()
        assert events == ["prepare", "seed", "lock"]
