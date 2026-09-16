from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pytest

from agent.data_analysis.discovery import discover_skills
from agent.data_analysis.persistence import AnalysisPersistenceError
from agent.data_analysis.reference_packs import builtin_pack_refs
from agent.data_analysis.structured_output import DataAnalysisStructuredOutputError
from agent.prompt_templates.proposal import render_data_analysis_evidence
from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    ArtifactIntrinsicScope,
    AssetProvenance,
    MaterializedAnalysisView,
    WorkspaceArtifactLocation,
)
from agent.schemas.data_analysis.common import CertifiedArtifactRef, canonical_sha256
from agent.schemas.data_analysis.context import DataAnalysisInput
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


class _Bridge:
    def __init__(self, *, analysis_input: DataAnalysisInput, **_kwargs) -> None:
        self.inp = analysis_input
        self.discovery = discover_skills(analysis_input.allowed_skill_packs)

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
            assert "counts must sum exactly to `dropped_count`" in system
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
        if label == "data_analysis.plan":
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
    assert not (root / "staging" / "summary-invocation").exists()
    assert not (root / "materializations" / "summary-invocation").exists()

    report_bytes = (root / "report.json").read_bytes()
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
def test_generated_program_is_persisted_before_plan_and_certified_as_evidence(
    tmp_path: Path,
) -> None:
    """Catches execution-time generation or generated source bypassing result certification."""

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
def test_generated_program_cannot_claim_an_artifact_it_did_not_write(tmp_path: Path) -> None:
    """Catches untrusted artifact declarations being treated as certified files."""

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
    assert "missing or escapes staging" in result["failure"]["message"]


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
