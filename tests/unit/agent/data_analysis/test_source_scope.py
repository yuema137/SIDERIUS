"""One inspectable analysis-source ceiling, enforced before scientific reads."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.data_analysis.authorization import authorize_materialization
from agent.data_analysis.discovery import DiscoverySnapshot
from agent.data_analysis.plan_validation import (
    AnalysisPlanResolutionError,
    ResolvedAssetBinding,
    ResolvedInferenceInputBinding,
    _validate_source_scope,
)
from agent.data_analysis.source_scope import (
    apply_source_prompt,
    source_prompt_identity,
)
from agent.prompt_templates.data_analysis import (
    render_analysis_plan_prompt,
    render_generated_program_prompt,
    render_skill_selection_prompt,
)
from agent.schemas.data_analysis.access import RequestedInformation
from agent.schemas.data_analysis.assets import AssetProvenance
from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.plan import PlannedAssetBinding, PlannedInferenceInputBinding
from agent.schemas.data_analysis.skills import SkillInputSlot
from agent.schemas.data_analysis.source_directive import _resolve_models
from agent.schemas.data_analysis.source_scope import AnalysisSourceScope, DeclaredAnalysisScope
from core.run_invariants import RunInvariants
from execute_tools.analysis_materialization import (
    AnalysisAuthorizationError,
    AnalysisMaterializationRequest,
)
from tests.unit.agent.data_analysis.test_contracts_and_authorization import _asset, _policy
from tests.unit.nodes.test_data_analysis_agent import _input
from workflows.model_exploration import _workflow_lock_identity
from workflows.run_config import WorkflowLaunchConfig


def test_automatic_scope_contains_only_declared_raw_input(tmp_path) -> None:
    inp = _input(tmp_path)
    assert "history_run_names" not in inp.model_dump(mode="json")["declared_scope"]
    scope = inp.effective_source_scope()
    assert scope.mode == "automatic"
    assert scope.raw_input_asset_ids == ("dataset",)
    assert scope.historical_model_asset_ids == ()
    assert scope.permits(asset_id="dataset", information_class="data", operation="materialize")
    assert not scope.permits(
        asset_id="dataset", information_class="target", operation="materialize"
    )
    assert not scope.permits(
        asset_id="old-predictions", information_class="prediction", operation="materialize"
    )
    _, prompt = render_skill_selection_prompt(inp, (), output_schema={})
    assert "Ground truth and persisted model outputs are not analysis sources" in prompt
    assert source_prompt_identity(None) is None
    assert source_prompt_identity("auto") is None
    assert apply_source_prompt(inp, None) is inp
    assert apply_source_prompt(inp, "auto") is inp


def test_one_lock_resolves_without_granting_target_or_saved_outputs(tmp_path) -> None:
    inp = _input(tmp_path)
    locked = apply_source_prompt(inp, "lock: raw=dataset; models=none")
    assert locked.source_scope is not None
    assert locked.source_scope.mode == "locked"
    assert locked.source_scope.raw_input_asset_ids == ("dataset",)
    assert locked.source_scope.historical_model_asset_ids == ()
    assert not locked.source_scope.permits(
        asset_id="dataset", information_class="target", operation="materialize"
    )
    assert locked.canonical_scientific_digest() != inp.canonical_scientific_digest()


def test_out_of_scope_asset_descriptor_is_not_shown_to_planner(tmp_path) -> None:
    inp = _input(tmp_path)
    hidden = inp.available_assets[0].model_copy(
        update={"asset_id": "hidden-target", "description": "Secret target descriptor"}
    )
    with_hidden = type(inp).model_validate(
        {
            **inp.model_dump(mode="json"),
            "available_assets": [
                inp.available_assets[0].model_dump(mode="json"),
                hidden.model_dump(mode="json"),
            ],
        }
    )
    assert [asset.asset_id for asset in with_hidden.planning_assets()] == ["dataset"]
    _, prompt = render_skill_selection_prompt(with_hidden, (), output_schema={})
    assert "hidden-target" not in prompt
    assert "Secret target descriptor" not in prompt


def test_planning_preserves_selected_identity_metadata_without_exposing_targets(tmp_path) -> None:
    """2026-09-19: source projection dropped declared cadence before code generation."""
    raw = _input(tmp_path).model_dump(mode="json")
    asset = raw["available_assets"][0]
    asset["metadata"] = {"sample_rate_hz": 1234.5, "target_mean": 9876.5}
    asset["metadata_sources"] = {
        "sample_rate_hz": {"information_class": "identity"},
        "target_mean": {"information_class": "target", "split_id": "validation"},
    }
    # The broader access policy allows target descriptors, but the raw-input
    # source ceiling must still remove them from planning.
    raw["access_policy"]["split_rules"][0]["targets_visible"] = True
    hidden = {**asset, "asset_id": "unselected", "description": "hidden identity"}
    raw["available_assets"].append(hidden)
    inp = type(_input(tmp_path)).model_validate(raw)
    projected = inp.planning_assets()
    assert len(projected) == 1
    assert projected[0].metadata == {"sample_rate_hz": 1234.5}
    for prompt in (
        render_skill_selection_prompt(inp, (), output_schema={})[1],
        render_generated_program_prompt(inp, question_ids=("q-summary",), output_schema={})[1],
    ):
        assert '"sample_rate_hz": 1234.5' in prompt
        assert "target_mean" not in prompt
        assert "unselected" not in prompt
        assert "hidden identity" not in prompt


def test_locked_prompt_hides_unselected_declared_source_ids(tmp_path) -> None:
    inp = _input(tmp_path)
    other = inp.available_assets[0].model_copy(
        update={"asset_id": "other-raw-input", "description": "Other raw source"}
    )
    expanded = type(inp).model_validate(
        {
            **inp.model_dump(mode="json"),
            "available_assets": [
                inp.available_assets[0].model_dump(mode="json"),
                other.model_dump(mode="json"),
            ],
            "declared_scope": {"raw_input_asset_ids": ["dataset", "other-raw-input"]},
        }
    )
    locked = apply_source_prompt(expanded, "lock: raw=dataset; models=none")
    _, prompt = render_skill_selection_prompt(locked, (), output_schema={})
    assert "other-raw-input" not in prompt
    assert "Other raw source" not in prompt
    discovery = DiscoverySnapshot(
        enabled_pack_ids=(),
        manifest_digests=(),
        skills=(),
        snapshot_digest=canonical_sha256(
            {"enabled_pack_ids": [], "manifest_digests": [], "skills": []}
        ),
    )
    _, plan_prompt = render_analysis_plan_prompt(locked, discovery, (), {})
    assert "other-raw-input" not in plan_prompt
    assert "Other raw source" not in plan_prompt


def test_lock_on_raw_parent_includes_only_declared_certified_input_derivation(tmp_path) -> None:
    inp = _input(tmp_path)
    derived = inp.available_assets[0].model_copy(
        update={
            "asset_id": "candidate-model-input",
            "provenance": AssetProvenance(
                producer="task-owned-derivation", source_asset_ids=("dataset",)
            ),
        }
    )
    undeclared = derived.model_copy(update={"asset_id": "undeclared-processing"})
    expanded = type(inp).model_validate(
        {
            **inp.model_dump(mode="json"),
            "available_assets": [
                asset.model_dump(mode="json")
                for asset in (inp.available_assets[0], derived, undeclared)
            ],
            "declared_scope": {
                "raw_input_asset_ids": ["dataset", "candidate-model-input"],
            },
        }
    )
    locked = apply_source_prompt(expanded, "lock: raw=dataset; models=none")
    assert locked.source_scope is not None
    assert locked.source_scope.raw_input_asset_ids == ("dataset", "candidate-model-input")
    assert not locked.source_scope.permits(
        asset_id="undeclared-processing", information_class="data", operation="materialize"
    )


@pytest.mark.parametrize(
    "directive",
    (
        "lock: raw=unknown; models=none",
        "lock: raw=dataset; models=ids:unknown",
        "lock: raw=dataset; models=last:0",
        "lock: raw=dataset; models=all; target=all",
        "lock: raw=*; models=none",
        "lock: raw=dataset",
        "please analyze the labels",
    ),
)
def test_ambiguous_or_escalating_directive_fails_closed(tmp_path, directive: str) -> None:
    with pytest.raises(ValueError):
        apply_source_prompt(_input(tmp_path), directive)


def test_prompt_is_bounded_and_participates_in_run_identity() -> None:
    directive = "lock: raw=dataset; models=none"
    assert source_prompt_identity(directive) is not None
    assert _workflow_lock_identity(
        WorkflowLaunchConfig(analysis_source_prompt=directive)
    ).analysis_source_prompt_sha256 == source_prompt_identity(directive)
    assert _workflow_lock_identity(WorkflowLaunchConfig()).analysis_source_prompt_sha256 is None
    base = RunInvariants(
        resolved_data_scope=[0], health_gate_enabled=False, health_config_sha256=None
    )
    changed = base.model_copy(
        update={"analysis_source_prompt_sha256": source_prompt_identity(directive)}
    )
    assert changed.canonical() != base.canonical()
    with pytest.raises(ValueError, match="4096"):
        source_prompt_identity("lock: " + "a" * 4097)
    with pytest.raises(ValueError, match="1-64"):
        source_prompt_identity(
            "lock: raw=" + ",".join(f"a{index}" for index in range(65)) + "; models=none"
        )


def test_historical_model_selection_uses_certified_completion_order() -> None:
    history = ("model-first", "model-second", "model-third")
    assert _resolve_models("all", history) == history
    assert _resolve_models("last:2", history) == history[-2:]
    assert _resolve_models("ids:model-third,model-first", history) == (
        "model-first",
        "model-third",
    )
    assert _resolve_models("none", history) == ()
    with pytest.raises(ValueError, match="outside the declared history"):
        _resolve_models("ids:foreign-model", history)


def test_recent_round_policy_counts_empty_rounds_not_model_files(tmp_path) -> None:
    raw = _input(tmp_path).available_assets[0]
    models = (
        raw.model_copy(
            update={
                "asset_id": "model-1a",
                "provenance": AssetProvenance(producer="test", run_id="iter_001"),
            }
        ),
        raw.model_copy(
            update={
                "asset_id": "model-1b",
                "provenance": AssetProvenance(producer="test", run_id="iter_001"),
            }
        ),
        raw.model_copy(
            update={
                "asset_id": "model-3",
                "provenance": AssetProvenance(producer="test", run_id="iter_003"),
            }
        ),
    )
    declared = tuple(asset.asset_id for asset in models)
    timeline = ("iter_001", "iter_002", "iter_003", "iter_004")
    assert (
        _resolve_models("last_rounds:1", declared, assets=models, history_run_names=timeline) == ()
    )
    assert _resolve_models(
        "last_rounds:2", declared, assets=models, history_run_names=timeline
    ) == ("model-3",)
    assert (
        _resolve_models("last_rounds:4", declared, assets=models, history_run_names=timeline)
        == declared
    )
    assert _resolve_models("last:2", declared) == ("model-1b", "model-3")
    two_rounds = source_prompt_identity("lock: raw=all; models=last_rounds:2")
    three_rounds = source_prompt_identity("lock: raw=all; models=last_rounds:3")
    assert two_rounds is not None and two_rounds != three_rounds
    with pytest.raises(ValueError, match="requires declared prior iteration history"):
        _resolve_models("last_rounds:2", declared, assets=models)
    with pytest.raises(ValueError, match="positive integer"):
        source_prompt_identity("lock: raw=all; models=last_rounds:0")


def test_direct_typed_scope_cannot_expand_caller_declaration(tmp_path) -> None:
    inp = _input(tmp_path)
    expanded = AnalysisSourceScope(
        mode="locked",
        raw_input_asset_ids=("dataset", "secret-data"),
        source_prompt="lock: raw=dataset,secret-data; models=none",
    )
    with pytest.raises(ValidationError, match="exceeds its declared"):
        type(inp).model_validate(
            {**inp.model_dump(mode="json"), "source_scope": expanded.model_dump(mode="json")}
        )
    with pytest.raises(ValidationError):
        DeclaredAnalysisScope(raw_input_asset_ids=("dataset", "dataset"))


def test_direct_typed_scope_must_match_its_inspectable_prompt(tmp_path) -> None:
    inp = _input(tmp_path)
    dishonest = AnalysisSourceScope(
        mode="locked",
        raw_input_asset_ids=("dataset",),
        source_prompt="lock: raw=unknown; models=none",
    )
    with pytest.raises(ValidationError, match="outside the declared scope"):
        type(inp).model_validate(
            {**inp.model_dump(mode="json"), "source_scope": dishonest.model_dump(mode="json")}
        )


def test_materialization_rechecks_source_scope_before_task_capability() -> None:
    asset = _asset()
    scope = AnalysisSourceScope(
        mode="locked",
        raw_input_asset_ids=(asset.asset_id,),
        source_prompt=f"lock: raw={asset.asset_id}; models=none",
    )
    request = AnalysisMaterializationRequest(
        request_id="locked-materialization",
        invocation_id="invocation-1",
        binding_id="binding-1",
        slot_id="series",
        asset=asset,
        split_id=asset.split_id,
        requested_scope=asset.authorized_scope,
        requested_information=(RequestedInformation(information_class="target"),),
        requested_format_id="siderius.numeric-array.v1",
        operation="materialize",
        sampling_policy={"mode": "fixed", "max_items": 10},
        access_policy=_policy(targets=True),
        source_scope=scope,
    )
    with pytest.raises(AnalysisAuthorizationError) as raised:
        authorize_materialization(request, available_assets={asset.asset_id: asset})
    assert raised.value.refusal.code == "information_not_visible"
    assert raised.value.refusal.materialization_occurred is False


def test_nested_model_input_must_be_in_same_single_scope(tmp_path) -> None:
    inp = _input(tmp_path)
    dataset = inp.available_assets[0]
    model = dataset.model_copy(update={"asset_id": "prior-model"})
    nested = PlannedInferenceInputBinding(
        binding_id="model-input",
        asset_id="dataset",
        requested_format_id="siderius.numeric-array.v1",
        requested_information=(RequestedInformation(information_class="data"),),
    )
    binding = PlannedAssetBinding.model_construct(
        binding_id="prediction",
        slot_id="prediction",
        asset_id="prior-model",
        operation="infer",
        requested_format_id="siderius.numeric-array.v1",
        requested_information=(RequestedInformation(information_class="prediction"),),
        inference_inputs=(nested,),
        inference_configuration=None,
    )
    slot = SkillInputSlot(
        slot_id="prediction",
        description="Transient canonical prediction",
        accepted_asset_types=("trained_model",),
        accepted_view_formats=("siderius.numeric-array.v1",),
        required_information=(RequestedInformation(information_class="prediction"),),
    )
    resolved = ResolvedAssetBinding(
        plan_binding=binding,
        slot=slot,
        asset=model,
        inference_inputs=(ResolvedInferenceInputBinding(plan_binding=nested, asset=dataset),),
    )
    model_only = AnalysisSourceScope(
        mode="locked",
        raw_input_asset_ids=("other-raw",),
        historical_model_asset_ids=("prior-model",),
        source_prompt="lock: raw=other-raw; models=ids:prior-model",
    )
    with pytest.raises(AnalysisPlanResolutionError, match="inference input exceeds"):
        _validate_source_scope(
            (resolved,),
            analysis_input=inp.model_copy(update={"source_scope": model_only}),
            strata_fields=(),
        )
    with_both = model_only.model_copy(update={"raw_input_asset_ids": ("dataset",)})
    _validate_source_scope(
        (resolved,),
        analysis_input=inp.model_copy(update={"source_scope": with_both}),
        strata_fields=(),
    )
