"""Optional typed workflow traversal for Interpreter -> Analysis -> Proposer."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from agent.data_analysis.generated_skill_registry import load_generated_skill_registry
from agent.data_analysis.persistence import AnalysisRunStore
from agent.data_analysis.source_scope import apply_source_prompt
from agent.schemas.data_analysis.common import CallerIdentity, CertifiedArtifactRef
from agent.schemas.data_analysis.generated_skill import GeneratedExperimentSkillRegistryRef
from agent.schemas.data_analysis.report import DataAnalysisReport
from agent.schemas.interpretation import InterpretationOutput
from agent.schemas.literature_review import LiteratureReviewOutput
from agent.schemas.proposal import ProposalInput
from agent.schemas.protocols.data_analysis_to_ml_model_propose import local_typed_evidence
from agent.schemas.protocols.interpreter_to_data_analysis import (
    MissingAnalysisBriefError,
    local_analysis_input,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from core.campaign_identity import validate_path_component
from execute_tools.historical_model_inference import (
    HistoricalModelInferenceCapability,
    LocalPytorchHistoricalModelInferenceCapability,
)
from ml_models.plugin_binding import active_run_model_plugins
from nodes.data_analysis_agent import DataAnalysisAgent
from workflows.data_analysis_composition import ResolvedWorkflowDataAnalysis
from workflows.historical_analysis_assets import (
    HistoricalTuningSource,
    derive_historical_analysis_assets,
)
from workflows.historical_inference_bindings import (
    RunBoundHistoricalArtifactExporter,
    RunBoundHistoricalModelPluginResolver,
)


@dataclass(frozen=True, slots=True)
class WorkflowAnalysisOutput:
    """The capability output plus the edge-certified persisted report identity."""

    report: DataAnalysisReport
    report_ref: CertifiedArtifactRef


def restore_prior_generated_skill_registry(
    *, workspace: Path, committed_iterations: tuple[int, ...]
) -> GeneratedExperimentSkillRegistryRef | None:
    """Restore the latest exact local toolbox from committed workflow output.

    This is a process-boundary resume adapter, not a node reading another
    node's storage as a communication channel. Only the caller-certified
    committed iteration list is examined; the registry itself remains
    content-addressed and confined to this chain workspace.
    """

    workspace = workspace.resolve()
    for iteration in reversed(committed_iterations):
        run_name = f"iter_{iteration:03d}"
        store = AnalysisRunStore(
            StorageConfig(
                backend="local",
                local=LocalStorageConfig(
                    workspace=str(workspace / run_name / f"iteration_{iteration:03d}"),
                    run_name=run_name,
                ),
            ),
            request_id=f"iteration-{iteration:03d}",
        )
        report_path = store.root / "report.json"
        if not report_path.exists():
            continue
        if (
            not report_path.is_file()
            or not report_path.resolve().is_relative_to(workspace)
            or any(
                part.is_symlink()
                for part in (report_path, *report_path.parents)
                if part != workspace and part.is_relative_to(workspace)
            )
        ):
            raise ValueError("prior Data Analysis report is not a regular file")
        report = DataAnalysisReport.model_validate_json(report_path.read_bytes())
        if report.report_id != f"iteration-{iteration:03d}.report":
            raise ValueError("prior Data Analysis report has the wrong iteration identity")
        ref = report.provenance.generated_skill_registry
        if ref is None:
            continue
        expected_root = store.generated_skill_registry_root
        if (
            expected_root.is_symlink()
            or not expected_root.resolve().is_relative_to(workspace)
            or Path(ref.registry_root).resolve() != expected_root.resolve()
        ):
            raise ValueError("prior generated skill registry escapes its committed iteration")
        load_generated_skill_registry(ref)
        return ref
    return None


def run_optional_data_analysis(
    interpretation: InterpretationOutput,
    *,
    binding: ResolvedWorkflowDataAnalysis | None,
    iteration: int,
    run_name: str,
    storage: StorageConfig,
    human_advice: str | None,
    source_prompt: str | None = None,
    retain_model_outputs: bool = False,
    llm_kwargs: dict,
    bridge_factory,
    historical_model_inference_capability: HistoricalModelInferenceCapability | None = None,
    historical_sources: tuple[HistoricalTuningSource, ...] = (),
    history_run_names: tuple[str, ...] = (),
    task_composition_fingerprint: str | None = None,
    chain_workspace: str | None = None,
    literature_output: LiteratureReviewOutput | None = None,
    generated_skill_registry: GeneratedExperimentSkillRegistryRef | None = None,
) -> WorkflowAnalysisOutput | None:
    """Run the independent capability only when the composition enables its edge.

    A missing brief is an explicit no-analysis disposition already recorded by
    the Interpreter's brief receipt.  This edge never invents replacement
    questions from prose.
    """

    if binding is None:
        return None
    # A failed Interpreter brief is already a typed no-analysis disposition.
    # Do not inspect historical artifacts merely because a workflow edge exists.
    if interpretation.analysis_brief is None:
        return None
    assert storage.local is not None
    if binding.historical_inference_base_asset_id is not None and historical_sources:
        if task_composition_fingerprint is None or chain_workspace is None:
            raise ValueError("historical analysis requires explicit workflow composition identity")
        derived = derive_historical_analysis_assets(
            binding,
            sources=historical_sources,
            task_composition_fingerprint=task_composition_fingerprint,
            workspace_root=Path(chain_workspace),
            history_run_names=history_run_names,
        )
        binding = derived.binding
        if derived.artifact_roots_by_sha256 and historical_model_inference_capability is None:
            from core.sandbox_executor import get_plugin_dir

            historical_model_inference_capability = LocalPytorchHistoricalModelInferenceCapability(
                workspace=Path(storage.local.workspace),
                artifact_exporter=RunBoundHistoricalArtifactExporter(
                    derived.artifact_roots_by_sha256
                ),
                plugin_resolver=RunBoundHistoricalModelPluginResolver(
                    declared_plugins=active_run_model_plugins(),
                    generated_plugin_dirs=tuple(
                        Path(
                            get_plugin_dir(
                                chain_workspace,
                                validate_path_component(
                                    source.output.run_name, kind="historical model run"
                                ),
                            )
                        )
                        for source in historical_sources
                    ),
                ),
            )
    request_id = f"iteration-{iteration:03d}"
    try:
        analysis_input = local_analysis_input(
            interpretation,
            request_id=request_id,
            task_context=binding.task_context,
            available_assets=binding.available_assets,
            declared_scope=binding.declared_scope,
            access_policy=binding.access_policy,
            resource_envelope=binding.resource_envelope,
            recovery_policy=binding.recovery_policy,
            allowed_skill_packs=binding.allowed_skill_packs,
            storage=storage,
            caller=CallerIdentity(
                caller_id=run_name,
                caller_type="workflow",
                request_source=f"iteration:{iteration}",
            ),
            human_advice=human_advice,
            allow_generated_skill_promotion=binding.allow_generated_skill_promotion,
            generated_skill_registry=generated_skill_registry,
            retain_model_outputs=retain_model_outputs,
        )
    except MissingAnalysisBriefError:
        return None
    if literature_output is not None:
        from agent.schemas.protocols.ml_literature_review_to_data_analysis import (
            attach_typed_evidence,
        )

        analysis_input = attach_typed_evidence(analysis_input, literature_output)

    analysis_input = apply_source_prompt(analysis_input, source_prompt)

    report = DataAnalysisAgent(
        task_analysis_capability=binding.task_analysis_capability,
        historical_model_inference_capability=historical_model_inference_capability,
        bridge_factory=bridge_factory,
        **llm_kwargs,
    ).run(analysis_input)
    relative = Path("data_analysis") / storage.local.run_name / request_id / "report.json"
    path = Path(storage.local.workspace) / relative
    payload = path.read_bytes()
    report_ref = CertifiedArtifactRef(
        logical_ref=str(relative),
        sha256=hashlib.sha256(payload).hexdigest(),
        media_type="application/json",
        byte_size=len(payload),
    )
    return WorkflowAnalysisOutput(report=report, report_ref=report_ref)


def attach_analysis_to_proposer(
    proposal_input: ProposalInput,
    analysis: WorkflowAnalysisOutput | None,
) -> ProposalInput:
    """Apply the Data Analysis -> Proposer edge without exposing report internals."""

    if analysis is None:
        return proposal_input
    return local_typed_evidence(
        analysis.report,
        report_ref=analysis.report_ref,
        proposal_input=proposal_input,
    )
