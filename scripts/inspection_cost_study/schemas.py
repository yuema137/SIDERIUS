"""V21 PR F — typed study records (measure only; nothing in production
reads these).

The vocabulary here is a study-level ENVELOPE around native production
evidence, never a replacement for it (design §0.F, operator-approved
final form). The one rule every field serves: exact observations, native
timeouts, harness backstops and absences must stay distinguishable
forever, because a later budget-change PR will be audited against these
files.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

#: The two operator-approved populations (Q-F-1). Never pooled.
Population = Literal["v20_generated_realized", "builtin_reference"]

#: The three measured operations (design §0.A census — only budgets that
#: production actually enforces are studied).
Operation = Literal["candidate_probe", "full_search", "training_probe"]

#: How one timed call actually ended (design §0.F).
ExecutionOutcome = Literal[
    "completed",  # exact elapsed, incl. exact post-hoc overruns
    "native_timeout",  # production's own bounded semantics ended it
    "harness_backstop",  # the study's emergency SIGALRM — study infra
    "harness_deadline",  # external kill (stuck-native residual, §0.G)
    "unloadable",  # plugin/config failed to load or instantiate
    "invalid_config",  # reference-grid config refused by its own schema
]

PointClass = Literal["CLEAR", "WOULD_BE_CENSORED", "INDETERMINATE"]


class SweepEntry(BaseModel):
    """One (population, model, exact config) — §0.D's MODEL ENTRY."""

    model_config = ConfigDict(frozen=True)

    entry_id: str
    population: Population
    architecture_family: str = Field(
        description="Interpretation boundary (operator rule): kept on every "
        "entry and figure; cross-family scatter is never fitted as a "
        "causal size law.",
    )
    model_identity: str = Field(
        description="Observational metadata ONLY — never a behavioural key.",
    )
    exact_config: dict[str, Any]
    segmentation_size: int = Field(gt=0)
    #: O-E-6 conventions, both, measured from the instantiated model.
    realized_total_parameter_count: int | None = Field(default=None, ge=0)
    realized_trainable_parameter_count: int | None = Field(default=None, ge=0)
    loss_type: Literal["ce", "smooth_l1"] = Field(
        description="The loss family used for the training probe, derived "
        "from the model's declared output type exactly as production "
        "pairs them (classifier/hybrid -> ce, regressor -> smooth_l1).",
    )
    #: Set when instantiation failed: the entry stays in the manifest as
    #: evidence (never silently replaced — timing-blind grid rule).
    load_error: str | None = None


class Measurement(BaseModel):
    """One repeat of one operation point — §0.F's envelope."""

    model_config = ConfigDict(frozen=True)

    entry_id: str
    operation: Operation
    candidate_batch: int | None = Field(default=None, gt=0)
    repeat_index: int = Field(ge=0)
    execution_outcome: ExecutionOutcome
    #: EXACT wall seconds. Present ONLY for outcomes that yield an exact
    #: observation (completed; native_timeout of a POST-HOC operation,
    #: whose ProbeTimeoutRecord carries a real elapsed). Never a bound.
    elapsed_seconds: float | None = Field(default=None, ge=0.0)
    #: Lower bound ONLY (native preemptive timeout at its own budget, or
    #: a harness backstop). Mutually exclusive with elapsed_seconds by
    #: validator below.
    lower_bound_seconds: float | None = Field(default=None, gt=0.0)
    #: The native production evidence, VERBATIM (ProbeTimeoutRecord
    #: model_dump for BatchSearchTimeout; operation label for the native
    #: ForwardPassTimeoutError which carries no typed record).
    native_record: dict[str, Any] | None = None
    native_operation: str | None = None
    error: str | None = None
    #: For full_search completions: the resolved batch (observational).
    resolved_batch: int | None = None
    #: Host context, per point (§0.E noise handling).
    loadavg_1m: float | None = None

    def model_post_init(self, _ctx: Any) -> None:
        # An exact time and a lower bound are contradictory claims about
        # the same call; refusing both here is what keeps "never write a
        # lower bound as though it were exact" mechanical.
        if self.elapsed_seconds is not None and self.lower_bound_seconds is not None:
            raise ValueError(
                "a measurement cannot carry both an exact elapsed_seconds "
                "and a lower_bound_seconds — exact and censored are "
                "different claims (design §0.F)"
            )


class PointVerdict(BaseModel):
    """Classification of one operation point against ONE production budget."""

    model_config = ConfigDict(frozen=True)

    entry_id: str
    operation: Operation
    candidate_batch: int | None = None
    budget_name: str
    budget_seconds: float = Field(gt=0.0)
    verdict: PointClass
    n_under: int = Field(ge=0)
    n_over_exact: int = Field(ge=0)
    n_over_censored: int = Field(ge=0)
    n_deadline: int = Field(ge=0)
    reason: str


class StudyHeader(BaseModel):
    """First line of every measurements file."""

    model_config = ConfigDict(frozen=True)

    manifest_hash: str
    seed: int
    repeats: int
    wall_seconds: float
    #: The PRODUCTION budgets the harness read at run time — pinned so
    #: budget drift is visible in the evidence itself.
    production_budgets: dict[str, float]
    host: str
    cap_bytes_for_full_search: int


def manifest_hash(entries: list[SweepEntry]) -> str:
    """Deterministic content hash over the canonical entry list."""
    canonical = json.dumps(
        [e.model_dump(mode="json") for e in entries],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
