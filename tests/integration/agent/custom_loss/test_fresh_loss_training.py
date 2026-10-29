"""A newly proposed loss survives admission, promotion, planning and CPU training.

Fake bridges replace only LLM responses. The numerical offset detects silent
criterion fallback; no predeclared task loss can satisfy this witness.
Criterion-side assertions catch #731: generated metadata must not truncate
fractional regression supervision before either training or validation.
This joins production boundaries explicitly; it does not run the complete
model-exploration orchestrator or test live LLM scientific choices.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import torch
import yaml

from agent.prompt_templates.tuner.rendering import EFFICIENCY_BAND_FRACTION, build_tuner_task_render
from agent.schemas.custom_loss_contract import custom_loss_snapshot_from_forward_contract
from agent.schemas.hyperparam_tuning import ExpertAdvice
from agent.schemas.proposal import CustomLossSpec, ProposalOutput
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import LLMCodeReview
from core.capability_registry import CapabilityRegistry
from core.generated_library import bind_generated_library_to_workspace
from core.sandbox_executor import TidmadSandbox, get_loss_dir, get_plugin_dir
from core.training_execution_bindings import TrainingExecutionBindings
from core.training_seeds import SeedContext
from execute_tools.health_checks.config import HealthChecksConfig
from execute_tools.metric_order import MetricOrder
from nodes.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_hyperparameter_tune_agent.contracts import (
    AttemptIdentity,
    AttemptOrdering,
    RunBindings,
)
from nodes.ml_hyperparameter_tune_agent.loss_inventory import resolve_run_custom_loss_inventory
from nodes.ml_hyperparameter_tune_agent.planning import prepare_attempt
from nodes.ml_model_implementor.ml_model_implementor import MLModelImplementor
from tests.helpers.probe_seed import PROBE_SEED
from tests.helpers.run_seed import TEST_RUN_SEED
from workflows.model_exploration import (
    _commit_candidate_capabilities,
    _promote_loss_to_global,
)
from workflows.plugin_staging import stage_native_plugins
from workflows.task_composition import (
    bind_run_task_composition,
    build_task_composition_ref,
    compose_run_task_bindings,
)

MODEL = "fresh_loss_regressor"
LOSS = "fresh_marked_masked_mse"
OFFSET = 123.0


@pytest.fixture(autouse=True)
def _isolate_plugin_registries():
    from ml_models import (
        loss_models_sandbox,
        loss_plugin_loader,
        models_format_sandbox,
        models_sandbox,
        plugin_loader,
    )

    snapshots = []
    for module, names in (
        (models_sandbox, ("MODEL_REGISTRY",)),
        (models_format_sandbox, ("PLUGIN_CONFIG_REGISTRY",)),
        (plugin_loader, ("PLUGIN_OUTPUT_TYPE_REGISTRY", "_PLUGIN_MODEL_ORIGINS")),
        (loss_models_sandbox, ("LOSS_REGISTRY", "LOSS_CONFIG_REGISTRY", "LOSS_CONTRACT_REGISTRY")),
        (loss_plugin_loader, ("LOSS_TARGET_DTYPE_REGISTRY", "LOSS_REDUCTION_REGISTRY")),
    ):
        for name in names:
            registry = getattr(module, name)
            snapshots.append((registry, dict(registry)))
    from execute_tools.task_registration_scope import run_registration_scope

    try:
        with run_registration_scope():
            yield
    finally:
        for registry, before in snapshots:
            registry.clear()
            registry.update(before)


def _composition(tmp_path):
    checkout = Path(__file__).resolve().parents[4]
    original = checkout / "configs/task_composition/synthetic_masked_regression.yaml"
    declaration = yaml.safe_load(original.read_text())

    def resolve_paths(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"file", "dir", "config", "declaration"} and isinstance(item, str):
                    value[key] = str((original.parent / item).resolve())
                else:
                    resolve_paths(item)
        elif isinstance(value, list):
            for item in value:
                resolve_paths(item)

    resolve_paths(declaration)
    declaration.pop("objective")
    declaration.pop("loss_plugins")
    manifest = tmp_path / "composition.yaml"
    manifest.write_text(yaml.safe_dump(declaration))
    return compose_run_task_bindings(str(manifest))


def _pair():
    return torch.tensor([[0.2], [0.3]]), torch.tensor([[0.1, 1.0], [0.4, 1.0]])


def _proposal(composition):
    return ProposalOutput(
        model_name=MODEL,
        output_type="regressor",
        model_description="A linear regressor over three synthetic features.",
        mathematical_definition="y = Wx + b",
        motivation="Exercise new loss transport.",
        expert_advice=ExpertAdvice(),
        baseline_config={
            "model_config": {"model_type": MODEL, "segmentation_size": 3},
            "train_config": {"epochs": 1, "batch_size": 48, "device": "cpu", "lr": 0.001},
            "loss_config": {"loss_type": "custom", "loss_name": LOSS},
        },
        custom_loss_spec=CustomLossSpec(
            loss_name=LOSS,
            description="Masked squared error with a diagnostic offset.",
            mathematical_definition="mean((prediction - target)^2 on valid rows) + 123",
            contract_snapshot=custom_loss_snapshot_from_forward_contract(
                composition.forward_contract
            ),
        ),
    )


def _implementor():
    agent = MLModelImplementor.__new__(MLModelImplementor)
    agent._registry = CapabilityRegistry()
    agent.bridge = MagicMock()
    agent.bridge.generate_text.return_value = "Implement the declared linear model and masked loss."
    agent.bridge.generate.side_effect = [
        {
            "extra_imports": "",
            "config_fields_code": "    pass",
            "config_fields": {},
            "config_validators_code": "",
            "init_body": "        pass",
            "forward_body": (
                "        assert targets.dtype == torch.float32, 'Regression target dtype changed'\n"
                "        assert torch.any(targets[:, 0] != targets[:, 0].trunc()), "
                "'Fractional regression targets were lost'\n"
                "        valid = targets[:, 1] > 0.5\n"
                "        return ((inputs[:, 0] - targets[:, 0])[valid] ** 2).mean() + 123.0"
            ),
            "target_dtype": "float",
            "reduction": "mean",
        },
        {
            "extra_imports": "",
            "config_fields_code": "    pass",
            "config_fields": {},
            "init_body": "        self.linear = nn.Linear(3, 1)",
            "forward_body": "        return self.linear(x.float())",
        },
    ]
    return agent


def _admit(proposal, composition, storage):
    impl_input = local_full_spec(
        proposal, storage, task_composition_ref=build_task_composition_ref(composition)
    )
    impl_input.forward_contract = composition.forward_contract
    output = _implementor().run(impl_input)
    assert output.loss_provenance.action == "generated"
    assert output.loss_provenance.dummy_tensor_validated
    bridge = MagicMock()
    bridge.generate.return_value = LLMCodeReview(
        spec_alignment=True,
        trainability_concerns=[],
        implementation_issues=[],
        passed=True,
        notes="Synthetic fixture review.",
    ).model_dump()
    verdict = MLCodeValidatorAgent(bridge_factory=lambda **_: bridge, probe_seed=PROBE_SEED).run(
        local_all_fields(output, storage)
    )
    assert verdict.passed, verdict.error_message
    _commit_candidate_capabilities(output)
    workspace, run_name = storage.local.workspace, storage.local.run_name
    stage_native_plugins(
        output, MODEL, get_plugin_dir(workspace, run_name), get_loss_dir(workspace, run_name)
    )
    _promote_loss_to_global(output)
    return output, verdict


def _plan(composition, proposal, verdict, storage, sandbox):
    ref = build_task_composition_ref(composition)
    inp = local_validated_model(
        verdict,
        proposal,
        storage,
        max_rounds=1,
        task_composition_ref=ref,
        file_index=0,
        planner_strategy="native-timing-v1",
        is_trial=True,
        health_gate_enabled=False,
        run_seed=TEST_RUN_SEED,
    )
    inventory = resolve_run_custom_loss_inventory(
        CapabilityRegistry(), composition.forward_contract.model_io, ref
    )
    assert LOSS in inventory.names
    promoted = next(entry for entry in inventory.entries if entry.name == LOSS)
    assert "generated_library" in Path(promoted.file_path).parts
    brain = MagicMock()
    brain.plan.return_value = {
        **proposal.baseline_config,
        "model_type": MODEL,
        "hypothesis": "Execute the freshly admitted objective.",
        "reasoning": "Select the compatible generated loss.",
        "is_trial": True,
        "trial_strategy": "snapshot",
        "trial_portion": 1.0,
        "train_portion": 1.0,
        "eval_strategy": "snapshot",
        "eval_portion": 1.0,
        "train_validation_align": True,
    }
    bindings = RunBindings(
        agent_input=inp,
        sandbox=sandbox,
        brain=brain,
        custom_loss_inventory=inventory,
        run_profile=composition.dataset_profile,
        run_model_io=composition.forward_contract.model_io,
        run_deliverable_spec=None,
        run_metric=composition.metric,
        run_secondary_metrics=(),
        run_order=MetricOrder(composition.metric.spec),
        run_task_render=build_tuner_task_render(
            dataset=None,
            model_io_contract=composition.forward_contract.model_io,
            health_config=HealthChecksConfig(),
            efficiency_band_fraction=EFFICIENCY_BAND_FRACTION,
            composed=True,
        ),
        run_name=storage.local.run_name,
        workspace=storage.local.workspace,
        file_index=0,
        max_rounds=1,
        model_type_setting=MODEL,
        trial_allowed=True,
        resolved_data_scope=[0, 1],
        scope_is_partial=False,
        expert_advice_str="",
        config_manual_data=None,
        model_description=proposal.model_description,
        trial_vram_budget=None,
        formal_vram_budget=None,
        trial_time_budget=None,
        formal_time_budget=None,
        attempts_per_round_setting=1,
        attempts_per_formal_round_setting=1,
        max_fail_rounds_setting=1,
        formal_reference_score=None,
        formal_reference_source=None,
        resolved_skip_formal_threshold=None,
        resolved_bypass_formal_threshold=None,
        hardware_context=None,
        device_identity=None,
        time_data_dir=None,
        anchor_map_data=None,
        reference_scores=None,
        started_at="",
        health_checks_config_source=None,
        health_config_sha256=None,
        run_task_data_path=composition.task_data_path,
    )
    prepared = prepare_attempt(
        bindings,
        attempt_ordering=AttemptOrdering(),
        identity=AttemptIdentity(round_index=1, attempt_in_round=1, is_formal_round=False),
        total_attempts=1,
        attempts_this_round=1,
        formal_trial_winner=None,
    )
    assert brain.plan.call_args.kwargs["custom_loss_inventory"] is inventory
    assert prepared.active_params["loss_config"] == {"loss_type": "custom", "loss_name": LOSS}
    assert (
        prepared.active_params["expected_custom_loss_snapshot"]
        == proposal.custom_loss_spec.contract_snapshot
    )
    return prepared


@pytest.mark.allow_real_subprocess
def test_fresh_loss_reaches_native_cpu_training(tmp_path, monkeypatch):
    env = {}
    workspace = tmp_path / "workspace"
    bind_generated_library_to_workspace(str(workspace), environ=env)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    composition = _composition(tmp_path)
    task = composition.task_data_path
    monkeypatch.setattr(
        type(task), "custom_loss_validation_pair", staticmethod(_pair), raising=False
    )
    bundle = sys.modules[type(task).__module__].materialize_run_bundle(tmp_path / "data")
    storage = StorageConfig(
        backend="local", local=LocalStorageConfig(workspace=str(workspace), run_name="fresh")
    )
    with bind_run_task_composition(composition, physical_data_root=bundle["data_dir"]):
        proposal = _proposal(composition)
        output, verdict = _admit(proposal, composition, storage)
        sandbox = TidmadSandbox(
            workspace=str(workspace), run_name="fresh", file_index=0, progress_bar=False
        )
        prepared = _plan(composition, proposal, verdict, storage, sandbox)
        params = prepared.active_params
        trained = sandbox.execute_training(
            params["exp_id"],
            params["run_name"],
            params["model_type"],
            params["model_config"],
            params["train_config"],
            params["loss_config"],
            seed_context=SeedContext(run_seed=17),
            execution_bindings=TrainingExecutionBindings(
                task_scopes=params["task_scopes"],
                expected_custom_loss_snapshot=params["expected_custom_loss_snapshot"],
            ),
        )
    assert trained["status"] == "success", trained
    loss_path = Path(sandbox.dirs["configs"]) / f"loss_config_{prepared.exp_id}.json"
    persisted_loss = json.loads(loss_path.read_text())
    assert persisted_loss["loss_type"] == "custom"
    assert persisted_loss["loss_name"] == LOSS
    history = trained["results"]["training_history"]
    assert len(history["train_objective"]) == 1
    assert len(history["validation_objective"]) == 1
    assert all(OFFSET <= value < OFFSET + 100 for value in history["train_objective"])
    assert all(OFFSET <= value < OFFSET + 100 for value in history["validation_objective"])
    assert history["objective_kind"] == "custom"
    assert output.loss_provenance.loss_name == LOSS
