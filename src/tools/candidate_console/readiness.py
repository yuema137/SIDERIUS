"""Read-only credential projection after verified native/configured association."""

from typing import Literal

from tools.candidate_operations.models import OperationFailure
from tools.candidate_worker.models import CandidateRunRequest
from tools.candidate_worker.preflight import credential_requirements

from .files import credential_values
from .models import CredentialReadiness

FileStatus = Literal["not_needed", "not_selected", "readable", "missing", "unavailable"]
MISSING_FILE = (
    "The configured credential_file does not exist; create it (private JSON or dotenv, mode 600)."
)
UNREADABLE_FILE = "The configured credential_file cannot be read: check JSON or dotenv format, ownership and mode 600."


def read_names(names: tuple[str, ...], path: str | None) -> tuple[FileStatus, dict[str, str]]:
    """Name-only presence source: a missing file is distinct from an unreadable one."""
    if not names:
        return "not_needed", {}
    if path is None:
        return "not_selected", {}
    try:
        return "readable", credential_values(path)
    except FileNotFoundError:
        return "missing", {}
    except (OSError, ValueError, OperationFailure):
        return "unavailable", {}


def file_instruction(status: FileStatus) -> list[str]:
    return (
        [MISSING_FILE]
        if status == "missing"
        else [UNREADABLE_FILE]
        if status == "unavailable"
        else []
    )


def credential_readiness(request: CandidateRunRequest, path: str | None) -> CredentialReadiness:
    """Reuse worker requirements and strict private reader, returning names only."""
    policy = credential_requirements(request.selected_constructor_routes, request.environment_names)
    names = tuple(dict.fromkeys((*policy.required_names, *request.environment_names)))
    status, values = read_names(names, path)
    present = tuple(name for name in names if values.get(name))
    missing = tuple(name for name in names if name not in present)
    instructions = []
    if policy.omitted_names:
        instructions.append(
            "Add omitted names to candidate_environment_names; restart and Prepare again."
        )
    if policy.unresolved_routes:
        instructions.append("Repair the selected model profile routes; Prepare and review again.")
    if status in ("missing", "unavailable"):
        instructions.extend(file_instruction(status))
    elif missing and status == "not_selected":
        instructions.append(
            "Set credential_file in console.json to a private JSON or dotenv path; restart and review again."
        )
    elif missing:
        instructions.append(
            "Set nonempty values for missing names in credential_file (private JSON or dotenv, mode 600)."
        )
    return CredentialReadiness(
        **policy.model_dump(),
        present_names=present,
        missing_names=missing,
        file_status=status,
        ready=not (policy.omitted_names or policy.unresolved_routes or missing)
        and status not in ("missing", "unavailable"),
        instructions=tuple(instructions),
    )


def named_credential_readiness(
    required_names: tuple[str, ...], allowed_names: tuple[str, ...], path: str | None
) -> CredentialReadiness:
    """Project admission-owned names without inventing provider requirements."""
    names = tuple(dict.fromkeys((*required_names, *allowed_names)))
    omitted = tuple(name for name in required_names if name not in allowed_names)
    status, values = read_names(names, path)
    present = tuple(name for name in names if values.get(name))
    missing = tuple(name for name in names if name not in present)
    instructions = []
    if omitted:
        instructions.append("Add required names to this native choice's environment_names.")
    instructions.extend(file_instruction(status))
    if missing and status not in ("missing", "unavailable"):
        instructions.append(
            "Supply nonempty named values in credential_file (private JSON or dotenv, mode 600)."
        )
    return CredentialReadiness(
        required_names=required_names,
        omitted_names=omitted,
        unresolved_routes=(),
        present_names=present,
        missing_names=missing,
        file_status=status,
        ready=not (omitted or missing) and status not in ("missing", "unavailable"),
        instructions=tuple(instructions),
    )
