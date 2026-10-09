"""Resolve one task-owned candidate input through existing composition owners."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent.schemas.model_io_contract import AxisRole, ModelIOContract
from agent.schemas.model_probe import ModelProbeContext, ModelProbeRequest, ModelProbeSetupError
from agent.schemas.parameter_rules import (
    ParameterRuleError,
    ParameterRules,
    resolve_parameter_rule_document,
)
from agent.skills.model_io_probe_skill import declared_output_tensor, realize_shape

if TYPE_CHECKING:
    import torch

    from workflows.task_composition import RunTaskComposition


def _provider(task: object) -> Callable[[ModelProbeRequest], object] | None:
    provider = getattr(task, "model_validation_input", None)
    if provider is not None and not callable(provider):
        raise ModelProbeSetupError("task model_validation_input must be callable")
    return provider


def model_probe_context_for(composition: RunTaskComposition) -> ModelProbeContext | None:
    """Project the existing composed identity only when its task offers the capability."""
    task = composition.task_data_path
    if _provider(task) is None:
        return None
    return ModelProbeContext(
        manifest_path=composition.provenance.manifest_path,
        semantic_fingerprint=composition.semantic_fingerprint,
        task_data_path_id=type(task).task_data_path_id,
    )


@contextmanager
def _resolved_provider(context: ModelProbeContext, contract: ModelIOContract):
    from core.local_code.binding import bind_code_package
    from workflows.task_composition import compose_run_task_bindings

    try:
        composition = compose_run_task_bindings(context.manifest_path)
        if (
            composition.semantic_fingerprint != context.semantic_fingerprint
            or type(composition.task_data_path).task_data_path_id != context.task_data_path_id
            or composition.forward_contract.model_io != contract
        ):
            raise ModelProbeSetupError("model probe composition identity or model I/O changed")
        # Bind source identity only; synthetic fixtures never need a physical dataset.
        with bind_code_package(composition.code_package):
            provider = _provider(composition.task_data_path)
            if provider is None:
                raise ModelProbeSetupError("declared model_validation_input provider is missing")
            preferred_batches = getattr(
                composition.task_data_path, "model_validation_batch_sizes", (1, 2)
            )
            if (
                not isinstance(preferred_batches, (tuple, list))
                or not preferred_batches
                or any(type(value) is not int or value <= 0 for value in preferred_batches)
            ):
                raise ModelProbeSetupError(
                    "model_validation_batch_sizes must be nonempty positive integers"
                )
            yield provider, composition.parameter_rules, preferred_batches
    except ModelProbeSetupError:
        raise
    except Exception as exc:
        raise ModelProbeSetupError(f"cannot resolve model probe task: {exc}") from exc


def legal_probe_batches(
    contract: ModelIOContract,
    rules: ParameterRules | None,
    preferred: Sequence[int] = (1, 2),
) -> tuple[int, ...]:
    """Select test cases; the existing rule resolver alone judges legality."""
    fixed = next(
        (axis.dimension.fixed for axis in contract.input.axes if axis.role == AxisRole.BATCH), None
    )
    rule = rules.rules.get("train_config.batch_size") if rules else None
    selected_rules = ParameterRules(rules={"train_config.batch_size": rule}) if rule else None
    suggestions = list(preferred)
    if fixed is not None:
        suggestions = [fixed]
    elif rule is not None:
        # These are candidate test sizes, not a second constraint interpreter.
        # Every suggestion still goes through the one parameter-rule owner.
        if rule.allowed:
            suggestions.extend(v for v in rule.allowed if type(v) is int)
        if rule.range and rule.range.min is not None:
            suggestions.append(max(1, math.ceil(rule.range.min)))
    batches = []
    for value in suggestions:
        try:
            resolved = resolve_parameter_rule_document(
                {"train_config": {"batch_size": value}}, task_rules=selected_rules
            )["train_config"]["batch_size"]
        except ParameterRuleError:
            continue
        if type(resolved) is not int or resolved <= 0 or (fixed is not None and resolved != fixed):
            continue
        if resolved not in batches:
            batches.append(resolved)
    if not batches:
        raise ModelProbeSetupError(
            "cannot select a probe batch from the declared task rules; supply model_validation_batch_sizes with legal small batches"
        )
    return tuple(batches)


@dataclass(frozen=True)
class ModelProbeCase:
    input: torch.Tensor
    expected_output_shape: tuple[int, ...]


def task_model_probe_cases(
    context: ModelProbeContext,
    contract: ModelIOContract | None,
    output_type: str,
    *,
    symbolic: int | None = None,
) -> tuple[ModelProbeCase, ...]:
    """Build fresh CPU inputs; never fall back after an explicit provider fails."""
    import torch

    from execute_tools.model_input_dtype import resolve_contract_input_dtype

    if contract is None:
        raise ModelProbeSetupError("task-owned model probes require a model I/O contract")
    # Candidate output declarations are candidate errors, not task setup failures.
    output_tensor = declared_output_tensor(contract, output_type)
    cases = []
    with _resolved_provider(context, contract) as (provider, rules, preferred_batches):
        batches = legal_probe_batches(contract, rules, preferred_batches)
        dtype = resolve_contract_input_dtype(contract.input.dtype)
        for batch in batches:
            shape = realize_shape(contract.input, batch=batch, symbolic=symbolic)
            request = ModelProbeRequest(
                model_io_contract=contract,
                input_shape=shape,
                dtype=str(dtype).removeprefix("torch."),
            )
            try:
                value = provider(request)
            except Exception as exc:
                raise ModelProbeSetupError(f"task model_validation_input failed: {exc}") from exc
            if (
                not isinstance(value, torch.Tensor)
                or value.device.type != "cpu"
                or value.layout != torch.strided
                or tuple(value.shape) != shape
                or value.dtype != dtype
                or not torch.isfinite(value).all()
            ):
                raise ModelProbeSetupError(
                    f"task model_validation_input must return a finite CPU {dtype} tensor of shape {shape}"
                )
            cases.append(
                ModelProbeCase(
                    input=value.detach().clone(),
                    expected_output_shape=realize_shape(
                        output_tensor,
                        batch=batch,
                        symbolic=symbolic,
                    ),
                )
            )
    return tuple(cases)
