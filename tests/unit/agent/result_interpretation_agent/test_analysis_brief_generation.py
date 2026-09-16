from __future__ import annotations

import json

import pytest

from agent.data_analysis.reference_packs import builtin_pack_refs
from agent.schemas.analysis_brief_generation import AnalysisBriefGenerationReceipt
from agent.schemas.data_analysis.context import AnalysisTaskContext
from agent.schemas.data_analysis.resources import AnalysisResourceEnvelope
from agent.schemas.data_analysis.source_scope import DeclaredAnalysisScope
from agent.schemas.interpretation import InterpretationInput, ModelRunSummary
from agent.schemas.protocols.interpreter_to_data_analysis import (
    MissingAnalysisBriefError,
    local_analysis_input,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from nodes.result_interpretation_agent import ResultInterpretationAgent
from tests.helpers.metric_fixtures import shipped_spec
from tests.unit.agent.data_analysis.test_contracts_and_authorization import _asset

_SUMMARY = ModelRunSummary(
    model_type="synthetic_model",
    run_name="v1",
    status="completed",
    completed_rounds=2,
    best_denoising_score=0.8,
    worst_denoising_score=1.2,
    best_config={"model_config": {}, "train_config": {}, "loss_config": {}},
    round_scores=[1.2, 0.8],
    round_conclusions=["Initial measurement.", "Second measurement."],
    model_description="A synthetic model used only for contract testing.",
)


class _LegacyBridge:
    def __init__(self, workspace: str) -> None:
        self.workspace = workspace
        self.calls: list[tuple[str, str, str]] = []

    def generate(self, system: str, user: str, *, label: str, **_kwargs):
        self.calls.append(
            (
                label,
                system.replace(self.workspace, "<WORKSPACE>"),
                user.replace(self.workspace, "<WORKSPACE>"),
            )
        )
        if label == "interpretation.per_model":
            return {
                "key_findings": ["The second measurement is lower."],
                "bottlenecks": ["Only two measurements are available."],
                "best_config_analysis": "The second configuration has the lower score.",
                "score_trend": "The measured score decreased.",
            }
        if label == "interpretation.synthesis":
            return {
                "key_findings": ["The measured score decreased."],
                "bottlenecks": ["Evidence remains limited."],
                "take_home_message": "Collect structured evidence before another decision.",
            }
        raise AssertionError(label)


class _BriefBridge:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple[str, str, str]] = []

    def generate(self, system: str, user: str, *, label: str, **_kwargs):
        self.calls.append((label, system, user))
        if label != "interpretation.analysis_brief":
            raise AssertionError(f"cold start unexpectedly made primary call {label!r}")
        return self.response


class _HistoryBriefBridge(_LegacyBridge):
    def generate(self, system: str, user: str, *, label: str, **kwargs):
        if label == "interpretation.analysis_brief":
            self.calls.append(
                (
                    label,
                    system.replace(self.workspace, "<WORKSPACE>"),
                    user.replace(self.workspace, "<WORKSPACE>"),
                )
            )
            return {
                "questions": [
                    {
                        "question": "Which measured behavior explains the observed score change?",
                        "priority": 4,
                    }
                ]
            }
        return super().generate(system, user, label=label, **kwargs)


def _storage(tmp_path) -> StorageConfig:
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=str(tmp_path), run_name="brief-test"),
    )


def _cold_input(tmp_path, *, requested: bool) -> InterpretationInput:
    return InterpretationInput(
        cold_start=True,
        task_description="Characterize a generic uniformly sampled sensor signal.",
        human_advice="Prioritize periodic structure, without assuming any prior model.",
        analysis_brief_requested=requested,
        storage=_storage(tmp_path),
    )


def _adapter_kwargs(tmp_path) -> dict:
    asset = _asset()
    return {
        "request_id": "analysis-request",
        "task_context": AnalysisTaskContext(
            task_id="synthetic-task",
            scientific_goal="Understand a generic signal.",
            task_description="Synthetic regression.",
            input_description="A sampled scalar signal.",
            metric_summary="Lower error is better.",
            forward_contract=ForwardContract(),
        ),
        "available_assets": (asset,),
        "declared_scope": DeclaredAnalysisScope(raw_input_asset_ids=(asset.asset_id,)),
        "access_policy": {
            "policy_id": "policy",
            "policy_version": 1,
            "purpose": "Synthetic analysis",
            "split_rules": [{"split_id": "validation", "data_visible": True}],
        },
        "resource_envelope": AnalysisResourceEnvelope(
            wall_time_budget_s=30,
            per_skill_timeout_s=10,
        ),
        "allowed_skill_packs": builtin_pack_refs("core-analysis"),
        "storage": _storage(tmp_path),
        "caller": {"caller_id": "test-workflow", "caller_type": "workflow"},
    }


def test_false_preserves_legacy_primary_calls_and_serialized_contract(tmp_path) -> None:
    omitted_input = InterpretationInput(
        summaries=[_SUMMARY],
        metric_spec=shipped_spec(),
        task_description="A synthetic regression task.",
        storage=_storage(tmp_path / "omitted"),
    )
    explicit_input = InterpretationInput(
        summaries=[_SUMMARY],
        metric_spec=shipped_spec(),
        task_description="A synthetic regression task.",
        analysis_brief_requested=False,
        storage=_storage(tmp_path / "explicit"),
    )
    omitted_bridge = _LegacyBridge(str(tmp_path / "omitted"))
    explicit_bridge = _LegacyBridge(str(tmp_path / "explicit"))

    omitted = ResultInterpretationAgent(bridge_factory=lambda **_kwargs: omitted_bridge).run(
        omitted_input
    )
    explicit = ResultInterpretationAgent(bridge_factory=lambda **_kwargs: explicit_bridge).run(
        explicit_input
    )

    assert omitted_bridge.calls == explicit_bridge.calls
    assert all(call[0] != "interpretation.analysis_brief" for call in explicit_bridge.calls)
    assert omitted.model_dump() == explicit.model_dump()
    assert "analysis_brief_requested" not in explicit_input.model_dump(mode="json")
    assert "analysis_brief" not in explicit.model_dump(mode="json")
    assert not (tmp_path / "explicit" / "analysis_brief_generation_brief-test.json").exists()


def test_requested_cold_start_generates_and_resumes_one_narrow_brief(tmp_path) -> None:
    response = {
        "questions": [
            {
                "question": "Does the observed signal contain stable periodic structure?",
                "priority": 4,
                "observations_to_verify": ["A repeatable spectral component may be present."],
            }
        ],
        "optional_scope_note": "Characterize the authorized observations only.",
    }
    bridge = _BriefBridge(response)
    inp = _cold_input(tmp_path, requested=True)
    output = ResultInterpretationAgent(
        provider="test-provider",
        model_id="test-model",
        bridge_factory=lambda **_kwargs: bridge,
    ).run(inp)

    assert [call[0] for call in bridge.calls] == ["interpretation.analysis_brief"]
    assert output.analysis_brief is not None
    assert output.analysis_brief.questions[0].question.startswith("Does the observed")
    prompt_payload = json.loads(bridge.calls[0][2])
    assert prompt_payload["interpretation_evidence"] == {
        "cold_start": True,
        "statement": "No prior experimental evidence exists.",
    }
    serialized = output.analysis_brief.model_dump_json()
    for forbidden in ("skill_id", "asset_id", "sampling_plan", "model_architecture"):
        assert forbidden not in serialized

    record_path = tmp_path / "analysis_brief_generation_brief-test.json"
    record = json.loads(record_path.read_text())
    receipt = AnalysisBriefGenerationReceipt.model_validate(record["receipt"])
    assert receipt.status == "generated"
    assert receipt.brief_sha256 is not None
    adapted = local_analysis_input(output, **_adapter_kwargs(tmp_path))
    assert adapted.analysis_brief == output.analysis_brief

    resumed_bridge = _BriefBridge(response)
    resumed = ResultInterpretationAgent(
        provider="test-provider",
        model_id="test-model",
        bridge_factory=lambda **_kwargs: resumed_bridge,
    ).run(inp)
    assert resumed.analysis_brief == output.analysis_brief
    assert resumed_bridge.calls == []


def test_requested_history_path_keeps_primary_calls_then_adds_one_second_stage(tmp_path) -> None:
    bridge = _HistoryBriefBridge(str(tmp_path))
    output = ResultInterpretationAgent(
        provider="test-provider",
        model_id="test-model",
        bridge_factory=lambda **_kwargs: bridge,
    ).run(
        InterpretationInput(
            summaries=[_SUMMARY],
            metric_spec=shipped_spec(),
            task_description="A synthetic regression task.",
            analysis_brief_requested=True,
            storage=_storage(tmp_path),
        )
    )

    assert [call[0] for call in bridge.calls] == [
        "interpretation.per_model",
        "interpretation.analysis_brief",
    ]
    assert output.analysis_brief is not None


def test_malformed_brief_is_persisted_as_failure_and_adapter_does_not_guess(tmp_path) -> None:
    bridge = _BriefBridge(
        {
            "questions": [
                {
                    "question": "Inspect periodicity.",
                    "skill_id": "welch_psd",
                }
            ]
        }
    )
    inp = _cold_input(tmp_path, requested=True)
    output = ResultInterpretationAgent(
        provider="test-provider",
        model_id="test-model",
        bridge_factory=lambda **_kwargs: bridge,
    ).run(inp)
    assert output.analysis_brief is None
    record = json.loads((tmp_path / "analysis_brief_generation_brief-test.json").read_text())
    receipt = AnalysisBriefGenerationReceipt.model_validate(record["receipt"])
    assert receipt.status == "failed"
    assert receipt.failure_code == "invalid_analysis_brief"

    with pytest.raises(MissingAnalysisBriefError, match="no validated AnalysisBrief"):
        local_analysis_input(output, **_adapter_kwargs(tmp_path))
