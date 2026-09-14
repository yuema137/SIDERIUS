"""Typed, task-owned applicability for generated loss plugins.

This module deliberately sits at the ``agent`` boundary.  It reuses the
normalized tensor vocabulary, but keeps loss eligibility out of the model
registry and out of the generated plugin itself.  A custom loss is eligible
only when the task has supplied enough information to prove the prediction /
target contract; shape guesses are never permission.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.schemas.model_io_contract import DtypeAdmissibility, TensorContract


class ExplicitPairApplicability(BaseModel):
    """An exact prediction and target contract supplied by the task."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["explicit_pair"] = "explicit_pair"
    prediction: TensorContract
    target: TensorContract


class EqualShapeApplicability(BaseModel):
    """A loss that accepts equal-rank, equal-shape tensors."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["equal_shape"] = "equal_shape"
    dtype: DtypeAdmissibility
    rank: int | None = Field(default=None, gt=0)


type CustomLossApplicability = ExplicitPairApplicability | EqualShapeApplicability


class CustomLossApplicabilityResult(BaseModel):
    """Stable, serializable outcome of the one eligibility authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    eligible: bool
    reason: str

    @model_validator(mode="after")
    def _reason_is_present(self) -> CustomLossApplicabilityResult:
        if not self.reason.strip():
            raise ValueError("an applicability result must carry a reason")
        return self


class SyntheticLossPairProvider(Protocol):
    """Optional task-owned provider for tiny semantic validation tensors."""

    def __call__(self) -> tuple[object, object]:
        """Return ``(prediction, target)`` without reading task data."""

        ...


def _dtype_intersection(left: DtypeAdmissibility, right: DtypeAdmissibility) -> tuple[str, ...]:
    right_names = {_normalize_dtype(name) for name in right.admissible}
    return tuple(name for name in left.admissible if _normalize_dtype(name) in right_names)


def _normalize_dtype(name: str) -> str:
    """Use one spelling rule for declarations and runtime cast names."""

    return name.strip().lower()


def _axis_matches(actual, declared, *, side: str) -> str | None:
    """Return a named mismatch; dynamic extents are not proof of equality."""

    actual_dim = actual.dimension
    declared_dim = declared.dimension
    if actual_dim.fixed is not None and declared_dim.fixed is not None:
        if actual_dim.fixed != declared_dim.fixed:
            return f"{side} fixed extent {actual_dim.fixed} != {declared_dim.fixed}"
        return None
    if actual_dim.symbolic is not None and declared_dim.symbolic is not None:
        if actual_dim.symbolic != declared_dim.symbolic:
            return f"{side} symbol {actual_dim.symbolic!r} != {declared_dim.symbolic!r}"
        return None
    return f"{side} extent is not provably equal (dynamic or fixed/symbol mismatch)"


def _contract_matches(actual: TensorContract, declared: TensorContract, *, side: str) -> str | None:
    if actual.rank != declared.rank:
        return f"{side} rank {actual.rank} != {declared.rank}"
    for index, (actual_axis, declared_axis) in enumerate(
        zip(actual.axes, declared.axes, strict=True)
    ):
        if actual_axis.role != declared_axis.role:
            return f"{side} axis {index} role differs"
        mismatch = _axis_matches(actual_axis, declared_axis, side=f"{side} axis {index}")
        if mismatch:
            return mismatch
    if not _dtype_intersection(actual.dtype, declared.dtype):
        return f"{side} dtype sets have no intersection"
    return None


def _refused(reason: str) -> CustomLossApplicabilityResult:
    return CustomLossApplicabilityResult(eligible=False, reason=reason)


def resolve_custom_loss_applicability(
    prediction: TensorContract | None,
    supervision_target: TensorContract | None,
    declaration: CustomLossApplicability | None,
    *,
    target_cast_dtype: str | None = None,
) -> CustomLossApplicabilityResult:
    """Resolve custom-loss eligibility without guessing tensor semantics.

    ``prediction`` is the normalized model output and ``supervision_target``
    is the task-owned target contract.  A missing contract or declaration is
    an explicit unsupported state.  ``target_cast_dtype`` represents the
    existing runtime target cast; it narrows admissibility and never creates
    a new cast or a broadcast/reshape escape hatch.
    """

    if prediction is None:
        return _refused("custom-loss prediction contract is missing")
    if supervision_target is None:
        return _refused("custom-loss supervision_target contract is missing")
    if declaration is None:
        return _refused("custom-loss applicability declaration is missing")

    if isinstance(declaration, ExplicitPairApplicability):
        mismatch = _contract_matches(prediction, declaration.prediction, side="prediction")
        if mismatch:
            return _refused(mismatch)
        mismatch = _contract_matches(supervision_target, declaration.target, side="target")
        if mismatch:
            return _refused(mismatch)
        if target_cast_dtype and _normalize_dtype(target_cast_dtype) not in {
            _normalize_dtype(name) for name in declaration.target.dtype.admissible
        }:
            return _refused(
                f"target cast dtype {target_cast_dtype!r} is not admitted by the explicit target"
            )
        return CustomLossApplicabilityResult(
            eligible=True, reason="explicit prediction/target contract is compatible"
        )

    if prediction.rank != supervision_target.rank:
        return _refused(
            f"equal_shape requires equal rank, got prediction {prediction.rank} "
            f"and target {supervision_target.rank}"
        )
    if declaration.rank is not None and prediction.rank != declaration.rank:
        return _refused(f"declared equal_shape rank {declaration.rank} != {prediction.rank}")
    for index, (prediction_axis, target_axis) in enumerate(
        zip(prediction.axes, supervision_target.axes, strict=True)
    ):
        mismatch = _axis_matches(prediction_axis, target_axis, side=f"axis {index}")
        if mismatch:
            return _refused(f"equal_shape {mismatch}")
    if not _dtype_intersection(prediction.dtype, declaration.dtype):
        return _refused("prediction dtype is not admitted by equal_shape")
    target_dtype = target_cast_dtype or supervision_target.dtype.canonical
    if _normalize_dtype(target_dtype) not in {
        _normalize_dtype(name) for name in declaration.dtype.admissible
    }:
        return _refused(f"target dtype {target_dtype!r} is not admitted by equal_shape")
    return CustomLossApplicabilityResult(
        eligible=True, reason="equal-rank, equal-shape prediction/target contract is compatible"
    )


def validate_synthetic_loss_pair(
    pair: tuple[object, object],
    prediction: TensorContract,
    target: TensorContract,
    *,
    max_elements: int = 1_000_000,
) -> None:
    """Validate a task-owned tiny pair before invoking a custom criterion.

    This checks boundedness, rank, fixed extents, shared symbolic extents and
    dtype. ``max_elements`` is a TOTAL cap across prediction and target. It
    intentionally does not inspect a dataset or infer task meaning;
    the task provider owns the values and the custom criterion owns semantics.
    """

    try:
        import torch
    except ImportError as exc:  # pragma: no cover - torch is a runtime dependency
        raise ValueError("synthetic loss-pair validation requires torch") from exc
    if not isinstance(pair, tuple) or len(pair) != 2:
        raise ValueError("synthetic loss pair must be a (prediction, target) tuple")
    actual_prediction, actual_target = pair
    if not isinstance(actual_prediction, torch.Tensor) or not isinstance(
        actual_target, torch.Tensor
    ):
        raise ValueError("synthetic loss pair must contain torch tensors")
    total_elements = 0
    for name, tensor, contract in (
        ("prediction", actual_prediction, prediction),
        ("target", actual_target, target),
    ):
        if tensor.ndim != contract.rank:
            raise ValueError(f"synthetic {name} rank {tensor.ndim} != declared {contract.rank}")
        total_elements += tensor.numel()
        if total_elements > max_elements:
            raise ValueError(
                f"synthetic pair has {total_elements} elements after {name}; "
                f"total limit is {max_elements}"
            )
        dtype_name = _normalize_dtype(str(tensor.dtype).removeprefix("torch."))
        dtype_aliases = {
            "int64": "long",
            "int32": "int",
        }
        normalized_dtypes = {
            dtype_aliases.get(_normalize_dtype(item), _normalize_dtype(item))
            for item in contract.dtype.admissible
        }
        if dtype_aliases.get(dtype_name, dtype_name) not in normalized_dtypes:
            raise ValueError(
                f"synthetic {name} dtype {dtype_name!r} is not admitted by "
                f"{contract.dtype.admissible!r}"
            )
        for index, axis in enumerate(contract.axes):
            if axis.dimension.fixed is not None and tensor.shape[index] != axis.dimension.fixed:
                raise ValueError(
                    f"synthetic {name} axis {index} extent {tensor.shape[index]} "
                    f"!= declared {axis.dimension.fixed}"
                )
    shared_symbols: dict[str, int] = {}
    for tensor, contract in (
        (actual_prediction, prediction),
        (actual_target, target),
    ):
        for index, axis in enumerate(contract.axes):
            symbol = axis.dimension.symbolic
            if symbol is None:
                continue
            extent = tensor.shape[index]
            prior = shared_symbols.setdefault(symbol, extent)
            if prior != extent:
                raise ValueError(
                    f"synthetic shared symbol {symbol!r} has extents {prior} and {extent}"
                )
