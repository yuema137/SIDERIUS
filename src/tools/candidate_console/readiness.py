"""Read-only credential projection after verified native/configured association."""

from tools.candidate_operations.models import OperationFailure
from tools.candidate_worker.models import CandidateRunRequest
from tools.candidate_worker.preflight import credential_requirements

from .files import credential_values
from .models import CredentialReadiness


def credential_readiness(request: CandidateRunRequest, path: str | None) -> CredentialReadiness:
    """Reuse worker requirements and strict private reader, returning names only."""
    policy = credential_requirements(request.selected_constructor_routes, request.environment_names)
    names = tuple(dict.fromkeys((*policy.required_names, *request.environment_names)))
    status = "not_selected" if path is None else "readable"
    values: dict[str, str] = {}
    if not names:
        status = "not_needed"
    else:
        try:
            values = credential_values(path)
        except (OSError, ValueError, OperationFailure):
            status = "unavailable"
    present = tuple(name for name in names if values.get(name))
    missing = tuple(name for name in names if name not in present)
    instructions = []
    if policy.omitted_names:
        instructions.append(
            "Add omitted names to candidate_environment_names; restart and Prepare again."
        )
    if policy.unresolved_routes:
        instructions.append("Repair the selected model profile routes; Prepare and review again.")
    if status == "unavailable":
        instructions.append(
            "Check credential_file JSON format, ownership and mode 600 permissions."
        )
    elif missing and status == "not_selected":
        instructions.append(
            "Set credential_file in console.json to a private JSON path; restart and review again."
        )
    elif missing:
        instructions.append(
            "Set nonempty values for missing names in credential_file (private JSON, mode 600)."
        )
    return CredentialReadiness(
        **policy.model_dump(),
        present_names=present,
        missing_names=missing,
        file_status=status,
        ready=not (policy.omitted_names or policy.unresolved_routes or missing)
        and status != "unavailable",
        instructions=tuple(instructions),
    )
