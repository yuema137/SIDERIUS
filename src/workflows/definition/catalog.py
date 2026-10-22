"""Closed, inert catalog of audited native request/protocol boundaries.

Strings identify owners; they are never dynamically imported or executed.
"""

from dataclasses import dataclass
from types import MappingProxyType


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
        "proposal.input": "agent.schemas.proposal.ProposalInput",
        "proposal.output": "agent.schemas.proposal.ProposalOutput",
        "implementation.input": "agent.schemas.implementor.ImplementorInput",
        "implementation.output": "agent.schemas.implementor.ImplementorOutput",
        "validation.input": "agent.schemas.validator.ValidatorInput",
        "validation.output": "agent.schemas.validator.ValidatorOutput",
        "storage": "agent.schemas.storage.StorageConfig",
        "optional.constraint-context": "agent.schemas.constraint_disclosure.ConstraintContext | None",
        "optional.task-composition-ref": "agent.schemas.hyperparam_tuning.TaskCompositionRef | None",
        "llm-provider": "Literal['gemini', 'openai', 'deepseek']",
        "optional.model-id": "str | None",
    }
)

CAPABILITIES = MappingProxyType(
    {
        "proposal": CapabilityContract("proposal.input", "proposal.output"),
        "implementation": CapabilityContract("implementation.input", "implementation.output"),
        "validation": CapabilityContract("validation.input", "validation.output"),
    }
)

PROTOCOLS = MappingProxyType(
    {
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
