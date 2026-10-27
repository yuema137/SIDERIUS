"""Reconcile captured native inputs with the selected task and managed storage.

Imported only after the child binds its generated library. This is a closed
candidate boundary with optional native training, not an arbitrary protocol executor.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import TypeAdapter

from agent.llm_settings import default_model_for_provider
from agent.schemas.constraint_disclosure import ConstraintContext
from agent.schemas.hyperparam_tuning import TaskCompositionRef
from agent.schemas.parameter_rules import ParameterRules
from agent.schemas.proposal import ProposalInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from nodes.llm_settings import VALIDATE
from workflows.attempt_storage import ImplAttemptStorage, impl_attempt_storage
from workflows.definition import ExternalRequest, ExternalSource, ProtocolRequest
from workflows.definition.candidate import candidate_nodes
from workflows.definition.catalog import PROTOCOLS
from workflows.definition.models import ExternalBinding
from workflows.llm_config import WorkflowLLMConfig
from workflows.task_composition import RunTaskComposition, build_task_composition_ref

from .layout import candidate_proposal_dir
from .models import CandidateRunRequest

if TYPE_CHECKING:
    from .training_admission import TrainingAdmission


@dataclass(frozen=True)
class NativeInputs:
    proposal: ProposalInput
    attempt: ImplAttemptStorage
    validator_provider: Literal["gemini", "openai", "deepseek"]
    validator_model: str


def require_storage(actual: StorageConfig, expected: StorageConfig) -> None:
    if actual.backend != "local" or actual.local is None or expected.local is None:
        raise ValueError("candidate worker requires local managed storage")
    if (Path(actual.local.workspace).resolve(), actual.local.run_name) != (
        Path(expected.local.workspace).resolve(),
        expected.local.run_name,
    ):
        raise ValueError("external storage disagrees with managed storage")


def check_constraints(
    context: ConstraintContext | None,
    ref: TaskCompositionRef,
    *,
    workflow_rules: ParameterRules | None,
    trial_time_budget_minutes: float | None,
    formal_time_budget_minutes: float | None,
    vram_budget_gb: float | None,
) -> None:
    if context is None:
        return
    expected = {
        "task_rules": ref.parameter_rules,
        "workflow_rules": workflow_rules,
        "objective": ref.objective.model_dump(mode="json") if ref.objective else None,
    }
    for name, value in expected.items():
        actual = getattr(context, name)
        if (name in context.known_sections or actual is not None) and actual != value:
            raise ValueError(f"constraint_context.{name} disagrees with native authority")
    if context.overrides:
        raise ValueError("constraint_context.overrides has no candidate worker authority")
    if context.timing is not None:
        raise ValueError("constraint_context.timing has no candidate worker authority")
    if context.execution is not None:
        supported = {
            "trial_time_budget_minutes",
            "formal_time_budget_minutes",
            "trial_vram_budget_gb",
            "formal_vram_budget_gb",
        }
        for name, value in context.execution.model_dump().items():
            if name not in supported and value is not None:
                raise ValueError(
                    f"constraint_context.execution.{name} has no candidate worker authority"
                )
        known = "execution" in context.known_sections
        for name, expected_value in (
            ("trial_time_budget_minutes", trial_time_budget_minutes),
            ("formal_time_budget_minutes", formal_time_budget_minutes),
        ):
            value = getattr(context.execution, name)
            if (known or value is not None) and value != expected_value:
                raise ValueError(f"constraint_context.execution.{name} disagrees with seed")
        budgets = (context.execution.trial_vram_budget_gb, context.execution.formal_vram_budget_gb)
        selected = budgets[0] if budgets[0] is not None else budgets[1]
        if (known or selected is not None) and selected != vram_budget_gb:
            raise ValueError("constraint_context execution VRAM disagrees with seed")


def materialize_proposal(
    payload: bytes,
    *,
    proposal_storage: StorageConfig,
    composition: RunTaskComposition,
    data_root: Path,
    control: Path,
    admitted: "TrainingAdmission | None" = None,
    debug_root: Path | None = None,
) -> tuple[ProposalInput, TaskCompositionRef]:
    """Reconcile one selected seed with explicit managed storage and task authority."""
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise ValueError("proposal seed must be a JSON object")
    required = {
        "task_description",
        "forward_contract",
        "proposal_blocks",
        "task_composition_ref",
        "data_dir",
    }
    if not required.issubset(raw):
        raise ValueError(
            f"proposal seed omits task/execution facts: {sorted(required - raw.keys())}"
        )
    if "storage" not in raw:
        raw["storage"] = proposal_storage.model_dump(mode="json")
    seed = ProposalInput.model_validate(raw)
    require_storage(seed.storage, proposal_storage)
    seed.storage = proposal_storage
    ref = build_task_composition_ref(composition)
    assert ref is not None
    for name, expected in (
        ("task_description", composition.task_description),
        ("forward_contract", composition.forward_contract),
        ("proposal_blocks", composition.proposal_blocks),
        ("task_composition_ref", ref),
    ):
        if getattr(seed, name) != expected:
            raise ValueError(f"proposal seed {name} disagrees with composed task")
    if seed.data_dir is None or Path(seed.data_dir).resolve() != data_root:
        raise ValueError("proposal seed data_dir disagrees with selected physical root")
    debug_root = control / "debug" if debug_root is None else debug_root
    debug = seed.debug_dump_proposing_prompt_path
    if debug is not None and (
        not Path(debug).is_absolute() or not Path(debug).resolve().is_relative_to(debug_root)
    ):
        raise ValueError("debug prompt path must be inside candidate_run/debug")
    if admitted is None:
        check_constraints(
            seed.constraint_context,
            ref,
            workflow_rules=seed.workflow_parameter_rules,
            trial_time_budget_minutes=seed.trial_time_budget_minutes,
            formal_time_budget_minutes=seed.formal_time_budget_minutes,
            vram_budget_gb=seed.vram_budget_gb,
        )
    else:
        from .training_admission import reconcile_proposal

        seed = reconcile_proposal(seed, admitted)
    return seed, ref


def reconcile_protocol_inputs(
    protocols: tuple[ProtocolRequest, ...],
    *,
    contents: Mapping[str, bytes],
    externals: Mapping[str, ExternalBinding],
    seed: ProposalInput,
    ref: TaskCompositionRef,
    attempt: ImplAttemptStorage,
    provider: Literal["gemini", "openai", "deepseek"],
    model: str,
    admitted: "TrainingAdmission | None" = None,
) -> set[str]:
    """Check explicit protocol externals; return exactly the bindings consumed."""
    # Only these native scalar/protocol schemas may cross external boundaries.
    schemas = {
        "storage": TypeAdapter(StorageConfig),
        "optional.constraint-context": TypeAdapter(ConstraintContext | None),
        "optional.task-composition-ref": TypeAdapter(TaskCompositionRef | None),
        "llm-provider": TypeAdapter(Literal["gemini", "openai", "deepseek"]),
        "optional.model-id": TypeAdapter(str | None),
    }
    used: set[str] = set()
    for protocol in protocols:
        for argument in protocol.arguments:
            contract = next(
                item.contract
                for item in PROTOCOLS[protocol.protocol].arguments
                if item.name == argument.name
            )
            if contract in ("proposal.output", "implementation.output"):
                continue  # declaration admission proves the selected typed result edge
            if not isinstance(argument.source, ExternalSource):
                raise ValueError("only upstream output may be supplied by a result")
            binding = externals[argument.source.binding]
            used.add(binding.id)
            if binding.contract not in schemas:
                raise ValueError(f"unsupported native external: {binding.contract}")
            value = schemas[binding.contract].validate_json(contents[f"external.{binding.id}"])
            if argument.name == "storage":
                require_storage(value, attempt.storage)
            else:
                authority = {
                    "constraint_context": seed.constraint_context,
                    "task_composition_ref": ref,
                    "llm_provider": provider,
                    "llm_model_id": model,
                }[argument.name]
                if argument.name == "constraint_context" and admitted is not None:
                    from .training_admission import reconcile_constraints

                    reconcile_constraints(value, seed.constraint_context)
                    continue
                if value != authority:
                    raise ValueError(f"protocol {argument.name} disagrees with resolved authority")
    return used


def materialize(
    request: CandidateRunRequest,
    workspace: Path,
    composition: RunTaskComposition,
    config: WorkflowLLMConfig,
    admitted: "TrainingAdmission | None" = None,
) -> NativeInputs:
    definition = request.preview.document.definition
    control = workspace / "candidate_run"
    contents = {
        item.reference: (control / f"input_{index:03}.snapshot").read_bytes()
        for index, item in enumerate(request.files)
    }
    selected = candidate_nodes(definition)
    by_id = {node.id: node for node in definition.nodes}
    nodes = {role: by_id[node_id] for role, node_id in selected.items()}
    proposal_request = nodes["proposal"].request
    assert isinstance(proposal_request, ExternalRequest)
    proposal_storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(
            workspace=str(candidate_proposal_dir(workspace, request.run_name)),
            run_name=request.run_name,
        ),
    )
    assert proposal_storage.local is not None
    attempt = impl_attempt_storage(proposal_storage.local.workspace, request.run_name, 1)
    seed, ref = materialize_proposal(
        contents[f"external.{proposal_request.binding}"],
        proposal_storage=proposal_storage,
        composition=composition,
        data_root=(Path(request.preview.project_root) / definition.task.data_root).resolve(),
        control=control,
        admitted=admitted,
    )
    provider, model = validator_settings(config)
    externals = {item.id: item for item in definition.externals}
    used = {proposal_request.binding}
    if admitted is not None:
        tuning = nodes["tuning"].request
        assert isinstance(tuning, ProtocolRequest)
        source = next(arg.source for arg in tuning.arguments if arg.name == "settings")
        assert isinstance(source, ExternalSource)
        used.add(source.binding)
    implementation = nodes["implementation"].request
    validation = nodes["validation"].request
    assert isinstance(implementation, ProtocolRequest) and isinstance(validation, ProtocolRequest)
    used.update(
        reconcile_protocol_inputs(
            (implementation, validation),
            contents=contents,
            externals=externals,
            seed=seed,
            ref=ref,
            attempt=attempt,
            provider=provider,
            model=model,
            admitted=admitted,
        )
    )
    if used != set(externals):
        raise ValueError("unused external inputs are unsupported by the candidate worker")
    return NativeInputs(seed, attempt, provider, model)


def validator_settings(
    config: WorkflowLLMConfig,
) -> tuple[Literal["gemini", "openai", "deepseek"], str]:
    """Resolve the native validator defaults once for fixed and instance layouts."""
    validator = config.get("validate")
    provider = TypeAdapter(Literal["gemini", "openai", "deepseek"]).validate_python(
        validator.get("provider", VALIDATE.provider)
    )
    model = validator.get("model_id", VALIDATE.model_id) or default_model_for_provider(provider)
    return provider, model
