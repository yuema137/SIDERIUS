"""The declared output contract must survive EVERY hop, proposal to live rule.

V21 PR A3 acceptance. Testing that the generated file contains
``PLUGIN_OUTPUT_TYPE = "regressor"`` proves only the producer. This module
walks the whole transport contract with no LLM and no GPU:

    ProposalOutput.output_type
      -> proposal -> implementor protocol
      -> ImplementorInput.output_type
      -> generated plugin's PLUGIN_OUTPUT_TYPE literal
      -> ml_code_validator_agent reads the declaration (A2)
      -> plugin_loader registers it
      -> get_output_type(<generated name>)
      -> shared pair-compatibility rule (A2b)

Both contracts are exercised. The classifier case is not decoration: PR A
changes the validator, the implementor and a schema, so "regression works" is
worth nothing unless classification still does.

Deleting any single hop breaks a case here — that is the property the V20
post-mortems asked for, after `SIDERIUS_PLUGIN_DIRS` arrived at a subprocess
that then never used it.
"""

from __future__ import annotations

import pytest

from agent.schemas.proposal import ExpertAdvice, ProposalOutput
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from ml_models import plugin_loader
from ml_models.models_format_sandbox import validate_output_loss_compatibility
from nodes.ml_code_validator_agent import _check_instantiation_and_gradient
from nodes.ml_model_implementor.ml_model_implementor import _assemble_plugin

# Forward bodies that genuinely produce each contract's shape. The declaration
# alone is not enough — A2 checks the model against its own declaration.
_FORWARD_BODIES = {
    "classifier": "        out = self.emb(x).permute(0, 2, 1)\n        return self.head(out)",
    "regressor": (
        "        out = self.emb(x).permute(0, 2, 1)\n        return self.head(out).squeeze(1)"
    ),
}
_INIT_BODIES = {
    "classifier": (
        "        self.emb = nn.Embedding(256, 16)\n"
        "        self.head = nn.Conv1d(16, 256, kernel_size=1)"
    ),
    "regressor": (
        "        self.emb = nn.Embedding(256, 16)\n"
        "        self.head = nn.Conv1d(16, 1, kernel_size=1)"
    ),
}
_LEGAL_LOSS = {"classifier": "focal", "regressor": "smooth_l1"}
_ILLEGAL_LOSS = {"classifier": "smooth_l1", "regressor": "focal"}


def _proposal(output_type: str, model_name: str) -> ProposalOutput:
    return ProposalOutput(
        model_name=model_name,
        output_type=output_type,
        model_description=f"End-to-end {output_type} contract probe.",
        mathematical_definition="Embedding -> Conv1d head; contract under test.",
        motivation="Verify the declared contract reaches the live rule.",
        expert_advice=ExpertAdvice(
            focus_areas=["contract transport"],
            constraints=["tiny"],
            known_failures=[],
            suggested_directions=["keep it minimal"],
            rationale="Deterministic fixture, no LLM.",
        ),
        baseline_config={
            "model_config": {"channels": 16},
            "train_config": {"lr": 5e-4, "epochs": 1, "batch_size": 2},
            "loss_config": {"loss_type": _LEGAL_LOSS[output_type]},
        },
    )


@pytest.mark.parametrize("output_type", ["classifier", "regressor"])
def test_declared_contract_survives_every_hop(tmp_path, output_type):
    model_name = f"e2e_{output_type}_probe"
    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="r1"),
    )

    # hop 1-2: proposal -> protocol -> implementor input
    impl_input = local_full_spec(_proposal(output_type, model_name), storage)
    assert impl_input.output_type == output_type

    # hop 3: implementor renders the plugin
    source = _assemble_plugin(
        impl_input,
        {
            "extra_imports": "",
            "config_fields_code": "    channels: int = 16",
            "config_validators_code": "",
            "init_body": _INIT_BODIES[output_type],
            "forward_body": _FORWARD_BODIES[output_type],
        },
    )
    assert f'PLUGIN_OUTPUT_TYPE = "{output_type}"' in source

    plugin_path = tmp_path / f"{model_name}.py"
    plugin_path.write_text(source)

    # hop 4: the validator reads the declaration and checks the real forward
    inst_ok, grad_ok, otype_ok, err = _check_instantiation_and_gradient(str(plugin_path))
    assert (inst_ok, grad_ok, otype_ok, err) == (True, True, True, None)

    # hop 5-6: registration, then resolution through the production lookup
    registered = plugin_loader.register_model_in_memory(str(plugin_path))
    assert registered == model_name
    try:
        assert plugin_loader.get_output_type(model_name) == output_type

        # hop 7: the shared rule accepts the legal pair and refuses the illegal one
        validate_output_loss_compatibility(
            plugin_loader.get_output_type(model_name),
            _LEGAL_LOSS[output_type],
            model_type=model_name,
        )
        with pytest.raises(ValueError):
            validate_output_loss_compatibility(
                plugin_loader.get_output_type(model_name),
                _ILLEGAL_LOSS[output_type],
                model_type=model_name,
            )
    finally:
        plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY.pop(model_name, None)


def test_registry_default_would_hide_a_dropped_declaration(tmp_path):
    """Why the chain above is asserted hop by hop rather than end to end only.

    ``get_output_type`` returns ``"classifier"`` for an unregistered model, so a
    regressor whose declaration is lost anywhere upstream does not raise — it
    silently acquires classifier semantics and the illegal pair becomes legal.
    That silent-default behaviour is a known gap deferred to PR C; this test
    pins the reason the intermediate assertions exist.
    """
    assert plugin_loader.get_output_type("never_registered_model_xyz") == "classifier"


@pytest.mark.parametrize("output_type", ["classifier", "regressor"])
def test_generated_test_file_matches_the_declared_contract(tmp_path, output_type):
    """The plugin's OWN generated test must accept its declared contract.

    Found during A4 doc-sync: ``TEST_TEMPLATE.test_forward_shape`` asserted
    ``(2, 256, seg)`` unconditionally, and the implementor's ``_smoke_test_plugin``
    asserted ``(1, 256, T)``. Both would have rejected a correct regressor —
    the implementor emitting a plugin its own test then fails.

    This runs the generated test file with pytest, so the assertion is that the
    real artifact passes, not that the template contains some string.
    """
    import subprocess
    import sys

    from agent.schemas.storage import LocalStorageConfig, StorageConfig
    from nodes.ml_model_implementor.ml_model_implementor import TEST_TEMPLATE

    model_name = f"gen_test_{output_type}"
    storage = StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="r1"),
    )
    impl_input = local_full_spec(_proposal(output_type, model_name), storage)
    plugin_src = _assemble_plugin(
        impl_input,
        {
            "extra_imports": "",
            "config_fields_code": "    channels: int = 16",
            "config_validators_code": "",
            "init_body": _INIT_BODIES[output_type],
            "forward_body": _FORWARD_BODIES[output_type],
        },
    )
    (tmp_path / f"{model_name}.py").write_text(plugin_src)
    (tmp_path / f"test_{model_name}.py").write_text(TEST_TEMPLATE.format(model_name=model_name))

    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"test_{model_name}.py", "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"generated test file failed for {output_type}:\n{result.stdout}\n{result.stderr}"
    )
