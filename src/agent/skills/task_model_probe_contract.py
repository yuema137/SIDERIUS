"""Validate and render optional task-owned model fixture requirements."""

from __future__ import annotations

import math

from pydantic import BaseModel, ValidationError

from agent.schemas.model_io_contract import AxisRole, ModelIOContract
from agent.schemas.model_probe import ModelProbeContext, ModelProbeContract, ModelProbeSetupError
from agent.skills.model_io_probe_skill import ProbeConstructionError


def probe_declaration(task: object) -> ModelProbeContract | None:
    """Validate a declaration at its task-object boundary, without building a fixture."""
    value = getattr(task, "model_validation_contract", None)
    if value is None:
        return None
    try:
        return ModelProbeContract.model_validate(value)
    except ValidationError as exc:
        raise ModelProbeSetupError(f"invalid model_validation_contract: {exc}") from exc


def _validate_binding(contract: ModelIOContract, declaration: ModelProbeContract) -> None:
    if declaration.symbolic_extent_config_field is None:
        return
    axes = [
        axis
        for axis in contract.input.axes
        if axis.role != AxisRole.BATCH and axis.dimension.fixed is None
    ]
    symbols = {axis.dimension.symbolic for axis in axes}
    if len(symbols) != 1 or None in symbols:
        raise ModelProbeSetupError(
            "symbolic_extent_config_field requires exactly one input non-batch symbolic "
            "dimension and no dynamic axes; fixed dimensions are never overridden"
        )


def resolve_probe_declaration(
    task: object,
    contract: ModelIOContract,
    config: object | None,
    *,
    symbolic: int | None = None,
) -> tuple[ModelProbeContract | None, int | None, dict[str, int | float | bool]]:
    """Expose only declared scalar fields; never mutate candidate configuration."""
    declaration = probe_declaration(task)
    if declaration is None:
        return None, symbolic, {}
    _validate_binding(contract, declaration)
    fields = declaration.config_fields
    bound = declaration.symbolic_extent_config_field
    required = set(fields) | ({bound} if bound else set())
    if required and not isinstance(config, BaseModel):
        raise ProbeConstructionError(
            "declared model probe fields require validated candidate config"
        )
    values: dict[str, int | float | bool] = {}
    for name in sorted(required):
        if not isinstance(config, BaseModel) or name not in type(config).model_fields:
            raise ProbeConstructionError(f"model probe config field {name!r} is missing")
        value = getattr(config, name)
        if type(value) not in (int, float, bool) or (
            isinstance(value, float) and not math.isfinite(value)
        ):
            raise ProbeConstructionError(
                f"model probe config field {name!r} must be a finite scalar"
            )
        values[name] = value
    if bound is not None:
        extent = values[bound]
        if type(extent) is not int or extent <= 0:
            raise ProbeConstructionError(
                f"model probe extent field {bound!r} must be a positive integer"
            )
        if symbolic is not None and symbolic != extent:
            raise ProbeConstructionError(
                "declared probe extent conflicts with candidate temporal extent"
            )
        symbolic = extent
    return declaration, symbolic, {name: values[name] for name in fields}


def check_probe_input_size(declaration: ModelProbeContract, shape: tuple[int, ...]) -> None:
    """Refuse fixture allocation beyond the task's explicit input bound."""
    if math.prod(shape) > declaration.max_input_elements:
        raise ModelProbeSetupError("model probe input exceeds declared max_input_elements")


def resolve_task_probe_extent(
    context: ModelProbeContext,
    contract: ModelIOContract | None,
    config: object,
    *,
    symbolic: int | None = None,
) -> int | None:
    """Return a dispatch size indicator, never a replacement shape for the fixture."""
    from agent.skills.model_io_probe_skill import realize_shape
    from agent.skills.task_model_probe import _resolved_provider, legal_probe_batches

    if contract is None:
        raise ModelProbeSetupError("task-owned model probes require a model I/O contract")
    with _resolved_provider(context, contract) as (_, rules, batches, task):
        declaration, extent, _ = resolve_probe_declaration(
            task, contract, config, symbolic=symbolic
        )
        if declaration is not None:
            extent_for_dispatch = 1
            for batch in legal_probe_batches(contract, rules, batches):
                shape = realize_shape(contract.input, batch=batch, symbolic=extent)
                check_probe_input_size(declaration, shape)
                dispatch_extent = max(
                    (
                        size
                        for axis, size in zip(contract.input.axes, shape, strict=True)
                        if axis.role != AxisRole.BATCH
                    ),
                    default=1,
                )
                extent_for_dispatch = max(extent_for_dispatch, dispatch_extent)
            return extent_for_dispatch
        return extent


def render_model_probe_contract(context: ModelProbeContext, contract: ModelIOContract) -> str:
    """Describe declared requirements only; do not construct candidate code or fixtures."""
    from agent.skills.task_model_probe import _resolved_provider

    with _resolved_provider(context, contract) as (_, rules, batches, task):
        declaration = probe_declaration(task)
        if declaration is None:
            return ""
        _validate_binding(contract, declaration)
        from agent.skills.model_io_probe_skill import realize_shape
        from agent.skills.task_model_probe import legal_probe_batches

        geometry = (
            "The non-batch symbolic extent is read from candidate config field "
            f"{declaration.symbolic_extent_config_field!r}. Every occurrence of that "
            "non-batch symbolic dimension uses the same resolved extent; fixed output "
            "dimensions remain unchanged."
            if declaration.symbolic_extent_config_field is not None
            else "Default probe input shapes (candidate temporal length may refine them): "
            + repr(
                [
                    realize_shape(contract.input, batch=batch)
                    for batch in legal_probe_batches(contract, rules, batches)
                ]
            )
        )
        return (
            "Task-owned model validation contract:\n"
            + declaration.model_dump_json(indent=2)
            + "\n"
            + geometry
            + "\nThe CPU fixture must be accepted under the candidate's unchanged configuration. "
            "Only config_fields are provided to the fixture. Fixed I/O dimensions remain fixed. "
            "The input element cap bounds this validation fixture, not production data."
        )


def task_probe_declaration(
    context: ModelProbeContext, contract: ModelIOContract | None
) -> ModelProbeContract | None:
    """Resolve an identity-checked declaration without model construction."""
    from agent.skills.task_model_probe import _resolved_provider

    if contract is None:
        raise ModelProbeSetupError("task-owned model probes require a model I/O contract")
    with _resolved_provider(context, contract) as (_, _, _, task):
        declaration = probe_declaration(task)
        if declaration is not None:
            _validate_binding(contract, declaration)
        return declaration
