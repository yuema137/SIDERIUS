"""Contract regressions for immutable one-off generated analysis actions."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError

from agent.data_analysis.generated_programs import (
    GeneratedProgramDraft,
    load_generated_program,
    persist_generated_program,
)
from agent.data_analysis.persistence import AnalysisPersistenceError, AnalysisRunStore
from agent.prompt_templates.data_analysis import render_generated_program_prompt
from agent.schemas.data_analysis.access import InformationRequirement
from agent.schemas.data_analysis.action_identity import (
    GeneratedProgramGenerationProvenance,
)
from agent.schemas.data_analysis.assets import ArtifactIntrinsicScope
from agent.schemas.data_analysis.common import CertifiedArtifactRef, canonical_sha256
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.generated_program import (
    GeneratedAnalysisProgram,
    GeneratedMeasurementDeclaration,
    GeneratedParameterDeclaration,
    GeneratedProgramResourceRequest,
    validate_generated_parameters,
)
from agent.schemas.data_analysis.plan import AnalysisPlan
from agent.schemas.data_analysis.report import (
    CertifiedResultRef,
    ConfidenceAssessment,
    DataFinding,
    SkillResultSummary,
)
from agent.schemas.data_analysis.resources import SamplingPolicy
from agent.schemas.data_analysis.skills import (
    AnalysisCoverage,
    ArtifactOutputContract,
    ProducedArtifact,
    SkillExecutionProvenance,
    SkillInputSlot,
    SkillResult,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig


def _provenance(*, model_id: str = "model-a") -> GeneratedProgramGenerationProvenance:
    return GeneratedProgramGenerationProvenance(
        provider="test",
        model_id=model_id,
        llm_config_sha256="1" * 64,
        generation_prompt_sha256="2" * 64,
        originating_request_id="request-1",
        question_ids=("q1",),
    )


def _program(*, model_id: str = "model-a") -> GeneratedAnalysisProgram:
    source = b"def analyze(inputs, parameters, output_directory):\n    return {'summary': 'ok'}\n"
    source_sha = hashlib.sha256(source).hexdigest()
    return GeneratedAnalysisProgram(
        program_id="program-1",
        question_ids=("q1",),
        source_ref=CertifiedArtifactRef(
            logical_ref=f"generated_analysis/{source_sha}.py",
            sha256=source_sha,
            media_type="text/x-python",
            byte_size=len(source),
        ),
        source_sha256=source_sha,
        input_slots=(
            SkillInputSlot(
                slot_id="series",
                description="Authorized time series",
                accepted_asset_types=("dataset",),
                accepted_view_formats=("siderius.timeseries-array.v1",),
                required_information=(InformationRequirement(information_class="data"),),
            ),
        ),
        expected_measurements=(
            GeneratedMeasurementDeclaration(
                result_key="custom_measurement",
                description="The requested custom measurement",
                value_type="number",
            ),
        ),
        resource_request=GeneratedProgramResourceRequest(
            wall_time_s=5.0,
            max_host_memory_gb=1.0,
        ),
        determinism="deterministic",
        seed=7,
        generation_provenance=_provenance(model_id=model_id),
    )


def _coverage() -> AnalysisCoverage:
    return AnalysisCoverage(
        population_unit="example",
        total_available=4,
        analyzed_count=2,
        binding_ids=("binding-1",),
        selection_sha256="3" * 64,
        split_id="analysis",
        sampling_strategy="uniform",
        sampling_seed=0,
    )


def _execution_provenance() -> SkillExecutionProvenance:
    return SkillExecutionProvenance(
        plan_sha256="4" * 64,
        parameter_schema_sha256="5" * 64,
        validated_parameters_sha256="6" * 64,
        authorization_receipts=(),
        environment_lock_verified=True,
        started_at="2026-09-15T00:00:00+00:00",
        finished_at="2026-09-15T00:00:01+00:00",
    )


def test_generation_history_does_not_change_executable_program_identity() -> None:
    """Defect: a provider label change invalidated byte-identical executable code."""

    first = _program(model_id="model-a")
    second = _program(model_id="model-b")

    assert first.identity(runtime_environment_sha256="7" * 64) == second.identity(
        runtime_environment_sha256="7" * 64
    )
    assert canonical_sha256(first) != canonical_sha256(second)


def test_generated_result_cannot_masquerade_as_a_skill_result() -> None:
    """Defect: generated code retained both identities and inherited trusted execution."""

    identity = _program().identity(runtime_environment_sha256="7" * 64)
    with pytest.raises(ValidationError, match="requires only generated identity"):
        SkillResult(
            result_id="result-1",
            invocation_id="invocation-1",
            execution_origin="generated_program",
            status="completed",
            summary="completed",
            coverage=_coverage(),
            resource_usage={"wall_time_s": 1.0, "device": "cpu"},
            provenance=_execution_provenance(),
        )

    result = SkillResult(
        result_id="result-1",
        invocation_id="invocation-1",
        execution_origin="generated_program",
        generated_program_identity=identity,
        status="completed",
        summary="completed",
        coverage=_coverage(),
        resource_usage={"wall_time_s": 1.0, "device": "cpu"},
        provenance=_execution_provenance(),
    )
    assert result.skill_identity is None


def test_old_skill_invocation_wire_form_remains_readable() -> None:
    """Defect: adding the action discriminator made persisted v1 skill plans unreadable."""

    payload = {
        "plan_id": "plan-1",
        "input_digest": "1" * 64,
        "access_policy_digest": "2" * 64,
        "discovery_snapshot_digest": "3" * 64,
        "questions": ["q1"],
        "invocations": [
            {
                "invocation_id": "invocation-1",
                "skill_id": "summary_statistics",
                "question_ids": ["q1"],
                "bindings": [
                    {
                        "binding_id": "binding-1",
                        "slot_id": "values",
                        "asset_id": "asset-1",
                        "requested_format_id": "siderius.numeric-array.v1",
                        "requested_information": [{"information_class": "data", "fields": []}],
                    }
                ],
                "sampling_plan": {
                    "split_id": "analysis",
                    "requested_scope": {
                        "kind": "artifact_intrinsic",
                        "split_id": "analysis",
                        "description": "Persisted analysis artifact scope",
                    },
                    "policy": SamplingPolicy().model_dump(mode="json"),
                },
                "arguments": {},
                "expected_time_cost": "cheap",
                "expected_memory_cost": "low",
                "priority": 3,
            }
        ],
        "stop_policy": {"max_invocations": 1},
        "rationale": "legacy persisted plan",
    }

    plan = AnalysisPlan.model_validate(payload)
    assert plan.invocations[0].action_kind == "skill"
    assert "action_kind" not in plan.model_dump(mode="json")["invocations"][0]


def test_generated_finding_and_summary_use_generated_identity_only() -> None:
    """Defect: report synthesis mislabeled generated evidence as a reference skill."""

    result_ref = CertifiedResultRef(
        result_id="result-1",
        logical_ref="skill_results.jsonl#result-1",
        sha256="8" * 64,
    )
    finding = DataFinding(
        finding_id="finding-1",
        statement="The custom measurement is positive.",
        evidence=({"result_ref": result_ref},),
        confidence=ConfidenceAssessment(level="medium", rationale="bounded synthetic evidence"),
        scope=ArtifactIntrinsicScope(
            split_id="analysis",
            description="Persisted analysis artifact scope",
        ),
        method_generated_program_ids=("program-1",),
        coverage=_coverage(),
        modeling_relevance="May warrant follow-up analysis.",
    )
    summary = SkillResultSummary(
        result_ref=result_ref,
        execution_origin="generated_program",
        generated_program_id="program-1",
        status="completed",
        summary="completed",
        coverage=_coverage(),
    )

    assert finding.method_skill_ids == ()
    assert summary.skill_id is None


def test_generated_program_source_identity_mismatch_is_refused() -> None:
    """Defect: a mutated source reference could survive declaration validation."""

    payload = _program().model_dump(mode="json")
    payload["source_sha256"] = "9" * 64
    with pytest.raises(ValidationError, match="source ref does not match"):
        GeneratedAnalysisProgram.model_validate(payload)


def test_generated_program_rejects_unloadable_view_format_before_plan_or_resume() -> None:
    """A plausible format typo must fail before materialization or resume."""

    program = _program()
    invalid_slot = SkillInputSlot.model_validate(
        {
            **program.input_slots[0].model_dump(mode="json"),
            "accepted_view_formats": ["siderius.time-series-array.v1"],
        }
    )
    with pytest.raises(ValidationError, match="unsupported generated-program view formats"):
        GeneratedProgramDraft(
            program_id=program.program_id,
            question_ids=program.question_ids,
            source_code=(
                "def analyze(inputs, parameters, output_directory):\n    return {'summary': 'ok'}\n"
            ),
            input_slots=(invalid_slot,),
            expected_measurements=program.expected_measurements,
            resource_request=program.resource_request,
            determinism=program.determinism,
            seed=program.seed,
            rationale="Measure a bounded time-series property.",
        )

    persisted_payload = program.model_dump(mode="json")
    persisted_payload["input_slots"] = [invalid_slot.model_dump(mode="json")]
    with pytest.raises(ValidationError, match="unsupported generated-program view formats"):
        GeneratedAnalysisProgram.model_validate(persisted_payload)


def test_generated_program_prompt_names_the_exact_supported_view_abis() -> None:
    """The generator must not have to guess the time-series format spelling."""

    scope = SimpleNamespace(mode="auto")
    analysis_input = SimpleNamespace(
        analysis_brief=SimpleNamespace(questions=()),
        task_context={},
        literature_evidence=None,
        effective_source_scope=lambda: scope,
        planning_assets=lambda: (),
        access_policy={},
        resource_envelope={},
    )
    system, _user = render_generated_program_prompt(
        cast(DataAnalysisInput, analysis_input),
        question_ids=(),
        output_schema={},
    )

    assert "siderius.numeric-array.v1" in system
    assert "siderius.timeseries-array.v1" in system
    assert "siderius.time-series-array.v1" not in system


def test_deterministic_seed_is_rejected_at_draft_boundary_before_persistence() -> None:
    """Defect: an invalid draft wrote source bytes before immutable declaration refusal."""

    program = _program()
    with pytest.raises(ValidationError, match="require an explicit seed"):
        GeneratedProgramDraft(
            program_id=program.program_id,
            question_ids=program.question_ids,
            source_code=(
                "def analyze(inputs, parameters, output_directory):\n    return {'summary': 'ok'}\n"
            ),
            input_slots=program.input_slots,
            expected_measurements=program.expected_measurements,
            resource_request=program.resource_request,
            determinism="deterministic",
            seed=None,
            rationale="Invalid deterministic draft.",
        )


def test_generated_numeric_parameters_reject_null_and_nonfinite_values() -> None:
    """Defect: required/null or nonfinite scalar arguments entered executable identity."""

    required = GeneratedParameterDeclaration(
        name="order",
        value_type="number",
        description="Finite required order",
    )
    with pytest.raises(ValueError, match="cannot be null"):
        validate_generated_parameters((required,), {"order": None})
    with pytest.raises(ValueError, match="must be finite"):
        validate_generated_parameters((required,), {"order": float("inf")})
    with pytest.raises(ValidationError, match="declarations must be finite"):
        GeneratedParameterDeclaration(
            name="delay",
            value_type="number",
            description="Finite optional delay",
            required=False,
            default=float("nan"),
        )


def test_generated_artifact_declarations_fit_the_resource_request() -> None:
    """Defect: a valid declaration could require more artifacts than execution permits."""

    payload = _program().model_dump(mode="json")
    payload["expected_artifacts"] = [
        {
            "artifact_type": "table",
            "media_type": "text/csv",
            "description": "Required result table",
            "required": True,
        }
    ]
    payload["resource_request"]["max_artifact_count"] = 0
    with pytest.raises(ValidationError, match="declarations exceed the resource request"):
        GeneratedAnalysisProgram.model_validate(payload)


def test_discovery_identity_cannot_be_materialized_or_leave_orphan_source(tmp_path: Path) -> None:
    """Defect: generated code requested discovery identity and persisted unusable source."""

    program = _program()
    identity_slot = SkillInputSlot(
        slot_id="series",
        description="Incorrectly requests discovery identity",
        accepted_asset_types=("dataset",),
        accepted_view_formats=("siderius.timeseries-array.v1",),
        required_information=(
            InformationRequirement(information_class="identity"),
            InformationRequirement(information_class="data"),
        ),
    )
    draft = GeneratedProgramDraft(
        program_id=program.program_id,
        question_ids=program.question_ids,
        source_code=(
            "def analyze(inputs, parameters, output_directory):\n    return {'summary': 'ok'}\n"
        ),
        input_slots=(identity_slot,),
        expected_measurements=program.expected_measurements,
        resource_request=program.resource_request,
        determinism=program.determinism,
        seed=program.seed,
        rationale="Invalid discovery-only identity request.",
    )

    with pytest.raises(ValidationError, match="identity information is discovery-only"):
        persist_generated_program(
            root=tmp_path,
            draft=draft,
            generation_provenance=_provenance(),
        )

    assert not (tmp_path / "generated_analysis" / "sources").exists()


def test_persisted_source_mutation_is_refused_and_resume_never_regenerates(
    tmp_path: Path,
) -> None:
    """Defect: a final plan could execute changed bytes under its original identity."""

    program = _program()
    draft = GeneratedProgramDraft(
        program_id=program.program_id,
        question_ids=program.question_ids,
        source_code=(
            "def analyze(inputs, parameters, output_directory):\n    return {'summary': 'ok'}\n"
        ),
        input_slots=program.input_slots,
        expected_measurements=program.expected_measurements,
        resource_request=program.resource_request,
        determinism=program.determinism,
        seed=program.seed,
        rationale="Persist exact generated bytes.",
    )
    _persisted, identity = persist_generated_program(
        root=tmp_path,
        draft=draft,
        generation_provenance=_provenance(),
    )
    loaded, source_path = load_generated_program(root=tmp_path, identity=identity)
    assert loaded.source_sha256 == identity.source_sha256

    source_path.write_text(draft.source_code + "# changed\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"byte size|digest"):
        load_generated_program(root=tmp_path, identity=identity)


def test_persisted_source_symlink_substitution_is_refused(
    tmp_path: Path,
) -> None:
    """Defect: resolving before link inspection hid a mutated generated source path."""

    program = _program()
    draft = GeneratedProgramDraft(
        program_id=program.program_id,
        question_ids=program.question_ids,
        source_code=(
            "def analyze(inputs, parameters, output_directory):\n    return {'summary': 'ok'}\n"
        ),
        input_slots=program.input_slots,
        expected_measurements=program.expected_measurements,
        resource_request=program.resource_request,
        determinism=program.determinism,
        seed=program.seed,
        rationale="Persist exact generated bytes.",
    )
    persisted, identity = persist_generated_program(
        root=tmp_path,
        draft=draft,
        generation_provenance=_provenance(),
    )
    source_path = tmp_path / persisted.source_ref.logical_ref
    alias_target = tmp_path / "same-source.py"
    alias_target.write_bytes(source_path.read_bytes())
    source_path.unlink()
    source_path.symlink_to(alias_target)

    with pytest.raises(ValueError, match="source may not use symbolic links"):
        load_generated_program(root=tmp_path, identity=identity)


def test_generation_provenance_is_audited_without_changing_executable_identity(
    tmp_path: Path,
) -> None:
    """Defect: identical code either lost its second generation receipt or changed identity."""

    program = _program()
    draft = GeneratedProgramDraft(
        program_id=program.program_id,
        question_ids=program.question_ids,
        source_code=(
            "def analyze(inputs, parameters, output_directory):\n    return {'summary': 'ok'}\n"
        ),
        input_slots=program.input_slots,
        expected_measurements=program.expected_measurements,
        resource_request=program.resource_request,
        determinism=program.determinism,
        seed=program.seed,
        rationale="Persist exact generated bytes.",
    )
    first_program, first_identity = persist_generated_program(
        root=tmp_path,
        draft=draft,
        generation_provenance=_provenance(model_id="model-a"),
    )
    second_program, second_identity = persist_generated_program(
        root=tmp_path,
        draft=draft,
        generation_provenance=_provenance(model_id="model-b"),
    )

    assert first_identity == second_identity
    assert first_program.generation_provenance != second_program.generation_provenance
    receipts = list(
        (tmp_path / "generated_analysis" / "generation_provenance" / "program-1").glob("*.json")
    )
    assert len(receipts) == 2


def test_generated_artifact_certification_rejects_symbolic_link_aliases(tmp_path: Path) -> None:
    """Defect: resolving before checking links let untrusted output alias another file."""

    store = AnalysisRunStore(
        StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=str(tmp_path), run_name="sandbox"),
        ),
        request_id="request",
    )
    staging = store.staging_directory("invocation")
    target = staging / "actual.csv"
    target.write_text("value\n1\n", encoding="utf-8")
    (staging / "alias.csv").symlink_to(target.name)

    with pytest.raises(AnalysisPersistenceError, match="symbolic links"):
        store.certify_artifacts(
            staging_directory=staging,
            declarations=(
                ProducedArtifact(
                    artifact_type="table",
                    logical_name="alias",
                    media_type="text/csv",
                    relative_path="alias.csv",
                    description="Untrusted alias",
                ),
            ),
            contract=ArtifactOutputContract(
                output_directory_ref="staging/invocation",
                allowed_media_types=("text/csv",),
            ),
        )
