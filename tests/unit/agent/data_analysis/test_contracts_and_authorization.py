from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from agent.data_analysis.authorization import authorize_materialization
from agent.schemas.data_analysis.access import (
    AnalysisAccessPolicy,
    MetadataVisibility,
    RequestedInformation,
    SplitAccessRule,
)
from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    AssetProvenance,
    DescriptorMetadataSource,
    TaskDataAssetLocation,
    TaskOpaqueScopeRef,
)
from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.time import FixedTimePrecisionRequirement
from execute_tools.analysis_materialization import (
    AnalysisAuthorizationError,
    AnalysisMaterializationRequest,
)


def _scope(payload: str = '{"rows":"all"}') -> TaskOpaqueScopeRef:
    return TaskOpaqueScopeRef(
        task_data_path_id="task-path",
        serialized_scope=payload,
        sha256=hashlib.sha256(payload.encode()).hexdigest(),
    )


def _policy(*, targets: bool = False, metadata: tuple[str, ...] = ()) -> AnalysisAccessPolicy:
    return AnalysisAccessPolicy(
        policy_id="analysis-policy",
        policy_version=1,
        purpose="scientific diagnostics",
        split_rules=(
            SplitAccessRule(
                split_id="validation",
                targets_visible=targets,
                metadata=(
                    MetadataVisibility(mode="allowlist", fields=metadata)
                    if metadata
                    else MetadataVisibility()
                ),
            ),
        ),
    )


def _asset(*, metadata=None, metadata_sources=None) -> AnalysisAsset:
    return AnalysisAsset(
        asset_id="validation-data",
        asset_type="dataset",
        description="Safe validation descriptor",
        location=TaskDataAssetLocation(
            task_data_path_id="task-path",
            dataset_profile_sha256="1" * 64,
            logical_role="validation",
        ),
        provenance=AssetProvenance(producer="test"),
        authorized_scope=_scope(),
        split_id="validation",
        metadata=metadata or {},
        metadata_sources=metadata_sources or {},
    )


def test_discovery_metadata_is_rejected_when_policy_hides_its_source() -> None:
    asset = _asset(
        metadata={"target_mean": 0.4},
        metadata_sources={
            "target_mean": DescriptorMetadataSource(
                information_class="target", split_id="validation"
            )
        },
    )

    with pytest.raises(ValueError, match=r"target_mean.*not visible"):
        asset.validate_discovery_metadata(_policy(targets=False))


def test_target_request_is_refused_before_materialization() -> None:
    asset = _asset()
    request = AnalysisMaterializationRequest(
        request_id="materialize-1",
        invocation_id="invocation-1",
        binding_id="binding-1",
        slot_id="series",
        asset=asset,
        split_id="validation",
        requested_scope=_scope(),
        requested_information=(RequestedInformation(information_class="target"),),
        requested_format_id="siderius.numeric-array.v1",
        operation="materialize",
        sampling_policy={"mode": "fixed", "max_items": 10},
        access_policy=_policy(targets=False),
    )

    with pytest.raises(AnalysisAuthorizationError) as raised:
        authorize_materialization(request, available_assets={asset.asset_id: asset})

    assert raised.value.refusal.code == "information_not_visible"
    assert raised.value.refusal.materialization_occurred is False


def test_authorization_receipt_binds_request_policy_and_asset() -> None:
    asset = _asset()
    request = AnalysisMaterializationRequest(
        request_id="materialize-1",
        invocation_id="invocation-1",
        binding_id="binding-1",
        slot_id="series",
        asset=asset,
        split_id="validation",
        requested_scope=_scope(),
        requested_information=(RequestedInformation(information_class="data"),),
        requested_format_id="siderius.numeric-array.v1",
        operation="materialize",
        sampling_policy={"mode": "fixed", "max_items": 10},
        access_policy=_policy(),
    )

    authorized = authorize_materialization(request, available_assets={asset.asset_id: asset})

    assert authorized.authorization_receipt.decision == "allowed"
    assert authorized.authorization_receipt.binding_id == "binding-1"
    assert authorized.authorization_receipt.request_digest != "0" * 64


def test_descriptor_metadata_requires_explicit_lineage() -> None:
    with pytest.raises(ValidationError, match="metadata key requires"):
        _asset(metadata={"cadence": 1.0})


def test_time_precision_requirement_is_format_scoped() -> None:
    asset = _asset()

    with pytest.raises(ValidationError, match="applies only"):
        AnalysisMaterializationRequest(
            request_id="materialize-precision",
            invocation_id="invocation-1",
            binding_id="binding-1",
            slot_id="series",
            asset=asset,
            split_id="validation",
            requested_scope=_scope(),
            requested_information=(RequestedInformation(information_class="data"),),
            requested_format_id="siderius.numeric-array.v1",
            time_precision_requirement={
                "kind": "fixed",
                "required_resolution_seconds": 1e-9,
            },
            operation="materialize",
            sampling_policy={"mode": "fixed", "max_items": 10},
            access_policy=_policy(),
        )


def test_format_and_precision_change_canonical_request_identity() -> None:
    asset = _asset()
    common = {
        "request_id": "materialize-identity",
        "invocation_id": "invocation-1",
        "binding_id": "binding-1",
        "slot_id": "series",
        "asset": asset,
        "split_id": "validation",
        "requested_scope": _scope(),
        "requested_information": (RequestedInformation(information_class="data"),),
        "operation": "materialize",
        "sampling_policy": {"mode": "fixed", "max_items": 10},
        "access_policy": _policy(),
    }
    numeric = AnalysisMaterializationRequest(
        **common,
        requested_format_id="siderius.numeric-array.v1",
    )
    time_without_requirement = AnalysisMaterializationRequest(
        **common,
        requested_format_id="siderius.timeseries-array.v1",
    )
    time_with_requirement = AnalysisMaterializationRequest(
        **common,
        requested_format_id="siderius.timeseries-array.v1",
        time_precision_requirement=FixedTimePrecisionRequirement(required_resolution_seconds=1e-9),
    )

    assert canonical_sha256(numeric) != canonical_sha256(time_without_requirement)
    assert canonical_sha256(time_without_requirement) != canonical_sha256(time_with_requirement)


def test_precision_requirement_neither_grants_access_nor_overrides_asset() -> None:
    precision = FixedTimePrecisionRequirement(required_resolution_seconds=1e-9)
    asset = _asset().model_copy(update={"time_precision_requirement": precision})
    request = AnalysisMaterializationRequest(
        request_id="materialize-hidden-target",
        invocation_id="invocation-1",
        binding_id="binding-1",
        slot_id="series",
        asset=asset,
        split_id="validation",
        requested_scope=_scope(),
        requested_information=(RequestedInformation(information_class="target"),),
        requested_format_id="siderius.timeseries-array.v1",
        time_precision_requirement=precision,
        operation="materialize",
        sampling_policy={"mode": "fixed", "max_items": 10},
        access_policy=_policy(targets=False),
    )

    with pytest.raises(AnalysisAuthorizationError) as raised:
        authorize_materialization(request, available_assets={asset.asset_id: asset})
    assert raised.value.refusal.code == "information_not_visible"

    altered = request.model_copy(
        update={
            "time_precision_requirement": FixedTimePrecisionRequirement(
                required_resolution_seconds=1e-6
            )
        }
    )
    with pytest.raises(AnalysisAuthorizationError) as mismatch:
        authorize_materialization(altered, available_assets={asset.asset_id: asset})
    assert mismatch.value.refusal.code == "materialization_requirement_mismatch"
