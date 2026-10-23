"""Output-only symbols must not become probe recipe or input-size requirements."""

import pytest
import torch

from agent.schemas.model_io_contract import Dimension, ModelIOContract, TensorAxis, TensorContract
from agent.skills.model_io_probe_skill import ProbeConstructionError, expected_output_shape
from agent.skills.model_output_geometry import (
    resolve_output_shape,
    validate_model_output,
    validate_output_shape,
)
from tests.helpers.step04a_fixtures import SHIPPED_OUTPUT_DTYPE, tidmad_model_io


def contract(inputs, outputs):
    def tensor(dimensions):
        axes = []
        for value in dimensions:
            dimension = (
                Dimension(fixed=value)
                if isinstance(value, int)
                else Dimension(dynamic=True)
                if value is None
                else Dimension(symbolic=value)
            )
            axes.append(TensorAxis(dimension=dimension, role="batch" if value == "B" else None))
        return TensorContract(axes=tuple(axes), dtype=SHIPPED_OUTPUT_DTYPE)

    return ModelIOContract(input=tensor(inputs), output=tensor(outputs))


@pytest.mark.parametrize("slots", [0, 7, 64, 100, 5000])
def test_independent_output_count_is_observed(slots):
    declaration = contract(["B", 5, 10000], ["B", "K", 2])
    validate_model_output(
        declaration, "regressor", torch.zeros(2, 5, 10000), torch.zeros(2, slots, 2)
    )
    with pytest.raises(ProbeConstructionError, match="Cannot resolve output dimension"):
        expected_output_shape(declaration, "regressor")


@pytest.mark.parametrize("output", [(1, 7, 2), (2, 7, 3), (2, 7), (2, 7, 2, 1)])
def test_known_output_constraints_still_reject(output):
    with pytest.raises(ProbeConstructionError):
        validate_output_shape(
            contract(["B", 5, 10000], ["B", "K", 2]), "regressor", (2, 5, 10000), output
        )


def test_multiple_symbols_bind_by_identity_not_position_or_scalar():
    declaration = contract(["B", "H", "W"], ["B", "W", "K", "H"])
    validate_output_shape(declaration, "regressor", (2, 11, 17), (2, 17, 3, 11))
    with pytest.raises(ProbeConstructionError, match="symbol 'W'"):
        validate_output_shape(declaration, "regressor", (2, 11, 17), (2, 11, 3, 17))


def test_repeated_symbols_share_extent_but_dynamic_axes_do_not():
    declaration = contract(["B", 10], ["B", "K", "K", None, None])
    validate_output_shape(declaration, "regressor", (2, 10), (2, 7, 7, 3, 5))
    with pytest.raises(ProbeConstructionError, match="symbol 'K'"):
        validate_output_shape(declaration, "regressor", (2, 10), (2, 7, 8, 3, 5))
    with pytest.raises(ProbeConstructionError, match="Input symbol"):
        validate_output_shape(contract(["B", "T", "T"], ["B", 1]), "regressor", (2, 3, 4), (2, 1))


def test_fixed_batch_remains_authoritative():
    declaration = contract(["B", 10], [1, "K"])
    declaration = declaration.model_copy(
        update={
            "output": declaration.output.model_copy(
                update={
                    "axes": (
                        TensorAxis(dimension=Dimension(fixed=1), role="batch"),
                        declaration.output.axes[1],
                    )
                }
            )
        }
    )
    validate_output_shape(declaration, "regressor", (2, 10), (1, 7))
    with pytest.raises(ProbeConstructionError, match="fixed extent"):
        validate_output_shape(declaration, "regressor", (2, 10), (2, 7))


@pytest.mark.parametrize("size", [1, 64, 100, 4096])
def test_shared_paper_geometry_preserved_across_workload_sizes(size):
    declaration = tidmad_model_io()
    assert resolve_output_shape(declaration, "classifier", (2, size)) == (2, 256, size)
    assert resolve_output_shape(declaration, "regressor", (2, size)) == (2, size)
    assert expected_output_shape(declaration, "classifier", symbolic=size) == (1, 256, size)
    with pytest.raises(ProbeConstructionError, match="symbol 'T'"):
        validate_output_shape(declaration, "regressor", (2, size), (2, size + 1))


def test_dtype_and_finiteness_are_checked_without_coercion():
    declaration = contract(["B", 10], ["B", "K"])
    sample = torch.zeros(2, 10)
    with pytest.raises(ProbeConstructionError, match="dtype"):
        validate_model_output(
            declaration, "regressor", sample, torch.zeros(2, 7, dtype=torch.int64)
        )
    with pytest.raises(ProbeConstructionError, match="finite"):
        validate_model_output(declaration, "regressor", sample, torch.full((2, 7), float("nan")))
    with pytest.raises(ProbeConstructionError, match=r"torch\.Tensor"):
        validate_model_output(declaration, "regressor", sample, [[0]])


def test_dynamic_target_is_refused_and_fixed_target_is_resolved():
    with pytest.raises(ProbeConstructionError, match="task-owned target"):
        resolve_output_shape(contract(["B", 10], ["B", None]), "regressor", (2, 10))
    assert resolve_output_shape(contract(["B", 10], ["B", 7]), "regressor", (2, 10)) == (2, 7)
