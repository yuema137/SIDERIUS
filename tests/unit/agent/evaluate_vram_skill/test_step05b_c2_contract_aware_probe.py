"""Step 05b C2 — the VRAM probe realizes its target from a declared contract.

Design:
``docs/design/generic_framework_upgrade/step_05b_tuner_resource_time.md``
§0.5 (output-form authority), §2 (the `256` classification), C2.

The live capacity gate built its float target from a ``[B, 256, T]`` literal
(`wrapper.py`), while Step 04a already owned one shape-realization authority
that the implementor and the validator both use. C2 makes the gate the third
consumer of that authority — **without** a second form table, a second dtype
mapping, or any production caller supplying a contract yet.

The authority split C2 inherits, unchanged:

    candidate declaration (get_output_type)  ->  selects the output FORM
    ModelIOContract                          ->  supplies the FACTS in it
    model_io_probe_skill                     ->  realizes the tensor

Failure classes guarded here, each one a way the seam could look right and
be wrong:

1. **the legacy path moves.** With no contract, the gate must build exactly
   the C0 baseline. This is the whole compatibility claim and it is an
   equality, not an argument.
2. **the shipped contract is not equivalent to the literal.** Under TIDMAD,
   supplying the contract must produce the SAME tensor the literal produced.
   If it did not, C4 would change a live admission decision.
3. **a second form table appears.** The realized target must equal what
   ``declared_output_tensor`` + ``realize_shape`` produce for the same
   contract and form — asserted against the 04a authority, not a restated
   table here.
4. **dtype ownership moves to the contract.** The contract supplies shape;
   the loss supplies dtype. A contract whose declared dtype disagrees with
   the loss's must not move the built dtype.
5. **a contract failure falls back to the literal.** Refusals propagate. A
   silently-wrong probe reports a capacity number for a different model,
   which is the defect this seam removes, not one it may reintroduce.
"""

from __future__ import annotations

import pathlib

import pytest
import torch

from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from agent.skills.evaluate_vram_skill import wrapper
from agent.skills.evaluate_vram_skill.wrapper import _build_probe_tensors
from agent.skills.model_io_probe_skill import (
    ProbeConstructionError,
    declared_output_tensor,
    realize_shape,
)
from ml_models import plugin_loader
from tests.helpers.step04a_fixtures import (
    SHIPPED_INPUT_DTYPE,
    SHIPPED_OUTPUT_DTYPE,
    regressor_model_io,
    tidmad_model_io,
)

BATCH, SEG = 4, 128

#: A float-target loss. ``smooth_l1`` is the shipped one; it is what makes
#: the float branch — the only branch carrying a contract-owned extent —
#: reachable at all.
FLOAT_LOSS = "smooth_l1"


@pytest.fixture
def declared(monkeypatch):
    def _set(model_type: str, output_type: str) -> str:
        monkeypatch.setitem(plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY, model_type, output_type)
        return model_type

    return _set


def _float_target_loss(monkeypatch) -> None:
    """Make a CLASSIFIER-declared candidate take the float target branch.

    Reachable in production: ``loss_type='custom'`` is in neither
    ``CLASSIFICATION_LOSSES`` nor ``REGRESSION_LOSSES``
    (``models_format_sandbox.py:384-387``), so the semantic/loss rule permits
    a classifier with a custom float-target loss — and the classifier form is
    the one whose target actually carries the class alphabet. Patching the
    dtype resolver keeps the case a one-line fixture instead of a plugin.
    """
    monkeypatch.setattr(wrapper, "get_target_torch_dtype", lambda _cfg: torch.float32)


# ---------------------------------------------------------------------------
# 1 + 2. Legacy equality, and shipped-contract equivalence
# ---------------------------------------------------------------------------


class TestTheLegacyPathIsUntouched:
    @pytest.mark.parametrize(
        ("output_type", "loss_type", "expected_shape", "expected_dtype"),
        [
            ("classifier", "ce", (BATCH, SEG), torch.int64),
            ("regressor", FLOAT_LOSS, (BATCH, SEG), torch.float32),
            ("hybrid", FLOAT_LOSS, (BATCH, 256, SEG), torch.float32),
        ],
    )
    def test_no_contract_equals_the_c0_baseline(
        self, declared, output_type, loss_type, expected_shape, expected_dtype
    ):
        mt = declared(f"s05b_c2_legacy_{output_type}", output_type)
        _inp, tgt = _build_probe_tensors(BATCH, SEG, loss_type, None, model_type=mt)
        assert (tuple(tgt.shape), tgt.dtype) == (expected_shape, expected_dtype)


class TestTheShippedContractIsEquivalentToTheLiteral:
    """Under TIDMAD, supplying the contract must change nothing at all.

    This is what makes C4 safe to ship: the first live consumer cannot move
    a forecast, an admission decision or a resolved batch size, because the
    tensor it prices is the same tensor.
    """

    def test_classifier_form_reproduces_the_broadcast_target(self, declared, monkeypatch):
        mt = declared("s05b_c2_shipped_classifier", "classifier")
        _float_target_loss(monkeypatch)

        _i_legacy, legacy = _build_probe_tensors(BATCH, SEG, FLOAT_LOSS, None, model_type=mt)
        _i_bound, bound = _build_probe_tensors(
            BATCH, SEG, FLOAT_LOSS, None, model_type=mt, model_io_contract=tidmad_model_io()
        )
        assert tuple(bound.shape) == (BATCH, 256, SEG)
        assert (tuple(bound.shape), bound.dtype) == (tuple(legacy.shape), legacy.dtype)

    def test_regressor_form_reproduces_the_two_d_target(self, declared):
        mt = declared("s05b_c2_shipped_regressor", "regressor")
        _i_legacy, legacy = _build_probe_tensors(BATCH, SEG, FLOAT_LOSS, None, model_type=mt)
        _i_bound, bound = _build_probe_tensors(
            BATCH, SEG, FLOAT_LOSS, None, model_type=mt, model_io_contract=tidmad_model_io()
        )
        assert tuple(bound.shape) == (BATCH, SEG)
        assert (tuple(bound.shape), bound.dtype) == (tuple(legacy.shape), legacy.dtype)

    def test_the_class_index_branch_never_consults_the_contract(self, declared):
        """A long target is class indices — no contract-owned extent — so it
        returns before any contract is read. Supplying one must not move it,
        and must not make an unregistered model newly refusable."""
        mt = declared("s05b_c2_shipped_ce", "classifier")
        _inp, tgt = _build_probe_tensors(
            BATCH, SEG, "ce", None, model_type=mt, model_io_contract=tidmad_model_io()
        )
        assert (tuple(tgt.shape), tgt.dtype) == ((BATCH, SEG), torch.int64)


# ---------------------------------------------------------------------------
# 3. No second form table
# ---------------------------------------------------------------------------


class TestRealizationDelegatesToTheStep04aAuthority:
    @pytest.mark.parametrize("form", ["classifier", "regressor"])
    @pytest.mark.parametrize("num_classes", [256, 16])
    def test_the_target_equals_what_the_04a_authority_realizes(
        self, declared, monkeypatch, form, num_classes
    ):
        """Asserted against ``declared_output_tensor`` + ``realize_shape``,
        never against a table restated in this test. A local resolution table
        in the VRAM path is §10's failure class 5 — a SECOND probe authority,
        undoing Step 04a."""
        mt = declared(f"s05b_c2_authority_{form}_{num_classes}", form)
        _float_target_loss(monkeypatch)
        contract = tidmad_model_io(num_classes=num_classes)

        _inp, tgt = _build_probe_tensors(
            BATCH, SEG, FLOAT_LOSS, None, model_type=mt, model_io_contract=contract
        )
        expected = realize_shape(declared_output_tensor(contract, form), batch=BATCH, symbolic=SEG)
        assert tuple(tgt.shape) == expected

    def test_the_candidates_real_extents_are_honoured(self, declared, monkeypatch):
        """Not ``PROBE_BATCH`` / ``PROBE_SYMBOLIC_EXTENT``. A capacity probe
        realized at ``(1, ..., 64)`` measures a tensor nobody will run."""
        mt = declared("s05b_c2_extents", "classifier")
        _float_target_loss(monkeypatch)
        _inp, tgt = _build_probe_tensors(
            BATCH, SEG, FLOAT_LOSS, None, model_type=mt, model_io_contract=tidmad_model_io()
        )
        assert tuple(tgt.shape) == (BATCH, 256, SEG)

    def test_a_regressor_under_a_categorical_contract_is_accepted(self, declared):
        """§0.5's supported compatibility surface, not a conflict. Three live
        plugins declare ``regressor`` under the shipped categorical task
        today; rejecting them would be a TIDMAD verdict change."""
        mt = declared("s05b_c2_regressor_under_categorical", "regressor")
        _inp, tgt = _build_probe_tensors(
            BATCH, SEG, FLOAT_LOSS, None, model_type=mt, model_io_contract=tidmad_model_io()
        )
        assert tuple(tgt.shape) == (BATCH, SEG), "the class axis is dropped, not rejected"

    def test_hybrid_keeps_its_legacy_target_under_a_contract(self, declared):
        """``hybrid`` is a legacy builtin adapter value, NOT a tensor semantic
        (Step-03 §8c). ``fcnet`` returns ``[B, T]`` under ``smooth_l1`` and
        ``[B, C, T]`` otherwise, so its emitted shape is chosen by the LOSS —
        a fact no Model-I/O contract owns. There is nothing to derive, so the
        shipped target is preserved rather than guessed at."""
        mt = declared("s05b_c2_hybrid", "hybrid")
        _inp, tgt = _build_probe_tensors(
            BATCH,
            SEG,
            FLOAT_LOSS,
            None,
            model_type=mt,
            model_io_contract=tidmad_model_io(num_classes=16),
        )
        assert tuple(tgt.shape) == (BATCH, 256, SEG)


# ---------------------------------------------------------------------------
# 4. dtype ownership
# ---------------------------------------------------------------------------


class TestDtypeStillComesFromTheLoss:
    def test_a_contract_declaring_another_dtype_does_not_move_the_target(self, declared):
        """The contract supplies SHAPE. Sourcing dtype from it would create a
        second dtype mapping beside ``get_target_torch_dtype`` — and this is
        the only test that would notice, since under TIDMAD both answers
        happen to be float32."""
        float64_output = ModelIOContract(
            input=TensorContract(
                axes=(
                    TensorAxis(dimension=Dimension(symbolic="B"), role=AxisRole.BATCH),
                    TensorAxis(dimension=Dimension(symbolic="T"), role=AxisRole.TEMPORAL),
                ),
                dtype=SHIPPED_INPUT_DTYPE,
            ),
            output=TensorContract(
                axes=(
                    TensorAxis(dimension=Dimension(symbolic="B"), role=AxisRole.BATCH),
                    TensorAxis(dimension=Dimension(symbolic="T"), role=AxisRole.TEMPORAL),
                ),
                dtype=SHIPPED_INPUT_DTYPE,  # declares int64/int32, not float32
            ),
        )
        mt = declared("s05b_c2_dtype", "regressor")
        _inp, tgt = _build_probe_tensors(
            BATCH, SEG, FLOAT_LOSS, None, model_type=mt, model_io_contract=float64_output
        )
        assert tgt.dtype == torch.float32, "dtype follows the loss, not the contract"

    def test_the_input_tensor_is_unchanged_by_a_contract(self, declared):
        """C2 derives the TARGET only. The probe input keeps its shipped
        ``[B, T]`` int64 construction on both paths."""
        mt = declared("s05b_c2_input", "regressor")
        bound, _t = _build_probe_tensors(
            BATCH, SEG, FLOAT_LOSS, None, model_type=mt, model_io_contract=tidmad_model_io()
        )
        legacy, _t2 = _build_probe_tensors(BATCH, SEG, FLOAT_LOSS, None, model_type=mt)
        assert (tuple(bound.shape), bound.dtype) == (tuple(legacy.shape), legacy.dtype)
        assert (tuple(bound.shape), bound.dtype) == ((BATCH, SEG), torch.int64)


# ---------------------------------------------------------------------------
# 5. Refusals propagate
# ---------------------------------------------------------------------------


class TestContractFailuresNeverFallBackToTheLiteral:
    def test_a_classifier_under_a_contract_with_no_class_axis_refuses(self, declared, monkeypatch):
        """Step 04a's own fail-closed case, surfaced by the VRAM path rather
        than swallowed. Building ``[B, 256, T]`` here would fabricate an
        alphabet the task never declared and price the candidate against it."""
        mt = declared("s05b_c2_classifier_no_classes", "classifier")
        _float_target_loss(monkeypatch)
        with pytest.raises(ProbeConstructionError):
            _build_probe_tensors(
                BATCH,
                SEG,
                FLOAT_LOSS,
                None,
                model_type=mt,
                model_io_contract=regressor_model_io(),
            )

    def test_a_contract_without_a_declaration_refuses(self):
        """A contract with no ``model_type`` has no declaration to select a
        form from. Silently taking the literal would price whatever shape the
        legacy branch happens to pick."""
        with pytest.raises(ValueError, match="no model_type"):
            _build_probe_tensors(BATCH, SEG, FLOAT_LOSS, None, model_io_contract=tidmad_model_io())

    def test_the_unregistered_model_refusal_still_fires_with_a_contract(self):
        """The C0 baseline's class 3, unchanged: an unregistered model has no
        declaration, so the refusal precedes any contract question."""
        with pytest.raises(ValueError, match="Cannot build a probe target"):
            _build_probe_tensors(
                BATCH,
                SEG,
                FLOAT_LOSS,
                None,
                model_type="s05b_c2_unregistered",
                model_io_contract=tidmad_model_io(),
            )


# ---------------------------------------------------------------------------
# The contract is RECEIVED, never resolved here
# ---------------------------------------------------------------------------


def test_no_resource_consumer_resolves_a_contract_of_its_own():
    """The frozen invariant, guarded where it can actually be broken.

    A resource consumer that resolved its own contract — by loading the task
    config, or by reaching for any other parallel source — would price a run
    against a declaration the run is not necessarily using, and it would do
    so while every shape assertion above stayed green. That is the exact
    defect shape Steps 02a/02b/05a removed elsewhere: "happens to agree" is
    not a binding.

    The contract arrives as an argument. There is nowhere in this package
    that may go and get one.
    """
    import pkgutil

    import agent.skills.evaluate_vram_skill as pkg

    forbidden = ("load_task_config", "resolve_model_io_contract", "load_model_io_contract")
    offenders: list[str] = []
    for mod in pkgutil.iter_modules(pkg.__path__):
        source = (pathlib.Path(pkg.__path__[0]) / f"{mod.name}.py").read_text(encoding="utf-8")
        offenders += [f"{mod.name}:{name}" for name in forbidden if name in source]
    assert not offenders, (
        "a VRAM resource consumer acquires a Model-I/O contract on its own "
        f"authority instead of receiving the run-bound one: {offenders}"
    )
