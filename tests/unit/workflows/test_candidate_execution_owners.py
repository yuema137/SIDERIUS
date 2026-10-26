"""Parity witnesses for storage/context extraction from merged 23e71d10."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from workflows.attempt_storage import impl_attempt_storage
from workflows.run_context import bind_agent_run_context, contextual_bridge_factory


def test_attempt_storage_matches_captured_pre_extraction_outputs():
    # Captured by invoking model_exploration.impl_attempt_storage BEFORE moving
    # it, at 23e71d109ed4fef1e3586e924d8af1ad8b5abc02. Pure synthetic paths;
    # no filesystem reads/writes occur at those locations.
    baseline = json.loads(
        (Path(__file__).parents[2] / "fixtures/workflow_attempt_storage.json").read_text()
    )
    for index, expected in baseline.items():
        actual = impl_attempt_storage(
            "/tmp/candidate/iteration_001/attempt_001", "candidate", int(index)
        )
        assert {
            "impl_dir": actual.impl_dir,
            "storage": actual.storage.model_dump(mode="json"),
            "plugin_dir": actual.plugin_dir,
            "test_dir": actual.test_dir,
            "loss_dir": actual.loss_dir,
        } == expected


@pytest.mark.parametrize("run_name,run_id", [(None, "id"), ("name", None), (None, None)])
def test_missing_identity_leaves_agent_and_bridge_untouched(tmp_path, run_name, run_id):
    agent = SimpleNamespace(set_run_context=Mock(), bridge=Mock())
    bind_agent_run_context(agent, workspace=tmp_path, iteration=4, run_name=run_name, run_id=run_id)
    agent.set_run_context.assert_not_called()
    agent.bridge.set_run_context.assert_not_called()
    for factory in (None, Mock()):
        assert (
            contextual_bridge_factory(
                factory, workspace=tmp_path, iteration=4, run_name=run_name, run_id=run_id
            )
            is factory
        )


def test_eager_bridge_receives_current_iteration_and_path(tmp_path):
    bridge = Mock()
    agent = SimpleNamespace(bridge=bridge)
    for iteration in (1, 7):
        bind_agent_run_context(
            agent, workspace=str(tmp_path), iteration=iteration, run_name="chain", run_id="id"
        )
        bridge.set_run_context.assert_called_with(
            workspace=tmp_path, iter=iteration, run_name="chain", run_id="id"
        )
    assert bridge.set_run_context.call_count == 2


@pytest.mark.parametrize("agent", [SimpleNamespace(), SimpleNamespace(bridge=None)])
def test_agents_without_accounting_hook_remain_supported(tmp_path, agent):
    bind_agent_run_context(agent, workspace=tmp_path, iteration=1, run_name="chain", run_id="id")


def test_accounting_binding_errors_are_not_swallowed(tmp_path):
    agent = SimpleNamespace(set_run_context=Mock(side_effect=ValueError("identity changed")))
    with pytest.raises(ValueError, match="identity changed"):
        bind_agent_run_context(
            agent, workspace=tmp_path, iteration=2, run_name="chain", run_id="id"
        )


@pytest.mark.parametrize("separate_search", [False, True])
@pytest.mark.parametrize("custom_factory", [False, True])
def test_literature_late_bridges_write_real_usage_before_native_return(
    tmp_path, monkeypatch, separate_search, custom_factory
):
    """#882: a pre-run binder alone loses both real native usage rows."""
    from agent import llm_bridge
    from agent.schemas.literature_review import LiteratureReviewInput
    from nodes.ml_literature_review import MLLiteratureReviewAgent

    calls = []

    def complete(**kwargs):
        calls.append(kwargs["model"])
        content = (
            {"action": "done", "reasoning": "No search required"}
            if len(calls) == 1
            else {"findings": []}
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)))],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
            model=kwargs["model"],
        )

    monkeypatch.setenv("OPENAI_API_KEY", "offline-placeholder")
    monkeypatch.setattr(llm_bridge, "load_dotenv", lambda: None)
    monkeypatch.setattr(
        llm_bridge,
        "OpenAI",
        Mock(
            return_value=SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=complete))
            )
        ),
    )
    bindings = []
    original_bind = llm_bridge.LLMBridge.set_run_context

    def bind(bridge, **kwargs):
        bindings.append((bridge, kwargs))
        return original_bind(bridge, **kwargs)

    monkeypatch.setattr(llm_bridge.LLMBridge, "set_run_context", bind)
    supplied = Mock(side_effect=llm_bridge.LLMBridge) if custom_factory else None
    factory = contextual_bridge_factory(
        supplied, workspace=tmp_path, iteration=4, run_name="chain", run_id="run-882"
    )
    inp = LiteratureReviewInput.model_validate(
        {
            "interpretation_evidence": {
                "model_types": [],
                "key_findings": [],
                "bottlenecks": [],
                "take_home_message": "Synthetic task",
                "cold_start": True,
            },
            "dynamic_search": {"enabled": True, "max_rounds": 1},
            "storage": {
                "backend": "local",
                "local": {"workspace": str(tmp_path), "run_name": "native"},
            },
            "run_name": "native",
            "task_description": "Predict a synthetic target",
            "llm_provider": "openai",
            "llm_model_id": "offline-main",
            "search_llm_provider": "openai" if separate_search else None,
            "search_llm_model_id": "offline-search" if separate_search else None,
            "llm_max_retries": 0,
        }
    )
    agent = MLLiteratureReviewAgent(bridge_factory=factory, root_cache_dir=str(tmp_path / "cache"))
    result = agent.run(inp)
    assert result.findings == []
    assert (tmp_path / "ml_literature_review_native.json").is_file()
    assert calls == ["offline-search" if separate_search else "offline-main", "offline-main"]
    assert len(bindings) == (2 if separate_search else 1)
    assert (agent.search_bridge is agent.bridge) is (not separate_search)
    if supplied is not None:
        assert supplied.call_count == len(bindings)
    rows = [json.loads(line) for line in (tmp_path / "token_usage.jsonl").read_text().splitlines()]
    assert [row["label"] for row in rows] == ["lit_review.search_decision", "lit_review.synthesis"]
    assert [(row["run_id"], row["run_name"], row["iter"], row["tokens"]) for row in rows] == [
        ("run-882", "chain", 4, {"prompt": 11, "completion": 7, "total": 18}),
        ("run-882", "chain", 4, {"prompt": 11, "completion": 7, "total": 18}),
    ]
