# nodes/ml_hyperparameter_tune_agent/round_health.py
"""HealthGate evaluation at the ROUND boundary, for every scoring route.

**The defect this module exists to remove (F2).** The tuner's only production
gate call site used to sit *inside* the ``ScoringRoute.ANCHOR_NORMALIZED``
branch of the scoring block. That branch requires an anchor map, so:

```text
un-composed + --is_trial   -> ANCHOR_NORMALIZED  -> gates evaluated
un-composed + --no-is_trial-> SUBPROCESS_LEGACY  -> gates NEVER evaluated
composed (any task)        -> TASK_OWNED         -> gates NEVER evaluated
```

A composed task could declare a roster, materialize it into
``health_checks_effective.yaml``, have its sha pinned into the run-invariants
lock, pass ``--healthgate_mode blocking`` — and the production path would
evaluate nothing. Nothing in the run's output said so: the record carried
``health_gate_results: []`` beside ``health_gate_enabled: true``, which reads
as *"every gate passed"* when the truth was *"no gate ran"*.

``docs/design/pluggable_health_checks.md`` §8 and ``CLAUDE.md`` both already
specify the correct rule — **gates fire at tuner round boundaries** — so this
is a coupling being removed, not a semantic being invented. Gate evaluation is
a function of the ROUND's deliverable, never of how that round happened to be
scored.

**Why an extracted boundary rather than a widened branch.** Widening the
``if`` would encode the coupling in a second place. The repository's
responsibility-decomposition rule also forbids adding new branching to
``run_inference_scoring_health``, which is already a phase orchestrator. So the
decision lives here, as a total function with explicit inputs and a typed
result, and the orchestrator gains one call rather than a second gate block.

**The honesty field.** :attr:`RoundHealthOutcome.evaluated` is the reason an
empty gate list is no longer ambiguous. ``[]`` alone cannot distinguish "the
subsystem is disabled", "this round's position declares no gates", and "the
call site was unreachable" — and it was the third that hid this defect for as
long as it did. A caller can now record WHICH it was.
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from execute_tools.health_checks import (
    GateAction,
    HealthCheckContext,
    evaluate_and_persist_health_gates,
    get_gates_for_position,
)
from nodes.ml_hyperparameter_tune_agent.scope_acquisition import (
    project_attempt_topology_facts,
)


def build_target_path_fn(sandbox: Any, run_profile: Any) -> Any:
    """The RAW validation-file resolver a Health peek asks for.

    Owned here rather than by the orchestrator because nothing else calls it:
    the scoring paths resolve the DELIVERABLE (``denoised_filename_fn``), and
    only a check comparing against the RAW SIGNAL wants this one. The boundary
    resolving its own inputs is what the decomposition rule asks for.

    **Both halves resolve LAZILY, at call time**, and that is load-bearing.

    ``sandbox.dirs["data"]`` used to be read EAGERLY inside the tuner's
    anchor-normalized branch, where a physical data root is always present.
    Once gate evaluation moved to the round boundary — reachable on every
    scoring route — an eager read became unconditional, and a sandbox with no
    physical data root raised ``KeyError`` BEFORE any scoring, which the
    orchestrator's handler turned into a FAILED round. Moving WHEN gates run
    must not change what a round DOES.

    Deferring is also the shape Step 12 / PR-12d seam B already describes: the
    contrast packs' Health families consume decoded views of the deliverable,
    so this resolver is simply never called for them, and one that cannot be
    built must not cost a round that never needed it. A check that DOES ask
    gets a named refusal rather than a bare ``KeyError``.

    Step 12 / PR-12bc B7, satellite (f) is the other half of the contract:
    both the ROOT and the FILENAME come from the run's own authorities — the
    composed physical root and the profile's declared validation-file
    template. This previously joined the anchor task's IMPORT-TIME data-root
    constant to an inline anchor-task filename template, so a composed run
    peeked at the anchor task's files, under its names, in its directory,
    whatever it had declared. Neither of those two spellings may reappear in
    this module or in the orchestrator — a guard asserts their absence across
    both files, prose included, which is why they are described here rather
    than quoted.

    Returns:
        ``(index) -> str``: the absolute raw validation-file path.
    """

    def _target_fn(i: int, _sandbox=sandbox, _profile=run_profile) -> str:
        names = project_attempt_topology_facts(_profile).require_physical_dataset(
            "resolving a raw validation-file path for a Health peek"
        )
        try:
            base = _sandbox.dirs["data"]
        except KeyError as exc:
            raise KeyError(
                "a Health check asked for a raw validation-file path, but "
                "this run's sandbox exposes no physical data root "
                "('data'). Checks that read the raw signal cannot run "
                "here; checks consuming decoded views of the deliverable "
                "are unaffected."
            ) from exc
        return os.path.join(base, names.validation_file_name(i))

    return _target_fn


class RoundHealthOutcome(BaseModel):
    """What the round's HealthGates decided, and whether they ran at all."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    evaluated: bool = Field(
        description=(
            "Whether the gate engine was actually INVOKED for this round. "
            "False means the subsystem was disabled — never that gates ran "
            "and found nothing. An empty `persisted` with `evaluated=True` is "
            "a real 'this position declares no gates'; with `evaluated=False` "
            "it is 'nobody asked'. Conflating the two is F2."
        ),
    )
    persisted: list[Any] = Field(
        default_factory=list,
        description="PersistedHealthGateResult rows, exactly as the engine returned them.",
    )
    resolved_action: GateAction = Field(
        default=GateAction.CONTINUE,
        description="Severity-resolved action across every gate that fired.",
    )
    is_degenerate: bool = Field(default=False)
    failure_reason: str | None = Field(default=None)
    gate_action: str | None = Field(default=None)


def evaluate_round_health(
    *,
    enabled: bool,
    round_index: int,
    config_path: str | None,
    production_config_path: str,
    healthgate_mode: str | None,
    result_authority: str | None,
    model_name: str,
    run_name: str,
    exp_id: str,
    models_dir: str | None,
    denoised_filename_fn: Any,
    target_path_fn: Any,
    file_vector: list[Any],
    denoising_score: Any,
    per_sample_evidence: Any,
    gate_results_to_score_meta: Any,
) -> RoundHealthOutcome:
    """Evaluate this round's HealthGates. Route-independent by construction.

    The argument list is deliberately explicit: this is an extracted boundary,
    and a helper that reached back into the orchestrator's scope for these
    values would be the same complexity in a different file rather than a
    completed decomposition.

    Args:
        enabled: the run's ``health_gate_enabled`` switch (a run-level INPUT,
            not YAML — DataScope DS4-DS6). False short-circuits to a
            ``evaluated=False`` outcome with no engine call and no I/O.
        round_index: the round whose position selects the gate set.
        config_path: the operator's HealthGate config, or None for the shipped
            default. Threaded to BOTH the position lookup and the evaluation,
            exactly as the pre-extraction call site did.
        production_config_path: the framework policy file the engine compares
            against.
        healthgate_mode: declared enforcement posture, stamped onto results.
        result_authority: declared scientific authority, stamped onto results.
        model_name: model type, for the check context and checkpoint filename.
        run_name: the run's name, for the check context.
        exp_id: the attempt id, for the checkpoint filename.
        models_dir: the sandbox's models directory, or None when it has none.
        denoised_filename_fn: resolves a deliverable path per input identity.
        target_path_fn: resolves a RAW validation-file path; only checks that
            compare against the raw signal call it, and it declines by name
            when the task declares no physical geometry.
        file_vector: per-input metric values, possibly empty.
        denoising_score: the round's golden-metric scalar.
        per_sample_evidence: D18's typed statement about whether a per-sample
            concept exists for this task. Never inferred from ``file_vector``.
        gate_results_to_score_meta: the orchestrator's existing projection from
            gate results to ``(is_degenerate, failure_reason, action_str)``.
            Injected rather than imported so this module owns the LIFECYCLE
            decision and not the score-meta vocabulary, which already has an
            owner.

    Returns:
        A :class:`RoundHealthOutcome`. Never raises for the disabled case;
        engine exceptions propagate to the caller's existing handler, because
        a gate that could not be evaluated is not a gate that passed.
    """
    if not enabled:
        # DataScope DS5 — the subsystem is explicitly off: no gate evaluation
        # and no gate persistence. Score-validity classification stays the
        # caller's business and is unaffected.
        return RoundHealthOutcome(evaluated=False)

    gate_ids = (
        get_gates_for_position(round_index, config_path=config_path)
        if config_path
        else get_gates_for_position(round_index)
    )
    checkpoint_path = (
        os.path.join(models_dir, f"model_{model_name}_{exp_id}_agent.pth")
        if gate_ids and models_dir
        else None
    )
    ctx = HealthCheckContext(
        model_name=model_name,
        run_name=run_name,
        round_index=round_index,
        denoised_filename_fn=denoised_filename_fn,
        target_path_fn=target_path_fn,
        checkpoint_path=checkpoint_path,
        file_vector=file_vector,
        denoising_score=denoising_score,
        per_sample_evidence=per_sample_evidence,
    )
    gate_results, persisted, resolved_action = evaluate_and_persist_health_gates(
        ctx,
        config_path=config_path,
        production_config_path=production_config_path,
        gate_ids=gate_ids,
        # D-C7b: the run's declaration travels onto every gate result, so an
        # external reader never has to infer the posture from a gate id's
        # spelling.
        healthgate_mode=healthgate_mode,
        result_authority=result_authority,
    )
    is_degenerate, failure_reason, gate_action = gate_results_to_score_meta(
        gate_results, resolved_action
    )
    return RoundHealthOutcome(
        evaluated=True,
        persisted=list(persisted),
        resolved_action=resolved_action,
        is_degenerate=is_degenerate,
        failure_reason=failure_reason,
        gate_action=gate_action,
    )


def apply_round_health(score_res: dict[str, Any], *, merge_score_validity: Any, **kwargs: Any):
    """Evaluate this round's gates and STAMP the verdict onto ``score_res``.

    Evaluate, merge score-validity, write the four record-facing keys: three
    steps that are one responsibility — "what did this round's health say?" —
    and therefore one call at the orchestrator, which keeps sequencing.

    Score-validity classification runs whether or not gates ran. It always did,
    and DataScope DS5 explicitly keeps it active when the subsystem is off, so
    it is merged here rather than gated behind ``evaluated``.

    Args:
        score_res: the route's scoring result. Mutated in place — its
            ``results`` dict gains ``is_degenerate`` / ``failure_reason`` /
            ``gate_action`` / ``health_gate_results``, exactly the keys the
            anchor route used to write inline, in the same order.
        merge_score_validity: the orchestrator's existing score-validity
            projection. Injected rather than imported so this module owns the
            health LIFECYCLE without acquiring the score-meta vocabulary,
            which already has an owner.
        **kwargs: forwarded verbatim to :func:`evaluate_round_health`.

    Returns:
        The :class:`RoundHealthOutcome`, so a caller can still read
        ``evaluated`` — the honest answer to "did gates RUN?", which
        ``health_gate_results: []`` alone cannot give.
    """
    outcome = evaluate_round_health(**kwargs)
    is_degenerate, failure_reason = merge_score_validity(
        kwargs["denoising_score"],
        is_degenerate=outcome.is_degenerate,
        failure_reason=outcome.failure_reason,
    )
    score_res.setdefault("results", {}).update(
        {
            "is_degenerate": is_degenerate,
            "failure_reason": failure_reason,
            "gate_action": outcome.gate_action,
            "health_gate_results": [item.model_dump(mode="json") for item in outcome.persisted],
        }
    )
    return outcome
