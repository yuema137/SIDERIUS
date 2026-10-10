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
from typing import Any, ParamSpec, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from core.planner_strategy_identity import source_fingerprint

P = ParamSpec("P")
T = TypeVar("T", str, tuple[str, str])


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
    ):
        paths += list((root.parent / "nodes" / node).glob("*.py"))
    # The reflector block consumes a typed projection from these producers;
    # qualifying template bytes alone would miss changes in its input meaning.
    tuner = root.parent / "nodes" / "ml_hyperparameter_tune_agent"
    paths += [tuner / "planning.py", tuner / "provenance.py"]
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
            raise ValueError("Expected a rendering profile, but none was supplied")
        binding = None
    else:
        identity = profile.identity()
        if expected is not None and identity != expected:
            raise ValueError("Prompt renderer changed after composition")
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
                raise ValueError("Prompt renderer source changed during the run")
            if name in profile.native_boundaries:
                return native(*args, **kwargs)
            renderer = profile.renderers.get(name)
            if renderer is None:
                raise ValueError(
                    f"Prompt profile {profile.name!r} does not declare boundary {name!r}"
                )
            supplied = contract.bind(*args, **kwargs)
            supplied.apply_defaults()
            value = renderer(**deepcopy(dict(supplied.arguments)))
            return cast(Any, adapter.validate_python(value, strict=True))

        return render

    return decorate
