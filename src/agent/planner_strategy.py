"""Versioned planner prompt providers selected by declarations, not task names.

Experiment distributions may install one default provider through
``siderius.planner_strategy_defaults``. Explicit selections use
``siderius.planner_strategies``. Discovery is local; it never installs packages.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from agent.prompt_templates.tuner.rendering import TunerTaskRender
from agent.schemas.planner_timing import PlannerTimingContext
from core.planner_strategy_identity import PlannerStrategyIdentity, source_fingerprint


@dataclass(frozen=True)
class PlannerStrategy:
    """A trusted installed provider of prompts, never an execution policy."""

    identity: PlannerStrategyIdentity
    system_template: str
    user_renderer: Callable[..., str]
    uses_timing_context: bool
    task_renderer: Callable[[str, PlannerTimingContext | None], str] | None = None
    system_renderer: Callable[[str, TunerTaskRender], str] | None = None
    config_manual_renderer: Callable[[dict[str, Any]], str] | None = None

    def render_config_manual(self, manual: dict[str, Any]) -> str:
        """Render prompt-only configuration prose without changing execution schemas.

        An explicit experiment provider may preserve a historical manual. It
        receives a copy and owns qualification of that representation. Ordinary
        providers retain the current JSON rendering.
        """
        text = (
            self.config_manual_renderer(deepcopy(manual))
            if self.config_manual_renderer is not None
            else json.dumps(manual, indent=2)
        )
        if not isinstance(text, str):
            raise TypeError("planner strategy must return a string configuration manual")
        return text

    def render_system_template(self, task_render: TunerTaskRender) -> str:
        """Let the provider own conditional strategy prose before shared fact substitution."""
        text = (
            self.system_renderer(self.system_template, task_render)
            if self.system_renderer is not None
            else self.system_template
        )
        if not isinstance(text, str):
            raise TypeError("planner strategy must return a string system template")
        return text

    def render_user(self, arguments: dict[str, Any]) -> str:
        supplied = dict(arguments)
        if not self.uses_timing_context:
            supplied.pop("timing_context", None)
        text = self.user_renderer(**supplied)
        if not isinstance(text, str):
            raise TypeError("planner strategy must return a string prompt")
        return text


def resolve_planner_strategy(
    selection: str | None, *, expected: PlannerStrategyIdentity | None = None
) -> PlannerStrategy:
    """Use an explicit provider or the installed default; never guess a legacy version."""
    if selection == "native-timing-v1":
        from agent import prompts

        digest = source_fingerprint({"prompts.py": Path(prompts.__file__).read_bytes()})
        return _with_assembly_identity(
            PlannerStrategy(
                identity=PlannerStrategyIdentity(
                    name=selection, version="1", content_sha256=digest
                ),
                system_template=prompts.PLANNER_PROMPT,
                user_renderer=prompts.get_planner_user_prompt,
                uses_timing_context=True,
            ),
            expected=expected,
        )
    group = (
        "siderius.planner_strategies"
        if selection is not None
        else "siderius.planner_strategy_defaults"
    )
    matches = list(entry_points(group=group))
    if selection is not None:
        matches = [entry for entry in matches if entry.name == selection]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one declared planner strategy for {selection or 'installed default'!r}, "
            f"found {len(matches)}. Select an installed version explicitly or install exactly "
            "one experiment-owned default provider. No historical strategy is inferred."
        )
    resolved = matches[0].load()()
    if not isinstance(resolved, PlannerStrategy):
        raise TypeError("planner strategy entry point must return PlannerStrategy")
    return _with_assembly_identity(resolved, expected=expected)


def _with_assembly_identity(
    strategy: PlannerStrategy, *, expected: PlannerStrategyIdentity | None
) -> PlannerStrategy:
    """Pin the shared assembly, conservatively including adjacent render helpers.

    Task/configuration bytes remain owned by the task and run invariants. This
    digest records code, not a claim that stochastic model responses replay.
    """
    root = Path(__file__).parent
    paths = [
        root / "llm_bridge.py",
        root / "prompts.py",
        Path(__file__),
        root / "prompt_templates" / "timing_attribution.py",
    ]
    paths.extend((root / "prompt_templates" / "tuner").glob("*.py"))
    digest = source_fingerprint({str(p.relative_to(root)): p.read_bytes() for p in paths})
    identity = strategy.identity.model_copy(update={"assembly_sha256": digest})
    if expected is not None and identity != expected:
        raise ValueError(
            "Planner strategy changed after run preflight; refusing the provider call."
        )
    return replace(strategy, identity=identity)
