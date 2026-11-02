"""Resolve optional evaluation through existing composition code and identity owners."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from pydantic import JsonValue, TypeAdapter

from agent.schemas.judge_task import JudgeTaskDeclarations
from execute_tools.evaluation_metric import MetricSpec
from execute_tools.evaluation_registry import (
    IMPLEMENTED_CAPABILITIES,
    ComponentKindRegistration,
    EvaluationLoadContext,
    ResolvedComponent,
    builtin_registry,
    component_adapter,
    resolve_evaluation_rubric,
    validate_registration,
)
from execute_tools.evaluation_spec import (
    ComponentKinds,
    EvaluationSpec,
    RubricBalanceSelection,
    SymbolRef,
)
from execute_tools.evaluation_validation import formula_terms, inspection, validate_references

if TYPE_CHECKING:
    from workflows.task_composition import ResolvedPluginRef


@dataclass(frozen=True)
class ResolvedEvaluation:
    spec: EvaluationSpec
    registry: Mapping[str, ComponentKindRegistration]
    components: Mapping[str, ResolvedComponent]
    canonical_identity: dict[str, Any]
    required_capabilities: frozenset[str]
    plugins: tuple[ResolvedPluginRef, ...]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(
            json.dumps(
                self.canonical_identity, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()

    def inspect(self) -> dict[str, Any]:
        from workflows.evaluation_selection import selection_inspection

        return {
            **selection_inspection(self),
            **inspection(self.spec, self.components),
            "required_capabilities": sorted(self.required_capabilities),
            "identity": self.sha256,
        }


def _reject_host_paths(value: JsonValue) -> None:
    if isinstance(value, str):
        if PurePosixPath(value).is_absolute() or PureWindowsPath(value).is_absolute():
            raise ValueError(
                "evaluation fingerprint contributor must not contain absolute host paths"
            )
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_host_paths(key)
            _reject_host_paths(item)
        return
    if isinstance(value, list):
        for item in value:
            _reject_host_paths(item)


def _kind_bindings(
    section: dict[str, Any],
    ctx: EvaluationLoadContext,
) -> tuple[dict[str, ComponentKindRegistration], dict[str, JsonValue]]:
    registry = builtin_registry()
    identities: dict[str, JsonValue] = {}
    references = ComponentKinds.validate_python(section.get("component_kinds", {}))
    for name, reference in references.items():
        if name in registry:
            raise ValueError(f"component kind {name!r} cannot override a builtin")
        loaded, identity = ctx.load_symbol(reference, f"component_kinds.{name}")
        registration = validate_registration(name, loaded)
        registry[name] = registration
        identities[name] = {"source": dict(identity), "version": registration.version}
    return registry, identities


def _identity(
    spec: EvaluationSpec,
    registry: Mapping[str, ComponentKindRegistration],
    resolved: Mapping[str, ResolvedComponent],
    kinds: dict[str, JsonValue],
    ctx: EvaluationLoadContext,
) -> dict[str, Any]:
    # New defaulted fields must remain absent: schema growth is not semantic change.
    declaration = spec.model_dump(mode="json", exclude_defaults=True)
    declaration.pop("component_kinds", None)  # resolved role-bound identities replace paths
    contributions: dict[str, JsonValue] = {}
    for component in spec.components:
        registration = registry[component.kind]
        contribution = TypeAdapter(JsonValue).validate_python(
            dict(registration.fingerprint(component, resolved[component.id]))
        )
        json.dumps(contribution, allow_nan=False)  # JSON identity cannot contain NaN/Infinity.
        _reject_host_paths(contribution)
        contributions[component.id] = {
            "kind_version": registration.version,
            "resolved": contribution,
        }
    if isinstance(spec.selection, RubricBalanceSelection):
        declaration["selection"]["rubric"] = resolve_evaluation_rubric(
            spec.selection.rubric, ctx.judge_task
        ).model_dump(mode="json")
    return {"declaration": declaration, "component_kinds": kinds, "components": contributions}


def _required_capabilities(
    spec: EvaluationSpec,
    registry: Mapping[str, ComponentKindRegistration],
) -> frozenset[str]:
    capabilities = {"evaluation rendering"}
    for component in spec.components:
        capabilities.update(registry[component.kind].required_capabilities)
    if formula_terms(spec):
        capabilities.add("formula aggregation")
    if spec.constraints:
        capabilities.add("feasibility constraints")
    if isinstance(spec.selection, RubricBalanceSelection):
        capabilities.add("rubric balancing")
    return frozenset(capabilities)


def compose_evaluation(
    raw: dict[str, Any],
    manifest_dir: str,
    metrics: Mapping[str, MetricSpec],
    judge_task: JudgeTaskDeclarations | None,
) -> ResolvedEvaluation | None:
    """Resolve declarations without running measurements, arithmetic or judges."""
    from workflows.task_composition import TaskCompositionError, _load_symbol

    if "evaluation" not in raw:
        return None
    plugins: list[ResolvedPluginRef] = []

    def load(ref: SymbolRef, role: str) -> tuple[Any, Mapping[str, JsonValue]]:
        loaded, pin = _load_symbol(ref.model_dump(), manifest_dir, f"evaluation.{role}")
        assert pin is not None  # file-only refs always carry the existing content pin
        plugins.append(pin)
        identity = pin.canonical_identity()
        # Provenance retains absolute locations; evaluation identity does not.
        configured = ref.file
        if os.path.isabs(configured):
            configured = os.path.relpath(configured, manifest_dir)
        identity["configured_ref"] = os.path.normpath(configured).replace(os.sep, "/")
        return loaded, identity

    try:
        section = raw["evaluation"]
        if not isinstance(section, dict):
            raise ValueError("evaluation must be a mapping; omit it to disable evaluation")
        ctx = EvaluationLoadContext(metrics, judge_task, load)
        registry, kinds = _kind_bindings(section, ctx)
        spec = EvaluationSpec.model_validate(
            section, context={"component_adapter": component_adapter(registry)}
        )
        resolved = {c.id: registry[c.kind].load(c, ctx) for c in spec.components}
        if any(not isinstance(value, ResolvedComponent) for value in resolved.values()):
            raise ValueError("component loader must return a validated ResolvedComponent")
        validate_references(spec, registry, resolved)
        capabilities = _required_capabilities(spec, registry)
        identity = _identity(spec, registry, resolved, kinds, ctx)
        return ResolvedEvaluation(
            spec,
            MappingProxyType(registry),
            MappingProxyType(resolved),
            identity,
            frozenset(capabilities),
            tuple(plugins),
        )
    except ValueError as exc:
        raise TaskCompositionError(f"evaluation could not be composed: {exc}") from exc


def require_evaluation_runtime(evaluation: ResolvedEvaluation | None) -> None:
    if evaluation is None:
        return
    from workflows.evaluation_admission import require_component_runtime
    from workflows.task_composition import TaskCompositionError

    missing = sorted(
        name
        for name in evaluation.required_capabilities
        if not IMPLEMENTED_CAPABILITIES.get(name, False)
    )
    if missing:
        raise TaskCompositionError(
            "Evaluation composition succeeded, but launch requires unimplemented capabilities: "
            + ", ".join(missing)
            + ". Their runtime owners must land before this task can run."
        )
    # Named capability gates first: a referenced custom kind usually also needs
    # an unlanded capability, and that name is the more actionable refusal.
    try:
        require_component_runtime(evaluation)
    except ValueError as exc:
        raise TaskCompositionError(str(exc)) from exc
