"""Bounded planning recovery before any analysis action or data access."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from agent.data_analysis.discovery import DiscoverySnapshot
from agent.data_analysis.persistence import AnalysisRunStore
from agent.data_analysis.plan_validation import (
    AnalysisPlanResolutionError,
    ResolvedAnalysisInvocation,
    resolve_analysis_plan,
)
from agent.data_analysis.structured_output import (
    DataAnalysisStructuredOutputError,
    generate_validated,
)
from agent.schemas.data_analysis.common import canonical_sha256
from agent.schemas.data_analysis.context import DataAnalysisInput
from agent.schemas.data_analysis.plan import AnalysisPlan, PlannedGeneratedProgramInvocation
from agent.schemas.data_analysis.skills import ResolvedSkillInterface


def generate_resolved_analysis_plan(
    bridge,
    *,
    store: AnalysisRunStore,
    analysis_input: DataAnalysisInput,
    discovery: DiscoverySnapshot,
    resolved_interfaces: Mapping[str, ResolvedSkillInterface],
    control_root: Path,
    prepared_generated_identities: set[str],
    system: str,
    user: str,
    semantic_projection: Callable[[object], object | None],
) -> tuple[AnalysisPlan, tuple[ResolvedAnalysisInvocation, ...]]:
    """Share one replan allowance across schema and resolution failures.

    Representation repair cannot change decisions. A new planning attempt can,
    but must satisfy the same declarations, access policy and existing deadline.
    Exhaustion, provider failures and deadline failures still propagate honestly.
    """

    for attempt in range(2):
        plan = None
        try:
            plan = generate_validated(
                bridge,
                store=store,
                model_type=AnalysisPlan,
                system=system,
                user=user,
                label=(
                    "data_analysis.plan" if attempt == 0 else "data_analysis.plan.resolution_retry"
                ),
                semantic_projection=semantic_projection,
            )
            planned_identities = {
                canonical_sha256(item.program_identity)
                for item in plan.invocations
                if isinstance(item, PlannedGeneratedProgramInvocation)
            }
            if planned_identities != prepared_generated_identities:
                raise AnalysisPlanResolutionError(
                    "final AnalysisPlan must reference exactly the generated programs "
                    "prepared during its two-stage lifecycle"
                )
            resolved = resolve_analysis_plan(
                plan,
                analysis_input=analysis_input,
                discovery=discovery,
                resolved_interfaces=resolved_interfaces,
                control_root=control_root,
                generated_program_root=store.root,
            )
            return plan, resolved
        except (DataAnalysisStructuredOutputError, AnalysisPlanResolutionError) as exc:
            if attempt:
                raise
            if isinstance(exc, DataAnalysisStructuredOutputError):
                detail = exc.planning_feedback
            else:
                assert plan is not None
                detail = f"Previous plan:\n{plan.model_dump_json(indent=2)}"
            user += (
                f"\nThe previous AnalysisPlan was rejected before execution: {exc}.\n{detail}\n"
                "This is one fresh planning attempt, not representation-only repair. "
                "Generate one corrected complete plan using the same immutable contracts "
                "and authorized assets. Do not widen any binding or generated program declaration.\n"
            )
    raise AssertionError("bounded planning loop must return or raise")
