"""Typed, independently composable Literature Review / Data Analysis edges."""

import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent.prompt_templates.data_analysis import render_skill_selection_prompt
from agent.prompt_templates.proposal import (
    render_data_analysis_evidence,
    render_literature_review_evidence,
)
from agent.schemas.data_analysis.common import CertifiedArtifactRef, canonical_sha256
from agent.schemas.data_analysis.report import DataAnalysisReport
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.parameter_rules import ParameterRules
from agent.schemas.proposal import AgentCard, ExpertContextItem, ProposalInput
from agent.schemas.proposer_evidence import build_proposer_evidence
from agent.schemas.protocols.data_analysis_to_ml_literature_review import (
    local_typed_evidence as analysis_to_literature,
)
from agent.schemas.protocols.data_analysis_to_ml_model_propose import (
    local_typed_evidence as analysis_to_proposer,
)
from agent.schemas.protocols.interpreter_to_ml_literature_review import (
    local_typed_evidence as interpretation_to_literature,
)
from agent.schemas.protocols.ml_literature_review_to_data_analysis import (
    attach_typed_evidence as attach_literature_to_analysis,
)
from agent.schemas.protocols.ml_literature_review_to_data_analysis import (
    local_typed_evidence as literature_to_analysis,
)
from agent.schemas.protocols.ml_literature_review_to_ml_model_propose import (
    local_typed_evidence as literature_to_proposer,
)
from core.run_invariants import (
    RunInvariants,
    RunInvariantsViolation,
    validate_run_invariants,
    write_run_invariants,
)
from tests.unit.nodes.test_data_analysis_agent import _input
from workflows.scientific_evidence_stage import run_scientific_evidence_stage


def test_literature_contracts_do_not_import_data_analysis_private_schemas() -> None:
    """The Lit and Proposer-owned carriers must not depend on DA internals."""

    schema_root = Path(__file__).resolve().parents[4] / "src" / "agent" / "schemas"
    for name in ("literature_review.py", "proposer_literature_evidence.py"):
        tree = ast.parse((schema_root / name).read_text(encoding="utf-8"))
        imports = (
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert not any(module.startswith("agent.schemas.data_analysis") for module in imports)


def _interpretation() -> InterpretationOutput:
    return InterpretationOutput(
        model_types=["baseline"],
        model_descriptions={"baseline": "not projected"},
        total_experiments=1,
        key_findings=["Residual power is concentrated near 12 Hz."],
        bottlenecks=["A narrowband residual remains."],
        take_home_message="Investigate narrowband representations.",
    )


def _literature() -> LiteratureReviewOutput:
    return LiteratureReviewOutput(
        agent_card=AgentCard(
            agent_name="ml_literature_review",
            role="Find relevant methods.",
            expertise_domain="Scientific machine learning literature.",
            coverage="Configured scholarly sources.",
            limitations="External claims require empirical validation.",
            trust_level="soft_prior",
            trust_guidance="Use as hypotheses, not observed facts.",
        ),
        findings=[
            ExpertContextItem(
                source="ml_literature_review",
                kind="literature",
                content="Spectral losses can emphasize localized residual frequencies.",
                source_ref="doi:10.0000/example",
                confidence=0.8,
            )
        ],
        retrieved_papers=[],
        run_name="review-1",
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:01:00Z",
    )


def _report() -> DataAnalysisReport:
    result_ref = {
        "result_id": "result-1",
        "logical_ref": "results/result-1.json",
        "sha256": "1" * 64,
    }
    coverage = {
        "population_unit": "examples",
        "total_available": 10,
        "analyzed_count": 5,
        "binding_ids": ["signal"],
        "selection_sha256": "2" * 64,
        "split_id": "validation",
        "sampling_strategy": "uniform",
    }
    return DataAnalysisReport.model_validate(
        {
            "report_id": "report-1",
            "analysis_attempt_id": "attempt-1",
            "input_digest": "3" * 64,
            "plan_ref": {
                "logical_ref": "plan.json",
                "sha256": "4" * 64,
                "media_type": "application/json",
            },
            "analysis_scope": [
                {
                    "kind": "artifact_intrinsic",
                    "split_id": "validation",
                    "description": "Validation subset",
                }
            ],
            "executive_summary": "A narrowband residual remains near 12 Hz.",
            "question_outcomes": [
                {
                    "question_id": "q1",
                    "status": "addressed",
                    "summary": "Residual structure measured.",
                    "finding_ids": ["finding-1"],
                }
            ],
            "assets_inspected": ["residuals"],
            "findings": [
                {
                    "finding_id": "finding-1",
                    "statement": "Residual power peaks near 12 Hz.",
                    "evidence": [
                        {
                            "result_ref": result_ref,
                            "quantitative_result_ids": ["peak_hz"],
                        }
                    ],
                    "confidence": {"level": "high", "rationale": "Measured peak."},
                    "scope": {
                        "kind": "artifact_intrinsic",
                        "split_id": "validation",
                        "description": "Validation subset",
                    },
                    "method_skill_ids": ["residual_spectrum"],
                    "coverage": coverage,
                    "modeling_relevance": "Motivates checking frequency-aware methods.",
                }
            ],
            "skill_result_summaries": [
                {
                    "result_ref": result_ref,
                    "execution_origin": "reference_skill",
                    "skill_id": "residual_spectrum",
                    "status": "completed",
                    "summary": "Peak measured.",
                    "coverage": coverage,
                    "key_quantitative_results": [
                        {
                            "result_key": "peak_hz",
                            "value": 12.0,
                            "unit": "Hz",
                            "description": "Dominant residual frequency.",
                        }
                    ],
                }
            ],
            "skill_result_refs": [result_ref],
            "resource_usage": {
                "attempted_invocations": 1,
                "completed_invocations": 1,
                "total_wall_time_s": 0.1,
            },
            "provenance": {
                "input_digest": "3" * 64,
                "access_policy_digest": "5" * 64,
                "plan_digest": "6" * 64,
                "discovery_snapshot_digest": "7" * 64,
                "skill_result_set_digest": "8" * 64,
                "generated_at": "2026-01-01T00:00:00Z",
            },
        }
    )


def test_target_owned_projections_are_bounded_and_distinct() -> None:
    interpretation = interpretation_to_literature(_interpretation())
    assert interpretation.model_types == ("baseline",)
    assert not hasattr(interpretation, "model_descriptions")

    measured = analysis_to_literature(_report())
    assert measured.findings[0].measurements[0].value == 12.0
    assert measured.findings[0].measurements[0].unit == "Hz"

    literature = literature_to_analysis(_literature())
    assert literature.findings[0].source_ref == "doi:10.0000/example"
    assert not hasattr(literature, "access_policy")

    proposal = literature_to_proposer(
        _literature(),
        proposal_input=ProposalInput(interpretation_evidence=build_proposer_evidence({})),
    )
    assert proposal.literature_review_evidence is not None
    assert proposal.literature_review_evidence.findings[0].source_ref == "doi:10.0000/example"
    assert proposal.data_analysis_evidence is None


def test_literature_context_changes_reasoning_surface_without_changing_authority(
    tmp_path,
) -> None:
    """Catches a workflow edge accidentally broadening assets or access policy."""

    base = _input(tmp_path)
    authority_before = canonical_sha256(
        {
            "assets": [item.model_dump(mode="json") for item in base.available_assets],
            "policy": base.access_policy.model_dump(mode="json"),
            "packs": [item.model_dump(mode="json") for item in base.allowed_skill_packs],
        }
    )
    attached = attach_literature_to_analysis(base, _literature())
    authority_after = canonical_sha256(
        {
            "assets": [item.model_dump(mode="json") for item in attached.available_assets],
            "policy": attached.access_policy.model_dump(mode="json"),
            "packs": [item.model_dump(mode="json") for item in attached.allowed_skill_packs],
        }
    )

    assert authority_after == authority_before
    assert attached.literature_evidence is not None
    _, user = render_skill_selection_prompt(attached, (), output_schema={})
    assert "doi:10.0000/example" in user
    assert "reasoning context only; no authorization" in user


def test_proposer_renders_observed_and_external_evidence_as_separate_streams() -> None:
    proposal = ProposalInput(interpretation_evidence=build_proposer_evidence({}))
    proposal = literature_to_proposer(_literature(), proposal_input=proposal)
    proposal = analysis_to_proposer(
        _report(),
        report_ref=CertifiedArtifactRef(
            logical_ref="data_analysis/report.json",
            sha256="9" * 64,
            media_type="application/json",
        ),
        proposal_input=proposal,
    )

    observed = render_data_analysis_evidence(proposal.data_analysis_evidence)
    external = render_literature_review_evidence(proposal.literature_review_evidence)
    assert "## Data Analysis Evidence" in observed
    assert "Residual power peaks near 12 Hz" in observed
    assert "## Machine Learning Literature Review Evidence" in external
    assert "doi:10.0000/example" in external
    assert "external claims, not observations from our data" in external


def test_proposer_fan_in_preserves_exact_workflow_rule_after_both_edges() -> None:
    """Catches the real TIDMAD incident where nested rule nulls blocked ProposalInput."""
    rules = ParameterRules.model_validate({"model_config.segmentation_size": {"exact": 40_000}})
    proposal = ProposalInput(
        interpretation_evidence=build_proposer_evidence({}),
        workflow_parameter_rules=rules,
    )

    proposal = literature_to_proposer(_literature(), proposal_input=proposal)
    proposal = analysis_to_proposer(
        _report(),
        report_ref=CertifiedArtifactRef(
            logical_ref="data_analysis/report.json",
            sha256="9" * 64,
            media_type="application/json",
        ),
        proposal_input=proposal,
    )

    assert proposal.workflow_parameter_rules == rules
    assert proposal.literature_review_evidence is not None
    assert proposal.data_analysis_evidence is not None


def test_literature_edge_projections_refuse_unbounded_prompt_payloads(tmp_path) -> None:
    """Catches a large review bypassing the target-owned prompt-size boundary."""

    base = _literature()
    oversized = base.model_copy(update={"findings": tuple(base.findings) * 33})
    with pytest.raises(ValidationError, match="at most 32 items"):
        attach_literature_to_analysis(_input(tmp_path), oversized)
    with pytest.raises(ValidationError, match="at most 32 items"):
        literature_to_proposer(
            oversized,
            proposal_input=ProposalInput(interpretation_evidence=build_proposer_evidence({})),
        )

    verbose = base.model_copy(update={"findings": tuple(base.findings) * 10})
    verbose_findings = [
        finding.model_copy(update={"content": "Grounded method: " + "x" * 6990})
        for finding in verbose.findings
    ]
    verbose = verbose.model_copy(update={"findings": verbose_findings})
    with pytest.raises(ValidationError, match="65536-byte reasoning limit"):
        attach_literature_to_analysis(_input(tmp_path), verbose)
    with pytest.raises(ValidationError, match="65536-byte proposer limit"):
        literature_to_proposer(
            verbose,
            proposal_input=ProposalInput(interpretation_evidence=build_proposer_evidence({})),
        )


def test_workflow_order_is_explicit_and_nodes_remain_independent() -> None:
    trace: list[str] = []

    def analysis(literature):
        trace.append(f"analysis:{literature}")
        return "analysis-output"

    def literature(analysis_output):
        trace.append(f"literature:{analysis_output}")
        return "literature-output"

    first = run_scientific_evidence_stage(
        order="analysis_then_literature",
        run_analysis=analysis,
        run_literature=literature,
    )
    assert trace == ["analysis:None", "literature:analysis-output"]
    assert first.analysis_output == "analysis-output"

    trace.clear()
    second = run_scientific_evidence_stage(
        order="literature_then_analysis",
        run_analysis=analysis,
        run_literature=literature,
    )
    assert trace == ["literature:None", "analysis:literature-output"]
    assert second.literature_output == "literature-output"


def test_external_orchestrator_can_request_one_explicit_analysis_revisit() -> None:
    """Catches a revisit becoming recursive or hidden inside either node."""

    trace: list[str] = []

    def analysis(literature):
        trace.append("analysis:first" if literature is None else "analysis:revisit")
        return f"analysis-{len(trace)}"

    def literature(analysis_output):
        trace.append(f"literature:after:{analysis_output}")
        return "literature-output"

    first = run_scientific_evidence_stage(
        order="analysis_then_literature",
        run_analysis=analysis,
        run_literature=literature,
    )
    revisit = analysis(first.literature_output)

    assert trace == [
        "analysis:first",
        "literature:after:analysis-1",
        "analysis:revisit",
    ]
    assert revisit == "analysis-3"


def test_order_is_canonical_resume_identity(tmp_path) -> None:
    base = RunInvariants(
        resolved_data_scope=[0],
        health_gate_enabled=False,
        health_config_sha256=None,
        runtime_estimator_identity="estimator-v1",
        runtime_policy_identity="policy-v1",
    )
    write_run_invariants(str(tmp_path), base)
    validate_run_invariants(str(tmp_path), base)
    changed = base.model_copy(update={"scientific_evidence_order": "literature_then_analysis"})
    with pytest.raises(RunInvariantsViolation, match="scientific_evidence_order"):
        validate_run_invariants(str(tmp_path), changed)
