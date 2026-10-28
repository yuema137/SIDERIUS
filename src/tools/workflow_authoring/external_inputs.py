"""Presentation of how an author declares a new external input for a catalog contract.

The catalog (``CONTRACTS``) and ``ManagedCandidateBinding`` stay the authorities for
which contracts exist and which a reusable workflow may leave to candidate
preparation. This module only adds a one-line plain explanation and an example
file name. It never proposes a location: a task package declares none of these
inputs, so the author always types the project-relative path.
"""

from typing import get_args

from workflows.definition import ManagedCandidateBinding
from workflows.definition.catalog import CAPABILITIES, COLLECTION_CONTRACTS, CONTRACTS

from .models import ExternalInputCatalog, ExternalInputKind
from .options import contract_info

_SUMMARIES = {
    "interpretation.input": "Evidence the interpretation step reads to start a research round.",
    "optional.text": "An optional text value, such as a data directory.",
    "optional.expert-advice": "Optional expert advice given to the tuning or proposal step.",
    "optional.expert-context": "Optional list of expert context items for a proposal.",
    "optional.parameter-rules": "Optional workflow rules that limit tunable parameters.",
    "literature.input": "The question and settings the literature step searches with.",
    "proposal.input": "The starting request a proposal step works from.",
    "implementation.input": "A complete implementation request, normally built from a proposal.",
    "validation.input": "A complete validation request, normally built from an implementation.",
    "tuning.input": "A complete tuning request, normally built from a validated candidate.",
    "native-training.settings": "Training settings (budget, launch options) for tuning.",
    "storage": "Where this step keeps its records and outputs (a storage configuration).",
    "optional.constraint-context": "Optional constraints disclosed to the agent.",
    "optional.task-composition-ref": "Optional reference to the task composition manifest.",
    "llm-provider": "Which LLM provider this step calls, for example openai.",
    "optional.model-id": "Optional model id for the chosen LLM provider.",
}
_MANAGED = frozenset(get_args(ManagedCandidateBinding.model_fields["contract"].annotation)) - {
    # Managed literature additionally needs explicit literature_settings.
    "literature.input"
}


def external_input_catalog() -> ExternalInputCatalog:
    """Every catalog contract except those a connection supplies: capability results and
    collections a ``collect/v1`` adaptor assembles (no profile admits them as externals)."""
    results = {item.output for item in CAPABILITIES.values()} | set(COLLECTION_CONTRACTS.values())
    return ExternalInputCatalog(
        entries=tuple(
            ExternalInputKind(
                contract=contract_info(contract),
                managed=contract in _MANAGED,
                summary=_SUMMARIES[contract],
                example=contract.replace(".", "_").replace("-", "_") + ".json",
            )
            for contract in CONTRACTS
            if contract not in results
        )
    )
