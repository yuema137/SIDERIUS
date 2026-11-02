"""Copyable evaluation rendering inputs bound for the existing run scope."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent.schemas.judge_task import JudgeTaskDeclarations, RubricSpec, resolve_rubric_ref
from execute_tools.evaluation_metric import MetricIdentityKey, MetricSpec
from execute_tools.evaluation_registry import (
    ComponentKindRegistration,
    ComponentRenderContext,
    ResolvedComponent,
    resolve_evaluation_rubric,
)
from execute_tools.evaluation_spec import EvaluationRubricRef, EvaluationSpec, RubricComponent
from execute_tools.metric_order import MetricOrder

if TYPE_CHECKING:
    from workflows.evaluation_composition import ResolvedEvaluation


@dataclass(frozen=True)
class EvaluationPromptContext:
    """Plain containers allow prompt providers to receive isolated deep copies."""

    spec: EvaluationSpec
    primary: MetricSpec
    registry: dict[str, ComponentKindRegistration]
    components: dict[str, ResolvedComponent]
    judge_task: JudgeTaskDeclarations | None
    identity: str

    def rubric(self, reference: EvaluationRubricRef) -> RubricSpec:
        pinned = resolve_evaluation_rubric(reference, self.judge_task)
        return resolve_rubric_ref(pinned, self.judge_task.rubrics if self.judge_task else ())

    def component_context(self, component_id: str) -> ComponentRenderContext:
        component = next(c for c in self.spec.components if c.id == component_id)
        resolved = self.components[component_id]
        words = (
            MetricOrder(MetricIdentityKey(component_id, resolved.direction)).direction_words
            if resolved.direction is not None
            else {}
        )
        return ComponentRenderContext(
            direction_words=words,
            rubric=self.rubric(component.rubric)
            if isinstance(component, RubricComponent)
            else None,
        )


def build_evaluation_prompt_context(
    evaluation: ResolvedEvaluation | None,
    primary: MetricSpec,
    judge_task: JudgeTaskDeclarations | None,
) -> EvaluationPromptContext | None:
    if evaluation is None:
        return None
    return EvaluationPromptContext(
        evaluation.spec.model_copy(deep=True),
        primary,
        dict(evaluation.registry),
        dict(evaluation.components),
        judge_task,
        evaluation.sha256,
    )


_active: ContextVar[EvaluationPromptContext | None] = ContextVar("evaluation_prompt", default=None)


def active_evaluation_prompt_context() -> EvaluationPromptContext | None:
    return _active.get()


@contextmanager
def bind_evaluation_prompt_context(
    evaluation: ResolvedEvaluation | None,
    primary: MetricSpec,
    judge_task: JudgeTaskDeclarations | None,
) -> Iterator[None]:
    token = _active.set(build_evaluation_prompt_context(evaluation, primary, judge_task))
    try:
        yield
    finally:
        _active.reset(token)
