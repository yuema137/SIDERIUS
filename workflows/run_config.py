"""``WorkflowLaunchConfig`` — the exploration run's launch/transit configuration.

Step 09.5a, operator Amendment B. This carrier exists because a measurement:
**41 of ``run_workflow``'s 99 parameters had a single sink** — the tuner
protocol call — and 63 were consumed by some node protocol. Those values are
neither authorities the workflow consults nor state that evolves; they arrive
whole from the caller and leave whole. Their lifecycle is *pure transit*.

Putting them on ``WorkflowRunBindings`` alongside the run invariants and the
metric authority would have rebuilt the parameter bag this milestone exists to
remove, because the membership rule would have degenerated to "it was a
parameter". Here the rule is honest and enforceable:

    caller-supplied configuration this run forwards to its nodes
    and never interprets as an authority.

WHAT THIS IS NOT (frozen contract, Amendment B)
------------------------------------------------
It is **not** an authority for CLI defaults, task identity, model semantics,
``ModelIOContract``, objective semantics, ``MetricSpec``/direction, the Health
roster or thresholds, ``TaskDataPath``, plugin discovery, or any task-specific
scientific behaviour. Every one of those keeps its existing owner; this carrier
transports their already-resolved values.

Concretely that means:

* it **restates no default** — each field carries exactly the default
  ``run_workflow`` already had, and where a value has a schema-level owner
  downstream, that owner still validates it;
* it adds **no validation** — ``HyperparamTuningInput``, ``InterpretationInput``
  and ``ProposalInput`` already validate what they receive, and duplicating
  those rules here would create a second authority;
* it holds **no capability reference** — those are on the bindings carrier;
* it holds **no cross-iteration state** — enforced structurally against
  :class:`core.chain_state.ChainState`.

Its size is a measurement of the real transport surface, not a design failure.
**72 fields is not claimed as a final generic public API**: Step 10/12 may
reduce or replace how these values are supplied once the unified launcher and
composition root exist. Step 09.5a only establishes coherent *current*
ownership.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields as dataclass_fields

from agent.schemas.hyperparam_tuning import HealthGateMode, ResultAuthority
from agent.schemas.proposal import OutputTypeName
from core.runtime_control.admission import AdmissionEnforcement
from workflows.strategy_modes import ExplorationMode, FormalRoundStrategy, StrategyMode


@dataclass(frozen=True, slots=True)
class WorkflowLaunchConfig:
    """Immutable launch/execution configuration for one exploration run.

    Field order and defaults mirror ``run_workflow``'s original signature
    exactly, grouped by the sink each value is forwarded to, so a reader can see
    where every value goes.
    """

    source_paths: list[str] | None = None
    data_dir: str | None = None
    model_types: list[str] | None = None
    source_run_name: str | None = None
    max_iterations: int = 1
    start_iteration: int = 1
    max_rounds: int = 10
    max_proposal_attempts: int = 3
    target_score: float | None = None
    file_index: int = 6
    healthgate_mode: HealthGateMode | None = None
    result_authority: ResultAuthority | None = None
    human_advice_interpret: str | None = None
    human_advice_propose: str | None = None
    human_advice_implement: str | None = None
    human_advice_validate: str | None = None
    human_advice_tune: str | None = None
    human_advice_mindset: str | None = None
    is_trial: bool = False
    # Lane F2 (campaign-portion authority, 2026-08-26) — TRI-STATE: a TYPED
    # value is EXPERIMENT_FIXED (merged into the plan_overrides lock by
    # `frozen_portion_overrides`, so trial planning cannot silently override
    # it); None is AGENT_CONTROLLED (nothing merged; the planner's values
    # execute). The old concrete 0.1 defaults made "typed" indistinguishable
    # from "defaulted" — which is how the frozen campaign portions died in
    # transit (the tuner-input portion fields have NO tuner consumer).
    trial_portion: float | None = None
    train_portion: float | None = None
    # eval_portion joins the same tri-state/merge (Lane C's E1/E2/E3 audit
    # verdict, 2026-08-26): per-epoch validation (E1) and round-end scoring
    # (E2) SCALE with it; HealthGate (E3) consumes fixed prefix peeks and is
    # insensitive. That insensitivity is E3's own property — the portion
    # authority carries ONE value and never branches on which consumer
    # reads it. FORMAL frozen portions are NOT carried here: they ride the
    # existing formal_* fields (plan_overrides trial keys are DISCARDED on
    # formal rounds — the F14 mechanism).
    eval_portion: float | None = None
    train_validation_align: bool = True
    sampling_seed: int | None = None
    train_base_seed: int | None = None
    cleanup_denoised: bool = False
    max_epochs: int | None = None
    # D-BUD-6 — per-mode epoch ceilings (trial/formal split). None = the
    # mode-agnostic max_epochs governs that role, byte-identical to the
    # pre-split behavior. Validated ge=1 by HyperparamTuningInput.
    trial_max_epochs: int | None = None
    formal_max_epochs: int | None = None
    skip_formal_min_delta: float = -1.0
    bypass_formal_time_budget_min_delta: float = 0.0
    # Lane F3 — the elevated bypass ceiling; None = a qualified bypass
    # grants NO extension (the schema default's safety semantics).
    bypass_formal_time_budget_minutes: float | None = None
    plan_overrides: dict | None = None
    trial_time_budget_minutes: float | None = None
    formal_time_budget_minutes: float | None = None
    gpu_admission_measurement_source: str | None = None
    gpu_admission_enforcement: AdmissionEnforcement = "observe_only"
    gpu_pair_ceiling_gib: float | None = None
    trial_vram_budget_gb: float | None = None
    formal_vram_budget_gb: float | None = None
    vram_probe_step_timeout_seconds: float = 180.0
    vram_preflight_total_timeout_seconds: float = 900.0
    vram_preflight_host_memory_limit_gb: float | None = None
    formal_strategy: StrategyMode = "snapshot"
    formal_portion: float = 0.1
    formal_train_portion: float = 1.0
    formal_eval_portion: float = 1.0
    force_formal_round: bool = True
    formal_round_strategy: FormalRoundStrategy = "full_clone"
    degenerate_penalty_score: float | None = None
    attempts_per_round: int = 3
    attempts_per_formal_round: int = 5
    max_fail_rounds: int = 3
    max_steps_per_attempt: int | None = None
    min_formal_batch_size: int | None = None
    allow_extreme_steps: bool = False
    runtime_watchdog_enabled: bool = False
    runtime_safety_factor: float = 1.0
    runtime_trial_safety_factor: float | None = None
    runtime_formal_safety_factor: float | None = None
    runtime_watchdog_safety_factor: float | None = None
    runtime_watchdog_floor_seconds: float = 60.0
    exploration_mode: ExplorationMode = "auto"
    minimum_boldness: float = 0.05
    n_candidates: int | None = None
    max_impl_attempts: int = 3
    debug_dump_prompts: bool = False
    validation_fixed_candidate_plan: dict | None = None
    validation_max_portion: float | None = None
    validation_max_train_samples: int | None = None
    validation_max_samples: int | None = None
    validation_max_phase_seconds: float | None = None
    enable_chain_incumbent_formal_gates: bool = False
    health_feedback_history_window_iterations: int = 3
    health_feedback_history_max_entries_per_model: int = 8
    lit_review_enabled: bool = False
    lit_review_config_path: str | None = None
    require_probe_runner: bool = False
    # arXiv U1 (#254) — the OPAQUE experiment-arm label. Pure transit: the
    # workflow locks it and forwards it to the tuner; it never interprets
    # it (ruling R2). `None` is the unlabelled legacy run.
    experiment_arm: str | None = None
    # arXiv U3 (#260) — the WITHOUT arm's explicit isolation flag. Transit:
    # the workflow locks it, forwards it to the interpreter / proposer /
    # tuner inputs and refuses a bundled built-in proposal under it.
    baseline_isolation: bool = False
    # Gold campaign (advice-invariant) — the advice artifact this launch
    # OBSERVED. Pure transit: the workflow locks the pair and never reads it,
    # exactly like `experiment_arm` above. The advice CONTENT travels
    # separately in the `human_advice_*` fields; these two say WHICH bytes
    # that content came from, so a resume under different advice refuses.
    # `None` is the no-advice run (every legacy launch).
    advice_path: str | None = None
    advice_sha256: str | None = None
    # arXiv #259 (fleet ruling 2026-08-25) — the run's declared output-type
    # constraint for proposed models. Transit only: threaded into
    # ProposalInput.allowed_output_types, where the schema gate enforces it.
    # None = unconstrained legacy behavior (byte-identical prompts).
    allowed_output_types: tuple[OutputTypeName, ...] | None = None

    def __post_init__(self) -> None:
        """Refuse cross-iteration state (Amendment B).

        The forbidden set is DERIVED from :class:`core.chain_state.ChainState`
        rather than hand-listed, so it cannot go stale when that carrier grows —
        the failure mode of every maintained-by-hand deny list.
        """
        from core.chain_state import ChainState

        mutable = {f.name for f in dataclass_fields(ChainState)}
        offending = sorted(mutable & {f.name for f in dataclass_fields(self)})
        if offending:
            raise TypeError(
                f"WorkflowLaunchConfig must not carry cross-iteration state: {offending}. "
                "It is transit configuration — values that arrive whole from the caller "
                "and are forwarded unchanged. State that evolves across iterations "
                "belongs to ChainState, which owns its own lifecycle."
            )


def launch_config_field_names() -> frozenset[str]:
    """The carrier's field names — used by the structural censuses."""
    return frozenset(f.name for f in dataclass_fields(WorkflowLaunchConfig))


#: Lane F2 — the three plan-portion fields a TYPED launch value freezes.
#: Deliberately the LAUNCH-side trio (the plan fields the trial resolver
#: reads); the schema's TRIAL_SCOPED_OVERRIDE_KEYS is the RESOLVER-side
#: discard vocabulary (six keys incl. strategies + is_trial) — related
#: subjects, different sets, named separately on purpose (SRI-1).
FROZEN_PORTION_FIELDS: tuple[str, ...] = ("trial_portion", "train_portion", "eval_portion")


def frozen_portion_overrides(launch: WorkflowLaunchConfig) -> dict | None:
    """Lane F2 — merge EXPERIMENT_FIXED portions into the plan_overrides lock.

    The campaign's frozen TRIAL portions used to die in transit: the chain
    forwarded them into tuner-input fields no tuner code consumes, while
    trial workload came exclusively from the LLM plan. The ONE working
    operator authority is the ``plan_overrides`` lock (FU-10 validation,
    ``TRIAL_SCOPED_OVERRIDE_KEYS``, the F14 satisfiability refusal and
    mode-aware disclosure all apply to it unchanged) — so a TYPED portion
    joins it here, and an untyped one (``None``) stays AGENT_CONTROLLED.

    Conflict rule: the same key present in the operator's explicit
    ``--plan_overrides`` JSON with a DIFFERENT value is two authorities for
    one value — refused loudly. Identical values are fine.

    FORMAL frozen portions never pass through here: ``plan_overrides``
    trial keys are DISCARDED on formal rounds (the F14 mechanism), and the
    formal freeze's working carrier is the existing ``formal_*`` fields.

    Returns the merged dict (or the original/None when nothing is typed),
    never mutating ``launch.plan_overrides``.

    Raises:
        ValueError: a typed portion conflicts with an explicit
            ``plan_overrides`` entry for the same key.
    """
    typed = {
        field: value
        for field in FROZEN_PORTION_FIELDS
        if (value := getattr(launch, field)) is not None
    }
    if not typed:
        return launch.plan_overrides
    existing = dict(launch.plan_overrides or {})
    conflicts = {
        key: (existing[key], value)
        for key, value in typed.items()
        if key in existing and existing[key] != value
    }
    if conflicts:
        raise ValueError(
            "frozen portion flag(s) conflict with explicit --plan_overrides "
            f"entries for the same key(s) {{key: (plan_overrides, flag)}}: {conflicts}. "
            "Two authorities for one value — pick one: drop the flag or fix the JSON."
        )
    return existing | typed
