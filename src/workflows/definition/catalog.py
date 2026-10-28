"""Closed, inert catalog of audited native request/protocol boundaries.

Strings identify owners; they are never dynamically imported or executed.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


@dataclass(frozen=True)
class CapabilityContract:
    input: str
    output: str


@dataclass(frozen=True)
class ArgumentContract:
    name: str
    contract: str
    required: bool = True


@dataclass(frozen=True)
class ProtocolContract:
    owner: str
    output: str
    arguments: tuple[ArgumentContract, ...]


CONTRACTS = MappingProxyType(
    {
        "interpretation.input": "agent.schemas.interpretation.InterpretationInput",
        "interpretation.output": "agent.schemas.interpretation.InterpretationOutput",
        "optional.text": "str | None",
        "optional.expert-advice": "agent.schemas.hyperparam_tuning.ExpertAdviceInput | None",
        "optional.expert-context": "list[agent.schemas.proposal.ExpertContextItem] | None",
        "optional.parameter-rules": "agent.schemas.parameter_rules.ParameterRules | None",
        "literature.input": "agent.schemas.literature_review.LiteratureReviewInput",
        "literature.output": "agent.schemas.literature_review.LiteratureReviewOutput",
        "proposal.input": "agent.schemas.proposal.ProposalInput",
        "proposal.output": "agent.schemas.proposal.ProposalOutput",
        "implementation.input": "agent.schemas.implementor.ImplementorInput",
        "implementation.output": "agent.schemas.implementor.ImplementorOutput",
        "validation.input": "agent.schemas.validator.ValidatorInput",
        "validation.output": "agent.schemas.validator.ValidatorOutput",
        "tuning.input": "agent.schemas.hyperparam_tuning.HyperparamTuningInput",
        "tuning.output": "agent.schemas.hyperparam_tuning.HyperparamTuningOutput",
        "native-training.settings": "workflows.candidate_training_settings.CandidateTrainingSettings",
        "storage": "agent.schemas.storage.StorageConfig",
        "optional.constraint-context": "agent.schemas.constraint_disclosure.ConstraintContext | None",
        "optional.task-composition-ref": "agent.schemas.hyperparam_tuning.TaskCompositionRef | None",
        "llm-provider": "Literal['gemini', 'openai', 'deepseek', 'anthropic', 'moonshot', 'zai']",
        "optional.model-id": "str | None",
    }
)

CAPABILITIES = MappingProxyType(
    {
        "interpretation": CapabilityContract("interpretation.input", "interpretation.output"),
        "literature": CapabilityContract("literature.input", "literature.output"),
        "proposal": CapabilityContract("proposal.input", "proposal.output"),
        "implementation": CapabilityContract("implementation.input", "implementation.output"),
        "tuning": CapabilityContract("tuning.input", "tuning.output"),
        "validation": CapabilityContract("validation.input", "validation.output"),
    }
)

PROTOCOLS = MappingProxyType(
    {
        "interpretation-to-proposal": ProtocolContract(
            "agent.schemas.protocols.ml_result_interp_to_ml_model_propose.local_full_context",
            "proposal.input",
            (
                ArgumentContract("output", "interpretation.output"),
                ArgumentContract("storage", "storage"),
                ArgumentContract("data_dir", "optional.text", False),
                ArgumentContract("task_composition_ref", "optional.task-composition-ref", False),
                ArgumentContract("human_advice", "optional.expert-advice", False),
                ArgumentContract("expert_context", "optional.expert-context", False),
                ArgumentContract("constraint_context", "optional.constraint-context", False),
                ArgumentContract("workflow_parameter_rules", "optional.parameter-rules", False),
            ),
        ),
        "literature-to-proposal": ProtocolContract(
            "agent.schemas.protocols.ml_literature_review_to_ml_model_propose.local_typed_evidence",
            "proposal.input",
            (
                ArgumentContract("output", "literature.output"),
                ArgumentContract("proposal_input", "proposal.input"),
            ),
        ),
        "validated-candidate-to-tuning": ProtocolContract(
            "tools.candidate_worker.training.prepare_tuning_request",
            "tuning.input",
            (
                ArgumentContract("validation", "validation.output"),
                ArgumentContract("proposal", "proposal.output"),
                ArgumentContract("settings", "native-training.settings"),
            ),
        ),
        "proposal-to-implementation": ProtocolContract(
            "agent.schemas.protocols.ml_model_propose_to_ml_model_impl.local_full_spec",
            "implementation.input",
            (
                ArgumentContract("output", "proposal.output"),
                ArgumentContract("storage", "storage"),
                ArgumentContract("constraint_context", "optional.constraint-context", False),
                ArgumentContract("task_composition_ref", "optional.task-composition-ref", False),
            ),
        ),
        "proposed-implementation-to-validation": ProtocolContract(
            "workflows.candidate_validation_join.proposed_implementation_to_validation",
            "validation.input",
            (
                ArgumentContract("proposal", "proposal.output"),
                ArgumentContract("implementation", "implementation.output"),
                ArgumentContract("storage", "storage"),
                ArgumentContract("llm_provider", "llm-provider", False),
                ArgumentContract("llm_model_id", "optional.model-id", False),
                ArgumentContract("constraint_context", "optional.constraint-context", False),
            ),
        ),
        "implementation-to-validation": ProtocolContract(
            "agent.schemas.protocols.ml_model_impl_to_ml_model_valid.local_all_fields",
            "validation.input",
            (
                ArgumentContract("output", "implementation.output"),
                ArgumentContract("storage", "storage"),
                ArgumentContract("llm_provider", "llm-provider", False),
                ArgumentContract("llm_model_id", "optional.model-id", False),
                ArgumentContract("constraint_context", "optional.constraint-context", False),
            ),
        ),
    }
)


@dataclass(frozen=True)
class RouteObservable:
    """One readable native output field; ``field`` is documentation, never a lookup path."""

    contract: str
    field: str
    kind: Literal["bool", "enum", "metric"]
    values: tuple[str, ...] = ()


# Closed list of fields a route predicate may read. Adding one requires the
# native-schema drift test; predicates never name free fields or JSON paths.
ROUTE_OBSERVABLES = MappingProxyType(
    {
        "validation.passed": RouteObservable(
            "validation.output", "agent.schemas.validator.ValidatorOutput.passed", "bool"
        ),
        "tuning.status": RouteObservable(
            "tuning.output",
            "agent.schemas.hyperparam_tuning.HyperparamTuningOutput.status",
            "enum",
            ("completed", "partial", "failed"),
        ),
        "tuning.valid_formal": RouteObservable(
            "tuning.output",
            "agent.schemas.hyperparam_tuning.HyperparamTuningOutput"
            ".best_valid_formal_denoising_score",
            "metric",
        ),
    }
)
