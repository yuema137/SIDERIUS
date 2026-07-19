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
  │   ├── attempt_001/
  │   │   ├── proposal_{run_name}.json
  │   │   ├── implementor_{run_name}.json
  │   │   ├── validation_{run_name}.json
  │   │   ├── models/{model_name}.py
  │   │   └── tests/test_{model_name}.py
  │   └── {model_name}/              (tuning output, named by proposed model)
  │       ├── run_output_{run_name}.json
  │       ├── summary_{run_name}.json
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
import json
import os
import shutil
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from typing import Any, Literal

import psutil as _psutil
import yaml

from agent.schemas.external_agents import ExternalAgentOutput
from agent.schemas.hyperparam_tuning import (
    GateExhaustionInfo,
    HyperparamTuningOutput,
    PhysicalRejection,
)
from agent.schemas.interpretation import (
    InterpretationInput,
    InterpretationOutput,
    ModelRunSummary,
)
from agent.schemas.proposal import ExpertContextItem, VocabEntry
from agent.schemas.protocols.ml_model_impl_to_ml_model_valid import local_all_fields
from agent.schemas.protocols.ml_model_propose_to_ml_model_impl import local_full_spec
from agent.schemas.protocols.ml_model_valid_to_ml_model_tune import local_validated_model
from agent.schemas.protocols.ml_result_interp_to_ml_model_propose import local_full_context
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from agent.schemas.task_config import ForwardContract
from core.hardware_context import get_or_create as get_or_create_hardware_context
from nodes.ml_code_validator_agent import MLCodeValidatorAgent
from nodes.ml_hyperparameter_tune_agent import HyperparamTuningAgent
from nodes.ml_literature_review import MLLiteratureReviewAgent
from nodes.ml_model_implementor import MLModelImplementor
from nodes.ml_model_proposal_agent import MLModelProposalAgent
from nodes.result_interpretation_agent import (
    ResultInterpretationAgent,
    tuning_output_to_model_run_summary,
)
from workflows.llm_config import ProposalLLMConfig, WorkflowLLMConfig
from workflows.task_config import get_task_description, load_task_config

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
# ``local_full_context.trial_strategy``, ``local_validated_model.{trial,eval,
# formal,formal_round}_strategy``) without per-call casts.
ExplorationMode = Literal["auto", "explore", "exploit"]
StrategyMode = Literal["snapshot", "anchors", "target"]
FormalRoundStrategy = Literal[
    "full_clone",
    "hybrid_params",
    "independent",
    "inherit_best_trial",
    "llm_propose",
]


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
) -> list[ModelRunSummary]:
    """
    Convert a list of HyperparamTuningOutput objects into condensed
    ModelRunSummary objects suitable for InterpretationInput.

    Raw experiment records are NOT carried forward — only aggregates
    and per-round scores/conclusions are extracted.
    """
    return [tuning_output_to_model_run_summary(o) for o in outputs]


def _make_storage(workspace: str, run_name: str) -> StorageConfig:
    """Create a StorageConfig pointing at a specific workspace directory."""
    return StorageConfig(
        backend="local",
        local=LocalStorageConfig(workspace=workspace, run_name=run_name),
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

    The source path is anchored on :data:`SIDERIUS_ROOT` (not the
    process cwd) so integration tests that pass a tmp workspace without
    ``chdir``'ing into the repo root still pick up the committed config.

    See ``docs/design/enable_global_task_config.md`` § "Run provenance —
    task config snapshot" + § Commit T1b for the design + chain-mode
    rationale.
    """
    snapshot_path = os.path.join(run_dir, "task_config_snapshot.yaml")
    if not os.path.exists(snapshot_path):
        shutil.copy2(os.path.join(SIDERIUS_ROOT, "configs", "task_config.yaml"), snapshot_path)


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
    ge: GateExhaustionInfo,
) -> HyperparamTuningOutput:
    """Wrap a prior-chain-iter ``GateExhaustionInfo`` as a minimal
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
        started_at=now,
        finished_at=now,
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

    Args:
        config: Parsed YAML dict from ``configs/lit_review_config.yaml`` (or
            the operator-supplied path via ``--ml_lit_review_config``).
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

    # Fix 6 (Commit 6.5b-5) + Commit F: read task_description from YAML and
    # warn when empty. Post-Commit-F: there is no SIDERIUS_TASK fallback —
    # an empty value flows through as "" to the {TASK_DESCRIPTION} prompt
    # placeholder, leaving the prompt section bare (no task-domain anchor
    # for the LLM). Workflow uses print() for warnings (no logger in this
    # module — convention matches existing call sites e.g. line 136's
    # "Warning: failed to load vocab seed").
    task_description = str(config.get("task_description", "") or "").strip()
    if not task_description:
        print(
            "Warning: lit_review config has no `task_description` — "
            "lit-review LLM calls will receive no task-domain anchor and "
            "may produce off-domain queries. Strongly recommended: set "
            "`task_description:` in configs/lit_review_config.yaml to "
            "specialize the agent's search/synthesis behavior for your "
            "problem."
        )

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


def _cap_knowledge_cache(
    cache: dict,
    current_model: str,
    max_entries: int = 5,
) -> tuple[dict, set[str]]:
    """Keep top-N models by best_denoising_score + the current iteration's model.

    Returns:
        (capped_cache, evicted_model_types)
    """
    if len(cache) <= max_entries:
        return cache, set()

    scored = [
        (mt, entry.get("_stats", {}).get("best_denoising_score"))
        for mt, entry in cache.items()
        if mt != current_model
    ]
    scored.sort(key=lambda x: x[1] if x[1] is not None else float("-inf"), reverse=True)
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


def _add_plugin_to_registries(plugin_path: str) -> str | None:
    """Register a single plugin file in every in-process registry surface.

    Updates three surfaces so the tuner's planner (running in the same process
    as this workflow) can resolve the new model_type for both training and
    inference without a re-scan:

      1. ``ml_models.models_sandbox.MODEL_REGISTRY``
         — model_type → model class
      2. ``ml_models.models_format_sandbox.PLUGIN_CONFIG_REGISTRY``
         — model_type → config class
      3. ``ml_models.plugin_loader.PLUGIN_OUTPUT_TYPE_REGISTRY``
         — model_type → "classifier" | "regressor" | "hybrid", driving
         classifier-vs-regressor routing in scoring + inference.

    After the 2026-05 package refactor every import resolves through the
    qualified ``ml_models.*`` path, so there is a single canonical module
    identity for each registry. The historical bare-name mirror that
    previously protected the training subprocess from the duplicate-module
    bug (see ``ml_models/models_sandbox.py`` history pre-package-migration)
    is no longer required and has been removed.

    Args:
        plugin_path: filesystem path to the plugin ``.py`` file.

    Returns:
        The registered ``model_type`` string on success, or ``None`` if the
        plugin file failed to load (validation error, missing required
        attributes, etc — see ``ml_models.plugin_loader._load_plugin``).
    """
    from ml_models.models_format_sandbox import PLUGIN_CONFIG_REGISTRY
    from ml_models.models_sandbox import MODEL_REGISTRY
    from ml_models.plugin_loader import PLUGIN_OUTPUT_TYPE_REGISTRY, _load_plugin

    plugin_data = _load_plugin(plugin_path)
    if plugin_data is None:
        return None

    model_type = plugin_data["model_type"]
    MODEL_REGISTRY[model_type] = plugin_data["model_class"]
    PLUGIN_CONFIG_REGISTRY[model_type] = plugin_data["config_class"]
    PLUGIN_OUTPUT_TYPE_REGISTRY[model_type] = plugin_data["output_type"]

    return model_type


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
        registered = _add_plugin_to_registries(primary_plugin)
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
    """Promote a generated loss plugin to the global ``agent_generated/losses/``.

    L6c — called after the iteration's tuner completes so the loss is
    accessible to:

      * Future chain iterations whose workspace may differ from this one
        (workspaces are scratch; the global library persists across runs).
      * Parallel chain workflows that share the global capability registry.
      * Cross-process Branch B reuse after a chain resume from disk.

    Trigger condition: ``impl_output.loss_provenance.action == "generated"``.
    Per the design discussion (2026-06-23 L6c review), promotion fires
    REGARDLESS of training outcome — even if the round aborted before any
    record was scored, the implementor still produced a validated plugin
    (dummy-tensor check passed), and keeping it accessible avoids leaking
    the I12 failure mode to future runs. The proposer/tuner self-correct
    via the advice file's lit-review-driven mode and the existing 3-branch
    Rule 9 constraints.

    Content-hash deduplication: before copying, compares SHA256 of the
    source against every ``.py`` already in ``agent_generated/losses/``.
    On match, skips promotion and logs which existing entry is the
    duplicate. Catches the case where two iterations generate plugins
    with different ``loss_name``s but byte-identical contents (e.g. an
    LLM regenerating the same canonical loss).

    Registry update: after promotion, the capability registry entry's
    ``file_path`` is rewritten to the global path via
    ``CapabilityRegistry.replace()`` so subsequent Branch B reuse and
    cross-process resume resolve to the stable location.

    Idempotency: if the destination file already exists at the exact name
    (e.g. a parallel chain promoted first), promotion skips silently —
    first writer wins, registry update still fires so this chain's index
    entry points at the global path too.

    No-op when ``loss_provenance is None`` (built-in loss path) or
    ``action == "reused"`` (already promoted by the originating iteration).
    """
    loss_prov = getattr(impl_output, "loss_provenance", None)
    if loss_prov is None or loss_prov.action != "generated":
        return

    from agent_generated._loss_loader import LOSSES_DIR
    from agent_generated._registry import CapabilityMetadata, CapabilityRegistry

    src = loss_prov.loss_file_path
    if not src or not os.path.isfile(src):
        print(
            f"  Warning: cannot promote loss '{loss_prov.loss_name}' — "
            f"source file not found at {src}"
        )
        return

    os.makedirs(LOSSES_DIR, exist_ok=True)
    global_dest = os.path.join(LOSSES_DIR, f"{loss_prov.loss_name}.py")

    # Content-hash dedup: scan existing global plugins for byte-identical
    # content under a different name. Caches src hash to avoid re-reading.
    src_hash = _sha256_file(src)
    for fname in os.listdir(LOSSES_DIR):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        existing_path = os.path.join(LOSSES_DIR, fname)
        if existing_path == global_dest:
            continue  # same-name match handled by the idempotency check below
        if _sha256_file(existing_path) == src_hash:
            existing_name = fname[:-3]  # strip .py
            print(
                f"  Loss '{loss_prov.loss_name}' not promoted — identical "
                f"content already exists as '{existing_name}' "
                f"({global_dest} skipped)."
            )
            return

    if os.path.exists(global_dest):
        print(
            f"  Loss '{loss_prov.loss_name}' already at global path "
            f"{global_dest} (idempotent skip)."
        )
    else:
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
    """Promote a generated model plugin to the global ``agent_generated/models/``.

    Mirrors :func:`_promote_loss_to_global` for the model surface. Called
    by the workflow's iteration loop right after ``_register_plugin``
    returns (early-promotion timing matches the issue-#92 fix for losses)
    so a parallel chain or future-iter resume can resolve the model via
    the capability index without depending on this run's workspace.

    Trigger condition: ``impl_output.model_file_path`` exists AND
    ``impl_output.model_type`` is registered in the capability index with
    ``capability_type='model'``. The implementor writes that entry
    immediately after building the plugin (so by the time the workflow
    sees ``impl_output``, the index entry already exists), and Branch B
    reuse paths leave the existing registry entry alone — so this helper
    no-ops cleanly on Branch B (file already at the global path, registry
    already correct).

    Content-hash deduplication: before copying, compares SHA256 of the
    source against every ``.py`` already in the global models dir. On
    match, skips the copy and logs which existing entry is the duplicate.

    Registry update: after promotion, the capability registry entry's
    ``file_path`` is rewritten to the global path via
    ``CapabilityRegistry.replace()``.

    Idempotency: if the destination file already exists at the exact name
    (e.g. a parallel chain promoted first, or Branch B reuse), the copy
    is skipped silently and the registry update is still re-asserted.

    No-op when ``impl_output.model_file_path`` is empty (defensive) or
    when the model name is not in the registry (e.g. a built-in Branch A
    path that never wrote a generated plugin — nothing to promote).
    """
    model_file_path = getattr(impl_output, "model_file_path", "") or ""
    if not model_file_path or not os.path.isfile(model_file_path):
        return  # Built-in / Branch B with no fresh codegen / defensive guard.

    from agent_generated._registry import CapabilityMetadata, CapabilityRegistry
    from ml_models.plugin_loader import AGENT_GENERATED_DIR as MODELS_DIR

    model_name = getattr(impl_output, "model_type", None)
    if not model_name:
        print("  Warning: cannot promote model — impl_output.model_type is empty")
        return

    # Branch B reuse path: model_file_path already points at the global
    # directory (the implementor's Branch B short-circuit returns the
    # registry's file_path verbatim). Nothing to copy or update.
    abs_src = os.path.abspath(model_file_path)
    if os.path.dirname(abs_src) == os.path.abspath(MODELS_DIR):
        return

    os.makedirs(MODELS_DIR, exist_ok=True)
    global_dest = os.path.join(MODELS_DIR, f"{model_name}.py")

    # Content-hash dedup: scan existing global plugins for byte-identical
    # content under a different name. Caches src hash to avoid re-reading.
    src_hash = _sha256_file(abs_src)
    for fname in os.listdir(MODELS_DIR):
        if not fname.endswith(".py") or fname.startswith("_"):
            continue
        existing_path = os.path.join(MODELS_DIR, fname)
        if os.path.abspath(existing_path) == os.path.abspath(global_dest):
            continue  # same-name handled by the idempotency branch below
        if _sha256_file(existing_path) == src_hash:
            existing_name = fname[:-3]
            print(
                f"  Model '{model_name}' not promoted — identical content "
                f"already exists as '{existing_name}' "
                f"({global_dest} skipped)."
            )
            return

    if os.path.exists(global_dest):
        print(f"  Model '{model_name}' already at global path {global_dest} (idempotent skip).")
    else:
        shutil.copy2(abs_src, global_dest)
        print(f"  Promoted model '{model_name}' → {global_dest}")

    # Also copy the description.md subdir so the proposer's
    # ``{available_models_block}`` and downstream readers find it at the
    # canonical layout (``agent_generated/models/{name}/description.md``).
    desc_path = getattr(impl_output, "description_file_path", "") or ""
    if desc_path and os.path.isfile(desc_path):
        desc_dest_dir = os.path.join(MODELS_DIR, model_name)
        os.makedirs(desc_dest_dir, exist_ok=True)
        desc_dest = os.path.join(desc_dest_dir, "description.md")
        if not os.path.exists(desc_dest):
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


def run_workflow(
    workspace: str,
    run_name: str,
    # --- Source data: provide either source_paths OR (data_dir + model_types + source_run_name) ---
    source_paths: list[str] | None = None,
    data_dir: str | None = None,
    model_types: list[str] | None = None,
    source_run_name: str | None = None,
    max_iterations: int = 1,
    start_iteration: int = 1,
    max_rounds: int = 10,
    max_proposal_attempts: int = 3,
    target_score: float | None = None,
    file_index: int = 6,
    llm_config: WorkflowLLMConfig | None = None,
    health_checks_config: str | None = None,
    human_advice_interpret: str | None = None,
    human_advice_propose: str | None = None,
    human_advice_implement: str | None = None,
    human_advice_validate: str | None = None,
    human_advice_tune: str | None = None,
    human_advice_mindset: str | None = None,
    # --- Trial mode (optional — defaults preserve single-file behavior) ---
    is_trial: bool = False,
    trial_strategy: StrategyMode = "snapshot",
    trial_portion: float = 0.1,
    target_files: list[int] | None = None,
    train_portion: float = 0.1,
    eval_strategy: StrategyMode = "snapshot",
    eval_portion: float = 0.1,
    train_validation_align: bool = True,
    sampling_seed: int | None = None,
    train_base_seed: int | None = None,
    cleanup_denoised: bool = False,
    max_epochs: int | None = None,
    # Tuner delta-gate parameters (added in commit 8f1cf52). Defaults
    # match the HyperparamTuningInput schema defaults so omitting them
    # at the CLI surface reproduces pre-v16 behaviour.
    skip_formal_min_delta: float = -1.0,
    bypass_formal_time_budget_min_delta: float = 0.0,
    plan_overrides: dict | None = None,
    # --- Time-budget gate (evaluate_time_skill, docs/resource_estimator_implement.md §2.7.2 / Phase I) ---
    trial_time_budget_minutes: float | None = None,
    formal_time_budget_minutes: float | None = None,
    # --- VRAM-budget gate (evaluate_vram_skill, docs/resource_estimator_implement.md §10.9 / Phase K) ---
    # Tuner-only fan-out; no proposer-side gate in Phase K (§10.17).
    trial_vram_budget_gb: float | None = None,
    formal_vram_budget_gb: float | None = None,
    # --- Formal-mode training levers (Phase M, docs §12) + eval scope (Phase R, §13) ---
    # Training-side knobs applied on any round promoted to formal. Formal eval
    # strategy is locked to ``snapshot``; ``formal_eval_portion`` defaults to
    # 1.0 (production full-clone, §12.2) and is operator-controllable for
    # smoke / CI runs that need to fit a tight formal_time_budget_minutes.
    formal_strategy: StrategyMode = "snapshot",
    formal_portion: float = 0.1,
    formal_train_portion: float = 1.0,
    formal_eval_portion: float = 1.0,
    force_formal_round: bool = True,
    formal_round_strategy: FormalRoundStrategy = "full_clone",
    # --- Degenerate-output reaction policy (paired with tuner-side HealthGate evaluation) ---
    degenerate_penalty_score: float | None = None,
    # --- Per-round attempt budget (Phase L, docs/resource_estimator_implement.md §11) ---
    # Tuner-only fan-out (no proposer-side equivalent). Defaults mirror the
    # schema/protocol defaults so omitting them at the workflow surface yields
    # the documented Phase L behaviour.
    attempts_per_round: int = 3,
    attempts_per_formal_round: int = 5,
    max_fail_rounds: int = 3,
    # --- Reasoning pipeline ---
    exploration_mode: ExplorationMode = "auto",
    minimum_boldness: float = 0.05,
    n_candidates: int | None = None,
    # --- Implementation retry ---
    max_impl_attempts: int = 3,
    # --- Phase K.8 debug instrumentation ---
    debug_dump_prompts: bool = False,
    # --- Cross-iter knowledge carry-over (forwarded by chain runner) ---
    # Default None preserves the legacy in-process / first-iter behaviour
    # (static seed init, no accumulated findings). The chain runner
    # (sdsc_submission_scripts/run_one_iteration.py) populates both from
    # RestoredState. See docs/Consistent_growing_vocab_list.md.
    restored_runtime_vocab: list | None = None,
    accumulated_key_findings: list[str] | None = None,
    # --- Cross-iter knowledge-cache carry-over (Commit 6.1.a precondition) ---
    # Latest committed iter's per-model summarisation cache. Default None
    # preserves the in-process / first-iter contract (start with an empty
    # cache; build up across the in-process loop). The chain runner
    # populates this from state.model_knowledge_cache so the Stability
    # Filter at nodes/result_interpretation_agent.py:687-693 can fire in
    # production. See docs/audit_and_optimize_token_usage_and_growth.md
    # Rev 8.3 changelog (Commit 6.1.a).
    restored_model_knowledge_cache: dict | None = None,
    # --- Cross-iter negative-feedback carry-over (V8 hardening Domain 1) ---
    # Same shape as the knowledge carry-over above: chain runner populates
    # both from RestoredState; in-process / first-iter callers leave both at
    # None. The lists are already capped (K=10 each) by core.resume.
    # See docs/V8_Gap_Report.md Domain 1.
    accumulated_physical_rejections: list | None = None,
    accumulated_gate_exhaustions: list | None = None,
    # --- Cross-iter proposal carry-over (G1 bridge, Phase 1 Commit 1.2) ---
    # Latest committed iter's full proposal_iter_NNN.json dict. Chain runner
    # populates this from state.previous_proposal_data so that the local
    # `previous_proposal_data` seed is non-None on the very first round of
    # this iteration — closing the candidate channel that the chain
    # subprocess boundary was darkening. In-process / first-iter callers
    # leave this at None and behaviour is bit-for-bit unchanged.
    # See docs/Consistent_growing_vocab_list.md §10.3.3.
    restored_previous_proposal: dict | None = None,
    # --- Token-usage audit context (Phase 1 Commit 4 — design doc §1.4) ---
    # When both are non-None, every agent constructed inside the iter loop
    # has its bridge bound to (workspace, iter, chain_run_name, run_id) so
    # ``LLMBridge._record_usage`` can append a row to
    # ``{workspace}/token_usage.jsonl``. When either is None, the bind is
    # skipped — bridges keep their default no-op behaviour and no audit
    # rows are written. Legacy / pseudo-mode tests pass None; the
    # production runner (``sdsc_submission_scripts/run_one_iteration.py``
    # via ``run_chain.sh``) generates a ``run_id`` once at startup (or
    # restores it from the ``{workspace}/.token_run_id`` sidecar on iter
    # ≥ 2) and threads both through. See §1.4.1 for the immutability +
    # forward-only contract enforced by the bridge.
    chain_run_name: str | None = None,
    run_id: str | None = None,
    # --- External agents (Commit 6) ---
    # When True, the per-iteration loop fires ``MLLiteratureReviewAgent``
    # between interpretation and proposal, threading its findings +
    # agent_card + suggested_mindset into the proposer via the four
    # external-agent channels (``expert_context`` / ``vocab_seed`` /
    # ``agent_cards`` / ``mindset``). When False (default), the
    # per-iteration loop runs identically to pre-Commit-6 — no
    # ``MLLiteratureReviewAgent`` instantiation, no lit-review LLM
    # calls.
    # The runner ``sdsc_submission_scripts/run_one_iteration.py``
    # resolves ``lit_review_enabled`` from ``--ml_lit_review_enabled``
    # / ``--no-ml_lit_review_enabled`` (CLI) > YAML ``enabled`` >
    # default ``False``. ``lit_review_config_path`` is the YAML to
    # open + parse internally (Design Decision 2, 2026-06-11); defaults
    # to the canonical config, operators can pass
    # ``--ml_lit_review_config /path/to/other.yaml``. The workflow
    # only opens the file when ``lit_review_enabled=True`` — an unused
    # path never hits the filesystem.
    lit_review_enabled: bool = False,
    lit_review_config_path: str = "configs/lit_review_config.yaml",
    # --- Pseudo-mode factories (Stage 3, Commit 4.5) ---
    # Optional class/factory swaps for the LLM bridge and the sandbox.
    # When None (default), each agent uses its built-in production class
    # (``LLMBridge`` and ``TidmadSandbox``). The chain runner sets these
    # to ``StubLLMBridge`` / ``StubSandbox`` when ``--is_pseudo_llm`` /
    # ``--is_pseudo_training`` are passed, enabling a $0-cost wiring smoke
    # without touching the agent code paths. ``bridge_factory`` is
    # threaded into all 5 agents; ``sandbox_factory`` is threaded only
    # into ``HyperparamTuningAgent`` (the only agent that runs training).
    # See ``docs/audit_and_optimize_token_usage_and_growth.md`` Commit 4.5.
    bridge_factory: Callable | None = None,
    sandbox_factory: Callable | None = None,
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
        human_advice_interpret: Human guidance for interpretation steps.
        human_advice_propose: Human guidance for proposal steps.
        human_advice_implement: Human guidance for implementation steps.
        human_advice_validate: Human guidance for validation steps.
        human_advice_tune: Human guidance for tuning steps.
        is_trial: Enable trial mode for the tuning agent.
        trial_strategy: Sampling strategy ('snapshot', 'anchors', 'target').
        trial_portion: Fraction of segments per file for training scope.
        target_files: File indices for 'target' strategy.
        train_portion: Per-epoch subsample from training scope.
        eval_strategy: Sampling strategy for validation.
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
    if llm_config is None:
        llm_config = WorkflowLLMConfig()

    # 52 GB OOM forensics — see _log_rss docstring above.
    _log_rss("post-import (run_workflow entry)")

    # All workflow output goes under {workspace}/{run_name}/
    run_dir = os.path.join(workspace, run_name)
    os.makedirs(run_dir, exist_ok=True)
    _snapshot_task_config(run_dir)
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")

    # Anchor SIDERIUS_CHAIN_WORKSPACE for in-process / single-iteration
    # callers (e.g. integration smoke tests, ad-hoc workflow invocations).
    # ml_models.model_descriptions.get_model_description reads this env var
    # to walk {workspace}/plugins/*/{model_type}/description.md and resolve
    # agent-generated plugin descriptions on iter > 1. The chain entry
    # script (run_one_iteration.py) sets it earlier; only override here
    # when unset so chain mode keeps precedence.
    os.environ.setdefault("SIDERIUS_CHAIN_WORKSPACE", os.path.abspath(workspace))

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
    # L6c — preload promoted losses into the in-memory LOSS_REGISTRY so
    # cross-process Branch B reuse (chain resume after restart) resolves
    # without depending on SIDERIUS_LOSS_DIRS. Safe to call when
    # agent_generated/losses/ is empty (returns []). See
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
    if source_paths is not None:
        print(f"  Source paths  : {len(source_paths)} files")
        for p in source_paths:
            print(f"    - {p}")
    else:
        print(f"  Source run    : {source_run_name}")
        print(f"  Models        : {model_types}")
    print(f"  Workspace     : {workspace}")
    print(f"  Run name      : {run_name}")
    print(f"  LLM config    : {llm_config.model_dump(exclude_none=True)}")
    print(f"  Iterations    : {max_iterations} (starting at {start_iteration})")
    print(f"  Tune rounds   : {max_rounds} per iteration")
    print(f"  Proposal tries: {max_proposal_attempts} per iteration")
    if target_score is not None:
        print(f"  Target score  : {target_score}")
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
        trial_vram_budget_gb if trial_vram_budget_gb is not None else formal_vram_budget_gb
    )
    print(
        f"  Hardware      : {hardware_ctx.device_name} "
        f"({hardware_ctx.total_memory_gb:.2f} GB total, "
        f"{hardware_ctx.usable_cap_gb:.2f} GB usable cap), "
        f"budget={active_vram_budget_gb} GB\n"
    )

    # --- Step 0: Load existing tuning outputs ---
    print("Step 0: Loading existing tuning outputs...")
    if source_paths is not None:
        tuning_outputs = load_tuning_outputs_from_paths(source_paths)
    elif data_dir and model_types and source_run_name:
        tuning_outputs = load_tuning_outputs(data_dir, model_types, source_run_name)
    else:
        raise ValueError(
            "Must provide either source_paths OR (data_dir + model_types + source_run_name)."
        )
    seed_summaries = tuning_outputs_to_summaries(tuning_outputs)
    print(
        f"  Loaded {len(tuning_outputs)} tuning outputs "
        f"across {len(set(o.model_type for o in tuning_outputs))} model types.\n"
    )

    # Track all model types seen (for duplicate name guard)
    all_model_types = list({o.model_type for o in tuning_outputs})

    # --- Load vocabulary seed + reasoning pipeline config ---
    vocab_seed = _load_vocab_seed()
    reasoning_pipeline = _get_reasoning_pipeline(
        llm_config,
        exploration_mode=exploration_mode,
        minimum_boldness=minimum_boldness,
        n_candidates=n_candidates,
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

    # Collect results across iterations
    iteration_results: list[HyperparamTuningOutput] = []
    best_score_overall: float | None = None

    # Long-term memory: variables carried forward across iterations.
    # Chain mode: seed from `restored_previous_proposal` (forwarded by
    # `sdsc_submission_scripts/run_one_iteration.py` from
    # `RestoredState.previous_proposal_data`) so the candidate channel
    # survives the subprocess boundary. In-process / first-iter callers
    # pass None and the local update at line ~1217 takes over after iter 1.
    # See docs/Consistent_growing_vocab_list.md §10.3.3.
    previous_proposal_data: dict | None = (
        restored_previous_proposal  # serialized ProposalOutput from iter N-1
    )
    # Priority: chain-restored runtime_vocab > static seed. The static seed
    # is the first-iter bootstrap; once any iter has run, the latest
    # committed iter's runtime_vocab is the source of truth (already merged
    # with the seed via build_runtime_vocab on each prior iter). Without
    # this priority check, every chain iter resets to the 21-entry seed —
    # see docs/Consistent_growing_vocab_list.md §1.2 for the empirical bug.
    if restored_runtime_vocab:
        current_runtime_vocab = [
            v if hasattr(v, "name") else VocabEntry.model_validate(v)
            for v in restored_runtime_vocab
        ]
        print(
            f"  Vocab restored from prior chain iters: "
            f"{len(current_runtime_vocab)} entries "
            f"({sum(1 for v in current_runtime_vocab if v.kind == 'discovery')} discoveries)"
        )
    else:
        current_runtime_vocab = list(vocab_seed)  # first iter or in-process run
    # Per-model Phase 1 cache (grows once per model). Commit 6.1.a — chain
    # mode forwards the latest committed iter's cache via
    # restored_model_knowledge_cache so the cache-hit branch at
    # nodes/result_interpretation_agent.py:687-693 can fire across the
    # subprocess boundary. In-process / first-iter callers pass None and
    # behaviour is unchanged. Defensive copy: the workflow mutates the dict
    # in place at iter end; we don't want to alias the caller's reference.
    model_knowledge_cache: dict = (
        dict(restored_model_knowledge_cache) if restored_model_knowledge_cache else {}
    )
    if model_knowledge_cache:
        _cache_keys_preview = sorted(model_knowledge_cache)[:5]
        print(
            f"  Knowledge cache restored from prior chain iter: "
            f"{len(model_knowledge_cache)} entries "
            f"({_cache_keys_preview}"
            f"{'...' if len(model_knowledge_cache) > 5 else ''})"
        )
    latest_new_summary = None  # ModelRunSummary from the most recent tune
    # Phase N (§14.N) — bounded FIFO of the last 3 tuner outputs so the
    # interp→propose protocol can surface their gate_exhaustion summaries
    # (oldest-first) to the next proposer as the aggregate-window
    # [RECENT GATE EXHAUSTIONS] block. Empty on iteration 1; each iter-end
    # append auto-evicts the oldest when len > 3.
    recent_tune_outputs: deque[HyperparamTuningOutput] = deque(maxlen=3)

    # V8 Domain 1 — pre-populate the deque with synthetic HyperparamTuningOutput
    # wrappers carrying ONLY the prior chain iters' gate_exhaustions. Without
    # this, every chain-mode subprocess starts with an empty deque (max_iterations=1
    # means the in-process append at iter-end never feeds the same-subprocess
    # proposer). The protocol reads only `.gate_exhaustion` from each entry,
    # so placeholder values for the other required fields are safe.
    # See docs/V8_Gap_Report.md Domain 1.
    if accumulated_gate_exhaustions:
        for _ge in accumulated_gate_exhaustions:
            recent_tune_outputs.append(_synthetic_prior_iter_tune_output(_ge))
        print(
            f"  [chain] Pre-seeded recent_tune_outputs with "
            f"{len(recent_tune_outputs)} cross-iter gate-exhaustion summary"
            f"{'y' if len(recent_tune_outputs) == 1 else 'ies'} "
            f"(deque maxlen=3 keeps the latest)."
        )

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
        if chain_run_name is None or run_id is None:
            return
        kwargs = dict(
            workspace=_Path(workspace),
            iter=iteration,
            run_name=chain_run_name,
            run_id=run_id,
        )
        if hasattr(agent, "set_run_context") and not hasattr(agent, "bridge"):
            agent.set_run_context(**kwargs)
        elif hasattr(agent, "bridge") and agent.bridge is not None:
            agent.bridge.set_run_context(**kwargs)

    # Chain mode runs each iter as its own subprocess with max_iterations=1 and
    # an externally-supplied start_iteration. The loop variable becomes the
    # canonical chain-wide iteration index — it is what the InterpretationInput
    # carries (line below) and therefore what the evolution_log.jsonl writer
    # in nodes.result_interpretation_agent stamps on every row. Without this
    # offset, every chain iter would log iteration=1 (V8 Domain 3 bug).
    for iteration in range(start_iteration, start_iteration + max_iterations):
        iter_dir = os.path.join(run_dir, f"iteration_{iteration:03d}")
        os.makedirs(iter_dir, exist_ok=True)

        loop_pos = iteration - start_iteration + 1
        print(f"\n{'=' * 60}")
        print(f"  ITERATION {iteration} ({loop_pos}/{max_iterations})")
        print(f"  Directory: {iter_dir}")
        print(f"{'=' * 60}\n")

        # Fix 4 — parent-process memory probe at iteration entry.
        # See docs/optimize_inference_and_scoring.md §3 Fix 4.
        probe_memory(iter_idx=iteration, phase="start", workspace=workspace, scope="workflow")

        # --- Interpret (once per iteration) ---
        # First iter in this subprocess: all seeds are new (cache is empty).
        # Subsequent iters: only the model tuned in the previous iteration is
        # new. ``iteration == start_iteration`` is the chain-aware predicate
        # — chain-mode subprocesses run with ``start_iteration > 1``, but the
        # local "first iter in this subprocess" semantics still hold because
        # the seeds are loaded fresh per subprocess.
        if iteration == start_iteration:
            new_summaries = seed_summaries
        else:
            new_summaries = [latest_new_summary] if latest_new_summary is not None else []

        interp_storage = _make_storage(iter_dir, run_name)
        interp_input = InterpretationInput(
            summaries=new_summaries,
            model_knowledge_cache=model_knowledge_cache,
            human_advice=human_advice_interpret,
            runtime_vocab=current_runtime_vocab,
            previous_proposal=previous_proposal_data,
            storage=interp_storage,
            iteration=iteration,
            # T4b — task config injection. Substituted into the
            # {TASK_DESCRIPTION} placeholder in PER_MODEL_SYSTEM_PROMPT +
            # SYNTHESIS_SYSTEM_PROMPT at call time.
            # See docs/design/enable_global_task_config.md § Commit T4.
            task_description=get_task_description(load_task_config()),
        )

        print(f"  [{iteration}] Interpreting experiment results...")
        _interp_agent = ResultInterpretationAgent(
            **llm_config.get("interpret"),
            bridge_factory=bridge_factory,
        )
        _bind_iter_context(_interp_agent)
        interpretation = _interp_agent.run(interp_input)
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
        if should_run_literature_review(interpretation, enabled=lit_review_enabled):
            yaml_path = lit_review_config_path
            if not os.path.isabs(yaml_path):
                yaml_path = os.path.join(SIDERIUS_ROOT, yaml_path)
            print(f"  [{iteration}] Running lit-review (config: {yaml_path})...")
            with open(yaml_path, encoding="utf-8") as _f:
                lit_review_config = yaml.safe_load(_f)
            lit_storage = _make_storage(iter_dir, run_name)
            lit_input = _build_lit_review_input(
                lit_review_config,
                interpretation,
                llm_kwargs=llm_config.get("lit_review"),
                storage=lit_storage,
                run_name=run_name,
            )
            lit_agent = MLLiteratureReviewAgent(bridge_factory=bridge_factory)
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
        if iteration == start_iteration and accumulated_physical_rejections:
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
        if iteration_results:
            _prior = iteration_results[-1]
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

        for attempt in range(1, max_proposal_attempts + 1):
            print(
                f"  [{iteration}.{attempt}] Proposing new model (attempt {attempt}/{max_proposal_attempts})..."
            )

            # Create a temporary attempt dir; renamed after model name is known
            attempt_dir = os.path.join(iter_dir, f"attempt_{attempt:03d}")
            os.makedirs(attempt_dir, exist_ok=True)
            attempt_storage = _make_storage(attempt_dir, run_name)

            # Surface ALL prior iters' key_findings to the proposer as a
            # single ExpertContextItem. Without this, the proposer sees only
            # the current iter's interpretation.key_findings; chain-mode
            # amnesia drops everything before iter N-1. The accumulated
            # union is built once by core.resume.load_latest_knowledge and
            # forwarded by the chain runner. See
            # docs/Consistent_growing_vocab_list.md §3.3.4.
            expert_context_for_propose: list[ExpertContextItem] = []
            if accumulated_key_findings:
                bullet_block = "\n".join(f"- {kf}" for kf in accumulated_key_findings)
                expert_context_for_propose.append(
                    ExpertContextItem(
                        source="prior_iters",
                        kind="findings",
                        content=(
                            f"Accumulated key findings from "
                            f"{len(accumulated_key_findings)} prior iter(s):\n"
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
                    vocab_seed=vocab_seed + external_channels["vocab_seed"],
                    agent_cards=external_channels["agent_cards"],
                    mindset=external_channels["mindset"],
                    reasoning_pipeline=reasoning_pipeline,
                    human_advice=human_advice_propose,
                    is_trial=is_trial,
                    trial_strategy=trial_strategy,
                    trial_portion=trial_portion,
                    target_files=target_files,
                    train_portion=train_portion,
                    sampling_seed=sampling_seed,
                    trial_time_budget_minutes=trial_time_budget_minutes,
                    formal_time_budget_minutes=formal_time_budget_minutes,
                    data_dir=data_dir,
                    recent_tune_outputs=list(recent_tune_outputs),
                )
                propose_input.existing_model_types = list(all_model_types)
                # Task config injection (T3) — same pattern as T2's implementor
                # injection. The loader is cached per-process so this is a dict
                # lookup after the first iter. See
                # docs/design/enable_global_task_config.md § Commit T3.
                _task_cfg = load_task_config()
                propose_input.task_description = get_task_description(_task_cfg)
                propose_input.forward_contract = ForwardContract(**_task_cfg["forward_contract"])
                if previous_failures:
                    propose_input.previous_failures = previous_failures
                if human_advice_mindset is not None:
                    propose_input.mindset = human_advice_mindset
                # WS-B B.1 — hardware-context plumb-through. Both fields
                # always set (None is a valid value for vram_budget_gb);
                # the Proposer renderer decides whether to emit the block.
                propose_input.hardware_context = hardware_ctx
                propose_input.vram_budget_gb = active_vram_budget_gb

                # Phase K.8 debug — dump rendered proposing-stage system
                # prompt under {run_dir}/debug/ when the flag is on.
                if debug_dump_prompts:
                    propose_input.debug_dump_proposing_prompt_path = os.path.join(
                        run_dir,
                        "debug",
                        f"iter{iteration:03d}_attempt{attempt:03d}_proposing_system_prompt.md",
                    )

                _propose_agent = MLModelProposalAgent(
                    **llm_config.get("propose"),
                    bridge_factory=bridge_factory,
                )
                _bind_iter_context(_propose_agent)
                proposal = _propose_agent.run(propose_input)
                print(f"    Proposed: {proposal.model_name}")
                _log_rss(f"post-proposal (iter {iteration} attempt {attempt})")

                # Rename attempt dir to include model name
                named_dir = os.path.join(iter_dir, f"attempt_{attempt:03d}_{proposal.model_name}")
                os.rename(attempt_dir, named_dir)
                attempt_dir = named_dir
                attempt_storage = _make_storage(attempt_dir, run_name)

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

                valid_llm = llm_config.get("validate")
                previous_validation_failure: str | None = None

                for impl_attempt in range(1, max_impl_attempts + 1):
                    impl_suffix = (
                        f" (impl {impl_attempt}/{max_impl_attempts})"
                        if max_impl_attempts > 1
                        else ""
                    )
                    print(f"  [{iteration}.{attempt}] Implementing{impl_suffix}...")
                    impl_input = local_full_spec(proposal, attempt_storage)
                    impl_input.plugin_dir = os.path.join(attempt_dir, "models")
                    impl_input.test_dir = os.path.join(attempt_dir, "tests")
                    # L4b — loss-plugin staging directory. Mirrors plugin_dir
                    # for run-scoped isolation. Concurrent iterations write
                    # to disjoint dirs so no clobbering occurs. The sandbox
                    # executor adds this to SIDERIUS_LOSS_DIRS at training
                    # time so load_loss_plugin can find the freshly-written
                    # plugin. See docs/design/enable_loss_inventory.md § L4.
                    impl_input.loss_dir = os.path.join(attempt_dir, "losses")
                    # Task config injection (T2) — load + thread into the
                    # implementor input. The loader is cached per-process so
                    # this is a dict lookup after the first iter. See
                    # docs/design/enable_global_task_config.md § Commit T2.
                    _task_cfg = load_task_config()
                    impl_input.task_description = get_task_description(_task_cfg)
                    impl_input.forward_contract = ForwardContract(**_task_cfg["forward_contract"])
                    if human_advice_implement is not None:
                        impl_input.human_advice = human_advice_implement
                    if ref_code:
                        impl_input.reference_code = ref_code
                    if previous_validation_failure is not None:
                        impl_input.previous_validation_failure = previous_validation_failure

                    _impl_agent = MLModelImplementor(
                        **llm_config.get("implement"),
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
                        attempt_storage,
                        llm_provider=valid_llm.get("provider", "gemini"),
                        llm_model_id=valid_llm.get("model_id", "gemini-3.1-flash-lite-preview"),
                    )
                    if human_advice_validate is not None:
                        valid_input.human_advice = human_advice_validate
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
                            from ml_models.plugin_loader import (
                                register_model_in_memory,
                            )

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
                    if impl_attempt < max_impl_attempts:
                        print("    Retrying implementation with validator feedback...\n")

                if validation and validation.passed:
                    break

                # All impl attempts for this proposal exhausted
                previous_failures.append(previous_validation_failure or "Unknown error")
                if attempt < max_proposal_attempts:
                    print("    Retrying with a new proposal...\n")

            except Exception as e:
                error_msg = f"Node error: {type(e).__name__}: {e}"
                print(f"    ERROR: {error_msg}")
                previous_failures.append(error_msg)
                if attempt < max_proposal_attempts:
                    print("    Retrying with failure feedback...\n")

        if not validation or not validation.passed:
            print(
                f"\n  Iteration {iteration}: exhausted {max_proposal_attempts} proposal "
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
        tuning_storage = _make_storage(tuning_dir, run_name)

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

        tuner_plugin_dir = get_plugin_dir(tuning_dir, run_name)
        chain_plugin_dir = get_plugin_dir(workspace, run_name)
        # L6a — loss-plugin propagation mirrors the model-plugin pattern.
        # Tuner-scoped dir must match ``TidmadSandbox.loss_dir`` (computed
        # from the sandbox's own workspace ≈ ``tuning_dir``) so the
        # subprocess's ``SIDERIUS_LOSS_DIRS`` resolves the plugin.
        # Chain-canonical dir preserves the file for resume / future-iter
        # Branch B lookups. See docs/design/enable_loss_inventory.md § L6.
        tuner_loss_dir = get_loss_dir(tuning_dir, run_name)
        chain_loss_dir = get_loss_dir(workspace, run_name)
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

        print(f"  [{iteration}] Tuning '{proposal.model_name}' for {max_rounds} rounds...")
        tune_llm = llm_config.get("tune")
        tune_input = local_validated_model(
            validation,
            proposal,
            tuning_storage,
            max_rounds=max_rounds,
            health_checks_config=health_checks_config,
            file_index=file_index,
            llm_provider=tune_llm.get("provider", "gemini"),
            llm_model_id=tune_llm.get("model_id", "gemini-3.1-flash-lite-preview"),
            reflect_provider=tune_llm.get("reflect_provider"),
            reflect_model_id=tune_llm.get("reflect_model_id"),
            is_trial=is_trial,
            trial_strategy=trial_strategy,
            trial_portion=trial_portion,
            target_files=target_files,
            train_portion=train_portion,
            eval_strategy=eval_strategy,
            eval_portion=eval_portion,
            train_validation_align=train_validation_align,
            sampling_seed=sampling_seed,
            train_base_seed=train_base_seed,
            cleanup_denoised=cleanup_denoised,
            max_epochs=max_epochs,
            skip_formal_min_delta=skip_formal_min_delta,
            bypass_formal_time_budget_min_delta=bypass_formal_time_budget_min_delta,
            max_retries=tune_llm.get("max_retries"),
            plan_overrides=plan_overrides,
            trial_time_budget_minutes=trial_time_budget_minutes,
            formal_time_budget_minutes=formal_time_budget_minutes,
            data_dir=data_dir,
            trial_vram_budget_gb=trial_vram_budget_gb,
            formal_vram_budget_gb=formal_vram_budget_gb,
            formal_strategy=formal_strategy,
            formal_portion=formal_portion,
            formal_train_portion=formal_train_portion,
            formal_eval_portion=formal_eval_portion,
            force_formal_round=force_formal_round,
            formal_round_strategy=formal_round_strategy,
            degenerate_penalty_score=degenerate_penalty_score,
            attempts_per_round=attempts_per_round,
            attempts_per_formal_round=attempts_per_formal_round,
            max_fail_rounds=max_fail_rounds,
        )
        if human_advice_tune is not None:
            tune_input.human_advice = human_advice_tune
        # Task config injection (T4a) — substituted into the {TASK_DESCRIPTION}
        # placeholder in PLANNER_PROMPT via brain.plan(task_description=...).
        # See docs/design/enable_global_task_config.md § Commit T4a.
        tune_input.task_description = get_task_description(load_task_config())
        # Post-v15 delta-gate threading: tell the tuner the best score this
        # chain run has seen so far. Both the skip_formal and
        # bypass_formal_time_budget gates inside the tuner use this as the
        # reference point. ``best_score_overall`` reflects the workflow's
        # best ``tune_output.best_denoising_score`` across iterations
        # (formal-dominated under inherit_best_trial / full_clone, which is
        # the production default — see workflows/model_exploration.py:
        # 2134-2137). When no iter has completed yet, the schema default
        # (V17 fixed reference 0.0) applies, so iter_001's gates have a
        # meaningful anchor too. NOTE: 5.5763 is intentionally NOT the
        # default — it is the class-127 mode-collapse fingerprint (SNR=2^17
        # FP artifact), see docs/design/pluggable_health_checks.md §7.1.
        if best_score_overall is not None:
            tune_input.current_run_best_formal_score = best_score_overall

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
        iteration_results.append(tune_output)

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
        recent_tune_outputs.append(tune_output)

        # --- Update long-term memory for next iteration ---
        all_model_types.append(proposal.model_name)

        # Build ModelRunSummary for the newly tuned model (fed to iter N+1 as new_summaries)
        new_model_summaries = tuning_outputs_to_summaries([tune_output])
        for s in new_model_summaries:
            # Attach description so iter N+1 interpretation agent can find it
            # without filesystem access to the attempt directory
            s.model_description = proposal.model_description
        latest_new_summary = new_model_summaries[0]

        # Update knowledge cache from interpretation output
        if (
            hasattr(interpretation, "model_knowledge_cache")
            and interpretation.model_knowledge_cache
        ):
            model_knowledge_cache = dict(interpretation.model_knowledge_cache)
            model_knowledge_cache, evicted = _cap_knowledge_cache(
                model_knowledge_cache,
                current_model=proposal.model_name,
            )
            if evicted:
                print(
                    f"  [{iteration}] Cache capped: evicted {sorted(evicted)}, "
                    f"kept {len(model_knowledge_cache)} entries."
                )
            print(f"  [{iteration}] Knowledge cache: {len(model_knowledge_cache)} models cached.")

        # Update runtime vocab from interpretation output
        previous_proposal_data = proposal.model_dump()
        if hasattr(interpretation, "runtime_vocab") and interpretation.runtime_vocab:
            current_runtime_vocab = [
                v if hasattr(v, "name") else VocabEntry.model_validate(v)
                for v in interpretation.runtime_vocab
            ]
            print(
                f"  [{iteration}] Vocab updated: {len(current_runtime_vocab)} entries "
                f"({sum(1 for v in current_runtime_vocab if v.kind == 'discovery')} discoveries)"
            )

        # --- Check score target ---
        # ``best_score_overall`` is the reference for the next iter's
        # ``current_run_best_formal_score`` (the anchor for both
        # ``skip_formal_min_delta`` and ``bypass_formal_time_budget_min_delta``).
        # It must track FORMAL scores only — a noisy trial score from an iter
        # whose formal rounds all got gated would otherwise poison every
        # downstream gate decision. Falling back to ``best_denoising_score``
        # (the all-rounds max) is exactly what motivated this fix: v15's
        # mamba_multirate_fuser (trial 7.65) and dualpath_spectral_router
        # (trial 7.77) had every formal attempt time-gated, and under the
        # old logic their trial scores would have become the v16 anchor.
        if tune_output.best_formal_denoising_score is not None and (
            best_score_overall is None
            or tune_output.best_formal_denoising_score > best_score_overall
        ):
            best_score_overall = tune_output.best_formal_denoising_score

        print(
            f"\n  [{iteration}] Complete: {proposal.model_name} "
            f"best_score={tune_output.best_denoising_score}"
        )

        # Fix 4 — parent-process memory probe at iteration exit. Fires
        # even on the iteration that triggers the target-score break
        # (placed before the break check) so the last iteration's
        # terminal RSS is always logged.
        probe_memory(iter_idx=iteration, phase="end", workspace=workspace, scope="workflow")

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
        probe_memory(iter_idx=iteration, phase="post_gc", workspace=workspace, scope="workflow")

        if (
            target_score is not None
            and best_score_overall is not None
            and best_score_overall >= target_score
        ):
            print(
                f"\n  Target score {target_score} reached "
                f"(best={best_score_overall}). Stopping early."
            )
            break

    # --- Final summary ---
    finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'=' * 60}")
    print("  Workflow Complete")
    print(f"  Started     : {started_at}")
    print(f"  Finished    : {finished_at}")
    print(f"  Iterations  : {len(iteration_results)}/{max_iterations}")
    print(f"  Best overall: {best_score_overall}")
    for i, result in enumerate(iteration_results, 1):
        print(f"    Iteration {i}: {result.model_type} score={result.best_denoising_score}")
    print(f"{'=' * 60}\n")

    _save_workflow_summary(
        run_dir,
        run_name,
        started_at,
        finished_at,
        iteration_results,
        best_score_overall,
    )

    return iteration_results


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
        default=None,
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
    args = parser.parse_args()

    if args.data_dir is None:
        from execute_tools.data_paths import SIDERIUS_DATA_DIR

        args.data_dir = SIDERIUS_DATA_DIR

    # Build LLM config: --llm_config file takes precedence, then --provider/--model_id
    if args.llm_config:
        wf_llm_config = WorkflowLLMConfig.from_json(args.llm_config)
    elif args.provider and args.model_id:
        wf_llm_config = WorkflowLLMConfig.uniform(args.provider, args.model_id)
    elif args.provider:
        wf_llm_config = WorkflowLLMConfig.uniform(args.provider, "gemini-3.1-flash-lite-preview")
    else:
        wf_llm_config = None  # each node uses its own default

    run_workflow(
        data_dir=args.data_dir,
        model_types=args.models,
        source_run_name=args.source_run_name,
        workspace=args.workspace,
        run_name=args.run_name,
        max_iterations=args.max_iterations,
        max_rounds=args.max_rounds,
        max_proposal_attempts=args.max_proposal_attempts,
        target_score=args.target_score,
        file_index=args.file_index,
        llm_config=wf_llm_config,
        human_advice_interpret=args.advice_interpret,
        human_advice_propose=args.advice_propose,
        human_advice_implement=args.advice_implement,
        human_advice_validate=args.advice_validate,
        human_advice_tune=args.advice_tune,
    )


if __name__ == "__main__":
    main()
