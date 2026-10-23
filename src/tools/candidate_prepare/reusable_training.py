"""Source-derived training inputs and independent reusable bundle verification."""

from collections.abc import Callable
from pathlib import Path

from workflows.definition import ReusableWorkflowDocument


def settings_payload(document: ReusableWorkflowDocument) -> bytes | None:
    """Return canonical sparse effective ingress, without materializing native defaults."""
    if document.training_settings is None:
        return None
    from workflows.candidate_training_settings import effective_training_settings

    return effective_training_settings(
        document.training_settings, document.preparation_options.allowed_output_types
    )


def verify_training_payloads(
    document: ReusableWorkflowDocument, output: Path, read_bytes: Callable[[Path], bytes]
) -> None:
    """Regenerate settings/facts from retained source, independently of the child index."""
    expected = settings_payload(document)
    if expected is None:
        return
    from agent.schemas.proposal import ProposalInput
    from workflows.candidate_training_settings import (
        parse_training_settings,
        proposal_training_values,
    )

    if read_bytes(output / "training_settings.json") != expected:
        raise ValueError("training settings differ from captured source")
    proposal = ProposalInput.model_validate_json(read_bytes(output / "proposal.json"))
    if {"hardware_context", "constraint_context"} & proposal.model_fields_set:
        raise ValueError("reusable training seed contains runtime-owned facts")
    for name, value in proposal_training_values(parse_training_settings(expected)).items():
        if name not in proposal.model_fields_set or getattr(proposal, name) != value:
            raise ValueError(f"reusable proposal {name} differs from source training settings")
