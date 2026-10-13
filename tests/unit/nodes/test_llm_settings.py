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


@pytest.mark.parametrize("slot", ["implement", "interpret", "validate", "propose", "analyze"])
@pytest.mark.parametrize(
    "provider, expected",
    [
        (None, "gpt-5.6-luna"),
        ("gemini", "gemini-3.1-flash-lite-preview"),
        ("deepseek", "deepseek-v4-pro"),
    ],
)
def test_constructor_defaults_resolve_against_selected_provider(tmp_path, slot, provider, expected):
    """Exercise actual constructors and transport resolution without provider clients."""
    from agent.llm_settings import resolve_main_transport
    from nodes.data_analysis_agent import DataAnalysisAgent
    from nodes.ml_code_validator_agent import MLCodeValidatorAgent
    from nodes.ml_model_implementor import MLModelImplementor
    from nodes.ml_model_proposal_agent import MLModelProposalAgent
    from nodes.result_interpretation_agent import ResultInterpretationAgent

    constructors = {
        "implement": MLModelImplementor,
        "interpret": ResultInterpretationAgent,
        "validate": MLCodeValidatorAgent,
        "propose": MLModelProposalAgent,
        "analyze": DataAnalysisAgent,
    }
    captured = []

    def factory(**kwargs):
        kwargs.pop("max_retries", None)
        captured.append(resolve_main_transport(**kwargs))
        return Mock()

    extra = (
        {"capability_index_path": str(tmp_path / "index.json")}
        if slot in {"implement", "propose"}
        else {}
    )
    if provider is not None:
        extra["provider"] = provider
    if slot == "analyze":
        extra["task_analysis_capability"] = Mock()
    instance = constructors[slot](bridge_factory=factory, **extra)
    if slot == "analyze":
        instance._bridge()
    assert captured[0].model_id == expected
    assert captured[0].provider == (provider or "openai")


def test_tuner_workflow_projection_resolves_missing_and_empty_config() -> None:
    """Both unconfigured tuner paths must resolve a usable model, not PydanticUndefined."""
    for payload in ({}, {"tune": {}}):
        assert (
            resolve_standard_tuner_llm_options(
                WorkflowLLMConfig.model_validate(payload).get("tune")
            )["model_id"]
            == "gpt-5.6-luna"
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
