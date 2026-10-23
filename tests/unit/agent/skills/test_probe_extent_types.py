"""Reject malformed runtime extents at the probe boundary, before allocation."""

import pytest
import torch

from agent.skills.model_io_probe_skill import (
    ProbeConstructionError,
    build_model_input,
    realize_shape,
)
from tests.helpers.step04a_fixtures import tidmad_model_io


@pytest.mark.parametrize("argument", ["batch", "symbolic"])
@pytest.mark.parametrize(
    "value",
    [True, False, 1.5, 1.0, float("nan"), float("inf"), float("-inf"), "7"],
    ids=["true", "false", "fraction", "integral-float", "nan", "inf", "negative-inf", "string"],
)
def test_explicit_non_integer_extent_has_typed_refusal(argument, value):
    # A <= 0 check alone accepts True, fractions and NaN, or leaks TypeError
    # for strings. Both public keyword paths must reject at the same boundary.
    with pytest.raises(ProbeConstructionError, match=rf"{argument}=.*positive integer"):
        realize_shape(tidmad_model_io().input, **{argument: value})


@pytest.mark.parametrize("argument", ["batch", "symbolic"])
def test_model_input_refuses_invalid_extent_before_torch_allocation(monkeypatch, argument):
    def unexpected_allocation(*args, **kwargs):
        pytest.fail("invalid extent reached Torch allocation")

    monkeypatch.setattr(torch, "randint", unexpected_allocation)
    with pytest.raises(ProbeConstructionError, match="positive integer"):
        build_model_input(tidmad_model_io(), **{argument: float("nan")})


@pytest.mark.parametrize("batch,length", [(1, 7), (2, 64), (3, 4096)])
def test_valid_integer_input_geometry_is_preserved(batch, length):
    # A real consumer verifies dimensions and dtype at small and paper-scale
    # symbolic lengths; this must not become coercion or fallback to 64.
    value = build_model_input(tidmad_model_io(), batch=batch, symbolic=length)
    assert value.shape == (batch, length)
    assert value.dtype == torch.int64
