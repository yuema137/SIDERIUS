"""Step 05b C1 — caller-supplied extents on the Step-04a shape realizer.

Design:
``docs/design/generic_framework_upgrade/step_05b_tuner_resource_time.md``
§0.2 (OD-05b-1, option A), C1.

``realize_shape`` realized at VALIDATION-probe extents only — ``PROBE_BATCH``
and ``PROBE_SYMBOLIC_EXTENT``. A capacity probe must realize the SAME declared
shape at the candidate's real batch and segmentation size, or it forecasts
memory for a tensor nobody is going to run. C1 makes one realization
authority serve both, additively.

This module guards the four properties that make "additive" a fact rather
than a claim. Each names a defect no other test in the repository catches:

1. **default preservation** — with both arguments omitted, every existing
   Step-04a caller realizes exactly what it realized before. The existing
   04a modules assert specific shapes for specific contracts; none of them
   would notice a changed DEFAULT, because they were written against the
   constants directly.
2. **`fixed` precedence survives the new arguments** — a declared extent
   outranks a recipe. Without this, ``symbolic=T`` would overwrite the class
   alphabet and the capacity probe would price ``[B, T, T]``.
3. **`None`-sensitivity** — the override is written against ``None``, not
   against falsiness. A ``batch or PROBE_BATCH`` idiom passes every
   positive-value test in existence and silently resolves ``0`` to the
   validation default.
4. **one scalar is refused for two independent alignments** — rather than
   guessing, or growing a per-axis shape language this module does not own.
"""

from __future__ import annotations

import pytest

from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    TensorAxis,
    TensorContract,
)
from agent.skills.model_io_probe_skill import (
    LOSS_PROBE_BATCH,
    LOSS_PROBE_LENGTH,
    PROBE_BATCH,
    PROBE_SYMBOLIC_EXTENT,
    ProbeConstructionError,
    build_model_input,
    expected_output_shape,
    realize_shape,
)
from tests.helpers.step04a_fixtures import SHIPPED_OUTPUT_DTYPE, tidmad_model_io

FLOAT_DTYPE = SHIPPED_OUTPUT_DTYPE

RUNTIME_BATCH, RUNTIME_SEG = 8, 4096


def _axis(role: AxisRole, *, symbolic: str | None = None, fixed: int | None = None) -> TensorAxis:
    return TensorAxis(
        dimension=Dimension(symbolic=symbolic) if fixed is None else Dimension(fixed=fixed),
        role=role,
    )


def _shipped_contract():
    """The shipped TIDMAD declaration: ``[B, T] int`` → ``[B, 256, T] float``.

    Reuses the Step-04a frozen fixture rather than restating the declaration,
    so a contract edit cannot make 04a's oracles and 05b's disagree.
    """
    return tidmad_model_io()


# ---------------------------------------------------------------------------
# 1. Default preservation
# ---------------------------------------------------------------------------


class TestOmittedArgumentsAreByteIdentical:
    def test_shipped_contract_realizes_the_pre_05b_shapes(self):
        """Hardcoded, not re-derived from the constants — a test that read
        ``PROBE_BATCH`` back would pass for any value the module chose."""
        contract = _shipped_contract()
        assert realize_shape(contract.output) == (1, 256, 64)
        assert realize_shape(contract.input) == (1, 64)

    def test_the_recipe_constants_are_unchanged(self):
        """C1 is additive: it may not retune Step-04's validation recipe."""
        assert (PROBE_BATCH, PROBE_SYMBOLIC_EXTENT) == (1, 64)
        assert (LOSS_PROBE_BATCH, LOSS_PROBE_LENGTH) == (2, 100)

    def test_the_derived_step04_helpers_are_unchanged(self):
        """``expected_output_shape`` and ``build_model_input`` are the two
        derived consumers the node callers actually reach; both must resolve
        the pre-05b instance when nothing is supplied."""
        contract = _shipped_contract()
        assert expected_output_shape(contract, "classifier") == (1, 256, 64)
        assert expected_output_shape(contract, "regressor") == (1, 64)
        assert tuple(build_model_input(contract).shape) == (1, 64)


# ---------------------------------------------------------------------------
# 2. `fixed` precedence
# ---------------------------------------------------------------------------


class TestDeclaredExtentsOutrankSuppliedRecipes:
    def test_a_fixed_class_axis_ignores_the_symbolic_override(self):
        """THE precedence case. Supplying ``symbolic=4096`` on the shipped
        output must move ``T`` and leave the 256-class alphabet alone —
        overriding it would realize (and price) ``[B, T, T]``."""
        contract = _shipped_contract()
        assert realize_shape(contract.output, batch=RUNTIME_BATCH, symbolic=RUNTIME_SEG) == (
            RUNTIME_BATCH,
            256,
            RUNTIME_SEG,
        )

    def test_a_fixed_batch_role_axis_ignores_the_batch_override(self):
        """The one case where the two rules meet: an axis that is BOTH
        batch-role and ``fixed``. The declared fact wins."""
        pinned = TensorContract(
            axes=(
                _axis(AxisRole.BATCH, fixed=3),
                _axis(AxisRole.TEMPORAL, symbolic="T"),
            ),
            dtype=FLOAT_DTYPE,
        )
        assert realize_shape(pinned, batch=RUNTIME_BATCH, symbolic=RUNTIME_SEG) == (
            3,
            RUNTIME_SEG,
        )

    def test_rank_and_axis_order_still_come_from_the_contract(self):
        """Nothing in the parameterized path may assume 3-D or class-second.
        A class-LAST declaration realizes class-last at runtime extents."""
        class_last = TensorContract(
            axes=(
                _axis(AxisRole.BATCH, symbolic="B"),
                _axis(AxisRole.TEMPORAL, symbolic="T"),
                _axis(AxisRole.CLASS, fixed=7),
            ),
            dtype=FLOAT_DTYPE,
        )
        assert realize_shape(class_last, batch=RUNTIME_BATCH, symbolic=RUNTIME_SEG) == (
            RUNTIME_BATCH,
            RUNTIME_SEG,
            7,
        )


# ---------------------------------------------------------------------------
# 3. `None`-sensitivity
# ---------------------------------------------------------------------------


class TestExtentsAreNoneSensitiveNotTruthy:
    @pytest.mark.parametrize("supplied", [None])
    def test_explicit_none_resolves_the_recipe_default(self, supplied):
        contract = _shipped_contract()
        assert realize_shape(contract.output, batch=supplied, symbolic=supplied) == (
            1,
            256,
            64,
        )

    @pytest.mark.parametrize("bad", [0, -1, -4096])
    @pytest.mark.parametrize("argument", ["batch", "symbolic"])
    def test_a_non_positive_extent_refuses_instead_of_falling_back(self, argument, bad):
        """The mutation this exists for: rewriting the override as
        ``batch or PROBE_BATCH``. That idiom passes every positive case and
        resolves ``0`` to the validation default — a capacity forecast for a
        tensor the caller never asked for."""
        contract = _shipped_contract()
        with pytest.raises(ProbeConstructionError) as exc:
            realize_shape(contract.output, **{argument: bad})
        assert argument in str(exc.value)

    def test_the_refusal_is_the_modules_existing_typed_error(self):
        """One typed error for "this instance cannot be realized", not a
        second one bolted on beside it."""
        assert issubclass(ProbeConstructionError, ValueError)


# ---------------------------------------------------------------------------
# 4. Ambiguous symbolic extents
# ---------------------------------------------------------------------------


class TestTwoIndependentAlignmentsAreRefused:
    def _two_symbol_tensor(self) -> TensorContract:
        """``[B, H, W]`` — two independent spatial alignments.

        ``H`` and ``W`` carry no role: ``AxisRole`` ships exactly the three
        roles production reads, and an axis nothing branches on leaves
        ``role`` unset. That is also what keeps arbitrary rank expressible,
        which is precisely why this shape is representable and this refusal
        is reachable.
        """
        return TensorContract(
            axes=(
                _axis(AxisRole.BATCH, symbolic="B"),
                TensorAxis(dimension=Dimension(symbolic="H")),
                TensorAxis(dimension=Dimension(symbolic="W")),
            ),
            dtype=FLOAT_DTYPE,
        )

    def test_one_scalar_for_two_distinct_symbols_refuses(self):
        """``H`` and ``W`` are two independent alignments. Answering both
        with one number realizes a shape the contract never declared; the
        alternative — per-axis extents — is a shape language owned by the
        contract schema, not by this recipe module."""
        with pytest.raises(ProbeConstructionError) as exc:
            realize_shape(self._two_symbol_tensor(), symbolic=RUNTIME_SEG)
        assert "H" in str(exc.value) and "W" in str(exc.value)

    def test_the_legacy_path_still_realizes_it(self):
        """Reachable ONLY on the explicit-extent path. A caller that omits
        ``symbolic`` keeps the pre-05b realization for any contract at all —
        which is what makes C1 additive rather than a new restriction."""
        assert realize_shape(self._two_symbol_tensor()) == (1, 64, 64)

    def test_repeating_one_symbol_is_not_ambiguous(self):
        """Two axes sharing the SAME name are one alignment, so one scalar
        answers both. Rejecting this would refuse a legitimate contract."""
        same_symbol = TensorContract(
            axes=(
                _axis(AxisRole.BATCH, symbolic="B"),
                _axis(AxisRole.TEMPORAL, symbolic="T"),
                TensorAxis(dimension=Dimension(symbolic="T")),
            ),
            dtype=FLOAT_DTYPE,
        )
        assert realize_shape(same_symbol, symbolic=RUNTIME_SEG) == (
            1,
            RUNTIME_SEG,
            RUNTIME_SEG,
        )
