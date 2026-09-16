"""Regressions for run-scoped promotion and generated-skill discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.data_analysis.discovery import (
    DiscoveredGeneratedExperimentSkill,
    discover_skills,
    search_skill_cards,
)
from agent.data_analysis.generated_programs import GeneratedProgramDraft, persist_generated_program
from agent.data_analysis.generated_skill_registry import (
    GeneratedSkillRegistryError,
    generated_parameter_json_schema,
    load_generated_skill_registry,
    promote_generated_program,
)
from agent.schemas.data_analysis.access import InformationRequirement
from agent.schemas.data_analysis.action_identity import GeneratedProgramGenerationProvenance
from agent.schemas.data_analysis.generated_program import (
    GeneratedMeasurementDeclaration,
    GeneratedParameterDeclaration,
    GeneratedProgramResourceRequest,
)
from agent.schemas.data_analysis.generated_skill import GeneratedSkillPromotionDraft
from agent.schemas.data_analysis.skills import SkillInputSlot, SkillResult


def _persist_program(root: Path):
    draft = GeneratedProgramDraft(
        program_id="permutation-entropy",
        question_ids=("q-nonlinear",),
        source_code=(
            "def analyze(inputs, parameters, output_directory):\n"
            "    return {'summary': 'measured', 'quantitative_results': [], "
            "'produced_artifacts': [], 'analysis_usage': None, 'warnings': []}\n"
        ),
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
                result_key="permutation_entropy",
                description="Permutation entropy of the selected series",
                value_type="number",
            ),
        ),
        resource_request=GeneratedProgramResourceRequest(
            wall_time_s=5.0,
            max_host_memory_gb=1.0,
        ),
        determinism="deterministic",
        seed=17,
        rationale="No configured skill measures ordinal-pattern complexity.",
    )
    return persist_generated_program(
        root=root,
        draft=draft,
        generation_provenance=GeneratedProgramGenerationProvenance(
            provider="test",
            model_id="deterministic",
            llm_config_sha256="1" * 64,
            generation_prompt_sha256="2" * 64,
            originating_request_id="request-1",
            question_ids=("q-nonlinear",),
        ),
    )


def _promotion_draft() -> GeneratedSkillPromotionDraft:
    return GeneratedSkillPromotionDraft(
        program_id="permutation-entropy",
        skill_id="permutation_entropy_summary",
        title="Permutation entropy summary",
        one_line_description="Measures ordinal-pattern complexity in an authorized time series.",
        keywords=("ordinal", "complexity", "nonlinear"),
        aliases=("permutation entropy",),
        tags=("time-series",),
        applicable_when="Use when a question asks about ordinal or nonlinear signal complexity.",
        time_cost="moderate",
        memory_cost="low",
        rationale="The same complexity measurement is needed by later experiment iterations.",
    )


def test_promotion_is_explicit_run_scoped_and_discoverable(tmp_path: Path) -> None:
    """Defect: promoted code leaked globally or stayed invisible to normal card search."""

    source_root = tmp_path / "request-1"
    program, identity = _persist_program(source_root)
    registry_root = tmp_path / "run-a" / "generated_skill_registry"
    registry, ref = promote_generated_program(
        source_root=source_root,
        registry_root=registry_root,
        registry_id="run-a-generated-skills",
        existing=None,
        program=program,
        program_identity=identity,
        draft=_promotion_draft(),
        originating_request_id="request-1",
        originating_result_id="result-1",
    )

    loaded = load_generated_skill_registry(ref)
    assert loaded == registry
    assert discover_skills(()).skills == ()
    snapshot = discover_skills((), generated_skill_registry=ref)
    assert len(snapshot.skills) == 1
    assert isinstance(snapshot.skills[0], DiscoveredGeneratedExperimentSkill)
    assert snapshot.skills[0].identity == registry.skills[0].skill_identity
    assert snapshot.enabled_pack_ids == (
        "generated-experiment.run-a-generated-skills.permutation_entropy_summary",
    )
    assert search_skill_cards(snapshot, "ordinal complexity", limit=3) == snapshot.skills


def test_promoted_optional_null_parameter_schema_matches_executor_semantics() -> None:
    """Defect: planner schema rejected None although generated execution accepts it."""

    schema = generated_parameter_json_schema(
        (
            GeneratedParameterDeclaration(
                name="threshold",
                value_type="number",
                description="Optional threshold.",
                required=False,
                default=None,
            ),
        )
    )

    assert schema["properties"]["threshold"]["type"] == ["number", "null"]


def test_registry_resume_uses_exact_source_and_refuses_mutation(tmp_path: Path) -> None:
    """Defect: resume accepted rewritten generated source under an old registry identity."""

    source_root = tmp_path / "request-1"
    program, identity = _persist_program(source_root)
    _registry, ref = promote_generated_program(
        source_root=source_root,
        registry_root=tmp_path / "registry",
        registry_id="run-a-generated-skills",
        existing=None,
        program=program,
        program_identity=identity,
        draft=_promotion_draft(),
        originating_request_id="request-1",
        originating_result_id="result-1",
    )
    source_path = Path(ref.registry_root) / program.source_ref.logical_ref
    source_path.write_text("def analyze(*args):\n    return {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"source byte size changed|source digest differs"):
        load_generated_skill_registry(ref)


def test_promoted_result_keeps_skill_identity_and_untrusted_origin(tmp_path: Path) -> None:
    """Defect: promotion converted generated code into trusted configured-skill provenance."""

    source_root = tmp_path / "request-1"
    program, identity = _persist_program(source_root)
    registry, _ref = promote_generated_program(
        source_root=source_root,
        registry_root=tmp_path / "registry",
        registry_id="run-a-generated-skills",
        existing=None,
        program=program,
        program_identity=identity,
        draft=_promotion_draft(),
        originating_request_id="request-1",
        originating_result_id="result-1",
    )
    result = SkillResult(
        result_id="result-2",
        invocation_id="invocation-2",
        execution_origin="generated_experiment_skill",
        skill_identity=registry.skills[0].skill_identity,
        status="completed",
        summary="completed through sandbox",
        coverage={
            "population_unit": "example",
            "total_available": 4,
            "analyzed_count": 4,
            "binding_ids": ["binding-1"],
            "selection_sha256": "3" * 64,
            "split_id": "analysis",
            "sampling_strategy": "fixed:uniform",
        },
        resource_usage={"wall_time_s": 1.0, "device": "cpu"},
        provenance={
            "plan_sha256": "4" * 64,
            "parameter_schema_sha256": (
                registry.skills[0].resolved_interface.parameter_schema_sha256
            ),
            "validated_parameters_sha256": "5" * 64,
            "authorization_receipts": [],
            "environment_lock_verified": True,
            "started_at": "2026-09-15T00:00:00+00:00",
            "finished_at": "2026-09-15T00:00:01+00:00",
        },
    )

    assert result.generated_program_identity is None
    assert result.execution_origin == "generated_experiment_skill"
