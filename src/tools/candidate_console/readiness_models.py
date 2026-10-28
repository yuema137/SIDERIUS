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
    file_status: Literal["not_needed", "not_selected", "readable", "missing", "unavailable"]
    ready: bool
    instructions: tuple[str, ...]
