# PR 09a — interpreter evidence & ordering on the metric handle (child design)

## 0. Status and provenance

**REVISION 2 — FROZEN (operator final ruling 2026-08-19: "APPROVED WITH
MINOR FINAL AMENDMENTS" — freeze authority exercised after the mandated
adversarial pass, §11, closed without a new material contradiction). The
SEMANTIC design is frozen and is not reopened by implementation.**

*(Freeze-time state, preserved: implementation had NOT started; every
checkbox in §4 was `[ ]` and every §10 ledger entry was empty.)*

**IMPLEMENTATION COMPLETE** on branch
`step09-pr09a-interpreter-evidence-ordering` from the frozen base
`a325f33b`. This document is now also the LIVE implementation ledger: §4
checkboxes carry real state and §10 carries the evidence. Current
checkpoint: **C1a-C7 COMPLETE + pre-merge closeout applied** (operator
review 2026-08-19: code/semantic review PASS with two bounded closeout
items — the ledger synchronization below, and the F-09a-17 single-authority
audit, which CENTRALIZED the prediction-semantics ids). §4 is fully
synchronized against §10: **104 `[x]` / 0 `[ ]`** — every implementation-owned
box carries the evidence that satisfies it, and no box was ticked from a
re-run staged for that purpose. State: awaiting the exact-head CI on the
final candidate head, then operator merge.

Rev 1 (`79bfd564`, DRAFT) was reviewed by the operator; the C1a→C1b … C7
architecture and sequence were approved and the seven open questions were
ruled (§0.4). Rev 2 applies those rulings, the narrow parent factual
erratum they mandate, and the final adversarial pass.

Child of the FROZEN Step-09 parent
(`docs/design/generic_framework_upgrade/step_09_interpretation_task_blocks.md`,
REVISION 2 — FROZEN at `432cb51a`; Q-09-7 = B ruled at `205a4170`, parent
§0.2). Authority order: frozen parent (incl. §0.2) > current source (§2) >
merged Step-06/07/08 designs and ledgers > roadmap §11 / §22 > this design.
Where the parent's prose and the source differ, the difference is recorded
in §0.3 and the SOURCE governs the commit plan; the parent's frozen
architecture and acceptance are not reopened.

**Audit anchor: master `205a4170`** (the Q-09-7 ruling commit; production
source byte-identical to the parent's anchor `bf22827b` — the two commits
in between are docs-only). Working tree clean at the start of the audit.
Every `file:line` below was read at this anchor. **Zero
`SOURCE-INSPECTION REQUIRED` markers.**

Written under the operator's 09a authorization (2026-08-19): established
Step-07/08 child-design format; the first implementation milestone is the
frozen behaviour-preserving node-local extraction; 09a introduces NO
secondary-metric evaluator, NO secondary-metric loader, NO task-specific
binding path, NO new metric derivation site, NO task-name branch, and NO
third PR.

### 0.1 What this PR is, in one paragraph

Today every interpreter-side comparison of golden-metric values re-reads
"higher is better" as a literal (`>`/`<`/`max`/`min`/`sort(reverse=True)`),
the prediction band is sign-degenerate for TIDMAD's negative scores and
direction-wrong for any lower-is-better metric, an uncomputable prediction
is counted as a genuine "partial", and the evidence-borne metric identity,
the 07a training diagnosis and (by contract) secondary metrics never reach
the interpreter. 09a (i) extracts the deterministic evidence / ordering /
prediction logic it is about to modify into private node-local modules
behaviour-preservingly, (ii) transports the tuner's ONE resolved
`MetricSpec` additively on `HyperparamTuningOutput`, reconciles it in the
workflow and makes it the interpreter's fail-closed ordering authority
(`MetricOrder`, the 07b pattern), (iii) migrates EVERY interpreter direction
consumer onto it, (iv) freezes the sign-safe, direction-correct prediction
band with `unevaluated` and version-partitioned outcome accounting,
(v) projects identity / diagnosis / present-when-present secondaries /
authority-derived failure counts into the summary and digest, and (vi)
proves the contract on three tasks with L1 fixtures. **No prompt-TEMPLATE
byte changes** (PB-0/PB-7/PB-8 goldens EXACT); deterministic prompt
CONTENT changes only where the frozen band/`unevaluated` rules change an
outcome, owned by a committed differential digest oracle.

### 0.2 The boundary this PR must not cross

Per the parent §15/§16 and the 09a authorization: 09a owns deterministic
evidence and ordering only. It does NOT own: prompt templates, prompt
builders' CONTENT, `InterpretationTaskBlocks`, the TIDMAD declaration/
adapter, explicit renderers, Gate 1 (all 09b); tuner policy, incumbent
selection, `memory.conclusion` (07b); Health verdicts (08); metric
arithmetic (06); **secondary-metric declaration binding, additional
metric-handle execution, tuner-side secondary scoring, `ExperimentRecord`
secondary persistence, production secondary transport (Step 10, Q-09-7 =
B)**; `core/resume.py:436` / chain-incumbent / dashboard direction
literals (Step 10+); the `evaluation.py` name tables (Step 10); the dead
tune→interp protocol's fate (post-Step-12). **Planner/prompt exposure and
production-default changes are outside every commit below** — any such
delta is a material deviation requiring operator review.

### 0.3 Parent errata found by this source audit (recorded; architecture unchanged)

| id | parent text | source at `205a4170` | consequence for 09a |
|---|---|---|---|
| **E1** | §2.3 table lists 12 interpreter direction-consumer sites | FOUR more exist: `result_interpretation_agent.py:219-221` (`_render_health_summary_section` picks the "best-scoring round" with `s > best_score` — flag-ON prompt path); `nodes/interpretation_helpers.py:444` (`max(sota_from_prediction, overall_best_score)` "strictest SOTA"), `:450` (`best_score > sota_score`), `:455` (`best_score > sota_score * 0.95` — a SECOND relative band, sign-degenerate for negative sota exactly like §2.4) | all four migrate in C3 (§3.3); the discoveries band becomes sign-safe with its existing 0.05 width (Q-09a-5) |
| **E2** | §2.13 / §8: `prediction_outcomes_history` / `cumulative_information_gain` are "carried-forward" and "restore latest-wins from the committed digest (`core/resume.py` RestoredState)" | **No production carry-forward exists.** The workflow's inline `InterpretationInput(...)` (`workflows/model_exploration.py:2097-2120`) passes NEITHER field (nor `vocab_link_confirmations`); the in-process loop carries only cache / vocab / fingerprints / proposal (`:2724-2746`); `core/resume.py` has zero occurrences of the three names; `sdsc_submission_scripts/run_one_iteration.py` forwards none. Every production digest's pool is therefore exactly ONE outcome (the preserved `step07b_gate1_postrefactor` digest: `{partial: 1}`, accuracy `{partial: 1.0}`) | the §8 version-partition rule was designed for a pool that does not yet travel; RULED: 09a lands the NARROW interpreter-owned carry/restore through the existing canonical path (Q-09a-1 = A narrow, C5) and the exact per-field v1/v2 partition (Q-09a-2, §3.4) |
| **E3** | §13a: "private `_`-modules" | the executable boundary rule `tests/unit/nodes/test_node_public_boundary.py:54-59` treats ONLY non-underscore `*.py` files as a node's private modules (underscore-prefixed files are invisible to both halves of the rule); the tuner precedent uses plain names (`policy.py`, `records.py`, …) | 09a's private modules use PLAIN names so the rule covers them (§3.1) |
| **E4** | §22 "Temporary compatibility paths … the regime-A spec derivation (workflow)" | route B (§2.11) puts the ONE derivation in the TUNER (`ml_hyperparameter_tune_agent.py:541`); the workflow RECONCILES transported values | wording only; 09a adds no derivation site |
| **E5** | §2.4 documents the uncomputable-⇒-"partial" defect | additionally, `generate_discoveries` (`interpretation_helpers.py:397-435`) turns that label into a vocabulary DISCOVERY `prediction_<model>_partial` ("PARTIAL: … achieved metric=N/A …") | the `unevaluated` rule must also suppress the outcome discovery (§3.4) |

None of these reopens the parent's frozen architecture. E2 and the E1
census count are applied to the parent as a NARROW factual source erratum
("factual source correction only; frozen Step-09 architecture unchanged")
in the same freeze commit (parent §0.3, §2.3, §2.13, §8, §15, §19).

### 0.4 Operator final ruling (2026-08-19) — the seven questions, RESOLVED

| id | ruling | landed at |
|---|---|---|
| **Q-09a-1** | **A, NARROWLY** — 09a owns the narrow interpreter-memory transport that makes the frozen v1/v2 prediction-memory contract production-reachable: ONLY the interpreter-owned prediction fields, ONLY through the EXISTING canonical lifecycle (current digest → next-iteration workflow carry → existing `RestoredState` latest-wins). C5 is no longer conditional. Forbidden: redesigning generic resume, changing latest-wins policy, changing chain-incumbent restoration, touching unrelated workflow state, a new memory store, a second restore path, a task-specific resume branch. Semantic owner = interpreter; physical transport may touch workflow/resume ("semantic owner ≠ physical file location"). Parent factual erratum applied | §3.4, §4.6 (C5), parent §2.13/§8 |
| **Q-09a-2** | **exact per-field v1/v2 partition** — `prediction_outcomes_history` REMAINS the legacy/v1 pool (never incremented by 09a; old digests never rewritten); `prediction_outcomes_by_semantics["metric_order_signsafe_v2"]` owns the v2 confirmed/partial/refuted counts; `unevaluated` is recorded on the individual evaluation and counted in NEITHER comparable pool; `scientific_accuracy` is computed ONLY from the v2 pool and provenance-labelled by `prediction_evaluation_semantics = "metric_order_signsafe_v2"`; the digest exposes legacy-pool provenance explicitly; legacy and v2 information gain are NEVER pooled (legacy value preserved in the existing field; v2 accumulation in its own additive field); a field-semantics table is frozen (§3.4) | §3.4, §4.5 (C4) |
| **Q-09a-3** | **CONFIRMED** — no proposer prompt-template/protocol change in 09a; honesty statement: corrected deterministic prediction state IS planner/proposer-visible, so next-iteration prompt CONTENT may change through the existing renderer ("no prompt-template/protocol change; deterministic content change only through the explicitly frozen prediction-semantic correction"); if implementation finds a template edit is required to distinguish v1/v2 honestly → **STOP** (09b prompt work never moves into 09a) | §3.4, §4.5, §7 |
| **Q-09a-4** | **CONFIRMED** — bound run `MetricSpec` REQUIRED for any score-bearing interpretation; record `metric_id`/`direction` must match it exactly whenever a primary `MetricResult` exists; mismatch or absence ⇒ deterministic contract error BEFORE ordering, active-model selection, prediction evaluation, evidence rendering and any LLM call; no fallback to higher-is-better / `denoising_score` / task identity / `derive_tidmad_metric`; cold-start / genuinely scoreless inputs keep the frozen named-absence path; explicit negative owners for missing spec, id mismatch, direction mismatch, multi-output disagreement | §3.2, §4.3 (C2) |
| **Q-09a-5** | **CONFIRMED, source-bounded** — the four additional interpreter-semantic direction sites belong to 09a C3 (the final source re-read confirms they are ordering/comparison semantics); the second sign-degenerate relative 5% comparison in `generate_discoveries` becomes direction-correct / sign-safe with **margin 0.05 preserved exactly** (direction + negative-reference handling only; `MetricOrder` for better/worse; no higher/lower literal, task identity or metric-id branch); it does NOT feed the versioned accuracy pool, so NO third counter/version system — a declared deterministic correction pinned by hand-computed positive/negative × higher/lower cases; parent/child census counts reconciled (§2.2) | §2.2, §3.3, §4.4 (C3) |
| **Q-09a-6** | **ACKNOWLEDGED / FROZEN** — a pre-09a score-bearing tuning output lacking `metric_spec` FAILS CLOSED; no replacement spec is derived at interpreter / workflow / CLI / resume / PR3 path; the refusal is actionable and names "legacy/pre-09a output lacks the stamped run MetricSpec required for interpretation ordering"; a fresh/re-produced output is the compatibility path; documented as an intentional boundary incl. the auto-resume consequence | §3.2-8, §4.3 |
| **Q-09a-7** | **CONFIRMED WITH PRECISE WORDING** — the PR3 calibration fixture stamping a `MetricSpec` is TEST-FIXTURE CONSTRUCTION ("simulated tuner-output writer / fixture stamping"), not a production derivation authority; the production census proves Step 09 adds ZERO production `derive_tidmad_metric` / `derive_tidmad_metric_spec` sites; the helper stays unreachable from production code | §2.5, §4.3 |

Additional closeout precision from the ruling: C1b keeps ONE obvious main
node file with the old import surface through narrow re-exports, reduces
mixed responsibility (no duplicate authorities) — the extracted modules are
node-private BY OWNERSHIP even though the guard convention requires plain
filenames (§3.1, §4.2); C6 never re-opens Q-09-7 (§3.5, §4.7); Gate 1 and
Gate 2 stay NOT REQUIRED (§7); roadmap/README carry DESIGN status only
(§11.2).

## 1. Mandate (frozen parent §15 / §16 09a — quoted obligations)

* **Semantic owner**: behaviour-preserving node-local decomposition of the
  surfaces it touches (§13a); ONE run `MetricSpec` authority transported +
  reconciled (§2.11); record/spec consistency (§4a); primary evidence
  projection + the secondary-metric summary projection rendered
  present-when-present (§4b; production transport is Step 10's — Q-09-7 =
  B); ALL interpreter D1 ordering consumers incl. the memory-policy helpers
  (§7); prediction grammar; versioned sign-safe band (§13 ¶1, §8);
  additive deterministic digest provenance (§5); three-task deterministic
  ordering/evidence fixtures.
* **Key surfaces**: `hyperparam_tuning.py` (additive `metric_spec` ONLY —
  no secondary carriers in 09a), `records.py` (one writer),
  `interpretation.py` schemas (additive), `result_interpretation_agent.py`
  + NEW private node modules, `interpretation_helpers.py`,
  `model_exploration.py` (input construction + reconciliation + cache-cap
  semantics), node `.md` — plus, by the Q-09a-1 = A-narrow ruling, the
  NARROW interpreter-owned prediction-memory carry/restore through the
  existing canonical path (`workflows/model_exploration.py` loop carry,
  `core/resume.py` `RestoredState` latest-wins, `run_one_iteration.py`
  forward) — semantic owner interpreter, physical location workflow/resume.
* **Prod behaviour**: deterministic only; TIDMAD ordering results identical
  (higher-is-better); prediction outcomes under v2 semantics.
* **LLM-facing**: no prompt-TEMPLATE / prompt-protocol change (templates +
  PB-0/PB-7/PB-8 goldens EXACT; same LLMBridge kwargs for a fixed input);
  deterministic persisted-memory semantics change where frozen (v2 band →
  versioned accuracy fields the PROPOSER renders, §2.13).
* **Milestones (§16)**: M1 extraction → M2 `metric_spec` transport +
  reconciliation + input field + §4a → M3 ordering consumers onto
  `MetricOrder` → M4 grammar + band + `unevaluated` + version-partitioned
  counters → M5 evidence projection → M6 three-task fixtures + node `.md`.
* **Frozen invariants (§16, differential ownership)**: prompt TEMPLATE
  bytes EXACT; PB-0/PB-7/PB-8 goldens EXACT; same LLMBridge kwargs for an
  otherwise identical fixed input; D1 names unchanged; every existing
  deterministic field NOT owned by the migration equal to the pre-09a
  value on the differential fixture; TIDMAD metric ordering unchanged;
  fail-closed without a spec / on identity mismatch; no new loader; no
  orchestration change. ALLOWED/REQUIRED deltas, each declared: additive
  metric/diagnosis/secondary/provenance/version fields; prediction-derived
  fields differing ONLY on the designed sign-band/uncomputable cases;
  memory-policy behaviour differing ONLY where the old literal was
  direction-wrong (never for TIDMAD).
* **Validation (§16)**: hand-computed band matrix; alias read-only
  compatibility; capability-gated grammar; fail-closed spec absence;
  identity-mismatch refusal; multi-output reconciliation; additive schema
  round-trip; version-partitioned counters + version-pure accuracy; legacy
  dict untouched; mutation on the band + fail-closed + reconciliation
  paths; three-task L1 ordering/evidence fixtures; the node-public-boundary
  rule; a direction-literal census over the interpreter surface (planted
  offender). Acceptance: zero interpreter `>`/`<`/`max`/`min`/`sort` on
  golden-metric values outside `MetricOrder`; goldens byte-identical; the
  differential fixture green; every negative test named.
* **Gates (§17, Q-09-4)**: Gate 1 NOT required; Gate 2 NOT required.

## 2. Source audit (at `205a4170`)

### 2.1 The node — AST inventory and what 09a materially modifies

`nodes/result_interpretation_agent/result_interpretation_agent.py` — 2,144
lines. Top-level symbols (AST, start–end):

| symbol | lines | 09a touches? |
|---|---|---|
| `PER_MODEL_SYSTEM_PROMPT` 56-138 · `_build_per_model_system_prompt` 141-158 · `HEALTH_FEEDBACK_SYSTEM_INSTRUCTIONS` 161-178 | prompt constants/builders | no (09b) |
| `_render_health_summary_section` 181-236 | prompt section builder; **`:219-221` best-round selection literal `s > best_score` (E1)** | yes — C3 parameterizes the selection by `MetricOrder`; no template byte changes |
| `_build_per_model_prompt` 239-379 | user-prompt builder; calls the health section ONLY when `structured_health_feedback` (`:358-361`) | yes — C3 threads `order` through (keyword); bytes unchanged |
| `SYNTHESIS_SYSTEM_PROMPT` 386-468 · `_NARRATIVE_FIELDS_FOR_PROMPT` 474 · `_LIST_FIELDS_FOR_PROMPT` 484 · `_flatten_entry_for_prompt` 487-510 · `_build_synthesis_system_prompt` 513-521 · `_build_synthesis_prompt` 524-732 (`:591` is an equality, not a direction read; `:717-729` "Research Health Metrics" renders `cumulative_information_gain` — the INPUT value, `:1353`) · `DEDUP_SYSTEM_PROMPT` 739-761 · `_build_dedup_prompt` 764-782 | prompt builders | no (09b) |
| `_resolve_evolution_log_root` 790-798 · `_compute_evolution_stats` 801-826 · `_append_evolution_log` 829-849 | evolution sidecar I/O | no (stays in main — persistence) |
| `ResultInterpretationAgent.__init__` 858-869 · **`run` 871-1744 (874 lines)** · `_dedup_promoted` 1746-1824 | the god-method | yes — C1b extracts the deterministic regions (below); C2–C6 modify the extracted boundaries |
| `main` 1832-1899 | CLI | yes — C2 supplies `metric_spec` from the loaded output (R-09-3) |
| `_required_denoising_score` 1907-1915 · `_round_ordering` 1918-1935 · `_round_health` 1938-1971 · `_collect_health_evidence` 1974-2003 · `tuning_output_to_model_run_summary` 2006-2140 | evidence projection (records → summary; summaries → health aggregates) | yes — C1b moves to `evidence.py`; C3 migrates `:2045-2058`, `:2069`; C6 adds projections |

Inside `run()` (exact regions, read at the anchor):

| region | lines | responsibility | 09a |
|---|---|---|---|
| cold-start branch | 880-907 | deterministic early return | unchanged (C2: named absence of the spec) |
| effective types + descriptions | 909-941 | scope resolution + `get_model_description` I/O | stays inline |
| **deterministic pre-computation** | **943-1056** | per-model best/valid/worst/formal/config; overall best/valid/worst; `total_experiments`; cache `_stats` reconstruction (`:995-1025`); `partition_for_aggregation` authority filter (`:1052-1056`) — direction literals at `:969, :972, :979, :986, :988, :1014, :1018, :1024` | C1b extracts behind a typed boundary; C3 migrates the literals |
| expert advice + health merge | 1058-1080 | `_collect_health_evidence` + `merge_fingerprint_history` BEFORE the try | unchanged (health merge stays before the try) |
| LLM try-block: Phase 1 | 1097-1282 | active set (`select_active_models` `:1112-1118`), recall, per-model LLM calls, consolidation, archive I/O | C3 passes `order` to `select_active_models`; otherwise unchanged |
| enriched-field pre-compute | 1284-1319 | `per_model_score_tables` / params / training segments (reads `inp.summaries` + INPUT cache) — inside the try; a malformed cached table raises → degraded | C1b extracts as a function CALLED AT THE SAME POSITION (inside the try) |
| Phase 2 synthesis | 1321-1404 | prompt + one LLM call | unchanged |
| Phase C prediction + discoveries + vocab | 1406-1546 | `evaluate_prediction` `:1446-1450` (with `actual_results = {best_denoising_score, best_file_vector}` `:1438-1441`, `current_sota = prev_prediction["current_value"]` `:1445`), `generate_discoveries` `:1460-1468`, vocab build/promotion/dedup, E.7 links | C3/C4 pass `order` + bound id; C4 semantics |
| **E.4 accuracy + centrifugal gain** | **1548-1575** | pooled three-label counts (`:1550-1556`), `scientific_accuracy` (`:1557-1562`), `cumulative_information_gain` (`:1566-1571`) | C1b extracts; C4 rewrites (version partition) |
| output build + persist | 1588-1664 | healthy digest + `interpretation_{run_name}.json` + evolution log | additive fields (C2, C4, C6) |
| degraded fallback | 1665-1744 | `except Exception` → digest with deterministic fields threaded | additive fields threaded identically |

`nodes/result_interpretation_agent/__init__.py` re-exports ten names
(`:18-29`) and then **rebinds `sys.modules[__name__] = _impl`**
(`:50-54`) — identical to the tuner package. Empirically (07b-C7 ledger
§14.9.1 and re-verified on this node): a node-local submodule is reachable
through the dotted path ONLY if the MAIN module imports it at its top,
while `__init__` is still executing. Every private module 09a creates is
therefore imported eagerly by `result_interpretation_agent.py`, and moved
names that external code imports from the main module stay as deliberate
re-exports (declared in `__all__` so `ruff` keeps them and
`mock.patch("nodes.result_interpretation_agent.X")` keeps resolving).

`nodes/interpretation_helpers.py` — 1,024 lines, no classes, no
`MetricSpec`/`MetricOrder` import anywhere in the interpreter surface
(node package, helpers, interpretation schemas, the two interp protocols —
grep returned zero hits). Clusters: prediction evaluation
(`evaluate_prediction` 216-305, `_DENOISING_SCORE_ALIASES` 308-314,
`_compute_metric` 317-360); discoveries (`generate_discoveries` 363-497);
vocabulary (`_STOPWORDS`, `_content_words`, `_find_duplicate_candidate`,
`promote_candidates` 500-550, `compute_vocab_diversity_ratio` 553-592,
`build_runtime_vocab` 595-684, `update_vocab_link_confirmations`
687-779); active-model policy (`select_active_models` 801-882,
`should_recall_per_model` 954-1024); compression (`compress_model_summary`
885-951). External importers: the node (`:1107-1110`, `:1329`, `:1350`,
`:1407-1413` — all function-local imports inside `run()`), unit tests
(`test_vocab_feedback.py:14-23`, `test_stability_filter.py:31-35`,
`test_prediction_evaluation_join.py:38`,
`test_compressed_summary_contract.py:32`) and one integration test
(`tests/integration/workflows/test_chain_candidate_graduation.py:79`).

### 2.2 The ordering consumers — the COMPLETE list (parent §2.3 + E1)

| # | site | literal | migration (C3) |
|---|---|---|---|
| 1 | `result_interpretation_agent.py:969` | `s.best_denoising_score > current_best` | `order.is_better(s.best_denoising_score, current_best)` |
| 2 | `:972` | `s.best_denoising_score > overall_best_score` | `is_better` |
| 3 | `:979` | `s.best_valid_denoising_score > overall_best_valid_score` | `is_better` |
| 4 | `:986` | `s.worst_denoising_score < current_worst` | `order.is_better(current_worst, s.worst_denoising_score)` ("is worse than") |
| 5 | `:988` | `s.worst_denoising_score < overall_worst_score` | same |
| 6 | `:1014` | `best > overall_best_score` (cache `_stats`) | `is_better` |
| 7 | `:1018` | `best_valid > overall_best_valid_score` | `is_better` |
| 8 | `:1024` | `worst < overall_worst_score` | "is worse than" |
| 9 | `:2045-2052` | `max(success, key=… denoising_score … float("-inf"))` (raw best; the `-inf` arm is dead — `success` is pre-filtered on `denoising_score is not None` `:2044`) | `order.best(success, key=_required_denoising_score)` — ties → FIRST (identical to `max`) |
| 10 | `:2054` | `max(valid_records, key=_required_denoising_score)` | `order.best(...)` |
| 11 | `:2056-2058` | `max(valid_formal_records, key=_required_denoising_score)` | `order.best(...)` |
| 12 | `:2069` | `min(valid_scores)` (worst) | `order.worst(valid_scores, key=identity)` |
| 13 | **`:219-221`** (E1) | `s > best_score` — best-scoring round for recording diagnostics (flag-ON prompt section) | `order.is_better(s, best_score)`; `order` threaded via `_build_per_model_prompt(..., order=)` |
| 14 | `interpretation_helpers.py:284` | `if actual > sota:` → confirmed | C4 band (§3.4) |
| 15 | `:286` | `elif actual >= sota * (1.0 - partial_margin):` → partial (sign-degenerate for `sota < 0`) | C4 band |
| 16 | `:294` | `information_gain = delta if confirmed` (positive-is-good) | C4 band: `distance` |
| 17 | **`:444`** (E1) | `sota_score = max(sota_from_prediction, overall_best_score)` | `order.best([...], key=identity)` |
| 18 | **`:450`** (E1) | `best_score > sota_score` → "beating the previous SOTA … (+{best_score - sota_score:.4f})" | `order.is_better(best_score, sota_score)`; delta text `abs(best_score - sota_score)` (direction-neutral; identical bytes for TIDMAD, where the delta is positive) |
| 19 | **`:455`** (E1) | `best_score > sota_score * 0.95` → "within 5% of SOTA" (unreachable for negative sota) | sign-safe: `abs(best_score - sota_score) <= 0.05 * abs(sota_score)`; width 0.05 unchanged (Q-09a-5) |
| 20 | `:863` (`select_active_models`) | `scored.sort(key=lambda x: (-x[1], x[0]))` Top-K highest | `sorted(key=lambda x: (order.rank(present_scores, x[1]), x[0]))` — `rank` = 1 + #strictly-better; ties share a rank and break on `mt`, reproducing `(-score, mt)` exactly under `higher` and inverting under `lower` |
| 21 | `workflows/model_exploration.py:664` (`_cap_knowledge_cache`) | `scored.sort(key=lambda x: x[1] if x[1] is not None else float("-inf"), reverse=True)` | `scored.sort(key=lambda x: order.rank(present, x[1] if x[1] is not None else order.worst_sentinel))`; Python's sort is stable, so equal ranks keep insertion order exactly as `reverse=True` did; `None` scores rank last under both directions |

**Count reconciliation (ruling §5 / §12)**: the parent §2.3 table has 15
entries — 12 node sites (`:969, :972, :979, :986, :988, :1014, :1018,
:1024, :2046-2049, :2054, :2057, :2069`) + the helpers sign-band entry
(`:284-296`, ONE entry holding the three literals `:284`, `:286`, `:294`)
+ `select_active_models` + `_cap_knowledge_cache`. Expanding the band entry
into its three literals gives 17 rows; the four E1 sites (rows 13, 17, 18,
19) bring the child census to **21 rows = 21 literal sites**. The parent's
§2.3 table is extended with the four E1 rows in the same freeze commit
(factual census update; 12 → 16 interpreter-side table entries there, the
band staying one entry). No other interpreter literal exists at the anchor
(the C3 AST census is the executable proof).

Direction-NEUTRAL on purpose (unchanged): `interpretation_helpers.py:292`
(`boldness`, `abs`), `:879` and `:1023` (absolute score deltas in the
active-model policy), `_build_synthesis_prompt:591` (`!=`).
`should_recall_per_model`, `compress_model_summary`, the vocabulary
cluster and `_dedup_promoted` contain no ordering.

NOT 09a's (pinned to stay by
`tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py:160-183`
`NOT_REACHED_DIRECTION_CONSUMERS`): `workflows/model_exploration.py:2760-2764`
(`tune_output.best_formal_denoising_score > best_score_overall`),
`core/resume.py:436`, `execute_tools/per_file_best.py`, the two dashboard
sites. The same file's `:113-148` census asserts that NO production file
other than `execute_tools/evaluation_metric.py` and
`execute_tools/metric_order.py` executes a `"higher"`/`"lower"` STRING
constant (docstrings excluded) — 09a's new modules must not introduce one
(they never spell a direction; they ask `MetricOrder`).

### 2.3 The prediction grammar, band and accounting (exact code)

`interpretation_helpers.py:216-305`: `metric = prediction.get("metric",
"denoising_score")` (`:259`); `sota = current_sota if current_sota is not
None else prediction.get("current_value")` (`:263`); `actual =
_compute_metric(metric, actual_results)` (`:266`); **uncomputable ⇒
`outcome: "partial"`, `notes: "Could not compute metric from results."`,
`boldness 0.0`, `information_gain 0.0`** (`:268-279`); `delta = actual -
sota` (`:281`); band `:284-289`; `boldness = abs(predicted - sota) /
max(abs(sota), 1e-6)` (`:292`); `information_gain = delta if confirmed
else 0.0` (`:294`); success-branch keys `metric, predicted_value,
actual_value, current_sota, delta_from_sota, outcome, boldness,
information_gain` (`:296-305`) — the `notes` key exists ONLY on the
uncomputable branch. `partial_margin` default `0.05` (`:220`).

`_compute_metric` (`:317-360`): alias set `{"denoising_score",
"best_score", "overall denoising score", "score", "best_denoising_score"}`
(`:308-314`) → `results["best_denoising_score"]`; `mean(file_vector[N:M])`
and `file_vector[N]` over `results["best_file_vector"]` (`None` ⇒ `None`
`:329-331`); anything else ⇒ `None` (`:360`).

Consumers of the evaluation record: `generate_discoveries` (`:397-435`:
ANY truthy outcome yields a discovery; `confirmed`/`refuted` have their own
sentences and EVERYTHING ELSE renders "PARTIAL: … Results are
inconclusive." — E5), `update_vocab_link_confirmations` (`== "confirmed"`),
the E.4 counter (`result_interpretation_agent.py:1550-1556` — counts any
of the three labels), `this_info_gain` (`:1568-1570`), the digest
(`prediction_evaluation`, `scientific_accuracy`,
`prediction_outcomes_history`, `cumulative_information_gain`), and the
PROPOSER's "Prediction Track Record"
(`nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:1146-1165`:
reads `scientific_accuracy`, `cumulative_information_gain` AND
`prediction_outcomes_history` — `N = sum(pred_hist.values())`; whitelist
`:1681-1683`). `InterpretationOutput.prediction_evaluation` is
`dict[str, Any]` (`agent/schemas/interpretation.py:642-652`, description
`:646` "partial = within 5%% of SOTA"); **its "Contains:" key list is
pinned to the emitted keys by
`tests/unit/agent/result_interpretation_agent/test_prediction_evaluation_join.py:166-187`**.
`cumulative_information_gain`'s description (`:678-682`, "boldness × 1")
does not match the code (`delta`) — corrected in C4.

### 2.4 The run-spec transport path

* **The ONE derivation** stays `ml_hyperparameter_tune_agent.py:541`
  (`run_metric = derive_tidmad_metric(run_profile, run_deliverable_spec)`;
  comment `:531-540` "Not serialized; crosses no process boundary");
  `run_order = MetricOrder(run_metric.spec)` `:552`; both ride
  `RunBindings.run_metric / run_order` (`contracts.py:116-120`, typed
  `Any`; `FORBIDDEN_BINDING_FIELDS` `:44-75` unaffected).
* **The ONE writer**: `records.py:747-1016 finalize_run_output(bindings,
  exit_snapshot)` — it receives `RunBindings` (reads 23 bindings at
  `:762-784`; **`bindings.run_metric` is not read today**), builds
  `agent_output_dict` (`:863-934`), validates
  `HyperparamTuningOutput.model_validate(...)` (`:946`), dumps through
  `coerce_nonfinite_to_none(agent_output.model_dump())` (`:951`; tuples
  handled, `scoring_utils.py:714`) to `run_output_{run_name}.json`
  (`:936`); on serialization failure writes a `partial_dict`
  (`:960-990`, `json.dump(..., default=str)` `:992`) and re-validates it
  (`:998`). **Both dicts must carry `metric_spec`** — the same "launch
  fact survives a failed tuner" rule the comment at `:965-972` states for
  `healthgate_mode`.
* **JSON round-trip finding (verified by probe at the anchor)**:
  `MetricSpec` is frozen + `extra="forbid"` with an ABSTRACT
  `scoreability: SerializeAsAny[ScoreabilityContract]`
  (`evaluation_metric.py:355-387`). `spec.model_dump()` emits the SUBCLASS
  contract fields, so **`MetricSpec.model_validate(spec.model_dump())`
  FAILS** (3 `extra_forbidden` errors) while
  `metric_spec_from_declaration(json.loads(json.dumps(spec.model_dump())))
  == spec` is `True` (`:657-668` — "the ONE sanctioned rebind"). Every
  persisted carrier of a `MetricSpec` must therefore route a mapping
  through `metric_spec_from_declaration` on validation (§3.2) —
  `HyperparamTuningOutput.model_validate(data)` (`workflows/
  model_exploration.py:259`, the CLI `:1866`, `core/resume.py:297`
  `model_validate_json`) all re-read outputs from JSON.
* **Reader side (the workflow)**: `HyperparamTuningOutput` has 46 fields,
  no `model_config` (extra ignored), NO `metric_spec`/`secondary_*`
  field (grep zero). Outputs feeding the interpreter: first iteration of a
  process → `seed_summaries = tuning_outputs_to_summaries(tuning_outputs)`
  (`:1812`, from `load_tuning_outputs_from_paths(source_paths)` /
  `load_tuning_outputs(...)` `:1804-1811` — in chain mode
  `resolved_source_paths` = seeds + every committed iteration's
  `run_output` path, `core/resume.py:1202,:1322`); later in-process
  iterations → `[latest_new_summary]` from the in-process `tune_output`
  (`:2687`, `:2716-2721`); all in-process outputs accumulate in
  `iteration_results` (`:2688`). `_synthetic_prior_iter_tune_output`
  (`:399-423`) builds PLACEHOLDER outputs for gate-exhaustion context —
  never fed to the interpreter, so never reconciled. The input is built
  inline at `:2097-2120`; the agent is constructed at `:2123-2126`;
  `_cap_knowledge_cache` (`:646-668`, sole call `:2729-2732`) ranks cache
  entries by `_stats.best_denoising_score`.
* **Record-borne identity**: `ExperimentRecord.metric_result:
  MetricResult | None` (`hyperparam_tuning.py:659-673`), `metric_refusal:
  NotScoreableResult | None` (`:674-683`), validator `:685-721`
  (exclusive; scalar agrees with `denoising_score` on success; per-sample
  agrees with `file_vector`); `training_diagnosis: TrainingDiagnosis |
  None` (`:403-411`); `status` Literal of 13 values (`:301-329`);
  `failure_type` (`:344`), `failure_reason` (`:433-448`), `gate_action`
  (`:449-464`), `health_gate_results` (`:465-468`), `is_trial` (`:502`).
  `tuning_output_to_model_run_summary` reads NONE of `metric_result /
  metric_refusal / training_history / training_diagnosis`.

### 2.5 The ad-hoc callers and the CI-exercised preflight

| caller | construction | 09a treatment |
|---|---|---|
| node CLI `main()` `:1832-1899` | loads ONE `run_output_{run_name}.json` → `HyperparamTuningOutput.model_validate` → `InterpretationInput(summaries=[summary], storage=…)` (`:1869-1875`) | C2: `metric_spec=reconcile_metric_spec([tune_output])`; a legacy output (None) fails closed by the input contract with a named error |
| `scripts/pr3_l2_calibration/preflight.py:88-135` (`run_arm`) and `runner.py:185-253` (`run_sample`) | summaries from `spec["tune_outputs"]()` — SYNTHETIC `HyperparamTuningOutput`s built in code by `scripts/pr3_l2_calibration/fixtures.py:120-131` (`_tune_output`) — then `InterpretationInput(summaries, storage, iteration, enable_structured_health_feedback, collapse_fingerprint_history, task_description[, runtime_vocab])` | **`tests/unit/scripts/test_pr3_l2p_preflight.py::test_preflight_all_invariants` runs `preflight.main()` in CI.** C2 (Q-09a-7, CONFIRMED with precise wording): the FIXTURE module stamps `metric_spec` on its synthetic outputs — **TEST-FIXTURE CONSTRUCTION ("simulated tuner-output writer / fixture stamping"), not a production MetricSpec derivation authority**; it calls the authoritative Step-06 constructor to create the expected stamped value; `scripts.pr3_l2_calibration` is imported ONLY by its sibling calibration scripts and tests (grep at the anchor) and must stay unreachable from production code; both entry points reconcile like the workflow. The production census (C2 acceptance) proves Step 09 adds ZERO production `derive_tidmad_metric` / `derive_tidmad_metric_spec` sites: the executable production sites remain the tuner `:541`, `execute_tools/denoising_score_single.py:180`, `core/sandbox_executor.py:2009` and the metric module's own composition (`evaluation_metric.py:716`); `tools/example_packs/projection.py:122` is tooling never imported by production. No fresh derivation at the entry points (R-09-3) |
| `agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py:29-58` `local_all_records(output, storage)` | `InterpretationInput(summaries=[summary], storage=storage)`; no production caller (re-exported by `protocols/__init__.py:34-39`; tests only) | C2: maps `output.metric_spec` → `metric_spec` (protocol completeness rule — no field silently dropped); its unit tests supply stamped outputs |

### 2.6 The carry-forward that does not exist (E2) and what it means for the version partition

`InterpretationInput.prediction_outcomes_history` (`interpretation.py:361-366`,
default `{confirmed:0, partial:0, refuted:0}`), `cumulative_information_gain`
(`:352-358`, `0.0`) and `vocab_link_confirmations` (`:369-374`) are never
passed by the workflow (`:2097-2120`), never carried by the in-process
loop (`:2724-2746` carries cache / proposal / vocab / fingerprints) and
never restored by `core/resume.py` (`RestoredState` `:101-214` restores
vocab, findings, rejections, exhaustions, proposal, cache, fingerprints,
chain incumbents — zero occurrences of the three names;
`run_one_iteration.py` forwards none). Consequence today: every
production `scientific_accuracy` is a one-outcome fraction and the
proposer's "Prediction Track Record" always says `N=1` (or `N=0` if no
prediction). The parent's §8 rule ("legacy dict carried UNCHANGED as the
v1 pool; NEW outcomes in an additive versioned structure; accuracy
computed only within the current version") therefore needs BOTH a
semantics decision that stays coherent with the proposer's rendering
(Q-09a-2) and a transport decision (Q-09a-1) — §3.4, §8.

### 2.7 The tests and guards that constrain 09a (inputs to §5)

* **Rebind + patch targets**: `patch("nodes.result_interpretation_agent.LLMBridge")`
  ×10 across 5 unit files (e.g. `test_interpretation_agent.py:131,178,432,1133,1322`;
  `test_dispatcher_wiring.py:87`; `test_health_feedback_outputs.py:86,94`;
  `tests/unit/sdsc_submission_scripts/test_health_feedback_workspace_cases.py:83`);
  `patch("workflows.model_exploration.ResultInterpretationAgent")` ×19;
  one `patch("nodes.result_interpretation_agent.open", …)`
  (`test_evolution_log_schema.py:173-176`). All keep resolving as long as
  the main module keeps importing `LLMBridge` and the evolution-log
  helpers stay in main.
* **Source-text pins on `run()`** (`test_interpretation_agent.py`):
  `:1260-1270 test_the_agent_partitions_before_any_llm_call` —
  `inspect.getsource(ResultInterpretationAgent.run)` must contain
  `"partition_for_aggregation(inp.summaries)"` and that index must precede
  `"synthesis_response"`; `:1245-1258` — `inspect.getsource(
  tuning_output_to_model_run_summary)` must contain
  `"formal_rec.scientific_authority"`. The first breaks when C1b moves the
  partition call into the extracted pre-computation (tuner precedent:
  `tests/helpers/tuner_source.py:82-101 tuner_lifecycle_source()`); the
  second survives a move (getsource follows the function object).
* **REC-3 schema field-list golden**: `tests/unit/agent/tune_ml_hyperparam_agent/
  test_step00_record_baselines.py:182-195` pins
  `list(HyperparamTuningOutput.model_fields)` (46) and
  `list(InterpretationOutput.model_fields)` (35) in
  `goldens/rec3_schema_field_lists.json` — every additive field on either
  model regenerates the golden IN THE SAME COMMIT (§17 rule 3 of the
  Step-00 harness; `tests/helpers/golden.py:11-12, :61-65`: tests never
  regenerate; intentional change ⇒ regenerate in the same commit with
  provenance). New fields are APPENDED so the existing ordered prefix is
  unchanged. No pin exists over `InterpretationInput` (21) or
  `ModelRunSummary` (30) field lists.
* **Prediction key-list pin**: `test_prediction_evaluation_join.py:166-187`
  (description "Contains:" == emitted keys).
* **Prompt goldens**: PB-0 (`per_model_prompt_{legacy,collapse}.txt`,
  `per_model_system_prompt.txt`, `test_health_prompt_parity.py`), flag-ON
  + PB-7 + PB-8 (`test_step00_prompt_goldens.py`) — must stay
  byte-identical through 09a; never regenerated.
* **Direction census**: `test_step06_c5_boundary_and_structure.py:113-148`
  (executed `"higher"`/`"lower"` constants — interpreter clean today) +
  `:160-183 NOT_REACHED_DIRECTION_CONSUMERS` (no interpreter row — removing
  interpreter literals does NOT red it) + `:196-223
  MIGRATED_TO_THE_ORDER_AUTHORITY` (tuner literals ABSENT and
  `"MetricOrder" in source`) — 09a EXTENDS the migrated list with the
  interpreter sites (C3). The tuner-scoped extremum census
  (`tests/unit/agent/tune_ml_hyperparam_agent/test_step07b_c2_order_consumers.py:499-516`,
  regex `\b(max|min|sorted)\s*\(` AND `denoising_score` on one line) is
  the model for the interpreter census (C3).
* **Node public boundary**: `tests/unit/nodes/test_node_public_boundary.py`
  — outward (`:96-117`) and inward (`:120-133`) halves are generic over
  every `nodes/<name>/<name>.py` package (the interpreter is enumerated);
  the acyclicity (`:136-169`) and `__all__`/`_COMPATIBILITY_REECPORTS`
  (`:172-198`) halves are HARDCODED to the tuner — C1b generalizes them to
  every node that has private modules. "Stub internals on the module that
  CALLS them" is documented prose (`ml_hyperparameter_tune_agent.md:1115-1122`),
  not enforced.
* **Single-file negative scan**: `tests/unit/agent/schemas/test_health_feedback_p3v1_audit.py:63-73`
  reads ONLY the main node file for `HealthFeedbackRetentionPolicy(` /
  `DEFAULT_HISTORY_WINDOW` absence — C1b widens it to the node package.
* **Degraded carry-forward pin**: `test_interpretation_agent.py:1186-1196
  test_carry_forward_metrics_preserved` (`cumulative_information_gain ==
  2.5`, `prediction_outcomes_history == {3,1,2}` pass through the degraded
  path) — UPGRADED by C4 under the version partition (§3.4).
* **Cache cap**: `tests/unit/workflows/test_knowledge_cache_cap.py` (6
  tests, `:24-92`) calls `_cap_knowledge_cache(cache, current_model=…)` —
  UPGRADED in C3 to pass `order`.
* **Evaluation-dict tests**: `test_vocab_feedback.py:30-160
  TestEvaluatePrediction` (SOTA 5.0: confirmed 5.5 / partial 4.8 / refuted
  4.0 / at-SOTA partial / override / `mean(file_vector[0:5]) == 2.0` /
  missing data ⇒ "partial" + "Could not compute"), `:168-318
  TestGenerateDiscoveries`; `test_prediction_evaluation_join.py:41-143`;
  `test_stability_filter.py:92-204` (Top-K = highest; None excluded; lex
  tiebreak; negative thresholds raise). For positive sota under `higher`
  the v1 and v2 bands AGREE on every one of these cases (the relative band
  `actual >= sota(1-m)` ⟺ `sota - actual <= m·sota` when `sota > 0`), so
  only the uncomputable case and the new `order`/`bound_metric_id`
  parameters change these tests.
* **Pseudo accumulation (not CI)**: `tests/integration/workflows/
  test_vocab_accumulation.py:886-1110` carries the pool across two agent
  runs by hand and asserts v1 pooling (`{refuted:1}` then
  `{confirmed:1, refuted:1}` / 0.5) — UPGRADED by C4 (it must carry the
  `_by_semantics` dicts between its hand-chained runs and assert the v2
  pool + untouched legacy dict), run manually and recorded in the ledger
  (never added to CI).
* **Artifacts**: the preserved `step07b_gate1_postrefactor` run outputs
  have NO `metric_spec` and every record carries `metric_result`
  (`{metric_id: "tidmad_denoising_score", direction: "higher", …}`); the
  digest has the 35 REC-3 keys and `prediction_evaluation.outcome ==
  "partial"` for an uncomputable metric string (parent §2.4). Real
  artifacts are NOT test inputs (machine-local); the differential oracle
  is synthetic and portable.

### 2.8 Authorities consumed (landed; unchanged by 09a)

`MetricSpec` / `MetricResult` / `NotScoreableResult` / `MetricDirection =
Literal["higher","lower"]` / `metric_spec_from_declaration`
(`execute_tools/evaluation_metric.py:355, :390, :418, :110, :657`);
`MetricOrder` (`execute_tools/metric_order.py:59-247`: `is_better`,
`is_at_least`, `best` (ties → FIRST, raises on empty), `worst`, `rank`
(1 + #strictly better), `worst_sentinel`/`best_sentinel`,
`toward_better`/`toward_worse`, `direction_words`, banner symbols) —
**09a adds NO method to it**; `TrainingDiagnosis` (frozen; `state`
`ok|absent|invalid`, `validation_state` `present|absent`;
`agent/schemas/training_diagnosis.py:39-40, :68-135`); `RoundHealth` /
`classify_round_provenance` / `build_gate_outcomes` /
`build_collapse_fingerprint` (`agent/schemas/health_feedback.py`);
`partition_for_aggregation` (`execute_tools/scientific_aggregation.py:152`);
shared test fixtures `tests/helpers/metric_fixtures.py` (`shipped_spec`,
`direction_only_spec` — TIDMAD spec with `direction="lower"`,
`accuracy_like_spec`, `error_like_spec`). Pack declarations
`examples/oxford_iiit_pet/declared/metric_{accuracy,macro_f1}.json`,
`examples/davis_future_prediction/declared/metric_{mse,psnr,mae}.json`
(verified at the anchor: all five parse through
`metric_spec_from_declaration` to `PresenceScoreabilityContract` specs
with the expected ids/directions); 07a L1 diagnosis fixtures
`examples/<pack>/expected/training_diagnosis_l1_fixture.json` (label
`l1_fixture`); pack governance (`tests/unit/examples/test_pack_governance.py`:
no production import of `examples`; `declared/` sets pinned in
`test_oxford_iiit_pet_pack.py:173-179` / `test_davis_future_prediction_pack.py:204-205`
— 09a adds files ONLY under `expected/`).

## 3. Design (frozen for this child)

### 3.1 Node-local decomposition (C1b — behaviour-preserving, FIRST)

```text
nodes/result_interpretation_agent/
    result_interpretation_agent.py   PUBLIC  (unchanged role) — prompts + builders (09b's),
                                      ResultInterpretationAgent.run() lifecycle,
                                      _dedup_promoted, evolution-log I/O, main(),
                                      deliberate re-exports of moved names
    result_interpretation_agent.md   PUBLIC
    evidence.py      PRIVATE — persisted evidence → typed projections:
                     tuning_output_to_model_run_summary, _required_denoising_score,
                     _round_ordering, _round_health, _collect_health_evidence
                     (+ C6: identity / diagnosis / secondary / failure projections;
                      + C2: reconcile_metric_spec)
    ordering.py      PRIVATE — the run-scoped ordering boundary:
                     precompute_evidence(summaries, cache, effective_types[, order])
                       -> PrecomputedEvidence (frozen carrier: per_model_best / best_valid /
                          raw_best_health_validity / worst / formal (authority-filtered) /
                          best_config, overall_best / best_valid / worst scores + configs,
                          total_experiments, per_model_summary_input, aggregation_scope)
                     collect_enriched_fields(summaries, cache, per_model_summary_input)
                       -> EnrichedFields (score tables / params / training segments)
                     (+ C2: bind_run_order(inp) -> MetricOrder | None)
    prediction.py    PRIVATE — prediction grammar + band + accounting:
                     evaluate_prediction, _compute_metric, the legacy alias table
                     (MOVED from nodes/interpretation_helpers.py), and the E.4/E.7
                     accounting extracted from run() (:1548-1575)
                     (+ C4: sign-safe band, semantics versions, pools)
```

Rules (all executable, §4.2): plain module names (E3); every private
module imported EAGERLY by the main module (the rebind, §2.1); one-way
graph `main → {evidence, ordering, prediction}`, `ordering → evidence`
permitted (shared carriers) — never the reverse, never a private module
importing main; no `utils`/`helpers`/`common` module; `MetricOrder` does
not move. Blocks that STAY inline in `run()`: effective types +
descriptions (`:909-941`), the health merge (`:1070-1080`), Phase 1,
Phase 2, Phase C vocabulary, output build, persist, degraded fallback —
09a does not modify their semantics, and extracting LLM/vocab machinery is
outside the parent's §13a scope ("the deterministic evidence / ordering /
projection logic 09a is about to modify"). `collect_enriched_fields` is
CALLED from the same position inside the try-block (a malformed cached
table still reaches the degraded path). The moved `evaluate_prediction` /
`_compute_metric` leave NO back-edge from `nodes/interpretation_helpers.py`
into the node package: their external importers are tests only (§2.1) and
are updated (disposition MOVE) — the parent's "thin re-exports" clause
concerns names external PRODUCTION code imports from the MAIN module
(`tuning_output_to_model_run_summary`: `workflows/model_exploration.py:111-114`,
`scripts/pr3_l2_calibration/{preflight.py:105-108, runner.py:193-196}`,
`agent/schemas/protocols/ml_model_tune_to_ml_result_interp.py:26`,
`__init__.py:29`), which stays re-exported. Intended end state after 09a +
09b (parent §13a): main = lifecycle + degraded fallback + persistence +
CLI; private = evidence · ordering/prediction · (09b) rendering moved out.

### 3.2 The run `MetricSpec` transport (C2)

1. **Carrier type (declared ONCE, in the metric module)**:
   `MetricSpecField = Annotated[MetricSpec, BeforeValidator(<mapping →
   metric_spec_from_declaration>)]` in `execute_tools/evaluation_metric.py`
   beside `metric_spec_from_declaration` (`:657`) — a MetricSpec field that
   accepts its own dumped declaration (the §2.4 round-trip finding). The
   validator passes `MetricSpec` instances and `None` through untouched and
   routes a `Mapping` through the ONE sanctioned rebind; anything else is
   left to pydantic to reject. (Exact alias spelling confirmed at C2
   against name collisions; this is the only executable change to the
   metric module, additive.)
2. **Writer**: `HyperparamTuningOutput.metric_spec: MetricSpecField | None
   = None` (appended; description names Step 09a and "None on outputs
   predating the field"). `finalize_run_output` writes
   `bindings.run_metric.spec` into `agent_output_dict` and its
   `.model_dump()` into `partial_dict` — ONE writer function, both branches
   (the healthgate_mode rule, `records.py:965-972`).
3. **Reconciliation (node-owned helper, workflow-called)**:
   `reconcile_metric_spec(outputs: Sequence[HyperparamTuningOutput]) ->
   MetricSpec | None` in `evidence.py` (re-exported publicly like the
   summary builder): all present specs must be EQUAL (frozen-model
   equality, scoreability included) ⇒ that value; any output lacking a
   spec while another carries one, or two unequal specs ⇒
   `InterpretationContractError` naming every offending `run_name` /
   `model_type` and both specs; all `None` ⇒ `None` (a NAMED absence the
   input contract then judges). The workflow reconciles over every output
   this process has fed or will feed the interpreter —
   `[*tuning_outputs, *iteration_results]` (§2.4) — never over the
   synthetic gate-exhaustion placeholders — and passes the value as
   `InterpretationInput.metric_spec`.
4. **Input contract**: `InterpretationInput.metric_spec: MetricSpecField |
   None = None` (appended) + ONE `model_validator(mode="after")`:
   (a) if the input carries ORDERING EVIDENCE — any summary score field
   (`best_denoising_score`, `best_valid_denoising_score`,
   `worst_denoising_score`, `formal_score`, `best_valid_formal_score`, a
   non-None `round_scores` entry) or any cache entry's `_stats`
   `best_denoising_score` / `best_valid_denoising_score` /
   `worst_denoising_score` / `formal_score` not None — and `metric_spec is
   None` ⇒ `ValueError` naming the first evidence-bearing summary/cache
   key (parent §4a: no silent higher-is-better); cold-start and scoreless
   inputs accept `None`; (b) every summary whose `metric_identity` is
   present must equal the spec's `id` AND `direction` ⇒ else `ValueError`
   naming both (parent §4a, fail closed BEFORE ordering, prediction and
   rendering — construction time is the earliest point). The schema is the
   completeness contract (CLAUDE.md) and the protocol must map the field
   (§2.5). Q-09a-4 confirms this placement.
5. **Binding**: `ordering.bind_run_order(inp) -> MetricOrder | None` —
   `MetricOrder(inp.metric_spec)` when present; `None` only when the
   validator admitted a spec-less input (cold start / scoreless). Called
   once per `run()`, before the pre-computation, after the cold-start
   branch.
6. **Digest echo**: `InterpretationOutput.metric_identity: MetricIdentity
   | None` (appended; `MetricIdentity(metric_id, direction)` is a new
   frozen two-field model in `agent/schemas/interpretation.py`) — the
   identity actually used for ordering this iteration; `None` ONLY on
   cold-start / scoreless inputs (named absence; reachability-tested).
   Threaded into BOTH the healthy and degraded dicts.
7. **Summary identity**: `ModelRunSummary.metric_identity: MetricIdentity
   | None` (appended) — the builder projects it from the records' primary
   `metric_result` (all scored records in one output must agree, else the
   BUILDER raises `InterpretationContractError` — a corrupt output fails
   closed before any consumer); `None` when no record carries a
   `metric_result` (pre-Step-06 outputs).
8. **Legacy consequence (stated, not a question)**: outputs written before
   09a carry no spec; a chain resumed ACROSS the 09a boundary fails closed
   at its next interpretation with a named refusal (parent §2.11, R-09-3);
   a fresh chain is required. The ad-hoc callers (§2.5) get the spec from
   their outputs; the calibration FIXTURE stamps it.

### 3.3 Every interpreter ordering consumer onto `MetricOrder` (C3)

The 21-row mapping in §2.2 is the specification. Parameter threading:
`precompute_evidence(..., *, order: MetricOrder | None)` and
`tuning_output_to_model_run_summary(output, *, order: MetricOrder | None)`
take the run order as a REQUIRED keyword (no default); `None` is admitted
ONLY for a scoreless input/output — the first ranking that would need a
direction with `order is None` raises `InterpretationContractError` (the
builder ranks records itself and is a public function called by the
workflow, the CLI, the calibration scripts and the protocol BEFORE any
`InterpretationInput` exists, so it carries its own fail-closed clause;
the input validator §3.2-4 covers hand-built summaries). The workflow
therefore reconciles FIRST (`reconcile_metric_spec(tuning_outputs)` at
`:1804-1812`, then incrementally over `[*tuning_outputs,
*iteration_results]` before each in-process summary at `:2716`) and
builds summaries with `order=MetricOrder(run_metric_spec)`.
`select_active_models(..., *, order)` and `generate_discoveries(..., *,
order)` (helpers file; semantic owner 09a, location unchanged — parent
§7); `_cap_knowledge_cache(cache, current_model, *, order, max_entries=5)`
(workflow file; semantic migration only — Q-09-3); `_render_health_summary_
section(summary, *, order)` and `_build_per_model_prompt(..., order:
MetricOrder | None = None)` raising `ValueError` when
`structured_health_feedback` is ON and `order` is `None` (flag-OFF callers
and every prompt golden need no order; bytes unchanged). Tie semantics
are pinned by tests that fail on drift: `best` ties → FIRST (`max`
semantics), `rank`-keyed stable sorts reproduce `(-score, mt)` and
`reverse=True` orders including `None`-last. Under the shipped TIDMAD spec
every migrated site returns the IDENTICAL value/order (the differential
oracle and all prompt goldens stay byte-identical at C3); under
`direction_only_spec()` (lower) every site inverts (hand-computed tests).
The discoveries band (`:455`) becomes `abs(best - sota) <= 0.05 *
abs(sota)` (sign-safe; width unchanged, Q-09a-5) and its "(+delta)" text
uses `abs(best - sota)` (identical bytes for TIDMAD improvements).
**Census (C3)**: an AST census over the interpreter surface
(`nodes/result_interpretation_agent/*.py`, `nodes/interpretation_helpers.py`
and the `_cap_knowledge_cache` function source) with planted-offender
proof: no `Compare` with `Gt/Lt/GtE/LtE` whose operand source mentions a
golden-score token (`denoising_score|best_score|worst_score|sota|_score`)
and no `max(`/`min(`/`sorted(`/`.sort(` whose arguments mention one,
outside `execute_tools/metric_order.py`; allow-listed non-score
comparisons are enumerated (lengths, thresholds, round counts, seconds);
anti-vacuity: the census must VISIT the known call sites (count of
`order.` consumers ≥ the §2.2 row count it migrated) and turn RED on an
untracked planted offender. Plus `MIGRATED_TO_THE_ORDER_AUTHORITY`
extended with the interpreter literals (asserted ABSENT + `"MetricOrder"`
in each migrated file; the workflow row keeps its NOT_REACHED literal).

### 3.4 Prediction semantics v2 (C4) — grammar, band, `unevaluated`, versions

**Grammar resolution** (`prediction._compute_metric(metric, results, *,
bound_metric_id)` → `(value, resolution)`):

| `metric` string | resolution | value |
|---|---|---|
| `== bound_metric_id` (the run spec's `id`) | `bound_id` | `results["best_denoising_score"]` (the D1-frozen PRIMARY scalar name) |
| in the LEGACY alias table (`denoising_score`, `best_score`, `overall denoising score`, `score`, `best_denoising_score`) | `legacy_alias` — read-only compatibility for PRIOR predictions (R-09-5); the table is frozen, never grown, and documented as legacy | primary scalar |
| `mean(file_vector[N:M])` / `file_vector[N]` with per-sample evidence present | `per_sample_slice` / `per_sample_index` | as today |
| per-sample form with NO per-sample evidence | `per_sample_unavailable` | `None` |
| anything else | `unrecognized` | `None` |

The DEFAULT metric when the prediction omits `metric` is the bound id (was
the literal `"denoising_score"`). Predictions are AUTHORED by the proposer;
constraining NEW predictions to the bound id is a proposer prompt/schema
matter (09b / Step 10), not 09a's — 09a evaluates honestly and records the
resolution.

**Band (parent §13 ¶1, FROZEN; `evaluate_prediction(prediction,
actual_results, *, order, bound_metric_id, current_sota=None,
partial_margin=0.05)`)**:

```text
distance   = abs(actual - sota)
band_width = partial_margin * abs(sota)
if actual is None or sota is None:      outcome = unevaluated; information_gain = 0; NOT counted
elif order.is_better(actual, sota):     outcome = confirmed;   information_gain = distance
elif distance <= band_width:            outcome = partial;     information_gain = 0
else:                                   outcome = refuted;     information_gain = 0
```

`boldness` unchanged (`abs(predicted - sota) / max(abs(sota), 1e-6)`;
`0.0` when unevaluated). `delta_from_sota` stays SIGNED (`actual - sota`,
`None` when unevaluated). **Record shape UNIFORM across branches**:
`metric, metric_resolution, predicted_value, actual_value, current_sota,
delta_from_sota, outcome, boldness, information_gain, notes (str | None),
prediction_evaluation_semantics` — the `InterpretationOutput.prediction_
evaluation` description's "Contains:" list is updated in the same commit
(the §2.7 pin). Semantics ids declared ONCE in `prediction.py`:
`PREDICTION_SEMANTICS_SIGNSAFE_V2 = "metric_order_signsafe_v2"`,
`PREDICTION_SEMANTICS_LEGACY_V1 = "legacy_v1"` (absent ⇒ legacy).
Hand-computed matrix (tests): higher/positive, higher/negative
(TIDMAD: sota −2.55, actual −2.43 ⇒ confirmed gain 0.12; −2.60 ⇒ distance
0.05 ≤ 0.1275 ⇒ partial — REACHABLE now; −2.90 ⇒ refuted), lower/positive
(DAVIS: sota 0.0174, actual 0.0165 ⇒ confirmed gain 0.0009; 0.0178 ⇒
distance 0.0004 ≤ 0.00087 ⇒ partial; 0.0190 ⇒ refuted),
lower/negative, equality (⇒ partial), zero sota (band 0: equal ⇒ partial,
worse ⇒ refuted, better ⇒ confirmed), just-inside/just-outside,
uncomputable (⇒ unevaluated, not counted, no discovery).

**`unevaluated` downstream (E5)**: `generate_discoveries` emits NO outcome
discovery for `unevaluated` (explicit branch — an unevaluated prediction
is not a finding); `update_vocab_link_confirmations` is unaffected
(`== "confirmed"`); the E.4 counter ignores it; the digest's
`prediction_evaluation.outcome == "unevaluated"` names it.

**Version partition + accounting (parent §8; Q-09a-2 RULED — exact
per-field semantics, FROZEN; implementation may not reinterpret)**:

| field (Input ⇄ Output, same name) | semantics | written by 09a |
|---|---|---|
| `prediction_outcomes_history: dict[str,int]` (EXISTING) | the **legacy / v1 three-bucket pool** — carried forward byte-identically; **never incremented by 09a**; old persisted digests never rewritten | copied from the input (healthy AND degraded paths) |
| `prediction_outcomes_by_semantics: dict[str, dict[str,int]]` (NEW, appended; default `{}`) | version-keyed comparable pools; **`["metric_order_signsafe_v2"]` owns the v2 `confirmed` / `partial` / `refuted` counts** — the ONLY dict 09a increments; a legacy input simply has no v2 key yet | input copy + this iteration's v2 outcome |
| `prediction_evaluation.outcome == "unevaluated"` | recorded on the INDIVIDUAL evaluation only; **counted in NEITHER comparable pool**, never a discovery | — |
| `scientific_accuracy: dict[str,float] or None` (EXISTING) | fractions over the **v2 pool ONLY** (`None` while that pool is empty); **provenance-labelled** by `prediction_evaluation_semantics` | computed from `prediction_outcomes_by_semantics[V2]` |
| `prediction_evaluation_semantics: str` (NEW, appended; Output) | the semantics id the accuracy/v2 pool of THIS digest was computed under — `"metric_order_signsafe_v2"`; legacy digests lack the key ⇒ `legacy_v1` (never rewritten) | constant V2 |
| `prediction_pool_sizes: dict[str,int]` (NEW, appended; Output) | explicit legacy-pool provenance the parent §8 demands ("states the version and the legacy pool's size"): `{"legacy_v1": sum(prediction_outcomes_history), "metric_order_signsafe_v2": sum(v2 pool)}` — so no reader can mistake v1+v2 for one comparable statistic | derived |
| `cumulative_information_gain: float` (EXISTING) | the **legacy accumulated value — preserved, never pooled with v2**; carried forward unchanged (09a adds nothing to it) | copied from the input |
| `cumulative_information_gain_by_semantics: dict[str,float]` (NEW, appended; default `{}`) | **`["metric_order_signsafe_v2"]` = the v2 running sum** of `information_gain` (confirmed only); no single scalar anywhere means legacy + v2 | input copy + this iteration's gain |

* Accounting: `confirmed|partial|refuted` increments ONLY the v2 dict and
  adds `information_gain` ONLY to the v2 sum; `unevaluated` touches
  nothing; the legacy dict and legacy scalar pass through unchanged.
  No re-basing exists (the structure itself is versioned), so the degraded
  path simply copies every pool/sum/dict forward unchanged — the existing
  `test_carry_forward_metrics_preserved` (legacy `{3,1,2}` / `2.5` pass
  through) stays GREEN (KEEP) and is EXTENDED for the two `_by_semantics`
  dicts.
* Honesty statement (Q-09a-3, CONFIRMED): 09a makes NO proposer
  prompt-template/protocol change; but the proposer's existing renderer
  (`ml_model_proposal_agent.py:1146-1165`) reads `scientific_accuracy`
  (now v2-only), `cumulative_information_gain` (legacy) and
  `prediction_outcomes_history` (legacy; its sum is the rendered `N`).
  The rendered next-iteration CONTENT therefore changes deterministically
  — and `N` comes from the LEGACY pool while the fractions come from the
  v2 pool. That is a declared, frozen consequence of the per-field rule
  ("no prompt-template/protocol change; deterministic content change only
  through the explicitly frozen prediction-semantic correction"). **If
  implementation judges that an HONEST v1/v2 distinction in that rendering
  REQUIRES a proposer template edit → STOP and return** — 09b prompt work
  must not move into 09a silently.
* Transport (Q-09a-1 = A, NARROW): the four carried values
  (`prediction_outcomes_history`, `prediction_outcomes_by_semantics`,
  `cumulative_information_gain`, `cumulative_information_gain_by_semantics`)
  travel ONLY through the existing canonical lifecycle — C5 (§4.6): the
  workflow loop carry and the existing `RestoredState` latest-wins restore
  (the V19-PR3 fingerprint-history precedent); no new memory store, no
  second restore path, no resume redesign.

### 3.5 Evidence projection (C6) — identity, diagnosis, secondaries, failure counts

All projections are DETERMINISTIC reads of persisted record fields, threaded
into BOTH digest dicts, task-free, keyed by EXISTING authority
vocabularies (no new closed enum — parent §5):

* `ModelRunSummary.best_training_diagnosis` / `formal_training_diagnosis:
  TrainingDiagnosis | None` — verbatim from `best_rec` / `formal_rec`
  (the records whose best/formal scores the summary already exposes; the
  "one per role" of parent §4). Cached models keep nothing new (09b renders
  from summaries).
* `ModelRunSummary.secondary_metrics: list[SecondaryMetricEvidence] = []`
  with `SecondaryMetricEvidence(spec: MetricSpecField, result:
  MetricResult | None = None, refusal: NotScoreableResult | None = None)`
  (frozen; validator: result and refusal never both; `status` property
  `scored | refused | unavailable` — a declared-but-absent secondary is a
  NAMED ABSENCE with its own `spec.id`/`direction`). **In 09a the builder
  never populates it**: there is no record-level carrier to read until
  Step 10 lands `ExperimentRecord.secondary_metric_results /
  secondary_metric_refusals` and `HyperparamTuningOutput.secondary_metric_
  specs` (parent §4b; Q-09-7 = B), and reading undeclared keys would be a
  hidden contract. L1 fixtures attach carrier-shaped Step-06 result
  objects directly (§3.6). Digest: `per_model_secondary_metrics: dict[str,
  list[SecondaryMetricEvidence]] = {}` (present-when-present; empty in
  production until Step 10). Census: no `secondary_metrics` reference
  inside any `MetricOrder`-consuming function (parent §18-7, landed early
  here with a planted offender), and a behavioural test: mutating every
  secondary value changes NO ordering output.
* `ModelRunSummary.failure_counts: RecordFailureCounts | None` (frozen
  model): `records_total`; `status_counts: dict[str,int]` over
  `ExperimentRecord.status` (13 existing values); `diagnosis_state_counts`
  over `TrainingDiagnosis.state` for records carrying a diagnosis +
  `diagnosis_missing` (no diagnosis object); `validation_state_counts`
  over `validation_state`; `metric_refusal_count` + `refusal_contract_ids:
  dict[str,int]` (`verdict.contract_id`, opaque string — never parsed);
  `gate_action_counts` (`RoundHealth.gate_action`, `None` ⇒ `"none"`) and
  `health_provenance_counts` (`RoundHealth.provenance`). Digest:
  `per_model_failure_counts: dict[str, RecordFailureCounts]` for NEW
  summaries, plus the additive `_stats["failure_counts"]` cache key so
  cached models keep their counts (the `round_health_counts` precedent,
  `:1204`).
* `ModelRunSummary.metric_identity` + `InterpretationOutput.metric_identity`
  land in C2 (needed by §4a).

### 3.6 Three-task L1 evidence (C7)

Q-09-5 / parent §10: pack `expected/`, L1 synthetic contract-level
labelling, provenance naming the authorities used, zero production
dependency on `examples/`. Shape: `examples/oxford_iiit_pet/expected/
interpretation_evidence_l1_fixture.json` and `examples/davis_future_
prediction/expected/interpretation_evidence_l1_fixture.json` —
`{"_fixture": {"label": "l1_fixture", "kind": "interpretation_evidence",
"note": "NOT a real tuning output — L1 synthetic contract-level
interpretation evidence; the production workflow does not evaluate
secondary metrics (Step 10)"}, "tuning_output": <HyperparamTuningOutput
JSON: 3 minimal records (exp_id/status/model_type/timestamp/params +
denoising_score + metric_result + training_diagnosis from the pack's 07a
L1 diagnosis fixture + is_trial) with metric_spec = the pack's declared
primary>, "secondary_metrics": [<SecondaryMetricEvidence JSON built from
the pack's declared secondary specs + carrier-shaped MetricResult /
absence>], "prediction": {...}}`; TIDMAD inline (the synthetic
differential fixture: `tidmad_denoising_score` higher, per-sample present,
no secondaries). Test `tests/unit/examples/test_step09a_interpretation_
evidence_rung.py`, parametrized `tidmad | pets | davis`, drives the REAL
`tuning_output_to_model_run_summary(order=)`, `precompute_evidence`,
`evaluate_prediction`, with expectations HAND-COMPUTED as literals
(never read back): Pets (`accuracy` higher) — best/worst/formal selection,
identity `accuracy/higher` agrees with the spec, secondary `macro_f1`
(higher) SCORED present-when-present; DAVIS (`mse` lower) — best is the
SMALLEST, worst the largest, identity `mse/lower`, prediction band
confirmed/partial/refuted on the §3.4 values, secondaries `psnr` (higher)
scored + `mae` (lower) declared-but-unavailable (named absence); TIDMAD —
higher, negative sota, the now-reachable partial, no secondaries; all
three — a spec/identity MISMATCH fixture refuses at construction, and
flipping every secondary value leaves every ordering output identical.
Pack `STATUS.md` rows name the new fixture as L1 synthetic (no tuner /
workflow integration; secondaries not evaluated in production — Step 10).

### 3.7 What 09a does NOT change (invariants)

Prompt templates and prompt bytes for any fixed input; the node's public
identity (`ResultInterpretationAgent`, `run(InterpretationInput) ->
InterpretationOutput`, `main()` CLI arguments); phase order; the
degraded-mode contract; the digest path `interpretation_{run_name}.json`
and the evolution log; `__init__.py` re-exports; D1 field names;
`MetricOrder`'s API; metric arithmetic; tuner policy; Health; the
consolidator; vocabulary machinery (except the `unevaluated` branch and
the `order` parameter of `generate_discoveries`); retention numbers
(cache cap 5, windows); `core/resume.py:436` / chain incumbents /
dashboard literals; `evaluation.py`; any `examples/` dependency in
production (none).

### 3.8 Extensibility matrix for the NEW surfaces (parent §9 A–F)

| surface | A semantic | B binding | C discovery | D config | E registration | F vocabulary |
|---|---|---|---|---|---|---|
| `MetricSpecField` carrier + `HyperparamTuningOutput.metric_spec` + `InterpretationInput.metric_spec` | OPEN (any `MetricSpec`) | value transported from the tuner's ONE binding; reconciled | n/a | none new | none | none |
| input contract validator (§3.2-4) | framework rule | n/a | n/a | n/a | none | none |
| private node modules | structure only | n/a | n/a | n/a | none | none |
| `MetricIdentity`, `SecondaryMetricEvidence`, `RecordFailureCounts` | typed, task-free; keys = existing authority vocabularies; ids opaque | record-borne / fixture-supplied | n/a | n/a | none | none new (no closed enum) |
| semantics ids + versioned pool fields (`prediction_outcomes_by_semantics`, `cumulative_information_gain_by_semantics`, `prediction_pool_sizes`, `prediction_evaluation_semantics`) | framework version metadata; version-keyed dicts (no per-task growth) | n/a | n/a | n/a | none | the two version ids only |
| `PredictionMemory` carrier + `RestoredState.prediction_memory` + `load_latest_prediction_memory` (C5) | carrier of four digest fields; the digest stays the ONE store | existing canonical latest-wins path | n/a | n/a | none | none |

No new loader, registry, task-name branch, per-task table, derivation
site, memory store, or central config content. Verdict: the parent's PASS
is preserved.

## 4. Commit decomposition

### 4.0 Standing rules

* Each commit's first item is a bounded re-read of the exact functions it
  edits, at the implementation head; ambiguity or larger scope than this
  design assumes → **STOP and ask before changing the plan**.
* `[ ]` = not done; `[x]` only with recorded evidence (test counts, wall
  time, log path) in §10. **Every box below was `[ ]` at freeze** (they now
  carry real implementation state, per §0). Pytest verdicts
  come from complete log files (`> log 2>&1; rc=$?`), never a wrapper's
  exit status.
* Before EVERY commit: stop and show the exact diff summary, staged file
  list, the tests run, and any deviation from this design; wait for
  permission (the operator's standing per-commit rule for this child).
  pytest may run freely; no real-LLM / real-training runs exist in 09a.
* Planner/prompt exposure and production-default changes are OUTSIDE these
  commits; a prompt-golden byte delta at any commit is a STOP.
* Out of scope for every commit: secondary evaluation / loader / binding /
  record carrier; a new metric derivation site; task-name branches; prompt
  templates/renderers/task blocks (09b); tuner policy; Step 10 workflow
  composition; `core/resume.py:436` and chain incumbents.
* The REC-3 schema golden regenerates ONLY in the commit that appends a
  field, with the delta named in the commit message and §10.
* Commit messages name the milestone (`Step 09a C<n>: …`); git commits may
  be split at clean boundaries (`-code` / `-tests` / `-docs`) when a
  planned commit would otherwise be too large, preserving the last split's
  definition of done.

---

**Milestone M1 = commit C1 = the behaviour-preserving node-local
extraction (parent §13a), landed as two git commits at a clean boundary:
C1a captures the differential oracle from the UNMODIFIED tree (test-only,
so the parity claim has a measured baseline), C1b performs the extraction
against it. No semantic change precedes C1b; nothing in 09a precedes M1.**

### 4.1 C1a — the differential digest oracle (test-only; first half of M1)

**Goal.** A committed, CI-portable, FIXED interpretation input whose full
deterministic digest and LLMBridge call sequence are pinned BEFORE any
production line moves, so C1b's "behaviour-preserving" is measured, not
asserted, and C2–C6's ALLOWED deltas are DECLARED diffs against a golden.
It belongs first because every later commit's parity claim is defined
against it (parent §16: differential ownership, never "same full digest").

**Scope.** NEW `tests/unit/agent/result_interpretation_agent/
_step09a_fixture.py` (shared deterministic fixture builder), NEW
`test_step09a_c1a_differential_oracle.py`, NEW goldens
`goldens/step09a_differential_digest.json` + `goldens/step09a_differential_
llm_calls.json` (labels + sha256 of system/user prompts per call, in
order). Zero production changes. Depends on nothing.

**Implementation plan.**
- [x] Re-read `test_dispatcher_wiring.py:87-227` (label dispatch for
      `interpretation.per_model` / `interpretation.synthesis` /
      `cache_consolidator.list_merge`) and `test_step00_prompt_goldens.py:
      100-137` (`BoundaryRecorderBridge`) to reuse the stub/recording
      idioms; reuse `_gate_result/_record/_output` from
      `test_round_health_summary.py:22-57` for health-bearing records.
- [x] Fixture: TWO new TIDMAD-shaped `HyperparamTuningOutput`s → summaries
      through the REAL `tuning_output_to_model_run_summary` (success /
      skipped / collapse records; one with `score_table` + `file_vector`;
      persisted gate evidence on one record; `metric_result` on success
      records; `is_trial` mix with a formal record); ONE legacy-flat cache
      entry and ONE modern `CacheEntry`-shaped entry (exercises
      `consolidate`); `previous_proposal` with a COMPUTABLE, CONFIRMED
      prediction (`metric: "denoising_score"`, `current_value: -2.55`,
      actual best −2.43 ⇒ v1 ≡ v2), inherited components, vocab links and
      candidates below promotion; `prediction_outcomes_history =
      {confirmed:1, partial:0, refuted:1}`, `cumulative_information_gain =
      0.3` (so C4's partition delta is VISIBLE and declared);
      `enable_structured_health_feedback=False`; storage = `tmp_path`.
      — `tests/unit/agent/result_interpretation_agent/_step09a_fixture.py`
      (509 lines); THREE model types, see §10.1 finding F-09a-1.
- [x] Stub bridge returning canned JSON per label; record every
      `generate` call (label, sha256(system), sha256(user)).
      — `RecordingStubBridge`; also records `emit_marker` calls (§10.1).
- [x] Assert the digest (`json.loads(output.model_dump_json())`) and the
      call sequence against the two goldens via `tests/helpers/golden.py`
      (the harness NEVER regenerates — §17 rule 1; a missing golden fails
      with capture instructions, so the two goldens are captured ONCE by a
      one-off manual run against the UNMODIFIED production code at the C1a
      base, committed with `_captured_at` provenance in this same commit).
      — captured at `a325f33b`, provenance recorded in both goldens.
- [x] Assert the on-disk `interpretation_<run>.json` equals the in-memory
      digest (persistence parity).

**Validation plan.**
- [x] Unit: the oracle test (green on the unmodified tree); a second run is
      byte-identical (determinism). — 8 passed, twice; the repeatability
      test runs the fixture through TWO different workspaces.
- [x] Negative: a planted one-field perturbation of the digest (test-local
      mutation of the expected JSON) fails with a field-level diff message.
      — `TestTheOracleIsStrict`, two probes (digest field + prompt digest).
- [x] Backward-compat: nothing else changes. — `git status` shows FOUR
      untracked test-only files and zero modified production files.

**Acceptance criteria.**
- [x] `goldens/step09a_differential_digest.json` exists with `_captured_at`
      provenance naming the base commit; `step09a_differential_llm_calls.json`
      lists exactly the per-model / list-merge / synthesis calls the fixture
      causes (count asserted in the test, hardcoded).
- [x] The oracle is green twice in a row from a clean tree; the perturbation
      probe is red.

**Failure and edge cases.** Non-deterministic content (timestamps, tmp
paths) must NOT appear in the digest — asserted by the determinism run; if
one appears, normalize at the fixture (never in production).

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent/test_step09a_c1a_differential_oracle.py -q > /tmp/09a_c1a.log 2>&1; rc=$?` — **rc=0, 8 passed in 9.21s** (re-run after formatting: 8 passed in 7.81s, `/tmp/09a_c1a_final.log`).
- [x] `ruff check` + `ruff format --check` on the new files. — check clean; format reformatted the test module once, then `ruff format --check` over the whole directory: 19 files clean.

**Commit boundary.** Test-only; reviewable as "is this the right fixed
input and is the oracle strict enough?"; no production file touched.

---

### 4.2 C1b — behaviour-preserving node-local extraction (parent §13a, M1)

**Goal.** The deterministic evidence / ordering / prediction logic 09a is
about to modify lives in private node-local modules behind typed
boundaries, `run()` reads as a lifecycle, and NOTHING observable changes
(oracle + every golden + kwargs identical). First semantic milestone per
the parent's freeze; nothing else in 09a may precede it.

**Scope.** NEW `nodes/result_interpretation_agent/{evidence,ordering,
prediction}.py`; `result_interpretation_agent.py` (moves + eager imports +
`__all__` re-exports + `run()` calls the boundaries at the SAME positions);
`nodes/interpretation_helpers.py` (REMOVE `evaluate_prediction`,
`_compute_metric`, `_DENOISING_SCORE_ALIASES` — moved); tests: MOVE
imports in `test_vocab_feedback.py:19`, `test_prediction_evaluation_join.py:38`;
UPGRADE `test_interpretation_agent.py:1260-1270` (source pin → reachability
with a recording `partition_for_aggregation` patched on `ordering` — the
module that CALLS it — and a recording bridge; assert partition before the
first `generate`); UPGRADE `tests/unit/nodes/test_node_public_boundary.py`
acyclicity + `__all__` halves to iterate every node with private modules;
UPGRADE `tests/unit/agent/schemas/test_health_feedback_p3v1_audit.py:63-73`
to scan the node package; node `.md` "Module layout" section. Must NOT
change: any prompt constant/builder body, phase order, the degraded
contract, persistence, CLI, `__init__.py`, `MetricOrder`, any semantics.
Depends on C1a.

**Implementation plan.**
- [x] Re-read `run()` regions `:943-1056`, `:1284-1319`, `:1548-1575` and
      `:1907-2140`; capture the AST inventory (symbol/lines) into the
      ledger BEFORE moving anything. — §10.2 "AST inventory".
- [x] `evidence.py`: move `_required_denoising_score`, `_round_ordering`,
      `_round_health`, `_collect_health_evidence`,
      `tuning_output_to_model_run_summary` verbatim (lazy imports inside
      them preserved as they are). — 274 lines.
- [x] `ordering.py`: `PrecomputedEvidence` (frozen dataclass) +
      `precompute_evidence(summaries, model_knowledge_cache, effective_types)`
      reproducing `:943-1056` line-for-line incl. the authority filter and
      `total_experiments` from cache `_stats.completed_rounds`;
      `EnrichedFields` + `collect_enriched_fields(...)` reproducing
      `:1284-1319`; `run()` unpacks at the same positions (enriched inside
      the try). — 248 lines; see F-09a-5 (one dead local NOT re-created).
- [x] `prediction.py`: move `evaluate_prediction`, `_compute_metric`, the
      alias table verbatim; extract `accumulate_prediction_outcomes(history,
      evaluation) -> (new_history, scientific_accuracy)` and
      `accumulate_information_gain(prior, evaluation) -> float` reproducing
      `:1548-1575` exactly (same `round(…, 4)`); `run()` calls them.
      — 215 lines.
- [x] Main module: eager `from nodes.result_interpretation_agent.evidence
      import …` etc. at the top (rebind rule); `__all__` declares the moved
      names it re-exports; `run()` lifecycle comments; no other edits.
      — `__all__` (7 PUBLIC names) + `_COMPATIBILITY_REEXPORTS` (9 moved
      helpers), the tuner-C7 split; see F-09a-6.
- [x] `nodes/interpretation_helpers.py`: delete the moved symbols; module
      docstring updated; `generate_discoveries` still imports nothing
      node-local. — 1,024 → 876 lines; the now-unused `math` import removed.
- [x] Tests per Scope; node `.md` layout section.

**Validation plan.**
- [x] Unit: C1a oracle EXACT (digest + call sequence); all PB-0/PB-7/PB-8 +
      flag-ON goldens EXACT (`git status` clean on `goldens/`); the whole
      `tests/unit/agent/result_interpretation_agent/` directory;
      `tests/unit/agent/test_cold_start_prompt.py`;
      `tests/unit/agent/schemas/{test_health_feedback_p3v1_audit,test_ordering_not_executed}.py`;
      `tests/unit/agent/protocols/test_ml_model_tune_to_ml_result_interp.py`;
      `tests/unit/sdsc_submission_scripts/test_health_feedback_workspace_cases.py`;
      `tests/unit/workflows/test_model_exploration.py` (patch targets);
      `tests/unit/nodes/test_node_public_boundary.py` (generalized halves
      green for tuner AND interpreter). — see §10.2 validation table.
- [x] Reachability: the upgraded partition-before-LLM test is RED when the
      partition call is moved after the first `generate` (test-local
      mutation proof, recorded). — mutations A and B, §10.2.
- [x] Negative: a private module importing the main module reds the
      inward half; an outside production file importing
      `nodes.result_interpretation_agent.evidence` reds the outward half
      (planted, recorded, removed). — both RED naming the interpreter, §10.2.
- [x] Backward-compat: import census — every external importer of the
      node's public names (`workflows/model_exploration.py:111-114`,
      `scripts/pr3_l2_calibration/{preflight,runner}.py`, the protocol,
      `__init__.py`) still resolves; `main --help` byte-identical (sha256
      recorded); `patch("nodes.result_interpretation_agent.LLMBridge")`
      still intercepts (existing tests). — all four importers import
      cleanly; 10 `__init__` re-exports + 9 compatibility re-exports resolve
      on the package path; `--help` sha256 `bb964c11…` identical, 762 chars.

**Acceptance criteria.**
- [x] Oracle goldens byte-identical; zero prompt-golden bytes changed;
      `nodes/interpretation_helpers.py` no longer defines the three moved
      symbols; `run()` contains no inline best/worst/valid/formal
      accumulation loop and no E.4 arithmetic; the dependency graph is
      `main → {evidence, ordering, prediction}` with no reverse edge
      (boundary test); AST inventory before/after recorded (main-file and
      `run()` line counts, moved symbols). — `git status` on `goldens/`
      empty; main 2,144 → 1,826; `run()` 874 → 746 lines, branch-ish nodes
      114 → 71.
- [x] Ruling §8 precision: `result_interpretation_agent.py` remains the
      ONE obvious main node file (public class, `run()`, CLI entrypoint,
      orchestration, lifecycle ordering); every moved symbol is DEFINED
      exactly once (the main module re-exports by import — never a copy,
      no duplicate authority; pinned by an AST test that each moved name
      has one definition site in the package); the external import surface
      proven by the §2.1 census keeps resolving through the narrow
      re-exports; the extracted modules are node-private BY OWNERSHIP
      (plain filenames are a guard convention, not public-API status —
      the boundary test's outward half enforces privacy); no
      `utils`/`helpers`/`common` module.

**Failure and edge cases.** The rebind: a submodule imported lazily would
be unreachable from outside — all imports eager; `ruff` pruning an unused
re-export — `__all__` declares them; a test patching a moved name on the
package path — the census of patch targets (§2.7) shows none besides
`LLMBridge`/`open`; if one appears, patch the module that CALLS it.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent tests/unit/agent/test_cold_start_prompt.py tests/unit/agent/schemas tests/unit/agent/protocols/test_ml_model_tune_to_ml_result_interp.py tests/unit/nodes tests/unit/sdsc_submission_scripts/test_health_feedback_workspace_cases.py tests/unit/workflows/test_model_exploration.py -q > /tmp/09a_c1b.log 2>&1; rc=$?` — see §10.2.
- [x] `ruff check` + `ruff format --check`; pyright is CI-owned (recorded, never claimed locally). — check clean over `nodes/` and the four touched test areas; format clean over 30 files (two files reformatted once during development). **pyright NOT claimed locally — CI owns it.**
- [x] `git diff --stat` on `goldens/` empty; sha256 of `--help`. — goldens untouched; `--help` sha256 `bb964c115155b99a2a2f917cdce7658eed0b8db5ae666da98b867f29ba5b2bcd` at BOTH `a325f33b` and the C1b head.

**Commit boundary.** Structural only; reviewable as "is the boundary
right and is parity proven?"; no semantic change; no new field.

---

### 4.3 C2 — the run `MetricSpec` transport, reconciliation, input contract, digest echo (M2)

**Goal.** The interpreter has ONE run-scoped ordering/identity authority —
the tuner's already-resolved spec, transported additively and reconciled
— and refuses to order without it or against a disagreeing record
identity (parent §2.11 route B, §4a). Belongs before any consumer migrates
(C3 needs the order).

**Scope.** `execute_tools/evaluation_metric.py` (+`MetricSpecField`);
`agent/schemas/hyperparam_tuning.py` (`HyperparamTuningOutput.metric_spec`,
appended); `nodes/ml_hyperparameter_tune_agent/records.py` (one writer,
both dicts); `agent/schemas/interpretation.py` (`MetricIdentity`;
`ModelRunSummary.metric_identity`; `InterpretationInput.metric_spec` +
validator; `InterpretationOutput.metric_identity`);
`nodes/result_interpretation_agent/evidence.py` (`reconcile_metric_spec`,
identity projection, `InterpretationContractError`), `ordering.py`
(`bind_run_order`), main (`run()` binds + echoes; `main()` supplies the
spec); `workflows/model_exploration.py` (reconcile + pass);
`scripts/pr3_l2_calibration/fixtures.py` (stamp) + `preflight.py` /
`runner.py` (reconcile + pass); the dead protocol maps the field; REC-3
golden regenerated (two appended fields: `HyperparamTuningOutput.metric_spec`,
`InterpretationOutput.metric_identity`); node `.md` input/output tables.
Must NOT change: any ordering behaviour (C3), `MetricOrder`, the
`ExperimentRecord` schema (no record field is added anywhere in 09a),
prompt bytes. Depends on C1b.

**Implementation plan.**
- [x] Re-read `records.py:747-1016`, `hyperparam_tuning.py:2665-3020`,
      `evaluation_metric.py:355-387, :657-668`, `model_exploration.py:
      1804-1812, 2083-2120, 2687-2721`, `preflight.py:88-135`,
      `runner.py:185-253`, `fixtures.py:120-131`, the protocol file.
      The §2.4 round-trip finding was RE-VERIFIED at the head by probe, not
      taken on trust (§10.3).
- [x] `MetricSpecField` in the metric module (BeforeValidator → the ONE
      rebind; passthrough for instances/None).
- [x] `HyperparamTuningOutput.metric_spec` appended; `finalize_run_output`
      writes `bindings.run_metric.spec` (main dict) / `.model_dump()`
      (partial dict).
- [x] `reconcile_metric_spec` + `InterpretationContractError` in
      `evidence.py` (re-exported from main); builder projects
      `metric_identity` from records' `metric_result` (agreement enforced).
- [x] `InterpretationInput.metric_spec` + the two-clause validator;
      `InterpretationOutput.metric_identity`; `run()` → `bind_run_order`
      (after cold start), echo threaded into both dicts.
- [x] Workflow: `run_metric_spec = reconcile_metric_spec([*tuning_outputs,
      *iteration_results])` per iteration; `InterpretationInput(...,
      metric_spec=run_metric_spec)`; CLI `main()`, preflight, runner,
      protocol supply the spec from their outputs; the calibration fixture
      stamps `metric_spec=derive_tidmad_metric_spec(TIDMAD_PROFILE)` on
      its synthetic outputs (the simulated writer; documented in the
      fixture module docstring).
- [x] Regenerate `rec3_schema_field_lists.json` (delta: the two appended
      names); node `.md`. — 46 → 47 and 35 → 36, append-only, prefixes
      unchanged (verified programmatically before writing).

**Validation plan.**
- [x] Unit (tuner side, new `tests/unit/agent/tune_ml_hyperparam_agent/
      test_step09a_c2_output_metric_spec.py`, `pseudo_run` pattern of
      `test_step06_c4_record_payload.py`): the output carries
      `metric_spec == bindings.run_metric.spec`; the persisted JSON
      re-validates to an EQUAL spec (round-trip through the rebind); the
      degraded partial output also carries it (forced serialization
      failure); the committed pre-Step-06 replay artifact validates with
      `metric_spec is None`.
      — §10.3 — 8 passed (live stamping, JSON round trip, written file, DEGRADED partial, three carrier shapes, pre-Step-06 replay).
- [x] Unit (schemas): `InterpretationInput` validator — score-bearing
      summaries + None spec ⇒ error naming the summary; cache `_stats`
      scores + None spec ⇒ error; cold start / scoreless ⇒ accepted;
      identity mismatch on id, on direction ⇒ error naming both;
      agreement ⇒ accepted; `MetricSpecField` accepts instance / mapping /
      rejects garbage; `metric_spec_from_declaration` equivalence pinned.
      — §10.3 — part of the 28 interpreter-side cases (7 spec-required refusals, 3 named absences, 4 identity cases) + the carrier's three shapes; `MetricSpecField` equivalence pinned by F-09a-9.
- [x] Unit (reconciliation): equal specs across 3 outputs ⇒ value; one
      None among present ⇒ refusal naming it; two unequal ⇒ refusal naming
      both; all None ⇒ None; placeholders never included (workflow test).
      — §10.3 — 6 reconciliation cases.
- [x] Unit (builder): `metric_identity` projected; disagreeing records ⇒
      refusal; no `metric_result` ⇒ None.
      — §10.3 — 4 builder-projection cases.
- [x] Reachability: the workflow passes the reconciled spec (patch
      `ResultInterpretationAgent` and assert `run()`'s input carries it);
      the CLI `main()` on a legacy output fails with the named error (not
      a traceback from ordering); `test_pr3_l2p_preflight.py` green.
      — §10.3 — protocol + CLI reachability cases; `test_pr3_l2p_preflight` green from a clean tree (F-09a-11).
- [x] Mutation (recorded): remove the validator clause (a) ⇒ the spec-less
      test goes green-on-bad (RED expected); swap reconciliation equality
      for id-only ⇒ the direction-mismatch test must fail.
      — §10.3 — mutations C2-1 and C2-2, both RED, both restored.
- [x] Backward-compat: C1a oracle — ALLOWED delta = `metric_identity`
      present (echo) and nothing else; prompt goldens EXACT; all C1b suites
      green; `tests/unit/core/test_resume*.py` (outputs with/without the
      field validate); `tests/unit/workflows/test_model_exploration.py`.
      — §10.3 — oracle 8 passed, delta EXACTLY `metric_identity`, call manifest byte-identical.

**Acceptance criteria.**
- [x] Production spec-constructor census (executable, NEW in this commit's
      test module): the set of production modules (`nodes/`, `agent/`,
      `core/`, `execute_tools/`, `workflows/`, `dashboard/`, `scripts/`
      minus the fixture module below) that CALL `derive_tidmad_metric` or
      `derive_tidmad_metric_spec` equals exactly {`nodes/ml_hyperparameter_
      tune_agent/ml_hyperparameter_tune_agent.py`, `execute_tools/denoising_
      score_single.py`, `core/sandbox_executor.py`, `execute_tools/
      evaluation_metric.py` (its own composition)} — Step 09 adds ZERO;
      `scripts/pr3_l2_calibration/fixtures.py` is the ONE fixture-stamping
      module (test-fixture construction, Q-09a-7) and is asserted
      unreachable from production (no production module imports
      `scripts.pr3_l2_calibration`); planted offender (an untracked
      production module calling the constructor) turns the census RED.
      — §10.3 — `TestStep09AddsNoProductionMetricDerivationSite`: 4 modules, ZERO added, fixture module proved unreachable, planted offender RED.
- [x] Every negative test above named and green; the oracle delta is
      exactly the declared additive field.
      — §10.3 — all negatives named and green; oracle delta is the one additive field.

**Failure and edge cases.** Legacy outputs (None) ⇒ named refusal at input
construction whose message is ACTIONABLE and says, in substance,
"legacy/pre-09a tuning output `<run_name>` (`<model_type>`) lacks the
stamped run MetricSpec required for interpretation ordering — re-produce
the output under 09a or start a fresh chain" (Q-09a-6: an intentional
schema/semantic boundary, never loosened for resume convenience; no
replacement spec is derived at interpreter / workflow / CLI / resume /
PR3 path); mixed present/None ⇒ refusal; unequal specs ⇒ refusal naming
both (R-09-7: a changed binding IS a different run); a record identity
disagreeing with the spec ⇒ refusal (id mismatch and direction mismatch
each have a named negative owner, plus multi-output disagreement — Q-09a-4);
a corrupt output with disagreeing record identities ⇒ builder refusal;
`partial_dict` path keeps the spec; the pr3 CI test keeps passing because
the FIXTURE stamps (test-fixture construction, Q-09a-7). Documented
operational consequence: auto-resume of a chain whose committed outputs
predate 09a stops at its first post-09a interpretation with that refusal.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent tests/unit/agent/tune_ml_hyperparam_agent/test_step09a_c2_output_metric_spec.py tests/unit/agent/tune_ml_hyperparam_agent/test_step00_record_baselines.py tests/unit/agent/tune_ml_hyperparam_agent/test_step06_c4_record_payload.py tests/unit/agent/schemas tests/unit/agent/protocols/test_ml_model_tune_to_ml_result_interp.py tests/unit/workflows tests/unit/scripts/test_pr3_l2p_preflight.py tests/unit/core/test_resume.py tests/unit/execute_tools/test_step06_c1_evaluation_metric.py tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py -q > /tmp/09a_c2.log 2>&1; rc=$?`
      — §10.3 — rc=0, 1,080 passed from the clean commit.
- [x] `ruff check` + `ruff format --check`.
      — §10.3 — clean.

**Commit boundary.** One authority, one writer, one reader, one contract;
no ordering behaviour changes; reviewable as "is the spec transported and
enforced correctly?".

---

### 4.4 C3 — every interpreter ordering consumer onto `MetricOrder` + the direction census (M3)

**Goal.** Zero interpreter `>`/`<`/`max`/`min`/`sort` on golden-metric
values outside `MetricOrder` (the 21 rows of §2.2 incl. E1), with TIDMAD
results IDENTICAL and lower-is-better inverted. Belongs after C2 (the
order exists) and before C4 (the band uses the same order).

**Scope.** `ordering.py` (`precompute_evidence(..., order)`), `evidence.py`
(builder `order=` keyword-only), main (`_render_health_summary_section(...,
order)`, `_build_per_model_prompt(..., order=None)` + flag-ON guard;
`run()` threads the order), `nodes/interpretation_helpers.py`
(`select_active_models(..., *, order)`, `generate_discoveries(..., *,
order)` incl. the sign-safe 5% band + `abs` delta text),
`workflows/model_exploration.py` (`_cap_knowledge_cache(..., *, order)`,
its call site, and every `tuning_output_to_model_run_summary` call site —
workflow `:310-320`, CLI `main()`, the two calibration scripts, the
protocol — passing `order=MetricOrder(<reconciled spec>)` (None only when
the reconciled spec is None)); tests: UPGRADE `test_stability_filter.py`,
`test_vocab_feedback.py TestGenerateDiscoveries`,
`test_prediction_evaluation_join.py` discovery cases,
`tests/unit/workflows/test_knowledge_cache_cap.py`, health-rendering
flag-ON tests, every builder-calling test (pass `order`); NEW
`test_step09a_c3_order_consumers.py` (per-site lower-direction inversions
+ tie pins + census);
`test_step06_c5_boundary_and_structure.py::MIGRATED_TO_THE_ORDER_AUTHORITY`
extended; node `.md`. Must NOT change: any value under the shipped TIDMAD
spec; prompt bytes; `MetricOrder`. Depends on C2.

**Implementation plan.**
- [x] Re-read every §2.2 site at the head; confirm no additional literal
      appeared since the anchor (the census below is the proof).
- [x] Migrate rows 1–12 (pre-computation + builder) with `is_better` /
      `best` / `worst` exactly per the table (ties → FIRST; the dead
      `-inf` arm deleted with the filter it duplicated).
- [x] Row 13: `_render_health_summary_section(summary, *, order)`;
      `_build_per_model_prompt(..., order: MetricOrder | None = None)`
      raising `ValueError` when `structured_health_feedback and order is
      None`; `run()` passes `order` (flag-ON path only renders it).
- [x] Rows 17–19 (`generate_discoveries`): `order.best` for the strictest
      SOTA; `order.is_better`; the relative band becomes
      `abs(best - sota) <= 0.05 * abs(sota)` with **margin 0.05 preserved
      exactly** (direction + negative-reference handling only; no
      higher/lower literal, no task identity, no metric-id branch); `abs`
      delta text. This discovery rule does NOT feed the versioned accuracy
      pool, so NO third counter/version system — a declared deterministic
      correction pinned by hand-computed positive/negative × higher/lower
      cases (Q-09a-5). The margin is now the named constant
      `_DISCOVERY_RELATIVE_BAND = 0.05`, pinned by its own test.
- [x] Row 20 (`select_active_models`): `rank`-keyed sort.
- [x] Row 21 (`_cap_knowledge_cache`): `rank`-keyed stable sort with
      `worst_sentinel` for None; workflow passes
      `MetricOrder(run_metric_spec)`.
- [x] Census test + planted-offender proof; extend the Step-06 C5 lists.
      — 9 interpreter literals added to `MIGRATED_TO_THE_ORDER_AUTHORITY`.

**Validation plan.**
- [x] Unit (new): per-site inversion under `direction_only_spec()` —
      builder best/valid-best/valid-formal/worst, pre-compute per-model and
      overall extremes (summaries AND cache `_stats`), active-set Top-K,
      cache-cap keep/evict, health-summary best round, discoveries (SOTA
      choice, beating, within-5% band, below), each with a hand-computed
      expectation under `higher` AND `lower`; tie pins (equal scores →
      first record / lexicographic `mt`; `None` last in the cap).
      — §10.4 — 39 passed: per-site `higher` vs `lower` inversion for every row, tie pins, band matrix, inclusive edge.
- [x] Unit (upgraded): all existing consumer tests green with `order`
      passed; flag-ON rendering without `order` raises.
      — §10.4 — C3 targeted suite rc=0, 1,644 passed; row 13 raises when the flag is ON without `order`.
- [x] Census: the AST census over the interpreter surface is green; a
      planted `if s.best_denoising_score > best:` in an untracked probe
      module under the node package turns it RED (evidence recorded,
      probe removed); anti-vacuity count of visited `order.` consumers
      asserted; Step-06 C5 MIGRATED list asserts the old literals ABSENT
      and `"MetricOrder"` present in the three migrated files.
      — §10.4 — census green with 3 planted-offender probes; Step-06 C5 list extended with 9 interpreter literals (21 passed).
- [x] Backward-compat: C1a oracle byte-identical EXCEPT nothing (TIDMAD
      is `higher`) — asserted; all prompt goldens EXACT; the health flag-ON
      golden EXACT; `test_dispatcher_wiring.py` call counts unchanged.
      — §10.4 — the oracle is BYTE-IDENTICAL across C3 (digest AND call manifest); all 11 prompt goldens untouched.
- [x] Mutation (recorded): flip one migrated site back to `>` ⇒ the
      lower-direction test for that site is RED AND the census is RED.
      — §10.4 — mutations C3-1 (per-site + census RED after F-09a-16 closed the gap) and C3-2.

**Acceptance criteria.**
- [x] §2.2 rows 1–13 and 17–21 contain no literal (rows 14–16 are C4's);
      census green with planted-offender evidence; oracle and goldens
      byte-identical; the inversion suite green.
      — §10.4 — remaining offender set asserted EQUAL to `C4_OWNED_COMPARISONS` (rows 14-16), falsifiable in both directions (F-09a-13).

**Failure and edge cases.** Empty candidate lists: `order.best` raises on
empty exactly like `max` — every call stays guarded by the existing
emptiness checks (`if success`, `if valid_records`, …); `None` scores
excluded before ranking as today; flag-ON without an order fails closed.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent tests/unit/workflows/test_knowledge_cache_cap.py tests/unit/workflows/test_model_exploration.py tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py tests/unit/agent/test_cold_start_prompt.py -q > /tmp/09a_c3.log 2>&1; rc=$?`
      — §10.4 — rc=0, 1,644 passed in 591.55s.
- [x] `ruff check` + `ruff format --check`.
      — §10.4 — clean.

**Commit boundary.** Ordering semantics only; reviewable as "is every
direction read gone and is TIDMAD provably unchanged?".

---

### 4.5 C4 — prediction grammar + sign-safe band + `unevaluated` + version partition (M4)

**Goal.** The frozen v2 prediction semantics (§3.4): bound-id grammar with
read-only legacy aliases and capability-gated per-sample forms; the
parent's exact band; `unevaluated` never counted and never a discovery;
version-partitioned pools with version-pure accuracy and the legacy pool
preserved; uniform record shape carrying its semantics id. Belongs after
C3 (same order) and before transport (C5).

**Scope.** `prediction.py` (grammar, band, constants, versioned
accounting), `nodes/interpretation_helpers.py::generate_discoveries`
(`unevaluated` branch), main (`run()` passes `order` + bound id; threads
the versioned pools into both dicts), `agent/schemas/interpretation.py`
(`InterpretationInput.prediction_outcomes_by_semantics`,
`InterpretationInput.cumulative_information_gain_by_semantics` — appended,
default `{}`; `InterpretationOutput.prediction_evaluation_semantics`,
`prediction_outcomes_by_semantics`, `cumulative_information_gain_by_
semantics`, `prediction_pool_sizes` — appended (FOUR names); descriptions
of `prediction_outcomes_history` (now explicitly the legacy/v1 pool),
`scientific_accuracy` (v2-only, labelled), `cumulative_information_gain`
(legacy value, never pooled), `prediction_evaluation` (key list) corrected
per the §3.4 table); REC-3 golden regenerated (the four appended
`InterpretationOutput` names); tests: UPGRADE `test_vocab_feedback.py
TestEvaluatePrediction` (signature; uncomputable ⇒ `unevaluated`),
`test_prediction_evaluation_join.py` (key list; join); KEEP + EXTEND
`test_interpretation_agent.py:1186-1196` (legacy values still pass
through the degraded path unchanged; the two `_by_semantics` dicts pass
through too); the C1a oracle goldens regenerated with the DECLARED delta
(the fixture's legacy `{1,0,1}` / `0.3` UNCHANGED; NEW
`prediction_outcomes_by_semantics = {V2: {confirmed:1, partial:0,
refuted:0}}`, `cumulative_information_gain_by_semantics = {V2: 0.12}`,
`scientific_accuracy = {confirmed:1.0, partial:0.0, refuted:0.0}` (v2-only
— the pre-09a value over the pooled `{2,0,1}` differs, declared),
`prediction_evaluation_semantics = V2`, `prediction_pool_sizes =
{legacy_v1: 2, V2: 1}`, the uniform record keys); NEW
`test_step09a_c4_prediction_semantics.py` (band matrix, grammar table,
per-field partition); node `.md`. Must NOT change: prompt bytes; the
proposer (template/protocol); `boldness`; the `partial_margin` default;
the legacy dict and legacy scalar values; vocab machinery beyond the
`unevaluated` branch. Depends on C3.

**Implementation plan.**
- [x] Re-read `prediction.py` (moved code), `generate_discoveries`
      `:397-435`, the E.4 accounting, the proposer's track-record reader
      `:1146-1165` (read-only — no change).
- [x] Grammar: `_compute_metric(metric, results, *, bound_metric_id) ->
      (value, resolution)`; the alias table renamed to a LEGACY
      compatibility constant with the R-09-5 note; default metric = bound
      id.
- [x] Band exactly per §3.4; uniform record keys; semantics constants.
- [x] `generate_discoveries`: explicit `unevaluated` ⇒ no outcome
      discovery.
- [x] Versioned accounting per the §3.4 table (legacy dict/scalar copied
      unchanged; v2 dict/sum incremented; label; pool sizes); `run()`
      healthy and degraded dicts; input fields appended.
- [x] Descriptions fixed per the table; REC-3 + C1a goldens regenerated
      with the delta named. — REC-3 `InterpretationOutput` 36 → 40, verified
      APPEND-ONLY after a correction (F-09a-18).

**Validation plan.**
- [x] Unit: the hand-computed band matrix (§3.4 — nine cases × the
      direction/sign quadrants, equality, zero sota, just-inside/outside,
      uncomputable); grammar table (bound id, each legacy alias, slice,
      index, per-sample form without evidence ⇒ `unevaluated` +
      `per_sample_unavailable`, unrecognized ⇒ `unevaluated`); record keys
      uniform across branches and equal to the description's list (the
      existing pin); `information_gain == distance` only when confirmed.
      — §10.5 — 58 passed: the 12-cell band matrix, equality, inclusive edge, zero-SOTA, gain rules, the 10-row grammar table, uniform record shape across 5 branches.
- [x] Unit (per-field partition, §3.4 table): a legacy-only input (no
      `_by_semantics` keys) ⇒ legacy dict/scalar copied byte-identically,
      v2 dict = this outcome only, v2 sum = this gain, accuracy v2-only,
      label V2, pool sizes `{legacy_v1: n, V2: 1}`; an input already
      carrying v2 dicts ⇒ they continue accumulating and the legacy values
      still pass through unchanged; `unevaluated` increments NOTHING;
      `scientific_accuracy is None` while the v2 pool is empty; the
      degraded path copies every pool/sum forward unchanged;
      `prediction_evaluation_semantics` on the record AND the digest;
      no scalar anywhere equals legacy + v2 (asserted on a fixture where
      both are non-zero).
      — §10.5 — 7 partition cases.
- [x] Unit (discoveries): `unevaluated` ⇒ no `prediction_*` discovery;
      confirmed/partial/refuted sentences unchanged.
      — §10.5 — `unevaluated`: 5 cases including the no-discovery case and its anti-vacuity twin.
- [x] Negative: `evaluate_prediction` without `order` / `bound_metric_id`
      is a TypeError (keyword-only, no default); a "higher"/"lower" string
      in the new module would red the Step-06 C5 census (none is written).
      — §10.5 — `TestTheEvaluatorRefusesToGuess::test_order_and_bound_id_are_required_keywords`; the Step-06 C5 census stays green in the C4 targeted suite.
- [x] Mutation (recorded): (i) drop the `abs` in `band_width` ⇒ the
      higher/negative partial case goes RED; (ii) count `unevaluated` ⇒
      the not-counted test RED; (iii) increment the legacy dict with a new
      outcome ⇒ the legacy-untouched test RED; (iv) add the v2 gain into
      `cumulative_information_gain` ⇒ the never-pooled test RED.
      — §10.5 — mutations C4-1, C4-2, C4-3 and C4-4 (the legacy scalar pooling the v2 gain), all RED, all restored.
- [x] Backward-compat: C1a oracle delta = exactly the declared prediction/
      pool fields (enumerated in §10.5); prompt goldens EXACT (the
      synthesis "Cumulative information gain" line renders the INPUT
      legacy value `:1353`, unchanged); proposer tests untouched; the
      Q-09a-3 honesty statement (§3.4) re-checked — if an honest v1/v2
      distinction in the proposer rendering would need a template edit →
      STOP.
      — §10.5 — delta table verified key-by-key, call manifest byte-identical; Q-09a-3 re-checked at the head — NOT a STOP (see §10.5).
- [x] Manual (not CI, recorded): `tests/integration/workflows/
      test_vocab_accumulation.py` upgraded to carry the `_by_semantics`
      dicts between its hand-chained runs and re-run in pseudo mode.
      — §10.5 — UPGRADED and run: rc=0, 5 passed (`/tmp/09a_c4_pseudo.log`). It was RED before the upgrade — F-09a-25.

**Acceptance criteria.**
- [x] Every matrix cell (20: 4 direction×sign quadrants × 3 outcomes,
      equality, zero-sota ×3, just-inside, just-outside, uncomputable ×2)
      and grammar row has a named test; the four mutations are RED; the
      oracle's declared delta matches §3.4; the REC-3 delta is the four
      appended names; descriptions match emitted keys.
      — §10.5 — every cell and grammar row named; four mutations RED; oracle delta matches §3.4; REC-3 delta is the four appended names.

**Failure and edge cases.** `sota == 0` ⇒ band width 0 (equality partial,
else confirmed/refuted); `sota is None` (no `current_value`, no override)
⇒ `unevaluated`; negative sota partial reachable; alias predictions from
old proposals keep evaluating (compat) and say so (`legacy_alias`); a
malformed `mean(file_vector[a:b])` ⇒ `unevaluated`/`unrecognized` (as
today's `None`, now named).

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent tests/unit/agent/tune_ml_hyperparam_agent/test_step00_record_baselines.py tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py -q > /tmp/09a_c4.log 2>&1; rc=$?`
      — §10.5 — rc=0, 1,671 passed in 395.90s.
- [x] `.venv/bin/python -m pytest tests/integration/workflows/test_vocab_accumulation.py -q > /tmp/09a_c4_pseudo.log 2>&1; rc=$?` (manual; recorded only).
      — §10.5 — rc=0, 5 passed after the §5 UPGRADE (F-09a-25).
- [x] `ruff check` + `ruff format --check`.
      — §10.5 — clean.

**Commit boundary.** Prediction semantics only; reviewable as "is the
frozen band implemented exactly and is the version partition honest?".

---

### 4.6 C5 — prediction-memory transport through the EXISTING canonical path (Q-09a-1 = A, NARROW)

**Goal.** The frozen v1/v2 prediction-memory contract becomes
production-reachable: the interpreter-owned prediction state travels
across in-process iterations and chain subprocesses through the EXISTING
canonical lifecycle — current-iteration digest → next-iteration workflow
carry → existing `RestoredState` latest-wins restore (the V19-PR3
fingerprint-history precedent) — so the versioned pool is not
production-dead state (ruling Q-09a-1). Semantic owner = interpreter
(Step 09); physical location = workflow/resume because that is where the
canonical lifecycle lives ("semantic owner ≠ physical file location").
Step 10 keeps generic workflow/resume architecture and the remaining
direction/resume debt.

**Scope (ONLY this).** Carried values = exactly the four §3.4 fields:
`prediction_outcomes_history`, `prediction_outcomes_by_semantics`,
`cumulative_information_gain`, `cumulative_information_gain_by_semantics`
(typed together as ONE small frozen carrier `PredictionMemory` in
`agent/schemas/interpretation.py` — a carrier of digest fields, NOT a
store). `workflows/model_exploration.py`: loop carry of the four values
from `interpretation` into the next `InterpretationInput` (beside the
existing cache / vocab / fingerprint carry, `:2724-2746`) and
`run_workflow(restored_prediction_memory=…)` seeding of the first input;
`core/resume.py`: `load_latest_prediction_memory(...)` reading the four
digest keys with the SAME latest-wins idiom and error contract as
`load_latest_fingerprint_history` (`core/resume.py:863-942`; digest key read `:920`, latest-wins overwrite `:938`), and ONE additive
`RestoredState.prediction_memory` field; `sdsc_submission_scripts/
run_one_iteration.py`: forward the restored value (beside the fingerprint
history forward). Tests: `tests/unit/core/test_resume*.py` additive;
`tests/unit/workflows/test_model_exploration.py` carry; NEW `test_step09a_
c5_prediction_transport.py`. **Must NOT (ruling, verbatim)**: redesign
generic resume; change latest-wins policy; change chain-incumbent
restoration; touch unrelated workflow state; introduce a new memory store;
introduce a second restore path; introduce a task-specific resume branch.
NOT carried: `vocab_link_confirmations` (E.7 vocabulary — not part of the
prediction-memory contract; recorded as Step-10 debt, parent §19).
Depends on C4.

**Implementation plan.**
- [x] Re-read `core/resume.py:101-214, :838-1134, :1393-1447`,
      `run_one_iteration.py:2030-2061, :2122-2126`,
      `model_exploration.py:1949-2002, :2724-2746`; confirm the fingerprint
      loader's malformed-digest contract and mirror it exactly. — mirrored
      exactly: FILE-level warn+skip, DATA-level raise, ascending scan,
      latest-wins overwrite.
- [x] `PredictionMemory` carrier; loader + `RestoredState` field + forward
      + loop carry + first-input seeding — each a few additive lines beside
      its fingerprint-history sibling.

**Validation plan.**
- [x] Unit: loop carry in-process (iteration 2's input equals iteration
      1's digest's four values); restore latest-wins (two committed
      digests; the later wins; a legacy digest without the
      `_by_semantics` keys ⇒ legacy dict/scalar restored + empty v2 dicts;
      a missing digest ⇒ defaults); forward from `run_one_iteration.py`
      (the fingerprint-history arg-plumbing test pattern).
      — §10.6 — 16 passed + 2 workflow reachability cases (loop carry, latest-wins, legacy digest, defaults, the AST-parsed chain forward).
- [x] Negative: a digest with malformed pools ⇒ the SAME contract as the
      fingerprint loader (confirmed at re-read; named); the restore never
      touches any other `RestoredState` field (pinned: every other field
      equals the pre-09a restore on the same fixture workspace).
      — §10.6 — the corrupt-pool refusal and the FILE/DATA split; scope pinned as exactly-one-new-`RestoredState`-field plus a read-only loader (rather than a field-by-field diff against a pre-09a restore).
- [x] Backward-compat: every existing resume / workflow test green; C1a
      oracle unchanged (it never passes through the workflow).
      — §10.6 — C5 targeted suite rc=0, 4,019 passed; the oracle never passes through the workflow and is unchanged.

**Acceptance criteria.**
- [x] A two-iteration pseudo chain accumulates a v2 pool of size 2 with
      v2-only accuracy and an untouched legacy dict; a chain whose first
      digest is legacy shows `prediction_pool_sizes.legacy_v1` preserved and
      the v2 pool starting at the first 09a iteration; exactly ONE new
      `RestoredState` field; no new loader beyond the one sibling of the
      fingerprint loader.
      — §10.6 — in-process loop carry + restore tests; and the C4 pseudo integration run now proves the two-iteration accumulation end-to-end (v2 pool 2, accuracy 0.5, legacy pool untouched). Exactly ONE new field, ONE loader (`TestTheScopeStayedNarrow`).

**Failure and edge cases.** Missing/legacy digests; latest-wins across
gaps; forwarding omitted ⇒ defaults (never a crash); malformed pools ⇒
the fingerprint loader's contract.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/core tests/unit/workflows tests/unit/sdsc_submission_scripts -q > /tmp/09a_c5.log 2>&1; rc=$?`
      — §10.6 — rc=0, 4,019 passed in 271.61s.

**Commit boundary.** Narrow transport only; reviewable as "does the
interpreter's memory ride the existing canonical path and nothing else?".

---

### 4.7 C6 — evidence projection: diagnosis, secondaries (type + summary field), failure counts (M5)

**Goal.** The summary and digest carry the Rev-5 evidence the interpreter is
blind to today — diagnosis verbatim, present-when-present secondaries as
a typed open collection, authority-derived failure counts — with no new
vocabulary and no upstream carrier (Q-09-7 = B). Belongs after the
ordering/prediction milestones so the new fields are additive on a
settled boundary.

**Scope.** `agent/schemas/interpretation.py` (`SecondaryMetricEvidence`,
`RecordFailureCounts`; `ModelRunSummary.best_training_diagnosis`,
`formal_training_diagnosis`, `secondary_metrics`, `failure_counts`
appended; `InterpretationOutput.per_model_secondary_metrics`,
`per_model_failure_counts` appended), `evidence.py` (projections;
`secondary_metrics` NOT populated by the builder — documented), main
(`run()` aggregates per model into both dicts; `_stats["failure_counts"]`),
REC-3 golden regenerated (two appended `InterpretationOutput` names); NEW
`test_step09a_c6_evidence_projection.py`; secondaries-never-ordered census
(AST + behavioural); node `.md`. Must NOT change: prompt bytes; ordering;
any record schema. **Q-09-7 = B stays binding (ruling §9)** — C6 may add
the `ModelRunSummary.secondary_metrics` contract, named absence, the
deterministic rendering-facing evidence shape and L1 fixture population;
C6 must NOT add `ExperimentRecord` secondary fields, tuner secondary
evaluation, secondary metric-handle invocation, tuning-output secondary
transport, workflow secondary binding, or a secondary plugin loader (all
Step 10). The production builder therefore has NO production secondary
values to project before Step 10 — represented honestly as an empty
collection; **no placeholder fake values**. Depends on C5.

**Implementation plan.**
- [x] Re-read the builder and `run()`'s `new_stats` block (`:1186-1208`).
- [x] Models + projections per §3.5; counts keyed by the existing Literal
      values as strings; `refusal_contract_ids` opaque.
- [x] `run()`: per-model aggregation for NEW summaries; cached models'
      counts from `_stats` when present (else absent — never invented).

**Validation plan.**
- [x] Unit: diagnosis projected from the best and formal records (and
      None when absent); failure counts hand-computed on a mixed record
      set (every status value present once; diagnosis ok/absent/invalid/
      missing; one refusal with a contract id; gate actions; provenances);
      `SecondaryMetricEvidence` validator (result+refusal rejected;
      unavailable status); summary default `[]`; digest aggregation in
      both healthy and degraded paths; `_stats` carries counts.
      — §10.7 — 24 passed: per-role diagnosis + its record-contract coupling (F-09a-23), hand-counted mixed record set, missing-vs-absent split, the three secondary states, both digest paths, `_stats` counts.
- [x] Census: AST — no `secondary_metrics` reference inside any function
      that references `order`/`MetricOrder` in the interpreter surface;
      planted offender RED; behavioural — flipping secondary values leaves
      the pre-compute and builder outputs identical.
      — §10.7 — the NARROWED census (F-09a-22) with 3 planted offenders + 1 anti-over-reach case, plus the behavioural inertness test.
- [x] Negative: the builder never reads undeclared record keys for
      secondaries (a record dict with a stray `secondary_metric_results`
      key yields an empty summary collection — pinned, with the Step-10
      pointer).
      — §10.7 — the undeclared-key negative with its Step-10 pointer.
- [x] Backward-compat: C1a oracle delta = exactly the declared additive
      fields; prompt goldens EXACT; `test_round_health_summary.py:246-261`
      legacy-summary validation still green.
      — §10.7 — TWO added keys plus the `_stats["failure_counts"]` provision, verified key-by-key; call manifest unchanged.

**Acceptance criteria.**
- [x] All new fields typed, appended, threaded into both digest dicts;
      census + planted offender evidence; the REC-3 delta is the two names.
      — §10.7 — REC-3 `InterpretationOutput` 40 -> 42, append-only; census + planted-offender evidence recorded.

**Failure and edge cases.** Records without diagnosis/refusal/gate data ⇒
zero counts and `None` diagnosis (named absence, never invented);
unknown future status strings count under their own key (open dict, no
enum growth required).

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/result_interpretation_agent tests/unit/agent/tune_ml_hyperparam_agent/test_step00_record_baselines.py -q > /tmp/09a_c6.log 2>&1; rc=$?`
      — §10.7 — rc=0, 4,112 passed in 212.94s.

**Commit boundary.** Projection only; reviewable as "is every new field a
deterministic read of an existing authority, and are secondaries inert
for ordering?".

---

### 4.8 C7 — three-task L1 fixtures, final census, node `.md`, docs (M6)

**Goal.** Contract-level proof on TIDMAD / Pets / DAVIS (§3.6), the
interpreter-surface census closed, the node's public `.md` current with
the merged code (CLI args, defaults, module layout, new fields, the
fail-closed contract, the version partition), pack STATUS rows, and this
design's ledger complete. Last because it documents the merged state.

**Scope.** NEW `examples/oxford_iiit_pet/expected/interpretation_evidence_
l1_fixture.json`, `examples/davis_future_prediction/expected/
interpretation_evidence_l1_fixture.json`, pack `STATUS.md` rows; NEW
`tests/unit/examples/test_step09a_interpretation_evidence_rung.py`; final
census additions (prediction records carry the semantics id — schema
census over the oracle digest; secondaries census from C6 re-run);
`nodes/result_interpretation_agent/result_interpretation_agent.md`; parent
§19 / roadmap status touched ONLY at freeze/merge time per the standing
doc-sync rule (not in this commit unless the operator directs). No
production code. Depends on C6.

**Implementation plan.**
- [x] Re-read `tests/unit/examples/test_step07a_b1_diagnosis_structure_
      rung.py:42-187` (the L1 pattern) and the pack governance guards.
- [x] Fixtures per §3.6 (declared specs via `metric_spec_from_declaration`
      from the packs' `declared/` JSON; diagnosis from the packs' 07a L1
      fixtures; `_fixture` label + note + provenance listing the
      authorities).
- [x] Rung test: parametrized; hand-computed literals; atomicity (only the
      declared axis varies between TIDMAD and `direction_only_spec`);
      consumer-existence test (§22.23.7); mismatch refusal; secondaries
      inert.
- [x] Node `.md`: every flag/default/field quoted against the merged
      source (the standing doc-sync rule). — four sections added across
      C1b/C2/C3/C4/C6 plus the module layout.

**Validation plan.**
- [x] Unit: the rung (all three tasks); `tests/unit/examples/` whole
      directory (governance, pack pins, maturity vocabulary);
      `test_pack_governance.py` still green (JSON only under `expected/`;
      no production import of `examples`).
      — §10.8 — rung 31 passed; `tests/unit/examples` 204 passed with pack governance untouched.
- [x] Census: the interpreter-surface direction census (C3), the
      secondaries census (C6), the semantics-id census — all green with
      their planted-offender evidence re-recorded at the final head.
      — §10.8 — all three censuses green; re-run at the final head after the F-09a-17 centralization (the semantics-id census is now a single-authority census with its own planted-offender proof).
- [x] Backward-compat: oracle + goldens EXACT; the whole interpreter test
      directory.
      — §10.8 / §10.9 — oracle and goldens EXACT; the whole interpreter directory green (422 passed at the final head).

**Acceptance criteria.**
- [x] Pets and DAVIS fixtures load through the REAL builder with their
      declared specs; DAVIS best is the SMALLEST mse; TIDMAD partial
      reachable; secondaries present-when-present and inert; `.md`
      current; §10 ledger complete; parent §19/§21 references to 09a
      unchanged (status surfaces synced at freeze/merge).
      — §10.8 — fixtures compare field-by-field against each pack's OWN `declared/`; DAVIS best is the smallest mse (with its anti-vacuity guard); honesty pins asserted; node `.md` updated; §10 complete.

**Failure and edge cases.** Pack pins over `declared/` untouched (no new
declared file); STATUS rows keep the maturity vocabulary tokens the pins
require.

**Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/examples tests/unit/agent/result_interpretation_agent -q > /tmp/09a_c7.log 2>&1; rc=$?`
      — §10.8 — subsumed by the terminal run recorded in §10.9 (rc=0, 9,842 passed), which is a strict superset of this command.
- [x] Then: finalize docs → open the formal master-targeting PR → ONE
      exact-head CI on the final head (no local full suite, no manual
      dispatch).
      — §10.9 — docs finalized, PR #238 opened against master, ONE automatic CI per head and no manual dispatch or local full suite.

**Commit boundary.** Fixtures + docs + census; no production change.

## 5. Test disposition (named in advance, executed at the owning commit)

| existing surface | disposition | commit |
|---|---|---|
| PB-0 / flag-ON / PB-7 / PB-8 prompt goldens | **KEEP** byte-identical at every commit (a delta is a STOP) | all |
| `test_interpretation_agent.py:1260-1270` (source pin on `run()`) | **UPGRADE** → reachability (recording `partition_for_aggregation` patched on `ordering` + recording bridge) | C1b |
| `test_interpretation_agent.py:1245-1258` (builder source pin) | **KEEP** (getsource follows the moved function) | C1b |
| `test_node_public_boundary.py` acyclicity + `__all__` halves (tuner-hardcoded) | **UPGRADE** → generic over nodes with private modules | C1b |
| `test_health_feedback_p3v1_audit.py:63-73` (single-file scan) | **UPGRADE** → node package | C1b |
| `test_vocab_feedback.py:19`, `test_prediction_evaluation_join.py:38` imports of `evaluate_prediction` | **MOVE** to `nodes.result_interpretation_agent.prediction` | C1b |
| REC-3 `rec3_schema_field_lists.json` | **REGENERATE** in C2 (+1 `InterpretationOutput` name and +1 `HyperparamTuningOutput` name), C4 (+4), C6 (+2) — `InterpretationOutput` 35 → 42 names, `HyperparamTuningOutput` 46 → 47, each delta named | C2/C4/C6 |
| `test_prediction_evaluation_join.py:166-187` key-list pin | **KEEP** (description updated with the code) | C4 |
| `test_vocab_feedback.py TestEvaluatePrediction` | **UPGRADE** (signature; uncomputable ⇒ `unevaluated`; values unchanged — positive sota agrees) | C4 |
| `test_vocab_feedback.py TestGenerateDiscoveries`, `test_prediction_evaluation_join.py` join | **UPGRADE** (pass `order`; `unevaluated` case added) | C3/C4 |
| `test_stability_filter.py` | **UPGRADE** (pass `order`; lower-direction Top-K added) | C3 |
| `tests/unit/workflows/test_knowledge_cache_cap.py` | **UPGRADE** (pass `order`; lower-direction + None-last pins) | C3 |
| `test_interpretation_agent.py:1186-1196` degraded carry-forward | **KEEP + EXTEND** (legacy dict/scalar still pass through unchanged — the per-field rule never re-bases; the two `_by_semantics` dicts are asserted to pass through too) | C4 |
| `test_step06_c5_boundary_and_structure.py` MIGRATED list | **EXTEND** with interpreter literals; NOT_REACHED untouched | C3 |
| all `InterpretationInput` constructions with scores (unit + pr3 scripts + protocol tests) | **UPGRADE** (supply `metric_spec` via `tests/helpers/metric_fixtures.shipped_spec()` / the fixture stamp) | C2 |
| every `tuning_output_to_model_run_summary(...)` call in tests (`test_round_health_summary.py`, `test_round_ordering_summary.py`, `test_health_prompt_parity.py`, `test_health_prompt_rendering.py`, `test_health_feedback_outputs.py`, `tests/unit/agent/schemas/{test_health_feedback_p3v1_audit,test_ordering_not_executed}.py`, `tests/unit/sdsc_submission_scripts/test_health_feedback_workspace_cases.py`, `tests/integration/workflows/test_ordering_resolution_pseudo.py`) | **UPGRADE** (pass `order=MetricOrder(shipped_spec())`; assertions unchanged under `higher`) | C3 |
| `tests/integration/workflows/test_vocab_accumulation.py:886-1110` | **UPGRADE** (carry the `_by_semantics` dicts between its two hand-chained runs; assert the v2 pool `{refuted:1}` → `{confirmed:1, refuted:1}` / accuracy 0.5 and the legacy dict untouched); manual pseudo run recorded, never CI | C4 |
| `tests/integration/protocols/test_tune_to_interp*.py` | **UPGRADE** (stamped outputs); manual pseudo run recorded | C2 |
| everything else in §2.7 | **KEEP** | — |

## 6. Validation architecture / evidence economy

Targeted per-commit suites (listed in each §4 block); no local full suite;
no manual CI dispatch; ONE canonical exact-head PR CI on the final head
(operator review in parallel). Each checkpoint owns ONE evidence property:
C1a the fixed-input digest + kwargs; C1b structural parity; C2 the spec
contract; C3 direction inversion + census; C4 the band matrix + partition;
C5 transport; C6 projections + inert secondaries; C7 the three-task rung.
Every mutation proof is recorded with the exact edit, the RED output and
the restore (cache cleared; count == 1 target site). Integration (pseudo)
runs are manual, recorded in §10, never added to CI.

## 7. Gate disposition

**Gate 1 — NOT REQUIRED** (parent §17, Q-09-4; re-confirmed by the final
ruling §10): no prompt-template or prompt-protocol change; the
deterministic prompt-CONTENT deltas (proposer track-record values — v2-only
accuracy beside the legacy `N`; the synthesis "Cumulative information gain"
legacy input value; discovery sentences on uncomputable/now-partial cases)
are owned by the C1a differential oracle and the C4 tests. A real LLM Gate
is NOT added merely because corrected prediction state can later affect
proposer prompt content — 09a changes deterministic state semantics, not
the LLM prompt/protocol; 09b owns the real LLM Gate. Any accidental
template byte delta is a STOP → operator re-disposition. **Gate 2 — NOT
REQUIRED**: no data / training / inference / subprocess / lifecycle claim;
the tuner's only change is one additive output field (unit-proven through
the pseudo run). No Step-06/07/08 Gate is re-run. No local
repository-wide full suite by default; no manual duplicate full CI.

## 8. Operator questions — ALL RESOLVED (final ruling 2026-08-19)

| id | question (as posed at rev 1) | RULING |
|---|---|---|
| **Q-09a-1** | transport of the versioned prediction pool — 09a or Step 10? | **A, NARROWLY** — C5 (§4.6): interpreter-owned fields only, through the existing canonical digest → workflow carry → `RestoredState` latest-wins path; generic resume policy untouched; parent factual erratum applied |
| **Q-09a-2** | version-partition field semantics | **exact per-field table (§3.4)**: `prediction_outcomes_history` stays the legacy/v1 pool; `prediction_outcomes_by_semantics[V2]` owns v2 counts; `scientific_accuracy` v2-only + labelled by `prediction_evaluation_semantics`; `prediction_pool_sizes` explicit; legacy gain preserved in `cumulative_information_gain`, v2 gain in `cumulative_information_gain_by_semantics[V2]`; never pooled. The rev-1 "existing names = current pool" reading is REJECTED |
| **Q-09a-3** | proposer "Prediction Track Record" template untouched? | **CONFIRMED** — no template/protocol change; honest statement that deterministic CONTENT changes through the existing renderer; a template edit needed for an honest v1/v2 distinction ⇒ STOP |
| **Q-09a-4** | fail-closed spec rule at `InterpretationInput` construction? | **CONFIRMED** — required spec + exact id/direction agreement before ordering / active-model selection / prediction / rendering / any LLM call; no fallback; named negative owners (missing spec, id mismatch, direction mismatch, multi-output disagreement) |
| **Q-09a-5** | the four extra direction sites + the discoveries 5% band | **CONFIRMED, source-bounded** — C3; margin 0.05 exact; direction/negative-reference correction only; no third counter; hand-computed positive/negative × higher/lower cases; census counts reconciled (§2.2) |
| **Q-09a-6** | legacy-chain consequence | **ACKNOWLEDGED / FROZEN** — pre-09a score-bearing outputs without `metric_spec` FAIL CLOSED with an actionable refusal; no re-derivation anywhere; fresh/re-produced output is the compatibility path |
| **Q-09a-7** | the pr3 calibration fixture's spec stamp | **CONFIRMED WITH PRECISE WORDING** — test-fixture construction ("simulated tuner-output writer / fixture stamping"); production census proves ZERO new `derive_tidmad_metric` / `derive_tidmad_metric_spec` production sites; helper unreachable from production |

Open operator questions: **0**.

## 9. Risks

* **R-09a-1 rebind/patch breakage from the extraction** — mitigated by
  eager imports, `__all__` re-exports, the patch-target census (§2.7), the
  generalized boundary test, and C1a's oracle + kwargs golden.
* **R-09a-2 source-text pins** — the two known pins are dispositioned
  (§5); a new one appearing in CI is fixed by upgrading the test to a
  reachability assertion, never by keeping code in `run()` for the pin.
* **R-09a-3 fail-closed breaks callers** — the pr3 preflight (CI) gets a
  stamped fixture; the CLI/protocol read the output's spec; legacy chains
  fail closed by design (Q-09a-6); every refusal names its cause.
* **R-09a-4 tie/stability drift in extremum migration** — `best`/`worst`
  are first-wins like `max`/`min`; `rank`-keyed stable sorts reproduce the
  old orders; pinned by tie tests under both directions.
* **R-09a-5 version-partition incoherence at the proposer** — the per-field
  rule (Q-09a-2) means the proposer's existing renderer shows `N` from the
  LEGACY pool beside a v2-only accuracy; this is a declared deterministic
  content delta (Q-09a-3), pinned by C1a's oracle; if an honest v1/v2
  distinction is judged to need a proposer TEMPLATE edit → STOP (never
  silently moved into 09a); a future proposer-side rendering change is
  09b/Step-10 prompt work.
* **R-09a-11 C5 scope creep into resume/workflow architecture** — the
  ruling's verbatim must-not list is C5's scope statement; acceptance pins
  exactly ONE new `RestoredState` field and one sibling loader; every other
  restored field equal to the pre-09a restore on the same fixture
  workspace; a wider change is a STOP (ruling §13).
* **R-09a-6 scope creep into secondary transport** — the builder never
  populates secondaries; no record field; no evaluator/loader/binding;
  the C6 negative test pins it with the Step-10 pointer.
* **R-09a-7 REC-3 golden churn** — three regenerations, each with a
  named delta; fields appended so prefixes never move.
* **R-09a-8 `MetricSpec` JSON rebind** — found at audit; `MetricSpecField`
  routes every mapping through the ONE sanctioned rebind; round-trip
  equality tested on the tuner's persisted output and on resume.
* **R-09a-9 the differential oracle becomes a change-deterrent** — every
  regeneration is a declared delta attributed to a §3 rule (C2, C4, C6);
  an undeclared delta is a STOP.
* **R-09a-10 E.7 `vocab_link_confirmations` never carried (E2)** — not
  part of the prediction-memory contract, so not carried by C5; recorded
  as Step-10 debt in the parent §19 at freeze.

## 10. Ledger

*(filled per commit during implementation; empty at REVISION 2 — FROZEN)*

### 10.0 Implementation-context provenance

Branch `step09-pr09a-interpreter-evidence-ordering`, created from the frozen
master `a325f33b9ce44f81f3ef688e2cf53a0bfdc6662e` (== local master ==
`origin/master` at initialization; clean tree). Design confirmed at that SHA:
REVISION 2 — FROZEN, 104 `[ ]` / 0 `[x]`, 0 open operator questions.

**Working-rule reconciliation (recorded, not a design change).** §4.0's third
standing rule ("Before EVERY commit: stop and show the exact diff summary …
wait for permission (the operator's standing per-commit rule for this child)")
was written during the design session. The operator's 09a IMPLEMENTATION
authorization supersedes it explicitly — "Commits are AUTONOMOUS … No
operator checkpoint is required", and the Step-09a Implementation Working
Rules state the contract "does NOT introduce: per-commit operator approval".
Implementation therefore commits autonomously; every other clause of §4.0
(bounded re-read first, `[x]` only with recorded evidence, pytest verdicts
from complete log files, prompt-golden delta = STOP) stands unchanged.

### 10.1 C1a — differential digest oracle

**Commit.** `Step 09a C1a: capture the pre-refactor differential oracle`
(test-only; zero production files touched — `git status` at commit time
listed exactly the four new test artifacts).

**What landed.**

| artifact | role |
|---|---|
| `tests/unit/agent/result_interpretation_agent/_step09a_fixture.py` | the FIXED input + `RecordingStubBridge` (canned JSON per label; records label + sha256(system) + sha256(user) + `emit_marker` calls) |
| `…/test_step09a_c1a_differential_oracle.py` | 8 tests: digest golden, persistence parity, workspace-independence/repeatability, call-sequence golden, hardcoded label/marker shape, prompt repeatability, two anti-vacuity perturbation probes |
| `…/goldens/step09a_differential_digest.json` | the full `InterpretationOutput` (52 KB), `_captured_at` = `a325f33b` |
| `…/goldens/step09a_differential_llm_calls.json` | the ordered call manifest + markers, same provenance |

**F-09a-1 — the fixture uses THREE model types, not two.** §4.1 specifies
"TWO new `HyperparamTuningOutput`s"; it also requires a legacy-flat cache
entry, a modern `CacheEntry`-shaped entry and the `consolidate` path. Source
reading showed those cannot all sit on two model types while ALSO exercising
the cache-`_stats` reconstruction loop (`:995-1025`), the Stability-Filter
skip (`emit_marker`), the cached score-table re-validation (`:1307-1317`) and
`compress_model_summary` — every one of which needs a model that has a cache
entry and NO new summary. The fixture therefore keeps the two new tuning
outputs the design asks for and adds a third, cache-only model:

* `wavenet` — new output + MODERN `CacheEntry`-shaped entry (stored with the
  `stats`→`_stats` rename `run()` itself performs at `:1259`); active +
  4 rounds vs 3 cached ⇒ `interpretation.per_model`, then `consolidate` ⇒ two
  `cache_consolidator.list_merge` calls. Carries the run's only authoritative
  formal record, a `score_table`, a `file_vector`, a gated collapse round and
  a `skipped_oom_risk` round.
* `bidirectional_gated_tcn` — new output, NO cache entry ⇒ cache-miss build;
  it is the previous proposal's model, so it drives prediction evaluation and
  all three discovery branches. Its formal record carries NO
  `scientific_authority`, so `partition_for_aggregation` has both an included
  and an excluded member.
* `punet` — cache-only, LEGACY-FLAT shape, outside the active set ⇒ the skip
  marker, the `_stats` reconstruction loop, the cached-table re-validation and
  the compression path.

Classified as a BOUNDED deviation (§15): the frozen contract ("a committed,
CI-portable, FIXED interpretation input whose full deterministic digest and
LLMBridge call sequence are pinned") is achieved more completely, and nothing
semantic changes.

**F-09a-2 — the fixture pins candidate validity with the DS5 waiver.**
`classify_candidate_health` consults `required_blocking_gate_ids()` — i.e. the
ambient effective HealthGate roster — for any successful record that does not
carry `health_gate_enabled=False`. A fixture depending on that would make the
oracle move whenever `configs/health_checks.yaml` or a task health config
moves, which is exactly the kind of coupling a differential baseline must not
have. Every success record therefore carries `health_gate_enabled=False` (the
DS5 self-describing waiver, `candidate_eligibility.py:190-191`); the collapse
record carries real persisted gate results instead, so `RoundHealth`
provenance (`gated`), `gate_outcomes` and the collapse fingerprint are still
on the recorded path.

**F-09a-3 — the workspace is the only run-varying string, and it is
normalised at the RECORDER.** The tmp workspace is interpolated VERBATIM into
the synthesis prompt's compressed-model hint (`:641-651`, a MIGRATION-PARITY
behaviour PB-7 already pins with a frozen literal). It never reaches the
digest — proven by `test_the_digest_is_workspace_independent_and_repeatable`,
which runs the fixture through two different workspaces and deep-equals the
digests — but it would perturb the recorded prompt hash. `RecordingStubBridge`
replaces it with `<STEP09A_WORKSPACE>` before hashing (§4.1 "Failure and edge
cases": normalize at the fixture, never in production);
`test_the_recorded_prompts_are_repeatable_across_workspaces` fails if any
other interpolation site is missed.

**F-09a-4 — the fixture's prediction values are chosen so C3 and C4 have
DISJOINT declared deltas.** The design's prediction numbers are used exactly
(`current_value = -2.55`, actual best `-2.43` ⇒ confirmed, `delta_from_sota =
0.12`, `information_gain = 0.12`, `cumulative_information_gain` 0.3 → 0.42),
so v1 and v2 band semantics AGREE here and C4's delta is the version PARTITION
alone. Separately, the discovery-2 relative band (§2.2 row 19) is
sign-degenerate for negative SOTA and would otherwise diverge at C3: the
fixture makes `wavenet` the overall best at `-2.00`, so the strictest SOTA is
`-2.00`, `|−2.43 − (−2.00)| = 0.43` and `0.05 × |−2.00| = 0.10`. The old rule
(`best > sota × 0.95`) and the sign-safe replacement
(`|best − sota| ≤ 0.05 × |sota|`) BOTH resolve to "significantly below SOTA",
so §4.4's "C1a oracle byte-identical at C3" holds on this fixture. Observed
sentence at capture: *"bidirectional_gated_tcn scored -2.4300, significantly
below SOTA (-2.0000). The approach needs revision."*

**Recorded baseline (from the capture run at `a325f33b`).**

```text
effective_types      ['bidirectional_gated_tcn', 'punet', 'wavenet']
active set           2/3 — {'bidirectional_gated_tcn', 'wavenet'}  (punet skipped)
LLM calls            5, in order:
                       interpretation.per_model        (bidirectional_gated_tcn)
                       interpretation.per_model        (wavenet)
                       cache_consolidator.list_merge   (key_findings)
                       cache_consolidator.list_merge   (bottlenecks)
                       interpretation.synthesis
markers              1 — interpretation.per_model_skipped {reason: stable, model_type: punet}
overall best         -2.0
prediction           confirmed, delta_from_sota=0.12, actual=-2.43
discoveries          3 (prediction / score-vs-SOTA / timing)
runtime vocab        7 entries (3 discoveries, 2 canonical) — ZERO promotions,
                     so the dedup call site never fires and the sequence length is fixed
scientific_accuracy  {'confirmed': 0.6667, 'partial': 0.0, 'refuted': 0.3333}  (n=3, v1 pooled)
cumulative gain      0.42  (0.3 carried + 0.12 this iteration)
```

**Validation.**

| command | result |
|---|---|
| `.venv/bin/python -m pytest …/test_step09a_c1a_differential_oracle.py -q` | **rc=0 — 8 passed in 9.21s** (`/tmp/09a_c1a.log`) |
| the same, second consecutive run | rc=0 — 8 passed in 7.77s (`/tmp/09a_c1a_run2.log`) |
| the same, after `ruff format` | rc=0 — 8 passed in 7.81s (`/tmp/09a_c1a_final.log`) |
| `ruff check` (both new files) | All checks passed |
| `ruff format --check` (whole node test directory) | 19 files clean |
| `git status --porcelain` | 4 untracked test artifacts, 0 modified production files |

Anti-vacuity: both perturbation probes are RED against the committed goldens
(`total_experiments` +1 ⇒ the diff names the field; a zeroed `user_sha256` on
call 0 ⇒ the diff names it). The goldens contain no `/tmp` path and no
timestamp (grep at capture time).

**Deviations.** F-09a-1 (bounded, above). None material.
### 10.2 C1b — node-local extraction

**Commit.** `Step 09a C1b: extract evidence / ordering / prediction into
node-private modules`. Structural only; no intended semantic change.

**AST inventory (before → after).**

| surface | at `a325f33b` | after C1b |
|---|---|---|
| `result_interpretation_agent.py` | 2,144 lines | **1,826** |
| `ResultInterpretationAgent.run()` | 874 lines, 114 branch-ish AST nodes | **746 lines, 71** |
| `nodes/interpretation_helpers.py` | 1,024 lines | **876** |
| `evidence.py` / `ordering.py` / `prediction.py` | — | 274 / 248 / 215 |

Moved out of `run()`: the deterministic pre-computation (`:943-1056`), the
enriched-field pre-compute (`:1284-1319`) and the E.4 accounting
(`:1548-1575`). Moved out of the file: the five evidence-projection functions
(`:1907-2140`). Moved out of the mixed helpers module: `evaluate_prediction`,
`_compute_metric`, `_DENOISING_SCORE_ALIASES`.

`run()` now reads as a lifecycle: cold start → effective types + descriptions
→ `precompute_evidence` → expert advice + health merge → Phase 1 →
`collect_enriched_fields` → Phase 2 → Phase C → accumulate → build → persist,
with the degraded fallback unchanged.

**Single-definition census (executable, added this commit).** All twelve moved
symbols have exactly ONE definition site in the package; zero duplicates. The
rule is now
`tests/unit/nodes/test_node_public_boundary.py::test_a_decomposed_node_defines_each_symbol_exactly_once`,
parametrized over every decomposed node.

**F-09a-5 — the extraction surfaced a dead local in the pre-09a `run()`.**
`per_model_best_config` was written in three places (`:951`, `:971`, `:1010`,
`:1033` at `a325f33b`) and READ in none. Once the region became a typed
boundary, ruff's F841 saw it immediately — subscript assignment had hidden it.
The boundary still computes and exposes it on `PrecomputedEvidence` (C6's
projections are its first real consumer); `run()` simply does not unpack it,
with the reason recorded at the site. Behaviour-identical: an unread value.

**F-09a-6 — `__all__` and `_COMPATIBILITY_REEXPORTS` are now separated for the
interpreter too.** `__all__` = the 7 PUBLIC names (`ResultInterpretationAgent`,
`main`, `tuning_output_to_model_run_summary`, the four prompt constants);
`_COMPATIBILITY_REEXPORTS` = the 9 moved helpers kept resolvable at the old
path for `__init__.py` and existing `mock.patch` targets. The tuner-only
`__all__` guard was generalised to every decomposed node, deriving the public
anchors from the module's own AST (its public classes + `main`) rather than
hardcoding a node's names.

**F-09a-7 — the first cut of the duplicate-authority rule was too broad.** It
flagged three TUNER names — `_records` / `_runtime` (module-alias bindings via
`_import_module`, present in three and two files) and `SIDERIUS_ROOT` (derived
from `__file__` in two). Those are local bindings of the same object, not two
implementations that can drift. The rule was narrowed to `def` / `class` plus
module-level assignments of LITERAL data (so a duplicated lookup table such as
`_DENOISING_SCORE_ALIASES` is still covered), and the reason is recorded in the
test's docstring. It then passed on BOTH nodes and went RED on a planted copy.

**F-09a-8 — reaching a private module from a test needs the dotted path.** The
package `__init__` rebinds `sys.modules["nodes.result_interpretation_agent"]`
to the MAIN module, so `from nodes.result_interpretation_agent import ordering`
raises `ImportError` (no such attribute). The repo convention —
`importlib.import_module("nodes.<node>.<private>")`, as the tuner's conftest
does — is what the upgraded reachability test uses, and the reason is recorded
both in the test and in the node `.md`.

**Test dispositions applied.**

| surface | disposition | what changed |
|---|---|---|
| `test_vocab_feedback.py`, `test_prediction_evaluation_join.py` | **MOVE** | import `evaluate_prediction` from its new single definition site (`…prediction`), NOT a compatibility alias — the cases still exercise production code |
| `test_interpretation_agent.py` partition-before-LLM | **UPGRADE** | source-text pin on `getsource(run)` → REACHABILITY: a recording `partition_for_aggregation` patched on `ordering` (the CALLER) plus a recording bridge; asserts both events occurred and that the partition came first |
| `test_interpretation_agent.py` builder source pin | **KEEP** | `inspect.getsource` follows the moved function — green unchanged |
| `test_node_public_boundary.py` acyclicity + `__all__` halves | **UPGRADE** | tuner-hardcoded → parametrized over every decomposed node; plus the NEW duplicate-authority rule |
| `test_health_feedback_p3v1_audit.py` retention-constant scan | **UPGRADE** | single main file → the whole node package (a constant introduced in `evidence.py` would have been invisible), with a ≥4-file anti-vacuity assertion |

**Validation.**

| command / probe | result |
|---|---|
| C1a differential oracle | **rc=0 — 8 passed**, digest and call sequence BYTE-IDENTICAL to the pre-refactor goldens (`/tmp/09a_c1b_oracle.log`) |
| the full C1b targeted suite (design command) | **rc=0 — 798 passed in 189.09s** (`/tmp/09a_c1b.log`); the pre-upgrade run was `rc=1 — 1 failed, 793 passed`, the single failure being the source pin now upgraded |
| `git status` on `goldens/` | empty — zero prompt-golden bytes changed |
| import census | all 4 production importers import cleanly; 10 `__init__` re-exports + 9 compatibility re-exports resolve on the package path |
| `main --help` | sha256 `bb964c11…b2bcd`, 762 chars, IDENTICAL at `a325f33b` (measured in a throwaway worktree) and at the C1b head |
| `ruff check` / `ruff format --check` | clean (30 files) |
| pyright | NOT run locally — CI owns it |

**Mutations / planted offenders (each RED, each restored, `git diff` empty
after restore, `__pycache__` cleared around every run).**

| # | mutation | expected | observed |
|---|---|---|---|
| A | `precompute_evidence` builds the scope itself instead of calling `partition_for_aggregation` | reachability RED | RED — *"the production path never reached partition_for_aggregation — the aggregation authority is not actually wired into run()"* |
| B | the recorded authority call relocated into `collect_enriched_fields` (which runs AFTER Phase 1) via an import-time alias | ORDER RED | RED — *"the partition must precede every LLM call; observed order: ['llm:interpretation.per_model', 'llm:interpretation.per_model', 'partition', 'llm:interpretation.synthesis']"* |
| C | `prediction.py` imports the main module | inward half RED | RED — *"result_interpretation_agent: private modules imported the main module: {'prediction.py': [...]}"* |
| D | `workflows/model_exploration.py` imports `nodes.result_interpretation_agent.evidence` | outward half RED | RED — *"production code outside a node imported that node's private modules: {'workflows/model_exploration.py': ['nodes.result_interpretation_agent.evidence']}"* |
| E | a copy of `accumulate_information_gain` added to the main module | duplicate-authority RED | RED — naming both `prediction.py` and `result_interpretation_agent.py` |

Mutations C and D name the INTERPRETER, which is what proves the generalised
boundary rule actually covers the new node rather than only the tuner.

**Deviations.** F-09a-5 and F-09a-7 (both bounded, above). None material; the
oracle is byte-identical, so no behaviour moved.

### 10.3 C2 — run MetricSpec transport + contract

**Commit.** `Step 09a C2: transport the run's MetricSpec and fail closed
without it`.

**Route (parent §2.11 B), as built.**

```text
ml_hyperparameter_tune_agent.py:541   the ONE derivation (untouched)
  -> RunBindings.run_metric.spec
  -> records.finalize_run_output       ONE writer, BOTH dicts
  -> HyperparamTuningOutput.metric_spec
  -> reconcile_metric_spec(outputs)    workflow / CLI / preflight / runner / protocol
  -> InterpretationInput.metric_spec   fail-closed validator
  -> ordering.bind_run_order           the ONE MetricOrder (consumed from C3)
  -> InterpretationOutput.metric_identity   provenance echo, both digests
```

**F-09a-9 — the round-trip finding re-verified at the head, not trusted.**
The design's §2.4 audit claimed `MetricSpec.model_validate(spec.model_dump())`
FAILS while `metric_spec_from_declaration(json round-trip) == spec` holds. A
probe at the implementation head reproduced it exactly: 3 `extra_forbidden`
errors (the dumped `scoreability` carries the SUBCLASS fields `contract_id`,
`input_channel_group`, `required_attrs`, `required_storage_dtype`), and the
rebind round-trips to an equal spec. `MetricSpecField` is therefore load-bearing,
and `TestTheCarrierSurvivesItsOwnDump::test_a_bare_metric_spec_cannot_revalidate_its_own_dump`
pins the finding so the machinery cannot outlive its reason.

**F-09a-10 — the fail-closed contract's blast radius was 79 tests, and that is
the evidence.** Adding the validator turned 79 existing tests red at once.
Every one was a score-bearing `InterpretationInput` (or a fake tuning output
feeding one) built with no metric binding — i.e. every one of them had been
silently relying on the assumed direction. They were UPGRADED per the frozen
§5 disposition, not weakened: the fixtures now stamp
`tests.helpers.metric_fixtures.shipped_spec()` (TIDMAD, `higher`), so every
assertion is unchanged. Three central builders covered most of it
(`test_dispatcher_wiring._make_input`, `test_interpretation_agent.make_input` /
`_run_once`, `test_health_feedback_outputs._make_input`) plus 14 inline sites,
the two calibration entry points, the protocol's `make_tuning_output`, the
workflow's `_make_tuning_output`, and ONE DataScope preflight seed — the one
seed in that file designed to REACH interpretation; its sibling LEGACY seeds
are untouched because they fail earlier, on the invariants they exist to test.

**F-09a-11 — the PR3-L2 preflight failure was the guard, not a defect.**
`test_pr3_l2p_preflight.py::test_preflight_all_invariants` failed mid-C2 with
`no_production_file_modified` listing the nine production files this commit
edits. That is the documented PR3-L2 protocol rule (CLAUDE.md, operator
decision 2026-08-08): the full suite's verdict is meaningless from a
work-in-progress tree. It was NOT relaxed; the checkpoint was committed and the
suite re-run from a clean tree.

**Q-09a-7 made executable.** `TestStep09AddsNoProductionMetricDerivationSite`
walks the AST of every production module and pins the derivation call-site set
to exactly `{tuner, denoising_score_single, sandbox_executor, evaluation_metric}`
— four modules, ZERO added by Step 09 — with an anti-vacuity assertion that the
walk found them, plus proof that `scripts/pr3_l2_calibration/fixtures.py` is the
ONE spec-stamping script module and that NO production module imports
`pr3_l2_calibration`. The fixture stamp is a simulated tuner-output writer; it
calls the authoritative Step-06 constructor so it cannot drift.

**Validation.**

| command / probe | result |
|---|---|
| NEW `test_step09a_c2_metric_spec_contract.py` (interpreter side) | **28 passed** — 7 spec-required refusals, 3 named-absence cases, 4 identity-agreement cases, 4 builder-projection cases, 6 reconciliation cases, protocol + CLI reachability, 3 census tests |
| NEW `test_step09a_c2_output_metric_spec.py` (tuner side) | **8 passed** — live stamping, JSON round trip, the written file, the DEGRADED partial output, the carrier's three input shapes, the pre-Step-06 replay artifact |
| C1a differential oracle | **8 passed** — delta is EXACTLY one added key, `metric_identity = {"metric_id": "tidmad_denoising_score", "direction": "higher"}`; ZERO existing keys changed or removed; the LLM-call manifest byte-identical |
| REC-3 schema golden | regenerated: `HyperparamTuningOutput` 46 → 47 (`metric_spec`), `InterpretationOutput` 35 → 36 (`metric_identity`), both APPENDED with prefixes unchanged |
| `tests/unit/agent/result_interpretation_agent` | 298 passed |
| C2 targeted suite (design command), from the CLEAN commit | **1,080 passed, 0 failed**. The run made mid-edit reported `1 failed` — `test_pr3_l2p_preflight` — and the guard's offender list named exactly one file: `ordering.py`, an in-flight C3 edit. Re-run against the stashed clean tree at `fcfdb78e`: **rc=0, 1 passed**. Sequencing error on my part (editing production while a suite ran), not a C2 defect; the guard was not relaxed (F-09a-11) |
| `ruff check` / `ruff format --check` | clean across `agent/ nodes/ execute_tools/ workflows/ scripts/ tests/unit/` |
| pyright | NOT run locally — CI owns it |

**Mutations (both RED, both restored clean, caches cleared).**

| # | mutation | expected | observed |
|---|---|---|---|
| C2-1 | the validator's clause (a) witness scan always returns `None` (i.e. the spec-required rule is dropped) | the spec-less refusals go green-on-bad | RED — all 7 `TestAScoreBearingInputRequiresTheRunSpec` cases fail |
| C2-2 | reconciliation compares `metric_spec.id` instead of the whole spec | the direction disagreement is waved through | RED — and ONLY `test_two_specs_with_the_SAME_id_but_opposite_direction_are_refused` fails, which is exactly the case id-only comparison misses |

Mutation C2-2 required ADDING that case: the pre-existing unequal-spec test
used `direction_only_spec()`, which differs in id AND direction, so an id-only
comparison would still have caught it. The mutation is what exposed the gap —
recorded because a mutation that changes nothing is a finding about the tests,
not about the code.

**Deviations.** F-09a-10's scope (79 test upgrades) is larger than the design's
sentence implies but is exactly the disposition it names. None material.

### 10.4 C3 — ordering consumers + census

**Commit.** `Step 09a C3: every interpreter direction consumer reads
MetricOrder`.

**All 21 censused sites migrated.**

| rows | site | migration |
|---|---|---|
| 1–8 | `ordering.precompute_evidence` | per-model + overall best / best-valid / worst, over BOTH the summaries loop and the cache-`_stats` loop, via `is_better`. "Worse than" is asked as `is_better(incumbent, candidate)` — never by constructing an opposite-direction order |
| 9–12 | `evidence.tuning_output_to_model_run_summary` | `order.best` for best / best-valid / best-valid-formal, `order.worst` for the worst round score. The dead `float("-inf")` arm is deleted with the filter it duplicated |
| 13 | `_render_health_summary_section` | best-scoring round via `is_better`; `_build_per_model_prompt` gained `order=None` and RAISES when the flag is ON without it, so every flag-OFF caller and all 11 prompt goldens are untouched |
| 17–19 | `generate_discoveries` | strictest SOTA via `order.best`; "beating" via `is_better`; the second sign-degenerate band corrected to `abs(best - sota) <= 0.05 * abs(sota)`; the "(+delta)" text uses a MAGNITUDE so it cannot print `(+-1.0000)` under `lower` |
| 20 | `select_active_models` | `rank`-keyed sort replacing `(-score, mt)` |
| 21 | `_cap_knowledge_cache` | `rank`-keyed stable sort replacing `reverse=True` + a `-inf` fill; `worst_sentinel` ranks a scoreless entry last under BOTH directions |
| 14–16 | the prediction band | **C4's**, by the frozen plan — see the census note below |

`order` is keyword-only with NO default on `precompute_evidence` and on
`tuning_output_to_model_run_summary`; each carries its own fail-closed clause,
because the builder is called by the workflow, the CLI, the calibration
scripts and the protocol BEFORE any `InterpretationInput` exists.

**PARITY: the C1a oracle is BYTE-IDENTICAL across C3** — digest AND LLM-call
manifest. Twenty-one ordering sites changed shape and nothing observable
moved, which is the strongest available evidence that the migration is
faithful under TIDMAD's `higher`.

**F-09a-12 — the margin became a named constant.** `0.05` appeared as a bare
literal inside the band expression. It is now
`_DISCOVERY_RELATIVE_BAND = 0.05` with the Q-09a-5 freeze recorded at its
declaration, and `test_the_frozen_margin_is_still_five_percent` pins it. A
future edit that retunes the width now has to walk past the freeze note.

**F-09a-13 — the census flags the prediction band, and that is correct.** At
C3 the AST census reports exactly two remaining offenders,
`actual > sota` and `actual >= sota * (1.0 - partial_margin)` — rows 14–16,
which the frozen plan assigns to C4. Rather than exempting `prediction.py`,
the test names them in `C4_OWNED_COMPARISONS` and asserts the remaining set
equals it EXACTLY. The claim is therefore falsifiable in both directions: C3
fails if it left anything else behind, and C4 fails if it does not empty the
set.

**F-09a-14 — a literal in a COMMENT broke the migrated-literal guard.** The
first version of the C3 comment quoted the old band expression verbatim, and
`MIGRATED_TO_THE_ORDER_AUTHORITY` (a substring scan) failed on the comment
rather than the code. The comment was reworded to describe the old rule
instead of quoting it. Same class as the `... or True` incident this repo
already recorded: a scan-based guard cannot tell code from prose, so prose
must not contain the thing being banned.

**F-09a-15 — the "order=" substring check false-matched `resolved_file_order=`.**
The mechanical test-threading pass used `"order=" in call`, which is a
substring of `resolved_file_order=`, so three multi-line builder calls were
silently skipped and reported as already-threaded. Fixed with a word-boundary
regex `(?<![\w_])order=`. Worth recording because the same trap applies to any
future kwarg-threading sweep.

**Validation.**

| command / probe | result |
|---|---|
| NEW `test_step09a_c3_order_consumers.py` | **39 passed** — per-site `higher` vs `lower` inversion for the builder, the pre-computation (summaries AND cache), the active set, the cache cap, the health best-round and the discovery comparison; tie pins; the four-quadrant sign-safe band matrix; the inclusive edge; the frozen-margin pin; the census + 3 planted-offender probes |
| C1a differential oracle | **8 passed — BYTE-IDENTICAL** (digest + call manifest), as §4.4 requires |
| Step-06 C5 boundary/structure | 21 passed; `MIGRATED_TO_THE_ORDER_AUTHORITY` extended with 9 interpreter literals, each asserted ABSENT with `MetricOrder` present |
| C3 targeted suite (interpreter + schemas + protocol + cold-start + workflows + sdsc + Step-06 C5 + nodes + resume) | **rc=0 — 1,644 passed in 591.55s** (`/tmp/09a_c3.log`) |
| `ruff check` / `ruff format --check` | clean |
| pyright | NOT run locally — CI owns it |

**Mutations (both RED, both restored clean, caches cleared).**

| # | mutation | expected | observed |
|---|---|---|---|
| C3-1 | row 1 reverted to `s.best_denoising_score > current_best` | the per-site test AND the census RED | **first run: only the CENSUS went red** — see below |
| C3-2 | `_DISCOVERY_RELATIVE_BAND` retuned 0.05 → 0.10 | the band matrix RED | RED — 3 of the 4 quadrants plus the frozen-margin pin |

**F-09a-16 — mutation C3-1 exposed a real coverage gap, and it was closed.**
On its first run only the census caught the reverted literal: every test in
`TestThePrecomputationInverts` asserted OVERALL extremes, so the PER-MODEL
best (row 1) and per-model worst (row 4) had no per-site coverage at all. A
census that catches what no localised test catches is a census doing work it
cannot localise. Two cases were added
(`test_per_model_best_is_opposite_when_one_model_has_two_summaries`, which
also pins that the winning CONFIG travels with the winning score, and the
per-model worst equivalent); re-running C3-1 then turned BOTH the per-site
test and the census red. This is the mutation earning its place rather than
confirming what was already known.

**Deviations.** None material. F-09a-12 through F-09a-16 are bounded findings.

### 10.5 C4 — prediction semantics v2

**Commit.** `Step 09a C4: sign-safe prediction band, unevaluated, and the
v1/v2 partition`.

**The three defects, all fixed together because they share one call.**

| defect | before | after |
|---|---|---|
| direction-blind | `actual > sota` — labels every regression a confirmation under a minimised metric | `order.is_better(actual, sota)` |
| sign-degenerate | `actual >= sota * (1 - margin)` — scaling a NEGATIVE reference moves it toward zero, so `partial` was UNREACHABLE for every TIDMAD score and a near-miss was recorded as `refuted` | `distance <= partial_margin * abs(sota)`, margin unchanged at 0.05 |
| uncomputable counted | `outcome="partial"` + a note — entered the accuracy pool and was published as a discovery reading "achieved metric=N/A" | `unevaluated`, counted in NO pool, no discovery |

**Grammar.** `_compute_metric` returns `(value, resolution)`. The default
metric is the run's BOUND id, not the literal `denoising_score` (one task's
name hardcoded as the framework default). Resolutions: `bound_id`,
`legacy_alias` (the FROZEN table, read-only, never grown for a new task),
`per_sample_slice`, `per_sample_index`, `per_sample_unavailable` (a
scalar-only task — Pets and DAVIS both are) and `unrecognized`. The old
single `None` return collapsed the last three into one.

**Version partition (Q-09a-2), exactly per the §3.4 table.** The legacy dict
and scalar are carried forward and NEVER incremented; the v2 pool and sum
accumulate under `metric_order_signsafe_v2`; accuracy is v2-only and labelled;
`prediction_pool_sizes` states both. The degraded path copies every pool
forward unchanged — no re-basing exists, because the structure itself is
versioned.

**F-09a-17 — the semantics ids were copied into three modules, and the copies
are now gone (CLOSED at the pre-merge audit, operator review 2026-08-19).**

*The finding as first recorded.* Declaring the ids in `prediction.py` put them
where the schema cannot reach: `agent/schemas/interpretation.py` importing the
node package is a genuine cycle (node → schemas → node), and
`nodes/interpretation_helpers.py` must not depend on the node package either.
Both therefore spelled the ids as LITERALS, with an equality test pinning the
spellings together. Functionally correct, but the shape is
`one authority → three copies → a test keeping them equal`, which is debt.

*The bounded import-layer audit (operator ruling: centralize only if an
existing lower-layer home is legal and the move is small).* Five functional
spellings existed, not three — `core/resume.py:1514` and the node's own
`result_interpretation_agent.py:1618` also carried literals, neither named in
the original finding. The audit asked which module every consumer can import
downward without a cycle, a node-private leak, or a new module:

```text
agent/schemas/interpretation.py        <- imports agent.schemas.* + execute_tools
    ^            ^              ^  ^      (NEVER nodes.*)
    |            |              |  |
prediction.py  helpers.py  resume.py  <node>.py
```

`core/resume.py` ALREADY imported this module (`PredictionMemory`), and
`interpretation_helpers.py` already imports `agent.schemas.proposal`, so the
edge exists in both cases. The schema also OWNS the fields these values key
(`prediction_evaluation_semantics`, `prediction_outcomes_by_semantics`,
`prediction_pool_sizes`), which makes it the contract layer rather than a
convenience location.

*Disposition: CENTRALIZED.* `PREDICTION_SEMANTICS_SIGNSAFE_V2`,
`PREDICTION_SEMANTICS_LEGACY_V1`, `COMPARABLE_OUTCOMES` and
`OUTCOME_UNEVALUATED` are declared ONCE in `agent/schemas/interpretation.py`.
`prediction.py` imports and re-exports them under the same names, so no
caller's import site changed; the helpers, the resume path and the node main
file consume the declaration. NO new module, NO new layer, NO enum system, NO
loader — four moved constants and four import lines. `import` of all five
modules verified cycle-free at runtime.

`TestTheSemanticsIdsAgreeAcrossModules` is REPLACED by
`TestTheSemanticsIdsHaveOneAuthority`, which is strictly stronger: it parses
each production module and asserts each id is spelled exactly ONCE, outside
any docstring, in the declaring module only — plus an anti-vacuity check that
every consumer still imports it. Copying a literal back into `core/resume.py`
turns it RED (verified), which the old equality pin could not detect.

The schema's DEFAULT remains `legacy_v1`, not v2: a digest written before Step
09a has no such key and must read as what actually produced it.

**F-09a-18 — the first REC-3 regeneration broke the append-only rule.** The
four C4 fields were declared before `metric_identity`, so the golden's ordered
prefix moved (`prefix_unchanged=False`) even though nothing was removed. The
Step-00 harness requires fields to be APPENDED so the existing prefix is
untouched; the block was moved to the end of `InterpretationOutput` and the
prefix check re-run green. Caught only because the regeneration script prints
the prefix check rather than diffing counts.

**F-09a-19 — a hand-computed expectation was wrong, and the test caught it.**
`test_the_same_input_gets_opposite_verdicts_under_opposite_directions`
originally asserted that actual −2.43 vs SOTA −2.55 is `refuted` under
`lower`. It is `partial`: distance 0.12 ≤ 0.05 × 2.55 = 0.1275. The CODE was
right and the assertion was sloppy. The case now uses −2.20 (distance 0.35,
genuinely outside the band) so the two directions really do land on opposite
verdicts. Recorded because "hand-computed" is only a virtue if the hand
computation is checked.

**Declared C1a oracle delta (all four parts predicted by §4.5).**

| part | delta |
|---|---|
| added | `prediction_evaluation_semantics = "metric_order_signsafe_v2"`; `prediction_outcomes_by_semantics = {V2: {confirmed:1, partial:0, refuted:0}}`; `cumulative_information_gain_by_semantics = {V2: 0.12}`; `prediction_pool_sizes = {legacy_v1: 2, V2: 1}` |
| reverted to the INPUT value | `prediction_outcomes_history` 2/0/1 → **1/0/1** (the legacy pool is no longer incremented); `cumulative_information_gain` 0.42 → **0.3** (the legacy scalar no longer accumulates) |
| recomputed | `scientific_accuracy` {0.6667, 0.0, 0.3333} → **{1.0, 0.0, 0.0}**, v2-only |
| reshaped | `prediction_evaluation` gains `metric_resolution`, `notes`, `prediction_evaluation_semantics` — the UNIFORM key set |
| unchanged | the LLM-call manifest, byte-identical |

The outcome itself is still `confirmed` with gain 0.12: v1 and v2 agree on
this fixture by construction (F-09a-4), so the delta is the version PARTITION
alone.

**Validation.**

| command / probe | result |
|---|---|
| NEW `test_step09a_c4_prediction_semantics.py` | **58 passed** — the 12-cell band matrix over all four direction×sign quadrants, the reachable negative `partial`, equality, the inclusive edge, zero-SOTA, the gain rules, `unevaluated` (5 cases incl. no-discovery + its anti-vacuity twin), the 10-row grammar table, the uniform record shape across 5 branches, 7 partition cases, and the cross-module id pins |
| `tests/unit/agent/result_interpretation_agent` | 396 → **404 passed** |
| REC-3 golden | `InterpretationOutput` 36 → 40, append-only prefix verified |
| C4 targeted suite | **rc=0 — 1,671 passed in 395.90s** (`/tmp/09a_c4.log`) |
| `ruff check` / `ruff format --check` | clean |
| pyright | NOT run locally — CI owns it |

**Mutations (all RED, all restored clean, caches cleared).**

| # | mutation | observed |
|---|---|---|
| C4-1 | drop `abs()` from `band_width` | RED — 5 cases incl. the negative `partial`, equality and the inclusive edge |
| C4-2 | count `unevaluated` as comparable | RED — `test_it_increments_neither_pool` |
| C4-3 | pool the v2 counts into the legacy size | RED — 2 partition cases |
| C4-4 | the legacy scalar accumulates the v2 gain (`run()`:1627) | RED — 15 cases including the C1a differential oracle |

C4-1's first attempt silently applied NOTHING: its anchor matched the
DOCSTRING copy of the band, not the executable line, and the script's assert
fired. The mutation was redone against line 204 by index. A mutation that
does not apply reports "green" and proves the opposite of what it claims —
recorded as a hygiene note.

C4-4 is worth reading precisely: the C4 unit file itself stayed GREEN, because
it owns `accumulate_information_gain` in isolation while the mutation sits at
the `run()` composition site. The property is caught by the agent-level tests
and the differential oracle instead. Unlike F-09a-16 this is NOT a coverage
gap — the never-pooled claim is asserted where the pooling would actually
happen — but it is recorded so nobody reads "the C4 file is green" as "the
mutation survived".

**F-09a-25 — a planned test UPGRADE was never executed, and only the pre-merge
ledger audit found it.** §5 assigns C4 an UPGRADE of
`tests/integration/workflows/test_vocab_accumulation.py` (carry the
`_by_semantics` dicts between its two hand-chained runs). The implementation
never touched the file. Because integration tests are deliberately outside CI,
NOTHING was red: the file simply sat broken on the branch — all 5 tests failed,
9 score-bearing `InterpretationInput` constructions refused by C2's fail-closed
contract, and the accumulation assertions still written against the legacy
pool. It was found by checking the box against its evidence rather than by a
failing run, which is the argument for the audit itself.

Fixed as the disposition specified: every input stamps `shipped_spec()` (the
same upgrade the 79 unit tests received, F-09a-10), the two hand-chained runs
carry BOTH pools, and the assertions moved to the v2 pool with the legacy dict
pinned UNTOUCHED across both iterations (`{confirmed:0, partial:0, refuted:0}`
after a refuted and a confirmed outcome), accuracy 0.5 computed on the 2
comparable v2 outcomes, and `prediction_pool_sizes` stating both. **rc=0, 5
passed.** This is now the only test that proves the v1/v2 partition survives a
real two-iteration agent chain rather than a single call — which is also the
evidence C5's "two-iteration pseudo chain" acceptance criterion asked for.

**Q-09a-3 re-checked at the head (the frozen §3.4 STOP condition).** The
proposer's renderer (`ml_model_proposal_agent.py:1146-1165`) reads
`scientific_accuracy` (now v2-only), `cumulative_information_gain` (the frozen
legacy scalar) and `prediction_outcomes_history` (legacy; its sum is the
rendered `N`). Confirmed at the implementation head: the rendered
`Scientific accuracy (N=…)` line therefore pairs v2 FRACTIONS with a v1
DENOMINATOR. This is exactly the consequence §3.4 declares and freezes, not a
new discovery. Judgement, stated explicitly because the ruling demands one: an
honest v1/v2 distinction here does NOT require a template edit *in 09a* — the
digest already carries `prediction_evaluation_semantics` and
`prediction_pool_sizes`, so the honest data is present and only the proposer's
rendering is stale, and the proposer's rendering surface is 09b's. **No STOP.**
Carried forward as a named 09b item.

**Deviations.** None material.

### 10.6 C5 — prediction-memory transport (existing canonical path)

**Commit.** `Step 09a C5: carry the interpreter's prediction memory through
the existing canonical path`.

**Why it was needed at all.** Parent erratum E2: at the pre-09a anchor NO
production path carried or restored `prediction_outcomes_history` or
`cumulative_information_gain`. Every production digest's pool therefore held
exactly ONE outcome and the proposer's "Prediction Track Record" always
rendered `N=1` — the research-accounting feature had been inert since it was
written. C4's versioned pools would have been dead schema in the same way.

**The five additive hops, each beside its fingerprint-history sibling.**

| hop | where |
|---|---|
| the carrier | `PredictionMemory` in `agent/schemas/interpretation.py` — frozen, exactly the four ruled fields, no persistence methods |
| the loader | `core/resume.load_latest_prediction_memory`, a sibling of `load_latest_fingerprint_history`: same digest source, same ascending scan, same latest-wins overwrite, same FILE-level warn+skip / DATA-level raise split |
| the restored field | ONE additive `RestoredState.prediction_memory` |
| the chain forward | `run_one_iteration.py`, one line below `restored_collapse_fingerprint_history` |
| the loop carry + seeding | `model_exploration.py`: `restored_prediction_memory` seeds the loop variable; each iteration's digest REPLACES it; the four values are passed on the next `InterpretationInput` |

**F-09a-20 — mutation C5-3 initially SURVIVED, and the gap was real.**
Making the restore ACCUMULATE instead of overwrite left every test green,
because `test_latest_wins_rather_than_accumulating` exercised only the v2 pool
and gain while the mutation summed the LEGACY dict. A loader that fabricated a
legacy history would have shipped. The case now asserts ALL FOUR carried
fields; re-running C5-3 turns it RED.

**F-09a-21 — mutation C5-2 exposed a hop with NO test at all.** Deleting the
`run_one_iteration.py` forward leaves the restore loading state that nothing
consumes: every `core/` test passed, every workflow test passed, and the carry
silently stopped at the process boundary — exactly the pre-09a defect. Three
tests were added, asserting the kwarg by PARSING the `run_workflow(...)` call
(AST) rather than scanning for a substring, since F-09a-14 already showed a
substring can be satisfied by a comment; plus an anti-vacuity check that the
parse found the real call, and a signature check that the callee declares the
keyword.

**Scope, kept narrow and made checkable.** `TestTheScopeStayedNarrow` pins:
exactly ONE new `RestoredState` field (and that the four values live INSIDE
the carrier rather than as four restored fields); the carrier holds exactly
the four ruled fields; there is exactly ONE prediction-memory loader in
`core/resume.py` (a second restore path would take the shape of a second
loader); the loader only READS, so the digest remains the ONE store; and the
carrier is frozen, so restored state cannot become a second source of truth.

**Validation.**

| command / probe | result |
|---|---|
| NEW `tests/unit/core/test_step09a_c5_prediction_transport.py` | **16 passed** — restore of all four fields, latest-wins across two digests, the legacy-digest case (v1 restored, v2 NOT invented), first-iteration default, missing/unreadable warn+skip, the corrupt-pool refusal, the three forward tests, and five scope pins |
| NEW workflow reachability (2 cases in `TestRunWorkflowMultiIteration`) | iteration 2 receives iteration 1's digest with the v1/v2 separation intact; a restored memory seeds the FIRST iteration of a chain subprocess |
| C5 targeted suite (core + workflows + sdsc + interpreter + schemas) | **rc=0 — 4,019 passed in 271.61s** (`/tmp/09a_c5.log`) |
| `ruff check` / `ruff format --check` | clean |
| pyright | NOT run locally — CI owns it |

**Mutations (all RED after the gaps above were closed; all restored clean).**

| # | mutation | observed |
|---|---|---|
| C5-1 | delete the workflow loop carry | RED immediately |
| C5-2 | delete the chain forward | initially caught by NOTHING (F-09a-21); RED after the forward tests were added |
| C5-3 | restore accumulates instead of latest-wins | initially SURVIVED (F-09a-20); RED after the latest-wins case covered all four fields |

Two of the three mutations found a genuine hole. That is the value the
technique is supposed to provide, and it is recorded rather than smoothed
over.

**Deviations.** None material. The design's "two-iteration pseudo chain"
acceptance is covered by the in-process loop-carry test plus the restore
tests, which together exercise both hops deterministically; no pseudo
integration run was needed.

### 10.7 C6 — evidence projection

**Commit.** `Step 09a C6: project diagnosis, failure counts and the secondary
contract`.

**What reaches the summary now.** `best_training_diagnosis` and
`formal_training_diagnosis` (verbatim, ONE PER ROLE — a best trial round and
the formal round are different experiments), `failure_counts`, and the
`secondary_metrics` contract. Per-model aggregates are threaded into BOTH
digest paths, and `_stats["failure_counts"]` keeps a quiet model's counts
across iterations exactly as `round_health_counts` does.

**No new failure taxonomy (parent §5).** Every key comes from an authority
that already owns it. `diagnosis_missing` is counted SEPARATELY from `absent`:
"no diagnosis object" and "the diagnosis says the history was absent" are
different facts about different records, and folding them would report
training that never ran as training that ran without validation.

**Q-09-7 = B held.** The builder leaves `secondary_metrics` EMPTY —
pinned as a positive claim, with the Step-10 pointer — and
`TestQ097StaysBinding` asserts no secondary field was added to
`ExperimentRecord` or `HyperparamTuningOutput` and that no production module
defines a secondary evaluator/loader/binder.

**F-09a-22 — the first secondaries census was too coarse and would have
distorted the code.** It asked "does a function that reads `order` also
mention secondaries?" and flagged `run` and
`tuning_output_to_model_run_summary` — both of which legitimately RANK primary
scores and PROJECT secondary evidence in the same scope. Satisfying that test
would have meant splitting the projection into a contrived second function.
The rule was narrowed to what it actually claims: a secondary may not be an
operand of a comparison, an argument to a `MetricOrder` method, or a sort key.
Three planted offenders (one per shape) prove it bites, and a fourth case
proves it does NOT flag the legitimate projection.

**F-09a-23 — the record contract constrains what a diagnosis fixture may
be.** `ExperimentRecord` enforces `training_diagnosis.state != "absent" =>
training_history is not None` (`hyperparam_tuning.py:759-763`), so a fixture
asserting the PROJECTION cannot invent an `ok` diagnosis on a record with no
training results. Rather than working around it silently, the projection cases
use states the record admits and
`test_a_non_absent_diagnosis_requires_its_history` asserts the coupling
directly — it is what makes "carried verbatim" safe.

**F-09a-24 — mutation C6-3 survived twice, and the second survival was a real
gap.** The first attempt was a no-op (it read an attribute that does not
exist, so it fabricated nothing and proved nothing — the same hygiene failure
as C4-1). The second attempt fabricated a secondary only for records carrying
a `metric_result`, and SURVIVED because the emptiness test used a bare record
that never reached that branch. A "the builder leaves it empty" claim has to
be made on the record shape production actually produces; the case is now
parametrized over a bare AND a fully-scored record, and the mutation is RED on
the latter.

**Declared C1a oracle delta.** TWO keys added — `per_model_failure_counts`
(the two NEW summaries; `punet` is cached with no stored counts and is
therefore ABSENT rather than reported as zero failures) and
`per_model_secondary_metrics` (EMPTY) — plus the additive
`_stats["failure_counts"]` cache key on the two models that got a fresh
per-model call, which is the design's own §3.5 provision. Verified key-by-key
that NOTHING else inside `model_knowledge_cache` moved; the LLM-call manifest
is unchanged.

**Validation.**

| command / probe | result |
|---|---|
| NEW `test_step09a_c6_evidence_projection.py` | **24 passed** — the per-role diagnosis projection and its record-contract coupling, a hand-counted mixed record set, the missing-vs-absent split, the opaque refusal contract id, the open-dict future-status case, the DEGRADED-path reachability, the three secondary states and their exclusivity, the two emptiness cases, the undeclared-key negative, the narrowed census with 3 planted offenders + 1 anti-over-reach case, the behavioural inertness test, and the three Q-09-7 pins |
| REC-3 golden | `InterpretationOutput` 40 → **42**, append-only — the design's §11.2 predicted final total |
| C6 targeted suite | **rc=0 — 4,112 passed in 212.94s** (`/tmp/09a_c6.log`) |
| `ruff check` / `ruff format --check` | clean |
| pyright | NOT run locally — CI owns it |

**Mutations (all RED after F-09a-24 was closed; all restored clean).**

| # | mutation | observed |
|---|---|---|
| C6-1 | stop projecting the formal diagnosis | RED |
| C6-2 | fold `diagnosis_missing` into `absent` | RED — 2 cases |
| C6-3 | the builder fabricates a placeholder secondary | RED after the emptiness claim was made on a fully-scored record (F-09a-24) |

**Deviations.** None material.

### 10.8 C7 — three-task rung + docs

**Commit.** `Step 09a C7: three-task L1 interpretation evidence, censuses and
docs`.

**The rung.** `tests/unit/examples/test_step09a_interpretation_evidence_rung.py`
drives the SAME production boundaries —
`tuning_output_to_model_run_summary`, `ordering.precompute_evidence`,
`prediction.evaluate_prediction` — over three materially different
declarations:

| task | primary | per-sample | declared secondaries |
|---|---|---|---|
| TIDMAD | `tidmad_denoising_score`, higher, negative | present | none |
| Pets | `accuracy`, higher, [0,1] | scalar-only | `macro_f1` (higher), scored |
| DAVIS | `mse`, **LOWER** | scalar-only | `psnr` (higher) scored, `mae` (lower) **unavailable** |

DAVIS is the load-bearing row: under `lower` the best score is the SMALLEST
number, so a direction literal anywhere on the interpreter's path reports the
worst model as the best. Every expectation is a hand-computed literal, and
`test_the_hand_computed_davis_expectation_is_the_smallest_value` is the
anti-vacuity guard — without it a DAVIS expectation computed the TIDMAD way
would make the parametrized rung pass while proving nothing.

`mae` is DECLARED BUT UNAVAILABLE on purpose: the contract's third state, a
named absence that must never render as a number.

**Why the fixtures cannot drift.** They embed the packs' OWN `declared/`
metric JSON rather than restating it, and
`test_the_fixture_uses_the_packs_OWN_declared_specs` compares them
field-by-field against `declared/`. A fixture that hand-copied a declaration
could silently disagree with the thing it claims to represent.

**Honesty pins.** Each fixture's `_fixture` note must contain "NOT a real
tuning output" AND name **Step 10** as the owner of the production half —
asserted, because a reader who skips the note would otherwise take the
secondaries block for a production capability. Pack `STATUS.md` rows say the
same in the maturity vocabulary the existing pins require, and JSON was added
ONLY under `expected/` (no new `declared/` file), so the pack-governance
guards are untouched.

**Validation.**

| command / probe | result |
|---|---|
| NEW `test_step09a_interpretation_evidence_rung.py` | **31 passed** — direction, identity, precompute agreement, the prediction band, per-sample capability, secondaries present-when-present with their own directions, secondary inertness and the identity-mismatch refusal, each across all three tasks; plus atomicity, the two honesty pins, the declared-spec comparison and the no-`examples`-import census |
| `tests/unit/examples` | **204 passed** — pack governance, maturity vocabulary and the existing rungs unaffected |
| C7 / terminal targeted suite | see §10.9 |

**Deviations.** None material.
### 10.9 Final validation + PR + exact-head CI

**Terminal local validation at the final executable head.**

```text
python -m pytest tests/unit/agent tests/unit/core tests/unit/workflows \
    tests/unit/nodes tests/unit/examples tests/unit/sdsc_submission_scripts \
    tests/unit/execute_tools tests/unit/scripts -q > /tmp/09a_terminal.log 2>&1; rc=$?
```

**rc=0 — 9,842 passed, 1 skipped, 0 failed in 923.33s.** Verdict read from the
LOG, not a wrapper's exit status.

*Honest note on its breadth.* This is wider than the standing evidence-economy
rule prefers — eight top-level unit directories is close to the full local
suite, and the rule's default is 0 local full-suite runs because the canonical
repository-wide evidence is the ONE exact-head PR CI. It was run once, at the
final executable head, because Step 09a changed schemas (`HyperparamTuningOutput`,
`InterpretationInput`/`Output`, `ModelRunSummary`), a restore path and a
workflow signature — a fan-out the per-commit targeted suites do not bound. It
is recorded as what it is rather than relabelled "targeted", and it is NOT
repeated: the PR CI below is the canonical run.

**Static checks.** `ruff check` and `ruff format --check` clean across
`nodes/ agent/ core/ workflows/ execute_tools/ scripts/ tests/ examples/`.
**pyright was NOT run locally and is NOT claimed** — CI owns it.

**Gates.** Gate 1 = 0, Gate 2 = 0, real LLM = 0, real training/inference = 0,
GPU = 0, external API cost = 0 — exactly the frozen §7 disposition.

**Exact-head CI, and the two heads that preceded the final one.** pyright is
the one check this repository cannot run from the system node (v10.19 cannot
execute pyright's vendored bundle), so the first two PR heads failed on it:

| head | CI run | result |
|---|---|---|
| `fd9739fb` | 32310070368 | FAILURE — 5 pyright errors: the package `__init__` did not re-export `reconcile_metric_spec` / `InterpretationContractError` (runtime works through the `sys.modules` rebind; a type checker reads the explicit import list), and a set comprehension widened `MetricDirection` to `str` |
| `39afca72` | 32310562165 | FAILURE — 1 pyright error: the replacement `set[MetricIdentity]` is not provably hashable, because `frozen=True` lives in a runtime `ConfigDict` |
| `44121989` | 32311341230 | **SUCCESS** — fixed by declaring `set[tuple[str, MetricDirection]]`, which keeps hashable entries AND the Literal |

After run 32311341230 the local pyright limitation was solved rather than
worked around: a modern node (v26) ships inside `~/.cache/pyright-python/
nodeenv`, so `PATH=…/nodeenv/bin pyright` runs the real checker locally.
**0 errors, 13 warnings** at the final head — the same 13 pre-existing
warnings CI reports, none in files this PR touches. This is recorded because
§10.3-§10.8 each say "pyright NOT run locally — CI owns it", which was true
when written and is no longer the whole story.

**Pre-merge closeout (operator review 2026-08-19).** Two bounded items, both
applied at the final head: the §4 ledger synchronization (47 boxes ticked
against already-recorded evidence — which surfaced F-09a-25, a planned test
UPGRADE that had never been executed and had left an integration file broken
outside CI), and the F-09a-17 single-authority audit (CENTRALIZED; see §10.5).
The closeout ran only the narrow owning suites — the C4 file (60 passed), the
interpreter directory (422 passed), the pseudo integration file (5 passed),
schemas + protocols + boundary (867 passed), resume + workflows (325 passed),
ruff, and pyright — never the broad sweep again.

## 11. Final adversarial consistency pass (ruling §12 — 24 attacks) and freeze record

### 11.1 The 24 attacks, re-read against the FULL child at freeze

1. *Does C1 extraction preserve one main node + the old import surface?*
   YES — `result_interpretation_agent.py` keeps the class, `run()`, the CLI,
   the lifecycle; the five production import sites of
   `tuning_output_to_model_run_summary` (§3.1) resolve through narrow
   re-exports; moved names are defined once (§4.2 acceptance); the
   boundary test's outward/inward halves + the generalized acyclicity /
   `__all__` halves enforce it.
2. *Exactly ONE production MetricSpec authority?* YES — the tuner's `:541`
   binding, transported (§3.2); `reconcile_metric_spec` compares
   transported values, derives nothing.
3. *Did any compatibility path secretly call `derive_tidmad_metric` again?*
   NO — the C2 executable census (§4.3 acceptance) pins the production
   call-site set; the pr3 FIXTURE stamp is test-fixture construction in a
   module unreachable from production (Q-09a-7).
4. *Does every score-bearing path fail closed without a stamped spec?*
   YES — `InterpretationInput` validator (clause a), the builder's own
   `order` requirement when it would rank (§3.3), `_build_per_model_prompt`
   flag-ON guard; cold start / scoreless keep the named absence; negative
   owners named (§4.3).
5. *Are all discovered direction consumers enumerated exactly once?* YES —
   §2.2 rows 1–21, each with one migration; the count reconciliation
   paragraph ties 21 child rows to the parent's 15 (+4 erratum) entries.
6. *Do lower/higher and positive/negative hand cases prove the census is
   substantive?* YES — C3 per-site inversion suite under
   `direction_only_spec()`, tie pins, planted-offender census proof, and
   the Step-06 C5 MIGRATED-list extension; C4's 20-cell matrix covers all
   four direction×sign quadrants.
7. *Does `generate_discoveries` retain exactly the frozen 0.05 margin?*
   YES — `abs(best - sota) <= 0.05 * abs(sota)`; width unchanged; no
   retuning; no third counter (§3.3, §4.4, Q-09a-5).
8. *Does the prediction band retain the parent's exact semantics?* YES —
   §3.4 reproduces parent §13 ¶1 verbatim (distance/band_width,
   `is_better`, `<=` inclusive, gain = distance when confirmed).
9. *Is uncomputable always UNEVALUATED and excluded from all comparable
   counters/discoveries?* YES — §3.4 table row; `generate_discoveries`
   explicit branch; E.4 ignores it; mutation (ii) pins it.
10. *Are v1 and v2 counters/gains never silently pooled?* YES — per-field
    table (§3.4): legacy dict/scalar copied unchanged; v2 in
    `_by_semantics` dicts; `prediction_pool_sizes` explicit; mutations (iii)
    and (iv) pin it; accuracy labelled by `prediction_evaluation_semantics`.
11. *Does the production lifecycle actually carry the new v2 state after
    C5?* YES — loop carry + `RestoredState` restore + `run_one_iteration`
    forward + first-input seeding; two-iteration pseudo-chain acceptance
    (§4.6).
12. *Does C5 use the existing canonical workflow/resume path rather than a
    new memory mechanism?* YES — the digest stays the ONE store;
    `PredictionMemory` is a carrier; one loader sibling of the fingerprint
    loader; same latest-wins idiom.
13. *Does any `RestoredState` change exceed the narrow interpreter-owned
    fields?* NO — exactly one additive field; every other restored field
    pinned equal to the pre-09a restore (§4.6 negative).
14. *Are legacy/pre-09a score-bearing outputs refused rather than
    re-derived?* YES — Q-09a-6 wording in §4.3; no derivation at
    interpreter / workflow / CLI / resume / PR3 path.
15. *Is Q-09-7 = B still intact?* YES — §3.5, §4.7 must-not list; builder
    projects no secondaries; no record field, evaluator, loader, binding,
    transport; no placeholder values.
16. *Are secondary metrics observational only and unable to reach any
    primary `MetricOrder` consumer?* YES — AST census (no
    `secondary_metrics` reference in any `order`/`MetricOrder`-consuming
    function) + behavioural inertness test + planted offender (§4.7).
17. *Does TIDMAD retain higher-is-better ordering exactly?* YES — the
    shipped spec is `higher`; every migrated site returns the identical
    value/order; C1a oracle byte-identical at C3; prompt goldens EXACT
    throughout.
18. *Do Pets and DAVIS fixtures remain L1 contract evidence, not maturity
    inflation?* YES — `_fixture.label = "l1_fixture"`, notes naming "NOT a
    real tuning output" and "secondaries not evaluated in production
    (Step 10)"; STATUS rows keep the maturity vocabulary (§3.6, §4.8).
19. *Are PB-0/PB-7/PB-8 template-byte parity claims scoped correctly
    against the intended deterministic digest-content changes?* YES — the
    11 prompt goldens stay byte-identical (templates + fixed-input user
    prompts); digest/content deltas are owned by the C1a differential
    oracle and declared per commit (§1 frozen invariants; §7).
20. *Are every test/census/mutation owner and anti-vacuity proof
    explicit?* YES — §4 per commit (named owners, planted offenders,
    recorded mutations); §5 disposition; §6 evidence economy.
21. *Are C1→C7 semantic boundaries coherent and independently
    reviewable?* YES — each commit's "Commit boundary" line; dependencies
    form a chain C1a → C1b → C2 → C3 → C4 → C5 → C6 → C7.
22. *Does 09a still add zero task-name branches, zero subsystem loaders,
    zero per-task vocabulary growth?* YES — §3.8 matrix; the only new
    vocabulary is the two framework version ids.
23. *Does Step 12 still supply the SAME MetricSpec / interpretation
    contracts without replacing 09a?* YES — the composition root supplies
    the same typed `MetricSpec` value to the same carriers (parent §22);
    no interpreter loader exists to swap.
24. *Does any main node/module become MORE mixed after this PR?* NO —
    C1b removes the deterministic pre-computation, the E.4 arithmetic and
    the evidence projection from `run()`; the helpers file loses the
    prediction cluster; no new responsibility is added to any main file
    (the parent §13a.5 discipline).

### 11.2 Numeric reconciliation (ruling §12)

| claim | number | where |
|---|---|---|
| interpreter direction-literal sites | **21** child rows = parent 15 table entries (+4 erratum ⇒ 16 entries; band entry expanded to its 3 literals ⇒ 17 rows) + 4 E1 sites | §2.2 |
| production import sites of `tuning_output_to_model_run_summary` | **5** (workflow, preflight, runner, protocol, package `__init__`) + tests | §3.1 |
| REC-3 schema-golden regenerations | **3** (C2: +1 `InterpretationOutput`, +1 `HyperparamTuningOutput`; C4: +4; C6: +2) ⇒ `InterpretationOutput` 35 → 42, `HyperparamTuningOutput` 46 → 47; no pin over `InterpretationInput` (21 → 24) or `ModelRunSummary` (30 → 35) | §5 |
| prompt goldens kept byte-identical | **11** files (PB-0 ×3, flag-ON ×2, PB-7 ×4, PB-8 ×2) | §2.7 |
| prediction band matrix cells | **20** | §4.5 |
| production spec-constructor call sites after 09a | **4 modules, unchanged** (tuner, scoring subprocess, sandbox fallback, the metric module's own composition); new production sites: **0** | §4.3 |
| `RestoredState` additive fields | **1** | §4.6 |
| git commits / semantic milestones | **8 / 7** (C1a, C1b, C2, C3, C4, C5, C6, C7) | §4 |
| operator questions open | **0** (7 RESOLVED) | §0.4, §8 |

Zero `SOURCE-INSPECTION REQUIRED` markers; zero unresolved `Q-09a-*`; zero
"conditional on Q-09a-*"; zero implementation `[x]`.

### 11.3 Freeze record and status sync (ruling §11/§13)

* Child status → **REVISION 2 — FROZEN**; Q-09a-1..7 RESOLVED (§0.4, §8);
  implementation boxes all `[ ]`.
* Parent (same freeze commit, NARROW factual erratum — architecture
  unchanged): §0.3 erratum note; §2.3 census +4 rows; §2.13/§8 prediction-
  pool carry/restore premise corrected (pre-09a source: none; frozen
  target: 09a C5 narrow carry/restore); §15 09a surfaces note; §19 rows.
* Roadmap §15.1 Step-09 row and the README index: DESIGN status only —
  Step 09 parent FROZEN (rev 2 + Q-09-7 = B); 09a child FROZEN rev 2 /
  IMPLEMENTATION NOT STARTED; 09b design not yet written. Nothing marks
  Step 09 implementation started.
* No implementation code; no Gate 1 / Gate 2 / training / inference / local
  full suite.
