"""Step 04a — rung 6.5-D: a declared-regressor custom loss can be ACCEPTED.

Design: ``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
pr_04a_contract_derived_candidate_mechanics.md`` §4 (the custom-loss recipe),
§6 (Stage-B ladder), **§6.2** (this rung closes at the candidate-validation
boundary), §16 C5.

**This is the capability, not a literal sweep.** Before Step 04a
``_dummy_tensor_validate_loss`` built ``torch.randn(2, 256, 100)`` and
``torch.randint(0, 256, (2, 100))`` unconditionally. A declared-regressor
custom loss expects ``[B, T]`` float on both sides, so it could not pass under
any circumstance — it was rejected for a *shape accident*, never for anything
about the loss. The rung therefore **fails on the pre-Step-04a code by
construction**, which is what makes it worth writing.

**Why this module goes all the way to the validator.** §6.2 is explicit that
helper-level evidence is necessary but not sufficient: a finite scalar loss
and a finite ``inputs.grad`` prove the probe was built, not that the
capability exists. The frozen acceptance property is

    declared-regressor contract + valid custom loss
      -> production candidate generation
      -> production validator
      -> ACCEPT

so the test drives the real ``MLModelImplementor.run()``, maps its output
through the **production protocol**, and runs the real
``MLCodeValidatorAgent.run()``. No LLM call — the bridge is mocked with
recorded responses, which §6.2 explicitly permits.

**Atomicity (§6).** 6.5-D varies ONE axis against **6.5-C's established
regressor declaration**: same contract, now with a custom loss. It does not
also vary the output semantic — that is 6.5-C's job, and
``test_the_declaration_is_6_5_c_s_baseline_unchanged`` checks the two
declarations are identical mechanically rather than by assertion in prose.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent.schemas.implementor import ImplementorInput
from agent.schemas.proposal import CustomLossSpec
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.validator import LLMCodeReview
from agent_generated._registry import CapabilityRegistry
from nodes.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_model_implementor.ml_model_implementor import (
    MLModelImplementor,
    _assemble_loss_plugin,
    _dummy_tensor_validate_loss,
)
from tests.helpers.step04a_fixtures import forward_contract, regressor_model_io

# ---------------------------------------------------------------------------
# Recorded LLM contributions
# ---------------------------------------------------------------------------

#: A VALID regressor custom loss: MSE over a continuous prediction. Legal for
#: a continuous output semantic, and impossible to probe with the
#: classifier-shaped pair (F.mse_loss on [2,256,100] vs [2,100] int64 raises).
REGRESSOR_LOSS_CODE = {
    "extra_imports": "",
    "config_fields_code": "    beta: float = Field(default=1.0, gt=0.0)",
    "config_validators_code": "",
    "config_fields": {"beta": 1.0},
    "init_body": "        self.beta = config.beta",
    "forward_body": ("        return self.beta * F.mse_loss(inputs.float(), targets.float())"),
}

#: A regressor MODEL: [B, T] int -> [B, T] float.
REGRESSOR_MODEL_CODE = {
    "extra_imports": "",
    "config_fields_code": "    channels: int = Field(default=8, ge=1, le=64)",
    "config_fields": {"channels": 8},
    "init_body": (
        "        self.embedding = nn.Embedding(256, config.channels)\n"
        "        self.head = nn.Conv1d(config.channels, 1, 1)"
    ),
    "forward_body": (
        "        x = self.embedding(x.long()).transpose(1, 2)\n"
        "        return self.head(x).squeeze(1)"
    ),
}

FAKE_REASONING = "Frozen fixture reasoning for the 6.5-D capability rung."


@pytest.fixture
def loss_spec():
    return CustomLossSpec(
        loss_name="s04a_regressor_mse",
        description="Beta-scaled MSE for a continuous waveform prediction.",
        mathematical_definition="L = beta * mean((inputs - targets)^2)",
    )


@pytest.fixture
def regressor_input(tmp_path, loss_spec):
    """A candidate declaring the CONTINUOUS form under a regressor task."""
    return ImplementorInput(
        model_name="s04a_regressor_capability",
        output_type="regressor",
        model_description="Embedding -> Conv1d -> squeeze; continuous output.",
        mathematical_definition="y = Conv1d(Embedding(x)) squeezed to [B, T].",
        baseline_config={
            "model_config": {"channels": 8, "segmentation_size": 128},
            "train_config": {"lr": 5e-4, "epochs": 1, "batch_size": 2},
            "loss_config": {"loss_type": "custom", "loss_name": "s04a_regressor_mse"},
        },
        task_description="Continuous waveform denoising (6.5-C declaration).",
        forward_contract=forward_contract(regressor_model_io()),
        plugin_dir=str(tmp_path / "models"),
        test_dir=str(tmp_path / "tests"),
        loss_dir=str(tmp_path / "losses"),
        custom_loss_spec=loss_spec,
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path / "ws"), run_name="s04a_d"),
        ),
    )


@pytest.fixture
def implementor(tmp_path):
    agent = MLModelImplementor.__new__(MLModelImplementor)
    agent.bridge = MagicMock()
    agent.bridge.generate_text.return_value = FAKE_REASONING
    agent.bridge.generate.side_effect = [REGRESSOR_LOSS_CODE, REGRESSOR_MODEL_CODE]
    agent._registry = CapabilityRegistry(index_path=str(tmp_path / "_capability_index.json"))
    return agent


def _validator():
    bridge = MagicMock()
    bridge.generate.return_value = LLMCodeReview(
        spec_alignment=True,
        trainability_concerns=[],
        implementation_issues=[],
        passed=True,
        notes="fixture reviewer",
    ).model_dump()
    return MLCodeValidatorAgent(bridge_factory=lambda **_kw: bridge)


# ---------------------------------------------------------------------------
# The frozen acceptance property (§6.2)
# ---------------------------------------------------------------------------


def test_a_regressor_custom_loss_candidate_is_generated_and_ACCEPTED(implementor, regressor_input):
    """The 6.5-D capability, closed at the candidate-validation boundary.

    Fails when: the loss probe builds classifier-shaped tensors — i.e.
    today's behaviour, under which ``run()`` exhausts its repair loop and
    raises ``ValueError`` before a candidate exists at all.

    It also fails if the contract stops reaching the validator, because the
    generated regressor plugin would then be probed against the legacy
    classifier geometry.
    """
    # Nothing is stubbed on the validator side: its pytest subprocess really
    # runs the generated test file, so the candidate's OWN test is part of
    # the evidence rather than something the rung assumes away.
    impl_out = implementor.run(regressor_input)

    assert impl_out.loss_provenance is not None
    assert impl_out.loss_provenance.action == "generated"
    assert impl_out.loss_provenance.dummy_tensor_validated is True

    # The production protocol, not a hand-built ValidatorInput.
    valid_in = local_all_fields(
        impl_out,
        StorageConfig(
            backend="local",
            local=LocalStorageConfig(
                workspace=regressor_input.storage.local.workspace, run_name="s04a_d"
            ),
        ),
    )
    assert valid_in.model_io_contract == regressor_model_io()

    verdict = _validator().run(valid_in)

    assert verdict.instantiation_passed is True, verdict.error_message
    assert verdict.gradient_check_passed is True
    assert verdict.output_type_valid is True
    assert verdict.passed is True, verdict.error_message


# ---------------------------------------------------------------------------
# Helper-level evidence — necessary, and explicitly NOT sufficient (§6.2)
# ---------------------------------------------------------------------------


def test_the_probe_pair_is_shaped_for_the_declared_semantic(loss_spec):
    """The recipe itself, per design §4's table."""
    src = _assemble_loss_plugin("s04a_regressor_mse", loss_spec.description, REGRESSOR_LOSS_CODE)

    assert _dummy_tensor_validate_loss(src, "s04a_regressor_mse", regressor_model_io()) is None


def test_the_same_loss_is_rejected_by_the_legacy_classifier_pair(loss_spec):
    """C5 acceptance: **6.5-D reds without this commit**, recorded explicitly.

    The legacy path builds ``[2, 256, 100]`` float inputs against
    ``[2, 100]`` int64 targets. ``F.mse_loss`` on that pair raises, so the
    identical, perfectly valid loss is rejected — for a shape accident, not
    for anything about the loss. That is precisely the capability gap
    Step 04a closes, pinned here so it cannot silently return.
    """
    src = _assemble_loss_plugin("s04a_regressor_mse", loss_spec.description, REGRESSOR_LOSS_CODE)

    error = _dummy_tensor_validate_loss(src, "s04a_regressor_mse", None)
    assert error is not None
    assert "raised on dummy tensors" in error


def test_a_classifier_custom_loss_is_unaffected(loss_spec):
    """Stage-A parity for the loss probe: the classifier path is unchanged.

    Fails when: the recipe split changes what a categorical loss is offered.
    Asserted between the two paths, so drifting both together cannot hide it.
    """
    from tests.helpers.step04a_fixtures import tidmad_model_io

    ce_code = {
        "extra_imports": "",
        "config_fields_code": "    pass",
        "config_validators_code": "",
        "config_fields": {},
        "init_body": "        pass",
        "forward_body": "        return F.cross_entropy(inputs, targets)",
    }
    src = _assemble_loss_plugin("s04a_ce", "cross entropy", ce_code)

    assert _dummy_tensor_validate_loss(src, "s04a_ce", None) is None
    assert _dummy_tensor_validate_loss(src, "s04a_ce", tidmad_model_io()) is None


# ---------------------------------------------------------------------------
# The negatives §6.2 requires be RETAINED — distinct failure semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("contract_label", ["categorical", "continuous"])
def test_a_detached_loss_is_still_rejected_under_both_semantics(contract_label, loss_spec):
    """A severed graph is a different defect from a wrong shape.

    Fails when: the recipe split weakens the backward() check for either
    semantic. The loss below returns a finite scalar with
    ``requires_grad=False``, so only ``backward()`` can detect it.
    """
    from tests.helpers.step04a_fixtures import tidmad_model_io

    contract = tidmad_model_io() if contract_label == "categorical" else regressor_model_io()
    body = (
        "        return F.cross_entropy(inputs, targets).detach()"
        if contract_label == "categorical"
        else "        return F.mse_loss(inputs.float(), targets.float()).detach()"
    )
    code = {
        "extra_imports": "",
        "config_fields_code": "    pass",
        "config_validators_code": "",
        "config_fields": {},
        "init_body": "        pass",
        "forward_body": body,
    }
    src = _assemble_loss_plugin("s04a_detached", "detached", code)

    error = _dummy_tensor_validate_loss(src, "s04a_detached", contract)
    assert error is not None


@pytest.mark.parametrize("contract_label", ["categorical", "continuous"])
def test_a_non_finite_loss_is_still_rejected_under_both_semantics(contract_label, loss_spec):
    """A NaN scalar is a different defect again, and the finiteness check
    must survive the recipe split for both semantics."""
    from tests.helpers.step04a_fixtures import tidmad_model_io

    contract = tidmad_model_io() if contract_label == "categorical" else regressor_model_io()
    code = {
        "extra_imports": "",
        "config_fields_code": "    pass",
        "config_validators_code": "",
        "config_fields": {},
        "init_body": "        pass",
        "forward_body": "        return (inputs.float().sum() * float('nan'))",
    }
    src = _assemble_loss_plugin("s04a_nan", "nan", code)

    error = _dummy_tensor_validate_loss(src, "s04a_nan", contract)
    assert error is not None
    assert "non-finite" in error


# ---------------------------------------------------------------------------
# Atomicity (§6)
# ---------------------------------------------------------------------------


def test_the_declaration_is_6_5_c_s_baseline_unchanged(regressor_input):
    """6.5-D varies loss capability ONLY — proven, not asserted in prose.

    §6 forbids 6.5-D from varying the output semantic and the loss capability
    at once. Its baseline is 6.5-C's established regressor declaration, so the
    contract this rung runs under must be that exact object.

    Fails when: someone "fixes" this rung by also changing the declaration.
    """
    assert regressor_input.forward_contract.model_io == regressor_model_io()
    assert regressor_input.output_type == "regressor"
    # And the single axis that DOES differ from 6.5-C: a custom loss.
    assert regressor_input.custom_loss_spec is not None
    assert regressor_input.baseline_config["loss_config"]["loss_type"] == "custom"
