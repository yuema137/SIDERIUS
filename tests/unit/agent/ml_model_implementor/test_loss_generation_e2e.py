"""
End-to-end unit tests for the L4b loss-generation flow on
``MLModelImplementor``: bridge-mocked, with a tmp-dir CapabilityRegistry.

Covers the 5 scenarios from the design doc:

  1. Registry hit → no LLM call; ``loss_provenance.action == "reused"``;
     no file written by us this iteration.
  2. Registry miss → mocked LLM returns valid loss code; dummy-tensor
     passes; file written; ``CapabilityRegistry.register`` called once;
     ``loss_provenance.action == "generated"``.
  3. First mocked LLM response fails the scalar-shape assertion → retry
     triggered; second response succeeds → file written.
  4. All retries fail → ``ValueError`` raised; no registry entry written.
  5. ``custom_loss_spec=None`` → ``_generate_loss`` not invoked;
     ``loss_provenance`` on the output is ``None`` (regression guard).

Plus a ``TestRunIntegration`` group that exercises the full ``run()``
path with both model and loss mocked, asserting the threadthrough of
``loss_provenance`` into ``ImplementorOutput``.

See ``docs/design/enable_loss_inventory.md`` § Commit L4.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.schemas.implementor import ImplementorInput, LossProvenance
from agent.schemas.proposal import CustomLossSpec
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.capability_registry import CapabilityMetadata, CapabilityRegistry
from nodes.ml_model_implementor.ml_model_implementor import MLModelImplementor

# ---------------------------------------------------------------------------
# Fake LLM responses for the loss-generation flow
# ---------------------------------------------------------------------------

FAKE_LOSS_REASONING = (
    "Cross-entropy is the simplest valid loss for [B,256,T] logits and [B,T] "
    "int targets. Reduce via mean. Config: optional label_smoothing in [0, 0.5]."
)

# A "good" loss code dict that mirrors what a well-behaved LLM produces.
# Cross-entropy on the classifier contract — assembles, dummy-tensor passes.
GOOD_LOSS_CODE = {
    "extra_imports": "",
    "config_fields_code": "    label_smoothing: float = Field(default=0.0, ge=0.0, le=0.5)",
    "config_validators_code": "",
    "config_fields": {"label_smoothing": 0.0},
    "init_body": "        self.label_smoothing = config.label_smoothing",
    "forward_body": (
        "        return F.cross_entropy(inputs, targets, label_smoothing=self.label_smoothing)"
    ),
}

# A "bad" loss code dict that fails the dummy-tensor scalar-shape check
# (reduction='none' returns [B, T] instead of a scalar). Used for the
# retry-loop tests.
BAD_LOSS_CODE_NON_SCALAR = {
    "extra_imports": "",
    "config_fields_code": "    pass",
    "config_validators_code": "",
    "config_fields": {},
    "init_body": "        pass",
    "forward_body": "        return F.cross_entropy(inputs, targets, reduction='none')",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def custom_loss_spec():
    return CustomLossSpec(
        loss_name="snr_weighted_mse",
        description="SNR-weighted cross-entropy for noisy waveform classification.",
        mathematical_definition=(
            "L = mean(F.cross_entropy(inputs, targets, label_smoothing=label_smoothing))"
        ),
    )


@pytest.fixture
def storage(tmp_path: Path):
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path / "ws"), run_name="iter_007"),
    )


@pytest.fixture
def inp_loss_only(tmp_path: Path, storage, custom_loss_spec):
    """An ImplementorInput with ``custom_loss_spec`` set + per-run
    ``loss_dir`` so tests can write into ``tmp_path``."""
    return ImplementorInput(
        model_name="gated_dilated_tcn",
        model_description="A gated dilated TCN for signal denoising.",
        mathematical_definition="y = tanh(Wf * x) * sigmoid(Wg * x)",
        baseline_config={
            "model_config": {},
            "train_config": {},
            "loss_config": {
                "loss_type": "custom",
                "loss_name": "snr_weighted_mse",
            },
        },
        plugin_dir=str(tmp_path / "models"),
        test_dir=str(tmp_path / "tests"),
        loss_dir=str(tmp_path / "losses"),
        custom_loss_spec=custom_loss_spec,
        storage=storage,
    )


@pytest.fixture
def inp_no_loss(tmp_path: Path, storage):
    """An ImplementorInput WITHOUT ``custom_loss_spec`` — the regression
    guard path. Mirrors the legacy (pre-L3) shape."""
    return ImplementorInput(
        model_name="gated_dilated_tcn",
        model_description="x",
        mathematical_definition="x",
        baseline_config={
            "model_config": {"channels": 64, "depth": 4},
            "train_config": {"lr": 1e-4, "epochs": 10, "batch_size": 1},
            "loss_config": {"loss_type": "focal", "gamma": 2.0},
        },
        plugin_dir=str(tmp_path / "models"),
        test_dir=str(tmp_path / "tests"),
        storage=storage,
    )


@pytest.fixture
def index_path(tmp_path: Path) -> str:
    """Tmp capability-index path so tests don't touch the canonical index."""
    return str(tmp_path / "_capability_index.json")


@pytest.fixture
def agent_with_mocks(index_path):
    """``MLModelImplementor`` with the bridge mocked + a tmp registry."""
    agent = MLModelImplementor.__new__(MLModelImplementor)
    agent.bridge = MagicMock()
    agent.bridge.generate_text.return_value = FAKE_LOSS_REASONING
    agent.bridge.generate.return_value = GOOD_LOSS_CODE
    agent._registry = CapabilityRegistry(index_path=index_path)
    return agent


# ---------------------------------------------------------------------------
# 1. Registry-hit short-circuit
# ---------------------------------------------------------------------------


class TestRegistryHitShortCircuit:
    def test_composed_branch_b_refuses_mismatch_then_reuses_exact_contract(
        self, agent_with_mocks, inp_loss_only, tmp_path
    ):
        from agent.schemas.custom_loss_contract import (
            EqualShapeApplicability,
            custom_loss_snapshot_from_forward_contract,
        )
        from agent.schemas.hyperparam_tuning import TaskCompositionRef
        from agent.schemas.model_io_contract import (
            Dimension,
            ModelIOContract,
            TensorAxis,
            TensorContract,
        )
        from agent.schemas.task_config import ForwardContract
        from ml_models.models_format_sandbox import DtypeAdmissibility

        def tensor(extent):
            return TensorContract(
                axes=(
                    TensorAxis(dimension=Dimension(symbolic="B")),
                    TensorAxis(dimension=Dimension(fixed=extent)),
                ),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            )

        expected_tensor = tensor(1)
        inp_loss_only.forward_contract = ForwardContract(
            model_io=ModelIOContract(input=tensor(4), output=expected_tensor),
            supervision_target=expected_tensor,
            custom_loss_applicability=EqualShapeApplicability(
                dtype=DtypeAdmissibility(admissible=("float32",)), rank=2
            ),
        )
        inp_loss_only.task_composition_ref = TaskCompositionRef.model_construct(
            semantic_fingerprint="composed",
            task_data_path_id="fixture",
            task_health_binding=None,
            supervision_target=expected_tensor,
            custom_loss_applicability=EqualShapeApplicability(
                dtype=DtypeAdmissibility(admissible=("float32",)), rank=2
            ),
        )
        with pytest.raises(ValueError, match="missing its transported contract snapshot"):
            agent_with_mocks._generate_loss(inp_loss_only)
        agent_with_mocks.bridge.generate_text.assert_not_called()
        agent_with_mocks.bridge.generate.assert_not_called()

        inp_loss_only.custom_loss_spec = None
        inp_loss_only.baseline_config["model_config"] = {"model_name": "reused_model"}
        model_file = tmp_path / "reused_model.py"
        model_file.write_text("# registered model\n")
        agent_with_mocks._registry.register(
            CapabilityMetadata(
                name="snr_weighted_mse",
                capability_type="loss",
                file_path="/must/not/be/imported.py",
                created_at="2026-09-13T00:00:00Z",
                contract_snapshot=None,
            )
        )
        agent_with_mocks._registry.register(
            CapabilityMetadata(
                name="reused_model",
                capability_type="model",
                file_path=str(model_file),
                created_at="2026-09-13T00:00:00Z",
            )
        )
        with pytest.raises(ValueError, match="does not match the composed task"):
            agent_with_mocks.run(inp_loss_only)
        agent_with_mocks.bridge.generate_text.assert_not_called()
        agent_with_mocks.bridge.generate.assert_not_called()

        snapshot = custom_loss_snapshot_from_forward_contract(inp_loss_only.forward_contract)
        agent_with_mocks._registry.replace(
            CapabilityMetadata(
                name="snr_weighted_mse",
                capability_type="loss",
                file_path="/must/not/be/imported.py",
                created_at="2026-09-13T00:00:00Z",
                contract_snapshot=snapshot,
            )
        )
        output = agent_with_mocks.run(inp_loss_only)
        assert output.loss_provenance is not None
        assert output.loss_provenance.action == "reused"
        assert output.loss_provenance.contract_snapshot == snapshot

    def test_transport_disagreement_refuses_before_reuse(self, agent_with_mocks, inp_loss_only):
        from agent.schemas.custom_loss_contract import EqualShapeApplicability
        from agent.schemas.hyperparam_tuning import TaskCompositionRef
        from agent.schemas.model_io_contract import (
            Dimension,
            ModelIOContract,
            TensorAxis,
            TensorContract,
        )
        from agent.schemas.task_config import ForwardContract
        from ml_models.models_format_sandbox import DtypeAdmissibility

        def tensor(extent):
            return TensorContract(
                axes=(
                    TensorAxis(dimension=Dimension(symbolic="B")),
                    TensorAxis(dimension=Dimension(fixed=extent)),
                ),
                dtype=DtypeAdmissibility(admissible=("float32",)),
            )

        expected_tensor = tensor(1)
        applicability = EqualShapeApplicability(
            dtype=DtypeAdmissibility(admissible=("float32",)), rank=2
        )
        inp_loss_only.forward_contract = ForwardContract(
            model_io=ModelIOContract(input=tensor(4), output=expected_tensor),
            supervision_target=expected_tensor,
            custom_loss_applicability=applicability,
        )
        inp_loss_only.task_composition_ref = TaskCompositionRef.model_construct(
            semantic_fingerprint="composed",
            task_data_path_id="fixture",
            task_health_binding=None,
            supervision_target=tensor(2),
            custom_loss_applicability=applicability,
        )
        with pytest.raises(ValueError, match="disagree with the forward contract"):
            agent_with_mocks._generate_loss(inp_loss_only)
        agent_with_mocks.bridge.generate_text.assert_not_called()
        agent_with_mocks.bridge.generate.assert_not_called()

    def test_no_llm_call_on_registry_hit(self, agent_with_mocks, inp_loss_only):
        """When the registry already has an entry for the requested
        loss_name, ``_generate_loss`` must NOT call the bridge."""
        # Pre-populate the registry.
        agent_with_mocks._registry.register(
            CapabilityMetadata(
                name="snr_weighted_mse",
                capability_type="loss",
                file_path="/abs/agent_generated/losses/snr_weighted_mse.py",
                created_at="2026-06-20T00:00:00+00:00",
                source_iteration="iter_003",
                description="Pre-existing entry from a prior iteration.",
            )
        )
        prov = agent_with_mocks._generate_loss(inp_loss_only)

        agent_with_mocks.bridge.generate_text.assert_not_called()
        agent_with_mocks.bridge.generate.assert_not_called()

        assert prov.action == "reused"
        assert prov.loss_name == "snr_weighted_mse"
        assert prov.source_iteration == "iter_003"
        # Reuse points at the ORIGINAL file path, not at inp.loss_dir.
        assert prov.loss_file_path == "/abs/agent_generated/losses/snr_weighted_mse.py"
        assert prov.dummy_tensor_validated is True

    def test_no_file_written_on_registry_hit(self, agent_with_mocks, inp_loss_only):
        """On a registry hit, the implementor must not write to inp.loss_dir
        (the file is the one the original iteration already wrote)."""
        agent_with_mocks._registry.register(
            CapabilityMetadata(
                name="snr_weighted_mse",
                capability_type="loss",
                file_path="/abs/snr_weighted_mse.py",
                created_at="2026-06-20T00:00:00+00:00",
                source_iteration="iter_003",
                description="x",
            )
        )
        agent_with_mocks._generate_loss(inp_loss_only)
        assert not Path(inp_loss_only.loss_dir, "snr_weighted_mse.py").exists()


# ---------------------------------------------------------------------------
# 2. Registry-miss happy path
# ---------------------------------------------------------------------------


class TestGenerateLossHappyPath:
    def test_two_llm_calls_made(self, agent_with_mocks, inp_loss_only):
        """Two-call shape: reasoning then code, both with loss-specific
        labels."""
        agent_with_mocks._generate_loss(inp_loss_only)
        agent_with_mocks.bridge.generate_text.assert_called_once()
        agent_with_mocks.bridge.generate.assert_called_once()

        reasoning_label = agent_with_mocks.bridge.generate_text.call_args.kwargs.get("label")
        code_label = agent_with_mocks.bridge.generate.call_args.kwargs.get("label")
        assert reasoning_label == "implementor.loss.reasoning"
        assert code_label == "implementor.loss.code"

    def test_loss_file_written_to_loss_dir(self, agent_with_mocks, inp_loss_only):
        agent_with_mocks._generate_loss(inp_loss_only)
        expected = Path(inp_loss_only.loss_dir) / "snr_weighted_mse.py"
        assert expected.exists()
        # File contains the template-owned 3 required constants.
        src = expected.read_text()
        assert 'PLUGIN_LOSS_TYPE = "snr_weighted_mse"' in src
        assert "PLUGIN_LOSS_CONFIG_CLASS = SnrWeightedMseConfig" in src
        assert "PLUGIN_LOSS_CLASS = SnrWeightedMse" in src

    def test_registry_entry_written(self, agent_with_mocks, inp_loss_only):
        agent_with_mocks._generate_loss(inp_loss_only)
        entries = agent_with_mocks._registry.list(capability_type="loss")
        assert len(entries) == 1
        e = entries[0]
        assert e.name == "snr_weighted_mse"
        assert e.capability_type == "loss"
        assert e.source_iteration == "iter_007"
        assert e.file_path.endswith("snr_weighted_mse.py")
        assert e.created_at  # non-empty ISO-8601 string
        # Description collapsed to one line.
        assert "\n" not in e.description

    def test_provenance_action_generated(self, agent_with_mocks, inp_loss_only):
        prov = agent_with_mocks._generate_loss(inp_loss_only)
        assert isinstance(prov, LossProvenance)
        assert prov.action == "generated"
        assert prov.loss_name == "snr_weighted_mse"
        assert prov.source_iteration == "iter_007"
        assert prov.dummy_tensor_validated is True
        assert prov.loss_file_path.endswith("snr_weighted_mse.py")

    def test_reasoning_threaded_into_code_prompt(self, agent_with_mocks, inp_loss_only):
        """The reasoning output must appear verbatim in the code-call user
        prompt — the two calls are a chain-of-thought."""
        agent_with_mocks._generate_loss(inp_loss_only)
        code_user_prompt = agent_with_mocks.bridge.generate.call_args[0][1]
        assert FAKE_LOSS_REASONING in code_user_prompt


# ---------------------------------------------------------------------------
# 3. Validation failure → retry success
# ---------------------------------------------------------------------------


class TestRetryRecovery:
    def test_first_bad_response_triggers_retry(self, agent_with_mocks, inp_loss_only):
        """First mocked LLM code response fails dummy-tensor (non-scalar);
        second succeeds. The flow must retry, succeed, and write the file
        with the second response's code."""
        agent_with_mocks.bridge.generate.side_effect = [
            BAD_LOSS_CODE_NON_SCALAR,
            GOOD_LOSS_CODE,
        ]
        prov = agent_with_mocks._generate_loss(inp_loss_only)

        # Initial code call + 1 repair call = 2 total invocations.
        assert agent_with_mocks.bridge.generate.call_count == 2
        # Repair label was used on the retry.
        labels = [c.kwargs.get("label") for c in agent_with_mocks.bridge.generate.call_args_list]
        assert labels == ["implementor.loss.code", "implementor.loss.repair"]

        assert prov.action == "generated"
        # File written with the GOOD code's forward body.
        src = Path(prov.loss_file_path).read_text()
        assert "label_smoothing=self.label_smoothing" in src
        assert "reduction='none'" not in src


# ---------------------------------------------------------------------------
# 4. All retries fail → ValueError, no registry write
# ---------------------------------------------------------------------------


class TestAllRetriesFail:
    def test_value_error_when_all_retries_fail(self, agent_with_mocks, inp_loss_only):
        """When every code attempt fails validation, ``_generate_loss``
        must raise ``ValueError`` with the last error in the message."""
        inp_loss_only.max_retries = 1  # 1 initial + 1 repair = 2 attempts
        agent_with_mocks.bridge.generate.side_effect = [
            BAD_LOSS_CODE_NON_SCALAR,
            BAD_LOSS_CODE_NON_SCALAR,
        ]
        with pytest.raises(ValueError, match="Loss generation failed after 2 attempts"):
            agent_with_mocks._generate_loss(inp_loss_only)

    def test_no_registry_entry_on_failure(self, agent_with_mocks, inp_loss_only):
        """A failing run must NOT pollute the registry — the next
        iteration retries from a clean slate."""
        inp_loss_only.max_retries = 0
        agent_with_mocks.bridge.generate.return_value = BAD_LOSS_CODE_NON_SCALAR
        with pytest.raises(ValueError):
            agent_with_mocks._generate_loss(inp_loss_only)
        entries = agent_with_mocks._registry.list(capability_type="loss")
        assert entries == []


# ---------------------------------------------------------------------------
# 5. custom_loss_spec=None — regression guard
# ---------------------------------------------------------------------------


class TestNoCustomLossSpec:
    def test_run_without_spec_does_not_call_generate_loss(
        self, monkeypatch, agent_with_mocks, inp_no_loss
    ):
        """When ``inp.custom_loss_spec is None``, ``_generate_loss`` must
        NOT be invoked from ``run()`` — the legacy model-only path
        survives untouched."""
        # Spy on _generate_loss so we can assert it wasn't called.
        called = []
        monkeypatch.setattr(
            agent_with_mocks,
            "_generate_loss",
            lambda inp: called.append(inp),
        )
        # Mock model bridge response just enough for run() to reach the
        # ImplementorOutput construction. Use a minimal valid model code.
        agent_with_mocks.bridge.generate_text.return_value = "reasoning..."
        agent_with_mocks.bridge.generate.return_value = {
            "extra_imports": "",
            "config_fields_code": "    channels: int = Field(default=64, ge=8, le=256)",
            "config_fields": {"channels": 64},
            "init_body": (
                "        self.embedding = nn.Embedding(256, config.channels)\n"
                "        self.conv_out = nn.Conv1d(config.channels, 256, 1)"
            ),
            "forward_body": (
                "        x = self.embedding(x.long()).transpose(1, 2)\n"
                "        return self.conv_out(x)"
            ),
        }

        out = agent_with_mocks.run(inp_no_loss)
        assert called == []  # never invoked
        assert out.loss_provenance is None


# ---------------------------------------------------------------------------
# Integration: full run() with both model and loss mocked
# ---------------------------------------------------------------------------


class TestRunIntegration:
    """Verify that ``run()`` invokes ``_generate_loss`` when the spec is
    set and threads the resulting ``LossProvenance`` into the output."""

    def test_run_with_spec_attaches_loss_provenance(self, agent_with_mocks, inp_loss_only):
        # Bridge returns the same GOOD response for both reasoning calls
        # (loss + model) and the same GOOD code for both code calls.
        # The model-side smoke test needs a non-trivial model body.
        agent_with_mocks.bridge.generate.side_effect = [
            GOOD_LOSS_CODE,  # loss.code
            {  # model.code
                "extra_imports": "",
                "config_fields_code": ("    channels: int = Field(default=64, ge=8, le=256)"),
                "config_fields": {"channels": 64},
                "init_body": (
                    "        self.embedding = nn.Embedding(256, config.channels)\n"
                    "        self.conv_out = nn.Conv1d(config.channels, 256, 1)"
                ),
                "forward_body": (
                    "        x = self.embedding(x.long()).transpose(1, 2)\n"
                    "        return self.conv_out(x)"
                ),
            },
        ]
        out = agent_with_mocks.run(inp_loss_only)

        # The loss bridge was called BEFORE the model bridge (sequential
        # order — loss first).
        assert agent_with_mocks.bridge.generate.call_count == 2
        labels = [c.kwargs.get("label") for c in agent_with_mocks.bridge.generate.call_args_list]
        assert labels == ["implementor.loss.code", "implementor.code"]

        assert out.loss_provenance is not None
        assert out.loss_provenance.action == "generated"
        assert out.loss_provenance.loss_name == "snr_weighted_mse"

    def test_run_with_registry_hit_skips_loss_llm(self, agent_with_mocks, inp_loss_only):
        """Pre-populate the registry; ``run()`` should not call the bridge
        for the loss but should still call it for the model."""
        agent_with_mocks._registry.register(
            CapabilityMetadata(
                name="snr_weighted_mse",
                capability_type="loss",
                file_path="/abs/snr_weighted_mse.py",
                created_at="2026-06-20T00:00:00+00:00",
                source_iteration="iter_003",
                description="pre-existing",
            )
        )
        agent_with_mocks.bridge.generate.return_value = {
            "extra_imports": "",
            "config_fields_code": ("    channels: int = Field(default=64, ge=8, le=256)"),
            "config_fields": {"channels": 64},
            "init_body": (
                "        self.embedding = nn.Embedding(256, config.channels)\n"
                "        self.conv_out = nn.Conv1d(config.channels, 256, 1)"
            ),
            "forward_body": (
                "        x = self.embedding(x.long()).transpose(1, 2)\n"
                "        return self.conv_out(x)"
            ),
        }
        out = agent_with_mocks.run(inp_loss_only)

        # bridge.generate called ONCE (model only — loss was reused).
        assert agent_with_mocks.bridge.generate.call_count == 1
        assert agent_with_mocks.bridge.generate.call_args.kwargs["label"] == "implementor.code"
        # bridge.generate_text called ONCE (model reasoning only).
        assert agent_with_mocks.bridge.generate_text.call_count == 1

        assert out.loss_provenance is not None
        assert out.loss_provenance.action == "reused"
        assert out.loss_provenance.source_iteration == "iter_003"
