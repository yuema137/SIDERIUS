# nodes/ml_hyperparameter_tune_agent.py
"""
tune_ml_hyperparam_agent — Node 1 in the SIDERIUS graph.

Optimizes hyperparameters for a given ML model architecture over N rounds.
Each round: plan (LLM) → resource check → train → infer → score → reflect (LLM).

Node contract:
  run(input: HyperparamTuningInput) -> HyperparamTuningOutput
  CLI: --provider, --model_id, --expert_advice, --max_rounds, --force_model,
       --run_name, --workspace, --file_index, --progress_bar
"""

import os
import gc
import time
import json
import argparse
import importlib
import traceback
from pathlib import Path
from typing import Optional, Union

from pydantic import ValidationError

from core.hardware_context import get_or_create
from core.sandbox_executor import TidmadSandbox
from agent.llm_bridge import LLMBridge
from agent.schemas.hyperparam_tuning import (
    HyperparamTuningInput,
    HyperparamTuningOutput,
    ExperimentRecord,
    ExperimentPlan,
    ExpertAdvice,
    GateExhaustionInfo,
    PhysicalRejection,
    TrialConfig,
    serialize_expert_advice,
)
from execute_tools.sample_set_builder import build_sample_set
from execute_tools.scoring_utils import SampleSet, coerce_nonfinite_to_none
from execute_tools.scoring_helpers import build_score_table
from execute_tools.dataset_config import TIDMAD as DATASET_CONFIG
from execute_tools.build_anchor_map import load_anchor_map
from nodes.scoring_reference import load_reference_scores
from agent.schemas.score_table import ScoreComparisonTable
from agent.skills.evaluate_time_skill import calibration as time_calibration
from agent.utils.architectural_pattern_tagger import (
    TIME_FACTOR_THRESHOLD,
    VRAM_FACTOR_THRESHOLD,
    tag_architecture,
)


def _validate_data_config(
    trial_config: TrialConfig,
    segmentation_size: int,
    dataset_config=DATASET_CONFIG,
) -> None:
    """
    Validate integer relationships between dataset, PSD segments, ML segments,
    and sampling portions. Called in the agent loop where all configs converge.

    Raises:
        ValueError: If any constraint is violated.
    """
    psd = dataset_config.psd_segment_length
    segs_per_file = dataset_config.segments_per_file

    # 1. PSD segment must divide evenly into ML segments
    if psd % segmentation_size != 0:
        valid = sorted([d for d in range(100, psd + 1) if psd % d == 0 and d <= 100_000])
        raise ValueError(
            f"psd_segment_length ({psd}) must be divisible by "
            f"segmentation_size ({segmentation_size}). "
            f"Remainder: {psd % segmentation_size}. "
            f"Valid segmentation_size values: {valid}."
        )

    # 2. trial_portion must produce at least 1 PSD segment per file
    if trial_config.mode != "single_file":
        eval_segs = max(1, round(trial_config.trial_portion * segs_per_file))
        if eval_segs < 1:
            raise ValueError(
                f"trial_portion ({trial_config.trial_portion}) produces 0 segments "
                f"from {segs_per_file} segments per file."
            )

        # 3. train_portion must produce at least 1 PSD segment from the scope
        train_segs = max(1, round(trial_config.train_portion * eval_segs))
        if train_segs < 1:
            raise ValueError(
                f"train_portion ({trial_config.train_portion}) of "
                f"{eval_segs} scope segments produces 0 training segments."
            )


def _apply_mode_override_chain(
    plan: ExperimentPlan,
    *,
    trial_allowed: bool,
    is_formal_round: bool,
    force_formal_round: bool,
) -> ExperimentPlan:
    """Apply the run-level + last-round overrides to ``plan.is_trial``.

    Two independent gates can force ``plan.is_trial = False``:

    * ``trial_allowed=False`` — the run was launched without trial mode
      enabled, so every round runs formal regardless of what the planner
      picked.
    * ``is_formal_round and force_formal_round`` — the last round of every
      iteration normally forces formal so the run produces a
      cross-architecture comparable score. Operators can disable this
      override by passing ``--no-force_formal_round`` for testing /
      debugging where the trial-mode portions need to take effect on the
      final round.

    Mutates ``plan`` in place and returns it for caller-chaining.
    """
    if not trial_allowed:
        plan.is_trial = False
    if is_formal_round and force_formal_round:
        plan.is_trial = False
    return plan


def _resolve_sample_set_cfg(
    mode: str,
    agent_input: HyperparamTuningInput,
    plan: ExperimentPlan,
) -> dict:
    """Resolve sample-set config for one round based on trial/formal/single_file mode.

    Formal-mode eval is LOCKED to snapshot + eval_portion=1.0 so scores are
    architecturally comparable across architectures (Phase M, §12.2). Formal
    training levers come from ``agent_input.formal_*``. Trial-mode values come
    from the planner. Single-file mode uses safe defaults.

    Args:
        mode: One of ``"trial"``, ``"formal"``, ``"single_file"``.
        agent_input: Carries the operator-configurable ``formal_*`` knobs.
        plan: Planner-produced ExperimentPlan (source of trial-mode values).

    Returns:
        A dict with exactly 5 keys — ``trial_strategy``, ``trial_portion``,
        ``train_portion``, ``eval_strategy``, ``eval_portion``.
    """
    if mode == "formal":
        return {
            "trial_strategy": agent_input.formal_strategy,
            "trial_portion":  agent_input.formal_portion,
            "train_portion":  agent_input.formal_train_portion,
            "eval_strategy":  "snapshot",
            "eval_portion":   1.0,
        }
    if mode == "trial":
        return {
            "trial_strategy": plan.trial_strategy,
            "trial_portion":  plan.trial_portion,
            "train_portion":  plan.train_portion,
            "eval_strategy":  plan.eval_strategy,
            "eval_portion":   plan.eval_portion,
        }
    # single_file
    return {
        "trial_strategy": "snapshot",
        "trial_portion":  plan.trial_portion,
        "train_portion":  plan.train_portion,
        "eval_strategy":  "snapshot",
        "eval_portion":   1.0,
    }


def _copy_seed_plugin(src: str, dst_dir: str) -> str:
    """Copy the seed plugin file into the run's plugin directory.

    The schema validator (``HyperparamTuningInput._validate_seed_plugin_path``)
    already checked that ``src`` exists and declares a matching
    ``PLUGIN_MODEL_TYPE`` — this helper just performs the file copy.

    When ``src`` and the destination resolve to the same file, the copy is
    skipped (avoids ``shutil.SameFileError``). Otherwise the destination is
    overwritten — when ``run_name`` is reused, the most recent caller's
    seed wins.

    See docs/run_scoped_plugins.md (Phase 3).
    """
    import shutil
    dst = os.path.join(dst_dir, os.path.basename(src))
    if os.path.abspath(src) == os.path.abspath(dst):
        return dst
    shutil.copy2(src, dst)
    return dst


def _run_skill(skill_folder: str, sandbox: TidmadSandbox, **params) -> dict:
    """
    Dynamically loads and executes a research skill (Training, Inference, or Scoring).
    """
    module_path = f"agent.skills.{skill_folder}.wrapper"
    try:
        skill_module = importlib.import_module(module_path)
        return skill_module.run_skill(sandbox, **params)
    except Exception as e:
        print(f"Skill Error [{skill_folder}]: {str(e)}")
        return {"status": "error", "message": str(e)}


# _serialize_expert_advice is now shared — imported as serialize_expert_advice
_serialize_expert_advice = serialize_expert_advice


# ---------------------------------------------------------------------------
# Gate-exhaustion feedback helper (Phase K.7 — see §10.13)
# ---------------------------------------------------------------------------


def _collect_disallowed_patterns(
    records: list,
    *,
    vram_budget_gb: Optional[float],
    time_budget_minutes: Optional[float],
) -> list:
    """Return the sorted union of architectural-pattern tags for records that
    exceeded the §7 Decision 2 thresholds.

    For each gate-rejected attempt (``status in {"skipped_oom_risk",
    "skipped_time_risk"}``) we compute its individual ``time_factor`` and
    ``vram_factor`` from the per-attempt ``memory`` block. Only attempts that
    overshot by at least ``TIME_FACTOR_THRESHOLD`` (time) or
    ``VRAM_FACTOR_THRESHOLD`` (VRAM) contribute tags — a marginal 1.3× is a
    hyperparameter choice, not an architectural infeasibility, and banning the
    whole class on it would over-constrain the next proposer. See
    ``docs/reliable_resource_proposer.md`` §7 Decision 2 + §9 Commit 3.

    Non-gate failures (code bugs, schema violations) are skipped regardless of
    factor — their failure mode is not resource-structural.

    Returns a deterministic sorted list (empty if no attempt qualifies).
    """
    tags: set = set()
    for r in records:
        if r.get("status") not in {"skipped_oom_risk", "skipped_time_risk"}:
            continue
        mem = r.get("memory") or {}

        vram_factor = None
        if vram_budget_gb and vram_budget_gb > 0:
            vram_est = mem.get("vram_estimate_gb")
            if vram_est is not None:
                vram_factor = float(vram_est) / float(vram_budget_gb)

        time_factor = None
        if time_budget_minutes and time_budget_minutes > 0:
            time_est = mem.get("time_estimate_minutes")
            if time_est is not None:
                time_factor = float(time_est) / float(time_budget_minutes)

        exceeds_time = time_factor is not None and time_factor > TIME_FACTOR_THRESHOLD
        exceeds_vram = vram_factor is not None and vram_factor > VRAM_FACTOR_THRESHOLD
        if not (exceeds_time or exceeds_vram):
            continue

        model_type = r.get("model_type") or ""
        model_config = r.get("model_config") or {}
        tags.update(tag_architecture(model_type, model_config))

    return sorted(tags)


def _build_gate_exhaustion(
    records: list,
    active_mode: str,
    vram_budget_gb: Optional[float],
    time_budget_minutes: Optional[float],
    *,
    consecutive_fail_rounds_at_exit: int = 0,
    max_fail_rounds: int = 0,
    completed_rounds: int = 0,
) -> Optional[GateExhaustionInfo]:
    """
    Build the structured gate-exhaustion report for the next iteration's
    proposer (§10.13). Two triggers can fire:

    **Trigger A (Phase K, §10.13.1)** — *no rounds ever succeeded*. Fires when:

      * ``records`` is non-empty (the tuner actually ran).
      * No record has ``status == "success"``.
      * At least one record has ``status in {"skipped_oom_risk",
        "skipped_time_risk"}`` (failure was budget-related, not a code
        bug or schema violation).

    **Trigger B (Phase L, §11.4)** — *some rounds succeeded then the
    search collapsed*. Fires when:

      * ``consecutive_fail_rounds_at_exit >= max_fail_rounds > 0``
        (the outer loop aborted on the consecutive-failure brake, not
        on ``max_rounds``).
      * ``completed_rounds > 0`` (at least one round succeeded — this
        is the "after K successful rounds" framing that distinguishes
        Trigger B from Trigger A).
      * Burst gate-skip ratio ``>= 0.5`` — the trailing failure burst
        (records whose ``round_index == completed_rounds + 1``) was
        dominated by VRAM/time gate skips, not by code bugs.

    Returns ``None`` if neither trigger fires. When Trigger B fires, the
    report is keyed off the burst records (focused on the round that
    repeatedly failed). When Trigger A fires, the report is keyed off
    the full record list (no successful round to anchor on).
    """
    if not records:
        return None

    def _factor(estimate, budget):
        if estimate is None or budget is None or budget <= 0:
            return None
        return round(float(estimate) / float(budget), 3)

    def _worst_factor(rs, key, budget):
        if budget is None or budget <= 0:
            return None
        ests = [(r.get("memory") or {}).get(key) for r in rs]
        ests = [e for e in ests if e is not None]
        if not ests:
            return None
        return round(max(float(e) for e in ests) / float(budget), 3)

    # --- Trigger B (Phase L) — some successes, then a fail-round burst.
    trigger_b_fired = False
    burst_records: list = []
    if (
        max_fail_rounds > 0
        and consecutive_fail_rounds_at_exit >= max_fail_rounds
        and completed_rounds > 0
    ):
        burst_round_idx = completed_rounds + 1
        burst_records = [
            r for r in records
            if (r.get("memory") or {}).get("round_index") == burst_round_idx
        ]
        if burst_records:
            burst_gate = [
                r for r in burst_records
                if r.get("status") in {"skipped_oom_risk", "skipped_time_risk"}
            ]
            if len(burst_gate) / len(burst_records) >= 0.5:
                trigger_b_fired = True

    # --- Trigger A (Phase K) — no successes at all + budget-gated.
    trigger_a_fired = False
    if not any(r.get("status") == "success" for r in records):
        if any(
            r.get("status") in {"skipped_oom_risk", "skipped_time_risk"}
            for r in records
        ):
            trigger_a_fired = True

    if not (trigger_a_fired or trigger_b_fired):
        return None

    # When Trigger B fires, focus the report on the burst (more
    # actionable for the proposer); otherwise fall back to all records.
    report_records = burst_records if trigger_b_fired else records

    vram_gated = [r for r in report_records if r.get("status") == "skipped_oom_risk"]
    time_gated = [r for r in report_records if r.get("status") == "skipped_time_risk"]
    other = [
        r for r in report_records
        if r.get("status") not in {"skipped_oom_risk", "skipped_time_risk"}
    ]

    baseline_mem = (report_records[0].get("memory") or {})
    baseline_vram = baseline_mem.get("vram_estimate_gb")
    baseline_time = baseline_mem.get("time_estimate_minutes")

    baseline_vram_factor = _factor(baseline_vram, vram_budget_gb)
    baseline_time_factor = _factor(baseline_time, time_budget_minutes)
    worst_vram_factor = _worst_factor(report_records, "vram_estimate_gb", vram_budget_gb)
    worst_time_factor = _worst_factor(report_records, "time_estimate_minutes", time_budget_minutes)

    disallowed_patterns = _collect_disallowed_patterns(
        report_records,
        vram_budget_gb=vram_budget_gb,
        time_budget_minutes=time_budget_minutes,
    )

    if trigger_b_fired:
        summary = _render_gate_exhaustion_trigger_b_summary(
            total=len(report_records),
            vram_gated=len(vram_gated),
            time_gated=len(time_gated),
            other=len(other),
            active_mode=active_mode,
            vram_budget_gb=vram_budget_gb,
            time_budget_minutes=time_budget_minutes,
            baseline_vram=baseline_vram,
            baseline_vram_factor=baseline_vram_factor,
            baseline_time=baseline_time,
            baseline_time_factor=baseline_time_factor,
            worst_vram_factor=worst_vram_factor,
            worst_time_factor=worst_time_factor,
            consecutive_fail_rounds_at_exit=consecutive_fail_rounds_at_exit,
            completed_rounds=completed_rounds,
        )
    else:
        summary = _render_gate_exhaustion_summary(
            total=len(report_records),
            vram_gated=len(vram_gated),
            time_gated=len(time_gated),
            other=len(other),
            active_mode=active_mode,
            vram_budget_gb=vram_budget_gb,
            time_budget_minutes=time_budget_minutes,
            baseline_vram=baseline_vram,
            baseline_vram_factor=baseline_vram_factor,
            baseline_time=baseline_time,
            baseline_time_factor=baseline_time_factor,
            worst_vram_factor=worst_vram_factor,
            worst_time_factor=worst_time_factor,
        )

    return GateExhaustionInfo(
        total_attempts=len(report_records),
        vram_gated_attempts=len(vram_gated),
        time_gated_attempts=len(time_gated),
        other_failure_attempts=len(other),
        active_mode=active_mode,
        vram_budget_gb=vram_budget_gb,
        time_budget_minutes=time_budget_minutes,
        baseline_vram_estimate_gb=baseline_vram,
        baseline_vram_factor=baseline_vram_factor,
        baseline_time_estimate_minutes=baseline_time,
        baseline_time_factor=baseline_time_factor,
        worst_vram_factor=worst_vram_factor,
        worst_time_factor=worst_time_factor,
        summary_message=summary,
        disallowed_architectural_patterns=disallowed_patterns,
    )


def _render_gate_exhaustion_summary(
    *,
    total: int,
    vram_gated: int,
    time_gated: int,
    other: int,
    active_mode: str,
    vram_budget_gb: Optional[float],
    time_budget_minutes: Optional[float],
    baseline_vram: Optional[float],
    baseline_vram_factor: Optional[float],
    baseline_time: Optional[float],
    baseline_time_factor: Optional[float],
    worst_vram_factor: Optional[float],
    worst_time_factor: Optional[float],
) -> str:
    """One-paragraph LLM-readable synthesis of the gate-exhaustion state.

    The wording adapts to which axis was the binding ceiling — VRAM-only,
    time-only, or mixed — so the next proposer reads a clear instruction
    rather than a generic "everything failed" line. See §10.13.3.
    """
    parts = []

    # Lead sentence — what failed and how widely.
    if vram_gated and not time_gated:
        parts.append(
            f"All {total} attempt(s) ({vram_gated} VRAM-gated, {other} other "
            f"failures) were rejected by the pre-flight VRAM gate."
        )
    elif time_gated and not vram_gated:
        parts.append(
            f"All {total} attempt(s) ({time_gated} time-gated, {other} other "
            f"failures) were rejected by the pre-flight time gate."
        )
    else:
        parts.append(
            f"Of {total} attempt(s), {vram_gated} were rejected by the VRAM "
            f"gate and {time_gated} by the time gate "
            f"({other} other failures); none ever trained successfully."
        )

    # VRAM diagnostic.
    if vram_budget_gb is not None and baseline_vram is not None:
        parts.append(
            f"The baseline already estimated {baseline_vram:.2f} GB VRAM vs "
            f"the {vram_budget_gb:.2f} GB {active_mode} budget "
            f"(factor {baseline_vram_factor:.2f}×); the tuner's mutations "
            f"reached factor {worst_vram_factor:.2f}× at worst."
        )
    elif vram_budget_gb is not None and worst_vram_factor is not None:
        parts.append(
            f"VRAM estimates reached factor {worst_vram_factor:.2f}× of the "
            f"{vram_budget_gb:.2f} GB {active_mode} budget at worst "
            f"(baseline estimate not recorded)."
        )

    # Time diagnostic.
    if time_budget_minutes is not None and baseline_time is not None:
        parts.append(
            f"The baseline estimated {baseline_time:.2f} min wall-time vs the "
            f"{time_budget_minutes:.2f} min {active_mode} budget "
            f"(factor {baseline_time_factor:.2f}×); worst was factor "
            f"{worst_time_factor:.2f}×."
        )
    elif time_budget_minutes is not None and worst_time_factor is not None:
        parts.append(
            f"Time estimates reached factor {worst_time_factor:.2f}× of the "
            f"{time_budget_minutes:.2f} min {active_mode} budget at worst "
            f"(baseline estimate not recorded)."
        )

    # Verdict line — point the next proposer at the right lever.
    if vram_gated and not time_gated:
        parts.append(
            "Verdict: the proposed architecture is too heavy for the active "
            "VRAM budget. Reduce parameter count and/or layer count so the "
            "next baseline lands below the budget."
        )
    elif time_gated and not vram_gated:
        parts.append(
            "Verdict: the proposed architecture is too slow for the active "
            "time budget. Reduce model depth/width or computation per step "
            "so the next baseline lands below the budget."
        )
    else:
        parts.append(
            "Verdict: the proposed architecture is over budget on multiple "
            "axes. Both parameter count AND per-step compute must come down."
        )

    return " ".join(parts)


def _render_gate_exhaustion_trigger_b_summary(
    *,
    total: int,
    vram_gated: int,
    time_gated: int,
    other: int,
    active_mode: str,
    vram_budget_gb: Optional[float],
    time_budget_minutes: Optional[float],
    baseline_vram: Optional[float],
    baseline_vram_factor: Optional[float],
    baseline_time: Optional[float],
    baseline_time_factor: Optional[float],
    worst_vram_factor: Optional[float],
    worst_time_factor: Optional[float],
    consecutive_fail_rounds_at_exit: int,
    completed_rounds: int,
) -> str:
    """One-paragraph LLM-readable synthesis for the Phase L Trigger B
    case — the search collapsed into a fail-round burst after some
    successful rounds (§11.4). Lead sentence makes the
    "model too large after K successful rounds" framing explicit so the
    next proposer reduces model size before exploring further.
    """
    # Lead sentence — Trigger B framing per §11.4 spec.
    if vram_gated and not time_gated:
        gated_axis = "VRAM"
    elif time_gated and not vram_gated:
        gated_axis = "time"
    else:
        gated_axis = "VRAM/time"
    parts = [
        f"Model too large — {consecutive_fail_rounds_at_exit} consecutive "
        f"rounds exhausted attempts at the {gated_axis} gate after "
        f"{completed_rounds} successful round(s); proposer should reduce "
        f"model size before the next iteration."
    ]
    parts.append(
        f"Burst breakdown: {total} attempt(s) "
        f"({vram_gated} VRAM-gated, {time_gated} time-gated, "
        f"{other} other failures)."
    )

    # VRAM diagnostic.
    if vram_budget_gb is not None and baseline_vram is not None:
        parts.append(
            f"Burst baseline estimated {baseline_vram:.2f} GB VRAM vs the "
            f"{vram_budget_gb:.2f} GB {active_mode} budget "
            f"(factor {baseline_vram_factor:.2f}×); worst factor in burst "
            f"reached {worst_vram_factor:.2f}×."
        )
    elif vram_budget_gb is not None and worst_vram_factor is not None:
        parts.append(
            f"Burst VRAM estimates reached factor {worst_vram_factor:.2f}× "
            f"of the {vram_budget_gb:.2f} GB {active_mode} budget at worst "
            f"(burst baseline estimate not recorded)."
        )

    # Time diagnostic.
    if time_budget_minutes is not None and baseline_time is not None:
        parts.append(
            f"Burst baseline estimated {baseline_time:.2f} min wall-time vs "
            f"the {time_budget_minutes:.2f} min {active_mode} budget "
            f"(factor {baseline_time_factor:.2f}×); worst factor in burst "
            f"reached {worst_time_factor:.2f}×."
        )
    elif time_budget_minutes is not None and worst_time_factor is not None:
        parts.append(
            f"Burst time estimates reached factor {worst_time_factor:.2f}× "
            f"of the {time_budget_minutes:.2f} min {active_mode} budget at "
            f"worst (burst baseline estimate not recorded)."
        )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Node implementation
# ---------------------------------------------------------------------------

class HyperparamTuningAgent:
    """
    Hyperparameter tuning agent — optimizes model configs over N rounds.

    Each round: plan (LLM) → resource check → train → infer → score → reflect (LLM).
    OOM-risk configs are skipped but saved to memory. A hard cap of max_rounds * 3
    total attempts prevents infinite loops.

    Constructor dependency injection (see ``docs/pseudo_test_infra.md`` §4A):
      * ``bridge_factory``: callable that constructs an ``LLMBridge``-compatible
        object. Defaults to the real ``LLMBridge`` class. In pseudo-mode tests,
        the ``tuner_factories`` fixture passes a factory that returns a
        ``RecordingLLMBridge`` pre-loaded with canned responses.
      * ``sandbox_factory``: callable that constructs a ``TidmadSandbox``-
        compatible object. Defaults to the real ``TidmadSandbox``. In
        pseudo-mode tests, the fixture passes a factory that returns a
        ``RecordingSandbox`` pre-loaded with canned subprocess results.

    Production code never passes these — the defaults are the real classes,
    so the existing call ``HyperparamTuningAgent().run(input)`` continues to
    work identically. Only tests inject the fakes.
    """

    def __init__(self, bridge_factory=None, sandbox_factory=None):
        self._bridge_factory = bridge_factory or LLMBridge
        self._sandbox_factory = sandbox_factory or TidmadSandbox

    def run(self, agent_input: HyperparamTuningInput) -> HyperparamTuningOutput:
        """
        Execute the hyperparameter tuning loop.

        Args:
            agent_input: Validated HyperparamTuningInput with model_type, max_rounds,
                         expert_advice, storage config, and LLM config.

        Returns:
            HyperparamTuningOutput with status, best score, best config, and all records.
        """
        # --- Validate input ---
        agent_input = HyperparamTuningInput.model_validate(agent_input)

        # --- Extract frequently used fields ---
        workspace = agent_input.storage.local.workspace
        run_name = agent_input.storage.local.run_name

        # Per-run hardware manifest (Phase 6.6 §3.9) — file IPC with sandbox children.
        hardware_context = get_or_create(Path(workspace), run_name)
        print(
            f"[Tuner] Hardware context: {hardware_context.device_name} "
            f"| total={hardware_context.total_memory_gb:.1f} GB "
            f"| cap={hardware_context.usable_cap_gb:.1f} GB "
            f"| host={hardware_context.hostname} "
            f"| available={hardware_context.device_available}"
        )

        model_type_setting = agent_input.model_type
        max_rounds = agent_input.max_rounds
        file_index = agent_input.file_index
        trial_allowed = agent_input.is_trial
        expert_advice_str = _serialize_expert_advice(agent_input.expert_advice)
        if agent_input.human_advice:
            human_section = f"\n[Human Guidance (high priority)]:\n{agent_input.human_advice}"
            expert_advice_str = (expert_advice_str + human_section) if expert_advice_str else agent_input.human_advice

        print(f"Input validated: model={model_type_setting} | rounds={max_rounds} "
              f"| file_index={file_index} | trial_allowed={trial_allowed} "
              f"| provider={agent_input.llm_provider}")

        # Per-mode time-budget gate (Phase I). Each mode has its own optional
        # ceiling; the per-round pick happens inside the loop based on
        # plan.is_trial. Mirrors the "additive, opt-in" stance in
        # docs/resource_estimator_implement.md §5 — when both budgets are None the
        # gate never fires; when only one is set, rounds in the other mode skip
        # the gate (one-time warning printed below per mode).
        trial_time_budget = agent_input.trial_time_budget_minutes
        formal_time_budget = agent_input.formal_time_budget_minutes
        time_data_dir = agent_input.data_dir
        if trial_time_budget is None:
            print("[time-gate disabled / trial] trial_time_budget_minutes is None "
                  "— evaluate_time_skill will not gate trial-mode rounds.")
        if formal_time_budget is None:
            print("[time-gate disabled / formal] formal_time_budget_minutes is None "
                  "— evaluate_time_skill will not gate formal-mode rounds.")

        # Per-mode VRAM-budget gate (Phase K). Mirrors the time-gate shape: each
        # mode has its own optional ceiling, per-round pick happens inside the
        # loop based on plan.is_trial. When the mode's budget is None, the VRAM
        # skill falls back to the defensive free×0.8 behaviour (no operator
        # ceiling) — the skill still runs, but the vram_*_gb memory fields are
        # omitted so the planner sees "this round wasn't operator-budgeted."
        # See docs/resource_estimator_implement.md §10.4 / §10.8.
        trial_vram_budget = agent_input.trial_vram_budget_gb
        formal_vram_budget = agent_input.formal_vram_budget_gb
        if trial_vram_budget is None:
            print("[vram-gate disabled / trial] trial_vram_budget_gb is None "
                  "— evaluate_vram_skill uses free×0.8 defensive limit for "
                  "trial-mode rounds.")
        if formal_vram_budget is None:
            print("[vram-gate disabled / formal] formal_vram_budget_gb is None "
                  "— evaluate_vram_skill uses free×0.8 defensive limit for "
                  "formal-mode rounds.")

        # --- Initialize sandbox and brain (via factory for DI / pseudo-mode) ---
        sandbox = self._sandbox_factory(
            metadata_source="local",
            run_name=run_name,
            workspace=workspace,
            progress_bar=agent_input.progress_bar,
            file_index=file_index,
        )

        # Seed plugin copy — docs/run_scoped_plugins.md (Phase 3). Validation
        # (file exists + PLUGIN_MODEL_TYPE matches model_type) already ran in
        # HyperparamTuningInput; here we just stage the file in the run's
        # plugin dir so the training subprocess picks it up via
        # SIDERIUS_PLUGIN_DIRS.
        if agent_input.seed_plugin_path:
            copied = _copy_seed_plugin(agent_input.seed_plugin_path, sandbox.plugin_dir)
            print(f"[Tuner] Seed plugin staged: {os.path.basename(copied)} -> {sandbox.plugin_dir}")

        brain = self._bridge_factory(
            provider=agent_input.llm_provider,
            model_id=agent_input.llm_model_id,
            reflect_provider=agent_input.reflect_provider,
            reflect_model_id=agent_input.reflect_model_id,
            max_retries=agent_input.max_retries,
        )

        # --- Pre-load anchor map if any round might use trial mode ---
        anchor_map_data: Optional[dict] = None
        if trial_allowed:
            anchor_map_path = os.path.join(
                sandbox.dirs["data"], "segment_anchors.json"
            )
            if os.path.exists(anchor_map_path):
                anchor_map_data = load_anchor_map(anchor_map_path)
            else:
                raise FileNotFoundError(
                    f"Trial mode requires segment_anchors.json at {anchor_map_path}. "
                    "Run execute_tools/build_anchor_map.py first."
                )
            print(f"Trial mode enabled: anchor map loaded.")

        # Pre-load reference scores (raw_baseline + ground_truth per-file
        # logs, linear_sums, n_segments, and full-20 scalars). One disk
        # read per run — cached at module level after the first call.
        # Used every round to build the per-file score-comparison table
        # attached to each ExperimentRecord and substituted into the
        # tuner/reflector/interp/proposer prompts.
        # See docs/aggregated_score_table_awareness.md §7.1.
        reference_scores = load_reference_scores()
        print(
            f"Reference scores loaded: s_max={reference_scores.s_max:.4e}, "
            f"raw_scalar_full={reference_scores.raw_scalar_full:.4f}, "
            f"gt_scalar_full={reference_scores.gt_scalar_full:.4f}."
        )

        # Save run configuration once
        started_at = time.strftime("%Y-%m-%d %H:%M:%S")
        run_config = {
            "provider":       agent_input.llm_provider,
            "model_id":       agent_input.llm_model_id,
            "run_name":       run_name,
            "force_model":    model_type_setting,
            "max_rounds":     max_rounds,
            "file_index":     file_index,
            "trial_allowed":  trial_allowed,
            "started_at":     started_at,
        }
        run_config_path = os.path.join(workspace, f"run_config_{run_name}.json")
        with open(run_config_path, "w", encoding="utf-8") as f:
            json.dump(run_config, f, indent=4)

        print(f"=== TIDMAD Agent Activated ===")
        print(f"Provider: {agent_input.llm_provider} | Model: {agent_input.llm_model_id}")
        print(f"Expert Advice: {expert_advice_str}")
        print(f"Max Rounds: {max_rounds} | Strategy: {model_type_setting}")

        # --- Get the config manual before starting ---
        print(f"Reading model configuration manual...")
        config_manual = _run_skill("check_config_format_skill", sandbox)
        if config_manual["status"] == "success":
            config_manual_data = config_manual["data"]
        else:
            raise ValueError("Config Manual not provided.")

        # --- Load model description (architecture explanation for the LLM) ---
        model_description = None
        try:
            from ml_models.model_descriptions import get_model_description
            model_description = get_model_description(model_type_setting)
            print(f"Loaded model description for '{model_type_setting}' ({len(model_description)} chars)")
        except (FileNotFoundError, Exception) as e:
            print(f"No model description found for '{model_type_setting}': {e}")

        # --- Autonomous Research Loop ---
        # Phase L (§11) — success-counted outer loop with per-round inner
        # attempt budget. Pre-Phase-L the tuner used a single shared
        # ``max_rounds * 3`` attempt pool and counted both successes and
        # failures against ``max_rounds``; that meant a few unlucky rounds
        # could exhaust the pool before any formal round ever ran. Phase L
        # gives each round its own budget (``attempts_per_round`` for
        # trial rounds, ``attempts_per_formal_round`` for the formal
        # round) and only increments ``completed_rounds`` on success.
        # ``consecutive_fails`` aborts the iteration after
        # ``max_fail_rounds`` rounds in a row exhaust their inner budget.
        completed_rounds = 0
        total_attempts = 0
        consecutive_fails = 0
        # Phase 6.6 WS-B B.3 — per-attempt VRAM-gate rejection buffer.
        # Appended to on every evaluate_vram_skill feasible=False event.
        # Flushed to HyperparamTuningOutput.physical_rejections at run exit.
        # See docs/phase66_ws_b_proposer_hardening.md §2.3 / §2.4.
        physical_rejections_buffer: list[PhysicalRejection] = []
        attempts_per_round_setting = agent_input.attempts_per_round
        attempts_per_formal_round_setting = agent_input.attempts_per_formal_round
        max_fail_rounds_setting = agent_input.max_fail_rounds
        # Pre-initialise so finalisation can safely read `plan` for the
        # gate-exhaustion mode lookup even if the loop never assigns it
        # (e.g. max_rounds=0 or an early-exit path).
        plan: Optional[ExperimentPlan] = None

        while completed_rounds < max_rounds and consecutive_fails < max_fail_rounds_setting:
            round_index = completed_rounds + 1
            is_formal_round = (completed_rounds == max_rounds - 1)
            N = attempts_per_formal_round_setting if is_formal_round else attempts_per_round_setting
            round_succeeded = False

            for attempt_in_round in range(1, N + 1):
                total_attempts += 1
                iteration = round_index  # legacy alias for prints + brain.plan(current_round=...)
                try:
                    print(f"\n\n{'='*60}\nROUND {iteration}/{max_rounds} "
                          f"(attempt {attempt_in_round}/{N}, total {total_attempts}): "
                          f"Planning...\n{'='*60}")
    
                    # A. OBSERVE: Retrieve full Research Memory from summary.json
                    memory_history = sandbox.get_summary()
    
                    # Build exploration checklist from config schema + past records
                    from agent.prompts import (
                        build_exploration_checklist,
                        format_plugin_source_excerpt_block,
                    )
                    from ml_models.models_format_sandbox import get_config_class
                    config_cls = get_config_class(model_type_setting)
                    config_schema = config_cls.model_json_schema() if config_cls else {}
                    checklist = build_exploration_checklist(
                        config_schema=config_schema,
                        memory_history=memory_history,
                    )
                    # Phase D.1 — surface the raw config class source (validator
                    # bodies included) so the planner sees cross-field invariants
                    # that ``model_json_schema()`` drops. See
                    # docs/improving_validation_awareness.md §D.1.
                    plugin_source_excerpt = format_plugin_source_excerpt_block(config_cls)
    
                    # Phase K (K.6) — extract the most recent prior attempt's
                    # resource snapshot so the [ACTIVE RESOURCE BUDGETS] block can
                    # show the LLM a concrete number to react to. Looks at the
                    # last memory entry regardless of status (success / skipped):
                    # the resource fields are absent on records produced with the
                    # gates disabled and on schema-violation records. Round 1
                    # gives None on every field, which collapses to "(no prior
                    # estimate)" in the rendered block.
                    # See docs/resource_estimator_implement.md §10.3 / §10.11.
                    last_record = memory_history[-1] if memory_history else {}
                    last_memory = last_record.get("memory") or {}
                    last_train_cfg = (
                        (last_record.get("params") or {}).get("train_config") or {}
                    )
                    last_vram_estimate_gb = last_memory.get("vram_estimate_gb")
                    last_time_estimate_minutes = last_memory.get("time_estimate_minutes")
                    last_batch_size = last_train_cfg.get("batch_size")
                    last_mode = last_memory.get("time_mode")

                    # Pick the best-so-far score_table for the planner-prompt
                    # {SCORE_COMPARISON_TABLE} substitution. Filter to
                    # successful records with a populated score_table dict,
                    # then max by denoising_score. Empty history or no
                    # populated score_table → None, which the bridge replaces
                    # with the "no prior round yet" fallback. See
                    # docs/aggregated_score_table_awareness.md §9.1.
                    best_score_table_md: Optional[str] = None
                    _records_with_table = [
                        r for r in memory_history
                        if r.get("status") == "success"
                        and r.get("denoising_score") is not None
                        and isinstance(r.get("score_table"), dict)
                        and r["score_table"].get("rendered_markdown")
                    ]
                    if _records_with_table:
                        _best_rec = max(
                            _records_with_table,
                            key=lambda r: r["denoising_score"],
                        )
                        best_score_table_md = _best_rec["score_table"]["rendered_markdown"]

                    # B. THINK: Plan next experiment
                    decision = brain.plan(
                        memory_history,
                        expert_advice=expert_advice_str,
                        force_model=model_type_setting,
                        config_manual=config_manual_data,
                        model_description=model_description,
                        exploration_checklist=checklist,
                        plugin_source_excerpt=plugin_source_excerpt,
                        current_round=iteration,
                        max_rounds=max_rounds,
                        trial_allowed=trial_allowed,
                        force_formal_round=agent_input.force_formal_round,
                        plan_overrides=agent_input.plan_overrides,
                        max_epochs=agent_input.max_epochs,
                        trial_vram_budget_gb=trial_vram_budget,
                        formal_vram_budget_gb=formal_vram_budget,
                        trial_time_budget_minutes=trial_time_budget,
                        formal_time_budget_minutes=formal_time_budget,
                        last_vram_estimate_gb=last_vram_estimate_gb,
                        last_time_estimate_minutes=last_time_estimate_minutes,
                        last_batch_size=last_batch_size,
                        last_mode=last_mode,
                        score_table_md=best_score_table_md,
                    )
    
                    # Validate LLM output into ExperimentPlan (with fallback)
                    plan = ExperimentPlan.with_defaults(decision)
    
                    # Apply hard overrides from operator config (before other overrides).
                    # Unknown keys are warned and skipped; invalid values are warned
                    # and skipped — the run continues with the LLM's original value.
                    if agent_input.plan_overrides:
                        valid_fields = set(ExperimentPlan.model_fields.keys())
                        unknown = set(agent_input.plan_overrides) - valid_fields
                        if unknown:
                            print(f"  [WARN] plan_overrides: ignoring unknown keys: {unknown}")
                        safe_overrides = {k: v for k, v in agent_input.plan_overrides.items() if k in valid_fields}
                        if safe_overrides:
                            try:
                                merged = plan.model_dump(by_alias=True) | safe_overrides
                                plan = ExperimentPlan.model_validate(merged)
                                print(f"  Plan overrides applied: {list(safe_overrides.keys())}")
                            except Exception as e:
                                print(f"  [WARN] plan_overrides validation failed ({e}); "
                                      f"using LLM plan as-is")
    
                    # Override chain: trial-allowed lockout + last-round override.
                    # See _apply_mode_override_chain for semantics.
                    plan = _apply_mode_override_chain(
                        plan,
                        trial_allowed=trial_allowed,
                        is_formal_round=is_formal_round,
                        force_formal_round=agent_input.force_formal_round,
                    )
    
                    # Enforce max_epochs hard cap (prevents LLM from choosing excessively long training)
                    if agent_input.max_epochs is not None:
                        planned_epochs = plan.train_cfg.get("epochs", 1)
                        if planned_epochs > agent_input.max_epochs:
                            print(f"  Clamping epochs: {planned_epochs} → {agent_input.max_epochs} (max_epochs)")
                            plan.train_cfg["epochs"] = agent_input.max_epochs
    
                    # Build and validate TrialConfig from plan + overrides
                    if plan.is_trial:
                        mode = "trial"
                    elif trial_allowed:
                        mode = "formal"
                    else:
                        mode = "single_file"
    
                    # Phase M — mode-gated sample-set config. Formal-mode eval is
                    # LOCKED to snapshot + 1.0 so scores are architecturally
                    # comparable; formal training is operator-configurable via
                    # agent_input.formal_* fields. See docs/resource_estimator_implement.md §12.
                    _cfg = _resolve_sample_set_cfg(mode, agent_input, plan)
                    cfg_trial_strategy = _cfg["trial_strategy"]
                    cfg_trial_portion  = _cfg["trial_portion"]
                    cfg_train_portion  = _cfg["train_portion"]
                    cfg_eval_strategy  = _cfg["eval_strategy"]
                    cfg_eval_portion   = _cfg["eval_portion"]
    
                    # Generate deterministic seeds for reproducibility.
                    import hashlib
                    seed_input = f"{run_name}_{total_attempts}".encode()
                    seed_hash = int(hashlib.sha256(seed_input).hexdigest(), 16)
                    train_sampling_seed = agent_input.sampling_seed if agent_input.sampling_seed is not None else seed_hash % (2**31)
                    train_base_seed = agent_input.train_base_seed if agent_input.train_base_seed is not None else (seed_hash >> 31) % (2**31)
                    # Eval seed: same as train when aligned, different otherwise
                    if plan.train_validation_align:
                        eval_sampling_seed = train_sampling_seed
                    else:
                        eval_sampling_seed = (seed_hash >> 62) % (2**31)
    
                    trial_config = TrialConfig(
                        is_trial=plan.is_trial,
                        mode=mode,
                        # Training
                        trial_strategy=cfg_trial_strategy,
                        trial_portion=cfg_trial_portion,
                        train_portion=cfg_train_portion,
                        target_files=plan.target_files if plan.is_trial else [],
                        # Validation
                        eval_strategy=cfg_eval_strategy,
                        eval_portion=cfg_eval_portion,
                        # Alignment
                        train_validation_align=plan.train_validation_align,
                        # Legacy
                        file_index=file_index if mode == "single_file" else None,
                        # Seeds
                        train_sampling_seed=train_sampling_seed,
                        eval_sampling_seed=eval_sampling_seed,
                        train_base_seed=train_base_seed,
                    )
    
                    # Validate integer relationships between dataset, PSD, ML segments
                    _validate_data_config(trial_config, plan.model_cfg.get("segmentation_size", 10000))
    
                    # Build TWO independent SampleSets — training and validation
                    if trial_config.mode in ("trial", "formal"):
                        train_sample_set = build_sample_set(
                            is_trial=True,
                            trial_strategy=trial_config.trial_strategy,
                            trial_portion=trial_config.trial_portion,
                            target_files=trial_config.target_files or None,
                            seed=trial_config.train_sampling_seed,
                        )
                        eval_sample_set = build_sample_set(
                            is_trial=True,
                            trial_strategy=trial_config.eval_strategy,
                            trial_portion=trial_config.eval_portion,
                            target_files=trial_config.target_files or None,
                            seed=trial_config.eval_sampling_seed,
                        )
                        print(f"  {trial_config.mode.capitalize()} mode: "
                              f"train: {trial_config.trial_strategy} portion={trial_config.trial_portion} "
                              f"| eval: {trial_config.eval_strategy} portion={trial_config.eval_portion} "
                              f"| train_portion/epoch={trial_config.train_portion} "
                              f"| align={trial_config.train_validation_align}")
                    else:
                        train_sample_set = None
                        eval_sample_set = None
                        print(f"  Legacy mode: file_index={file_index}")
    
                    # Segment counts for records and reflector context
                    if train_sample_set:
                        train_psd_segments = sum(len(v) for v in train_sample_set.values())
                    else:
                        train_psd_segments = DATASET_CONFIG.segments_per_file  # legacy single-file
    
                    if eval_sample_set:
                        eval_psd_segments = sum(len(v) for v in eval_sample_set.values())
                    else:
                        eval_psd_segments = DATASET_CONFIG.segments_per_file  # legacy single-file
    
                    # When force_model is set, override the LLM's model_type choice.
                    if model_type_setting != "auto":
                        model_type = model_type_setting
                    else:
                        model_type = plan.model_type
                    exp_id = f"{model_type}_{run_name}_{total_attempts:03d}"
                    hypothesis = plan.hypothesis
    
                    print(f"Action: {model_type.upper()} | ID: {exp_id}")
                    print(f"Hypothesis: {hypothesis}")
                    print(f"Reasoning: {plan.reasoning or 'No reasoning provided.'}")
    
                    # Save validated TrialConfig
                    trial_config_path = os.path.join(
                        sandbox.dirs["configs"], f"trial_config_{exp_id}.json"
                    )
                    with open(trial_config_path, "w", encoding="utf-8") as f:
                        json.dump(trial_config.model_dump(), f, indent=2)
    
                    # C. ACT: Execute the Atomic Skill Pipeline (Train -> Inf -> Score)
                    model_config = plan.model_cfg.copy()
                    # Ensure model_config.model_type matches the forced model type
                    model_config["model_type"] = model_type
                    active_params = {
                        "exp_id":            exp_id,
                        "run_name":          run_name,
                        "model_type":        model_type,
                        "model_config":      model_config,
                        "train_config":      plan.train_cfg,
                        "loss_config":       plan.loss_cfg,
                        "sample_set":        train_sample_set,    # training data (from training files)
                        "train_portion":     trial_config.train_portion,
                        "train_base_seed":   trial_config.train_base_seed,
                        "eval_sample_set":   eval_sample_set,     # validation data (from validation files)
                    }
    
                    # Clean params for records — exclude bulky SampleSet dicts
                    record_params = {
                        "exp_id":       exp_id,
                        "run_name":     run_name,
                        "model_type":   model_type,
                        "model_config": model_config,
                        "train_config": plan.train_cfg,
                        "loss_config":  plan.loss_cfg,
                    }
    
                    # Phase K: per-mode VRAM-budget pick. plan.is_trial decides
                    # which ceiling applies for THIS round; the unselected one is
                    # ignored. When the chosen budget is None the skill still runs
                    # but falls back to free×0.8 defensive behaviour (no operator
                    # ceiling) — the memory's vram_*_gb fields are omitted in that
                    # case so the planner sees "this round wasn't operator-budgeted."
                    # See docs/resource_estimator_implement.md §10.4 / §10.8.
                    chosen_vram_budget = (trial_vram_budget
                                          if plan.is_trial
                                          else formal_vram_budget)
                    vram_budget_desc = (f"{chosen_vram_budget} GB"
                                        if chosen_vram_budget is not None
                                        else "free×0.8")
                    print(f"\n[Pre-flight 1/2] VRAM check "
                          f"(mode={'trial' if plan.is_trial else 'formal'}, "
                          f"budget={vram_budget_desc})...")
                    # Phase 6.6 A.11 — pass the per-run hardware manifest (from
                    # A.1.6's get_or_create) into the skill so the cap is
                    # physically correct and consistent across the whole run.
                    resource_check = _run_skill(
                        "evaluate_vram_skill",
                        sandbox,
                        **active_params,
                        vram_budget_gb=chosen_vram_budget,
                        hardware_context=hardware_context,
                    )
                    if resource_check.get("status") == "error":
                        raise RuntimeError(f"Resource check error: {resource_check.get('message')}")
    
                    # Phase D.4 — constraint-aware retry. The wrapper returns
                    # ``status="schema_violation"`` when the plugin's
                    # ``PLUGIN_CONFIG_CLASS(**model_cfg)`` call raised a
                    # ``ValidationError``. This typically happens when the tuner
                    # planner proposes a config that violates a cross-field
                    # invariant (e.g. U-Net non-decreasing channels) that
                    # ``model_json_schema()`` cannot represent. Save a
                    # ``skipped_schema_violation`` record so the violating
                    # fields/values surface in next round's ``memory_history``;
                    # the attempt does NOT count as a completed round.
                    # See docs/improving_validation_awareness.md §D.4.
                    if resource_check.get("status") == "schema_violation":
                        violations = resource_check.get("violations", [])
                        offending = resource_check.get("offending_config", {})
                        violating_fields = ", ".join(v.get("loc", "?") for v in violations) or "unknown"
                        print(f"Schema violation — this attempt does NOT count as a round.")
                        print(f"   Violating fields : {violating_fields}")
                        for v in violations:
                            print(f"   - {v.get('loc')} ({v.get('type')}): {v.get('msg')}")
    
                        violation_summary = "; ".join(
                            f"{v.get('loc')}={v.get('input')!r} → {v.get('msg')}"
                            for v in violations
                        ) or "unspecified schema violation"
                        schema_record = {
                            "exp_id":          exp_id,
                            "status":          "skipped_schema_violation",
                            "model_type":      model_type,
                            "timestamp":       time.strftime("%Y-%m-%d %H:%M:%S"),
                            "file_index":      file_index,
                            "params":          record_params,
                            "denoising_score": None,
                            "memory": {
                                "expert_advice_followed": expert_advice_str,
                                "hypothesis":    hypothesis,
                                "conclusion":    (
                                    f"Skipped: plugin schema rejected the proposed model_config. "
                                    f"Violating fields: {violating_fields}. "
                                    f"Offending values: {offending}."
                                ),
                                "discovery":     resource_check.get("verdict", ""),
                                "memory_update": (
                                    f"DO NOT repeat this exact combination — plugin schema requires: "
                                    f"{violation_summary}. Propose a config that satisfies every "
                                    f"@model_validator(mode='after') and per-field bound in the "
                                    f"plugin's PLUGIN_CONFIG_CLASS."
                                ),
                            },
                        }
                        schema_record["memory"]["round_index"] = round_index
                        schema_record["memory"]["attempt_in_round"] = attempt_in_round
                        ExperimentRecord.model_validate(schema_record)
                        sandbox.save_record(schema_record)
                        continue
    
                    if not resource_check.get("feasible", True):
                        print(f"Resource check FAILED — this attempt does NOT count as a round.")
                        print(f"   Verdict   : {resource_check.get('verdict', '')}")
                        print(f"   Suggestion: {resource_check.get('suggestion', '')}")

                        # Phase 6.6 WS-B B.3 Hop 2 — capture this rejection
                        # into the per-run buffer so the orchestrator can
                        # aggregate and feed it back to the next Proposer
                        # iteration as a [PHYSICAL REJECTION] string.
                        # See docs/phase66_ws_b_proposer_hardening.md §2.3.
                        _killer = resource_check.get("memory_killer") or {}
                        _binding = _killer.get("binding_cap", "vram")
                        _dom_bytes = _killer.get("dominant_layer_bytes") or 0
                        _attempt_snapshot = {
                            "model_type":        model_type,
                            "batch_size":        active_params.get("batch_size"),
                            "segmentation_size": active_params.get("segmentation_size"),
                        }
                        # Include architecture knobs if present — the Proposer
                        # reads these to see which dimension overshot.
                        for _k in ("depth", "width", "hidden_dim", "n_heads",
                                   "d_model", "kernel_size", "num_layers"):
                            if _k in active_params:
                                _attempt_snapshot[_k] = active_params[_k]
                        try:
                            physical_rejections_buffer.append(
                                PhysicalRejection(
                                    attempt_config=_attempt_snapshot,
                                    binding_cap=_binding,
                                    dominant_layer=_killer.get("dominant_layer") or "",
                                    dominant_layer_gb=round(
                                        _dom_bytes / (1024 ** 3), 4
                                    ),
                                    dominant_fraction=_killer.get("dominant_fraction") or 0.0,
                                    budget_gb=float(resource_check.get("limit_gb") or 0.0),
                                    estimated_gb=float(resource_check.get("estimated_gb") or 0.0),
                                    suggestion=resource_check.get("suggestion", ""),
                                )
                            )
                        except ValidationError as _rej_err:
                            # Never let a malformed rejection abort the run;
                            # log and continue. The feedback-loop contract is
                            # best-effort — the scored path must survive even
                            # if the rejection-capture payload is malformed.
                            print(f"   [B.3] PhysicalRejection capture skipped: {_rej_err}")

                        oom_record = {
                            "exp_id":          exp_id,
                            "status":          "skipped_oom_risk",
                            "model_type":      model_type,
                            "timestamp":       time.strftime("%Y-%m-%d %H:%M:%S"),
                            "file_index":      file_index,
                            "params":          record_params,
                            "denoising_score": None,
                            "memory": {
                                "expert_advice_followed": expert_advice_str,
                                "hypothesis":    hypothesis,
                                "conclusion":    (
                                    f"Skipped: estimated VRAM ({resource_check.get('estimated_gb', '?')} GB) "
                                    f"exceeds 80% safety limit ({resource_check.get('limit_gb', '?')} GB)."
                                ),
                                "discovery":     resource_check.get("verdict", ""),
                                "memory_update": resource_check.get("suggestion", "Reduce batch_size or segmentation_size."),
                            },
                        }
                        # Phase K — surface the same two VRAM fields the success
                        # record carries so the planner sees the same shape
                        # regardless of pass/fail. Omitted when the gate is
                        # disabled (chosen_vram_budget is None), mirroring §J.3
                        # for time. Mode is inferred from `time_mode` on records
                        # where the time gate also ran — no separate vram_mode.
                        # See docs/resource_estimator_implement.md §10.4 / §10.8.
                        if chosen_vram_budget is not None:
                            oom_record["memory"]["vram_estimate_gb"] = (
                                resource_check.get("estimated_gb")
                            )
                            oom_record["memory"]["vram_budget_gb"] = (
                                resource_check.get("limit_gb")
                            )
                        # K.2.5-8 — soft-fallback flag is independent of the
                        # budget being set; the gate runs unconditionally and the
                        # flag tells us whether the inference estimate was
                        # against a registered batch. Recorded on every
                        # skipped_oom_risk so post-hoc analysis can discount
                        # rejections that came from an uncalibrated estimate.
                        if resource_check.get("inference_batch_uncalibrated"):
                            oom_record["memory"]["inference_batch_uncalibrated"] = True
                        oom_record["memory"]["round_index"] = round_index
                        oom_record["memory"]["attempt_in_round"] = attempt_in_round
                        ExperimentRecord.model_validate(oom_record)
                        sandbox.save_record(oom_record)
                        continue

                    # Phase 6.6 A.11 — capture the batch the VRAM skill picked
                    # and propagate it through the rest of the attempt. Lands in
                    # active_params (so _run_skill("inference_skill", ...) forwards
                    # it to sandbox.execute_inference) and record_params (so the
                    # saved record reflects what actually ran, not the legacy
                    # registry default). ``inference_batch`` is always present on
                    # a feasible resource_check; fall back to None (executor's
                    # back-compat path) if the wrapper somehow omits it.
                    chosen_inference_batch = resource_check.get("inference_batch")
                    active_params["inference_batch"] = chosen_inference_batch
                    record_params["inference_batch"] = chosen_inference_batch

                    # [Pre-flight 2/2] Wall-time gate. Mirrors the VRAM gate above:
                    # error → raise; infeasible → emit skipped_time_risk record
                    # and continue without consuming a round. Skipped entirely
                    # when the budget for the active mode is None (one-time
                    # warning per mode printed at startup).
                    # See docs/resource_estimator_implement.md §2.7 / E1 / Phase I.
                    # The result is stashed so the post-flight calibration update
                    # (Phase F) can compare warmup vs actual ms/step.
                    # Phase I: per-mode budget pick. plan.is_trial decides which
                    # ceiling applies for THIS round; the unselected one is
                    # ignored. The skill itself stays mode-agnostic — it gets a
                    # single time_budget_minutes kwarg.
                    chosen_time_budget = (trial_time_budget
                                          if plan.is_trial
                                          else formal_time_budget)
                    time_check = None
                    if chosen_time_budget is not None:
                        print(f"\n[Pre-flight 2/2] Time check "
                              f"(mode={'trial' if plan.is_trial else 'formal'}, "
                              f"budget={chosen_time_budget} min)...")
                        time_check = _run_skill(
                            "evaluate_time_skill",
                            sandbox,
                            **active_params,
                            time_budget_minutes=chosen_time_budget,
                            data_dir=time_data_dir,
                        )
                        if time_check.get("status") == "error":
                            raise RuntimeError(
                                f"Time check error: {time_check.get('message')}"
                            )
    
                        if not time_check.get("feasible", True):
                            print(f"Time check FAILED — this attempt does NOT count as a round.")
                            print(f"   Verdict   : {time_check.get('verdict', '')}")
                            print(f"   Suggestion: {time_check.get('suggestion', '')}")
    
                            time_record = {
                                "exp_id":          exp_id,
                                "status":          "skipped_time_risk",
                                "model_type":      model_type,
                                "timestamp":       time.strftime("%Y-%m-%d %H:%M:%S"),
                                "file_index":      file_index,
                                "params":          record_params,
                                "denoising_score": None,
                                "memory": {
                                    "expert_advice_followed": expert_advice_str,
                                    "hypothesis":    hypothesis,
                                    "conclusion":    (
                                        f"Skipped: estimated wall-time "
                                        f"({time_check.get('estimated_minutes', '?')} min) "
                                        f"exceeds budget ({time_check.get('limit_minutes', '?')} min)."
                                    ),
                                    "discovery":     time_check.get("verdict", ""),
                                    "memory_update": time_check.get(
                                        "suggestion",
                                        "Reduce model size, batch_size, segmentation_size, or train_portion.",
                                    ),
                                    # Phase J — same three fields the success
                                    # record carries, so the planner sees the
                                    # same shape regardless of pass/fail.
                                    # See docs/resource_estimator_implement.md §J.3.
                                    "time_estimate_minutes": time_check.get("estimated_minutes"),
                                    "time_budget_minutes":   time_check.get("limit_minutes"),
                                    "time_mode":             "trial" if plan.is_trial else "formal",
                                },
                            }
                            # K.2.5-8 — propagate inference soft-fallback flag.
                            # Either gate's result carries the same flag (both
                            # call the same inference estimator); the time
                            # wrapper's flag is the natural source here.
                            if time_check.get("inference_batch_uncalibrated"):
                                time_record["memory"]["inference_batch_uncalibrated"] = True
                            time_record["memory"]["round_index"] = round_index
                            time_record["memory"]["attempt_in_round"] = attempt_in_round
                            ExperimentRecord.model_validate(time_record)
                            sandbox.save_record(time_record)
                            continue
    
                    print(f"\n[Step 1/3] Training...")
                    t0 = time.time()
                    train_status = _run_skill("training_skill", sandbox, **active_params)
                    train_time = round(time.time() - t0, 1)
                    if train_status.get("status") == "error":
                        error_msg = train_status.get("message", "Unknown training error")
                        is_oom = "CUDA out of memory" in error_msg or "OutOfMemoryError" in error_msg
                        # Truncate long tracebacks — keep last 500 chars for the LLM
                        short_msg = error_msg[-500:] if len(error_msg) > 500 else error_msg
                        error_record = {
                            "exp_id":          exp_id,
                            "status":          "error_training_oom" if is_oom else "error_training",
                            "model_type":      model_type,
                            "timestamp":       time.strftime("%Y-%m-%d %H:%M:%S"),
                            "file_index":      file_index,
                            "params":          record_params,
                            "denoising_score": None,
                            "memory": {
                                "expert_advice_followed": expert_advice_str,
                                "hypothesis":    hypothesis,
                                "conclusion":    f"Training failed: {short_msg}",
                                "discovery":     "CUDA OOM — reduce model size, batch_size, or segmentation_size." if is_oom else f"Training crashed: {short_msg}",
                                "memory_update": "This config exceeds GPU memory. Try smaller architecture." if is_oom else "Fix the error before retrying this config.",
                            },
                        }
                        error_record["memory"]["round_index"] = round_index
                        error_record["memory"]["attempt_in_round"] = attempt_in_round
                        ExperimentRecord.model_validate(error_record)
                        sandbox.save_record(error_record)
                        print(f"  Saved error record: {error_record['status']}")
                        continue
    
                    print(f"[Step 2/3] Inference...")
                    t0 = time.time()
                    inf_status = _run_skill("inference_skill", sandbox, **active_params)
                    inference_time = round(time.time() - t0, 1)
                    if inf_status.get("status") == "error":
                        error_msg = inf_status.get("message", "Unknown inference error")
                        is_oom = "CUDA out of memory" in error_msg or "OutOfMemoryError" in error_msg

                        # Phase 6.7 Fix 3 — when the inference subprocess fails
                        # because the trainer-side sentinel was missing, the
                        # error message carries the ``error_training:`` prefix
                        # (raised by ``inference_single._assert_training_sentinel``).
                        # That is a *training* failure surfaced through the
                        # inference subprocess, not an inference failure.
                        # Re-route the category so the planner sees the right
                        # cause instead of "inference crashed for mysterious
                        # reasons" — and the executor-side silent-crash check
                        # in ``execute_training`` already catches the same
                        # condition upstream when the process exited 0.
                        is_silent_train_crash = "error_training:" in error_msg

                        short_msg = error_msg[-500:] if len(error_msg) > 500 else error_msg
                        if is_silent_train_crash:
                            status_tag = "error_training"
                            conclusion = f"Training crashed silently (detected at inference preflight): {short_msg}"
                            discovery = f"Training subprocess returned 0 but produced no checkpoint sentinel: {short_msg}"
                            memory_update = (
                                "Silent training crash — investigate the trainer logs for a "
                                "post-save segfault, OOM-kill, or GPU watchdog. Do not retry "
                                "blindly until the root cause is identified."
                            )
                        elif is_oom:
                            status_tag = "error_inference_oom"
                            conclusion = f"Inference failed: {short_msg}"
                            discovery = "CUDA OOM during inference — reduce batch_size or model size."
                            memory_update = "Inference OOM — the model trained but can't infer. Try smaller batch."
                        else:
                            status_tag = "error_inference"
                            conclusion = f"Inference failed: {short_msg}"
                            discovery = f"Inference crashed: {short_msg}"
                            memory_update = "Fix the inference error before retrying."

                        error_record = {
                            "exp_id":          exp_id,
                            "status":          status_tag,
                            "model_type":      model_type,
                            "timestamp":       time.strftime("%Y-%m-%d %H:%M:%S"),
                            "file_index":      file_index,
                            "params":          record_params,
                            "denoising_score": None,
                            "memory": {
                                "expert_advice_followed": expert_advice_str,
                                "hypothesis":    hypothesis,
                                "conclusion":    conclusion,
                                "discovery":     discovery,
                                "memory_update": memory_update,
                            },
                        }
                        error_record["memory"]["round_index"] = round_index
                        error_record["memory"]["attempt_in_round"] = attempt_in_round
                        ExperimentRecord.model_validate(error_record)
                        sandbox.save_record(error_record)
                        print(f"  Saved error record: {error_record['status']}")
                        continue
    
                    print(f"[Step 3/3] Scoring...")
                    # Fix 4 — memory probe around the scoring block. See
                    # docs/optimize_inference_and_scoring.md §3 Fix 4. The
                    # tuner's ``round_index`` is the iter axis inside the
                    # tuner scope; workflow-scope probes (different
                    # ``scope`` field) give the outer iteration index.
                    from core.memory_probe import probe_memory
                    probe_memory(iter_idx=round_index, phase="pre_score",
                                 workspace=workspace, scope="tuner")
                    t0 = time.time()
                    if anchor_map_data is not None:
                        # Anchor-normalized scoring (both trial and formal modes).
                        # Trial: sparse SampleSet. Formal: full SampleSet (all 20 × 200).
                        def _denoised_fn(fi):
                            return f"abra_validation_denoised_{model_type}_{run_name}_{exp_id}_{fi:04d}.h5"
                        file_vector, final_scalar = sandbox.score_vector(
                            sample_set=eval_sample_set,
                            anchor_map=anchor_map_data["anchors"],
                            s_max=anchor_map_data["s_max"],
                            denoised_filename_fn=_denoised_fn,
                        )
                        score_res = {
                            "status": "success",
                            "results": {
                                "denoising_score": final_scalar,
                                "file_vector": file_vector,
                            },
                        }
                    else:
                        # Legacy single-file mode (trial_allowed=False, no anchor map)
                        score_res = _run_skill("denoising_score_skill", sandbox, **active_params)
                    scoring_time = round(time.time() - t0, 1)
                    probe_memory(iter_idx=round_index, phase="post_score",
                                 workspace=workspace, scope="tuner")
    
                    # Extract results from each stage
                    train_results = train_status.get("results", {})
                    score_results = score_res.get("results", {})

                    # Build the per-file score-comparison table (model vs
                    # raw_baseline vs ground_truth) with subset-scoped
                    # aggregates. Defensive try/except — the 15-hour tuning
                    # loop must not crash on a rendering bug; a None
                    # score_table simply skips the enriched prompt block in
                    # the next round. See docs/aggregated_score_table_awareness.md §7.1.
                    score_table: Optional[ScoreComparisonTable] = None
                    _sc_fv = score_results.get("file_vector")
                    _sc_scalar = score_results.get("denoising_score")
                    if _sc_fv is not None and _sc_scalar is not None:
                        try:
                            score_table = build_score_table(
                                model_fv_log=_sc_fv,
                                model_scalar=_sc_scalar,
                                reference=reference_scores,
                            )
                        except Exception as e:
                            print(
                                f"[score_table] build_score_table failed: "
                                f"{type(e).__name__}: {e} — continuing with "
                                f"score_table=None."
                            )
                            score_table = None

                    # Cleanup denoised files to save disk space
                    if agent_input.cleanup_denoised:
                        import glob as _glob
                        pattern = os.path.join(
                            sandbox.base_dir,
                            f"abra_validation_denoised_*_{exp_id}_*.h5",
                        )
                        denoised_files = _glob.glob(pattern)
                        if denoised_files:
                            total_bytes = sum(os.path.getsize(f) for f in denoised_files)
                            for f in denoised_files:
                                os.remove(f)
                            print(f"  Cleaned up {len(denoised_files)} denoised files "
                                  f"({total_bytes / (1024**3):.1f} GB freed)")
    
                    # D. REFLECT: Analyze results and generate insights
                    print(f"\nGenerating Research Memory...")
    
                    current_score     = score_results.get("denoising_score")
                    current_loss_type = active_params["loss_config"].get("loss_type")
                    successful = [
                        r for r in memory_history
                        if r.get("status") == "success" and r.get("denoising_score") is not None
                    ]
                    baseline_record = next(
                        (r for r in memory_history if "baseline" in r.get("exp_id", "")), None
                    )
                    all_scores   = [r["denoising_score"] for r in successful]
                    best_score   = max(all_scores) if all_scores else None
                    best_record  = max(successful, key=lambda r: r["denoising_score"]) if successful else None
                    sorted_scores = sorted(all_scores, reverse=True)
                    rank = sorted_scores.index(current_score) + 1 if current_score in sorted_scores else None
    
                    same_loss_finals = [
                        r["final_loss"]
                        for r in successful
                        if r.get("params", {}).get("loss_config", {}).get("loss_type") == current_loss_type
                        and r.get("final_loss") is not None
                    ]
                    current_final_loss = train_results.get("final_loss")
                    if current_final_loss is not None:
                        all_same_loss_finals  = same_loss_finals + [current_final_loss]
                        sorted_finals         = sorted(all_same_loss_finals)
                        same_loss_loss_rank   = sorted_finals.index(current_final_loss) + 1
                        same_loss_total       = len(all_same_loss_finals)
                    else:
                        same_loss_loss_rank = None
                        same_loss_total     = len(same_loss_finals)
    
                    current_params  = train_results.get("model_params")
                    current_epochs  = active_params["train_config"].get("epochs")
                    baseline_params = baseline_record.get("model_params") if baseline_record else None
                    baseline_epochs = baseline_record.get("params", {}).get("train_config", {}).get("epochs") if baseline_record else None
                    params_ratio    = round(current_params / baseline_params, 3) if (current_params and baseline_params) else None
                    epochs_ratio    = round(current_epochs / baseline_epochs, 3) if (current_epochs and baseline_epochs) else None
    
                    worst_score     = min(all_scores) if all_scores else None
                    score_range     = (best_score - worst_score) if (best_score is not None and worst_score is not None and best_score != worst_score) else None
                    score_threshold = (best_score - 0.05 * score_range) if score_range is not None else best_score
                    best_params     = best_record.get("model_params") if best_record else None
                    best_epochs     = best_record.get("params", {}).get("train_config", {}).get("epochs") if best_record else None
                    is_more_efficient = (
                        score_threshold is not None
                        and current_score is not None
                        and current_score >= score_threshold
                        and (
                            (current_params is not None and best_params is not None and current_params < best_params)
                            or (current_epochs is not None and best_epochs is not None and current_epochs < best_epochs)
                        )
                    )
    
                    reflection_context = {
                        "baseline_score":           baseline_record.get("denoising_score") if baseline_record else None,
                        "best_score_so_far":        best_score,
                        "is_new_best":              current_score is not None and (best_score is None or current_score > best_score),
                        "rank":                     rank,
                        "total_experiments":        len(successful),
                        "best_config_so_far":       best_record.get("params") if best_record else None,
                        "best_same_loss_final_loss": min(same_loss_finals) if same_loss_finals else None,
                        "current_loss_type":        current_loss_type,
                        "same_loss_loss_rank":      same_loss_loss_rank,
                        "same_loss_total":          same_loss_total,
                        "baseline_params":          baseline_params,
                        "baseline_epochs":          baseline_epochs,
                        "current_params":           current_params,
                        "current_epochs":           current_epochs,
                        "params_ratio":             params_ratio,
                        "epochs_ratio":             epochs_ratio,
                        "is_more_efficient":        is_more_efficient,
                        "training_psd_segments":    train_psd_segments,
                        "eval_psd_segments":        eval_psd_segments,
                        "baseline_psd_segments":    baseline_record.get("training_psd_segments") if baseline_record else None,
                        "trial_portion":            trial_config.trial_portion if trial_config.mode != "single_file" else None,
                        "eval_portion":             trial_config.eval_portion if trial_config.mode != "single_file" else None,
                        # Pre-rendered per-file comparison table (model vs
                        # raw_baseline vs ground_truth) — consumed verbatim
                        # by the reflector prompt in sub-commit C. None on
                        # failed/skipped rounds so the prompt can branch.
                        "score_comparison_table":   score_table.rendered_markdown if score_table else None,
                    }
    
                    # Pass both training and scoring results to the reflector
                    reflect_results = {**train_results, **score_results}
                    reflection = brain.reflect(exp_id, hypothesis, reflect_results, reflection_context)
    
                    # Defensive unwrap: LLM occasionally emits [{...}] instead of {...}.
                    if isinstance(reflection, list) and len(reflection) == 1 and isinstance(reflection[0], dict):
                        print("[reflect] LLM returned a single-element list — unwrapping to dict.")
                        reflection = reflection[0]
                    if not isinstance(reflection, dict):
                        print(f"[reflect] LLM returned non-dict ({type(reflection).__name__}); using empty reflection.")
                        reflection = {}
    
                    print(f"{'-'*30}")
                    print(f"RESEARCH REFLECTION for {exp_id}:")
                    print(f"Conclusion  : {reflection.get('conclusion', 'N/A')}")
                    print(f"Key Factor  : {reflection.get('key_factor', 'N/A')}")
                    print(f"Discovery   : {reflection.get('discovery', 'N/A')}")
                    print(f"Memory Update: {reflection.get('memory_update', 'N/A')}")
                    print(f"{'-'*30}")
    
                    # E. COMMIT: Build, validate, and save the finalized record
                    final_record = {
                        "exp_id":     exp_id,
                        "status":     "success",
                        "model_type": model_type,
                        "timestamp":  time.strftime("%Y-%m-%d %H:%M:%S"),
                        "file_index": file_index,
                        "params":     record_params,
                        # Training results
                        "final_loss":    train_results.get("final_loss"),
                        "loss_history":  train_results.get("loss_history"),
                        "model_params":  train_results.get("model_params"),
                        # Scoring results
                        "denoising_score": score_results.get("denoising_score"),
                        "file_vector":     score_results.get("file_vector"),
                        # Per-file comparison table enrichment. Stored as a
                        # plain dict on the record (ExperimentRecord.model_validate
                        # coerces it back to ScoreComparisonTable below). None
                        # when scoring failed or no scalar was produced.
                        "score_table":     score_table.model_dump() if score_table else None,
                        # Data volume
                        "training_psd_segments": train_psd_segments,
                        "eval_psd_segments":    eval_psd_segments,
                        "timing": {
                            "train_time_s":     train_time,
                            "inference_time_s": inference_time,
                            "scoring_time_s":   scoring_time,
                        },
                        "memory": {
                            "expert_advice_followed": expert_advice_str,
                            "hypothesis":    hypothesis,
                            "conclusion":    reflection.get("conclusion"),
                            "key_factor":    reflection.get("key_factor"),
                            "discovery":     reflection.get("discovery"),
                            "memory_update": reflection.get("memory_update"),
                        },
                    }
                    # Phase J — surface pre-flight time-estimator context to the
                    # planner via the next round's experiment_history. Only added
                    # when the gate actually ran (chosen_time_budget was set);
                    # the keys are absent on records produced with the gate
                    # disabled, so the reflector doesn't have to filter None.
                    # See docs/resource_estimator_implement.md §J.1.
                    if time_check is not None:
                        final_record["memory"]["time_estimate_minutes"] = (
                            time_check.get("estimated_minutes")
                        )
                        final_record["memory"]["time_budget_minutes"] = (
                            time_check.get("limit_minutes")
                        )
                        final_record["memory"]["time_mode"] = (
                            "trial" if plan.is_trial else "formal"
                        )
                    # Phase K — surface pre-flight VRAM-estimator context to the
                    # planner the same way Phase J surfaces time context. Only
                    # added when the gate ran with a budget (chosen_vram_budget
                    # was set); omitted when the gate fell back to free×0.8.
                    # Mode is inferred from `time_mode` above when present.
                    # See docs/resource_estimator_implement.md §10.4.
                    if chosen_vram_budget is not None:
                        final_record["memory"]["vram_estimate_gb"] = (
                            resource_check.get("estimated_gb")
                        )
                        final_record["memory"]["vram_budget_gb"] = (
                            resource_check.get("limit_gb")
                        )
                    # K.2.5-8 — soft-fallback flag from the inference estimator.
                    # Independent of vram_budget being set; recorded whenever
                    # the gate reported a substitution so post-hoc audit can
                    # identify success rounds that ran against a guessed batch.
                    if resource_check.get("inference_batch_uncalibrated"):
                        final_record["memory"]["inference_batch_uncalibrated"] = True
                    # Phase L — round bookkeeping for the per-round budget audit.
                    final_record["memory"]["round_index"] = round_index
                    final_record["memory"]["attempt_in_round"] = attempt_in_round
                    # Trial context
                    if trial_config.is_trial:
                        final_record["is_trial"] = True
                        final_record["trial_strategy"] = trial_config.trial_strategy
                        final_record["trial_portion"] = trial_config.trial_portion
                        final_record["eval_strategy"] = trial_config.eval_strategy
                        final_record["eval_portion"] = trial_config.eval_portion
                        final_record["train_portion"] = trial_config.train_portion
                        if trial_config.trial_strategy == "target":
                            final_record["target_files"] = trial_config.target_files
    
                    ExperimentRecord.model_validate(final_record)
                    sandbox.save_record(final_record)
    
                    # Phase F post-flight: update per-GPU calibration from this
                    # successful run. Only runs when the gate used the real-dataset
                    # warmup path (the static formula has no warmup signal to
                    # calibrate against). See docs/resource_estimator_implement.md §2.6.5.
                    if time_check is not None:
                        bd = time_check.get("breakdown") or {}
                        if bd.get("source") == "real_dataset_warmup":
                            gpu_name = bd.get("gpu_name")
                            warmup_ms = float(bd.get("ms_per_step_warmup") or 0.0)
                            total_steps = int(bd.get("total_train_steps") or 0)
                            if gpu_name and warmup_ms > 0 and total_steps > 0 and train_time > 0:
                                try:
                                    actual_ms = train_time * 1000.0 / total_steps
                                    entry = time_calibration.make_entry(
                                        gpu_name=gpu_name,
                                        model_type=model_type,
                                        seg_size=int(active_params["model_config"].get("segmentation_size", 0)),
                                        batch_size=int(active_params["train_config"].get("batch_size", 1)),
                                        total_steps=total_steps,
                                        warmup_ms_per_step=warmup_ms,
                                        actual_ms_per_step=actual_ms,
                                        estimated_minutes=float(time_check.get("estimated_minutes") or 0.0),
                                        actual_minutes=train_time / 60.0,
                                    )
                                    table = time_calibration.load_table(gpu_name)
                                    time_calibration.update_k(table, entry)
                                    time_calibration.save_table(gpu_name, table)
                                    drift = time_calibration.detect_drift(table)
                                    if drift:
                                        print(f"  [time-calibration] {drift}")
                                    else:
                                        new_k = time_calibration.lookup_k(table, model_type)
                                        print(
                                            f"  [time-calibration] {gpu_name} / {model_type}: "
                                            f"ratio={entry['ratio']:.3f} → k={new_k:.3f}"
                                        )
                                except Exception as cal_exc:  # pragma: no cover — defensive
                                    print(f"  [time-calibration skipped] {cal_exc}")
    
                    # Phase L — success path: mark the round landed, reset the
                    # consecutive-failure counter, and break out of the inner
                    # attempt loop so the outer while moves on to the next round.
                    round_succeeded = True
                    completed_rounds += 1
                    consecutive_fails = 0
                    print(f"Round {completed_rounds}/{max_rounds} Complete. "
                          f"Score: {score_results.get('denoising_score', 'N/A')}")
    
                    time.sleep(2)  # Cool-down to avoid API rate limits
                    break
    
                except Exception as e:
                    print(f"Loop Error: {e}")
                    traceback.print_exc()
                    time.sleep(5)

            # Phase L — inner attempt loop ended without a successful
            # break. Bump the consecutive-failure counter so the outer
            # while can decide whether to abort the iteration.
            if not round_succeeded:
                consecutive_fails += 1
                print(
                    f"Round {round_index} exhausted all {N} attempt(s) "
                    f"without a successful experiment "
                    f"(consecutive_fail_rounds={consecutive_fails}/"
                    f"{max_fail_rounds_setting})."
                )

            # Phase 6.8 §2 Layer C (Commit 4) — per-round cleanup. Drop
            # local refs to the largest per-round transients before the
            # next round's plan() call so inter-round RSS stays flat.
            # NameError-guarded because early-exit paths (gate skip,
            # training crash before score) leave some names unbound.
            # See docs/phase68_task1_memory_diagnostic_20260427.md §2 Commit 4.
            try: del train_results
            except NameError: pass
            try: del score_results
            except NameError: pass
            try: del score_table
            except NameError: pass
            try: del file_vector
            except NameError: pass
            try: del final_scalar
            except NameError: pass
            try: del reflect_results
            except NameError: pass
            try: del memory_history
            except NameError: pass
            gc.collect()

        # --- Build, validate, and save the run output ---
        finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        # Phase L (§11) — termination_reason captures *why* the outer
        # loop exited. ``aborted_fail_rounds`` fires when the
        # consecutive-fail counter hits ``max_fail_rounds`` before all
        # rounds completed; otherwise we either landed every round
        # ("completed") or stopped early for some other reason
        # ("partial" — currently unreachable with ``max_rounds >= 1``,
        # kept as a defensive fallback).
        if completed_rounds >= max_rounds:
            run_status = "completed"
            termination_reason = "completed"
        elif consecutive_fails >= max_fail_rounds_setting:
            run_status = "partial"
            termination_reason = "aborted_fail_rounds"
        else:
            run_status = "partial"
            termination_reason = "completed"
        all_records = sandbox.get_summary()
        successful_records = [
            r for r in all_records
            if r.get("status") == "success" and r.get("denoising_score") is not None
        ]
        top_record = max(successful_records, key=lambda r: r["denoising_score"]) if successful_records else None

        # Dual-track best-record selection for score_table propagation:
        #   best_*  — highest denoising_score across all successful records
        #             (may be a trial-mode record on subset indices).
        #   formal_* — highest denoising_score among formal-mode records only
        #             (full 20-file subset). Formal records have no "is_trial"
        #             key (it's set to True only when trial_config.is_trial);
        #             absence == formal. Surfaces the "canonical" table to
        #             downstream nodes without the trial-mode subset caveat.
        formal_records = [
            r for r in successful_records if not r.get("is_trial", False)
        ]
        formal_top_record = (
            max(formal_records, key=lambda r: r["denoising_score"])
            if formal_records else None
        )

        # Phase K.7 — gate-exhaustion feedback for the next iteration's
        # proposer (§10.13). active_mode comes from the most recent plan;
        # the helper returns None unless the trigger criterion fires.
        gate_active_mode = "trial" if (plan is not None and plan.is_trial) else "formal"
        gate_vram_budget = (
            trial_vram_budget if gate_active_mode == "trial" else formal_vram_budget
        )
        gate_time_budget = (
            trial_time_budget if gate_active_mode == "trial" else formal_time_budget
        )
        gate_exhaustion = _build_gate_exhaustion(
            records=all_records,
            active_mode=gate_active_mode,
            vram_budget_gb=gate_vram_budget,
            time_budget_minutes=gate_time_budget,
            consecutive_fail_rounds_at_exit=consecutive_fails,
            max_fail_rounds=max_fail_rounds_setting,
            completed_rounds=completed_rounds,
        )
        if gate_exhaustion is not None:
            print(
                f"[gate-exhaustion] iteration ended without ever training; "
                f"{gate_exhaustion.vram_gated_attempts} VRAM-gated, "
                f"{gate_exhaustion.time_gated_attempts} time-gated, "
                f"{gate_exhaustion.other_failure_attempts} other failures. "
                f"Surfacing to next proposer."
            )

        agent_output = HyperparamTuningOutput.model_validate({
            "run_name":                          run_name,
            "model_type":                        model_type_setting,
            "file_index":                        file_index,
            "status":                            run_status,
            "completed_rounds":                  completed_rounds,
            "total_attempts":                    total_attempts,
            "best_exp_id":                       top_record.get("exp_id") if top_record else None,
            "best_denoising_score":              top_record.get("denoising_score") if top_record else None,
            "best_config":                       top_record.get("params") if top_record else None,
            "best_file_vector":                  top_record.get("file_vector") if top_record else None,
            "best_score_table":                  top_record.get("score_table") if top_record else None,
            "formal_score_table":                formal_top_record.get("score_table") if formal_top_record else None,
            "all_records":                       all_records,
            "started_at":                        started_at,
            "finished_at":                       finished_at,
            "gate_exhaustion":                   gate_exhaustion,
            # Phase 6.6 WS-B B.3 — flush per-attempt VRAM-gate rejections.
            # Empty list when every attempt was feasible. Orchestrator
            # aggregates (worst-offender per architecture) before rendering
            # into the next Proposer's previous_failures.
            "physical_rejections":               physical_rejections_buffer,
            # Phase L (§11) — echo budget settings + termination metadata.
            "attempts_per_round":                attempts_per_round_setting,
            "attempts_per_formal_round":         attempts_per_formal_round_setting,
            "max_fail_rounds":                   max_fail_rounds_setting,
            "consecutive_fail_rounds_at_exit":   consecutive_fails,
            "termination_reason":                termination_reason,
        })

        output_path = os.path.join(workspace, f"run_output_{run_name}.json")
        # Coerce float('-inf') no-signal sentinels to JSON null at the storage
        # boundary — model_dump_json would otherwise emit non-standard
        # ``-Infinity`` tokens that break the dashboard's ``JSON.parse``.
        safe_output = coerce_nonfinite_to_none(agent_output.model_dump())
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(safe_output, f, indent=4)
        print(f"Output validated and saved -> {output_path}")

        if termination_reason == "completed":
            print(f"\nCompleted {completed_rounds} research rounds. Loop terminated.")
        elif termination_reason == "aborted_fail_rounds":
            print(
                f"\nAborted after {consecutive_fails} consecutive fail-rounds "
                f"(max_fail_rounds={max_fail_rounds_setting}); "
                f"{completed_rounds}/{max_rounds} rounds completed across "
                f"{total_attempts} total attempts."
            )
        else:
            print(
                f"\nLoop ended with status={run_status}; "
                f"{completed_rounds}/{max_rounds} rounds completed across "
                f"{total_attempts} total attempts."
            )

        return agent_output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    """Thin CLI wrapper — parses args, builds HyperparamTuningInput, calls run()."""
    # Import MODEL_REGISTRY here (not at module level) because it depends on
    # ml_models/ being on PYTHONPATH, which is only guaranteed in CLI/pytest contexts.
    from ml_models.models_sandbox import MODEL_REGISTRY

    parser = argparse.ArgumentParser(description="TIDMAD Autonomous Agent Kernel")

    parser.add_argument("--provider", type=str, choices=["gemini", "openai"], default="gemini",
                        help="LLM provider for the planner sub-call (default for reflector when not overridden).")
    parser.add_argument("--model_id", type=str, default="gemini-3.1-flash-lite-preview",
                        help="Model ID for the planner sub-call (default for reflector when not overridden).")
    parser.add_argument("--reflect_provider", type=str, choices=["gemini", "openai"], default=None,
                        help="Optional separate provider for the reflector sub-call. "
                             "When None, the reflector uses --provider.")
    parser.add_argument("--reflect_model_id", type=str, default=None,
                        help="Optional separate model for the reflector sub-call (e.g., gemini-2.5-flash). "
                             "When None, the reflector uses --model_id.")
    parser.add_argument("--expert_advice", type=str, default="None",
                        help="Initial advice from a human expert to guide exploration.")
    parser.add_argument("--max_rounds", type=int, default=10,
                        help="Maximum number of experiment rounds to prevent token drain.")

    # ``--force_model`` accepts any string (not just MODEL_REGISTRY keys),
    # because plugin models seeded via ``--seed_plugin_path`` are not in the
    # registry at CLI parse time — the seed plugin only gets registered
    # after the tuner copies it into the run-scoped plugin dir
    # (docs/run_scoped_plugins.md, Phase 3/4). The schema validator and the
    # planner reject unknown model_types at runtime with a clearer error.
    builtin_choices = list(MODEL_REGISTRY.keys()) + ["auto"]
    parser.add_argument("--force_model", type=str, default="auto",
                        help=(
                            "Force a specific architecture or let the agent decide "
                            "('auto'). Built-in choices: "
                            f"{', '.join(builtin_choices)}. Plugin model_types are "
                            "also accepted when paired with --seed_plugin_path."
                        ))
    parser.add_argument("--seed_plugin_path", type=str, default=None,
                        help=(
                            "Path to a plugin .py file used as the seed model "
                            "for this run. Required when --force_model is a "
                            "plugin model_type (i.e. not a built-in). The file's "
                            "PLUGIN_MODEL_TYPE must equal --force_model. The "
                            "tuner copies the file into "
                            "<workspace>/plugins/<run_name>/ at run start so "
                            "the training subprocess sees it via "
                            "SIDERIUS_PLUGIN_DIRS. See "
                            "docs/run_scoped_plugins.md (Phase 3)."
                        ))

    parser.add_argument("--run_name", type=str, default="test_run",
                        help="Run name for the auto-exploration.")
    parser.add_argument("--workspace", type=str, default="./siderius_workspace",
                        help="Root directory for all agent-generated outputs.")
    parser.add_argument("--progress_bar", action="store_true",
                        help="Stream live tqdm progress bars from training/inference subprocesses.")
    parser.add_argument("--file_index", type=int, default=6,
                        help="Validation/training file index (default: 6). Ignored when --is_trial.")

    # Trial mode arguments
    parser.add_argument("--is_trial", action="store_true",
                        help="Enable trial-explore mode with multi-file sparse sampling.")
    parser.add_argument("--trial_strategy", type=str, default="snapshot",
                        choices=["snapshot", "anchors", "target"],
                        help="Training sampling strategy (default: snapshot).")
    parser.add_argument("--trial_portion", type=float, default=0.1,
                        help="Fraction of segments per file for training scope (default: 0.1).")
    parser.add_argument("--eval_strategy", type=str, default="snapshot",
                        choices=["snapshot", "anchors", "target"],
                        help="Validation sampling strategy (default: snapshot).")
    parser.add_argument("--eval_portion", type=float, default=0.1,
                        help="Fraction of segments per file for validation (default: 0.1).")
    parser.add_argument("--train_portion", type=float, default=0.1,
                        help="Per-epoch subsample from training scope (default: 0.1).")

    # Formal-mode training levers (Phase M). Eval side is hardcoded to
    # snapshot + eval_portion=1.0 in the tuner — not operator-configurable.
    # See docs/resource_estimator_implement.md §12.
    parser.add_argument("--formal_strategy", type=str, default="snapshot",
                        choices=["snapshot", "anchors", "target"],
                        help="Training-side sampling strategy in formal mode (default: snapshot).")
    parser.add_argument("--formal_portion", type=float, default=0.1,
                        help="Fraction of segments per file for formal training scope (default: 0.1).")
    parser.add_argument("--formal_train_portion", type=float, default=1.0,
                        help="Per-epoch iteration fraction for formal training (default: 1.0).")

    parser.add_argument("--human_advice", type=str, default=None,
                        help="Human guidance for the agent (injected alongside expert_advice).")
    parser.add_argument("--cleanup_denoised", action="store_true",
                        help="Delete denoised HDF5 files after scoring each round to save disk space.")

    # evaluate_time_skill gate (Phase E1, Phase I two-budget split). Each
    # default is None, which keeps that mode's gate off — matches the
    # workflow-level CLI in run_exploration_adaptive.py.
    parser.add_argument("--trial_time_budget_minutes", type=float, default=None,
                        help="Wall-time budget (minutes) for the evaluate_time_skill "
                             "gate on rounds where plan.is_trial=True. None disables "
                             "the trial gate.")
    parser.add_argument("--formal_time_budget_minutes", type=float, default=None,
                        help="Wall-time budget (minutes) for the evaluate_time_skill "
                             "gate on rounds where plan.is_trial=False. None disables "
                             "the formal gate. Sized independently from the trial "
                             "budget because formal runs use the full dataset and "
                             "are 50–100x longer.")
    parser.add_argument("--data_dir", type=str, default=None,
                        help="TIDMAD data directory used by evaluate_time_skill's real-dataset "
                             "warmup. None makes the skill fall back to its static formula.")

    # evaluate_vram_skill gate (Phase K two-budget split). Each default is
    # None which keeps that mode's budget disabled — skill falls back to the
    # defensive free×0.8 limit. Matches run_exploration_adaptive.py.
    parser.add_argument("--trial_vram_budget_gb", type=float, default=None,
                        help="Per-mode VRAM ceiling (GB) for the evaluate_vram_skill "
                             "gate on rounds where plan.is_trial=True. None → "
                             "skill uses free×0.8 defensive limit.")
    parser.add_argument("--formal_vram_budget_gb", type=float, default=None,
                        help="Per-mode VRAM ceiling (GB) for the evaluate_vram_skill "
                             "gate on rounds where plan.is_trial=False. None → "
                             "skill uses free×0.8 defensive limit. Sized "
                             "independently from the trial budget because formal "
                             "rounds often use larger batch_size / segmentation_size.")

    # Per-round attempt budget (Phase L, §11). All three default to the
    # schema defaults so the CLI surface matches the schema-only path.
    parser.add_argument("--attempts_per_round", type=int, default=3,
                        help="Inner attempt budget for trial rounds (default 3). "
                             "Each round runs up to N attempts; success → break + "
                             "reset the consecutive-fail counter, exhaustion → "
                             "bump it. See docs/resource_estimator_implement.md §11.")
    parser.add_argument("--attempts_per_formal_round", type=int, default=5,
                        help="Inner attempt budget for the formal-promotion round "
                             "(default 5, intentionally higher than --attempts_per_round). "
                             "Formal is the only cross-architecture comparable "
                             "measurement, so an iteration with no formal score is "
                             "wasted entirely — extra attempts are worth the cost.")
    parser.add_argument("--max_fail_rounds", type=int, default=3,
                        help="Consecutive-failure brake (default 3). The outer "
                             "loop aborts with termination_reason='aborted_fail_rounds' "
                             "after this many consecutive rounds exhaust their inner "
                             "attempt budget.")

    args = parser.parse_args()

    # Preflight: catch the "plugin model_type without seed file" mistake
    # before any sandbox setup. The schema validator would catch this later
    # (planner crashes on get_config_class), but flagging it here gives the
    # operator an actionable message instead of a stack trace mid-run.
    if (
        args.force_model != "auto"
        and args.force_model not in MODEL_REGISTRY
        and args.seed_plugin_path is None
    ):
        parser.error(
            f"--force_model={args.force_model!r} is not a built-in model "
            f"({', '.join(builtin_choices)}). If this is a plugin model, "
            f"pass --seed_plugin_path /path/to/{args.force_model}.py so the "
            f"tuner can stage it into the run-scoped plugin dir."
        )

    input_dict = {
        "model_type":      args.force_model,
        "seed_plugin_path": args.seed_plugin_path,
        "file_index":      args.file_index,
        "max_rounds":      args.max_rounds,
        "expert_advice":   args.expert_advice,
        "llm_provider":    args.provider,
        "llm_model_id":    args.model_id,
        "reflect_provider": args.reflect_provider,
        "reflect_model_id": args.reflect_model_id,
        "storage": {
            "backend": "local",
            "local": {"workspace": args.workspace, "run_name": args.run_name},
        },
        "progress_bar":      args.progress_bar,
        "cleanup_denoised":  args.cleanup_denoised,
        "is_trial":          args.is_trial,
    }
    if args.is_trial:
        input_dict.update({
            "trial_strategy":  args.trial_strategy,
            "trial_portion":   args.trial_portion,
            "eval_strategy":   args.eval_strategy,
            "eval_portion":    args.eval_portion,
            "train_portion":   args.train_portion,
        })
        # Clamp the LLM's per-round ExperimentPlan portions to the operator's
        # CLI values. Without this, the top-level trial_portion only sizes the
        # sample set; the LLM is still free to pick its own ExperimentPlan
        # portions, which can blow past the time-budget gate. Mirrors
        # run_exploration_adaptive.py's plan_overrides wiring.
        input_dict["plan_overrides"] = {
            "is_trial":      True,
            "trial_portion": args.trial_portion,
            "train_portion": args.train_portion,
            "eval_portion":  args.eval_portion,
        }
    # Phase M — formal-mode training levers. Always forwarded (trial or not)
    # because they apply whenever a round is promoted to formal.
    input_dict["formal_strategy"]      = args.formal_strategy
    input_dict["formal_portion"]       = args.formal_portion
    input_dict["formal_train_portion"] = args.formal_train_portion

    if args.human_advice:
        input_dict["human_advice"] = args.human_advice
    if args.trial_time_budget_minutes is not None:
        input_dict["trial_time_budget_minutes"] = args.trial_time_budget_minutes
    if args.formal_time_budget_minutes is not None:
        input_dict["formal_time_budget_minutes"] = args.formal_time_budget_minutes
    if args.data_dir is not None:
        input_dict["data_dir"] = args.data_dir
    if args.trial_vram_budget_gb is not None:
        input_dict["trial_vram_budget_gb"] = args.trial_vram_budget_gb
    if args.formal_vram_budget_gb is not None:
        input_dict["formal_vram_budget_gb"] = args.formal_vram_budget_gb

    # Phase L (§11) — per-round attempt budget. Always forwarded so a CLI
    # invocation matches the workflow path. Schema validators enforce ge=1.
    input_dict["attempts_per_round"] = args.attempts_per_round
    input_dict["attempts_per_formal_round"] = args.attempts_per_formal_round
    input_dict["max_fail_rounds"] = args.max_fail_rounds

    agent_input = HyperparamTuningInput.model_validate(input_dict)

    agent = HyperparamTuningAgent()
    agent.run(agent_input)


if __name__ == "__main__":
    main()
