"""Caller-independent Data Analysis Agent orchestration."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import model_validator

from agent.data_analysis.action_execution import execute_resolved_action
from agent.data_analysis.discovery import (
    DiscoveredAnalysisSkill,
    DiscoveredGeneratedExperimentSkill,
    discover_skills,
    search_skill_cards,
)
from agent.data_analysis.executor import resolve_skill_interface
from agent.data_analysis.generated_program_planning import prepare_generated_program
from agent.data_analysis.generated_programs import load_generated_program
from agent.data_analysis.generated_skill_registry import (
    import_generated_skill_registry_snapshot,
    load_generated_skill_registry,
    promote_generated_program,
)
from agent.data_analysis.persistence import AnalysisRunStore
from agent.data_analysis.plan_validation import resolve_analysis_plan
from agent.data_analysis.rendering import render_report_markdown
from agent.data_analysis.structured_output import generate_validated
from agent.llm_bridge import LLMBridge
from agent.prompt_templates.data_analysis import (
    render_analysis_plan_prompt,
    render_generated_skill_promotion_prompt,
    render_report_synthesis_prompt,
    render_skill_selection_prompt,
)
from agent.schemas.data_analysis.common import FrozenModel, NonEmptyStr, canonical_sha256, utc_now
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.generated_skill import (
    GeneratedExperimentSkillRegistryRef,
    GeneratedSkillPromotionDraft,
)
from agent.schemas.data_analysis.plan import AnalysisPlan, PlannedGeneratedProgramInvocation
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
from agent.schemas.data_analysis.skills import SkillResult
from execute_tools.analysis_materialization import TaskAnalysisCapability
from execute_tools.historical_model_inference import HistoricalModelInferenceCapability


class _SkillSelection(FrozenModel):
    skill_ids: tuple[NonEmptyStr, ...] = ()
    generated_program_question_ids: tuple[NonEmptyStr, ...] = ()
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def validate_ids(self):
        if len(set(self.skill_ids)) != len(self.skill_ids):
            raise ValueError("selected skill IDs must be unique")
        if len(set(self.generated_program_question_ids)) != len(
            self.generated_program_question_ids
        ):
            raise ValueError("generated-program question IDs must be unique")
        if not self.skill_ids and not self.generated_program_question_ids:
            raise ValueError("selection requires a skill or generated program")
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


class _GeneratedSkillPromotionDecision(FrozenModel):
    promotions: tuple[GeneratedSkillPromotionDraft, ...] = ()
    rationale: NonEmptyStr

    @model_validator(mode="after")
    def validate_promotions(self):
        program_ids = [item.program_id for item in self.promotions]
        skill_ids = [item.skill_id for item in self.promotions]
        if len(set(program_ids)) != len(program_ids):
            raise ValueError("a generated program may be promoted at most once")
        if len(set(skill_ids)) != len(skill_ids):
            raise ValueError("promoted generated skill IDs must be unique")
        return self


class DataAnalysisAgent:
    """Plan, execute and synthesize authorized scientific analysis skills."""

    def __init__(
        self,
        *,
        task_analysis_capability: TaskAnalysisCapability,
        provider: str = "gemini",
        model_id: str | None = None,
        max_retries: int | None = None,
        reasoning_effort: str | None = None,
        bridge_factory: Callable[..., object] | None = None,
        historical_model_inference_capability: HistoricalModelInferenceCapability | None = None,
    ) -> None:
        self._capability = task_analysis_capability
        self._provider = provider
        self._model_id = model_id
        self._max_retries = max_retries
        self._reasoning_effort = reasoning_effort
        self._bridge_factory = bridge_factory or LLMBridge
        self._historical_inference_capability = historical_model_inference_capability

    def _bridge(self):
        kwargs = {"provider": self._provider, "model_id": self._model_id}
        if self._max_retries is not None:
            kwargs["max_retries"] = self._max_retries
        if self._reasoning_effort is not None:
            kwargs["reasoning_effort"] = self._reasoning_effort
        return self._bridge_factory(**kwargs)

    @staticmethod
    def _selection_semantics(value: object) -> object | None:
        if not isinstance(value, dict):
            return None
        skill_ids = value.get("skill_ids")
        generated_question_ids = value.get("generated_program_question_ids", [])
        if (
            not isinstance(skill_ids, list)
            or not all(isinstance(item, str) and item.strip() for item in skill_ids)
            or len(set(skill_ids)) != len(skill_ids)
            or not isinstance(generated_question_ids, list)
            or not all(isinstance(item, str) and item.strip() for item in generated_question_ids)
            or len(set(generated_question_ids)) != len(generated_question_ids)
            or (not skill_ids and not generated_question_ids)
        ):
            return None
        return (tuple(skill_ids), tuple(generated_question_ids))

    @staticmethod
    def _plan_semantics(value: object) -> object | None:
        if not isinstance(value, dict) or not isinstance(value.get("invocations"), list):
            return None

        def without_non_authoritative_fields(item: object, *, path: tuple[str, ...] = ()) -> object:
            if isinstance(item, dict):
                information_class = item.get("information_class")
                return {
                    key: without_non_authoritative_fields(child, path=(*path, key))
                    for key, child in item.items()
                    if not (
                        key == "fields"
                        and information_class
                        in {"identity", "data", "target", "prediction", "residual"}
                    )
                    and not (
                        path
                        == (
                            "invocations",
                            "[]",
                            "bindings",
                            "[]",
                            "inference_configuration",
                        )
                        and key == "seed"
                        and item.get("determinism", "deterministic") == "deterministic"
                    )
                }
            if isinstance(item, list):
                return [
                    without_non_authoritative_fields(child, path=(*path, "[]")) for child in item
                ]
            return item

        return {
            key: without_non_authoritative_fields(item, path=(key,))
            for key, item in value.items()
            if key != "rationale"
        }

    @staticmethod
    def _synthesis_semantics(value: object) -> object | None:
        if not isinstance(value, dict) or not isinstance(value.get("question_outcomes"), list):
            return None

        def without_rationales(item: object) -> object:
            if isinstance(item, dict):
                return {
                    key: without_rationales(child)
                    for key, child in item.items()
                    if key != "confidence_rationale"
                }
            if isinstance(item, list):
                return [without_rationales(child) for child in item]
            return item

        return without_rationales(value)

    @staticmethod
    def _candidate_cards(inp: DataAnalysisInput, discovery) -> tuple[DiscoveredAnalysisSkill, ...]:
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
        discovery = discover_skills(
            inp.allowed_skill_packs,
            generated_skill_registry=inp.generated_skill_registry,
        )
        store.write_discovery(discovery)
        bridge = self._bridge()
        candidates = self._candidate_cards(inp, discovery)
        selection_system, selection_user = render_skill_selection_prompt(
            inp,
            candidates,
            output_schema=_SkillSelection.model_json_schema(),
        )
        selection = generate_validated(
            bridge,
            store=store,
            model_type=_SkillSelection,
            system=selection_system,
            user=selection_user,
            label="data_analysis.skill_selection",
            semantic_projection=self._selection_semantics,
        )
        candidate_by_id = {item.card.skill_id: item for item in candidates}
        try:
            selected = tuple(candidate_by_id[skill_id] for skill_id in selection.skill_ids)
        except KeyError as exc:
            raise ValueError(
                f"planner selected unavailable candidate skill {exc.args[0]!r}"
            ) from exc

        available_question_ids = {item.question_id for item in inp.analysis_brief.questions}
        if not set(selection.generated_program_question_ids).issubset(available_question_ids):
            raise ValueError("planner requested generated code for an unknown question")
        generated_programs = ()
        if selection.generated_program_question_ids:
            generated_programs = (
                prepare_generated_program(
                    bridge=bridge,
                    store=store,
                    analysis_input=inp,
                    question_ids=selection.generated_program_question_ids,
                    provider=self._provider,
                    requested_model_id=self._model_id,
                    llm_config={
                        "provider": self._provider,
                        "model_id": self._model_id,
                        "max_retries": self._max_retries,
                    },
                ),
            )

        control_root = store.root / "control"
        control_root.mkdir(parents=True, exist_ok=True)
        interfaces = {
            skill.card.skill_id: (
                skill.resolved_interface
                if isinstance(skill, DiscoveredGeneratedExperimentSkill)
                else resolve_skill_interface(
                    skill,
                    control_directory=control_root / f"interface-{skill.card.skill_id}",
                    timeout_s=inp.resource_envelope.per_skill_timeout_s,
                    max_host_memory_gb=inp.resource_envelope.max_host_memory_gb,
                )
            )
            for skill in selected
        }
        plan_system, plan_user = render_analysis_plan_prompt(
            inp,
            discovery,
            selected,
            interfaces,
            generated_programs=generated_programs,
        )
        plan = generate_validated(
            bridge,
            store=store,
            model_type=AnalysisPlan,
            system=plan_system,
            user=plan_user,
            label="data_analysis.plan",
            semantic_projection=self._plan_semantics,
        )
        planned_generated_identities = {
            canonical_sha256(item.program_identity)
            for item in plan.invocations
            if isinstance(item, PlannedGeneratedProgramInvocation)
        }
        prepared_generated_identities = {
            canonical_sha256(identity) for _program, identity in generated_programs
        }
        if planned_generated_identities != prepared_generated_identities:
            raise ValueError(
                "final AnalysisPlan must reference exactly the generated programs prepared "
                "during its two-stage lifecycle"
            )
        resolved = resolve_analysis_plan(
            plan,
            analysis_input=inp,
            discovery=discovery,
            resolved_interfaces=interfaces,
            control_root=control_root,
            generated_program_root=store.root,
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
            outcome = execute_resolved_action(
                item=item,
                inp=inp,
                plan=plan,
                store=store,
                task_capability=self._capability,
                inference_capability=self._historical_inference_capability,
                control_root=control_root,
                deadline_monotonic_s=deadline,
            )
            for receipt in outcome.inference_receipts:
                store.append_inference_receipt(receipt)
            inspected_assets.update(outcome.inspected_asset_ids)
            result = outcome.result
            result_ref = store.append_skill_result(result)
            results.append(result)
            result_refs.append(result_ref)
            invocation_by_result[result.result_id] = item.invocation
            if result.status != "completed" and not plan.stop_policy.continue_after_skill_failure:
                break

        generated_skill_registry = self._promote_generated_skills(
            bridge,
            inp=inp,
            store=store,
            generated_programs=generated_programs,
            results=tuple(results),
        )
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
            store=store,
            generated_skill_registry=generated_skill_registry,
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
        store,
        generated_skill_registry,
    ) -> DataAnalysisReport:
        system, user = render_report_synthesis_prompt(
            inp,
            results,
            output_schema=_ReportSynthesis.model_json_schema(),
        )
        draft = generate_validated(
            bridge,
            store=store,
            model_type=_ReportSynthesis,
            system=system,
            user=user,
            label="data_analysis.synthesis",
            semantic_projection=DataAnalysisAgent._synthesis_semantics,
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
                    method_skill_ids=(
                        (result.skill_identity.skill_id,)
                        if result.skill_identity is not None
                        else ()
                    ),
                    method_generated_program_ids=(
                        (result.generated_program_identity.program_id,)
                        if result.generated_program_identity is not None
                        else ()
                    ),
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
                execution_origin=result.execution_origin,
                skill_id=(
                    result.skill_identity.skill_id if result.skill_identity is not None else None
                ),
                generated_program_id=(
                    result.generated_program_identity.program_id
                    if result.generated_program_identity is not None
                    else None
                ),
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
            source_scope=inp.effective_source_scope(),
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
                generated_skill_registry=generated_skill_registry,
            ),
        )

    @staticmethod
    def _promotion_semantics(value: object) -> object | None:
        if not isinstance(value, dict) or not isinstance(value.get("promotions", []), list):
            return None
        return value.get("promotions", [])

    @staticmethod
    def _promote_generated_skills(
        bridge,
        *,
        inp: DataAnalysisInput,
        store: AnalysisRunStore,
        generated_programs,
        results: tuple[SkillResult, ...],
    ) -> GeneratedExperimentSkillRegistryRef | None:
        current_ref = inp.generated_skill_registry
        if not inp.allow_generated_skill_promotion:
            return current_ref
        completed = {
            result.generated_program_identity.program_id: result
            for result in results
            if result.status == "completed" and result.generated_program_identity is not None
        }
        programs = {
            program.program_id: (program, identity) for program, identity in generated_programs
        }
        # Large sources remain valid one-off programs, but cannot be reviewed
        # in full by this bounded promotion stage. Never promote from a
        # truncated source preview.
        max_review_source_bytes = 24 * 1024
        promotable = sorted(
            program_id
            for program_id in set(completed) & set(programs)
            if programs[program_id][0].source_ref.byte_size is not None
            and programs[program_id][0].source_ref.byte_size <= max_review_source_bytes
        )
        if not promotable:
            return current_ref
        reviewed_sources = {}
        for program_id in promotable:
            program, identity = programs[program_id]
            persisted, source_path = load_generated_program(root=store.root, identity=identity)
            if persisted != program:
                raise ValueError("promotion source differs from its immutable declaration")
            reviewed_sources[program_id] = source_path.read_text(encoding="utf-8")
        system, user = render_generated_skill_promotion_prompt(
            inp,
            completed_programs=[
                {
                    "program_id": program_id,
                    "program_identity": programs[program_id][1].model_dump(mode="json"),
                    "declaration": programs[program_id][0].model_dump(
                        mode="json", exclude={"generation_provenance"}
                    ),
                    "source_code": reviewed_sources[program_id],
                    "summary": completed[program_id].summary,
                    "quantitative_result_keys": [
                        item.result_key for item in completed[program_id].quantitative_results
                    ],
                }
                for program_id in promotable
            ],
            output_schema=_GeneratedSkillPromotionDecision.model_json_schema(),
        )
        decision = generate_validated(
            bridge,
            store=store,
            model_type=_GeneratedSkillPromotionDecision,
            system=system,
            user=user,
            label="data_analysis.generated_skill_promotion",
            semantic_projection=DataAnalysisAgent._promotion_semantics,
        )
        if not decision.promotions:
            return current_ref
        if not {item.program_id for item in decision.promotions}.issubset(promotable):
            raise ValueError("promotion decision references a non-completed generated program")
        registry_root = store.generated_skill_registry_root
        if current_ref is None:
            existing = None
        elif Path(current_ref.registry_root).resolve() == registry_root.resolve():
            existing = load_generated_skill_registry(current_ref)
        else:
            existing = import_generated_skill_registry_snapshot(
                current_ref, destination_root=registry_root
            )
        registry_id = (
            existing.registry_id
            if existing is not None
            else f"generated-skills-{canonical_sha256({'run_name': inp.storage.local.run_name})}"
        )
        updated_ref = current_ref
        for draft in decision.promotions:
            program, identity = programs[draft.program_id]
            existing, updated_ref = promote_generated_program(
                source_root=store.root,
                registry_root=registry_root,
                registry_id=registry_id,
                existing=existing,
                program=program,
                program_identity=identity,
                draft=draft,
                originating_request_id=inp.request_id,
                originating_result_id=completed[draft.program_id].result_id,
            )
        return updated_ref
