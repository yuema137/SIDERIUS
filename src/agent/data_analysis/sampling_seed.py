"""Resolve the executed analysis sampling seed after plan acceptance (issue #983).

Contract: ``docs/agent-reference/mechanisms/seeding.md`` "Data-analysis sampling".

Explicitness belongs to the operator: an envelope whose ``sampling_policy``
declares ``seed`` executes exactly that seed, and every planned invocation
must already carry it (checked during plan resolution, so a mismatch takes the
existing replan path, ``plan_validation.resolve_analysis_plan``). Otherwise the seed is
``derive_seed(run_seed, "data_analysis.sampling", SeedCoordinates())``; the
plan's own value (usually a copied schema default) is ignored, replaced before
materialization and recorded. The LLM plan never decides explicitness.
"""

from __future__ import annotations

import dataclasses
from typing import Literal

from agent.schemas.data_analysis.resources import (
    AnalysisResourceEnvelope,
    AnalysisSamplingSeeds,
    InvocationSamplingSeed,
)
from core.seeding import SeedCoordinates, derive_seed

from .plan_validation import ResolvedAnalysisInvocation

#: Run-level coordinates: one analysis sampling stream per run (the native
#: chain has no graph node id and the stream does not vary by iteration).
SAMPLING_COORDINATES = SeedCoordinates()

SamplingSeedSource = Literal["declared", "derived"]


def resolve_analysis_sampling_seed(
    envelope: AnalysisResourceEnvelope, run_seed: int
) -> tuple[int, SamplingSeedSource]:
    """The seed every invocation executes and its source (``declared``/``derived``)."""
    declared = envelope.declared_sampling_seed()
    if declared is not None:
        return declared, "declared"
    return derive_seed(run_seed, "data_analysis.sampling", SAMPLING_COORDINATES), "derived"


def apply_sampling_seed(
    resolved: tuple[ResolvedAnalysisInvocation, ...],
    *,
    envelope: AnalysisResourceEnvelope,
    run_seed: int,
) -> tuple[tuple[ResolvedAnalysisInvocation, ...], AnalysisSamplingSeeds]:
    """Give every accepted invocation the executed seed; record what replaced what."""
    seed, source = resolve_analysis_sampling_seed(envelope, run_seed)
    executed: list[ResolvedAnalysisInvocation] = []
    records: list[InvocationSamplingSeed] = []
    for item in resolved:
        sampling = item.invocation.sampling_plan
        planned = sampling.policy.seed
        if source == "derived":
            # A declared seed already equals the plan's (plan resolution checks
            # it), so a declared invocation is executed exactly as planned.
            policy = sampling.policy.model_copy(update={"seed": seed})
            invocation = item.invocation.model_copy(
                update={"sampling_plan": sampling.model_copy(update={"policy": policy})}
            )
            item = dataclasses.replace(item, invocation=invocation)
        executed.append(item)
        records.append(
            InvocationSamplingSeed(
                invocation_id=item.invocation.invocation_id,
                sampling_seed=seed,
                sampling_seed_source=source,
                llm_plan_seed_ignored=planned if source == "derived" else None,
            )
        )
    return tuple(executed), AnalysisSamplingSeeds(
        run_seed=run_seed,
        invocations=tuple(records),
        program_seed=derive_seed(run_seed, "data_analysis.program", SAMPLING_COORDINATES),
    )
