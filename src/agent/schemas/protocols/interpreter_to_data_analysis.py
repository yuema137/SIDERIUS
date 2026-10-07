"""Typed reference-workflow adapter from Interpreter to Data Analysis."""

from __future__ import annotations

from agent.schemas.data_analysis.access import AnalysisAccessPolicy
from agent.schemas.data_analysis.assets import AnalysisAsset
from agent.schemas.data_analysis.common import CallerIdentity
from agent.schemas.data_analysis.context import (
    AnalysisTaskContext,
    DataAnalysisInput,
    PriorEvidenceRef,
    SkillPackRef,
)
from agent.schemas.data_analysis.generated_skill import GeneratedExperimentSkillRegistryRef
from agent.schemas.data_analysis.recovery import AnalysisRecoveryPolicy
from agent.schemas.data_analysis.resources import AnalysisResourceEnvelope
from agent.schemas.data_analysis.source_scope import DeclaredAnalysisScope
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.storage import StorageConfig


class MissingAnalysisBriefError(ValueError):
    """Analysis was requested but the Interpreter produced no validated brief."""


def local_analysis_input(
    interpretation: InterpretationOutput,
    *,
    request_id: str,
    task_context: AnalysisTaskContext,
    available_assets: tuple[AnalysisAsset, ...],
    declared_scope: DeclaredAnalysisScope,
    access_policy: AnalysisAccessPolicy,
    resource_envelope: AnalysisResourceEnvelope,
    allowed_skill_packs: tuple[SkillPackRef, ...],
    storage: StorageConfig,
    caller: CallerIdentity,
    prior_evidence: tuple[PriorEvidenceRef, ...] = (),
    generated_skill_registry: GeneratedExperimentSkillRegistryRef | None = None,
    human_advice: str | None = None,
    allow_generated_skill_promotion: bool = False,
    retain_model_outputs: bool = False,
    recovery_policy: AnalysisRecoveryPolicy | None = None,
) -> DataAnalysisInput:
    """Combine an Interpreter-owned brief with caller-owned run authorities.

    The adapter never derives questions from free-form interpretation prose,
    searches for assets, or expands visibility beyond ``access_policy``.
    """

    if interpretation.analysis_brief is None:
        raise MissingAnalysisBriefError(
            "analysis was requested but InterpretationOutput has no validated AnalysisBrief"
        )
    return DataAnalysisInput(
        request_id=request_id,
        task_context=task_context,
        analysis_brief=interpretation.analysis_brief,
        available_assets=available_assets,
        declared_scope=declared_scope,
        prior_evidence=prior_evidence,
        generated_skill_registry=generated_skill_registry,
        access_policy=access_policy,
        resource_envelope=resource_envelope,
        recovery_policy=recovery_policy,
        allowed_skill_packs=allowed_skill_packs,
        human_advice=human_advice,
        storage=storage,
        caller=caller,
        allow_generated_skill_promotion=allow_generated_skill_promotion,
        retain_model_outputs=retain_model_outputs,
    )
