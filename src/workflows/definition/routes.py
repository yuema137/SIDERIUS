"""Static checks for inert route declarations; nothing here evaluates a predicate.

A branch's *arm* for one case (or the default) is every node reachable from the
branch source whose every path from that source passes through one of the
case's targets. Skipping the case skips exactly its arm. Because every target
has a control edge from the source, disjoint target sets always give disjoint
arms: a path's last target can be reached directly, avoiding the other arms.
"""

from collections.abc import Iterator

from .catalog import CAPABILITIES, ROUTE_OBSERVABLES
from .models import (
    AllOf,
    AnyOf,
    AuthoredLoop,
    BoolIs,
    Branch,
    EnumIn,
    IsMissing,
    MetricAtLeast,
    Not,
    ProtocolRequest,
    ResultSource,
    ReusableWorkflowDefinition,
    RoutePredicate,
    SelectedSource,
    WorkflowDefinition,
)

Facts = tuple[tuple[str, frozenset[str]], ...]
Arms = dict[str, tuple[frozenset[str], ...]]

_LEAF_KINDS = {BoolIs: "bool", EnumIn: "enum", MetricAtLeast: "metric", IsMissing: "metric"}


def route_entries(branch: Branch) -> tuple[tuple[str, ...], ...]:
    """Entry targets of every arm that can run: each case, then the default."""
    cases = tuple(case.targets for case in branch.cases)
    return cases if branch.default is None else (*cases, branch.default)


def validate_routes(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
    facts: Facts,
    order: tuple[str, ...],
) -> None:
    """Refuse a route that reads an uncatalogued field, overlaps, starves or skips feedback.

    ``facts`` already include route control edges and passed the cycle check.
    """
    branches = {branch.id: branch for branch in definition.routes}
    if len(branches) != len(definition.routes):
        raise ValueError("Branch IDs must be unique")
    capabilities = {node.id: node.capability for node in definition.nodes}
    children: dict[str, set[str]] = {node: set() for node in capabilities}
    for node, sources in facts:
        for source in sources:
            children[source].add(node)
    arms: Arms = {}
    targeted: set[str] = set()
    for branch in definition.routes:
        contract = CAPABILITIES[capabilities[branch.source.node]].output
        for case in branch.cases:
            _check_predicate(branch.id, case.when, contract)
        entries = route_entries(branch)
        flat = {target for entry in entries for target in entry}
        if len(flat) != sum(len(entry) for entry in entries) or flat & targeted:
            raise ValueError(f"route {branch.id}: a node may be one target of one branch")
        targeted |= flat
        arms[branch.id] = tuple(_arm(branch.source.node, entry, children) for entry in entries)
    _check_merges(definition, arms)
    _check_arm_dependencies(definition, arms, order)
    if definition.loop is not None:
        _check_loop(definition.loop, arms, dict(facts))


def _check_predicate(branch: str, predicate: RoutePredicate, contract: str) -> None:
    if isinstance(predicate, (AllOf, AnyOf)):
        leaves = predicate.terms
    elif isinstance(predicate, Not):
        leaves = (predicate.term,)
    else:
        leaves = (predicate,)
    for leaf in leaves:
        observable = ROUTE_OBSERVABLES.get(leaf.observable)
        if observable is None or observable.contract != contract:
            raise ValueError(f"route {branch}: observable is not catalogued for {contract}")
        if observable.kind != _LEAF_KINDS[type(leaf)]:
            raise ValueError(f"route {branch}: {leaf.kind} cannot read a {observable.kind}")
        if isinstance(leaf, EnumIn) and (
            len(set(leaf.values)) != len(leaf.values)
            or not set(leaf.values) <= set(observable.values)
        ):
            raise ValueError(f"route {branch}: enum values must be unique catalogued values")


def _reachable(start: str, children: dict[str, set[str]], stop: frozenset[str]) -> set[str]:
    """Nodes reachable from ``start``; ``stop`` nodes are not entered."""
    seen = {start}
    pending = [start]
    while pending:
        for child in children[pending.pop()]:
            if child not in seen and child not in stop:
                seen.add(child)
                pending.append(child)
    return seen


def _arm(source: str, entry: tuple[str, ...], children: dict[str, set[str]]) -> frozenset[str]:
    return frozenset(
        _reachable(source, children, frozenset()) - _reachable(source, children, frozenset(entry))
    )


def _selected_sources(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
) -> Iterator[tuple[str, SelectedSource]]:
    for node in definition.nodes:
        if isinstance(node.request, ProtocolRequest):
            for argument in node.request.arguments:
                if isinstance(argument.source, SelectedSource):
                    yield node.id, argument.source


def _check_merges(definition: WorkflowDefinition | ReusableWorkflowDefinition, arms: Arms) -> None:
    """Each merge takes one candidate from every arm that can run, so it is never starved."""
    for consumer, merge in _selected_sources(definition):
        branch_arms = arms.get(merge.branch)
        if branch_arms is None:
            raise ValueError(f"{consumer}: merge names an unknown branch")
        if any(consumer in arm for arm in branch_arms):
            raise ValueError(f"{consumer}: a merge consumer must lie outside its branch arms")
        covered = [
            index
            for item in merge.candidates
            for index, arm in enumerate(branch_arms)
            if item.node in arm
        ]
        if len(covered) != len(merge.candidates) or sorted(covered) != list(
            range(len(branch_arms))
        ):
            raise ValueError(f"{consumer}: merge requires one candidate in every branch arm")


def _check_arm_dependencies(
    definition: WorkflowDefinition | ReusableWorkflowDefinition,
    arms: Arms,
    order: tuple[str, ...],
) -> None:
    """Refuse a node depending on two exclusive arms of one branch except through a merge."""
    plain: dict[str, set[str]] = {node.id: set() for node in definition.nodes}
    merged: dict[str, list[SelectedSource]] = {node.id: [] for node in definition.nodes}
    for node in definition.nodes:
        if isinstance(node.request, ProtocolRequest):
            for argument in node.request.arguments:
                if isinstance(argument.source, ResultSource):
                    plain[node.id].add(argument.source.node)
                elif isinstance(argument.source, SelectedSource):
                    merged[node.id].append(argument.source)
    for branch in definition.routes:
        for entry in route_entries(branch):
            for target in entry:
                plain[target].add(branch.source.node)
    labels: dict[str, frozenset[tuple[str, int]]] = {}
    for node in order:
        current = {
            (branch, index)
            for branch, items in arms.items()
            for index, arm in enumerate(items)
            if node in arm
        }
        for source in plain[node]:
            current |= labels[source]
        for merge in merged[node]:
            for item in merge.candidates:
                current |= {label for label in labels[item.node] if label[0] != merge.branch}
        branches = [branch for branch, _ in current]
        if len(branches) != len(set(branches)):
            raise ValueError(f"{node}: depends on two exclusive arms without a merge")
        labels[node] = frozenset(current)


def _check_loop(loop: AuthoredLoop, arms: Arms, dependencies: dict[str, frozenset[str]]) -> None:
    """v1: no route may skip the feedback source or any node it depends on."""
    required = {loop.feedback.source.node}
    pending = [loop.feedback.source.node]
    while pending:
        for source in dependencies[pending.pop()]:
            if source not in required:
                required.add(source)
                pending.append(source)
    if any(required & arm for items in arms.values() for arm in items):
        raise ValueError("routes may not skip the loop feedback source or its predecessors")
