# Audit & Optimize Token Usage and Growth

**Status**: Design draft, revision 8.2 (2026-05-05) — "Knowledge Accumulator". G0 approved; G1 baseline LANDED; Phase 1 CLOSED. Commit 4.3.2 closed with H1 verdict; Commit 4.3.3 (11th audit key) merged. **Phase 2 in progress.** Commit 6.3 promoted from "Source-Level Merge & Prune" (Rev 8) to **Knowledge Accumulator Refactor** after a code audit (2026-05-05) revealed the cache is currently a *frozen snapshot* (`nodes/result_interpretation_agent.py:687-693` — cache hit copies verbatim, no merging path), not a cumulative ledger. The Rev 8 spec assumed accumulation across iters; the code provides none. Rev 8.2 reframes 6.3 as a two-part refactor: (i) modify the cache update path so a cache hit performs a *light merge* against new findings, and (ii) reconcile the 8 existing LLM text fields (`key_findings, bottlenecks, best_config_analysis, score_trend, per_file_analysis, data_sensitivity, efficiency_assessment, strategy_assessment`) with the consolidated schema. **Sequencing**: Commit 6.1 (Stability Filter + Synthesis Window) ships first to clamp the call-multiplication bleed; 6.3 follows with the schema heart-transplant. Phase 2 entry point is Commit 6.1.
**Author**: drafted 2026-05-04, revised 2026-05-04 (rev 2 — safety/forensic/retention gates), revised 2026-05-04 (rev 3 — commit ledger + hybrid DRR + fail-fast formalization), revised 2026-05-05 (rev 4 — T1-Sanity green + Commit 4.3.1 chain-wrapper parity + V12 launch), revised 2026-05-05 (rev 5 — V12 iter 1–13 calibration + Phase 2 priority pivot), revised 2026-05-05 (rev 6 — Targeted O(N) Dehydration + USD tracking + Phase 3 split), revised 2026-05-05 (rev 7 — V12 iter 14 multi-dimensional explosion: Stability Filter, Knowledge Consolidation, Attribution Audit), revised 2026-05-05 (rev 8 — H1 verdict on 4.3.2 leak + Commit 4.3.3 11th audit key + Commit 6.3 escalated to source-level cache dehydration), revised 2026-05-05 (rev 8.1 — Gate G3.5 SOTA Replication + Metric #12 SRR + Commit 11.2 verify_sota_replication.py), revised 2026-05-05 (rev 8.2 — code audit confirms frozen-cache discrepancy; Commit 6.3 promoted to Knowledge Accumulator refactor; Phase 2 entry sequenced as 6.1 → 6.3).
**Inputs**:

- `reports/v11_20250503_token_usage.md` §12 (Proposer Internal Workflow & Feedback Logic) — the audit that motivates this doc.
- Verified file:line citations against `agent/llm_bridge.py`, `nodes/ml_model_proposal_agent.py`, `agent/schemas/proposal.py`, `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`.
- V11 forensic workspace: `/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v11_0503/` (used as the offline benchmark target in §2.8).

### Revision 2 changelog

- §1.4 expanded: Setter Safety Protocol — RunID + iter validation on every `_record_usage` call; explicit Context Flush at iter boundaries.
- New §1.9: mandatory **Top-3 Bloat Report** after the first 5 iterations of the Phase 1 baseline run. If the bloat is not in the proposer, Phase 2 pivots — surgery follows the data, not the §12 prior.
- New §2.8: **Offline Forensic Benchmark** — `ErrorSignatureSkill` must extract the V11 `spectral_u_operator_lite` failure (VRAM spike location + the specific FFT/U-Net layer) before any Phase 2 code lands.
- New §2.9: **The Trap Test** — long-term wisdom retention. A fatal flaw planted in iter-2 ledger must still be cited at iter 10, proving the sliding window does not throw away load-bearing context.
- §4 expanded: three new quantitative metrics — Failure Re-occurrence Rate (FRR), Delta Realization Rate (DRR), Dehydration Compression Ratio (Cr).
- §5 implementation steps re-numbered to insert the new gate steps (offline forensic test runs *before* step 11 lands; Top-3 Bloat Report runs *between* phases).

### Revision 3 changelog

- §1.4.1 expanded: **Run-ID Fail-Fast Logic** formalized. `LLMBridgeContextError` is a `SystemExit`-class failure — the whole process aborts; no silent fallback path is permitted on RunID mismatch.
- §4.2 metric #8 (DRR) restructured into **Hybrid DRR**: split into `DRR_LLM` (semantic, LLM-judge) and `DRR_Structural` (AST/regex match against the source-code diff). Both must pass; their *gap* is itself a published metric — a large gap indicates "Reasoning Hallucination."
- New §8: **Step-by-Step Commit & Validation Ledger**. The 24 implementation steps in §5 are grouped into **12 atomic commits** (Phase 1: commits 1–5; Phase 2: commits 6–12). Each commit carries a `[ ]` task list, a Pre-Commit Verification block (positive test + quantitative metric + negative test), and a Definition of Done. §5 step numbers carry an annotation `(Commit N)` so the two sections are synchronized — "Execute Commit #N" maps deterministically to the §5 substeps.
- §6 expanded with the Structural-vs-Semantic DRR question.

### Revision 4 changelog

- §1.5.1.1 T1-Sanity attested **GREEN** (2026-05-05) — M1 (sidecar binding), M2 (10-key Δ=0 across all 3 proposer rows), M3 (`[TOKEN_ITER]` rollup ≡ JSONL row sum) all hold. Run details captured inline.
- §8 **Commit 4.3** closed: Pre-Commit sanity gate ☑, Definition of Done **GREEN**.
- New §8 **Commit 4.3.1** — `sdsc_submission_scripts/_chain_common.sh` wrapper fix: thread `--run_name` through to `run_one_iteration.py`. Caught at the V12 launch dry-run audit; without this, every chain iter would have crashed at argparse on the new required flag. Three new dry-run unit tests in `tests/unit/scripts/test_chain_wrapper_run_name.py` pin the contract (required-flag check, value forwarding, no silent auto-derivation from workspace basename).
- V12 chains launched 2026-05-05 (`explore_novel_v12_0504`, `exploit_cnn_v12_0504`); both writing `token_usage.jsonl` with `run_id` correctly bound to `{workspace}/.token_run_id`. Commit 5 baseline data is now being generated.

### Revision 5 changelog

- **V12 Calibration Data (iter 1-13, explore chain) folded into the design** — see §1.5.1.2. Total prompt tokens grew **2.39×** from iter 1 (198 K) to iter 13 (474 K) and is still climbing.
- **Phase 2 priority pivot.** V12 data shows the bottleneck is not the proposer (3.3× sublinear) but **`interpretation.synthesis` (9.3× near-linear, 4.7K → 40K)**. The original Phase 2 §2 design assumed proposer-first; the V12 calibration overrides that assumption. Commits 6.1 (interpretation sliding window) and 6.2 (proposer prior_stage_outputs management) are inserted as the new high-priority Phase 2 entry points.
- **§8 Commit 5 spec finalized (initial)** — `tools/build_token_baseline_report.py` must segment Happy-Path-Cost vs Recovery-Cost, report per-label `tokens_per_iteration` + `growth_slope`, and alert on `tokens.prompt > 50K` per call. *(USD cost tracking added in Rev 6.)*

### Revision 6 changelog (2026-05-05)

**Status**: G0 approved; V12 calibration confirmed Interpretation as primary bloat; Phase 2 priorities pivoted to O(N) components.

- **Targeted O(N) Dehydration** is the new framing. V12 data partitions the bleed into two regimes:
  - **O(N) growth (the bleeding arteries)**: `interpretation.synthesis` (9.3× over 13 iters, near-linear) and `proposer.prior_stage_outputs` (3.3× sublinear). Both clamped by Commits 6.1 + 6.2 — these are the only Phase 2 commits that ship.
  - **O(1) fixed cost (the structural cost)**: the 21% "Template Tax" on `proposer.comparison`. Necessary for prompt adherence; does *not* scale with iterations. Optimizing fixed cost while linear growth bleeds is the wrong order.
- **Template Dehydration moved to Phase 3 (Optional)**. Removed from Commit 11.1 in §8; new §9 "Phase 3 (Optional)" section appended to the doc. Phase 3 is opportunistic: only triggered if Commits 6.1/6.2 do not bring per-iter cost under target.
- **§8 Commit 5 spec finalized — USD cost tracking + $1.50/iter bloat alert added**. The tool now computes per-iter cost using the production model's rate card (default `$10/1M prompt + $30/1M completion`, configurable via CLI). Two alert thresholds emitted in the report: `[BLOAT_ALERT]` when an iter's total USD exceeds $1.50 (the **post-dehydration target ceiling** — at V12 rates this fires on every iter; quieting this alert is the success criterion for Commits 6.1/6.2), and `[CONTEXT_EXPLOSION]` when any single call's `tokens.prompt` exceeds 50 K.
- **Cleanup**: removed the Rev 4 → Rev 5 cross-references to the non-existent `chain_run_name = None` bug. The doc now reflects that `run_name` is correctly bound across all V12 production rows. No further mention.

### Revision 7 changelog (2026-05-05) — "Full Stop" Pivot

**Status**: G1 baseline LANDED — `tools/build_token_baseline_report.py` produced `reports/v12_token_baseline.md` + `reports/v12_top3_bloat.md` against the live `explore_novel_v12_0504` workspace (iters 1–14, 366 rows, run_id `explore_novel_v12_0504-20260505T070526-1028759`). **Verdict: Confirmed Proposer Hypothesis.** Cumulative cost across 14 iters: $72.73 (avg $5.20/iter). Iter 14 hit **$9.43 = 6.3× the $1.50 ceiling** with 2 `[CONTEXT_EXPLOSION]` events on `proposer.causal_reasoning`. `[BLOAT_ALERT]` fires 14/14 iters (by design — North Star).

The V12 calibration also surfaced **three findings the Rev 6 spec did not anticipate**, requiring Phase 2 to be re-scoped:

1. **`interpretation.per_model` is the hidden #2 bleeder** — slope **+5,947 tok/iter (R²=0.98)**, nearly **2× `interpretation.synthesis`'s slope** (+2,982/iter). Mechanism is *not* prompt-size growth: it is **call-count multiplication**. Iter 1 = 2 per_model calls; iter 14 = 12 calls — one per accumulated `model_type`. Commit 6.1 as specced in Rev 6 only clamped synthesis prompt size; it did nothing about call multiplication. **Commit 6.1 is expanded** to add a "Stability Filter" — only LLM-summarize model_types active in the current iter or showing significant score deltas; pull stable historicals from the cache without a fresh LLM call.

2. **`expert_context_block` grew 24.30×** (7,476 → 181,668 chars) — by ratio, the **largest O(N) bleeder of any component**. Was not on the Phase 2 dehydration list at all. **New Commit 6.3** added: "Knowledge Consolidation" — every iter, perform a Merge & Prune over the accumulated findings, collapsing similar entries into a bounded set of **5–8 high-signal conclusions**. Bounds the block to a fixed budget regardless of iter count.

3. **`template_and_scaffolding` grew 11.00×** (50K → 555K chars). Partly explained by call-count doubling (iter 1: 20 calls; iter 14: 40 calls including 2 `implementor.repair`), but per-call scaffolding still inflates ~5×. The catch-all is computed as `chars.total - sum(other_9_named_components)`, so an 11× growth implies dynamic content is leaking out of the 9 named keys into the unnamed bucket — i.e., our 10-key attribution is regressing as iterations accumulate. **New Commit 4.3.2** (Phase 1 amendment, blocks Phase 2): an Attribution Audit must locate the leak and either (a) add a missing component key to capture the un-attributed content, or (b) prove the growth is genuinely structural (more calls per iter, not unaccounted bytes per call). **Phase 2 surgery is gated on this audit** — we do not optimize numbers we don't trust.

- **Phase 1 reopened** to admit Commit 4.3.2 as a hard gate for trusting the per-component breakdown.
- **Commit 6.1 expanded** to address call-multiplication, not just prompt-size growth.
- **Commit 6.3 added** as a sibling of 6.1/6.2 — Knowledge Consolidation for `expert_context_block`. Critical Priority alongside 6.1.
- **Phase 3 unchanged** — Template Dehydration remains optional, post-G1.5.
- Commit Map redrawn (see end of §8).

### Revision 8 changelog (2026-05-05) — "Drain the Swamp" Pivot

**Status**: Commit 4.3.2 **CLOSED with H1 verdict** — leak located and fixed. Phase 2 unblocked.

The 4.3.2 forensic audit produced a definitive answer:

1. **H1 (attribution leak) confirmed; H2 ruled out.** Per-call `template_and_scaffolding` grew **8.6 K → 92.8 K chars (10.75×) inside a single proposer call** (iter 1 → iter 14, same `proposer.proposing` happy-path row). H2 (call-count amplification) requires a stable per-call value — the data shows the opposite. Cross-label uniformity (`proposer.proposing` 92.8 K, `comparison` 91.2 K, `causal_reasoning` 92.6 K at iter 14, all within ±2 %) further confirms a shared content leak, not call multiplication.

2. **The leak is `non_candidates_overview`.** The forensic single-row diff isolated **+84,160 chars** of un-attributed growth at iter 14. Reconstruction of the proposer's `accumulated["non_candidates_overview"]` (built at `nodes/ml_model_proposal_agent.py:1010-1034` from `model_descriptions` + `model_knowledge_cache`) sized this single field at **15,440 chars (iter 1) → 109,991 chars (iter 14) — Δ +94,551 chars**, accounting for **113 % of the catch-all delta** (upper-bound reconstruction; the small over-shoot is the reconstruction assumption that all non-proposed model_types are non-candidates). The audit hook listed `non_candidates_overview` as a `_PROPOSER_INPUT_KEY` (excluded from `prior_stage_outputs`) but never gave it a dedicated component key, so its chars fell through to the catch-all.

3. **Upstream sources are shared with `expert_context_block`.** Both `non_candidates_overview` (Rev 8 leak) and `expert_context_block` (Rev 7 24× bleeder) draw from `model_knowledge_cache` (24 K → 275 K, 11.4×) and `model_descriptions` (6.7 K → 56 K, 8.4×). This is the single largest mechanical insight of Rev 8: **two of the four worst leaks share one root**. Pruning `model_knowledge_cache` at the source dehydrates both downstream blocks for free. This reframes Commit 6.3's scope.

Changes landing in Rev 8:

- **Commit 4.3.2 closed** — H1 confirmed; verdict, evidence chain, and per-row data appended in §8.
- **New Commit 4.3.3** (Phase 1, ships before Phase 2): `_audit_proposer_components` gains an 11th content key — `non_candidates_overview`. The bridge's catch-all formula auto-shrinks to the true wrapper baseline (~8 K chars per call). 5 unit tests pin the contract (10-key set, char-accounting, leak-attribution non-overlap with `prior_stage_outputs`, sum invariant). All proposer-row consumers (`tools/build_token_baseline_report.py`, the §1.9 Top-3 table) now operate on a trusted breakdown.
- **Commit 6.3 escalated** — pivots from "expert_context_block injection-point pruning" to **Centralized Cache Dehydration** at `model_knowledge_cache`. Same Merge & Prune algorithm, but applied at the source so both `non_candidates_overview` and `expert_context_block` shrink simultaneously. Adds an explicit **Error-Signature Preservation Guard**: the consolidation algorithm must keep every unique `failure_class` + `last_frames` signature (Commit 6 schema) so the Gate G3 Trap Test (§2.9) — which assumes a fatal flaw planted at iter 2 is still cited at iter 10 — still passes.
- **Commit 6.1 unchanged** in scope; the cache-source dehydration in 6.3 also reduces the `interpretation.per_model` per-call payload, but the call-multiplication clamp (Stability Filter) is orthogonal and remains a separate fix.
- **Phase 1 closes** with Commit 4.3.3. Phase 2 entry is unblocked.
- Commit Map redrawn (Rev 8 — see end of §8). G1.5 expanded to 5 metrics (the new metric tracks the cache dehydration's impact on both downstream blocks).

### Revision 8.1 changelog (2026-05-05) — "Closing the Creativity Gap"

**Status**: Rev 8 spec'd Memory (Trap Test, G3) and Integrity (Hybrid DRR, G4) safeguards but had no aspirational metric for **Retained Capability** — every existing intelligence metric was *defensive* (catches regressions). Rev 8.1 adds the missing pillar.

The audit finding driving Rev 8.1: FRR catches "don't repeat bads" and DRR catches "claims = code", but neither asks the question — *can the dehydrated agent still navigate to the high-signal architectures the V12-rich-context agent discovered?* An agent could pass G3 + G4 and still produce mediocre-but-honest proposals because the consolidator's Merge & Prune dropped the high-signal architectural insight that originally drove SOTA. We need a guard that proves consolidation does not "lop off the peak" of our collective wisdom.

Changes landing in Rev 8.1:

- **New §2.10 — Gate G3.5: SOTA Replication Test.** Pick a "Golden Iteration" from the V12 baseline (the iter that produced the highest `denoising_score`), reconstruct its upstream state, push it through the post-6.3 dehydrated cache, and let the proposer make a real LLM call. Compare the new proposal against the V12 original on two axes: **Structural Fidelity ≥ 0.7** (AST match on encoder/decoder/key innovations) and **Reasoning Density ≥ 75 %** (LLM judge on `delta_reasoning` informativeness). Failure = consolidator is pruning load-bearing creative signal.
- **§4.2 metric #12 — SOTA Retention Rate (SRR).** Aggregate of G3.5 across the top 3 V12 architectures: pass on **≥ 2 of 3**. Below target blocks Phase 2 exit.
- **New Commit 11.2 — `tools/verify_sota_replication.py`.** Automates Golden-State extraction from V12 artefacts + AST/LLM-judge comparison. Lands alongside Commit 11 (Trap Test) so G3 and G3.5 can be evaluated together.
- **Commit Map redrawn.** G3.5 inserted between G3 (Trap) and G4 (Full V13 Metrics) in the Phase 2 sequence.

**Framing**: Rev 8.1 shifts the conversation from "how much can we cut?" to "how much signal must we keep?" The Trap Test protects Memory; Hybrid DRR protects Integrity; SOTA Replication protects Creativity. The agent must not only be small and honest — it must remain a world-class architect.

### Revision 8.2 changelog (2026-05-05) — "Knowledge Accumulator"

**Status**: Phase 2 entry. Code audit (2026-05-05) of `model_knowledge_cache` exposed a structural mismatch between the Rev 8 Commit 6.3 spec and the production code. Documented here so the next contributor sees the gap before writing a single line of consolidator code.

**The audit finding**:

1. **Cache is a frozen snapshot, not a cumulative ledger.** `nodes/result_interpretation_agent.py:687-693` shows the cache-hit branch literally copies the prior iter's entry verbatim and skips the LLM call entirely. The cache-miss branch (L722-738) builds a fresh entry from a single LLM response + `_stats`. There is **no path** that merges new findings into an existing entry across iters. Once a `model_type` is summarised, its findings are frozen — even if the same architecture is re-tuned at a later iter and produces new evidence.
2. **The Rev 8 6.3 spec assumed accumulation.** The "Merge within `(model_type, field)` bucket — collapse overlapping statements into one with unioned `evidence_iters`" algorithm presupposes a list of statements grew across iters. Under current code there is nothing to merge — each entry has a single iter's findings.
3. **The Rev 8 6.3 spec listed schema fields that don't exist in code.** The spec's `lessons`, `recommendations`, `error_signatures` keys are not in the production cache. The actual entry has 8 LLM text fields (`key_findings, bottlenecks, best_config_analysis, score_trend, per_file_analysis, data_sensitivity, efficiency_assessment, strategy_assessment`) plus `_stats`. The doc and code drifted apart.
4. **Cache count is already capped, content is not.** `workflows/model_exploration.py:369-392` (`_cap_knowledge_cache`) caps to **5 entries** by best_score + current model. So the per-entry size (~25 K) × 5 = 125 K floor — already exceeds the Rev 8 ≤60 K target *under the existing schema*. Per-entry truncation is required regardless of whether accumulation is added.

**The decision (2026-05-05)**: choose Option (A) — Schema Rewrite + Accumulation Logic. The "frozen snapshot" cache is the antithesis of an evolutionary system: a fatal lesson learned at iter 2 must survive even if the same architecture is re-tested and re-summarised at iter 20. Truncation alone (Option B) does not solve this; it only bounds size. Option (A) bounds size *and* preserves cumulative wisdom.

Changes landing in Rev 8.2:

- **Commit 6.3 promoted** from "Source-Level Merge & Prune" to **Knowledge Accumulator Refactor** — see refined spec in §8. Two-part work: (i) cache update path refactor so a cache hit performs a *light merge* (compare new LLM output against cached entry, append/distill the delta) instead of a verbatim skip; (ii) consolidated schema reconciles the 8 existing fields with the new accumulator fields, plus `error_signatures` (Commit 6 schema, load-bearing for G3). Per-entry merge & prune happens *inside* the cache update path.
- **Sequencing fixed**: 6.1 → 6.3 (was: 6.1, 6.2, 6.3 in priority order). Rationale: 6.1 (Stability Filter) is well-defined against the current frozen-cache code and addresses the immediate +5,947 tok/iter bleed. 6.3's cache-path refactor depends on 6.1's "Active Model" decision (only active models trigger a re-call → only those entries get merged). Doing 6.3 first would mean refactoring against a soon-to-change call-dispatch path.
- **6.2 (Proposer prior_stage_outputs)** unchanged in scope; sequenced after 6.1 and before 6.3, since 6.2 is independent of cache mechanics.
- **No changes** to Gates G3 (Trap Test) or G3.5 (SRR) — both still pass against the post-6.3 accumulator cache, and the Error-Signature Preservation Guard remains load-bearing for G3.

**Why this matters for the safeguards**: G3 (Trap Test) plants a fatal flaw in iter-2 ledger and asserts citation at iter 10. Under the current frozen-cache, this passes trivially (the iter-2 finding is never overwritten — it's just never *enriched* either). Under the Rev 8.2 accumulator, the iter-2 error_signature must merge correctly with iter-10 evidence (set-union, not replacement). The Pre-Commit Checklist for 6.3 must pin both behaviours.

### Revision 8.3 changelog (2026-05-05) — "Subprocess Amnesia" Fix

**Status**: mid-Commit-6.1. A production-chain audit (2026-05-05, between Commit 6.1's helper-layer landing and dispatcher wiring) discovered that `model_knowledge_cache` is **persisted but never restored** across chain-subprocess boundaries. This is the root cause of the +5,947 tok/iter `interpretation.per_model` slope that Commit 6.1 was meant to clamp — the Stability Filter would be dead code in production until cache restoration is added.

**The audit finding** (verified against current code, 2026-05-05):

1. **Production path is chain-mode, one subprocess per iter.** `sdsc_submission_scripts/run_chain.sh` invokes `run_one_iteration.py` per iter — lilab mode forks foreground, SDSC mode `sbatch --dependency=afterany`. Each iter is a fresh Python process; no in-memory state survives.
2. **`RestoredState` carries 8 fields, none for the cache.** `core/resume.py:128-135` defines `RestoredState` with `resolved_source_paths`, `restored_plugins`, `committed_iters`, `runtime_vocab`, `accumulated_key_findings`, `accumulated_physical_rejections`, `accumulated_gate_exhaustions`, `previous_proposal_data`. **No 9th field for `model_knowledge_cache`.**
3. **`load_latest_knowledge` ignores the cache.** `core/resume.py:262-339` reads each prior iter's `interpretation_iter_NNN.json` digest but only consumes `runtime_vocab` and `key_findings`. The digest's `model_knowledge_cache` field is left on disk.
4. **`run_workflow` is invoked with 5 carry-over kwargs, not 6.** `run_one_iteration.py:830-890` threads `restored_runtime_vocab`, `accumulated_key_findings`, `accumulated_physical_rejections`, `accumulated_gate_exhaustions`, `restored_previous_proposal`. **No `restored_model_knowledge_cache=...` kwarg exists in either the call site or the workflow signature.**
5. **Cache resets every subprocess.** `workflows/model_exploration.py:830` — unconditional `model_knowledge_cache: dict = {}`. No `if restored_*: ... else: {}` branch.
6. **The Stability Filter has no production target.** `nodes/result_interpretation_agent.py:687-693` cache-hit branch (`if mt in inp.model_knowledge_cache: ... continue`) is the *only* code path that skips a per_model LLM call. In chain mode, `inp.model_knowledge_cache` is the empty dict from step 5 → every `mt` falls through → fresh LLM call per model per iter, regardless of what `should_recall_per_model()` returns.

**Empirical confirmation** (V12 `explore_novel_v12_0504`, audit log + on-disk digests):

| iter | per_model calls | per_model summed prompt tokens | synthesis prompt tokens | cache entries on disk |
|---|---|---|---|---|
| 1 | 2 | 7,272 | 4,657 | 2 |
| 7 | 6 | 29,574 | 20,958 | (mid-chain) |
| 14 | 12 | 69,669 | 44,903 | 10 (iter_012 digest) |

The cache **does** accumulate on disk — iter_005 has 5 entries, iter_012 has 10. Persistence works; restoration is the gap.

**Why doc lines 753 and 1957 contradicted each other**:
- Line 753 ("cache hit-on-repeat, calls grow only on new architecture") is **true for in-process runs** (single Python process loops `range(start_iteration, start_iteration + max_iterations)` and the iter-end re-assignment keeps the dict alive).
- Line 1957 ("fresh LLM call for every model_type ever proposed, on every iter") is **true for chain mode** (the actual production path).

Both authors were right about their respective regime; the regime difference itself was undocumented.

**Changes landing in Rev 8.3**:

- **NEW Commit 6.1.a — Knowledge Restoration (precondition for 6.1).** Extend `RestoredState` with a `model_knowledge_cache` field, extend `load_latest_knowledge` (or a sibling loader) to read the latest committed iter's `model_knowledge_cache` from `interpretation_iter_NNN.json`, thread `restored_model_knowledge_cache=...` as a 6th carry-over kwarg through `run_one_iteration.py:830-890`, and accept it in `workflows/model_exploration.py` to seed the L830 dict. Latest-wins semantics (parallel to `runtime_vocab`). After this lands, chain mode has cache hits → 6.1's Stability Filter has actual targets to gate.
- **Sequencing**: 6.1.a → 6.1 (resume current scope: dispatcher wiring + audit markers) → 6.3 (Knowledge Accumulator). The 6.1 spec itself does not change — its tasks were already correct against the in-process semantics; 6.1.a just makes those semantics apply in production.
- **Commit 6.1 intro updated** to name 6.1.a as the precondition. The existing 4 helper-layer tasks/tests (`select_active_models`, `compress_model_summary`, `should_recall_per_model`, schema fields) stay marked complete — they are correct as-is. Only the dispatcher wiring (T4) and end-to-end Pre-Commit checks now have a real target.
- **NEW Commit 4.3.4 — Legacy Runner Deletion (standalone cleanup).** Remove `run_exploration_adaptive.py` and update its 4 test dependencies + `launch_v11_v4.sh` to reference `run_one_iteration.py` (or local helpers). Ships **after** 6.1.a + 6.1 land — bundling it into the cache-restoration commit would conflate "fix subprocess amnesia" with "delete dead code", and the legacy runner has live test imports (`test_chain_consistency.py`, `test_portion_floor.py`, `test_token_log_iter_rollup.py`, `test_resilience.py`). Per "Slow is Smooth", clean cuts only.
- **No changes** to Commits 6.2, 6.3, or any Phase 2 gate. G1.5's 5-metric re-baseline still applies; metric (2) (`interpretation.per_model` calls per iter) is the one most directly unblocked by 6.1.a.

**Why this matters for chain-mode invariants**: the existing 5 carry-over kwargs already cover *evidence* (vocab, findings, rejections, gate exhaustions, prior proposal). The 6th — `model_knowledge_cache` — covers *summarised knowledge*: the LLM-distilled per-model interpretation that turns raw evidence into a Phase-1 cache entry. Without it, every chain subprocess re-pays the summarisation cost from scratch. With it, the chain's "memory" is complete and the Stability Filter starts saving real tokens.

---

## 0. Problem Statement

V11 production runs exhibit linear growth in proposer prompt size across iterations. The §12 audit identified the root causes:

1. **Telemetry blindspot** — `agent/llm_bridge.py` discards `response.usage` (prompt_tokens / completion_tokens). The only token signal we have is the `[PROMPT_SIZE] N chars` debug print. We are estimating, not measuring.
2. **Unbounded JSON region** — `interpretation['per_model_score_tables']` is dumped verbatim into the JSON region of every stage's user prompt (`_render_stage_user_prompt`, `ml_model_proposal_agent.py:444`). Markdown is bounded by `select_candidate_models(top_n=5)`; JSON is not.
3. **Repeated boilerplate** — at iter 4, ~41% of the proposer prompt is static scaffolding repeated verbatim every iter (vocabulary, hardware context, instructions, forward contract).
4. **Shallow feedback** — `previous_failures` is a flat list of `[PHYSICAL REJECTION]` strings (`ml_model_proposal_agent.py:644-646`). No causal pattern is extracted across iters; no reflection step compares attempt N-1 to attempt N.
5. **No sliding window for code** — full source is implicitly carried for every prior attempt via the candidate markdown blocks, regardless of how relevant N-k is to the current decision.

Goal: replace the current "digital hoarding" with a **Structured Evolutionary Ledger** — bounded, dehydrated, and explicitly delta-aware — while gaining first-class telemetry to verify the fix.

The work splits into two strictly ordered phases. Phase 1 ("the Scale") must land first; we cannot claim Phase 2 ("the Blade") was successful without Phase 1's measurements.

---

## 1. Phase 1 — Real-Time Audit & Telemetry ("the Scale")

### 1.1 Goals

| # | Outcome | Verifies |
|---|---------|----------|
| 1.1 | Every LLM call writes a structured `token_usage.jsonl` row to the workspace, with real `prompt_tokens` / `completion_tokens` from the API response. | We stop estimating. |
| 1.2 | Every proposer call writes a per-component breakdown (system / vocabulary / interpretation_json / prior_results / previous_failures / prior_stage_outputs) to the same log. | We can answer "which component bloated" per iter. |
| 1.3 | `chain_log.txt` carries a one-line summary at each LLM call so a `tail -f` shows live spend. | Operators can spot a runaway component at iter 5, not iter 30. |

### 1.2 API Usage Capture — `agent/llm_bridge.py`

**Current**: `_chat_json` (line 578), `generate_text` (line 682), and `tool_call` (line 701) all discard the API response after extracting `.choices[0].message.content`. The `response.usage` field is never inspected.

**Change**: introduce a thin wrapper helper:

```python
def _record_usage(self, *, response, label: str, system_prompt: str,
                  user_prompt: str, extra: Optional[dict] = None) -> None:
    """Append one row to {workspace}/token_usage.jsonl."""
```

It:

1. Pulls `response.usage.prompt_tokens`, `completion_tokens`, `total_tokens` (OpenAI-compatible — verified for the providers we use: openai, deepseek, gemini-via-openai-shim).
2. Records `len(system_prompt)` + `len(user_prompt)` as char counts (cheap cross-check).
3. Captures `model_name`, `label` (the call-site identifier — see §1.5), `timestamp`, `iter` (read from `LLMBridge.context_iter`, see §1.4), and any caller-supplied `extra` dict.
4. Appends to `{workspace}/token_usage.jsonl` (one JSON object per line, never rewritten).

**Hook sites**: every place `client.chat.completions.create(...)` is currently called inside the bridge — `_chat_json` (line 604) and `generate_text` (line 689) and `tool_call` body. Three call sites, one helper.

**Failure handling**: if `response.usage` is missing (older API shape, or stream mode), record `None` for token counts but still emit the char-level row. Never let telemetry failure abort a real run.

### 1.3 Component-Level Pre-Assembly Hook — `nodes/ml_model_proposal_agent.py`

**Current**: `_render_stage_user_prompt(accumulated)` (line 444) returns one merged string. The `accumulated` dict has known keys (`candidates`, `non_candidates_overview`, `interpretation_summary`, `existing_model_types`, `previous_failures`); on top of that the caller appends `agent_cards_block`, `expert_context_block`, `vocab_block` (lines 1001-1006). We have no granular size data.

**Change**: introduce `_audit_proposer_components(accumulated, agent_cards_block, expert_context_block, vocab_block, system_prompt) -> dict` called immediately before `self.bridge.generate(...)` at line 1014 / 1134. Returns a dict like:

```python
{
    "stage_name": "causal_reasoning",
    "iter": 4,
    "components": {
        "system_prompt":        len(system_prompt),
        "candidates_markdown":  len(markdown_block),
        "interpretation_json":  len(json.dumps(cleaned_interp)),
        "previous_failures":    sum(len(s) for s in inp.previous_failures),
        "vocab_block":          len(vocab_block) if vocab_block else 0,
        "expert_context_block": len(expert_context_block) if expert_context_block else 0,
        "agent_cards_block":    len(agent_cards_block) if agent_cards_block else 0,
        "prior_stage_outputs":  len(json.dumps(_extract_prior_stage_keys(accumulated))),
        "recent_gate_block":    len(_format_recent_gate_exhaustions_block(inp.recent_gate_exhaustions)),
    },
    "total_chars": <sum>,
}
```

The breakdown is passed into `LLMBridge._record_usage` as the `extra` argument so each row in `token_usage.jsonl` has both API-side counts (post-tokenization) and component-level char counts (pre-tokenization). The two together let us identify the bloating component **before** we have a tokenizer that reproduces OpenAI's exact split.

### 1.4 Workspace + iter context — minimal plumbing

`LLMBridge.__init__` does not currently know which workspace or which iteration the call is part of. Two options:

| Option | Sketch | Cost |
|--------|--------|------|
| **A. Pass `workspace` + `iter` into bridge constructor** | `WorkflowLLMConfig` already carries workspace; thread `iter` through `Workflow.run(iter=...)`. | Touches every node `run()` signature — invasive but explicit. |
| **B. Module-level setter on bridge** | `LLMBridge.set_run_context(workspace, iter, run_name, run_id)`; called once per iter at the top of the workflow. | One call site. Less invasive. State is per-instance, not global. |

**Recommendation: B.** The bridge is already an instance per node; one setter at iter boundaries is cleaner than threading kwargs everywhere. Setter writes to `self._token_usage_path`, `self._iter`, `self._run_id`. If unset, `_record_usage` falls back to a sentinel path (`/tmp/token_usage_unbound.jsonl`) and stamps `run_id="unbound"` so unit tests still work but production rows are immediately distinguishable.

#### 1.4.1 Setter Safety Protocol — Context Flush & Validate

Module-level state on a long-lived bridge instance is a known foot-gun: an iter-N call could silently log into iter-(N-1)'s row stream if the setter is not called, called late, or called with stale arguments. The protocol below makes leakage detectable and self-blocking rather than silent.

**Run-ID generation** (one per chain run, immutable for the run's lifetime):

```python
# At workflow startup, deterministic from (run_name, ts):
run_id = f"{run_name}-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
```

`run_id` is generated once at `run_exploration_adaptive.py` start and threaded as the *only* identity argument through the workflow. It is the immutable owner of the `token_usage.jsonl` file.

**Setter contract** (`LLMBridge.set_run_context`):

1. Records `(workspace, iter, run_name, run_id)` plus a `set_at_ts` timestamp.
2. **Refuses `run_id` mutation mid-stream**: if `self._run_id is not None and run_id != self._run_id`, raise `LLMBridgeContextError`. This is the one case where telemetry failure should be loud — a wrong run_id means we're about to corrupt another run's log.
3. Permits `iter` advancement only forward (`new_iter >= self._iter`); same-iter re-entry is allowed for stage retries; backward-iter is rejected with the same error.
4. On legitimate iter advancement, calls `_flush_iter_marker()` (see below) before the new iter takes effect.

**`_flush_iter_marker()`** (called at iter boundary):

Writes one synthetic row at iter end:

```json
{"ts": "...", "label": "_iter_flush", "iter": 4, "run_id": "...", "marker": "iter_end"}
```

This is the audit trail for "iter 4 telemetry stream is closed; iter 5 begins on the next row." Any `iter=4` row appearing *after* an `_iter_flush` for iter 4 is a leak and is detectable by a one-pass linter on the JSONL file (added as a unit test in §1.8).

**Per-row validation in `_record_usage`**:

Before each append, the helper asserts:

| Check | Failure mode | Action |
|-------|--------------|--------|
| `self._run_id` matches the file's first-row `run_id` | Wrong workspace target | Raise `LLMBridgeContextError`, never write. |
| `self._iter` is not less than the last logged iter | Backwards leak | Raise `LLMBridgeContextError`. |
| `self._token_usage_path` exists and is writable | Path corruption | Raise OSError; do not silently swallow. |
| `ts` is monotonically non-decreasing per (run_id, iter) | Clock skew or stale call | Log warning to stderr; still write the row (clock issues are real but rare). |

The first-row `run_id` check is the strongest guard: when the bridge is first asked to write, it reads the file's first line (if any) and verifies the `run_id` matches its own. A mismatch means we're pointing at an *earlier* run's log file — the bridge refuses to write rather than corrupt history.

**Workspace ownership**: only the workflow that owns `run_id` may write to `{workspace}/token_usage.jsonl`. A second concurrent workflow targeting the same workspace would fail the first-row check on its first write and abort — which is the correct behaviour, not a bug.

**Failure handling philosophy**: telemetry-internal corruption (stale iter, wrong run_id) is **loud** — these mean the audit log is unreliable and the operator must see it. Telemetry-data corruption (provider didn't return `usage`, clock skew) is **quiet** — log a warning, write what we have. The two failure classes have different operational responses.

#### 1.4.2 Run-ID Fail-Fast — formal contract

A Run-ID mismatch is **never** recoverable in-process. The bridge does not attempt to "fix" the context, retry, or fall back to a default path. Specifically:

```python
class LLMBridgeContextError(RuntimeError):
    """Audit-log integrity violation. Process must abort.

    Raised by LLMBridge when the run-context invariants in §1.4.1 are violated.
    Catching this exception inside the bridge or its callers is forbidden — the
    only legitimate handlers are (a) the top-level workflow runner, which
    re-raises after writing a SystemExit-class shutdown record, and (b) tests
    that explicitly assert raise behavior.
    """
```

**Mandatory contract**:

1. The bridge **raises** `LLMBridgeContextError` synchronously, before the offending row is written. The corrupting row never reaches disk.
2. The exception is **uncaught by intent** — `agent/llm_bridge.py` must not wrap any of the four checks in try/except. Static check (`tests/unit/agent/llm_bridge/test_no_silent_swallow.py`) AST-greps the bridge module to ensure no `except LLMBridgeContextError` exists in production code.
3. The runner (`run_exploration_adaptive.py`) installs a top-level handler that on `LLMBridgeContextError`:
   - Logs a structured shutdown row to stderr + `chain_log.txt`: `[FATAL] LLMBridgeContextError: <reason> — aborting run to prevent telemetry corruption.`
   - Calls `sys.exit(2)` (distinct from the `exit(1)` used by the consecutive-failure brake, so a downstream classifier can tell the two apart).
4. **No workaround flag exists.** There is no `--skip-runid-check` CLI option. If the check is wrong, the fix is to fix the bridge, not to bypass the check.

**Rationale**: a corrupted `token_usage.jsonl` poisons every metric in §4. Continuing past a known corruption point produces audit data that *looks* valid but isn't — the worst possible failure mode. Aborting is safer than producing convincing-but-wrong numbers.

**Tested by** `test_runner_aborts_on_runid_mismatch`: spawn a subprocess runner pointed at a workspace whose `token_usage.jsonl` already has a different run_id; assert exit code 2 and the FATAL log line.

**Tests** (added to §1.8):

| Test | Asserts |
|------|---------|
| `test_setter_rejects_run_id_mutation` | Calling `set_run_context` twice with different `run_id` raises `LLMBridgeContextError`. |
| `test_setter_rejects_backwards_iter` | Calling `set_run_context(iter=3)` after `set_run_context(iter=5)` raises. |
| `test_record_usage_aborts_on_run_id_mismatch` | Writing to a file whose first row has a different `run_id` is refused. |
| `test_iter_flush_marker_emitted` | After advancing iter, the previous iter has an `_iter_flush` marker as its last row. |
| `test_jsonl_linter_detects_leakage` | One-pass linter flags a row with `iter=N` that appears after the `_iter_flush` for iter `N`. |

### 1.5 Call-Site Labels

Each LLM call must have a stable `label` that names *which* prompt fired. Today the only signal is the inconsistent `[PROMPT_SIZE] {label}` print. Standardize on:

| Label | Site |
|-------|------|
| `proposer.comparison` | `_render_stage_user_prompt` for `COMPARATIVE_ANALYSIS` stage |
| `proposer.causal_reasoning` | same, `CAUSAL_REASONING` stage (incl. boldness retry) |
| `proposer.proposing` | same, `proposing` stage (line 1134 region) |
| `proposer.legacy_reasoning` | legacy 2-call path, `generate_text` at `ml_model_proposal_agent.py:780` |
| `proposer.legacy_commit` | legacy 2-call path, `generate` at `ml_model_proposal_agent.py:797` |
| `tuner.planner` | `agent/llm_bridge.py:401` (existing planner call) |
| `tuner.reflector` | `LLMBridge.reflect` (line 403) |
| `interpretation.per_model` | `result_interpretation_agent.py:714` |
| `interpretation.synthesis` | same, line 820 |
| `interpretation.dedup` | same, line 1179 |
| `validator.code_review` | wherever the validator's LLM step calls `generate` |
| `implementor.reasoning` | `ml_model_implementor.py:751` (free-text reasoning call) |
| `implementor.code` | `ml_model_implementor.py:756` (strict-JSON code commit) |
| `implementor.repair` | `ml_model_implementor.py:769` (validate→repair loop) |

Add the label to every call site as an explicit arg threaded through `bridge.generate(label=...)`. The bridge stores it in the row.

**Component breakdowns** are passed only by call sites that build their user prompt via `_render_stage_user_prompt` (the staged proposer pipeline + boldness retry + proposing). The legacy 2-call path uses `_build_reasoning_prompt` / `_build_commit_prompt` and does not produce a structured-key breakdown — its rows leave `components` empty (still labeled, so chain_log stays clean). See §1.3 for the breakdown shape (currently 10 named keys + 1 catch-all = 11 keys total per proposer row, post-Commit-4.3.3).

### 1.6 chain_log.txt Live Reporting

Per-call line, written to stdout (already tee'd into `chain_log.txt` by Phase R `_TeeStream`):

```
[TOKEN] iter=04 stage=proposer.causal_reasoning  prompt_tok=11423  comp_tok=842  total_tok=12265  chars(sys/user)=1812/40081
```

And one per-iter rollup line (emitted by the workflow at iter end after all calls have flushed):

```
[TOKEN_ITER] iter=04 calls=12 total_tok=148231 (proposer=87421  tuner=42109  interp=18701)  cumulative_total=412903
```

Operators can `grep '\[TOKEN_ITER\]' chain_log.txt | awk ...` for a per-run cost sparkline.

### 1.7 Schema — `token_usage.jsonl`

One JSON object per line:

```json
{
  "ts":         "2026-05-04T15:32:11.443Z",
  "run_name":   "exploit_cnn_v11_0503",
  "iter":       4,
  "label":      "proposer.causal_reasoning",
  "model":      "gpt-4o-mini",
  "provider":   "openai",
  "tokens": {
    "prompt":     11423,
    "completion": 842,
    "total":      12265
  },
  "chars": {
    "system":  1812,
    "user":    40081,
    "total":   41893
  },
  "components": {
    "system_prompt":        1812,
    "candidates_markdown":  9213,
    "interpretation_json":  14207,
    "previous_failures":     1042,
    "vocab_block":           3754,
    "expert_context_block":   612,
    "agent_cards_block":      488,
    "prior_stage_outputs":   7104,
    "recent_gate_block":     3661
  },
  "extra": { "stage_idx": 1, "attempt": 1 }
}
```

Pydantic schema lives at `agent/schemas/telemetry/token_usage.py`. A new module — there is no existing telemetry schema package; the V11 audit is the first call site that needs it, so we introduce it here and reuse for any future per-call audits.

### 1.8 Unit + integration tests

| Test | Scope |
|------|-------|
| `tests/unit/agent/llm_bridge/test_record_usage.py` | Mock the OpenAI client to return a fixed `Usage(prompt_tokens=…)` shape; assert one row appended to a tmp_path log. Cover the `usage is None` fallback. |
| `tests/unit/agent/ml_model_proposal_agent/test_audit_components.py` | Build a synthetic `accumulated` dict + blocks; assert all 10 named component keys present (post-Commit-4.3.3; was 9 pre-4.3.3) and sum to total. |
| `tests/unit/runner/test_token_log_iter_rollup.py` | Mock 3 LLM calls with known token counts; assert the `[TOKEN_ITER]` rollup line is emitted with correct totals. |
| Pseudo-mode integration | Run a one-iter pseudo workflow end-to-end; assert `token_usage.jsonl` exists and parses; assert ≥4 rows (proposer × 3 stages + interp × 1). |

No real-API tests required for Phase 1 — the usage-capture path is exercised by the mock, and the row-shape contract is what we care about.

### 1.9 Top-3 Bloat Report — mandatory Phase 2 gate

After Phase 1 lands, run a real chain (≥ 5 iterations, V11-equivalent settings) and produce `reports/v12_top3_bloat.md`. **Phase 2 cannot start until this report is written and reviewed** — the §12 audit was estimation; this is measurement.

#### 1.9.1 What the report must contain

For each of iterations 1–5:

| Column | Source |
|--------|--------|
| `iter` | row `iter` field |
| `total_prompt_tokens` | sum across all calls |
| `top_3_bloat` | the 3 component-keys with the largest `chars.components.<key>` values, ranked, with their token estimates |
| `top_3_share_pct` | what fraction of total prompt tokens those 3 components account for |
| `growth_vs_iter1` | per-component delta from iter 1 baseline |

Plus an aggregate table:

| Component | Iter 1 chars | Iter 5 chars | Growth | Verdict |
|-----------|--------------|--------------|--------|---------|
| `interpretation_json` | … | … | … | bloating / bounded / shrinking |
| `candidates_markdown` | … | … | … | … |
| `previous_failures` | … | … | … | … |
| `vocab_block` | … | … | … | … |
| `system_prompt` | … | … | … | … |
| `prior_stage_outputs` | … | … | … | … |
| `expert_context_block` | … | … | … | … |
| `agent_cards_block` | … | … | … | … |
| `recent_gate_block` | … | … | … | … |

The `Verdict` column uses fixed thresholds: `bloating` if growth > 30% iter-over-iter, `bounded` if within ±10%, `shrinking` if < -10%.

#### 1.9.2 The decision branch

The report ends with one of three explicit verdicts:

1. **"Confirmed Proposer Hypothesis"** — top-3 bloat is dominated by `interpretation_json`, `candidates_markdown`, `previous_failures`, or `prior_stage_outputs`. Phase 2 proceeds as designed in §2.
2. **"Pivot Required — Tuner"** — top-3 bloat is dominated by tuner planner / reflector calls (visible in row `label` = `tuner.planner` / `tuner.reflector`). Phase 2 surgery target shifts from proposer to tuner; the §2 design is set aside and a tuner-focused dehydration design is drafted instead.
3. **"Pivot Required — Other"** — bloat is somewhere else (interpretation synthesis, validator code review, or an unexpected component). Surgery follows the data; we draft a new design before any code lands.

The Phase 2 §2 design is therefore **conditional**: it only applies if verdict (1) is reached. Verdicts (2) or (3) trigger a fresh design pass, not blind execution of §2.

#### 1.9.3 Sanity floor

If verdict (1) is reached **but** total token spend at iter 5 is < 1.5× iter 1 (i.e., growth is gentler than expected), the design lead may decide Phase 2 is not yet justified — the cost is real but small enough that the engineering effort doesn't pay off. This is an explicit "do nothing" exit; document the decision and revisit at iter 15.

---

## 1.5 Phase 1.5 — Certification (mandatory gate before V12 baseline)

> **Runner unification (2026-05-04, Commit 4.3)**. The original Phase 1.5 gates (T0 / T1 / T2)
> were certified under `run_exploration_adaptive.py`. During the V12 launch we discovered a
> parity gap: V12 production uses the chain-first runner (`run_chain.sh` →
> `sdsc_submission_scripts/run_one_iteration.py`), which was not instrumented with
> `set_run_context` — so `token_usage.jsonl` was never written for V12 despite real LLM
> calls happening. Commit 4.3 closes the gap by porting the audit context, run_id sidecar,
> fail-fast handler, and `[TOKEN_ITER]` rollup into the chain-first runner. The adaptive
> runner is **deprecated** — all future certification and production runs use
> `run_one_iteration.py` (wrapped in a small bash loop for multi-iter gates). The historical
> T1/T2 attestations below are preserved unchanged as audit-trail proof that the
> bridge / workflow / audit-hook code is correct; new attestations from the chain-first
> runner appear in §1.5.1.1 (T1-Sanity).

The infrastructure committed in §8 Commits 1–4 is not trusted in production until three
certification gates have been observed green. They form a cost-ladder of increasing
confidence and increasing GPU/wall-clock cost:

| Gate | Surface | Real LLM? | Real training? | Wall clock | When to run |
|---|---|---|---|---|---|
| **T0** — Cognitive Plumbing | label coverage, 10-key components math, `template_and_scaffolding` accounting, fail-fast wiring | ✅ | ❌ pseudo (synthetic `ModelRunSummary` fixtures) | ~30–90 s, no GPU | Cheap pre-gate. Run on every commit that touches the LLM bridge, audit hook, or label routing. Zero-cost regression filter. |
| **T1** — Telemetry Integrity | T0 surface + per-iter `[TOKEN_ITER]` rollup match across a real workflow loop | ✅ | ✅ trivially-real (`--is_trial`, `--trial_portion 0.01`, `--max_epochs 1`) | ~10–15 min, GPU | Pre-baseline mandatory. The smallest real-graph run that still exercises the iter boundary. |
| **T2** — System Stability | watchdog compliance under telemetry I/O, JSONL parseability under concurrent writes during real training, `agent_data_stream.jsonl` unit consistency | ✅ | ✅ real (still trial-mode portions) | ~10–15 min, GPU | Pre-baseline mandatory. Audits a disjoint surface from T1 — GPU-side observability rather than LLM-side telemetry. |

These gates exist because Phase 1 added telemetry that touches every LLM call site, opens a
new file handle per chain, and adds JSONL I/O inside the hot path of every node. Any of those
changes can silently break the experiment (corrupted data) or break the wall-clock (watchdog
trip). We therefore verify cognitive plumbing, signal integrity, and system stability —
in that order — *before* declaring the V11→V12 baseline ready to compare.

The gates are inserted in §8 between Commit 4 and Commit 5. The V12 baseline run (Commit 5)
must not start until **all three** gates are green. T0 may be parallelised with T1/T2; T1
and T2 audit disjoint surfaces and may also be parallelised (see §1.5.1 routing note).

**Decision branch**:
- T0 green ∧ T1 green ∧ T2 green → proceed to Commit 5 (V12 baseline + Top-3 Bloat Report).
- Any red → **STOP**. Open a remediation commit (numbered Commit 4.x) before re-attempting the failed gate.
- T0 red but T1/T2 green is structurally impossible (T1 is a strict superset of T0's surface). If observed, treat as an audit-tooling bug: T0 wasn't actually exercising what it claims.

### 1.5.0 Gate T0 — Cognitive Plumbing (Pseudo-Training Gate)

**Goal**: catch label-coverage, components-math, and `template_and_scaffolding`-accounting
regressions on the real LLM surface — without spinning up the GPU or paying for a full
workflow loop. T0 is the cheapest filter that still calls real OpenAI; if a commit breaks
the bridge's audit invariants, T0 fails in seconds rather than 10 minutes into T1.

**Setup** (agent-level pytest harness, no production runner):
- Drive `ResultInterpretationAgent.run()`, `MLModelProposalAgent.run()`, and (optionally)
  `ml_model_implementor.run()` directly per-iter with synthetic `ModelRunSummary` fixtures
  shaped for the V12 dataset structure. The fixture is the same shape used by
  `tests/integration/workflows/test_score_table_pseudo_smoke.py` — 20 files with
  hand-tuned `raw_baseline` / `ground_truth` / `model` columns covering dead-zone,
  low-headroom, and high-headroom cases.
- LLM provider: real OpenAI via `RecordingOpenAIBridge` (the thin `LLMBridge` subclass
  ported from `test_score_table_pseudo_smoke.py:196` that proxies every `generate` /
  `generate_text` call to real OpenAI and appends `(method, system_prompt, user_prompt,
  response)` to a shared call log). The bridge writes its own `token_usage.jsonl` into a
  `tmp_path`-scoped workspace exactly as in production.
- Training, scoring, VRAM probe, and hardware context: pseudo / mocked. The point is
  cognitive-layer plumbing, not GPU stress.
- Iteration count: ≥ 2 (single iter cannot exercise the chain hand-off; T1 is the place
  for full iter-rollup math, but T0 should still cover ≥ 1 inter-iter transition to catch
  state-leak between LLMBridge instances).

**Realisation file**: `tests/integration/agent/test_token_usage_pseudo_smoke.py` (landed
2026-05-04, this commit). Skipped automatically without `OPENAI_API_KEY`. Measured
wall-time: **83 s** for a 2-iter run (12 LLM calls observed: 5 interpretation + 6
proposer + 1 cached lookup), no GPU. Cost: a few cents per run on `gpt-4o-mini`.

**Success metrics** (all four must hold for T0 = green; verification scripts mirror T1):

| # | Metric | Verification |
|---|--------|-------------|
| 1 | Zero unlabeled calls | every row in the harness's `token_usage.jsonl` has `label != "unlabeled"`. Same grep as T1.1. |
| 2 | 10-key components payload accuracy | every `proposer.*` row has all 10 keys (9 content + `template_and_scaffolding`) and `chars.total - sum(components.values()) == 0` exactly. Same invariant as T1.2 post-Commit 4.2. |
| 3 | `template_and_scaffolding` non-negative | the catch-all key is `>= 0` on every proposer row (the bridge's `max(0, …)` clamp must never need to fire — if it does, the audit hook is over-counting). |
| 4 | Fail-fast wired | `pytest tests/unit/agent/llm_bridge/test_no_silent_swallow.py tests/integration/runner/test_token_log_iter_rollup.py::test_runner_aborts_on_runid_mismatch` green. Carries forward the Commit 4 contract — same evidence as T1.4. |

**Out of T0 scope** (covered by T1 / T2): per-iter `[TOKEN_ITER]` rollup math (needs
the real workflow loop); watchdog compliance (needs real training); JSONL parseability
under concurrent writes (needs real multi-agent inner loop).

**Calibration check**: the gate is only meaningful if it is sensitive to the regressions
it claims to catch. Before promoting T0 to a hard pre-baseline gate, validate by reverting
the C4.2 commit locally and re-running — metric 2 must turn red. If it stays green on
broken code, the assertions are too weak.

**Status**: **GREEN** (2026-05-04) — definition added in commit `3c9ec88`; realisation
landed in this commit; first run passed all four metrics on the first try.

**Results — first run (2026-05-04, `tmp_path`-scoped run, `gpt-4o-mini` × 2 iters)**:

13 rows in `token_usage.jsonl`: 6 proposer (3 stages × 2 iters) + 5 interpretation
(`per_model` × 3, `synthesis` × 2 — wavenet/punet hit the cache in iter 2) +
2 `_iter_flush` markers (one per agent's bridge — interp + proposer — flushed when iter
advanced 1 → 2). iter 1 elapsed 45.5 s, iter 2 elapsed 36.6 s (cache hits shaved ~9 s).

| # | Metric | Verdict | Detail |
|---|--------|---------|--------|
| 1 | Zero unlabeled calls | ✅ green | 0 / 13 rows had `label == "unlabeled"`. |
| 2 | 10-key components payload accuracy | ✅ green | All 6 proposer rows have exactly 10 keys (9 content + `template_and_scaffolding`) and `Δ = chars.total - sum(components) = +0` exactly. Per-row tns char counts: iter 1 [1039, 1395, 1519], iter 2 [3345, 3655, 3777]. |
| 3 | `template_and_scaffolding` non-negative | ✅ green | Range 1039–3777; bridge's `max(0, …)` clamp never fired. |
| 4 | Fail-fast wired | ✅ green | Carried forward from Commit 4 (c975df5) — `test_no_silent_swallow` and `test_runner_aborts_on_runid_mismatch` passed 7/7 on 2026-05-04. |

**`prior_stage_outputs` progression** — monotonically non-decreasing across the 3 stages
in *both* iters, confirming the in-iter chain works AND survives the iter boundary:
- iter 1: `[2, 2190, 4175]` chars (comparison → causal_reasoning → proposing)
- iter 2: `[2, 1798, 3683]` chars (same shape; iter 2 is smaller because cached models
  shrink the candidate-markdown surface)

Iter 1 produced `freq_specialized_wavenet`; iter 2 read iter 1's proposal via
`previous_proposal` and produced `freq_enhanced_residual_net`.

**Calibration**: deferred. The C4.2 invariant is independently confirmed by T1's 9 / 9
proposer rows on the production graph (§1.5.1 results), which gives the same evidence as
a manual C4.2 revert would. Worth wiring as a regression-guard CI step before Commit 5
lands; not blocking.

### 1.5.1 Gate T1 — Telemetry Integrity (Signal Gate)

**Goal**: confirm 100 % label coverage and audit-row accuracy under a 3-iter real-graph run.

**Setup** (decided per Q1 Option A — runner with `--is_trial` + tiny portions; pseudo-training
mode does not exist in the production runner, and a synthetic harness would certify a path
production never takes):

```bash
# Canonical chain-first invocation (Commit 4.3 — replaces run_exploration_adaptive.py).
# A 3-iter gate is a small bash loop because run_one_iteration.py runs ONE iter per call.
WS=/home/klz/Data/SIDEREIS_DATA/exploration_certify_t1_0504
RN=certify_t1_0504
SEED=/home/klz/Data/SIDEREIS_DATA/exploration_seeds_v1/run_output_punet.json
screen -S siderius-certify-t1 -d -m bash -c "
  for i in 1 2 3; do
    .venv/bin/python sdsc_submission_scripts/run_one_iteration.py \
        --workspace \$WS --run_name \$RN --start_iteration \$i \
        --seed_paths \$SEED \
        --advice tuner_advice/exploration_adaptive_v1.json \
        --llm_config llm_configs/openai_tiered_v1.json \
        --max_rounds 1 --is_trial \
        --trial_portion 0.01 --eval_portion 0.01 --max_epochs 1 \
        2>&1 | tee -a /tmp/certify_t1.log || break
  done
"
```

Workspace: `/home/klz/Data/SIDEREIS_DATA/exploration_certify_t1_0504`. The sidecar at
`{workspace}/.token_run_id` is created by iter 1 and read by iters 2/3 to preserve §1.4.1
run_id immutability across the subprocess boundary.

**Routing note (revised 2026-05-04)**: T1/T2 use the **production** `llm_configs/openai_tiered_v1.json`,
not `llm_configs/certify_minimal.json` (the gpt-4o-mini-only file from C4.1). The first T1 attempt
with the minimal config was plumbing-correct but ran into an *intelligence floor*: gpt-4o-mini's
implementor could not produce a compiling plugin, so every iter ended `no_records` and the
runner brake fired at iter 3. T2 is unreachable under that floor — it audits training-loop
telemetry, which only emits when the implementor writes runnable code. The plumbing claim
(usage objects, label routing, rollup math) is already certified by Commit 4 unit tests; the
remaining gates need real implementor output. `certify_minimal.json` is retained for fast
local plumbing smoke runs but no longer used for the formal Phase 1.5 gates.

**Floor note (Commit 4.1, 2026-05-04)**: `--trial_portion`/`--eval_portion` floor is **0.01**,
enforced at argparse-time by `_portion_floor` in both `run_exploration_adaptive.py` and
`sdsc_submission_scripts/run_one_iteration.py`. This mirrors the Pydantic `ge=0.01` on
`ProposalInput.trial_portion` and `HyperparamTuningInput.{trial,eval}_portion`. The first
T1 attempt (2026-05-04) used 0.005 and crashed inside the Proposer's Pydantic validator
after spending 16 008 interpretation tokens — the argparse floor prevents that failure
mode. Reason: with `SEGMENTS_PER_FILE=200`, 0.005 collapses to one segment per file via
the `max(1, …)` floor in `execute_tools.sample_set_builder` — physically valid but too
noisy to discriminate architectures in trial mode.

**Success metrics** (all four must hold for T1 = green):

| # | Metric | Verification |
|---|--------|-------------|
| 1 | Zero unlabeled calls | `grep -c '"label":\s*"unlabeled"' token_usage.jsonl` returns `0` |
| 2 | 10-key components payload accuracy | every `proposer.*` row has all 10 keys present and `sum(components.values()) == chars.total`. Canonical 10 keys: 9 content keys (`system_prompt`, `candidates_markdown`, `interpretation_json`, `previous_failures`, `vocab_block`, `expert_context_block`, `agent_cards_block`, `prior_stage_outputs`, `recent_gate_block`) reported by `_audit_proposer_components` + 1 catch-all key `template_and_scaffolding` injected by `LLMBridge._record_usage` (Commit 4.2) holding the user-prompt template wrapper chars (= `chars.total - sum(other 9)`). After C4.2, `Δ` per row must be `0` — no tolerance. |
| 3 | Rollup math match | every `[TOKEN_ITER]` line in `chain_log.txt` exactly equals the row-sum from `token_usage.jsonl` for that iter (no rounding tolerance) |
| 4 | Fail-fast wired | `pytest tests/integration/runner/test_token_log_iter_rollup.py::test_runner_aborts_on_runid_mismatch` passed at Commit 4 (2026-05-04, 7/7). No manual repro required (Q2 confirmed) |

**Status**: **GREEN** (2026-05-04, re-run under production `openai_tiered_v1.json`) — first attempt was RED on metric 2; Commit 4.2 closed the gap; the re-run is recorded immediately below the first-attempt history.

**Results — re-run (2026-05-04, run_id `certify_t1_0504_v3-20260505T011837-957220`, `openai_tiered_v1.json`)**:

Workspace: `/home/klz/Data/SIDEREIS_DATA/exploration_certify_t1_0504_v3`. **36 rows** in `token_usage.jsonl` across 3 iters: 9 proposer (3 stages × 3 iters) + 12 interpretation (`per_model` × 9 + `synthesis` × 3) + 6 implementor (`reasoning` + `code` × 3) + 6 tuner (`planner` + `reflector` × 3) + 3 validator. Best score 5.32 (`post_skip_transformer_causal_stack`, iter 3). Wall ≈ 15 min, finished 2026-05-04 18:58:02. Token cost: 262 552 prompt + 54 122 completion (cumulative_total = 316 674 per chain_log rollup).

| # | Metric | Verdict | Detail |
|---|--------|---------|--------|
| 1 | Zero unlabeled calls | ✅ green | 0 / 36 rows had `label == "unlabeled"`. |
| 2 | 10-key components payload accuracy | ✅ green | All 9 proposer rows have exactly 10 keys and `Δ = +0` (no tolerance). C4.2 invariant holds on the real graph as designed. |
| 3 | Rollup math match | ✅ green | All 3 `[TOKEN_ITER]` lines exactly equal per-iter row sums: iter 01 = 82 779, iter 02 = 104 500, iter 03 = 129 395, cumulative_total = 316 674. No rounding tolerance. |
| 4 | Fail-fast wired | ✅ green | Same as first attempt — Commit 4 (c975df5) test passed 7/7 on 2026-05-04. |

**Anomaly observed (cross-cutting, see §1.5.2.1)**: zero `_iter_flush` marker rows in this run despite 2 iter advancements (1→2, 2→3). The mechanism works in unit tests and in T0 (which calls `set_run_context` directly per iter); the production runner appears to take a different path. Filed for follow-up — does not affect the four T1 metrics, all of which are green.

**Results — first attempt (2026-05-04, run_id `certify_t1_0504_v2-20260504T234843-844114`, `certify_minimal.json`)**:

Workspace: `/home/klz/Data/SIDEREIS_DATA/exploration_certify_t1_0504_v2`. 72 rows in `token_usage.jsonl`, 3 iters × (3 interp + 3 proposer + 1–4 implementor). All three iters failed implementation under gpt-4o-mini and the runner brake fired (3 consecutive `no_records`); this did *not* affect the gate evaluation, which is plumbing-only.

| # | Metric | Verdict | Detail |
|---|--------|---------|--------|
| 1 | Zero unlabeled calls | ✅ green | 0 / 72 rows had `label == "unlabeled"`. |
| 2 | 9-key components payload accuracy | ❌ **RED** | Every proposer row has all 9 keys present, but `sum(components)` consistently undershoots `chars.total` by **7,524–8,335 chars** (≈ 22 % of each user prompt). Example (iter 1, attempt 0, `proposer.comparison`): `chars.system=6916`, `chars.user=27855`, `chars.total=34771`; components sum to 27,247 — gap **7,524 chars**. The undershoot is the user-prompt **template wrapper** text (section headers like `## Interpretation Summary`, key-value preludes like `Models analysed: [...]`, stage-specific instructions) injected by `_build_reasoning_prompt` / `_build_comparison_prompt` / `_build_proposing_prompt` in `nodes/ml_model_proposal_agent.py`. The 9 keys cover the *content payloads* but not the template that strings them together. |
| 3 | Rollup math match | ✅ green | All 3 `[TOKEN_ITER]` lines in `chain_log.txt` exactly equal the per-iter row sums in `token_usage.jsonl` (no rounding tolerance): iter 01 = 130 049, iter 02 = 130 195, iter 03 = 130 436, cumulative 390 680. |
| 4 | Fail-fast wired | ✅ green | Verified by Commit 4 (c975df5) test `test_runner_aborts_on_runid_mismatch` (passed 7/7 on 2026-05-04). |

**Component growth observation** (`prior_stage_outputs` across iter 1 attempt 0):
- `proposer.comparison`     →    2 chars (first stage, no prior — JSON `"{}"` literal)
- `proposer.causal_reasoning` →  2 408 chars (carries comparison output)
- `proposer.proposing`       →  4 470 chars (carries comparison + causal_reasoning)

Growth is monotonic and additive as expected. **It does *not* become the dominant component** by the proposing stage — the ranking at proposing is `candidates_markdown 13 296` ≫ `system_prompt 6 997` > `prior_stage_outputs 4 470` > `interpretation_json 1 940` > `expert_context_block 1 542`. Notable: `vocab_block` drops from 3 551 chars in comparison/causal to **0** in proposing (deliberate — by then the architecture is named).

**Remediation (Commit 4.2, 2026-05-04, Option A)**: closed the component-coverage gap by adding a 10th catch-all key `template_and_scaffolding` to every proposer row, computed in `LLMBridge._record_usage` as `max(0, chars.total - sum(other 9))`. The fix lives in the bridge rather than the audit hook because the bridge is the only point that sees both the rendered prompt total and the components dict at write time. The hook still reports 9 keys; the bridge augments them on write. After C4.2, `sum(components.values()) == chars.total` is enforced for every row by construction.

Decision rationale: Option A (catch-all) over Option B (decompose template into named sub-components). A is lossless, cheap (~5 LOC), and lets us monitor template overhead as a single bucket throughout the V12 baseline. B is more informative but invasive (~50–100 LOC across 3 builders + audit hook); deferred to a future post-baseline refinement if the bucket proves load-bearing.

**Re-run plan (2026-05-04)**: T1 and T2 will be relaunched in parallel under production `openai_tiered_v1.json`. T1 verifies the 10-key delta is zero on every proposer row across 3 iters; T2 verifies training-loop telemetry, watchdog compliance, and concurrent-write JSONL parseability under 1 iter of real training (`trial_portion=0.01, eval_portion=0.01`). Parallelisation is permitted because T2 audits a disjoint surface (training-loop telemetry, watchdog timing, JSONL concurrency) from T1 (label coverage, component math, rollup math); neither gate's verification depends on the other.

#### 1.5.1.1 T1-Sanity (Chain-Runner Re-cert, Commit 4.3)

**Goal**: prove that the Commit 4.3 instrumentation of `sdsc_submission_scripts/run_one_iteration.py`
(sidecar run_id resolver, `set_run_context` wiring via `chain_run_name`/`run_id` kwargs to
`run_workflow`, `LLMBridgeContextError → sys.exit(2)` handler, `[TOKEN_ITER]` rollup with
JSONL-seeded cumulative) produces a `token_usage.jsonl` of equivalent shape and integrity
to the adaptive-runner T1 attestation above. This is a 1-iter sanity check, not a full
3-iter T1 — the multi-iter `_iter_flush` marker behaviour was already declared an unrelated
known-issue in §1.5.2.1.

**Setup**:

```bash
WS=/home/klz/Data/SIDEREIS_DATA/exploration_certify_t1_sanity_0504
RN=certify_t1_sanity_0504
SEED=/home/klz/Data/SIDEREIS_DATA/exploration_seeds_v1/run_output_punet.json
screen -S siderius-certify-t1-sanity -d -m bash -c "
  .venv/bin/python sdsc_submission_scripts/run_one_iteration.py \
      --workspace \$WS --run_name \$RN --start_iteration 1 \
      --seed_paths \$SEED \
      --advice tuner_advice/exploration_adaptive_v1.json \
      --llm_config llm_configs/openai_tiered_v1.json \
      --max_rounds 1 --is_trial \
      --trial_portion 0.01 --eval_portion 0.01 --max_epochs 1 \
      2>&1 | tee /tmp/certify_t1_sanity.log
"
```

**Success metrics** (all three must hold for sanity = green):

| # | Metric | Verification |
|---|--------|-------------|
| 1 | `token_usage.jsonl` written | file exists at `{workspace}/token_usage.jsonl`; ≥ 4 rows; every row's `run_id` matches the contents of `{workspace}/.token_run_id` (sidecar binding round-trip) |
| 2 | 10-key Δ=0 invariant on chain runner | every `proposer.*` row has all 10 component keys and `chars.total - sum(components.values()) == 0` exactly. C4.2 invariant carried across the runner switch. |
| 3 | `[TOKEN_ITER]` rollup line emitted | exactly one `[TOKEN_ITER] iter=01 ...` line in stdout (captured to `/tmp/certify_t1_sanity.log`); its `total_tok` equals the row sum from `token_usage.jsonl` |

**Out-of-scope** for this sanity (intentionally — covered by historical T1/T2 above): cross-iter rollup math (single iter), `_iter_flush` markers (no advancement), watchdog under real training (T2 surface), formal-round behaviour.

**Status**: **GREEN** (2026-05-05).

**Results (2026-05-05, run_id `certify_t1_sanity_0504-20260505T052619-1011326`)**:

Workspace: `/home/klz/Data/SIDEREIS_DATA/exploration_certify_t1_sanity_0504`. **11 rows** in `token_usage.jsonl` — 3 proposer (`comparison`, `causal_reasoning`, `proposing`) + 4 interpretation + 1 implementor + 2 tuner + 1 validator. Wall ~1 h 35 min (training 27 min + inference 35 min + scoring 25 min). Iter 1 was real `--is_trial` punet+wavenet seeds under `openai_tiered_v1.json`.

| # | Metric | Verdict | Detail |
|---|--------|---------|--------|
| 1 | `token_usage.jsonl` written + sidecar binding | ✅ green | 11 rows; every `run_id` equals the contents of `{workspace}/.token_run_id` (`certify_t1_sanity_0504-20260505T052619-1011326`); the immutable run_id (§1.4.1) survives the would-be subprocess boundary. |
| 2 | 10-key Δ=0 invariant on chain runner | ✅ green | All 3 proposer rows have exactly the canonical 10 component keys (per `nodes/ml_model_proposal_agent.py:588-598` + `agent/llm_bridge.py:961`) and `chars.total - sum(components.values()) == 0` exactly. C4.2 invariant carries unchanged across the runner switch. |
| 3 | `[TOKEN_ITER]` rollup ≡ JSONL row sum | ✅ green | rollup `total_tok` = 82 236; JSONL `prompt + completion` sum = 82 236 (exact match). `_emit_token_iter_rollup`'s JSONL-seeded cumulative path is mathematically correct. |

**Conclusion**: Commit 4.3 instrumentation produces a `token_usage.jsonl` of identical shape and integrity to the historical adaptive-runner T1 attestation. Phase 1.5 gate ladder is complete on the chain-first path; Commit 5 (V12 baseline) is unblocked from the certification side and was launched same-day (see Revision 4 changelog).

#### 1.5.1.2 V12 Live Observation — first 13 iters of production explore (Rev 5)

**Source**: `/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v12_0504/token_usage.jsonl`, snapshot at iter 13 of 30. Run still in progress at the time of this revision.

**Per-iteration prompt-token totals (explore chain)**:

| iter | calls | prompt tokens | growth vs iter 1 | proposer | tuner | interpretation | implementor | validator |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 20 | 198,516 | 1.00× | 68 K | 102 K | 11 K | 12 K | 3 K |
| 2 | 21 | 233,412 | 1.18× | 93 K | 103 K | 20 K | 11 K | 4 K |
| 3 | 21 | 239,999 | 1.21× | 100 K | 95 K | 29 K | 10 K | 4 K |
| 4 | 24 | 313,321 | 1.58× | 119 K | 149 K | 29 K | 10 K | 3 K |
| 5 | 23 | 306,372 | 1.54× | 144 K | 103 K | 40 K | 13 K | 4 K |
| 6 | 24 | 338,940 | 1.71× | 136 K | 132 K | 50 K | 14 K | 5 K |
| 7 | 24 | 338,456 | 1.70× | 162 K | 108 K | 50 K | 11 K | 5 K |
| 8 | 27 | 425,286 | 2.14× | 215 K | 131 K | 61 K | 11 K | 4 K |
| 9 | 26 | 403,582 | 2.03× | 215 K | 108 K | 61 K | 12 K | 5 K |
| 10 | 30 | 428,523 | 2.16× | 171 K | 136 K | 73 K | 33 K | 13 K |
| 11 | 28 | 465,210 | 2.34× | 223 K | 138 K | 83 K | 13 K | 6 K |
| 12 | 27 | 425,879 | 2.14× | 207 K | 105 K | 93 K | 12 K | 7 K |
| 13 | 30 | 474,396 | **2.39×** | 225 K | 104 K | 102 K | 27 K | 13 K |

**Component-level growth (iter 1 → iter 13, prompt tokens)**:

| Component | iter 1 | iter 13 | growth | shape | verdict |
|---|---:|---:|---:|---|---|
| `interpretation` | 11 K | 102 K | **9.3×** | near-linear ↑ | bloating (primary target) |
| `proposer` | 68 K | 225 K | **3.3×** | sublinear ↑ | bloating (secondary target) |
| `validator` | 3 K | 13 K | 4.3× | flat-ish | bounded |
| `implementor` | 12 K | 27 K | 2.3× | flat-ish | bounded |
| `tuner` | 102 K | 104 K | **1.0×** | **flat** | **C4.1 instrumentation success** |

**Interpretation breakdown** — the 9.3× growth is structural, not a per-call inflation:

| iter | per_model: calls | per_model tok/call | synthesis prompt tokens |
|---:|---:|---:|---:|
| 1 | 2 | 3,636 | 4,657 |
| 5 | 5 | 4,873 | 16,588 |
| 9 | 7 | 5,291 | 24,636 |
| 13 | 11 | **5,621 (saturated)** | **40,365 (still linear)** |

- `interpretation.per_model` per-call cost has plateaued at ~5.6 K (the per-model record is bounded). The number of *calls* grows because every distinct `model_type` ever proposed gets a per-model summary. The `model_knowledge_cache` (`nodes/result_interpretation_agent.py:685-783`) is hit-on-repeat, so calls grow only when a new architecture appears (~0.7 new model_types per iter).
- `interpretation.synthesis` is one call per iter, but its prompt **concatenates every cached model summary**. There is **no N-iter window cap**. Synthesis cost grows ~3 K/iter; on the current trajectory iter 30 will be ≈ 80 K tokens for synthesis alone.

**Headline takeaways for Phase 2**:

1. The bottleneck is **interpretation, not proposer**. Original §2 design ranked proposer first; V12 calibration inverts that. See Commit 6.1 (sliding-window the synthesis prompt over `model_knowledge_cache`).
2. **Proposer is real but secondary.** 3.3× growth is driven by `prior_stage_outputs` (4 K → 14 K, ~3.5×) + `vocab_block` (3.5 K, stable). See Commit 6.2.
3. **Tuner is the success story.** Flat at ~100 K/iter — C4.1 portion-floor + components instrumentation introduced zero drift. No surgery needed.
4. The "22% Template Tax" hypothesis from Sanity-T1 (§1.5.1.1) replicates in production for `proposer.comparison` (21.0%, both chains, iter 1) but is dwarfed by the linear-growth components — Template Dehydration deferred to Commit 11.1 (low priority).
5. Exploit chain (`exploit_cnn_v12_0504`) died at iter 2 from kernel OOM-killer (see `reports/v12_20260504.md`); only 2 iters of data — insufficient to corroborate the curve. Explore alone is the calibration baseline for Commit 5.

### 1.5.2 Gate T2 — System Stability (Plumbing Gate)

**Goal**: confirm the new telemetry writes don't push the per-call architectural-probe wall
beyond the 60 s `evaluate_vram_skill` SIGALRM watchdog (commit 1972fee), and that the JSONL
remains parsable under the multi-agent concurrent writes that happen inside one full
3-trial-+-1-formal V4 iter.

**Setup** (canonical chain-first invocation, Commit 4.3):

```bash
WS=/home/klz/Data/SIDEREIS_DATA/exploration_certify_t2_0504
RN=certify_t2_0504
SEED=/home/klz/Data/SIDEREIS_DATA/exploration_seeds_v1/run_output_punet.json
screen -S siderius-certify-t2 -d -m bash -c "
  .venv/bin/python sdsc_submission_scripts/run_one_iteration.py \
      --workspace \$WS --run_name \$RN --start_iteration 1 \
      --seed_paths \$SEED \
      --advice tuner_advice/exploration_adaptive_v1.json \
      --llm_config llm_configs/openai_tiered_v1.json \
      --max_rounds 4 --is_trial \
      --trial_portion 0.01 --eval_portion 0.01 \
      --formal_portion 0.01 --formal_eval_portion 0.01 \
      --max_epochs 1 \
      2>&1 | tee /tmp/certify_t2.log
"
```

Workspace: `/home/klz/Data/SIDEREIS_DATA/exploration_certify_t2_0504`. T2 is single-iter
so no bash loop is needed; the sidecar at `{workspace}/.token_run_id` is created and
read once.

**Success metrics** (all three must hold for T2 = green):

| # | Metric | Verification |
|---|--------|-------------|
| 1 | Watchdog compliance | no SIGALRM firing in `chain_log.txt` (0 hits via `grep -c 'evaluate_vram_skill timed out' chain_log.txt`); no `[WATCHDOG]` markers either |
| 2 | JSONL parseability | every line of `token_usage.jsonl` parses with `json.loads` (no partial writes / interleaved bytes from concurrent writers) |
| 3 | No regression in scoring/training | `run_output_iter_001.json` exists, contains a numeric `denoising_score` for at least the formal round, and round-trips through its Pydantic schema |

**Status**: **GREEN** (2026-05-04) — launched in parallel with the T1 re-run under production `openai_tiered_v1.json`.

**Results (2026-05-04, run_id `certify_t2_0504_v1-20260505T011837-957225`)**:

Workspace: `/home/klz/Data/SIDEREIS_DATA/exploration_certify_t2_0504_v1`. **23 rows** in `token_usage.jsonl` across 2 iters (the run was upgraded from the original 1-iter spec to 2 iters to also exercise the chain hand-off): 6 proposer + 7 interpretation (`per_model` × 5 + `synthesis` × 2) + 4 implementor + 4 tuner + 2 validator. Best score -3.23 (`skip_context_wavemixer`, iter 2). Wall ≈ 18 min, finished 2026-05-04 18:45:53. Token cost: 156 502 prompt + 35 277 completion (cumulative_total = 191 779 per chain_log rollup).

| # | Metric | Verdict | Detail |
|---|--------|---------|--------|
| 1 | Watchdog compliance | ✅ green | 0 hits of `evaluate_vram_skill timed out` in `chain_log.txt`; no `[WATCHDOG]` markers. |
| 2 | JSONL parseability | ✅ green | All 23 lines parse with `json.loads`; no partial writes / interleaved bytes. |
| 3 | No regression in scoring/training | ✅ green | `run_output_iter_NNN.json` files exist for both iters and round-trip through their Pydantic schema; numeric `denoising_score` present (iter 1 baseline + iter 2 baseline). |

**Bonus checks** (re-using T1 metrics on the T2 log for free): 0 unlabeled rows; all 6 proposer rows show exactly 10 components keys and `Δ = +0`; rollup math matches `[TOKEN_ITER]` lines (iter 01 = 82 853, iter 02 = 108 926, cumulative_total = 191 779). The C4.2 invariant therefore holds on **21 / 21 proposer rows across all three gates**.

#### 1.5.2.1 Cross-gate follow-up — `_iter_flush` markers absent in production runs

**Observation (2026-05-04)**: T0 emitted 2 `_iter_flush` rows (one per agent's bridge — interp + proposer — flushed at the iter 1→2 boundary). T1 (3 iters, 2 boundaries) and T2 (2 iters, 1 boundary) emitted **0** flush rows each. Unit tests in `tests/unit/agent/llm_bridge/test_setter_safety.py` pin the mechanism (the `set_run_context(iter=N+1)` path calls `_flush_iter_marker_locked`) and they pass. T0's harness hits that path because the test calls `set_run_context` directly per iter; the production `run_exploration_adaptive.py` path apparently does not.

**Hypothesis** (unverified): the chain-first runner used for T1/T2 either (a) instantiates fresh `LLMBridge` instances per iter so there is no living bridge to advance, or (b) writes the new iter's rows under a freshly-bound bridge whose `self._iter` was `None` (no advancement, no flush). Either way the per-iter rollup math (§1.5.1 metric 3, §1.5.2 bonus check) is unaffected because rollup keys on the row's own `iter` field, not on flush boundaries.

**Severity**: not a Phase 1.5 blocker. The flush markers are a *defense-in-depth* mechanism that lets the linter (`tools/validate_token_usage_jsonl.py`) detect a row appearing under the wrong iter; their absence weakens that check but does not corrupt any row. C4.2 invariants hold; rollup math matches; gates T0/T1/T2 are all green.

**Follow-up audit ticket** (deferred to a post-Commit 5 cleanup pass): trace the chain-first runner's bridge wiring to confirm the hypothesis, and either (a) wire `set_run_context` per iter on the chain bridge so flushes fire as designed, or (b) revise §1.4.1 to remove the marker mechanism entirely if a fresh-bridge-per-iter pattern is preferred. Decision can wait until after the V12 baseline; the four T1 metrics and the three T2 metrics are green either way.

### 1.5.3 Graceful Degradation note

If a network drop causes `response.usage` to be missing or unparseable, the bridge logs the
row with `tokens.{prompt,completion,total}` set to `None` and continues — the character-count
audit still works, the experiment proceeds, only the per-row token counter is degraded for
that single call. This is preferable to aborting a long run on a transient network blip.
**Hardening status**: deferred to Phase 2 unless T1 or T2 surfaces an actual missing-usage
row in the wild.

---

## 2. Phase 2 — Context Dehydration Surgery ("the Blade")

**Conditional**: applies only if §1.9 verdict is "Confirmed Proposer Hypothesis." Pivot verdicts trigger a fresh design.

Phase 2 lands **only after** Phase 1 telemetry is in production for at least one full chain run, so we have a baseline against which to measure the dehydration effect.

### 2.1 Goals

| # | Outcome | Verifies |
|---|---------|----------|
| 2.1 | Failures forwarded to the next iter are **dehydrated** to ~300 char "Error Signatures" rather than full traceback / log strings. | Failure-block size is bounded per iter. |
| 2.2 | `interpretation['per_model_score_tables']` is truncated to top-N (default N=5) before serialization into the proposer's JSON region. | JSON region size flattens after iter 5. |
| 2.3 | Only the immediate predecessor (iter N-1) carries full source + full causal_hypothesis; older attempts carry a 1-line "idea + failure_reason" summary. | Per-iter prompt size is no longer O(num_models). |
| 2.4 | The proposer's system prompt requires a `delta_reasoning` field that **explicitly compares the new proposal to N-1**, not to the full history. | Forces signal extraction; gives us a structured audit trail. |
| 2.5 | The "Evolutionary Ledger" is a single, schema-validated object the proposer reads — not a free-form accumulation of fields. | One source of truth for what flows iter-to-iter. |

### 2.2 Log Dehydration — Error Signature Skill

**New file**: `agent/skills/error_signature_skill.py`.

**Contract**:

```python
@dataclass
class ErrorSignature:
    error_type: str          # e.g. "torch.cuda.OutOfMemoryError"
    short_message: str       # ≤ 120 chars, the bare error message
    last_frames: list[str]   # last 3-5 traceback lines that name *user* code
    failure_class: str       # one of: "vram", "training", "validation", "shape", "scoring", "unknown"

def extract(traceback_text: str, *, max_frames: int = 5) -> ErrorSignature: ...
def render(sig: ErrorSignature) -> str:
    """Return a 4-line markdown block: kind + message + last frames."""
```

**Where it's invoked**:

1. `workflows/model_exploration.py` `_render_physical_rejection` — dehydrate the existing rejection block to 4 lines instead of the current ~350 chars per entry.
2. `nodes/ml_code_validator_agent.py` — when emitting validator `error_message`, store both the full text (for `validator_iter_NNN.json` on disk) and an `ErrorSignature` (for in-memory propagation).
3. The implementor's `previous_failures` list is built from `ErrorSignature.render(...)`, not from raw traceback strings.

**Caveat**: do not lose information. The full traceback is still written to disk per call (e.g. `validator_iter_NNN.json`); only the **propagated** version is dehydrated.

### 2.3 JSON Truncation — `per_model_score_tables`

**Current**: `ml_model_proposal_agent.py:929-934` includes the full `per_model_score_tables` dict in `accumulated["interpretation_summary"]`. `_render_stage_user_prompt` (line 475-478) strips the markdown-rendered version but keeps the dict intact in JSON. At iter 30 this is ~30 KB.

**Change**: introduce `truncate_score_tables(tables: Dict[str, ScoreComparisonTable], top_n: int) -> Dict[...]` in `nodes/proposal_helpers.py`. It:

1. Sorts by `best_score` (or whichever metric the existing top-N selector uses, to stay consistent with `select_candidate_models`).
2. Returns only the top-N entries.
3. For dropped models, emits a single companion field: `"score_tables_omitted": ["modelA", "modelB", ...]` so the proposer knows the universe is larger than what's in context.

Call site: just before populating `accumulated["interpretation_summary"]["per_model_score_tables"]`.

`top_n` is configurable via the proposer's `pipeline.model_selection` config — default 5 to match the existing markdown selector.

### 2.4 Sliding Window for Source Code

**Current**: every candidate emitted by `select_candidate_models` carries `source_code` and `score_table` markdown into `build_candidate_markdown_block`. There is no distinction between "the model we just trained (N-1)" and "models we tried 10 iters ago".

**Change**: introduce a window policy in `nodes/proposal_helpers.py`:

```python
def apply_source_window(candidates: list[dict], *,
                        full_source_for: int = 1,   # iters back
                        summary_for_older: bool = True) -> list[dict]:
    """For each candidate, decide whether to include source_code / score_table_full
    or a 1-line summary stub."""
```

Each candidate dict carries an `iter_offset` (0 = current, 1 = N-1, ≥ 2 = older). For `iter_offset >= 2`:

- `source_code` removed.
- `score_table` replaced with one line: `"<model_type>: best_score=<val>, failure_reason=<dehydrated>"`.

**Schema impact**: `ProposalInput.interpretation` already carries enough metadata to compute `iter_offset` (per_model_score_tables has `iter_introduced` or similar; if not, we add it via the interpretation agent — see §3 for the schema change list).

### 2.5 Delta Reasoning Requirement — Prompt Templates

**Affected files**:

- `agent/prompt_templates/proposal/causal_reasoning_stage.md`
- `agent/prompt_templates/proposal/proposing_stage.md`
- `_explore` and `_exploit` mode variants of each (currently 6 files total).

**Change**: add a required output field to the proposer's structured response (`agent/schemas/proposal.py` `ProposalOutput`):

```python
delta_reasoning: DeltaReasoning = Field(
    description="Required comparison between this proposal and the immediately "
                "preceding attempt (N-1). Forces explicit signal extraction "
                "rather than free-form 'add another idea on top'."
)

class DeltaReasoning(BaseModel):
    predecessor_model_type: str
    what_we_keep: list[str]    # bounded ≤ 3 entries
    what_we_change: list[str]  # bounded ≤ 3 entries
    why_change_addresses_predecessor_failure: str  # ≤ 400 chars
```

Prompt-template addition (in causal_reasoning):

> **Required: Delta Reasoning.** Before proposing, name the immediate predecessor (iter N-1) and answer in ≤3 bullets each: (a) what specific component of N-1 do you keep? (b) what specific component do you change? (c) why does the change address N-1's documented failure (cite the Error Signature)?

A field validator on `DeltaReasoning` enforces the bounded list lengths.

### 2.6 The Evolutionary Ledger — schema

**New schema**: `agent/schemas/proposal.py` adds:

```python
class EvolutionaryLedger(BaseModel):
    """Bounded, dehydrated cross-iter context. Replaces ad-hoc accumulation
    of previous_failures + interpretation['per_model_score_tables'] +
    expert_context['accumulated_key_findings']."""

    predecessor: PredecessorEntry  # full source + full causal_hypothesis + full ErrorSignature
    older_attempts: list[OlderAttemptSummary]  # bounded ≤ K (default 8); 1-line each
    confirmed_lessons: list[str]  # promoted lessons from interpretation; ≤ 6 entries
    open_bottlenecks: list[str]   # current-iter unresolved bottlenecks; ≤ 4 entries

class PredecessorEntry(BaseModel):
    iter:           int
    model_type:     str
    causal_hypothesis: str       # ≤ 600 chars
    source_code:    str          # full
    score_summary:  str          # 1 line
    error_signature: Optional[ErrorSignature]  # None on success

class OlderAttemptSummary(BaseModel):
    iter:           int
    model_type:     str
    one_line_idea:  str          # ≤ 140 chars
    failure_reason: str          # ≤ 140 chars
```

`ProposalInput` gets a single new field `ledger: EvolutionaryLedger` and the workflow protocol populates it via `restore_prior_state(...)`. The legacy fields (`previous_failures`, `interpretation`, `expert_context`'s accumulated_key_findings, etc.) **stay** for one release as a fallback path; the proposer reads the ledger first, falls back to the legacy fields only if `ledger is None` — a feature flag (`use_evolutionary_ledger=True` default) lets us A/B for one chain run.

After validation, the legacy fields are deleted.

### 2.7 What gets removed (after validation)

| File | Removal |
|------|---------|
| `nodes/ml_model_proposal_agent.py` | The flat `previous_failures` rendering at line 644-648 (replaced by `ledger.predecessor.error_signature` + `ledger.older_attempts[*].failure_reason`). |
| `nodes/ml_model_proposal_agent.py` | `interpretation_summary["per_model_score_tables"]` (line 934) — replaced by ledger. |
| `agent/schemas/proposal.py` | `previous_failures: List[str]` field (line 642) and `recent_gate_exhaustions` field if its info is fully covered by `ledger.confirmed_lessons` + dehydrated signatures (TBD by Phase 1 measurement — keep if telemetry shows it's still load-bearing). |
| Workflow assembly | The `accumulated_physical_rejections` and `accumulated_key_findings` synthesis paths in `workflows/model_exploration.py` (lines 916-954) — replaced by ledger construction. |

### 2.8 Offline Forensic Benchmark — pre-flight test before any code lands

Phase 2 is a destructive refactor (we are throwing away ~90% of the raw failure text). Before we trust the new `ErrorSignatureSkill` to compress live runs, we must prove it captures the actual root cause from a known-failure log. The V11 `spectral_u_operator_lite` run is the perfect benchmark — it failed in a specific, traceable way and the full forensic trail is on disk.

#### 2.8.1 Benchmark target

**Forensic source**: `/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v11_0503/iter_002/iteration_002/spectral_u_operator_lite/`

Available artefacts:

- `run_output_iter_002.json` — full tuner run output including per-attempt error strings.
- `run_config_iter_002.json` — the config that was running.
- `cached_models/` — surviving artefacts from the failed attempts.
- `records/` — per-attempt records with timing and error fields.
- `iter_002_hardware.json` — the hardware context at the time of failure.

The cross-iter trail (workflow chain log + memory traces) lives in the workspace root.

#### 2.8.2 The test

A new test file `tests/forensic/test_v11_spectral_u_signature.py` (a new `tests/forensic/` directory — these are pre-flight verifications, not unit/integration):

```python
def test_spectral_u_failure_signature_captures_root_cause():
    raw_log = _load_v11_spectral_u_failure_text()  # reads run_output + chain_log
    sig = error_signature_skill.extract(raw_log)

    # 1. Failure class must be correctly inferred
    assert sig.failure_class == "vram"

    # 2. The error type must name the actual exception class
    assert "OutOfMemoryError" in sig.error_type or "MemoryError" in sig.error_type

    # 3. Last frames must mention the offending architectural component
    frames_text = "\n".join(sig.last_frames).lower()
    assert "fft" in frames_text or "spectral" in frames_text, \
        "Signature lost the FFT layer — compressor is failing"
    assert "u_net" in frames_text or "decoder" in frames_text or "encoder" in frames_text, \
        "Signature lost the U-Net layer — compressor is failing"

    # 4. The rendered short_message must mention VRAM, not just "error"
    assert any(tok in sig.short_message.lower() for tok in ("vram", "cuda", "memory")), \
        f"Signature short_message is generic ({sig.short_message!r}) — compressor is failing"

    # 5. The fully rendered signature must be < 600 chars (target: ~300)
    rendered = error_signature_skill.render(sig)
    assert len(rendered) < 600, f"Signature too long: {len(rendered)} chars"

    # 6. Compression ratio gate (also enforced as §4 metric Cr)
    cr = len(rendered) / len(raw_log)
    assert cr < 0.10, f"Compression ratio {cr:.3f} ≥ 0.10 — too verbose"
```

**Pass criteria**:

- All 6 assertions hold.
- The signature is independently human-reviewable: a reviewer reads the rendered output and answers "yes, this is what failed and why" without consulting the raw log.

**Fail criteria**:

- Any assertion fails — the compressor is not extracting the load-bearing tokens. **Phase 2 code does not land** until the skill is improved and the test passes.
- Specifically: if the rendered signature says `"Unknown Error"` or only mentions "training failed" without naming the layer, the skill has thrown away the cause and is unsafe to deploy.

#### 2.8.3 Why this benchmark before live deployment

A live chain run cannot be the first place we discover the compressor is dropping the FFT-layer signal — by then the proposer has seen 30 iterations of vague "Unknown Error" feedback and the run is wasted. The offline benchmark gives a deterministic pass/fail on real failure data before we trust the skill in production.

The test stays in the suite (gated behind a `@pytest.mark.forensic` marker) as a regression guard — any future change to `ErrorSignatureSkill` must keep passing this test.

### 2.9 The Trap Test — long-term wisdom retention

The Sliding Window (§2.4) shrinks attempts older than N-1 to a 1-line summary. The risk: a fatal architectural lesson learned at iter 2 is forgotten by iter 10. The Trap Test makes this risk measurable.

#### 2.9.1 The setup

A pseudo-mode integration test `tests/integration/proposer/test_long_term_wisdom_trap.py`:

1. **Iter 1**: ledger is empty. Proposer proposes any model.
2. **Iter 2**: a synthetic predecessor is injected with a clearly-fatal flaw — the test plants:
   - `model_type = "deep_recurrent_no_residual_v1"`
   - `error_signature.short_message = "vanishing gradient: all params got grad_norm < 1e-9 by epoch 3 because the 32-layer LSTM has no residual connections"`
   - `error_signature.failure_class = "training"`
   - `older_attempts[*].failure_reason = "no residual connections in deep recurrent stack → vanishing gradient"`
3. **Iters 3–9**: the test feeds a sequence of unrelated successful proposals so the trap entry ages out of the immediate predecessor slot and into `older_attempts`.
4. **Iter 10**: the predecessor (N-1) is a *successful* unrelated model; the trap entry is now in `older_attempts[7]` (8 iters old). The proposer is given a real LLM call with a prompt that biases towards trying a deep recurrent stack again (e.g., "the user wants a temporal-causal architecture with maximum depth").

#### 2.9.2 The assertion

The proposer's `delta_reasoning` or causal_hypothesis output must explicitly cite the iter-2 trap:

```python
def test_proposer_cites_iter2_trap_when_deciding_iter10():
    output = run_proposer_with_trap_at_iter2(target_iter=10, biased_prompt=DEEP_RECURRENT_BIAS)

    full_reasoning = (
        output.delta_reasoning.why_change_addresses_predecessor_failure +
        " " + output.causal_hypothesis
    ).lower()

    # Must reference the specific lesson from iter 2
    assert "vanishing gradient" in full_reasoning or "residual" in full_reasoning, \
        f"Proposer at iter 10 did not cite the iter-2 trap. Reasoning: {full_reasoning!r}"

    # Must not propose the trap architecture
    assert "no residual" not in output.proposal.architecture_summary.lower(), \
        "Proposer fell into the trap — it proposed the very architecture that failed at iter 2"
```

#### 2.9.3 Pass / fail

- **Pass**: proposer cites the iter-2 lesson AND avoids the failing architecture. The Sliding Window retained signal at distance 8.
- **Fail (proposer falls into the trap)**: dehydration is too aggressive. Increase `older_attempts` depth, or promote chronic lessons into `confirmed_lessons` more aggressively.
- **Fail (proposer cites the lesson but proposes the architecture anyway)**: this is a prompt issue, not a context issue. Sharpen the Delta Reasoning prompt.

The test runs in real-API mode (gated behind `@real_run`) because the wisdom-retention question is fundamentally about LLM behaviour, not code paths. A pseudo-mode version (with a fixed mock response) verifies only the *plumbing* — that the iter-2 lesson is *present* in the rendered prompt — and is a unit test:

```python
def test_iter2_lesson_present_in_iter10_prompt():
    rendered_prompt = build_proposer_prompt_with_trap_at_iter2(target_iter=10)
    assert "vanishing gradient" in rendered_prompt
    assert "deep_recurrent_no_residual_v1" in rendered_prompt
```

The unit test is a strict prerequisite — if the lesson is not in the prompt, the LLM cannot possibly cite it, and the real-API test is meaningless.

#### 2.9.4 Tuning knobs

If the test fails for reasons (1) or (2), we have explicit knobs to tune:

| Knob | Default | Effect |
|------|---------|--------|
| `older_attempts_K` | 8 | Number of older summaries kept. Larger = better retention, more tokens. |
| `confirmed_lessons_min_iters` | 1 | If a lesson appears in N+ attempts, promote to `confirmed_lessons`. Lower = more aggressive lesson retention. |
| `error_signature.last_frames_count` | 5 | More frames = more context per failure, larger ledger. |

The Trap Test is the empirical scoreboard for setting these knobs.

### 2.10 The SOTA Replication Test — retained creative capability (Gate G3.5)

The Trap Test (§2.9) protects the agent's **memory** — known bads stay known. The Hybrid DRR (§4.2 #8a–8c) protects its **integrity** — claims match code. Neither asks the harder question: *can the dehydrated agent still navigate to the high-signal architectures the V12-rich-context agent discovered?* Without a guard for **retained creative capability**, every existing intelligence metric is *defensive*; we have no aspirational metric proving the consolidator preserved the peak of our collective wisdom.

Gate G3.5 closes that gap. It is a Phase 2 exit gate, run *after* G3 (Trap) and *before* G4 (full V13 metrics).

#### 2.10.1 Setup — Pick the "Golden Iteration"

From the V12 explore baseline (`/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v12_0504/`), select the iteration that produced the highest `denoising_score` — the **Golden Iteration**. For breadth, also identify the **top 3 V12 architectures by `denoising_score`**; G3.5 is run independently on each, and the SRR metric (§4.2 #12) requires ≥ 2 of 3 to pass.

The selection is deterministic and automated by `tools/verify_sota_replication.py` (Commit 11.2): it parses `run_output_*.json` + per-iter records, ranks by formal `denoising_score`, and emits the Golden Iteration set as a JSON manifest committed to the test fixture path.

#### 2.10.2 State reconstruction

For each Golden Iteration, extract the upstream state **as it existed at the start of that iteration** (i.e., the inputs the proposer would have seen):

- `model_knowledge_cache` — the full accumulated cache *just before* the Golden Iteration's proposer call.
- `model_descriptions` — same temporal cut.
- Prior iter records (interpretation outputs, validator outputs, training results) — needed to drive the consolidator's Merge & Prune logic.

This reconstruction must match what was actually fed to the V12 proposer at that iter — verified by replaying the V12 record's input hash, not by trusting the live workspace state.

#### 2.10.3 Dehydrated re-run

Process the reconstructed state through the **Commit 6.3 consolidator**, producing the new dehydrated cache. Build the proposer's input from that cache (using the post-6.3 protocols). Issue **a real LLM call** (gated `@real_run`, same model + temperature as the V12 baseline call) to generate a new proposal.

The proposer is given the same task framing as V12 — no biased prompt, no nudge toward the V12 architecture. The point is to verify that the dehydrated context still *naturally* leads the proposer to a competitive solution, not that the test rigs the answer.

#### 2.10.4 Success metrics

Two axes, both must pass per Golden Iteration:

| Axis | Metric | Target | Computation |
|------|--------|--------|-------------|
| **Structural Fidelity** | AST overlap on core architectural primitives (encoder family, decoder family, key innovations — e.g., FFT layer, attention block, residual structure) | **≥ 0.7** | Plugin AST parse on both proposals; compute Jaccard on a curated set of "primitive" node-types. Deterministic. |
| **Reasoning Density** | LLM judge (gpt-4o-mini, temp=0) compares new `delta_reasoning` + `causal_hypothesis` against the V12 originals. Returns: "the new reasoning is at least as targeted, specific, and historically informed as the original — yes/no." | **≥ 75 %** of judges' verdicts return "yes" across all sampled claims | Same judge model used for DRR_LLM (§4.2 #8b) for cost control. Multiple-judgment averaging reduces variance. |

Pass criterion per iteration: `Structural ≥ 0.7 AND Reasoning Density ≥ 75 %`.

#### 2.10.5 Failure trigger

If the new proposal scores below either threshold, the consolidator's Merge & Prune is **lopping off the peak** of our collective wisdom — high-signal architectural insights that drove V12 SOTA are being collapsed into generic summaries. Do not ship Phase 2.

Diagnostic next steps when G3.5 fails:

1. Inspect which V12 cache entries were dropped or merged before reaching the proposer in the dehydrated run.
2. If a load-bearing `key_findings` entry was merged into a generic bucket → tighten the consolidator's similarity threshold (raise the merge bar).
3. If the active-set policy excluded the Golden Iteration's parent architecture → expand the active-set inclusion rule (e.g., "always retain top-K by historical `denoising_score`").
4. If the failure persists after both knob adjustments, the cache schema itself is too lossy — escalate back to Commit 6.3 design.

#### 2.10.6 Tuning knobs

| Knob | Default | Effect |
|------|---------|--------|
| `consolidator.merge_similarity_threshold` | 0.85 | Raise to merge less aggressively (preserves more peaks; larger cache). |
| `consolidator.active_set_top_k` | 5 | Lowest-cost protection for Golden Iteration parent architectures: always keep the top-K by historical `denoising_score`. |
| `srr.judge_n_samples` | 3 | More LLM-judge samples per claim = lower variance, higher cost. |
| `srr.required_pass_count` | 2 (of 3 top architectures) | Tighter bar = stricter Phase 2 exit; SRR is the aggregate (§4.2 #12). |

These knobs are tuned *before* G3.5 is declared a hard gate; the first SRR run produces a calibration distribution that informs the production thresholds.

#### 2.10.7 Why this gate is aspirational, not defensive

FRR (§4.2 #7) measures "did the agent re-try a known failure?" — defensive.
DRR (§4.2 #8) measures "did the agent's claims match its code?" — defensive.
Cr (§4.2 #10) measures "is the compressor compressing?" — defensive.
**SRR (§4.2 #12) measures "can the agent still find what it found before?" — aspirational.**

Without SRR, every existing intelligence metric could pass while the agent quietly produces mediocre-but-honest proposals. The dehydration goal is to keep the agent small *and* honest *and* a world-class architect; G3.5 is the only gate that pins the third property.

---

## 3. Files Touched — Full List

| Path | Phase | Change |
|------|-------|--------|
| `agent/llm_bridge.py` | 1 | Capture `response.usage`; new `_record_usage` helper; `set_run_context` setter; thread `label` arg into `generate`/`generate_text`/`tool_call`/`reflect`. |
| `agent/schemas/telemetry/token_usage.py` | 1 | **New file**. Pydantic schema for `token_usage.jsonl` row. |
| `agent/schemas/telemetry/__init__.py` | 1 | **New file**. Package init. |
| `nodes/ml_model_proposal_agent.py` | 1 + 2 | Pre-assembly hook (`_audit_proposer_components`, Phase 1); ledger consumption + delta_reasoning rendering (Phase 2); remove flat `previous_failures` path (Phase 2 cleanup). |
| `nodes/result_interpretation_agent.py` | 1 + 2 | Add `iter_introduced` to per_model_score_tables (Phase 2 prerequisite); add labels to LLM calls (Phase 1). |
| `nodes/ml_hyperparameter_tune_agent.py` | 1 | Add labels to planner / reflector calls. |
| `nodes/ml_code_validator_agent.py` | 1 + 2 | Add labels (Phase 1); emit `ErrorSignature` alongside full error_message (Phase 2). |
| `nodes/proposal_helpers.py` | 2 | Add `truncate_score_tables`, `apply_source_window`. |
| `agent/skills/error_signature_skill.py` | 2 | **New file**. `extract` + `render` + `ErrorSignature` dataclass. |
| `agent/schemas/proposal.py` | 2 | Add `EvolutionaryLedger`, `PredecessorEntry`, `OlderAttemptSummary`, `DeltaReasoning`. Add `ProposalInput.ledger` field. Add `ProposalOutput.delta_reasoning` field. |
| `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` | 2 | Build `ledger` from `recent_tune_outputs` + interpretation; populate the new field. |
| `workflows/model_exploration.py` | 2 | Replace `accumulated_physical_rejections` + flat failure assembly with ledger construction. Setter call to `bridge.set_run_context` per iter (Phase 1). |
| `core/resume.py` | 2 | Build older-attempts summary list from disk-resident interpretations (replaces `accumulated_key_findings` flat list). |
| `agent/prompt_templates/proposal/causal_reasoning_stage*.md` (×3) | 2 | Add Delta Reasoning required block. |
| `agent/prompt_templates/proposal/proposing_stage*.md` (×3) | 2 | Reference `delta_reasoning` field in output schema. |
| `run_exploration_adaptive.py` | 1 | Per-iter `[TOKEN_ITER]` rollup line emit. |
| `tests/unit/agent/llm_bridge/test_record_usage.py` | 1 | **New**. |
| `tests/unit/agent/proposal/test_audit_components.py` | 1 | **New**. |
| `tests/unit/agent/skills/test_error_signature.py` | 2 | **New**. |
| `tests/unit/agent/proposal/test_evolutionary_ledger.py` | 2 | **New**. |
| `tests/unit/agent/proposal/test_truncate_score_tables.py` | 2 | **New**. |
| `tests/unit/agent/proposal/test_source_window.py` | 2 | **New**. |
| `tests/unit/runner/test_token_log_iter_rollup.py` | 1 | **New**. |

---

## 4. Success Metrics

Measurable at iter end via `token_usage.jsonl` aggregation (Phase 1 must be live first).

The metrics split into two families:

- **Cost metrics** — does the prompt actually shrink? (rows 1–6, 9 below)
- **Intelligence metrics** — does the agent stay smart after we shrink the prompt? (rows 7–8, 10–11 below)

A refactor that improves cost while regressing intelligence is a failure. The intelligence metrics are non-negotiable.

### 4.1 Cost & coverage metrics

| # | Metric | Phase | Target | Failure threshold |
|---|--------|-------|--------|-------------------|
| 1 | **Telemetry coverage** | 1 | 100% of LLM calls produce one row in `token_usage.jsonl`. | Any call missing — Phase 1 has not landed. |
| 2 | **Round 4 vs Round 1 size** | 2 | `prompt_tokens(iter=4) ≤ 1.20 × prompt_tokens(iter=1)` for the proposer's `proposing` stage. | > 1.5× — Phase 2 has not solved the growth problem. |
| 3 | **Iter 30 cap** | 2 | `prompt_tokens(iter=30) ≤ 1.50 × prompt_tokens(iter=1)`. | > 2.5× — ledger is leaking. |
| 4 | **JSON region size** | 2 | `chars.components.interpretation_json` is bounded ≤ 8 KB regardless of iter. | unbounded growth — `truncate_score_tables` not effective. |
| 5 | **Failure block size** | 2 | `chars.components.previous_failures` ≤ 1.5 KB per iter (~5 entries × 300 char Error Signatures). | > 4 KB — dehydration regressed. |
| 6 | **Boilerplate share** | 2 | static + repeated content (vocab, hardware, system prompt) ≤ 25% of proposer prompt at iter 4 (down from ~41% per §12.4). | > 35% — boilerplate de-dup didn't land. |
| 9 | **Total run cost** | 2 | A 30-iter chain run total token spend ≤ 60% of a matched V11 baseline. | > 90% — refactor did not pay off; revisit. |

### 4.2 Intelligence-preservation metrics (the "leaner ≠ stupider" gates)

These are the metrics that prove Phase 2 didn't lobotomize the agent. They are mandatory pass-criteria; the refactor does not ship if any of these regress.

| # | Metric | Phase | Definition | Target | Failure threshold |
|---|--------|-------|------------|--------|-------------------|
| 7 | **Failure Re-occurrence Rate (FRR)** | 2 | Count of iters where the proposer either (a) re-proposes an architecture name that already appears in `older_attempts` with a non-null `error_signature`, or (b) emits a model whose `error_signature` after training matches a prior iter's error_signature by `(failure_class, error_type)`. Computed as `FRR = n_repeated / n_total_iters`. | **0.00** in any 30-iter window. | **> 0.00** — dehydration is hiding load-bearing context. The proposer is forgetting documented failures and re-trying them. Block ship; tune §2.9 retention knobs. |
| 8a | **DRR_Structural** (AST/regex) | 2 | Sample 10 iters at random from a 30-iter run. For each `delta_reasoning.what_we_change` claim, attempt to find a corresponding AST node delta or regex match in the source-code diff (predecessor → current iter). A claim is *structurally realized* if either (a) an AST node added/removed/modified at the named location matches the claim's referent, or (b) a regex derived from the claim's keywords matches a non-empty diff hunk. Computed deterministically — no LLM in the loop. | **≥ 0.85** | **< 0.70** — the proposer's claimed changes are not detectable in the source. The Delta Reasoning is structurally hallucinated. Sharpen the §2.5 prompt schema or block ship. |
| 8b | **DRR_LLM** (semantic) | 2 | Same 10-iter sample. Cheap LLM judge (deterministic temperature=0) reads each `what_we_change` claim alongside the predecessor and current source; returns `realized=True/False` per claim. Reports `DRR_LLM = n_realized / n_declared`. | **≥ 0.90** | **< 0.75** — the change is not present semantically (the structural match was a coincidence, or the change is renamed/refactored away). |
| 8c | **DRR Gap** (hallucination indicator) | 2 | `gap = abs(DRR_LLM − DRR_Structural)`. A small gap means the two methods agree and the result is trustworthy. A large gap means one method is being fooled — usually it's the LLM judge being too generous (claim "I added attention" matches semantically against any attention-shaped code, even pre-existing). | **≤ 0.15** | **> 0.25** — the two graders disagree materially. Either the structural matcher is too strict or the LLM judge is too lenient. Re-tune the methods before trusting either number. |
| 10 | **Dehydration Compression Ratio (Cr)** | 2 | Per failed attempt: `Cr = len(rendered_signature) / len(raw_traceback_or_log)`. Computed across all failures in a 30-iter chain run; reported as `(median, p95)`. | **median Cr < 0.10**, **p95 Cr < 0.15**. | **median Cr ≥ 0.15** — compressor is not compressing. **p95 Cr ≥ 0.30** — pathological cases (long tracebacks) are slipping through, which is exactly when compression matters most. |
| 11 | **delta_reasoning presence** | 2 | 100% of `ProposalOutput` payloads carry a non-null, schema-valid `delta_reasoning` (bounded list lengths, all required subfields). | 100% | < 100% — schema validation should make this impossible; any missing payload is a regression. |
| 12 | **SOTA Retention Rate (SRR)** | 2 | Aggregate of the §2.10 SOTA Replication Test (Gate G3.5) across the **top 3 V12 architectures by `denoising_score`**. Per architecture: pass = `Structural Fidelity ≥ 0.7 AND Reasoning Density ≥ 75 %`. SRR = number of passing architectures. **Aspirational guard** — verifies the dehydrated agent still navigates to the high-signal architectures the V12-rich-context agent discovered. | **≥ 2 of 3** | **< 2 of 3** — the consolidator is lopping off the peak of collective wisdom. **Blocks Phase 2 exit.** Tighten consolidator knobs (§2.10.6) or revisit Commit 6.3 design before retesting. |

#### 4.2.1 How the intelligence metrics are computed

- **FRR computation** is automated: `tools/compute_frr.py` reads `token_usage.jsonl` + per-iter ledger artefacts + per-iter validator outputs, joins on `error_signature`, and emits a CSV. Runs as a CI step on the V13 chain output before Phase 2 ships.
- **DRR_Structural computation** is fully automated: `tools/compute_drr.py` parses each claim, derives an AST query (when the claim is structural — "add residual connection", "change kernel size", "replace LSTM with GRU") or a regex (when the claim is non-structural — "increase dropout to 0.3"), and matches against the source-code diff between predecessor and current iter. Output: per-claim realized/not + the AST/regex evidence string for human spot-check.
- **DRR_LLM computation** is semi-automated: same script invokes a cheap LLM judge (gpt-4o-mini, temperature=0) with the claim + diff hunks; returns realized/not per claim with a one-line rationale. The LLM judge is deliberately lighter than the proposer's own model — we don't want the judge to share blind spots with the proposer.
- **DRR Gap** is just `abs(DRR_LLM - DRR_Structural)`; reported alongside the two raw numbers. The first 30-iter run uses both methods on every sample so we can calibrate the gap distribution before deciding to lean on one or the other long-term (open question §6.1).
- **Cr** is computed in-process whenever `ErrorSignatureSkill.extract` runs on a real failure: the skill records `(input_chars, output_chars)` to a sidecar log; aggregator reports median + p95.
- **SRR computation** is automated by `tools/verify_sota_replication.py` (Commit 11.2): selects the top-3 V12 architectures from `run_output_*.json` by `denoising_score`; reconstructs upstream state at each Golden Iteration; processes through the post-6.3 dehydrated cache; issues a real proposer LLM call per architecture (`@real_run`-gated); computes Structural Fidelity (AST Jaccard on architectural primitives) deterministically and Reasoning Density via the same gpt-4o-mini judge used for DRR_LLM (§2.10.4). Outputs a CSV row per architecture + an SRR aggregate. Runs as a CI step on the V13 chain output, gating Phase 2 exit alongside G4.

#### 4.2.2 Caveats

- The metrics rely on Phase 1 being trustworthy. If Phase 1 telemetry shows `tokens.prompt is None` for >5% of rows (provider does not return usage), we degrade to char-based comparison and document the caveat.
- FRR can be falsely zero if the proposer never has occasion to repeat itself (e.g., the chain explores a wide design space). To guard against false negatives, also check `n_unique_architectures / n_total_iters` is healthy (> 0.7) — a high-FRR-but-also-low-diversity proposer would be a different kind of broken.
- DRR uses an LLM judge; any LLM judge has noise. Calibrate by running DRR on a known-good baseline (V11 records, where we can manually agree on realized vs not) and verify the judge produces reasonable numbers.

---

## 5. Implementation Steps — Numbered Action List

**Decision gates** (no implementation begins until each gate passes):

- **Gate G0 (this doc)** — design approval. The quantitative success criteria in §4 must be explicitly agreed before any code lands.
- **Gate G1** — Phase 1 baseline report (`reports/v12_token_baseline.md`) + Top-3 Bloat Report (`reports/v12_top3_bloat.md`, §1.9) — gates Phase 2 design validity.
- **Gate G2** — Offline Forensic Benchmark (§2.8) passes — gates `ErrorSignatureSkill` going to production.
- **Gate G3** — Trap Test (§2.9) passes — gates the Sliding Window going to production.
- **Gate G3.5** — SOTA Replication Test (§2.10) passes on ≥ 2 of 3 top V12 architectures (Metric #12, SRR) — gates Phase 2 exit. Aspirational guard: verifies the consolidator did not prune the high-signal architectural insights that drove V12 SOTA.
- **Gate G4** — All §4 metrics pass on V13 chain run — gates legacy-path removal.

Each step is annotated `(Commit N)` matching the §8 commit ledger. Within a commit, all listed steps land together — they are not separately committable.

### Phase 1 (telemetry — must land first)

1. **(Commit 1)** **`agent/schemas/telemetry/token_usage.py`** — define `TokenUsageRow` Pydantic schema. Includes `tokens` (`prompt`/`completion`/`total`, all `Optional[int]`), `chars`, `components: Dict[str, int]`, `label`, `iter`, `model`, `provider`, `run_name`, `run_id`, `ts`, `extra`. Add `__init__.py`. Define `LLMBridgeContextError` exception alongside.
2. **(Commit 1 + Commit 2)** **`agent/llm_bridge.py`**:
   - **(Commit 1)** Modify `_chat_json` (line 615 region) to capture `response.usage` and pass it through. Same for `generate_text` (line 689) and `tool_call` and `reflect`.
   - **(Commit 1)** Add `_record_usage(...)` helper that appends one validated `TokenUsageRow` to `{workspace}/token_usage.jsonl`. Silent no-op when context unset.
   - **(Commit 1)** Add `label: str` kwarg to `generate`, `generate_text`, `tool_call`, `reflect`. Default `"unlabeled"` so old callers don't break, but log a warning when default is hit.
   - **(Commit 2)** Add `set_run_context(workspace, iter, run_name, run_id)` method with the §1.4.1 Setter Safety Protocol — refuses run_id mutation, refuses backwards iter, emits `_iter_flush` markers at iter boundaries; raises `LLMBridgeContextError` per §1.4.2.
3. **(Commit 1 + Commit 2)** **Unit tests for the bridge** — `tests/unit/agent/llm_bridge/`:
   - **(Commit 1)** `test_record_usage.py` — mock OpenAI client; assert one row written; assert fallback when `response.usage` is None.
   - **(Commit 2)** `test_setter_safety.py` — `test_setter_rejects_run_id_mutation`, `test_setter_rejects_backwards_iter`, `test_record_usage_aborts_on_run_id_mismatch`, `test_iter_flush_marker_emitted`, `test_jsonl_linter_detects_leakage`, `test_no_silent_swallow` (AST-grep static check), `test_runner_aborts_on_runid_mismatch` (subprocess test).
4. **(Commit 3)** **`nodes/ml_model_proposal_agent.py`** — add `_audit_proposer_components(...)` helper. Call it just before each `bridge.generate(...)` invocation (line 1014, 1054, 1134). Pass result as `extra` to the bridge.
5. **(Commit 3)** **Unit test for component audit** — `tests/unit/agent/proposal/test_audit_components.py`. Synthetic `accumulated` dict; assert all 9 keys present; assert sum equals total.
6. **(Commit 3)** **Add labels to all LLM call sites** — proposer, tuner planner, tuner reflector, interpretation per-model + synthesis + dedup, validator code review.
7. **(Commit 4)** **`workflows/model_exploration.py`** — call `bridge.set_run_context(workspace, iter, run_name, run_id)` at the top of each iter, with run_id generated once at workflow start.
8. **(Commit 4)** **`run_exploration_adaptive.py`** — generate run_id at startup; at iter end, read `token_usage.jsonl` for the current iter, emit `[TOKEN_ITER]` rollup line via the existing `_TeeStream`.
9. **(Commit 4)** **Pseudo-mode integration test** — one-iter end-to-end; assert `token_usage.jsonl` exists; assert ≥4 rows present and parse cleanly; assert `_iter_flush` markers correct.
10. **(Commit 5)** **Land Phase 1**, run one V12-baseline chain (5+ iters), publish `reports/v12_token_baseline.md` showing real per-call token counts.
11. **(Commit 5) Gate G1: Top-3 Bloat Report** — produce `reports/v12_top3_bloat.md` per §1.9 spec. **Decision branch**:
    - Verdict (1) "Confirmed Proposer Hypothesis" → continue to Commit 6.
    - Verdict (2) "Pivot Required — Tuner" or (3) "Other" → set §2 aside, draft a new design targeting the actual bloat source. **STOP HERE** until the new design is approved.
    - Sanity floor (§1.9.3) trips → defer Phase 2; revisit at iter 15.

### Phase 2 (dehydration — only after Gate G1 verdict 1)

12. **(Commit 6)** **`agent/skills/error_signature_skill.py`** — `ErrorSignature` dataclass + `extract` + `render`. Unit-test with samples from existing `validator_iter_*.json` files.
13. **(Commit 7) Gate G2: Offline Forensic Benchmark** — write `tests/forensic/test_v11_spectral_u_signature.py` per §2.8. Run against the V11 `spectral_u_operator_lite` forensic workspace. **All 6 assertions must pass.** If any fails, iterate on the skill (re-open Commit 6) before proceeding. **Do not land Commit 8 until this passes.**
14. **(Commit 8)** **`agent/schemas/proposal.py`** — add `EvolutionaryLedger`, `PredecessorEntry`, `OlderAttemptSummary`, `DeltaReasoning`. Add `ProposalInput.ledger` (default `None` for backward compat) and `ProposalOutput.delta_reasoning` (default `None` initially; tighten to required after one chain run).
15. **(Commit 9)** **`nodes/proposal_helpers.py`** — `truncate_score_tables`, `apply_source_window`. Unit-test both.
16. **(Commit 10)** **`core/resume.py`** + **`workflows/model_exploration.py`** + **`agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py`** — build the `EvolutionaryLedger` from disk-resident interpretation + run_output files. Include the dehydrated `ErrorSignature` for the predecessor.
17. **(Commit 11)** **`nodes/ml_model_proposal_agent.py`** — render the ledger in the user prompt (replacing the flat `previous_failures` block, the full `per_model_score_tables` JSON, and the per-attempt source code dump). Keep the legacy path behind `inp.ledger is None`.
18. **(Commit 11)** **`agent/prompt_templates/proposal/causal_reasoning_stage*.md`** — add the Delta Reasoning required block (×3 files). Same for `proposing_stage*.md` (×3) referencing the `delta_reasoning` output field.
19. **(Commit 11)** **Unit tests** — `test_evolutionary_ledger.py`, `test_truncate_score_tables.py`, `test_source_window.py`, `test_iter2_lesson_present_in_iter10_prompt` (the §2.9 plumbing-only Trap unit test). All synthetic, no API.
20. **(Commit 11) Gate G3: Trap Test** — write `tests/integration/proposer/test_long_term_wisdom_trap.py` per §2.9. Run in real-API mode with `@real_run` marker. **Both assertions must pass** (cite the iter-2 lesson AND avoid the failing architecture). If fails, tune §2.9.4 knobs before proceeding.
21. **(Commit 11)** **Tier-1 integration test** — `tests/integration/nodes/test_ml_model_proposal_agent_ledger.py` — real LLM call with a populated `EvolutionaryLedger`; assert `delta_reasoning` is present and well-formed.
22. **(Commit 12)** **Land Phase 2 behind `use_evolutionary_ledger=True` default**, run one V13 chain (5+ iters; ideally ≥ 15 iters so iter 30 metrics extrapolate), compare against V12 baseline.
23. **(Commit 12) Gate G4: §4 metrics validation** — publish `reports/v13_token_dehydration.md` reporting all 13 metrics (cost rows 1–6, 9 + intelligence rows 7, 8a, 8b, 8c, 10, 11). **All metrics must pass their target.** If any fails:
    - FRR > 0 → revisit §2.4 sliding window depth, §2.6 confirmed_lessons promotion threshold.
    - DRR_Structural < 0.70 → tighten the §2.5 Delta Reasoning prompt to demand specific, machine-checkable claims.
    - DRR Gap > 0.25 → re-tune the structural matcher and/or the LLM judge before trusting either number.
    - Cr ≥ 0.15 median or ≥ 0.30 p95 → revisit `error_signature_skill.extract` heuristics; widen `last_frames_count`.
    - Cost metrics fail → ledger is leaking; instrument and patch.
24. **(Commit 12 cleanup)** **If all G4 metrics pass**, remove the legacy fallback path (line 644-648 in proposer, the flat `previous_failures` field, the un-truncated `per_model_score_tables` inclusion). One cleanup commit.

---

## 6. Open Questions for Reviewer

1. **Structural-vs-Semantic DRR — long-term direction**: revision 3 keeps both `DRR_Structural` (AST/regex) and `DRR_LLM` (semantic judge) as a hybrid. Three options going forward:
   - (a) Keep both forever. Cost: every metrics run is two passes; gap is informative but redundant once calibrated.
   - (b) Promote `DRR_Structural` to canonical, demote `DRR_LLM` to spot-check (e.g. run only when gap > 0.25 was observed in the previous run). Cost: depends on a working AST matcher across all proposer claim types.
   - (c) Build a richer **AST-diffing skill** (`agent/skills/ast_diff_skill.py`) that emits typed deltas (`ConvLayerAdded(channels=64, kernel=3)`, `LSTMReplacedByGRU`, etc.). The proposer's `delta_reasoning` claims are then matched in a typed namespace, not regex. Higher upfront cost; eliminates LLM-judge dependency entirely.
   - **Recommendation: (a) for the first chain run, then decide based on the gap distribution.** If the gap is consistently small, move to (b); if claim shapes are too varied for AST matching, defer (c) as a later refactor. Marked here as an explicit open question because option (c) is significant engineering and warrants its own design doc if pursued.

2. **Sliding-window default (`K`)**: I propose `older_attempts` ≤ 8 entries. Too aggressive? Too lax? An iter-30 run has 27 older attempts; we need to pick which are kept (latest 8? top-8 by score? mixed?).
3. **`recent_gate_exhaustions` overlap**: this field is already bounded to 3. Does it stay as a separate field, or fold into `confirmed_lessons` of the ledger? Folding is cleaner; keeping is safer for the gate-exhaustion-specific telemetry already being read elsewhere. Phase 1 measurements should answer whether the field is still load-bearing.
4. **Pricing tier coverage in the bridge**: should `_record_usage` also record an estimated dollar cost per row, or is that a downstream report-builder concern? I lean toward the latter — pricing tiers change; the row should stay raw.
5. **Validator + implementor LLM calls**: are these in scope for Phase 1 telemetry? They emit smaller prompts but they fire many times during repair loops. Recommend yes; cheap to label.
6. **Backwards compat window for the legacy fields**: do we keep `previous_failures: List[str]` as a deprecated field for one release, or remove on land? A V11 forensic re-run might want to read old proposal_iter_*.json files — schema removal would break that.

---

## 7. Out of Scope (explicitly)

- Tokenizer-accurate pre-flight prediction (we emit `chars` for cross-check; we do *not* run a local tokenizer to predict token count before sending). Not worth the dependency churn for the optimization gain.
- Streaming token count (some providers stream; we capture only the final `response.usage`).
- Cross-run comparison dashboard. The `token_usage.jsonl` rows are the building block; a dashboard is a follow-up.
- Tuner planner refactor. `memory_history` resets per-iter, so within-iter growth is a separate problem domain. Phase 1 telemetry will tell us whether the tuner is the next refactor target.

---

## 8. Step-by-Step Commit & Validation Ledger

This section is the executable contract. "Execute Commit #N" maps deterministically to the tasks, tests, and Definition of Done below. §5 step numbers are cross-referenced as "(§5 step X)" throughout. Mark `[x]` only after the Pre-Commit Checklist passes — never sooner.

**Conventions for every commit**:

- **Scope** lists every file touched (new + modified). Files outside Scope must not be touched in the commit.
- **Tasks** is the implementation work, in order. `[ ]` = not done; `[x]` = verified done.
- **Pre-Commit Checklist** has three required entries: a positive test (the new code works), a quantitative metric (the change is measurable), and a negative test (failure modes raise loudly). All three must pass before the commit lands.
- **Definition of Done** is a one-line operator-level statement of what is now true after this commit lands.
- **Out of Scope** is the explicit "don't gold-plate" list — work that belongs in a *later* commit.

---

### Commit 1: Bridge usage capture + token_usage row schema

**Phase**: 1 (Telemetry foundation).
**§5 steps**: 1, 2 (capture portion only), 3 (positive test only).

**Scope**:
- `agent/schemas/telemetry/__init__.py` (new)
- `agent/schemas/telemetry/token_usage.py` (new)
- `agent/llm_bridge.py` (modify `_chat_json`, `generate_text`, `tool_call`, `reflect`)
- `tests/unit/agent/llm_bridge/__init__.py` (new, may already exist)
- `tests/unit/agent/llm_bridge/test_record_usage.py` (new)

**Tasks**:
- [x] Define `TokenUsageRow` Pydantic model with the §1.7 fields. All token counts `Optional[int]`.
  - **Implementation note (2026-05-04)**: split into three Pydantic models in `agent/schemas/telemetry/token_usage.py` for clarity — `TokenCounts` (provider-reported `prompt`/`completion`/`total`, all `Optional[int]`), `TokenUsageChars` (local `system`/`user`/`total`, `int` with `ge=0`), and `TokenUsageRow` (the row itself). All three use `ConfigDict(extra="forbid")` so accidental schema drift is caught at validation. `components: Dict[str, int]` and `extra: Dict[str, Any]` deliberately stay open (no nested model) so callers can supply per-stage breakdowns and free-form context without a schema migration. `iter`, `model`, `provider` are `Optional` because marker rows (e.g. `_iter_flush`) do not have those values; `chars` is required because we always know the local lengths.
  - **Package init**: `agent/schemas/telemetry/__init__.py` re-exports `LLMBridgeContextError`, `TokenCounts`, `TokenUsageChars`, `TokenUsageRow`.
- [x] Define `LLMBridgeContextError(RuntimeError)` exception (used by Commit 2; declared here so the import exists).
  - **Implementation note (2026-05-04)**: subclass of `RuntimeError`. The runner translates it into `sys.exit(2)` (Commit 2 work) — the exception itself is `RuntimeError` per §1.4.2 so existing test harnesses that intercept `BaseException` only via `pytest.raises(RuntimeError)` continue to work; the fail-fast behaviour comes from the runner's top-level handler, not from inheriting `SystemExit` directly. The static AST check (`tests/unit/agent/llm_bridge/test_no_silent_swallow.py`, Commit 2) is the guarantee that no inner `except` swallows it.
- **Smoke test result (2026-05-04)**: hand-run via `.venv/bin/python -c "..."` covered 7 invariants — happy-path round-trip (`model_dump_json` → `model_validate_json` produces identical row, 415 chars), degraded path (`tokens={prompt:None,completion:None,total:None}`), marker row (`label='_iter_flush'`, no model/provider), `extra="forbid"` rejection (ValidationError on unknown root field), `ge=0` rejection (ValidationError on negative `chars.user`), and `LLMBridgeContextError` is a `RuntimeError` subclass. **All 7 checks passed.**
- [x] In `LLMBridge._chat_json` (line 615 region), capture `response.usage`; pass to a new `_record_usage` helper.
  - **Implementation note (2026-05-04)**: `_chat_json` now takes `label: str` and `provider: Optional[str]` kwargs. The body was restructured so that status classification (`"ok"` / `"empty_content"` / `"json_decode_error"` / `"wrong_type"`) happens before the existing retry-sleep branch, and `_record_usage` is invoked once per attempt with `extra={"attempt": N, "status": <classified>}`. The success path (`status == "ok"`) is unchanged in observable behaviour; the only added cost on the success path is one `model_dump_json()` per call when the run-context is bound. When `provider` is omitted, the helper auto-detects it: `self.reflect_provider` if `client is self.reflect_client`, else `self.provider`.
- [x] In `LLMBridge.generate_text` (line 689), capture `response.usage`; pass through.
  - **Implementation note (2026-05-04)**: plain-text mode has no content-retry, so `_record_usage` is invoked once with `extra={"attempt": 0, "status": "ok"}`. Provider passes as `self.provider`.
- [x] In `LLMBridge.tool_call` and `LLMBridge.reflect`, capture `response.usage`; pass through.
  - **Implementation note (2026-05-04)**: `tool_call` records before the `if not message.tool_calls` raise — even a `no_tool_call` response burned tokens, so we still write a row with `extra={"attempt": 0, "status": "no_tool_call"}` before raising `ValueError`. `reflect` flows through `_chat_json` with `label="tuner.reflector"` and `provider=self.reflect_provider`, inheriting the per-attempt telemetry of `_chat_json` for free.
- [x] Implement `_record_usage(label, response, system_prompt, user_prompt, extra=None)`. Silent no-op when `self._token_usage_path is None` (context unset — Commit 2 wires the setter).
  - **Implementation note (2026-05-04)**: signature uses keyword-only args (`*, response, label, system_prompt, user_prompt, model_name, provider, extra=None`) for clarity at every call site. Reads `response.usage.{prompt_tokens,completion_tokens,total_tokens}` via `getattr`, so an SDK shape with no `.usage` attribute (e.g. older client, stream mode) degrades to `TokenCounts()` (all-None) rather than `AttributeError`. Char counts always populated. File appended in `"a"` mode with `buffering=1` (line-buffered) per user directive — concurrent bridge instances in one process do not interleave partial lines. Schema-validation failures and `OSError` on append are logged to stderr and swallowed; **only** `LLMBridgeContextError` (Commit 2) is allowed to propagate. The four run-context fields (`_token_usage_path`, `_iter`, `_run_id`, `_run_name`) are initialized to `None` in `__init__`; setter that populates them is Commit 2.
- [x] Add `label: str = "unlabeled"` kwarg to `generate`, `generate_text`, `tool_call`, `reflect`. Log a warning when default is hit. **Decision (2026-05-04)**: per Q2 confirmation, internal sites `plan()` and `reflect()` will pass `label="tuner.planner"` / `label="tuner.reflector"` immediately in this commit so the V12 baseline run is meaningfully labeled and `chain_log.txt` is clean of internal "unlabeled" warnings. External-node labeling (proposer, interp, validator) remains in Commit 3.
  - **Implementation note (2026-05-04)**: class attribute `_DEFAULT_LABEL = "unlabeled"` plus helper `_warn_default_label(method_name)` prints a one-line `[LLMBridge.<method>] WARNING:` to stderr referencing §1.5 of the design doc. The warning fires per-call (not deduped) so a missed call site is visible in `chain_log.txt` until labeled. `plan()` calls `self.generate(..., label="tuner.planner")`; `reflect()` calls `self._chat_json(..., label="tuner.reflector", provider=self.reflect_provider)`. Both internal call sites short-circuit the warning because they pass an explicit label.
- **Per-attempt telemetry decision (2026-05-04, Q1 confirmed)**: in `_chat_json`'s content-retry loop, `_record_usage` is called **inside** the loop, after `_call_with_retry(...)` returns but before JSON parsing. Each attempt — including JSON-decode failures — produces one row, with `extra={"attempt": N, "status": "ok"|"json_decode_error"|"empty_content"|"wrong_type"}`. This makes provider noise (e.g. deepseek-v4-pro empty-content events) measurable rather than estimated.

**Pre-Commit Checklist**:
- [x] **Positive test**: `pytest tests/unit/agent/llm_bridge/test_record_usage.py -v` — mock the OpenAI client to return `Usage(prompt_tokens=100, completion_tokens=50, total_tokens=150)`; assert exactly one valid `TokenUsageRow` is appended to a tmp_path log file with the correct counts and label. **Result (2026-05-04)**: `test_generate_writes_one_row_with_correct_counts` PASSED — counts/label/run_id/iter/components/extra all match expected; row validates through `TokenUsageRow` round-trip.
- [x] **Quantitative metric**: with context unset, calling `generate(...)` produces 0 rows in any log file (the no-op path is verified by `pytest -k test_record_usage_noop_when_unbound`). **Result (2026-05-04)**: `test_record_usage_noop_when_unbound` PASSED — `bridge._token_usage_path` defaults to `None`; after a `generate()` call returning a valid response, `tmp_path` is empty.
- [x] **Negative test**: `pytest -k test_record_usage_handles_missing_usage` — when the mocked response has `usage=None`, the row is still written, with `tokens.prompt=None` and `chars.user > 0` (graceful degradation, not silent skip). **Result (2026-05-04)**: `test_record_usage_handles_missing_usage` PASSED — row written with `tokens={prompt:None,completion:None,total:None}` and char counts populated.
- [x] **Per-attempt quantitative check** (Q1 verification per user directive): a multi-retry `_chat_json` call produces exactly N rows where N = number of attempts, with monotonic `attempt` indices and correct per-attempt `status`. **Result (2026-05-04)**: `test_chat_json_writes_one_row_per_attempt` PASSED — three side-effect responses (bad-JSON, bad-JSON, ok) yielded three rows with `attempt=[0,1,2]`, `status=["json_decode_error","json_decode_error","ok"]`, and prompt-token sequence `[10,11,12]` matching the mock side_effect order. Companion `test_chat_json_writes_row_for_empty_content` covers the `empty_content` status branch.
- [x] **`tool_call` no-tool-call branch**: even when the model declines to invoke a tool, the row is still written before raising `ValueError`. **Result (2026-05-04)**: `test_tool_call_writes_row_then_raises_when_no_tool_call` PASSED — row stamped `extra={"attempt":0,"status":"no_tool_call"}`.
- [x] **Internal-label coverage** (Q2 verification): `plan()` rows are labeled `tuner.planner` and `reflect()` rows are labeled `tuner.reflector`; neither method emits the "unlabeled" stderr warning. **Result (2026-05-04)**: `test_plan_uses_tuner_planner_label` and `test_reflect_uses_tuner_reflector_label` both PASSED — labels correctly stamped, `capsys.readouterr().err` contains no `WARNING: called without label=`.
- [x] **Default-label warn path**: `generate("s", "u")` with no `label=` kwarg writes a row with `label="unlabeled"` AND prints `[LLMBridge.generate] WARNING: called without label=` to stderr. **Result (2026-05-04)**: `test_generate_default_label_emits_warning` PASSED.
- [x] **Regression: existing bridge tests pass unchanged**. **Result (2026-05-04)**: `pytest tests/unit/agent/test_llm_bridge.py tests/unit/agent/test_llm_bridge_singleton.py` — 54 pre-existing tests + 11 new = **65 total PASSED in 0.54s**. The `label=` kwargs all default to `"unlabeled"` so legacy callers (test fixtures) emit a stderr warning but do not break.
- [x] `grep -n "label=" agent/llm_bridge.py` shows the kwarg present on `generate`, `generate_text`, `tool_call`, `reflect` (verified at lines for the four public entry points + `_chat_json` private helper).

**Definition of Done**: every LLMBridge entry point captures `response.usage` and routes it through `_record_usage`; with no setter wired, the helper is a verified no-op; the row schema is validated. **Status (2026-05-04): MET.**

**Out of Scope**: setter logic (Commit 2), call-site labeling (Commit 3), workflow plumbing (Commit 4).

---

### Commit 2: Setter Safety Protocol + fail-fast

**Phase**: 1.
**§5 steps**: 2 (setter portion), 3 (safety tests).

**Scope**:
- `agent/llm_bridge.py` (add `set_run_context`, validation hooks, `_flush_iter_marker`)
- `tests/unit/agent/llm_bridge/test_setter_safety.py` (new)
- `tests/unit/agent/llm_bridge/test_no_silent_swallow.py` (new — AST-grep static check)
- `tools/validate_token_usage_jsonl.py` (new — the leak linter, also used by Commit 5 reports)

**Tasks**:
- [x] Add `set_run_context(workspace, iter, run_name, run_id)` method per §1.4.1. Stores `_token_usage_path`, `_iter`, `_run_name`, `_run_id`, `_set_at_ts`.
  - **Implementation note (2026-05-04)**: keyword-only args (`*, workspace, iter, run_name, run_id`). Body is wrapped in `with self._lock:` per the user's concurrency directive — see "Concurrency mechanism" below. Performs four ordered checks before mutating state: run_id immutability → backwards-iter → workspace existence → workspace writability (`os.access(parent, os.W_OK)`). Only after all four pass does it (a) optionally call `_flush_iter_marker_locked` and (b) update the four primary fields plus `_set_at_ts`.
- [x] Implement run_id immutability check: if `self._run_id is not None and run_id != self._run_id`, raise `LLMBridgeContextError`.
  - **Implementation note (2026-05-04)**: error message includes both old and new run_id and explicitly tells the operator that "a new run_id requires a fresh LLMBridge instance" — telemetry corruption being silent is the failure mode we're guarding against, so the message is verbose by design.
- [x] Implement forward-only iter advancement: same-iter re-entry allowed; backward-iter raises.
  - **Implementation note (2026-05-04)**: `iter == self._iter` permitted (covers stage retries within the same iter — e.g. proposer retried after validator rejection). `iter < self._iter` raises `LLMBridgeContextError`. `iter > self._iter` triggers the flush marker. Negative `iter` raises `ValueError` (programmer bug, not run-time corruption).
- [x] On legitimate iter advancement, call `_flush_iter_marker()` which appends `{"label": "_iter_flush", "iter": <prev>, "marker": "iter_end", ...}`.
  - **Implementation note (2026-05-04)**: implemented as `_flush_iter_marker_locked` (caller-holds-lock convention). Constructs a `TokenUsageRow` with `label="_iter_flush"`, `iter=<prev_iter>`, `tokens=TokenCounts()` (all-None), `chars=TokenUsageChars(0,0,0)`, `extra={"marker": "iter_end"}`; runs `_validate_pre_write_locked` against `prev_iter` so a marker write that would violate any §1.4.1 invariant fails the same way a normal row would. Per the concurrency directive, `f.flush()` is called explicitly before exiting the `open()` block to maintain strict ordering with subsequent `_record_usage` rows.
- [x] In `_record_usage`, add the four per-row checks per §1.4.1 (run_id matches file's first row, iter not less than last logged, path writable, ts monotonic warning).
  - **Implementation note (2026-05-04)**: factored into `_validate_pre_write_locked(target_iter, ts)` for reuse by `_flush_iter_marker_locked`. First-row run_id check is **lazy + cached**: on first invocation, reads the file's first line (if file exists and non-empty); caches the result in `self._first_row_run_id_cache`. Subsequent calls compare against the cache (no disk hit). When the file is missing/empty on first write, the bridge's own run_id is cached (we own row 0). A corrupt first line (invalid JSON) raises `LLMBridgeContextError` because the audit log is already broken. Iter-monotonic check uses `self._last_logged_iter` (in-memory tracker, updated on every successful append). ts-monotonic is a soft warning to stderr — clock skew doesn't justify aborting a run.
- [x] Implement `tools/validate_token_usage_jsonl.py` — one-pass linter: detects rows with `iter=N` after an `_iter_flush` for iter `N`; mismatched run_ids; non-monotonic timestamps. Returns nonzero exit code on any anomaly.
  - **Implementation note (2026-05-04)**: ~150 lines. `lint(path) -> (errors, warnings)` is the importable entrypoint (used by both the CLI `main()` and the unit tests). Validates each row via `TokenUsageRow.model_validate` rather than just JSON-parsing, so schema violations are caught alongside structural issues. Error tags: `[BAD_JSON]` / `[BAD_SCHEMA]` / `[RUN_ID_MISMATCH]` / `[DUPLICATE_FLUSH]` / `[LEAK]`. Warnings (`[WARN]`) are non-fatal — non-monotonic ts only. CLI: `python tools/validate_token_usage_jsonl.py <path>` returns 0/1; `--quiet` suppresses the success line for use in CI.

**Concurrency mechanism (per user directive 2026-05-04)** — documented here as required:

A `threading.Lock` (plain, not RLock) is created in `LLMBridge.__init__` as `self._lock`. Two regions enter the lock:

1. **`set_run_context` body** — entire body after the cheap `iter < 0` ValueError check is wrapped in `with self._lock:`. The lock holds across run_id check → backwards-iter check → workspace checks → optional `_flush_iter_marker_locked` → state mutation. This makes the "state-check / iter-flush write / state-update" sequence atomic with respect to any concurrent `_record_usage` caller.
2. **`_record_usage` post-no-op block** — after the early-return on unbound state, the lock holds across `_validate_pre_write_locked` → row construction → `open()` + `f.write()` + `f.flush()` → `self._last_logged_iter` / `self._last_ts` update. Without this, a concurrent `set_run_context` advancing iter could write a flush marker between this method's pre-write check and its actual append, producing a leak.

Helpers `_flush_iter_marker_locked` and `_validate_pre_write_locked` are named with the `_locked` suffix as a convention: the caller is required to hold `self._lock`. This avoids the cost of RLock (re-entrance support) without sacrificing correctness — there are no call paths that re-enter the lock.

Atomicity of small JSONL appends is reinforced by `buffering=1` (line buffering) plus an explicit `f.flush()` before the `with open()` block exits, both per the directive. This guarantees that a row landing on disk is the complete row, never a partial line — even under SIGINT mid-write.

**Pre-Commit Checklist**:
- [x] **Positive test**: `pytest tests/unit/agent/llm_bridge/test_setter_safety.py::test_setter_happy_path` — calling `set_run_context` then `_record_usage` writes one row; advancing `iter` writes the prior `_iter_flush` marker first; the linter passes the resulting file. **Result (2026-05-04)**: PASSED — bound state correct, row written with `iter=0` and `run_id="r-001"`; `test_setter_advance_iter_writes_flush_marker` separately verifies that `set_run_context(iter=4)` after `iter=3` writes a flush marker for `iter=3` with `extra={"marker":"iter_end"}` and zeroed counts.
- [x] **Quantitative metric**: in a 5-iter mock run with 12 calls/iter, the JSONL contains exactly `60 + 4` rows (4 `_iter_flush` markers between iters; no flush after the final iter); linter exit code is 0. **Result (2026-05-04)**: `test_5_iter_quantitative_and_linter_passes` PASSED — observed exactly 60 data rows + 4 flush rows (iters [0,1,2,3]); no flush after iter=4; `tools.validate_token_usage_jsonl.lint(path)` returned `errors=[]`.
- [x] **Negative test (run_id)**: `pytest -k test_setter_rejects_run_id_mutation` — calling `set_run_context` twice with different run_ids raises `LLMBridgeContextError`; the second call writes nothing. **Result (2026-05-04)**: PASSED — `bridge._run_id` remains `"r-A"` after the rejected `"r-B"` call.
- [x] **Negative test (backwards iter)**: `pytest -k test_setter_rejects_backwards_iter` — `set_run_context(iter=5)` then `set_run_context(iter=3)` raises. **Result (2026-05-04)**: PASSED — `LLMBridgeContextError` matches `"backwards iter"`; `bridge._iter` stays at `5`.
- [x] **Negative test (file-level run_id)**: `pytest -k test_record_usage_aborts_on_runid_mismatch` — pre-seed a JSONL with run_id=`A`; bridge with run_id=`B` raises on first write; file is unchanged. **Result (2026-05-04)**: PASSED — `LLMBridgeContextError` matches `"run_id mismatch"`; pre-seeded file has exactly 1 row, run_id=`OTHER-RUN`, unmutated.
- [x] **Negative test (no silent swallow)**: `pytest tests/unit/agent/llm_bridge/test_no_silent_swallow.py` — AST-greps `agent/llm_bridge.py` for any `except LLMBridgeContextError`; assertion fails if any are present. **Result (2026-05-04)**: 3/3 PASSED — `test_bridge_path_resolves` (sanity), `test_no_except_llm_bridge_context_error_in_bridge` (direct AST-grep), and `test_bare_except_does_not_swallow_context_error` (softer check that bare/`Exception`-typed `except` blocks don't enclose `_record_usage` / `set_run_context` / `_validate_pre_write_locked` / `_flush_iter_marker_locked` calls).
- [ ] **Negative test (subprocess abort)**: `pytest -k test_runner_aborts_on_runid_mismatch` — spawn a subprocess pointed at a workspace with a conflicting run_id; assert exit code 2 and `[FATAL] LLMBridgeContextError` in stderr. **Deferred (2026-05-04)**: this test depends on `run_exploration_adaptive.py` installing a top-level `LLMBridgeContextError → sys.exit(2)` handler, which is part of Commit 4's runner scope (Commit 2 explicitly excludes the runner from its `Scope`). **Moved to Commit 4's checklist** — see the deferred item there. The bridge's *own* contract (it raises pre-write, never writes the corrupting row) is covered by `test_record_usage_aborts_on_runid_mismatch` above.
- [x] **Negative test (linter — leak)**: hand-craft a JSONL with iter=4 row appearing after `_iter_flush` for iter=4; `tools/validate_token_usage_jsonl.py` returns nonzero with the leak location. **Result (2026-05-04)**: `test_linter_detects_post_flush_leak` PASSED — `lint()` returned an error tagged `[LEAK]`; CLI `main([str(log)])` returned exit code `1`. Companion `test_linter_detects_run_id_mismatch` covers `[RUN_ID_MISMATCH]`; `test_linter_warns_on_non_monotonic_ts` covers the warn-only ts path (errors empty, warnings non-empty).
- [x] **Concurrency check (per user directive)**: 8 threads racing on `set_run_context(iter=0)` with the bridge already at `iter=0` produce zero `_iter_flush` markers (strict-greater-than guard) and no exceptions. **Result (2026-05-04)**: `test_setter_thread_safety_no_duplicate_flush` PASSED — 8 data rows, 0 flush markers, no captured exceptions.
- [x] **Regression**: full bridge test bundle (`tests/unit/agent/llm_bridge/`, `tests/unit/agent/test_llm_bridge.py`, `tests/unit/agent/test_llm_bridge_singleton.py`). **Result (2026-05-04)**: **92 PASSED in 0.59s** (11 Commit 1 + 13 Commit 2 setter + 3 AST guard + 65 pre-existing).

**Definition of Done**: a corrupted run_id or backwards iter aborts the process with exit code 2 before any row reaches disk; the linter detects post-hoc leaks; static check guarantees no `except LLMBridgeContextError` exists in production code. **Status (2026-05-04): bridge-side MET; the runner-side `exit(2)` is delivered by Commit 4. Bridge guarantee: every code path that could corrupt the audit log raises `LLMBridgeContextError` *before* any append, verified by the negative tests above. Linter is implemented and detects all three documented anomaly classes. AST static check has zero violations on the bridge module.**

**Out of Scope**: changing the runner's existing exit-code conventions (the brake's `exit(1)` is preserved); pricing computation (out of doc scope); the runner's top-level `LLMBridgeContextError → sys.exit(2)` handler (deferred to Commit 4 along with the subprocess test that exercises it).

---

### Commit 3: Component pre-assembly hook + LLM call labels

**Phase**: 1.
**§5 steps**: 4, 5, 6.

**Scope**:
- `agent/llm_bridge.py` (thread `components: Optional[Dict[str, int]]` kwarg through `_record_usage`, `_chat_json`, `generate`, `generate_text`, `tool_call`)
- `nodes/ml_model_proposal_agent.py` (add `_audit_proposer_components` + `_extract_prior_stage_keys`, label all 6 call sites, pass `components=` on the 4 staged sites)
- `nodes/ml_model_implementor.py` (label 3 call sites — discovered during the static AST sweep; not in original scope but required for the "no `label=unlabeled`" gate)
- `nodes/result_interpretation_agent.py` (label per_model + synthesis + dedup calls)
- `nodes/ml_code_validator_agent.py` (label code-review call)
- `tests/unit/agent/ml_model_proposal_agent/test_audit_components.py` (new — placed under existing proposer test dir per project convention)
- `tests/unit/agent/llm_bridge/test_all_calls_labeled.py` (new — permanent AST regression guard)
- Tuner is unchanged: `LLMBridge.plan()` and `LLMBridge.reflect()` already pass `label="tuner.planner"` / `label="tuner.reflector"` internally (landed in Commit 1).

**Tasks**:
- [x] Add `components: Optional[Dict[str, int]] = None` kwarg to `_record_usage`, `_chat_json`, `generate`, `generate_text`, `tool_call`. Caller-supplied dict lands in `row.components` (the schema's dedicated field) — `extra` continues to carry the retry-status payload (`{"attempt": N, "status": ...}`) untouched. **Decision (2026-05-04, Q1 confirmation)**: §1.3's "passed as `extra`" wording was imprecise; the schema split between `components` and `extra` is the real contract.
- [x] Implement `_audit_proposer_components(*, inp: ProposalInput, accumulated, agent_cards_block, expert_context_block, vocab_block, system_prompt, stage_name) -> dict` per §1.3. Returns `{stage_name, components: {9 keys}, total_chars}`. `inp` and `stage_name` were added to the original 5-arg signature (Q3 confirmation) so the function has direct access to `inp.previous_failures` and `inp.recent_gate_exhaustions`. Helper `_extract_prior_stage_keys(accumulated)` partitions stage outputs from input keys via the `_PROPOSER_INPUT_KEYS` set.
- [x] Call the hook before each `self.bridge.generate(...)` invocation in `ml_model_proposal_agent.py` and pass result via `components=` (NOT `extra=`):
  - **Staged loop (line 1011/1014 region)**: `label=f"proposer.{stage.name}"` resolves to `proposer.comparison` / `proposer.causal_reasoning` / `proposer.proposing` depending on which stage runs.
  - **Boldness retry**: `label="proposer.causal_reasoning"`, components recomputed from current `accumulated`.
  - **Proposing stage**: `label="proposer.proposing"`. Audit hook is called with `vocab_block=""` to mirror the actual user prompt assembly (proposing user prompt does NOT append the vocab block — only `agent_cards` + `expert_context`).
- [x] Label the legacy 2-call path: `label="proposer.legacy_reasoning"` (line 780) and `label="proposer.legacy_commit"` (line 797). Components is omitted (the legacy path uses `_build_reasoning_prompt` / `_build_commit_prompt`, not `_render_stage_user_prompt`, so the 9-key breakdown does not apply). Q2 confirmation: visibility over granularity for deprecated code.
- [x] Add `label="interpretation.per_model"` (line 714), `"interpretation.synthesis"` (line 820), `"interpretation.dedup"` (line 1179) to `result_interpretation_agent.py`.
- [x] Add `label="validator.code_review"` (line 544) to `ml_code_validator_agent.py`.
- [x] Add `label="implementor.reasoning"` / `"implementor.code"` / `"implementor.repair"` to `ml_model_implementor.py` (lines 751/756/769). The implementor was not in the original §1.5 table; discovered via the AST sweep and added because it is a node that calls the bridge. §1.5 table updated to reflect this.
- [x] Tuner labels: no change required. `brain.plan()` and `brain.reflect()` already pass labels internally (Commit 1).

**Implementation Details (2026-05-04)**:

- **Bridge plumbing**: `components` is keyword-only on every public method; threaded as `components=components` from each entry point down to `_record_usage`. The previous `components={}` hard-code in the row construction is replaced with `components=components or {}` so non-proposer calls produce empty dicts (schema-valid, distinguishable in downstream reports).
- **Audit hook locality**: `_audit_proposer_components` lives next to `_render_stage_user_prompt` in `ml_model_proposal_agent.py`. It computes the same `cleaned` interpretation summary (drops `per_model_score_tables` to mirror the prompt assembly) and uses `build_candidate_markdown_block` for the markdown count — so the audit's char numbers reflect what the LLM actually saw, not a separate pre-merge computation. The `_format_recent_gate_exhaustions_block` helper at module level is reused for the `recent_gate_block` count.
- **`_extract_prior_stage_keys`**: a small helper that returns `{k: v for k, v in accumulated.items() if k not in _PROPOSER_INPUT_KEYS}`. The fixed `_PROPOSER_INPUT_KEYS = {candidates, non_candidates_overview, interpretation_summary, existing_model_types, previous_failures}` set defines what counts as input vs. stage output — anything else is attributed to `prior_stage_outputs`.
- **`__init__.py` test compat**: `tests/unit/agent/result_interpretation_agent/test_interpretation_agent.py::_llm_dispatch` was updated to accept `**kwargs` so the new `label=` / `components=` kwargs from the bridge call sites no longer raise `TypeError` against the mock side_effect. No other test fixture changes were required (proposer/implementor mocks already used `*a, **kw` patterns).

**Pre-Commit Checklist**:
- [x] **Positive test**: `pytest tests/unit/agent/ml_model_proposal_agent/test_audit_components.py` — synthetic `accumulated` dict; asserts all 9 component keys present in the returned breakdown; asserts `total_chars == sum(components.values())` (the original "+ len(system_prompt)" wording was a doc bug — `system_prompt` is already one of the 9 components, so it would double-count). **Result: 5/5 PASS.**
- [x] **Quantitative metric**: AST sweep over `nodes/**/*.py` finds **0** `bridge.{generate,generate_text,tool_call}` calls without `label=` kwarg. Verified by the new permanent regression guard `tests/unit/agent/llm_bridge/test_all_calls_labeled.py`.
- [x] **Negative test**: `test_audit_components_handles_empty_blocks` — when `vocab_block` / `agent_cards_block` / `expert_context_block` / `system_prompt` are empty strings, the breakdown still has all 9 keys present (value 0 for the empty blocks; `interpretation_json` and `prior_stage_outputs` collapse to `len("{}") == 2`). **Result: PASS.**
- [x] **Static check (permanent)**: `tests/unit/agent/llm_bridge/test_all_calls_labeled.py::test_every_bridge_call_in_nodes_has_label_kwarg` walks every `<expr>.bridge.{generate,generate_text,tool_call}` call under `nodes/` and asserts `label=` is present. Q4 confirmation: chosen as a permanent regression guard rather than a one-off shell command, mirroring the `test_no_silent_swallow.py` pattern from Commit 2. **Result: 2/2 PASS.**
- [x] **Bridge bundle regression**: `pytest tests/unit/agent/llm_bridge/` — Commit 2's setter-safety + no-silent-swallow tests still pass with the new `components` kwarg threaded through. **Result: all bridge tests PASS.**
- [x] **Affected-node bundles regression**: `pytest tests/unit/agent/{ml_model_proposal_agent,result_interpretation_agent,ml_code_validator_agent,ml_model_implementor}/` — the new label/components kwargs do not break existing proposer/interp/validator/implementor unit tests. **Result: 781/781 PASS** (full suite of the 5 affected dirs including the 7 new C3 tests).

**Definition of Done**: every proposer LLM call writes a 9-key component breakdown to `token_usage.jsonl.components`; every other node's LLM call has a stable label in `token_usage.jsonl.label`; no call site under `nodes/` emits `label="unlabeled"` (verified by AST regression guard). **Status (2026-05-04): MET.**

**Out of Scope**: workflow's `set_run_context` call (Commit 4); the V12 baseline run (Commit 5).

---

### Commit 4: Workflow plumbing + per-iter rollup

**Phase**: 1.
**§5 steps**: 7, 8, 9.

**Scope**:
- `workflows/model_exploration.py` (call `bridge.set_run_context` per iter)
- `run_exploration_adaptive.py` (generate `run_id`; emit `[TOKEN_ITER]` rollup)
- `tests/integration/runner/test_token_log_iter_rollup.py` (new — pseudo mode)

**Design decisions (locked before code)**:
- **Q1 — `run_workflow` signature**: Option A — flat `chain_run_name: str | None = None` and `run_id: str | None = None` kwargs (matches existing kwarg density; no new dataclass).
- **Q2 — `run_id is None` semantics**: Option B — workflow defaults `None` and silently skips `set_run_context` (preserves the dozens of existing pseudo-mode tests). The production runner (`run_exploration_adaptive.py`) is the *single* enforcement point: it always generates a `run_id`. Therefore the `test_workflow_aborts_on_unset_run_id` negative test from the original spec is **superseded** — the contract is "runner enforces presence", not "workflow rejects None".
- **Q3 — `[TOKEN_ITER]` emission point**: Option A — runner emits after each `_run_one_iter` returns. In-process multi-iter mode (legacy/ad-hoc) gets no rollup; chain mode (production) is fully covered.
- **Q4 — Subprocess test mechanism**: Option A — purpose-built harness `tests/integration/runner/_runid_mismatch_harness.py` invoked via real `python` subprocess. No monkey-patching of internals.

**Tasks**:
- [x] Generate `run_id` once at runner startup using the §1.4.1 format (`{run_name}-{utc_ts}-{pid}`).
  - **Implementation**: `_generate_run_id(run_name)` in `run_exploration_adaptive.py` uses `datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")` (timezone-aware; avoids the `datetime.utcnow()` deprecation). The pid disambiguates concurrent runs from the same shell (e.g. parallel screens).
  - **Call site**: `main()` invokes it once after `args.workspace` is resolved and prints `[TOKEN] run_id = <id>` so the chain_log records the immutable identifier on its first line.
- [x] Thread `run_id` from runner into `workflows/model_exploration.py`.
  - **Implementation**: `_run_one_iter(args, workspace, llm_config, advice, source_paths, iteration, *, run_id)` now takes `run_id` as a keyword-only argument and forwards it together with `chain_run_name=args.run_name` into `run_workflow(...)`. `run_workflow` itself gains the matching kwargs `chain_run_name: str | None = None, run_id: str | None = None` (Q1 Option A — flat density preserved).
- [x] At the top of each iter in the workflow, call `bridge.set_run_context(workspace, iter, run_name, run_id)` for every bridge instance in scope (proposer, tuner, interpreter, validator).
  - **Implementation**: a local closure `_bind_iter_context(agent)` inside the iter loop dispatches by duck-typing — for the four direct-bridge agents (`ResultInterpretationAgent`, `MLModelProposalAgent`, `MLModelImplementor`, `MLCodeValidatorAgent`) it calls `agent.bridge.set_run_context(...)`; for the tuner (which builds its bridge lazily inside `run()`) it calls `agent.set_run_context(...)` and the tuner stores the kwargs in `self._pending_run_context`, applying them after `brain` is constructed.
  - **Tuner change**: `nodes/ml_hyperparameter_tune_agent.py` gained `set_run_context(*, workspace, iter, run_name, run_id)` plus a 4-line block that propagates the pending kwargs onto `brain` once it exists. This keeps the *contract* uniform across all 5 agents while respecting the tuner's lazy-construction internal.
  - **Backward compat**: when `chain_run_name is None or run_id is None`, `_bind_iter_context` returns early — bridges remain in their silent no-op mode (Q2 Option B). The dozens of existing pseudo-mode tests need no changes.
- [x] At iter end in the runner, parse `token_usage.jsonl` rows for the just-finished iter; emit `[TOKEN_ITER] iter=NN calls=K total_tok=… (proposer=… tuner=… interp=…)  cumulative_total=…` via the existing `_TeeStream` so it tees into `chain_log.txt`.
  - **Implementation**: `_emit_token_iter_rollup(workspace, iteration, cumulative_total_in)` reads the JSONL line by line, filters rows whose `iter` matches `iteration` (skipping `_iter_flush` synthetic markers), groups totals by `label.split('.', 1)[0]` (so `proposer.comparison` and `proposer.proposing` collapse into a single `proposer` bucket), prints exactly one summary line, and returns `cumulative_total_in + iter_total` so the caller carries the running sum across iters.
  - **Robustness**: `OSError` on `open()` returns `cumulative_total_in` unchanged (don't crash a successful iter on a transient FS hiccup); malformed JSON lines are individually skipped via `except json.JSONDecodeError` so a single bad row doesn't lose the whole rollup.
- [x] Install a top-level `LLMBridgeContextError` handler in the runner (deferred from Commit 2 per §1.4.2): on catch, emit `[FATAL] LLMBridgeContextError: <reason> — aborting run to prevent telemetry corruption.` to stderr + chain_log.txt, then call `sys.exit(2)`. The exit code is intentionally distinct from the consecutive-failure brake's `exit(1)`.
  - **Implementation**: `from agent.schemas.telemetry import LLMBridgeContextError` at module top; the iter loop in `main()` is wrapped in `try: ... except LLMBridgeContextError as e: print("[FATAL] ...", file=sys.stderr); sys.exit(2)`. Because the runner already tees stdout/stderr into `chain_log.txt` via `_TeeStream`, the `[FATAL]` line lands in the chain log automatically — no double-write needed.

**Pre-Commit Checklist**:
- [x] **Positive test (focused unit-style coverage of the rollup helper)**: `pytest tests/integration/runner/test_token_log_iter_rollup.py` — 7 tests covering the `_generate_run_id` format, `_emit_token_iter_rollup` aggregation by node prefix, missing-file handling, cumulative carry across calls, and malformed-row resilience. **Result: 7 passed in 1.58s** (2026-05-04). Note: the original spec ("one-iter pseudo run; ≥4 rows; `_iter_flush` marker; one `[TOKEN_ITER]` line in captured chain_log") would require booting the full pseudo workflow and capturing tee'd stdout; the focused tests instead exercise the rollup function directly with seeded JSONL fixtures, which is the load-bearing logic. The end-to-end "rollup line lands in `chain_log.txt`" assertion is naturally exercised by the Commit 5 V12 chain run.
- [ ] **Quantitative metric**: in a 3-iter pseudo run, `chain_log.txt` contains exactly 3 `[TOKEN_ITER]` lines; their per-node breakdowns sum to the file's per-row totals (verified by `tools/validate_token_usage_jsonl.py --rollup-check`). **Deferred to Commit 5** — the linter `tools/validate_token_usage_jsonl.py --rollup-check` does not yet exist (Commit 5 builds it alongside `tools/build_token_baseline_report.py`); the V12 chain itself is the natural fixture for this metric.
- [x] ~~**Negative test**: `pytest -k test_workflow_aborts_on_unset_run_id`~~ — **Superseded by Q2 Option B.** With `run_id=None` defaulted in `run_workflow`, the workflow silently skips `set_run_context` rather than raising; enforcement lives in the production runner. The "programming error if run_id is missing" framing now applies only to `run_exploration_adaptive.py::main`, where `_generate_run_id` is unconditional.
- [x] **Negative test (subprocess abort, deferred from Commit 2)**: `pytest -k test_runner_aborts_on_runid_mismatch` — spawn a subprocess runner pointed at a workspace whose `token_usage.jsonl` already has a different run_id; assert exit code 2 and `[FATAL] LLMBridgeContextError` in stderr. This validates the §1.4.2 end-to-end contract (bridge raises → runner translates → `sys.exit(2)`).
  - **Implementation**: `tests/integration/runner/_runid_mismatch_harness.py` is a 90-line standalone subprocess that imports the real `LLMBridge`, calls `set_run_context(...)` with a fresh `run_id`, then calls `_record_usage(...)` with a `SimpleNamespace` SDK-shape response. The first-row check fires inside the bridge, raises `LLMBridgeContextError`, the harness's top-level `except` mirrors the production handler exactly (`[FATAL] LLMBridgeContextError: ... — aborting run to prevent telemetry corruption.` + `sys.exit(2)`). The test seeds `token_usage.jsonl` with a row carrying `"run_id": "PRIOR-RUN-ID-DIFFERENT"`, spawns the harness with `"FRESH-RUN-ID"` as argv[2], and asserts `proc.returncode == 2`, `"[FATAL]" in proc.stderr`, and `"LLMBridgeContextError" in proc.stderr`. **Result: PASSED in 1.58s** (2026-05-04, included in the 7-test suite above).

**Definition of Done**: every iter of a workflow run emits one `[TOKEN_ITER]` rollup line into `chain_log.txt` and a clean stretch of rows in `token_usage.jsonl`; the linter passes. **Status (2026-05-04)**: code path is in place and unit-verified; the end-to-end "one rollup per iter in `chain_log.txt`" assertion will be observed for the first time in the Commit 5 V12 chain run, where it doubles as the input to the baseline report.

**Out of Scope**: the V12 baseline run + report (Commit 5); the `tools/validate_token_usage_jsonl.py --rollup-check` linter (built in Commit 5 alongside `tools/build_token_baseline_report.py`).

---

### Commit 4.1: Argparse-to-schema floor alignment + minimal certification config

**Phase**: 1.5 (pre-gate hardening — surfaced by the first T1 attempt on 2026-05-04).

**Scope**:
- `run_exploration_adaptive.py` — add `_portion_floor` validator; apply to `--trial_portion` and `--eval_portion`.
- `sdsc_submission_scripts/run_one_iteration.py` — mirror `_portion_floor` (parity with the chain-consistency contract in `tests/unit/scripts/test_chain_consistency.py`).
- `llm_configs/certify_minimal.json` (new) — every role pinned to `gpt-4o-mini` for T1/T2.
- `tests/unit/scripts/test_portion_floor.py` (new) — 17 tests parametrised across both runners; `test_floor_rejects_just_below` reproduces the 2026-05-04 T1 crash mode (0.005).

**Tasks**:
- [x] Add `_portion_floor(s)` mirroring the Pydantic `ge=0.01` constraint with a clear error message that names the segment-integrity reason. Applied to both `--trial_portion` and `--eval_portion` on both runners.
- [x] Create `llm_configs/certify_minimal.json`. Loads cleanly via `WorkflowLLMConfig.from_json` (verified 2026-05-04); the `_comment` key is silently ignored by Pydantic v2 default `extra="ignore"`.
- [x] Add 17 unit tests covering both validators (adaptive + ROI), boundary, sub-floor reject, zero/negative/non-numeric reject, above-1.0 reject, name parity, and end-to-end argparse exit-code-2 on `--trial_portion 0.005` / `--eval_portion 0.005`. **Result: 17/17 PASSED in 1.33s** (2026-05-04).
- [x] `TestTypeParity` and `TestFlagNameParity` from `test_chain_consistency.py` still green after the type change. (`TestDefaultParity` is **pre-existing** RED on master c975df5 for `--max_rounds` and `--trial_portion` defaults — out of scope for this commit; tracked separately.)

**Definition of Done**: `--trial_portion 0.005` aborts at argparse time on both runners with a message that explains the segment-integrity floor. `certify_minimal.json` loads cleanly. The Phase 1.5 launch commands in §1.5.1 / §1.5.2 reference the new config.

**Out of Scope**: lowering the schema `ge=0.01` (decided 2026-05-04: keep — it's a hard statistical constraint, not just defensive). Fixing the pre-existing `TestDefaultParity` mismatches (`--max_rounds: 4 vs 3`, `--trial_portion: 0.05 vs 0.1`) — both predate this work.

---

### Commit 4.2: Component-coverage catch-all (`template_and_scaffolding`)

**Phase**: 1.5 (T1.2 remediation — surfaced by the first Gate T1 run on 2026-05-04).

**Scope**:
- `agent/llm_bridge.py` — in `_record_usage`, when the caller passed a non-empty `components` dict, augment it with a 10th key `template_and_scaffolding = max(0, chars.total - sum(values))` before constructing the row. Applied to proposer rows only (only call site that passes components).
- `agent/schemas/telemetry/token_usage.py` — update the `TokenUsageRow.components` field docstring to document the 10-key set.
- `nodes/ml_model_proposal_agent.py` — update `_audit_proposer_components` docstring noting the bridge augments the dict on write; the hook itself remains 9-key.
- `tests/unit/agent/llm_bridge/test_template_and_scaffolding.py` (new) — 5 tests pinning the contract: non-empty components get the 10th key with `chars.total - sum(other 9)`; empty / missing components are untouched (no 10th key on non-proposer rows); over-counting clamps to 0; exact-match yields 0; sum of all 10 keys equals `chars.total`.

**Tasks**:
- [x] Bridge edit: 11-line block injected into `_record_usage` between the `chars` construction and the `_TokenUsageRow` instantiation. `if components:` guards the empty-dict case so non-proposer rows stay schema-empty.
- [x] Schema docstring: lists all 10 keys, names which are reported by the hook vs injected by the bridge, references §1.5 / Commit 4.2.
- [x] Audit-hook docstring: cross-references the bridge augmentation so future readers don't expect the hook to emit 10 keys.
- [x] Unit tests for the bridge: 5/5 PASSED (2026-05-04). Existing `test_audit_components.py` (hook-level, 9 keys) and `test_record_usage.py` (no-components paths) both still green: 21/21 across the three files.

**Definition of Done**: every proposer row in a future Gate T1 run has 10 keys in `components`, and `chars.total - sum(components.values()) == 0` exactly (no tolerance). The audit hook's 9-key contract is unchanged; the 10th key is purely a write-time accounting layer.

**Out of Scope**: decomposing the template wrapper into named sub-components (`section_headers`, `task_instructions`, ...; was Option B in §1.5.1). Deferred until V12 baseline reports show the catch-all bucket is load-bearing enough to warrant the ~50–100 LOC refactor. Reverting `certify_minimal.json` — the file stays in the repo for future plumbing-only smoke runs but is no longer used by the formal Phase 1.5 gates (see §1.5.1 routing note).

---

### Phase 1.5 — Certification Gates T1 + T2 (mandatory before Commit 5)

Before Commit 5 starts, both **Gate T1 — Telemetry Integrity** and **Gate T2 — System
Stability** must be observed green on the real production graph. Specifications, launch
commands, and success metrics are in §1.5.1 and §1.5.2 above. Gate results are recorded
in those sub-sections; this anchor exists so the commit ledger reads chronologically.

**Gate ordering**: T1 → T2 → Commit 5. Either gate red → STOP and open a Commit 4.x
remediation before retrying. The V12 baseline numbers are not allowed to be quoted until
both gates are green.

---

### Commit 4.3: Chain-first runner instrumentation (runner unification)

**Phase**: 1.5 (post-T1/T2 hardening — surfaced by the V12 launch on 2026-05-04).

**Why this exists**: T0/T1/T2 all certified the bridge / workflow / audit-hook code under
`run_exploration_adaptive.py`. V12 production launches via `run_chain.sh` →
`sdsc_submission_scripts/run_one_iteration.py` (chain-first runner). The chain runner
was never instrumented with the audit context, so the V12 chains made real LLM calls
but wrote **zero rows** to `token_usage.jsonl`. The Phase 1.5 attestations were
correct-but-narrow: they certified one of the two production code paths. Commit 4.3
closes the parity gap and **deprecates the adaptive runner** so future drift is
impossible — there is now exactly one production runner.

**Scope**:
- `sdsc_submission_scripts/run_one_iteration.py` — add `--run_name` (chain-level run
  name, required); add `_resolve_chain_run_id(workspace, run_name)` sidecar helper at
  `{workspace}/.token_run_id` so the immutable run_id (§1.4.1) survives the subprocess
  boundary; add `_emit_token_iter_rollup` (chain-runner-adapted: cumulative seed read
  from JSONL since each iter is a fresh subprocess with no in-memory carry); add
  `LLMBridgeContextError` import + handler around `run_workflow(...)` that mirrors the
  adaptive runner's `[FATAL] ... → sys.exit(2)` contract; pass
  `chain_run_name=args.run_name, run_id=run_id` into `run_workflow(...)`.
- `tests/unit/scripts/test_chain_run_id_sidecar.py` (new) — 5 tests pinning the sidecar
  contract: fresh-workspace generation, idempotent re-read, run_name-mismatch ignored
  (sidecar wins), empty-sidecar treated as missing, workspace-creation tolerance.
- `docs/audit_and_optimize_token_usage_and_growth.md` — §1.5 adaptive-runner
  deprecation banner; §1.5.1 setup-block update (now uses `run_one_iteration.py` in a
  bash loop); new §1.5.1.1 (T1-Sanity placeholder) and §1.5.2 setup-block update.
  Historical T1/T2 attestations preserved unchanged as audit-trail proof.

**Design decisions (locked before code)**:
- **Q1 — run_id resolution across the subprocess boundary**: sidecar file at
  `{workspace}/.token_run_id`. Iter 1 generates and writes; iters 2+ read back. Naive
  per-process `_generate_run_id` would mint a fresh id every iter (different `pid +
  utc_ts`) and trip the bridge's run_id-immutability check on iter 2. The sidecar is
  the cheapest mechanism that preserves §1.4.1 without sharing parent-process state.
- **Q2 — `--run_name` as required argparse arg vs derived from `basename(workspace)`**:
  required arg. The adaptive runner has `--run_name` (required). Adding it to the
  chain runner gives explicit naming parity and avoids the silent failure mode where
  two distinct chains living in the same `/data/$user` end up with the same run_id
  because their workspace basenames collide.
- **Q3 — `_emit_token_iter_rollup` cumulative seed**: read from JSONL each call, summing
  rows where `iter < current_iter` (skipping `_iter_flush` markers). The adaptive
  runner threads cumulative through the in-process loop; the chain runner has no such
  loop. Recomputing from JSONL is O(rows) per call but the file is small (≤ ~50 rows
  per iter × 30 iters = 1.5k rows worst case). Cleaner than introducing a second
  sidecar for cumulative state.
- **Q4 — Adaptive runner kept for now or removed in this commit**: kept (deprecation
  banner only). Removal is a separate follow-up commit so this PR's diff stays
  minimally focused on the parity fix. The adaptive runner is no longer the canonical
  path but its file remains for one release window in case any external operator has
  an in-flight chain pinned to it.

**Tasks**:
- [x] Implement `_resolve_chain_run_id(workspace, run_name)` with sidecar persistence; format
      matches `run_exploration_adaptive._generate_run_id` (`{run_name}-{utc_ts}-{pid}`).
- [x] Implement `_emit_token_iter_rollup(workspace, iteration)` with JSONL-seeded cumulative;
      best-effort (`OSError` returns silently; malformed rows skipped).
- [x] Add `--run_name` (required) to the argparse; print `[TOKEN] chain_run_name = ...` and
      `[TOKEN] run_id = ...` at iter start.
- [x] Pass `chain_run_name=args.run_name, run_id=run_id` into `run_workflow(...)`.
- [x] Wrap `run_workflow(...)` in `try ... except LLMBridgeContextError` that writes a
      `crashed=True` manifest, prints `[FATAL] ...` to stderr, and `sys.exit(2)`.
- [x] Emit the rollup line after `write_manifest(...)` and before the status-branch exits.

**Pre-Commit Checklist**:
- [x] **Positive test (sidecar contract)**: `pytest tests/unit/scripts/test_chain_run_id_sidecar.py`
      — 5 tests, all green. **Result: 5/5 PASS** (2026-05-04).
- [x] **Regression — token bundle intact**: `pytest tests/unit/agent/llm_bridge/
      tests/integration/runner/test_token_log_iter_rollup.py` — Commit 4 contracts
      unaffected by the chain-runner port. **Result: 41/41 PASS** (2026-05-04).
- [x] **Smoke — argparse**: `.venv/bin/python sdsc_submission_scripts/run_one_iteration.py
      --help` parses without error and shows `--run_name` as required. **Result: PASS**.
- [x] **Sanity gate (1-iter chain runner under `openai_tiered_v1.json`)**:
      `token_usage.jsonl` exists, ≥4 rows, all rows' `run_id` match `{workspace}/.token_run_id`,
      every proposer row has 10-key Δ=0; one `[TOKEN_ITER] iter=01 ...` line in stdout
      whose `total_tok` equals the JSONL row sum. **Result: GREEN** (2026-05-05) —
      11 rows, M1+M2+M3 all PASS; run_id `certify_t1_sanity_0504-20260505T052619-1011326`.
      Detail in §1.5.1.1.

**Definition of Done**: V12 production chains write `token_usage.jsonl` with the same
schema and run_id-binding properties as the historical adaptive-runner gates. The
adaptive runner is marked deprecated. **Status (2026-05-05)**: **GREEN** — T1-Sanity
attested; V12 explore + exploit chains launched same day and confirmed writing JSONL
with sidecar-bound run_ids on iter 1.

**Out of Scope**: removing `run_exploration_adaptive.py` (separate follow-up); a Tier-2
integration test that drives `run_one_iteration.py` end-to-end through a pseudo
workflow (the V12 chain itself is the natural fixture, parallel to Commit 4's same
deferral pattern).

---

### Commit 4.3.1: Chain-wrapper `--run_name` parity (V12 launch hotfix)

**Phase**: 1.5 (immediate follow-up to Commit 4.3 — surfaced at the V12 launch dry-run audit).

**Why this exists**: Commit 4.3 made `--run_name` a *required* argparse flag in
`sdsc_submission_scripts/run_one_iteration.py` (so the chain-level run name pins the
sidecar and audit labels), but did **not** update the bash wrapper layer
(`sdsc_submission_scripts/_chain_common.sh`) that builds the per-iter Python invocation.
Result: any V12 launch using `run_chain.sh` would have crashed at argparse on iter 1
with `error: the following arguments are required: --run_name`, exit ≠ 0. Auto-resume
would see no manifest, decide iter 1 still pending, and re-launch the same broken
command for all 20 iterations — both V12 chains hung on iter 1 forever. Caught by the
pre-launch wrapper audit; never reached production.

**Scope**:
- `sdsc_submission_scripts/_chain_common.sh` (4 edits, +9 lines):
  - Add `RUN_NAME=""` to defaults block with comment explaining sidecar/audit role.
  - Add `--run_name) RUN_NAME="$2"; shift 2 ;;` parser case (alongside `--workspace`).
  - Extend the required-flag check: `--run_name` joins `--workspace` and `--seed_paths`
    in the canonical "Required:" stderr message; missing flag → `exit 1`.
  - Add `--run_name "$RUN_NAME"` to `APP_ARGS` in `build_app_args()`, immediately after
    `--workspace`, so it appears in every per-iter Python invocation.
- `tests/unit/scripts/test_chain_wrapper_run_name.py` (new, 3 tests, dry-run-driven):
  - `test_run_name_required_when_missing` — wrapper exits non-zero with canonical
    error when `--run_name` is omitted.
  - `test_run_name_threads_through_to_runner_args` — `--dry-run` output includes
    `--run_name <value>` verbatim; no transformation.
  - `test_run_name_distinct_from_workspace_basename` — pin: wrapper must not silently
    derive run_name from `basename(workspace)`. An operator's typo in `--run_name`
    must NOT be invisibly papered over by basename inheritance, otherwise audit logs
    would lie about chain identity.
- `tests/unit/scripts/test_chain_consistency.py` (1-line helper update): the existing
  `_run_dry()` smoke helper now passes `--run_name dryrun_test_chain` to satisfy the
  new required check; without this, 4 pre-existing dry-run smoke tests would have
  red-marked from the new wrapper-side enforcement.

**Tasks**:
- [x] Apply 4 wrapper edits.
- [x] Add 3 dry-run unit tests.
- [x] Update `_run_dry` helper in `test_chain_consistency.py`.
- [x] Verify both V12 dry-runs (`--mode lilab --dry-run` for explore + exploit) print
      `--run_name <value>` correctly threaded into the Python invocation.

**Pre-Commit Checklist**:
- [x] **Positive test (wrapper contract)**: `pytest tests/unit/scripts/test_chain_wrapper_run_name.py`
      — 3/3 PASS (2026-05-05).
- [x] **Regression — existing scripts unit tests intact**: `pytest tests/unit/scripts/`
      — 27 wrapper-related tests green (3 fresh + 24 pre-existing). The 3 pre-existing
      `test_chain_consistency.py` failures (`test_defaults_match`,
      `test_kwargs_match_modulo_documented_exemptions`, `test_every_three_way_flag_is_in_kwargs`)
      are unrelated drift carried from before this commit.
- [x] **Smoke — V12 launch dry-runs**: `bash run_chain.sh --mode lilab --dry-run ...`
      for both explore and exploit V12 commands prints `--run_name explore_novel_v12_0504`
      / `--run_name exploit_cnn_v12_0504` correctly inside the would-exec command.
- [x] **Live verification**: V12 chains launched 2026-05-05 in two screens
      (`siderius-v12-explore`, `siderius-v12-exploit`); both produced
      `{workspace}/.token_run_id` sidecars with the right run_name prefix and started
      writing `token_usage.jsonl` rows whose `run_id` field matches the sidecar exactly.

**Definition of Done**: the bash wrapper enforces `--run_name` symmetrically with
`run_one_iteration.py`'s argparse; V12 production launches succeed at iter 1 without
operator intervention; the chain-runner contract is end-to-end testable in the unit
layer (no live GPU required to catch wrapper drift). **Status (2026-05-05)**: GREEN
— landed as commit `609ac64`; V12 chains live.

**Out of Scope**: any further wrapper-layer plumbing beyond the `--run_name` thread.

---

### Commit 4.3.2: Attribution Audit — `template_and_scaffolding` 11× leak (Rev 7 — **CLOSED H1, Rev 8**)

**Phase**: 1 (amendment — gated Phase 2 entry; gate now released).
**§5 step**: 14b (new, between 14a Commit 4.3.1 and 15 Commit 5 follow-up).
**Status**: **CLOSED — H1 (Leak Found) confirmed 2026-05-05.** Forensic evidence below; remediation in Commit 4.3.3.

**Why this commit**: The Gate G1 baseline (Commit 5) reported `template_and_scaffolding` grew **11.00×** across iter 1 → iter 14 (50,422 → 554,774 chars). This bucket is *defined* as the catch-all residue: `chars.total − sum(other_9_named_components)`. By construction, growth in the catch-all means content is appearing in the prompt that none of the 9 named keys is capturing. Either:

  - **(H1) Attribution leak** — a real, measurable, *named* category of dynamic content (e.g. a new prompt section, a renamed block, an iter-by-iter accumulator) is being inserted into the prompt without being routed through one of the 9 component keys. In this case, our top-3 bloat report is *misattributing* the leak's growth, and the 10-key breakdown is unsafe to base Phase 2 surgery on.
  - **(H2) Structural call-count amplification** — the catch-all is genuinely fixed *per call* (~7.5K), but iter 14 has 40 proposer calls vs. iter 1's 20, so the *summed* catch-all doubles from call multiplication alone. In this case the 10-key breakdown is sound; the growth is real but explained.

These two hypotheses have different downstream consequences. **(H1) requires a code fix before Phase 2.** **(H2) requires only a denominator change in the report (per-call instead of summed).** Phase 2 cannot proceed until we know which one we are seeing.

**Scope** (read-only investigation + targeted fix if H1):
- `agent/llm_bridge.py:_record_usage` — the site that computes `template_and_scaffolding = chars.total − sum(other_9)`.
- `nodes/ml_model_proposal_agent.py:_audit_proposer_components` — the proposer-side hook that populates the 9 named keys (Commit 4.2).
- `agent/prompt_templates/proposal/*.md` — to enumerate every dynamic block the templates reference.
- The V12 `token_usage.jsonl` rows themselves — for forensic reconstruction.

**Tasks** (executed 2026-05-05, ad-hoc forensic scripts against V12 workspace, no production code touched):
- [x] **Per-call check**: same-call comparison of `proposer.proposing` (attempt 0, status ok) at iter 1 vs iter 14 — per-call `template_and_scaffolding` grew **8,630 → 92,790 chars (10.75×)**. Cross-label uniformity at iter 14: `proposing=92,790`, `comparison=91,176`, `causal_reasoning=92,608` (stdev within iter+label cell ≈ 0). H2 ruled out: per-call is not stable; this is per-call growth, not call multiplication. iter 14 ran 6 proposer calls, same as iter 1 — call count is constant.
- [x] **Forensic diff**: row-level component diff (single iter-1 vs single iter-14 `proposer.proposing` row, same call-site):

   | key                          | iter 1  | iter 14 |     Δ    | growth × |
   |------------------------------|--------:|--------:|---------:|---------:|
   | system_prompt                |   6,997 |   7,333 |     +336 |    1.05× |
   | candidates_markdown          |  13,296 |  20,517 |   +7,221 |    1.54× |
   | interpretation_json          |   4,162 |   8,380 |   +4,218 |    2.01× |
   | expert_context_block         |   1,246 |  30,278 |  +29,032 |   24.30× |
   | prior_stage_outputs          |  13,670 |  18,320 |   +4,650 |    1.34× |
   | **template_and_scaffolding** |   8,630 |  92,790 |  +84,160 |   10.75× |
   | **chars.total**              |  48,001 | 177,618 | +129,617 |    3.70× |

   Named keys captured +45,457 chars (35 % of total Δ). The catch-all swallowed +84,160 chars (65 % of total Δ). H1 confirmed.
- [x] **Source-side audit**: traced the proposer's `accumulated` dict construction (`nodes/ml_model_proposal_agent.py:1046-1066`) and the cleaned-dict JSON region of `_render_stage_user_prompt` (`:444-488`). Three input fields end up in the JSON region but were not audited as dedicated keys: `non_candidates_overview`, `existing_model_types`, the cleaned-candidates JSON residue. Of these, only `non_candidates_overview` carries dynamic per-iter growth at scale.
- [x] **Quantification**: reconstructed the proposer's `non_candidates_overview` from the on-disk `interpretation_iter_NN.json` (using the same logic at `:1010-1034` — pulling `description` from `model_descriptions`, `key_findings`/`bottlenecks`/`score_trend`/`strategy_assessment` from `model_knowledge_cache`, plus `score_summary` from `per_model_score_tables` via `build_score_summary_line`). Result: **15,440 chars (iter 1) → 109,991 chars (iter 14) — Δ +94,551 chars, 7.12× growth**. Δ ratio vs the +84,160 catch-all delta = **113.6 %** (upper-bound reconstruction; the actual list excludes `candidates ⊆ model_types`, slightly fewer entries than the proposed-only exclusion used in reconstruction).
- [x] **Verdict**: **H1 (Leak Found).** Mechanism: dynamic content from `model_knowledge_cache` (24 K → 275 K chars, 11.4×) and `model_descriptions` (6.7 K → 56 K chars, 8.4×) flows through `non_candidates_overview` into the prompt's JSON region without being routed through any of the 9 named audit keys.
- [x] **Remediation deferred to Commit 4.3.3** (audit-hook fix) and **Commit 6.3** (source-level cache dehydration). See those commits for implementation.

**Pre-Commit Checklist** (all satisfied by the forensic deliverable):
- [x] **Verdict recorded**: H1 confirmed with quantitative evidence (this section).
- [x] **No regression in existing tests**: forensic scripts were read-only; no production code modified in 4.3.2 itself.
- [x] **Re-baseline plan**: Commit 4.3.3 tests pin the new 11-key contract; a future re-run of `tools/build_token_baseline_report.py` post-4.3.3 will reflect the corrected attribution. (Re-running the tool against the *existing* V12 JSONL still shows the old 10-key shape — old rows were written before the audit hook gained the new key. New chains will report the trusted breakdown.)

**Definition of Done**: ✅ H1 explicitly chosen, evidence published in this section. Remediation lands in Commit 4.3.3. Phase 2 (Commits 6.1, 6.2, 6.3) is unblocked.

**Out of Scope**: changing what content goes *into* the proposer prompt (that is Phase 2's job — Commits 6.1, 6.2, 6.3); reducing the catch-all chars by template compression (that is Phase 3's job — Commit 11.1).

---

### Commit 4.3.3: Add `non_candidates_overview` as 11th audit key (Rev 8)

**Phase**: 1 (closes the 4.3.2 verdict — last commit before Phase 2 begins).
**§5 step**: 14c (new, immediately after 14b Commit 4.3.2).

**Why this commit**: Commit 4.3.2 isolated `non_candidates_overview` as the source of the false `template_and_scaffolding` 11× growth signal. With the leak named, the audit hook can route its chars to a dedicated component key — restoring the catch-all to its true wrapper baseline (~8 K chars per proposer call) and giving Phase 2 surgery a trustworthy per-component breakdown.

**Scope**:
- `nodes/ml_model_proposal_agent.py` — `_audit_proposer_components` gains a 4th content-key derivation block (`non_candidates_overview` → `len(json.dumps(value, default=str))`) and emits it as a new entry in the returned components dict.
- `tests/unit/agent/ml_model_proposal_agent/test_audit_components.py` — `_EXPECTED_KEYS` set updated from 9 to 10 entries; existing `test_audit_components_handles_empty_blocks` extended to assert the new key collapses to `len("[]") == 2` for empty/missing input; new dedicated regression test pins three properties (exact char count, non-overlap with `prior_stage_outputs`, 10-key contract).
- No bridge change: `LLMBridge._record_usage`'s catch-all formula (`chars.total - sum(content_components)`) is generic — adding an 11th content key auto-shrinks `template_and_scaffolding` without code changes.

**Tasks**:
- [x] Add `non_candidates_overview_chars = len(json.dumps(non_candidates_overview or [], default=str))` to `_audit_proposer_components`.
- [x] Add the new key to the returned `components` dict (placed between `interpretation_json` and `previous_failures` for consistency with the prompt assembly order).
- [x] Update the docstring's "9-key" / "10-key catch-all" wording to "10-key" / "11-key catch-all" and append a Commit 4.3.3 note explaining the V12-derived motivation.
- [x] Update `_EXPECTED_KEYS` in the test (and the test name `test_audit_components_returns_all_9_keys_with_full_payload` → `..._10_keys_...`).
- [x] Extend `test_audit_components_handles_empty_blocks`: empty/missing → 2 chars (`"[]"`).
- [x] Add `test_audit_components_non_candidates_overview_attributed_separately`: with a populated `non_candidates_overview` value, the new key matches `len(json.dumps(value, default=str))` exactly; the same chars are NOT also counted in `prior_stage_outputs` (non-overlap regression); the 10-key contract holds.

**Pre-Commit Checklist**:
- [x] **All tests pass**: `pytest tests/unit/agent/ml_model_proposal_agent/test_audit_components.py tests/unit/agent/llm_bridge/test_template_and_scaffolding.py` → **11/11 green** (6 audit-hook tests including the new regression + 5 catch-all tests verifying the bridge formula is unchanged).
- [x] **Catch-all baseline**: simulated 11-key view of the iter 14 `proposer.proposing` row from the V12 JSONL (using reconstructed `non_candidates_overview = 109,991`) shows the catch-all collapsing from 92,790 chars → ~0 (upper-bound reconstruction; expected real-world catch-all is the wrapper baseline ≈ 8 K chars per call, matching iter 1's measured 8,630).
- [x] **No regression in catch-all clamp**: the bridge's `max(0, ...)` clamp behavior is untouched; the new key flows through the same formula. The 5 existing `test_template_and_scaffolding.py` tests still pass.

**Definition of Done**: ✅ 11-key audit hook live; tests green; catch-all returns to fixed-template baseline; Phase 2 unblocked.

**Out of Scope**: re-processing the existing V12 JSONL to retroactively populate the new key (rows are immutable; new chains will write the 11-key shape from launch); changing what `non_candidates_overview` *contains* (that's Commit 6.3's job — source-level cache dehydration).

---

### Commit 4.3.4: Legacy Runner Deletion — retire `run_exploration_adaptive.py` (Rev 8.3 — Standalone Cleanup, sequenced after 6.1)

**Phase**: 1 cleanup (debt retirement, no behaviour change for production chains).
**§5 step**: 14d (new, after 14c Commit 4.3.3, but **landing order is post-6.1.a + post-6.1** — see Sequencing below).

**Why this commit**: the chain-first runner (`sdsc_submission_scripts/run_one_iteration.py` + `run_chain.sh`) is the production path. `run_exploration_adaptive.py` is the legacy in-process runner — kept around through Phase 6.8 for parity testing and ad-hoc dev runs. Two regimes coexisting created the doc-line-753-vs-1957 contradiction (Rev 8.3 changelog) by hiding which runner was authoritative. Eliminating the second regime is the durable fix: one runner, one set of carry-over semantics, one path to audit.

**Sequencing rationale (do NOT reorder)**:

1. Land **6.1.a** (Knowledge Restoration) first — touches `core/resume.py` + `run_one_iteration.py`; tests stay green because the legacy runner is unaffected.
2. Land **6.1** (Stability Filter dispatcher wiring + audit markers) — touches `nodes/result_interpretation_agent.py`; orthogonal to the runner.
3. Land **4.3.4** (this commit) — touches `run_exploration_adaptive.py` (delete) + 4 tests + 1 shell script. Bundling it earlier would conflate "fix subprocess amnesia" with "delete dead code"; doing it last means the cache-restoration code has stable parity-test coverage during its landing.

**Scope**:
- **Delete**: `run_exploration_adaptive.py` (repo root).
- **Update tests** (4 files):
   - `tests/unit/scripts/test_chain_consistency.py` — currently imports `parse_args` from `run_exploration_adaptive` to verify flag-set parity with `run_one_iteration.py`. With the legacy runner gone, the parity test loses its other side. **Decision**: convert to a single-runner schema test (assert `run_one_iteration.parse_args` accepts the canonical flag set) OR delete entirely if redundant against `test_chain_run_id_sidecar.py` + `test_portion_floor.py`. Decide during implementation.
   - `tests/unit/scripts/test_portion_floor.py` — imports `_portion_floor` from both runners for parity. After deletion, drop the adaptive-runner half; keep the `run_one_iteration.py` half.
   - `tests/integration/runner/test_token_log_iter_rollup.py` — imports `_emit_token_iter_rollup` from `run_exploration_adaptive`. The chain runner has its own rollup helper at `run_one_iteration.py:134` (commented as mirroring the adaptive version). Repoint the import; verify the rollup still emits the `[TOKEN_ITER]` line.
   - `tests/unit/runner/test_resilience.py` — Phase R resilience tests against the adaptive runner's top-level handler. The chain runner has a parallel handler at `run_one_iteration.py:891-900` (also commented as mirroring). Repoint the test target.
- **Update launch script** (1 file):
   - `sdsc_submission_scripts/launch_v11_v4.sh:54` — `RUNNER="$REPO_ROOT/run_exploration_adaptive.py"` → either delete the script entirely (if V11_v4 is no longer launched) OR repoint to a small wrapper that invokes `run_chain.sh`. Decide during implementation by checking last-launch date.
- **Update doc references** (~15 doc files contain non-load-bearing prose mentions): leave as-is unless they describe behaviour that no longer holds. The Rev 8.3 changelog already pins the new authoritative runner; older sections can carry historical context without correction.

**Tasks**:
- [ ] Delete `run_exploration_adaptive.py`.
- [ ] Triage `tests/unit/scripts/test_chain_consistency.py`: convert to single-runner contract test or delete (post-deletion the "parity" framing is meaningless).
- [ ] Update `tests/unit/scripts/test_portion_floor.py`: drop the `from run_exploration_adaptive import _portion_floor` block; keep the chain-runner side.
- [ ] Update `tests/integration/runner/test_token_log_iter_rollup.py`: repoint import to `sdsc_submission_scripts.run_one_iteration`.
- [ ] Update `tests/unit/runner/test_resilience.py`: change `RUNNER_PATH` to the chain runner; verify the resilience contract still holds (the chain runner's top-level handler is comment-pinned to mirror the adaptive one).
- [ ] Update or delete `sdsc_submission_scripts/launch_v11_v4.sh`: if obsolete, delete; if still useful, repoint to the chain.
- [ ] Run the full unit + integration test suite to confirm no orphaned import remains.

**Pre-Commit Checklist**:
- [ ] `grep -r "run_exploration_adaptive" --include="*.py" --include="*.sh"` returns **zero** code matches (doc matches OK as historical context).
- [ ] `pytest tests/unit/scripts/ tests/unit/runner/ tests/integration/runner/` is green.
- [ ] A 1-iter chain smoke launch via `run_chain.sh` (lilab mode, pseudo-training) reaches the iter-end manifest write — confirms the integration of the surviving runner is unbroken.
- [ ] Commit message links to the Rev 8.3 changelog block so the rationale is git-archaeologically discoverable.

**Definition of Done**: legacy runner deleted; all 4 test dependencies updated or removed; one production runner remains; future contributors cannot mistake which runner is authoritative.

**Out of Scope**: doc cleanup of historical mentions in `docs/phase68_*.md` and `docs/Consistent_growing_vocab_list.md` (those are versioned design docs — they record the regime that existed at their time of writing); migrating any in-flight V11_v4 chains (none active per 2026-05-05 ops state).

---

### Commit 5: V12 baseline run + Top-3 Bloat Report (Gate G1)

**Phase**: 1.
**§5 steps**: 10, 11.

**Scope**:
- `tools/build_token_baseline_report.py` (new — aggregates `token_usage.jsonl` into the report)
- `reports/v12_token_baseline.md` (new — output artifact)
- `reports/v12_top3_bloat.md` (new — output artifact)

**Tasks**:
- [x] Run a V12 chain (settings matching V11 baseline: `openai_tiered_v1.json` routing, 5+ iters minimum). The run is the deliverable, not a code change. **Done — `run_id explore_novel_v12_0504-20260505T070526-1028759`, 14 iters captured.**
- [x] Implement `tools/build_token_baseline_report.py` per the spec below.
- [x] Write `reports/v12_token_baseline.md`: real per-call token counts, per-iter trend, comparison against the §12-audit estimates.
- [x] Write `reports/v12_top3_bloat.md`: tables per §1.9.1; ends with one of the three §1.9.2 verdicts.

**`build_token_baseline_report.py` spec (Rev 6 finalized — adds USD cost tracking + bloat alert)**:

The tool reads one or more `{workspace}/token_usage.jsonl` files and emits per-label aggregates. Four behaviours are mandatory:

1. **Cost segmentation — Happy Path vs Recovery**. Each row carries `extra.attempt` (0 = first try, ≥1 = retry) and `extra.status` (`"ok"`, `"retry_quota"`, `"error"`, etc.). Split aggregates accordingly:
   - **Happy-Path-Cost**: rows where `extra.attempt == 0 AND extra.status == "ok"` — the cost of the iteration if everything goes right first time.
   - **Recovery-Cost**: all other rows (retries, validator-rejected proposals causing implementor repairs, quota-driven re-tries). Reported as a separate column so we can see what fraction of total spend is overhead from failures.

2. **Growth tracking — `tokens_per_iteration` and `growth_slope`**. For every distinct `label` (e.g. `proposer.comparison`, `interpretation.synthesis`, `tuner.planner`):
   - emit a per-iter row with `tokens_per_iteration = sum(prompt + completion)` for that label that iter,
   - compute `growth_slope` as `(tokens_at_iter_N - tokens_at_iter_1) / (N - 1)` once N ≥ 5,
   - flag any label whose slope > 0 with 95% confidence (simple linear regression, p < 0.05).

3. **USD cost tracking (Rev 6)**. Each row's USD cost is computed as `(tokens.prompt × rate_prompt + tokens.completion × rate_completion) / 1_000_000`. Default rates: `$10/1M prompt + $30/1M completion` (placeholder for gpt-5.4 production rates — *operator must verify and override via `--rate-prompt` and `--rate-completion` CLI flags before publishing the report*). The report emits:
   - per-iter total USD,
   - per-iter Happy-Path USD vs Recovery USD,
   - cumulative-to-date USD,
   - per-label USD growth slope (USD/iter), so dehydration impact can be priced directly.

4. **Alerting — two thresholds**.
   - `[BLOAT_ALERT]`: any iter whose total USD exceeds **$1.50**. This is the **post-dehydration target ceiling**, not a description of current state — at V12 rates every iter trips it (iter 1 ≈ $2.83, iter 13 ≈ $6.73). Quieting this alert is the explicit success criterion for Commits 6.1/6.2.
   - `[CONTEXT_EXPLOSION]`: any single row with `tokens.prompt > 50_000` (with iter, label, attempt, run_id). 50 K is the soft ceiling: above this, the model's own attention starts degrading (recall drops on dense-context benchmarks past ~64 K) and we are paying for capacity we cannot use.

   Both alerts are informational (exit 0), not fatal — they appear inline in the report at the top of the affected iter's section, and as a summary block at the end.

**Pre-Commit Checklist**:
- [x] **Positive test**: `python tools/build_token_baseline_report.py --workspace <v12-ws>` produces both reports without error; both render in markdown without broken tables. (`tests/unit/tools/test_token_baseline_report.py::test_end_to_end_positive_run`)
- [x] **Quantitative metric**: for the 5-iter run, the report shows a clean per-iter token sparkline; the linter on the JSONL returns 0 anomalies. (`tools/validate_token_usage_jsonl.py` against the V12 file → `[OK] clean (0 warnings)`; report contains all 14 iters of per-iter rows.)
- [x] **Segmentation test**: hand-craft a 3-row JSONL with one `attempt=0,status=ok` row and two `attempt=1` retry rows. Assert the tool reports Happy-Path-Cost = first row's tokens, Recovery-Cost = sum of the other two. (`test_segmentation_3_row_jsonl` + `test_happy_path_classifier`)
- [x] **USD test**: hand-craft a row with `prompt=100_000, completion=10_000`. With default rates, assert reported USD = `100000*10/1e6 + 10000*30/1e6 = $1.30` exactly (precision check; floating-point assertion to 4 decimals). (`test_usd_precision_to_four_decimals` + `test_usd_overrides_propagate`)
- [x] **Alert test (CONTEXT)**: hand-craft a row with `tokens.prompt = 60_000`. Assert the tool emits `[CONTEXT_EXPLOSION]` for that row and exits 0. (`test_context_explosion_alert_fires_above_threshold` + `test_context_explosion_silent_at_threshold`)
- [x] **Alert test (BLOAT)**: hand-craft a 1-iter JSONL whose total cost computes to $2.00 USD. Assert the tool emits `[BLOAT_ALERT]` for that iter and exits 0. Then hand-craft another at $1.20 — assert no `[BLOAT_ALERT]`. (`test_bloat_alert_fires_above_threshold` + `test_bloat_alert_silent_below_threshold`)
- [x] **Negative test**: run the report generator against a workspace whose `token_usage.jsonl` has been hand-corrupted (drop an `_iter_flush` marker). Assert the generator refuses to publish — emits "AUDIT LOG CORRUPTION DETECTED" and exits nonzero. We never publish numbers from a corrupted log. (`test_corrupted_jsonl_blocks_publication` + `test_skip_lint_bypasses_corruption_block`)
- [x] **Verdict recorded**: §1.9.2 verdict is written explicitly at the top of `reports/v12_top3_bloat.md` — Confirmed Proposer / Pivot Tuner / Pivot Other / Sanity Floor. (Top of file: `## Verdict: **Confirmed Proposer Hypothesis**`. `test_verdict_written_at_top_of_top3_report` pins the contract.)

**Definition of Done (Gate G1)**: real V12 baseline numbers exist; Happy-Path/Recovery segmentation is reported; per-label growth slopes are reported; per-iter USD costs are reported; both alert thresholds are evaluated; the verdict is recorded; the team has explicitly chosen one of the four branches (continue to Commit 6.1, pivot, or stop).

**Decision branch**:
- Verdict = "Confirmed Proposer Hypothesis" → proceed to Commit 6.
- Verdict = "Pivot Required — Tuner" or "Pivot Required — Other" → **STOP**. The current §2 design is shelved; a new design pass begins.
- Verdict = Sanity Floor tripped → **DEFER**. Re-run at iter 15 and re-evaluate.

**Out of Scope**: any Phase 2 work.

---

### Phase 2 — V12-Calibration Override (Rev 5)

The original Phase 2 ordering (Commits 6 → 12 below) assumed proposer-first dehydration. **V12 calibration data (§1.5.1.2) shows interpretation is the primary bleed**, so two new commits are inserted at the top of Phase 2 ahead of the original sequence:

- **Commit 6.1** — Interpretation Sliding Window (high priority — addresses the 9.3× growth)
- **Commit 6.2** — Proposer `prior_stage_outputs` Management (medium priority — addresses the 3.3× growth)

The original Commits 6-12 still apply but at lower priority. Commit 11.1 (Template Dehydration) is added at the end of Phase 2 to capture the 21% template share now that we know it is fixed cost, not growth.

---

### Commit 6.1.a: Knowledge Restoration — carry `model_knowledge_cache` across chain iters (Rev 8.3 — Critical Priority, precondition for 6.1)

**Phase**: 2 (precondition for Commit 6.1; lands first).
**§5 step**: 11.5 (new — between Commit 5 baseline and 12a Commit 6.1).

**Why this commit, why first**: Rev 8.3 audit established that `model_knowledge_cache` is persisted to disk (`interpretation_iter_NNN.json` already carries the full dict) but never restored across chain-subprocess boundaries. The Stability Filter (6.1) gates the cache-hit branch in `nodes/result_interpretation_agent.py:687-693`, which is the *only* code path that skips a per_model LLM call. With every chain subprocess starting on an empty cache, the filter would be dead code in production. 6.1.a closes the persistence gap so 6.1 has real targets to gate.

**The minimal fix shape** (verified against current code):

| # | File | Change |
|---|---|---|
| 1 | `core/resume.py` (`RestoredState` dataclass, L128-135) | Add 9th field: `model_knowledge_cache: Dict[str, Dict] = field(default_factory=dict)`. Update docstring with latest-wins semantics + cross-reference to `runtime_vocab` (also latest-wins). |
| 2 | `core/resume.py` (`load_latest_knowledge`, L262) | Either extend the existing function's return tuple OR add a sibling `load_latest_knowledge_cache(workspace, current_iter, committed_iters) -> Dict[str, Dict]`. **Decision: sibling loader.** Rationale — the existing function's return type is documented in its docstring + consumers; widening the tuple risks call-site drift. A sibling function with the same iter-walk + soft-fail policy (UserWarning on missing/malformed digest, skip + continue) keeps the surface explicit. |
| 3 | `core/resume.py` (`restore_prior_state`, L458) | After computing `runtime_vocab` + `accumulated_key_findings`, also compute `model_knowledge_cache` via the new loader and assign it onto the `RestoredState`. |
| 4 | `sdsc_submission_scripts/run_one_iteration.py` (the `run_workflow(...)` call, L830-890) | Add a 6th carry-over kwarg between L884 and L886: `restored_model_knowledge_cache=state.model_knowledge_cache,`. Group it with the other knowledge carry-over kwargs under the existing `# Cross-iter knowledge carry-over` comment. |
| 5 | `workflows/model_exploration.py` (`run_workflow` signature) | Accept the new kwarg with a default of `None` (so in-process callers and pseudo-mode tests don't need to thread it). Type: `Optional[Dict[str, Dict]] = None`. |
| 6 | `workflows/model_exploration.py:830` | Replace unconditional `model_knowledge_cache: dict = {}` with `model_knowledge_cache: dict = dict(restored_model_knowledge_cache) if restored_model_knowledge_cache else {}`. The `dict(...)` copy is defensive — the workflow mutates the dict in place at iter end, and we don't want to mutate the caller's reference. Add a `print()` log line mirroring the existing `Vocab restored from prior chain iters` line at L823, e.g. `Knowledge cache restored from prior chain iter: N entries`. |
| 7 | `workflows/model_exploration.py:1266-1274` | No change. The post-iter `_cap_knowledge_cache(max_entries=5)` call already runs against whatever the in-iter cache became. Cap continues to apply across the chain. |

**Scope** (files touched):
- `core/resume.py` (modify — `RestoredState` + new `load_latest_knowledge_cache` + `restore_prior_state` plumbing)
- `sdsc_submission_scripts/run_one_iteration.py` (modify — add 6th carry-over kwarg)
- `workflows/model_exploration.py` (modify — accept kwarg, replace L830 init)
- `tests/unit/core/test_resume.py` (modify — add cache-restoration cases, parallel to existing runtime_vocab cases)
- `tests/unit/workflows/test_model_exploration.py` OR a dedicated new file (add a 2-iter pseudo-chain cache-roundtrip test)

**Tasks**:
- [ ] **T1 — Schema**: add `model_knowledge_cache` field to `RestoredState`. Verify the field's type matches `InterpretationOutput.model_knowledge_cache` (also `Dict[str, Dict]`). Update the dataclass docstring.
- [ ] **T2 — Loader**: implement `load_latest_knowledge_cache(workspace, current_iter, committed_iters)` in `core/resume.py`. Walks `committed_iters` ascending; reads each iter's `interpretation_iter_NNN.json`; returns the **latest parseable digest's** `model_knowledge_cache` (latest-wins, mirroring `runtime_vocab`). Soft-fail on missing/malformed digest (UserWarning, skip).
- [ ] **T3 — `restore_prior_state` plumbing**: call the new loader after the existing `load_latest_knowledge` invocation, assign to `state.model_knowledge_cache`. Confirm `current_iter == 1` short-circuits to empty dict (mirrors the existing `runtime_vocab` short-circuit at L291).
- [ ] **T4 — Runner kwarg**: add `restored_model_knowledge_cache=state.model_knowledge_cache` to the `run_workflow(...)` call in `run_one_iteration.py:830-890`. Place it in the "Cross-iter knowledge carry-over" group adjacent to `restored_runtime_vocab`.
- [ ] **T5 — Workflow signature + init**: accept `restored_model_knowledge_cache` in `run_workflow`'s signature; replace the L830 init; emit a one-line log message on non-empty restore.
- [ ] **T6 — Unit test (resume)**: in `tests/unit/core/test_resume.py`, add a test that synthesises a 2-iter workspace where iter_001/interpretation has `model_knowledge_cache = {"punet": {...}, "wavenet": {...}}`, calls `restore_prior_state(workspace, current_iter=2, ...)`, asserts `state.model_knowledge_cache` has both keys with verbatim values.
- [ ] **T7 — Unit test (workflow plumbing)**: a pseudo-mode 2-iter chain test where iter 1 produces a non-empty `model_knowledge_cache`, the chain restarts (simulated subprocess boundary), iter 2 enters `run_workflow` with `restored_model_knowledge_cache=...`, and the test asserts the iter-2 `InterpretationInput.model_knowledge_cache` has the iter-1 entries before the per_model loop runs. Reuses the existing `tests/integration/agent/test_token_usage_pseudo_smoke.py` harness if practical.
- [ ] **T8 — Doc tick**: mark this task list complete in §8, fold the empirical V12 disk-evidence numbers into the final commit message.

**Pre-Commit Checklist**:
- [ ] **Soft-fail policy**: corrupted iter_001 digest (e.g. truncated JSON) → UserWarning emitted, restoration continues with empty cache. (Test: synthesise `interpretation_iter_001.json` with a syntax error; expect warning + `state.model_knowledge_cache == {}`.)
- [ ] **Latest-wins semantics**: 3-iter workspace where iter_001 has `{a:1}`, iter_002 has `{b:2}`, iter_003 has `{c:3}`; `restore_prior_state(current_iter=4)` returns `{c:3}` (NOT `{a:1, b:2, c:3}`). This matches `runtime_vocab` behaviour and is correct because each digest already carries cumulative state via `_cap_knowledge_cache`'s 5-entry rolling window.
- [ ] **Empty cache short-circuit**: `current_iter=1` → `state.model_knowledge_cache == {}`. Mirrors the runtime_vocab short-circuit at `core/resume.py:291`.
- [ ] **Workflow integration**: 2-iter pseudo-chain — iter 1 writes non-empty cache to disk, iter 2 (simulated subprocess) reads it via the new kwarg and the L830 init reflects it. Assert iter-2's `interp_input.model_knowledge_cache` has iter-1 keys.
- [ ] **No regression**: full `tests/unit/core/test_resume.py` + `tests/unit/workflows/test_model_exploration.py` + `tests/unit/scripts/test_chain_consistency.py` pass. The existing 5 carry-over kwargs remain unchanged in shape.

**Definition of Done**: in a 2-iter pseudo-run on a chain workspace, iter 2's `nodes/result_interpretation_agent.py:687-693` cache-hit branch fires for at least one model (i.e. `inp.model_knowledge_cache` is non-empty at iter-2 entry). Once Commit 6.1 lands on top, the `interpretation.per_model_skipped` audit markers will appear in the production JSONL — verifiable in the next 5-iter chain re-baseline.

**Out of Scope**: changing the cache *update* mechanism (that is Commit 6.3 — the Knowledge Accumulator); changing the eviction cap (`_cap_knowledge_cache(max_entries=5)` is unchanged); modifying the digest schema (`InterpretationOutput.model_knowledge_cache` already has the right shape and is being written by every iter).

---

### Commit 6.1: Interpretation Call-on-Demand — Sliding Window + Stability Filter (Rev 7 — Critical Priority, expanded; Rev 8.3 — gated on 6.1.a)

**Phase**: 2 (gated on Commit 4.3.2 closing AND Commit 6.1.a landing).
**§5 step**: 12a.

> **Rev 8.3 status note (2026-05-05)**: The helper-layer (T1-T3) and schema (T5) tasks below are already complete (commits `6190e32` + `d3c6eef`). The remaining wiring (T4) and end-to-end tests (T6) **require Commit 6.1.a (Knowledge Restoration) to land first** — without it, the cache-hit branch this commit gates is unreachable in production chains. Once 6.1.a is in, resume here with T4 + T6 + T7 unchanged. The 6.1 spec itself does not change; only its production-effectiveness is unlocked by 6.1.a.

**Why this commit, why critical**: V12 explore data exposed **two distinct linear-growth axes** in the interpretation agent. Both must be clamped here because they share the same source of state (`model_knowledge_cache`):

1. **Synthesis prompt-size growth (Rev 5 finding)**: `interpretation.synthesis` grew 4.7 K → 40 K tokens over iters 1–13 (8.7×). Driver: the synthesis prompt concatenates *all* entries in `model_knowledge_cache` verbatim — no window cap.
2. **per_model call-count growth (Rev 7 finding)**: `interpretation.per_model` grew **2 calls/iter (iter 1) → 12 calls/iter (iter 14)**. Slope **+5,947 tok/iter (R²=0.98)** — nearly 2× the synthesis slope. Driver: the agent currently issues a fresh LLM summary call for *every* `model_type` ever proposed, on every iter. Stable historical models (no new training rounds, no score change) are re-summarized every iter against unchanged data — pure waste.

The Rev 5 spec only addressed (1). Rev 7 expands the commit to also address (2) — the per_model call multiplication. **Both fixes share the active-model selection policy**, so they belong together: deciding which models are "active enough to need attention" gates both whether we re-call per_model and whether we keep their entry expanded in synthesis.

**Scope**:
- `nodes/interpretation_helpers.py` (modify — add `select_active_models`, `compress_model_summary`, `should_recall_per_model`)
- `nodes/result_interpretation_agent.py` (modify — synthesis assembly reads compressed entries for non-active models; per_model dispatcher consults `should_recall_per_model` before issuing each call)
- `tests/unit/agent/result_interpretation_agent/test_sliding_window.py` (new — covers both axes)
- `tests/unit/agent/result_interpretation_agent/test_stability_filter.py` (new — Rev 7)

**Tasks**:
- [x] **Active-model policy** (shared by synthesis + per_model): "Top-K + Last-N + Delta-Δ". Keep full detail / re-call per_model for the union of:
   - Top K models by `best_denoising_score` ever seen (default K=3),
   - Last N models proposed by recency (default N=2),
   - any model whose `best_denoising_score` changed in the current iter beyond a threshold Δ (default `abs(Δ) ≥ 0.05` in normalized score units).
   All other models are "stable" — pulled from cache as-is, no LLM call.
   *Implementation: `select_active_models()` at `nodes/interpretation_helpers.py:503`. Negative thresholds rejected; ties broken by `(-score, model_type)` lex order; models with `best_denoising_score=None` excluded from Top-K ranking.*
- [x] **Sliding-window compression (axis 1)**: implement `compress_model_summary(entry) -> dict` returning `{model_type, best_score, n_rounds, one_line_takeaway}`. Takeaway field extracted *deterministically* from the existing cached summary's `key_finding` — no fresh LLM call. Target ≤ 200 chars per model.
   *Implementation: `compress_model_summary()` at `nodes/interpretation_helpers.py:584`. Takeaway extracted from `key_findings[0]` → `best_config_analysis` → "(no cached takeaway)" placeholder; truncates with `…` ellipsis at `max_takeaway_chars-1`.*
- [x] **Stability Filter (axis 2)**: implement `should_recall_per_model(model_type, cache_entry, current_iter_records) -> bool`. Returns `True` iff the model is in the active set AND has either (a) at least one new training record in the current iter, or (b) a score delta ≥ Δ. Stable models return `False` — the dispatcher pulls the previous cache entry verbatim and skips the LLM call. The skip path emits a single `_iter_flush`-style audit row with `label="interpretation.per_model_skipped"`, `tokens=None`, `extra={"reason": "stable", "cached_iter": <iter>}` so the audit log preserves the count of skipped calls (we want to *measure* the savings, not hide them).
   *Helper implementation: `should_recall_per_model()` at `nodes/interpretation_helpers.py:638`. Decision tree: cache miss → always True; not active → False; active + new rounds OR Δ ≥ threshold → True; active + no new evidence → False. **Audit marker emission still pending** — wired in T4 (synthesis assembly + per_model dispatcher).*
- [ ] **Synthesis-prompt assembly** (axis 1): replace "all entries verbatim" with active-full + stable-compressed. Add a single line at the top of the historical block: `"[N older architectures compressed for context budget — see {workspace}/iter_{i}/interpretation.json for full detail]"`.
- [ ] **per_model dispatcher** (axis 2): consult `should_recall_per_model` before each LLM call; on skip, write the audit marker and reuse the previous cache entry. Total per_model LLM calls per iter must equal `|active_set|`, not `|model_knowledge_cache|`.
- [x] **Configurable**: K, N, Δ all live on `InterpretationInput` (no new CLI flag); defaults documented in the schema.
   *Implementation: `active_model_top_k`, `active_model_last_n`, `active_model_score_delta` fields added to `agent/schemas/interpretation.py` `InterpretationInput`. Defaults K=3, N=2, Δ=0.05 match the design spec; all three are `ge=0` validated. **Doc-correction note**: Rev 7 phrasing said "LLM-config schema" — that was incorrect. `WorkflowLLMConfig.interpret` is `NodeLLMConfig` (provider+model only) and is never read by the interpretation agent; the agent's behavioural knobs belong on the input schema. Tests: 6 new cases in `tests/unit/agent/result_interpretation_agent/test_interpretation_schemas.py::TestInterpretationInput` covering defaults, custom values, zero-edge, and negative-rejection on all three fields. All pass.*

**Pre-Commit Checklist**:
- [x] **Active-set test**: `test_active_set_top_k_plus_last_n_plus_delta` — given a 7-model cache with synthetic scores, recency, and one model with a current-iter score delta ≥ Δ, the active set is exactly `top3 ∪ last2 ∪ {delta_model}` (deduplicated).
   *Result: PASSED. File `tests/unit/agent/result_interpretation_agent/test_stability_filter.py::TestSelectActiveModels` — 9 tests covering headline 7-model case, None-score exclusion, Last-N truncation, Delta-with-no-prior path, below/at/above threshold boundaries, lex-tiebreak determinism, empty-input edge, and negative-threshold rejection. All 9 pass. Boundary test uses 0.5 (exactly representable) to avoid float-imprecision false negatives.*
- [x] **Compression test (axis 1)**: `test_compress_preserves_key_finding` — `compress_model_summary` extracts the original `key_finding` verbatim and emits ≤ 200 chars.
   *Result: PASSED. File `tests/unit/agent/result_interpretation_agent/test_stability_filter.py::TestCompressModelSummary` — 6 tests covering verbatim preservation, ellipsis truncation, fallback to `best_config_analysis`, placeholder when nothing available, total-serialised-length-under-200 budget check, and `max_takeaway_chars=0` rejection. All 6 pass.*
- [x] **Stability Filter test (axis 2 — helper-level)**: `test_stability_filter_skips_stable_models` — given a 7-model cache where 5 models are stable (no new records, no score delta) and 2 are active, assert `should_recall_per_model` returns `False` for the 5 and `True` for the 2.
   *Result: PASSED. File `tests/unit/agent/result_interpretation_agent/test_stability_filter.py::TestShouldRecallPerModel` — 7 tests covering cache-miss-always-recalls, 5/2 split (the headline 7-model assertion), active-with-more-rounds, active-with-Δ, active-with-no-new-evidence, inactive-with-new-data-still-skips (Stability Filter respects active gate), and below-threshold-Δ-skips. All 7 pass. **The audit-log marker assertion is deferred** — markers are emitted by the dispatcher (T4 wiring), not the helper, so it lives in the T4 audit-log test below.*
- [ ] **Synthesis-prompt size regression test (axis 1)**: with a synthetic 13-model cache (mimicking iter 13 of explore V12), the new synthesis prompt is **< 15 K chars** (vs. V12 baseline ~40 K). Quantify the compression ratio in the test assertion message.
- [ ] **per_model call-count regression test (axis 2)**: with a synthetic 12-model cache (mimicking iter 14 of explore V12) where 9 models are stable, assert the agent issues exactly **3 LLM calls** for that iter (active set size), not 12. Reuses the existing pseudo-LLM harness.
- [ ] **Behavioural test**: synthesis output still mentions every model_type at least once (active = full, compressed = one-liner) — no model is silently dropped from the prompt.
- [ ] **Audit-log test**: skipped per_model calls produce countable marker rows (so the savings are measurable in `tools/build_token_baseline_report.py`'s output).

**Definition of Done (Gate G1.5)**: re-run a 5-iter chain post-implementation; both axes must clamp:
- `interpretation.synthesis` `tokens.prompt` slope drops from V12's ~3 K/iter to **< 500 tokens/iter** between iter 3 and iter 5.
- `interpretation.per_model` summed prompt tokens per iter drops from V12's +5,947 tok/iter slope to **< 1 K tok/iter** (sub-linear; ideally flat).
The new chain's `build_token_baseline_report.py` output replaces V12 as the Phase 2 baseline. Both slopes are reported in `reports/v12post_dehydration_baseline.md`.

**Out of Scope**: model_knowledge_cache *eviction* (we keep the full cache for forensic recovery; only the *prompt assembly* and *call dispatch* read a windowed view); the 21% template tax on `proposer.comparison` (Phase 3, Commit 11.1).

---

### Commit 6.2: Proposer `prior_stage_outputs` Management (Rev 5 — V12-driven, medium priority)

**Phase**: 2.
**§5 step**: 12b (new).

**Why this commit, why second**: V12 data shows proposer grew 68 K → 225 K (3.3×) over 13 iters. Component breakdown of the iter-1 vs iter-late `proposer.proposing` row indicates `prior_stage_outputs` is the dominant growth contributor — at iter 1 it's 13 K chars, by iter 13 it dominates the per-call assembly. The other proposer components are largely flat: `system_prompt` ~7 K (fixed), `vocab_block` ~3.5 K (slow), `template_and_scaffolding` ~8 K (fixed).

**Scope**:
- `nodes/ml_model_proposal_agent.py` (modify — `prior_stage_outputs` assembly)
- `tests/unit/agent/proposal/test_prior_stage_truncation.py` (new)

**Tasks**:
- [ ] Audit what `prior_stage_outputs` actually contains today (history of which prior stage's outputs concatenated how). Document in the commit message — we may discover it's already wrong, not just bloated.
- [ ] Apply a max-chars truncation per stage entry (default 2 K chars per prior stage, configurable). Trim from the middle (keep first 1 K and last 1 K), insert `[... N chars elided ...]` marker. Preserves head + tail, both of which are typically high signal.
- [ ] Alternative consideration (decide before implementation): semantic compression via a deterministic extractor (e.g., keep only the JSON keys, not values, for prior-stage outputs that are large dicts). Lower risk than LLM-based compression but loses some signal.
- [ ] Pin the policy in the LLM-config schema; do not hardcode the threshold.

**Pre-Commit Checklist**:
- [ ] **Positive test**: 4 K input → 2 K output, with first-1 K and last-1 K verbatim and the `[... 2000 chars elided ...]` marker between.
- [ ] **Idempotence test**: applying truncation to an already-truncated string is a no-op.
- [ ] **Quantitative metric**: against a synthetic iter-13-shape proposer assembly, `proposer.proposing.tokens.prompt` drops by ≥ 30%. (Don't promise a flat curve here — proposer growth has multiple sources; we're targeting the largest one.)

**Definition of Done (Gate G1.5b)**: re-run a 5-iter chain post-implementation; verify `proposer.proposing` token growth slope drops by ≥ 30% relative to V12 baseline.

**Out of Scope**: `vocab_block` compression (separate concern, addressed in Phase 3 if vocab keeps growing); `candidates_markdown` compression (already bounded by gate-block design).

---

### Commit 6.3: Knowledge Accumulator Refactor — Cache Update Path + Consolidated Schema (Rev 8.2 — Critical Priority, promoted from Rev 8)

**Phase**: 2 (sequenced after Commit 6.1; depends on 6.1's `should_recall_per_model` decision so only active-model entries flow through the merge path).
**§5 step**: 12c (refactor scope, same step number).

**Why this commit (Rev 8.2 promotion)**: a code audit on 2026-05-05 (documented in the Rev 8.2 changelog) found the Rev 8 spec assumed accumulation that the production code does not implement. `nodes/result_interpretation_agent.py:687-693` shows the cache-hit branch copies the prior iter's entry verbatim and skips the LLM call entirely — once a `model_type` is summarised, its findings are *frozen*. The Rev 8 "Merge within `(model_type, field)` bucket" algorithm presupposes a list grew across iters; under current code there is nothing to merge. Two leaks (`expert_context_block` 24× and `non_candidates_overview` 7×) still share one root (`model_knowledge_cache` 11.4×, `model_descriptions` 8.4×), but the *fix* now requires changing the cache update mechanism, not just adding a consolidator at the injection point.

| downstream block            | iter 1 → iter 14 chars | growth | upstream source                         |
|-----------------------------|-----------------------:|-------:|------------------------------------------|
| `expert_context_block`      |          7.5 K → 181 K |   24×  | `model_knowledge_cache` (LLM text fields) + curated text |
| `non_candidates_overview`   |           15 K → 110 K |    7×  | `model_descriptions` + `model_knowledge_cache` (LLM text fields) |

The Rev 8.2 reframe: **the cache itself must become a cumulative ledger.** A fatal lesson learned at iter 2 must survive even if the same architecture is re-tested and re-summarised at iter 20 — the iter-20 finding *enriches* the iter-2 entry, never overwrites it. This is what an evolutionary system needs; truncation alone (the rejected Option B) bounds size but does not preserve cumulative wisdom.

**Scope** (Rev 8.2 — refactor, not just consolidator):

1. **Cache update path refactor** in `nodes/result_interpretation_agent.py`: replace the verbatim-copy cache-hit branch (L687-693) with a *light merge* path. On cache hit for an active model (per 6.1's `should_recall_per_model`), the agent calls the LLM, then merges the new findings into the cached entry rather than overwriting. On cache hit for a stable model (6.1 says skip), the verbatim-copy behaviour is preserved (no extra LLM call, no merge).
2. **New consolidated schema** in `agent/schemas/cache_entry.py` (Pydantic). Reconciles the 8 existing LLM text fields with the accumulator semantics. Field mapping spec under "Tasks" below.
3. **New `agent/cache_consolidator.py`** — deterministic Merge & Prune over the consolidated entry. Pure function; no LLM call. Used by the cache update path on every merge.
4. **New `tests/unit/agent/result_interpretation_agent/test_cache_consolidator.py`** — schema validation + merge + prune + error-signature preservation tests.
5. **`nodes/result_interpretation_agent.py` integration test (Tier 1)** — simulated 14-iter chain, asserts cache stays bounded and findings accumulate (a finding planted at iter 2 is still cited at iter 14).
6. **No producer changes** to `expert_context_block` or `non_candidates_overview` — they read from the now-bounded cache and shrink as a side effect (verified in the bounded-size test).

**Tasks**:

- [ ] **T1 — Locate cache-maintenance site (verified during audit)**: cache hit / miss branches at `nodes/result_interpretation_agent.py:687-738`; cache eviction at `workflows/model_exploration.py:369-392` (`_cap_knowledge_cache`, currently caps to 5 entries by best_score + current). Document in commit message.

- [ ] **T2 — Field reconciliation between live cache and accumulator schema**: the 8 existing LLM text fields (from `PER_MODEL_SYSTEM_PROMPT` at `result_interpretation_agent.py:36-116`) map onto the new schema as follows:

  | live field                   | accumulator type           | rationale                                                    |
  |------------------------------|----------------------------|--------------------------------------------------------------|
  | `key_findings: list[str]`    | `list[ConsolidatedFinding]`| ranked observations — natural list-of-statements accumulator |
  | `bottlenecks: list[str]`     | `list[ConsolidatedFinding]`| root causes — accumulator                                    |
  | `best_config_analysis: str`  | `ConsolidatedNarrative`    | single narrative; merged by *replacement-with-history* (see policy below) |
  | `score_trend: str`           | `ConsolidatedNarrative`    | single narrative; replacement-with-history                   |
  | `per_file_analysis: str`     | `ConsolidatedNarrative`    | single narrative; replacement-with-history                   |
  | `data_sensitivity: str`      | `ConsolidatedNarrative`    | single narrative; replacement-with-history                   |
  | `efficiency_assessment: str` | `ConsolidatedNarrative`    | single narrative; replacement-with-history                   |
  | `strategy_assessment: str`   | `ConsolidatedNarrative`    | single narrative; replacement-with-history                   |
  | (new) `error_signatures`     | `list[ErrorSignature]`     | Commit 6 schema; load-bearing for Gate G3 — set-merge, no cap|
  | (preserved) `_stats: dict`   | `_stats: dict`             | numerical, untouched by consolidator                         |

  **Schema** (Pydantic):
  ```python
  class ConsolidatedFinding(BaseModel):
      statement: str  # non-empty, max 500 chars
      evidence_iters: list[int]  # union grows across iters
      strength: Literal["weak", "moderate", "strong"]

  class ConsolidatedNarrative(BaseModel):
      latest: str  # current iter's narrative (max 800 chars)
      history: list[tuple[int, str]]  # [(iter_index, prior_narrative), ...] — capped to last 3

  class CacheEntry(BaseModel):
      model_type: str
      key_findings: list[ConsolidatedFinding]
      bottlenecks: list[ConsolidatedFinding]
      best_config_analysis: ConsolidatedNarrative
      score_trend: ConsolidatedNarrative
      per_file_analysis: ConsolidatedNarrative
      data_sensitivity: ConsolidatedNarrative
      efficiency_assessment: ConsolidatedNarrative
      strategy_assessment: ConsolidatedNarrative
      error_signatures: list[ErrorSignature]
      stats: dict  # _stats passthrough; not consolidated
  ```

  No new LLM contract — the LLM still emits the 8 flat string/list fields it does today (`PER_MODEL_SYSTEM_PROMPT` unchanged). The consolidator is the layer that adapts the LLM's flat output into the accumulator entry.

- [ ] **T3 — Cache update path refactor** (`nodes/result_interpretation_agent.py:687-738`): the cache-hit branch becomes a *decision point*:

  ```python
  for mt in effective_types:
      if mt in inp.model_knowledge_cache:
          if not should_recall_per_model(mt, ...):  # 6.1 stability filter
              # Stable: verbatim copy, no LLM call (preserved behaviour)
              model_knowledge_cache[mt] = inp.model_knowledge_cache[mt]
              continue
          # Active cache hit: re-call LLM, merge into cached entry
          new_response = self.bridge.generate(...)
          merged = consolidate(
              prior=CacheEntry.parse(inp.model_knowledge_cache[mt]),
              new_llm_output=new_response,
              new_stats=...,
              current_iter=current_iter,
          )
          model_knowledge_cache[mt] = merged.model_dump()
          continue
      # Cache miss: build initial entry from single LLM call (existing behaviour)
      ...
  ```

  The merge happens **inside the cache update path**, gated on the active-model decision. A model that never enters the active set is never re-called, never merged — its frozen entry is fine.

- [ ] **T4 — Merge & Prune policy** (deterministic, no LLM call, in `agent/cache_consolidator.py`):
  - **List fields** (`key_findings`, `bottlenecks`):
    - Merge: new findings whose normalized text matches a prior finding (`difflib.SequenceMatcher.ratio() ≥ 0.7` OR explicit key-noun overlap) collapse into the prior; the merged finding unions `evidence_iters` and takes the higher `strength`.
    - Prune to **≤ 8 per field per model_type**, ranked by `(strength, len(evidence_iters), recency)`. Pruned items archived to `{workspace}/iter_{i}/cache_archive_{model_type}.json`.
  - **Narrative fields** (`best_config_analysis`, `score_trend`, `per_file_analysis`, `data_sensitivity`, `efficiency_assessment`, `strategy_assessment`):
    - Merge by **replacement-with-history**: `latest = new_response[field]`; the prior `latest` is appended to `history` with the prior iter index. `history` capped to last 3 entries (older entries archived).
    - This shape preserves "what the agent thought *now*" while still letting downstream consumers see "what changed" without paying for full redundancy. Each narrative bounded ≤ 800 chars latest + 3 × 200 chars history = **≤ 1.4 K per field**.
  - **Error signatures** (`error_signatures`):
    - Set-merge by `(failure_class, top_user_frame, error_type)` tuple. Duplicates union `evidence_iters`. **NO numerical cap** — Gate G3 (§2.9 Trap Test) requires every distinct signature to survive forever.
  - **Numerical stats** (`stats`): passthrough, untouched.

  Implementation: separate `_merge_list_field`, `_merge_narrative_field`, `_dedupe_error_signatures` paths so the asymmetric semantics are explicit and individually testable.

- [ ] **T5 — Hook into the cache-update path** at the active-cache-hit branch (T3). All persistence (workspace JSON, downstream prompt assembly) reads from the consolidated entry. Verify by running existing interpretation tests — no schema break for stable-model copy or initial-miss paths.

- [ ] **T6 — No producer changes** for `expert_context_block` or `non_candidates_overview`. They continue to read from the cache. Confirm in the bounded-size test below that both downstream blocks shrink as a side effect (no per-block consolidator needed).

**Performance Guard — Error Signature Preservation (Gate G3)** ⚠️:

> The consolidator **must NOT collapse or rank-prune unique error signatures**. Each `ErrorSignature` (Commit 6 schema: `failure_class`, `last_frames`, `short_message`) is keyed by the tuple `(failure_class, top_user_frame, error_type)`. The consolidator treats `error_signatures` as a SET — duplicates (same key tuple) merge by unioning `evidence_iters`, but distinct signatures are NEVER pruned, regardless of the per-field cap on text findings.
>
> **Why**: Gate G3 (§2.9 Trap Test) plants a fatal flaw in iter-2 ledger and asserts the proposer cites it correctly at iter 10. Under the Rev 8.2 accumulator the iter-2 signature must merge correctly with iter-10 evidence (set-union, not replacement). The 8-cap on text findings is fine — those are reasoning summaries, redundant by nature. Error signatures are forensic primary sources; their loss is information loss.
>
> **Implementation**: a separate `_dedupe_error_signatures` path (set-merge only, no cap) distinct from `_merge_list_field` (capped) and `_merge_narrative_field` (replacement-with-history). The behavioural tests (below) pin this distinction.

**Pre-Commit Checklist**:

- [ ] **Schema test**: invalid `CacheEntry` / `ConsolidatedFinding` / `ConsolidatedNarrative` / `ErrorSignature` (missing fields, empty statement, unknown `failure_class`, narrative `latest` over 800 chars) rejected by Pydantic with a useful error.
- [ ] **Field-reconciliation test**: a fresh LLM response (the 8 flat fields from `PER_MODEL_SYSTEM_PROMPT`) parses correctly into a `CacheEntry` via the consolidator's `from_initial_llm_response()` constructor. All 8 fields populated; `error_signatures` defaults to `[]`; `_stats` passthrough.
- [ ] **List-merge test (text-list fields)**: two `key_findings` entries across iters — "ridge near 50 Hz dominates" (iter 2) and "the 50 Hz ridge is the dominant feature" (iter 5) — merge into one with `evidence_iters=[2,5]`.
- [ ] **List-prune test**: a model with 30 accumulated `key_findings` across simulated iters prunes to ≤ 8 outputs; weak findings dropped first; remaining ranked by `(strength, len(evidence_iters), recency)`. Pruned items present in archive file.
- [ ] **Narrative-merge test**: a `score_trend` field updated across iters 1, 4, 7, 10 — the iter-10 merged entry has `latest` = iter-10 text and `history` = `[(7, ...), (4, ...), (1, ...)]` (capped to last 3, oldest dropped).
- [ ] **Error-signature preservation test (Gate G3 prerequisite)**: input cache with 12 distinct error signatures (different `failure_class`/`top_user_frame` tuples) across one `model_type` — consolidator output retains ALL 12. Repeat with 30 signatures: assert no signature dropped, set-merge of duplicates correctly unions `evidence_iters`. **Load-bearing guard against G3 regression.**
- [ ] **Cache-hit-merge regression test (Rev 8.2 specific)**: simulate the active-cache-hit path — prior entry has iter-2 finding "VRAM spike at 16 GB"; new LLM response at iter 10 has finding "model OOMs at 18 GB on long sequences". After merge: both findings present (low text similarity, different statements); `evidence_iters` reflects only the iter-2 entry's prior history + iter-10 marker. Confirms the verbatim-copy regression cannot return.
- [ ] **Frozen-cache regression test**: simulate the stable-model branch — `should_recall_per_model` returns False; the cache entry is copied verbatim, **no LLM call issued, no merge invoked**. Asserts the 6.1 fast-path is preserved post-refactor.
- [ ] **Bounded-size regression test (downstream blocks)**: simulate a 14-iter accumulation feeding the cache-update path (mimicking V12 iter 14). After every iter the consolidator runs as part of the active-cache-hit branch. Targets: `model_knowledge_cache` total chars **≤ 60 K** (vs. V12's 275 K) AND derived `expert_context_block` chars **≤ 12 K** AND derived `non_candidates_overview` chars **≤ 30 K**. Assert all three thresholds in one test; quantify compression ratios in the message.
- [ ] **Behavioural test (no signal loss)**: every `(model_type, field)` bucket that had at least one `strength="strong"` finding pre-consolidation still has at least one finding post-consolidation. Plus the error-signature preservation test above.
- [ ] **No LLM call inside the consolidator**: the consolidator itself is pure (deterministic similarity via `difflib.SequenceMatcher.ratio() ≥ 0.7`). LLM is called *outside* the consolidator (by the agent's existing per_model dispatcher) and the response is fed in. LLM-based merging deferred; out of scope.

**Definition of Done (Gate G1.5c — Rev 8.2)**: re-run a 5-iter chain post-implementation; report under `tools/build_token_baseline_report.py` (with the Commit 4.3.3 11-key audit live) shows **all four** of the following:

| metric                          | V12 iter 14 | post-6.3 iter 5 target |
|---------------------------------|------------:|------------------------:|
| `model_knowledge_cache` chars   |       275 K |              ≤ 60 K     |
| `expert_context_block` chars    |       181 K |              ≤ 12 K     |
| `non_candidates_overview` chars |       110 K |              ≤ 30 K     |
| **Trap Test (Gate G3)**: iter-2 error_signature still cited at iter 5+ | (not yet measured) | **PASS** |

If any size target is exceeded, the policy is too lenient — tighten the per-field caps. If Gate G3 fails, the merge logic is dropping load-bearing context — fix before Phase 2 progresses.

**Out of Scope**: changing the *content* policy of what counts as a finding (interpretation agent's reasoning module's job); LLM-based merging (deferred — only revisit if deterministic merge demonstrably loses signal); changing `expert_context_block` or `non_candidates_overview` *render* paths (they keep reading from the now-bounded cache); changing `_cap_knowledge_cache`'s eviction policy (separate concern — eviction operates over whole entries, consolidation operates within an entry).

---

### Commit 6: ErrorSignatureSkill — extract + render

**Phase**: 2 (Dehydration surgery; only after Gate G1 passes).
**§5 step**: 12.

**Scope**:
- `agent/skills/error_signature_skill.py` (new)
- `tests/unit/agent/skills/test_error_signature.py` (new)

**Tasks**:
- [ ] Implement `ErrorSignature` dataclass per §2.2 (fields: `error_type`, `short_message`, `last_frames`, `failure_class`).
- [ ] Implement `extract(traceback_text, max_frames=5) -> ErrorSignature` with heuristic classification:
  - `failure_class` mapping: VRAM strings → `"vram"`, NaN/grad strings → `"training"`, validator errors → `"validation"`, etc.
  - `last_frames` filters traceback to user-code frames (skip site-packages / torch internals).
- [ ] Implement `render(sig) -> str` returning a 4-line markdown block.
- [ ] Sanity unit tests with synthetic tracebacks for each `failure_class`.

**Pre-Commit Checklist**:
- [ ] **Positive test**: `pytest tests/unit/agent/skills/test_error_signature.py` — for each of the 5 classifier classes, a synthetic traceback is correctly classified and rendered.
- [ ] **Quantitative metric**: across the 5 synthetic samples, all rendered signatures are `< 600` chars; median compression ratio (rendered / raw) `< 0.10`.
- [ ] **Negative test**: `pytest -k test_extract_unknown_does_not_silently_succeed` — when `extract` is given an unparseable input, it returns `ErrorSignature(failure_class="unknown", ...)` *and* logs a warning; downstream callers can detect "unknown" and decide whether to keep raw text instead.

**Definition of Done**: the skill can dehydrate a synthetic traceback in five known classes; the unknown path is explicitly flagged.

**Out of Scope**: the V11 forensic test (Commit 7); ledger schema (Commit 8).

---

### Commit 7: Offline Forensic Benchmark (Gate G2)

**Phase**: 2.
**§5 step**: 13.

**Scope**:
- `tests/forensic/__init__.py` (new)
- `tests/forensic/conftest.py` (new — fixtures pointing at `/home/klz/Data/SIDEREIS_DATA/exploration_explore_novel_v11_0503/...`)
- `tests/forensic/test_v11_spectral_u_signature.py` (new)

**Tasks**:
- [ ] Implement `_load_v11_spectral_u_failure_text()` fixture: reads `run_output_iter_002.json` + relevant `chain_log` slice; concatenates raw failure text.
- [ ] Implement the 6 §2.8.2 assertions verbatim.
- [ ] Add `@pytest.mark.forensic` marker; register in `conftest.py` so it runs only when `--run-forensic` is passed (skipped by default to keep CI quick).

**Pre-Commit Checklist**:
- [ ] **Positive test**: `pytest tests/forensic/test_v11_spectral_u_signature.py --run-forensic` passes all 6 assertions on the V11 spectral_u_operator_lite forensic data.
- [ ] **Quantitative metric**: `Cr = len(rendered) / len(raw_log) < 0.10`; rendered length `< 600` chars; both reported by the test (as test-output prints, not just asserts).
- [ ] **Negative test**: hand-construct a generic Python `RuntimeError` traceback with no FFT or U-Net references; assert that running the benchmark assertions against *that* traceback fails (proves the assertions actually require the FFT/U-Net mention, not just any signature).

**Definition of Done (Gate G2)**: `ErrorSignatureSkill` extracts the V11 root cause (VRAM + FFT/U-Net) deterministically. If this commit's tests fail, **Commit 8 cannot start** — return to Commit 6 and improve `extract` until G2 passes.

**Out of Scope**: ledger schema (Commit 8) — schema work begins only after this gate.

---

### Commit 8: Ledger schemas

**Phase**: 2.
**§5 step**: 14.

**Scope**:
- `agent/schemas/proposal.py` (add `EvolutionaryLedger`, `PredecessorEntry`, `OlderAttemptSummary`, `DeltaReasoning`; add `ProposalInput.ledger`, `ProposalOutput.delta_reasoning`)
- `tests/unit/agent/schemas/test_evolutionary_ledger.py` (new)

**Tasks**:
- [ ] Define the 4 new Pydantic models per §2.6 with bounded list lengths enforced by validators.
- [ ] Add `ProposalInput.ledger: Optional[EvolutionaryLedger] = None` (backward compat).
- [ ] Add `ProposalOutput.delta_reasoning: Optional[DeltaReasoning] = None` initially; tighten to required in Commit 12 cleanup after the chain run validates.
- [ ] Update `ProposalOutput`'s docstring to reference the new field.

**Pre-Commit Checklist**:
- [ ] **Positive test**: `pytest tests/unit/agent/schemas/test_evolutionary_ledger.py` — construct a valid `EvolutionaryLedger`; round-trip through `model_dump()` / `model_validate()` matches.
- [ ] **Quantitative metric**: a valid serialized ledger with predecessor + 8 older_attempts + 6 confirmed_lessons + 4 open_bottlenecks renders to `≤ 4 KB` JSON (proves the schema's natural size matches the design intent).
- [ ] **Negative test**: `pytest -k test_ledger_rejects_oversized_lists` — constructing a ledger with `older_attempts` length > K raises ValidationError; constructing `DeltaReasoning` with `what_we_change` length > 3 raises.

**Definition of Done**: ledger and delta-reasoning schemas exist and validate; existing proposer code paths still work because new fields are Optional.

**Out of Scope**: helpers (Commit 9); workflow assembly (Commit 10); rendering (Commit 11).

---

### Commit 9: Truncation + sliding-window helpers

**Phase**: 2.
**§5 step**: 15.

**Scope**:
- `nodes/proposal_helpers.py` (add `truncate_score_tables`, `apply_source_window`)
- `tests/unit/agent/proposal/test_truncate_score_tables.py` (new)
- `tests/unit/agent/proposal/test_source_window.py` (new)

**Tasks**:
- [ ] Implement `truncate_score_tables(tables, top_n) -> (truncated, omitted_names)` per §2.3.
- [ ] Implement `apply_source_window(candidates, full_source_for=1, summary_for_older=True) -> list[dict]` per §2.4.
- [ ] Both helpers must be pure (no I/O, no global state) so tests are deterministic.

**Pre-Commit Checklist**:
- [ ] **Positive test**: `pytest tests/unit/agent/proposal/test_truncate_score_tables.py tests/unit/agent/proposal/test_source_window.py` — synthetic 30-model dict truncates to 5 by best_score; older candidates keep only one summary line.
- [ ] **Quantitative metric**: with 30 models in the input dict and `top_n=5`, JSON-serialized truncated output is `≤ 8 KB` (matches §4 metric #4 target).
- [ ] **Negative test**: `pytest -k test_truncate_handles_empty_dict` — empty input returns empty output and `omitted_names=[]`; no IndexError. `pytest -k test_window_rejects_invalid_iter_offset` — candidate with `iter_offset=-1` raises.

**Definition of Done**: both helpers compress as designed and refuse malformed inputs.

**Out of Scope**: wiring helpers into the workflow (Commit 10); rendering (Commit 11).

---

### Commit 10: Ledger construction in workflow + protocol

**Phase**: 2.
**§5 step**: 16.

**Scope**:
- `core/resume.py` (build older_attempts summary + confirmed_lessons from disk)
- `workflows/model_exploration.py` (replace `accumulated_physical_rejections` etc. with ledger construction; lines 916-954 region)
- `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` (populate `ProposalInput.ledger`)
- `tests/unit/agent/protocols/test_ledger_assembly.py` (new)

**Tasks**:
- [ ] In `core/resume.py`, parse all prior `interpretation_iter_*.json` and `run_output_iter_*.json` to build `older_attempts: list[OlderAttemptSummary]` and `confirmed_lessons: list[str]`.
- [ ] Use `ErrorSignatureSkill.extract(...)` (Commit 6) to dehydrate the predecessor's failure into `PredecessorEntry.error_signature`.
- [ ] Use `truncate_score_tables` (Commit 9) before placing tables into the ledger / interpretation summary.
- [ ] Use `apply_source_window` (Commit 9) when building candidate dicts handed to the proposer.
- [ ] Update the protocol to pass the assembled `ledger` into `ProposalInput`.

**Pre-Commit Checklist**:
- [ ] **Positive test**: `pytest tests/unit/agent/protocols/test_ledger_assembly.py` — synthetic disk fixture with 5 prior iters; assert ledger.predecessor matches iter 5; older_attempts has 4 entries; sizes within bounds.
- [ ] **Quantitative metric**: assembled ledger from a 10-iter fixture is `≤ 4 KB` serialized; predecessor source code is full; older_attempts each ≤ 280 chars (one_line_idea ≤ 140 + failure_reason ≤ 140).
- [ ] **Negative test**: `pytest -k test_assembly_aborts_on_corrupt_disk` — when one of the prior interpretation files is malformed JSON, the assembly raises a clear error rather than silently dropping the iter (data quality is load-bearing for the ledger; we don't paper over corruption).

**Definition of Done**: a populated `EvolutionaryLedger` is built from real disk artifacts and reaches `ProposalInput`; helpers are exercised end-to-end.

**Out of Scope**: rendering in the proposer prompt (Commit 11).

---

### Commit 11: Proposer rendering + Delta Reasoning prompt + Trap Test (Gate G3)

**Phase**: 2.
**§5 steps**: 17, 18, 19, 20, 21.

**Scope**:
- `nodes/ml_model_proposal_agent.py` (render ledger; remove flat `previous_failures` block when `inp.ledger is not None`; legacy path preserved as fallback)
- `agent/prompt_templates/proposal/comparison_stage*.md` (×3 — declare `delta_reasoning` schema reference)
- `agent/prompt_templates/proposal/causal_reasoning_stage*.md` (×3 — required Delta Reasoning block)
- `agent/prompt_templates/proposal/proposing_stage*.md` (×3 — output-schema reference for `delta_reasoning`)
- `tests/unit/agent/proposal/test_iter2_lesson_present_in_iter10_prompt.py` (new — plumbing-only Trap unit test)
- `tests/integration/proposer/test_long_term_wisdom_trap.py` (new — real-API Trap test)
- `tests/integration/nodes/test_ml_model_proposal_agent_ledger.py` (new — Tier-1 integration)

**Tasks**:
- [ ] Add ledger rendering helpers in `ml_model_proposal_agent.py` (replaces the flat `previous_failures` rendering at line 644-648 *when* `inp.ledger is not None`; legacy path retained otherwise per §2.6 fallback policy).
- [ ] Update the 9 prompt-template files (3 stages × 3 explore/exploit/default variants) to add the Delta Reasoning required block and reference the new output field.
- [ ] Implement the §2.9 plumbing-only Trap unit test.
- [ ] Implement the §2.9 real-API Trap test with `@real_run` marker.
- [ ] Implement the Tier-1 integration test asserting `delta_reasoning` is present and well-formed on a real call.

**Pre-Commit Checklist**:
- [ ] **Positive test (plumbing)**: `pytest tests/unit/agent/proposal/test_iter2_lesson_present_in_iter10_prompt.py` — the iter-2 trap text is verifiably present in the rendered iter-10 prompt.
- [ ] **Positive test (Tier-1)**: `pytest tests/integration/nodes/test_ml_model_proposal_agent_ledger.py --real-api-call` — real LLM call; `delta_reasoning` field is present, well-formed, and bounded list lengths satisfied.
- [ ] **Quantitative metric (Gate G3)**: `pytest tests/integration/proposer/test_long_term_wisdom_trap.py --real-api-call` — both assertions pass (proposer cites iter-2 lesson AND avoids the failing architecture).
- [ ] **Negative test**: `pytest -k test_proposer_falls_back_when_ledger_missing` — with `inp.ledger=None`, the legacy `previous_failures` rendering is used and produces a valid prompt (regression-guard for the fallback path).

**Definition of Done (Gate G3)**: ledger is rendered correctly; `delta_reasoning` is in every output; the Trap Test demonstrates 8-iter retention. If G3 fails, tune §2.9.4 knobs (older_attempts_K, confirmed_lessons_min_iters, last_frames_count) and re-run before proceeding to Commit 11.2.

**Out of Scope**: SOTA Replication tooling (Commit 11.2); V13 chain run (Commit 12); legacy-path removal (Commit 12 cleanup).

---

### Commit 11.2: SOTA Replication tooling + Gate G3.5

**Phase**: 2.
**§2 ref**: 2.10. **§4.2 ref**: metric #12 (SRR).

**Scope**:
- `tools/verify_sota_replication.py` (new — Golden Iteration extraction, dehydrated re-run, AST + LLM-judge comparison)
- `tests/integration/proposer/test_sota_replication.py` (new — `@real_run`-gated test that drives `verify_sota_replication.py` against the V12 baseline workspace)
- `tests/unit/tools/test_verify_sota_replication.py` (new — synthetic-fixture unit tests for the deterministic pieces: Golden Iteration ranking, AST Jaccard, manifest schema)
- `reports/v13_sota_replication.md` (new — output artefact; one row per Golden Iteration, plus SRR aggregate)

**Tasks**:
- [ ] Implement `tools/verify_sota_replication.py` per §2.10:
  - Golden-Iteration selector: rank V12 `run_output_*.json` by `denoising_score`; emit a manifest (top-3 architectures, source iter, source workspace).
  - State reconstructor: extract `model_knowledge_cache` + `model_descriptions` + prior records as they existed at the start of each Golden Iteration; verify reconstruction fidelity via input-hash replay.
  - Dehydrated re-runner: process state through the Commit 6.3 consolidator; issue a real proposer LLM call (`@real_run`-gated) using the post-6.3 protocols.
  - Comparator (Structural Fidelity): plugin-AST parse on both proposals; compute Jaccard on a curated primitive-node set (encoder family, decoder family, FFT/attention/residual presence). Deterministic.
  - Comparator (Reasoning Density): cheap LLM judge (gpt-4o-mini, temp=0) compares new `delta_reasoning` + `causal_hypothesis` against V12 originals; multi-sample to reduce variance.
  - Reporter: emit `reports/v13_sota_replication.md` with per-architecture verdict, the AST evidence string, the LLM-judge rationale, and the SRR aggregate.
- [ ] Implement the unit tests for the deterministic pieces (no LLM in the loop): Golden ranking, AST Jaccard math, manifest schema.
- [ ] Implement the `@real_run`-gated integration test that exercises the full pipeline on the V12 baseline workspace.

**Pre-Commit Checklist**:
- [ ] **Positive test (unit)**: `pytest tests/unit/tools/test_verify_sota_replication.py` — Golden Iteration ranking is deterministic given a fixed manifest; AST Jaccard returns 1.0 on identical primitives, 0.0 on disjoint sets, expected fractions on partial overlaps; manifest schema rejects malformed inputs.
- [ ] **Positive test (Gate G3.5)**: `pytest tests/integration/proposer/test_sota_replication.py --real-api-call` against the V12 baseline workspace. **Pass criterion**: SRR ≥ 2 of 3 (each passing architecture meets `Structural Fidelity ≥ 0.7 AND Reasoning Density ≥ 75 %`).
- [ ] **Negative test (consolidator regression sentinel)**: with a synthetic adversarial cache (top-K active set zeroed out), assert SRR drops to 0 — proves the metric is sensitive to the consolidator dropping load-bearing entries.
- [ ] **Quantitative metric**: report cost — total LLM spend for one full SRR run ≤ \$2 (3 proposer calls + ~15 judge calls). SRR is run gated on Phase 2 exit, not per-iter.

**Definition of Done (Gate G3.5)**: `tools/verify_sota_replication.py` produces a verdict CSV + `reports/v13_sota_replication.md` for the top-3 V12 architectures; SRR ≥ 2 of 3; the failing-case diagnostic (§2.10.5) is exercised at least once via the adversarial-cache sentinel test. If SRR < 2 of 3, tune §2.10.6 knobs (`merge_similarity_threshold`, `active_set_top_k`) and re-run before proceeding to Commit 12.

**Out of Scope**: V13 chain run (Commit 12); legacy-path removal (Commit 12 cleanup); SRR running per-iter (it is a gate, not a continuous metric).

---

### Commit 12: V13 chain run + metrics validation (Gate G4) + cleanup

**Phase**: 2.
**§5 steps**: 22, 23, 24.

**Scope**:
- `tools/compute_frr.py` (new — Failure Re-occurrence Rate computation)
- `tools/compute_drr.py` (new — DRR_Structural + DRR_LLM + Gap)
- `reports/v13_token_dehydration.md` (new — output artifact)
- `nodes/ml_model_proposal_agent.py` (cleanup: remove legacy fallback at line 644-648)
- `agent/schemas/proposal.py` (cleanup: remove `previous_failures: List[str]` field; tighten `delta_reasoning` to required)
- `workflows/model_exploration.py` (cleanup: remove `accumulated_physical_rejections` synthesis path at lines 916-954)

**Tasks**:
- [ ] Run a V13 chain (≥ 5 iters; ≥ 15 preferred for iter-30 extrapolation) with `use_evolutionary_ledger=True`.
- [ ] Implement `tools/compute_frr.py` per §4.2.1: joins `token_usage.jsonl` + ledger artefacts + validator outputs; emits FRR CSV.
- [ ] Implement `tools/compute_drr.py` per §4.2.1: structural matcher (AST/regex) + LLM judge (gpt-4o-mini, temp=0); emits DRR_Structural, DRR_LLM, Gap.
- [ ] Build `reports/v13_token_dehydration.md`: all 13 §4 metrics reported (rows 1–6, 7, 8a, 8b, 8c, 9, 10, 11). Each metric has its target, actual, and pass/fail verdict.
- [ ] **Conditional on all metrics passing**: remove the legacy fallback paths listed in scope. Tighten `ProposalOutput.delta_reasoning` to required (non-Optional).

**Pre-Commit Checklist**:
- [ ] **Positive test (Gate G4)**: every metric in the `reports/v13_token_dehydration.md` table is at or beyond its target.
- [ ] **Quantitative metric**: `prompt_tokens(iter=4) / prompt_tokens(iter=1) ≤ 1.20` for the proposer's `proposing` stage; total V13 cost `≤ 60%` of V12 baseline; FRR `= 0`; DRR_Structural `≥ 0.85`; DRR Gap `≤ 0.15`; Cr median `< 0.10`, p95 `< 0.15`.
- [ ] **Negative test (regression guard)**: full unit-test suite passes after cleanup commit (the legacy-path removal must not break any existing test). `pytest tests/ -x` exits 0.
- [ ] **Negative test (forensic re-runnability)**: assert that loading an old V11 `proposal_iter_NNN.json` against the new `ProposalOutput` schema produces a clear deprecation warning rather than crashing — open question §6.6 may revise this.

**Definition of Done (Gate G4)**: V13 chain run shows the refactor delivered the target cost reduction without regressing any intelligence metric; legacy paths removed; the system is on the new architecture.

**Out of Scope**: anything Phase 3 (tuner refactor, dashboard, etc.).

---

### Commit Map (visual — Rev 8.1)

```
Phase 1 (Telemetry — CLOSED)             Phase 2 (Targeted O(N) Dehydration)              Phase 3 (Optional)
 ┌──────────────────────────────┐         ┌─────────────────────────────────────┐          ┌─────────────────┐
 │ C1 capture                   │         │ C6.1 Interp Call-on-Demand          │ ★★ CRIT  │ C11.1 Template  │
 │ C2 setter+fail               │         │      sliding-window (synthesis)     │          │       Dehydration│
 │ C3 audit+labels              │         │      + Stability Filter             │          │   (21% fixed)   │
 │ C4 plumbing                  │         │      (per_model call clamp)         │          │   opportunistic │
 │ C4.3.2 ATTRIBUTION ✓ CLOSED  │         │ C6.3 Source-Level Cache Drain       │ ★★ CRIT  │   post-G1.5     │
 │   H1 verdict — leak in       │         │      Merge & Prune over             │          └─────────────────┘
 │   non_candidates_overview    │         │      model_knowledge_cache          │
 │ C4.3.3 11th audit key ✓      │         │      → both expert_context AND      │
 │   (catch-all → ~8K baseline) │ ──────▶ │      non_candidates_overview shrink │
 │ C5 G1 baseline (LANDED)      │         │      [GUARD: preserve ErrorSigs]    │
 │   USD + bloat (verdict ✓)    │         │ C6.2 Proposer prior-stage           │   MED
 └──────────────────────────────┘         │      mid-truncation                 │
                                          │      (clamp 3.3× O(N))              │
                                          │ ─── G1.5 re-baseline (5 metrics) ───│
                                          │ C6 ErrorSig                         │
                                          │ C7 G2 forensic                      │
                                          │ C8 schemas                          │
                                          │ C9 helpers                          │
                                          │ C10 assembly                        │
                                          │ C11 G3 trap (depends on 6.3 guard)  │
                                          │ C11.2 G3.5 SOTA Replication ★ NEW   │
                                          │      (verify_sota_replication.py;   │
                                          │       SRR ≥ 2/3 top-V12 archs;      │
                                          │       aspirational creativity guard)│
                                          │ C12 G4 + cleanup                    │
                                          └─────────────────────────────────────┘
```

Gates G1, G1.5, G2, G3, G3.5, G4 are explicit STOP points.

- **G1 (LANDED)**: Commit 5 produced `reports/v12_token_baseline.md` + `reports/v12_top3_bloat.md`. Verdict: Confirmed Proposer Hypothesis. 14/14 BLOAT_ALERT. Commit 4.3.2 surfaced as a Phase-1 blocker.
- **G1 audit closure (Rev 8)**: Commit 4.3.2 closed with H1 verdict; Commit 4.3.3 ships the 11-key audit. The 10→11-key shift restores `template_and_scaffolding` to its true wrapper baseline (~8 K chars per call), and Phase 2 surgery now operates on a trusted breakdown.
- **G1.5 (Rev 8 — 5 metrics)**: post-Commit-6.1/6.2/6.3 re-baseline. Re-run the chain, recompute the following five and bound each:
   1. `interpretation.synthesis` chars per call (Rev 5 target — clamped by 6.1 sliding window).
   2. `interpretation.per_model` calls per iter (Rev 7 target — clamped by 6.1 Stability Filter).
   3. `proposer.prior_stage_outputs` chars per call (Rev 6 target — clamped by 6.2 mid-truncation).
   4. `expert_context_block` chars per call (Rev 7 target — bounded as a side-effect of 6.3 source-level drain).
   5. `non_candidates_overview` chars per call (Rev 8 NEW — bounded as a side-effect of 6.3 source-level drain; visible only because Commit 4.3.3 promoted it to a named key).

   **All five must drop from O(N) to ≤ O(log N) or bounded ≤ 1.5× iter5/iter1.** If G1.5 fails on any, return to the responsible commit (6.1/6.2/6.3) and tighten before proceeding.
- **Phase 2 entry**: unblocked by Commit 4.3.3 (Rev 8). Phase 1 fully closed.
- **G3 dependency**: Commit 11's Trap Test (§2.9) depends on Commit 6.3's Error-Signature Preservation Guard. If 6.3 prunes error signatures, G3 fails. The guard is a hard requirement, pinned by a dedicated unit test in 6.3's Pre-Commit Checklist.
- **G3.5 (Rev 8.1 — NEW)**: Commit 11.2's SOTA Replication Test (§2.10) verifies the *aspirational* property — the dehydrated agent can still navigate to the high-signal architectures the V12-rich-context agent discovered. Computed via `tools/verify_sota_replication.py`: per-architecture verdict on Structural Fidelity (≥ 0.7) AND Reasoning Density (≥ 75 %); SRR aggregate (Metric #12) requires ≥ 2 of 3 top V12 architectures to pass. Below threshold = consolidator's Merge & Prune is lopping off the peak; tune §2.10.6 knobs (`merge_similarity_threshold`, `active_set_top_k`) and re-run. **Blocks Phase 2 exit.** Rationale: FRR + DRR are defensive guards (catch regressions); SRR is the only aspirational guard (verifies retained creative capability).

---

## 9. Phase 3 (Optional) — Fixed-Cost Shaving

Phase 3 is **opportunistic, not mandatory**. It is triggered only if Commits 6.1 + 6.2 have landed, the G1.5 re-baseline shows the O(N) bleed is clamped, **and** per-iter USD is still above the $1.50 target ceiling. If the post-6.1/6.2 baseline already meets the target, Phase 3 is skipped entirely.

**Rationale for the deferral**: V12 calibration (§1.5.1.2) shows the proposer's template + system_prompt + scaffolding is ~21% of `proposer.comparison`'s prompt cost (7.5 K of 36 K chars at iter 1). This is structural fixed cost — necessary for prompt adherence, does not grow with iterations. While shaving it is technically possible, it is the wrong order: optimizing fixed cost while linear growth bleeds 3 K tokens/iter into the synthesis prompt would be polishing a leaking bucket. We address fixed cost only after the leaks are sealed.

### Commit 11.1 (Phase 3, Optional): Template Dehydration

**Phase**: 3 (Optional — post-G1.5).

**Trigger condition**: Commits 6.1 + 6.2 landed; G1.5 passed; per-iter USD still above target ceiling.

**Scope**:
- `agent/prompt_templates/proposal/*.md` (×9 — section header tightening, instruction-block compression)
- `nodes/ml_model_proposal_agent.py` (`system_prompt` audit — strip duplicated instructions if any)

**Tasks**:
- [ ] Audit each of the 9 proposer template files for redundancy: section headers that restate themselves, instructions that duplicate `system_prompt` content, multi-paragraph framing that could be a single sentence.
- [ ] Apply mechanical compressions only (no semantic content drop). Target: 30% reduction in `template_and_scaffolding` chars without changing the rendered task description.
- [ ] Re-run proposer behavioural tests (existing) — assert no test fails as a result of the compression. The Trap Test (Commit 11) is the strict gate: if compression silently drops a behavioural cue, the Trap Test will catch it.

**Pre-Commit Checklist**:
- [ ] **Positive test**: `template_and_scaffolding` chars in a synthetic iter-1 proposer assembly drop from ~7.5 K to ≤ 5.3 K (≥ 30% reduction).
- [ ] **Behaviour-preservation test**: full existing proposer test suite passes (`pytest tests/unit/agent/proposal/ tests/integration/nodes/test_ml_model_proposal_agent.py`).
- [ ] **Trap Test rerun**: `pytest tests/integration/proposer/test_long_term_wisdom_trap.py --real-api-call` still passes — compression did not erase the long-term wisdom behaviour.

**Definition of Done**: 30% template-tax reduction; no behavioural regression; per-iter USD cost moves measurably toward the $1.50 ceiling. If the trigger condition was never met, this commit is *not done* — it is *not needed*, and that's a successful Phase 2.

**Out of Scope**: changing prompt semantics, reordering stages, adding/removing template sections.
