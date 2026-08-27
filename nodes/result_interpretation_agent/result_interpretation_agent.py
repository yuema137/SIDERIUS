# nodes/result_interpretation_agent/result_interpretation_agent.py
"""
result_interpretation_agent — Node 2 in the SIDERIUS graph.

Two-phase interpretation:
  Phase 1 — Per-model summarization: one LLM call per model type, receiving
            the condensed ModelRunSummary (scores, trajectory, conclusions)
            — NOT raw experiment records.
  Phase 2 — Cross-model synthesis: one LLM call consuming all per-model
            summaries to produce the final interpretation.

Node contract:
  run(input: InterpretationInput) -> InterpretationOutput
  CLI: --workspace, --run_name, --model_type, --provider, --model_id
"""

import argparse
import json
import os
from typing import TYPE_CHECKING, Any, cast

from pydantic import ValidationError

from agent.cache_consolidator import consolidate
from agent.llm_bridge import LLMBridge
from agent.prompt_templates.interpretation.rendering import (
    DEDUP_SYSTEM_PROMPT,
    _build_dedup_prompt,
    _build_per_model_prompt,
    _build_per_model_system_prompt,
    _build_synthesis_prompt,
    _build_synthesis_system_prompt,
    _flatten_entry_for_prompt,
)
from agent.schemas.cache_entry import CacheEntry
from agent.schemas.health_feedback import merge_fingerprint_history
from agent.schemas.hyperparam_tuning import serialize_expert_advice
from agent.schemas.interpretation import (
    InterpretationInput,
    InterpretationOutput,
    MetricIdentity,
    SecondaryMetricEvidence,
)
from agent.schemas.storage import LocalStorageConfig, StorageConfig
from execute_tools.metric_order import MetricOrder
from ml_models.model_descriptions import get_model_description

# Node-private modules (Step 09a C1b). Imported EAGERLY and at module scope on
# purpose: `__init__.py` rebinds `sys.modules["nodes.result_interpretation_agent"]`
# to THIS module, so after that rebind the package path has no `__path__` and a
# lazy `import nodes.result_interpretation_agent.evidence` would fail. Binding
# them while `__init__` is still executing puts each submodule in `sys.modules`
# for good. (Same rule the tuner's C7 decomposition follows.)
from nodes.result_interpretation_agent.evidence import (
    InterpretationContractError,
    _collect_health_evidence,
    _required_denoising_score,
    _round_health,
    _round_ordering,
    reconcile_metric_spec,
    tuning_output_to_model_run_summary,
)
from nodes.result_interpretation_agent.ordering import (
    bind_run_order,
    collect_enriched_fields,
    precompute_evidence,
)
from nodes.result_interpretation_agent.prediction import (
    PREDICTION_SEMANTICS_LEGACY_V1,
    PREDICTION_SEMANTICS_SIGNSAFE_V2,
    accumulate_information_gain,
    accumulate_prediction_outcomes,
    evaluate_prediction,
    prediction_pool_sizes,
)

if TYPE_CHECKING:
    from agent.schemas.proposal import VocabEntry

__all__ = [
    "InterpretationContractError",
    "ResultInterpretationAgent",
    "main",
    "reconcile_metric_spec",
    "tuning_output_to_model_run_summary",
]

#: COMPATIBILITY ONLY — not part of the node's contract.
#:
#: C1b moved these helpers into the node-local submodules. They are re-exported
#: here because the package `__init__` and a body of tests reach them at this
#: path, and because `mock.patch("nodes.result_interpretation_agent.X")` must
#: keep resolving to the object production actually calls.
#:
#: They are NOT documented in result_interpretation_agent.md, they are NOT a
#: promise to callers, and NO new production consumer may be added: import the
#: owning submodule from inside the node instead. The list is expected to
#: shrink, never grow.
#:
#: Listing them here also KEEPS them alive: without a reference the linter
#: prunes the re-export and the package `__init__` fails at import.
_COMPATIBILITY_REEXPORTS = (
    _collect_health_evidence,
    _required_denoising_score,
    _round_health,
    _round_ordering,
    accumulate_information_gain,
    accumulate_prediction_outcomes,
    collect_enriched_fields,
    evaluate_prediction,
    precompute_evidence,
)


# ---------------------------------------------------------------------------
# V8 hardening Domain 3 — Evolution observability
# ---------------------------------------------------------------------------


def _resolve_evolution_log_root(agent_workspace: str) -> str:
    """Resolve the chain-root directory where evolution_log.jsonl lives.

    In chain mode, run_one_iteration.py sets SIDERIUS_CHAIN_WORKSPACE to the
    chain root (one level above the per-iter dir given to the agent), so the
    log accumulates across iters at a single tail-able path. In single-process
    mode the env var is unset and we fall back to the agent's own workspace.
    """
    return os.environ.get("SIDERIUS_CHAIN_WORKSPACE", agent_workspace)


def _compute_evolution_stats(
    runtime_vocab: list[Any],
    promoted_this_iter: int,
    is_degraded: bool,
) -> dict[str, int | bool]:
    """Snapshot vocab counts + promotion + degraded flag.

    `promoted_this_iter` is the count returned by promote_candidates() this
    iter — entries that crossed the Tested-only threshold (seen_in_runs >= 3
    distinct actually-tried runs). It excludes any vocab additions from
    new_discoveries or proposed_candidates that are still in the candidate
    tier.
    """
    canonical = sum(
        1 for v in runtime_vocab if (v.tier if hasattr(v, "tier") else v.get("tier")) == "canonical"
    )
    candidate = sum(
        1 for v in runtime_vocab if (v.tier if hasattr(v, "tier") else v.get("tier")) == "candidate"
    )
    return {
        "vocab_total": len(runtime_vocab),
        "vocab_canonical": canonical,
        "vocab_candidate": candidate,
        "promoted_this_iter": promoted_this_iter,
        "is_degraded": is_degraded,
    }


def _append_evolution_log(workspace_root: str, payload: dict[str, Any]) -> None:
    """Append one JSON line to {workspace_root}/evolution_log.jsonl.

    Append-only: the file is created on first call (iteration 1 of a new
    workspace) and grown on subsequent iters. Each line is a self-contained
    JSON object so `tail -f` shows complete rows. Any IO error is logged but
    swallowed — observability must never break the pipeline.
    """
    import datetime

    log_path = os.path.join(workspace_root, "evolution_log.jsonl")
    line = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        **payload,
    }
    try:
        os.makedirs(workspace_root, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, default=str) + "\n")
    except Exception as e:
        print(f"  [evolution_log] WARN: failed to append to {log_path}: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------


class ResultInterpretationAgent:
    def __init__(
        self,
        provider: str = "gemini",
        model_id: str = "gemini-3.1-flash-lite-preview",
        max_retries: int | None = None,
        bridge_factory=None,
        **kwargs,
    ):
        self._bridge_factory = bridge_factory or LLMBridge
        self.bridge = self._bridge_factory(
            provider=provider, model_id=model_id, max_retries=max_retries
        )

    def run(self, inp: InterpretationInput) -> InterpretationOutput:
        # --- Cold-start branch (explicit workflow state) ---
        # A cold start is the first iteration of a chain with NO prior
        # experimental evidence. There is nothing to interpret or rank, so emit
        # a deterministic "no prior evidence" interpretation (no LLM call, no
        # fabricated history). We branch on the EXPLICIT inp.cold_start flag set
        # by the workflow — never inferred here from empty summaries. Registries
        # remain the proposer's concern (available options), so model_types and
        # model_descriptions are intentionally left empty.
        if inp.cold_start:
            return InterpretationOutput(
                model_types=[],
                model_descriptions={},
                total_experiments=0,
                key_findings=[
                    "Cold start: no prior experimental runs or score history exist yet.",
                ],
                bottlenecks=[],
                take_home_message=(
                    "This is a cold start — there is no prior experimental evidence. "
                    "Propose the first experiment from the task description, the "
                    "available model/loss registries (as options, not results), "
                    "advice, and resource constraints. Do not claim improvement "
                    "over prior runs; none exist."
                ),
                runtime_vocab=inp.runtime_vocab,
                # Step 10 / P5+P6 C2, DD-2 — carry the confirmation map through,
                # exactly as the degraded branch below does. Without this the
                # cold-start branch omits the field, the schema default `{}`
                # wins, and the workflow's loop closure (which reads the output
                # unconditionally) would CLOBBER a restored non-empty mapping.
                # Whether that state is reachable depends on a distant workflow
                # condition; making the three branches symmetric makes the
                # closure safe by LOCAL construction instead. Digest bytes are
                # unchanged for every pre-P5 caller, whose input is always `{}`.
                vocab_link_confirmations=dict(inp.vocab_link_confirmations),
                cold_start=True,
                # V19 PR 3 — the deterministic merge runs on every path
                # (a cold start has no summaries, so this is retention
                # applied to the carried history — normally empty).
                collapse_fingerprint_history=merge_fingerprint_history(
                    inp.collapse_fingerprint_history,
                    {},
                    inp.iteration,
                    inp.health_feedback_retention_policy(),
                ),
            )

        # --- Bind the run's ordering authority (Step 09a C2) ---
        # ONE MetricOrder for the whole iteration, from the spec the run
        # already resolved and transported. `None` only where the input
        # contract admitted a spec-less input (cold start / scoreless); a
        # score-bearing input without a spec was refused at construction, so
        # nothing below can silently fall back to "higher is better".
        run_order = bind_run_order(inp)

        def _require_order(what: str) -> MetricOrder:
            """The bound order, or a refusal naming what needed it.

            ``run_order`` is ``None`` only on the cold-start / scoreless path
            the contract admits. Anything below that actually ranks says so.
            """
            if run_order is None:
                raise InterpretationContractError(
                    f"{what} requires the run's MetricOrder, but this input was admitted "
                    "without a MetricSpec (cold start / scoreless). Refusing rather than "
                    "assuming a direction."
                )
            return run_order

        def _require_metric_identity(what: str) -> MetricIdentity:
            """The bound metric's identity, or a refusal naming what needed it.

            Step 09a C4: a NEW prediction's default metric is the run's bound
            id — never the literal ``denoising_score``, which was one task's
            name hardcoded in the framework.
            """
            if run_metric_identity is None:
                raise InterpretationContractError(
                    f"{what} requires the run's bound metric identity, but this input "
                    "was admitted without a MetricSpec (cold start / scoreless)."
                )
            return run_metric_identity

        run_metric_identity = (
            MetricIdentity(metric_id=inp.metric_spec.id, direction=inp.metric_spec.direction)
            if inp.metric_spec is not None
            else None
        )

        # --- Effective model types ---
        # Union of: new summaries + explicitly listed types + cache (models from prior iterations)
        effective_types = sorted(
            {s.model_type for s in inp.summaries}
            | set(inp.model_types or [])
            | set(inp.model_knowledge_cache.keys())
        )

        # --- Load descriptions ---
        # For agent-generated models, the description may be passed directly
        # in ModelRunSummary.model_description (avoiding filesystem dependency).
        # For built-in models, load from description.md on disk.
        model_descriptions: dict[str, str] = {}
        for mt in effective_types:
            # Priority 1: inline description from current iteration's summaries
            inline_desc = None
            for s in inp.summaries:
                if s.model_type == mt and s.model_description:
                    inline_desc = s.model_description
                    break
            if inline_desc:
                model_descriptions[mt] = inline_desc
                continue

            # Priority 2: description cached from a previous iteration's _stats
            cached_stats = inp.model_knowledge_cache.get(mt, {}).get("_stats", {})
            cached_desc = cached_stats.get("model_description")
            if cached_desc:
                model_descriptions[mt] = cached_desc
                continue

            # Priority 3: load from description.md on disk (built-in or plugin models)
            # arXiv U3 (#260): under isolation the loader refuses the BUNDLED
            # baseline description, so none can reach the `_stats` cache below.
            model_descriptions[mt] = get_model_description(
                mt, baseline_isolation=inp.baseline_isolation
            )

        # --- Deterministic pre-computation (ordering.precompute_evidence) ---
        # New models are read from inp.summaries, cached models from their
        # `_stats` block, and the scientific-aggregation authority filter runs
        # inside the boundary — all BEFORE any LLM call. Unpacked into the
        # local names the rest of the lifecycle already reads.
        evidence = precompute_evidence(
            inp.summaries, inp.model_knowledge_cache, effective_types, order=run_order
        )
        per_model_best = evidence.per_model_best
        per_model_best_valid = evidence.per_model_best_valid
        per_model_raw_best_health_validity = evidence.per_model_raw_best_health_validity
        per_model_worst = evidence.per_model_worst
        per_model_formal = evidence.per_model_formal
        per_model_formal_excluded = evidence.per_model_formal_excluded
        # `evidence.per_model_best_config` is deliberately NOT unpacked: the
        # pre-C1b `run()` built that dict in three places and read it in none
        # (verified at a325f33b). The boundary still computes and exposes it —
        # C6's projections are its first real consumer — but reintroducing a
        # dead local here would be noise, not parity.
        overall_best_score = evidence.overall_best_score
        overall_best_valid_score = evidence.overall_best_valid_score
        overall_worst_score = evidence.overall_worst_score
        overall_best_config = evidence.overall_best_config
        overall_best_valid_config = evidence.overall_best_valid_config
        total_experiments = evidence.total_experiments
        per_model_summary_input = evidence.per_model_summary_input
        aggregation_scope = evidence.aggregation_scope

        # F-SCANE-1 — the exclusion provenance reaches a HUMAN.
        # `InterpretationOutput.scientific_aggregation`'s own field
        # description names `AggregationScope.provenance_lines()` as its
        # renderer, and until this call that renderer had ZERO production
        # callers: 14 of 15 real digests concluded "EVERY result was excluded
        # — this campaign produced no scientifically authoritative result"
        # and the conclusion reached nobody. Printed HERE, before the LLM
        # block, so an interpreter failure cannot swallow it, and printed
        # rather than prompted because §4.7 keeps the exclusion narrative
        # deterministic and out of the model's reach.
        for _provenance_line in aggregation_scope.provenance_lines():
            print(f"    [scientific aggregation] {_provenance_line}")

        # --- Step 09a C6: per-model evidence projection ---
        # Deterministic reads of persisted record fields, computed BEFORE the
        # LLM block for the same structural reason the health evidence is: an
        # interpreter LLM failure must not lose them. New summaries project
        # fresh; cached models keep whatever their `_stats` carried, and a
        # cached model with no stored counts is simply ABSENT rather than
        # reported as zero failures.
        per_model_failure_counts: dict[str, Any] = {
            s_.model_type: s_.failure_counts
            for s_ in inp.summaries
            if s_.failure_counts is not None
        }
        for _mt, _entry in inp.model_knowledge_cache.items():
            if _mt in per_model_failure_counts:
                continue
            _cached_counts = (_entry.get("_stats") or {}).get("failure_counts")
            if _cached_counts is not None:
                per_model_failure_counts[_mt] = _cached_counts
        # Present-when-present, and — Step 10 / P2b C3 — now with the cache
        # half `failure_counts` above has always had (audit B-6). Before P2b
        # this projection had NEITHER half, so the Stability-Filter reuse path
        # (a model that goes quiet for an iteration, no fresh LLM call) was
        # precisely the path that lost the evidence.
        per_model_secondary_metrics: dict[str, Any] = {
            s_.model_type: list(s_.secondary_metrics)
            for s_ in inp.summaries
            if s_.secondary_metrics
        }
        for _mt, _entry in inp.model_knowledge_cache.items():
            if _mt in per_model_secondary_metrics:
                continue
            _cached_secondaries = (_entry.get("_stats") or {}).get("secondary_metrics")
            if not _cached_secondaries:
                # Missing is ABSENT, never fabricated: a cache entry predating
                # this key, or a run that declared no secondary, both correctly
                # contribute nothing.
                continue
            try:
                per_model_secondary_metrics[_mt] = [
                    SecondaryMetricEvidence.model_validate(entry) for entry in _cached_secondaries
                ]
            except Exception as exc:
                # A corrupt cached payload degrades to absence rather than
                # crashing the interpretation — and says so, because silently
                # dropping evidence is how a carry asymmetry hides.
                #
                # Deliberately broad (IR-P2b-6). The narrow
                # `(ValidationError, TypeError)` written first was WRONG, and a
                # test caught it: `MetricSpecField`'s validator reaches
                # `metric_spec_from_declaration`, which raises a bare `KeyError`
                # on a spec dict missing `scoreability`. This parses untrusted
                # JSON from a previous iteration's cache file, where the
                # requirement is "never a crash" — enumerating the exception
                # types a nested declaration parser may raise is a promise this
                # call site cannot keep.
                print(
                    f"  [interpretation] discarding unreadable cached secondary "
                    f"metrics for {_mt!r}: {type(exc).__name__}: {exc}"
                )

        # Serialize expert advice (soft edge input)
        expert_advice_str = serialize_expert_advice(inp.expert_advice) if inp.expert_advice else ""

        # --- Structured HealthGate feedback: deterministic aggregates +
        #     history merge (V19 PR 3, design §3.6/§3.8/§3.10) ---
        # Computed BEFORE the LLM try-block and threaded into BOTH the
        # healthy and degraded output dicts, so the §3.10 invariant is
        # structural: an interpreter LLM failure cannot lose this
        # iteration's real gate evidence. Inputs are the deterministic
        # RoundHealth data on the summaries — never LLM prose. Populated
        # regardless of enable_structured_health_feedback (recording-only
        # provenance; the flag gates PROMPTS only).
        (
            per_model_round_health_counts,
            per_model_collapse_fingerprints,
            _health_merge_input,
        ) = _collect_health_evidence(inp.summaries)
        collapse_fingerprint_history = merge_fingerprint_history(
            inp.collapse_fingerprint_history,
            _health_merge_input,
            inp.iteration,
            inp.health_feedback_retention_policy(),
        )

        # The bound metric is stated in the operator log: "overall best" means
        # nothing without knowing which way is better (Step 09a C2).
        _metric_banner = (
            f"{run_metric_identity.metric_id} ({run_order.direction}-is-better)"
            if run_order is not None and run_metric_identity is not None
            else "no bound metric (scoreless input)"
        )
        print(
            f"Interpreting {len(inp.summaries)} model summary(ies) across "
            f"{len(effective_types)} model(s): {effective_types} "
            f"(overall best: {overall_best_score}; metric: {_metric_banner})"
        )

        # --- LLM-dependent flow ---
        # V8 hardening Domain 2b: the LLM-dependent portion of run() is
        # wrapped in a try/except. If any bridge.generate() call raises
        # past the Bridge's 3-retry envelope (genuinely persistent failure),
        # we still write a digest carrying the incoming runtime_vocab forward
        # unchanged with is_degraded=True. Without this, an interp LLM
        # failure left no digest on disk and the next iter's
        # load_latest_knowledge() skipped the affected iter — causing a
        # 2-iter vocab regression. See docs/V8_Gap_Report.md Domain 2b.
        try:
            # --- Phase 1: Per-model summarization (Stability Filter — Commit 6.1) ---
            # Compute the active set ONCE for this iter — gates both per_model
            # recall (axis 2) and synthesis-prompt expansion (axis 1).
            #     active_set = Top-K-by-best-score
            #                  ∪ Last-N-by-recency
            #                  ∪ {mt | |Δ score| ≥ threshold}
            # `should_recall_per_model` then decides per-model whether the
            # cache entry can be reused verbatim (no LLM call) or whether
            # fresh evidence warrants a fresh per_model call.
            from nodes.interpretation_helpers import (
                select_active_models,
                should_recall_per_model,
            )

            active_set = select_active_models(
                cache_entries=inp.model_knowledge_cache,
                current_iter_summaries=inp.summaries,
                top_k=inp.active_model_top_k,
                last_n=inp.active_model_last_n,
                score_delta_threshold=inp.active_model_score_delta,
                order=_require_order("selecting the active model set"),
            )
            print(
                f"  Active models ({len(active_set)}/{len(effective_types)}): {sorted(active_set)}"
            )

            model_knowledge_cache: dict[str, dict] = {}
            n_skipped = 0
            for mt in effective_types:
                cache_entry = inp.model_knowledge_cache.get(mt)
                current_summary = per_model_summary_input.get(mt)

                # Stability Filter decision: True → recall LLM, False → reuse cache.
                recall = should_recall_per_model(
                    model_type=mt,
                    cache_entry=cache_entry,
                    current_iter_summary=current_summary,
                    active_set=active_set,
                    score_delta_threshold=inp.active_model_score_delta,
                )

                if not recall and cache_entry is not None:
                    # Stable model with a usable cache → reuse verbatim, emit
                    # audit marker so build_token_baseline_report.py can count
                    # the savings. The skip is countable but charges zero
                    # tokens / chars.
                    model_knowledge_cache[mt] = cache_entry
                    n_skipped += 1
                    self.bridge.emit_marker(
                        label="interpretation.per_model_skipped",
                        extra={"reason": "stable", "model_type": mt},
                    )
                    print(
                        f"  Phase 1: {mt} — Stability Filter skip "
                        f"(cached entry reused, no LLM call)."
                    )
                    continue

                if mt not in per_model_summary_input:
                    # No tuning data and no cache: placeholder (shouldn't happen in normal flow)
                    model_knowledge_cache[mt] = {
                        "key_findings": ["No tuning run available for this model."],
                        "bottlenecks": [],
                        "best_config_analysis": "N/A",
                        "score_trend": "N/A",
                        "_stats": {},
                    }
                    continue

                summary = per_model_summary_input[mt]
                print(
                    f"  Phase 1: Summarizing {mt} ({summary.completed_rounds} rounds) — LLM call..."
                )
                per_model_prompt = _build_per_model_prompt(
                    summary=summary,
                    description=model_descriptions[mt],
                    expert_advice_str=expert_advice_str,
                    human_advice=inp.human_advice,
                    structured_health_feedback=inp.enable_structured_health_feedback,
                    order=run_order,
                )
                # T4b — system prompt has {TASK_DESCRIPTION} placeholder
                # substituted at call time from inp.task_description; see
                # docs/design/enable_global_task_config.md § Commit T4.
                llm_response = self.bridge.generate(
                    _build_per_model_system_prompt(inp),
                    per_model_prompt,
                    label="interpretation.per_model",
                )

                new_stats = {
                    "best_denoising_score": summary.best_denoising_score,
                    "best_valid_denoising_score": summary.best_valid_denoising_score,
                    "best_raw_health_validity": summary.best_raw_health_validity,
                    "worst_denoising_score": summary.worst_denoising_score,
                    "best_file_vector": summary.best_file_vector,
                    "best_score_table": (
                        summary.best_score_table.model_dump() if summary.best_score_table else None
                    ),
                    "best_model_params": summary.best_model_params,
                    "completed_rounds": summary.completed_rounds,
                    "best_config": summary.best_config,
                    "best_valid_config": summary.best_valid_config,
                    "formal_score": summary.formal_score,
                    "model_description": model_descriptions.get(mt),
                    # V19 PR 3 — deterministic side of the cache (§3.6):
                    # cached (non-active) models keep their health facts
                    # without a fresh LLM call.
                    "round_health_counts": per_model_round_health_counts.get(mt, {}),
                    # Step 09a C6 — so a model that goes quiet keeps its
                    # failure counts across iterations without a fresh LLM
                    # call, exactly as round_health_counts does.
                    "failure_counts": (
                        summary.failure_counts.model_dump()
                        if summary.failure_counts is not None
                        else None
                    ),
                    "collapse_fingerprints": [
                        fp.model_dump() for fp in per_model_collapse_fingerprints.get(mt, [])
                    ],
                }
                # Step 10 / P2b C3 — the SAME write beside `failure_counts`, for
                # the same reason (audit B-6): a model that goes quiet keeps its
                # secondary evidence across iterations without a fresh LLM call.
                # Deliberately the `failure_counts` idiom — typed model_dump
                # here, validated read-back on the reuse path — and NOT a third
                # carry representation.
                #
                # Written only when there IS evidence, unlike `failure_counts`,
                # which records `None` as a meaningful "no counts". That is the
                # frozen zero-secondary invariant (design §4.7): a run that
                # declared no secondary creates no `_stats` secondary key at
                # all, so its cache entry is byte-identical to its pre-P2b self.
                if summary.secondary_metrics:
                    new_stats["secondary_metrics"] = [
                        evidence.model_dump() for evidence in summary.secondary_metrics
                    ]

                if cache_entry is None:
                    # Cache miss: build initial entry from the LLM response.
                    # Structurally unchanged from the legacy flat-dict shape
                    # (Rev 8.5 C4 directive). Next iter, this entry is lifted
                    # via CacheEntry.from_legacy_dict before being passed to
                    # consolidate() — so the accumulator activates on the first
                    # active-cache-hit and not earlier.
                    model_knowledge_cache[mt] = {
                        **llm_response,
                        "_stats": new_stats,
                    }
                else:
                    # Active cache hit: run the LLM-powered semantic
                    # consolidator (Commit 6.3, Rev 8.5). The prior entry may
                    # be legacy-flat (first re-call after cache-miss build) or
                    # already in CacheEntry shape (post-first-merge); try the
                    # modern shape first, fall back to the legacy adapter.
                    prior_iter = max(0, inp.iteration - 1)
                    # Modern-shape entries are stored with the `_stats` legacy
                    # alias (line ~920); restore the schema name before
                    # validation. The legacy flat-dict shape (cache-miss build)
                    # has no `model_type` key and falls through to the adapter.
                    candidate = dict(cache_entry)
                    if "_stats" in candidate and "stats" not in candidate:
                        candidate["stats"] = candidate.pop("_stats")
                    try:
                        prior_entry = CacheEntry.model_validate(candidate)
                    except ValidationError:
                        prior_entry = CacheEntry.from_legacy_dict(
                            cache_entry,
                            model_type=mt,
                            current_iter=prior_iter,
                        )

                    merged_entry, archived_items = consolidate(
                        self.bridge,
                        prior=prior_entry,
                        new_llm_response=llm_response,
                        new_stats=new_stats,
                        current_iter=inp.iteration,
                        prior_iter=prior_iter,
                    )

                    dumped = merged_entry.model_dump()
                    # Back-compat: legacy `_stats` key for downstream readers
                    # in this module (lines ~643, ~693, ~873) and the
                    # synthesis-prompt filter (line ~897). The CacheEntry's
                    # `stats` field is the same passthrough dict — only the
                    # key name differs.
                    dumped["_stats"] = dumped.pop("stats")
                    model_knowledge_cache[mt] = dumped

                    if archived_items and inp.storage.backend == "local" and inp.storage.local:
                        archive_dir = os.path.join(
                            inp.storage.local.workspace,
                            f"iter_{inp.iteration:03d}",
                        )
                        os.makedirs(archive_dir, exist_ok=True)
                        archive_path = os.path.join(archive_dir, f"cache_archive_{mt}.json")
                        with open(archive_path, "w", encoding="utf-8") as f:
                            json.dump(archived_items, f, indent=2, default=str)

                print(
                    f"    {mt}: {len(llm_response.get('key_findings', []))} findings, "
                    f"{len(llm_response.get('bottlenecks', []))} bottlenecks"
                )

            if n_skipped:
                print(
                    f"  Stability Filter: {n_skipped} model_type(s) skipped "
                    f"(cache reused; saved {n_skipped} interpretation.per_model "
                    f"LLM call(s) this iter)."
                )

            # --- Pre-compute enriched fields (ordering.collect_enriched_fields) ---
            # Called from HERE, inside the try-block, exactly as before: a
            # malformed cached score table raises, and the degraded path is the
            # designed outcome for that.
            enriched = collect_enriched_fields(
                inp.summaries, inp.model_knowledge_cache, per_model_summary_input
            )
            per_model_score_tables = enriched.per_model_score_tables
            per_model_params = enriched.per_model_params
            per_model_training_segments = enriched.per_model_training_segments

            # --- Phase 2: Cross-model synthesis (Sliding Window — Commit 6.1) ---
            # Active models: full LLM-text block expanded into the synthesis
            # prompt (existing behaviour, minus _stats which is shown separately).
            # Stable models: deterministic one-line takeaway via
            # `compress_model_summary` — no LLM call, target ≤ 200 chars per
            # model. This clamps axis 1 (synthesis prompt-size growth) by
            # replacing the V12 "concatenate every cache entry verbatim"
            # behaviour with a windowed view.
            from nodes.interpretation_helpers import compress_model_summary

            per_model_summaries_for_prompt: dict[str, dict] = {}
            compressed_set: set[str] = set()
            for mt, entry in model_knowledge_cache.items():
                if mt in active_set:
                    per_model_summaries_for_prompt[mt] = _flatten_entry_for_prompt(entry)
                else:
                    per_model_summaries_for_prompt[mt] = compress_model_summary(mt, entry)
                    compressed_set.add(mt)
            n_compressed = len(compressed_set)
            if n_compressed:
                print(
                    f"  Phase 2: {n_compressed} stable model(s) compressed "
                    f"to one-liners for the synthesis prompt "
                    f"(active: {len(active_set)})."
                )

            # Compute prior-state health metrics from the *incoming* vocab and cumulative
            # before Phase 2 synthesis so the LLM can see the research trajectory so far.
            # The updated metrics (post-Phase-C) are computed after vocab is rebuilt below.
            from nodes.interpretation_helpers import compute_vocab_diversity_ratio as _cvdr

            prior_vocab_diversity_ratio = _cvdr(list(inp.runtime_vocab))
            prior_cumulative_info_gain = inp.cumulative_information_gain

            if len(effective_types) == 1:
                single_mt = effective_types[0]
                summary = model_knowledge_cache[single_mt]
                llm_findings = summary.get("key_findings", [])
                llm_bottlenecks = summary.get("bottlenecks", [])
                llm_take_home = (
                    f"The {single_mt} model shows: "
                    + summary.get("score_trend", "unclear trend")
                    + ". "
                    + (summary.get("best_config_analysis", "") or "")
                )
                print("  Phase 2: Single model — skipping synthesis.")
            else:
                print(f"  Phase 2: Synthesizing across {len(effective_types)} models...")
                synthesis_prompt = _build_synthesis_prompt(
                    per_model_summaries=per_model_summaries_for_prompt,
                    per_model_best=per_model_best,
                    per_model_best_valid=per_model_best_valid,
                    per_model_raw_best_health_validity=per_model_raw_best_health_validity,
                    per_model_worst=per_model_worst,
                    overall_best_score=overall_best_score,
                    overall_best_valid_score=overall_best_valid_score,
                    overall_worst_score=overall_worst_score,
                    overall_best_config=overall_best_config,
                    per_model_score_tables=per_model_score_tables or None,
                    per_model_params=per_model_params or None,
                    per_model_training_segments=per_model_training_segments or None,
                    expert_advice_str=expert_advice_str,
                    human_advice=inp.human_advice,
                    runtime_vocab=list(inp.runtime_vocab) if inp.runtime_vocab else None,
                    per_model_formal=per_model_formal or None,
                    # F-SCANE-1 — passed UNCONDITIONALLY (not `or None`): the
                    # whole defect is that an emptied container silently
                    # cancels a warning, and this dict is empty exactly when
                    # there is nothing to say.
                    per_model_formal_excluded=per_model_formal_excluded,
                    vocab_diversity_ratio=prior_vocab_diversity_ratio,
                    cumulative_information_gain=prior_cumulative_info_gain,
                    compressed_model_types=compressed_set,
                    # Step 09b C3 — the identity this iteration was ORDERED
                    # under, already bound above (09a C2). Rendering only.
                    metric_identity=run_metric_identity,
                    # Step 09b C4 — the INCOMING prediction memory, rendered
                    # version-labelled. Same values the pre-09b prompt read
                    # (`prior_cumulative_info_gain`), now with their pools and
                    # their semantics ids so v1 and v2 cannot read as one.
                    prediction_outcomes_history=dict(inp.prediction_outcomes_history),
                    prediction_outcomes_by_semantics={
                        version: dict(counts)
                        for version, counts in inp.prediction_outcomes_by_semantics.items()
                    },
                    cumulative_information_gain_by_semantics=dict(
                        inp.cumulative_information_gain_by_semantics
                    ),
                    # The PRIOR accuracy, obtained from the 09a accumulator
                    # itself with no new outcome (`evaluation=None`) rather
                    # than from a second fraction computation living here.
                    scientific_accuracy=accumulate_prediction_outcomes(
                        inp.prediction_outcomes_by_semantics, None
                    )[1],
                    # Cast is a pure type-system shim: at every caller of
                    # this synthesis branch, `storage.backend == "local"` and
                    # `storage.local` is populated. Avoids re-declaring the
                    # invariant as a runtime guard.
                    workspace=cast(LocalStorageConfig, inp.storage.local).workspace,
                )
                # T4b — system prompt has {TASK_DESCRIPTION} placeholder
                # substituted at call time from inp.task_description.
                synthesis_response = self.bridge.generate(
                    _build_synthesis_system_prompt(inp),
                    synthesis_prompt,
                    label="interpretation.synthesis",
                )
                llm_findings = synthesis_response.get("key_findings", [])
                llm_bottlenecks = synthesis_response.get("bottlenecks", [])
                llm_take_home = synthesis_response.get("take_home_message", "")

            # --- Phase C: Vocabulary feedback loop ---
            from nodes.interpretation_helpers import (
                build_runtime_vocab,
                generate_discoveries,
                promote_candidates,
                update_vocab_link_confirmations,
            )

            prediction_evaluation = None
            new_discoveries = []
            prev_model_type = ""

            if inp.previous_proposal:
                prev_prediction = inp.previous_proposal.get("falsifiable_prediction")
                prev_model_type = inp.previous_proposal.get("model_name", "unknown")
                prev_inherited = inp.previous_proposal.get("inherited_components", [])
                prev_vocab_links = inp.previous_proposal.get("proposed_vocab_links", [])

                # Evaluate the prediction against actual results
                if prev_prediction:
                    # Find the best score for the proposed model
                    prev_best = per_model_best.get(prev_model_type)
                    # evaluate_prediction consumes the file_vector as a list of floats
                    # (per its metric-parser contract: "mean(file_vector[N:M])",
                    # "file_vector[N]"). Synthesize that list from rows[i].model so
                    # the reflector-side payload key "best_file_vector" keeps its
                    # existing shape while the upstream dict stores a
                    # ScoreComparisonTable.
                    prev_table = (per_model_score_tables or {}).get(prev_model_type)
                    prev_fv = [r.model for r in prev_table.rows] if prev_table is not None else None

                    actual_results = {
                        "best_denoising_score": prev_best,
                        "best_file_vector": prev_fv,
                    }
                    # current_sota = SOTA at proposal time (FalsifiablePrediction.current_value).
                    # The workflow may pass a fresher value via overall_best_score if needed,
                    # but the proposal-time baseline is the fairest comparison for evaluation.
                    sota_at_proposal = prev_prediction.get("current_value")
                    prediction_evaluation = evaluate_prediction(
                        prev_prediction,
                        actual_results,
                        current_sota=sota_at_proposal,
                        order=_require_order("evaluating the previous prediction"),
                        bound_metric_id=_require_metric_identity(
                            "evaluating the previous prediction"
                        ).metric_id,
                    )
                    print(
                        f"  Prediction evaluation: {prediction_evaluation.get('outcome', '?')} "
                        f"(delta_from_sota={prediction_evaluation.get('delta_from_sota')}, "
                        f"actual={prediction_evaluation.get('actual_value')})"
                    )

                # Generate discoveries from the evaluation
                prev_summary = per_model_summary_input.get(prev_model_type)
                prev_timing = prev_summary.best_timing if prev_summary else None
                new_discoveries = generate_discoveries(
                    prediction_eval=prediction_evaluation,
                    model_type=prev_model_type,
                    best_score=per_model_best.get(prev_model_type),
                    inherited_components=prev_inherited,
                    proposed_vocab_links=prev_vocab_links,
                    timing=prev_timing,
                    overall_best_score=overall_best_score,
                    order=_require_order("generating score-comparison discoveries"),
                )
                if new_discoveries:
                    print(f"  New discoveries: {len(new_discoveries)}")
                    for d in new_discoveries:
                        print(f"    - {d.description[:100]}...")

            # Build updated runtime vocabulary
            # Feature/capability candidates come from proposed_vocab_candidates (C.5-2).
            # Discovery entries are generated separately above and passed as new_discoveries.
            # Inject proposed_by_run from the proposal's model_name so build_runtime_vocab
            # can populate seen_in_runs — the LLM never produces this key itself.
            proposed_candidates = []
            if inp.previous_proposal:
                model_name = inp.previous_proposal.get("model_name", "")
                raw_candidates = inp.previous_proposal.get("proposed_vocab_candidates", [])
                proposed_candidates = [
                    {**c, "proposed_by_run": model_name} if not c.get("proposed_by_run") else c
                    for c in raw_candidates
                ]
            runtime_vocab = build_runtime_vocab(
                incoming_vocab=list(inp.runtime_vocab),
                new_discoveries=new_discoveries,
                proposed_candidates=proposed_candidates,
            )

            # Structural promotion: candidates seen in >= 3 runs → canonical
            runtime_vocab, promoted_names = promote_candidates(runtime_vocab)
            # Log promotions before dedup (promoted entries may be removed by dedup)
            vocab_changes = [
                f"Promoted '{name}' to canonical (seen in "
                f"{next(len(e.seen_in_runs) for e in runtime_vocab if e.name == name)} runs)."
                for name in promoted_names
            ]
            if promoted_names:
                print(f"  Vocab promotions ({len(promoted_names)}): {promoted_names}")

            # Semantic dedup: check newly promoted entries against existing canonicals
            if promoted_names:
                print(f"  Dedup: checking {len(promoted_names)} newly promoted entries...")
                runtime_vocab, merge_changes = self._dedup_promoted(promoted_names, runtime_vocab)
                vocab_changes.extend(merge_changes)

            print(
                f"  Runtime vocab: {len(runtime_vocab)} entries "
                f"({sum(1 for v in runtime_vocab if v.kind == 'discovery')} discoveries, "
                f"{sum(1 for v in runtime_vocab if v.tier == 'canonical')} canonical)"
            )

            # --- Phase E.7: Update ProposedVocabLink confirmation tracking ---
            # When prediction is confirmed, each proposed link from the previous run
            # gains one confirmation. Links confirmed in >= min_runs distinct runs
            # are promoted to VocabEntry.related_to (feature gains capability as established fact).
            prev_vocab_links: list[dict[str, Any]] = (
                inp.previous_proposal.get("proposed_vocab_links", [])
                if inp.previous_proposal
                else []
            )
            link_confirmations, runtime_vocab, promoted_link_pairs = (
                update_vocab_link_confirmations(
                    prev_vocab_links=prev_vocab_links,
                    prediction_outcome=(
                        prediction_evaluation.get("outcome") if prediction_evaluation else None
                    ),
                    run_name=prev_model_type if inp.previous_proposal else "",
                    existing_confirmations=inp.vocab_link_confirmations,
                    runtime_vocab=runtime_vocab,
                    min_runs=3,
                )
            )
            if promoted_link_pairs:
                print(
                    f"  Vocab link promotions ({len(promoted_link_pairs)}): {promoted_link_pairs}"
                )
                for pair in promoted_link_pairs:
                    feature, _, capability = pair.partition(":")
                    vocab_changes.append(
                        f"Link '{feature} → {capability}' confirmed in ≥3 runs; "
                        f"added '{capability}' to {feature}.related_to."
                    )

            # --- Phase E.4: Scientific accuracy tracking (prediction.py) ---
            # Step 09a C4: the LEGACY pool is carried forward untouched; only
            # the versioned pool accumulates, and the accuracy is computed from
            # that pool alone (Q-09a-2).
            legacy_outcomes_history = dict(inp.prediction_outcomes_history)
            new_outcomes_by_semantics, scientific_accuracy = accumulate_prediction_outcomes(
                inp.prediction_outcomes_by_semantics, prediction_evaluation
            )
            pool_sizes = prediction_pool_sizes(legacy_outcomes_history, new_outcomes_by_semantics)
            if scientific_accuracy:
                v2_total = pool_sizes[PREDICTION_SEMANTICS_SIGNSAFE_V2]
                print(
                    f"  Scientific accuracy ({PREDICTION_SEMANTICS_SIGNSAFE_V2}): "
                    f"{scientific_accuracy} (n={v2_total}; "
                    f"legacy pool n={pool_sizes[PREDICTION_SEMANTICS_LEGACY_V1]}, "
                    f"not pooled)"
                )

            # --- Centrifugal health metrics (post-Phase-C, on the updated vocab) ---
            vocab_diversity_ratio = _cvdr(runtime_vocab)
            # The legacy scalar is preserved verbatim; only the versioned sum
            # accumulates. No single number anywhere means "legacy + v2".
            cumulative_information_gain = inp.cumulative_information_gain
            new_gain_by_semantics = accumulate_information_gain(
                inp.cumulative_information_gain_by_semantics, prediction_evaluation
            )
            print(
                f"  Vocab diversity ratio: {vocab_diversity_ratio:.3f} "
                f"(cumulative info gain: {cumulative_information_gain:.4f})"
            )

            # --- V8 Domain 3 — evolution stats (healthy path) ---
            # Snapshot vocab counts + promotion count + degraded flag now,
            # after promote_candidates + dedup have settled. promoted_names
            # carries the count from promote_candidates this iter (Tested-only
            # threshold). is_degraded=False on the healthy return.
            evolution_stats = _compute_evolution_stats(
                runtime_vocab=runtime_vocab,
                promoted_this_iter=len(promoted_names),
                is_degraded=False,
            )

            # --- Build and validate output ---
            output = InterpretationOutput.model_validate(
                {
                    "model_types": effective_types,
                    "model_descriptions": model_descriptions,
                    "total_experiments": total_experiments,
                    "per_model_best": per_model_best,
                    "per_model_best_valid": per_model_best_valid,
                    "per_model_raw_best_health_validity": per_model_raw_best_health_validity,
                    "per_model_worst": per_model_worst,
                    # D-C5: threaded into BOTH the healthy and the
                    # degraded dict, so an interpreter LLM failure
                    # cannot lose the exclusion provenance — the same
                    # structural rule the health evidence follows.
                    "scientific_aggregation": aggregation_scope.model_dump(),
                    "best_denoising_score": overall_best_score,
                    "best_valid_denoising_score": overall_best_valid_score,
                    "worst_denoising_score": overall_worst_score,
                    "best_config": overall_best_config,
                    "best_valid_config": overall_best_valid_config,
                    "model_knowledge_cache": model_knowledge_cache,
                    # V19 PR 3 — deterministic health evidence, computed
                    # before the LLM block (never from prose).
                    "per_model_round_health_counts": per_model_round_health_counts,
                    "per_model_collapse_fingerprints": per_model_collapse_fingerprints,
                    "collapse_fingerprint_history": collapse_fingerprint_history,
                    "key_findings": llm_findings,
                    "bottlenecks": llm_bottlenecks,
                    # Enriched fields
                    "per_model_score_tables": per_model_score_tables or None,
                    "per_model_params": per_model_params or None,
                    "per_model_training_segments": per_model_training_segments or None,
                    "take_home_message": llm_take_home,
                    # Phase C: vocabulary feedback
                    "runtime_vocab": [
                        v.model_dump() if hasattr(v, "model_dump") else v for v in runtime_vocab
                    ],
                    "prediction_evaluation": prediction_evaluation,
                    "new_discoveries": [d.model_dump() for d in new_discoveries],
                    "vocab_changes": vocab_changes,
                    # Centrifugal health metrics
                    "vocab_diversity_ratio": vocab_diversity_ratio,
                    "cumulative_information_gain": cumulative_information_gain,
                    # Phase E: scientific accuracy + vocab link promotion
                    "scientific_accuracy": scientific_accuracy,
                    # Step 09a C4 — the legacy pool passes through UNCHANGED;
                    # the versioned pools carry this iteration's outcome.
                    "prediction_outcomes_history": legacy_outcomes_history,
                    "prediction_outcomes_by_semantics": new_outcomes_by_semantics,
                    "cumulative_information_gain_by_semantics": new_gain_by_semantics,
                    "prediction_pool_sizes": pool_sizes,
                    "prediction_evaluation_semantics": PREDICTION_SEMANTICS_SIGNSAFE_V2,
                    "vocab_link_confirmations": link_confirmations,
                    # V8 Domain 3 — evolution observability
                    "evolution_stats": evolution_stats,
                    # Step 09a C2 — which metric this iteration was ORDERED
                    # under. Provenance, not evidence.
                    "metric_identity": run_metric_identity,
                    # Step 09a C6 — deterministic evidence projection.
                    "per_model_failure_counts": per_model_failure_counts,
                    "per_model_secondary_metrics": per_model_secondary_metrics,
                }
            )

            # --- Persist ---
            if inp.storage.backend == "local" and inp.storage.local:
                workspace = inp.storage.local.workspace
                run_name = inp.storage.local.run_name
                os.makedirs(workspace, exist_ok=True)
                out_path = os.path.join(workspace, f"interpretation_{run_name}.json")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(output.model_dump_json(indent=4))
                print(f"Interpretation saved -> {out_path}")

                # V8 Domain 3 — append per-iter row to chain-root evolution log.
                # Resolved via SIDERIUS_CHAIN_WORKSPACE in chain mode (one level
                # above the per-iter agent workspace) so all iters share one
                # tail-able file. Falls back to the agent workspace otherwise.
                _append_evolution_log(
                    workspace_root=_resolve_evolution_log_root(workspace),
                    payload={
                        "iteration": inp.iteration,
                        "evolution_stats": evolution_stats,
                        "best_score_so_far": output.best_denoising_score,
                        "take_home_message": output.take_home_message,
                    },
                )

            return output
        except Exception as e:
            print(f"  [DEGRADED] Interpretation LLM flow failed: {type(e).__name__}: {e}")
            print(
                f"  [DEGRADED] Carrying forward incoming runtime_vocab "
                f"({len(inp.runtime_vocab)} entries) unchanged. "
                f"Writing digest with is_degraded=True."
            )
            # V8 Domain 3 — evolution stats (degraded path).
            # No promotions ran; vocab is the incoming list verbatim. Still
            # emit a row so tail -f sees the iter and the dashboard can flag
            # is_degraded=True visually.
            degraded_stats = _compute_evolution_stats(
                runtime_vocab=list(inp.runtime_vocab),
                promoted_this_iter=0,
                is_degraded=True,
            )
            output = InterpretationOutput.model_validate(
                {
                    "model_types": effective_types,
                    "model_descriptions": model_descriptions,
                    "total_experiments": total_experiments,
                    "per_model_best": per_model_best,
                    "per_model_best_valid": per_model_best_valid,
                    "per_model_raw_best_health_validity": per_model_raw_best_health_validity,
                    "per_model_worst": per_model_worst,
                    # D-C5: threaded into BOTH the healthy and the
                    # degraded dict, so an interpreter LLM failure
                    # cannot lose the exclusion provenance — the same
                    # structural rule the health evidence follows.
                    "scientific_aggregation": aggregation_scope.model_dump(),
                    "best_denoising_score": overall_best_score,
                    "best_valid_denoising_score": overall_best_valid_score,
                    "worst_denoising_score": overall_worst_score,
                    "best_config": overall_best_config,
                    "best_valid_config": overall_best_valid_config,
                    "model_knowledge_cache": dict(inp.model_knowledge_cache),
                    # V19 PR 3 §3.10 invariant: the deterministic merge ran
                    # BEFORE the LLM block, so this iteration's real gate
                    # evidence is recorded even though the LLM failed.
                    # Degradation affects LLM commentary only.
                    "per_model_round_health_counts": per_model_round_health_counts,
                    "per_model_collapse_fingerprints": per_model_collapse_fingerprints,
                    "collapse_fingerprint_history": collapse_fingerprint_history,
                    "key_findings": [],
                    "bottlenecks": [],
                    "take_home_message": (
                        f"DEGRADED: interpreter LLM failed "
                        f"({type(e).__name__}). Vocab carried forward unchanged."
                    ),
                    "runtime_vocab": [
                        v.model_dump() if hasattr(v, "model_dump") else v for v in inp.runtime_vocab
                    ],
                    "new_discoveries": [],
                    "vocab_changes": [],
                    "prediction_outcomes_history": dict(inp.prediction_outcomes_history),
                    # Step 09a C4 — the degraded path copies every pool and sum
                    # forward unchanged. No re-basing exists: the structure is
                    # versioned, so nothing has to be reinterpreted here.
                    "prediction_outcomes_by_semantics": {
                        version: dict(counts)
                        for version, counts in inp.prediction_outcomes_by_semantics.items()
                    },
                    "cumulative_information_gain_by_semantics": dict(
                        inp.cumulative_information_gain_by_semantics
                    ),
                    "prediction_pool_sizes": prediction_pool_sizes(
                        dict(inp.prediction_outcomes_history),
                        inp.prediction_outcomes_by_semantics,
                    ),
                    "prediction_evaluation_semantics": PREDICTION_SEMANTICS_SIGNSAFE_V2,
                    "vocab_link_confirmations": dict(inp.vocab_link_confirmations),
                    "cumulative_information_gain": inp.cumulative_information_gain,
                    "is_degraded": True,
                    "evolution_stats": degraded_stats,
                    # Step 09a C2 — threaded into the degraded dict too: an
                    # interpreter LLM failure must not lose the ordering
                    # provenance (the same structural rule the health
                    # evidence and the aggregation scope follow).
                    "metric_identity": run_metric_identity,
                    # Step 09a C6 — deterministic evidence projection.
                    "per_model_failure_counts": per_model_failure_counts,
                    "per_model_secondary_metrics": per_model_secondary_metrics,
                }
            )
            if inp.storage.backend == "local" and inp.storage.local:
                workspace = inp.storage.local.workspace
                run_name = inp.storage.local.run_name
                os.makedirs(workspace, exist_ok=True)
                out_path = os.path.join(workspace, f"interpretation_{run_name}.json")
                with open(out_path, "w", encoding="utf-8") as f:
                    f.write(output.model_dump_json(indent=4))
                print(f"  [DEGRADED] Interpretation saved -> {out_path}")

                _append_evolution_log(
                    workspace_root=_resolve_evolution_log_root(workspace),
                    payload={
                        "iteration": inp.iteration,
                        "evolution_stats": degraded_stats,
                        "best_score_so_far": output.best_denoising_score,
                        "take_home_message": output.take_home_message,
                    },
                )
            return output

    def _dedup_promoted(
        self,
        promoted_names: list[str],
        vocab: list["VocabEntry"],
    ) -> tuple[list["VocabEntry"], list[str]]:
        """
        Semantic deduplication of newly promoted canonical entries (C.6).

        For each promoted entry, asks the LLM whether it is a near-duplicate of
        an existing canonical of the same kind. If yes: the promoted entry is
        removed from the vocab and its name is added to the existing entry's
        aliases. If no: it stays canonical.

        Each promoted entry that has at least one existing canonical of the same
        kind triggers one LLM call. Promotion is rare so total cost is low.

        Args:
            promoted_names: Names of entries just promoted by promote_candidates.
            vocab:          Current runtime vocabulary (includes promoted entries).

        Returns:
            (updated_vocab, merge_changes) — updated vocab and human-readable
            log strings for each merge (e.g. "Merged 'x' into 'y' as alias.").
        """

        if not promoted_names:
            return vocab, []

        vocab_by_name: dict[str, Any] = {e.name: e for e in vocab}
        merge_changes: list[str] = []

        for name in promoted_names:
            if name not in vocab_by_name:
                continue  # already removed by a prior merge this loop

            entry = vocab_by_name[name]
            kind = entry.kind if hasattr(entry, "kind") else entry.get("kind", "")

            # Only compare against existing canonicals of the same kind
            existing = [
                e
                for n, e in vocab_by_name.items()
                if n != name
                and (e.tier if hasattr(e, "tier") else e.get("tier")) == "canonical"
                and (e.kind if hasattr(e, "kind") else e.get("kind")) == kind
            ]
            if not existing:
                print(f"  Dedup: '{name}' — no existing canonicals of kind='{kind}', keeping.")
                continue

            prompt = _build_dedup_prompt(entry, existing)
            response = self.bridge.generate(
                DEDUP_SYSTEM_PROMPT,
                prompt,
                label="interpretation.dedup",
            )

            is_dup = response.get("is_duplicate", False)
            dup_of = response.get("duplicate_of")
            rationale = response.get("rationale", "")

            if is_dup and dup_of and dup_of in vocab_by_name:
                existing_entry = vocab_by_name[dup_of]
                current_aliases = (
                    existing_entry.aliases
                    if hasattr(existing_entry, "aliases")
                    else existing_entry.get("aliases", [])
                )
                vocab_by_name[dup_of] = existing_entry.model_copy(
                    update={"aliases": [*current_aliases, name]}
                )
                del vocab_by_name[name]
                msg = f"Merged '{name}' into '{dup_of}' as alias. Rationale: {rationale}"
                merge_changes.append(msg)
                print(f"  Dedup: {msg}")
            else:
                print(f"  Dedup: '{name}' — genuine new canonical.")

        return list(vocab_by_name.values()), merge_changes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="SIDERIUS result_interpretation_agent")
    parser.add_argument(
        "--workspace",
        type=str,
        default="./siderius_workspace",
        help="Root directory for reading summaries and writing output",
    )
    parser.add_argument(
        "--run_name",
        type=str,
        default="v1",
        help="Run name — reads summary_{run_name}.json, writes interpretation_{run_name}.json",
    )
    parser.add_argument(
        "--model_type", type=str, required=True, help="Model architecture (e.g. 'punet')."
    )
    parser.add_argument("--provider", type=str, default="gemini", choices=["gemini", "openai"])
    parser.add_argument("--model_id", type=str, default="gemini-3.1-flash-lite-preview")
    args = parser.parse_args()

    # Load run output from workspace
    output_path = os.path.join(args.workspace, f"run_output_{args.run_name}.json")
    if not os.path.exists(output_path):
        raise FileNotFoundError(
            f"Run output not found: {output_path}\n"
            f"Run tune_ml_hyperparam_agent first, or check --workspace and --run_name."
        )
    with open(output_path, encoding="utf-8") as f:
        run_data = json.load(f)

    # Build ModelRunSummary from run output
    from agent.schemas.hyperparam_tuning import HyperparamTuningOutput

    tune_output = HyperparamTuningOutput.model_validate(run_data)
    run_metric_spec = reconcile_metric_spec([tune_output])
    summary = tuning_output_to_model_run_summary(
        tune_output,
        order=MetricOrder(run_metric_spec) if run_metric_spec is not None else None,
    )

    # Step 09b C2 — the ad-hoc CLI is a Regime-A entry point like the
    # workflow: it resolves the task guidance through the ONE bounded adapter.
    from agent.prompt_templates.interpretation.task_blocks import (
        load_interpretation_task_blocks,
    )

    agent_input = InterpretationInput(
        summaries=[summary],
        # Step 09a C2 — the spec comes FROM the loaded output; the CLI derives
        # nothing. A legacy/pre-09a output carries none, and the input contract
        # then refuses with a named error instead of ordering on a guess.
        metric_spec=run_metric_spec,
        task_blocks=load_interpretation_task_blocks(),
        storage=StorageConfig(
            backend="local",
            local=LocalStorageConfig(workspace=args.workspace, run_name=args.run_name),
        ),
    )
    print(f"Input validated: model={args.model_type} | rounds={summary.completed_rounds}")

    agent = ResultInterpretationAgent(provider=args.provider, model_id=args.model_id)
    output = agent.run(agent_input)

    print(f"\n{'=' * 60}")
    print(f"  Interpretation — {output.model_types}")
    print(f"{'=' * 60}")
    print(f"  Total experiments : {output.total_experiments}")
    print(f"  Overall best      : {output.best_denoising_score}")
    print(f"  Overall worst     : {output.worst_denoising_score}")
    for mt in output.model_types:
        print(
            f"  {mt}: best={output.per_model_best.get(mt)} worst={output.per_model_worst.get(mt)}"
        )
    print("\n  Key findings:")
    for f in output.key_findings:
        print(f"    - {f}")
    print("\n  Bottlenecks:")
    for b in output.bottlenecks:
        print(f"    - {b}")
    print("\n  Take-home message:")
    print(f"    {output.take_home_message}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
