"""Review settings must describe production without eager node imports."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from nodes.llm_settings import literature_bridge_arguments
from workflows.llm_config import WorkflowLLMConfig, resolve_standard_tuner_llm_options


def test_inert_settings_and_legacy_proposer_import(tmp_path: Path) -> None:
    """Cold imports catch package rebind regressions and accidental SDK imports."""
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            """
import sys
from nodes import llm_settings, proposer_routing, tuner_llm_settings
assert "openai" not in sys.modules
assert "agent.llm_bridge" not in sys.modules
assert "workflows.model_exploration" not in sys.modules
from nodes.ml_model_proposal_agent.routing import ProposerRoute
assert ProposerRoute is proposer_routing.ProposerRoute
""",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "slot,default_model",
    [
        ("implement", "gemini-3.1-pro-preview"),
        ("interpret", "gemini-3.1-flash-lite-preview"),
        ("validate", "gemini-3.1-flash-lite-preview"),
    ],
)
def test_constructor_and_empty_config_keep_distinct_owners(tmp_path, slot, default_model) -> None:
    """Empty config must not silently replace the omitted implementor's pro model."""
    from nodes.ml_code_validator_agent import MLCodeValidatorAgent
    from nodes.ml_model_implementor import MLModelImplementor
    from nodes.result_interpretation_agent import ResultInterpretationAgent

    constructors = {
        "implement": MLModelImplementor,
        "interpret": ResultInterpretationAgent,
        "validate": MLCodeValidatorAgent,
    }
    for payload, expected in (
        ({}, default_model),
        ({slot: {}}, "gemini-3.1-flash-lite-preview"),
    ):
        factory = Mock()
        extra = (
            {"capability_index_path": str(tmp_path / "index.json")} if slot == "implement" else {}
        )
        constructors[slot](
            **WorkflowLLMConfig.model_validate(payload).get(slot), bridge_factory=factory, **extra
        )
        assert factory.call_args.kwargs == {
            "provider": "gemini",
            "model_id": expected,
            "max_retries": None,
        }


def test_tuner_workflow_projection_preserves_missing_versus_empty_config() -> None:
    """Missing tune is the input schema default, not TunerLLMConfig's pro default."""
    assert (
        resolve_standard_tuner_llm_options(WorkflowLLMConfig().get("tune"))["model_id"]
        == "gemini-3.1-flash-lite-preview"
    )
    assert (
        resolve_standard_tuner_llm_options(
            WorkflowLLMConfig.model_validate({"tune": {}}).get("tune")
        )["model_id"]
        == "gemini-3.1-pro-preview"
    )


def test_literature_search_keeps_its_own_effort_and_client_split() -> None:
    """A search override must not inherit main reasoning effort by accident."""
    shared = literature_bridge_arguments(
        provider="openai",
        model_id="main",
        reasoning_effort="high",
        search_provider=None,
        search_model_id=None,
        search_reasoning_effort=None,
    )
    assert shared.search is None
    separate = literature_bridge_arguments(
        provider="openai",
        model_id="main",
        reasoning_effort="high",
        search_provider="gemini",
        search_model_id=None,
        search_reasoning_effort=None,
    )
    assert separate.search == {"provider": "gemini", "model_id": "main"}
    assert separate.main == {"provider": "openai", "model_id": "main", "reasoning_effort": "high"}
