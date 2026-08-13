"""The normalized Model-I/O contract — Step 03 Phase A, milestone M1.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§4c (single input / single output), §4e (no relation DSL), §4b
(cardinality derived, no `0` sentinel), **§4a.1 AMENDMENT A-1** (dtype
admissibility), §16 (invalid-state analogues), §21.

**Scope discipline.** Nothing here re-tests what Pydantic already
enforces — not an optional field defaulting to ``None``, not a declared
type accepting its own type, not a required field being required. Every
test below covers runtime behaviour a declaration cannot express:
validator logic, derived values, conditional branches, and the rendered
bytes.

The load-bearing test is
``TestTidmadRoundTrip::test_the_normalized_contract_renders_the_shipped_prose``.
Byte-identity of LLM-facing prose is a §21 stop condition, and the whole
point of M1 is that the prose becomes DERIVED rather than authored. If
that test cannot pass, Step 03's rendering migration cannot proceed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from agent.schemas.task_config import ForwardContract
from workflows.task_config import load_task_config


def _axis(role: AxisRole | None = None, **dim) -> TensorAxis:
    return TensorAxis(dimension=Dimension(**dim), role=role)


#: The shipped TIDMAD contract, expressed normalized. This is the fixture
#: the round-trip is measured against — NOT a copy of the YAML strings.
TIDMAD = ModelIOContract(
    input=TensorContract(
        axes=(
            _axis(AxisRole.BATCH, symbolic="B"),
            _axis(AxisRole.TEMPORAL, symbolic="T"),
        ),
        # A-1: the embedding arm admits BOTH concrete integer dtypes (A6
        # executed this). int64 is canonical because it is what the
        # shipped prose says.
        dtype=DtypeAdmissibility(admissible=("int64", "int32")),
    ),
    output=TensorContract(
        axes=(
            _axis(AxisRole.BATCH, symbolic="B"),
            _axis(AxisRole.CLASS, fixed=256),
            _axis(AxisRole.TEMPORAL, symbolic="T"),
        ),
        dtype=DtypeAdmissibility(admissible=("float32",)),
    ),
)


class TestTidmadRoundTrip:
    """The normalized contract must reproduce the shipped prose exactly."""

    @pytest.fixture
    def shipped(self) -> ForwardContract:
        return ForwardContract(**load_task_config()["forward_contract"])

    def test_the_normalized_contract_renders_the_shipped_prose(self, shipped):
        """Byte-identity, both tensors, against the real YAML.

        Asserted against ``configs/task_config.yaml`` rather than a
        hardcoded copy, because the claim is *"the contract can replace
        the shipped prose"* — a copy would still pass if the shipped
        prose changed underneath.
        """
        assert TIDMAD.input.render() == shipped.input_shape
        assert TIDMAD.output.render() == shipped.output_shape

    def test_the_rendered_bytes_are_the_expected_literals(self, shipped):
        """The same claim, hardcoded, so a failure says WHICH side moved.

        With only the test above, a change to both the renderer and the
        YAML would agree with each other and stay green.
        """
        assert TIDMAD.input.render() == "[B, T] int64"
        assert TIDMAD.output.render() == "[B, 256, T] float32"
        assert shipped.input_shape == "[B, T] int64"
        assert shipped.output_shape == "[B, 256, T] float32"

    def test_cardinality_is_derived_not_declared(self, shipped):
        """§4b: one cardinality authority. The contract DERIVES the count
        from the class axis rather than carrying a second declaration."""
        assert TIDMAD.class_cardinality == 256
        assert TIDMAD.class_cardinality == shipped.num_classes


class TestRendering:
    """Shape rendering across ranks — the branch-free path §4d requires."""

    @pytest.mark.parametrize(
        ("axes", "expected"),
        [
            (({"symbolic": "B"},), "[B]"),
            (({"symbolic": "B"}, {"symbolic": "T"}), "[B, T]"),
            (({"symbolic": "B"}, {"fixed": 256}, {"symbolic": "T"}), "[B, 256, T]"),
            (
                ({"symbolic": "B"}, {"fixed": 3}, {"fixed": 32}, {"fixed": 32}),
                "[B, 3, 32, 32]",
            ),
            (({"symbolic": "B"}, {"dynamic": True}), "[B, ...]"),
        ],
        ids=["rank1", "rank2", "rank3", "rank4", "dynamic"],
    )
    def test_shape_renders_at_any_rank(self, axes, expected):
        """Rank is data, not a branch. A renderer that special-cased rank 2
        or 3 — which every shipped prose restatement effectively does —
        would fail the rank-1 and rank-4 rows."""
        contract = TensorContract(
            axes=tuple(_axis(**a) for a in axes),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        )
        assert contract.render_shape() == expected
        assert contract.rank == len(axes)


class TestDimensionIsExactlyOneForm:
    """The validator §16 names as the 'invalid file_order' analogue."""

    def test_no_form_is_rejected(self):
        with pytest.raises(ValidationError, match="exactly one of"):
            Dimension()

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"fixed": 8, "symbolic": "T"},
            {"fixed": 8, "dynamic": True},
            {"symbolic": "T", "dynamic": True},
            {"fixed": 8, "symbolic": "T", "dynamic": True},
        ],
        ids=["fixed+symbolic", "fixed+dynamic", "symbolic+dynamic", "all three"],
    )
    def test_more_than_one_form_is_rejected(self, kwargs):
        """Two forms is the dangerous case: it would render as whichever
        the implementation checked first, silently."""
        with pytest.raises(ValidationError, match="exactly one of"):
            Dimension(**kwargs)


class TestAxisRoles:
    def test_duplicate_roles_are_rejected(self):
        """Two axes claiming one role makes ``axis_with_role`` ambiguous, so
        a consumer would silently take the first."""
        with pytest.raises(ValidationError, match="duplicate axis role"):
            TensorContract(
                axes=(
                    _axis(AxisRole.CLASS, fixed=256),
                    _axis(AxisRole.CLASS, fixed=10),
                ),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            )

    def test_unroled_axes_may_repeat(self):
        """An axis nothing branches on carries no role, and any number of
        those must be allowed — otherwise arbitrary rank is unexpressible
        without inventing consumer-less roles."""
        contract = TensorContract(
            axes=(
                _axis(AxisRole.BATCH, symbolic="B"),
                _axis(fixed=32),
                _axis(fixed=32),
            ),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        )
        assert contract.render_shape() == "[B, 32, 32]"

    def test_lookup_is_by_role_not_position(self):
        """The lookup that replaces positional assumptions. The class axis
        is deliberately NOT at the index TIDMAD puts it."""
        contract = TensorContract(
            axes=(
                _axis(AxisRole.BATCH, symbolic="B"),
                _axis(AxisRole.TEMPORAL, symbolic="T"),
                _axis(AxisRole.CLASS, fixed=7),
            ),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        )
        found = contract.axis_with_role(AxisRole.CLASS)
        assert found is not None
        assert found.dimension.fixed == 7
        assert contract.axis_with_role(AxisRole.BATCH) is contract.axes[0]


class TestCardinality:
    """§4b — derived, and 'not applicable' is semantic, not a sentinel."""

    def test_absent_class_axis_yields_none_not_zero(self):
        """The explicit *"cardinality is not meaningful for this output"*.

        The legacy ``num_classes: int = 0`` sentinel is exactly what §4b
        forbids promoting into the contract, so ``None`` — not ``0`` — is
        the answer, and a consumer cannot confuse it with a real count.
        """
        continuous = ModelIOContract(
            input=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(AxisRole.TEMPORAL, symbolic="T")),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            ),
            output=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(AxisRole.TEMPORAL, symbolic="T")),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            ),
        )
        assert continuous.class_cardinality is None
        assert continuous.class_cardinality != 0

    def test_a_symbolic_class_axis_has_no_concrete_count(self):
        """A class axis whose extent is symbolic carries no number, so the
        derived cardinality is ``None`` rather than a fabricated one."""
        contract = ModelIOContract(
            input=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"),),
                dtype=DtypeAdmissibility(admissible=("int64",)),
            ),
            output=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(AxisRole.CLASS, symbolic="C")),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            ),
        )
        assert contract.class_cardinality is None


class TestDtypeAdmissibility:
    """AMENDMENT A-1 — a requirement, not a concrete cast."""

    def test_canonical_is_the_first_admissible_dtype(self):
        """Order is meaning: the canonical representation is what renders
        into LLM-facing prose and what resolution defaults to."""
        assert DtypeAdmissibility(admissible=("int64", "int32")).canonical == "int64"
        assert DtypeAdmissibility(admissible=("int32", "int64")).canonical == "int32"

    def test_admits_the_whole_declared_set_not_only_the_canonical_one(self):
        """The A6 fact this exists to represent: the embedding arm accepts
        int32 AND int64, so a site preferring either is satisfied."""
        req = DtypeAdmissibility(admissible=("int64", "int32"))
        assert req.admits("int64")
        assert req.admits("int32")
        assert not req.admits("float32")

    def test_duplicates_are_rejected(self):
        with pytest.raises(ValidationError, match="duplicate dtype"):
            DtypeAdmissibility(admissible=("int64", "int64"))

    @pytest.mark.parametrize(
        "dtype",
        ["float16", "bfloat16", "float64", "bool", "complex64", "complex128"],
    )
    def test_dtypes_beyond_todays_validated_set_are_EXPRESSIBLE(self, dtype):
        """A-1 correction 2: contract expressiveness exceeds validated
        runtime support.

        Declaring one of these must not require a schema redesign later.
        This asserts EXPRESSIBILITY only — it is emphatically **not** a
        claim that the adaptation path can materialize these today. Only
        int32, int64 and float32 are validated as executable (A6), and
        execution support stays capability-gated.
        """
        req = DtypeAdmissibility(admissible=(dtype,))
        assert req.canonical == dtype
        assert req.admits(dtype)

    def test_an_empty_requirement_is_rejected(self):
        """A model admitting nothing is not a permissive model — it is an
        authoring error whose intersection is empty by construction."""
        with pytest.raises(ValidationError):
            DtypeAdmissibility(admissible=())


class TestSharedSymbolConsistency:
    """§4e — alignment rides on shared symbols, with no relation DSL."""

    def test_the_same_symbol_on_both_sides_is_the_alignment(self):
        """``T`` on input and output IS *"the output is as long as the
        input"*. No ``relationships:`` surface exists, and adding one is a
        §21 stop condition."""
        shared = {a.dimension.symbolic for a in TIDMAD.input.axes if a.dimension.symbolic} & {
            a.dimension.symbolic for a in TIDMAD.output.axes if a.dimension.symbolic
        }
        assert shared == {"B", "T"}

    def test_a_shared_symbol_with_conflicting_roles_is_rejected(self):
        """A shared symbol declares the SAME extent, so the two axes cannot
        mean different things."""
        with pytest.raises(ValidationError, match="different semantic roles"):
            ModelIOContract(
                input=TensorContract(
                    axes=(_axis(AxisRole.TEMPORAL, symbolic="X"),),
                    dtype=DtypeAdmissibility(admissible=("int64",)),
                ),
                output=TensorContract(
                    axes=(_axis(AxisRole.CLASS, symbolic="X"),),
                    dtype=DtypeAdmissibility(admissible=("float32",)),
                ),
            )

    def test_an_output_only_symbol_is_allowed(self):
        """Not every output extent must appear on the input — requiring it
        would be the relationship constraint §4e defers."""
        contract = ModelIOContract(
            input=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"),),
                dtype=DtypeAdmissibility(admissible=("int64",)),
            ),
            output=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(symbolic="Z")),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            ),
        )
        assert contract.output.render_shape() == "[B, Z]"


class TestMultiplicityIsBounded:
    """§4c — one input, one output. The bound is the point."""

    def test_the_contract_exposes_exactly_one_input_and_one_output(self):
        """A structural assertion, so a future 'just make it a list' edit
        has to confront §4c rather than slip through as a refactor."""
        fields = set(ModelIOContract.model_fields)
        assert fields == {"input", "output"}

    def test_no_multi_tensor_container_field_exists(self):
        with pytest.raises(ValidationError):
            ModelIOContract(
                inputs=[TIDMAD.input],  # type: ignore[call-arg]
                outputs=[TIDMAD.output],  # type: ignore[call-arg]
            )
