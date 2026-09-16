from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.data_analysis.plan_validation import (
    AnalysisPlanResolutionError,
    ResolvedAssetBinding,
    validate_binding_format,
    validate_binding_information,
    validate_invocation_metadata_selections,
)
from agent.schemas.data_analysis.access import (
    AnalysisAccessPolicy,
    RequestedInformation,
    SplitAccessRule,
)
from agent.schemas.data_analysis.assets import (
    AnalysisAsset,
    ArtifactIntrinsicScope,
    AssetProvenance,
    WorkspaceArtifactLocation,
)
from agent.schemas.data_analysis.common import CertifiedArtifactRef, canonical_sha256
from agent.schemas.data_analysis.plan import PlannedAssetBinding
from agent.schemas.data_analysis.skills import (
    ResolvedSkillInterface,
    SkillIdentity,
    SkillInputSlot,
)


def _slot() -> SkillInputSlot:
    return SkillInputSlot(
        slot_id="evaluation",
        description="Aligned targets, SNR metadata, and optional predictions.",
        accepted_asset_types=("dataset", "predictions"),
        accepted_view_formats=("aligned-evaluation.v1",),
        required_information=(
            {"information_class": "target"},
            {"information_class": "metadata", "fields": ["snr"]},
        ),
        optional_information=(
            {"information_class": "prediction"},
            {"information_class": "metadata", "fields": ["quality_flag"]},
        ),
    )


def _binding(*requested) -> PlannedAssetBinding:
    return PlannedAssetBinding(
        binding_id="evaluation-1",
        slot_id="evaluation",
        asset_id="evaluation-artifact",
        requested_format_id="aligned-evaluation.v1",
        requested_information=requested,
    )


def _asset() -> AnalysisAsset:
    return AnalysisAsset(
        asset_id="evaluation-artifact",
        asset_type="evaluation_artifact",
        description="Aligned evaluation values.",
        location=WorkspaceArtifactLocation(
            artifact_ref=CertifiedArtifactRef(
                logical_ref="evaluation.npz",
                sha256="1" * 64,
                media_type="application/x-npz",
            )
        ),
        provenance=AssetProvenance(producer="test"),
        authorized_scope=ArtifactIntrinsicScope(
            split_id="validation", description="Validation examples."
        ),
        split_id="validation",
    )


def _interface(*, include_selector: bool = True) -> ResolvedSkillInterface:
    properties = {"metadata_field": {"type": "string"}} if include_selector else {}
    schema = {"type": "object", "properties": properties}
    return ResolvedSkillInterface(
        skill_identity=SkillIdentity(
            pack_id="core-analysis",
            pack_version="1.0.0",
            pack_content_sha256="2" * 64,
            skill_id="performance_slice_summary",
            skill_version="1.0.0",
            implementation_sha256="3" * 64,
            determinism="deterministic",
        ),
        parameter_json_schema=schema,
        parameter_schema_sha256=canonical_sha256(schema),
        selected_skill_instructions="Slice prediction error by one authorized field.",
    )


def test_required_information_must_be_requested_before_materialization() -> None:
    binding = _binding({"information_class": "metadata", "fields": ["snr"]})

    with pytest.raises(AnalysisPlanResolutionError, match="omits required 'target'"):
        validate_binding_information(binding, _slot())


def test_target_visible_to_policy_is_still_invalid_for_data_only_slot() -> None:
    """The plan/slot boundary must reject the observed TIDMAD LLM mistake."""

    policy = AnalysisAccessPolicy(
        policy_id="validation-diagnostics",
        policy_version=1,
        purpose="Permit separate target diagnostics",
        split_rules=(SplitAccessRule(split_id="validation", targets_visible=True),),
    )
    assert policy.permits(split_id="validation", information_class="target")
    data_only = SkillInputSlot(
        slot_id="evaluation",
        description="Observed values only, even if target is visible elsewhere.",
        accepted_asset_types=("dataset",),
        accepted_view_formats=("aligned-evaluation.v1",),
        required_information=({"information_class": "data"},),
    )
    binding = _binding(
        {"information_class": "data"},
        {"information_class": "target"},
    )
    with pytest.raises(AnalysisPlanResolutionError, match="undeclared information class"):
        validate_binding_information(binding, data_only)


def test_request_must_stay_within_required_and_optional_information() -> None:
    binding = _binding(
        {"information_class": "target"},
        {"information_class": "metadata", "fields": ["snr", "secret_label"]},
    )

    with pytest.raises(AnalysisPlanResolutionError, match="undeclared metadata"):
        validate_binding_information(binding, _slot())


def test_exact_required_plus_optional_request_is_valid() -> None:
    binding = _binding(
        {"information_class": "target"},
        {"information_class": "prediction"},
        {"information_class": "metadata", "fields": ["snr", "quality_flag"]},
    )

    validate_binding_information(binding, _slot())


def test_required_and_optional_metadata_fields_cannot_overlap() -> None:
    with pytest.raises(ValidationError, match="metadata fields must be disjoint"):
        SkillInputSlot(
            slot_id="bad",
            description="Invalid duplicate metadata authority.",
            accepted_asset_types=("dataset",),
            accepted_view_formats=("test.v1",),
            required_information=({"information_class": "metadata", "fields": ["snr"]},),
            optional_information=({"information_class": "metadata", "fields": ["snr"]},),
        )


def test_dynamic_metadata_is_additive_to_static_metadata() -> None:
    slot = SkillInputSlot(
        slot_id="slice_metadata",
        description="A fixed sample rate plus one selected scientific covariate.",
        accepted_asset_types=("evaluation_artifact",),
        accepted_view_formats=("siderius.numeric-array.v1",),
        required_information=(
            {"information_class": "target"},
            {"information_class": "metadata", "fields": ["sample_rate_hz"]},
        ),
        optional_information=({"information_class": "metadata", "fields": ["quality_flag"]},),
        invocation_metadata_selection={
            "minimum_fields": 1,
            "maximum_fields": 1,
            "parameter_name": "metadata_field",
        },
    )
    binding = _binding(
        {"information_class": "target"},
        {
            "information_class": "metadata",
            "fields": ["sample_rate_hz", "quality_flag", "snr"],
        },
    ).model_copy(update={"slot_id": "slice_metadata"})
    validate_binding_information(binding, slot)

    validate_invocation_metadata_selections(
        (ResolvedAssetBinding(plan_binding=binding, slot=slot, asset=_asset()),),
        interface=_interface(),
        validated_parameters={"metadata_field": "snr"},
    )


@pytest.mark.parametrize(
    ("parameter_value", "requested_fields", "message"),
    [
        ("frequency", ["snr"], "does not exactly match"),
        (["snr", "frequency"], ["snr", "frequency"], "outside its declared bounds"),
    ],
)
def test_dynamic_metadata_parameter_must_exactly_match_bounded_request(
    parameter_value,
    requested_fields,
    message,
) -> None:
    slot = SkillInputSlot(
        slot_id="slice_metadata",
        description="Exactly one invocation-selected covariate.",
        accepted_asset_types=("evaluation_artifact",),
        accepted_view_formats=("siderius.numeric-array.v1",),
        required_information=(),
        invocation_metadata_selection={
            "minimum_fields": 1,
            "maximum_fields": 1,
            "parameter_name": "metadata_field",
        },
    )
    binding = _binding({"information_class": "metadata", "fields": requested_fields}).model_copy(
        update={"slot_id": "slice_metadata"}
    )
    validate_binding_information(binding, slot)

    with pytest.raises(AnalysisPlanResolutionError, match=message):
        validate_invocation_metadata_selections(
            (ResolvedAssetBinding(plan_binding=binding, slot=slot, asset=_asset()),),
            interface=_interface(),
            validated_parameters={"metadata_field": parameter_value},
        )


def test_dynamic_metadata_selector_must_exist_in_resolved_schema() -> None:
    slot = SkillInputSlot(
        slot_id="slice_metadata",
        description="Exactly one invocation-selected covariate.",
        accepted_asset_types=("evaluation_artifact",),
        accepted_view_formats=("siderius.numeric-array.v1",),
        required_information=(),
        invocation_metadata_selection={
            "minimum_fields": 1,
            "maximum_fields": 1,
            "parameter_name": "metadata_field",
        },
    )
    binding = _binding({"information_class": "metadata", "fields": ["snr"]}).model_copy(
        update={"slot_id": "slice_metadata"}
    )

    with pytest.raises(AnalysisPlanResolutionError, match="schema omits"):
        validate_invocation_metadata_selections(
            (ResolvedAssetBinding(plan_binding=binding, slot=slot, asset=_asset()),),
            interface=_interface(include_selector=False),
            validated_parameters={"metadata_field": "snr"},
        )


def test_metadata_wildcards_remain_forbidden() -> None:
    with pytest.raises(ValidationError, match="wildcard"):
        PlannedAssetBinding(
            binding_id="slice-1",
            slot_id="slice_metadata",
            asset_id="evaluation-artifact",
            requested_format_id="siderius.numeric-array.v1",
            requested_information=({"information_class": "metadata", "fields": ["*"]},),
        )


def test_requested_information_fields_are_conditional_on_metadata() -> None:
    """Catches named fields becoming an authority for non-metadata information."""

    assert RequestedInformation(information_class="data", fields=()).fields == ()
    assert RequestedInformation(information_class="metadata", fields=("snr",)).fields == ("snr",)

    with pytest.raises(ValidationError, match="only for metadata"):
        RequestedInformation(information_class="prediction", fields=("prediction",))


def test_requested_format_must_be_accepted_before_materialization() -> None:
    binding = _binding({"information_class": "target"}).model_copy(
        update={"requested_format_id": "unrelated-format.v1"}
    )

    with pytest.raises(AnalysisPlanResolutionError, match="not accepted"):
        validate_binding_format(binding, _slot())
