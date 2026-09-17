from __future__ import annotations

from typing import Any, cast

import pytest

from agent.data_analysis.materialization import (
    AnalysisMaterializationError,
    authorize_invocation_bindings,
    materialize_authorized_invocation,
)
from agent.data_analysis.plan_validation import (
    ResolvedAssetBinding,
    ResolvedPlannedInvocation,
)
from agent.data_analysis.worker_protocol import ValidatedParameters
from agent.schemas.data_analysis.access import AnalysisAccessPolicy, SplitAccessRule
from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    ArtifactIntrinsicScope,
    AssetProvenance,
    MaterializedAnalysisView,
    WorkspaceArtifactLocation,
)
from agent.schemas.data_analysis.common import CertifiedArtifactRef, canonical_sha256
from agent.schemas.data_analysis.plan import PlannedAssetBinding, PlannedSkillInvocation
from agent.schemas.data_analysis.skills import SkillInputSlot
from agent.schemas.data_analysis.time import (
    FixedTimePrecisionRequirement,
    TaskProvidedTimePrecisionRequirement,
)
from execute_tools.analysis_materialization import (
    AnalysisAuthorizationError,
    AnalysisMaterializationRefusal,
)


def _scope() -> ArtifactIntrinsicScope:
    return ArtifactIntrinsicScope(split_id="validation", description="Validation examples")


def _asset(*, precision: FixedTimePrecisionRequirement | None = None) -> AnalysisAsset:
    return AnalysisAsset(
        asset_id="series-asset",
        asset_type="dataset",
        description="Generic time-series asset",
        location=WorkspaceArtifactLocation(
            artifact_ref=CertifiedArtifactRef(
                logical_ref="source.npz",
                sha256="1" * 64,
                media_type="application/x-npz",
            )
        ),
        provenance=AssetProvenance(producer="test"),
        authorized_scope=_scope(),
        split_id="validation",
        time_precision_requirement=precision,
    )


def _resolved(
    asset: AnalysisAsset,
    *,
    requested_format_id: str = "siderius.timeseries-array.v1",
) -> ResolvedPlannedInvocation:
    slot = SkillInputSlot(
        slot_id="series",
        description="Authorized series",
        accepted_asset_types=("dataset",),
        accepted_view_formats=("siderius.timeseries-array.v1",),
        required_information=({"information_class": "data"},),
    )
    binding = PlannedAssetBinding(
        binding_id="binding-series",
        slot_id="series",
        asset_id=asset.asset_id,
        requested_format_id=requested_format_id,
        requested_information=({"information_class": "data"},),
    )
    invocation = PlannedSkillInvocation(
        invocation_id="invocation-series",
        skill_id="sampling_cadence_and_gaps",
        question_ids=("question-series",),
        bindings=(binding,),
        sampling_plan={
            "split_id": "validation",
            "requested_scope": _scope(),
            "policy": {"mode": "fixed", "max_items": 2, "seed": 7},
        },
        expected_time_cost="cheap",
        expected_memory_cost="low",
    )
    return ResolvedPlannedInvocation(
        invocation=invocation,
        resolved_scope=invocation.sampling_plan.requested_scope,
        skill=cast(Any, None),
        bindings=(ResolvedAssetBinding(plan_binding=binding, slot=slot, asset=asset),),
        validated_parameters=ValidatedParameters(
            parameters={},
            parameter_schema_sha256="2" * 64,
            validated_parameters_sha256="3" * 64,
        ),
    )


def _policy() -> AnalysisAccessPolicy:
    return AnalysisAccessPolicy(
        policy_id="policy",
        policy_version=1,
        purpose="generic diagnostics",
        split_rules=(SplitAccessRule(split_id="validation"),),
    )


class _Capability:
    def __init__(
        self,
        *,
        returned_format_id: str,
        preserve_precision: bool = True,
        source_digests: tuple[str, ...] = ("6" * 64,),
    ) -> None:
        self.returned_format_id = returned_format_id
        self.preserve_precision = preserve_precision
        self.source_digests = source_digests
        self.observed_request = None

    def materialize_analysis_view(self, authorized) -> MaterializedAnalysisView:
        self.observed_request = authorized.request
        request = authorized.request
        selection = {
            "selection_id": "selection-series",
            "selection_sha256": "4" * 64,
            "sampling_policy_sha256": canonical_sha256(request.sampling_policy),
            "sampling_mode": request.sampling_policy.mode,
            "sampling_strategy": request.sampling_policy.strategy,
            "sampling_seed": request.sampling_policy.seed,
            "population_unit": "examples",
            "total_available": 10,
            "selected_count": 2,
        }
        return MaterializedAnalysisView(
            materialization_id="materialization-series",
            invocation_id=request.invocation_id,
            binding_id=request.binding_id,
            slot_id=request.slot_id,
            asset_id=request.asset.asset_id,
            split_id=request.split_id,
            content_ref=CertifiedArtifactRef(
                logical_ref="materialized.npz",
                sha256="5" * 64,
                media_type="application/x-npz",
            ),
            format_id=self.returned_format_id,
            time_precision_requirement=(
                request.time_precision_requirement if self.preserve_precision else None
            ),
            population_unit="examples",
            total_available=10,
            materialized_count=2,
            certified_information=request.requested_information,
            selection_identity=selection,
            source_digests=self.source_digests,
            authorization_receipt=authorized.authorization_receipt,
        )


def test_binding_format_and_precision_reach_materializer_unchanged() -> None:
    precision = FixedTimePrecisionRequirement(required_resolution_seconds=1e-9)
    asset = _asset(precision=precision)
    invocation = _resolved(asset)
    requests = authorize_invocation_bindings(
        invocation,
        available_assets={asset.asset_id: asset},
        access_policy=_policy(),
    )
    capability = _Capability(returned_format_id="siderius.timeseries-array.v1")

    materialize_authorized_invocation(
        capability,
        invocation=invocation,
        requests=requests,
    )

    assert capability.observed_request is not None
    assert (
        capability.observed_request.requested_format_id
        == invocation.bindings[0].plan_binding.requested_format_id
    )
    assert capability.observed_request.time_precision_requirement == precision


def test_materializer_cannot_substitute_requested_format() -> None:
    asset = _asset()
    invocation = _resolved(asset)
    requests = authorize_invocation_bindings(
        invocation,
        available_assets={asset.asset_id: asset},
        access_policy=_policy(),
    )

    with pytest.raises(AnalysisMaterializationError, match="unrequested view format"):
        materialize_authorized_invocation(
            _Capability(returned_format_id="siderius.numeric-array.v1"),
            invocation=invocation,
            requests=requests,
        )


def test_task_materializer_refusal_is_typed_instead_of_aborting_the_workflow() -> None:
    """A task-owned ValueError must become a failed invocation, not a chain traceback."""

    asset = _asset()
    invocation = _resolved(asset)
    requests = authorize_invocation_bindings(
        invocation,
        available_assets={asset.asset_id: asset},
        access_policy=_policy(),
    )

    class RefusingCapability:
        def materialize_analysis_view(self, _authorized):
            raise ValueError("unsupported requested view format at private/task/path")

    with pytest.raises(
        AnalysisMaterializationError, match="task capability refused analysis materialization"
    ) as caught:
        materialize_authorized_invocation(
            RefusingCapability(),  # type: ignore[arg-type]
            invocation=invocation,
            requests=requests,
        )
    assert "private/task/path" not in str(caught.value)
    assert isinstance(caught.value.__cause__, ValueError)


def test_task_authorization_refusal_is_not_reclassified_as_materialization_failure() -> None:
    """Authorization is a ValueError subtype and must retain its refusal status."""

    asset = _asset()
    invocation = _resolved(asset)
    requests = authorize_invocation_bindings(
        invocation,
        available_assets={asset.asset_id: asset},
        access_policy=_policy(),
    )
    refusal = AnalysisMaterializationRefusal(
        code="task_materialization_refused",
        message="task denied this scope",
        request_id=requests[0].request.request_id,
    )

    class RefusingCapability:
        def materialize_analysis_view(self, _authorized):
            raise AnalysisAuthorizationError(refusal)

    with pytest.raises(AnalysisAuthorizationError) as caught:
        materialize_authorized_invocation(
            RefusingCapability(),  # type: ignore[arg-type]
            invocation=invocation,
            requests=requests,
        )
    assert caught.value.refusal is refusal


def test_materializer_must_preserve_precision_requirement() -> None:
    asset = _asset(precision=FixedTimePrecisionRequirement(required_resolution_seconds=1e-9))
    invocation = _resolved(asset)
    requests = authorize_invocation_bindings(
        invocation,
        available_assets={asset.asset_id: asset},
        access_policy=_policy(),
    )

    with pytest.raises(AnalysisMaterializationError, match="time-precision requirement"):
        materialize_authorized_invocation(
            _Capability(
                returned_format_id="siderius.timeseries-array.v1",
                preserve_precision=False,
            ),
            invocation=invocation,
            requests=requests,
        )


def test_task_provided_precision_requires_its_authority_digest() -> None:
    authority_digest = "7" * 64
    asset = AnalysisAsset.model_validate(
        {
            **_asset().model_dump(mode="json"),
            "time_precision_requirement": {
                "kind": "task_provided",
                "requirement_id": "source-timestamp-resolution",
                "source_sha256": authority_digest,
            },
        }
    )
    assert isinstance(asset.time_precision_requirement, TaskProvidedTimePrecisionRequirement)
    invocation = _resolved(asset)
    requests = authorize_invocation_bindings(
        invocation,
        available_assets={asset.asset_id: asset},
        access_policy=_policy(),
    )

    with pytest.raises(AnalysisMaterializationError, match="precision authority"):
        materialize_authorized_invocation(
            _Capability(returned_format_id="siderius.timeseries-array.v1"),
            invocation=invocation,
            requests=requests,
        )

    views = materialize_authorized_invocation(
        _Capability(
            returned_format_id="siderius.timeseries-array.v1",
            source_digests=(authority_digest,),
        ),
        invocation=invocation,
        requests=requests,
    )
    assert views[0].time_precision_requirement == asset.time_precision_requirement
