"""
Tests for agent/schemas/implementor.py
"""

import pytest
from pydantic import ValidationError

from agent.schemas.implementor import (
    ImplementorInput,
    ImplementorOutput,
    LossProvenance,
)
from agent.schemas.proposal import CustomLossSpec


class TestImplementorInput:
    def test_valid(self):
        inp = ImplementorInput(
            model_name="attn_unet",
            model_description="Attention U-Net.",
            mathematical_definition="Encoder: 3 down blocks.",
            baseline_config={"model_config": {}, "train_config": {}, "loss_config": {}},
        )
        assert inp.model_name == "attn_unet"
        assert inp.plugin_dir == "agent_generated/models"
        assert inp.test_dir == "agent_generated/tests"
        assert inp.storage.backend == "local"

    def test_custom_plugin_and_test_dirs(self):
        inp = ImplementorInput(
            model_name="attn_unet",
            model_description="x",
            mathematical_definition="x",
            baseline_config={},
            plugin_dir="/custom/models",
            test_dir="/custom/tests",
        )
        assert inp.plugin_dir == "/custom/models"
        assert inp.test_dir == "/custom/tests"

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError) as exc:
            ImplementorInput(
                model_description="x",
                mathematical_definition="x",
                baseline_config={},
            )
        assert "model_name" in str(exc.value)

    def test_missing_mathematical_definition_raises(self):
        with pytest.raises(ValidationError) as exc:
            ImplementorInput(
                model_name="attn_unet",
                model_description="x",
                baseline_config={},
            )
        assert "mathematical_definition" in str(exc.value)

    def test_storage_independent_of_plugin_dir(self):
        # plugin_dir and test_dir are separate from storage.local.workspace
        inp = ImplementorInput(
            model_name="x",
            model_description="x",
            mathematical_definition="x",
            baseline_config={},
            storage={"backend": "local", "local": {"workspace": "/runs", "run_name": "r1"}},
        )
        assert inp.storage.local.workspace == "/runs"
        assert inp.plugin_dir == "agent_generated/models"  # unchanged


class TestImplementorOutput:
    def test_valid(self):
        out = ImplementorOutput(
            model_type="attn_unet",
            description_file_path="/abs/agent_generated/models/attn_unet/description.md",
            model_file_path="/abs/agent_generated/models/attn_unet.py",
            test_file_path="/abs/agent_generated/tests/test_attn_unet.py",
            config_fields={"depth": 2, "num_heads": 4},
            model_description="A gated TCN.",
            mathematical_definition="y = tanh * sigmoid",
        )
        assert out.model_type == "attn_unet"
        assert out.config_fields["depth"] == 2

    def test_missing_model_file_path_raises(self):
        with pytest.raises(ValidationError) as exc:
            ImplementorOutput(
                model_type="attn_unet",
                test_file_path="/abs/test.py",
                config_fields={},
                model_description="x",
                mathematical_definition="x",
            )
        assert "model_file_path" in str(exc.value)

    def test_model_description_present(self):
        out = ImplementorOutput(
            model_type="attn_unet",
            description_file_path="/abs/desc.md",
            model_file_path="/abs/model.py",
            test_file_path="/abs/test.py",
            config_fields={},
            model_description="A gated TCN for denoising.",
            mathematical_definition="y = tanh(Wf*x) * sigmoid(Wg*x)",
        )
        assert "gated TCN" in out.model_description

    def test_mathematical_definition_present(self):
        out = ImplementorOutput(
            model_type="attn_unet",
            description_file_path="/abs/desc.md",
            model_file_path="/abs/model.py",
            test_file_path="/abs/test.py",
            config_fields={},
            model_description="x",
            mathematical_definition="y = tanh(Wf*x) * sigmoid(Wg*x)",
        )
        assert "tanh" in out.mathematical_definition

    def test_missing_model_description_raises(self):
        with pytest.raises(ValidationError) as exc:
            ImplementorOutput(
                model_type="attn_unet",
                description_file_path="/abs/desc.md",
                model_file_path="/abs/model.py",
                test_file_path="/abs/test.py",
                config_fields={},
                mathematical_definition="y = tanh(Wf*x) * sigmoid(Wg*x)",
            )
        assert "model_description" in str(exc.value)


# ==========================================
# L3 — loss_dir + custom_loss_spec on ImplementorInput;
#       LossProvenance + loss_provenance on ImplementorOutput
# ==========================================
#
# Verifies the schema-only channel additions from L3. See
# ``docs/design/enable_loss_inventory.md`` § Commit L3.


@pytest.fixture
def base_input_kwargs():
    """Minimal valid ImplementorInput kwargs reused across L3 tests."""
    return dict(
        model_name="attn_unet",
        model_description="x",
        mathematical_definition="x",
        baseline_config={
            "model_config": {},
            "train_config": {},
            "loss_config": {"loss_type": "focal"},
        },
    )


@pytest.fixture
def base_output_kwargs():
    """Minimal valid ImplementorOutput kwargs reused across L3 tests."""
    return dict(
        model_type="attn_unet",
        description_file_path="/abs/desc.md",
        model_file_path="/abs/model.py",
        test_file_path="/abs/test.py",
        config_fields={},
        model_description="x",
        mathematical_definition="x",
    )


@pytest.fixture
def custom_spec():
    return CustomLossSpec(
        loss_name="snr_weighted_mse",
        description="x",
        mathematical_definition="x",
    )


class TestImplementorInputL3:
    """L3 additions to ImplementorInput: loss_dir + custom_loss_spec."""

    def test_loss_dir_default(self, base_input_kwargs):
        inp = ImplementorInput(**base_input_kwargs)
        assert inp.loss_dir == "agent_generated/losses"

    def test_loss_dir_override(self, base_input_kwargs):
        inp = ImplementorInput(**base_input_kwargs, loss_dir="/custom/losses")
        assert inp.loss_dir == "/custom/losses"

    def test_custom_loss_spec_defaults_to_none(self, base_input_kwargs):
        inp = ImplementorInput(**base_input_kwargs)
        assert inp.custom_loss_spec is None

    def test_custom_loss_spec_accepted(self, base_input_kwargs, custom_spec):
        inp = ImplementorInput(**base_input_kwargs, custom_loss_spec=custom_spec)
        assert inp.custom_loss_spec is not None
        assert inp.custom_loss_spec.loss_name == "snr_weighted_mse"

    def test_back_compat_with_pre_l3_construction(self, base_input_kwargs):
        """A pre-L3 caller passing only the original fields must still
        produce a fully-valid ImplementorInput."""
        inp = ImplementorInput(**base_input_kwargs)
        # All new L3 fields must have their defaults.
        assert inp.loss_dir == "agent_generated/losses"
        assert inp.custom_loss_spec is None


class TestLossProvenance:
    """LossProvenance schema enforcement."""

    def test_valid_generated(self):
        p = LossProvenance(
            loss_name="snr_weighted_mse",
            action="generated",
            source_iteration="iter_001",
            loss_file_path="/abs/agent_generated/losses/snr_weighted_mse.py",
            dummy_tensor_validated=True,
        )
        assert p.action == "generated"
        assert p.source_iteration == "iter_001"

    def test_valid_reused(self):
        p = LossProvenance(
            loss_name="snr_weighted_mse",
            action="reused",
            source_iteration="iter_000",
            loss_file_path="/abs/agent_generated/losses/snr_weighted_mse.py",
            dummy_tensor_validated=True,
        )
        assert p.action == "reused"

    def test_source_iteration_none_allowed(self):
        """Hand-curated losses seeded into the registry have no recorded
        origin — source_iteration=None is valid."""
        p = LossProvenance(
            loss_name="hand_curated_loss",
            action="reused",
            source_iteration=None,
            loss_file_path="/abs/path.py",
            dummy_tensor_validated=True,
        )
        assert p.source_iteration is None

    def test_invalid_action_raises(self):
        with pytest.raises(ValidationError, match="action"):
            LossProvenance(
                loss_name="x",
                action="invented_action",  # type: ignore[arg-type]
                source_iteration="iter_001",
                loss_file_path="/abs/x.py",
                dummy_tensor_validated=True,
            )

    def test_empty_loss_name_raises(self):
        with pytest.raises(ValidationError, match="loss_name"):
            LossProvenance(
                loss_name="",
                action="generated",
                source_iteration="iter_001",
                loss_file_path="/abs/x.py",
                dummy_tensor_validated=True,
            )

    def test_empty_loss_file_path_raises(self):
        with pytest.raises(ValidationError, match="loss_file_path"):
            LossProvenance(
                loss_name="x",
                action="generated",
                source_iteration="iter_001",
                loss_file_path="",
                dummy_tensor_validated=True,
            )


class TestImplementorOutputLossProvenance:
    """L3 additions to ImplementorOutput: loss_provenance."""

    def test_defaults_to_none(self, base_output_kwargs):
        out = ImplementorOutput(**base_output_kwargs)
        assert out.loss_provenance is None

    def test_accepts_generated_provenance(self, base_output_kwargs):
        prov = LossProvenance(
            loss_name="snr_weighted_mse",
            action="generated",
            source_iteration="iter_001",
            loss_file_path="/abs/snr_weighted_mse.py",
            dummy_tensor_validated=True,
        )
        out = ImplementorOutput(**base_output_kwargs, loss_provenance=prov)
        assert out.loss_provenance is not None
        assert out.loss_provenance.action == "generated"

    def test_accepts_reused_provenance(self, base_output_kwargs):
        prov = LossProvenance(
            loss_name="snr_weighted_mse",
            action="reused",
            source_iteration="iter_000",
            loss_file_path="/abs/snr_weighted_mse.py",
            dummy_tensor_validated=True,
        )
        out = ImplementorOutput(**base_output_kwargs, loss_provenance=prov)
        assert out.loss_provenance is not None
        assert out.loss_provenance.action == "reused"

    def test_round_trip_via_json(self, base_output_kwargs):
        """JSON round-trip preserves loss_provenance — needed because the
        record is serialised to ``implementor_output_{run_name}.json`` and
        re-loaded by downstream nodes."""
        prov = LossProvenance(
            loss_name="snr_weighted_mse",
            action="generated",
            source_iteration="iter_001",
            loss_file_path="/abs/snr_weighted_mse.py",
            dummy_tensor_validated=True,
        )
        out = ImplementorOutput(**base_output_kwargs, loss_provenance=prov)
        restored = ImplementorOutput.model_validate_json(out.model_dump_json())
        assert restored.loss_provenance is not None
        assert restored.loss_provenance.loss_name == "snr_weighted_mse"
        assert restored.loss_provenance.action == "generated"

    def test_back_compat_no_loss_provenance(self, base_output_kwargs):
        """A pre-L3 caller building ImplementorOutput without loss_provenance
        gets a None default — no validation error."""
        out = ImplementorOutput(**base_output_kwargs)
        assert out.loss_provenance is None
