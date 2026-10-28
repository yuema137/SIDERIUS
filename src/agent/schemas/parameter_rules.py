"""Typed rules that constrain resolved experiment-plan parameters.

Rules are keyed by dotted paths into :class:`ExperimentPlan`.  An omitted
path remains agent-controlled.  ``exact`` replaces the authored value; the
other rule kinds validate the authored value without choosing one for the
agent.

Predicate declarations name a registered callable.  Configuration never
contains executable Python expressions: raw lambdas are neither reproducible
nor safe to load from an experiment manifest.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from copy import deepcopy
from types import UnionType
from typing import Annotated, Any, Union, get_args, get_origin

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

ParameterPredicate = Callable[[Any], bool]

_PREDICATES: dict[str, ParameterPredicate] = {}


class ParameterRuleError(ValueError):
    """A parameter-rule declaration or effective value is invalid."""


def _model_path_exists(annotation: Any, parts: list[str]) -> bool:
    """Recognize fields from their consuming models, including optional unions."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return _model_path_exists(get_args(annotation)[0], parts)
    if origin in (Union, UnionType):
        return any(_model_path_exists(branch, parts) for branch in get_args(annotation))
    if not isinstance(annotation, type) or not issubclass(annotation, BaseModel):
        return False
    field = annotation.model_fields.get(parts[0])
    if field is None:
        return False
    return len(parts) == 1 or _model_path_exists(field.annotation, parts[1:])


def _validate_training_rule_path(path: str, parts: list[str]) -> None:
    """Keep fixed training targets aligned with the actual execution schema."""
    if parts[0] != "train_config":
        return
    from ml_models.models_format_sandbox import TrainConfig

    if not _model_path_exists(TrainConfig, parts[1:]):
        raise ParameterRuleError(
            f"unsupported training parameter path {path!r}: target must exist in "
            "TrainConfig or one of its nested configuration models; check the "
            "training fields in the task-composition parameter-rule contract"
        )


def _validate_parameter_path(path: str) -> None:
    """Validate declaration syntax and fixed-contract target membership."""
    parts = path.split(".")
    if any(not part or not part.isidentifier() for part in parts):
        raise ParameterRuleError(f"invalid parameter path {path!r}")
    if len(parts) < 2 or parts[0] not in {"model_config", "train_config", "loss_config"}:
        raise ParameterRuleError(
            f"parameter path {path!r} must target a leaf under "
            "model_config, train_config, or loss_config"
        )
    _validate_training_rule_path(path, parts)


def register_parameter_predicate(name: str, predicate: ParameterPredicate) -> None:
    """Register a deterministic predicate under a stable task-owned name."""
    normalized = name.strip()
    if not normalized:
        raise ParameterRuleError("parameter predicate name must not be empty")
    if normalized in _PREDICATES and _PREDICATES[normalized] is not predicate:
        raise ParameterRuleError(f"parameter predicate {normalized!r} is already registered")
    _PREDICATES[normalized] = predicate


def _is_odd_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value % 2 == 1


def _is_even_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value % 2 == 0


register_parameter_predicate("odd_integer", _is_odd_integer)
register_parameter_predicate("even_integer", _is_even_integer)


class NumericRange(BaseModel):
    """Inclusive numeric interval for one resolved parameter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Strict bounds: lax coercion would silently read ``true`` as 1.0 or "3" as
    # 3.0, while the enforced parameter value itself must be a non-bool number.
    min: float | None = Field(default=None, strict=True)
    max: float | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def validate_interval(self) -> NumericRange:
        if self.min is None and self.max is None:
            raise ValueError("range must declare min, max, or both")
        if self.min is not None and not math.isfinite(self.min):
            raise ValueError("range.min must be finite")
        if self.max is not None and not math.isfinite(self.max):
            raise ValueError("range.max must be finite")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("range.min must be less than or equal to range.max")
        return self


class ParameterRule(BaseModel):
    """Exactly one constraint on one dotted ExperimentPlan path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exact: Any = None
    range: NumericRange | None = None
    allowed: tuple[Any, ...] | None = None
    predicate: str | None = None

    @model_validator(mode="before")
    @classmethod
    def require_one_rule_kind(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            raise ValueError("parameter rule must be a mapping")
        present = [key for key in ("exact", "range", "allowed", "predicate") if key in value]
        if len(present) != 1:
            raise ValueError(
                "parameter rule must declare exactly one of exact, range, allowed, predicate"
            )
        return value

    @model_validator(mode="after")
    def validate_rule(self) -> ParameterRule:
        # Only ``exact`` may carry null. A null range/allowed/predicate would
        # otherwise fall through ``kind`` and silently become an exact-null lock.
        for kind in ("range", "allowed", "predicate"):
            if kind in self.model_fields_set and getattr(self, kind) is None:
                raise ValueError(
                    f"{kind} rule must not be null; declare {{'exact': null}} to lock a null value"
                )
        if self.allowed is not None and not self.allowed:
            raise ValueError("allowed must contain at least one value")
        if self.predicate is not None and not self.predicate.strip():
            raise ValueError("predicate name must not be empty")
        return self

    @property
    def kind(self) -> str:
        if self.range is not None:
            return "range"
        if self.allowed is not None:
            return "allowed"
        if self.predicate is not None:
            return "predicate"
        return "exact"

    @model_serializer(mode="wrap")
    def serialize_active_kind(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Keep the one-of declaration intact through parent model dump/revalidation.

        The default Pydantic dump includes three inactive null fields.  Those
        fields are not part of the authored rule and make a later strict
        validation fail, especially at typed Proposer evidence fan-in edges.
        The active kind alone is the canonical wire representation; this also
        preserves the distinct valid ``{"exact": null}`` declaration.
        """
        serialized = handler(self)
        if "exact" in self.model_fields_set and self.exact is None:
            # Parent null filtering must not erase an explicitly locked null value.
            return {"exact": None}
        return {self.kind: serialized[self.kind]}


class ParameterRules(BaseModel):
    """A closed, immutable set of dotted-path parameter constraints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rules: dict[str, ParameterRule] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_direct_mapping(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "rules" not in value:
            return {"rules": dict(value)}
        return value

    @model_validator(mode="after")
    def validate_paths(self) -> ParameterRules:
        for path in self.rules:
            _validate_parameter_path(path)
        return self


def _read_path(document: Mapping[str, Any], path: str) -> Any:
    current: Any = document
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise ParameterRuleError(f"parameter path {path!r} does not exist in ExperimentPlan")
        current = current[part]
    return current


def _write_path(document: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current: dict[str, Any] = document
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            raise ParameterRuleError(f"parameter path {path!r} does not exist in ExperimentPlan")
        current = child
    current[parts[-1]] = value


def _validate_value(path: str, value: Any, rule: ParameterRule, owner: str) -> None:
    if rule.range is not None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ParameterRuleError(
                f"{owner} parameter rule for {path!r} requires a numeric value; got {value!r}"
            )
        if rule.range.min is not None and value < rule.range.min:
            raise ParameterRuleError(
                f"{owner} parameter rule for {path!r} requires value >= {rule.range.min}; got {value!r}"
            )
        if rule.range.max is not None and value > rule.range.max:
            raise ParameterRuleError(
                f"{owner} parameter rule for {path!r} requires value <= {rule.range.max}; got {value!r}"
            )
    elif rule.allowed is not None and value not in rule.allowed:
        raise ParameterRuleError(
            f"{owner} parameter rule for {path!r} allows {list(rule.allowed)!r}; got {value!r}"
        )
    elif rule.predicate is not None:
        predicate = _PREDICATES.get(rule.predicate)
        if predicate is None:
            raise ParameterRuleError(
                f"{owner} parameter rule for {path!r} names unregistered predicate "
                f"{rule.predicate!r}"
            )
        try:
            accepted = predicate(value)
        except Exception as exc:
            raise ParameterRuleError(
                f"predicate {rule.predicate!r} raised for {path!r}: {type(exc).__name__}: {exc}"
            ) from exc
        if accepted is not True:
            raise ParameterRuleError(
                f"{owner} predicate {rule.predicate!r} rejected {path!r}={value!r}"
            )


def apply_parameter_rules(
    plan: Any,
    *,
    task_rules: ParameterRules | None = None,
    workflow_rules: ParameterRules | None = None,
) -> Any:
    """Apply exact locks and validate every task/workflow constraint.

    Task and workflow declarations are peers at enforcement time: all rules
    must hold.  A workflow may therefore narrow a task constraint but cannot
    overwrite or bypass it.
    """
    from agent.schemas.hyperparam_tuning import ExperimentPlan

    document = resolve_parameter_rule_document(
        plan.model_dump(by_alias=True),
        task_rules=task_rules,
        workflow_rules=workflow_rules,
    )
    try:
        return ExperimentPlan.model_validate(document)
    except Exception as exc:
        raise ParameterRuleError(
            f"parameter rules produced an invalid effective ExperimentPlan: {exc}"
        ) from exc


def resolve_parameter_rule_document(
    document: Mapping[str, Any],
    *,
    task_rules: ParameterRules | None = None,
    workflow_rules: ParameterRules | None = None,
    defer_missing_non_exact: bool = False,
) -> dict[str, Any]:
    """Resolve the same typed rules on a plan or proposal baseline mapping.

    The caller owns its resulting schema. This function never mutates the
    authored input: exact rules create effective values in the returned copy,
    while other rule kinds only validate existing values. A proposal baseline
    may defer an omitted non-exact field until the tuner chooses it; the tuner
    itself uses the strict default and must validate the effective plan.
    """
    declarations = (
        ("task", task_rules or ParameterRules()),
        ("workflow", workflow_rules or ParameterRules()),
    )
    # Frozen models can still contain a mutated rules dictionary. Recheck at
    # this shared execution boundary, including proposal-baseline resolution.
    resolved = deepcopy(dict(document))
    paths = {path for _, rules in declarations for path in rules.rules}
    for path in paths:
        _validate_parameter_path(path)
    for path in sorted(paths):
        exact_values = [
            rule.exact
            for _, rules in declarations
            for rule_path, rule in rules.rules.items()
            if rule_path == path and rule.kind == "exact"
        ]
        if exact_values and any(value != exact_values[0] for value in exact_values[1:]):
            raise ParameterRuleError(
                f"task and workflow exact rules conflict for {path!r}: {exact_values!r}"
            )
        if exact_values:
            _write_path(resolved, path, exact_values[0])
        try:
            value = _read_path(resolved, path)
        except ParameterRuleError:
            if defer_missing_non_exact and not exact_values:
                continue
            raise
        for owner, rules in declarations:
            rule = rules.rules.get(path)
            if rule is not None:
                _validate_value(path, value, rule, owner)
    return resolved


def validate_parameter_rule_ownership(
    *,
    objective_declared: bool,
    task_rules: ParameterRules | None,
    workflow_rules: ParameterRules | None,
) -> None:
    """Keep task-owned objectives from competing with loss parameter rules."""
    if not objective_declared:
        return
    if any(
        path == "loss_config" or path.startswith("loss_config.")
        for rules in (task_rules, workflow_rules)
        if rules is not None
        for path in rules.rules
    ):
        raise ParameterRuleError(
            "parameter_rules must not constrain loss_config when the task declares "
            "an authoritative objective; the objective is the sole owner of loss semantics"
        )
