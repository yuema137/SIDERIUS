"""
Tier 2 integration test: ml_model_proposal_agent -> ml_model_implementor.

Exercises the full edge:
  1. Run ml_model_proposal_agent with a synthetic ProposalInput (real API)
  2. Apply protocol local_full_spec to produce ImplementorInput
  3. Run ml_model_implementor (real API — two LLM calls: reasoning + code)
  4. Validate ImplementorOutput: files exist, plugin loads, syntax is valid

No GPU or real TIDMAD data required — both nodes are LLM-only.

Requires:
  - GEMINI_API_KEY and/or OPENAI_API_KEY set in the environment (or .env file)

Run with:
  uv run pytest -m real_run tests/integration/protocols/test_propose_to_implement.py -v -s

DO NOT run in CI.
"""
import ast
import os
import pytest
from dotenv import load_dotenv

from agent.schemas.proposal import ProposalInput
from agent.schemas.implementor import ImplementorOutput
from agent.schemas.storage import StorageConfig, LocalStorageConfig
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.ml_model_implementor import MLModelImplementor
from ml_models.plugin_loader import _load_plugin

# Reuse the synthetic interpretation from the node integration test
from tests.integration.nodes.test_ml_model_proposal_agent import SYNTHETIC_INTERPRETATION

load_dotenv()

pytestmark = pytest.mark.real_run


# ---------------------------------------------------------------------------
# Skip guard
# ---------------------------------------------------------------------------

def _skip_if_no_key(provider: str):
    key = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    if not os.getenv(key):
        pytest.skip(f"{key} not set — skipping real API test")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_proposal(provider: str, model_id: str, tmp_path):
    inp = ProposalInput(
        interpretation=SYNTHETIC_INTERPRETATION,
        existing_model_types=["punet", "fcnet"],
        constraints=["VRAM < 10 GB", "params < 100M"],
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="propose_to_impl"),
        ),
    )
    return MLModelProposalAgent(provider=provider, model_id=model_id).run(inp)


def _assert_implementor_output(output: ImplementorOutput):
    assert isinstance(output, ImplementorOutput)
    assert len(output.model_type) > 0

    # Files exist
    assert os.path.exists(output.model_file_path), "Plugin file not found"
    assert os.path.exists(output.test_file_path),  "Test file not found"

    # Plugin is syntactically valid Python
    plugin_src = open(output.model_file_path).read()
    try:
        ast.parse(plugin_src)
    except SyntaxError as e:
        pytest.fail(f"Generated plugin has a syntax error: {e}\n\n{plugin_src}")

    # Plugin loads through the plugin loader
    plugin = _load_plugin(output.model_file_path)
    assert plugin is not None, "plugin_loader._load_plugin() returned None"
    assert plugin["model_type"] == output.model_type

    # Config instantiates with defaults
    config = plugin["config_class"]()
    assert config.segmentation_size > 0


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProposeToImplementGemini:

    def setup_method(self):
        _skip_if_no_key("gemini")

    def test_propose_to_implement_full_chain(self, tmp_path):
        """
        Full edge: proposal agent -> local_full_spec protocol -> implementor.
        """
        provider = "gemini"
        model_id = "gemini-3.1-flash-lite-preview"
        storage  = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="propose_to_impl"),
        )

        # Step 1: run proposal agent (real API)
        proposal_output = _run_proposal(provider, model_id, tmp_path)
        assert len(proposal_output.model_name) > 0

        # Step 2: apply protocol
        impl_input = local_full_spec(proposal_output, storage)
        assert impl_input.model_name == proposal_output.model_name
        assert impl_input.mathematical_definition == proposal_output.mathematical_definition

        # Step 3: run implementor (real API)
        impl_input.plugin_dir = str(tmp_path / "models")
        impl_input.test_dir   = str(tmp_path / "tests")
        output = MLModelImplementor(provider=provider, model_id=model_id).run(impl_input)

        # Step 4: validate
        _assert_implementor_output(output)
        assert (tmp_path / "implementor_propose_to_impl.json").exists()

        plugin_src = open(output.model_file_path).read()
        print(f"\n  proposed model  : {proposal_output.model_name}")
        print(f"  model_type      : {output.model_type}")
        print(f"  config_fields   : {output.config_fields}")
        print(f"\n=== Generated plugin ===\n{plugin_src}")


class TestProposeToImplementOpenAI:

    def setup_method(self):
        _skip_if_no_key("openai")

    def test_propose_to_implement_full_chain(self, tmp_path):
        """
        Full edge via OpenAI: proposal agent -> local_full_spec -> implementor.
        """
        provider = "openai"
        model_id = "gpt-4o-mini"
        storage  = StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="propose_to_impl"),
        )

        proposal_output = _run_proposal(provider, model_id, tmp_path)
        impl_input = local_full_spec(proposal_output, storage)
        impl_input.plugin_dir = str(tmp_path / "models")
        impl_input.test_dir   = str(tmp_path / "tests")
        output = MLModelImplementor(provider=provider, model_id=model_id).run(impl_input)

        _assert_implementor_output(output)

        print(f"\n  proposed model : {proposal_output.model_name}")
        print(f"  config_fields  : {output.config_fields}")
