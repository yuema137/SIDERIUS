"""Typed transport for one graph node dispatched to its own process (B3-3).

A `NodeInvocation` carries every value the in-process dispatch passed to a
native phase: the run arguments of `execute_fanout`, the selected typed input,
the typed predecessor outputs and, for tuning, the admitted training facts. The
child rebuilds only what the parent had bound ambiently (the task composition,
verified by its semantic fingerprint). A `NodeUnitResult` carries the phase
output back. Neither crosses the boundary unless it round-trips exactly,
including which fields were explicitly set, because protocol mappings and
reconciliation read `model_fields_set`.
"""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from agent.schemas.constraint_disclosure import ConstraintContext
from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.interpretation import InterpretationInput, InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewInput, LiteratureReviewOutput
from agent.schemas.ordering import OrderStrategy
from agent.schemas.proposal import ProposalOutput
from agent.schemas.storage import StorageConfig
from agent.schemas.validator import ValidatorOutput
from core.hardware_models import HardwareContext
from core.run_invariants import RunInvariants
from core.runtime_control.measurement_capability import ResolvedMeasurementCapability
from core.runtime_control.observed_subprocess import ProcessLifecycle
from execute_tools.dataset_config import DataScope
from workflows.candidate_training_settings import CandidateTrainingSettings
from workflows.llm_config import WorkflowLLMConfig
from workflows.run_bindings import WorkflowRunBindings
from workflows.task_composition import RunTaskComposition

from .inputs import NativeInputs
from .invocation import NativePhase
from .models import CandidateRunReceipt, CandidateRunRequest
from .training_admission import TrainingAdmission

_FROZEN = ConfigDict(frozen=True, extra="forbid")

NodeOutput = (
    ProposalOutput
    | ImplementorOutput
    | ValidatorOutput
    | LiteratureReviewOutput
    | InterpretationOutput
    | HyperparamTuningOutput
)
OUTPUT_TYPES: dict[NativePhase, type[NodeOutput]] = {
    "proposal": ProposalOutput,
    "implementation": ImplementorOutput,
    "validation": ValidatorOutput,
    "literature": LiteratureReviewOutput,
    "interpretation": InterpretationOutput,
    "tuning": HyperparamTuningOutput,
}


class AdmittedTraining(BaseModel):
    """`TrainingAdmission` without the run-scoped composition and LLM config.

    Those two are the child's own re-bound values; every other admitted
    binding travels here. `admission_from` refuses a binding this model does
    not carry, so a new admitted field cannot be dropped silently.
    """

    model_config = _FROZEN
    settings: CandidateTrainingSettings
    constraints: ConstraintContext | None
    node_id: str
    workspace: str
    run_name: str
    run_dir: str
    run_id: str | None
    data_scope: DataScope | None
    resolved_data_scope: tuple[int, ...]
    scope_is_partial: bool
    run_invariants: RunInvariants | None
    health_gate_enabled: bool
    health_gate_files: tuple[int, ...] | None
    health_checks_config: str | None
    order_strategy_override: OrderStrategy | None
    file_order_override: tuple[int, ...] | None
    enable_structured_health_feedback: bool
    measurement_capability: ResolvedMeasurementCapability | None
    hardware_context: HardwareContext | None
    active_vram_budget_gb: float | None

    def restore(
        self, composition: RunTaskComposition, config: WorkflowLLMConfig
    ) -> TrainingAdmission:
        values = {name: getattr(self, name) for name in _binding_fields()}
        return TrainingAdmission(
            self.settings,
            WorkflowRunBindings(**values, task_composition=composition, llm_config=config),
            self.constraints,
            self.node_id,
        )


def _binding_fields() -> tuple[str, ...]:
    return tuple(
        name
        for name in AdmittedTraining.model_fields
        if name not in ("settings", "constraints", "node_id")
    )


def admission_from(
    admitted: TrainingAdmission, composition: RunTaskComposition, config: WorkflowLLMConfig
) -> AdmittedTraining:
    transport = AdmittedTraining(
        settings=admitted.settings,
        constraints=admitted.constraints,
        node_id=admitted.node_id,
        **{name: getattr(admitted.bindings, name) for name in _binding_fields()},
    )
    if transport.restore(composition, config) != admitted:
        raise ValueError("training admission carries a binding the unit transport omits")
    return transport


class ProposalUnit(BaseModel):
    model_config = _FROZEN
    phase: Literal["proposal"]
    inputs: NativeInputs


class ImplementationUnit(BaseModel):
    model_config = _FROZEN
    phase: Literal["implementation"]
    inputs: NativeInputs
    proposal: ProposalOutput


class ValidationUnit(BaseModel):
    model_config = _FROZEN
    phase: Literal["validation"]
    inputs: NativeInputs
    proposal: ProposalOutput
    implementation: ImplementorOutput


class LiteratureUnit(BaseModel):
    model_config = _FROZEN
    phase: Literal["literature"]
    inputs: LiteratureReviewInput


class InterpretationUnit(BaseModel):
    model_config = _FROZEN
    phase: Literal["interpretation"]
    inputs: InterpretationInput


class TuningUnit(BaseModel):
    model_config = _FROZEN
    phase: Literal["tuning"]
    proposal: ProposalOutput
    implementation: ImplementorOutput
    validation: ValidatorOutput
    admission: AdmittedTraining
    chain_formal_incumbent_reference: float | None


PhaseUnit = Annotated[
    ProposalUnit
    | ImplementationUnit
    | ValidationUnit
    | LiteratureUnit
    | InterpretationUnit
    | TuningUnit,
    Field(discriminator="phase"),
]


class NodeInvocation(BaseModel):
    """One dispatched graph node: `execute_fanout` arguments plus its phase payload.

    `manifest_path`, `composition_fingerprint` and `physical_data_root` describe
    the composition the parent had bound; the child recomposes and refuses a
    different fingerprint before any native effect.
    """

    model_config = _FROZEN
    request: CandidateRunRequest
    initial: CandidateRunReceipt
    config: WorkflowLLMConfig
    manifest_path: str
    composition_fingerprint: str
    physical_data_root: str
    node_id: str
    iteration: PositiveInt
    storage: StorageConfig
    unit: PhaseUnit


class NodeUnitResult(BaseModel):
    """Terminal outcome of one unit process.

    `returned` carries the phase output and its native record path. `raised`
    is an ordinary native exception (its traceback is already in the worker
    log). `exited` and `interrupted` are `SystemExit` and `KeyboardInterrupt`,
    which the parent re-raises exactly as the in-process dispatch propagated
    them. `lifecycles` are the child's observed subprocess lifecycles, replayed
    to the parent's lifecycle observer in order.
    """

    model_config = _FROZEN
    node_id: str
    phase: NativePhase
    outcome: Literal["returned", "raised", "exited", "interrupted"]
    output: str | None = None
    record_path: str | None = None
    exit_code: int | str | None = None
    lifecycles: tuple[ProcessLifecycle, ...] = ()


def unit_paths(initial: CandidateRunReceipt, node_id: str, *, iteration: int) -> tuple[Path, Path]:
    """Write-once invocation and result of one node in one body."""
    from .layout import candidate_control_dir

    directory = (
        candidate_control_dir(Path(initial.workspace), iteration=iteration) / "units" / node_id
    )
    return directory / "invocation.json", directory / "result.json"
