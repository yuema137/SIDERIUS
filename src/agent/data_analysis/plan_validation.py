"""Deterministic resolution between a validated plan and any data access."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from agent.schemas.data_analysis.access import InformationRequirement
from agent.schemas.data_analysis.assets import AnalysisAsset, TrainedModelArtifactLocation
from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.generated_program import (
    GeneratedAnalysisProgram,
    validate_generated_parameters,
)
from agent.schemas.data_analysis.plan import (
    AnalysisPlan,
    PlannedAssetBinding,
    PlannedGeneratedExperimentSkillInvocation,
    PlannedGeneratedProgramInvocation,
    PlannedInferenceInputBinding,
    PlannedSkillInvocation,
)
from agent.schemas.data_analysis.skills import ResolvedSkillInterface, SkillInputSlot

from .discovery import (
    DiscoveredGeneratedExperimentSkill,
    DiscoveredSkill,
    DiscoverySnapshot,
)
from .executor import validate_skill_parameters
from .generated_programs import load_generated_program
from .worker_protocol import ValidatedParameters


class AnalysisPlanResolutionError(ValueError):
    """A typed plan could not be bound to certified inputs and discovered skills."""


@dataclass(frozen=True)
class ResolvedAssetBinding:
    plan_binding: PlannedAssetBinding
    slot: SkillInputSlot
    asset: AnalysisAsset
    inference_inputs: tuple[ResolvedInferenceInputBinding, ...] = ()


@dataclass(frozen=True)
class ResolvedInferenceInputBinding:
    plan_binding: PlannedInferenceInputBinding
    asset: AnalysisAsset


@dataclass(frozen=True)
class ResolvedPlannedInvocation:
    invocation: PlannedSkillInvocation
    skill: DiscoveredSkill
    bindings: tuple[ResolvedAssetBinding, ...]
    validated_parameters: ValidatedParameters


@dataclass(frozen=True)
class ResolvedGeneratedProgramInvocation:
    invocation: PlannedGeneratedProgramInvocation
    program: GeneratedAnalysisProgram
    source_path: Path
    bindings: tuple[ResolvedAssetBinding, ...]
    validated_parameters: ValidatedParameters


@dataclass(frozen=True)
class ResolvedGeneratedExperimentSkillInvocation:
    invocation: PlannedGeneratedExperimentSkillInvocation
    skill: DiscoveredGeneratedExperimentSkill
    program: GeneratedAnalysisProgram
    source_path: Path
    bindings: tuple[ResolvedAssetBinding, ...]
    validated_parameters: ValidatedParameters


ResolvedAnalysisInvocation = (
    ResolvedPlannedInvocation
    | ResolvedGeneratedProgramInvocation
    | ResolvedGeneratedExperimentSkillInvocation
)


def _validate_source_scope(
    bindings: tuple[ResolvedAssetBinding, ...],
    *,
    analysis_input: DataAnalysisInput,
    strata_fields: tuple[str, ...],
) -> None:
    """Check all reads, including model-worker inputs, before execution starts."""

    scope = analysis_input.effective_source_scope()
    for resolved in bindings:
        asset = resolved.asset
        for item in resolved.plan_binding.requested_information:
            if not scope.permits(
                asset_id=asset.asset_id,
                information_class=item.information_class,
                operation=resolved.plan_binding.operation,
                fields=item.fields,
            ):
                raise AnalysisPlanResolutionError("planned binding exceeds the analysis scope")
        for nested in resolved.inference_inputs:
            for item in nested.plan_binding.requested_information:
                if not scope.permits(
                    asset_id=nested.asset.asset_id,
                    information_class=item.information_class,
                    operation="materialize",
                    fields=item.fields,
                ):
                    raise AnalysisPlanResolutionError(
                        "historical inference input exceeds the analysis scope"
                    )
    if strata_fields:
        for resolved in bindings:
            # Inference output inherits the certified selection of its explicit
            # input view; the model artifact itself does not expose strata.
            selection_inputs = (
                resolved.inference_inputs
                if resolved.plan_binding.operation == "infer"
                else (resolved,)
            )
            for item in selection_inputs:
                if not scope.permits(
                    asset_id=item.asset.asset_id,
                    information_class="metadata",
                    operation="materialize",
                    fields=strata_fields,
                ):
                    raise AnalysisPlanResolutionError(
                        "stratified sampling exceeds the analysis scope"
                    )


def _requirements_by_class(
    requirements: tuple[InformationRequirement, ...],
) -> dict[str, set[str]]:
    return {item.information_class: set(item.fields) for item in requirements}


def validate_binding_information(
    binding: PlannedAssetBinding,
    slot: SkillInputSlot,
) -> None:
    required = _requirements_by_class(slot.required_information)
    optional = _requirements_by_class(slot.optional_information)
    requested = _requirements_by_class(binding.requested_information)
    for information_class, required_fields in required.items():
        if information_class not in requested:
            raise AnalysisPlanResolutionError(
                f"binding {binding.binding_id!r} omits required {information_class!r} information"
            )
        if not required_fields.issubset(requested[information_class]):
            raise AnalysisPlanResolutionError(
                f"binding {binding.binding_id!r} omits required {information_class!r} fields"
            )
    allowed_classes = set(required) | set(optional)
    if slot.invocation_metadata_selection is not None:
        allowed_classes.add("metadata")
    if not set(requested).issubset(allowed_classes):
        raise AnalysisPlanResolutionError(
            f"binding {binding.binding_id!r} requests an undeclared information class"
        )
    for information_class, requested_fields in requested.items():
        allowed_fields = required.get(information_class, set()) | optional.get(
            information_class, set()
        )
        if (
            information_class == "metadata"
            and not requested_fields.issubset(allowed_fields)
            and slot.invocation_metadata_selection is None
        ):
            raise AnalysisPlanResolutionError(
                f"binding {binding.binding_id!r} requests undeclared metadata fields"
            )


def validate_binding_format(binding: PlannedAssetBinding, slot: SkillInputSlot) -> None:
    if binding.requested_format_id not in slot.accepted_view_formats:
        raise AnalysisPlanResolutionError(
            f"view format {binding.requested_format_id!r} is not accepted by slot {slot.slot_id!r}"
        )


def _selected_metadata_parameter(value: object, *, parameter_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        fields = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        fields = tuple(value)
    else:
        raise AnalysisPlanResolutionError(
            f"metadata selector parameter {parameter_name!r} must be a string or sequence"
        )
    if not all(isinstance(item, str) and item for item in fields):
        raise AnalysisPlanResolutionError(
            f"metadata selector parameter {parameter_name!r} contains an invalid field name"
        )
    if len(set(fields)) != len(fields):
        raise AnalysisPlanResolutionError(
            f"metadata selector parameter {parameter_name!r} contains duplicate fields"
        )
    return fields


def validate_invocation_metadata_selections(
    bindings: tuple[ResolvedAssetBinding, ...],
    *,
    interface: ResolvedSkillInterface,
    validated_parameters: Mapping[str, object],
) -> None:
    """Cross-check dynamic metadata names without granting access to them."""

    grouped: dict[str, list[ResolvedAssetBinding]] = defaultdict(list)
    for binding in bindings:
        grouped[binding.slot.slot_id].append(binding)
    properties = interface.parameter_json_schema.get("properties")
    schema_properties = properties if isinstance(properties, dict) else {}
    for slot_bindings in grouped.values():
        slot = slot_bindings[0].slot
        selection = slot.invocation_metadata_selection
        if selection is None:
            continue
        if selection.parameter_name not in schema_properties:
            raise AnalysisPlanResolutionError(
                f"resolved parameter schema omits metadata selector {selection.parameter_name!r}"
            )
        if selection.parameter_name not in validated_parameters:
            raise AnalysisPlanResolutionError(
                f"validated parameters omit metadata selector {selection.parameter_name!r}"
            )
        static_metadata = {
            field
            for requirement in (*slot.required_information, *slot.optional_information)
            if requirement.information_class == "metadata"
            for field in requirement.fields
        }
        requested_metadata = {
            field
            for resolved in slot_bindings
            for requirement in resolved.plan_binding.requested_information
            if requirement.information_class == "metadata"
            for field in requirement.fields
        }
        dynamic_metadata = requested_metadata - static_metadata
        if not (selection.minimum_fields <= len(dynamic_metadata) <= selection.maximum_fields):
            raise AnalysisPlanResolutionError(
                f"slot {slot.slot_id!r} dynamically requests {len(dynamic_metadata)} metadata "
                "fields outside its declared bounds"
            )
        parameter_fields = set(
            _selected_metadata_parameter(
                validated_parameters[selection.parameter_name],
                parameter_name=selection.parameter_name,
            )
        )
        if parameter_fields != dynamic_metadata:
            raise AnalysisPlanResolutionError(
                f"metadata selector {selection.parameter_name!r} does not exactly match "
                f"the dynamically requested fields for slot {slot.slot_id!r}"
            )


def _bind_invocation(
    invocation: PlannedSkillInvocation
    | PlannedGeneratedProgramInvocation
    | PlannedGeneratedExperimentSkillInvocation,
    *,
    input_slots: tuple[SkillInputSlot, ...],
    assets: dict[str, AnalysisAsset],
) -> tuple[ResolvedAssetBinding, ...]:
    slots = {slot.slot_id: slot for slot in input_slots}
    grouped: dict[str, list[PlannedAssetBinding]] = defaultdict(list)
    resolved: list[ResolvedAssetBinding] = []
    for binding in invocation.bindings:
        slot = slots.get(binding.slot_id)
        if slot is None:
            raise AnalysisPlanResolutionError(
                f"binding {binding.binding_id!r} references unknown slot {binding.slot_id!r}"
            )
        asset = assets.get(binding.asset_id)
        if asset is None:
            raise AnalysisPlanResolutionError(
                f"binding {binding.binding_id!r} references unknown asset {binding.asset_id!r}"
            )
        # An ``infer`` binding names the immutable model that produces the
        # slot's prediction view.  The slot contract describes what the skill
        # receives (``predictions``), not the source artifact used to create
        # it.  Ordinary bindings continue to match their source asset type
        # directly.
        delivered_asset_type = "predictions" if binding.operation == "infer" else asset.asset_type
        if delivered_asset_type not in slot.accepted_asset_types:
            raise AnalysisPlanResolutionError(
                f"delivered asset type {delivered_asset_type!r} is not accepted by slot "
                f"{slot.slot_id!r}"
            )
        validate_binding_format(binding, slot)
        if asset.split_id != invocation.sampling_plan.split_id:
            raise AnalysisPlanResolutionError(
                f"binding {binding.binding_id!r} is not on the invocation selection split"
            )
        validate_binding_information(binding, slot)
        inference_inputs: list[ResolvedInferenceInputBinding] = []
        if binding.operation == "infer":
            if not isinstance(asset.location, TrainedModelArtifactLocation):
                raise AnalysisPlanResolutionError(
                    "historical inference requires a trained-model artifact location"
                )
            contract = asset.location.artifact.model_io_contract.inference
            assert contract is not None
            configuration = binding.inference_configuration
            assert configuration is not None
            if binding.requested_format_id != contract.prediction_output_format:
                raise AnalysisPlanResolutionError(
                    "inference prediction format differs from the model I/O contract"
                )
            if configuration.determinism != contract.determinism:
                raise AnalysisPlanResolutionError(
                    "inference determinism differs from the model I/O contract"
                )
            expected_information = {
                item.information_class: set(item.fields) for item in contract.required_information
            }
            for nested in binding.inference_inputs:
                input_asset = assets.get(nested.asset_id)
                if input_asset is None:
                    raise AnalysisPlanResolutionError(
                        f"inference input binding {nested.binding_id!r} references unknown asset"
                    )
                if input_asset.asset_type == "trained_model":
                    raise AnalysisPlanResolutionError("a model cannot be its own inference input")
                if input_asset.split_id != invocation.sampling_plan.split_id:
                    raise AnalysisPlanResolutionError(
                        "historical inference input is not on the invocation selection split"
                    )
                if nested.requested_format_id not in contract.accepted_input_view_formats:
                    raise AnalysisPlanResolutionError(
                        "inference input format is not accepted by the model I/O contract"
                    )
                requested = _requirements_by_class(nested.requested_information)
                if requested != expected_information:
                    raise AnalysisPlanResolutionError(
                        "inference input information must exactly match the model I/O contract"
                    )
                inference_inputs.append(
                    ResolvedInferenceInputBinding(plan_binding=nested, asset=input_asset)
                )
        grouped[slot.slot_id].append(binding)
        resolved.append(
            ResolvedAssetBinding(
                plan_binding=binding,
                slot=slot,
                asset=asset,
                inference_inputs=tuple(inference_inputs),
            )
        )

    for slot in slots.values():
        count = len(grouped[slot.slot_id])
        if slot.required and count == 0:
            raise AnalysisPlanResolutionError(f"required input slot {slot.slot_id!r} is unbound")
        if slot.cardinality == "one" and count > 1:
            raise AnalysisPlanResolutionError(
                f"single-cardinality input slot {slot.slot_id!r} has multiple bindings"
            )
    return tuple(resolved)


def resolve_analysis_plan(
    plan: AnalysisPlan,
    *,
    analysis_input: DataAnalysisInput,
    discovery: DiscoverySnapshot,
    resolved_interfaces: Mapping[str, ResolvedSkillInterface],
    control_root: Path,
    generated_program_root: Path | None = None,
) -> tuple[ResolvedAnalysisInvocation, ...]:
    """Bind and validate every invocation before authorization or materialization."""

    if plan.input_digest != canonical_sha256(analysis_input):
        raise AnalysisPlanResolutionError("plan input digest does not match DataAnalysisInput")
    if plan.access_policy_digest != canonical_sha256(analysis_input.access_policy):
        raise AnalysisPlanResolutionError("plan access-policy digest does not match the input")
    if plan.discovery_snapshot_digest != discovery.snapshot_digest:
        raise AnalysisPlanResolutionError("plan discovery digest does not match enabled packs")
    expected_questions = {
        question.question_id for question in analysis_input.analysis_brief.questions
    }
    if set(plan.questions) != expected_questions:
        raise AnalysisPlanResolutionError("plan questions must exactly match the analysis brief")

    skills = {skill.card.skill_id: skill for skill in discovery.skills}
    assets = {asset.asset_id: asset for asset in analysis_input.available_assets}
    resolved: list[ResolvedAnalysisInvocation] = []
    for invocation in plan.invocations:
        sampling = invocation.sampling_plan.policy
        if sampling.strategy == "stratified" and not analysis_input.access_policy.permits(
            split_id=invocation.sampling_plan.split_id,
            information_class="metadata",
            source_fields=sampling.strata_fields,
        ):
            raise AnalysisPlanResolutionError(
                "stratified sampling fields are not visible under the access policy"
            )
        if isinstance(invocation, PlannedGeneratedProgramInvocation):
            if generated_program_root is None:
                raise AnalysisPlanResolutionError(
                    "plan references a generated program without an experiment-local store"
                )
            try:
                program, source_path = load_generated_program(
                    root=generated_program_root,
                    identity=invocation.program_identity,
                )
                parameters = validate_generated_parameters(
                    program.parameters,
                    invocation.arguments,
                )
            except ValueError as exc:
                raise AnalysisPlanResolutionError(str(exc)) from exc
            if not set(invocation.question_ids).issubset(program.question_ids):
                raise AnalysisPlanResolutionError(
                    "generated invocation questions exceed its persisted declaration"
                )
            if (
                program.resource_request.wall_time_s
                > analysis_input.resource_envelope.per_skill_timeout_s
            ):
                raise AnalysisPlanResolutionError(
                    "generated program wall-time request exceeds the resource envelope"
                )
            if (
                analysis_input.resource_envelope.max_host_memory_gb is not None
                and program.resource_request.max_host_memory_gb
                > analysis_input.resource_envelope.max_host_memory_gb
            ):
                raise AnalysisPlanResolutionError(
                    "generated program memory request exceeds the resource envelope"
                )
            bindings = _bind_invocation(
                invocation,
                input_slots=program.input_slots,
                assets=assets,
            )
            _validate_source_scope(
                bindings,
                analysis_input=analysis_input,
                strata_fields=sampling.strata_fields if sampling.strategy == "stratified" else (),
            )
            validated = ValidatedParameters(
                parameters=parameters,
                parameter_schema_sha256=program.parameter_schema_sha256(),
                validated_parameters_sha256=canonical_sha256(parameters),
            )
            resolved.append(
                ResolvedGeneratedProgramInvocation(
                    invocation=invocation,
                    program=program,
                    source_path=source_path,
                    bindings=bindings,
                    validated_parameters=validated,
                )
            )
            continue
        if isinstance(invocation, PlannedGeneratedExperimentSkillInvocation):
            skill = skills.get(invocation.skill_id)
            if not isinstance(skill, DiscoveredGeneratedExperimentSkill):
                raise AnalysisPlanResolutionError(
                    f"invocation references no generated experiment skill {invocation.skill_id!r}"
                )
            try:
                program, source_path = load_generated_program(
                    root=Path(skill.registry_root),
                    identity=skill.program_identity,
                )
                parameters = validate_generated_parameters(program.parameters, invocation.arguments)
            except ValueError as exc:
                raise AnalysisPlanResolutionError(str(exc)) from exc
            if invocation.expected_time_cost != skill.card.time_cost:
                raise AnalysisPlanResolutionError(
                    "generated skill time-cost hint differs from its SkillCard"
                )
            if invocation.expected_memory_cost != skill.card.memory_cost:
                raise AnalysisPlanResolutionError(
                    "generated skill memory-cost hint differs from its SkillCard"
                )
            if (
                program.resource_request.wall_time_s
                > analysis_input.resource_envelope.per_skill_timeout_s
            ):
                raise AnalysisPlanResolutionError(
                    "generated skill wall-time request exceeds the resource envelope"
                )
            if (
                analysis_input.resource_envelope.max_host_memory_gb is not None
                and program.resource_request.max_host_memory_gb
                > analysis_input.resource_envelope.max_host_memory_gb
            ):
                raise AnalysisPlanResolutionError(
                    "generated skill memory request exceeds the resource envelope"
                )
            bindings = _bind_invocation(
                invocation,
                input_slots=skill.card.input_slots,
                assets=assets,
            )
            _validate_source_scope(
                bindings,
                analysis_input=analysis_input,
                strata_fields=sampling.strata_fields if sampling.strategy == "stratified" else (),
            )
            validated = ValidatedParameters(
                parameters=parameters,
                parameter_schema_sha256=skill.resolved_interface.parameter_schema_sha256,
                validated_parameters_sha256=canonical_sha256(parameters),
            )
            resolved.append(
                ResolvedGeneratedExperimentSkillInvocation(
                    invocation=invocation,
                    skill=skill,
                    program=program,
                    source_path=source_path,
                    bindings=bindings,
                    validated_parameters=validated,
                )
            )
            continue
        skill = skills.get(invocation.skill_id)
        if skill is None or isinstance(skill, DiscoveredGeneratedExperimentSkill):
            raise AnalysisPlanResolutionError(
                f"invocation references undiscovered skill {invocation.skill_id!r}"
            )
        interface = resolved_interfaces.get(invocation.skill_id)
        if interface is None or interface.skill_identity != skill.identity:
            raise AnalysisPlanResolutionError(
                f"invocation lacks the exact resolved interface for {invocation.skill_id!r}"
            )
        if invocation.expected_time_cost != skill.card.time_cost:
            raise AnalysisPlanResolutionError(
                "invocation time-cost hint differs from its skill card"
            )
        if invocation.expected_memory_cost != skill.card.memory_cost:
            raise AnalysisPlanResolutionError(
                "invocation memory-cost hint differs from its skill card"
            )
        if not skill.card.supports_sampling and (
            sampling.mode != "full_if_feasible"
            or sampling.max_items is not None
            or sampling.fraction is not None
        ):
            raise AnalysisPlanResolutionError(
                f"skill {skill.card.skill_id!r} does not support sampled execution"
            )
        bindings = _bind_invocation(
            invocation,
            input_slots=skill.card.input_slots,
            assets=assets,
        )
        _validate_source_scope(
            bindings,
            analysis_input=analysis_input,
            strata_fields=sampling.strata_fields if sampling.strategy == "stratified" else (),
        )
        validated = validate_skill_parameters(
            skill,
            interface,
            invocation.arguments,
            control_directory=control_root / f"validate-{invocation.invocation_id}",
            timeout_s=min(
                analysis_input.resource_envelope.per_skill_timeout_s,
                analysis_input.resource_envelope.wall_time_budget_s,
            ),
            max_host_memory_gb=analysis_input.resource_envelope.max_host_memory_gb,
        )
        validate_invocation_metadata_selections(
            bindings,
            interface=interface,
            validated_parameters=validated.parameters,
        )
        resolved.append(
            ResolvedPlannedInvocation(
                invocation=invocation,
                skill=skill,
                bindings=bindings,
                validated_parameters=validated,
            )
        )
    return tuple(resolved)
