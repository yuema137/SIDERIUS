"""Issue 712: reject missing inventory before workflow or tuner paid work."""

from types import SimpleNamespace

import pytest

from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.model_output_retention import require_local_output_inventory


def test_presence_check_never_enumerates_future_outputs():
    def unavailable_yet(request):
        pytest.fail("Startup must not enumerate future outputs")

    require_local_output_inventory(
        task=SimpleNamespace(enumerate_output_artifacts=unavailable_yet),
        composed=True,
        external_evaluation=False,
    )


@pytest.mark.parametrize("task", [None, object(), SimpleNamespace(enumerate_output_artifacts=None)])
def test_missing_or_noncallable_inventory_refused(task):
    with pytest.raises(ValueError, match="task setup error"):
        require_local_output_inventory(task=task, composed=True, external_evaluation=False)


@pytest.mark.parametrize(("composed", "external"), [(False, False), (True, True)])
def test_other_execution_routes_do_not_require_local_inventory(composed, external):
    require_local_output_inventory(task=object(), composed=composed, external_evaluation=external)


@pytest.mark.parametrize("retain", [False, True])
def test_workflow_refuses_before_workspace_or_agent_creation(tmp_path, monkeypatch, retain):
    from workflows import model_exploration as workflow
    from workflows.run_config import WorkflowLaunchConfig

    monkeypatch.setattr(workflow, "verify_composition_is_bound", lambda composition: None)
    monkeypatch.setattr(
        workflow,
        "require_lit_review_config_when_enabled",
        lambda **kwargs: pytest.fail("Reached later startup before inventory refusal"),
    )
    workspace = tmp_path / "never-created"
    with pytest.raises(ValueError, match="enumerate_output_artifacts"):
        workflow.run_workflow(
            launch=WorkflowLaunchConfig(retain_model_outputs=retain),
            workspace=str(workspace),
            run_name="inventory-check",
            task_composition=SimpleNamespace(task_data_path=object()),
        )
    assert not workspace.exists()


@pytest.mark.parametrize("retain", [False, True])
def test_direct_tuner_refuses_before_model_config_or_bridge(tmp_path, monkeypatch, retain):
    import importlib

    from agent.schemas.hyperparam_tuning import HyperparamTuningInput, TaskCompositionRef

    tuner = importlib.import_module("nodes.ml_hyperparameter_tune_agent")

    monkeypatch.setattr(tuner, "resolve_bound_task_data_path", lambda: object())
    monkeypatch.setattr(
        tuner,
        "resolve_dataset_profile",
        lambda: pytest.fail("Reached later startup before inventory refusal"),
    )
    agent = tuner.HyperparamTuningAgent(
        bridge_factory=lambda **kwargs: pytest.fail("LLM bridge must not be built")
    )
    inp = HyperparamTuningInput(
        model_type="fixture",
        run_name="inventory-check",
        workspace=str(tmp_path),
        retain_model_outputs=retain,
        task_composition_ref=TaskCompositionRef(
            semantic_fingerprint="fixture",
            task_data_path_id="fixture",
            task_health_binding=HealthBindingState.EXPLICIT_NONE,
        ),
    )
    with pytest.raises(ValueError, match="enumerate_output_artifacts"):
        agent.run(inp)


@pytest.mark.parametrize("route", ["external", "legacy", "local"])
@pytest.mark.parametrize("entry", ["workflow", "tuner"])
def test_entrypoints_preserve_supported_routes(tmp_path, monkeypatch, route, entry):
    import importlib
    from contextlib import nullcontext

    from agent.schemas.hyperparam_tuning import HyperparamTuningInput, TaskCompositionRef
    from execute_tools.evaluation_execution import bind_candidate_evaluation
    from workflows import model_exploration as workflow
    from workflows.run_config import WorkflowLaunchConfig

    class ReachedNextStartup(Exception):
        pass

    def next_startup(*args, **kwargs):
        raise ReachedNextStartup

    def no_enumeration(request):
        pytest.fail("Startup enumerated outputs")

    task = (
        SimpleNamespace(enumerate_output_artifacts=no_enumeration) if route == "local" else object()
    )
    external = SimpleNamespace(
        evaluate=lambda request: pytest.fail("Startup evaluated a candidate")
    )
    scope = bind_candidate_evaluation(external) if route == "external" else nullcontext()
    with scope, pytest.raises(ReachedNextStartup):
        if entry == "workflow":
            monkeypatch.setattr(workflow, "verify_composition_is_bound", lambda composition: None)
            monkeypatch.setattr(workflow, "require_lit_review_config_when_enabled", next_startup)
            workflow.run_workflow(
                launch=WorkflowLaunchConfig(),
                workspace=str(tmp_path),
                run_name="preflight",
                task_composition=None
                if route == "legacy"
                else SimpleNamespace(task_data_path=task),
            )
        else:
            tuner = importlib.import_module("nodes.ml_hyperparameter_tune_agent")

            def resolve_task():
                if route == "legacy":
                    pytest.fail("Legacy execution acquired an ambient composed task")
                return task

            monkeypatch.setattr(tuner, "resolve_bound_task_data_path", resolve_task)
            monkeypatch.setattr(tuner, "resolve_dataset_profile", next_startup)
            inp = HyperparamTuningInput(
                model_type="fixture",
                run_name="preflight",
                workspace=str(tmp_path),
                task_composition_ref=None
                if route == "legacy"
                else TaskCompositionRef(
                    semantic_fingerprint="fixture",
                    task_data_path_id="fixture",
                    task_health_binding=HealthBindingState.EXPLICIT_NONE,
                ),
            )
            tuner.HyperparamTuningAgent().run(inp)
