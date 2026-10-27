"""Fresh candidate inputs and name-only credential policy before new admission."""

from collections.abc import Mapping

from agent.llm_settings import provider_configuration
from tools.setup_review.environment import credential_name_checks
from tools.setup_review.route_models import LLMRoute
from tools.workflow_preview import preview_workflow
from tools.workflow_preview.models import PreviewModel, WorkflowPreview
from tools.workspace_sandbox.profile import SandboxProfile

from .models import CandidateRunRequest


class CandidateCredentialRequirements(PreviewModel):
    """Local binding requirements, never provider authentication or secret values."""

    required_names: tuple[str, ...]
    omitted_names: tuple[str, ...]
    unresolved_routes: tuple[str, ...]


def credential_requirements(
    routes: tuple[LLMRoute, ...], environment_names: tuple[str, ...]
) -> CandidateCredentialRequirements:
    """Project active registry-backed routes without reading an environment."""
    required = tuple(
        check.name
        for check in credential_name_checks(list(routes), requested=False)
        if check.routes
    )
    unresolved = tuple(
        route.name
        for route in routes
        if route.applicability not in {"disabled", "pseudo"}
        and (route.transport is None or provider_configuration(route.transport.provider) is None)
    )
    return CandidateCredentialRequirements(
        required_names=required,
        omitted_names=tuple(name for name in required if name not in environment_names),
        unresolved_routes=unresolved,
    )


def require_credentials(
    routes: tuple[LLMRoute, ...],
    environment_names: tuple[str, ...],
    environment: Mapping[str, str],
) -> None:
    """Refuse incomplete bindings using names only, including extra declared names."""
    SandboxProfile.environment_keys(environment_names)
    policy = credential_requirements(routes, environment_names)
    if policy.unresolved_routes:
        raise ValueError(
            "unresolved candidate credential routes: " + ", ".join(policy.unresolved_routes)
        )
    if policy.omitted_names:
        raise ValueError(
            "required credential names omitted from environment_names: "
            + ", ".join(policy.omitted_names)
        )
    missing = tuple(name for name in environment_names if not environment.get(name))
    if missing:
        raise ValueError("missing required environment names: " + ", ".join(missing))


def fresh_preview(request: CandidateRunRequest) -> WorkflowPreview:
    """Reobserve the declaration's files/routes at each new effect boundary."""
    if request.preview.document.definition.loop is not None:
        from .loop_models import admit_loop

        admit_loop(request)
    observed = preview_workflow(request.preview)
    if request.declaration_digest != request.preview.document.definition.declaration_digest():
        raise ValueError("stale workflow declaration")
    if (
        request.files != observed.files
        or request.selected_constructor_routes != observed.selected_constructor_routes
    ):
        raise ValueError("stale selected files or constructor routes")
    return observed
