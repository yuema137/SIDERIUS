from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest

from agent.data_analysis.analysis_code_sandbox import AnalysisCodeSandbox
from agent.data_analysis.discovery import discover_skills
from agent.data_analysis.persistence import AnalysisPersistenceError
from agent.data_analysis.plan_validation import AnalysisPlanResolutionError
from agent.data_analysis.reference_packs import builtin_pack_refs
from agent.data_analysis.structured_output import DataAnalysisStructuredOutputError
from agent.prompt_templates.proposal import render_data_analysis_evidence
from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    ArtifactIntrinsicScope,
    AssetProvenance,
    MaterializedAnalysisView,
    TaskOpaqueScopeRef,
    WorkspaceArtifactLocation,
)
from agent.schemas.data_analysis.common import CertifiedArtifactRef, canonical_sha256
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.plan import AnalysisPlan
from agent.schemas.proposal import ProposalInput
from agent.schemas.proposer_data_analysis_evidence import (
    build_proposer_data_analysis_evidence,
)
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.protocols.data_analysis_to_ml_model_propose import local_typed_evidence
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from nodes.data_analysis_agent import DataAnalysisAgent
from nodes.data_analysis_agent.data_analysis_agent import _SkillSelection


class _Capability:
    def __init__(self) -> None:
        buffer = io.BytesIO()
        np.savez(
            buffer,
            example_ids=np.asarray(["a", "b", "c", "d"]),
            information__data=np.asarray([1.0, 2.0, 3.0, 4.0]),
        )
        self.payload = buffer.getvalue()

    def materialize_analysis_view(self, authorized) -> MaterializedAnalysisView:
        request = authorized.request
        digest = hashlib.sha256(self.payload).hexdigest()
        return MaterializedAnalysisView(
            materialization_id="materialized-summary",
            invocation_id=request.invocation_id,
            binding_id=request.binding_id,
            slot_id=request.slot_id,
            asset_id=request.asset.asset_id,
            split_id=request.split_id,
            content_ref=CertifiedArtifactRef(
                logical_ref="opaque://task-store/summary-input",
                sha256=digest,
                media_type="application/x-npz",
                byte_size=len(self.payload),
            ),
            format_id=request.requested_format_id,
            population_unit="examples",
            total_available=4,
            materialized_count=4,
            certified_information=request.requested_information,
            selection_identity={
                "selection_id": "selection-summary",
                "selection_sha256": "4" * 64,
                "sampling_policy_sha256": canonical_sha256(request.sampling_policy),
                "sampling_mode": request.sampling_policy.mode,
                "sampling_strategy": request.sampling_policy.strategy,
                "sampling_seed": request.sampling_policy.seed,
                "population_unit": "examples",
                "total_available": 4,
                "selected_count": 4,
            },
            source_digests=(digest,),
            authorization_receipt=authorized.authorization_receipt,
        )

    def export_analysis_materialization(self, content_ref, destination: Path) -> None:
        assert content_ref.logical_ref.startswith("opaque://")
        destination.write_bytes(self.payload)


class _RecordingCapability(_Capability):
    def __init__(self) -> None:
        super().__init__()
        self.requested_scopes = []

    def materialize_analysis_view(self, authorized) -> MaterializedAnalysisView:
        self.requested_scopes.append(authorized.request.requested_scope)
        return super().materialize_analysis_view(authorized)


class _Bridge:
    def __init__(self, *, analysis_input: DataAnalysisInput, **_kwargs) -> None:
        self.inp = analysis_input
        self.discovery = discover_skills(
            analysis_input.allowed_skill_packs,
            generated_skill_registry=analysis_input.generated_skill_registry,
        )

    def generate(self, _system, _user, *, label):
        if label == "data_analysis.skill_selection":
            return {
                "skill_ids": ["summary_statistics"],
                "rationale": "The question asks for a bounded numeric summary.",
            }
        if label == "data_analysis.plan":
            scope = self.inp.available_assets[0].authorized_scope.model_dump(mode="json")
            return {
                "plan_id": "summary-plan",
                "input_digest": canonical_sha256(self.inp),
                "access_policy_digest": canonical_sha256(self.inp.access_policy),
                "discovery_snapshot_digest": self.discovery.snapshot_digest,
                "questions": ["q-summary"],
                "invocations": [
                    {
                        "invocation_id": "summary-invocation",
                        "skill_id": "summary_statistics",
                        "question_ids": ["q-summary"],
                        "bindings": [
                            {
                                "binding_id": "summary-values",
                                "slot_id": "values",
                                "asset_id": "dataset",
                                "requested_format_id": "siderius.numeric-array.v1",
                                "requested_information": [{"information_class": "data"}],
                            }
                        ],
                        "sampling_plan": {
                            "split_id": "validation",
                            "requested_scope": scope,
                            "policy": {
                                "mode": "fixed",
                                "max_items": 4,
                                "strategy": "uniform",
                                "seed": 11,
                            },
                        },
                        "arguments": {},
                        "expected_time_cost": "cheap",
                        "expected_memory_cost": "low",
                    }
                ],
                "stop_policy": {"max_invocations": 1},
                "rationale": "Run the smallest sufficient summary skill.",
            }
        if label == "data_analysis.synthesis":
            return {
                "executive_summary": "The selected values have a mean of 2.5.",
                "findings": [
                    {
                        "finding_id": "finding-mean",
                        "result_id": f"{self.inp.request_id}.summary-invocation.result",
                        "statement": "The four inspected values have mean 2.5.",
                        "quantitative_result_ids": ["mean", "finite_count"],
                        "confidence_level": "high",
                        "confidence_rationale": "The deterministic summary completed on all selected examples.",
                        "confidence_limitations": [],
                        "modeling_relevance": "The observed scale may inform later model diagnostics.",
                    }
                ],
                "question_outcomes": [
                    {
                        "question_id": "q-summary",
                        "status": "addressed",
                        "summary": "Summary statistics were measured.",
                        "finding_ids": ["finding-mean"],
                    }
                ],
                "limitations": [],
                "unresolved_questions": [],
                "modeling_relevance": ["The values' scale is now explicitly measured."],
            }
        raise AssertionError(label)


class _RepairingBridge(_Bridge):
    def __init__(self, *, change_decision: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self.change_decision = change_decision
        self.calls: list[tuple[str, str]] = []

    def generate(self, system, user, *, label):
        self.calls.append((label, user))
        if label == "data_analysis.skill_selection":
            return {
                "skill_ids": ["summary_statistics"],
                "rationale": {"reason": "A bounded numeric summary answers the question."},
            }
        if label == "data_analysis.skill_selection.repair":
            return {
                "skill_ids": (
                    ["nonfinite_and_missingness"]
                    if self.change_decision
                    else ["summary_statistics"]
                ),
                "rationale": "A bounded numeric summary answers the question.",
            }
        return super().generate(system, user, label=label)


class _PlanRepairingBridge(_Bridge):
    def __init__(self, *, repair_change: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.repair_change = repair_change
        self.calls: list[tuple[str, str]] = []
        self.system_prompts: dict[str, str] = {}

    def _malformed_plan(self, system, user):
        plan = copy.deepcopy(super().generate(system, user, label="data_analysis.plan"))
        requested = plan["invocations"][0]["bindings"][0]["requested_information"]
        requested[0]["fields"] = ["data"]
        if self.repair_change == "metadata_field":
            requested.append({"information_class": "metadata", "fields": ["snr"]})
        return plan

    def generate(self, system, user, *, label):
        self.calls.append((label, user))
        self.system_prompts[label] = system
        if label == "data_analysis.plan":
            return self._malformed_plan(system, user)
        if label == "data_analysis.plan.repair":
            plan = self._malformed_plan(system, user)
            invocation = plan["invocations"][0]
            binding = invocation["bindings"][0]
            binding["requested_information"][0]["fields"] = []
            changes = {
                "information_class": lambda: binding["requested_information"][0].update(
                    information_class="target"
                ),
                "metadata_field": lambda: binding["requested_information"][1].update(
                    fields=["frequency"]
                ),
                "skill": lambda: invocation.update(skill_id="nonfinite_and_missingness"),
                "binding": lambda: binding.update(binding_id="changed-binding"),
                "asset": lambda: binding.update(asset_id="changed-asset"),
                "format": lambda: binding.update(requested_format_id="changed-format.v1"),
                "sampling": lambda: invocation["sampling_plan"]["policy"].update(seed=12),
                "parameters": lambda: invocation.update(arguments={"ddof": 1}),
                "priority": lambda: invocation.update(priority=5),
                "stop_policy": lambda: plan["stop_policy"].update(minimum_remaining_time_s=2.0),
                "resource_intent": lambda: invocation.update(expected_time_cost="moderate"),
            }
            if self.repair_change is not None:
                changes[self.repair_change]()
            return plan
        return super().generate(system, user, label=label)


class _GeneratedProgramBridge(_Bridge):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.calls: list[str] = []

    @staticmethod
    def _generated_identity(plan_prompt: str) -> dict:
        start = plan_prompt.index("Persisted generated programs available to the final plan:")
        start = plan_prompt.index("[", start)
        end = plan_prompt.index("\n\nGenerated programs already exist", start)
        payload = json.loads(plan_prompt[start:end])
        return payload[0]["identity"]

    def generate(self, system, user, *, label):
        self.calls.append(label)
        if label == "data_analysis.skill_selection":
            return {
                "skill_ids": [],
                "generated_program_question_ids": ["q-summary"],
                "rationale": "No configured skill measures successive absolute differences.",
            }
        if label == "data_analysis.generated_program":
            assert "`required=true`" in system
            assert "`default`" in system
            assert "must be null" in system
            assert "explicit non-negative `seed`" in system
            assert "Binding IDs are chosen after source generation" in system
            assert '`descriptor["slot_id"]`' in system
            assert "information arrays `[N,C,T]`" in system
            assert "`valid_mask[N,T]`" in system
            assert "`effective_count + dropped_count` must equal" in system
            assert "drop reasons are unique" in system
            assert '`descriptor["population_unit"]`' in system
            assert "including description wording" in system
            assert "Authoritative JSON schema for the payload returned by analyze" in user
            assert '"title": "SkillPayload"' in user
            assert '"relative_path"' in user
            assert '"effective_count"' in user
            return {
                "program_id": "successive-difference",
                "question_ids": ["q-summary"],
                "source_code": (
                    "import numpy as np\n\n"
                    "def analyze(inputs, parameters, output_directory):\n"
                    "    values = inputs['custom-values']['arrays']['information__data']\n"
                    "    measured = float(np.mean(np.abs(np.diff(values))))\n"
                    "    return {\n"
                    "        'summary': 'Measured mean absolute successive difference.',\n"
                    "        'quantitative_results': [{\n"
                    "            'result_key': 'mean_absolute_successive_difference',\n"
                    "            'value': measured,\n"
                    "            'unit': None,\n"
                    "            'description': 'Mean absolute difference of successive values',\n"
                    "        }],\n"
                    "        'produced_artifacts': [],\n"
                    "        'analysis_usage': {\n"
                    "            'effective_count': 4, 'dropped_count': 0, 'drop_reasons': []\n"
                    "        },\n"
                    "        'warnings': [],\n"
                    "    }\n"
                ),
                "input_slots": [
                    {
                        "slot_id": "values",
                        "description": "Authorized numeric values",
                        "accepted_asset_types": ["dataset"],
                        "accepted_view_formats": ["siderius.numeric-array.v1"],
                        "required_information": [{"information_class": "data", "fields": []}],
                    }
                ],
                "parameters": [],
                "expected_measurements": [
                    {
                        "result_key": "mean_absolute_successive_difference",
                        "description": "Mean absolute difference of successive values",
                        "value_type": "number",
                    }
                ],
                "expected_artifacts": [],
                "resource_request": {
                    "wall_time_s": 4.0,
                    "max_host_memory_gb": 1.0,
                    "max_artifact_count": 0,
                    "max_artifact_bytes": 0,
                },
                "determinism": "deterministic",
                "seed": 11,
                "rationale": "This bounded statistic is absent from the configured toolbox.",
            }
        if label in {"data_analysis.plan", "data_analysis.plan.resolution_retry"}:
            identity = self._generated_identity(user)
            scope = self.inp.available_assets[0].authorized_scope.model_dump(mode="json")
            return {
                "plan_id": "generated-plan",
                "input_digest": canonical_sha256(self.inp),
                "access_policy_digest": canonical_sha256(self.inp.access_policy),
                "discovery_snapshot_digest": self.discovery.snapshot_digest,
                "questions": ["q-summary"],
                "invocations": [
                    {
                        "action_kind": "generated_program",
                        "invocation_id": "generated-invocation",
                        "program_identity": identity,
                        "question_ids": ["q-summary"],
                        "bindings": [
                            {
                                "binding_id": "custom-values",
                                "slot_id": "values",
                                "asset_id": "dataset",
                                "requested_format_id": "siderius.numeric-array.v1",
                                "requested_information": [
                                    {"information_class": "data", "fields": []}
                                ],
                            }
                        ],
                        "sampling_plan": {
                            "split_id": "validation",
                            "requested_scope": scope,
                            "policy": {
                                "mode": "fixed",
                                "max_items": 4,
                                "strategy": "uniform",
                                "seed": 11,
                            },
                        },
                        "arguments": {},
                    }
                ],
                "stop_policy": {"max_invocations": 1},
                "rationale": "Execute the already-persisted custom analysis.",
            }
        if label == "data_analysis.synthesis":
            return {
                "executive_summary": "Successive values differ by 1.0 on average.",
                "findings": [
                    {
                        "finding_id": "finding-successive-difference",
                        "result_id": f"{self.inp.request_id}.generated-invocation.result",
                        "statement": "The mean absolute successive difference is 1.0.",
                        "quantitative_result_ids": ["mean_absolute_successive_difference"],
                        "confidence_level": "high",
                        "confidence_rationale": "All four selected values were analyzed.",
                        "confidence_limitations": [],
                        "modeling_relevance": "Adjacent variation is now measured.",
                    }
                ],
                "question_outcomes": [
                    {
                        "question_id": "q-summary",
                        "status": "addressed",
                        "summary": "The custom statistic was measured.",
                        "finding_ids": ["finding-successive-difference"],
                    }
                ],
                "limitations": [],
                "unresolved_questions": [],
                "modeling_relevance": ["Adjacent variation is explicit."],
            }
        raise AssertionError(label)


class _MissingGeneratedArtifactBridge(_GeneratedProgramBridge):
    def generate(self, system, user, *, label):
        if label == "data_analysis.generated_program":
            payload = super().generate(system, user, label=label)
            payload["expected_artifacts"] = [
                {
                    "artifact_type": "table",
                    "media_type": "text/csv",
                    "description": "Required generated table",
                    "required": True,
                }
            ]
            payload["resource_request"]["max_artifact_count"] = 1
            payload["resource_request"]["max_artifact_bytes"] = 1024
            payload["source_code"] = payload["source_code"].replace(
                "'produced_artifacts': [],",
                "'produced_artifacts': [{'artifact_type': 'table', "
                "'logical_name': 'missing', 'media_type': 'text/csv', "
                "'relative_path': 'artifacts/missing.csv', "
                "'description': 'Required generated table'}],",
            )
            return payload
        if label == "data_analysis.synthesis":
            self.calls.append(label)
            return {
                "executive_summary": "Generated output could not be certified.",
                "findings": [],
                "question_outcomes": [
                    {
                        "question_id": "q-summary",
                        "status": "unresolved",
                        "summary": "The declared artifact was absent.",
                        "finding_ids": [],
                        "limitation_ids": ["missing-artifact"],
                    }
                ],
                "limitations": [
                    {
                        "limitation_id": "missing-artifact",
                        "statement": "Generated artifact certification failed.",
                        "affected_question_ids": ["q-summary"],
                    }
                ],
                "unresolved_questions": ["q-summary"],
                "modeling_relevance": [],
            }
        return super().generate(system, user, label=label)


class _PromotingGeneratedProgramBridge(_GeneratedProgramBridge):
    def generate(self, system, user, *, label):
        if label == "data_analysis.generated_skill_promotion":
            self.calls.append(label)
            self.promotion_prompt = (system, user)
            return {
                "promotions": [
                    {
                        "program_id": "successive-difference",
                        "skill_id": "successive_difference_summary",
                        "title": "Successive difference summary",
                        "one_line_description": (
                            "Measures mean absolute successive differences in numeric observations."
                        ),
                        "keywords": ["successive", "difference", "adjacent"],
                        "aliases": ["adjacent difference"],
                        "tags": ["numeric"],
                        "applicable_when": (
                            "Use when later questions need the same adjacent-variation measure."
                        ),
                        "time_cost": "cheap",
                        "memory_cost": "low",
                        "rationale": "The next analysis question requests the same operation.",
                    }
                ],
                "rationale": "Promote exactly one reusable completed operation.",
            }
        return super().generate(system, user, label=label)


class _GeneratedSkillReuseBridge(_Bridge):
    def __init__(self, *, analysis_input: DataAnalysisInput, **_kwargs) -> None:
        self.inp = analysis_input
        self.discovery = discover_skills(
            analysis_input.allowed_skill_packs,
            generated_skill_registry=analysis_input.generated_skill_registry,
        )
        self.calls: list[str] = []

    def generate(self, _system, _user, *, label):
        self.calls.append(label)
        if label == "data_analysis.skill_selection":
            return {
                "skill_ids": ["successive_difference_summary"],
                "rationale": "Reuse the exact promoted local operation.",
            }
        if label == "data_analysis.plan":
            scope = self.inp.available_assets[0].authorized_scope.model_dump(mode="json")
            return {
                "plan_id": "generated-skill-reuse-plan",
                "input_digest": canonical_sha256(self.inp),
                "access_policy_digest": canonical_sha256(self.inp.access_policy),
                "discovery_snapshot_digest": self.discovery.snapshot_digest,
                "questions": ["q-reuse"],
                "invocations": [
                    {
                        "action_kind": "generated_experiment_skill",
                        "invocation_id": "generated-skill-reuse",
                        "skill_id": "successive_difference_summary",
                        "question_ids": ["q-reuse"],
                        "bindings": [
                            {
                                "binding_id": "custom-values",
                                "slot_id": "values",
                                "asset_id": "dataset",
                                "requested_format_id": "siderius.numeric-array.v1",
                                "requested_information": [
                                    {"information_class": "data", "fields": []}
                                ],
                            }
                        ],
                        "sampling_plan": {
                            "split_id": "validation",
                            "requested_scope": scope,
                            "policy": {
                                "mode": "fixed",
                                "max_items": 4,
                                "strategy": "uniform",
                                "seed": 11,
                            },
                        },
                        "arguments": {},
                        "expected_time_cost": "cheap",
                        "expected_memory_cost": "low",
                    }
                ],
                "stop_policy": {"max_invocations": 1},
                "rationale": "Execute the promoted skill without regenerating source.",
            }
        if label == "data_analysis.synthesis":
            return {
                "executive_summary": "The promoted local skill reproduced the measurement.",
                "findings": [
                    {
                        "finding_id": "finding-reused-difference",
                        "result_id": f"{self.inp.request_id}.generated-skill-reuse.result",
                        "statement": "The mean absolute successive difference remains 1.0.",
                        "quantitative_result_ids": ["mean_absolute_successive_difference"],
                        "confidence_level": "high",
                        "confidence_rationale": "The exact promoted content completed.",
                        "confidence_limitations": [],
                        "modeling_relevance": "Adjacent variation remains stable.",
                    }
                ],
                "question_outcomes": [
                    {
                        "question_id": "q-reuse",
                        "status": "addressed",
                        "summary": "The promoted operation was reused.",
                        "finding_ids": ["finding-reused-difference"],
                    }
                ],
                "limitations": [],
                "unresolved_questions": [],
                "modeling_relevance": ["Exact local capability reuse was measured."],
            }
        raise AssertionError(label)


def _input(tmp_path: Path) -> DataAnalysisInput:
    scope = ArtifactIntrinsicScope(split_id="validation", description="Validation data")
    asset = AnalysisAsset(
        asset_id="dataset",
        asset_type="dataset",
        description="Four numeric validation examples",
        location=WorkspaceArtifactLocation(
            artifact_ref=CertifiedArtifactRef(
                logical_ref="task-owned-dataset",
                sha256="8" * 64,
                media_type="application/x-task-data",
            )
        ),
        provenance=AssetProvenance(producer="test-task"),
        authorized_scope=scope,
        split_id="validation",
    )
    return DataAnalysisInput(
        request_id="request",
        task_context={
            "task_id": "generic-regression",
            "scientific_goal": "Characterize selected values.",
            "task_description": "A generic supervised scientific task.",
            "input_description": "Scalar numeric observations.",
            "metric_summary": "Lower error is better.",
            "forward_contract": ForwardContract(),
        },
        analysis_brief={
            "brief_id": "brief",
            "questions": [
                {
                    "question_id": "q-summary",
                    "question": "Compute summary statistics for the numeric values.",
                }
            ],
            "source": "human",
            "source_ref": "test",
        },
        available_assets=(asset,),
        declared_scope={"raw_input_asset_ids": ["dataset"]},
        access_policy={
            "policy_id": "policy",
            "policy_version": 1,
            "purpose": "Authorized summary analysis",
            "split_rules": [{"split_id": "validation", "data_visible": True}],
        },
        resource_envelope={
            "wall_time_budget_s": 15,
            "per_skill_timeout_s": 5,
            "preferred_device": "cpu",
        },
        allowed_skill_packs=builtin_pack_refs("core-analysis"),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="standalone"),
        ),
        caller={"caller_id": "human-test", "caller_type": "human"},
    )


@pytest.mark.allow_real_subprocess
def test_standalone_agent_runs_typed_pipeline_and_persists_bounded_report(tmp_path: Path) -> None:
    analysis_input = _input(tmp_path)
    agent = DataAnalysisAgent(
        task_analysis_capability=_Capability(),
        bridge_factory=lambda **kwargs: _Bridge(analysis_input=analysis_input, **kwargs),
        provider="test",
        model_id="fake",
    )

    report = agent.run(analysis_input)

    persisted_input = json.loads(
        (tmp_path / "data_analysis" / "standalone" / "request" / "input.json").read_text()
    )
    assert "generated_skill_registry" not in persisted_input
    assert "allow_generated_skill_promotion" not in persisted_input
    assert report.findings[0].statement.endswith("mean 2.5.")
    assert report.findings[0].coverage.analyzed_count == 4
    assert report.skill_result_summaries[0].execution_origin == "reference_skill"
    assert report.assets_inspected == ("dataset",)
    root = tmp_path / "data_analysis" / "standalone" / "request"
    assert (root / "input.json").is_file()
    assert (root / "discovery.json").is_file()
    assert (root / "plan.json").is_file()
    assert (root / "skill_results.jsonl").is_file()
    assert (root / "report.json").is_file()
    assert (root / "report.md").is_file()
    rendered_report = (root / "report.md").read_text()
    assert "## Certified measurements" in rendered_report
    assert "mean: 2.5" in rendered_report
    assert not (root / "staging" / "summary-invocation").exists()
    assert not (root / "materializations" / "summary-invocation").exists()

    report_bytes = (root / "report.json").read_bytes()
    assert "generated_skill_registry" not in json.loads(report_bytes)["provenance"]
    evidence = build_proposer_data_analysis_evidence(
        report,
        report_ref=CertifiedArtifactRef(
            logical_ref="data_analysis/standalone/request/report.json",
            sha256=hashlib.sha256(report_bytes).hexdigest(),
            media_type="application/json",
            byte_size=len(report_bytes),
        ),
    )
    assert evidence.findings[0].quantitative_evidence[0].result_key == "mean"
    rendered = render_data_analysis_evidence(evidence)
    assert "## Data Analysis Evidence" in rendered
    assert "mean 2.5" in rendered
    assert render_data_analysis_evidence(None) == ""
    proposal_input = local_typed_evidence(
        report,
        report_ref=evidence.report_ref,
        proposal_input=ProposalInput(interpretation_evidence=build_proposer_evidence({})),
    )
    assert proposal_input.data_analysis_evidence == evidence

    resumed = agent.run(analysis_input)
    assert resumed == report
    assert len((root / "skill_results.jsonl").read_text().splitlines()) == 1

    with pytest.raises(AnalysisPersistenceError, match="different canonical input"):
        agent.run(analysis_input.model_copy(update={"human_advice": "Changed request semantics"}))


@pytest.mark.allow_real_subprocess
def test_certified_scope_reference_reaches_authorization_as_exact_opaque_scope(
    tmp_path: Path,
) -> None:
    class ScopeRefBridge(_Bridge):
        def generate(self, system, user, *, label):
            payload = super().generate(system, user, label=label)
            if label == "data_analysis.plan":
                payload["invocations"][0]["sampling_plan"]["requested_scope"] = {
                    "kind": "certified_asset_scope",
                    "asset_id": "dataset",
                }
            return payload

    serialized_scope = '{"scientific_selection":"validation-two"}'
    opaque = TaskOpaqueScopeRef(
        task_data_path_id="synthetic-task",
        serialized_scope=serialized_scope,
        sha256=hashlib.sha256(serialized_scope.encode()).hexdigest(),
    )
    original = _input(tmp_path)
    inp = original.model_copy(
        update={
            "available_assets": (
                original.available_assets[0].model_copy(update={"authorized_scope": opaque}),
            )
        }
    )
    capability = _RecordingCapability()
    report = DataAnalysisAgent(
        task_analysis_capability=capability,
        bridge_factory=lambda **kwargs: ScopeRefBridge(analysis_input=inp, **kwargs),
        provider="test",
        model_id="fake",
    ).run(inp)
    assert capability.requested_scopes == [opaque]
    assert report.analysis_scope == (opaque,)
    assert report.findings[0].scope == opaque


@pytest.mark.allow_real_subprocess
def test_generated_program_is_persisted_before_plan_and_certified_as_evidence(
    tmp_path: Path,
) -> None:
    """Catches execution-time generation or generated source bypassing result certification."""

    capability = AnalysisCodeSandbox().probe()
    if not capability.available:
        pytest.skip(f"host cannot enforce sandbox: {capability.reason}")

    analysis_input = _input(tmp_path)
    bridge = _GeneratedProgramBridge(analysis_input=analysis_input)
    agent = DataAnalysisAgent(
        task_analysis_capability=_Capability(),
        bridge_factory=lambda **_kwargs: bridge,
        provider="test",
        model_id="fake",
    )

    report = agent.run(analysis_input)

    assert bridge.calls == [
        "data_analysis.skill_selection",
        "data_analysis.generated_program",
        "data_analysis.plan",
        "data_analysis.synthesis",
    ]
    root = tmp_path / "data_analysis" / "standalone" / "request"
    plan = json.loads((root / "plan.json").read_text())
    invocation = plan["invocations"][0]
    assert invocation["action_kind"] == "generated_program"
    assert "source_code" not in invocation
    assert list((root / "generated_analysis" / "sources").glob("*.py"))
    assert list((root / "generated_analysis" / "programs").glob("*/*.json"))
    summary = report.skill_result_summaries[0]
    assert summary.execution_origin == "generated_program"
    assert summary.generated_program_id == "successive-difference"
    assert summary.key_quantitative_results[0].value == 1.0
    assert report.findings[0].method_generated_program_ids == ("successive-difference",)
    assert report.findings[0].method_skill_ids == ()
    report_bytes = (root / "report.json").read_bytes()
    proposer_evidence = build_proposer_data_analysis_evidence(
        report,
        report_ref=CertifiedArtifactRef(
            logical_ref="data_analysis/standalone/request/report.json",
            sha256=hashlib.sha256(report_bytes).hexdigest(),
            media_type="application/json",
            byte_size=len(report_bytes),
        ),
    )
    assert proposer_evidence.findings[0].method_generated_program_ids == ("successive-difference",)
    assert "generated_program:successive-difference" in render_data_analysis_evidence(
        proposer_evidence
    )

    resumed = agent.run(analysis_input)
    assert resumed == report
    assert bridge.calls == [
        "data_analysis.skill_selection",
        "data_analysis.generated_program",
        "data_analysis.plan",
        "data_analysis.synthesis",
    ]


@pytest.mark.allow_real_subprocess
def test_plan_resolution_retries_generated_question_mismatch_without_widening(
    tmp_path: Path,
) -> None:
    probe = AnalysisCodeSandbox().probe()
    if not probe.available:
        pytest.skip(f"host cannot enforce sandbox: {probe.reason}")

    class ResolutionRetryBridge(_GeneratedProgramBridge):
        def generate(self, system, user, *, label):
            payload = super().generate(system, user, label=label)
            if label in {"data_analysis.plan", "data_analysis.plan.resolution_retry"}:
                payload["questions"].append("q-extra")
            if label == "data_analysis.plan":
                payload["invocations"][0]["question_ids"].append("q-extra")
            if label == "data_analysis.plan.resolution_retry":
                assert "generated invocation questions exceed its persisted declaration" in user
            if label == "data_analysis.synthesis":
                payload["question_outcomes"].append(
                    {
                        "question_id": "q-extra",
                        "status": "unresolved",
                        "summary": "This question was not measured.",
                        "finding_ids": [],
                    }
                )
            return payload

    base = _input(tmp_path)
    input_payload = base.model_dump(mode="python")
    input_payload["analysis_brief"]["questions"] = [
        *input_payload["analysis_brief"]["questions"],
        {"question_id": "q-extra", "question": "Describe another possible analysis."},
    ]
    analysis_input = DataAnalysisInput.model_validate(input_payload)
    bridge = ResolutionRetryBridge(analysis_input=analysis_input)
    capability = _RecordingCapability()
    report = DataAnalysisAgent(
        task_analysis_capability=capability,
        bridge_factory=lambda **_kwargs: bridge,
        provider="test",
        model_id="fake",
    ).run(analysis_input)

    root = tmp_path / "data_analysis" / "standalone" / "request"
    plan = json.loads((root / "plan.json").read_text())
    assert plan["invocations"][0]["question_ids"] == ["q-summary"]
    assert report.skill_result_summaries[0].status == "completed"
    assert len(capability.requested_scopes) == 1
    assert bridge.calls.count("data_analysis.plan.resolution_retry") == 1
    receipts = [
        json.loads(line)
        for line in (root / "structured_output_receipts.jsonl").read_text().splitlines()
    ]
    assert [r["stage"] for r in receipts if r["stage"].startswith("data_analysis.plan")] == [
        "data_analysis.plan",
        "data_analysis.plan.resolution_retry",
    ]


@pytest.mark.allow_real_subprocess
def test_plan_resolution_retry_still_rejects_invalid_second_plan(tmp_path: Path) -> None:
    class AlwaysInvalidPlanBridge(_Bridge):
        def generate(self, system, user, *, label):
            if label in {"data_analysis.plan", "data_analysis.plan.resolution_retry"}:
                payload = super().generate(system, user, label="data_analysis.plan")
                payload["questions"].append("q-extra")
                return payload
            return super().generate(system, user, label=label)

    analysis_input = _input(tmp_path)
    agent = DataAnalysisAgent(
        task_analysis_capability=_Capability(),
        bridge_factory=lambda **kwargs: AlwaysInvalidPlanBridge(
            analysis_input=analysis_input, **kwargs
        ),
        provider="test",
        model_id="fake",
    )
    with pytest.raises(AnalysisPlanResolutionError, match="exactly match the analysis brief"):
        agent.run(analysis_input)
    root = tmp_path / "data_analysis" / "standalone" / "request"
    assert not (root / "plan.json").exists()
    assert not (root / "skill_results.jsonl").exists()


@pytest.mark.allow_real_subprocess
def test_generated_python_json_literal_gets_one_audited_repair_before_persistence(
    tmp_path: Path,
) -> None:
    probe = AnalysisCodeSandbox().probe()
    if not probe.available:
        pytest.skip(f"host cannot enforce sandbox: {probe.reason}")

    class JsonLiteralBridge(_GeneratedProgramBridge):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.initial_draft = None

        def generate(self, system, user, *, label):
            if label == "data_analysis.generated_program.repair":
                self.calls.append(label)
                assert self.initial_draft is not None
                repaired = copy.deepcopy(self.initial_draft)
                repaired["source_code"] = repaired["source_code"].replace(
                    "'unit': null", "'unit': None"
                )
                return repaired
            draft = super().generate(system, user, label=label)
            if label == "data_analysis.generated_program":
                assert "source_code` is Python, not JSON" in system
                draft["source_code"] = draft["source_code"].replace("'unit': None", "'unit': null")
                self.initial_draft = copy.deepcopy(draft)
            return draft

    inp = _input(tmp_path)
    bridge = JsonLiteralBridge(analysis_input=inp)
    agent = DataAnalysisAgent(
        task_analysis_capability=_Capability(),
        bridge_factory=lambda **_kwargs: bridge,
        provider="test",
        model_id="fake",
    )
    report = agent.run(inp)
    assert report.skill_result_summaries[0].status == "completed"
    assert bridge.calls.count("data_analysis.generated_program.repair") == 1
    root = tmp_path / "data_analysis" / "standalone" / "request"
    persisted_source = next((root / "generated_analysis" / "sources").glob("*.py")).read_text()
    assert "'unit': None" in persisted_source
    assert "'unit': null" not in persisted_source
    receipts = [
        json.loads(line)
        for line in (root / "structured_output_receipts.jsonl").read_text().splitlines()
    ]
    generation = next(
        item for item in receipts if item["stage"] == "data_analysis.generated_program"
    )
    assert generation["initial_validation_passed"] is False
    assert generation["repair_attempted"] is True
    assert generation["repair_passed"] is True
    assert agent.run(inp) == report


@pytest.mark.allow_real_subprocess
def test_generated_program_promotes_then_reuses_exact_local_skill(tmp_path: Path) -> None:
    """Catches promotion regenerating code or routing a local skill through trusted execution."""

    capability = AnalysisCodeSandbox().probe()
    if not capability.available:
        pytest.skip(f"host cannot enforce sandbox: {capability.reason}")

    first_input = _input(tmp_path).model_copy(update={"allow_generated_skill_promotion": True})
    first_bridge = _PromotingGeneratedProgramBridge(analysis_input=first_input)
    first_report = DataAnalysisAgent(
        task_analysis_capability=_Capability(),
        bridge_factory=lambda **_kwargs: first_bridge,
        provider="test",
        model_id="fake",
    ).run(first_input)
    registry_ref = first_report.provenance.generated_skill_registry
    assert registry_ref is not None
    assert "data_analysis.generated_skill_promotion" in first_bridge.calls
    promotion_system, promotion_user = first_bridge.promotion_prompt
    assert "generic scientific operation" in promotion_system
    assert '"source_code"' in promotion_user
    assert "def analyze(inputs, parameters, output_directory):" in promotion_user

    second_payload = first_input.model_dump(mode="json")
    second_payload.update(
        request_id="request-reuse",
        analysis_brief={
            "brief_id": "brief-reuse",
            "questions": [
                {
                    "question_id": "q-reuse",
                    "question": "Repeat the same adjacent-variation measurement.",
                }
            ],
            "source": "human",
            "source_ref": "test",
        },
        generated_skill_registry=registry_ref.model_dump(mode="json"),
        allow_generated_skill_promotion=False,
    )
    second_input = DataAnalysisInput.model_validate(second_payload)
    second_bridge = _GeneratedSkillReuseBridge(analysis_input=second_input)
    second_report = DataAnalysisAgent(
        task_analysis_capability=_Capability(),
        bridge_factory=lambda **_kwargs: second_bridge,
        provider="test",
        model_id="fake",
    ).run(second_input)

    summary = second_report.skill_result_summaries[0]
    assert summary.execution_origin == "generated_experiment_skill"
    assert summary.skill_id == "successive_difference_summary"
    assert summary.generated_program_id is None
    assert second_report.findings[0].method_skill_ids == ("successive_difference_summary",)
    assert "data_analysis.generated_program" not in second_bridge.calls
    assert second_report.provenance.generated_skill_registry == registry_ref


@pytest.mark.allow_real_subprocess
def test_generated_program_cannot_claim_an_artifact_it_did_not_write(tmp_path: Path) -> None:
    """Catches untrusted artifact declarations being treated as certified files."""

    capability = AnalysisCodeSandbox().probe()
    if not capability.available:
        pytest.skip(f"host cannot enforce sandbox: {capability.reason}")

    analysis_input = _input(tmp_path)
    bridge = _MissingGeneratedArtifactBridge(analysis_input=analysis_input)
    report = DataAnalysisAgent(
        task_analysis_capability=_Capability(),
        bridge_factory=lambda **_kwargs: bridge,
        provider="test",
        model_id="fake",
    ).run(analysis_input)

    summary = report.skill_result_summaries[0]
    assert summary.status == "failed"
    assert report.findings == ()
    root = tmp_path / "data_analysis" / "standalone" / "request"
    result = json.loads((root / "skill_results.jsonl").read_text())
    assert result["failure"]["failure_type"] == "generated_payload_certification"
    assert "is missing relative to output_directory" in result["failure"]["message"]


@pytest.mark.allow_real_subprocess
def test_one_schema_repair_preserves_selection_and_persists_receipt(tmp_path: Path) -> None:
    """Catches malformed JSON semantics bypassing validation or repair becoming replanning."""

    analysis_input = _input(tmp_path)
    bridge = _RepairingBridge(analysis_input=analysis_input)
    report = DataAnalysisAgent(
        task_analysis_capability=_Capability(),
        bridge_factory=lambda **_kwargs: bridge,
        provider="test",
        model_id="fake",
    ).run(analysis_input)

    assert report.skill_result_summaries[0].skill_id == "summary_statistics"
    assert [label for label, _user in bridge.calls] == [
        "data_analysis.skill_selection",
        "data_analysis.skill_selection.repair",
        "data_analysis.plan",
        "data_analysis.synthesis",
    ]
    selection_user = bridge.calls[0][1]
    authoritative_schema = json.dumps(_SkillSelection.model_json_schema(), sort_keys=True, indent=2)
    assert authoritative_schema in selection_user

    receipt_path = (
        tmp_path / "data_analysis" / "standalone" / "request" / "structured_output_receipts.jsonl"
    )
    receipts = [json.loads(line) for line in receipt_path.read_text().splitlines()]
    assert len(receipts) == 3
    assert receipts[0]["stage"] == "data_analysis.skill_selection"
    assert receipts[0]["initial_validation_passed"] is False
    assert receipts[0]["repair_attempted"] is True
    assert receipts[0]["repair_passed"] is True
    assert receipts[0]["llm_call_count"] == 2
    assert receipts[0]["validation_errors"][0]["path"] == "rationale"
    assert receipts[1]["initial_validation_passed"] is True
    assert receipts[2]["initial_validation_passed"] is True


def test_schema_repair_cannot_change_recoverable_skill_selection(tmp_path: Path) -> None:
    """Catches a representation repair silently becoming a second planning round."""

    analysis_input = _input(tmp_path)
    bridge = _RepairingBridge(analysis_input=analysis_input, change_decision=True)
    with pytest.raises(DataAnalysisStructuredOutputError, match="changed the recoverable"):
        DataAnalysisAgent(
            task_analysis_capability=_Capability(),
            bridge_factory=lambda **_kwargs: bridge,
            provider="test",
            model_id="fake",
        ).run(analysis_input)

    root = tmp_path / "data_analysis" / "standalone" / "request"
    assert not (root / "plan.json").exists()
    receipt = json.loads((root / "structured_output_receipts.jsonl").read_text())
    assert receipt["repair_passed"] is False
    assert receipt["repair_validation_errors"][0]["error_type"] == ("semantic_decision_changed")


@pytest.mark.allow_real_subprocess
def test_plan_repair_may_only_delete_illegal_nonmetadata_fields(tmp_path: Path) -> None:
    """Catches the TIDMAD incident where harmless field deletion was called replanning."""

    analysis_input = _input(tmp_path)
    bridge = _PlanRepairingBridge(analysis_input=analysis_input)
    report = DataAnalysisAgent(
        task_analysis_capability=_Capability(),
        bridge_factory=lambda **_kwargs: bridge,
        provider="test",
        model_id="fake",
    ).run(analysis_input)

    assert report.skill_result_summaries[0].skill_id == "summary_statistics"
    plan_system_rule = (
        "RequestedInformation.fields is conditional: use explicit names only when information_class is\n"
        '"metadata".'
    )
    assert plan_system_rule in bridge.system_prompts["data_analysis.plan"]
    plan_prompt = bridge.system_prompts["data_analysis.plan"]
    assert (
        "requested_information must include the selected slot's required_information" in plan_prompt
    )
    assert (
        "may add only information declared by that same slot's optional_information" in plan_prompt
    )
    assert "that does not make target valid for a data-only slot" in plan_prompt
    assert "Use a declared target-capable slot if the question needs target evidence" in plan_prompt
    assert 'determinism="deterministic" must omit seed' in plan_prompt

    receipt_path = (
        tmp_path / "data_analysis" / "standalone" / "request" / "structured_output_receipts.jsonl"
    )
    receipts = [json.loads(line) for line in receipt_path.read_text().splitlines()]
    plan_receipt = next(item for item in receipts if item["stage"] == "data_analysis.plan")
    assert plan_receipt["initial_validation_passed"] is False
    assert plan_receipt["validation_errors"][0]["path"].endswith("requested_information.0")
    assert plan_receipt["repair_attempted"] is True
    assert plan_receipt["repair_passed"] is True
    assert plan_receipt["llm_call_count"] == 2


def test_plan_repair_may_drop_only_a_forbidden_deterministic_inference_seed() -> None:
    """The real round-2 seed error is representational, not permission to replan."""

    original = {
        "invocations": [
            {
                "invocation_id": "measure-prior-model",
                "bindings": [
                    {
                        "asset_id": "trained-model-a",
                        "information_class": "prediction",
                        "inference_configuration": {
                            "batch_size": 8,
                            "device": "cpu",
                            "determinism": "deterministic",
                            "seed": 0,
                        },
                    }
                ],
            }
        ]
    }
    repaired = copy.deepcopy(original)
    del repaired["invocations"][0]["bindings"][0]["inference_configuration"]["seed"]
    assert DataAnalysisAgent._plan_semantics(original) == DataAnalysisAgent._plan_semantics(
        repaired
    )

    changed = copy.deepcopy(repaired)
    changed["invocations"][0]["bindings"][0]["inference_configuration"]["determinism"] = (
        "stochastic_seeded"
    )
    changed["invocations"][0]["bindings"][0]["inference_configuration"]["seed"] = 0
    assert DataAnalysisAgent._plan_semantics(original) != DataAnalysisAgent._plan_semantics(changed)

    changed = copy.deepcopy(repaired)
    changed["invocations"][0]["bindings"][0]["inference_configuration"]["batch_size"] = 16
    assert DataAnalysisAgent._plan_semantics(original) != DataAnalysisAgent._plan_semantics(changed)

    parameter_change = copy.deepcopy(repaired)
    parameter_change["invocations"][0]["arguments"] = {
        "inference_configuration": {"determinism": "deterministic", "seed": 0}
    }
    without_parameter_seed = copy.deepcopy(parameter_change)
    del without_parameter_seed["invocations"][0]["arguments"]["inference_configuration"]["seed"]
    assert DataAnalysisAgent._plan_semantics(parameter_change) != DataAnalysisAgent._plan_semantics(
        without_parameter_seed
    )


@pytest.mark.parametrize(
    "repair_change",
    [
        "information_class",
        "metadata_field",
        "skill",
        "binding",
        "asset",
        "format",
        "sampling",
        "parameters",
        "priority",
        "stop_policy",
        "resource_intent",
    ],
)
def test_plan_repair_rejects_semantic_changes(tmp_path: Path, repair_change: str) -> None:
    """Catches one-shot schema repair gaining authority to alter executable plan semantics."""

    analysis_input = _input(tmp_path)
    bridge = _PlanRepairingBridge(
        analysis_input=analysis_input,
        repair_change=repair_change,
    )
    with pytest.raises(DataAnalysisStructuredOutputError, match="changed the recoverable"):
        DataAnalysisAgent(
            task_analysis_capability=_Capability(),
            bridge_factory=lambda **_kwargs: bridge,
            provider="test",
            model_id="fake",
        ).run(analysis_input)

    receipt_path = (
        tmp_path / "data_analysis" / "standalone" / "request" / "structured_output_receipts.jsonl"
    )
    receipts = [json.loads(line) for line in receipt_path.read_text().splitlines()]
    plan_receipt = next(item for item in receipts if item["stage"] == "data_analysis.plan")
    assert plan_receipt["repair_passed"] is False
    assert plan_receipt["repair_validation_errors"][0]["error_type"] == (
        "semantic_decision_changed"
    )


def test_output_retention_changes_standalone_identity_not_data_authority(tmp_path: Path) -> None:
    default = _input(tmp_path)
    retained = DataAnalysisInput.model_validate(
        {**default.model_dump(mode="python"), "retain_model_outputs": True}
    )

    assert default.retain_model_outputs is False
    assert canonical_sha256(default) != canonical_sha256(retained)
    assert retained.declared_scope == default.declared_scope
    assert retained.access_policy == default.access_policy


@pytest.mark.allow_real_subprocess
@pytest.mark.parametrize(
    "late_stage",
    [
        "data_analysis.skill_selection",
        "data_analysis.synthesis",
        "data_analysis.synthesis.grounding_retry",
    ],
)
def test_analysis_deadline_includes_llm_stages_and_refuses_late_report(
    tmp_path: Path, monkeypatch, late_stage: str
) -> None:
    """The skill budget used to reset after planning and omit final synthesis."""
    from core.execution_deadline import ExecutionDeadlineExceeded

    now = [0.0]
    monkeypatch.setattr("core.execution_deadline.time.monotonic", lambda: now[0])
    inp = _input(tmp_path)

    class SlowBridge(_Bridge):
        def generate(self, system, user, *, label):
            source_label = (
                "data_analysis.synthesis" if label.endswith(".grounding_retry") else label
            )
            result = super().generate(system, user, label=source_label)
            if late_stage.endswith(".grounding_retry") and label == "data_analysis.synthesis":
                result["findings"][0]["quantitative_result_ids"] = ["unknown"]
            now[0] += 16 if label == late_stage else 3
            return result

    agent = DataAnalysisAgent(
        task_analysis_capability=_Capability(),
        provider="test",
        model_id="fake",
        bridge_factory=lambda **kw: SlowBridge(analysis_input=inp, **kw),
    )
    with pytest.raises(ExecutionDeadlineExceeded, match=late_stage):
        agent.run(inp)
    root = tmp_path / "data_analysis/standalone/request"
    assert not (root / "report.json").exists()
    receipt = json.loads((root / "budget_receipt.json").read_text())
    assert receipt["status"] == "deadline_exceeded"
    assert receipt["last_boundary"] == late_stage
    assert receipt["elapsed_seconds"] > receipt["budget_seconds"]


def test_no_applicable_analysis_is_persisted_without_data_access_or_fake_findings(tmp_path):
    class NoReadCapability:
        def materialize_analysis_view(self, _request):
            raise AssertionError("non-execution must not materialize data")

        def export_analysis_materialization(self, *_args):
            raise AssertionError("non-execution must not export data")

    class DecliningBridge:
        calls = 0

        def generate(self, _system, _user, *, label):
            self.calls += 1
            assert label == "data_analysis.skill_selection"
            return {
                "skill_ids": [],
                "generated_program_question_ids": [],
                "rationale": "Questions require inaccessible evidence.",
                "non_execution_reason": "Targets are not available under this policy.",
            }

    bridge = DecliningBridge()
    inp = _input(tmp_path)
    agent = DataAnalysisAgent(
        task_analysis_capability=NoReadCapability(),
        bridge_factory=lambda **_kwargs: bridge,
    )
    report = agent.run(inp)
    assert report.findings == report.assets_inspected == report.skill_result_refs == ()
    assert report.resource_usage.attempted_invocations == 0
    assert all(q.status == "unresolved" for q in report.question_outcomes)
    assert report.limitations and report.unresolved_questions
    root = tmp_path / "data_analysis/standalone/request"
    plan = AnalysisPlan.model_validate_json((root / "plan.json").read_bytes())
    assert not plan.invocations and plan.non_execution_reason
    assert (root / "budget_receipt.json").is_file()
    assert agent.run(inp) == report
    assert bridge.calls == 1
    with pytest.raises(ValueError, match="explicit non-execution"):
        _SkillSelection(skill_ids=(), rationale="Empty without explanation")
    with pytest.raises(ValueError, match="cannot request"):
        _SkillSelection(
            skill_ids=("summary_statistics",),
            rationale="Contradiction",
            non_execution_reason="No work",
        )
    with pytest.raises(ValueError, match="requires an invocation"):
        AnalysisPlan.model_validate({**plan.model_dump(), "non_execution_reason": None})


def test_no_work_report_preserves_previously_certified_skill_registry(tmp_path):
    from agent.data_analysis.non_execution import build_non_execution_report
    from agent.data_analysis.persistence import AnalysisRunStore
    from agent.schemas.data_analysis.generated_skill import GeneratedExperimentSkillRegistryRef

    registry = GeneratedExperimentSkillRegistryRef(
        registry_id="prior-registry",
        registry_root=str(tmp_path / "prior-registry"),
        manifest_ref=CertifiedArtifactRef(
            logical_ref="registry.json", sha256="3" * 64, media_type="application/json"
        ),
        registry_sha256="4" * 64,
    )
    inp = _input(tmp_path).model_copy(update={"generated_skill_registry": registry})
    report = build_non_execution_report(
        inp=inp,
        store=AnalysisRunStore(inp.storage, request_id=inp.request_id),
        discovery_digest="5" * 64,
        reason="No additional applicable work",
    )
    assert report.provenance.generated_skill_registry == registry
    assert not report.findings and not report.assets_inspected


@pytest.mark.allow_real_subprocess
@pytest.mark.parametrize("retry_valid", [True, False])
def test_synthesis_grounding_retries_once_without_rerunning_skills(tmp_path, retry_valid):
    """Unknown measured keys must never publish; one corrected draft uses the same evidence."""
    analysis_input = _input(tmp_path)

    class GroundingBridge(_Bridge):
        def __init__(self):
            super().__init__(analysis_input=analysis_input)
            self.calls = []

        def generate(self, system, user, *, label):
            self.calls.append(label)
            if label in ("data_analysis.synthesis", "data_analysis.synthesis.grounding_retry"):
                draft = super().generate(system, user, label="data_analysis.synthesis")
                if label == "data_analysis.synthesis" or not retry_valid:
                    draft["findings"][0]["quantitative_result_ids"] = ["invented_mean"]
                else:
                    assert "invented_mean" in user and "allowed keys" in user
                return draft
            return super().generate(system, user, label=label)

    bridge = GroundingBridge()
    agent = DataAnalysisAgent(
        task_analysis_capability=_Capability(),
        bridge_factory=lambda **kwargs: bridge,
        provider="test",
    )
    root = tmp_path / "data_analysis" / "standalone" / "request"
    if retry_valid:
        report = agent.run(analysis_input)
        assert report.findings[0].evidence[0].quantitative_result_ids == ("mean", "finite_count")
    else:
        with pytest.raises(ValueError, match="evidence validation after one retry"):
            agent.run(analysis_input)
        assert not (root / "report.json").exists()
    assert bridge.calls.count("data_analysis.plan") == 1
    assert bridge.calls.count("data_analysis.synthesis.grounding_retry") == 1
    assert len((root / "skill_results.jsonl").read_text().splitlines()) == 1
    receipts = [
        json.loads(line)
        for line in (root / "synthesis_grounding_receipts.jsonl").read_text().splitlines()
    ]
    assert len(receipts) == 2
    assert "invented_mean" in receipts[0]["errors"][0]
    assert bool(receipts[1]["errors"]) is (not retry_valid)
    assert receipts[0]["draft"]["findings"][0]["quantitative_result_ids"] == ["invented_mean"]
