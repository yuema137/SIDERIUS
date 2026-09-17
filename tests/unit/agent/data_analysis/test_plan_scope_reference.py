"""Plan-visible scope references resolve only to bound, identical certified scopes."""

from __future__ import annotations

import pytest

from agent.data_analysis.plan_validation import (
    AnalysisPlanResolutionError,
    ResolvedAssetBinding,
    _resolve_invocation_scope,
)
from agent.schemas.data_analysis.access import InformationRequirement, RequestedInformation
from agent.schemas.data_analysis.plan import (
    PlannedAssetBinding,
    PlannedSkillInvocation,
    SamplingPlan,
)
from agent.schemas.data_analysis.resources import SamplingPolicy
from agent.schemas.data_analysis.skills import SkillInputSlot
from tests.unit.agent.data_analysis.test_contracts_and_authorization import _asset, _scope


def _binding(asset_id: str) -> PlannedAssetBinding:
    return PlannedAssetBinding(
        binding_id=f"binding-{asset_id}",
        slot_id="series",
        asset_id=asset_id,
        requested_format_id="siderius.timeseries-array.v1",
        requested_information=(RequestedInformation(information_class="data"),),
    )


def _invocation(scope: dict[str, str], *asset_ids: str) -> PlannedSkillInvocation:
    return PlannedSkillInvocation(
        invocation_id="inspect-series",
        skill_id="synthetic-skill",
        question_ids=("question-1",),
        bindings=tuple(_binding(asset_id) for asset_id in asset_ids),
        sampling_plan=SamplingPlan(
            split_id="validation",
            requested_scope=scope,
            policy=SamplingPolicy(mode="fixed", max_items=2),
        ),
        expected_time_cost="cheap",
        expected_memory_cost="low",
    )


def _resolved(asset_id: str, *, scope_payload: str = '{"rows":"all"}') -> ResolvedAssetBinding:
    asset = _asset().model_copy(
        update={"asset_id": asset_id, "authorized_scope": _scope(scope_payload)}
    )
    return ResolvedAssetBinding(
        plan_binding=_binding(asset_id),
        slot=SkillInputSlot(
            slot_id="series",
            description="Authorized data series",
            accepted_asset_types=("dataset",),
            accepted_view_formats=("siderius.timeseries-array.v1",),
            required_information=(InformationRequirement(information_class="data"),),
        ),
        asset=asset,
    )


def test_short_reference_resolves_exact_certified_opaque_scope() -> None:
    invocation = _invocation(
        {"kind": "certified_asset_scope", "asset_id": "historical-input"},
        "historical-input",
        "history-model",
    )
    bindings = (_resolved("historical-input"), _resolved("history-model"))
    assert _resolve_invocation_scope(invocation, bindings) == bindings[0].asset.authorized_scope
    assert invocation.sampling_plan.requested_scope.model_dump(mode="json") == {
        "kind": "certified_asset_scope",
        "asset_id": "historical-input",
    }


def test_reference_cannot_name_unbound_asset_or_combine_different_scopes() -> None:
    bindings = (_resolved("historical-input"), _resolved("history-model"))
    with pytest.raises(AnalysisPlanResolutionError, match="bound by the same invocation"):
        _resolve_invocation_scope(
            _invocation(
                {"kind": "certified_asset_scope", "asset_id": "hidden"}, "historical-input"
            ),
            bindings,
        )
    with pytest.raises(AnalysisPlanResolutionError, match="share the exact scope"):
        _resolve_invocation_scope(
            _invocation(
                {"kind": "certified_asset_scope", "asset_id": "historical-input"},
                "historical-input",
                "history-model",
            ),
            (_resolved("historical-input"), _resolved("history-model", scope_payload='{"rows":1}')),
        )


def test_existing_explicit_scope_plan_remains_unchanged() -> None:
    scope = _scope()
    invocation = _invocation(scope.model_dump(mode="json"), "historical-input")
    assert _resolve_invocation_scope(invocation, (_resolved("historical-input"),)) == scope
