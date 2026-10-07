"""An invalid program repair must not terminate unrelated model exploration."""

import copy
import json

import pytest

from agent.data_analysis.analysis_code_sandbox import AnalysisCodeSandbox
from agent.prompt_templates.proposal import render_data_analysis_evidence
from agent.schemas.data_analysis.common import CallerIdentity
from agent.schemas.data_analysis.recovery import AnalysisRecoveryPolicy
from agent.schemas.protocols.interpreter_to_data_analysis import local_analysis_input
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from nodes.data_analysis_agent import DataAnalysisAgent
from tests.unit.nodes.test_data_analysis_agent import (
    _GeneratedProgramBridge,
    _input,
    _RecordingCapability,
)
from tests.unit.workflows.test_data_analysis_stage import _interpretation
from workflows.data_analysis_composition import ResolvedWorkflowDataAnalysis
from workflows.data_analysis_stage import attach_analysis_to_proposer, run_optional_data_analysis


class BrokenRepairBridge(_GeneratedProgramBridge):
    def __init__(self, *, exhausted=False, **kwargs):
        super().__init__(**kwargs)
        self.exhausted = exhausted
        self.draft = None

    def generate(self, system, user, *, label):
        if label.endswith(".repair") and label.startswith("data_analysis.generated_program"):
            self.calls.append(label)
            assert "Preserve the original seed" in system
            assert "deleting a forbidden numeric" not in system
            repaired = copy.deepcopy(self.draft)
            repaired["source_code"] = repaired["source_code"].replace(
                "'unit': null", "'unit': None"
            )
            repaired["seed"] = None  # Observed failure: repair introduces a different error.
            return repaired
        if label == "data_analysis.generated_program.regeneration":
            self.calls.append(label)
            assert "explicit seed" in user
            assert "fresh generation attempt" in user
            fresh = copy.deepcopy(self.draft)
            if not self.exhausted:
                fresh["source_code"] = fresh["source_code"].replace("'unit': null", "'unit': None")
            return fresh
        result = super().generate(system, user, label=label)
        if label == "data_analysis.generated_program":
            result["source_code"] = result["source_code"].replace("'unit': None", "'unit': null")
            self.draft = copy.deepcopy(result)
        return result


def test_recovery_policy_changes_resume_identity_not_scientific_prompt(tmp_path):
    """Detect an unpinned recovery change or accidental policy leakage into prompts."""
    from agent.prompt_templates.data_analysis import _planning_input

    native = _input(tmp_path)
    historical = native.model_copy(
        update={"recovery_policy": AnalysisRecoveryPolicy(generated_program_retries=0)}
    )
    assert native.canonical_scientific_digest() != historical.canonical_scientific_digest()
    assert _planning_input(native) == _planning_input(historical)


@pytest.mark.allow_real_subprocess
def test_program_regeneration_executes_and_reuses_report(tmp_path):
    probe = AnalysisCodeSandbox().probe()
    if not probe.available:
        pytest.skip(f"host cannot enforce sandbox: {probe.reason}")
    inp = _input(tmp_path)
    bridge = BrokenRepairBridge(analysis_input=inp)
    capability = _RecordingCapability()
    node = DataAnalysisAgent(
        task_analysis_capability=capability,
        bridge_factory=lambda **_: bridge,
        provider="test",
        model_id="fake",
    )
    report = node.run(inp)
    assert report.findings
    assert report.skill_result_summaries[0].status == "completed"
    assert len(capability.requested_scopes) == 1
    assert bridge.calls.count("data_analysis.generated_program.regeneration") == 1
    calls = list(bridge.calls)
    assert node.run(inp) == report
    assert bridge.calls == calls


@pytest.mark.parametrize("retries", [None, 0, 2])
def test_exhausted_program_recovery_reaches_proposer_without_data_access(tmp_path, retries):
    template = _input(tmp_path)
    interpretation = _interpretation(template.analysis_brief)
    capability = _RecordingCapability()
    binding = ResolvedWorkflowDataAnalysis(
        task_context=template.task_context,
        available_assets=template.available_assets,
        declared_scope=template.declared_scope,
        access_policy=template.access_policy,
        resource_envelope=template.resource_envelope,
        recovery_policy=(
            None if retries is None else AnalysisRecoveryPolicy(generated_program_retries=retries)
        ),
        allowed_skill_packs=template.allowed_skill_packs,
        task_analysis_capability=capability,
        report_schema_version=1,
        config_content_sha256="7" * 64,
        config_path=str(tmp_path / "analysis-policy.json"),
    )
    expected = local_analysis_input(
        interpretation,
        request_id="iteration-001",
        task_context=binding.task_context,
        available_assets=binding.available_assets,
        declared_scope=binding.declared_scope,
        access_policy=binding.access_policy,
        resource_envelope=binding.resource_envelope,
        recovery_policy=binding.recovery_policy,
        allowed_skill_packs=binding.allowed_skill_packs,
        storage=template.storage,
        caller=CallerIdentity(
            caller_id="workflow-run", caller_type="workflow", request_source="iteration:1"
        ),
    )
    bridge = BrokenRepairBridge(analysis_input=expected, exhausted=True)
    output = run_optional_data_analysis(
        interpretation,
        binding=binding,
        iteration=1,
        run_name="workflow-run",
        storage=template.storage,
        human_advice=None,
        llm_kwargs={"provider": "test", "model_id": "fake"},
        bridge_factory=lambda **_: bridge,
    )
    assert output is not None
    report = output.report
    assert not report.findings and not report.assets_inspected and not report.skill_result_refs
    assert all(q.status == "unresolved" for q in report.question_outcomes)
    assert report.limitations[0].limitation_id == "analysis-preparation-failed"
    proposal = local_full_context(interpretation, storage=template.storage)
    proposal = attach_analysis_to_proposer(proposal, output)
    prompt = render_data_analysis_evidence(proposal.data_analysis_evidence)
    assert "Analysis preparation exhausted" in prompt
    assert not capability.requested_scopes
    expected_retries = 1 if retries is None else retries
    assert bridge.calls.count("data_analysis.generated_program.regeneration") == expected_retries
    assert (
        bridge.calls.count("data_analysis.generated_program.regeneration.repair")
        == expected_retries
    )
    assert "data_analysis.plan" not in bridge.calls
    receipt_path = (
        tmp_path
        / "data_analysis"
        / "standalone"
        / "iteration-001"
        / "structured_output_receipts.jsonl"
    )
    receipts = [json.loads(line) for line in receipt_path.read_text().splitlines()]
    failed = [r for r in receipts if r["stage"].startswith("data_analysis.generated_program")]
    assert len(failed) == 1 + expected_retries
    assert all(r["repair_passed"] is False for r in failed)
