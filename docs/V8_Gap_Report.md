# V8 Pre-Flight Gap Report

**Date**: 2026-04-30
**Branch**: `hotfix/estimator-recalibration-v7` (post-vocab-persistence-patch, uncommitted)
**Scope**: 360° audit of SIDERIUS chain across 4 domains before V8 launch
**Goal**: V8 codebase must be "bulletproof" — sustain 30+ autonomous iterations without human intervention

---

## Executive Summary

| # | Domain | Verdict | Worst Risk |
|---|--------|---------|------------|
| 1 | Genetic bottleneck (negative-feedback persistence) | **BROKEN** in chain mode | **HIGH** |
| 2 | Silent failure (crash → evidence loss) | **PARTIALLY BROKEN** | **HIGH** |
| 3 | Observability (evolution stats) | **MISSING** but data exists | **MED** |
| 4 | `inherit_best_trial` correctness | **ALL CORRECT** | none |

**Bottom line**: V8 is **not yet bulletproof**. Two HIGH-severity structural gaps (chain-mode amnesia of negative feedback; multiple silent-crash paths) plus one MED-severity blind-spot (no chain-level evolution dashboard). The `inherit_best_trial` path — the most subtle area — is verified clean and doesn't need a fix.

---

## Domain 1 — Genetic Bottleneck (Negative-Feedback Persistence)

**Question audited**: When iter N's trials hit OOM / VRAM gate / time gate / validation failure, does iter N+1's proposer see those failures so it doesn't repeat them?

**Verdict**: **BROKEN for chain-mode**.

### Confirmed gaps

| Field | Prompt block exists? | Chain-persisted? | File:line |
|---|---|---|---|
| `previous_failures` (validation + physical rejection retries) | ✅ yes | ❌ NO — `[]` literal at start of every subprocess | prompt: `nodes/ml_model_proposal_agent.py:644-648`; reset: `workflows/model_exploration.py:809` |
| `recent_tune_outputs` (gate-exhaustion FIFO) | ✅ yes | ❌ NO — `deque(maxlen=3)` initialized empty per subprocess | prompt: `nodes/ml_model_proposal_agent.py:650-656`; reset: `workflows/model_exploration.py:760` |
| `physical_rejections` (VRAM-gate rejections) | ✅ yes (rendered into `previous_failures`) | ⚠️ PARTIAL — only iter N-1 seeded from `iteration_results[-1]`; iter N-2 and earlier lost | seed: `workflows/model_exploration.py:817-832` |
| `gate_exhaustion` (tuner abort signals) | ✅ yes | ❌ NO — visible only via `recent_tune_outputs` within current subprocess | schema: `agent/schemas/hyperparam_tuning.py:1345-1353` |

**Architectural pattern recognized but not finished**: comment at `workflows/model_exploration.py:842-848` explicitly documents that `key_findings` had chain-mode amnesia and was just fixed. The same pattern was **not** applied to negative signals — that's the gap.

**RestoredState** (`core/resume.py:48-86`) currently carries: `runtime_vocab`, `accumulated_key_findings`, `committed_iters`, `restored_plugins`, `resolved_source_paths`. Missing: anything related to past failures.

**Symptom users will see**: LLM re-proposes architectures that already failed at iter N-2 with VRAM > 12 GB. Confirms the V7 observation of "zombie architectures."

### Proposed micro-fix (Risk: HIGH)

1. Extend `RestoredState` with `accumulated_physical_rejections: List[PhysicalRejection]` and `accumulated_gate_exhaustions: List[GateExhaustionInfo]`.
2. New helper `_load_accumulated_failures(workspace, current_iter, committed_iters)` that walks each committed iter's `run_output_*.json` (HyperparamTuningOutput) and unions both lists.
3. Wire call into `restore_prior_state()` after `load_latest_knowledge()`.
4. Forward both new fields from `run_one_iteration.py` into `run_workflow(...)`.
5. In `workflows/model_exploration.py`, prepend accumulated rejections to `previous_failures` before the existing iter N-1 seed logic.

**Estimated LOC**: ~80 (mirrors the vocab-persistence patch shape, all 4 files we already touched).

---

## Domain 2 — Silent Failure Paths

**Question audited**: When training / scoring / interpretation crashes mid-iteration, does an evidence record survive so the next iter knows what happened?

**Verdict**: **PARTIALLY BROKEN** — three HIGH-severity scenarios where evidence is silently lost.

### Confirmed gaps

| Crash scenario | Record written? | Checkpoint? | Severity | File:line |
|---|---|---|---|---|
| Training mid-epoch (NaN/CUDA) | ✅ yes (`error_training`) | partial | MED | `nodes/ml_hyperparameter_tune_agent.py:1544` |
| Training OOM mid-epoch | ✅ yes (`error_training_oom`) | partial | MED | `nodes/ml_hyperparameter_tune_agent.py:1527` |
| **Silent training crash (exit 0, no `_OK_<exp_id>` sentinel)** | ✅ yes BUT delayed → masked as `error_inference` | yes | **HIGH** | `core/sandbox_executor.py:501-512`, `nodes/ml_hyperparameter_tune_agent.py:1585` |
| **Scoring crash (training succeeded)** | ❌ **NO** — exception bubbles past loop with no record | yes | **HIGH** | `nodes/ml_hyperparameter_tune_agent.py:1639-1658` (no try/except around `score_vector`) |
| **Formal-after-trial crash (e.g., epoch 40/100)** | ❌ **NO** record for the formal attempt | trial checkpoint preserved | **HIGH** | `nodes/ml_hyperparameter_tune_agent.py:1975` (top-level except, no per-attempt record write) |
| **Interpreter LLM call fails** | ❌ **NO** `interpretation_iter_NNN.json` written | n/a | **HIGH** | `nodes/result_interpretation_agent.py:578, 695` (no try/except around `bridge.generate`) |
| `_OK_<exp_id>` sentinel never written | depends on inference | maybe | MED | `core/sandbox_executor.py:501` |

**Why this matters for V8**: when interpreter fails silently, `interpretation_iter_NNN.json` is missing → next iter's `load_latest_knowledge()` skips that iter → 2-iter vocab regression (the "knowledge digest not found" warning we already see in tests). Combined with Domain 1, two consecutive crashes can erase a chunk of the chain's memory.

### Proposed micro-fixes (Risk: HIGH)

**Fix 2a — Scoring crash handler** (`nodes/ml_hyperparameter_tune_agent.py:~1660`): wrap `_run_skill("denoising_score_skill", ...)` in `try/except`, write `error_scoring` record, `continue`.

**Fix 2b — Interpreter LLM failure handler** (`nodes/result_interpretation_agent.py:578, 695`): wrap each `self.bridge.generate(...)` call in `try/except`. On failure, build a degraded `InterpretationOutput` with `is_degraded=True`, empty `key_findings`, **previous iter's `runtime_vocab` carried forward unchanged**, and write the digest. (Add `is_degraded: bool` to `InterpretationOutput` schema.)

**Fix 2c — Tuner top-level finally block** (`nodes/ml_hyperparameter_tune_agent.py:~2110`): wrap final `run_output_*.json` construction in `try/finally` so a partial output is written even on serialization error.

**Fix 2d (optional, MED)** — Promote silent-training-crash from `error_inference` mask back to `error_training` at the detection site (`sandbox_executor.py:501-512`) so root cause is preserved in the record's `status` field.

**Estimated LOC**: ~60 across 3 files.

---

## Domain 3 — Observability of Chain Evolution

**Question audited**: Can a user or dashboard answer "did vocab grow from 21 → 24 → 27 over iters 1-3?" without manual `jq` over five JSON files?

**Verdict**: **MISSING** — data exists in `runtime_vocab` and `vocab_changes`, but no aggregate field or chain-level surface exposes growth metrics.

### Confirmed gaps

**`InterpretationOutput`** (`agent/schemas/interpretation.py:257-428`) has rich fields but NO aggregate stats:
- ✅ Has: `runtime_vocab`, `vocab_changes` (narrative strings), `new_discoveries`, `vocab_diversity_ratio`, `vocab_link_confirmations`
- ❌ Missing: `num_canonical_added_this_iter`, `num_candidates_promoted`, `total_active_vocab_size`, `key_findings_count`

**`promote_candidates`** (`nodes/interpretation_helpers.py:270-308`) returns names list but no counts; caller has to `len()` it.

**Workflow summary** (`workflows/model_exploration.py:1185-1215`, `workflow_{run_name}.json`): tracks iters / scores / rounds / status — but **no vocab fields**.

**Dashboard** (`dashboard/api/router.py:492-574`, iteration table endpoint): exposes only model performance — no vocab metrics, no `/evolution` endpoint, no growth trajectory.

**No chain-level evolution log** (`evolution_log.jsonl` or similar) — would be a single-line-per-iter append-only feed of vocab counts + score + take-home, perfect for `tail -f`.

### Proposed micro-fix (Risk: MED — visibility, not correctness)

**Smallest viable**: add an `evolution_stats: dict` aggregate field to `InterpretationOutput` populated at the end of `result_interpretation_agent.run()`:

```python
evolution_stats = {
    "vocab_total":       len(runtime_vocab),
    "vocab_canonical":   sum(1 for v in runtime_vocab if v.tier == "canonical"),
    "vocab_candidate":   sum(1 for v in runtime_vocab if v.tier == "candidate"),
    "vocab_discovery":   sum(1 for v in runtime_vocab if v.kind == "discovery"),
    "promoted_this_iter": len(promoted_names),
    "key_findings_total": len(accumulated_key_findings),
}
```

**Plus** an append-only `{workspace}/evolution_log.jsonl` (one entry per iter: iteration, timestamp, evolution_stats, best_score, take_home) so users can `tail -f` the chain's progress.

**Estimated LOC**: ~25.

**Defer to later (LOW priority)**: dashboard `/evolution` endpoint + frontend tile.

---

## Domain 4 — `inherit_best_trial` Correctness

**Verdict**: **ALL CORRECT — no fix needed**.

All 7 audit questions answered green with file:line evidence and existing test coverage:

| Q | Answer | Evidence |
|---|---|---|
| Q1: formal eval_portion = 1.0? | ✅ yes (hardcoded) | `nodes/ml_hyperparameter_tune_agent.py:285` |
| Q2: formal time budget swap? | ✅ yes (per-round selection) | `nodes/ml_hyperparameter_tune_agent.py:1449-1461` |
| Q3: formal VRAM budget swap? | ✅ yes (per-round selection) | `nodes/ml_hyperparameter_tune_agent.py:1255-1273` |
| Q4: hyperparams (loss/lr) inherited? | ✅ yes, ONLY those | `nodes/ml_hyperparameter_tune_agent.py:177-180` |
| Q5: trial fields leaking? | ✅ none | mode-gated `_resolve_sample_set_cfg` |
| Q6: tiny trial eval_portion contaminating formal? | ✅ no, hardcoded 1.0 | `tests/unit/agent/tune_ml_hyperparam_agent/test_formal_sample_set.py:156-174` |
| Q7: test coverage? | ✅ 7 dedicated tests | `test_force_formal_round.py`, `test_formal_sample_set.py` |

The most subtle area in the codebase is in fact our cleanest. No action.

---

## Recommended V8 Pre-Launch Sequence

1. **(BLOCKER)** Domain 1 fix — accumulated negative feedback in RestoredState (~80 LOC, mirrors vocab patch).
2. **(BLOCKER)** Domain 2 fixes 2a + 2b + 2c — three try/except islands + `is_degraded` schema field (~60 LOC).
3. **(NICE-TO-HAVE)** Domain 3 fix — `evolution_stats` field + `evolution_log.jsonl` (~25 LOC).
4. Commit the already-landed cross-iter vocab persistence patch on `hotfix/estimator-recalibration-v7` *together with* steps 1+2 as a single "V8 hardening" PR (or split into 3 commits if you prefer fine-grained review).
5. Smoke-test on a fresh V8 workspace: run 3 iters, deliberately inject (a) a scoring exception, (b) an LLM API failure, (c) a VRAM-gate rejection. Verify each leaves an evidence record + the next iter's proposer sees it.
6. **Then** launch the V8 chain.

---

## Risk Heatmap (post-fix)

| Domain | Pre-fix | Post-fix |
|---|---|---|
| 1. Genetic bottleneck | HIGH | LOW |
| 2. Silent failure | HIGH | LOW |
| 3. Observability | MED | LOW |
| 4. inherit_best_trial | (already LOW) | LOW |

**Total estimated effort**: ~165 LOC across 5 files + ~6 unit tests. ~half a day of focused work + smoke run.

---

## Open Questions for User Review

1. **Domain 1 fix scope**: should we accumulate ALL prior iters' physical rejections, or cap at last K (e.g., K=5) to avoid prompt bloat? Each rejection is ~150 chars; K=5 over a 30-iter chain ≈ 22 KB worst-case. Recommend cap at K=10.
2. **Domain 2b interpreter degraded mode**: when interp LLM fails, should we (a) carry vocab forward unchanged + `is_degraded=true`, or (b) re-try once with shorter prompt before degrading? `agent/llm_bridge.py` already has a content-level retry per the recent uncommitted bridge fix — recommend (a) since (b) duplicates the bridge's job.
3. **Domain 3 placement**: should `evolution_log.jsonl` live at `{workspace}/evolution_log.jsonl` (run-level) or `{workspace}/iter_NNN/iteration_001/evolution.jsonl` (per-iter)? Recommend run-level, append-only, for `tail -f` ergonomics.
4. **Commit strategy**: one bundled "V8 hardening" PR, or three sequential commits (negative-feedback / silent-failure / observability)?

Awaiting your review before any code changes.
