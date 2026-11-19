"""Explicit, scoped rendering providers for trusted experiment packages.

Providers receive copies of already constructed rendering inputs. They return
text only; node orchestration, response validation and execution remain native.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass
from functools import wraps
from importlib.metadata import entry_points
from inspect import signature
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, ParamSpec, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from core.planner_strategy_identity import source_fingerprint

P = ParamSpec("P")
T = TypeVar("T", str, tuple[str, str])


IntegrityKind = Literal["undeclared", "source_drift", "identity_drift", "renderer_failure"]

_REMEDIES: dict[str, str] = {
    "undeclared": "declare the boundary in the profile and requalify it, or run without the profile",
    "source_drift": "restore the provider source the run started with, or requalify the changed source",
    "identity_drift": "restore the provider source pinned at composition, or requalify and recompose",
    "renderer_failure": "fix the profile's renderer for this boundary",
}


class PromptProfileIntegrityError(RuntimeError):
    """An explicitly bound prompt profile cannot render faithfully; the run stops (#1542).

    Raised for every integrity failure of a bound profile: a reached boundary it
    does not declare (``undeclared``), provider sources that changed during the
    run (``source_drift``) or since composition (``identity_drift``), and a
    renderer that raised or returned something other than the boundary's text
    type (``renderer_failure``). Continuing would silently change the run's
    prompts (for example by turning the failure into proposer feedback), so
    callers that convert exceptions into recoverable feedback re-raise it via
    ``raise_if_prompt_profile_failure``. Deliberately not a ``ValueError``, so
    handlers for ordinary validation errors do not absorb it.
    """

    def __init__(
        self, profile: str, boundary: str | None, reason: str, kind: IntegrityKind
    ) -> None:
        self.profile = profile
        self.boundary = boundary
        self.reason = reason
        self.kind = kind
        target = f"boundary {boundary!r}" if boundary is not None else "its binding"
        super().__init__(
            f"Prompt profile {profile!r} cannot render {target}: {reason}. The run stops "
            f"instead of continuing with different prompts. Remedy: {_REMEDIES[kind]}."
        )


def prompt_profile_failure(exc: BaseException) -> PromptProfileIntegrityError | None:
    """The integrity error ``exc`` is or explicitly wraps (``raise ... from``), if any."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, PromptProfileIntegrityError):
            return current
        seen.add(id(current))
        current = current.__cause__
    return None


def raise_if_prompt_profile_failure(exc: BaseException) -> None:
    """Re-raise a prompt-profile integrity failure hidden in ``exc``; else return."""
    failure = prompt_profile_failure(exc)
    if failure is not None:
        raise failure


class PromptRenderingIdentity(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    assembly_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def rendering_assembly_digest() -> str:
    """Conservatively bind the framework rendering surface, not a task name."""
    root = Path(__file__).parent
    paths = [Path(__file__), *(root / "prompt_templates").rglob("*.py")]
    paths += list((root / "prompt_templates").rglob("*.md"))
    paths += list((root / "schemas").rglob("*.py"))
    paths += list((root / "data_analysis").glob("*.py"))
    for node in (
        "ml_model_implementor",
        "ml_code_validator_agent",
        "ml_model_proposal_agent",
        "result_interpretation_agent",
        "data_analysis_agent",
        "ml_literature_review",
    ):
        paths += list((root.parent / "nodes" / node).glob("*.py"))
    # The reflector block consumes a typed projection from these producers;
    # qualifying template bytes alone would miss changes in its input meaning.
    tuner = root.parent / "nodes" / "ml_hyperparameter_tune_agent"
    paths += [
        tuner / "planning.py",
        tuner / "provenance.py",
        tuner / "feedback.py",
        tuner / "contracts.py",
    ]
    paths.append(root / "llm_bridge.py")
    # Generated config manuals include these typed training declarations.
    paths += [
        root.parent / "ml_models" / "models_format_sandbox.py",
        root.parent / "ml_models" / "learning_rate_schedule.py",
    ]
    paths += [
        root.parent / "workflows" / "constraint_disclosure.py",
    ]
    paths += [
        root.parent / name
        for name in (
            "agent/evaluation_context.py",
            "execute_tools/evaluation_component_rendering.py",
            "execute_tools/evaluation_registry.py",
            "execute_tools/evaluation_spec.py",
            "execute_tools/evaluation_validation.py",
            "execute_tools/metric_order.py",
        )
    ]
    return source_fingerprint({str(p.relative_to(root.parent)): p.read_bytes() for p in paths})


@dataclass(frozen=True)
class PromptRenderingProfile:
    """An installed text provider with explicit native fallthrough boundaries.

    ``sources`` must include the provider's implementation and template bytes.
    It is a declared trusted-code closure, not a sandbox for untrusted plugins.
    """

    name: str
    version: str
    renderers: Mapping[str, Callable[..., object]]
    native_boundaries: frozenset[str]
    sources: Mapping[str, Path]

    def __post_init__(self) -> None:
        if self.renderers.keys() & self.native_boundaries:
            raise ValueError("A prompt boundary cannot be both overridden and native")
        if not self.sources:
            raise ValueError("A rendering provider must declare its source files")
        object.__setattr__(self, "renderers", MappingProxyType(dict(self.renderers)))
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))
        object.__setattr__(self, "native_boundaries", frozenset(self.native_boundaries))

    def identity(self) -> PromptRenderingIdentity:
        sources = {k: p.read_bytes() for k, p in self.sources.items()}
        if "__boundaries__.json" in sources:
            raise ValueError("Provider source label '__boundaries__.json' is reserved")
        sources["__boundaries__.json"] = json.dumps(
            {"overridden": sorted(self.renderers), "native": sorted(self.native_boundaries)},
            sort_keys=True,
        ).encode()
        return PromptRenderingIdentity(
            name=self.name,
            version=self.version,
            content_sha256=source_fingerprint(sources),
            assembly_sha256=rendering_assembly_digest(),
        )


def resolve_prompt_profile(selection: str) -> PromptRenderingProfile:
    matches = [e for e in entry_points(group="siderius.prompt_renderers") if e.name == selection]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one installed prompt renderer {selection!r}; found {len(matches)}"
        )
    profile = matches[0].load()()
    if not isinstance(profile, PromptRenderingProfile) or profile.name != selection:
        raise TypeError("Prompt renderer factory must return the selected PromptRenderingProfile")
    profile.identity()  # Fail before binding if its declared sources are unreadable.
    return profile


_active: ContextVar[tuple[PromptRenderingProfile, PromptRenderingIdentity] | None] = ContextVar(
    "prompt_rendering_profile", default=None
)


def active_prompt_identity() -> PromptRenderingIdentity | None:
    binding = _active.get()
    return None if binding is None else binding[1]


@contextmanager
def bind_prompt_profile(
    profile: PromptRenderingProfile | None, *, expected: PromptRenderingIdentity | None = None
) -> Iterator[None]:
    if profile is None:
        if expected is not None:
            raise PromptProfileIntegrityError(
                expected.name,
                None,
                "composition expected this profile, but none was supplied",
                "identity_drift",
            )
        binding = None
    else:
        identity = profile.identity()
        if expected is not None and identity != expected:
            raise PromptProfileIntegrityError(
                profile.name, None, "Prompt renderer changed after composition", "identity_drift"
            )
        binding = (profile, identity)
    token = _active.set(binding)
    try:
        yield
    finally:
        _active.reset(token)


def prompt_boundary(name: str, *, pair: bool = False) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """Publish a named rendering signature while preserving the native call path."""
    adapter = TypeAdapter(tuple[str, str] if pair else str)

    def decorate(native: Callable[P, T]) -> Callable[P, T]:
        contract = signature(native)

        @wraps(native)
        def render(*args: P.args, **kwargs: P.kwargs) -> T:
            binding = _active.get()
            if binding is None:
                return native(*args, **kwargs)
            profile, identity = binding
            if profile.identity() != identity:
                raise PromptProfileIntegrityError(
                    profile.name, name, "its provider source changed during the run", "source_drift"
                )
            if name in profile.native_boundaries:
                return native(*args, **kwargs)
            renderer = profile.renderers.get(name)
            if renderer is None:
                raise PromptProfileIntegrityError(
                    profile.name,
                    name,
                    f"it does not declare boundary {name!r} (no renderer, not native)",
                    "undeclared",
                )
            supplied = contract.bind(*args, **kwargs)
            supplied.apply_defaults()
            try:
                value = renderer(**deepcopy(dict(supplied.arguments)))
            except PromptProfileIntegrityError:
                raise
            except Exception as exc:
                raise PromptProfileIntegrityError(
                    profile.name,
                    name,
                    f"its renderer raised {type(exc).__name__}: {exc}",
                    "renderer_failure",
                ) from exc
            try:
                return cast(Any, adapter.validate_python(value, strict=True))
            except ValidationError as exc:
                raise PromptProfileIntegrityError(
                    profile.name,
                    name,
                    f"its renderer returned {type(value).__name__}, not text",
                    "renderer_failure",
                ) from exc

        return render

    return decorate
