"""Caller-independent Data Analysis Agent orchestration."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Literal

from pydantic import model_validator

from agent.data_analysis.discovery import DiscoveredSkill, discover_skills, search_skill_cards
from agent.data_analysis.executor import execute_skill, resolve_skill_interface
from agent.data_analysis.historical_inference import HistoricalInferenceError
from agent.data_analysis.invocation_materialization import prepare_invocation_materializations
from agent.data_analysis.materialization import (
    AnalysisMaterializationError,
)
from agent.data_analysis.persistence import AnalysisRunStore
from agent.data_analysis.plan_validation import resolve_analysis_plan
from agent.data_analysis.rendering import render_report_markdown
from agent.llm_bridge import LLMBridge
from agent.prompt_templates.data_analysis import (
    render_analysis_plan_prompt,
    render_report_synthesis_prompt,
    render_skill_selection_prompt,
)
from agent.schemas.data_analysis.common import FrozenModel, NonEmptyStr, canonical_sha256, utc_now
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.plan import AnalysisPlan
from agent.schemas.data_analysis.report import (
    AnalysisResourceSummary,
    CertifiedResultRef,
    ConfidenceAssessment,
    DataAnalysisReport,
    DataAnalysisReportProvenance,
    DataFinding,
    EvidencePointer,
    QuestionOutcome,
    ReportLimitation,
    SkillResultSummary,
)
from agent.schemas.data_analysis.resources import ResourceUsage
from agent.schemas.data_analysis.skills import (
    ArtifactOutputContract,
    SkillExecutionProvenance,
    SkillFailure,
    SkillInput,
    SkillResult,
)
from execute_tools.analysis_materialization import (
    AnalysisAuthorizationError,
    TaskAnalysisCapability,
)
from execute_tools.historical_model_inference import HistoricalModelInferenceCapability


class _SkillSelection(FrozenModel):
    skill_ids: tuple[NonEmptyStr, ...]
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def validate_ids(self):
        if not self.skill_ids or len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("selected skill IDs must be non-empty and unique")
        return self


class _FindingDraft(FrozenModel):
    finding_id: NonEmptyStr
    result_id: NonEmptyStr
    statement: NonEmptyStr
    quantitative_result_ids: tuple[NonEmptyStr, ...] = ()
    confidence_level: Literal["low", "medium", "high"]
    confidence_rationale: NonEmptyStr
    confidence_limitations: tuple[NonEmptyStr, ...] = ()
    modeling_relevance: NonEmptyStr


class _QuestionOutcomeDraft(FrozenModel):
    question_id: NonEmptyStr
    status: Literal["addressed", "partially_addressed", "unresolved", "refused"]
    summary: NonEmptyStr
    finding_ids: tuple[NonEmptyStr, ...] = ()
    limitation_ids: tuple[NonEmptyStr, ...] = ()


class _LimitationDraft(FrozenModel):
    limitation_id: NonEmptyStr
    statement: NonEmptyStr
    affected_question_ids: tuple[NonEmptyStr, ...] = ()


class _ReportSynthesis(FrozenModel):
    executive_summary: NonEmptyStr
    findings: tuple[_FindingDraft, ...] = ()
    question_outcomes: tuple[_QuestionOutcomeDraft, ...]
    limitations: tuple[_LimitationDraft, ...] = ()
    unresolved_questions: tuple[NonEmptyStr, ...] = ()
    modeling_relevance: tuple[NonEmptyStr, ...] = ()


class DataAnalysisAgent:
    """Plan, execute and synthesize authorized scientific analysis skills."""

    def __init__(
        self,
        *,
        task_analysis_capability: TaskAnalysisCapability,
        provider: str = "gemini",
        model_id: str | None = None,
        max_retries: int | None = None,
        bridge_factory: Callable[..., object] | None = None,
        historical_model_inference_capability: HistoricalModelInferenceCapability | None = None,
    ) -> None:
        self._capability = task_analysis_capability
        self._provider = provider
        self._model_id = model_id
        self._max_retries = max_retries
        self._bridge_factory = bridge_factory or LLMBridge
        self._historical_inference_capability = historical_model_inference_capability

    def _bridge(self):
        kwargs = {"provider": self._provider, "model_id": self._model_id}
        if self._max_retries is not None:
            kwargs["max_retries"] = self._max_retries
        return self._bridge_factory(**kwargs)

    @staticmethod
    def _pre_execution_result(
        *,
        inp: DataAnalysisInput,
        item,
        plan: AnalysisPlan,
        status: Literal["failed", "refused"],
        failure_type: str,
        message: str,
        materialization_occurred: bool,
        authorization_receipts=(),
        inference_receipts=(),
        started_at: str,
        started_monotonic: float,
    ) -> SkillResult:
        return SkillResult(
            result_id=f"{inp.request_id}.{item.invocation.invocation_id}.result",
            invocation_id=item.invocation.invocation_id,
            skill_identity=item.skill.identity,
            status=status,
            summary="Skill invocation could not reach bounded execution.",
            resource_usage=ResourceUsage(
                wall_time_s=max(0.0, time.monotonic() - started_monotonic),
                peak_rss_bytes=0,
                device="cpu",
                measurement_limitations=(
                    "No skill worker was launched; resource usage covers orchestration only.",
                ),
            ),
            failure=SkillFailure(
                failure_type=failure_type,
                message=message,
                materialization_occurred=materialization_occurred,
                refusal_code=failure_type if status == "refused" else None,
            ),
            provenance=SkillExecutionProvenance(
                plan_sha256=canonical_sha256(plan),
                parameter_schema_sha256=item.validated_parameters.parameter_schema_sha256,
                validated_parameters_sha256=(item.validated_parameters.validated_parameters_sha256),
                authorization_receipts=tuple(authorization_receipts),
                inference_receipts=tuple(inference_receipts),
                environment_lock_verified=False,
                started_at=started_at,
                finished_at=utc_now(),
                host_details={"supervisor_disposition": "worker_not_started"},
            ),
        )

    @staticmethod
    def _candidate_cards(inp: DataAnalysisInput, discovery) -> tuple[DiscoveredSkill, ...]:
        by_identity = {}
        for question in inp.analysis_brief.questions:
            query = " ".join(
                (
                    question.question,
                    *question.suspected_failure_modes,
                    *question.observations_to_verify,
                )
            )
            for skill in search_skill_cards(discovery, query, limit=8):
                by_identity[skill.card.skill_id] = skill
        # Natural-language wording can legitimately share no literal token with
        # a concise manifest.  Discovery must still expose the enabled cards to
        # the planner; an empty retrieval result must not make an installed
        # capability unreachable.  The shipped/reference inventory is bounded,
        # and only selected interfaces are imported in the next phase.
        if not by_identity:
            by_identity = {item.card.skill_id: item for item in discovery.skills}
        return tuple(by_identity[key] for key in sorted(by_identity))

    def run(self, inp: DataAnalysisInput) -> DataAnalysisReport:
        inp = DataAnalysisInput.model_validate(inp)
        store = AnalysisRunStore(inp.storage, request_id=inp.request_id)
        resumed = store.resume_completed_report(inp)
        if resumed is not None:
            return resumed
        store.write_input(inp)
        discovery = discover_skills(inp.allowed_skill_packs)
        store.write_discovery(discovery)
        bridge = self._bridge()
        candidates = self._candidate_cards(inp, discovery)
        selection_system, selection_user = render_skill_selection_prompt(inp, candidates)
        selection = _SkillSelection.model_validate(
            bridge.generate(selection_system, selection_user, label="data_analysis.skill_selection")
        )
        candidate_by_id = {item.card.skill_id: item for item in candidates}
        try:
            selected = tuple(candidate_by_id[skill_id] for skill_id in selection.skill_ids)
        except KeyError as exc:
            raise ValueError(
                f"planner selected unavailable candidate skill {exc.args[0]!r}"
            ) from exc

        control_root = store.root / "control"
        control_root.mkdir(parents=True, exist_ok=True)
        interfaces = {
            skill.card.skill_id: resolve_skill_interface(
                skill,
                control_directory=control_root / f"interface-{skill.card.skill_id}",
                timeout_s=inp.resource_envelope.per_skill_timeout_s,
                max_host_memory_gb=inp.resource_envelope.max_host_memory_gb,
            )
            for skill in selected
        }
        plan_system, plan_user = render_analysis_plan_prompt(inp, discovery, selected, interfaces)
        plan = AnalysisPlan.model_validate(
            bridge.generate(plan_system, plan_user, label="data_analysis.plan")
        )
        resolved = resolve_analysis_plan(
            plan,
            analysis_input=inp,
            discovery=discovery,
            resolved_interfaces=interfaces,
            control_root=control_root,
        )
        plan_ref = store.write_plan(plan)
        deadline = time.monotonic() + inp.resource_envelope.wall_time_budget_s
        results: list[SkillResult] = []
        result_refs: list[CertifiedResultRef] = []
        invocation_by_result = {}
        inspected_assets: set[str] = set()
        for item in resolved:
            if time.monotonic() + plan.stop_policy.minimum_remaining_time_s >= deadline:
                break
            started_at = utc_now()
            started_monotonic = time.monotonic()
            materialization_directory = (
                store.root / "materializations" / item.invocation.invocation_id
            )
            try:
                bundle = prepare_invocation_materializations(
                    invocation=item,
                    task_capability=self._capability,
                    inference_capability=self._historical_inference_capability,
                    available_assets={asset.asset_id: asset for asset in inp.available_assets},
                    access_policy=inp.access_policy,
                    resource_envelope=inp.resource_envelope,
                    deadline_monotonic_s=deadline,
                    destination_root=materialization_directory,
                )
                views = bundle.views
                materialization_paths = bundle.paths
                for receipt in bundle.inference_receipts:
                    store.append_inference_receipt(receipt)
            except AnalysisAuthorizationError as exc:
                result = self._pre_execution_result(
                    inp=inp,
                    item=item,
                    plan=plan,
                    status="refused",
                    failure_type=exc.refusal.code,
                    message=exc.refusal.message,
                    materialization_occurred=False,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                )
                result_refs.append(store.append_skill_result(result))
                results.append(result)
                invocation_by_result[result.result_id] = item.invocation
                if not plan.stop_policy.continue_after_skill_failure:
                    break
                continue
            except AnalysisMaterializationError as exc:
                store.cleanup_materializations(materialization_directory)
                result = self._pre_execution_result(
                    inp=inp,
                    item=item,
                    plan=plan,
                    status="failed",
                    failure_type="materialization_contract",
                    message=str(exc),
                    materialization_occurred=True,
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                )
                result_refs.append(store.append_skill_result(result))
                results.append(result)
                invocation_by_result[result.result_id] = item.invocation
                if not plan.stop_policy.continue_after_skill_failure:
                    break
                continue
            except HistoricalInferenceError as exc:
                store.cleanup_materializations(materialization_directory)
                if exc.receipt is not None:
                    store.append_inference_receipt(exc.receipt)
                result = self._pre_execution_result(
                    inp=inp,
                    item=item,
                    plan=plan,
                    status="refused" if exc.refused else "failed",
                    failure_type=(
                        "historical_inference_capability_unavailable"
                        if exc.refused
                        else "historical_inference_failed"
                    ),
                    message=str(exc),
                    materialization_occurred=not exc.refused,
                    inference_receipts=(exc.receipt,) if exc.receipt is not None else (),
                    started_at=started_at,
                    started_monotonic=started_monotonic,
                )
                result_refs.append(store.append_skill_result(result))
                results.append(result)
                invocation_by_result[result.result_id] = item.invocation
                if not plan.stop_policy.continue_after_skill_failure:
                    break
                continue
            inspected_assets.update(bundle.inspected_asset_ids)
            artifact_contract = ArtifactOutputContract(
                output_directory_ref=f"staging/{item.invocation.invocation_id}",
                allowed_media_types=("application/json", "image/png", "text/csv"),
            )
            skill_input = SkillInput(
                invocation_id=item.invocation.invocation_id,
                skill_identity=item.skill.identity,
                materializations=views,
                question_ids=item.invocation.question_ids,
                deadline_monotonic_s=deadline,
                artifact_output_contract=artifact_contract,
            )
            staging = store.staging_directory(item.invocation.invocation_id)
            try:
                result = execute_skill(
                    result_id=f"{inp.request_id}.{item.invocation.invocation_id}.result",
                    skill=item.skill,
                    validated_parameters=item.validated_parameters,
                    skill_input=skill_input,
                    materialization_paths=materialization_paths,
                    store=store,
                    staging_directory=staging,
                    control_directory=control_root / f"execute-{item.invocation.invocation_id}",
                    plan_sha256=canonical_sha256(plan),
                    timeout_s=min(
                        inp.resource_envelope.per_skill_timeout_s,
                        max(0.0, deadline - time.monotonic()),
                    ),
                    max_host_memory_gb=inp.resource_envelope.max_host_memory_gb,
                    pre_execution_resource_usage=tuple(
                        receipt.resource_usage for receipt in bundle.inference_receipts
                    ),
                )
            finally:
                store.cleanup_staging(staging)
                store.cleanup_materializations(materialization_directory)
            result_ref = store.append_skill_result(result)
            results.append(result)
            result_refs.append(result_ref)
            invocation_by_result[result.result_id] = item.invocation

        report = self._synthesize_report(
            bridge,
            inp=inp,
            plan=plan,
            plan_ref=plan_ref,
            discovery_digest=discovery.snapshot_digest,
            results=tuple(results),
            result_refs=tuple(result_refs),
            invocation_by_result=invocation_by_result,
            inspected_assets=inspected_assets,
        )
        store.write_report(report, markdown=render_report_markdown(report))
        return report

    @staticmethod
    def _synthesize_report(
        bridge,
        *,
        inp,
        plan,
        plan_ref,
        discovery_digest,
        results,
        result_refs,
        invocation_by_result,
        inspected_assets,
    ) -> DataAnalysisReport:
        system, user = render_report_synthesis_prompt(inp, results)
        draft = _ReportSynthesis.model_validate(
            bridge.generate(system, user, label="data_analysis.synthesis")
        )
        result_by_id = {item.result_id: item for item in results}
        ref_by_id = {item.result_id: item for item in result_refs}
        findings = []
        for item in draft.findings:
            result = result_by_id.get(item.result_id)
            if result is None or result.status != "completed" or result.coverage is None:
                raise ValueError("finding references a non-completed or unknown SkillResult")
            quantitative_ids = {value.result_key for value in result.quantitative_results}
            if not set(item.quantitative_result_ids).issubset(quantitative_ids):
                raise ValueError("finding cites unknown quantitative result IDs")
            invocation = invocation_by_result[item.result_id]
            findings.append(
                DataFinding(
                    finding_id=item.finding_id,
                    statement=item.statement,
                    evidence=(
                        EvidencePointer(
                            result_ref=ref_by_id[item.result_id],
                            quantitative_result_ids=item.quantitative_result_ids,
                            artifact_refs=result.artifact_refs,
                        ),
                    ),
                    confidence=ConfidenceAssessment(
                        level=item.confidence_level,
                        rationale=item.confidence_rationale,
                        limitations=item.confidence_limitations,
                    ),
                    scope=invocation.sampling_plan.requested_scope,
                    method_skill_ids=(result.skill_identity.skill_id,),
                    coverage=result.coverage,
                    modeling_relevance=item.modeling_relevance,
                )
            )
        question_ids = {question.question_id for question in inp.analysis_brief.questions}
        if {item.question_id for item in draft.question_outcomes} != question_ids:
            raise ValueError("report synthesis must address every AnalysisBrief question exactly")
        finding_ids = {item.finding_id for item in findings}
        outcomes = tuple(
            QuestionOutcome(
                question_id=item.question_id,
                status=item.status,
                summary=item.summary,
                finding_ids=item.finding_ids,
                limitation_ids=item.limitation_ids,
            )
            for item in draft.question_outcomes
        )
        if any(not set(item.finding_ids).issubset(finding_ids) for item in outcomes):
            raise ValueError("question outcome cites an unknown finding")
        limitations = tuple(
            ReportLimitation(
                limitation_id=item.limitation_id,
                statement=item.statement,
                affected_question_ids=item.affected_question_ids,
            )
            for item in draft.limitations
        )
        summaries = tuple(
            SkillResultSummary(
                result_ref=ref_by_id[result.result_id],
                skill_id=result.skill_identity.skill_id,
                status=result.status,
                summary=result.summary,
                coverage=result.coverage,
                key_quantitative_results=result.quantitative_results[:32],
                warning_count=len(result.warnings),
            )
            for result in results
        )
        scopes = []
        scope_digests = set()
        for invocation in invocation_by_result.values():
            scope = invocation.sampling_plan.requested_scope
            digest = canonical_sha256(scope)
            if digest not in scope_digests:
                scopes.append(scope)
                scope_digests.add(digest)
        usage = AnalysisResourceSummary(
            attempted_invocations=len(results),
            completed_invocations=sum(item.status == "completed" for item in results),
            total_wall_time_s=sum(item.resource_usage.wall_time_s for item in results),
            maximum_peak_rss_bytes=max(
                (item.resource_usage.peak_rss_bytes or 0 for item in results), default=0
            ),
            maximum_peak_vram_bytes=max(
                (item.resource_usage.peak_vram_bytes or 0 for item in results), default=0
            ),
            measurement_limitations=tuple(
                sorted(
                    {
                        limitation
                        for item in results
                        for limitation in item.resource_usage.measurement_limitations
                    }
                )
            ),
        )
        return DataAnalysisReport(
            report_id=f"{inp.request_id}.report",
            analysis_attempt_id=inp.request_id,
            input_digest=canonical_sha256(inp),
            plan_ref=plan_ref,
            analysis_scope=tuple(scopes),
            executive_summary=draft.executive_summary,
            question_outcomes=outcomes,
            assets_inspected=tuple(sorted(inspected_assets)),
            findings=tuple(findings),
            skill_result_summaries=summaries,
            skill_result_refs=result_refs,
            artifacts=tuple(artifact for result in results for artifact in result.artifact_refs),
            modeling_relevance=draft.modeling_relevance,
            limitations=limitations,
            unresolved_questions=draft.unresolved_questions,
            resource_usage=usage,
            provenance=DataAnalysisReportProvenance(
                input_digest=canonical_sha256(inp),
                access_policy_digest=canonical_sha256(inp.access_policy),
                plan_digest=canonical_sha256(plan),
                discovery_snapshot_digest=discovery_digest,
                skill_result_set_digest=canonical_sha256(
                    [item.model_dump(mode="json") for item in result_refs]
                ),
                generated_at=utc_now(),
            ),
        )
