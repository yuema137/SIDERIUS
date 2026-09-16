from __future__ import annotations

import hashlib

import pytest

from agent.data_analysis.source_scope import apply_source_prompt
from agent.schemas.data_analysis.common import CallerIdentity, canonical_sha256
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.protocols.interpreter_to_data_analysis import local_analysis_input
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from tests.unit.nodes.test_data_analysis_agent import _Bridge, _Capability, _input
from workflows.data_analysis_composition import ResolvedWorkflowDataAnalysis
from workflows.data_analysis_stage import (
    attach_analysis_to_proposer,
    run_optional_data_analysis,
)


def _interpretation(brief) -> InterpretationOutput:
    return InterpretationOutput(
        model_types=[],
        model_descriptions={},
        total_experiments=0,
        cold_start=True,
        analysis_brief=brief,
        key_findings=[],
        bottlenecks=[],
        take_home_message="No prior experiment evidence exists.",
    )


@pytest.mark.allow_real_subprocess
def test_workflow_stage_uses_typed_adapters_and_persisted_report_identity(
    tmp_path, monkeypatch
) -> None:
    template = _input(tmp_path)
    interpretation = _interpretation(template.analysis_brief)
    capability = _Capability()
    binding = ResolvedWorkflowDataAnalysis(
        task_context=template.task_context,
        available_assets=template.available_assets,
        declared_scope=template.declared_scope,
        access_policy=template.access_policy,
        resource_envelope=template.resource_envelope,
        allowed_skill_packs=template.allowed_skill_packs,
        task_analysis_capability=capability,
        report_schema_version=1,
        config_content_sha256="7" * 64,
        config_path=str(tmp_path / "analysis-policy.json"),
        allow_generated_skill_promotion=True,
    )
    expected_input = local_analysis_input(
        interpretation,
        request_id="iteration-001",
        task_context=binding.task_context,
        available_assets=binding.available_assets,
        declared_scope=binding.declared_scope,
        access_policy=binding.access_policy,
        resource_envelope=binding.resource_envelope,
        allowed_skill_packs=binding.allowed_skill_packs,
        storage=template.storage,
        caller=CallerIdentity(
            caller_id="workflow-run",
            caller_type="workflow",
            request_source="iteration:1",
        ),
        human_advice="Measure before interpreting.",
        allow_generated_skill_promotion=True,
    )
    historical_inference_capability = object()
    seen = {}
    from workflows import data_analysis_stage

    real_agent = data_analysis_stage.DataAnalysisAgent

    def capturing_agent(**kwargs):
        seen["historical_model_inference_capability"] = kwargs.get(
            "historical_model_inference_capability"
        )
        return real_agent(**kwargs)

    monkeypatch.setattr(data_analysis_stage, "DataAnalysisAgent", capturing_agent)

    output = run_optional_data_analysis(
        interpretation,
        binding=binding,
        iteration=1,
        run_name="workflow-run",
        storage=template.storage,
        human_advice="Measure before interpreting.",
        llm_kwargs={"provider": "test", "model_id": "fake"},
        bridge_factory=lambda **kwargs: _Bridge(analysis_input=expected_input, **kwargs),
        historical_model_inference_capability=historical_inference_capability,
    )

    assert output is not None
    assert output.report_ref.logical_ref.endswith("iteration-001/report.json")
    report_path = tmp_path / output.report_ref.logical_ref
    assert output.report_ref.sha256 == hashlib.sha256(report_path.read_bytes()).hexdigest()
    proposal_input = local_full_context(interpretation, template.storage)
    projected = attach_analysis_to_proposer(proposal_input, output)
    assert projected.data_analysis_evidence is not None
    assert projected.data_analysis_evidence.findings[0].statement.endswith("mean 2.5.")
    assert seen["historical_model_inference_capability"] is historical_inference_capability
    assert expected_input.allow_generated_skill_promotion is True


def test_missing_brief_stops_at_typed_edge_without_invoking_agent(tmp_path) -> None:
    template = _input(tmp_path)
    binding = ResolvedWorkflowDataAnalysis(
        task_context=template.task_context,
        available_assets=template.available_assets,
        declared_scope=template.declared_scope,
        access_policy=template.access_policy,
        resource_envelope=template.resource_envelope,
        allowed_skill_packs=template.allowed_skill_packs,
        task_analysis_capability=_Capability(),
        report_schema_version=1,
        config_content_sha256="7" * 64,
        config_path=str(tmp_path / "analysis-policy.json"),
    )

    output = run_optional_data_analysis(
        _interpretation(None),
        binding=binding,
        iteration=1,
        run_name="workflow-run",
        storage=template.storage,
        human_advice=None,
        llm_kwargs={},
        bridge_factory=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("brief failure must not invoke Data Analysis")
        ),
    )

    assert output is None
    assert not (tmp_path / "data_analysis").exists()


@pytest.mark.allow_real_subprocess
def test_inline_lock_reaches_same_standalone_input_contract(tmp_path) -> None:
    template = _input(tmp_path)
    interpretation = _interpretation(template.analysis_brief)

    class _LockCapturingCapability(_Capability):
        def __init__(self) -> None:
            super().__init__()
            self.seen_lock = None

        def materialize_analysis_view(self, authorized):
            self.seen_lock = authorized.request.source_scope
            return super().materialize_analysis_view(authorized)

    capability = _LockCapturingCapability()
    binding = ResolvedWorkflowDataAnalysis(
        task_context=template.task_context,
        available_assets=template.available_assets,
        declared_scope=template.declared_scope,
        access_policy=template.access_policy,
        resource_envelope=template.resource_envelope,
        allowed_skill_packs=template.allowed_skill_packs,
        task_analysis_capability=capability,
        report_schema_version=1,
        config_content_sha256="7" * 64,
        config_path=str(tmp_path / "analysis-policy.json"),
    )
    expected = apply_source_prompt(
        local_analysis_input(
            interpretation,
            request_id="iteration-001",
            task_context=binding.task_context,
            available_assets=binding.available_assets,
            declared_scope=template.declared_scope,
            access_policy=binding.access_policy,
            resource_envelope=binding.resource_envelope,
            allowed_skill_packs=binding.allowed_skill_packs,
            storage=template.storage,
            caller=CallerIdentity(
                caller_id="workflow-run", caller_type="workflow", request_source="iteration:1"
            ),
        ),
        "lock: raw=dataset; models=none",
    )

    output = run_optional_data_analysis(
        interpretation,
        binding=binding,
        iteration=1,
        run_name="workflow-run",
        storage=template.storage,
        human_advice=None,
        source_prompt="lock: raw=dataset; models=none",
        llm_kwargs={"provider": "test", "model_id": "fake"},
        bridge_factory=lambda **kwargs: _Bridge(analysis_input=expected, **kwargs),
    )

    assert output is not None
    assert output.report.input_digest == canonical_sha256(expected)
    assert capability.seen_lock == expected.source_scope
    assert output.report.source_scope == expected.source_scope
