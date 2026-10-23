"""Validate output geometry using observed inputs, never probe recipe extents."""

from __future__ import annotations

from collections.abc import Sequence

from agent.schemas.model_io_contract import AxisRole, ModelIOContract, TensorContract
from agent.skills.model_io_probe_skill import ProbeConstructionError, declared_output_tensor


def _check_shape(tensor: TensorContract, shape: Sequence[int], label: str) -> None:
    if len(shape) != tensor.rank:
        raise ProbeConstructionError(
            f"{label} rank {len(shape)} does not match declared rank {tensor.rank}"
        )
    for axis, size in zip(tensor.axes, shape, strict=True):
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ProbeConstructionError(f"{label} has invalid extent {size!r}")
        if axis.dimension.fixed is not None and size != axis.dimension.fixed:
            raise ProbeConstructionError(
                f"{label} shape {tuple(shape)} violates fixed extent {axis.dimension.fixed}"
            )


def _bind(symbols: dict[str, int], name: str | None, size: int, label: str) -> None:
    if name is None:
        return
    if name in symbols and symbols[name] != size:
        raise ProbeConstructionError(
            f"{label} symbol {name!r} has extent {size}, expected {symbols[name]}"
        )
    symbols[name] = size


def _input_bindings(
    contract: ModelIOContract, input_shape: Sequence[int]
) -> tuple[dict[str, int], int | None]:
    _check_shape(contract.input, input_shape, "Input")
    symbols: dict[str, int] = {}
    batch = None
    for axis, size in zip(contract.input.axes, input_shape, strict=True):
        _bind(symbols, axis.dimension.symbolic, size, "Input")
        if axis.role is AxisRole.BATCH:
            batch = size
    return symbols, batch


def validate_output_shape(
    contract: ModelIOContract,
    declared_output_type: str,
    input_shape: Sequence[int],
    output_shape: Sequence[int],
) -> None:
    """Check fixed axes, observed batch and symbol equality; dynamic axes stay free.

    Independent output symbols bind on their first occurrence in this output.
    Repeated occurrences must agree. Bindings never persist across calls. Zero
    extents are legal for symbolic/dynamic axes (for example an empty event set).
    """
    output = declared_output_tensor(contract, declared_output_type)
    symbols, batch = _input_bindings(contract, input_shape)
    _check_shape(output, output_shape, "Output")
    for axis, size in zip(output.axes, output_shape, strict=True):
        if (
            axis.dimension.fixed is None
            and axis.role is AxisRole.BATCH
            and batch is not None
            and size != batch
        ):
            raise ProbeConstructionError(f"Output batch extent {size}, expected {batch}")
        _bind(symbols, axis.dimension.symbolic, size, "Output")


def resolve_output_shape(
    contract: ModelIOContract,
    declared_output_type: str,
    input_shape: Sequence[int],
) -> tuple[int, ...]:
    """Resolve only output extents established by input or fixed declarations.

    Synthetic target construction cannot infer independent output dimensions.
    Callers needing those dimensions must supply task-owned target samples.
    """
    output = declared_output_tensor(contract, declared_output_type)
    symbols, batch = _input_bindings(contract, input_shape)
    sizes: list[int] = []
    for axis in output.axes:
        size = axis.dimension.fixed
        if size is None and axis.role is AxisRole.BATCH:
            size = batch
        if size is None and axis.dimension.symbolic is not None:
            size = symbols.get(axis.dimension.symbolic)
        if size is None:
            raise ProbeConstructionError(
                f"Cannot resolve output dimension {axis.dimension.render()!r} from input "
                "geometry; supply task-owned target samples for synthetic training probes "
                "or validate an observed model output"
            )
        sizes.append(size)
    validate_output_shape(contract, declared_output_type, input_shape, sizes)
    return tuple(sizes)


def validate_model_output(
    contract: ModelIOContract,
    declared_output_type: str,
    input_tensor: object,
    output: object,
) -> None:
    """Validate a finite tensor at the declared output dtype and geometry."""
    import torch

    if not isinstance(input_tensor, torch.Tensor) or not isinstance(output, torch.Tensor):
        raise ProbeConstructionError("Model input and output must be torch.Tensor instances")
    tensor = declared_output_tensor(contract, declared_output_type)
    validate_output_shape(contract, declared_output_type, input_tensor.shape, output.shape)
    dtype = str(output.dtype).removeprefix("torch.")
    if dtype not in tensor.dtype.admissible:
        raise ProbeConstructionError(
            f"Output dtype {dtype!r} is not admissible: {tensor.dtype.admissible}"
        )
    if not torch.isfinite(output).all():
        raise ProbeConstructionError("Model output must be finite")
