"""Route decisions inside one graph body (B1-PR5): decide, cite skips, re-derive.

The worker and the verifier share these functions, so a recorded decision is a
replayable fact: the verifier re-projects the source node's committed record and
re-runs the pure evaluator (``route_eval``); readiness consumes the decisions
(``readiness``). Nothing here dispatches a node or reads ``ChainState``.
"""

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path

from core.canonical_json import canonical_json_bytes
from execute_tools.evaluation_metric import MetricSpec
from workflows.definition import ReusableWorkflowDefinition, WorkflowDefinition
from workflows.definition.routes import merge_arms, route_targets
from workflows.definition.validation import predecessor_facts

from .graph_models import GraphNodeEvidence, GraphRouteEvidence
from .readiness import MergeCandidate, MergeReadiness, NodeRouting
from .route_eval import (
    RouteConditionError,
    RouteEvaluationInput,
    admit_route_metrics,
    evaluate_route,
    project_observation,
)

Definition = WorkflowDefinition | ReusableWorkflowDefinition


def node_routing(definition: Definition) -> dict[str, NodeRouting]:
    """Readiness route facts of every routed node, projected from the declaration.

    Empty for an unrouted declaration, so readiness behaves exactly as before.
    """
    if not definition.routes:
        return {}
    targets = route_targets(definition)
    merges = merge_arms(definition, predecessor_facts(definition))
    return {
        node: NodeRouting(
            route=None if node not in targets else targets[node].branch,
            control=targets[node].source
            if node in targets and targets[node].control_only
            else None,
            merges=tuple(
                MergeReadiness(
                    branch=merge.branch,
                    candidates=tuple(
                        MergeCandidate(node=item.node, entry=item.entry)
                        for item in merge.candidates
                    ),
                )
                for merge in merges.get(node, ())
            ),
        )
        for node in (*targets, *(key for key in merges if key not in targets))
    }


def admit_route_metric(definition: Definition, composed: MetricSpec) -> MetricSpec | None:
    """The one run metric every route evaluation uses, admitted before any dispatch.

    The composed task metric is the run metric (the routed profile admits no loop, so
    no captured seed is reconciled). A ``metric_at_least`` naming another metric is
    refused here, so a mismatch orphans no native record.
    """
    if not definition.routes:
        return None
    admit_route_metrics(definition.routes, composed)
    return composed


def decide_routes(
    definition: Definition,
    entry: GraphNodeEvidence,
    metric: MetricSpec | None,
    *,
    iteration: int,
    stamped: bool = False,
) -> tuple[GraphRouteEvidence, ...]:
    """Decide every branch read from ``entry`` once it closed with a native record.

    A rejected source decides too (the fallback arm reads ``validation.passed``); a
    failed one decides nothing and its targets are blocked. Any projection or
    evaluation error, not only ``RouteConditionError``, is raised as a
    ``RouteConditionError``: the body fails rather than read the route as false.
    ``stamped`` (verifier only) evaluates under the record's own stamped metric.
    """
    if entry.state not in ("succeeded", "rejected") or entry.record_path is None:
        return ()
    decided = []
    for branch in definition.routes:
        if branch.source.node != entry.node_id:
            continue
        try:
            observation = project_observation(
                branch, entry.capability, Path(entry.record_path), iteration=iteration
            )
            if observation.record_sha256 != entry.record_sha256:
                raise RouteConditionError("the route source record changed after it closed")
            decision = evaluate_route(
                RouteEvaluationInput(
                    branch=branch,
                    observation=observation,
                    metric=observation.metric_spec if stamped else metric,
                )
            )
        except RouteConditionError:
            raise
        except Exception as error:
            raise RouteConditionError(f"route {branch.id}: {error}") from error
        decided.append(
            GraphRouteEvidence(
                branch_id=branch.id,
                source_node=entry.node_id,
                source_record_sha256=observation.record_sha256,
                decision=decision,
            )
        )
    return tuple(decided)


def declared_order(
    definition: Definition, routes: Iterable[GraphRouteEvidence]
) -> tuple[GraphRouteEvidence, ...]:
    """Recorded decisions in branch declaration order, independent of execution order."""
    by_branch = {item.branch_id: item for item in routes}
    return tuple(by_branch[branch.id] for branch in definition.routes if branch.id in by_branch)


def evidence_digest(evidence: GraphRouteEvidence) -> str:
    return hashlib.sha256(canonical_json_bytes(evidence)).hexdigest()


def skip_citations(
    entries: Mapping[str, GraphNodeEvidence],
    routes: Iterable[GraphRouteEvidence],
    routing: Mapping[str, NodeRouting],
) -> dict[str, str]:
    """The skip record each route-skipped node cites: its causing decision's digest.

    A node is skipped by its own branch's decision, or inherits the skip from a
    skipped predecessor (declared order); the walk ends at the deciding branch. An
    adaptor cites this digest as ``AdaptorInputRef.record_sha256`` of a skipped input.
    """
    evidence = {item.branch_id: item for item in routes}
    citations: dict[str, str] = {}
    for node_id, entry in entries.items():
        if entry.state != "skipped" or entry.reason != "route_not_selected":
            continue
        current, seen = node_id, set()
        while current not in seen:
            seen.add(current)
            route = routing.get(current, NodeRouting()).route
            decided = evidence.get(route) if route is not None else None
            if decided is not None and current in decided.decision.skipped_targets:
                citations[node_id] = evidence_digest(decided)
                break
            skipped = [
                key
                for key in entries[current].predecessors
                if entries[key].state == "skipped" and entries[key].reason == "route_not_selected"
            ]
            if not skipped:
                break
            current = skipped[0]
    return citations


def verify_routes(
    definition: Definition,
    nodes: tuple[GraphNodeEvidence, ...],
    recorded: tuple[GraphRouteEvidence, ...],
    *,
    iteration: int,
) -> None:
    """Re-derive every decision from the committed source record; refuse any difference.

    The verifier holds no task composition, so a metric comparison uses the source
    record's own stamped metric: the worker already reconciled that stamp with the
    composed run metric, and only a tuning record (which stamps it) carries a metric
    observable. A missing decision, an extra one, a changed record digest or a
    different decision is refused.
    """
    expected = [
        decided
        for entry in nodes
        for decided in decide_routes(definition, entry, None, iteration=iteration, stamped=True)
    ]
    if recorded != declared_order(definition, expected):
        raise ValueError("graph route evidence does not match its re-derivation")
