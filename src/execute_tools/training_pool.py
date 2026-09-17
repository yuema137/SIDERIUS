"""Optional task-owned frozen training pool for composed workflows.

The framework never interprets a task's scope. A task that opts in supplies
the immutable parent and proves containment of every sampled child. Tasks
without this capability retain the existing scope-construction behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from execute_tools.task_data_path import ScopeBuildRequest


class FrozenTrainingPool(BaseModel):
    """Parent scope and its fraction of the task's full training population."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    scope: object
    source_portion: float = Field(gt=0.0, le=1.0)


class FrozenTrainingPoolError(RuntimeError):
    """A declared frozen-pool contract cannot be satisfied."""


class TaskFrozenTrainingPoolCapability(Protocol):
    """Optional, task-owned selection and containment semantics."""

    def build_frozen_training_pool(self, request: ScopeBuildRequest) -> FrozenTrainingPool:
        """Build the same parent for every attempt under this task binding."""
        ...

    def sample_training_pool(self, pool: object, request: ScopeBuildRequest) -> object:
        """Sample ``request.portion`` of the parent, not of the full dataset."""
        ...

    def training_scope_is_contained(self, child: object, pool: object) -> bool:
        """Prove the task's opaque child scope is inside its parent."""
        ...


_POOL_METHODS = (
    "build_frozen_training_pool",
    "sample_training_pool",
    "training_scope_is_contained",
)


def resolve_frozen_training_pool_capability(
    impl: object,
) -> TaskFrozenTrainingPoolCapability | None:
    """Return the opt-in capability; reject incomplete declarations."""

    present = tuple(callable(getattr(impl, name, None)) for name in _POOL_METHODS)
    if not any(present):
        return None
    if not all(present):
        missing = [name for name, exists in zip(_POOL_METHODS, present, strict=True) if not exists]
        raise FrozenTrainingPoolError(
            f"incomplete frozen training pool capability: missing {', '.join(missing)}"
        )
    # The resolver above verifies the complete callable surface at runtime.
    return cast(TaskFrozenTrainingPoolCapability, impl)


def select_training_scope(
    impl: TaskFrozenTrainingPoolCapability,
    request: ScopeBuildRequest,
    *,
    serialize_scope: Callable[[object], str],
) -> object:
    """Formal uses the parent; Trial is a checked relative sample of it."""

    pool = impl.build_frozen_training_pool(request)
    if not isinstance(pool, FrozenTrainingPool):
        raise FrozenTrainingPoolError("frozen training pool provider returned an invalid contract")
    if request.round_kind == "formal":
        if abs(request.portion - pool.source_portion) > 1e-9:
            raise FrozenTrainingPoolError(
                "formal training portion does not match the frozen parent pool: "
                f"requested={request.portion}, parent={pool.source_portion}"
            )
        child = pool.scope
    else:
        child = impl.sample_training_pool(pool.scope, request)
    if not impl.training_scope_is_contained(child, pool.scope):
        raise FrozenTrainingPoolError("training scope escapes the frozen parent pool")
    if request.round_kind == "formal" and serialize_scope(child) != serialize_scope(pool.scope):
        raise FrozenTrainingPoolError("formal training scope must equal the frozen parent pool")
    return child
