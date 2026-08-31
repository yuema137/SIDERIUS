#!/usr/bin/env python3
"""
workflows/model_exploration.py — First SIDERIUS workflow.

Iterative model exploration loop:

  for each iteration:
      interpret (all accumulated results)
      for each attempt (up to max_proposal_attempts):
          propose (with previous failures if retrying)
          implement
          validate
          if passed → break
      tune the validated model
      accumulate results for next iteration

Stop conditions (whichever comes first):
  - max_iterations reached (successful iterations = validated + tuned)
  - target_score achieved (best_denoising_score >= target)

Single-pass mode is max_iterations=1 (the default).

This is a workflow, not an orchestrator — the path is fixed and deterministic.
The workflow retries propose→implement→validate on validation failure, feeding
error messages back to the proposal agent. Full retry/rerouting logic belongs
in a future orchestrator.

Storage layout (run_name is consistent across all files):
  {workspace}/{run_name}/
  ├── workflow_{run_name}.json
  ├── iteration_001/
  │   ├── interpretation_{run_name}.json
  │   ├── attempt_001_{model_name}/  (renamed from attempt_001 once proposed)
  │   │   ├── proposal_{run_name}.json
  │   │   ├── impl_001/              (one dir PER implement→validate attempt, S2 / U6)
  │   │   │   ├── implementor_{run_name}.json
  │   │   │   ├── validation_{run_name}.json
  │   │   │   ├── models/{model_name}.py  (+ models/{model_name}/description.md)
  │   │   │   ├── tests/test_{model_name}.py
  │   │   │   └── losses/{loss_name}.py
  │   │   └── impl_002/ ...          (a retry never overwrites impl_001)
  │   └── {model_name}/              (tuning output, named by proposed model)
  │       ├── run_output_{run_name}.json
  │       ├── summary_{run_name}.json (derived view of records/{run_name}/records.jsonl)
  │       ├── run_config_{run_name}.json
  │       ├── cached_models/
  │       ├── configs/
  │       └── records/
  ├── iteration_002/
  │   └── ...

Usage:
  python workflows/model_exploration.py \\
      --data_dir /home/klz/Data/SIDEREIS_DATA \\
      --models punet wavenet \\
      --workspace ./workflow_output \\
      --run_name explore_v1 \\
      --max_iterations 3 \\
      --max_rounds 10
"""

import argparse
import gc
import hashlib
import json
import os
import shutil
import time
import warnings
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import psutil as _psutil
import yaml

from agent.prompt_templates.implementor.task_blocks import load_implementor_task_blocks
from agent.prompt_templates.interpretation.task_blocks import load_interpretation_task_blocks
from agent.prompt_templates.proposal.task_blocks import load_proposal_task_blocks
from agent.schemas.external_agents import ExternalAgentOutput
from agent.schemas.health_feedback import TrialValidityFeedback
from agent.schemas.hyperparam_tuning import (
    GateExhaustionInfo,
    HyperparamTuningInput,
    HyperparamTuningOutput,
    PhysicalRejection,
)
from agent.schemas.interpretation import (
    InterpretationInput,
    InterpretationOutput,
    ModelRunSummary,
    PredictionMemory,
)
from agent.schemas.ordering import OrderStrategy
from agent.schemas.proposal import ExpertContextItem, ProposalOutput, VocabEntry
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from agent.utils.proposer_preflight import (
    UNCONSTRAINED_TRAIN_PORTION,
    UNCONSTRAINED_TRIAL_PORTION,
)
from core.chain_state import ChainState
from core.hardware_context import get_or_create as get_or_create_hardware_context

# Step 12 / PR-12a C6 — `core.resume` no longer imports a private symbol from
# THIS module, so the cycle that forced `RestoredState` under TYPE_CHECKING and
# `union_key_findings` into a function-local import is gone. Both are ordinary
# top-level imports again.
from core.resume import RestoredState, union_key_findings
from core.run_invariants import (
    LockLaunchIdentity,
    RunHealthMaterialization,
    build_run_invariants,
    ensure_run_invariants,
    validate_stamped_invariants,
)
from core.runtime_control.launch_guard import run_launch_self_test
from core.runtime_control.measurement_capability import ResolvedMeasurementCapability
from execute_tools.dataset_config import DataScope, resolve_dataset_profile
from execute_tools.evaluation_metric import (
    StampedMetricSpec,
    metric_identity_unavailable_notice,
    reconcile_metric_specs,
)
from execute_tools.health_checks._composition import HealthBindingState
from execute_tools.health_checks.candidate_eligibility import resolve_run_scientific_gate_ids
from execute_tools.impl_attempts import impl_attempt_dir
from execute_tools.metric_order import MetricOrder
from ml_models.plugin_loader import register_model_in_memory
from nodes.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.ml_literature_review import MLLiteratureReviewAgent
from nodes.ml_model_implementor import MLModelImplementor
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.result_interpretation_agent import (
    ResultInterpretationAgent,
    reconcile_metric_spec,
    tuning_output_to_model_run_summary,
)
from workflows.llm_config import ProposalLLMConfig, WorkflowLLMConfig
from workflows.run_bindings import WorkflowRunBindings
from workflows.run_config import WorkflowLaunchConfig, frozen_portion_overrides
from workflows.strategy_modes import (
    ExplorationMode,
    FormalRoundStrategy,
    StrategyMode,
)
from workflows.task_composition import (
    RunTaskComposition,
    bind_run_task_composition,
    build_task_composition_ref,
    compose_run_task_bindings,
    verify_composition_is_bound,
)
from workflows.task_config import (
    default_task_config_path,
    get_task_description,
    load_task_config,
)

SIDERIUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _log_rss(step: str) -> None:
    """Print orchestrator RSS at a named workflow step.

    Added after the v15 arch chain was OOM-killed at 53 GB anon_rss during
    VRAM pre-flight (Iter 1, 2026-06-24). The kill arrived between the
    ``[Probe RSS] delta=0.46 GB`` log line and the bash wrapper's ``Killed``
    print, so we never saw which earlier step allocated the bulk of the 52 GB.
    These checkpoints make the allocation site visible in screen logs before
    any future OOM.

    Cheap: one ``psutil.Process().memory_info()`` call (~µs) plus a single
    ``print`` per checkpoint. Safe to leave on permanently — no privileged
    syscalls, no flush stalls (``flush=True`` keeps screen captures crisp
    if the next allocation crashes immediately).
    """
    rss_gb = _psutil.Process().memory_info().rss / 1024**3
    print(f"[RSS] {step}: {rss_gb:.2f} GB", flush=True)


# Centralised Literal type aliases that match the protocol-layer signatures.
# Defined here so the four strategy kwargs threaded through ``run_workflow`` /
# ``_get_reasoning_pipeline`` carry the same narrow types as their downstream
# consumers (``ReasoningPipelineConfig.exploration_mode``,
# ``local_validated_model.{formal,formal_round}_strategy``) without
# per-call casts. (DS7 removed the trial/eval strategy threading.)
# Step 09.5a C2 — the three aliases moved to `workflows/strategy_modes.py` so
# `workflows/run_config.py` can type its fields without importing this module
# (which imports it). Re-exported here: same objects, one definition, every
# existing `from workflows.model_exploration import StrategyMode` still works.
ExplorationMode = ExplorationMode
StrategyMode = StrategyMode
FormalRoundStrategy = FormalRoundStrategy


#: Lane F2 — the tuner-input portion fields are TRANSIT-ONLY (no tuner
#: consumer; the executed lock is plan_overrides). A bare launch (None)
#: restores each field's own schema default, keeping input bytes identical
#: to pre-F2 runs. Derived from the schema, never restated.
_TUNER_INPUT_PORTION_DEFAULTS: dict[str, float] = {
    name: HyperparamTuningInput.model_fields[name].default
    for name in ("trial_portion", "train_portion", "eval_portion")
}


def _portion_or(value: float | None, fallback: float) -> float:
    """None -> fallback. Module-level so call sites inside ``run_workflow``
    add ZERO branch nodes (the §12.1 frozen tripwire counts If/IfExp)."""
    return fallback if value is None else value


def _load_vocab_seed() -> list:
    """Load the canonical vocabulary seed from agent/schemas/vocab_seed.json.

    Returns a list of VocabEntry objects. Returns empty list if the file
    is missing (backward compat — legacy workflows without vocab).
    """
    seed_path = os.path.join(SIDERIUS_ROOT, "agent", "schemas", "vocab_seed.json")
    if not os.path.exists(seed_path):
        return []
    try:
        from agent.schemas.proposal import VocabEntry

        with open(seed_path, encoding="utf-8") as f:
            raw = json.load(f)
        return [VocabEntry.model_validate(entry) for entry in raw]
    except Exception as e:
        print(f"Warning: failed to load vocab seed: {e}")
        return []


def _get_reasoning_pipeline(
    llm_config: WorkflowLLMConfig,
    exploration_mode: ExplorationMode = "auto",
    minimum_boldness: float = 0.05,
    n_candidates: int | None = None,
):
    """Build a ReasoningPipelineConfig from the workflow's ProposalLLMConfig.

    Returns None if propose is not a ProposalLLMConfig (legacy mode).

    Args:
        llm_config: Workflow LLM config; must have a ProposalLLMConfig in the
            propose slot for the pipeline to be active.
        exploration_mode: One of "auto", "explore", "exploit".
            "auto" lets the pipeline resolver choose based on n_agent_proposed
            and vocab_diversity_ratio. "explore" and "exploit" force the mode
            regardless of those signals.
        minimum_boldness: Minimum required boldness for a FalsifiablePrediction
            (|predicted - current| / |current|). Predictions below this threshold
            trigger a causal_reasoning retry. Default 0.05.
        n_candidates: Optional override for the top-N candidate cut used by the
            comparison stage. When None, falls through to the schema default
            (ModelSelectionStrategy → {"n": 5}). Set to a larger value for
            large-scale experiments that want more past models in the prompt.
    """
    if llm_config.propose and isinstance(llm_config.propose, ProposalLLMConfig):
        from agent.schemas.proposal import (
            ModelSelectionStrategy,
            ReasoningPipelineConfig,
            ReasoningStage,
            ResearchPolicy,
        )

        selection = (
            ModelSelectionStrategy(params={"n": n_candidates})
            if n_candidates is not None
            else ModelSelectionStrategy()
        )
        pipeline = ReasoningPipelineConfig(
            stages=[
                ReasoningStage(name="comparison", system_prompt_key="COMPARATIVE_ANALYSIS"),
                ReasoningStage(name="causal_reasoning", system_prompt_key="CAUSAL_REASONING"),
            ],
            model_selection=selection,
            exploration_mode=exploration_mode,
            policy=ResearchPolicy(minimum_boldness=minimum_boldness),
        )
        return pipeline
    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_tuning_outputs_from_paths(
    paths: list[str],
) -> list[HyperparamTuningOutput]:
    """
    Load HyperparamTuningOutput from an explicit list of JSON file paths.

    Used by per-iteration Slurm runs where each iteration's source data
    is a heterogeneous list of paths (original seeds + previous iterations'
    outputs), which can't be derived from a single run_name pattern.

    Args:
        paths: List of explicit paths to run_output_*.json files.

    Returns:
        List of validated HyperparamTuningOutput objects (one per path).
        Raises FileNotFoundError if any path is missing or invalid.
    """
    outputs = []
    missing = []
    for path in paths:
        if not os.path.exists(path):
            missing.append(f"  not found: {path}")
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            output = HyperparamTuningOutput.model_validate(data)
            outputs.append(output)
            print(
                f"  Loaded: {path} "
                f"({output.model_type}, {len(output.all_records)} records, "
                f"best={output.best_denoising_score})"
            )
        except Exception as e:
            missing.append(f"  invalid: {path} — {e}")

    if missing:
        raise FileNotFoundError("Missing or invalid source files:\n" + "\n".join(missing))
    return outputs


def load_tuning_outputs(
    data_dir: str,
    model_types: list[str],
    source_run_name: str,
) -> list[HyperparamTuningOutput]:
    """
    Backward-compat wrapper: load HyperparamTuningOutput from a single run by
    constructing paths from (data_dir, model_types, source_run_name).

    Looks for:
      {data_dir}/{model_type}/{source_run_name}/agent/run_output_{source_run_name}_agent.json

    Prefer ``load_tuning_outputs_from_paths()`` for new code.

    Args:
        data_dir: Root data directory (e.g. /home/klz/Data/SIDEREIS_DATA).
        model_types: Model type keys to load (e.g. ["punet", "wavenet"]).
        source_run_name: The run name to load from (e.g. "small_sample_trial_v0").

    Returns:
        List of validated HyperparamTuningOutput objects (one per model).
        Raises FileNotFoundError if any model's output is missing.
    """
    paths = [
        os.path.join(
            data_dir,
            model_type,
            source_run_name,
            "agent",
            f"run_output_{source_run_name}_agent.json",
        )
        for model_type in model_types
    ]
    return load_tuning_outputs_from_paths(paths)


def tuning_outputs_to_summaries(
    outputs: list[HyperparamTuningOutput],
    *,
    order: MetricOrder | None,
    required_gate_ids: frozenset[str] | None = None,
) -> list[ModelRunSummary]:
    """
    Convert a list of HyperparamTuningOutput objects into condensed
    ModelRunSummary objects suitable for InterpretationInput.

    Raw experiment records are NOT carried forward — only aggregates
    and per-round scores/conclusions are extracted.

    ``required_gate_ids`` is the run's scientific gate set, resolved ONCE from
    its own Health declaration (Step 10 / P5+P6 W6) and passed down as a
    resolved value. ``None`` = the legacy default, unchanged.
    """
    return [
        tuning_output_to_model_run_summary(o, order=order, required_gate_ids=required_gate_ids)
        for o in outputs
    ]


def _make_storage(workspace: str, run_name: str) -> StorageConfig:
    """Create a StorageConfig pointing at a specific workspace directory."""
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=workspace, run_name=run_name),
    )


@dataclass(frozen=True)
class ImplAttemptStorage:
    """Where ONE implement→validate attempt persists (S2 / U6, #256).

    Every field is derived from the nested ``impl_NNN`` directory the
    ``execute_tools.impl_attempts`` authority names, so the implementor
    record, the validation record and the three generated-source
    directories of one retry can never overwrite another's.
    """

    impl_dir: str
    storage: StorageConfig
    plugin_dir: str
    test_dir: str
    loss_dir: str


def impl_attempt_storage(attempt_dir: str, run_name: str, impl_attempt: int) -> ImplAttemptStorage:
    """The typed persistence boundary for implementation attempt ``impl_attempt``.

    Before U6 the loop reused the proposal attempt's storage and derived
    ``models/`` / ``tests/`` / ``losses/`` from ``attempt_dir`` on every
    retry, so a retry silently replaced the previous attempt's records and
    sources. Extracted so the loop body only sequences; the layout is owned
    here and read back by ``funnel_assembly`` / ``workflow_validation``
    through the same authority.
    """
    impl_dir = impl_attempt_dir(attempt_dir, impl_attempt)
    return ImplAttemptStorage(
        impl_dir=impl_dir,
        storage=_make_storage(impl_dir, run_name),
        plugin_dir=os.path.join(impl_dir, "models"),
        test_dir=os.path.join(impl_dir, "tests"),
        loss_dir=os.path.join(impl_dir, "losses"),
    )


def _snapshot_task_config(run_dir: str) -> None:
    """Copy ``configs/task_config.yaml`` into ``run_dir`` as
    ``task_config_snapshot.yaml`` for replay provenance.

    Called once during ``run_workflow`` setup, immediately after
    ``os.makedirs(run_dir, exist_ok=True)``. The "copy only if absent"
    guard means the snapshot is written on the first invocation that
    initializes a clean ``run_dir`` and skipped on every subsequent call —
    chain mode (iter 2+ in the same chain) therefore preserves the
    config that was active when iter 1 ran, even if the operator edits
    ``configs/task_config.yaml`` mid-chain.

    The source path comes from :func:`default_task_config_path` — the ONE
    SIDERIUS_ROOT-anchored resolution authority (F-SCANA-2) that also
    serves ``load_task_config`` (the read) and ``task_config_file_sha256``
    (the F-SCANH-1 lock pin) — so the snapshot, the read and the pinned
    sha address the SAME file regardless of the process cwd.

    See ``docs/design/enable_global_task_config.md`` § "Run provenance —
    task config snapshot" + § Commit T1b for the design + chain-mode
    rationale.
    """
    snapshot_path = os.path.join(run_dir, "task_config_snapshot.yaml")
    if not os.path.exists(snapshot_path):
        shutil.copy2(default_task_config_path(), snapshot_path)


# ---------------------------------------------------------------------------
# Phase 6.6 WS-B B.3 Hop 4 — worst-offender aggregation + [PHYSICAL
# REJECTION] renderer. One entry per (prior-iteration tuning output,
# architecture) group; fed to the next Proposer's previous_failures so
# the LLM sees per-architecture lessons, not every failed attempt.
# See docs/phase66_ws_b_proposer_hardening.md §2.4 / §3.2.
# ---------------------------------------------------------------------------


def _aggregate_worst_offender_rejections(
    rejections: list[PhysicalRejection],
) -> list[tuple[PhysicalRejection, int]]:
    """Group rejections by ``attempt_config["model_type"]``; return one
    ``(worst_rejection, count_in_group)`` tuple per group.

    Worst = highest ``estimated_gb / budget_gb`` ratio; tie broken by
    higher ``dominant_fraction``. ``budget_gb == 0`` is treated as +inf
    ratio — a degenerate signal the orchestrator should still surface.

    Empty input -> empty output (no-op for iterations with zero rejections).
    """
    if not rejections:
        return []

    from collections import defaultdict

    groups: dict[str, list[PhysicalRejection]] = defaultdict(list)
    for r in rejections:
        mt = str(r.attempt_config.get("model_type", "unknown"))
        groups[mt].append(r)

    out: list[tuple[PhysicalRejection, int]] = []
    for _mt, rejs in groups.items():

        def _rank(r: PhysicalRejection) -> tuple[float, float]:
            ratio = (r.estimated_gb / r.budget_gb) if r.budget_gb > 0 else float("inf")
            return (ratio, r.dominant_fraction)

        worst = max(rejs, key=_rank)
        out.append((worst, len(rejs)))
    return out


def _synthetic_prior_iter_tune_output(
    ge: GateExhaustionInfo | None = None,
    trial_validity_feedback: TrialValidityFeedback | None = None,
) -> HyperparamTuningOutput:
    """Wrap prior-chain negative feedback as a minimal
    ``HyperparamTuningOutput`` for the ``recent_tune_outputs`` deque.

    The interp→propose protocol's only read of each deque entry is
    ``tune_out.gate_exhaustion``; every other required field is just a
    placeholder. Used by chain-mode workflow entry to surface cross-iter
    gate aborts (loaded from RestoredState) to the proposer's
    ``[RECENT GATE EXHAUSTIONS]`` prompt block. See docs/V8_Gap_Report.md
    Domain 1.
    """
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    return HyperparamTuningOutput(
        run_name="prior_iter",
        model_type="(prior_iter)",
        file_index=-1,
        status="completed",
        completed_rounds=0,
        total_attempts=0,
        gate_exhaustion=ge,
        trial_validity_feedback=trial_validity_feedback,
        started_at=now,
        finished_at=now,
    )


def _restored_negative_feedback(
    restored_state: RestoredState | None,
) -> list[tuple[GateExhaustionInfo | None, TrialValidityFeedback | None]]:
    """Return the current typed channel, with the pre-#396 fallback."""
    if restored_state is None:
        return []
    if restored_state.accumulated_negative_feedback:
        return restored_state.accumulated_negative_feedback
    return [(item, None) for item in restored_state.accumulated_gate_exhaustions]


def _seed_recent_negative_feedback(
    state: ChainState,
    feedback: list[tuple[GateExhaustionInfo | None, TrialValidityFeedback | None]],
) -> None:
    """Seed the bounded proposer window from prior chain iterations."""
    if not feedback:
        return
    for gate_exhaustion, trial_feedback in feedback:
        state.recent_tune_outputs.append(
            _synthetic_prior_iter_tune_output(gate_exhaustion, trial_feedback)
        )
    count = len(state.recent_tune_outputs)
    print(
        f"  [chain] Pre-seeded recent_tune_outputs with {count} "
        f"cross-iter negative-feedback summar{'y' if count == 1 else 'ies'} "
        f"(deque maxlen=3 keeps the latest)."
    )


def _render_physical_rejection(rej: PhysicalRejection, n_rejections: int) -> str:
    """Render one aggregated ``[PHYSICAL REJECTION]`` string for the
    Proposer's ``previous_failures`` list.

    Format (multi-line, leading ``[PHYSICAL REJECTION]`` tag so the
    downstream prompt's "DO NOT repeat these mistakes" header is
    unambiguous; the Proposer's existing previous_failures renderer in
    ``_build_reasoning_prompt`` splices the whole string verbatim):

        [PHYSICAL REJECTION] <model_type>: rejected N attempt(s) by the VRAM gate.
          Worst offender: estimated X.XX GB > budget Y.YY GB (binding cap: ...).
          Dominant layer: <name> consumed Z.ZZ GB (PP% of peak).
          Attempted config: {...}.
          Suggestion: <verbatim from killer_report>.
    """
    model_type = str(rej.attempt_config.get("model_type", "unknown"))
    plural = "s" if n_rejections != 1 else ""
    lines = [
        f"[PHYSICAL REJECTION] {model_type}: rejected {n_rejections} "
        f"attempt{plural} by the VRAM gate.",
        f"  Worst offender: estimated {rej.estimated_gb:.2f} GB > "
        f"budget {rej.budget_gb:.2f} GB (binding cap: {rej.binding_cap}).",
    ]
    if rej.dominant_layer:
        lines.append(
            f"  Dominant layer: {rej.dominant_layer} consumed "
            f"{rej.dominant_layer_gb:.2f} GB "
            f"({rej.dominant_fraction * 100:.0f}% of peak)."
        )
    lines.append(f"  Attempted config: {rej.attempt_config}.")
    if rej.suggestion:
        lines.append(f"  Suggestion: {rej.suggestion}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commit 6 — external-agent integration helpers
# ---------------------------------------------------------------------------


def should_run_literature_review(
    interp_output: InterpretationOutput,
    *,
    enabled: bool,
) -> bool:
    """Decide whether to run the literature-review node this iteration.

    For v1 this is just the resolved ``enabled`` flag (resolution priority
    CLI > YAML > default False — Design Decisions 1 + 2, 2026-06-11). The
    runner ``sdsc_submission_scripts/run_one_iteration.py`` resolves the
    boolean from ``--ml_lit_review_enabled`` / ``--no-ml_lit_review_enabled``
    (BooleanOptionalAction) against the YAML's top-level ``enabled``,
    then passes the result into ``run_workflow(lit_review_enabled=...)``.

    ``interp_output`` is reserved for future content-based gating — e.g.
    skip lit-review when ``cumulative_information_gain`` is above a
    threshold (the proposer has enough signal), or skip in pure-exploit
    mode. Marked unused via ``del`` to keep the contract obvious.

    Args:
        interp_output: This iteration's ``InterpretationOutput``.
            Reserved for future content-based gating; not consulted in v1.
        enabled: Resolved enable flag.

    Returns:
        ``True`` if lit-review should fire this iteration.
    """
    del interp_output  # reserved for future content-based gating
    return enabled


def merge_external_agent_outputs(
    outputs: list[ExternalAgentOutput],
) -> dict[str, Any]:
    """Merge external-agent outputs into the four-channel kwargs dict
    consumed by ``local_full_context(...)`` via ``**channels`` spreading.

    Three cases:

    * **N=0** (no external agents fired this iter): returns the empty
      default so the downstream call can ``**`` spread it unconditionally
      without branching on emptiness.
    * **N=1** (v1 — only ``ml_literature_review`` is active): delegates
      to the Commit-5 protocol's ``local_all_channels`` so the per-agent
      mapping logic is not duplicated here. The protocol's 4-kwarg dict
      is returned verbatim.
    * **N>=2** (future, when a second external agent — e.g. a physics
      agent — lands): list channels are concatenated; ``mindset`` uses
      the last non-``None`` (a v1 rule per commit plan §6.4 — flagged
      for revisit when a second agent populates ``mindset``).

    Args:
        outputs: External-agent outputs that ran this iteration. Order
            matters only for the ``last non-None mindset wins`` rule.

    Returns:
        Dict with exactly the 4 keys ``local_full_context`` accepts:
        ``expert_context``, ``vocab_seed``, ``agent_cards``, ``mindset``.
    """
    if not outputs:
        return {
            "expert_context": [],
            "vocab_seed": [],
            "agent_cards": [],
            "mindset": None,
        }
    if len(outputs) == 1:
        # Lazy imports: keep workflows.model_exploration's top-level
        # imports identical to pre-Commit-6 and avoid any risk of a
        # circular dependency if the protocol module ever needs to
        # reach back into a workflows.* helper.
        from agent.schemas.literature_review import LiteratureReviewOutput
        from agent.schemas.protocols.ml_literature_review_to_ml_model_propose import (
            local_all_channels,
        )

        # ``isinstance`` narrows ``outputs[0]`` from ``ExternalAgentOutput`` to
        # the protocol's expected ``LiteratureReviewOutput``. In v1 only
        # lit-review is wired, so this branch always fires; once a second
        # external agent (e.g. a physics agent) lands, an unknown subtype
        # would fall through to the generic merge below — future-proofing
        # without a special case today.
        if isinstance(outputs[0], LiteratureReviewOutput):
            return local_all_channels(outputs[0])
    # N>=2, OR N==1 with a non-lit-review subtype (future) — generic merge
    merged_findings: list[ExpertContextItem] = []
    merged_vocab: list[VocabEntry] = []
    merged_cards: list = []
    last_mindset: str | None = None
    for output in outputs:
        merged_findings.extend(output.findings)
        merged_vocab.extend(output.new_vocab_candidates)
        merged_cards.append(output.agent_card)
        if output.suggested_mindset is not None:
            last_mindset = output.suggested_mindset
    return {
        "expert_context": merged_findings,
        "vocab_seed": merged_vocab,
        "agent_cards": merged_cards,
        "mindset": last_mindset,
    }


def resolve_lit_review_config_path(config_path: str) -> str:
    """The ONE rule that turns a lit-review config path into a file to read.

    Relative paths resolve against ``SIDERIUS_ROOT`` (the checkout), exactly
    as the lit-review branch of ``run_workflow`` has always done; absolute
    paths are taken as-is. Both the workflow's read and the chain runner's
    ``enabled`` peek call this, so the lock's config pin can never describe
    a file the run does not read.
    """
    if os.path.isabs(config_path):
        return config_path
    return os.path.join(SIDERIUS_ROOT, config_path)


def lit_review_config_sha256(config_path: str | None, *, enabled: bool) -> str | None:
    """sha256 of the resolved lit-review YAML bytes, or ``None`` when disabled.

    arXiv U1 (#253): the lock pins the lit-review CONFIG, not just the
    topology flag — two runs whose literature-review node read different
    root-paper lists are not comparable. Hashed at pre-flight from the same
    resolved path the node later opens.

    Raises:
        ValueError: lit-review is enabled but the resolved config cannot be
            read. Refused here, before any LLM call, instead of crashing
            inside the iteration after the interpreter has already run.
    """
    if not enabled:
        return None
    if config_path is None:
        raise ValueError(
            "literature review is enabled but no config was declared. Supply "
            "the task or experiment config explicitly before launch."
        )
    resolved = resolve_lit_review_config_path(config_path)
    try:
        with open(resolved, "rb") as f:
            payload = f.read()
    except OSError as exc:
        raise ValueError(
            f"lit-review is enabled but its config {resolved!r} cannot be read "
            f"({exc}). The run-invariants lock pins the config's sha256, so an "
            "unreadable config is refused at pre-flight rather than after the "
            "first LLM call."
        ) from exc
    return hashlib.sha256(payload).hexdigest()


def _build_lit_review_input(
    config: dict,
    interp_output: InterpretationOutput,
    *,
    llm_kwargs: dict,
    storage: StorageConfig,
    run_name: str,
):
    """Build a ``LiteratureReviewInput`` from the parsed YAML + workflow state.

    Maps the YAML's operator-visible knobs into the schema fields, fills the
    workflow-supplied fields (``experiment_history`` / ``storage`` / ``run_name``)
    and the LLM-routing fields from ``llm_kwargs`` (the 4-field flatten from
    ``WorkflowLLMConfig.get('lit_review')``).

    Schema ``default_factory`` fires for any block omitted from the YAML, but
    Design Decision 3 (2026-06-11) requires every operator-visible knob to be
    present in the YAML — operator visibility, not minimal config.

    ``task_description`` is the ONE exception: since Step 04b it is resolved
    from the canonical task profile (``configs/task_config.yaml``) and is
    never read from ``config``. See
    ``docs/design/generic_framework_upgrade/step_04_candidate_creation_mechanics/
    pr_04b_task_description_single_source.md``.

    Args:
        config: Parsed YAML dict from the caller-supplied path given through
            ``--ml_lit_review_config``.
            Supplies the lit-review module's own knobs only — root papers,
            search, verbosity, synthesis, confidence rubric. A
            ``task_description`` key here is stale and is ignored.
        interp_output: This iteration's ``InterpretationOutput``; populates
            ``experiment_history``.
        llm_kwargs: 4-field LLM routing flatten from
            ``WorkflowLLMConfig.get('lit_review')``: ``llm_provider``,
            ``llm_model_id``, ``search_llm_provider``,
            ``search_llm_model_id``.
        storage: Iter-scoped storage; the lit-review node writes its
            output under
            ``{storage.local.workspace}/ml_literature_review_{run_name}.json``.
        run_name: Chain-wide run name (same as the rest of the workflow).
    """
    # Lazy import keeps top-of-file imports identical to pre-Commit-6 for
    # the lit-review schema types (which form a long import chain).
    from agent.schemas.literature_review import LiteratureReviewInput

    # Step 04b — SINGLE SOURCE. The task description is resolved from the
    # active task declaration, NOT from the lit-review YAML. `config` is deliberately
    # not consulted for this key: a stale operator copy that still carries
    # `task_description:` must be IGNORED, never merged or preferred, or the
    # duplicate authority this PR removed would return invisibly.
    #
    # Same accessor and same call shape as the sibling production consumers
    # (interpreter / proposer / implementor / tuner in this module). Its
    # fail-closed semantics are upstream and deliberate: `load_task_config`
    # already rejects a missing or empty task description, which is why the
    # pre-04b empty-value warning here is gone rather than reimplemented —
    # it guarded a state the canonical loader cannot produce.
    task_description = get_task_description(load_task_config())

    return LiteratureReviewInput.model_validate(
        {
            "experiment_history": interp_output,
            "root_papers": config.get("root_papers", []),
            "dynamic_search": config.get("dynamic_search", {}),
            "synthesis_config": config.get("synthesis", {}),
            "confidence_rubric": config.get("confidence_rubric", {}),
            "findings_verbosity": config.get("findings_verbosity", 1),
            "task_description": task_description,
            "storage": storage,
            "run_name": run_name,
            **llm_kwargs,
        }
    )


def _acquire_iteration_order(bindings, tune_output) -> MetricOrder | None:
    """The reconciled ``MetricOrder`` for one iteration's golden comparisons.

    Step 10 P2a C1, design §4.1. Acquisition is RECONCILIATION, not
    precedence: the run's bound composition spec and the compared output's own
    stamp are both offered to the ONE shared authority, so a composed run whose
    bound metric disagrees with what the artifact was actually scored under
    FAILS CLOSED instead of silently preferring either.

    Args:
        bindings: the run's ``WorkflowRunBindings``. ``task_composition`` is
            ``None`` on a non-composed (legacy) run, in which case the output's
            own stamp is the only identity available.
        tune_output: the ``HyperparamTuningOutput`` being folded in.

    Returns:
        The order to rank with, or ``None`` when no identity is available
        anywhere — the §4.2 unrankable state, which the caller must honour by
        NOT ranking rather than by assuming a direction.

    Raises:
        MetricIdentityConflictError: bound spec and artifact stamp declare
            different metrics. Deliberately not caught here: ranking an
            iteration on a metric it was not scored under is worse than
            stopping, and the message names both offenders.
    """
    composition = getattr(bindings, "task_composition", None)
    bound = getattr(getattr(composition, "metric", None), "spec", None)
    spec = reconcile_metric_specs(
        [
            StampedMetricSpec(
                label=f"{tune_output.run_name!r} ({tune_output.model_type!r})",
                spec=getattr(tune_output, "metric_spec", None),
            )
        ],
        bound=bound,
    )
    return MetricOrder(spec) if spec is not None else None


class _OncePerRunNotice:
    """Prints a named notice the FIRST time a run hits an unrankable state.

    Once per run rather than once per iteration: an unranked chain would
    otherwise print the same line on every iteration and bury the run's real
    output. The contexts that followed are still counted, so the closing line
    reports how many iterations were affected rather than implying one.
    """

    __slots__ = ("_contexts", "_shown")

    def __init__(self) -> None:
        self._shown = False
        self._contexts: list[str] = []

    def warn_once(self, context: str) -> None:
        self._contexts.append(context)
        if self._shown:
            return
        self._shown = True
        print(
            metric_identity_unavailable_notice(
                "the workflow best-score and chain-incumbent trackers",
                detail=f"first at {context}",
            )
        )

    @property
    def affected(self) -> tuple[str, ...]:
        return tuple(self._contexts)


def _cap_knowledge_cache(
    cache: dict,
    current_model: str,
    max_entries: int = 5,
    *,
    order: MetricOrder | None,
) -> tuple[dict, set[str]]:
    """Keep top-N models by best score + the current iteration's model.

    Interpreter-MEMORY truncation policy, hosted in the workflow file
    (parent §7, Q-09-3: semantic owner != physical location). Step 09a C3
    migrates its COMPARISON onto the run's ``MetricOrder`` and moves nothing:
    the retention count, the current-model exemption and the public
    orchestration are unchanged.

    Returns:
        (capped_cache, evicted_model_types)
    """
    if len(cache) <= max_entries:
        return cache, set()

    if order is None:
        raise ValueError(
            "capping the knowledge cache evicts models by score, which requires the "
            "run's MetricOrder. None was supplied and the cache is over its limit — "
            "refusing rather than evicting on an assumed direction."
        )

    scored = [
        (mt, entry.get("_stats", {}).get("best_denoising_score"))
        for mt, entry in cache.items()
        if mt != current_model
    ]
    # Step 09a C3. Was `reverse=True` with a `-inf` fill — both direction
    # literals: under a minimised metric that KEEPS the worst models and
    # evicts the best. `rank` is 1 + (values strictly better) and Python's
    # sort is stable, so equal ranks keep insertion order exactly as
    # `reverse=True` did, and a scoreless entry still ranks last because
    # `worst_sentinel` is the value nothing can be worse than.
    present = [value for _, value in scored if value is not None]
    scored.sort(
        key=lambda x: order.rank(present, x[1] if x[1] is not None else order.worst_sentinel)
    )
    keep = {current_model} | {mt for mt, _ in scored[: max_entries - 1]}
    evicted = set(cache) - keep
    capped = {mt: entry for mt, entry in cache.items() if mt in keep}
    return capped, evicted


_CONSTRUCTION_RSS_THRESHOLD_GB = 0.5  # 500 MB


def _validate_construction_memory(
    model_class: type,
    config_class: type,
    model_name: str,
    representative_T: int = 16000,
) -> None:
    """Validate that instantiating the model plugin does not allocate
    excessive RAM during ``__init__``.

    Catches faulty SSM/attention implementations that pre-allocate buffers
    scaling with T (e.g. ``[T, T]`` attention matrices, ``[B, T, d_state]``
    state buffers) in ``__init__`` rather than in ``forward()``. Added after
    the 2026-06-24 v15 arch chain was OOM-killed at 53 GB during VRAM
    pre-flight — the suspect was a generated SSM plugin with a T-scaling
    construction-time allocation that the structural VRAM probe could not
    catch (because the offending allocation lived in CPU host RAM, not CUDA).

    The check is cheap (one ``__init__`` call, no forward, no autograd)
    and tight (RSS delta measured around a single ``model_class(cfg)``
    invocation with ``gc.collect`` on either side).

    Args:
        model_class: the plugin's ``PLUGIN_MODEL_CLASS``.
        config_class: the plugin's ``PLUGIN_CONFIG_CLASS``.
        model_name: used in error messages.
        representative_T: sequence length to test — defaults to ``16000``
            which is the §10 attractor value for SSM/FNO families. At
            T=16000, a single ``[T, T]`` float32 matrix = 1 GB, well above
            the ``_CONSTRUCTION_RSS_THRESHOLD_GB`` floor. Injected into
            the config as ``segmentation_size`` when the schema accepts
            that field; otherwise the config's own defaults are used.

    Raises:
        ValueError: if construction RSS delta exceeds
            ``_CONSTRUCTION_RSS_THRESHOLD_GB`` OR if ``__init__`` itself
            raises (a plugin that cannot be constructed with default
            config is already rejected by the dummy-tensor validator, but
            we re-raise here as ``ValueError`` so callers see a uniform
            failure shape).
    """
    import gc as _gc
    import inspect as _inspect

    import psutil as _psutil
    import torch as _torch

    # Real plugins are always ``nn.Module`` subclasses (plugin loader
    # contract: ``PLUGIN_MODEL_CLASS: type — nn.Module subclass``). Stub
    # classes used by some fixture tests aren't, and would crash inside
    # ``model_class(cfg)`` for unrelated reasons. Skip with a visible
    # warning so an accidental non-Module in a real path is still loud.
    if not (isinstance(model_class, type) and issubclass(model_class, _torch.nn.Module)):
        print(
            f"    [MemCheck] '{model_name}' skipped — not an nn.Module subclass "
            f"(type={type(model_class).__name__}).",
            flush=True,
        )
        return

    _gc.collect()
    rss_before = _psutil.Process().memory_info().rss

    model = None
    cfg = None
    try:
        # Inject representative_T as segmentation_size when the schema
        # accepts it. Pydantic v2 exposes the field map via model_fields.
        cfg_kwargs: dict[str, Any] = {}
        fields = getattr(config_class, "model_fields", None) or {}
        if "segmentation_size" in fields:
            cfg_kwargs["segmentation_size"] = representative_T
        try:
            cfg = config_class(**cfg_kwargs)
        except Exception:
            # If representative_T was rejected (out of declared bounds),
            # fall back to the schema's own defaults. Still better than
            # skipping — the bug usually trips at any T ≥ a few thousand.
            cfg = config_class()
        # Mirror evaluate_vram_skill._build_model: pass loss_type when the
        # model's __init__ accepts it (fcnet hybrid pattern, plus any
        # future plugin that adopts the same convention).
        if "loss_type" in _inspect.signature(model_class.__init__).parameters:
            model = model_class(cfg, loss_type="focal")
        else:
            model = model_class(cfg)
        # Measure RSS BEFORE releasing the model. ``del model, cfg`` would
        # let the allocator reclaim the buffers before we ever sample
        # ``rss_after``, so a faulty plugin's 1+ GB allocation would
        # cancel out and the check would never trip.
        _gc.collect()
        rss_after = _psutil.Process().memory_info().rss
    except Exception as e:
        raise ValueError(
            f"Model plugin '{model_name}': __init__ raised {type(e).__name__}: {e}. "
            f"The plugin must be constructable with default config."
        ) from e
    finally:
        # Release whatever was successfully constructed. Runs after the
        # measurement, so even a passing plugin doesn't leak its
        # construction-time RSS into the next checkpoint.
        del model, cfg
        _gc.collect()

    delta_gb = (rss_after - rss_before) / 1024**3

    print(
        f"    [MemCheck] '{model_name}' __init__ RSS delta: {delta_gb:.3f} GB "
        f"(threshold: {_CONSTRUCTION_RSS_THRESHOLD_GB} GB)",
        flush=True,
    )

    if delta_gb > _CONSTRUCTION_RSS_THRESHOLD_GB:
        raise ValueError(
            f"Model plugin '{model_name}' allocated {delta_gb:.2f} GB during "
            f"__init__ (threshold: {_CONSTRUCTION_RSS_THRESHOLD_GB} GB). "
            f"This indicates a construction-time buffer that scales with T. "
            f"Common causes: [T, T] attention/SSM matrices, [B, T, d_state] "
            f"state buffers, FFT mixing matrices. "
            f"Fix: move all T-dependent allocations to forward(). "
            f"SSM hidden states must be shape [B, d_state], not [B, T, d_state]."
        )


def resolve_run_implementor_blocks(task_composition: Any) -> Any:
    """The run's task-owned IMPLEMENTOR science (Step 12 / PR-12a C7-4).

    Identical rule to :func:`resolve_run_proposal_blocks`, one node over:

        composed    -> the composition's OWN declaration, INCLUDING the legal
                       ``None`` of a task that declares none
        un-composed -> the ONE bounded Regime-A adapter

    A named authority rather than an inline conditional, for the same reason
    its sibling is: ``run_workflow``'s §12.1 tripwire pins the branch count,
    and a fork worth testing should be testable without a workflow drive.
    """
    if task_composition is None:
        return load_implementor_task_blocks()
    return task_composition.implementor_blocks


def resolve_run_proposal_blocks(task_composition: Any) -> Any:
    """The run's task-owned PROPOSER guidance (Step 12 / PR-12a C7, D-12a-6).

    Resolved exactly as 09b resolves the interpreter's blocks:

        composed    -> the composition's OWN declaration, INCLUDING the legal
                       ``None`` of a task that declares none (absent blocks
                       render zero added bytes, never another task's science)
        un-composed -> the ONE bounded Regime-A adapter, whose single
                       task-identity occurrence is a default-path CONSTANT

    A named authority rather than an inline conditional because
    ``run_workflow`` is already 1,500+ lines and its §12.1 sibling-shape
    tripwire pins the branch count — the same disposition C1 and C7-1 reached.
    It also makes the composed/un-composed fork independently testable
    instead of only reachable through a full workflow drive.
    """
    if task_composition is None:
        return load_proposal_task_blocks()
    return task_composition.proposal_blocks


class BaselineIsolationViolation(ValueError):
    """A run under ``--baseline_isolation`` reached for a bundled baseline."""


def refuse_builtin_proposal_under_isolation(
    proposal: ProposalOutput, *, baseline_isolation: bool
) -> None:
    """arXiv U3 (#260, ruling R6): no bundled built-in candidate under isolation.

    The WITHOUT arm must not train, tune or reuse a shipped baseline
    architecture, whether the proposer named it as the candidate
    (``model_name``) or pointed the model config at it as a reuse target
    (``baseline_config.model_config.model_name``). Refused fail-closed and
    NAMED here — before the attempt directory is renamed, before the
    implementor runs and long before the tuner. The attempt loop's existing
    generic handler converts the raise into ``previous_failures`` feedback
    for the NEXT proposal attempt (the LLM is told exactly why), and an
    iteration that never yields a compliant candidate ends with none: no
    bundled architecture is ever implemented or tuned under isolation.

    Keyed on the explicit isolation FLAG, never on the arm label (R2). The
    bundled set is the loader's own authority
    (``ml_models.model_descriptions.BUNDLED_MODEL_TYPES``), so the two
    refusals cannot name different baselines. A non-isolated run is untouched.

    Raises:
        BaselineIsolationViolation: naming every bundled type the proposal
            reached for.
    """
    if not baseline_isolation:
        return
    from ml_models.model_descriptions import BUNDLED_MODEL_TYPES, is_bundled_model_type

    reached: set[str] = {proposal.model_name}
    model_cfg = (proposal.baseline_config or {}).get("model_config") or {}
    reuse_target = model_cfg.get("model_name") if isinstance(model_cfg, dict) else None
    if isinstance(reuse_target, str):
        reached.add(reuse_target)
    offending = sorted(name for name in reached if is_bundled_model_type(name))
    if offending:
        raise BaselineIsolationViolation(
            f"baseline_isolation is ON and the proposal reached for the bundled "
            f"built-in model type(s) {offending} (proposal.model_name="
            f"{proposal.model_name!r}). The WITHOUT arm excludes every shipped "
            f"baseline {sorted(BUNDLED_MODEL_TYPES)}; propose a new architecture "
            "or reuse an agent-generated plugin."
        )


def require_lit_review_config_when_enabled(
    *,
    lit_review_enabled: bool,
    lit_review_config_path: str | None,
) -> None:
    """Require explicit literature-review configuration when enabled.

    Step 12 / PR-12a C7, D-12a-7 (Q-12-3, RATIFIED 2026-08-22).

    The node and its four-channel proposer handoff are task-generic. Root
    papers, search settings, and confidence criteria are task or experiment
    inputs, so the framework never supplies a scientific default.

    Raises:
        ValueError: literature review is enabled without an explicit config,
            before any LLM or GPU spend.
    """
    if not lit_review_enabled:
        return
    if lit_review_config_path is not None:
        return
    raise ValueError(
        "literature review is enabled but no config was declared. Supply the "
        "task or experiment config through --ml_lit_review_config, or launch "
        "without --ml_lit_review_enabled."
    )


def resolve_tuner_health_config_source(
    *,
    task_composition: object | None,
    effective_config_path: str | None,
    operator_config: str | None,
) -> str | None:
    """The original HealthGate source the workflow hands the tuner.

    The chain and tuner each materialize the effective config in their own
    workspace. They must start from the same original source and the same
    task binding. Passing the chain's already-materialized file through a
    second materialization drops its ``resolved_plugins`` provenance marker,
    changes ``health_config_sha256``, and makes iteration two refuse iteration
    one's otherwise-comparable records.

    The tuner now receives the task binding through ``TaskCompositionRef``.
    Therefore the old workaround of substituting the chain-level effective
    path is no longer needed and is actively incorrect. Keeping this named
    boundary documents the transport rule and avoids reintroducing an inline
    branch at the orchestration site.

    Args:
        task_composition: retained for call-site compatibility; the binding
            itself crosses through ``TaskCompositionRef``.
        effective_config_path: retained for call-site compatibility and never
            forwarded because an effective artifact is not an input source.
        operator_config: the operator's raw ``--health_checks_config`` value.

    Returns:
        ``operator_config`` unchanged.
    """
    del task_composition, effective_config_path
    return operator_config


def _register_plugin(
    impl_output,
    model_name: str,
    dest_plugin_dirs: "list[str] | str",
    dest_loss_dirs: "list[str] | str | None" = None,
):
    """
    Mirror validated plugin files to one or more destination dirs.

    Two destinations are typical in chain mode:

      * **Tuner-scoped** dir at ``{tuning_dir}/plugins/{run_name}/`` — the
        training/inference/scoring subprocess discovers plugins here via
        ``SIDERIUS_PLUGIN_DIRS`` (docs/run_scoped_plugins.md, Phase 4).
      * **Chain-canonical** dir at ``{workspace}/plugins/{run_name}/`` —
        ``core.resume.restore_prior_state`` looks here when later iters of
        the chain re-register prior plugins, and
        ``ml_models.model_descriptions.get_model_description`` walks
        ``{workspace}/plugins/iter_*/{model_type}/description.md`` to
        resolve agent-generated model descriptions on the next iter.

    Both dests receive identical files:

      - ``{model_file_path}``       → ``{dest}/{model_name}.py``
      - ``{description_file_path}`` → ``{dest}/{model_name}/description.md``

    The first dest in the list is treated as the primary; its ``.py`` is
    used to extend the in-process ``MODEL_REGISTRY`` /
    ``PLUGIN_CONFIG_REGISTRY`` so the tuner's planner (same Python process
    as the workflow) resolves the new model type without a re-scan.

    Accepts a single string for back-compat with older call sites and tests.

    L6a — loss-plugin propagation. When ``dest_loss_dirs`` is provided AND
    ``impl_output.loss_provenance.action == "generated"``, the loss plugin
    file at ``loss_provenance.loss_file_path`` is mirrored to each dest as
    ``{dest}/{loss_name}.py``. Callers typically pass both a tuner-scoped
    ``get_loss_dir(tuning_dir, run_name)`` (so the training subprocess's
    ``SIDERIUS_LOSS_DIRS`` resolves the plugin) and a chain-canonical
    ``get_loss_dir(workspace, run_name)`` (so resume / cross-iter Branch B
    reuse can find the same plugin without re-traversing the per-attempt
    tree). Pre-L6a, the implementor wrote the loss file to a per-attempt
    ``{attempt_dir}/losses/`` directory that no subsequent code copied
    anywhere, so training subprocesses could never load it. Defaults to
    ``None`` for back-compat with all existing call sites and unit tests.
    Skipped silently when ``loss_provenance is None`` (built-in loss path)
    or when ``loss_provenance.action == "reused"`` (the chain-canonical
    copy from the originating iter is expected to still exist).

    Skips gracefully if source files don't exist (e.g. unit tests with mocks).
    """
    if isinstance(dest_plugin_dirs, str):
        dest_plugin_dirs = [dest_plugin_dirs]

    if not os.path.isfile(impl_output.model_file_path):
        print(
            f"    Warning: plugin file not found at "
            f"{impl_output.model_file_path}, skipping registration"
        )
        return

    # Forensic copy — preserve the generated plugin source under a
    # workspace-relative sentinel directory BEFORE any registration / build
    # step that could OOM-kill the orchestrator and leave us with no record
    # of the offending code. Anchored under the SIDERIUS_CHAIN_WORKSPACE env
    # var so the sentinel lives at the workspace root (not the per-iter
    # attempt tree), surviving the per-iter cleanup that `--cleanup_denoised`
    # and similar flags perform. Added after the 2026-06-24 v15 arch OOM
    # where the generated plugin source was lost when we cleaned the
    # workspace post-mortem. Best-effort: failures here never block plugin
    # registration; the sentinel is a debug aid, not a load-bearing step.
    try:
        _sentinel_root = os.environ.get(
            "SIDERIUS_CHAIN_WORKSPACE",
            os.path.dirname(os.path.dirname(impl_output.model_file_path)),
        )
        _sentinel_dir = os.path.join(_sentinel_root, "plugin_source_sentinel")
        os.makedirs(_sentinel_dir, exist_ok=True)
        _sentinel_path = os.path.join(_sentinel_dir, f"{model_name}.py")
        shutil.copy2(impl_output.model_file_path, _sentinel_path)
        print(f"    [DEBUG] Plugin source saved to sentinel: {_sentinel_path}", flush=True)
    except Exception as _e:
        print(f"    [DEBUG] Plugin source sentinel write skipped ({type(_e).__name__}: {_e})")

    primary_plugin: str | None = None
    for d in dest_plugin_dirs:
        os.makedirs(d, exist_ok=True)
        dest_plugin = os.path.join(d, f"{model_name}.py")
        shutil.copy2(impl_output.model_file_path, dest_plugin)
        if primary_plugin is None:
            primary_plugin = dest_plugin
        print(f"    Plugin registered → {dest_plugin}")

    if os.path.isfile(impl_output.description_file_path):
        for d in dest_plugin_dirs:
            desc_dest_dir = os.path.join(d, model_name)
            os.makedirs(desc_dest_dir, exist_ok=True)
            dest_desc = os.path.join(desc_dest_dir, "description.md")
            shutil.copy2(impl_output.description_file_path, dest_desc)
            print(f"    Description registered → {dest_desc}")
    else:
        print(
            f"    Warning: description not found at "
            f"{impl_output.description_file_path}, skipping registration"
        )

    # L6a — loss plugin propagation. Only mirror on "generated" so reused
    # losses (Branch B) don't double-copy onto themselves on every iter.
    loss_prov = getattr(impl_output, "loss_provenance", None)
    if dest_loss_dirs is not None and loss_prov is not None and loss_prov.action == "generated":
        if isinstance(dest_loss_dirs, str):
            loss_dest_list = [dest_loss_dirs]
        else:
            loss_dest_list = list(dest_loss_dirs)
        if not os.path.isfile(loss_prov.loss_file_path):
            print(
                f"    Warning: loss plugin file not found at "
                f"{loss_prov.loss_file_path}, skipping loss registration"
            )
        else:
            for d in loss_dest_list:
                os.makedirs(d, exist_ok=True)
                dest_loss = os.path.join(d, f"{loss_prov.loss_name}.py")
                shutil.copy2(loss_prov.loss_file_path, dest_loss)
                print(f"    Loss plugin registered → {dest_loss}")
            # L6c — also register in-memory so in-process pre-flight
            # (evaluate_vram_skill, evaluate_time_skill) resolves the plugin
            # without depending on SIDERIUS_LOSS_DIRS. First dest is
            # sufficient — same file regardless of dest. See
            # docs/design/enable_loss_inventory.md § L6c.
            from ml_models.loss_models_sandbox import register_loss_in_memory

            # L6c bug-fix — loss_dest_list[0] is a DIRECTORY; the plugin
            # file is at ``{dir}/{loss_name}.py``. Passing the directory
            # caused ``spec_from_file_location`` to return None silently,
            # leaving LOSS_REGISTRY empty and breaking every custom-loss
            # pre-flight (in-process callers fell through to filesystem
            # with no SIDERIUS_LOSS_DIRS set). Reconstruct the file path.
            _loss_file_for_registry = os.path.join(loss_dest_list[0], f"{loss_prov.loss_name}.py")
            _registered_loss = register_loss_in_memory(_loss_file_for_registry)
            if _registered_loss is not None:
                print(f"    Loss '{_registered_loss}' added to in-memory LOSS_REGISTRY")

    if primary_plugin is None:
        # ``dest_plugin_dirs`` was empty after normalization — the copy loop
        # never ran, so there is nothing to register. Defensive guard; also
        # narrows ``primary_plugin`` from ``str | None`` to ``str`` for the
        # call below.
        return

    registered: str | None = None
    try:
        # Step 12 / PR-12a C6 — the PUBLIC registration authority.
        # `workflows._add_plugin_to_registries` was a private duplicate of it:
        # same `_load_plugin`, same three registries, same `model_type | None`
        # return. Its only behavioural difference was the absence of the
        # re-registration warning, which is strictly less visible.
        registered = register_model_in_memory(primary_plugin)
        if registered:
            print(f"    Model '{model_name}' added to registries (model_type='{registered}')")
    except Exception as e:
        print(f"    Warning: could not extend registries: {e}")

    # Construction-time RSS validator — catches faulty SSM/attention plugins
    # that pre-allocate T-scaling buffers in __init__ before the structural
    # VRAM probe ever runs. Runs OUTSIDE the registry-extension try/except
    # because a positive verdict here is load-bearing: a faulty plugin that
    # passes registry extension but allocates 50+ GB at construct time would
    # OOM-kill the orchestrator at the tuner's VRAM probe. The
    # ``ValueError`` from this helper propagates up to the iteration loop
    # so the iteration ends loudly instead of silently advancing.
    if registered is not None:
        from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
        from ml_models.models_sandbox import MODEL_REGISTRY

        _validate_construction_memory(
            model_class=MODEL_REGISTRY[registered],
            config_class=PLUGIN_CONFIG_REGISTRY[registered],
            model_name=model_name,
        )


# ---------------------------------------------------------------------------
# L6c — Loss promotion to the global library
# ---------------------------------------------------------------------------


def _promote_loss_to_global(impl_output) -> None:
    """Promote a generated loss plugin to the resolved capability library.

    arXiv P1 — the destination is the resolved generated-library losses dir
    (``core.generated_library.generated_losses_dir()``), NEVER the repository
    checkout. The legacy checkout ``agent_generated/losses/`` is consulted
    read-only for dedup / idempotency so pre-migration promotions are neither
    duplicated nor overwritten.

    Supported entry points bind the destination to the chain workspace, so
    later iterations and resumed child processes can reuse the validated loss
    without exposing it to another workspace.

    Trigger condition: ``impl_output.loss_provenance.action == "generated"``.
    Per the design discussion (2026-06-23 L6c review), promotion fires
    REGARDLESS of training outcome — even if the round aborted before any
    record was scored, the implementor still produced a validated plugin
    (dummy-tensor check passed), and keeping it accessible avoids leaking
    the I12 failure mode to future runs. The proposer/tuner self-correct
    via the advice file's lit-review-driven mode and the existing 3-branch
    Rule 9 constraints.

    Content-hash deduplication: before copying, compares SHA256 of the
    source against every ``.py`` in the active library set. Workspace-bound
    runs use only their resolved library; unbound legacy callers also consult
    the checkout fallback. On match, skips promotion and
    logs which existing entry is the duplicate. Catches the case where two
    iterations generate plugins with different ``loss_name``s but
    byte-identical contents (e.g. an LLM regenerating the same canonical
    loss).

    Registry update: after promotion, the capability registry entry's
    ``file_path`` is rewritten to the promoted path via
    ``CapabilityRegistry.replace()`` so subsequent Branch B reuse and
    cross-process resume resolve to the stable location.

    Idempotency: if a file with the destination name already exists in the
    active library set, promotion skips silently
    — first writer wins — and the registry update still fires, pointing this
    chain's index entry at the file that actually exists.

    No-op when ``loss_provenance is None`` (built-in loss path) or
    ``action == "reused"`` (already promoted by the originating iteration).
    """
    loss_prov = getattr(impl_output, "loss_provenance", None)
    if loss_prov is None or loss_prov.action != "generated":
        return

    from agent_generated._loss_loader import LOSSES_DIR
    from agent_generated._registry import CapabilityMetadata, CapabilityRegistry
    from core.generated_library import generated_library_is_workspace_bound, generated_losses_dir

    src = loss_prov.loss_file_path
    if not src or not os.path.isfile(src):
        print(
            f"  Warning: cannot promote loss '{loss_prov.loss_name}' — "
            f"source file not found at {src}"
        )
        return

    # arXiv P1 — the promotion DESTINATION is the resolved generated-library
    # losses dir, never the repository checkout. The legacy checkout dir
    # (``LOSSES_DIR``) participates READ-ONLY below — in the content dedup
    # and the same-name idempotency check — so a loss promoted before the
    # migration is neither duplicated nor clobbered, and is never written to.
    library_losses_dir = generated_losses_dir()
    loss_library_dirs = [library_losses_dir]
    if not generated_library_is_workspace_bound():
        loss_library_dirs.append(LOSSES_DIR)
    dest_basename = f"{loss_prov.loss_name}.py"
    global_dest = os.path.join(library_losses_dir, dest_basename)

    # Content-hash dedup: scan BOTH library locations for byte-identical
    # content under a different name. Same-basename entries are excluded —
    # the idempotency branch below owns that case. Caches src hash to avoid
    # re-reading.
    src_hash = _sha256_file(src)
    for scan_dir in loss_library_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for fname in os.listdir(scan_dir):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            if fname == dest_basename:
                continue  # same-name match handled by the idempotency check below
            existing_path = os.path.join(scan_dir, fname)
            if _sha256_file(existing_path) == src_hash:
                existing_name = fname[:-3]  # strip .py
                print(
                    f"  Loss '{loss_prov.loss_name}' not promoted — identical "
                    f"content already exists as '{existing_name}' "
                    f"({global_dest} skipped)."
                )
                return

    # Same-name idempotency — first writer wins ACROSS both library
    # locations: a copy already promoted (a parallel chain into the resolved
    # library, or a pre-migration run into the checkout) keeps its bytes, and
    # the registry below is pointed at the file that actually exists.
    existing_same_name = next(
        (
            os.path.join(path, dest_basename)
            for path in loss_library_dirs
            if os.path.isfile(os.path.join(path, dest_basename))
        ),
        None,
    )
    if existing_same_name is not None:
        print(
            f"  Loss '{loss_prov.loss_name}' already at global path "
            f"{existing_same_name} (idempotent skip)."
        )
        global_dest = existing_same_name
    else:
        os.makedirs(library_losses_dir, exist_ok=True)
        shutil.copy2(src, global_dest)
        print(f"  Promoted loss '{loss_prov.loss_name}' → {global_dest}")

    # Update the capability registry entry to point at the stable global path
    # so future chain runs and parallel workflows resolve the loss even after
    # this run's workspace is cleaned. Uses the default index location —
    # callers that override capability_index_path on agents do so for tests
    # only; production runs share the canonical index.
    try:
        registry = CapabilityRegistry()
        existing = next(
            (m for m in registry.list(capability_type="loss") if m.name == loss_prov.loss_name),
            None,
        )
        if existing is None:
            print(
                f"  Warning: loss '{loss_prov.loss_name}' is not in the "
                f"capability index — registry not updated. Promotion file "
                f"copy is preserved at {global_dest}."
            )
            return
        promoted_meta = CapabilityMetadata(
            name=existing.name,
            capability_type=existing.capability_type,
            file_path=global_dest,
            created_at=existing.created_at,
            source_iteration=existing.source_iteration,
            description=existing.description,
            # L6c bug-fix — preserve mathematical_definition through promotion.
            # The original construction left this field as the default empty
            # string, so promoted entries lost the formula even when the
            # implementor had persisted it at registry write time. Result:
            # the proposer's {available_losses_block} rendered description
            # only, never the formula block.
            mathematical_definition=existing.mathematical_definition,
        )
        registry.replace(promoted_meta)
        print(f"  Updated registry entry '{loss_prov.loss_name}' file_path → {global_dest}")
    except Exception as e:
        # Registry update failure is non-fatal — the global copy is still
        # discoverable via _resolve_loss_dirs() union mode, just not via the
        # registry's file_path field. Log and continue.
        print(f"  Warning: could not update registry for '{loss_prov.loss_name}': {e}")


def _sha256_file(path: str) -> str:
    """Return SHA256 hex digest of a file's contents.

    Used by ``_promote_loss_to_global`` for content-based dedup of byte-
    identical loss plugins generated under different names.
    """
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Model promotion to the global library (symmetric to L6c for losses)
# ---------------------------------------------------------------------------


def _promote_model_to_global(impl_output) -> None:
    """Promote a generated model plugin to the resolved capability library.

    arXiv P1 — the destination is the resolved generated-library models dir
    (``core.generated_library.generated_models_dir()``), NEVER the repository
    checkout. The legacy checkout ``agent_generated/models`` is consulted
    read-only (Branch-B detection, dedup, idempotency) so pre-migration
    promotions are neither duplicated nor overwritten.

    Mirrors :func:`_promote_loss_to_global` for the model surface. Called
    by the workflow's iteration loop right after ``_register_plugin``
    returns (early-promotion timing matches the issue-#92 fix for losses),
    so a future iteration or resume in the same workspace can resolve it
    through the capability index.

    Trigger condition: ``impl_output.model_file_path`` exists AND
    ``impl_output.model_type`` is registered in the capability index with
    ``capability_type='model'``. The implementor writes that entry
    immediately after building the plugin (so by the time the workflow
    sees ``impl_output``, the index entry already exists), and Branch B
    reuse paths leave the existing registry entry alone — so this helper
    no-ops cleanly on Branch B (file already at the global path, registry
    already correct).

    Content-hash deduplication: before copying, compares SHA256 of the
    source against every ``.py`` in the active library set. Workspace-bound
    runs use only their resolved library; unbound legacy callers also consult
    the checkout fallback. On match, skips the copy and
    logs which existing entry is the duplicate.

    Registry update: after promotion, the capability registry entry's
    ``file_path`` is rewritten to the promoted path via
    ``CapabilityRegistry.replace()``.

    Idempotency: if a file with the destination name already exists in the
    active library set, the copy is
    skipped silently and the registry update is still re-asserted against
    the file that actually exists.

    No-op when ``impl_output.model_file_path`` is empty (defensive) or
    when the model name is not in the registry (e.g. a built-in Branch A
    path that never wrote a generated plugin — nothing to promote).
    """
    model_file_path = getattr(impl_output, "model_file_path", "") or ""
    if not model_file_path or not os.path.isfile(model_file_path):
        return  # Built-in / Branch B with no fresh codegen / defensive guard.

    from agent_generated._registry import CapabilityMetadata, CapabilityRegistry
    from core.generated_library import generated_library_is_workspace_bound, generated_models_dir
    from ml_models.plugin_loader import AGENT_GENERATED_DIR as LEGACY_MODELS_DIR

    model_name = getattr(impl_output, "model_type", None)
    if not model_name:
        print("  Warning: cannot promote model — impl_output.model_type is empty")
        return

    # arXiv P1 — the promotion DESTINATION is the resolved generated-library
    # models dir, never the repository checkout. The legacy checkout dir
    # participates READ-ONLY below (Branch-B detection, content dedup,
    # same-name idempotency), so a model promoted before the migration is
    # neither duplicated nor clobbered — and is never written to.
    library_models_dir = generated_models_dir()
    model_library_dirs = [library_models_dir]
    if not generated_library_is_workspace_bound():
        model_library_dirs.append(LEGACY_MODELS_DIR)

    # Branch B reuse path: model_file_path already points into EITHER library
    # location (the implementor's Branch B short-circuit returns the
    # registry's file_path verbatim — which is a legacy checkout path for a
    # pre-migration promotion). Nothing to copy or update.
    abs_src = os.path.abspath(model_file_path)
    if os.path.dirname(abs_src) in tuple(os.path.abspath(path) for path in model_library_dirs):
        return

    dest_basename = f"{model_name}.py"
    global_dest = os.path.join(library_models_dir, dest_basename)

    # Content-hash dedup: scan BOTH library locations for byte-identical
    # content under a different name. Same-basename entries are excluded —
    # the idempotency branch below owns that case. Caches src hash to avoid
    # re-reading.
    src_hash = _sha256_file(abs_src)
    for scan_dir in model_library_dirs:
        if not os.path.isdir(scan_dir):
            continue
        for fname in os.listdir(scan_dir):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            if fname == dest_basename:
                continue  # same-name handled by the idempotency branch below
            existing_path = os.path.join(scan_dir, fname)
            if _sha256_file(existing_path) == src_hash:
                existing_name = fname[:-3]
                print(
                    f"  Model '{model_name}' not promoted — identical content "
                    f"already exists as '{existing_name}' "
                    f"({global_dest} skipped)."
                )
                return

    # Same-name idempotency — first writer wins ACROSS both library
    # locations (a parallel chain into the resolved library, or a
    # pre-migration run into the checkout); the registry below is pointed at
    # the file that actually exists.
    existing_same_name = next(
        (
            os.path.join(path, dest_basename)
            for path in model_library_dirs
            if os.path.isfile(os.path.join(path, dest_basename))
        ),
        None,
    )
    if existing_same_name is not None:
        print(
            f"  Model '{model_name}' already at global path {existing_same_name} (idempotent skip)."
        )
        global_dest = existing_same_name
    else:
        os.makedirs(library_models_dir, exist_ok=True)
        shutil.copy2(abs_src, global_dest)
        print(f"  Promoted model '{model_name}' → {global_dest}")

    # Also copy the description.md subdir so the proposer's
    # ``{available_models_block}`` and downstream readers find it at the
    # canonical layout (``{models_dir}/{name}/description.md``). Written
    # ONLY under the resolved library (never the checkout); skipped when a
    # description already exists in EITHER location — same first-writer
    # rule as the plugin file.
    desc_path = getattr(impl_output, "description_file_path", "") or ""
    if desc_path and os.path.isfile(desc_path):
        desc_dest = os.path.join(library_models_dir, model_name, "description.md")
        existing_descriptions = [
            os.path.join(path, model_name, "description.md") for path in model_library_dirs
        ]
        if not any(os.path.exists(path) for path in existing_descriptions):
            os.makedirs(os.path.dirname(desc_dest), exist_ok=True)
            shutil.copy2(desc_path, desc_dest)
            print(f"  Promoted model description → {desc_dest}")

    # Update capability registry to point at the global path.
    try:
        registry = CapabilityRegistry()
        existing = next(
            (m for m in registry.list(capability_type="model") if m.name == model_name),
            None,
        )
        if existing is None:
            print(
                f"  Warning: model '{model_name}' is not in the capability "
                f"index — registry not updated. Promotion file copy is "
                f"preserved at {global_dest}."
            )
            return
        promoted_meta = CapabilityMetadata(
            name=existing.name,
            capability_type=existing.capability_type,
            file_path=global_dest,
            created_at=existing.created_at,
            source_iteration=existing.source_iteration,
            description=existing.description,
            mathematical_definition=existing.mathematical_definition,
        )
        registry.replace(promoted_meta)
        print(f"  Updated registry entry '{model_name}' file_path → {global_dest}")
    except Exception as e:
        print(f"  Warning: could not update registry for '{model_name}': {e}")


# ---------------------------------------------------------------------------
# Startup cleanup — phantom registry entries
# ---------------------------------------------------------------------------


def _cleanup_stale_registry_entries(registry) -> tuple[int, list[str]]:
    """Remove ``_capability_index.json`` rows whose ``file_path`` is missing.

    Phantom entries accumulate when the implementor writes a
    ``CapabilityMetadata`` row before validation (the pre-``feat/v16-fixes``
    behaviour) and validation later fails, or when a workspace containing
    the plugin file is cleaned but the global index still references it,
    or when unit-test fixtures leak a ``tmp_path`` entry into the canonical
    index. The v16 loss-chain iter_015 failure is the reproducer: the
    global index contains ``gated_dilated_tcn`` whose file_path is a
    ``/tmp/pytest-of-...`` path that no longer exists.

    This helper runs once at workflow startup so every subsequent proposer
    sees an index consistent with the filesystem. Entries are removed via
    :meth:`CapabilityRegistry.remove` (atomic tmp-file rewrite), so a
    parallel reader never sees a half-repaired index.

    Args:
        registry: A ``CapabilityRegistry`` — typically the default global
            one. Duck-typed for tests that pass a stub.

    Returns:
        ``(n_removed, names)`` where ``names`` are the entries that were
        pruned. ``(0, [])`` on a clean index.
    """
    stale: list[tuple[str, str, str]] = []  # (name, capability_type, file_path)
    for meta in registry.list():
        fp = getattr(meta, "file_path", "") or ""
        if fp and not os.path.isfile(fp):
            stale.append((meta.name, meta.capability_type, fp))

    for name, cap_type, _ in stale:
        registry.remove(name, capability_type=cap_type)

    return len(stale), [f"{name} ({cap_type})" for name, cap_type, _ in stale]


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


def _refuse_data_scope_for_a_foreign_topology(scope_is_partial: bool, task_composition) -> None:
    """`--data_scope` names FILE INDICES; refuse it for a task without them.

    Step 12 / PR-12bc B7 (§D.4). Extracted rather than inlined: `run_workflow`
    carries a §12.1 branch tripwire, and this check is a self-contained
    decision with its own reason — exactly the shape that belongs behind a
    call.

    `--data_scope` is TIDMAD/legacy vocabulary. Silently resolving it against a
    composed task's partition count would restrict a run to partitions the
    operator never meant. Refused BY NAME, at startup, before an LLM call or a
    GPU minute. Composed TIDMAD keeps honouring it through its own capability,
    which is why the discriminator is "does this task declare TIDMAD's
    topology" and never a task name.
    """
    if not scope_is_partial or task_composition is None:
        return
    from execute_tools.dataset_config import tidmad_topology

    try:
        tidmad_topology(resolve_dataset_profile())
    except ValueError as exc:
        raise ValueError(
            f"--data_scope names FILE INDICES, which is legacy vocabulary this "
            f"composed task does not share ({exc}). Declare the restriction "
            f"through the task's own scope capability instead; a file-index "
            f"list cannot be reinterpreted for a task with a different "
            f"partition concept."
        ) from exc


def _workflow_lock_identity(launch) -> LockLaunchIdentity:
    """The workflow's arXiv-U1/U3 lock identity, from the launch config.

    Pure construction, extracted from ``run_workflow`` under the 12a
    structural budget (the SE.2 idiom). An unlabelled, lit-review-OFF launch
    yields the defaults, so its lock is byte-identical (the keys are
    omitted, never null); the config sha is derived from the SAME resolved
    path the lit-review branch later opens, so the lock always pins the file
    the run reads.
    """
    return LockLaunchIdentity(
        lit_review_enabled=launch.lit_review_enabled,
        lit_review_config_sha256=lit_review_config_sha256(
            launch.lit_review_config_path, enabled=launch.lit_review_enabled
        ),
        experiment_arm=launch.experiment_arm,
        # arXiv U3 — the WITHOUT arm's isolation flag is a prompt-surface
        # identity, so it is locked like the topology.
        baseline_isolation=launch.baseline_isolation,
        # Gold campaign — the advice pin the LAUNCHER observed, carried on
        # the launch config and never re-derived here. Re-hashing the file at
        # this point would describe whatever is on disk when the workflow
        # starts rather than what the launch certified, which is the
        # recomputation defect F-12bc-7 named: a pin that follows the very
        # edit it exists to catch.
        advice_sha256=launch.advice_sha256,
        advice_path=launch.advice_path,
        # F-SCANF-1 — the formal round's evaluation FRACTION, from the SAME
        # launch config the tuner child receives it from, so the chain lock
        # and the tuner sub-workspace lock cannot disagree.
        formal_eval_portion=launch.formal_eval_portion,
    )


def run_workflow(
    *,
    # --- transit configuration (Step 09.5a C3; the 72 values this run
    # forwards to its nodes and never interprets as an authority) ---------
    launch: WorkflowLaunchConfig | None = None,
    # --- run-scoped authorities: what this run establishes at startup -----
    workspace: str,
    run_name: str,
    chain_run_name: str | None = None,
    run_id: str | None = None,
    data_scope: DataScope | None = None,
    health_gate_enabled: bool = True,
    health_gate_files: list[int] | None = None,
    health_checks_config: str | None = None,
    order_strategy_override: OrderStrategy | None = None,
    file_order_override: list[int] | None = None,
    enable_structured_health_feedback: bool = False,
    llm_config: WorkflowLLMConfig | None = None,
    # --- immutable capability references (Amendment A) --------------------
    bridge_factory: Callable | None = None,
    sandbox_factory: Callable | None = None,
    measurement_capability: ResolvedMeasurementCapability | None = None,
    # --- restored chain state: ONE typed parameter (Step 10 P1 C5) --------
    # Step 09.5a's C4b hand-off. The launcher used to unpack `RestoredState`
    # into nine separate kwargs and this signature had to declare all nine —
    # a transport shape that grew by one every time resume learned to carry
    # another value. `RestoredState` is resume's OWN type and is allowed
    # across the launcher edge (09.5a §16); `ChainState` still never crosses
    # a process boundary. `None` is cold start.
    # Step 12 / PR-12a C6 — an ordinary annotation again. It was QUOTED
    # because `core.resume` imported a private symbol from this module
    # (`_add_plugin_to_registries`), making an eager import here a cycle. That
    # symbol is retired and resume now uses the public registration authority,
    # so there is no cycle and no reason to defer the name.
    restored_state: RestoredState | None = None,
    # --- run-scoped TASK composition (Step 10 P1) -------------------------
    task_composition: RunTaskComposition | None = None,
    # --- DS7 deprecated no-ops, kept for behaviour parity (FU-2) ----------
    trial_strategy: StrategyMode = "snapshot",
    target_files: list[int] | None = None,
    eval_strategy: StrategyMode = "snapshot",
) -> list[HyperparamTuningOutput]:
    """
    Execute the model exploration workflow for one or more iterations.

    Each iteration: interpret → (propose → implement → validate) → tune.
    The propose→implement→validate inner loop retries on validation failure.

    Args:
        workspace: Root output directory for this workflow run.
        run_name: Unique name for this workflow run.
        source_paths: (preferred) Explicit list of HyperparamTuningOutput JSON file
            paths to load as historical context. Use this when chaining iterations
            across separate Slurm jobs — each iteration's source list = original
            seeds + all previous iteration outputs.
        data_dir: (legacy) Root data directory containing existing tuning results.
            Used only when source_paths is None.
        model_types: (legacy) List of model types to load from source_run_name.
            Used only when source_paths is None.
        source_run_name: (legacy) The run name to load initial tuning results from
            (e.g. "small_sample_trial_v0"). One output per model is loaded from
            {data_dir}/{model_type}/{source_run_name}/agent/. Used only when
            source_paths is None.
        max_iterations: Number of successful iterations (validated + tuned).
        max_rounds: Tuning budget per iteration.
        max_proposal_attempts: Max propose→implement→validate retries per iteration.
        target_score: Optional early stop — halt if best score >= target.
        file_index: Training/validation file index (ignored when is_trial=True).
        llm_config: Per-node LLM configuration. If None, each node uses its
            own built-in default. See WorkflowLLMConfig for details.
        health_checks_config: Optional HealthGate YAML override forwarded to
            every tuner invocation. None preserves the tuner's shipped default.
        data_scope: DataScope restricting every component of this run to a
            file subset (DS6b). None = complete dataset. Partial scopes
            require formal_strategy='snapshot' and, when gates are enabled,
            an explicit health_gate_files. Pinned per workspace by the
            run-invariants lock. See docs/design/enable_partial_file_list.md.
        health_gate_enabled: HealthGate subsystem switch, forwarded to every
            tuner invocation and pinned by the run-invariants lock.
        health_gate_files: Run-level shared monitored-file list for ALL
            HealthGate checks (None = YAML defaults; only legal with a full
            scope when gates are enabled).
        human_advice_interpret: Human guidance for interpretation steps.
        human_advice_propose: Human guidance for proposal steps.
        human_advice_implement: Human guidance for implementation steps.
        human_advice_validate: Human guidance for validation steps.
        human_advice_tune: Human guidance for tuning steps.
        is_trial: Enable trial mode for the tuning agent.
        trial_strategy: DEPRECATED no-op (DS7) — warns when non-default.
        trial_portion: Fraction of segments per file for training scope.
        target_files: DEPRECATED no-op (DS7) — warns when non-default.
        train_portion: Per-epoch subsample from training scope.
        eval_strategy: DEPRECATED no-op (DS7) — warns when non-default.
        eval_portion: Fraction of segments per file for validation.
        train_validation_align: When True, train and eval scopes share segment indices.
        sampling_seed: Seed for SampleSet construction.
        train_base_seed: Base seed for per-epoch training subsampling.
        cleanup_denoised: Delete denoised H5 files after scoring.
        trial_time_budget_minutes: Wall-time budget (minutes) for the
            evaluate_time_skill gate on trial-mode rounds (plan.is_trial=True).
            Fanned out to BOTH ProposalInput (proposer's baseline gate) and
            HyperparamTuningInput (tuner's per-round gate). None = trial gate
            disabled. See docs/resource_estimator_implement.md §2.7.2 / Phase I.
        formal_time_budget_minutes: Same as above, but for formal-mode rounds
            (plan.is_trial=False). Sized independently because formal runs
            use the full dataset and are 50-100x longer.
        gpu_admission_measurement_source: V20 B-G3. Reference naming
            where an authoritative GPU measurement would resolve
            from. Never a figure. Unresolved before PR C, so formal
            rounds refuse with policy_unavailable.
        gpu_pair_ceiling_gib: V20 B-G3. Aggregate GPU ceiling (GiB)
            passed explicitly to the admission gate. None defers to
            the environment resolver, i.e. pre-B-G3 behaviour.
        trial_vram_budget_gb: Per-mode VRAM ceiling (GB) for the
            evaluate_vram_skill gate on trial-mode rounds. Fanned out to
            HyperparamTuningInput only — Phase K has no proposer-side VRAM
            gate (deferred per §10.17). None → tuner's skill falls back to
            the defensive free×0.8 limit. See §10.9 / Phase K.
        formal_vram_budget_gb: Same as above, but for formal-mode rounds.
            Sized independently because formal rounds often use larger
            batch_size / segmentation_size so the VRAM ceiling can differ.

    Returns:
        List of HyperparamTuningOutput objects, one per successful iteration.
    """
    # Step 09.5a C3 — the transit configuration is one value now. A caller
    # that supplies none gets exactly the defaults the 72 individual
    # parameters carried before; the carrier restates none of them.
    if launch is None:
        launch = WorkflowLaunchConfig()

    if llm_config is None:
        llm_config = WorkflowLLMConfig()

    # Step 10 / P1 — a composed run must arrive with its authorities ACTIVE.
    #
    # This workflow CONSUMES the composition; it does not establish it. The
    # binding is entered at the composition edge (the launcher, or this
    # module's CLI) so that its lifetime is the composition's lifetime and it
    # covers the startup pre-flight below as well as the iteration loop —
    # scope resolution and the Health materialisation both read the run's
    # profile before iteration 1.
    #
    # The refusal is what makes that split safe: a run holding a composition
    # whose bindings are NOT active would read the composed interpretation
    # blocks and Health family while resolving the profile, metric and task
    # description from the legacy defaults, and would look completely normal
    # doing it. An un-composed run is a no-op here.
    verify_composition_is_bound(task_composition)

    # Step 12 / PR-12a C7 (D-12a-7, Q-12-3 RATIFIED) — refused HERE, at
    # startup, because this is the first point where composition presence and
    # the resolved flag are both in hand, and refusing before the iteration
    # loop means before any LLM call and any GPU work. The decision itself is
    # a named authority so this orchestrator gains a CALL rather than another
    # branch family (§12.1's sibling-shape tripwire).
    require_lit_review_config_when_enabled(
        lit_review_enabled=launch.lit_review_enabled,
        lit_review_config_path=launch.lit_review_config_path,
    )

    # DS7 — deprecated no-op strategy params (removal tracked as FU-2).
    for _name, _val, _default in (
        ("trial_strategy", trial_strategy, "snapshot"),
        ("target_files", target_files, None),
        ("eval_strategy", eval_strategy, "snapshot"),
    ):
        if _val not in (_default, []):
            warnings.warn(
                f"run_workflow({_name}=...) is deprecated and IGNORED (DS7): "
                f"the input field it fed was dead at both ends and has been "
                f"removed. Use data_scope to restrict data; per-round "
                f"strategy belongs to the LLM plan.",
                DeprecationWarning,
                stacklevel=2,
            )

    # 52 GB OOM forensics — see _log_rss docstring above.
    _log_rss("post-import (run_workflow entry)")

    # All workflow output goes under {workspace}/{run_name}/
    run_dir = os.path.join(workspace, run_name)
    os.makedirs(run_dir, exist_ok=True)
    # Runtime-generated capabilities belong to this workspace. This happens
    # before registry cleanup, preload, and run-invariant construction so all
    # readers and writers observe one root and descendant processes inherit it.
    from core.generated_library import bind_generated_library_to_workspace

    bind_generated_library_to_workspace(workspace)
    _snapshot_task_config(run_dir)
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")

    # ``bind_generated_library_to_workspace`` also anchors
    # SIDERIUS_CHAIN_WORKSPACE for in-process callers. The chain entry script
    # derives the same value from the same workspace argument.

    print(f"\n{'=' * 60}")
    print("  SIDERIUS Model Exploration Workflow")
    # v16-fixes — phantom sweep BEFORE preload. Any ``_capability_index.json``
    # row whose ``file_path`` doesn't resolve to a real file is removed
    # here so downstream preload + proposer rendering never advertises a
    # loadable plugin that isn't actually there. Historically this happened
    # when the pre-fix implementor wrote the index entry before the
    # validator ran; the ``feat/v16-fixes`` commit moved the write to
    # post-validation, but existing indexes may already carry phantoms
    # from prior runs (e.g. v16 global index still has
    # ``gated_dilated_tcn`` pointing at a stale pytest tmp dir).
    from agent_generated._registry import CapabilityRegistry as _StartupCapReg

    _n_pruned, _pruned_names = _cleanup_stale_registry_entries(_StartupCapReg())
    if _n_pruned:
        print(
            f"  Pruned {_n_pruned} stale registry entr"
            f"{'y' if _n_pruned == 1 else 'ies'} (missing file_path): "
            f"{_pruned_names}"
        )
    # Name the workspace-owned generated-capability library once at startup.
    # The run-invariants lock records the same path durably.
    from core.generated_library import resolve_generated_library

    _lib = resolve_generated_library()
    print(f"  Generated library: {_lib.root} (source: {_lib.source})")
    # L6c — preload promoted losses into the in-memory LOSS_REGISTRY so
    # cross-process Branch B reuse (chain resume after restart) resolves
    # without depending on SIDERIUS_LOSS_DIRS. Safe to call when the
    # library losses dirs are empty (returns []). See
    # docs/design/enable_loss_inventory.md § L6c.
    from ml_models.loss_models_sandbox import preload_global_losses
    from ml_models.plugin_loader import preload_global_models

    _preloaded = preload_global_losses()
    if _preloaded:
        print(f"  Preloaded {len(_preloaded)} global loss plugin(s): {sorted(_preloaded)}")
    # Model surface — symmetric preload so Branch B model reuse resolves
    # without depending on the workspace's SIDERIUS_PLUGIN_DIRS. Safe when
    # ``agent_generated/models/`` is empty (returns []).
    _preloaded_models = preload_global_models()
    if _preloaded_models:
        print(
            f"  Preloaded {len(_preloaded_models)} global model plugin(s): "
            f"{sorted(_preloaded_models)}"
        )
    print(f"  Started       : {started_at}")
    if launch.source_paths is not None:
        print(f"  Source paths  : {len(launch.source_paths)} files")
        for p in launch.source_paths:
            print(f"    - {p}")
    else:
        print(f"  Source run    : {launch.source_run_name}")
        print(f"  Models        : {launch.model_types}")
    print(f"  Workspace     : {workspace}")
    print(f"  Run name      : {run_name}")
    print(f"  LLM config    : {llm_config.model_dump(exclude_none=True)}")
    print(f"  Iterations    : {launch.max_iterations} (starting at {launch.start_iteration})")
    print(f"  Tune rounds   : {launch.max_rounds} per iteration")
    print(f"  Proposal tries: {launch.max_proposal_attempts} per iteration")
    if launch.target_score is not None:
        print(f"  Target score  : {launch.target_score}")
    print(f"{'=' * 60}\n")

    # --- Phase 6.6 WS-B (B.1) — hardware context for the Proposer ---
    # Discover once per workflow run and thread into every ProposalInput
    # via post-hoc assignment after local_full_context returns (pattern
    # mirrors previous_failures and mindset below at the propose call site).
    # The tuner's own HardwareContext.get_or_create call in its run() init
    # reads the same manifest path — first-caller-writes, later-callers-read.
    # See docs/phase66_ws_b_proposer_hardening.md §4.1.
    from pathlib import Path as _Path

    hardware_ctx = get_or_create_hardware_context(
        _Path(workspace),
        run_name,
    )
    # Pick the active VRAM budget per WS-B doc §4.2: trial preferred (the
    # Proposer's baseline is almost always trial-sized), fall back to
    # formal, else None (→ PHYSICAL regime rendered from the physical cap).
    active_vram_budget_gb: float | None = (
        launch.trial_vram_budget_gb
        if launch.trial_vram_budget_gb is not None
        else launch.formal_vram_budget_gb
    )
    print(
        f"  Hardware      : {hardware_ctx.device_name} "
        f"({hardware_ctx.total_memory_gb:.2f} GB total, "
        f"{hardware_ctx.usable_cap_gb:.2f} GB usable cap), "
        f"budget={active_vram_budget_gb} GB\n"
    )

    # Step 10 / P5+P6 W6 — resolve the run's scientific gate set ONCE, from
    # the run's OWN Health declaration, before anything classifies a record.
    #
    # Finding F-P56-2: every downstream classifier used to reach
    # `resolve_scientific_gate_ids(None)`, which composes with
    # `LEGACY_OMITTED` — the legacy TIDMAD task-health config. Reading gate
    # roles therefore BOUND TIDMAD's Health family process-globally, and a
    # composed run's own family was then refused by the Step-08b run-scope
    # guard: a composed contrast run could not start at all. Resolving here,
    # with the composition's declared binding, makes the run's OWN family the
    # first (and only) one bound, so the later `build_run_invariants`
    # materialisation is idempotent.
    #
    # An un-composed run passes the default binding and is byte-for-byte
    # unchanged. Nothing here inspects a task NAME: the argument is one of the
    # three declared binding STATES.
    _run_required_gate_ids = resolve_run_scientific_gate_ids(
        task_composition.task_health_binding
        if task_composition is not None
        else HealthBindingState.LEGACY_OMITTED
    )

    # --- Step 0: Load existing tuning outputs ---
    print("Step 0: Loading existing tuning outputs...")
    if launch.source_paths is not None:
        tuning_outputs = load_tuning_outputs_from_paths(launch.source_paths)
    elif launch.data_dir and launch.model_types and launch.source_run_name:
        tuning_outputs = load_tuning_outputs(
            launch.data_dir, launch.model_types, launch.source_run_name
        )
    else:
        raise ValueError(
            "Must provide either source_paths OR (data_dir + model_types + source_run_name)."
        )
    # Step 09a C2/C3 — the seeds' own reconciled spec orders their summaries.
    seed_metric_spec = reconcile_metric_spec(tuning_outputs)
    seed_summaries = tuning_outputs_to_summaries(
        tuning_outputs,
        order=MetricOrder(seed_metric_spec) if seed_metric_spec is not None else None,
        required_gate_ids=_run_required_gate_ids,
    )
    print(
        f"  Loaded {len(tuning_outputs)} tuning outputs "
        f"across {len(set(o.model_type for o in tuning_outputs))} model types.\n"
    )

    # --- DataScope + HealthGate pre-flight (DS6b) ---
    # Fails BEFORE iteration 1's LLM calls. Ordering is deliberate:
    # (1) resolve + operator-config contract checks, (2) materialize the
    # effective HealthGate config and hash it (build_run_invariants — the
    # same shared path the tuner runs, so both compute identical invariant
    # values), (3) validate every piece of ingress evidence against the
    # invariants, and only then (4) create-or-validate the workspace lock —
    # a legacy workspace is never silently locked before its restored
    # history is checked. Per-iteration tuner startup re-validates the full
    # input via validate_runtime_config; this pre-flight mirrors only the
    # subset needed to fail fast.
    _run_scope = data_scope if data_scope is not None else DataScope.default()
    # Step 10 / P1 (S1) — the run's OWN dataset topology, not the module-level
    # TIDMAD import this file used to resolve scope against. Un-composed this
    # is byte-identical: `resolve_dataset_profile()` returns `TIDMAD_PROFILE`
    # and `TIDMAD_PROFILE.dataset` IS the `TIDMAD` singleton (same object).
    # Composed, it is the composed profile — without this a composed 4-file
    # task would have had its scope resolved against TIDMAD's 20 files and
    # its `scope_is_partial` computed from somebody else's topology.
    _run_partitions = resolve_dataset_profile().partition_count
    _resolved_scope = _run_scope.resolve(_run_partitions)
    _scope_is_partial = _resolved_scope != list(range(_run_partitions))
    if _scope_is_partial and launch.formal_strategy != "snapshot":
        raise ValueError(
            f"partial data_scope requires formal_strategy='snapshot' "
            f"(got {launch.formal_strategy!r}). Operator configuration is a "
            f"contract — it is never normalized."
        )
    _refuse_data_scope_for_a_foreign_topology(_scope_is_partial, task_composition)
    if health_gate_enabled and _scope_is_partial and health_gate_files is None:
        raise ValueError(
            "partial data_scope with HealthGates enabled requires an "
            "explicit health_gate_files list (there is no automatic "
            "default). Pass health_gate_files ⊆ the scope, or disable "
            "the subsystem with health_gate_enabled=False."
        )
    _run_invariants, _run_effective_health_config = build_run_invariants(
        resolved_data_scope=_resolved_scope,
        health_gate_enabled=health_gate_enabled,
        health_gate_files=health_gate_files,
        health_checks_config=health_checks_config,
        workspace=workspace,
        # V19 PR 2 — must match what the tuner locks for this workspace,
        # or the two would write contradictory locks and abort the run.
        ordering_override_strategy=order_strategy_override,
        ordering_override_file_order=file_order_override,
        # V19 PR 3 — same rule for the structured-health-feedback policy.
        structured_health_feedback_enabled=enable_structured_health_feedback,
        health_feedback_history_window_iterations=(
            launch.health_feedback_history_window_iterations
        ),
        health_feedback_history_max_entries_per_model=(
            launch.health_feedback_history_max_entries_per_model
        ),
        # Step 10 / P1 — the composed task Health binding and the composed
        # run's semantic identity. Both are `None` for an un-composed run,
        # which keeps 08b's `LEGACY_OMITTED` resolution and leaves the
        # workspace lock byte-identical (the fingerprint key is OMITTED, not
        # serialized as null — design §5.9).
        health_materialization=RunHealthMaterialization(
            task_health_binding=(
                task_composition.task_health_binding if task_composition is not None else None
            )
        ),
        task_composition_fingerprint=(
            task_composition.semantic_fingerprint if task_composition is not None else None
        ),
        # arXiv U1 (#253 / #254) — workflow topology + experiment arm,
        # built by the ONE module-level helper (the SE.2 extraction under the
        # 12a budget); the config sha is derived from the same resolved path
        # the lit-review branch below opens.
        launch_identity=_workflow_lock_identity(launch),
    )
    for _output in tuning_outputs:
        validate_stamped_invariants(
            {
                "resolved_data_scope": getattr(_output, "resolved_data_scope", None),
                "health_gate_enabled": getattr(_output, "health_gate_enabled", None),
                "health_config_sha256": getattr(_output, "health_config_sha256", None),
                # Step 11 C8 / R-11-9.
                "task_composition_fingerprint": getattr(
                    _output, "task_composition_fingerprint", None
                ),
                # arXiv U1 (#254) — a labelled run refuses a seed/restored
                # output it cannot certify as belonging to its arm.
                "experiment_arm": getattr(_output, "experiment_arm", None),
            },
            _run_invariants,
            full_scope=list(range(_run_partitions)),
            source=f"seed/restored output '{_output.run_name}' ({_output.model_type})",
        )
    # C9d — runtime-control launch guard. Runs BEFORE any LLM call or
    # trajectory mutation and EXERCISES the lifecycle (shared estimator +
    # policy, static-cannot-block, measured-can-block, REQUEST_PROBE
    # resolving through the production entry point, exactly-once probing,
    # infrastructure failure aborting). A real launch additionally
    # requires a buildable bounded-probe runner: without one, a formal
    # decision would have no measured evidence to resolve to.
    # The capability is RESOLVED BY THE CALLER and threaded in. This module
    # is generic orchestration: it must not know which task's dataset to
    # look for, so it neither imports a task resolver nor names one.
    #
    # `run_launch_self_test` defaults `capability` to None, and generic
    # runtime-control then reports "no measurement capability was resolved
    # by the caller" — so a real launch (`require_probe_runner=True`) could
    # never satisfy the guard. Measured: a bounded real chain aborted with
    # LaunchGuardFailure before any LLM call while the capability was in
    # fact available.
    #
    # Same defect class C-C3b fixed at the tuner's call site, at the site
    # its reachability test did not cover. Fail-closed is preserved: a
    # genuinely unavailable capability still refuses, with its reason.
    _launch_report = run_launch_self_test(
        require_probe_runner=launch.require_probe_runner,
        capability=measurement_capability,
    )
    print(
        f"[RUNTIME] Launch self-test passed in {_launch_report.elapsed_seconds:.2f}s "
        f"({len(_launch_report.checks)} checks) | estimator="
        f"{_launch_report.estimator_identity} | policy="
        f"{_launch_report.policy_identity} | probe_runner="
        f"{_launch_report.probe_runner_detail}"
    )
    ensure_run_invariants(workspace, _run_invariants)
    if _scope_is_partial:
        print(
            f"[DATASCOPE] Workflow scope: files={_resolved_scope} "
            f"| health_gate_enabled={health_gate_enabled} "
            f"| monitored={health_gate_files}"
        )

    # --- Load vocabulary seed + reasoning pipeline config ---
    vocab_seed = _load_vocab_seed()
    reasoning_pipeline = _get_reasoning_pipeline(
        llm_config,
        exploration_mode=launch.exploration_mode,
        minimum_boldness=launch.minimum_boldness,
        n_candidates=launch.n_candidates,
    )
    if vocab_seed:
        print(f"  Vocab seed: {len(vocab_seed)} entries loaded.")
    if reasoning_pipeline and reasoning_pipeline.stages:
        print(
            f"  Reasoning pipeline: {[s.name for s in reasoning_pipeline.stages]} "
            f"({reasoning_pipeline.exploration_mode} mode)"
        )
    else:
        print("  Reasoning pipeline: legacy 2-call mode (no stages configured).")

    # Step 09.5a C3 — the run's immutable authorities become ONE typed
    # carrier, constructed HERE and nowhere else.
    #
    # Here, and not at the launcher, because three of these fields can only
    # exist after the startup side-effects above: the run invariants are
    # built by `build_run_invariants`, the hardware context by
    # `get_or_create_hardware_context`, and the resolved scope by
    # `DataScope.resolve` — all of which must run inside this function, in
    # this order (design §3.8). Moving construction to the launcher is
    # Step-10/12 work (design §22), not this milestone's.
    #
    # The parameters above stay explicit rather than becoming a "bindings
    # input" bag — design §13: a bag of inputs is still a bag. What changes
    # is the SOURCE OF TRUTH: from this line on, every read of a run-scoped
    # authority goes through the carrier, so no free local can drift away
    # from it. `__post_init__` refuses any `ChainState` field name, deriving
    # the forbidden set from `ChainState.__dataclass_fields__` rather than a
    # hand-written list.
    bindings = WorkflowRunBindings(
        workspace=workspace,
        run_name=run_name,
        run_dir=run_dir,
        chain_run_name=chain_run_name,
        run_id=run_id,
        data_scope=data_scope,
        resolved_data_scope=tuple(_resolved_scope),
        scope_is_partial=_scope_is_partial,
        health_gate_enabled=health_gate_enabled,
        health_gate_files=(tuple(health_gate_files) if health_gate_files is not None else None),
        # Step 12 / PR-12a **D-12a-2, source half** — the config the run
        # ACTUALLY READS, not the operator's raw source value. The decision
        # itself lives in `resolve_tuner_health_config_source`, a named
        # module-level authority, so this orchestrator gains a CALL rather
        # than another conditional (§12.1's sibling-shape tripwire, and
        # CLAUDE.md's rule that a new responsibility gets a boundary before
        # it gets a branch).
        health_checks_config=resolve_tuner_health_config_source(
            task_composition=task_composition,
            effective_config_path=_run_effective_health_config,
            operator_config=health_checks_config,
        ),
        order_strategy_override=order_strategy_override,
        file_order_override=(
            tuple(file_order_override) if file_order_override is not None else None
        ),
        enable_structured_health_feedback=enable_structured_health_feedback,
        run_invariants=_run_invariants,
        task_composition=task_composition,
        llm_config=llm_config,
        seed_metric_spec=seed_metric_spec,
        hardware_context=hardware_ctx,
        active_vram_budget_gb=active_vram_budget_gb,
        reasoning_pipeline=reasoning_pipeline,
        vocab_seed=tuple(vocab_seed),
        bridge_factory=bridge_factory,
        sandbox_factory=sandbox_factory,
        measurement_capability=measurement_capability,
    )

    # Step 10 / P1 C5 — unpack the restored transport ONCE.
    #
    # Every rule below is the one the launcher applied when it did this
    # unpacking itself; nothing is reinterpreted here. Cold start (`None`)
    # yields the same values the nine parameters defaulted to, and a restored
    # chain yields the same values the launcher passed — `RestoredState`'s own
    # container defaults are empty, which every consumer below already treats
    # identically to `None` (each tests truthiness).
    restored_runtime_vocab = restored_state.runtime_vocab if restored_state else None
    # Step 10 / P5+P6 C3 — named `restored_*` like its eight siblings now that
    # `ChainState` declares `accumulated_key_findings`. The old spelling shared
    # the carrier's field name, which the single-writer census reads as a bare
    # local twin of `state.accumulated_key_findings` — the duplicate-authority
    # shape Step 09.5a's Amendment C exists to prevent.
    restored_accumulated_key_findings = (
        restored_state.accumulated_key_findings if restored_state else None
    )
    restored_model_knowledge_cache = (
        restored_state.model_knowledge_cache if restored_state else None
    )
    accumulated_physical_rejections = (
        restored_state.accumulated_physical_rejections if restored_state else None
    )
    accumulated_negative_feedback = _restored_negative_feedback(restored_state)
    restored_previous_proposal = restored_state.previous_proposal_data if restored_state else None
    restored_chain_incumbent_score = (
        restored_state.chain_best_valid_formal_score if restored_state else None
    )
    restored_collapse_fingerprint_history = (
        restored_state.collapse_fingerprint_history if restored_state else None
    )
    restored_prediction_memory = restored_state.prediction_memory if restored_state else None
    restored_vocab_link_confirmations = (
        restored_state.vocab_link_confirmations if restored_state else None
    )

    # Step 09.5a C4 — the eleven cross-iteration accumulators are ONE typed
    # carrier now. Every seeding rule below is the one this function already
    # applied (restored vocabulary beats the static seed; the knowledge cache
    # is copied because the loop mutates it in place; best_score_overall is
    # deliberately NOT restored, being this execution's own raw-formal tracker
    # rather than the chain's decision state) — they moved to
    # `ChainState.from_restored`, they did not change.
    state = ChainState.from_restored(
        vocab_seed=list(bindings.vocab_seed),
        restored_runtime_vocab=restored_runtime_vocab,
        restored_model_knowledge_cache=restored_model_knowledge_cache,
        restored_previous_proposal=restored_previous_proposal,
        restored_chain_incumbent_score=restored_chain_incumbent_score,
        restored_collapse_fingerprint_history=restored_collapse_fingerprint_history,
        restored_prediction_memory=restored_prediction_memory,
        restored_vocab_link_confirmations=restored_vocab_link_confirmations,
        restored_accumulated_key_findings=restored_accumulated_key_findings,
        all_model_types=list({o.model_type for o in tuning_outputs}),
    )
    if restored_runtime_vocab:
        print(
            f"  [chain] Restored runtime_vocab: {len(state.current_runtime_vocab)} entries "
            f"(seed had {len(bindings.vocab_seed)})."
        )
    if state.model_knowledge_cache:
        _cache_keys_preview = sorted(state.model_knowledge_cache)[:5]
        print(
            f"  [chain] Restored model_knowledge_cache: "
            f"{len(state.model_knowledge_cache)} model(s) {_cache_keys_preview}."
        )

    # V8 Domain 1 / V20 PR D — pre-seed the bounded window with synthetic
    # wrappers carrying prior chain iterations' resource and Health feedback. Without this, every
    # chain-mode subprocess starts with an empty deque (max_iterations=1 means
    # the in-process append at iter-end never feeds the same-subprocess
    # proposer). The protocol reads only `.gate_exhaustion` from each entry, so
    # placeholder values for the other required fields are safe.
    # See docs/V8_Gap_Report.md Domain 1.
    _seed_recent_negative_feedback(state, accumulated_negative_feedback)

    # --- Iteration loop ---
    from pathlib import Path as _Path

    from core.memory_probe import probe_memory

    # Token-usage audit binder (§1.4). Closes over the workflow-local
    # ``chain_run_name`` / ``run_id`` so each agent's bridge writes rows to
    # ``{workspace}/token_usage.jsonl`` tagged with the immutable run_id.
    # When either kwarg is None (legacy / pseudo-mode tests) the bind is
    # skipped; bridges keep their default no-op behaviour. Dispatches on
    # the agent contract:
    #   * agents with an eager ``self.bridge`` (interpreter / proposer /
    #     implementor / validator) get the bridge bound directly.
    #   * the tuner exposes its own ``set_run_context`` that stashes the
    #     args until ``run()`` builds ``brain``.
    def _bind_iter_context(agent) -> None:
        if bindings.chain_run_name is None or bindings.run_id is None:
            return
        kwargs = dict(
            workspace=_Path(bindings.workspace),
            iter=iteration,
            run_name=bindings.chain_run_name,
            run_id=bindings.run_id,
        )
        if hasattr(agent, "set_run_context") and not hasattr(agent, "bridge"):
            agent.set_run_context(**kwargs)
        elif hasattr(agent, "bridge") and agent.bridge is not None:
            agent.bridge.set_run_context(**kwargs)

    # Step 10 P2a C1 — run-scoped so the Q-10-2 unrankable notice is printed
    # once for the whole run rather than once per iteration.
    _metric_identity_notice = _OncePerRunNotice()
    # `_iter_order` is bound per iteration by the fold below; predeclared so
    # the early-stop check reads a defined name even if an iteration exits
    # before reaching the fold.
    _iter_order: MetricOrder | None = None

    # Chain mode runs each iter as its own subprocess with max_iterations=1 and
    # an externally-supplied start_iteration. The loop variable becomes the
    # canonical chain-wide iteration index — it is what the InterpretationInput
    # carries (line below) and therefore what the evolution_log.jsonl writer
    # in nodes.result_interpretation_agent stamps on every row. Without this
    # offset, every chain iter would log iteration=1 (V8 Domain 3 bug).
    for iteration in range(launch.start_iteration, launch.start_iteration + launch.max_iterations):
        iter_dir = os.path.join(bindings.run_dir, f"iteration_{iteration:03d}")
        os.makedirs(iter_dir, exist_ok=True)

        loop_pos = iteration - launch.start_iteration + 1
        print(f"\n{'=' * 60}")
        print(f"  ITERATION {iteration} ({loop_pos}/{launch.max_iterations})")
        print(f"  Directory: {iter_dir}")
        print(f"{'=' * 60}\n")

        # Fix 4 — parent-process memory probe at iteration entry.
        # See docs/optimize_inference_and_scoring.md §3 Fix 4.
        probe_memory(
            iter_idx=iteration, phase="start", workspace=bindings.workspace, scope="workflow"
        )

        # --- Interpret (once per iteration) ---
        # First iter in this subprocess: all seeds are new (cache is empty).
        # Subsequent iters: only the model tuned in the previous iteration is
        # new. ``iteration == start_iteration`` is the chain-aware predicate
        # — chain-mode subprocesses run with ``start_iteration > 1``, but the
        # local "first iter in this subprocess" semantics still hold because
        # the seeds are loaded fresh per subprocess.
        if iteration == launch.start_iteration:
            new_summaries = seed_summaries
        else:
            new_summaries = (
                [state.latest_new_summary] if state.latest_new_summary is not None else []
            )

        # Cold start (explicit workflow state): no prior experimental evidence to
        # interpret — no seed/restored summaries AND an empty knowledge cache.
        # Computed here and passed explicitly so downstream nodes read the flag
        # rather than inferring it from empty prompt text. Becomes False as soon
        # as iteration 1 commits a real output (restored into new_summaries for
        # iteration 2). Never fabricates history.
        is_cold_start = (not new_summaries) and (not state.model_knowledge_cache)

        interp_storage = _make_storage(iter_dir, bindings.run_name)
        # Step 09a C2 — reconcile the run's bound MetricSpec across EVERY
        # tuning output this process has fed or will feed the interpreter:
        # the seeds/committed outputs loaded at Step 0 plus everything tuned
        # in-process. All present specs must be equal (one run, one metric) or
        # this refuses; nothing here derives a spec. The synthetic
        # gate-exhaustion placeholders are deliberately NOT included — they
        # never reach the interpreter.
        run_metric_spec = reconcile_metric_spec([*tuning_outputs, *state.iteration_results])
        interp_input = InterpretationInput(
            summaries=new_summaries,
            model_knowledge_cache=state.model_knowledge_cache,
            metric_spec=run_metric_spec,
            # Step 09a C5 — the four carried prediction-memory fields.
            prediction_outcomes_history=dict(
                state.current_prediction_memory.prediction_outcomes_history
            ),
            prediction_outcomes_by_semantics={
                version: dict(counts)
                for version, counts in (
                    state.current_prediction_memory.prediction_outcomes_by_semantics.items()
                )
            },
            cumulative_information_gain=state.current_prediction_memory.cumulative_information_gain,
            cumulative_information_gain_by_semantics=dict(
                state.current_prediction_memory.cumulative_information_gain_by_semantics
            ),
            # Step 10 / P5+P6 C2 — the vocab-link confirmation map. Before this,
            # the workflow never passed it, so the interpreter always received
            # the schema default `{}`: one iteration could append at most one
            # run_name and `VocabEntry.related_to` promotion (min_runs=3
            # DISTINCT runs) was unreachable in production.
            vocab_link_confirmations=dict(state.current_vocab_link_confirmations),
            cold_start=is_cold_start,
            # arXiv U3 (#260) — under isolation the interpreter refuses a
            # bundled built-in description, so none reaches its carried cache.
            baseline_isolation=launch.baseline_isolation,
            human_advice=launch.human_advice_interpret,
            runtime_vocab=state.current_runtime_vocab,
            previous_proposal=state.previous_proposal_data,
            storage=interp_storage,
            iteration=iteration,
            # V19 PR 3 — structured-health-feedback policy + carried
            # typed history (the interpreter runs the deterministic
            # merge; output replaces the loop variable below).
            enable_structured_health_feedback=bindings.enable_structured_health_feedback,
            health_feedback_history_window_iterations=(
                launch.health_feedback_history_window_iterations
            ),
            health_feedback_history_max_entries_per_model=(
                launch.health_feedback_history_max_entries_per_model
            ),
            collapse_fingerprint_history=state.current_collapse_fingerprint_history,
            # T4b — task config injection. Substituted into the
            # {TASK_DESCRIPTION} placeholder in PER_MODEL_SYSTEM_PROMPT +
            # SYNTHESIS_SYSTEM_PROMPT at call time.
            # See docs/design/enable_global_task_config.md § Commit T4.
            task_description=get_task_description(load_task_config()),
            # Step 09b C2 — task-owned interpretation guidance, resolved by
            # the ONE bounded Regime-A adapter (a default-path constant, not
            # a branch). Step 12's composition root replaces this call site;
            # the typed value contract stays.
            # Step 10 / P1 — a composed run supplies its OWN blocks, including
            # the legal `None` of a task that declares no interpretation
            # prose (09b: absent ⇒ no header, no bytes). The zero-arg loader
            # below remains the UN-COMPOSED branch and the bounded Regime-A
            # adapter Step 12 removes.
            task_blocks=(
                bindings.task_composition.interpretation_blocks
                if bindings.task_composition is not None
                else load_interpretation_task_blocks()
            ),
        )

        print(f"  [{iteration}] Interpreting experiment results...")
        _interp_agent = ResultInterpretationAgent(
            **bindings.llm_config.get("interpret"),
            bridge_factory=bridge_factory,
        )
        _bind_iter_context(_interp_agent)
        interpretation = _interp_agent.run(interp_input)
        # V19 PR 3 — one-directional carry: the interpreter's merged
        # history REPLACES the loop variable (never merged again here,
        # never read back from proposer output or prompts).
        state.current_collapse_fingerprint_history = dict(
            interpretation.collapse_fingerprint_history
        )
        print(f"    Take-home: {interpretation.take_home_message}")
        print(f"    Best score: {interpretation.best_denoising_score}")
        print(f"    Models: {interpretation.model_types}\n")

        # --- Lit-review (Commit 6 sub-step 6e) ---
        # Runs ONCE per iteration (before the propose/impl/valid attempts).
        # The 4-channel merge output is concatenated with the existing
        # accumulated context and threaded into every attempt's
        # ``local_full_context`` call. When ``lit_review_enabled=False``
        # (default), ``external_outputs`` stays empty and
        # ``external_channels`` is the 4-channel zero — the merge call
        # is a no-op and the proposer's behaviour is bit-identical to
        # pre-Commit-6.
        external_outputs: list[ExternalAgentOutput] = []
        if should_run_literature_review(interpretation, enabled=launch.lit_review_enabled):
            # arXiv U1 — the same resolver the pre-flight hashed through, so
            # the lock's `lit_review_config_sha256` pins THIS file.
            if launch.lit_review_config_path is None:
                raise AssertionError(
                    "literature-review config was not validated at workflow startup"
                )
            yaml_path = resolve_lit_review_config_path(launch.lit_review_config_path)
            print(f"  [{iteration}] Running lit-review (config: {yaml_path})...")
            with open(yaml_path, encoding="utf-8") as _f:
                lit_review_config = yaml.safe_load(_f)
            lit_storage = _make_storage(iter_dir, bindings.run_name)
            lit_input = _build_lit_review_input(
                lit_review_config,
                interpretation,
                llm_kwargs=bindings.llm_config.get("lit_review"),
                storage=lit_storage,
                run_name=bindings.run_name,
            )
            lit_agent = MLLiteratureReviewAgent(
                bridge_factory=bridge_factory,
                root_cache_dir=os.path.join(
                    workspace,
                    "cache",
                    "literature",
                    "root_papers",
                ),
            )
            _bind_iter_context(lit_agent)
            lit_output = lit_agent.run(lit_input)
            external_outputs.append(lit_output)
            print(
                f"    Lit-review: {len(lit_output.findings)} finding(s), "
                f"{lit_output.search_rounds_used} search round(s), "
                f"{len(lit_output.retrieved_papers)} paper(s) retrieved"
            )
            _log_rss(f"post-lit-review (iter {iteration})")
        external_channels = merge_external_agent_outputs(external_outputs)

        # --- Propose → Implement → Validate (retry loop) ---
        proposal = None
        impl_output = None
        validation = None
        previous_failures: list[str] = []

        # V8 Domain 1 — seed previous_failures with cross-iter accumulated
        # [PHYSICAL REJECTION] strings from EVERY committed prior chain iter
        # (not just the immediately-preceding one), capped to K=10 by
        # core.resume. Without this, chain-mode subprocesses run with
        # max_iterations=1 → iteration_results is empty on the first
        # in-subprocess iter → the Hop-4 seed below never fires → the
        # proposer is blind to iter N-2 and earlier rejections.
        # Runs only on the first in-subprocess iter so it doesn't double-
        # count when max_iterations > 1 (in-process mode). The Hop-4 block
        # below already covers that path via iteration_results[-1].
        # See docs/V8_Gap_Report.md Domain 1.
        if iteration == launch.start_iteration and accumulated_physical_rejections:
            _cross_iter_aggregated = _aggregate_worst_offender_rejections(
                list(accumulated_physical_rejections)
            )
            for _worst, _count in _cross_iter_aggregated:
                previous_failures.append(_render_physical_rejection(_worst, _count))
            if _cross_iter_aggregated:
                print(
                    f"  [{iteration}] Seeded {len(_cross_iter_aggregated)} "
                    f"cross-iter [PHYSICAL REJECTION] entr"
                    f"{'y' if len(_cross_iter_aggregated) == 1 else 'ies'} "
                    f"into previous_failures from "
                    f"{len(accumulated_physical_rejections)} accumulated rejection(s) "
                    f"across prior chain iters."
                )

        # Phase 6.6 WS-B B.3 Hop 4 — seed previous_failures with aggregated
        # [PHYSICAL REJECTION] strings from the PRIOR iteration's tuner so
        # the Proposer sees per-architecture VRAM lessons. No-op on
        # iteration 1 (no prior tuner output) and on iterations whose
        # prior tuner had zero infeasible attempts.
        # See docs/phase66_ws_b_proposer_hardening.md §4.3 / §6.2.
        if state.iteration_results:
            _prior = state.iteration_results[-1]
            _aggregated = _aggregate_worst_offender_rejections(
                _prior.physical_rejections,
            )
            for _worst, _count in _aggregated:
                previous_failures.append(_render_physical_rejection(_worst, _count))
            if _aggregated:
                print(
                    f"  [{iteration}] Seeded {len(_aggregated)} "
                    f"[PHYSICAL REJECTION] entr"
                    f"{'y' if len(_aggregated) == 1 else 'ies'} into "
                    f"previous_failures from iteration {iteration - 1}'s tuner."
                )

        for attempt in range(1, launch.max_proposal_attempts + 1):
            print(
                f"  [{iteration}.{attempt}] Proposing new model (attempt {attempt}/{launch.max_proposal_attempts})..."
            )

            # Create a temporary attempt dir; renamed after model name is known
            attempt_dir = os.path.join(iter_dir, f"attempt_{attempt:03d}")
            os.makedirs(attempt_dir, exist_ok=True)
            attempt_storage = _make_storage(attempt_dir, bindings.run_name)

            # Surface ALL prior iters' key_findings to the proposer as a
            # single ExpertContextItem. Without this, the proposer sees only
            # the current iter's interpretation.key_findings; chain-mode
            # amnesia drops everything before iter N-1. See
            # docs/Consistent_growing_vocab_list.md §3.3.4.
            #
            # Step 10 / P5+P6 C3 — reads the ChainState carrier. In chain mode
            # the union arrives restored (`core.resume.project_knowledge`); it
            # now also grows IN-PROCESS, so a multi-iteration run no longer
            # shows iteration 3 only what iteration 1 saw. (The comment here
            # previously cited `core.resume.load_latest_knowledge`, a function
            # Step 09.5a C1 replaced with `project_knowledge`.)
            expert_context_for_propose: list[ExpertContextItem] = []
            if state.accumulated_key_findings:
                bullet_block = "\n".join(f"- {kf}" for kf in state.accumulated_key_findings)
                expert_context_for_propose.append(
                    ExpertContextItem(
                        source="prior_iters",
                        kind="findings",
                        content=(
                            f"Accumulated key findings from "
                            f"{len(state.accumulated_key_findings)} prior iter(s):\n"
                            f"{bullet_block}"
                        ),
                        source_ref="prior_iters_key_findings",
                    )
                )

            try:
                # --- Propose ---
                # Forward the trial-mode mirror + budget set so the proposer's
                # evaluate_time_skill gate constructs the same sample_set the
                # tuner will (docs/resource_estimator_implement.md §2.7.2).
                # External-agent channels (Commit 6 sub-step 6e) — when
                # lit-review fires for this iter, its findings extend the
                # proposer's ``expert_context`` (+ its ``vocab_seed`` /
                # ``agent_cards`` / ``mindset``). When disabled,
                # ``external_channels`` is the 4-channel zero so the
                # concatenations are no-ops and ``agent_cards=[]`` /
                # ``mindset=None`` reach the protocol — which collapses
                # both to "no contributor block" via its existing
                # ``list(x or [])`` and ``if mindset is not None`` guards
                # (see ``ml_result_interp_to_ml_model_propose.py:136-198``).
                propose_input = local_full_context(
                    interpretation,
                    attempt_storage,
                    expert_context=expert_context_for_propose + external_channels["expert_context"],
                    vocab_seed=list(bindings.vocab_seed) + external_channels["vocab_seed"],
                    agent_cards=external_channels["agent_cards"],
                    mindset=external_channels["mindset"],
                    reasoning_pipeline=bindings.reasoning_pipeline,
                    human_advice=launch.human_advice_propose,
                    is_trial=launch.is_trial,
                    data_scope=bindings.data_scope,
                    # Lane F2 — FROZEN (typed) portions flow to the
                    # proposer's estimate as-is; UNFROZEN (None) resolves to
                    # the unconstrained-planner default at THIS boundary
                    # (ProposalInput stays a concrete float; absence has one
                    # meaning in one place). _portion_or is module-level so
                    # run_workflow gains ZERO branch nodes (§12.1 tripwire).
                    trial_portion=_portion_or(launch.trial_portion, UNCONSTRAINED_TRIAL_PORTION),
                    train_portion=_portion_or(launch.train_portion, UNCONSTRAINED_TRAIN_PORTION),
                    sampling_seed=launch.sampling_seed,
                    trial_time_budget_minutes=launch.trial_time_budget_minutes,
                    formal_time_budget_minutes=launch.formal_time_budget_minutes,
                    data_dir=launch.data_dir,
                    recent_tune_outputs=list(state.recent_tune_outputs),
                    # V19 PR 3 — proposer prompt flag (evidence itself
                    # travels inside the interpretation dump regardless).
                    enable_structured_health_feedback=(bindings.enable_structured_health_feedback),
                )
                propose_input.existing_model_types = list(state.all_model_types)
                # arXiv U3 (#260) — the proposer's prompt surface names no
                # bundled baseline under isolation.
                propose_input.baseline_isolation = launch.baseline_isolation
                # arXiv #259 — the declared output-type constraint, threaded
                # post-hoc like hardware_context/mindset (established pattern).
                if launch.allowed_output_types is not None:
                    propose_input.allowed_output_types = tuple(launch.allowed_output_types)
                # Task config injection (T3) — same pattern as T2's implementor
                # injection. The loader is cached per-process so this is a dict
                # lookup after the first iter. See
                # docs/design/enable_global_task_config.md § Commit T3.
                _task_cfg = load_task_config()
                propose_input.task_description = get_task_description(_task_cfg)
                propose_input.forward_contract = ForwardContract(**_task_cfg["forward_contract"])
                # Step 12 / PR-12a C7 (D-12a-6) — task-owned PROPOSER science,
                # resolved exactly as 09b resolves the interpreter's blocks: a
                # composed run supplies its OWN declaration (including the
                # legal `None` of a task that declares none, which renders
                # zero added bytes), and the un-composed branch is the ONE
                # bounded Regime-A adapter — a default-path constant, not a
                # branch on a task name.
                propose_input.proposal_blocks = resolve_run_proposal_blocks(
                    bindings.task_composition
                )
                if previous_failures:
                    propose_input.previous_failures = previous_failures
                if launch.human_advice_mindset is not None:
                    propose_input.mindset = launch.human_advice_mindset
                # WS-B B.1 — hardware-context plumb-through. Both fields
                # always set (None is a valid value for vram_budget_gb);
                # the Proposer renderer decides whether to emit the block.
                propose_input.hardware_context = bindings.hardware_context
                propose_input.vram_budget_gb = bindings.active_vram_budget_gb

                # Phase K.8 debug — dump rendered proposing-stage system
                # prompt under {run_dir}/debug/ when the flag is on.
                if launch.debug_dump_prompts:
                    propose_input.debug_dump_proposing_prompt_path = os.path.join(
                        bindings.run_dir,
                        "debug",
                        f"iter{iteration:03d}_attempt{attempt:03d}_proposing_system_prompt.md",
                    )

                if launch.validation_fixed_candidate_plan is not None:
                    # VALIDATION POSTURE ONLY. The proposer is skipped; every
                    # downstream stage still runs for real.
                    proposal = ProposalOutput.model_validate(launch.validation_fixed_candidate_plan)
                    candidate_source = "fixed_validation_plan"
                    print(
                        f"    [FIXED PLAN] proposer bypassed — candidate "
                        f"{proposal.model_name!r} supplied by the operator "
                        f"(candidate_source={candidate_source})"
                    )
                else:
                    _propose_agent = MLModelProposalAgent(
                        **bindings.llm_config.get("propose"),
                        bridge_factory=bridge_factory,
                    )
                    _bind_iter_context(_propose_agent)
                    proposal = _propose_agent.run(propose_input)
                    candidate_source = "llm_proposal"
                    print(f"    Proposed: {proposal.model_name}")
                _log_rss(f"post-proposal (iter {iteration} attempt {attempt})")
                # arXiv U3 (#260) — a bundled built-in candidate is refused
                # under isolation BEFORE implementation or tuning, by a named
                # authority (a call, not a branch: the §12.1 tripwire).
                refuse_builtin_proposal_under_isolation(
                    proposal, baseline_isolation=launch.baseline_isolation
                )

                # Rename attempt dir to include model name
                named_dir = os.path.join(iter_dir, f"attempt_{attempt:03d}_{proposal.model_name}")
                os.rename(attempt_dir, named_dir)
                attempt_dir = named_dir
                attempt_storage = _make_storage(attempt_dir, bindings.run_name)

                # --- Implement → Validate (inner retry loop per proposal) ---
                # Load reference code once (shared across impl attempts for this proposal)
                ref_code: dict = {}
                if hasattr(proposal, "inherited_components") and proposal.inherited_components:
                    from nodes.proposal_helpers import load_model_source

                    # Reference code is only available for experiment-source
                    # inheritances (past chain runs). External-agent and human
                    # source inheritances have no plugin source to load.
                    # ProposalOutput.inherited_components is typed as
                    # list[InheritedComponent] (Pydantic-validated upstream), so
                    # no dict fallback is required here.
                    ref_models = {
                        ic.source_id
                        for ic in proposal.inherited_components
                        if ic.source_type == "experiment" and ic.source_id
                    }
                    for mt in ref_models:
                        src = load_model_source(mt)
                        if src:
                            ref_code[mt] = src
                    if ref_code:
                        print(
                            f"    Reference code: {list(ref_code.keys())} "
                            f"({sum(len(v.split(chr(10))) for v in ref_code.values())} lines)"
                        )

                valid_llm = bindings.llm_config.get("validate")
                previous_validation_failure: str | None = None

                for impl_attempt in range(1, launch.max_impl_attempts + 1):
                    impl_suffix = (
                        f" (impl {impl_attempt}/{launch.max_impl_attempts})"
                        if launch.max_impl_attempts > 1
                        else ""
                    )
                    print(f"  [{iteration}.{attempt}] Implementing{impl_suffix}...")
                    # S2 / U6 (#256): each implement→validate attempt gets
                    # its own nested `impl_NNN/` — records and generated
                    # sources of a retry never overwrite the previous one.
                    impl_storage = impl_attempt_storage(
                        attempt_dir, bindings.run_name, impl_attempt
                    )
                    impl_input = local_full_spec(proposal, impl_storage.storage)
                    impl_input.plugin_dir = impl_storage.plugin_dir
                    impl_input.test_dir = impl_storage.test_dir
                    # L4b — loss-plugin staging directory. Mirrors plugin_dir
                    # for run-scoped isolation. Concurrent iterations write
                    # to disjoint dirs so no clobbering occurs. The sandbox
                    # executor adds this to SIDERIUS_LOSS_DIRS at training
                    # time so load_loss_plugin can find the freshly-written
                    # plugin. See docs/design/enable_loss_inventory.md § L4.
                    impl_input.loss_dir = impl_storage.loss_dir
                    # Task config injection (T2) — load + thread into the
                    # implementor input. The loader is cached per-process so
                    # this is a dict lookup after the first iter. See
                    # docs/design/enable_global_task_config.md § Commit T2.
                    _task_cfg = load_task_config()
                    impl_input.task_description = get_task_description(_task_cfg)
                    impl_input.forward_contract = ForwardContract(**_task_cfg["forward_contract"])
                    # Step 12 / PR-12a C7-4 — task-owned IMPLEMENTOR science,
                    # resolved by the same rule as its two siblings.
                    impl_input.implementor_blocks = resolve_run_implementor_blocks(
                        bindings.task_composition
                    )
                    # Step 04a (OD-S4-1): the same live manifest and budget
                    # the proposer receives, so the implementor's capacity
                    # prose quotes this machine instead of a stale literal.
                    impl_input.hardware_context = bindings.hardware_context
                    impl_input.vram_budget_gb = bindings.active_vram_budget_gb
                    if launch.human_advice_implement is not None:
                        impl_input.human_advice = launch.human_advice_implement
                    if ref_code:
                        impl_input.reference_code = ref_code
                    if previous_validation_failure is not None:
                        impl_input.previous_validation_failure = previous_validation_failure

                    _impl_agent = MLModelImplementor(
                        **bindings.llm_config.get("implement"),
                        bridge_factory=bridge_factory,
                    )
                    _bind_iter_context(_impl_agent)
                    impl_output = _impl_agent.run(impl_input)
                    print(f"    Plugin: {impl_output.model_file_path}")
                    _log_rss(
                        f"post-implement (iter {iteration} attempt {attempt} impl {impl_attempt})"
                    )

                    # --- Validate ---
                    print(f"  [{iteration}.{attempt}] Validating...")
                    valid_input = local_all_fields(
                        impl_output,
                        impl_storage.storage,
                        llm_provider=valid_llm.get("provider", "gemini"),
                        llm_model_id=valid_llm.get("model_id", "gemini-3.1-flash-lite-preview"),
                    )
                    if launch.human_advice_validate is not None:
                        valid_input.human_advice = launch.human_advice_validate
                    if hasattr(proposal, "inherited_components") and proposal.inherited_components:
                        valid_input.inherited_components = proposal.inherited_components

                    _valid_agent = MLCodeValidatorAgent(
                        **valid_llm,
                        bridge_factory=bridge_factory,
                    )
                    _bind_iter_context(_valid_agent)
                    validation = _valid_agent.run(valid_input)
                    _log_rss(
                        f"post-validate (iter {iteration} attempt {attempt} impl {impl_attempt})"
                    )

                    if validation.passed:
                        print("    All 7 checks passed.\n")
                        # Mirror the #92 fix for the model surface: register
                        # the model in ``_capability_index.json`` and load it
                        # into ``MODEL_REGISTRY`` ONLY after validation
                        # passes. The implementor now hands the metadata
                        # back via ``impl_output.capability_metadata`` (see
                        # ``agent/schemas/implementor.py``) so the registry
                        # write happens here, not inside the implementor.
                        # Before this fix, a validation failure left a
                        # phantom index entry that every future proposer
                        # then advertised as a Branch B candidate (v16
                        # iter_015 ``gated_dilated_tcn``).
                        _capmeta = getattr(impl_output, "capability_metadata", None)
                        if _capmeta is not None:
                            from agent_generated._registry import (
                                CapabilityRegistry as _CapReg,
                            )

                            _CapReg().register(_capmeta)
                            print(f"    ✅ Registered → model '{_capmeta.name}' (post-validation)")
                            _registered_in_memory = register_model_in_memory(
                                impl_output.model_file_path
                            )
                            if _registered_in_memory is not None:
                                print(
                                    f"    ✅ MODEL_REGISTRY ← '{_registered_in_memory}' (in-memory)"
                                )
                        break

                    previous_validation_failure = (
                        validation.error_message or "Unknown validation error"
                    )
                    print(f"    Validation FAILED: {previous_validation_failure}")
                    if impl_attempt < launch.max_impl_attempts:
                        print("    Retrying implementation with validator feedback...\n")

                if validation and validation.passed:
                    break

                # All impl attempts for this proposal exhausted
                previous_failures.append(previous_validation_failure or "Unknown error")
                if attempt < launch.max_proposal_attempts:
                    print("    Retrying with a new proposal...\n")

            except Exception as e:
                error_msg = f"Node error: {type(e).__name__}: {e}"
                print(f"    ERROR: {error_msg}")
                previous_failures.append(error_msg)
                if attempt < launch.max_proposal_attempts:
                    print("    Retrying with failure feedback...\n")

        if not validation or not validation.passed:
            print(
                f"\n  Iteration {iteration}: exhausted {launch.max_proposal_attempts} proposal "
                f"attempts without passing validation. Skipping to next iteration."
            )
            continue

        # Invariant: ``validation.passed`` is True here, which means the
        # propose → impl → validate chain ran end-to-end this iteration —
        # ``proposal`` was assigned before ``impl_input`` was constructed.
        # The assert documents the invariant and narrows
        # ``proposal: ProposalOutput | None`` to ``ProposalOutput`` for the
        # rest of the iteration body (tuning + cache update + score check).
        assert proposal is not None

        # --- Tune (set up storage + run-scoped plugin dir up front) ---
        tuning_dir = os.path.join(iter_dir, proposal.model_name)
        os.makedirs(tuning_dir, exist_ok=True)
        tuning_storage = _make_storage(tuning_dir, bindings.run_name)

        # --- Register validated plugin into TWO dirs:
        #
        #     1. Tuner-scoped ``{tuning_dir}/plugins/{run_name}/`` — the
        #        training subprocess picks it up via SIDERIUS_PLUGIN_DIRS
        #        (docs/run_scoped_plugins.md, Phase 4). The tuner's sandbox
        #        has not been constructed yet, but ``get_plugin_dir`` is the
        #        single source of truth for the layout, so the workflow can
        #        write here safely; the sandbox will ``_ensure_dir`` the
        #        same path moments later without disturbing existing
        #        contents.
        #     2. Chain-canonical ``{workspace}/plugins/{run_name}/`` —
        #        ``core.resume.restore_prior_state`` looks here on the next
        #        iter to re-register the plugin class, and
        #        ``ml_models.model_descriptions.get_model_description``
        #        walks this tree to resolve agent-generated descriptions
        #        across iterations. Phase 6.8 §3.3.
        from core.sandbox_executor import get_loss_dir, get_plugin_dir

        tuner_plugin_dir = get_plugin_dir(tuning_dir, bindings.run_name)
        chain_plugin_dir = get_plugin_dir(bindings.workspace, bindings.run_name)
        # L6a — loss-plugin propagation mirrors the model-plugin pattern.
        # Tuner-scoped dir must match ``TidmadSandbox.loss_dir`` (computed
        # from the sandbox's own workspace ≈ ``tuning_dir``) so the
        # subprocess's ``SIDERIUS_LOSS_DIRS`` resolves the plugin.
        # Chain-canonical dir preserves the file for resume / future-iter
        # Branch B lookups. See docs/design/enable_loss_inventory.md § L6.
        tuner_loss_dir = get_loss_dir(tuning_dir, bindings.run_name)
        chain_loss_dir = get_loss_dir(bindings.workspace, bindings.run_name)
        _register_plugin(
            impl_output,
            proposal.model_name,
            [tuner_plugin_dir, chain_plugin_dir],
            dest_loss_dirs=[tuner_loss_dir, chain_loss_dir],
        )

        # Issue #92 — promote the generated loss plugin to the global
        # ``agent_generated/losses/`` library IMMEDIATELY after validation
        # succeeds and the workspace-scoped registration completes, not
        # after the tuner finishes. The previous behaviour (call only at
        # iter end, post-tuner) opened a window during which the
        # capability index advertised the loss but the ``.py`` file still
        # lived in this chain's workspace — a parallel chain reading the
        # index could not load it (v15 arch iters 1-3 blocked on this
        # exact failure, unblocked only by a manual ``cp``). Calling
        # ``_promote_loss_to_global`` here closes that window before
        # tuner.run() consumes the registry. The helper's atomicity
        # (file copy first, then ``registry.replace``) means no parallel
        # reader sees a registry-says-yes / file-says-no state. The late
        # call below remains as an idempotent safety net.
        _promote_loss_to_global(impl_output)
        # Model surface — symmetric early promotion so Branch B model
        # reuse from a parallel chain or the next iter resolves the
        # plugin via the global path without depending on this run's
        # workspace. Helper no-ops cleanly on Branch B reuse (file
        # already at the global path) and on Branch A (no generated
        # plugin to promote). See ``_promote_model_to_global`` docstring.
        _promote_model_to_global(impl_output)

        print(f"  [{iteration}] Tuning '{proposal.model_name}' for {launch.max_rounds} rounds...")
        tune_llm = bindings.llm_config.get("tune")
        tune_input = local_validated_model(
            validation,
            proposal,
            tuning_storage,
            max_rounds=launch.max_rounds,
            health_checks_config=bindings.health_checks_config,
            # Step 12 / PR-12a (D-12a-1) — the composition projection crosses
            # the edge on the INPUT, beside every other run-scoped decision
            # this protocol already maps.
            task_composition_ref=build_task_composition_ref(bindings.task_composition),
            data_scope=bindings.data_scope,
            health_gate_enabled=bindings.health_gate_enabled,
            health_gate_files=(
                list(bindings.health_gate_files) if bindings.health_gate_files is not None else None
            ),
            # V21 PR D — hop 7 -> hop 8, unchanged including `None`.
            healthgate_mode=launch.healthgate_mode,
            result_authority=launch.result_authority,
            file_index=launch.file_index,
            llm_provider=tune_llm.get("provider", "gemini"),
            llm_model_id=tune_llm.get("model_id", "gemini-3.1-flash-lite-preview"),
            reflect_provider=tune_llm.get("reflect_provider"),
            reflect_model_id=tune_llm.get("reflect_model_id"),
            is_trial=launch.is_trial,
            # Lane F2 — TRANSIT-ONLY fields (no tuner consumer); a bare
            # launch restores the input-schema default so input bytes are
            # byte-identical to pre-F2 runs. The EXECUTED lock is the
            # plan_overrides merge above.
            trial_portion=_portion_or(
                launch.trial_portion, _TUNER_INPUT_PORTION_DEFAULTS["trial_portion"]
            ),
            train_portion=_portion_or(
                launch.train_portion, _TUNER_INPUT_PORTION_DEFAULTS["train_portion"]
            ),
            eval_portion=_portion_or(
                launch.eval_portion, _TUNER_INPUT_PORTION_DEFAULTS["eval_portion"]
            ),
            train_validation_align=launch.train_validation_align,
            sampling_seed=launch.sampling_seed,
            train_base_seed=launch.train_base_seed,
            cleanup_denoised=launch.cleanup_denoised,
            max_epochs=launch.max_epochs,
            # D-BUD-6 — per-mode epoch ceilings, carried through unchanged
            # including `None` (None = mode-agnostic max_epochs governs).
            trial_max_epochs=launch.trial_max_epochs,
            formal_max_epochs=launch.formal_max_epochs,
            validation_max_portion=launch.validation_max_portion,
            validation_max_train_samples=launch.validation_max_train_samples,
            validation_max_samples=launch.validation_max_samples,
            validation_max_phase_seconds=launch.validation_max_phase_seconds,
            skip_formal_min_delta=launch.skip_formal_min_delta,
            bypass_formal_time_budget_min_delta=launch.bypass_formal_time_budget_min_delta,
            bypass_formal_time_budget_minutes=launch.bypass_formal_time_budget_minutes,
            max_retries=tune_llm.get("max_retries"),
            # Lane F2 — EXPERIMENT_FIXED portions join the plan_overrides
            # lock here (typed-only; conflict with explicit JSON refuses).
            plan_overrides=frozen_portion_overrides(launch),
            trial_time_budget_minutes=launch.trial_time_budget_minutes,
            formal_time_budget_minutes=launch.formal_time_budget_minutes,
            data_dir=launch.data_dir,
            gpu_admission_measurement_source=launch.gpu_admission_measurement_source,
            gpu_admission_enforcement=launch.gpu_admission_enforcement,
            gpu_pair_ceiling_gib=launch.gpu_pair_ceiling_gib,
            trial_vram_budget_gb=launch.trial_vram_budget_gb,
            formal_vram_budget_gb=launch.formal_vram_budget_gb,
            formal_strategy=launch.formal_strategy,
            formal_portion=launch.formal_portion,
            formal_train_portion=launch.formal_train_portion,
            formal_eval_portion=launch.formal_eval_portion,
            force_formal_round=launch.force_formal_round,
            formal_round_strategy=launch.formal_round_strategy,
            degenerate_penalty_score=launch.degenerate_penalty_score,
            attempts_per_round=launch.attempts_per_round,
            attempts_per_formal_round=launch.attempts_per_formal_round,
            max_fail_rounds=launch.max_fail_rounds,
            max_steps_per_attempt=launch.max_steps_per_attempt,
            min_formal_batch_size=launch.min_formal_batch_size,
            allow_extreme_steps=launch.allow_extreme_steps,
            runtime_watchdog_enabled=launch.runtime_watchdog_enabled,
            runtime_safety_factor=launch.runtime_safety_factor,
            runtime_trial_safety_factor=launch.runtime_trial_safety_factor,
            runtime_formal_safety_factor=launch.runtime_formal_safety_factor,
            runtime_watchdog_safety_factor=launch.runtime_watchdog_safety_factor,
            runtime_watchdog_floor_seconds=launch.runtime_watchdog_floor_seconds,
            # V19 PR 1 (P1-C3) — the chain incumbent travels as a NAMED
            # protocol parameter (two-state design, design doc §3.4).
            # ``chain_formal_incumbent_reference`` is decision state:
            # seeded from RestoredState, updated only from committed
            # VALID formals. ``best_score_overall`` (raw progress) is
            # deliberately NOT used here — the pre-V19 post-hoc mutation
            # that fed it to the tuner is removed.
            current_run_best_formal_score=state.chain_formal_incumbent_reference,
            enable_chain_incumbent_formal_gates=launch.enable_chain_incumbent_formal_gates,
            # V19 PR 2 — operator ordering override for every round of this
            # iteration. The agent's per-round proposal is resolved against
            # it inside the tuner; the workflow never resolves ordering.
            order_strategy_override=bindings.order_strategy_override,
            file_order_override=(
                list(bindings.file_order_override)
                if bindings.file_order_override is not None
                else None
            ),
            # V19 PR 3 — policy pass-through so the TUNER's lock matches
            # the workflow's (contradictory locks abort the run).
            enable_structured_health_feedback=bindings.enable_structured_health_feedback,
            health_feedback_history_window_iterations=(
                launch.health_feedback_history_window_iterations
            ),
            health_feedback_history_max_entries_per_model=(
                launch.health_feedback_history_max_entries_per_model
            ),
            # arXiv U1 (#253 / #254) — read from the ONE lock object this
            # pre-flight built (never re-derived here), so the tuner's
            # per-model lock and the chain lock cannot disagree — the
            # F-11-C10-a lesson: two derivations of one identity are two
            # chances to diverge.
            experiment_arm=_run_invariants.experiment_arm,
            lit_review_enabled=_run_invariants.lit_review_enabled,
            lit_review_config_sha256=_run_invariants.lit_review_config_sha256,
            baseline_isolation=_run_invariants.baseline_isolation,
        )
        if launch.human_advice_tune is not None:
            tune_input.human_advice = launch.human_advice_tune
        # Task config injection (T4a) — substituted into the {TASK_DESCRIPTION}
        # placeholder in PLANNER_PROMPT via brain.plan(task_description=...).
        # See docs/design/enable_global_task_config.md § Commit T4a.
        tune_input.task_description = get_task_description(load_task_config())

        _tune_agent = HyperparamTuningAgent(
            bridge_factory=bridge_factory,
            sandbox_factory=sandbox_factory,
        )
        _bind_iter_context(_tune_agent)
        # The tuner's planner is what triggers evaluate_vram_skill internally;
        # log RSS here so an OOM during the probe leaves us with a baseline
        # to subtract from in the dmesg dump.
        _log_rss(f"pre-vram-probe (iter {iteration}, before tuner.run)")
        tune_output = _tune_agent.run(tune_input)
        state.iteration_results.append(tune_output)

        # Issue #92 safety net — the primary promotion fires earlier
        # (right after ``_register_plugin``) so the loss is globally
        # available before the tuner starts. This late call is kept as an
        # idempotent backstop in case the early call was skipped (e.g.
        # the file moved between calls, a concurrent process altered the
        # global path, or a future code change inadvertently bypassed
        # the early promotion). The helper's idempotency check (file
        # already at global path → skip the copy, still re-assert the
        # registry entry) makes this safe to call unconditionally.
        #
        # Originally L6c was here as the ONLY promotion point — fired
        # after the iteration's tuner completes so a tuner-failed iter
        # would still publish its validated plugin. That behaviour is
        # preserved by the early call above. See
        # ``docs/design/enable_loss_inventory.md § L6c`` for design
        # rationale; the early-promotion fix is tracked as issue #92.
        _promote_loss_to_global(impl_output)
        # Phase N (§14.N) — append to the bounded FIFO; deque(maxlen=3)
        # auto-evicts the oldest entry so the next iteration's
        # local_full_context call sees only the most recent 3.
        state.recent_tune_outputs.append(tune_output)

        # --- Update long-term memory for next iteration ---
        state.all_model_types.append(proposal.model_name)

        # Build ModelRunSummary for the newly tuned model (fed to iter N+1 as new_summaries)
        new_model_summaries = tuning_outputs_to_summaries(
            [tune_output],
            order=(
                MetricOrder(tune_output.metric_spec)
                if tune_output.metric_spec is not None
                else None
            ),
            # W6 — the same resolved set the seeds were classified against,
            # so an in-run summary and a restored one cannot disagree about
            # which gates decide validity.
            required_gate_ids=_run_required_gate_ids,
        )
        for s in new_model_summaries:
            # Attach description so iter N+1 interpretation agent can find it
            # without filesystem access to the attempt directory
            s.model_description = proposal.model_description
        state.latest_new_summary = new_model_summaries[0]

        # Update knowledge cache from interpretation output
        if (
            hasattr(interpretation, "model_knowledge_cache")
            and interpretation.model_knowledge_cache
        ):
            state.model_knowledge_cache = dict(interpretation.model_knowledge_cache)
            state.model_knowledge_cache, evicted = _cap_knowledge_cache(
                state.model_knowledge_cache,
                current_model=proposal.model_name,
                order=MetricOrder(run_metric_spec) if run_metric_spec is not None else None,
            )
            if evicted:
                print(
                    f"  [{iteration}] Cache capped: evicted {sorted(evicted)}, "
                    f"kept {len(state.model_knowledge_cache)} entries."
                )
            print(
                f"  [{iteration}] Knowledge cache: {len(state.model_knowledge_cache)} models cached."
            )

        # Step 09a C5 — carry the interpreter's prediction memory to the next
        # iteration. Read straight off the digest the interpreter just wrote,
        # so the in-process loop and the chain-subprocess restore agree by
        # construction rather than by two independent accumulations.
        state.current_prediction_memory = PredictionMemory(
            prediction_outcomes_history=dict(interpretation.prediction_outcomes_history),
            prediction_outcomes_by_semantics={
                version: dict(counts)
                for version, counts in interpretation.prediction_outcomes_by_semantics.items()
            },
            cumulative_information_gain=interpretation.cumulative_information_gain,
            cumulative_information_gain_by_semantics=dict(
                interpretation.cumulative_information_gain_by_semantics
            ),
        )

        # Step 10 / P5+P6 C2 — carry the vocab-link confirmation map, the same
        # way and for the same reason. LATEST-WINS on the whole mapping:
        # `update_vocab_link_confirmations` already returned the FULL cumulative
        # map, so re-merging here would be a second accumulation authority and
        # could disagree with the producer about the promotion count.
        state.current_vocab_link_confirmations = {
            key: list(runs) for key, runs in interpretation.vocab_link_confirmations.items()
        }

        # Step 10 / P5+P6 C3 — union THIS iteration's findings into the carried
        # history by CALLING the one authority (`core.resume.union_key_findings`),
        # which the digest projection also calls. Genuinely applied, not
        # re-implemented: an uninterrupted in-process trajectory and a
        # per-iteration chain restore produce EQUAL state by construction, and
        # the merge rule does not live in this already-large function.
        #
        union_key_findings(state.accumulated_key_findings, interpretation.key_findings)

        # Update runtime vocab from interpretation output
        state.previous_proposal_data = proposal.model_dump()
        if hasattr(interpretation, "runtime_vocab") and interpretation.runtime_vocab:
            state.current_runtime_vocab = [
                v if hasattr(v, "name") else VocabEntry.model_validate(v)
                for v in interpretation.runtime_vocab
            ]
            print(
                f"  [{iteration}] Vocab updated: {len(state.current_runtime_vocab)} entries "
                f"({sum(1 for v in state.current_runtime_vocab if v.kind == 'discovery')} discoveries)"
            )

        # --- Check score target ---
        # ``best_score_overall`` is the current-workflow RAW-formal
        # progress tracker (print + workflow summary ONLY — V19 PR 1
        # two-state design; it no longer feeds the tuner). It must track
        # FORMAL scores only — a noisy trial score from an iter whose
        # formal rounds all got gated would otherwise misreport progress.
        # (Historical context: v15's mamba_multirate_fuser trial 7.65 /
        # dualpath_spectral_router trial 7.77 motivated formal-only.)
        # Step 10 P2a C1 — the order these three decisions use is acquired by
        # RECONCILIATION, not precedence (design §4.1): the run's bound spec
        # and this output's own stamp are BOTH offered, and a disagreement
        # fails closed rather than letting either shadow the other. Acquired
        # ONCE per iteration because all three decisions must rank on the same
        # metric; a bound-vs-stamp conflict raises out of this call.
        _iter_order = _acquire_iteration_order(bindings, tune_output)

        if _iter_order is None:
            # Q-10-2 / §4.2 case B-C: no reconciled identity, so NOTHING is
            # ranked. The trackers are deliberately left untouched — including
            # the bootstrap, because a tracker seeded with an arbitrary first
            # value would then be printed as "Best overall" while no
            # comparison was ever legitimate. Raw scores stay visible in the
            # per-iteration line and the summary; no direction is assumed.
            _metric_identity_notice.warn_once(f"iteration {iteration}")
        else:
            if tune_output.best_formal_denoising_score is not None and (
                state.best_score_overall is None
                or _iter_order.is_better(
                    tune_output.best_formal_denoising_score, state.best_score_overall
                )
            ):
                state.best_score_overall = tune_output.best_formal_denoising_score

            # V19 PR 1 — DECISION-STATE incumbent update (in-process
            # multi-iteration equivalence with N chained subprocesses,
            # design §3.4): only this iteration's committed VALID formal may
            # advance ``chain_formal_incumbent_reference``; strictly-BETTER
            # keeps the earliest holder on ties (§3.3), which `is_better`
            # preserves under both directions.
            _iter_valid_formal = tune_output.best_valid_formal_denoising_score
            if _iter_valid_formal is not None and (
                state.chain_formal_incumbent_reference is None
                or _iter_order.is_better(_iter_valid_formal, state.chain_formal_incumbent_reference)
            ):
                state.chain_formal_incumbent_reference = _iter_valid_formal

        print(
            f"\n  [{iteration}] Complete: {proposal.model_name} "
            f"best_score={tune_output.best_denoising_score}"
        )

        # Fix 4 — parent-process memory probe at iteration exit. Fires
        # even on the iteration that triggers the target-score break
        # (placed before the break check) so the last iteration's
        # terminal RSS is always logged.
        probe_memory(
            iter_idx=iteration, phase="end", workspace=bindings.workspace, scope="workflow"
        )

        # Phase 6.8 §2 Layer B (Commit 3) — per-iteration cleanup. Drop
        # local refs to per-iter agent outputs, force a GC cycle, then
        # emit a post_gc probe so the trace consumer can read the
        # freed-memory delta as ``end.rss_gb - post_gc.rss_gb``.
        # tune_output is also retained in iteration_results /
        # recent_tune_outputs (live refs); the local del here just
        # decrements the local-name refcount. NameError-guarded
        # because early-exit paths may leave some names unbound.
        # See docs/phase68_task1_memory_diagnostic_20260427.md §2 Commit 3.
        with suppress(NameError):
            del proposal
        with suppress(NameError):
            del impl_output
        with suppress(NameError):
            del validation
        with suppress(NameError):
            del interpretation
        with suppress(NameError):
            del interp_input
        with suppress(NameError):
            del tune_input
        with suppress(NameError):
            del tune_output
        gc.collect()
        probe_memory(
            iter_idx=iteration, phase="post_gc", workspace=bindings.workspace, scope="workflow"
        )

        # Step 10 P2a C1 — "reached the target" means AT LEAST AS GOOD AS the
        # target on the metric's own axis, which under a minimised metric is
        # `<=`. `_iter_order` is this iteration's reconciled order; when it is
        # None nothing was ranked, `best_score_overall` was never advanced, and
        # the guard below short-circuits on it — an unranked run never stops
        # early on an assumed direction.
        if (
            launch.target_score is not None
            and state.best_score_overall is not None
            and _iter_order is not None
            and _iter_order.is_at_least(state.best_score_overall, launch.target_score)
        ):
            print(
                f"\n  Target score {launch.target_score} reached "
                f"(best={state.best_score_overall}). Stopping early."
            )
            break

    # --- Final summary ---
    finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 60}")
    print("  Workflow Complete")
    print(f"  Started     : {started_at}")
    print(f"  Finished    : {finished_at}")
    print(f"  Iterations  : {len(state.iteration_results)}/{launch.max_iterations}")
    print(f"  Best overall: {state.best_score_overall}")
    for i, result in enumerate(state.iteration_results, 1):
        print(f"    Iteration {i}: {result.model_type} score={result.best_denoising_score}")
    print(f"{'=' * 60}\n")

    _save_workflow_summary(
        bindings.run_dir,
        bindings.run_name,
        started_at,
        finished_at,
        state.iteration_results,
        state.best_score_overall,
    )

    return state.iteration_results


def _save_workflow_summary(
    workspace: str,
    run_name: str,
    started_at: str,
    finished_at: str,
    iteration_results: list[HyperparamTuningOutput],
    best_score_overall: float | None,
):
    """Save a JSON summary of the full workflow run."""
    summary = {
        "workflow": "model_exploration",
        "run_name": run_name,
        "status": "completed" if iteration_results else "failed",
        "started_at": started_at,
        "finished_at": finished_at,
        "total_iterations": len(iteration_results),
        "best_score_overall": best_score_overall,
        "iterations": [
            {
                "model_type": r.model_type,
                "best_score": r.best_denoising_score,
                "completed_rounds": r.completed_rounds,
                "status": r.status,
            }
            for r in iteration_results
        ],
    }
    path = os.path.join(workspace, f"workflow_{run_name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=4)
    print(f"  Workflow summary saved -> {path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="SIDERIUS Model Exploration Workflow — "
        "iteratively interpret results, propose new models, implement, "
        "validate, and tune.",
    )
    parser.add_argument(
        "--data_dir",
        type=str,
        required=True,
        help="Root data directory containing existing tuning results.",
    )
    parser.add_argument(
        "--models",
        type=str,
        nargs="+",
        required=True,
        help="Model types to include in initial interpretation (e.g. punet wavenet rnn).",
    )
    parser.add_argument(
        "--source_run_name",
        type=str,
        required=True,
        help="Run name to load initial tuning results from (e.g. 'v3_file6'). "
        "One output per model is loaded from {data_dir}/{model}/{source_run_name}/agent/.",
    )
    parser.add_argument(
        "--workspace",
        type=str,
        default="./workflow_output",
        help="Root output directory for this workflow run.",
    )
    parser.add_argument(
        "--run_name",
        type=str,
        default="explore_v1",
        help="Unique name for this workflow run.",
    )
    parser.add_argument(
        "--max_iterations",
        type=int,
        default=1,
        help="Number of successful iterations (default: 1 = single pass).",
    )
    parser.add_argument(
        "--max_rounds",
        type=int,
        default=10,
        help="Tuning budget per iteration (default: 10).",
    )
    parser.add_argument(
        "--max_proposal_attempts",
        type=int,
        default=3,
        help="Max propose→implement→validate retries per iteration (default: 3).",
    )
    parser.add_argument(
        "--target_score",
        type=float,
        default=None,
        help="Optional early stop: halt if best score >= target.",
    )
    parser.add_argument(
        "--file_index",
        type=int,
        default=6,
        help="Training/validation file index (default: 6).",
    )
    # LLM configuration
    parser.add_argument(
        "--llm_config",
        type=str,
        default=None,
        help="Path to a JSON file with per-node LLM config. "
        'Format: {"interpret": {"provider": "gemini", "model_id": "..."}, ...}. '
        "Nodes not listed use their built-in defaults.",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        choices=["gemini", "openai"],
        help="LLM provider for ALL nodes (shorthand — overridden by --llm_config).",
    )
    parser.add_argument(
        "--model_id",
        type=str,
        default=None,
        help="LLM model ID for ALL nodes (shorthand — overridden by --llm_config).",
    )

    # Human advice per step (all optional)
    parser.add_argument(
        "--advice_interpret",
        type=str,
        default=None,
        help="Human guidance for interpretation steps.",
    )
    parser.add_argument(
        "--advice_propose",
        type=str,
        default=None,
        help="Human guidance for proposal steps "
        "(e.g. 'propose a lightweight model with < 100K params').",
    )
    parser.add_argument(
        "--advice_implement",
        type=str,
        default=None,
        help="Human guidance for implementation steps.",
    )
    parser.add_argument(
        "--advice_validate",
        type=str,
        default=None,
        help="Human guidance for validation steps.",
    )
    parser.add_argument(
        "--advice_tune",
        type=str,
        default=None,
        help="Human guidance for tuning steps (e.g. 'keep epochs <= 3 for quick testing').",
    )
    parser.add_argument(
        "--task_composition",
        type=str,
        required=True,
        help=(
            "Path to a required YAML task-composition manifest. "
            "It binds the task for the complete run and fails closed if unresolved."
        ),
    )
    args = parser.parse_args()

    # Build LLM config: --llm_config file takes precedence, then --provider/--model_id
    if args.llm_config:
        wf_llm_config = WorkflowLLMConfig.from_json(args.llm_config)
    elif args.provider and args.model_id:
        wf_llm_config = WorkflowLLMConfig.uniform(args.provider, args.model_id)
    elif args.provider:
        wf_llm_config = WorkflowLLMConfig.uniform(args.provider, "gemini-3.1-flash-lite-preview")
    else:
        wf_llm_config = None  # each node uses its own default

    # Step 10 / P1 — the module CLI is a composition edge too, and it owns
    # the binding for exactly the same reason the chain launcher does.
    run_composition = compose_run_task_bindings(args.task_composition)
    # Step 11 C4 — same binding, same authority as the chain launcher.
    # A composed run with no --data_dir is refused rather than silently
    # reading TIDMAD's data (R-11-8).
    with bind_run_task_composition(run_composition, physical_data_root=args.data_dir):
        run_workflow(
            launch=WorkflowLaunchConfig(
                data_dir=args.data_dir,
                model_types=args.models,
                source_run_name=args.source_run_name,
                max_iterations=args.max_iterations,
                max_rounds=args.max_rounds,
                max_proposal_attempts=args.max_proposal_attempts,
                target_score=args.target_score,
                file_index=args.file_index,
                human_advice_interpret=args.advice_interpret,
                human_advice_propose=args.advice_propose,
                human_advice_implement=args.advice_implement,
                human_advice_validate=args.advice_validate,
                human_advice_tune=args.advice_tune,
            ),
            workspace=args.workspace,
            run_name=args.run_name,
            llm_config=wf_llm_config,
            task_composition=run_composition,
        )


if __name__ == "__main__":
    main()
