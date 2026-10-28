"""Pure route evaluator: one declared ``Branch`` over one verified native record.

The decision is a function of an explicit typed input only: the branch, a
projection of the source node's committed record and the run metric. It never
reads ``ChainState`` or native history and never dispatches; readiness consumes
the output (skip semantics are a separate owner). A metric comparison goes only
through ``MetricOrder``; direction is never inferred from a name.
"""

import hashlib
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

from execute_tools.evaluation_metric import MetricSpec, StampedMetricSpec, reconcile_metric_specs
from execute_tools.metric_order import MetricOrder
from workflows.definition.catalog import CAPABILITIES, CONTRACTS, ROUTE_OBSERVABLES
from workflows.definition.models import (
    AllOf,
    AnyOf,
    BoolIs,
    Branch,
    EnumIn,
    IsMissing,
    MetricAtLeast,
    Not,
    RoutePredicate,
)
from workflows.definition.routes import route_entries

from .loop_stop import StopModel

RouteValue = bool | str | Annotated[float, Field(allow_inf_nan=False)] | None
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class RouteConditionError(ValueError):
    """A route cannot be evaluated; the body fails rather than treat it as false."""


class RouteObservation(StopModel):
    """Projection of one verified native record; only the observables a branch reads."""

    source_node: str
    iteration: int = Field(gt=0)
    record_sha256: Sha256  # binds the decision to the native record bytes
    values: tuple[tuple[str, RouteValue], ...]
    metric_spec: MetricSpec | None  # the record's own stamp, never a second authority

    @model_validator(mode="after")
    def _unique(self) -> Self:
        ids = [observable for observable, _ in self.values]
        if len(set(ids)) != len(ids):
            raise ValueError("route observation repeats an observable")
        return self


class RouteEvaluationInput(StopModel):
    branch: Branch
    observation: RouteObservation
    metric: MetricSpec | None  # the run metric admitted before dispatch

    @model_validator(mode="after")
    def _same_source(self) -> Self:
        if self.observation.source_node != self.branch.source.node:
            raise ValueError("route observation was not projected from the branch source")
        return self


class RouteEvaluationOutput(StopModel):
    branch_id: str
    selected_case: int | None = Field(ge=0)  # None: the default arm, or no arm without one
    selected_targets: tuple[str, ...]
    skipped_targets: tuple[str, ...]
    # One predicate outcome per case, in declared order, up to and including the match.
    leaf_results: tuple[bool, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _first_match(self) -> Self:
        *earlier, last = self.leaf_results
        matched = self.selected_case is not None
        if any(earlier) or last != matched:
            raise ValueError("route outcomes must end at the first matching case")
        if matched and self.selected_case != len(earlier):
            raise ValueError("selected case must be the first matching case")
        if set(self.selected_targets) & set(self.skipped_targets):
            raise ValueError("a route target cannot be both selected and skipped")
        return self


def _leaves(predicate: RoutePredicate) -> tuple[BoolIs | EnumIn | MetricAtLeast | IsMissing, ...]:
    if isinstance(predicate, (AllOf, AnyOf)):
        return predicate.terms
    if isinstance(predicate, Not):
        return (predicate.term,)
    return (predicate,)


def admit_route_metrics(branches: tuple[Branch, ...], metric: MetricSpec | None) -> None:
    """The one identity check: every ``metric_at_least`` names the run metric.

    Called before any dispatch and again by ``evaluate_route`` over ALL cases, so an
    earlier matching case cannot hide an unevaluable later one.
    """
    for branch in branches:
        for index, case in enumerate(branch.cases):
            for leaf in _leaves(case.when):
                if not isinstance(leaf, MetricAtLeast):
                    continue
                if metric is None:
                    raise RouteConditionError(
                        f"route {branch.id} case {index} (metric_at_least) requires a run "
                        "metric; none is bound"
                    )
                if leaf.metric_id != metric.id:
                    raise RouteConditionError(
                        f"route {branch.id} case {index} (metric_at_least) names metric "
                        f"{leaf.metric_id!r}; the run metric is {metric.id!r}"
                    )


def evaluate_route(value: RouteEvaluationInput) -> RouteEvaluationOutput:
    """Pure decision for one branch; the first matching case in declared order wins."""
    branch = value.branch
    admit_route_metrics((branch,), value.metric)
    order: MetricOrder | None = None
    if value.metric is not None:
        try:
            reconcile_metric_specs(
                [
                    StampedMetricSpec(
                        label="the route source record", spec=value.observation.metric_spec
                    )
                ],
                bound=value.metric,
            )
        except ValueError as error:
            raise RouteConditionError(f"route {branch.id}: {error}") from error
        order = MetricOrder(value.metric)
    values = dict(value.observation.values)
    outcomes: list[bool] = []
    for case in branch.cases:
        outcomes.append(_holds(branch.id, case.when, values, order))
        if outcomes[-1]:
            break
    selected = len(outcomes) - 1 if outcomes[-1] else None
    entries = route_entries(branch)
    # Entry index of the arm that runs: the matched case, else the default if declared.
    chosen = selected if selected is not None else len(branch.cases)
    return RouteEvaluationOutput(
        branch_id=branch.id,
        selected_case=selected,
        selected_targets=entries[chosen] if chosen < len(entries) else (),
        skipped_targets=tuple(
            target for index, entry in enumerate(entries) if index != chosen for target in entry
        ),
        leaf_results=tuple(outcomes),
    )


def _holds(
    branch: str,
    predicate: RoutePredicate,
    values: dict[str, RouteValue],
    order: MetricOrder | None,
) -> bool:
    if isinstance(predicate, AllOf):
        return all(_leaf(branch, term, values, order) for term in predicate.terms)
    if isinstance(predicate, AnyOf):
        # Every leaf is evaluated, so an unevaluable later leaf is never masked.
        return any([_leaf(branch, term, values, order) for term in predicate.terms])
    if isinstance(predicate, Not):
        return not _leaf(branch, predicate.term, values, order)
    return _leaf(branch, predicate, values, order)


def _leaf(
    branch: str,
    leaf: BoolIs | EnumIn | MetricAtLeast | IsMissing,
    values: dict[str, RouteValue],
    order: MetricOrder | None,
) -> bool:
    if leaf.observable not in values:
        raise RouteConditionError(f"route {branch}: observation lacks {leaf.observable!r}")
    observed = values[leaf.observable]
    match leaf:
        case BoolIs() if isinstance(observed, bool):
            return observed is leaf.value
        case EnumIn() if isinstance(observed, str):
            return observed in leaf.values
        case IsMissing() if observed is None or isinstance(observed, float):
            return observed is None
        case MetricAtLeast() if observed is None:
            return False  # an absent metric is false, never an error (decision B1-Q4)
        case MetricAtLeast() if isinstance(observed, float):
            assert order is not None  # admit_route_metrics bound the run metric
            return order.is_at_least(observed, leaf.threshold)
        case _:
            raise RouteConditionError(
                f"route {branch}: {leaf.kind} cannot read {type(observed).__name__} "
                f"from {leaf.observable!r}"
            )


def _native_model(contract: str) -> type[BaseModel]:
    """The native output schema owning ``contract``; lazy, as for every native record."""
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput
    from agent.schemas.validator import ValidatorOutput

    model = {"validation.output": ValidatorOutput, "tuning.output": HyperparamTuningOutput}.get(
        contract
    )
    if model is None or CONTRACTS[contract] != f"{model.__module__}.{model.__name__}":
        raise RouteConditionError(f"no route projection owns contract {contract!r}")
    return model


def project_observation(
    branch: Branch, capability: str, record_path: Path, *, iteration: int
) -> RouteObservation:
    """Project the observables ``branch`` reads from the source node's native record.

    ``capability`` is the declared capability of ``branch.source.node``. The digest
    covers exactly the bytes parsed; the verifier re-projects the same record and
    requires equality.
    """
    from .graph_evidence import read_graph_control

    contract = CAPABILITIES[capability].output
    model = _native_model(contract)
    payload = read_graph_control(record_path)
    record = model.model_validate_json(payload)
    read: list[str] = []
    for case in branch.cases:
        for leaf in _leaves(case.when):
            if leaf.observable not in read:
                read.append(leaf.observable)
    values: list[tuple[str, RouteValue]] = []
    for observable in read:
        entry = ROUTE_OBSERVABLES.get(observable)
        if entry is None or entry.contract != contract:
            raise RouteConditionError(f"route {branch.id}: {observable!r} is not on {contract}")
        values.append((observable, getattr(record, entry.field.rpartition(".")[2])))
    return RouteObservation(
        source_node=branch.source.node,
        iteration=iteration,
        record_sha256=hashlib.sha256(payload).hexdigest(),
        values=tuple(values),
        metric_spec=getattr(record, "metric_spec", None),
    )


__all__ = [
    "RouteConditionError",
    "RouteEvaluationInput",
    "RouteEvaluationOutput",
    "RouteObservation",
    "admit_route_metrics",
    "evaluate_route",
    "project_observation",
]
