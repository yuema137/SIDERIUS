"""Explicitly requested key-name presence checks; never load dotenv or clients."""

from __future__ import annotations

import os
from collections.abc import Mapping

from agent.llm_settings import KNOWN_PROVIDERS
from tools.setup_review.route_models import CredentialNameCheck, LLMRoute


def credential_name_checks(
    routes: list[LLMRoute], *, requested: bool, environment: Mapping[str, str] | None = None
) -> list[CredentialNameCheck]:
    """Return only names/statuses. Unrequested or unused keys are never read."""
    groups: dict[str, list[LLMRoute]] = {}
    for route in routes:
        if route.transport is not None:
            provider = KNOWN_PROVIDERS.get(route.transport.provider)
            if provider is not None:
                groups.setdefault(provider["api_key_env"], []).append(route)
    checks = []
    for name, candidates in sorted(groups.items()):
        needed = [
            route.name for route in candidates if route.applicability not in {"disabled", "pseudo"}
        ]
        if not needed:
            status = "not_required"
        elif not requested:
            status = "not_checked"
        else:
            source = os.environ if environment is None else environment
            status = "present_nonempty" if source.get(name) else "missing"
        checks.append(CredentialNameCheck(name=name, routes=needed, status=status))
    return checks
