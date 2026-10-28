"""Shared name-only credential facts for console review projections."""

from typing import Literal

from tools.workflow_preview.models import PreviewModel


class CredentialReadiness(PreviewModel):
    """Ephemeral name-only facts; never admission or provider authentication."""

    required_names: tuple[str, ...]
    omitted_names: tuple[str, ...]
    unresolved_routes: tuple[str, ...]
    present_names: tuple[str, ...]
    missing_names: tuple[str, ...]
    file_status: Literal["not_needed", "not_selected", "readable", "unavailable"]
    ready: bool
    instructions: tuple[str, ...]


# Task data (created_by="operator") reports presence only, never ownership.
WorkspaceStatus = Literal["present", "missing", "not_directory", "symlink", "not_owner"]


class WorkspaceEntry(PreviewModel):
    """One fixed or derived folder by workspace-relative name; never an absolute path."""

    name: str
    status: WorkspaceStatus
    # init: `candidate_console init` creates it; writer: created lazily when first
    # written; operator: task data the tool never creates.
    created_by: Literal["init", "writer", "operator"]


class WorkspaceReadiness(PreviewModel):
    """Ephemeral name-only layout facts; never admission and never a creation request."""

    workspace_status: WorkspaceStatus
    entries: tuple[WorkspaceEntry, ...]
    ready: bool
    init_command: str | None
