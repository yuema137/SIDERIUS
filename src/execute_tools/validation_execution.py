"""Explicit run-scoped validation execution, separate from task semantics.

The deployment implements the executor and its process boundary. This binding
neither authenticates a service nor grants private-data access. No binding means
the original native execution; a supplied executor failure never falls back.
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

import torch
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, JsonValue, StrictInt

from agent.schemas.model_io_contract import ModelIOContract
from ml_models.models_format_sandbox import LossConfig


class ValidationExecutionRequest(BaseModel):
    """Live research-side objects; never serialize this object across trust boundaries."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)
    model: torch.nn.Module
    criterion: torch.nn.Module
    model_type: str
    model_io: ModelIOContract | None
    loss: LossConfig
    scope: object
    device: torch.device
    batch_size: Annotated[StrictInt, Field(gt=0)]
    expected_rows: Annotated[StrictInt, Field(gt=0)]


class ValidationExecutionResult(BaseModel):
    """Aggregate result from a deployment executor; no private tensors or RNG."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    r3: float  # Nonfinite objective evidence remains native evidence.
    rows: Annotated[StrictInt, Field(gt=0)]
    observables: dict[str, FiniteFloat] = Field(default_factory=dict)
    failed_observables: tuple[str, ...] = ()


@dataclass(frozen=True)
class ValidationCallbacks:
    """Research-side callbacks; a client must invoke them DURING execution."""

    verifier: Any
    on_verified: Callable[[], None] | None
    check_allocation: Callable[[], None] | None


class ValidationExecutor(Protocol):
    def declared_rows(self, scope: object) -> int:
        """Ask the task-owning service to authorize scope and declare its rows."""
        ...

    def observe(
        self, request: ValidationExecutionRequest, callbacks: ValidationCallbacks
    ) -> ValidationExecutionResult:
        """Execute one pass, preserving callbacks and returning aggregates only."""
        ...


class ValidationDeployment(BaseModel):
    """Explicit research-client factory/settings; contains no private authority or secrets."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    factory: str = Field(pattern=r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*:[A-Za-z_]\w*$")
    settings: dict[str, JsonValue] = Field(default_factory=dict)


@dataclass(frozen=True)
class _Binding:
    executor: ValidationExecutor
    deployment: ValidationDeployment | None


_ACTIVE: ContextVar[_Binding | None] = ContextVar("siderius_validation_executor", default=None)


@contextmanager
def bind_validation_executor(executor: ValidationExecutor) -> Iterator[ValidationExecutor]:
    """Bind an in-process executor; spawning with this alone is refused."""
    with _bind(executor, None):
        yield executor


@contextmanager
def _bind(executor, deployment):
    token = _ACTIVE.set(_Binding(executor, deployment))
    try:
        yield executor
    finally:
        _ACTIVE.reset(token)


@contextmanager
def bind_validation_deployment(deployment: ValidationDeployment) -> Iterator[ValidationExecutor]:
    """Load an explicit research-side client, never a private worker/scorer factory."""
    deployment = deployment.model_copy(deep=True)
    module_name, name = deployment.factory.split(":")
    factory = getattr(importlib.import_module(module_name), name)
    executor = factory(deployment.model_dump()["settings"])
    if not callable(getattr(executor, "declared_rows", None)) or not callable(
        getattr(executor, "observe", None)
    ):
        raise TypeError("validation deployment factory returned an invalid executor")
    with _bind(executor, deployment):
        yield executor


def validation_executor_argv() -> list[str]:
    binding = _ACTIVE.get()
    if binding is None:
        return []
    if binding.deployment is None:
        raise ValueError("bound validation executor has no subprocess deployment declaration")
    return ["--validation_executor_json", binding.deployment.model_dump_json()]


@contextmanager
def child_validation_executor_binding(payload: str | None) -> Iterator[None]:
    """A supplied but broken binding fails; no ambient environment discovery."""
    if payload is None:
        if _ACTIVE.get() is not None:
            raise ValueError("training child omitted an active validation deployment")
        yield
    else:
        with bind_validation_deployment(ValidationDeployment.model_validate_json(payload)):
            yield


def bound_validation_rows(scope: object) -> int | None:
    """None means unbound; invalid or failed declarations never select local I/O."""
    binding = _ACTIVE.get()
    if binding is None:
        return None
    rows = binding.executor.declared_rows(scope)
    if type(rows) is not int or rows <= 0:
        raise ValueError("validation executor must declare a positive integer row count")
    return rows


def execute_validation_epoch(
    local: Callable[..., tuple[float, int, float]], *, expected_rows: int, **kwargs: Any
) -> tuple[float, int, float]:
    """One dispatch point; observation/history ownership remains native."""
    observation = kwargs["observables"]
    binding = _ACTIVE.get()
    if binding is None:
        observation.start_epoch()
        result = local(**kwargs)
        observation.finish_epoch()
        return result
    started = time.perf_counter()
    request = ValidationExecutionRequest(
        model=kwargs["model"],
        criterion=kwargs["criterion"],
        model_type=kwargs["model_cfg"].model_type,
        model_io=kwargs["model_io"],
        loss=kwargs["loss_cfg"],
        scope=kwargs["task_eval_scope"],
        device=kwargs["device"],
        batch_size=kwargs["batch_size"],
        expected_rows=expected_rows,
    )
    result = binding.executor.observe(
        request,
        ValidationCallbacks(
            verifier=kwargs.get("verifier"),
            on_verified=kwargs.get("on_verified"),
            check_allocation=kwargs.get("check_allocation"),
        ),
    )
    if not isinstance(result, ValidationExecutionResult):
        raise TypeError("validation executor must return a validated result")
    if result.rows != expected_rows:
        raise ValueError("validation executor materialized rows differ from declaration")
    observation.accept_external_epoch(result.observables, result.failed_observables)
    # Include snapshots, transport and callbacks, not just remote kernel time.
    return result.r3, result.rows, time.perf_counter() - started
