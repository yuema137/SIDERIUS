"""
Unit tests for the MLModelImplementor Branch B model-reuse short-circuit.

The model surface gains Branch B (reuse a previously-registered model
plugin) symmetric to the loss-side L4b short-circuit. The implementor's
``run()`` checks ``inp.baseline_config['model_config']['model_name']``
before reasoning + code generation:

  * Branch B happy path → no LLM call, no plugin file written, returns
    ``ImplementorOutput`` pointing at the existing registry file_path.
  * Phantom Branch B (name not in registry) → ``ValueError`` with a
    diagnostic message naming the missing key and registry contents.

Plus a separate group asserting that the standard Branch C codegen path
DOES write a ``capability_type='model'`` entry to the index (criterion
#4 from the V16 plan — symmetric to the loss-side index write).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.schemas.implementor import ImplementorInput
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.capability_registry import CapabilityMetadata, CapabilityRegistry
from nodes.ml_model_implementor.ml_model_implementor import MLModelImplementor


@pytest.fixture
def storage(tmp_path: Path) -> StorageConfig:
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path / "ws"), run_name="iter_002"),
    )


@pytest.fixture
def index_path(tmp_path: Path) -> str:
    return str(tmp_path / "_capability_index.json")


@pytest.fixture
def agent_with_mocks(index_path):
    agent = MLModelImplementor.__new__(MLModelImplementor)
    agent.bridge = MagicMock()
    agent._registry = CapabilityRegistry(index_path=index_path)
    return agent


def _branch_b_input(tmp_path: Path, storage: StorageConfig, *, model_name: str) -> ImplementorInput:
    return ImplementorInput(
        model_name=model_name,
        model_description="x",
        mathematical_definition="x",
        baseline_config={
            "model_config": {"model_name": model_name},
            "train_config": {},
            "loss_config": {"loss_type": "focal", "gamma": 2.0},
        },
        plugin_dir=str(tmp_path / "models"),
        test_dir=str(tmp_path / "tests"),
        loss_dir=str(tmp_path / "losses"),
        storage=storage,
    )


class TestBranchBShortCircuit:
    """Criterion 2 — Branch B with a registered model_name skips code
    generation and returns an ImplementorOutput pointing at the existing
    plugin path."""

    def test_branch_b_hit_skips_llm_and_reuses_registered_path(
        self, agent_with_mocks, tmp_path: Path, storage
    ):
        # Pre-populate the registry with a model entry the proposer wants to reuse.
        existing_path = str(tmp_path / "global_models" / "wavenet_baseline_v16.py")
        Path(existing_path).parent.mkdir(parents=True, exist_ok=True)
        Path(existing_path).write_text("# stub plugin\n")
        agent_with_mocks._registry.register(
            CapabilityMetadata(
                name="wavenet_baseline_v16",
                capability_type="model",
                file_path=existing_path,
                created_at="2026-06-25T00:00:00+00:00",
                source_iteration="iter_001",
                description="WaveNet baseline.",
                mathematical_definition="y = sum_l tanh(W_f x) * sigmoid(W_g x)",
            )
        )
        inp = _branch_b_input(tmp_path, storage, model_name="wavenet_baseline_v16")

        out = agent_with_mocks.run(inp)

        # No LLM call (neither reasoning nor code commit).
        agent_with_mocks.bridge.generate_text.assert_not_called()
        agent_with_mocks.bridge.generate.assert_not_called()
        # Output points at the existing global path.
        assert out.model_type == "wavenet_baseline_v16"
        assert Path(out.model_file_path).resolve() == Path(existing_path).resolve()
        # No fresh plugin file was written into the workspace plugin_dir.
        assert not (tmp_path / "models" / "wavenet_baseline_v16.py").exists()


class TestPhantomBranchBImplementorGuard:
    """Criterion 3 — Branch B with a model_name NOT in the registry must
    raise ValueError at the implementor (the upstream schema validator
    catches it first when context is passed, but the implementor is the
    last-line guard for callers that bypass the proposer agent)."""

    def test_phantom_branch_b_raises_value_error(self, agent_with_mocks, tmp_path: Path, storage):
        inp = _branch_b_input(tmp_path, storage, model_name="ghost_arch")

        with pytest.raises(ValueError, match=r"Branch B model proposal.*not in the model"):
            agent_with_mocks.run(inp)

        # No file was written and no LLM was called before the guard fired.
        agent_with_mocks.bridge.generate_text.assert_not_called()
        agent_with_mocks.bridge.generate.assert_not_called()
        assert not (tmp_path / "models" / "ghost_arch.py").exists()


class TestModelRegistryEntryShape:
    """Criterion 4 — when codegen runs (Branch C), the implementor must
    register a ``capability_type='model'`` entry with the same fields the
    loss-side L6c entry carries (so ``render_available_models`` can render
    it on the next iter). We validate the shape directly here; the
    end-to-end codegen path is exercised by the integration suite.
    """

    def test_model_metadata_is_storable_and_listable(self, index_path):
        """The capability registry accepts ``capability_type='model'``
        rows with the same field set as ``loss`` rows, and ``list``
        filters by type correctly."""
        registry = CapabilityRegistry(index_path=index_path)
        registry.register(
            CapabilityMetadata(
                name="wavenet_baseline_v16",
                capability_type="model",
                file_path="/abs/agent_generated/models/wavenet_baseline_v16.py",
                created_at="2026-06-25T00:00:00+00:00",
                source_iteration="iter_001",
                description="WaveNet baseline.",
                mathematical_definition="y = sum_l tanh(...) * sigmoid(...)",
            )
        )
        registry.register(
            CapabilityMetadata(
                name="snr_weighted_mse",
                capability_type="loss",
                file_path="/abs/agent_generated/losses/snr_weighted_mse.py",
                created_at="2026-06-25T00:00:00+00:00",
                source_iteration="iter_001",
                description="SNR-weighted MSE.",
                mathematical_definition="L = mean(w * (y - y_hat)^2)",
            )
        )

        models = registry.list(capability_type="model")
        losses = registry.list(capability_type="loss")
        assert [m.name for m in models] == ["wavenet_baseline_v16"]
        assert [m.name for m in losses] == ["snr_weighted_mse"]
        # The model row carries the same architecture-definition slot the
        # proposer's ``render_available_models`` reads.
        assert "tanh" in models[0].mathematical_definition
