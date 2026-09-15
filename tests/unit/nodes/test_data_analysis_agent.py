from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np
import pytest

from agent.data_analysis.discovery import discover_skills
from agent.data_analysis.persistence import AnalysisPersistenceError
from agent.data_analysis.reference_packs import builtin_pack_refs
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
