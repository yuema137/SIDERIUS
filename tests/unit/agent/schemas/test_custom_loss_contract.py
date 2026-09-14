"""Focused contract tests for task-owned custom-loss applicability.

Each test names a failure that schema validation or the existing built-in
loss matrix cannot catch: custom prediction/target compatibility and the
pre-criterion synthetic-pair boundary.
"""

import pytest
import torch
from pydantic import TypeAdapter, ValidationError

from agent.schemas.custom_loss_contract import (
    EqualShapeApplicability,
    ExplicitPairApplicability,
    resolve_custom_loss_applicability,
    validate_synthetic_loss_pair,
)
from agent.schemas.model_io_contract import Dimension, ModelIOContract, TensorAxis, TensorContract
from ml_models.models_format_sandbox import DtypeAdmissibility


def _tensor(*dims: int | str, dtype: str = "float32") -> TensorContract:
    axes = tuple(
        TensorAxis(dimension=(Dimension(fixed=d) if isinstance(d, int) else Dimension(symbolic=d)))
        for d in dims
    )
    return TensorContract(axes=axes, dtype=DtypeAdmissibility(admissible=(dtype,)))


def test_explicit_pair_accepts_asymmetric_masked_target():
    prediction = _tensor("B", 1)
    target = _tensor("B", 2)
    declaration = ExplicitPairApplicability(
        prediction=prediction,
        target=target,
    )
    result = resolve_custom_loss_applicability(prediction, target, declaration)
    assert result.eligible


def test_equal_shape_rejects_rank_and_extent_mismatch():
    declaration = EqualShapeApplicability(dtype=DtypeAdmissibility(admissible=("float32",)), rank=2)
    assert (
        "equal rank"
        in resolve_custom_loss_applicability(
            _tensor("B", 2), _tensor("B", 2, 1), declaration
        ).reason
    )
    assert (
        "fixed extent"
        in resolve_custom_loss_applicability(_tensor("B", 2), _tensor("B", 3), declaration).reason
    )


def test_equal_shape_rejects_dynamic_dimensions_as_unproven():
    declaration = EqualShapeApplicability(dtype=DtypeAdmissibility(admissible=("float32",)))
    dynamic = TensorContract(
        axes=(
            TensorAxis(dimension=Dimension(symbolic="B")),
            TensorAxis(dimension=Dimension(dynamic=True)),
        ),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    )
    result = resolve_custom_loss_applicability(dynamic, dynamic, declaration)
    assert not result.eligible
    assert "provably equal" in result.reason


def test_equal_shape_rejects_disjoint_dtypes_and_accepts_normalized_cast():
    declaration = EqualShapeApplicability(dtype=DtypeAdmissibility(admissible=(" float32 ",)))
    incompatible = resolve_custom_loss_applicability(
        _tensor("B", 2, dtype="float64"), _tensor("B", 2), declaration
    )
    assert not incompatible.eligible and "dtype" in incompatible.reason
    compatible = resolve_custom_loss_applicability(
        _tensor("B", 2), _tensor("B", 2), declaration, target_cast_dtype=" FLOAT32 "
    )
    assert compatible.eligible


@pytest.mark.parametrize(
    "prediction,target,needle",
    [
        (_tensor("B", 1), _tensor("B", 3), "fixed extent"),
        (_tensor("B", 1), _tensor("N", 1), "symbol"),
        (_tensor("B", 1), _tensor("B", 1, 2), "rank"),
    ],
)
def test_explicit_pair_rejects_unproven_target_contract(prediction, target, needle):
    declaration = ExplicitPairApplicability(prediction=prediction, target=_tensor("B", 2))
    result = resolve_custom_loss_applicability(prediction, target, declaration)
    assert not result.eligible
    assert needle in result.reason


def test_equal_shape_accepts_dtype_intersection_and_declared_rank():
    prediction = _tensor("B", 4)
    target = _tensor("B", 4, dtype="float32")
    declaration = EqualShapeApplicability(
        dtype=DtypeAdmissibility(admissible=("float32", "float64")), rank=2
    )
    assert resolve_custom_loss_applicability(prediction, target, declaration).eligible


def test_missing_declaration_and_target_fail_closed():
    prediction = _tensor("B", 1)
    assert not resolve_custom_loss_applicability(prediction, None, None).eligible
    result = resolve_custom_loss_applicability(prediction, _tensor("B", 1), None)
    assert not result.eligible and "declaration is missing" in result.reason


def test_extra_fields_are_rejected_by_the_typed_forms():
    with pytest.raises(ValidationError):
        EqualShapeApplicability(dtype=DtypeAdmissibility(admissible=("float32",)), unexpected=True)


def test_synthetic_pair_checks_declared_fixed_extents_before_criterion():
    prediction = _tensor("B", 2)
    target = _tensor("B", 2, dtype="long")
    with pytest.raises(ValueError, match="synthetic prediction axis 1"):
        validate_synthetic_loss_pair(
            (torch.zeros(3, 1), torch.zeros(3, 2, dtype=torch.long)), prediction, target
        )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"mode": "explicit_pair"},
        {"mode": "equal_shape", "dtype": {"admissible": ["float32"]}, "rank": 0},
        {
            "mode": "equal_shape",
            "dtype": {"admissible": ["float32"]},
            "unexpected": True,
        },
    ],
)
def test_malformed_or_ambiguous_applicability_declarations_fail_closed(payload):
    with pytest.raises(ValidationError):
        from agent.schemas.custom_loss_contract import CustomLossApplicability

        TypeAdapter(CustomLossApplicability).validate_python(payload)


def test_synthetic_pair_is_bounded_and_does_not_require_equal_shape():
    prediction = _tensor("B", 1)
    target = _tensor("B", "T", dtype="long")
    validate_synthetic_loss_pair(
        (torch.zeros(2, 1, requires_grad=True), torch.zeros(2, 2, dtype=torch.long)),
        prediction,
        target,
    )


def test_synthetic_pair_total_cap_and_shared_symbol_mismatch_fail():
    prediction = _tensor("B", 2)
    target = _tensor("B", "T", dtype="long")
    with pytest.raises(ValueError, match="total limit"):
        validate_synthetic_loss_pair(
            (torch.zeros(2, 2), torch.zeros(2, 2, dtype=torch.long)),
            prediction,
            target,
            max_elements=7,
        )
    with pytest.raises(ValueError, match="shared symbol"):
        validate_synthetic_loss_pair(
            (torch.zeros(2, 2), torch.zeros(3, 2, dtype=torch.long)),
            prediction,
            target,
        )


def test_synthetic_pair_rejects_non_tensor_values():
    with pytest.raises(ValueError, match="torch tensors"):
        validate_synthetic_loss_pair(([1], torch.zeros(1, 1)), _tensor("B", 1), _tensor("B", 1))


def test_forward_contract_carries_task_owned_target_and_applicability():
    from agent.schemas.task_config import ForwardContract

    target = _tensor("B", 2, dtype="long")
    applicability = ExplicitPairApplicability(prediction=_tensor("B", 1), target=target)
    contract = ForwardContract(
        supervision_target=target,
        custom_loss_applicability=applicability,
    )
    assert contract.supervision_target == target
    assert contract.custom_loss_applicability == applicability


def test_implementor_refuses_before_generated_plugin_import(tmp_path):
    """A bad declared pair must not execute arbitrary generated source."""

    from nodes.ml_model_implementor.ml_model_implementor import _dummy_tensor_validate_loss

    marker = tmp_path / "imported"
    output = _tensor("B", 1)
    target = _tensor("B", 2, dtype="long")
    declaration = ExplicitPairApplicability(prediction=_tensor("B", 3), target=target)
    model_io = ModelIOContract(input=_tensor("B", 4), output=output)
    source = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported')\n"
        "PLUGIN_LOSS_TYPE = 'side_effect'\n"
    )
    error = _dummy_tensor_validate_loss(
        source,
        "side_effect",
        model_io,
        target,
        declaration,
    )
    assert error is not None and "fixed extent" in error
    assert not marker.exists()
