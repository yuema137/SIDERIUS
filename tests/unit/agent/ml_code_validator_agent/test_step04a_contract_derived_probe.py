"""Step 04a — the validator's shape probe derives from the declared contract.

Design: ``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
pr_04a_contract_derived_candidate_mechanics.md`` §16 C3, §15.1 (rows 1-3),
§9 failure classes 1, 2 and 5.

**The defect only this module catches.** ``_PROBE_NUM_CLASSES = 256`` was an
independent restatement of a task fact — the FU-A-1 deferral. Deleting the
constant is not the property; the property is that the probe's class extent,
rank, axis order and input value range now come FROM the declaration. A
rewrite that deleted the constant and inlined ``256`` at the call site would
pass every pre-existing test in this directory.

So every assertion below is on the **constructed tensor and the realized
shape**, never on a config field — §16's binding rule: *assert the
observable artifact, never the configuration value*.

The cardinality used throughout is **16**, not 256, for the reason that
makes the whole ladder work: the legacy path produces 256 anyway, so any
TIDMAD-valued assertion is satisfied by a probe that ignores the contract
entirely.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import torch

from agent.schemas.model_io_contract import (
    AxisRole,
    Dimension,
    ModelIOContract,
    TensorAxis,
    TensorContract,
)
from agent.skills.model_io_probe_skill import (
    PROBE_BATCH,
    PROBE_SYMBOLIC_EXTENT,
    ProbeConstructionError,
    build_model_input,
    expected_output_shape,
    realize_shape,
)
from nodes.ml_code_validator_agent import (
    MLCodeValidatorAgent,
    _check_instantiation_and_gradient,
)
from tests.helpers.step04a_fixtures import (
    SHIPPED_INPUT_DTYPE,
    SHIPPED_OUTPUT_DTYPE,
    regressor_model_io,
    tidmad_model_io,
)

# ---------------------------------------------------------------------------
# Plugin fixtures — a real forward pass, because a shape claim is only worth
# what an actual tensor proves.
# ---------------------------------------------------------------------------

_PLUGIN = """\
import torch
import torch.nn as nn
from pydantic import BaseModel, Field

PLUGIN_MODEL_TYPE = "{name}"


class Cfg(BaseModel):
    model_type: str = Field(default="{name}")
    segmentation_size: int = Field(default=64, ge=1)
    batch_size: int = Field(default=1, ge=1)


PLUGIN_CONFIG_CLASS = Cfg


class Net(nn.Module):
    def __init__(self, config):
        super().__init__()
        self.emb = nn.Embedding({vocab}, 8)
        self.head = nn.Conv1d(8, {out_channels}, kernel_size=1)

    def forward(self, x):
        out = self.head(self.emb(x).permute(0, 2, 1))
        return {return_expr}


PLUGIN_MODEL_CLASS = Net
PLUGIN_OUTPUT_TYPE = "{declaration}"
"""


def _write_plugin(tmp_path, name, *, vocab, out_channels, squeeze, declaration):
    path = tmp_path / f"{name}.py"
    path.write_text(
        _PLUGIN.format(
            name=name,
            vocab=vocab,
            out_channels=out_channels,
            return_expr="out.squeeze(1)" if squeeze else "out",
            declaration=declaration,
        ),
        encoding="utf-8",
    )
    return str(path)


# ---------------------------------------------------------------------------
# The headline: cardinality reaches the probe (rung 6.5-A's validator half)
# ---------------------------------------------------------------------------


def test_declared_cardinality_reaches_the_constructed_probe_tensor():
    """C3 acceptance: under ``{fixed: 16}`` the probe's max admissible index
    is 15 and the expected shape's class axis is 16 — asserted on the
    tensor, not on the contract.

    Fails when: the class extent is restated anywhere in the probe path.
    A re-hardcoded 256 gives max index 255 and class axis 256.
    """
    contract = tidmad_model_io(num_classes=16)

    probe = build_model_input(contract)
    assert probe.shape == (PROBE_BATCH, PROBE_SYMBOLIC_EXTENT)
    assert probe.dtype == torch.int64
    assert int(probe.max()) <= 15, "an index outside the declared alphabet was drawn"
    assert int(probe.min()) >= 0

    expected = expected_output_shape(contract, "classifier")
    assert expected == (PROBE_BATCH, 16, PROBE_SYMBOLIC_EXTENT)


def test_a_sixteen_class_candidate_validates_under_its_own_declaration(tmp_path):
    """End to end through the production probe, not the helper.

    A 16-symbol embedding fed a 256-valued index would raise inside the
    forward pass; a 16-class head judged against a 256-class expectation
    would be rejected on shape. Both failure modes are what this catches,
    and both are what a re-hardcoded literal reintroduces.
    """
    path = _write_plugin(
        tmp_path,
        "s04a_c3_sixteen",
        vocab=16,
        out_channels=16,
        squeeze=False,
        declaration="classifier",
    )
    verdict = _check_instantiation_and_gradient(path, tidmad_model_io(num_classes=16))
    assert verdict[:4] == (True, True, True, None)


def test_the_same_candidate_is_rejected_under_the_tidmad_declaration(tmp_path):
    """The negative twin — without it the test above proves only "it runs".

    A 16-class candidate is NOT valid for a 256-class task, and the error
    must name the shape it judged against so an operator can see why.
    """
    path = _write_plugin(
        tmp_path,
        "s04a_c3_sixteen_under_tidmad",
        vocab=256,
        out_channels=16,
        squeeze=False,
        declaration="classifier",
    )
    inst_ok, _grad, _otype, err, _t, _tt = _check_instantiation_and_gradient(
        path, tidmad_model_io()
    )
    assert inst_ok is False
    assert err is not None
    assert "(1, 256, 64)" in err, f"the error does not name the declared shape: {err}"


# ---------------------------------------------------------------------------
# §15.1 rows 1-3
# ---------------------------------------------------------------------------


def test_tidmad_contract_reproduces_the_legacy_verdict_exactly(tmp_path):
    """Row 2 under the shipped task: deriving must change nothing.

    Fails when: the derivation and the legacy geometry disagree for TIDMAD —
    which is the Stage-A parity criterion, checked here on a live verdict
    rather than only on the Checkpoint-0 golden.
    """
    path = _write_plugin(
        tmp_path,
        "s04a_c3_parity",
        vocab=256,
        out_channels=256,
        squeeze=False,
        declaration="classifier",
    )
    legacy = _check_instantiation_and_gradient(path)
    derived = _check_instantiation_and_gradient(path, tidmad_model_io())
    assert derived == legacy


def test_absent_contract_does_not_raise_and_keeps_legacy_geometry(tmp_path):
    """Row 1: absence is the legacy path, never an error.

    Fails when: someone collapses rows 1 and 3 into "no contract -> fail
    closed", which the design calls out explicitly as wrong.
    """
    path = _write_plugin(
        tmp_path,
        "s04a_c3_legacy",
        vocab=256,
        out_channels=256,
        squeeze=False,
        declaration="classifier",
    )
    assert _check_instantiation_and_gradient(path)[:4] == (True, True, True, None)


def test_continuous_contract_with_a_classifier_declaration_fails_closed(tmp_path):
    """Row 3: an explicit contract that cannot supply a required semantic.

    The candidate claims a class alphabet its task never declared. There is
    no cardinality to derive, so the probe must refuse rather than guess —
    a fabricated 256 would validate it against a shape nobody asked for.

    Fails when: the probe falls back to any default cardinality.
    """
    path = _write_plugin(
        tmp_path,
        "s04a_c3_failclosed",
        vocab=256,
        out_channels=256,
        squeeze=False,
        declaration="classifier",
    )
    inst_ok, grad_ok, otype_ok, err, _t, _tt = _check_instantiation_and_gradient(
        path, regressor_model_io()
    )
    assert (inst_ok, grad_ok, otype_ok) == (False, False, False)
    assert err is not None
    assert "Probe construction failed" in err
    assert "no class-alphabet axis" in err or "class cardinality" in err

    # The helper raises the typed error rather than returning a shape.
    with pytest.raises(ProbeConstructionError):
        expected_output_shape(regressor_model_io(), "classifier")


def test_a_regressor_contract_does_not_synthesize_a_class_axis(tmp_path):
    """C3 edge case: no class axis declared -> none in the expected shape."""
    contract = regressor_model_io()
    assert contract.class_cardinality is None
    assert expected_output_shape(contract, "regressor") == (
        PROBE_BATCH,
        PROBE_SYMBOLIC_EXTENT,
    )

    path = _write_plugin(
        tmp_path,
        "s04a_c3_regressor",
        vocab=64,
        out_channels=1,
        squeeze=True,
        declaration="regressor",
    )
    assert _check_instantiation_and_gradient(path, contract)[:4] == (True, True, True, None)


def test_a_regressor_candidate_still_passes_under_a_categorical_task(tmp_path):
    """The Stage-A precedent the derivation must NOT break.

    Three plugins in the live corpus declare ``regressor`` while the shipped
    task contract is categorical, and they validate today: a model is judged
    against the contract IT declares (V21 PR-A2). Deriving the FORM from the
    task contract instead of the declaration would start rejecting them —
    a TIDMAD verdict change, i.e. a Stage-A parity break.

    Fails when: the class axis is forced into the expected shape for a
    candidate that declared the continuous form.
    """
    contract = tidmad_model_io()
    assert expected_output_shape(contract, "regressor") == (
        PROBE_BATCH,
        PROBE_SYMBOLIC_EXTENT,
    )

    path = _write_plugin(
        tmp_path,
        "s04a_c3_reg_under_cat",
        vocab=256,
        out_channels=1,
        squeeze=True,
        declaration="regressor",
    )
    assert _check_instantiation_and_gradient(path, contract)[:4] == (True, True, True, None)


# ---------------------------------------------------------------------------
# Rank/axis-order blindness — the property that makes this generic at all
# ---------------------------------------------------------------------------


def test_realization_follows_declared_rank_and_axis_order():
    """Rank and order come from the contract, not from a 2-D/3-D assumption.

    Fails when: the realizer hardcodes a position for the class axis, or
    assumes the class axis is second. A task declaring
    ``[B, T, C]`` — class LAST — must realize as ``(1, 64, 7)``, not
    ``(1, 7, 64)``.

    This is not a hypothetical shape: ``AxisRole`` exists precisely so a
    consumer asks *which axis is the alphabet* rather than *is this rank 3*
    (Step-03 §4d), and nothing in the contract constrains the order.
    """
    class_last = ModelIOContract(
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
                TensorAxis(dimension=Dimension(fixed=7), role=AxisRole.CLASS),
            ),
            dtype=SHIPPED_OUTPUT_DTYPE,
        ),
    )

    assert realize_shape(class_last.output) == (
        PROBE_BATCH,
        PROBE_SYMBOLIC_EXTENT,
        7,
    )
    assert expected_output_shape(class_last, "classifier") == (
        PROBE_BATCH,
        PROBE_SYMBOLIC_EXTENT,
        7,
    )
    # Dropping the class axis must remove the LAST axis here, not the middle.
    assert expected_output_shape(class_last, "regressor") == (
        PROBE_BATCH,
        PROBE_SYMBOLIC_EXTENT,
    )


class TestTheProductionPathActuallyUsesTheContract:
    """Reachability: ``run()`` must FORWARD the contract into the probe.

    **This class exists because a mutation survived without it.** Replacing
    ``model_io_contract=inp.model_io_contract`` with ``None`` inside
    ``MLCodeValidatorAgent.run`` left the whole validator directory green:
    every other test in this module calls ``_check_instantiation_and_gradient``
    directly, so none of them crosses the production wiring. That is exactly
    the boundary CLAUDE.md requires reachability evidence for — a helper can
    be perfect and never be reached.

    The candidate here is 16-class. It validates ONLY if the 16-class
    declaration travelled from ``ValidatorInput`` to the probe; under the
    legacy geometry the probe feeds indices up to 255 into a 16-symbol
    embedding and the forward pass raises.
    """

    @staticmethod
    def _passing_bridge():
        from agent.schemas.validator import LLMCodeReview

        bridge = MagicMock()
        bridge.generate.return_value = LLMCodeReview(
            spec_alignment=True,
            trainability_concerns=[],
            implementation_issues=[],
            passed=True,
            notes="fixture",
        ).model_dump()
        return bridge

    def _input(self, tmp_path, contract):
        from agent.schemas.storage import LocalStorageConfig, StorageConfig
        from agent.schemas.validator import ValidatorInput

        model_path = _write_plugin(
            tmp_path,
            "s04a_c3_reachability",
            vocab=16,
            out_channels=16,
            squeeze=False,
            declaration="classifier",
        )
        desc = tmp_path / "description.md"
        desc.write_text("A sixteen-class candidate used as reachability evidence." * 3)
        test_file = tmp_path / "test_s04a_c3_reachability.py"
        test_file.write_text("def test_ok():\n    assert True\n")

        return ValidatorInput(
            model_type="s04a_c3_reachability",
            model_file_path=model_path,
            test_file_path=str(test_file),
            description_file_path=str(desc),
            config_fields={"channels": 8},
            model_description="reachability probe",
            mathematical_definition="reachability probe",
            model_io_contract=contract,
            storage=StorageConfig(
                backend="local",
                local=LocalStorageConfig(workspace=str(tmp_path), run_name="s04a"),
            ),
        )

    def test_run_forwards_the_contract_so_a_16_class_candidate_passes(self, tmp_path):
        """Fails when: ``run()`` stops passing ``inp.model_io_contract``."""
        agent = MLCodeValidatorAgent(bridge_factory=lambda **_kw: self._passing_bridge())
        out = agent.run(self._input(tmp_path, tidmad_model_io(num_classes=16)))

        assert out.instantiation_passed is True, out.error_message
        assert out.gradient_check_passed is True
        assert out.output_type_valid is True

    def test_run_without_a_contract_rejects_the_same_candidate(self, tmp_path):
        """The negative twin: proves the test above is not passing by luck.

        With no contract the legacy probe draws indices up to 255 and the
        16-symbol embedding raises — so a green result in the test above
        genuinely required the declaration to arrive.
        """
        agent = MLCodeValidatorAgent(bridge_factory=lambda **_kw: self._passing_bridge())
        out = agent.run(self._input(tmp_path, None))

        assert out.instantiation_passed is False
        assert out.error_message is not None


def test_a_fixed_extent_is_honoured_and_a_symbolic_one_is_a_recipe():
    """The recipe/semantics boundary, asserted rather than asserted-in-prose.

    A ``fixed`` extent is a declared fact the probe must reproduce; a
    ``symbolic`` one names an alignment, so any length satisfies it. Fails
    when: a fixed extent is realized at the recipe length (the task's
    declared alphabet silently replaced by 64), or a symbolic axis is
    treated as a magnitude.
    """
    contract = tidmad_model_io(num_classes=13)
    assert realize_shape(contract.output) == (PROBE_BATCH, 13, PROBE_SYMBOLIC_EXTENT)
    assert realize_shape(contract.input) == (PROBE_BATCH, PROBE_SYMBOLIC_EXTENT)


# ---------------------------------------------------------------------------
# C6 — the reviewer's prompt states the contract it was given
# ---------------------------------------------------------------------------


class TestTheReviewPromptRendersFromTheDeclaration:
    """Design §9 failure class 6: *a rendered prompt drifts from the contract
    it claims to state*.

    A system prompt naming ``[B, 256, T]`` for a task declaring sixteen
    classes does not merely read oddly — it instructs the LLM reviewer to
    reject every correct candidate. Nothing else in the pipeline catches it,
    because the defect lives in prose: the deterministic probe would pass the
    candidate and the reviewer would fail it, and the verdict would look like
    a model-quality judgement.

    ``pb6_*`` pins the shipped bytes but cannot detect this, because the
    fixture supplies no contract and so exercises only the legacy path.
    """

    @staticmethod
    def _prompt(contract):
        from nodes.ml_code_validator_agent.ml_code_validator_agent import (
            _build_review_system_prompt,
        )

        return _build_review_system_prompt(contract)

    def test_the_legacy_path_renders_the_shipped_text(self):
        """§15.1 row 1 — and the reason ``pb6_*`` stays exact."""
        rendered = self._prompt(None)
        assert '"classifier" must emit [B, 256, T]' in rendered
        assert '"regressor" must emit [B, T]' in rendered
        assert "{CLASSIFIER_SHAPE}" not in rendered
        assert "{REGRESSOR_SHAPE}" not in rendered

    def test_tidmad_renders_byte_identically_to_the_legacy_path(self):
        """Stage-A parity, asserted between the two paths.

        Comparing each to a golden would let both drift together; comparing
        them to each other cannot.
        """
        assert self._prompt(tidmad_model_io()) == self._prompt(None)

    def test_a_sixteen_class_task_is_described_as_sixteen_class(self):
        """The headline: change the declaration, the prompt follows.

        Fails when: either shape token is restated instead of rendered.
        """
        rendered = self._prompt(tidmad_model_io(num_classes=16))
        assert '"classifier" must emit [B, 16, T]' in rendered
        assert "[B, 256, T]" not in rendered

    def test_a_continuous_task_does_not_promise_a_class_alphabet(self):
        """A task declaring no alphabet has no classifier form to describe.

        The probe fails closed on exactly this case, so the prompt must not
        promise the reviewer something the probe would refuse. Fails when: a
        cardinality is invented to fill the sentence.
        """
        rendered = self._prompt(regressor_model_io())
        assert '"regressor" must emit [B, T]' in rendered
        assert "(not declared by this task)" in rendered
        assert "[B, 256, T]" not in rendered
