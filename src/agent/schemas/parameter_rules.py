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
from collections.abc import Callable, Iterable, Mapping
from copy import deepcopy
from types import UnionType
from typing import Annotated, Any, Literal, Union, get_args, get_origin

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


def _target_annotations(annotation: Any, parts: list[str]) -> list[Any]:
    """Leaf annotations that consume ``parts`` in a model, across optional unions.

    An empty result means no consuming field exists. A model with
    ``extra="allow"`` keeps unknown keys, so they are consumed as ``Any``.
    """
    origin = get_origin(annotation)
    if origin is Annotated:
        return _target_annotations(get_args(annotation)[0], parts)
    if origin in (Union, UnionType):
        return [
            leaf for branch in get_args(annotation) for leaf in _target_annotations(branch, parts)
        ]
    if not isinstance(annotation, type) or not issubclass(annotation, BaseModel):
        return []
    field = annotation.model_fields.get(parts[0])
    if field is None:
        return [Any] if annotation.model_config.get("extra") == "allow" else []
    if len(parts) == 1:
        return [field.annotation]
    return _target_annotations(field.annotation, parts[1:])


def _admits_bool(annotation: Any) -> bool:
    """Whether a field type keeps a boolean as a boolean instead of coercing it."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return _admits_bool(get_args(annotation)[0])
    if origin in (Union, UnionType):
        return any(_admits_bool(branch) for branch in get_args(annotation))
    if origin is Literal:
        return any(isinstance(value, bool) for value in get_args(annotation))
    return annotation is Any or annotation is bool


def _fixed_rule_schemas() -> dict[str, type[BaseModel]]:
    """Consuming execution schema for each closed rule root.

    ``model_config`` is absent: its consuming schema is the executed model's
    configuration class, known only per plan (see
    :func:`_validate_model_rule_paths`). Custom-loss plugin hyperparameters
    are not transported through ``loss_config``; ``LossConfig`` is the
    complete loss-routing surface.
    """
    from ml_models.models_format_sandbox import LossConfig, TrainConfig

    return {"train_config": TrainConfig, "loss_config": LossConfig}


def _validate_rule_target(
    path: str,
    parts: list[str],
    schema: type[BaseModel],
    rules: Iterable[ParameterRule],
) -> None:
    """Refuse a rule the consuming schema would silently drop or reinterpret."""
    leaves = _target_annotations(schema, parts[1:])
    if not leaves:
        raise ParameterRuleError(
            f"unsupported {parts[0]} parameter path {path!r}: target must exist in "
            f"{schema.__name__} or one of its nested configuration models; check the "
            f"{parts[0]} fields in the task-composition parameter-rule contract"
        )
    if any(_admits_bool(leaf) for leaf in leaves):
        return
    for rule in rules:
        declared = [rule.exact] if rule.kind == "exact" else list(rule.allowed or ())
        if any(isinstance(value, bool) for value in declared):
            raise ParameterRuleError(
                f"{rule.kind} parameter rule for {path!r} declares a boolean, but the "
                f"{schema.__name__} field type does not admit a boolean (a numeric field "
                "would coerce it to 1 or 0); declare a value of the field's type"
            )


def _validate_fixed_rule_path(path: str, parts: list[str], rules: Iterable[ParameterRule]) -> None:
    """Keep fixed training and loss targets aligned with their execution schema."""
    schema = _fixed_rule_schemas().get(parts[0])
    if schema is not None:
        _validate_rule_target(path, parts, schema, rules)


def _validate_model_rule_paths(
    resolved: dict[str, Any],
    declarations: tuple[tuple[str, ParameterRules], ...],
    executed_model_type: Any,
    *,
    defer_unknown_model: bool,
) -> None:
    """Bind ``model_config`` rules to the model that will actually execute.

    The executed model is chosen by ``force_model`` or the plan's top-level
    ``model_type``; the planner overwrites the nested ``model_config.model_type``
    mirror with it before execution. A ``model_config.model_type`` rule is
    therefore judged against the executed type (an exact lock that disagrees
    is refused, never silently overwritten), and every other ``model_config``
    target must exist in that model's configuration class.

    Only a proposal baseline (``defer_unknown_model``) may defer when the
    model or its config class is not known yet; the tuner fails closed.
    """
    paths = sorted(
        {
            path
            for _, rules in declarations
            for path in rules.rules
            if path.startswith("model_config.")
        }
    )
    if not paths:
        return
    if not isinstance(executed_model_type, str):
        if defer_unknown_model:
            return
        raise ParameterRuleError(
            f"parameter rules {paths!r} target model_config, but no executed model_type "
            "is known to check them against"
        )
    if "model_config.model_type" in paths:
        for _, rules in declarations:
            rule = rules.rules.get("model_config.model_type")
            if rule is not None and rule.kind == "exact" and rule.exact != executed_model_type:
                raise ParameterRuleError(
                    f"exact parameter rule for 'model_config.model_type' locks "
                    f"{rule.exact!r}, but the executed model is {executed_model_type!r}; the "
                    "executed model comes from force_model or the plan's model_type"
                )
        model_config = resolved.setdefault("model_config", {})
        if isinstance(model_config, dict):
            # Mirror the executed type, as the planner does, so non-exact
            # model_type rules validate the model that will run.
            model_config["model_type"] = executed_model_type
    from ml_models.models_format_sandbox import get_config_class

    schema = get_config_class(executed_model_type)
    if schema is None:
        if defer_unknown_model:
            return
        raise ParameterRuleError(
            f"parameter rules {paths!r} target model_config, but model_type "
            f"{executed_model_type!r} has no registered configuration class to check them"
        )
    for path in paths:
        if path != "model_config.model_type":
            _validate_rule_target(
                path,
                path.split("."),
                schema,
                [rules.rules[path] for _, rules in declarations if path in rules.rules],
            )


def validate_model_parameter_rules(
    model_type: str,
    *,
    task_rules: ParameterRules | None,
    workflow_rules: ParameterRules | None,
) -> None:
    """Launch-time check of ``model_config`` rules against a fixed model.

    With ``force_model`` every attempt executes this model, so a misdeclared
    lock is refused once before any attempt instead of failing each one.
    """
    declarations = (
        ("task", task_rules or ParameterRules()),
        ("workflow", workflow_rules or ParameterRules()),
    )
    _validate_model_rule_paths({}, declarations, model_type, defer_unknown_model=False)


def _validate_parameter_path(path: str, rules: Iterable[ParameterRule]) -> None:
    """Validate declaration syntax and fixed-contract target membership and type."""
    parts = path.split(".")
    if any(not part or not part.isidentifier() for part in parts):
        raise ParameterRuleError(f"invalid parameter path {path!r}")
    if len(parts) < 2 or parts[0] not in {"model_config", "train_config", "loss_config"}:
        raise ParameterRuleError(
            f"parameter path {path!r} must target a leaf under "
            "model_config, train_config, or loss_config"
        )
    _validate_fixed_rule_path(path, parts, rules)


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
        for path, rule in self.rules.items():
            _validate_parameter_path(path, (rule,))
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
    executed_model_type: str | None = None,
) -> Any:
    """Apply exact locks and validate every task/workflow constraint.

    Task and workflow declarations are peers at enforcement time: all rules
    must hold.  A workflow may therefore narrow a task constraint but cannot
    overwrite or bypass it. ``executed_model_type`` defaults to the plan's
    top-level ``model_type``.
    """
    from agent.schemas.hyperparam_tuning import ExperimentPlan

    document = resolve_parameter_rule_document(
        plan.model_dump(by_alias=True),
        task_rules=task_rules,
        workflow_rules=workflow_rules,
        executed_model_type=executed_model_type,
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
    executed_model_type: str | None = None,
) -> dict[str, Any]:
    """Resolve the same typed rules on a plan or proposal baseline mapping.

    The caller owns its resulting schema. This function never mutates the
    authored input: exact rules create effective values in the returned copy,
    while other rule kinds only validate existing values. A proposal baseline
    may defer an omitted non-exact field, and a model not yet known or
    registered, until the tuner chooses it; the tuner itself uses the strict
    default and must validate the effective plan. ``executed_model_type`` is
    the model that will run (``force_model`` or the plan's ``model_type``);
    it defaults to the document's top-level ``model_type``.
    """
    declarations = (
        ("task", task_rules or ParameterRules()),
        ("workflow", workflow_rules or ParameterRules()),
    )
    # Frozen models can still contain a mutated rules dictionary. Recheck at
    # this shared execution boundary, including proposal-baseline resolution.
    resolved = deepcopy(dict(document))
    rules_by_path: dict[str, list[ParameterRule]] = {}
    for _, rules in declarations:
        for path, rule in rules.rules.items():
            rules_by_path.setdefault(path, []).append(rule)
    paths = set(rules_by_path)
    for path, path_rules in rules_by_path.items():
        _validate_parameter_path(path, path_rules)
    if executed_model_type is None:
        executed_model_type = resolved.get("model_type")
    _validate_model_rule_paths(
        resolved,
        declarations,
        executed_model_type,
        defer_unknown_model=defer_missing_non_exact,
    )
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
