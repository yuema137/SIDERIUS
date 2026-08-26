"""``ExecutionProvenance`` — what the framework RESOLVED after the plan was authored.

An experiment's plan is authored by the planner and then *resolved* by the
framework: operator overrides are merged, a round-mode chain may inherit
another round's hyperparameters wholesale, a task-declared objective may
replace the planner's loss, a partial data scope normalizes the sampling
strategies, and an epoch bound clamps the training length. Every one of those
steps changes what EXECUTES. None of them changes ``plan.hypothesis``, which is
free prose the planner wrote *before* any of it happened.

That gap is the defect this type closes. The witnessed instance (F15): a
research-memory reflection read *"using kernel_size=15 with custom Smooth L1
beta=0.5"* for a run whose task-declared objective ``waveform_exact_mse``
actually executed and whose ``beta`` was null. The narrative was not describing
the run — it was describing a proposal the framework had already overruled.

The governing rule, stated once:

```text
DOWNSTREAM NARRATIVE DESCRIBING A RUN MUST DERIVE FROM
RESOLVED EXECUTION PROVENANCE, NOT FROM STALE PROPOSAL ASSUMPTIONS.
```

**This type is a record of DISAGREEMENT, not a copy of the configuration.**
It carries only the fields whose authored value differs from the executed one,
so a run where the planner's plan survived resolution intact produces an EMPTY
provenance and renders nothing at all. The proposal prose is kept and still
shown — labelled as a proposal — because *what was proposed* is a true and
useful fact. What must never happen is a proposed value being narrated as
though it ran.

Deliberately NOT a diagnosis: no judgement, no severity, no "was this
override good". Like :class:`~agent.schemas.training_diagnosis.TrainingDiagnosis`
it is a pure, deterministic derivation, computed once at the tuner boundary and
rendered downstream — never re-derived by a consumer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: The resolution authorities, in the order they run inside planning. Each is
#: a step that may overrule the authored plan. The vocabulary is CLOSED so a
#: renderer can never be handed an unexplained authority name, and
#: ``unattributed`` is the safety net: it is what the final sweep reports when
#: a plan field moved without any wrapped step claiming it — i.e. when a
#: SEVENTH resolution step is added and not registered here.
#:
#: The completeness property matters more than the labels. A tracker that
#: enumerated the known steps and stopped would go silently blind the day
#: someone adds another one — the same census-blindness shape that has bitten
#: this repository repeatedly. The final sweep means a new step is reported as
#: a real disagreement with a vague authority, never as agreement.
KNOWN_AUTHORITIES: frozenset[str] = frozenset(
    {
        "operator_plan_overrides",
        "round_mode_override_chain",
        "task_declared_objective",
        "partial_scope_strategy_normalization",
        "max_epochs_bound",
        "forced_model_type",
        "unattributed",
    }
)

#: Human sentences for each authority, used by the renderer. Keyed by the same
#: closed vocabulary so a missing entry is a KeyError at render time rather
#: than a blank line in an LLM prompt.
AUTHORITY_DESCRIPTIONS: dict[str, str] = {
    "operator_plan_overrides": "operator plan_overrides lock",
    "round_mode_override_chain": "round-mode override chain (trial lockout / formal inheritance)",
    "task_declared_objective": "task-declared objective",
    "partial_scope_strategy_normalization": "partial data scope normalization",
    "max_epochs_bound": "--max_epochs bound",
    "forced_model_type": "forced model type",
    "unattributed": "resolved after the plan was authored (step not registered)",
}


class ResolutionEvent(BaseModel):
    """ONE field whose authored value was overruled before execution.

    ``proposed`` and ``executed`` are pre-rendered strings, not the original
    objects. The consumer is a prompt renderer and a report, and both need a
    stable textual form; keeping live objects here would invite a consumer to
    re-interpret them and re-introduce the very divergence this type records.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str = Field(
        description=(
            "Dotted path within the plan, e.g. `loss_cfg.loss_type` or "
            "`train_cfg.epochs`. Identifies the disagreement precisely enough "
            "that a reader can check it against the persisted record."
        )
    )
    proposed: str = Field(description="The value as the planner AUTHORED it, rendered as text.")
    executed: str = Field(description="The value the run ACTUALLY executed with, rendered as text.")
    authority: str = Field(
        description=(
            "Which resolution step overruled the authored value. One of "
            "KNOWN_AUTHORITIES; `unattributed` when the final sweep found the "
            "change but no registered step claimed it."
        )
    )


class ExecutionProvenance(BaseModel):
    """The complete set of authored-vs-executed disagreements for one attempt.

    ``events`` empty means the authored plan survived resolution unchanged, and
    the planner's prose therefore describes what ran. That is the common case
    and it renders NOTHING — an un-overridden run's prompt bytes do not move.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    events: tuple[ResolutionEvent, ...] = Field(
        default=(),
        description=(
            "One entry per field whose authored value differs from the "
            "executed one. Empty when the plan was not overruled."
        ),
    )

    @property
    def diverged(self) -> bool:
        """True when the proposal prose cannot be trusted to describe the run."""
        return bool(self.events)
