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


@dataclass(frozen=True)
class ProtectedField:
    """One framework-owned location inside a custom-adaptor output contract.

    ``path`` is dotted; ``[]`` addresses every list element. ``unset`` requires
    the author to leave the value absent/None/empty, ``stamp-source`` additionally
    lets the framework write the adaptor provenance label there, and
    ``forbid-value`` refuses exactly ``value``.
    """

    path: str
    rule: Literal["unset", "stamp-source", "forbid-value"]
    value: str | None = None


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

#: Contracts a custom adaptor COMBINE may emit (operator decision B6-D3 = B).
#: Authority contracts (validation, tuning, interpretation), capability inputs,
#: storage, constraints, parameter rules and task references are never
#: emittable. Widening this set is a reviewed catalog change.
CUSTOM_EMITTABLE = frozenset(
    {
        "optional.expert-context",
        "optional.expert-advice",
        "optional.text",
        "proposal.output",
        "literature.output",
    }
)


def _context_item_rules(prefix: str) -> tuple[ProtectedField, ...]:
    """`ExpertContextItem`: framework-stamped producer; never human or chain-mode findings."""
    return (
        ProtectedField(f"{prefix}source", "stamp-source"),
        ProtectedField(f"{prefix}kind", "forbid-value", "human"),
        ProtectedField(f"{prefix}kind", "forbid-value", "findings"),
    )


def _vocab_entry_rules(prefix: str) -> tuple[ProtectedField, ...]:
    """`VocabEntry`: external origin, no run attribution, never canonical."""
    return (
        ProtectedField(f"{prefix}origin", "stamp-source"),
        ProtectedField(f"{prefix}proposed_by_run", "unset"),
        ProtectedField(f"{prefix}seen_in_runs", "unset"),
        ProtectedField(f"{prefix}tier", "forbid-value", "canonical"),
    )


#: Framework-owned fields of every emittable contract. The author leaves them
#: unset; the framework stamps provenance after validation. Any other value is
#: refused, never silently replaced.
PROTECTED_FIELDS = MappingProxyType(
    {
        "optional.expert-context": _context_item_rules("[]."),
        "optional.expert-advice": (),
        "optional.text": (),
        "proposal.output": (
            ProtectedField("candidate_id", "unset"),
            ProtectedField("observed_prediction_reference", "unset"),
            ProtectedField("preflight_estimated_minutes", "unset"),
            ProtectedField("preflight_factor", "unset"),
            *_vocab_entry_rules("proposed_discoveries[]."),
        ),
        "literature.output": (
            ProtectedField("agent_card.agent_name", "stamp-source"),
            ProtectedField("agent_card.trust_level", "forbid-value", "hard_limit"),
            ProtectedField("run_name", "stamp-source"),
            *_context_item_rules("findings[]."),
            *_vocab_entry_rules("new_vocab_candidates[]."),
            ProtectedField("search_decisions", "unset"),
        ),
    }
)
