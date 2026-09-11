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
    inst_ok, grad_ok, otype_ok, err, _total, _trainable = _check_instantiation_and_gradient(
        str(plugin_path)
    )
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
    """A dropped declaration must FAIL CLOSED, not acquire classifier semantics.

    **Inverted by V21 PR C1 (2026-08-08). Kept, not deleted** — this test is
    the historical record of the exact defect C1 closes.

    PR A wrote it as an assertion that the defect was *present*:

        assert get_output_type("never_registered_model_xyz") == "classifier"

    That silent default is why the chain above is asserted hop by hop rather
    than end to end only: a regressor whose declaration was lost anywhere
    upstream did not raise, it silently became a classifier, and the illegal
    loss pair became legal.

    C1 replaced the default with ``UnknownOutputContractError``. The
    hop-by-hop assertions above are still correct and still valuable, but the
    reason has changed: they now localise *where* a declaration was dropped,
    rather than compensating for the fact that nothing would notice.

    Fails if: anyone restores a default return value for an unregistered
    model, in any form — ``"classifier"``, ``"unknown"``, or ``None``.
    """
    with pytest.raises(plugin_loader.UnknownOutputContractError) as exc:
        plugin_loader.get_output_type("never_registered_model_xyz")

    # The message must blame registration, not describe the model. A message
    # that reads "defaulting to classifier" would mean the semantics leaked
    # back in as prose.
    assert exc.value.model_type == "never_registered_model_xyz"
    assert "never_registered_model_xyz" in str(exc.value)
    assert "REGISTRATION FAILED" in str(exc.value)


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
    from nodes.ml_model_implementor.ml_model_implementor import (
        _assemble_test,
        _declared_segmentation_size,
    )

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
    # Step 04a: render through the PRODUCTION assembler, not the raw template.
    # `_assemble_test` is what the implementor actually calls, and it is where
    # the contract-derived class count is applied — formatting the template
    # directly would test a string this node never emits.
    #
    # C12-P / F-12e-G1: the declaration flag is DERIVED from the same authority
    # production reads (`MLModelImplementor.run` does exactly this), not
    # hardcoded. This fixture's baseline omits `segmentation_size`, so the
    # assembled plugin declares it REQUIRED and its generated test must state a
    # probe size. Hardcoding `False` here would pass today and silently stop
    # mirroring production the moment the fixture gained a declared size.
    (tmp_path / f"test_{model_name}.py").write_text(
        _assemble_test(
            model_name,
            impl_input.forward_contract.model_io,
            config_declares_segmentation_size=(
                _declared_segmentation_size(impl_input.baseline_config) is not None
            ),
        )
    )

    result = subprocess.run(
        [sys.executable, "-m", "pytest", f"test_{model_name}.py", "-q"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"generated test file failed for {output_type}:\n{result.stdout}\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# The hop the A3 transport contract missed (found by Gate 1R, 2026-08-07)
# ---------------------------------------------------------------------------
#
# A3 declared the chain starting at ``ProposalOutput.output_type`` and treated
# that as the source. The REAL source is the LLM's raw JSON, and there is a
# lossy parse step before a ProposalOutput exists: both construction sites in
# ml_model_proposal_agent build from an EXPLICIT key allow-list, so a field
# absent from that list is silently dropped and the schema default applies.
#
# Gate 1R caught it in production. The agent followed the regression advice
# (loss_type=smooth_l1, model named "..._regressor_v1") and the proposal still
# arrived as output_type="classifier", because the parser never read the key.
#
# Lesson recorded in the ledger: a transport contract must start at the real
# PRODUCER, not at the first typed object in the chain.
#
# MUTATION TARGET: drop `"output_type": raw.get(...)` from either construction
# site and the matching case below fails.


class TestRawProposalJsonCarriesOutputContract:
    @staticmethod
    def _sites() -> str:
        import inspect

        from nodes import ml_model_proposal_agent as mod

        return inspect.getsource(mod)

    @pytest.mark.parametrize("declared", ["classifier", "regressor"])
    def test_parser_allowlist_reads_output_type(self, declared):
        """A ProposalOutput built the way the agent builds it must preserve a
        declared output_type rather than silently defaulting."""
        from agent.schemas.proposal import ProposalOutput

        raw = {
            "model_name": "raw_probe",
            "output_type": declared,
            "model_description": "probe",
            "mathematical_definition": "probe",
            "motivation": "probe",
            "expert_advice": {
                "focus_areas": ["x"],
                "constraints": ["y"],
                "known_failures": [],
                "suggested_directions": ["z"],
                "rationale": "probe",
            },
            "baseline_config": {
                "model_config": {},
                "train_config": {},
                "loss_config": {"loss_type": "focal"},
            },
        }
        built = ProposalOutput.model_validate(
            {
                "model_name": raw["model_name"],
                "output_type": raw.get("output_type", "classifier"),
                "model_description": raw["model_description"],
                "mathematical_definition": raw["mathematical_definition"],
                "motivation": raw["motivation"],
                "expert_advice": raw["expert_advice"],
                "baseline_config": raw["baseline_config"],
            }
        )
        assert built.output_type == declared

    def test_both_construction_sites_read_output_type(self):
        """Reachability: BOTH allow-lists in the proposal agent must read the
        key. One site fixed and one missed is the same silent-default defect."""
        src = self._sites()
        assert src.count('"output_type": raw.get(') == 2, (
            "every ProposalOutput construction site must read output_type from "
            "the raw LLM JSON; an omitted site silently defaults to classifier"
        )

    def test_json_skeletons_request_output_type(self):
        """The agent cannot emit a field it is never asked for."""
        from pathlib import Path

        from nodes.ml_model_proposal_agent import PROPOSAL_COMMIT_PROMPT

        assert '"output_type"' in PROPOSAL_COMMIT_PROMPT

        template = (
            Path(__file__).resolve().parents[3]
            / "src/agent/prompt_templates/proposal/proposing_stage.md"
        )
        assert '"output_type"' in template.read_text(encoding="utf-8")
