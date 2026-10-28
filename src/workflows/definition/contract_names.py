"""Single owner of the human-facing names of catalog contract schemas.

A name names the SCHEMA a contract carries (its semantic type where declared,
otherwise its native type ignoring an optional ``| None`` wrapper), never a module and never a direction: the same schema shows
the same name on an input socket, an output socket, the palette, the legend and in
documents, whichever modules exchange it. Contract ids in
:data:`workflows.definition.catalog.CONTRACTS` remain the identity and the
compatibility key; names, descriptions and kinds are presentation only. Future
modules and adaptors reuse an existing schema name rather than inventing one.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from .catalog import CONTRACTS

ContractKind = Literal["produced", "external", "setting"]
"""Where a value of the schema comes from, never a direction: ``produced`` is made
inside the workflow (a module's result, or a brief a declared mapping assembles);
``external`` is a resource you provide; ``setting`` is guidance or configuration
you provide. Sockets show direction with arrows, not names."""

ADAPTOR_ARROW = " → "
OPTIONAL_SUFFIX = " | None"

# Semantic schema types for contracts whose native type is a bare primitive. Two
# catalog ids carry ``str | None`` with different meanings and stay separate
# (not interconnectable), so each is keyed by its own semantic type here. These
# labels are local to the definition catalog: native signatures, contract ids and
# wire formats are unchanged.
DATA_FOLDER_PATH = "semantic.DataFolderPath"
LANGUAGE_MODEL_NAME = "semantic.LanguageModelName"
SEMANTIC_SCHEMAS = MappingProxyType(
    {"optional.text": DATA_FOLDER_PATH, "optional.model-id": LANGUAGE_MODEL_NAME}
)


@dataclass(frozen=True)
class SchemaName:
    name: str
    description: str
    kind: ContractKind


# Keyed by the catalog native type label without its optional wrapper.
SCHEMA_NAMES = MappingProxyType(
    {
        "agent.schemas.interpretation.InterpretationInput": SchemaName(
            "Run summaries",
            "Condensed summaries of one or more finished training runs.",
            "produced",
        ),
        "agent.schemas.interpretation.InterpretationOutput": SchemaName(
            "Results analysis",
            "A reading of run results with per-model scores and the best and worst models.",
            "produced",
        ),
        "agent.schemas.literature_review.LiteratureReviewInput": SchemaName(
            "Search evidence",
            "Evidence from earlier analysis that a literature search looks for papers about.",
            "produced",
        ),
        "agent.schemas.literature_review.LiteratureReviewOutput": SchemaName(
            "Paper findings",
            "Findings from published papers, with the retrieved papers behind them.",
            "produced",
        ),
        "agent.schemas.proposal.ProposalInput": SchemaName(
            "Design brief",
            "Everything needed to design the next model.",
            "produced",
        ),
        "agent.schemas.proposal.ProposalOutput": SchemaName(
            "Model plan",
            "A complete model specification, ready to implement and train.",
            "produced",
        ),
        "agent.schemas.implementor.ImplementorInput": SchemaName(
            "Coding brief",
            "A model plan with run context, ready to be turned into code.",
            "produced",
        ),
        "agent.schemas.implementor.ImplementorOutput": SchemaName(
            "Model code",
            "Paths of the written model source files.",
            "produced",
        ),
        "agent.schemas.validator.ValidatorInput": SchemaName(
            "Review brief",
            "Model code with its context, ready to be checked before training.",
            "produced",
        ),
        "agent.schemas.validator.ValidatorOutput": SchemaName(
            "Code verdict",
            "A verdict on whether the model code is safe to train.",
            "produced",
        ),
        "agent.schemas.hyperparam_tuning.HyperparamTuningInput": SchemaName(
            "Training job",
            "A validated model with its training settings, ready to be trained and tuned.",
            "produced",
        ),
        "agent.schemas.hyperparam_tuning.HyperparamTuningOutput": SchemaName(
            "Training report",
            "The full report of a completed training and tuning run.",
            "produced",
        ),
        "workflows.candidate_training_settings.CandidateTrainingSettings": SchemaName(
            "Training settings",
            "Training launch and startup controls that you provide in a settings file.",
            "setting",
        ),
        "agent.schemas.storage.StorageConfig": SchemaName(
            "Storage folder",
            "Where records and outputs are written; you provide it.",
            "external",
        ),
        "Literal['gemini', 'openai', 'deepseek', 'anthropic', 'moonshot', 'zai']": SchemaName(
            "Language model provider",
            "Which language model service is called, such as openai or anthropic.",
            "external",
        ),
        DATA_FOLDER_PATH: SchemaName(
            "Data folder",
            "The path of the folder that holds the task's data, as you provide it.",
            "external",
        ),
        LANGUAGE_MODEL_NAME: SchemaName(
            "Language model name",
            "An exact model name at the chosen service; when omitted, the service's "
            "default model is used.",
            "external",
        ),
        "agent.schemas.hyperparam_tuning.ExpertAdviceInput": SchemaName(
            "Expert advice",
            "Advice written by a person for a module to consider.",
            "setting",
        ),
        "list[agent.schemas.proposal.ExpertContextItem]": SchemaName(
            "Expert notes",
            "Context items from people or analysis modules that inform a model design.",
            "setting",
        ),
        "agent.schemas.parameter_rules.ParameterRules": SchemaName(
            "Parameter rules",
            "Limits on which model and training parameters may change and how.",
            "setting",
        ),
        "agent.schemas.constraint_disclosure.ConstraintContext": SchemaName(
            "Run constraints",
            "A statement of the known run restrictions and who declared them.",
            "setting",
        ),
        "agent.schemas.hyperparam_tuning.TaskCompositionRef": SchemaName(
            "Task reference",
            "A pointer to the run's task declaration, never a second copy of it.",
            "external",
        ),
    }
)


def contract_schema(contract_id: str) -> str:
    """Schema a contract carries: its semantic type when declared, otherwise the
    native type label without its optional wrapper."""
    native = CONTRACTS[contract_id].removesuffix(OPTIONAL_SUFFIX)
    return SEMANTIC_SCHEMAS.get(contract_id, native)


def contract_name(contract_id: str) -> SchemaName:
    """Presentation of one catalog contract's schema; an unknown id is a ``KeyError``."""
    return SCHEMA_NAMES[contract_schema(contract_id)]


def adaptor_name(source_contract: str, target_contract: str) -> str:
    """Name of an adaptor converting one schema into another: ``<from> → <to>``.

    Both ids must be catalog contracts; an adaptor between contracts carrying the
    same schema is meaningless and is refused.
    """
    source, target = contract_name(source_contract), contract_name(target_contract)
    if source == target:
        raise ValueError("An adaptor joins two different schemas")
    return source.name + ADAPTOR_ARROW + target.name
