"""Checkpoint B — the atomic contrast ladder — Step 03 §11.

Design:
``docs/design/generic_framework_upgrade/step_03_model_loss_contract.md``
§11 (the ladder), **§11.1** (what makes a rung count), §8b, §21.

This module owns the two rungs no milestone produced as a by-product —
**3-A** (axis structure) and **3-D** (canonical output semantic) — and the
ladder-level property §11.1 demands of ALL of them:

    *atomicity is machine-checked, not asserted in prose* — each rung
    varies exactly one axis relative to the TIDMAD declaration, proven
    mechanically (the 02a/02b/02c ``_diff_paths`` precedent).

The other six rungs live with the milestone that made them true, and are
listed in ``LADDER`` below so Checkpoint B has one place that enumerates
the whole ladder rather than a claim spread across six files:

===========  ==================================================
rung         owned by
===========  ==================================================
3-A          this module
3-B          test_step03_m5_input_dtype_resolution.py
3-B-neg      test_step03_m5_input_dtype_resolution.py
3-C          test_step03_m6_cardinality_derivation.py
3-D          this module
FX-3         test_model_io_resolution.py
FX-4         test_model_io_resolution.py
3-E          test_model_io_resolution.py
===========  ==================================================
"""

from __future__ import annotations

import pytest

from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    DtypeAdmissibility,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from ml_models.models_format_sandbox import (
    OutputSemantic,
    validate_semantic_loss_compatibility,
)

#: Every rung of §11, with the module that proves it. Checkpoint B asserts
#: this list is complete and that nothing was quietly dropped.
LADDER = {
    "3-A": "tests/unit/agent/schemas/test_step03_checkpoint_b_ladder.py",
    "3-B": "tests/unit/execute_tools/test_step03_m5_input_dtype_resolution.py",
    "3-B-neg": "tests/unit/execute_tools/test_step03_m5_input_dtype_resolution.py",
    "3-C": "tests/unit/ml_models/test_step03_m6_cardinality_derivation.py",
    "3-D": "tests/unit/agent/schemas/test_step03_checkpoint_b_ladder.py",
    "FX-3": "tests/unit/agent/schemas/test_model_io_resolution.py",
    "FX-4": "tests/unit/agent/schemas/test_model_io_resolution.py",
    "3-E": "tests/unit/agent/schemas/test_model_io_resolution.py",
}


def _axis(role: AxisRole | None = None, **dim) -> TensorAxis:
    return TensorAxis(dimension=Dimension(**dim), role=role)


def _tidmad() -> ModelIOContract:
    return ModelIOContract(
        input=TensorContract(
            axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(AxisRole.TEMPORAL, symbolic="T")),
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


# ---------------------------------------------------------------------------
# §11.1 — atomicity, machine-checked
# ---------------------------------------------------------------------------


def _semantic_facets(contract: ModelIOContract) -> dict[str, object]:
    """The independent semantic axes of the contract, one entry each.

    Deliberately NOT ``model_dump()``: a raw dump conflates facets (moving
    the class axis changes ``axes`` AND ``class_cardinality`` AND
    ``output_semantic``), so a diff over it could never show that a rung
    varies one THING. These keys are the axes §11 names.
    """
    return {
        "input_axis_roles": tuple(a.role for a in contract.input.axes),
        "input_rank": contract.input.rank,
        "input_dtype": contract.input.dtype.admissible,
        "output_axis_roles": tuple(a.role for a in contract.output.axes),
        "output_rank": contract.output.rank,
        "output_dtype": contract.output.dtype.admissible,
        "output_semantic": contract.output_semantic,
        "class_cardinality": contract.class_cardinality,
    }


def _varied_facets(baseline: ModelIOContract, contrast: ModelIOContract) -> set[str]:
    """Exactly which semantic facets differ. The ``_diff_paths`` precedent."""
    base, other = _semantic_facets(baseline), _semantic_facets(contrast)
    return {key for key in base if base[key] != other[key]}


# ---------------------------------------------------------------------------
# Rung 3-A — axis structure
# ---------------------------------------------------------------------------


class TestRung3AAxisStructure:
    """**3-A** — rank and ordered axes vary; roles preserved.

    §11's failure criterion: *"any consumer branching on rank"*.
    """

    @pytest.fixture
    def rank4(self) -> ModelIOContract:
        """TIDMAD with ONE extra unroled axis on each tensor.

        Unroled deliberately: adding a *roled* axis would also move the
        role tuples, and roles are what the other rungs vary. This changes
        rank and rank alone.
        """
        return ModelIOContract(
            input=TensorContract(
                axes=(
                    _axis(AxisRole.BATCH, symbolic="B"),
                    _axis(fixed=3),
                    _axis(AxisRole.TEMPORAL, symbolic="T"),
                ),
                dtype=DtypeAdmissibility(admissible=("int64", "int32")),
            ),
            output=TensorContract(
                axes=(
                    _axis(AxisRole.BATCH, symbolic="B"),
                    _axis(AxisRole.CLASS, fixed=256),
                    _axis(fixed=3),
                    _axis(AxisRole.TEMPORAL, symbolic="T"),
                ),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            ),
        )

    def test_it_varies_rank_and_only_rank(self, rank4):
        """Atomicity, machine-checked. The role tuples grow a `None` entry
        because an axis was inserted — that IS the rank change, and the
        SEQUENCE of non-None roles is asserted identical below."""
        varied = _varied_facets(_tidmad(), rank4)
        assert varied == {"input_rank", "output_rank", "input_axis_roles", "output_axis_roles"}

    def test_the_semantic_roles_are_preserved_in_order(self, rank4):
        """§11 says 'roles preserved'. The unroled insertion must not
        reorder or drop a role."""
        for baseline_tensor, contrast_tensor in (
            (_tidmad().input, rank4.input),
            (_tidmad().output, rank4.output),
        ):
            assert [a.role for a in baseline_tensor.axes if a.role is not None] == [
                a.role for a in contrast_tensor.axes if a.role is not None
            ]

    def test_every_unvaried_consumer_is_unchanged(self, rank4):
        """The independence claim §11.1 requires: dtype, cardinality and
        output semantics must all be untouched by a rank change."""
        baseline = _tidmad()
        assert rank4.input.dtype.admissible == baseline.input.dtype.admissible
        assert rank4.output.dtype.admissible == baseline.output.dtype.admissible
        assert rank4.class_cardinality == baseline.class_cardinality == 256
        assert rank4.output_semantic is baseline.output_semantic

    @pytest.mark.parametrize("rank", [1, 2, 3, 4, 5])
    def test_rendering_does_not_branch_on_rank(self, rank):
        """The consumer §11 names. A renderer that special-cased rank — as
        every hand-written `[B, 256, T]` prose restatement effectively does
        — cannot produce these."""
        axes = tuple([_axis(AxisRole.BATCH, symbolic="B")] + [_axis(fixed=8)] * (rank - 1))
        tensor = TensorContract(axes=axes, dtype=DtypeAdmissibility(admissible=("float32",)))
        expected = "[" + ", ".join(["B"] + ["8"] * (rank - 1)) + "]"
        assert tensor.render_shape() == expected
        assert tensor.rank == rank

    def test_role_lookup_is_position_independent(self, rank4):
        """The mechanism that makes rank-independence possible: a consumer
        asks which axis has a role, never which index it sits at. The class
        axis is at index 1 in TIDMAD and still index 1 here — so the
        stronger case is asserted directly."""
        shuffled = TensorContract(
            axes=(
                _axis(AxisRole.TEMPORAL, symbolic="T"),
                _axis(fixed=3),
                _axis(AxisRole.CLASS, fixed=256),
                _axis(AxisRole.BATCH, symbolic="B"),
            ),
            dtype=DtypeAdmissibility(admissible=("float32",)),
        )
        found = shuffled.axis_with_role(AxisRole.CLASS)
        assert found is not None and found.dimension.fixed == 256
        assert shuffled.axis_with_role(AxisRole.BATCH) is shuffled.axes[3]


# ---------------------------------------------------------------------------
# Rung 3-D — canonical output semantic
# ---------------------------------------------------------------------------


class TestRung3DOutputSemantic:
    """**3-D** — the canonical output semantic varies, alone.

    §11's failure criterion: *"loss legality still keyed on a legacy
    string"*.

    **A reconciliation with §11's phrasing, recorded rather than glossed.**
    §11 lists 3-D as holding *"axes, dtype, cardinality"* fixed. That was
    written when the design imagined output semantics as a separate
    DECLARATION. §8b made it DERIVED from the output tensor, so a contract
    cannot change its output semantic without changing whether it carries a
    class axis — and cardinality then becomes *not applicable* rather than
    a different number.

    This is still ONE semantic axis (does the output carry a class
    alphabet), not two, so §11.1's *"a rung that needs two axes is a STOP"*
    does not fire. What varies is the semantic; the class axis is its
    representation, and cardinality following it to ``None`` is §4b's
    deliberate asymmetry, not a second variable. The facet diff below
    states exactly that, mechanically.
    """

    @pytest.fixture
    def continuous(self) -> ModelIOContract:
        """TIDMAD with the class axis removed — a continuous output."""
        return ModelIOContract(
            input=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(AxisRole.TEMPORAL, symbolic="T")),
                dtype=DtypeAdmissibility(admissible=("int64", "int32")),
            ),
            output=TensorContract(
                axes=(_axis(AxisRole.BATCH, symbolic="B"), _axis(AxisRole.TEMPORAL, symbolic="T")),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            ),
        )

    def test_it_varies_the_output_semantic_and_its_representation_only(self, continuous):
        """Atomicity, machine-checked, and the reconciliation made explicit:
        the INPUT side is entirely untouched, and every output facet that
        moves is the class axis or something derived from it."""
        varied = _varied_facets(_tidmad(), continuous)
        assert varied == {
            "output_semantic",
            "class_cardinality",
            "output_axis_roles",
            "output_rank",
        }
        assert not {f for f in varied if f.startswith("input_")}

    def test_the_semantic_flips(self, continuous):
        assert _tidmad().output_semantic is OutputSemantic.CATEGORICAL
        assert continuous.output_semantic is OutputSemantic.CONTINUOUS

    def test_loss_legality_follows_the_semantic(self, continuous):
        """The rung's point. Legality is a function of the canonical
        semantic — a rule still keyed on the legacy string could not be
        driven from a contract at all."""
        categorical = _tidmad().output_semantic
        validate_semantic_loss_compatibility(categorical, "focal", model_type="3d_probe")
        with pytest.raises(ValueError):
            validate_semantic_loss_compatibility(categorical, "smooth_l1", model_type="3d_probe")

        cont = continuous.output_semantic
        validate_semantic_loss_compatibility(cont, "smooth_l1", model_type="3d_probe")
        with pytest.raises(ValueError):
            validate_semantic_loss_compatibility(cont, "focal", model_type="3d_probe")

    def test_the_verdicts_genuinely_differ_between_the_two(self, continuous):
        """Without this, a rule that accepted everything would satisfy both
        halves above and the rung would prove nothing."""
        legal = {}
        for name, contract in (("categorical", _tidmad()), ("continuous", continuous)):
            accepted = []
            for loss in ("ce", "focal", "focal_cw", "smooth_l1", "custom"):
                try:
                    validate_semantic_loss_compatibility(
                        contract.output_semantic, loss, model_type="3d_probe"
                    )
                    accepted.append(loss)
                except ValueError:
                    pass
            legal[name] = accepted
        assert legal["categorical"] == ["ce", "focal", "focal_cw", "custom"]
        assert legal["continuous"] == ["smooth_l1", "custom"]

    def test_dtype_does_not_follow_the_output_semantic(self, continuous):
        """§4a.1 forbids inferring the input dtype requirement from output
        semantics. The contrast flips the semantic and the input
        admissibility must not move — the correlation A6 shows in the
        current builtin roster is not a framework law."""
        assert continuous.input.dtype.admissible == _tidmad().input.dtype.admissible


# ---------------------------------------------------------------------------
# Ladder completeness
# ---------------------------------------------------------------------------


class TestLadderIsComplete:
    """Checkpoint B's own claim: every §11 rung exists and is owned."""

    def test_every_frozen_rung_has_an_owner(self):
        assert set(LADDER) == {
            "3-A",
            "3-B",
            "3-B-neg",
            "3-C",
            "3-D",
            "FX-3",
            "FX-4",
            "3-E",
        }

    def test_each_owning_module_exists(self):
        import pathlib

        repo = pathlib.Path(__file__).resolve().parents[4]
        for rung, module in LADDER.items():
            assert (repo / module).is_file(), f"{rung} -> {module}"

    def test_no_multi_tensor_or_relation_rung_was_added(self):
        """§4c and §4e defer both, and §11 says multi-tensor is explicitly
        NOT a rung. A ladder that grew one would mean the deferral leaked."""
        assert not any("multi" in rung.lower() or "relation" in rung.lower() for rung in LADDER)
