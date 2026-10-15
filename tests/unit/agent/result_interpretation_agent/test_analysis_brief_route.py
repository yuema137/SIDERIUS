"""Brief receipts and resume must describe the route that actually executes."""

import json

import pytest

from agent import llm_bridge
from agent.llm_settings import DEFAULT_LLM_MODEL
from nodes.result_interpretation_agent import ResultInterpretationAgent
from nodes.result_interpretation_agent.analysis_brief import AnalysisBriefResumeMismatchError
from tests.unit.agent.result_interpretation_agent.test_analysis_brief_generation import (
    _BriefBridge,
    _cold_input,
)

_RESPONSE = {"questions": [{"question": "Which observable patterns recur?"}]}


def _receipt(tmp_path):
    return json.loads((tmp_path / "analysis_brief_generation_brief-test.json").read_text())[
        "receipt"
    ]


@pytest.mark.parametrize("response,status", [(_RESPONSE, "generated"), ({}, "failed")])
def test_real_bridge_default_route_is_recorded_offline(tmp_path, monkeypatch, response, status):
    monkeypatch.setattr(llm_bridge, "load_dotenv", lambda: None)
    monkeypatch.setattr(llm_bridge, "OpenAI", lambda **_: object())
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-not-a-credential")
    monkeypatch.setattr(llm_bridge.LLMBridge, "generate", lambda *_args, **_kwargs: response)
    agent = ResultInterpretationAgent(provider="OPENAI")
    agent.run(_cold_input(tmp_path, requested=True))
    receipt = _receipt(tmp_path)
    assert receipt["model_id"] == DEFAULT_LLM_MODEL
    assert receipt["provider"] == "openai"
    assert receipt["status"] == status


@pytest.mark.parametrize(
    "provider,model,expected",
    [
        ("OPENAI", None, DEFAULT_LLM_MODEL),
        ("custom-provider", "explicit-model", "explicit-model"),
    ],
)
def test_metadata_free_bridge_uses_declared_route(tmp_path, provider, model, expected):
    bridge = _BriefBridge(_RESPONSE)
    agent = ResultInterpretationAgent(
        provider=provider, model_id=model, bridge_factory=lambda **_: bridge
    )
    agent.run(_cold_input(tmp_path, requested=True))
    assert _receipt(tmp_path)["model_id"] == expected
    assert _receipt(tmp_path)["provider"] == provider


@pytest.mark.parametrize("changed_field", ["provider", "model_name"])
def test_actual_bridge_route_controls_receipt_and_resume(tmp_path, changed_field):
    bridge = _BriefBridge(_RESPONSE)
    bridge.provider = "custom-provider"
    bridge.model_name = "actual-model"
    agent = ResultInterpretationAgent(model_id="requested-model", bridge_factory=lambda **_: bridge)
    inp = _cold_input(tmp_path, requested=True)
    agent.run(inp)
    assert _receipt(tmp_path)["model_id"] == "actual-model"
    assert _receipt(tmp_path)["provider"] == "custom-provider"
    agent.run(inp)
    assert len(bridge.calls) == 1
    setattr(bridge, changed_field, "changed-route")
    with pytest.raises(AnalysisBriefResumeMismatchError):
        agent.run(inp)
    assert len(bridge.calls) == 1


def test_provider_only_bridge_resolves_its_own_default(tmp_path):
    bridge = _BriefBridge(_RESPONSE)
    bridge.provider = "gemini"
    ResultInterpretationAgent(bridge_factory=lambda **_: bridge).run(
        _cold_input(tmp_path, requested=True)
    )
    assert _receipt(tmp_path)["model_id"] == "gemini-3.1-flash-lite-preview"
    assert _receipt(tmp_path)["provider"] == "gemini"


@pytest.mark.parametrize("expose_invalid_model", [False, True])
def test_unresolved_route_refuses_before_call_but_disabled_path_is_unchanged(
    tmp_path, expose_invalid_model
):
    bridge = _BriefBridge(_RESPONSE)
    if expose_invalid_model:
        bridge.model_name = (
            None  # Do not replace invalid execution metadata with a guessed default.
        )
    agent = ResultInterpretationAgent(provider="unknown", bridge_factory=lambda **_: bridge)
    agent.run(_cold_input(tmp_path / "disabled", requested=False))
    with pytest.raises(ValueError, match="resolved model identity"):
        agent.run(_cold_input(tmp_path, requested=True))
    assert bridge.calls == []
    assert not (tmp_path / "analysis_brief_generation_brief-test.json").exists()


def test_timeout_receipt_uses_resolved_model(tmp_path):
    class TimeoutBridge(_BriefBridge):
        def generate(self, *_args, **_kwargs):
            raise TimeoutError("offline timeout")

    bridge = TimeoutBridge(_RESPONSE)
    ResultInterpretationAgent(bridge_factory=lambda **_: bridge).run(
        _cold_input(tmp_path, requested=True)
    )
    receipt = _receipt(tmp_path)
    assert receipt["status"] == "timed_out"
    assert receipt["model_id"] == DEFAULT_LLM_MODEL


def test_disabled_brief_does_not_inspect_route_metadata(tmp_path):
    class UninspectableBridge(_BriefBridge):
        @property
        def provider(self):
            raise AssertionError("disabled brief must not inspect routing")

    bridge = UninspectableBridge(_RESPONSE)
    output = ResultInterpretationAgent(bridge_factory=lambda **_: bridge).run(
        _cold_input(tmp_path, requested=False)
    )
    assert output.analysis_brief is None
    assert bridge.calls == []
