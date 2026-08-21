# Step 10 / P3 — Proposer Typed Evidence + Prediction Authoring

## 0. Status

**REVISION 3 — FROZEN. OPERATOR APPROVED (freeze rulings 2026-08-20).
IMPLEMENTATION COMPLETE — MERGED 2026-08-21, PR #245, squash `254cbaa1466125873d6c7a72f59a7d25fd2c5619`.**

Implementation status (live; the ledger is §17):

| item | state |
|---|---|
| C0 · C1 · C2 · C3 · C4 | COMPLETE, each with recorded evidence (§17.3-§17.7) |
| Gate 1 (Q-P3-2) | **PASS** on the second candidate; the first was a genuine behavioural FAIL, diagnosed and corrected rather than re-run (§17.9) |
| Gate 2 / real training / real inference / GPU | NOT REQUIRED, NOT RUN |
| validation provenance | both operator-named gaps closed with tree-hash and exact-SHA evidence (§17.11) |
| adversarial debt review | operator-requested; three live test failures and several design/test defects found and FIXED; carried debt recorded (§17.12) |
| terminal exact-head CI | **32457848717 SUCCESS** on `31cdabaa3d720c1b796bb20202700bd309664eb9` (§17.14) |

The frozen sections below (§0-§16) are the design as approved and are NOT
rewritten by implementation; everything the implementation learned lives in
§17.

Revision 3 applies the operator freeze rulings to the PASSED Revision 2
(`79f300a6`; architecture verdict PASS, no redesign): **Q-P3-2 =
GATE_1_REQUIRED** (≤ 3 real calls, coverage CORRECTED to BOTH
comparison/SOTA interpretation AND causal prediction authoring under the
lower-is-better control), **Q-P3-3 = NO_RAW_SECONDARY_CONSUMPTION**,
**Q-P3-4 = INCLUDE / BOUNDED** (the F-P3-1 clamp migration is a mandatory
C2 item), plus two bounded freeze corrections — **C-P3-1** (Gate-surface
consistency: no wording may imply causal-only Gate coverage) and **C-P3-2**
(ordering-wording precision: P3 adds zero NEW ordering semantics/authorities
and MIGRATES the existing F-P3-1 site). Full rulings: §14/§14.1. Open
operator questions: **0**.

Revision 2 superseded DRAFT rev 1 (`2b59235f`, architecture-review PASSED
2026-08-20). Every `PROVISIONAL(P2a)` / `PROVISIONAL(P2b)` marker is resolved
against merged source; §13 is the full reconciliation table. Three findings
of that reconciliation changed the design materially and were flagged for
the freeze review (all three now dispositioned):

1. **Q-P3-1 (rev 1) is DISSOLVED BY SOURCE, not ruled.** The legacy path has
   NO prediction-authoring surface at all — `_run_legacy` never extracts a
   `falsifiable_prediction` and `PROPOSAL_COMMIT_PROMPT`'s JSON spec has no
   such field (§2.5). "Does legacy also get the direction-safe grammar?" has
   no referent; legacy byte parity is the only coherent state, not a choice.
2. **The `FalsifiablePrediction` schema description is NOT LLM-facing.**
   `LLMBridge.generate` sends prompts under `response_format=json_object`
   with NO schema attached (`agent/llm_bridge.py:1661-1698`), and
   `threshold_for_refutation` has ZERO production consumers (§2.5). Rev 1's
   "it is part of the structured-generation contract" is withdrawn. The
   LLM-visible authoring-grammar surface is exactly ONE example block in one
   template, plus the absence of any direction statement anywhere (§2.6).
3. **F-P3-1 — a thirteenth direction site, on this child's own file.**
   `clamp_comparative_analysis` (`nodes/proposal_helpers.py:521,555`) selects
   which comparison entries survive prompt clamping by `best_score`
   DESCENDING, through a `_score` helper indirection that the P2a scanner's
   deliberate one-hop alias rule cannot see (§2.7.1). Under DAVIS it curates
   the WORST models' evidence into later-stage prompts. **Dispositioned:
   Q-P3-4 = INCLUDE / BOUNDED — a correctness closure, not scope creep
   (operator freeze ruling, §14.1).**

| field | value |
|---|---|
| parent | Step-10 parent REVISION 2 (FROZEN), §3.6 / §11 / §11.2 (ruling FROZEN) / §11.3 / §20.6 / §22.1; owns scope item **S4** |
| source anchor | merged `master` = **`06291e5f`** (post-P2b status sync; production tree == the P2b squash `5a2ecfd1`). Every §2 line anchor was measured here in this session. Line anchors are evidence, not implementation authority |
| depends on | **P2a MERGED** (`e094fa26` — ordering closed; the C4 threading note addressed to P3 is in source at `proposal_helpers.py:36-43`) and **P2b MERGED** (`5a2ecfd1` — secondaries real; **its diff touches ZERO proposer files**, verified §2.4) — **both satisfied** |
| downstream | **P5** consumes the typed boundary this child creates (its consumer wiring is `PROVISIONAL(P3)` on its side; P5 freezes AFTER P3 merges); **P6** runs the loop through it |
| Gate disposition | **FROZEN (Q-P3-2): Gate 1 REQUIRED — ONE bounded run, ≤ 3 real calls, covering BOTH comparison/SOTA interpretation AND causal prediction authoring under a DAVIS-shaped LOWER-is-better fixture** (§8.2, C-P3-1); verdict from persisted stage artifacts, never from prompt inspection alone. **Gate 2 NOT REQUIRED — FROZEN** (§8.3) |
| open operator questions | **0** — Q-P3-2 / Q-P3-3 / Q-P3-4 RESOLVED by operator freeze rulings (§14, dispositions §14.1). Q-P3-1 was RESOLVED BY SOURCE in rev 2 |

**Frozen by the parent regardless of this revision's fate** (§11.2, operator
ruling 2026-08-20): both entrypoints survive; both consume ONE typed
proposer-facing evidence value produced by the protocol; they may RENDER it
differently; neither may independently mine a raw dict; legacy prompt bytes
are preserved through an ADAPTER from the typed value, never by preserving
raw-dict ownership; and no new evidence field may ever again need wiring into
two readers.

---

## 1. Parent contract (recovered, binding)

* **§3.6**: there is no typed reader to consolidate — there are TWO untyped
  ones over `ProposalInput.interpretation: dict[str, Any]`. Production uses
  the PIPELINE reader; legacy is reachable via `llm_config=None` and the
  node's standalone CLI. The whitelist is effectively unpinned (deleting its
  prediction keys leaves every unit test green).
* **§11.2 (FROZEN)**: retain the reachable legacy/standalone ENTRYPOINT;
  remove the duplicated semantic READER. Acceptance is the executable rule
  that no new evidence field can require wiring into two readers.
* **§11.3**: the one production direction defect (`proposal_helpers.py`
  `top_n`) was **P2a's** to migrate — **DONE, merged** (§2.3). The
  prediction-AUTHORING grammar is P3's, "because it is the same child's
  evidence surface".
* **§20.6**: P3 is separate because it is a node-boundary redesign with its
  own Gate-1 exposure.
* **§22.1 (FROZEN)**: P3's evidence owner = "typed-contract tests on BOTH
  entrypoints + prompt-byte parity for the legacy adapter"; "Gate 1 only if
  parity cannot be proven — this is the child most likely to need it".
* **Q-10-2 heritage** (P2a §4.0/§4.2): identity ≠ direction; the proposer
  never re-derives either; a consumer without identity refuses to rank with
  the visible named absence, and assumed higher-is-better is FORBIDDEN.
* **Parent §5 non-goal 3 + roadmap §15.1b**: "any task's science" is not
  Step 10's; *proposer-side task-science prompt ownership is Step 10/12* —
  deliberately unassigned to any Step-10 child. P3 therefore does NOT
  migrate the proposer's TIDMAD prose (the "signal denoising" persona, the
  wavenet/5.57 examples, `_format_known_constraints_block(DATASET_CONFIG)`,
  the `TIDMAD` imports at `ml_model_proposal_agent.py:48,512`); §3 lists
  them as named non-goals with the one exception D2 absorbs (the
  `'denoising_score'` literal inside the grammar example it re-renders).
* **Parent §5 non-goal 7**: dead proposer reads are Step-09.5 class-C debt,
  repairable in passing ONLY when a Step-10 change touches that exact line —
  P3's C3 touches exactly those lines, so their deletion is authorized.

---

## 2. Current source audit (RE-MEASURED at `06291e5f`)

### 2.1 The input surface and every entry path

`ProposalInput.interpretation: dict[str, Any]` (`agent/schemas/proposal.py:650`),
populated by the protocol with the FULL dump: `"interpretation":
output.model_dump()` (`agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py:172`).

Every production `ProposalInput` construction site, and the §4 audit answers:

| entry path | site | evidence object entering | typed? | persisted or in-memory? | re-derives anything? | has metric id+direction? | sees secondaries? | authors predictions? | can diverge from production? |
|---|---|---|---|---|---|---|---|---|---|
| **workflow (production)** | `workflows/model_exploration.py:2309` via `local_full_context` + post-hoc field assignments `:2331-2356` | full `InterpretationOutput.model_dump()` | NO — raw dict | in-memory | no (P2a C4 reads the dict's `metric_identity`; nothing derived) | in the dict (`metric_identity`), read ONLY by `_interpretation_order` | in the dict (`per_model_secondary_metrics`), read by NOTHING | YES (pipeline causal stage) | it IS production |
| **standalone CLI** | `ml_model_proposal_agent.py:2310-2383` — loads `interpretation_{run_name}.json` `:2328-2335`, builds `ProposalInput` directly `:2347-2357` | the interpreter's persisted `model_dump_json` (`result_interpretation_agent.py:1035-1037/:1143-1145` — same shape as the in-memory dump) | NO — raw dict | persisted | no | in the file, unread (CLI runs LEGACY mode — no `reasoning_pipeline` ⇒ `has_pipeline` falsy at `:1470-1477`) | in the file, unread | NO (legacy mode, §2.5) | YES — different reader, different prompt |
| **audit / calibration scripts** | `scripts/render_proposer_prompts_for_audit.py`, `scripts/pr3_l2_calibration/{runner,preflight}.py` | via `local_full_context` | NO | fixture/in-memory | no | as production | as production | as configured | no — they ride the protocol |
| **lit-review channel** | `agent/schemas/protocols/ml_literature_review_to_ml_model_propose.py` | returns 4 channel kwargs (expert_context / vocab_seed / agent_cards / mindset) that feed the SAME `local_full_context` call | n/a | n/a | no | n/a — it never carries interpretation | no | no | no — not a second constructor |

**Conclusion**: exactly ONE protocol constructor plus ONE direct-raw-JSON
constructor (the CLI). A projection called by the protocol and by the CLI
covers every path. No other production module reads
`ProposalInput.interpretation` (repo grep, this session).

### 2.2 The two readers — re-measured

Dispatch: `:1470-1477` — `_run_pipeline(inp) if has_pipeline else
_run_legacy(inp)`. Raw interpretation reads (`interp*.get(` /
`interpretation[`): **40** in the node module, **12** in
`nodes/proposal_helpers.py` (rev 1 counted 11; P2a C4 added the
`metric_identity` read — the count moved for a known, cited reason).

| reader | entry | shape | reads |
|---|---|---|---|
| LEGACY | `_build_reasoning_prompt` `:1086-1309` (224 LOC), via `_run_legacy` `:1503-1569` | flat markdown prompt | its own `.get()` set incl. **two DEAD reads** — `per_file_comparison` (`:1180`) and `efficiency_comparison` (`:1184`), fields `InterpretationOutput` does not declare (re-verified against the 42-field schema) — plus legacy-only LIVE `best_valid_denoising_score` (`:1108`) and `best_config` (`:1227`); renders the track record through the ONE 09b authority (`:1157-1163`) |
| PIPELINE | `_run_pipeline` `:1575-2240` (666 LOC) | the **18-key whitelist** into `accumulated["interpretation_summary"]` (`:1669-1699`, key tuple re-counted: 18) + **5 direct reads** (`model_knowledge_cache` `:1620`, `model_descriptions` `:1621`, `per_model_best_valid` `:1622`, `per_model_score_tables` `:1623`, `model_types` `:1626`) | production path |
| shared | `_format_healthgate_evidence_block` `:789-896`, called from BOTH paths (`:1274` legacy, `:1747-1751` pipeline), flag-gated | health evidence block | `per_model_round_health_counts`, `per_model_collapse_fingerprints`, `collapse_fingerprint_history`, `model_types` (`:816-825`) |
| shared | `run()` `:1466-1468` | banner print | `model_types` |
| helpers | `select_candidate_models` `:81-89`, `resolve_exploration_mode` `:409,:417`, `_interpretation_order` `:50` | candidate summaries / mode / order | 12 reads: `model_types` (×2), `per_model_best`, `per_model_best_valid`, `per_model_raw_best_health_validity`, `per_model_worst`, `per_model_score_tables`, `per_model_params`, `model_descriptions`, `per_model_training_segments`, `vocab_diversity_ratio`, `metric_identity` |

**The measured LIVE read-union is 30 of `InterpretationOutput`'s 42 fields.**
NOT read by the proposer (and therefore NOT projected — §4.1's non-goal
evidence): `cold_start` (already a typed `ProposalInput` field via the
protocol), `scientific_aggregation`, `best_valid_config`, `runtime_vocab`
(protocol maps it to `vocab_seed`), `prediction_evaluation`,
`new_discoveries`, `vocab_changes`, `vocab_link_confirmations` (P5's),
`is_degraded`, `evolution_stats`, `per_model_failure_counts`,
`per_model_secondary_metrics` (Q-P3-3), plus the 2 dead read targets.

Measured drift (parent §3.6, re-confirmed): LEGACY-only live reads exist that
PIPELINE never sees (`best_valid_denoising_score`, `best_config`) and vice
versa (`model_knowledge_cache`, `prediction_pool_sizes`,
`prediction_evaluation_semantics`, and now `metric_identity` — pipeline-only
via the helpers). The source records two drift incidents found by live Gates
rather than review (`:1257-1263`, `:1741-1746`).

### 2.3 What P2a landed on this surface (consumed, not re-litigated)

* `_interpretation_order` (`proposal_helpers.py:28-51`): reads
  `interpretation.get("metric_identity")` through
  `metric_identity_from_mapping` (the ONE transported-identity validator,
  `execute_tools/evaluation_metric.py:927-961`) → `MetricOrder | None`. Its
  docstring `:36-43` is an explicit note TO P3: *"supply this same identity
  through that reader and delete this function — the semantics to preserve
  are 'read the declared identity, never assume a direction, and fall back
  to order-free `all` when it is absent'"*. **P3 does exactly that.**
* The `top_n` cut (`:115-140`) asks `order.rank`; absent identity takes the
  Q-P2a-1 order-free `all` fallback with the canonical notice
  (`metric_identity_unavailable_notice`, `evaluation_metric.py:733-750`,
  phrase constant `METRIC_IDENTITY_UNAVAILABLE` `:730`). **The comparison
  itself is P2a's and is NOT re-touched.**
* Pins P3 must flip (guard-disposition table §2.8):
  `test_the_helper_signature_did_not_change` and
  `test_no_typed_evidence_reader_was_introduced`
  (`tests/unit/nodes/test_step10_p2a_c4_proposer_top_n.py:194-211`) — both
  written expressly to be retired by P3.

### 2.4 What P2b landed (consumed, not extended) — and what it did NOT touch

* `git diff --name-only 3dc298f1 5a2ecfd1` contains **ZERO proposer files**
  (no `ml_model_proposal_agent*`, no `proposal_helpers.py`, no
  `proposal.py`, no proposer protocol, no proposal templates). The rev-1
  §13 obligation "P2b touched no proposer reader" is DISCHARGED.
* Secondaries are now real: `InterpretationOutput.per_model_secondary_metrics:
  dict[str, list[SecondaryMetricEvidence]]` (`interpretation.py:1272`)
  carries `spec` (each metric's OWN direction) + `status ∈ {scored, refused,
  unavailable}`; 09b's `render_secondary_metrics`
  (`agent/prompt_templates/interpretation/rendering.py:298-332`) renders the
  three states with per-secondary direction words.
* **The planner-exposure precedent (binding rationale for Q-P3-3)**: P2b
  extended `_PLANNER_HIDDEN_RECORD_KEYS` (`agent/prompts.py:944-960`) to hide
  all three secondary carriers from the tuner's planner, with the recorded
  reason: *"showing the planner a second, differently-directed number beside
  the one it is optimising invites it to trade the two off, which is exactly
  the vote secondaries must never get"* — and the crash carrier is "an
  operator-facing diagnostic about the implementation, not a fact about the
  science".
* The 09a ordering-operand invariant
  (`tests/unit/agent/result_interpretation_agent/test_step09a_c6_evidence_projection.py`)
  scans `INTERPRETER_FILES + PRODUCTION_FILES` — **no proposer file is in
  either list**. Whatever Q-P3-3's ruling, P3's C0 extends the scanned
  surface to the proposer files with a plant proving the extension is live
  (the P2b precedent: extend scope BEFORE values can arrive).

### 2.5 Prediction authoring — the surfaces, re-measured precisely

**The evaluation half is done and frozen** (09a): `evaluate_prediction`
(`nodes/result_interpretation_agent/prediction.py:98-216`) takes a REQUIRED
keyword-only `order: MetricOrder` and decides `confirmed =
order.is_better(actual, sota)`, `partial = distance <= 0.05·|sota|`
(inclusive), else `refuted`; uncomputable ⇒ `unevaluated`, in NO pool. Two
facts rev 1 did not state:

* **`threshold_for_refutation` is a DEAD field downstream.** The evaluator
  never reads it; repo-wide, its only non-fixture occurrence is its own
  schema declaration (`proposal.py:57-61`). It is authored, persisted, and
  consumed by nothing.
* **The schema description is NOT LLM-visible.** `LLMBridge.generate`
  (`agent/llm_bridge.py:1661-1698`) sends system+user text under JSON mode
  with no schema attachment. Rewriting `:57-61` is a documentation
  correction, not an LLM-facing delta.

**The authoring half — the complete LLM-visible surface** (every proposer
prompt file + both system-prompt constants audited this session):

| surface | direction posture | LLM-visible? |
|---|---|---|
| `causal_reasoning_stage.md:102-126` example JSON block — `current_value: 1.5, predicted_value: 2.5, threshold_for_refutation: 1.2`, metric example `'denoising_score'` | **upward-only pattern**; a pattern-matching model under `lower` authors an inverted band | YES — the base template is shared by both exploration modes (`{# EXPLORATION_MODE_BLOCK #}` at `:164` injects the variants; `load_stage_prompt`, `agent/prompt_templates/proposal/__init__.py`) |
| `causal_reasoning_stage_{explore,exploit}.md` "Methodology — falsifiable_prediction" sections | direction-NEUTRAL ("predict a specific score outcome... delta") | YES |
| base template rule 2 (`:138-142`) boldness formula | direction-neutral (magnitude: `abs(predicted-current)/abs(current)`) | YES |
| `comparison_stage.md:74-76` — the LLM is asked to author `sota_model_type` / `sota_score` / `sota_mechanism`; examples `:63` ("scores 5.57 ... score below 2.0") and `:71` ("top 3 models") | **SOTA identification is DELEGATED to the LLM with no stated direction**; the examples imply higher-is-better | YES |
| every other proposer prompt surface | **NO surface states the run's metric identity or direction, anywhere** — `MetricSpec`/`MetricOrder`/`metric_identity` render into zero proposer prompt bytes today | — |
| `FalsifiablePrediction.threshold_for_refutation` description (`proposal.py:57-61`) | inverted under `lower` ("Below this value... refuted ... threshold < current") | NO (see above) |
| `DiscoveryMemo.sota_model_type` description "best-scoring model" (`:408-410`) | direction-safe ("best") | NO |

**What is already direction-safe and must NOT be re-touched**: `boldness`
(magnitude); `_prediction_differs_from_current` (`proposal.py:74-81`); the v2
evaluator and its versioned pools; `render_prediction_track_record`
(direction-agnostic by construction; already the ONE shared authority for
both consumers, `rendering.py:335+`); the boldness runtime check
(`ml_model_proposal_agent.py:1876-1960` — reads `pred.boldness` only).

### 2.6 Direction-vocabulary audit (task-mandated classification)

Grep set `higher|lower|better|worse|improve|degrade|increase|decrease|
maximize|minimize|top|best|above|below` over the proposer's three modules,
nine templates and both system-prompt constants. Classification:

| class | sites | disposition |
|---|---|---|
| **stale/hardcoded (direction-encoding)** | the causal example block values (§2.5 row 1); the comparison-stage example prose implying higher (§2.5 row 4); `clamp_comparative_analysis`'s descending retention draw (§2.7.1) | the D1/D2/D3 deltas + F-P3-1 |
| **direction-safe (uses better/worse/improve semantics, valid under both directions)** | "improve performance/the score" (`causal_reasoning_stage.md:9-11,:105`), "best estimate", "best-scoring", legacy "Overall raw best/worst" labels (labels over values, no comparison) | UNCHANGED |
| **direction-independent** | boldness (magnitude); `strong_prior or higher` (`causal_reasoning_stage.md:90` — trust levels, not scores); "top-level markdown", "top of the prompt" (positional); registry/branch prose | UNCHANGED |
| **already routed through an authority** | `top_n` via `order.rank` (P2a C4); track record (09b) | UNCHANGED |

### 2.7 New findings of this reconciliation

#### 2.7.1 F-P3-1 — the clamp's best-score retention draw (a 13th direction site)

`clamp_comparative_analysis` (`nodes/proposal_helpers.py:466-558`) clamps
`DiscoveryMemo.comparative_analysis` to Draw A = "top 3 by `best_score`
DESCENDING" (`:521` `sorted(indexed, key=lambda it: (-_score(it), it[0]))`;
truncation repeat at `:555`), where `_score` (`:514-516`) reads
`item[1].get("best_score")` and maps missing → `-inf` ("missing sorts as
worst" — itself a higher-is-better assumption). Under a `lower` metric the
draw retains the WORST three models' comparison entries in every later-stage
prompt whenever the pool exceeds `top_k` (default 5).

* It is a golden-metric preference decision under P2a §4.0's frozen contract
  ("no raw `reverse=True`/sort may independently encode primary-metric
  preference"), on values the LLM copies from the run's primary scores
  (`ModelComparison.best_score`, `proposal.py:340`).
* It is ABSENT from P2a's 12-site table and from its pinned
  NOT-direction-sensitive list (P2a §2.1/§2.2), and **invisible to the P2a
  scanner by construction**: `GOLDEN_SCORE_NAMES` includes `best_score`
  (`test_step10_p2a_c0_ordering_scanner.py:93`), but the sort key's text
  (`-_score(it)`) contains no golden token, and the scanner's alias tracking
  is deliberately ONE-hop assignment-shaped (`:194-232` — transitive taint
  measured 22 false positives vs 12 real sites). A function-call indirection
  defeats it. This is the F-P2b-4 pattern class — a census green for a
  reason narrower than its claim — surfacing in a second census, exactly as
  that finding predicted.
* Consequence class: prompt-EVIDENCE curation (which comparisons the model
  sees), not a ranking output — smaller than the `top_n` inversion, but the
  same scientific sign error feeding every post-clamp stage.

Disposition: **Q-P3-4 = INCLUDE / BOUNDED (operator freeze ruling, §14.1)**
— a bounded correctness closure, not scope creep: the fix's mechanism IS
P3's typed evidence (the same identity, through the same reader, with the
Q-P2a-1 absence rule), the file is P3's own primary surface, and parent
acceptance criterion J cannot close for Step 10 with a known unmigrated
direction site left as debt. The scanner itself is NOT extended (its
one-hop precision contract is deliberate and stays — the ruling forbids
widening its transitive-taint behavior for this site); the site's standing
guard is the set of hand-computed behavioral fixtures (§7 C2), and the
blind-spot class is recorded in the scanner's docstring per the F-P2b-4
rule (per-census, when touched).

#### 2.7.2 The dead typed mirror

`ProposalInput.per_model_score_tables` (`proposal.py:691-698`, populated by
the protocol at `:185-188`) has **zero readers anywhere** — the node reads
the dict copy exclusively. "Consumers may read either" describes a choice no
consumer ever made. It is a third carrier of one value (dump + typed mirror
+ nothing). Disposition: REMOVED in C3 together with the raw dict field —
the typed evidence's `per_model_score_tables` becomes the ONE carrier.

#### 2.7.3 The schema import cycle the typed value must not create

`agent/schemas/interpretation.py:32` imports `VocabEntry` FROM
`agent/schemas/proposal.py` — a backwards edge (upstream node schema
importing from downstream node schema). Any module that (a) declares types
drawn from `interpretation.py` (`MetricIdentity`, `SecondaryMetricEvidence`,
`CollapseFingerprint*`) and (b) is imported by `proposal.py` for the new
`ProposalInput` field closes the cycle
`proposal → proposer_evidence → interpretation → proposal`. Resolution
(§4.2): relocate `VocabEntry` to a new `agent/schemas/vocab.py` with a
backward-compatible re-export from `proposal.py` — measured cost: ONE import
line changes outside the new module (`interpretation.py:32`); every other
`from agent.schemas.proposal import … VocabEntry` site (single- and
multi-line forms — C1 pins the exact inventory) keeps working through the
re-export.

#### 2.7.4 No direction statement reaches the proposer, and SOTA choice is delegated

§2.5 rows 4-5: the comparison stage asks the LLM to identify the SOTA and
nothing anywhere tells it which direction is better — under DAVIS the model
must GUESS from TIDMAD-typical examples. The typed contract alone cannot fix
this (it is a prompt-content gap); D1 (§4.5) closes it by rendering the ONE
existing identity-statement authority into the two stages that decide or
author (comparison + causal).

### 2.8 Guard-disposition table (every pin P3 turns red, and how it retires)

| guard | pins today | P3 disposition |
|---|---|---|
| `test_the_helper_signature_did_not_change` (`test_step10_p2a_c4_proposer_top_n.py:194-201`) | `select_candidate_models(interpretation, strategy)` — recorded "because P3 will replace the mechanism" | RETIRE in C2, replaced by the typed-signature test; the SEMANTICS it protected (declared identity · never assume · order-free fallback) re-pinned on the typed path |
| `test_no_typed_evidence_reader_was_introduced` (`:203-211`, asserts zero classes in `proposal_helpers.py`) | no reader type before P3 | RETIRE in C1 (its stated purpose arrives); the ONE-authority census (§8.1) is its successor |
| PB-3 goldens (`tests/unit/agent/ml_model_proposal_agent/goldens/pb3_*`) — pipeline stage system+user bytes at the LLM boundary | pipeline prompt bytes | KEEP as the parity baseline; C0 adds a FULL-coverage fixture (all 18 whitelist keys + legacy-only fields + health fields + identity — the parent measured the current fixture carries 8/18 and none of the four prediction keys); C4 re-captures ONLY the enumerated delta surfaces |
| PB-4 / S1-E goldens (`pb4_legacy_*`, `s1e_legacy_reasoning_system.txt`) + `test_step01b_legacy_reasoning_golden.py` | legacy prompt bytes | KEEP — legacy is byte-exact THROUGH the adapter (C3 acceptance) |
| WF-3 components key set (`wf3_proposer_components_key_sets.json`) | `_audit_proposer_components` 11-key breakdown | KEEP unchanged — the audit reads `accumulated`, whose shape is preserved (§4.3) |
| 09a ordering-operand invariant (`test_step09a_c6_evidence_projection.py`) | no ordering expression takes a secondary operand, over interpreter+P2b files | KEEP; **scope EXTENDED in C0** to the proposer node, helpers, schema and protocol, plant-proven |
| P2a C4 behavioral fixtures (DAVIS inversion, Pets, TIDMAD, absent-identity `all`) | `top_n` semantics | KEEP — must stay green across C2's mechanism swap (the comparison is untouched) |
| health-block tests (`test_health_evidence_block.py`, `test_health_prompt_parity.py`) incl. the malformed-history ValueError | flag-gated health rendering | UPGRADE in C2: rendering parity preserved; the malformed-entry failure MOVES from render-time to projection-time (typed `CollapseFingerprintHistoryEntry` validation) — declared behavior delta, fail-closed earlier |

### 2.9 Source-site disposition table (audit → target)

| source site | current input shape | target after P3 | disposition |
|---|---|---|---|
| protocol `:172` | `output.model_dump()` → raw dict field | protocol calls `build_proposer_evidence(...)` → typed field | REWRITE (C1) |
| protocol `:185-188` | dead typed mirror population | removed with the mirror | DELETE (C3) |
| pipeline whitelist `:1669-1699` | raw dict, 18 keys | ONE serializer over the typed value, byte-exact keys/order/`is not None` filtering | MIGRATE (C2) |
| pipeline direct reads `:1620-1626` | raw dict, 5 keys | typed fields | MIGRATE (C2) |
| helpers 12 reads incl. `_interpretation_order` | raw dict fragments | typed fields; `_interpretation_order` DELETED per its own docstring; `top_n` comparison untouched | MIGRATE (C2) |
| `_format_healthgate_evidence_block` `:789-896` | raw dict, 4 keys | typed fields (moves to the private rendering module) | MIGRATE (C2) |
| `run()` print `:1466-1468` | raw dict | typed field | MIGRATE (C2) |
| legacy reader `:1086-1309` | raw dict | ADAPTER renderer over the typed value; bytes == goldens; 2 DEAD reads deleted; legacy-only LIVE reads become typed fields | MIGRATE (C3) |
| standalone CLI `:2328-2357` | persisted JSON → raw dict | the SAME projection over the loaded mapping | MIGRATE (C3) |
| `ProposalInput.interpretation` `:650` | `dict[str, Any]` | REMOVED (not deprecated), replaced by `interpretation_evidence` | REMOVE (C3) |
| authoring grammar: causal example block; comparison sota wording; absent direction statement | static template text | D1/D2/D3 rendered/rewritten surfaces (§4.5) | REWRITE (C4, declared LLM-facing delta) |
| `threshold_for_refutation` description `:57-61` | inverted prose | direction-neutral prose (non-LLM-facing doc fix) | REWRITE (C4) |
| clamp draw `:521,:555` | `best_score` descending | order-aware retention from the typed identity; absent ⇒ recency-only (Q-P2a-1 shape) | MIGRATE (C2 — Q-P3-4 = INCLUDE, frozen) |

---

## 3. Goal / semantic owner / boundary

**One semantic owner: the proposer-facing interpretation-evidence contract
(+ the prediction-authoring grammar that renders from it).**

After P3: the protocol produces ONE narrow typed value; both entrypoints,
the helpers and the health block consume it; the raw `interpretation` dict
field and the dead typed mirror are GONE from `ProposalInput`; the legacy
prompt is produced by an adapter over the typed value at byte parity; the
pipeline's prompts state the run's metric identity once and render a
direction-correct authoring example from it; a planted new raw semantic
reader turns a census RED.

**Ownership table (explicit, mirrored where the peer child owns the line):**

| concern | owner | P3's relationship |
|---|---|---|
| proposer-facing evidence TYPE + projection | **P3** | creates |
| pipeline/legacy/CLI convergence at the typed boundary | **P3** | creates |
| prediction-authoring grammar (direction-safe, identity-stated) | **P3** | creates (parent §11.3) |
| primary ranking semantics, `MetricOrder`, reconciliation, unavailable formatter | **P2a (merged)** | consumes verbatim; adds NO authority |
| the `top_n` comparison | **P2a (merged)** | mechanism swap only (identity via the typed value); behavior pinned unchanged |
| secondary production/evaluation/persistence/rendering | **P2b (merged) / 09b** | NOT consumed (Q-P3-3 = NO_RAW_SECONDARY_CONSUMPTION, frozen §14.1) |
| secondary ordering | **FORBIDDEN** (09a invariant) | scope-extends the invariant to its own files |
| cross-iteration carry / restore / `accumulated_key_findings` / vocab confirmations | **P5** | none — the value is built per invocation; P5 consumes the typed boundary later |
| proposer task-science prompt content (persona, TIDMAD nouns, `DATASET_CONFIG` constraints block, wavenet/5.57 examples) | **Step 10/12 — unassigned** (roadmap §15.1b) | non-goal; byte-preserved; ONE exception: D2 re-renders the `'denoising_score'` literal inside the grammar example it owns |
| Health declaration semantics | **P4 (merged)** | none |
| three-task full-chain closure | **P6** | none |
| composition root / task package | **Step 12** | none |

**Not a producer-schema copy** (operator §6, rev 1, re-affirmed): the typed
value is a CONSUMER-VIEW projection — the measured 30-field live-read union,
nothing more. Twelve upstream fields are deliberately NOT carried (§2.2),
and the two dead reads are dropped; that asymmetry is the proof it is a
boundary, not a mirror.

**Non-goals**: everything in the ownership table not owned by P3; the
`accumulated` stage-state mechanism (`clamp_and_backstop_accumulated`
composition, `_render_stage_user_prompt`, `_audit_proposer_components` —
their INPUT construction migrates, their shape and logic do not); the
proposal OUTPUT schema (except the `threshold_for_refutation` description
prose); v2 evaluation semantics and pools; the reflector; adding a
side-consistency VALIDATOR for `threshold_for_refutation` (considered and
REJECTED: the field is dead downstream, and a context-dependent validator
would add causal-correction retries for zero consumer value — the grammar +
Gate 1 own the property).

---

## 4. Design (all PROVISIONALs resolved)

### 4.1 The typed value — `ProposerInterpretationEvidence`

New module `agent/schemas/proposer_evidence.py`. A frozen Pydantic model;
field names are the upstream D1-frozen names VERBATIM (renaming would create
a mapping layer and un-grep the lineage).

**The field-shape rule that owns byte parity**: every whitelist-participating
field is `| None` with **None meaning "key absent from the dump"**, never
coalesced to an empty container — the whitelist's `is not None` filter
(`:1698`) renders a present-but-empty `{}` and omits an absent key, and the
CLI path feeds legacy artifacts where the difference is real.

| field | type | source (InterpretationOutput) | req? | absence semantics | class | proposer may reason from it? | may order by it? |
|---|---|---|---|---|---|---|---|
| `metric_identity` | `MetricIdentityKey \| None` | `metric_identity` via `metric_identity_from_mapping` (the ONE validator — malformed/unknown-direction ⇒ None, the same NAMED absence the helper implements today) | opt | None = Q-10-2 named absence; no direction language renders; order-free fallbacks engage | evidence (provenance) | yes | it IS the order source (via `MetricOrder`) |
| `model_types` | `list[str]` | `model_types` | req (default `[]`) | empty = cold start | evidence | yes | no |
| `model_descriptions` | `dict[str, str]` | same name | opt-empty | `{}` | evidence | yes | no |
| `total_experiments` | `int \| None` | same | opt | None = absent | evidence | yes | no |
| `per_model_best` / `per_model_best_valid` / `per_model_worst` | `dict[str, float \| None] \| None` | same names | opt | None = key absent (whitelist omission) | evidence | yes | ONLY through `MetricOrder` from `metric_identity` |
| `per_model_raw_best_health_validity` | `dict[str, str] \| None` | same | opt | None/`{}` | evidence | yes | no |
| `per_model_score_tables` | `dict[str, ScoreComparisonTable] \| None` | same (typed upstream) | opt | None — absorbs the dead ProposalInput mirror as the ONE carrier | evidence | yes | no |
| `per_model_params` | `dict[str, int] \| None` | same | opt | None | evidence | yes | no |
| `per_model_training_segments` | `dict[str, int] \| None` | same | opt | None | evidence | yes | no |
| `model_knowledge_cache` | `dict[str, dict[str, Any]] \| None` | same — the producer itself types it loosely; the projection does NOT invent a schema the producer doesn't declare | opt | None/`{}` | evidence | yes | no |
| `best_denoising_score` / `best_valid_denoising_score` / `worst_denoising_score` | `float \| None` | same (D1-frozen names) | opt | None | evidence | yes | only via order |
| `best_config` | `dict[str, Any] \| None` | same | opt | None | evidence | yes | no |
| `key_findings` / `bottlenecks` | `list[str] \| None` | same | opt | None = absent key; `[]` = present-empty | evidence | yes | no |
| `take_home_message` | `str \| None` | same | opt | None/"" | evidence | yes | no |
| `scientific_accuracy` | `dict[str, float] \| None` | same | opt | None | evidence | yes | no |
| `cumulative_information_gain` | `float \| None` | same | opt | None | evidence | yes | no |
| `prediction_outcomes_history` | `dict[str, int] \| None` | same (frozen v1 pool) | opt | None | evidence | yes | no |
| `prediction_outcomes_by_semantics` | `dict[str, dict[str, int]] \| None` | same | opt | None | evidence | yes | no |
| `cumulative_information_gain_by_semantics` | `dict[str, float] \| None` | same | opt | None | evidence | yes | no |
| `prediction_pool_sizes` | `dict[str, int] \| None` | same | opt | None | evidence | yes | no |
| `prediction_evaluation_semantics` | `str \| None` | same | opt | None | evidence | yes | no |
| `vocab_diversity_ratio` | `float \| None` | same | opt | None disables the stagnation signal (today's behavior) | evidence | yes | no |
| `per_model_round_health_counts` | `dict[str, dict[str, int]] \| None` | same | opt | None/`{}` ⇒ block renders nothing | evidence | yes | no |
| `per_model_collapse_fingerprints` | `dict[str, list[CollapseFingerprint]] \| None` | same (typed upstream, `agent/schemas/health_feedback.py`) | opt | None/`{}` | evidence | yes | no |
| `collapse_fingerprint_history` | `dict[str, list[CollapseFingerprintHistoryEntry]] \| None` | same | opt | None/`{}`; a malformed entry now fails the PROJECTION (typed validation) instead of the renderer — declared delta, fail-closed earlier | evidence | yes | no |

**Explicitly NOT fields** (each with the reason, so the review can check the
boundary): `per_model_failure_counts` (no demonstrated proposer consumer);
`per_model_secondary_metrics` (**Q-P3-3 = NO_RAW_SECONDARY_CONSUMPTION,
FROZEN** — a RESERVED name documented in the model's docstring, the 09a
reserved-names precedent P2b itself consumed; a future exposure decision
requires its own explicit semantic ruling and must NOT be introduced
incidentally by P5 or any other child); `is_degraded`, `evolution_stats`,
`vocab_link_confirmations` (P5's), `runtime_vocab` / `cold_start` (already
typed `ProposalInput` channels via the protocol), `scientific_aggregation`,
`best_valid_config`, `prediction_evaluation`, `new_discoveries`,
`vocab_changes` (no consumer), and the two dead-read names
(`per_file_comparison`, `efficiency_comparison` — the schema never declared
them; carrying them would fabricate a contract).

**Diagnostic-vs-scientific separation**: every carried field is scientific
evidence or run provenance; no crash strings, no infrastructure diagnostics
enter the value (the health fingerprints are deterministic gate evidence,
already LLM-rendered today; secondary crash carriers are excluded with
Q-P3-3 itself).

### 4.2 The projection authority — placement, signature, failure policy

```text
agent/schemas/vocab.py                       (NEW, ~60 LOC moved)
    VocabEntry                               relocated VERBATIM from proposal.py;
                                             proposal.py re-exports it so all 7
                                             existing production import sites are
                                             untouched; interpretation.py:32 now
                                             imports the new home — the ONE
                                             import-line change, breaking §2.7.3's
                                             backwards edge

agent/schemas/proposer_evidence.py           (NEW, ONE owner)
    ProposerInterpretationEvidence           the frozen typed value (§4.1)
    build_proposer_evidence(
        interpretation: Mapping[str, Any],   ← the DUMP shape — the one shape both
    ) -> ProposerInterpretationEvidence        entrypoints already possess
```

* **Input is the mapping, not the model.** The protocol passes
  `output.model_dump()`; the CLI passes the loaded
  `interpretation_{run_name}.json` (the interpreter persists exactly
  `model_dump_json`, `result_interpretation_agent.py:1035-1037` — same
  shape). One function, one input shape, two callers: that is §11.2's
  executable rule. It also means the module needs interpretation.py ONLY for
  the embedded types, which §4.2's relocation makes cycle-free.
* **Failure policy**: absent keys ⇒ the documented per-field absence
  semantics (today's `.get()` tolerance, preserved deliberately —
  compatibility with every legacy artifact). PRESENT-but-malformed values ⇒
  Pydantic `ValidationError`, fail-closed — a declared upgrade over today,
  where a malformed value flows silently into prompt text. `metric_identity`
  is the one exception by design: malformed ⇒ `None` (the P2a-frozen NAMED
  absence, `metric_identity_from_mapping`'s own contract — never a crash,
  never a guess).
* **Why the schema layer and not the protocol module**: the protocol remains
  the production MAPPING caller (repo rule: protocols are where field
  mapping happens), but the CLI is a second legitimate caller that must not
  import a protocol to read its own node's persisted input. The function
  lives beside the type; the protocol and CLI both call it. (Considered:
  defining it inside `ml_result_interp_to_ml_model_propose.py` — rejected
  because the CLI import would make a node depend on a protocol module,
  inverting the architecture.)
* The relocation preserves `VocabEntry` byte-for-byte and every existing
  importer through the `proposal.py` re-export; C1's inventory test pins
  the complete importer set (single- and multi-line import forms both).

`ProposalInput` change (C1 adds, C3 removes):

```text
ProposalInput.interpretation_evidence: ProposerInterpretationEvidence   (REQUIRED)
ProposalInput.interpretation: dict[str, Any]                            (REMOVED in C3)
ProposalInput.per_model_score_tables                                    (REMOVED in C3 — §2.7.2)
```

Workflow-owned context (`existing_model_types`, `previous_failures`,
budgets, hardware, vocab_seed, agent_cards, …) stays as ProposalInput
fields — the typed evidence is interpretation-derived ONLY.

### 4.3 The pipeline serializer — bytes through the type

`accumulated` keeps its exact shape (plain JSON-able dicts — it is
`json.dumps`-ed with `default=str` at `:936` and clamped/audited by helpers
that must not change). ONE new renderer (private node module, §6) produces:

* `interpretation_summary`: the SAME 18 keys, in the SAME tuple order, with
  the SAME `is not None` filter, each value serialized to the dict shape the
  dump had (`ScoreComparisonTable.model_dump()` etc.) — byte-equal JSON
  region vs the C0 goldens;
* `candidates` / `non_candidates_overview`: `select_candidate_models` and
  the overview loop read typed fields but emit the SAME dict-shaped
  summaries (`score_table` re-serialized via `model_dump()`), because
  `build_candidate_markdown_block` dispatches on `isinstance(table, dict)`
  (`proposal_helpers.py:340`) and a typed object would silently render
  "_Score table unavailable._" — a named parity hazard with its own C2 test;
* `_audit_proposer_components` unchanged (WF-3 stays green).

### 4.4 The legacy adapter — bytes through the type

`_build_reasoning_prompt` becomes a renderer over
`ProposerInterpretationEvidence` (relocated to the private rendering module)
reproducing today's bytes for today's inputs (C0 goldens + the C0
full-coverage fixture). The two DEAD reads are deleted — provably
unreachable (the schema never carried the fields), so byte parity is
unaffected; parent non-goal 7's in-passing rule authorizes exactly this.
Legacy-only LIVE reads (`best_valid_denoising_score`, `best_config`) are
typed fields, so the adapter needs no side channel. The track-record call
keeps passing the five typed fields to the unchanged 09b authority.

### 4.5 Direction-safe authoring — the enumerated LLM-facing deltas

Three delta surfaces, and ONLY these; everything else is parity-owned:

* **D1 — the metric-context statement.** A new rendered block, injected via
  the existing `template_vars` mechanism into the COMPARISON and CAUSAL base
  templates (a `{metric_context_block}` placeholder; the proposing stage
  does not rank or author and gets none). Content when identity present: a
  short block built on `render_metric_identity` — the 09b line authority
  producing ``golden metric `<id>` (<higher|lower> is better)`` from
  `MetricOrder.direction_words` (`rendering.py:240-263`; the proposer
  already imports this module for the track record, so the import edge
  exists). It states: the identity line; that SOTA/“better” judgements and
  the prediction must be read on this direction. When `metric_identity is
  None`: the canonical `METRIC_IDENTITY_UNAVAILABLE` phrase with the
  explicit instruction to use NO direction language and make NO ranking
  claims (Q-10-2's named absence, rendered rather than defaulted).
* **D2 — the authoring example, rendered per-direction.** The causal
  template's example JSON sub-block (`:102-126`'s `falsifiable_prediction`
  lines) becomes a rendered fragment: the `metric` example names the RUN's
  `metric_id` (the `'denoising_score'` literal leaves the framework
  template; the per-sample-slice DSL mention stays as a generic capability
  note); the `current_value → predicted_value` pair moves TOWARD BETTER
  under the declared direction (upward under `higher`, downward under
  `lower`); `threshold_for_refutation` sits on the REFUTED side of
  `current_value`; one sentence aligns the wording with the unchanged v2
  evaluator ("confirmed when the actual result is better than the SOTA
  under this direction"). When identity is absent: the numeric example is
  OMITTED and a direction-neutral instruction renders in its place — never
  a defaulted upward example.
* **D3 — comparison-stage SOTA wording.** A static, one-time neutral
  rewrite of the `sota_*` guidance so SOTA is defined as "best under the
  stated metric direction" (referencing D1's block) rather than implied by
  higher-typical examples. The TIDMAD-flavored example VALUES (`5.57`,
  wavenet) are task-science prose and stay — named Step-10/12 debt, not
  P3's.

Doc-only companion (not LLM-facing, §2.5): the
`threshold_for_refutation` description rewrite in `proposal.py:57-61`
("on the refuted side of `current_value` for this run's metric direction").

**These are INTENTIONAL LLM-facing deltas** — enumerated, byte-diffed in the
ledger, with everything outside them at exact parity (PB-3/PB-4/S1-E +
C0 full-coverage goldens). Legacy prompts carry NONE of them (§11.2's
compatibility value; and legacy authors no predictions, §2.5).

### 4.6 Secondary evidence — Q-P3-3 = NO_RAW_SECONDARY_CONSUMPTION (FROZEN)

**Operator ruling (2026-08-20): P3 does NOT consume raw secondary metric
evidence.** The frozen live contract:

* `ProposerInterpretationEvidence` carries NO `per_model_secondary_metrics`
  field; the name is documented in the model's docstring as RESERVED only.
* Proposer prompts contain no raw `macro_f1` / `psnr` / `mae` values, no
  secondary refusal entries, and no secondary runtime diagnostics;
  `secondary_metric_errors` / crash strings are NEVER proposer evidence.
* A future decision to expose raw secondary observations to the proposer
  requires an explicit semantic owner/ruling of its own — it must not be
  introduced incidentally by P5 or another child.

Grounds (measured, accepted by the ruling):

* P2b's operator-approved planner rationale (§2.4) names the exact hazard —
  a second, differently-directed number beside the optimised one invites a
  trade-off, "exactly the vote secondaries must never get" — and the
  comparison stage (which picks the SOTA to build on) is the
  optimization-adjacent surface where that temptation would land. P2b's
  observational-only boundary stays explicit.
* The interpreter ALREADY synthesizes scientifically relevant secondary
  observations into `key_findings` / `take_home_message` (it renders all
  three secondary states since 09b/P2b), and those channels ARE projected —
  the proposer legitimately consumes secondary-informed science without raw
  differently-directed numbers.
* Every typed field requires a demonstrated consumer; there is none.

**Required negative test (frozen)**: a DAVIS fixture whose upstream dump
contains REAL `psnr` + `mae` secondary evidence, asserting that
`ProposerInterpretationEvidence` contains none of it AND the proposer
prompt bytes contain none of it. The ordering-operand invariant remains
scope-extended over the proposer files regardless (§7 C0).

*Historical note (rejected alternative, recorded per the freeze-cleanup
rule)*: rev 2 pre-declared a CONSUME shape (field default `{}`, rendering
ONLY via 09b's `render_secondary_metrics` with each metric's own direction,
crash carriers excluded) so a CONSUME ruling would have been cheap. The
ruling was NO; that shape is NOT part of P3's contract and survives only in
this note as the record of what was considered.

### 4.7 F-P3-1 — the clamp migration (Q-P3-4 = INCLUDE / BOUNDED, FROZEN)

**Operator ruling (2026-08-20): included in P3 as a BOUNDED correctness
closure, not scope creep.** Mandatory in C2:
`clamp_and_backstop_accumulated` and `clamp_comparative_analysis` gain a
keyword-only `order: MetricOrder | None` supplied by `_run_pipeline` from
the SAME typed metric identity the proposer already uses (no new ordering
authority, no new metric derivation). Draw A becomes "the 3 BEST by
`order`"; `_score`'s missing-value sentinel becomes `order.worst_sentinel`;
the final-truncation sort keys follow the same order. `order is None`
(absent identity) ⇒ the score-based draw is SKIPPED and retention falls to
the existing direction-independent recency behavior, with no "best" claim —
the Q-P2a-1 shape: no metric ranking happens without identity. Ties and the
recency draw are direction-independent and preserved byte-for-byte.

Required deterministic fixtures (frozen): DAVIS lower — lowest mse
retained, the known worst model clamped out; TIDMAD/Pets higher — highest
retained; absent identity — no metric ordering, recency-only. The P2a
scanner's transitive-taint behavior is deliberately NOT widened to catch
this site (its precision contract stands); the helper-indirection blind
spot is recorded in that census's docstring when touched, and the
hand-computed behavioral fixtures own the migrated site's direction
semantics (§2.7.1).

*Historical note (rejected alternative)*: rev 2 carried an else-branch —
record the site as named Step-10 direction debt at the post-merge sync —
kept here only as the record of the alternative the ruling rejected.

### 4.8 Convergence (the §11.2 executable rule, restated as code paths)

```text
production:  InterpretationOutput ──model_dump()──► local_full_context
                                                        │ build_proposer_evidence(dump)
standalone:  interpretation_{run}.json ──json.load──► main()
                                                        │ build_proposer_evidence(loaded)
                                                        ▼
                                         ProposalInput.interpretation_evidence
                                                        │
                     ┌──────────────────────────────────┼───────────────────────────┐
                     ▼                                  ▼                           ▼
              _run_pipeline                        _run_legacy                  helpers
        (serializer + stage loop)             (adapter renderer)         (typed signatures)
```

After C3 there is nothing else to read: the dict field no longer exists, so
a bypass has no input — plus the standing census (§8.1).

---

## 5. Three-task control

| concern | TIDMAD | Pets | DAVIS | same framework path? |
|---|---|---|---|---|
| identity in evidence | `tidmad_denoising_score` / higher (negative values) | `accuracy` / higher | `mse` / **lower** | YES — a value, not a branch |
| D1 statement renders | "higher is better" | "higher is better" | **"lower is better"** | YES — one renderer |
| D2 example renders | upward, threshold below current | upward | **downward, threshold ABOVE current** | YES |
| clamp retention (F-P3-1, migrated) | best-3 = highest | highest | **best-3 = LOWEST mse; the worst model's entry is clamped OUT — hand-computed** | YES |
| `top_n` cut (P2a, pinned) | unchanged bytes | unchanged | unchanged (already direction-aware) | YES |
| secondaries upstream (P2b) | none | `macro_f1` | `psnr` (higher) + `mae` (lower) | evidence + prompt bytes contain ZERO of them (Q-P3-3 ruling) — the required NEGATIVE assertion, asserted on the DAVIS fixture where the temptation is real |
| absent identity (legacy artifact) | named absence: D1 renders the canonical phrase, NO direction words, no numeric example; `top_n` → order-free `all`; clamp → recency-only | same | same | YES |

The DAVIS column is the falsification case: a sign mistake in D1/D2/clamp
turns at least one hand-computed fixture RED. A fourth task composes via P1
and inherits the projection with zero framework edits.

---

## 6. Structure preflight (parent §19.3 — measured, not estimated)

| file | measured now | P3 change | owners after |
|---|---|---|---|
| `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` | 2,383 LOC; `_run_pipeline` **666 LOC / 83 branch-ish nodes**; `_build_reasoning_prompt` 224 LOC; `_format_healthgate_evidence_block` 108 LOC | **shrinks**: the legacy renderer, health block and the new serializer/grammar renderers move to ONE private rendering module; `_run_pipeline` keeps sequencing and consumes rendered parts. NO new inline reader | node orchestration only |
| `nodes/ml_model_proposal_agent/evidence_rendering.py` (NEW, private — exact name fixed at implementation) | — | ~450-550 LOC arriving BY EXTRACTION (whitelist serializer · legacy adapter · health block · D1/D2 grammar renderers), each a small pure function over the typed value | ONE (proposer prompt-evidence rendering) |
| `agent/schemas/proposer_evidence.py` (NEW) | — | typed value + projection, est. 250-350 LOC | ONE |
| `agent/schemas/vocab.py` (NEW) | — | `VocabEntry` relocated verbatim (~60 LOC) | ONE |
| `agent/schemas/proposal.py` | 1,307 | field swap on `ProposalInput`; mirror removal; `VocabEntry` re-export; description rewrite | unchanged set |
| `agent/schemas/interpretation.py` | 1,286 | ONE import line (`:32` → vocab.py) | unchanged |
| `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` | 295 | maps through the projection; drops the mirror population | unchanged |
| `nodes/proposal_helpers.py` | **777** (rev 1's "~120" was wrong — corrected §13) | typed signatures; `_interpretation_order` deleted; clamp order-param (Q-P3-4); net ≈ flat | unchanged set |
| stage templates | 9 files | 2 base templates gain `{metric_context_block}`; causal base's example sub-block becomes rendered; comparison D3 rewrite | unchanged |

The private-module extraction runs UNDER the node public-boundary rule
(`tests/unit/nodes/test_node_public_boundary.py` — the 07b-C7 precedent, as
the interpreter's `evidence.py`/`ordering.py`/`prediction.py` already
demonstrate in `nodes/result_interpretation_agent/`). Decomposition is by
ownership (prompt-evidence rendering vs orchestration), not arithmetic; the
extraction lands in the SAME commit as the migration that needs it (C2/C3),
never as a separate cleanup.

---

## 7. Commit decomposition — SIX commits, full plans

**Per-commit rules**: semantic commits are autonomous — inspect the diff
scope, run the cheapest authoritative targeted validation, update this
ledger, commit, continue. All checklists start `[ ]` and are checked only
with recorded evidence. No full local suite before the final head; ONE
exact-head CI at the end (validation-economy rule).

### C0 — baselines, censuses, guard dispositions

**1. Goal.** Freeze the CURRENT observable behavior so every later claim is
a diff against recorded evidence, and make the invariants that must survive
P3 executable BEFORE anything moves.

**2. Scope.** Tests + goldens + ledger only; zero production edits.
Depends on: nothing.

**3. Implementation plan.**
- [ ] Full-coverage interpretation fixture: a dump carrying ALL 18 whitelist
      keys populated, the legacy-only live fields, the health-evidence
      fields, `metric_identity`, AND `per_model_secondary_metrics` entries
      (so the negative assertion has teeth), plus a legacy variant with
      absent keys. Capture pipeline (both modes) + legacy prompt bytes at
      the LLM boundary (the PB-3/PB-4 recorder pattern) as NEW goldens
      beside the kept existing ones.
- [ ] Raw-reader census, executable: pins the exact current inventory —
      **40** node-module reads + **12** helper reads (the §2.2 tables as
      data) — so C2/C3 flip it to a shrinking, then zero, count rather than
      to an unverifiable prose claim.
- [ ] Ordering-operand invariant scope extension: add
      `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py`,
      `nodes/proposal_helpers.py`, `agent/schemas/proposal.py` and the
      proposer protocol to `SCANNED_FILES` (the invariant asserts every
      scanned file EXISTS, so `agent/schemas/proposer_evidence.py` and the
      private rendering module join the list in the commits that create
      them — C1/C2); plant a synthetic secondary-keyed sort in a
      newly-scanned file and record it RED, then remove.
- [ ] Guard-disposition table (§2.8) recorded in the ledger with each
      guard's flipping commit.
- [ ] Scanner blind-spot note (F-P3-1): one docstring paragraph in the P2a
      scanner recording the helper-indirection limitation and pointing at
      the behavioral fixture as the owner (per the F-P2b-4 per-census rule).

**4. Validation plan.** New goldens byte-stable across two runs; the plant
turns the extended invariant RED and its removal restores green; census
equals the hand-counted inventory.

**5. Acceptance criteria.** Goldens committed; census pins 40+12; invariant
extension live-proven; zero production diffs (`git diff --stat` shows
tests/docs only).

**6. Failure/edge cases.** A golden that embeds an absolute path or
process-varying ordering (frozenset iteration) is a broken baseline — the
existing `sorted()` loss-list contract (`:1320-1350`) is the precedent to
follow.

**7. Verification commands.** Targeted:
`pytest tests/unit/agent/ml_model_proposal_agent tests/unit/nodes/test_step10_p2a_c4_proposer_top_n.py tests/unit/agent/result_interpretation_agent/test_step09a_c6_evidence_projection.py -q`
(record counts + wall time in the ledger).

**8. Commit boundary.** Tests/goldens/docs only; independently reviewable;
no production change.

### C1 — VocabEntry relocation + the typed value + projection + protocol

**1. Goal.** The contract exists and production populates it — while BOTH
old readers still work off the dict (the ONE intermediate state, closed in
C2/C3 inside the same PR).

**2. Scope.** `agent/schemas/vocab.py` (new), `agent/schemas/proposal.py`
(re-export + new REQUIRED field `interpretation_evidence`),
`agent/schemas/interpretation.py` (one import line),
`agent/schemas/proposer_evidence.py` (new), the proposer protocol (calls the
projection; keeps populating the dict field FOR NOW). Depends on C0.

**3. Implementation plan.**
- [ ] Relocate `VocabEntry` verbatim; re-export from `proposal.py`;
      re-point `interpretation.py:32`; import-cycle probe (a test importing
      `proposal` → `proposer_evidence` → `interpretation` in one process).
- [ ] `ProposerInterpretationEvidence` per §4.1 (frozen; the None-vs-empty
      rule enforced by field types) + `build_proposer_evidence` per §4.2.
- [ ] `metric_identity` populated ONLY via `metric_identity_from_mapping`.
- [ ] Protocol: `result["interpretation_evidence"] =
      build_proposer_evidence(dump)` beside the existing dict population.
- [ ] CLI (`main()`): builds the evidence via the SAME call beside its dict
      (full convergence lands in C3; this keeps C1 reviewable).
- [ ] Retire `test_no_typed_evidence_reader_was_introduced` (its purpose
      arrives), citing this commit in the ledger.

**4. Validation plan.** Projection unit tests: round-trip from the C0
full-coverage fixture (every §4.1 field lands, every non-field is absent);
legacy-absence fixture (None-vs-empty preserved); malformed-value
fail-closed (`per_model_best="x"` raises); malformed `metric_identity` ⇒
None (never a raise, never a default direction); dump-of-current-output
equivalence (protocol path == CLI path on the same bytes — the convergence
property, tested from C1 on).

**5. Acceptance criteria.** Both entrypoints produce EQUAL evidence values
from the same artifact; prompt bytes unchanged (goldens green — nothing
reads the new field yet); pyright clean over the new modules.

**6. Failure/edge cases.** Import cycle (probed); a field defaulting where
the dump had no key (the None rule test); `VocabEntry` importers breaking
(the re-export keeps all seven sites — grep-pinned in the test).

**7. Verification commands.**
`pytest tests/unit/agent/ml_model_proposal_agent tests/unit/agent/protocols -q`
+ `pyright agent/schemas/proposer_evidence.py agent/schemas/vocab.py`.

**8. Commit boundary.** Schema layer + protocol only; no reader migrated;
no prompt byte moves.

### C2 — pipeline reader onto the typed value (+ helpers, + health block, + the F-P3-1 clamp migration)

**1. Goal.** The production path consumes the typed value; the whitelist
finally gets its pin; the P2a threading is replaced by the mechanism its
docstring requested; the F-P3-1 direction site is migrated onto the
existing order authority.

**2. Scope.** `_run_pipeline`'s evidence assembly; the new private rendering
module (serializer + health block move); `proposal_helpers.py`
(`select_candidate_models`, `resolve_exploration_mode` typed;
`_interpretation_order` DELETED; `_guess_source` drops its unused parameter
in passing; the §4.7 clamp migration — MANDATORY, Q-P3-4 = INCLUDE);
`run()`'s print. Depends on C1.

**3. Implementation plan.**
- [ ] Whitelist serializer in the private module: 18 keys, tuple order,
      `is not None`, dict-shaped values (§4.3) — byte parity vs C0 goldens.
- [ ] Direct reads `:1620-1626` → typed fields; candidate summaries keep
      dict-shaped `score_table` (the §4.3 hazard test).
- [ ] `select_candidate_models(evidence, strategy)` /
      `resolve_exploration_mode(evidence, pipeline)`; `top_n` reads
      `evidence.metric_identity` → `MetricOrder` (comparison line
      UNTOUCHED); `_interpretation_order` deleted; the C4 signature pin
      retired with the successor test landed.
- [ ] `_format_healthgate_evidence_block` over typed fields, relocated;
      malformed-history failure moves to projection (C1's validation);
      rendering parity vs C0 health goldens.
- [ ] The F-P3-1 clamp migration per §4.7 (Q-P3-4 = INCLUDE, frozen): the
      keyword-only order parameter, the recency-only absence path, and the
      three hand-computed retention fixtures.
- [ ] Raw-reader census count drops to the legacy-reader remainder;
      recorded.

**4. Validation plan.** Byte parity: pipeline goldens (both modes, full
fixture + legacy fixture); WF-3 unchanged; P2a C4 behavioral fixtures stay
green unmodified; clamp fixtures (DAVIS lower / TIDMAD higher /
absent-identity recency-only); health parity + the projection-time
malformed test (UPGRADE disposition recorded).

**5. Acceptance criteria.** Pipeline prompt bytes IDENTICAL to C0 goldens on
every unchanged surface; census shows zero pipeline-side raw reads; the
DAVIS clamp fixture proves the worst model's entry is clamped OUT and the
absence fixture proves recency-only retention with no metric ordering;
`_run_pipeline` LOC/branch count did not grow (measured, in the ledger).

**6. Failure/edge cases.** Typed-object leakage into `accumulated`
(`json.dumps(default=str)` would silently change bytes — the parity goldens
are the tripwire, plus an explicit shape assertion); empty-vs-absent
whitelist keys (legacy fixture); over-capacity clamp only (n ≤ top_k path
byte-identical).

**7. Verification commands.**
`pytest tests/unit/agent/ml_model_proposal_agent tests/unit/nodes -q -k "proposal or proposer or top_n"`.

**8. Commit boundary.** Pipeline + helpers only; legacy reader untouched;
no template edits.

### C3 — legacy adapter + CLI convergence + dict-field removal

**1. Goal.** One reader remains. The §11.2 acceptance becomes true by
construction: the dict has no field to read.

**2. Scope.** `_build_reasoning_prompt` → adapter in the private module;
`main()` drops its raw dict; `ProposalInput.interpretation` REMOVED;
`ProposalInput.per_model_score_tables` REMOVED; protocol stops populating
both; test-fixture migration (test-disposition audit per the standing rule —
every fixture constructing `ProposalInput(interpretation=...)` is
KEEP/UPGRADE/REWRITE'd by intent, never mass-edited). Depends on C2.

**3. Implementation plan.**
- [ ] Adapter renders from the typed value; PB-4/S1-E + C0 legacy goldens
      byte-equal; DEAD reads deleted (non-goal-7 authorization cited).
- [ ] CLI: `build_proposer_evidence(json.load(...))` only; the
      protocol/CLI equality test from C1 now runs the FULL node path in
      pseudo mode on both entries.
- [ ] Remove the two `ProposalInput` fields + the mirror population; sweep
      `scripts/` for `.interpretation` readers (measured zero this session;
      re-verified at head).
- [ ] Raw-reader census flips to ZERO and becomes a standing guard (any
      `interpretation.get(`/`interpretation[` in the proposer's modules is
      RED); plant-and-catch recorded.

**4. Validation plan.** Legacy byte parity; census zero + plant; schema
tests (REQUIRED field enforced — constructing ProposalInput without
evidence fails); full proposer test directory green after fixture
disposition.

**5. Acceptance criteria.** `grep -c` raw reads = 0 in node+helpers; both
entrypoints' prompts byte-identical to their goldens; no production module
references `ProposalInput.interpretation`.

**6. Failure/edge cases.** A stale persisted artifact missing new-ish keys
(the legacy fixture path proves tolerance); a test fixture silently relying
on the removed mirror (the disposition audit names each).

**7. Verification commands.**
`pytest tests/unit/agent/ml_model_proposal_agent tests/unit/agent/protocols tests/unit/nodes -q`.

**8. Commit boundary.** Reader unification only; zero prompt-semantic
changes (C4 owns those).

### C4 — direction-safe authoring (the declared LLM-facing delta)

**1. Goal.** The proposer is TOLD the direction and shown a
direction-correct example; the roadmap's "proposer prediction-authoring
grammar" item closes.

**2. Scope.** D1 + D2 + D3 per §4.5; the `threshold_for_refutation`
description rewrite; the delta-byte enumeration in the ledger. Depends on
C2 (the evidence reaches `_run_pipeline`), C3 (so the delta diff is clean).

**3. Implementation plan.**
- [ ] `{metric_context_block}` placeholder in comparison + causal base
      templates; renderer over `render_metric_identity` +
      `METRIC_IDENTITY_UNAVAILABLE`; template_vars wiring.
- [ ] The causal example sub-block rendered per §4.5 D2 (present-higher /
      present-lower / absent states).
- [ ] D3 static rewrite of the comparison sota guidance.
- [ ] Schema-description rewrite (doc-only, non-LLM-facing — recorded as
      such).
- [ ] Enumerate the exact byte-diff surfaces in the ledger: for each stage ×
      mode, the diff between C3-head and C4-head prompt bytes must touch
      ONLY the declared blocks.

**4. Validation plan.** Three-task rendering fixtures with HAND-WRITTEN
expected text (TIDMAD negative-higher upward · Pets higher · DAVIS lower
downward with threshold ABOVE current · absence with zero direction words —
asserted by a direction-word scan of the rendered block); the
delta-enumeration test (unchanged surfaces byte-equal, changed surfaces
match the new goldens); legacy prompts byte-identical (no delta reaches
them).

**5. Acceptance criteria.** The DAVIS fixture fails if any rendered example
moves upward or places the threshold below current; the absence fixture
fails if "higher" or "lower" appears; the diff-surface census lists exactly
D1/D2/D3 bytes and nothing else.

**6. Failure/edge cases.** `str.replace` template_vars collisions (the
placeholder name must not occur in prose — probed); mindset-override path
(`load_stage_prompt` mindset replaces the MODE block, not the base — D1/D2
live in the base and survive; tested).

**7. Verification commands.**
`pytest tests/unit/agent/ml_model_proposal_agent -q -k "grammar or metric_context or golden"`.

**8. Commit boundary.** Templates + renderers + schema prose only.

### C5 — closure: censuses, Gate 1, docs, ledger, ONE CI

**1. Goal.** The standing guards hold at the final head; the bounded Gate 1
runs per the frozen disposition; the operator surface is current.

**2. Scope.** Census finalization; Gate 1 execution + evidence; node `.md`
(the doc-sync rule: CLI args, the evidence contract, the removed field);
parent §0 + roadmap sync happens at the post-merge status commit, not here.
Depends on C0–C4.

**3. Implementation plan.**
- [ ] Standing censuses green at head: ONE projection authority (a second
      `build_proposer_evidence`-shaped constructor or a raw-dict reader
      plants RED); zero raw reads; ordering-operand invariant over the
      extended scope; the P2a scanner untouched and green.
- [ ] **Gate 1 (operator-approved before launch; Q-P3-2 frozen coverage)**:
      ≤ 3 real calls, covering BOTH affected behavioral responsibilities
      under a DAVIS-shaped LOWER-is-better primary fixture. **Preferred
      shape**: ONE production-shaped proposer run through the normal real
      stage path — comparison → causal → proposing is exactly 3 calls when
      no retry fires — with every stage output persisted. **Fallback** (if
      the harness can only exercise stages independently): call 1 =
      comparison/DAVIS-lower; call 2 = causal/DAVIS-lower; call 3 =
      optional higher-regime control if useful.
      **Acceptance A (comparison/SOTA)**: given unambiguous candidate
      scores, the persisted stage output identifies the LOWER score as the
      SOTA/better candidate under the stated direction
      (`sota_model_type`/`sota_score`).
      **Acceptance B (causal/authoring)**: schema-valid
      `FalsifiablePrediction`; `predicted_value` moves toward BETTER =
      LOWER; `threshold_for_refutation` lies on the REFUTED side; no
      upward/higher-is-better inversion.
      NO real call is spent on absent metric identity — that state is
      deterministic (canonical unavailable statement, zero direction
      language, zero numeric example, no ranking) and unit/golden tests own
      it. The verdict is read from the actual produced/persisted stage
      artifacts, never from inspecting the prompt alone.
- [ ] Node `.md` sync quoting each documented flag/default against merged
      source; ledger closed (all checklists evidenced).
- [ ] Push ONCE; the formal PR's automatic CI on the final head is the ONE
      canonical run; verdict from the log.

**4-5. Validation / acceptance.** All prior commits' targeted suites green
at head (recorded per commit, not re-run wholesale); Gate 1 PASS recorded
with call count and artifact paths; CI run id + SHA in the ledger.

**6. Failure/edge cases.** A model that follows the prompt incorrectly
under lower-is-better — on EITHER surface (SOTA choice or authoring) — is a
REAL Gate failure, never a test flake, and is never passed by blind rerun.
The disposition is a grammar/code correction, which produces a NEW candidate
that may then receive its own bounded Gate; every attempt is recorded.

**7-8.** Standard: diff summary + staged list + deviations before the
commit; STOP at READY FOR OPERATOR REVIEW — DO NOT MERGE.

---

## 8. Validation strategy / Gate rulings

### 8.1 Deterministic owners (the cheapest authoritative owner per claim)

| claim | owner |
|---|---|
| projection completeness/absence/malformed semantics | C1 unit tests over the full-coverage + legacy fixtures |
| both entrypoints read one authority | the C1/C3 equality test + the raw-reader census at zero + plant |
| unchanged prompt bytes | PB-3/PB-4/S1-E + C0 goldens (both entrypoints, both modes) |
| the intentional delta is exactly D1/D2/D3 | the C4 diff-surface enumeration test |
| direction correctness of rendered grammar | three-task hand-written fixtures; DAVIS is the falsifier |
| no re-derivation, no second order authority | zero `MetricOrder(`-construction outside the evidence path except P2a's own sites; direction words only via `render_metric_identity`/`direction_words`; census |
| secondaries un-consumed / un-ordered | the negative assertion fixture + the C0-extended ordering-operand invariant |
| `top_n` unchanged | P2a's C4 fixtures, unmodified |
| clamp direction (Q-P3-4) | hand-computed retention fixtures |
| structural boundary | node public-boundary test + preflight LOC/branch measurements in the ledger |

### 8.2 Gate 1 — REQUIRED (Q-P3-2 = GATE_1_REQUIRED, FROZEN 2026-08-20)

The standard's assignment rows
(`docs/gates/gate_testing_standard.md` "Gate assignment by commit type"):
*"Prompt placeholder substitution → Unit only + optional Gate 1"* and *"New
LLM-facing system prompt → Gate 1"*. C4 is between the rows: not a new
system prompt, but more than mechanical substitution — D1/D2/D3
intentionally change real LLM-facing INSTRUCTIONAL semantics, and the
failure class is LLM-behavioral: deterministic fixtures prove the prompt is
correct, not that a real model obeys lower-is-better instructions. No prior
proposer Gate has ever run a `lower` regime; the parent pre-named P3 "the
child most likely to require Gate 1" (§22, §22.1), and 09b's five-call Gate
on the interpreter's direction-correct reading is the precedent on the
consuming side.

**Frozen coverage (operator correction C-P3-1): the Gate must exercise BOTH
affected behavioral responsibilities, because D3 is a COMPARISON-stage
change and D1/D2 are causal-stage changes** —

* **A. comparison/SOTA interpretation** under a DAVIS-shaped
  lower-is-better primary: given unambiguous candidate scores, the real
  model identifies the LOWER score as the SOTA/better candidate under the
  stated direction;
* **B. causal/prediction authoring** under the same fixture: schema-valid
  `FalsifiablePrediction`, `predicted_value` toward BETTER = LOWER,
  threshold on the REFUTED side, no upward inversion.

Budget **≤ 3 real calls**; preferred execution is ONE production-shaped
proposer run (comparison → causal → proposing) on the DAVIS/lower fixture,
per-stage fallback allowed (C5's plan). Evidence comes from the persisted
stage artifacts, never from prompt inspection alone. Absent-identity gets
NO real call — it is deterministic and unit/golden-owned. A wrong model
behavior is a REAL failure: no blind rerun; a grammar/code correction is a
new candidate with its own bounded Gate. Everything outside D1/D2/D3 is
parity-owned and gets no Gate. The deterministic D1/D2/D3 diff-surface
tests remain required regardless of the Gate.

### 8.3 Gate 2 — NOT REQUIRED (FROZEN 2026-08-20)

No real-data / GPU / training / scoring semantics change anywhere in P3's
diff: the tuner, sandbox, metric arithmetic and record lifecycle are
untouched; the standard assigns Gate 2 to checkpoint commits of features
with a real execution failure class ("real LLM, real training… functional
validation"). P3's execution-facing behavior is byte-parity-pinned prompt
assembly. (P6 owns the real multi-task loop evidence.)

---

## 9. Cross-child boundary — P3 ↔ P5 (mirrored in the P5 draft §4.4)

* P3 owns: the consumer-facing TYPE and projection, built per invocation
  from the interpretation output/artifact the caller already holds.
* P5 owns: which interpretation-derived values SURVIVE iterations —
  persistence, restore, carry, `accumulated_key_findings`,
  `vocab_link_confirmations`.
* P3 creates NO carrier field, NO digest reader, NO restore path, NO
  `ChainState` change. The workflow's key-findings `ExpertContextItem`
  block (`model_exploration.py:2278-2292`) is P5's consumer surface and P3
  does not move it (it feeds `expert_context`, which is not interpretation
  evidence).
* When P5 needs carried values to reach the proposer, they arrive through
  THIS typed value's declared extension surface (a new field behind the one
  projection) — P5 marks that wiring `PROVISIONAL(P3)` and freezes after P3
  merges precisely so it lands against real code.
* Classification of everything P3 renders: same-iteration available. Nothing
  P3 needs is P5-carried; nothing unavailable was silently substituted.

---

## 10. Preservation invariants

Un-changed-surface prompt bytes EXACT (both entrypoints, both modes, via
goldens); dispatch `:1470-1477` untouched; `accumulated`'s shape, the clamp
composition (`clamp_and_backstop_accumulated` semantics outside Q-P3-4's
draw), `_render_stage_user_prompt`, `_audit_proposer_components` (WF-3)
unchanged; proposal OUTPUT schema untouched except the
`threshold_for_refutation` description PROSE; the v2 evaluator, its pools
and `render_prediction_track_record` untouched; `top_n`'s comparison and
its P2a fixtures untouched; **ordering semantics stated precisely (C-P3-2):
P3 adds ZERO NEW ordering semantics, ZERO NEW ordering authorities and ZERO
metric-direction derivation authorities; it MIGRATES the already-existing
F-P3-1 clamp preference site from raw descending `best_score` logic onto
the existing P2a `MetricOrder` authority — the semantic decision already
existed, P3 fixes its direction handling. The `MetricOrder` implementation,
the reconciliation authority and the P2a scanner's precision contract are
all unchanged, and the scanner stays green over P3's whole diff**; the
frozen D1 record names untouched; no
ordering expression gains a secondary operand (invariant, scope-extended);
the boldness check, retry loops, causal-correction loop, candidate-id mint
and persistence untouched; legacy CLI behavior identical except that its
evidence now arrives typed.

---

## 11. Failure / edge cases (cross-commit view)

| case | behaviour |
|---|---|
| legacy artifact lacking newer keys (CLI path) | projection's per-field absence semantics — same rendered bytes as today (C0 legacy goldens) |
| present-but-malformed evidence value | projection raises with the field named — fail-closed at the boundary instead of garbage prompt text (declared delta) |
| malformed / unknown-direction `metric_identity` | `None` — the P2a named absence; D1 renders the canonical phrase; `top_n` → order-free `all`; clamp → recency-only; NO example numbers |
| cold start | evidence mostly-None/empty; existing cold-start banner unchanged; D1 renders the absence state if no identity |
| dump with secondaries present | projected NOWHERE (Q-P3-3 ruling); prompt bytes free of them — the required negative assertion |
| mindset override active | D1/D2 live in the BASE template and survive the mode-block replacement — tested |
| identity present, all scores None | `top_n`'s existing empty-`scored` path preserved; D1 still states the direction (identity is provenance, not a score) |
| a future field added to `InterpretationOutput` | invisible to the proposer until DECLARED on the typed value — §11.2 rule 4's exact intent; the census makes a bypass RED |

---

## 12. Risk register

| risk | mitigation |
|---|---|
| the typed value drifts toward `InterpretationOutput` v2 | field set = measured live-read union ONLY; twelve non-carried fields named with reasons; review trigger on any field addition without a consumer test |
| byte drift through re-serialization (typed objects into `json.dumps`) | the §4.3 shape rule + goldens on the FULL-coverage fixture, both modes |
| a third reader appears mid-migration | C0 census precedes any migration; C3 removes the input it would read; standing plant |
| the authoring delta leaks beyond D1/D2/D3 | the C4 diff-surface enumeration test |
| the VocabEntry relocation breaks an importer | verbatim move + re-export; the seven sites grep-pinned; import-cycle probe |
| Gate-1 model behaves wrongly under `lower` on EITHER surface (SOTA choice or authoring) | a REAL Gate failure, recorded (C5); never a blind rerun — a grammar/code correction produces a NEW candidate with its own bounded Gate |
| P5 lands a competing consumer path | freeze ordering (P5 after P3) + §9's mirror statement |
| raw secondaries arrive later through a side door (P5 or another child) | §4.6's frozen rule: a future exposure needs its own explicit ruling; the field is absent, the negative fixture and the scope-extended invariant stand guard |

---

## 13. Reconciliation table (DRAFT rev 1 → REVISION 2)

| rev-1 statement | current source truth | disposition |
|---|---|---|
| anchor `d7d94740` | merged `06291e5f` (P2a `e094fa26` + P2b `5a2ecfd1` in tree) | REVISED — every §2 anchor re-measured |
| "40 + 11 reads" | 40 + **12** (P2a C4 added the helpers' `metric_identity` read) | REVISED; census pins the new counts |
| helpers "~120 LOC" (§6) | **777 LOC** (726 at the old anchor — the rev-1 figure was simply wrong) | CORRECTED; preflight re-measured |
| "P2a C4 threads the identity… record exactly how" (PROVISIONAL(P2a)) | landed as `_interpretation_order` with an explicit delete-me note addressed to P3 (`proposal_helpers.py:36-43`) + two pins written to be retired | RESOLVED — C2 executes the note |
| canonical formatter home (PROVISIONAL(P2a)) | `metric_identity_unavailable_notice` / `METRIC_IDENTITY_UNAVAILABLE` in `execute_tools/evaluation_metric.py:730-750`; validator `metric_identity_from_mapping:927` | RESOLVED — imports fixed |
| "P2b may add proposer-visible fields; re-check no proposer reader was touched" (PROVISIONAL(P2b)) | P2b's diff touches ZERO proposer files; it HID secondaries from the planner with a recorded rationale | RESOLVED; the rationale now grounds Q-P3-3 |
| threshold description "is part of the structured-generation contract" | FALSE — `generate()` attaches no schema; the field also has zero downstream consumers | WITHDRAWN; the rewrite is reclassified doc-only, and the LLM-facing surface re-enumerated (§2.5) |
| Q-P3-1 "does legacy also get the grammar?" | legacy authors NO predictions (no field in its JSON spec, none extracted) | DISSOLVED BY SOURCE — legacy parity is the only coherent state |
| Q-P3-2 Gate proposal | ruled REQUIRED with the standard's row quoted (§8.2) | CARRIED as a freeze confirmation |
| commit decomposition C0–C5 | six commits kept; C1 gains the VocabEntry relocation (new cycle finding); C2 gains the health block + Q-P3-4; C4's surface re-scoped to D1/D2/D3 incl. the previously-missing D1 (no direction statement existed anywhere) and D3 (SOTA delegation) | REVISED |
| "extension points: secondaries projected from `per_model_secondary_metrics` when real" (§4.6 rev 1) | values are real; decision now explicit: NOT consumed (recommended), reserved docstring name | REVISED → Q-P3-3 |
| structure preflight (§6 rev 1) | re-measured: `_run_pipeline` 666 LOC/83 branch nodes; extraction plan made concrete (ONE private rendering module) | REVISED |
| not known to rev 1 | F-P3-1 (clamp direction site, scanner-invisible); the dead typed mirror; the VocabEntry cycle; the ordering-invariant proposer-scope gap; SOTA delegation with no direction statement | NEW — §2.7 |

*This table is the HISTORICAL rev 1 → rev 2 reconciliation record and is
deliberately preserved (freeze-cleanup rule: resolved questions do not erase
their evidence). The rev 2 → rev 3 changes are the operator freeze rulings,
recorded live in §14/§14.1; where a row above says "recommended", the
binding disposition is §14.1's.*

---

## 14. Operator questions — ALL RESOLVED (freeze rulings 2026-08-20)

| id | question | ruling |
|---|---|---|
| **Q-P3-2** | Gate-1 disposition and coverage | **RESOLVED = GATE_1_REQUIRED** — with the coverage CORRECTED at freeze: the run must exercise BOTH comparison/SOTA interpretation AND causal prediction authoring under the DAVIS-shaped lower control (a causal-only Gate would leave D3, a comparison-stage behavioral change, unexercised). Budget ≤ 3 real calls; §8.2 is the frozen contract |
| **Q-P3-3** | Does proposer-facing evidence include P2b's secondary observations at all? | **RESOLVED = NO_RAW_SECONDARY_CONSUMPTION** — no field, no raw values/refusals/diagnostics in prompts; crash strings never proposer evidence; reserved docstring name only; a future exposure requires its own explicit ruling and must not arrive incidentally via P5 or another child; the negative test and invariant scope-extension are REQUIRED (§4.6) |
| **Q-P3-4** | Is F-P3-1 (the clamp's descending retention draw) fixed inside P3, or recorded as named Step-10 direction debt? | **RESOLVED = INCLUDE / BOUNDED** — classified a bounded correctness closure, not scope creep: Step 10 cannot claim direction closure while knowingly leaving the site unmigrated; the §4.7 mechanism exactly, mandatory in C2 |

Q-P3-1 (rev 1) was RESOLVED BY SOURCE in rev 2 (§0 item 1) and never
reached the operator.

### 14.1 Freeze dispositions (operator rulings 2026-08-20, recorded verbatim)

| id | disposition |
|---|---|
| **Q-P3-2** | `GATE_1_REQUIRED` · budget **≤ 3 real calls** · coverage = **comparison + causal lower-direction behavioral surfaces** (acceptance A: given unambiguous candidate scores the real model identifies the LOWER score as SOTA under the stated direction; acceptance B: schema-valid prediction, `predicted_value` toward BETTER = LOWER, threshold on the REFUTED side, no inversion) · preferred execution = ONE production-shaped proposer run on a DAVIS/lower fixture; per-stage fallback allowed; optional higher-regime control only in the fallback shape · NO real call on absent identity (deterministic-owned) · evidence from persisted stage artifacts, not prompt inspection · a wrong model behavior is a real Gate failure — no blind rerun; a grammar/code correction is a NEW candidate with its own bounded Gate |
| **Q-P3-3** | `NO_RAW_SECONDARY_CONSUMPTION` · `ProposerInterpretationEvidence` has NO `per_model_secondary_metrics` field · no raw `macro_f1`/`psnr`/`mae`, refusal entries or runtime diagnostics in proposer prompts · `secondary_metric_errors`/crash strings NEVER proposer evidence · reserved extension name documented only · future exposure needs an explicit semantic owner/ruling · required negative test: DAVIS upstream carries real `psnr`+`mae`, evidence and prompt bytes carry none · ordering-operand invariant stays scope-extended over proposer files |
| **Q-P3-4** | `INCLUDE / BOUNDED` — a bounded correctness closure, not scope creep · §4.7's exact mechanism: `clamp_and_backstop_accumulated` / `clamp_comparative_analysis` consume `MetricOrder \| None` from the SAME typed identity; no new ordering authority; no new metric derivation · order present ⇒ retention = BEST per `MetricOrder`; order absent ⇒ score draw SKIPPED, recency-only, no "best" claim · required fixtures: DAVIS lower (lowest retained, worst clamped out) · TIDMAD/Pets higher · absent identity (recency-only) · the P2a scanner's transitive-taint behavior is NOT widened; the blind spot is recorded in that census when touched; hand-computed behavioral fixtures own the migrated site |
| **C-P3-1** | Gate-surface consistency — every live Gate contract (C5, §8.2, §16, the §0 table) states that Gate 1 covers BOTH comparison/SOTA interpretation AND causal prediction authoring under the lower control; no wording implies causal-only coverage; the deterministic D1/D2/D3 diff-surface tests remain required |
| **C-P3-2** | Ordering-wording precision — the live invariant reads: P3 adds ZERO NEW ordering semantics, ZERO NEW ordering authorities, ZERO metric-direction derivation authorities, and MIGRATES the already-existing F-P3-1 clamp preference site onto the existing P2a `MetricOrder` authority (the semantic decision already existed; P3 fixes its direction handling). `MetricOrder` implementation, reconciliation authority, `top_n` comparison and the P2a scanner's precision contract all unchanged (§10) |
| **Gate 2** | `NOT REQUIRED` (§8.3) |

---

## 15. Adversarial self-review

| attack | answer |
|---|---|
| A proposer path still bypasses the projection? | After C3 the raw field does not exist; the CLI calls the same function; census + plant stand guard; no other production module reads `ProposalInput.interpretation` (measured §2.1) |
| Production and standalone read the same artifact differently? | One function, one Mapping input shape, equality-tested on identical bytes from C1; the persisted artifact IS `model_dump_json` (§4.2) |
| Lower-is-better becomes higher through wording? | D1 states direction from the ONE wording authority; D2's DAVIS fixture falsifies an upward example; the §2.6 vocabulary audit classifies every remaining "best/improve" as direction-safe |
| A secondary influences ranking? | none is projected (Q-P3-3 ruling); the ordering-operand invariant is scope-extended to the proposer files with a live plant; if a future ruling ever exposes them, the same invariant already covers the surface |
| A secondary inherits the primary direction? | no secondary renders in P3 at all (Q-P3-3); the historically-recorded rejected shape would have mandated `render_secondary_metrics`, which asks each spec's OWN order (09b, unchanged) |
| Direction re-derived from a name/sign/task? | the ONLY identity source is `metric_identity_from_mapping` over the digest's provenance; zero new `MetricOrder` construction sites outside the evidence path; the P2a scanner stays green over the whole diff |
| Unavailable/refused presented as scored? | absent identity renders the canonical phrase and suppresses examples/ranking (D1/D2 absence states; `top_n`/clamp fallbacks); the projection never fabricates a value for an absent key (None rule) |
| A crash diagnostic masquerades as science? | no crash carrier is projected (§4.1's exclusion list; secondary errors excluded with Q-P3-3) |
| Raw `InterpretationOutput` leaks past the boundary? | the value embeds only declared fields; the protocol passes the dump ONLY into `build_proposer_evidence`; a whole-object field would fail §4.1's non-goal review trigger and the census |
| The schema mirrors the producer and defines no boundary? | 30 carried / 12 refused / 2 dead-dropped, each refusal named with a reason (§4.1) — the asymmetry is the boundary |
| P3 implemented P5 lifecycle? | zero carrier/digest/restore/ChainState changes (§9; §10's invariant list) |
| P3 widened Step-12 composition/package semantics? | zero composition-root, manifest, or task-package edits; the task-science prompt content byte-preserved and its ownership left with the roadmap's Step-10/12 line (§1, §3) |
| Tests green for the wrong reason? | the whitelist finally gets a FULL-coverage golden (the parent measured 8/18 keys and zero prediction keys pinned today); the C0 plant/mutation steps prove each census can go RED; the clamp's guard is behavioral because the AST census provably cannot see the site (§2.7.1) |
| The intermediate states are incoherent? | C1's dual-population state is the ONE declared intermediate, closed by C2/C3 inside the same PR (parent §20.7's anti-rule satisfied — no fake/unreachable feature at any commit boundary) |

### 15.1 Freeze-time adversarial check (operator-required, answered before freeze)

| attack | answer / owner |
|---|---|
| Can comparison-stage D3 pass every deterministic test while a real model still chooses the numerically highest DAVIS score as SOTA? | YES — deterministic tests prove prompt bytes, not obedience. **That is precisely why Gate-1 acceptance A exists** (§8.2): the persisted comparison artifact must name the LOWER score as SOTA on unambiguous inputs, or the Gate FAILS |
| Can causal D2 move upward under DAVIS? | in rendering: the hand-written DAVIS fixture turns RED on any upward example or below-current threshold. In model behavior: Gate-1 acceptance B catches it from the persisted prediction |
| Can the clamp still retain highest rather than best-under-order? | the DAVIS hand-computed retention fixture asserts the LOWEST-mse entries are retained and the known worst model is clamped OUT — RED otherwise (§4.7; the AST scanner provably cannot own this site, so the behavioral fixture is the standing guard) |
| Can absent identity silently default to higher? | impossible at all four surfaces by construction: `top_n` → the P2a-pinned order-free `all` fallback; clamp → score draw SKIPPED, recency-only; D1 → the canonical unavailable statement with zero direction words; D2 → numeric example OMITTED. Each has its own absence fixture, and `metric_identity_from_mapping` returns None (never a default direction) for malformed identity |
| Can raw P2b secondaries enter proposer evidence? | the field does not exist (schema), the required DAVIS negative fixture asserts evidence AND prompt bytes carry none, and the raw-dict input is removed in C3 so there is nothing left to mine them from |
| Can P3 create a new ordering authority? | NO — zero new comparators/enums/derivations; every ordering ask goes through the existing `MetricOrder` from the one validated identity; the P2a scanner plus the §8.1 census row stand guard (C-P3-2's precise wording in §10) |
| Can P3 implement P5 lifecycle? | NO — zero carrier/digest/restore/`ChainState` changes (§9, §10); the value is built per invocation |

---

## 16. Definition of done

All §7 checklists `[x]` with evidence; censuses standing; **Gate 1 PASS per
§8.2 — BOTH behavioral surfaces (comparison/SOTA interpretation AND causal
prediction authoring) under the lower-is-better control, ≤ 3 real calls,
operator-approved launch, verdict from persisted stage artifacts**; the
deterministic D1/D2/D3 diff-surface tests green; node `.md` synced; ONE
exact-head CI green with run id + SHA recorded; STOP at **READY FOR
OPERATOR REVIEW — DO NOT MERGE**. Post-merge status sync (parent §0 ·
roadmap Step-10 row · CLAUDE.md current-state) is a separate follow-up
commit, per Step-10 practice.

---

## 17. Implementation ledger (LIVE — opened at implementation start)

**Numbering note.** §16 is the frozen *Definition of done*; renumbering a
frozen section would rewrite frozen history, so the ledger opens at **§17**.
No semantic change.

| field | value |
|---|---|
| freeze SHA | `c5f95ff0af680d732cbc2b6b0a34407c38cb36a8` (subject: *docs(step10/p3): REVISION 3 — FROZEN; operator freeze rulings + two bounded corrections*; parent `79f300a6`) |
| implementation base | `c5f95ff0` — **identical to `origin/master`** at implementation start, so post-freeze drift is ZERO. Contains P1 `bcb17e45`, P4 `79833db8`, P2a `e094fa26`, P2b `5a2ecfd1` (all four merged prerequisites verified as ancestors) |
| implementation branch | `step10-p3-proposer-typed-evidence-impl` |
| Gate disposition | **Gate 1 REQUIRED** (§8.2, Q-P3-2) · Gate 2 NOT REQUIRED / NOT RUN · real training, real inference, GPU NOT RUN |

### 17.1 Source preflight (performed BEFORE any edit, at `c5f95ff0`)

The design's §2 anchors were measured at merged `06291e5f`; the only commits
between that and `c5f95ff0` are the two P3 design-document commits
(`79f300a6`, `c5f95ff0`), so the **production tree is byte-identical to the
tree §2 describes**. Re-measured and CONFIRMED at head:

| §2 claim | measured at `c5f95ff0` | verdict |
|---|---|---|
| node module 2,383 LOC | 2,383 | EXACT |
| `nodes/proposal_helpers.py` 777 LOC | 777 | EXACT |
| `agent/schemas/proposal.py` 1,307 · `interpretation.py` 1,286 · protocol 295 | 1,307 · 1,286 · 295 | EXACT |
| `_run_pipeline` 666 LOC / 83 branch-ish | lines 1575-2240, **666 LOC**, **83** branch-ish (IR-P3-1) | EXACT |
| `_build_reasoning_prompt` 224 LOC | lines 1086-1309, 224 | EXACT |
| `_format_healthgate_evidence_block` 108 LOC | lines 789-896, 108 | EXACT |
| raw reads: 40 node + 12 helpers | 40 + 12, every site enumerated below | EXACT |
| `InterpretationOutput` 42 fields | 42 | EXACT |
| 30 carried / 12 refused | 42 − 12 refused = 30 carried; both lists enumerated below | EXACT |
| `ProposalInput.per_model_score_tables` has ZERO readers (§2.7.2) | repo grep: only the schema declaration (`proposal.py:691-698`) and the protocol population (`:185-188`) — no reader anywhere | CONFIRMED |
| `interpretation.py:32` imports `VocabEntry` from `proposal.py` (§2.7.3 cycle) | `agent/schemas/interpretation.py:32` — `from agent.schemas.proposal import VocabEntry` | CONFIRMED |
| protocol populates the full dump at `:172` | `"interpretation": output.model_dump()` at :172 | EXACT |
| CLI builds `ProposalInput` directly at `:2347-2357` from `interpretation_{run}.json` `:2328-2335` | EXACT | CONFIRMED |

**IR-P3-1 — the branch-ish metric definition.** §6's "83 branch-ish nodes"
had no stated AST predicate. Measured reproducibly: counting
`{If, For, AsyncFor, While, Try, BoolOp, IfExp, comprehension}` over
`_run_pipeline`'s subtree gives **exactly 83** (If 48 · For 7 · Try 3 ·
BoolOp 10 · IfExp 2 · comprehension 13); adding `ExceptHandler` gives 86 and
adding `Return/Raise/Break/Continue` gives 98. The 83-matching predicate is
therefore the frozen baseline's definition and is the one this ledger uses
for every later measurement. Validation: the same script reproduces §6's
other three measured LOC figures exactly.

**The 40 node-module raw reads, by owner** (`interp*.get(` / `interpretation[`):
`_format_healthgate_evidence_block` :816, :817, :818, :825 (4) ·
`_build_reasoning_prompt` :1105-:1227 (26) · `run()` :1467 (1) ·
`_run_pipeline` :1620, :1621, :1622, :1623, :1626, :1670, :1698 (7) ·
`main()` (CLI) :2359, :2360 (2). **The 12 helper reads**:
`_interpretation_order` :50 (1) · `select_candidate_models` :81-:89 (9) ·
`resolve_exploration_mode` :409, :417 (2).

*Preflight note (bounded, no design change)*: §2.1's table describes the CLI
as reading the raw dict at its construction site; the CLI **also** prints
two raw reads at `:2359-2360`. They are inside the same `main()` and are
covered by C3's "the CLI uses `build_proposer_evidence` only" — the standing
census counts them, so C3's ZERO includes them.

**The 30 carried fields** (= the measured live-read union): `model_types` ·
`model_descriptions` · `total_experiments` · `per_model_best` ·
`per_model_best_valid` · `per_model_raw_best_health_validity` ·
`per_model_worst` · `best_denoising_score` · `best_valid_denoising_score` ·
`worst_denoising_score` · `best_config` · `model_knowledge_cache` ·
`key_findings` · `bottlenecks` · `take_home_message` ·
`per_model_score_tables` · `per_model_params` ·
`per_model_training_segments` · `vocab_diversity_ratio` ·
`cumulative_information_gain` · `scientific_accuracy` ·
`prediction_outcomes_history` · `per_model_round_health_counts` ·
`per_model_collapse_fingerprints` · `collapse_fingerprint_history` ·
`metric_identity` · `prediction_evaluation_semantics` ·
`prediction_outcomes_by_semantics` ·
`cumulative_information_gain_by_semantics` · `prediction_pool_sizes`.
**The 12 refused**: `cold_start` · `scientific_aggregation` ·
`best_valid_config` · `runtime_vocab` · `prediction_evaluation` ·
`new_discoveries` · `vocab_changes` · `vocab_link_confirmations` ·
`is_degraded` · `evolution_stats` · `per_model_failure_counts` ·
`per_model_secondary_metrics`. 30 + 12 = 42 — the arithmetic closes against
the live schema, so §4.1's field set is complete and exclusive.

**IR-P3-2 — the §2.7.3 import cycle would NOT have fired with the frozen
field types; the relocation is executed anyway, as frozen.**

```text
Previous assumption (§2.7.3):
  proposer_evidence.py must declare "types drawn from interpretation.py
  (MetricIdentity, SecondaryMetricEvidence, CollapseFingerprint*)", closing
  the cycle proposal -> proposer_evidence -> interpretation -> proposal.

Audit evidence (measured at c5f95ff0):
  * CollapseFingerprint / CollapseFingerprintHistoryEntry are declared in
    agent/schemas/health_feedback.py, NOT interpretation.py (interpretation.py:25-30
    imports them from there);
  * SecondaryMetricEvidence is NOT carried at all (Q-P3-3 = NO_RAW_SECONDARY_CONSUMPTION);
  * the identity field's frozen type is `MetricIdentityKey | None` (§4.1) — a
    NamedTuple in execute_tools/evaluation_metric.py:763, the return type of
    metric_identity_from_mapping — NOT interpretation.py's MetricIdentity model;
  * none of evaluation_metric.py / score_table.py / health_feedback.py imports
    agent.schemas.proposal (grep, this session).

Corrected understanding:
  With §4.1's frozen field set, proposer_evidence.py needs NO import of
  interpretation.py, so no cycle would have formed.

Implementation consequence: NONE — the relocation is executed exactly as
frozen (§4.2, C1 checklist item 1). It is an unconditional frozen invariant,
not a conditional remedy, and it independently removes a real backwards
architectural edge (an UPSTREAM node schema importing from a DOWNSTREAM node
schema, interpretation.py:32) that §2.7.3 correctly identifies as a defect on
its own terms. It also removes the hazard for any FUTURE field whose type
does live in interpretation.py.

Validation consequence: the C1 import-cycle probe still lands, but it is now
recorded as proving the ABSENCE of a cycle rather than the repair of one;
the seven-importer re-export inventory test is unaffected.
```

**Measured anchor corrections (test files only; no design semantics move).**

| §2 anchor | design says | measured at `c5f95ff0` |
|---|---|---|
| P2a ordering scanner path | `test_step10_p2a_c0_ordering_scanner.py` (path implied under `tests/unit/nodes/`) | **`tests/unit/execute_tools/test_step10_p2a_c0_ordering_scanner.py`** (786 LOC) |
| `GOLDEN_SCORE_NAMES` | `:93` | `:87-101` (the tuple); `_GOLDEN_RE` at `:103` |
| one-hop alias rule | `:194-232` | `_golden_aliases` at `:194-232` — EXACT |
| P2a pins P3 retires | `test_step10_p2a_c4_proposer_top_n.py:194-211` | `:194-201` and `:203-211` — EXACT |
| 09a invariant lists | `INTERPRETER_FILES + PRODUCTION_FILES` | `:440-446` / `:452-463`, `SCANNED_FILES` `:465`; existence assert `:527-543`; live-scope probe `:545-571` iterates **`PRODUCTION_FILES` only** |
| PB-3 fixture whitelist coverage | "8/18 keys" (parent's measurement) | **10/18** — `model_types` · `total_experiments` · `best_denoising_score` · `worst_denoising_score` · `key_findings` · `bottlenecks` · `take_home_message` · `per_model_best` · `per_model_worst` · `per_model_score_tables`. The 8 ABSENT are the seven prediction keys + `vocab_diversity_ratio`. The design's point stands unchanged (no prediction key is pinned today); only the count moves |

**IR-P3-3 — D1 renders through the `.id`-reading sibling of the SAME authority.**

```text
Question:
  §4.5 D1 says the metric-context block is "built on render_metric_identity"
  (agent/prompt_templates/interpretation/rendering.py:240-263). But §4.1 freezes
  the evidence field type as `MetricIdentityKey | None`, and
  render_metric_identity reads `identity.metric_id` — a field MetricIdentityKey
  does not have (its field is `id`).

Source evidence:
  * probe at head: render_metric_identity(MetricIdentityKey(id='mse',
    direction='lower')) -> AttributeError: no attribute 'metric_id';
  * agent/prompt_templates/tuner/rendering.py:264-273 declares
    render_metric_identity_line(spec), which reads `spec.id` and produces the
    IDENTICAL sentence — probe: "golden metric `mse` (lower is better)" and
    "golden metric `tidmad_denoising_score` (higher is better)";
  * BOTH renderers obtain their direction words from the SAME single authority,
    render_metric_direction_words -> MetricOrder.direction_words
    (tuner/rendering.py:246-261); render_metric_identity's own docstring
    (:249-252) records that the two exist precisely because the two carriers
    name the id field differently.

Options considered:
  (a) change the frozen field type to interpretation.MetricIdentity — rejected:
      it re-opens the §2.7.3 import edge and edits a frozen §4.1 row;
  (b) adapt MetricIdentityKey into MetricIdentity at the render site — rejected:
      an adapter between two carriers of the same pair is the mapping layer
      §4.1 exists to avoid;
  (c) call render_metric_identity_line, the sibling that already reads `.id`.

Chosen ruling: (c). ZERO new authority, ZERO new direction derivation — the
direction words still come from MetricOrder and nowhere else, satisfying
Step 06's C5 boundary guard and C-P3-2 exactly. §4.5's phrase "the 09b line
authority" is satisfied in substance: it is the same sentence from the same
direction authority, addressed to the carrier P3 actually holds.

Validation: the C4 three-task hand-written fixtures assert the exact rendered
bytes for higher / lower / absent.
```

**IR-P3-4 — `interpretation_evidence` is OPTIONAL in C1 and REQUIRED in C3.**

```text
Question:
  §4.2 annotates ProposalInput.interpretation_evidence "(REQUIRED)" under a
  "(C1 adds, C3 removes)" heading. Making it required in C1 breaks every
  existing ProposalInput construction.

Source evidence:
  * 49 ProposalInput( sites across 23 test files; 46 pass `interpretation=`
    and NONE passes `per_model_score_tables=` (measured this session);
  * the FROZEN invariant is worded "**By C3**: interpretation_evidence
    REQUIRED" — a deadline, not a C1 state;
  * §7 C3's scope explicitly OWNS "test-fixture migration (test-disposition
    audit per the standing rule — every fixture constructing
    ProposalInput(interpretation=...) is KEEP/UPGRADE/REWRITE'd by intent,
    never mass-edited)";
  * §7 C1's own acceptance reads "prompt bytes unchanged (goldens green —
    nothing reads the new field yet)", which presupposes that existing
    fixtures still validate at C1.

Chosen ruling: C1 declares `interpretation_evidence: ProposerInterpretationEvidence
| None = None`, populated by BOTH production entrypoints. C3 flips it to a
REQUIRED field with no default in the SAME commit that removes
`interpretation` / `per_model_score_tables` and performs the frozen fixture
disposition audit. No compatibility shim, no schema-level back-fill validator,
and no second construction site: the ONLY producers of the value remain the
protocol and the CLI, both calling build_proposer_evidence.

Rejected alternative: a model_validator back-filling the evidence from the raw
dict when absent. It would have removed the fixture churn entirely, but it
makes "the protocol populates the field" unobservable by omission — a wiring
that is silently repaired is the exact defect class the §11.2 acceptance rule
exists to prevent.

Validation: C3's schema test asserts ProposalInput cannot be constructed
without the evidence; the C1 equality test asserts the protocol and CLI produce
EQUAL values from identical bytes.
```

**IR-P3-5 — the private rendering module takes a NON-underscore name and the
node adopts the decomposed-node public boundary in the same commit.**

```text
Question:
  §6 fixes the private module's "exact name at implementation". A leading
  underscore would make it invisible to tests/unit/nodes/test_node_public_boundary.py
  (_private_modules(), :54-59, skips names starting with "_"), which is the
  cheaper path but forfeits the very guard §6 says the extraction runs UNDER.

Source evidence:
  * §6: "The private-module extraction runs UNDER the node public-boundary rule
    ... as the interpreter's evidence.py/ordering.py/prediction.py already
    demonstrate in nodes/result_interpretation_agent/" — the cited precedent
    uses NON-underscore names and is therefore a scanned, decomposed node;
  * nodes/ml_model_proposal_agent/ has ZERO private modules today, so it is
    currently EXCLUDED from the decomposed-node rules (4/5/6);
  * rule 6 (:227-270) requires the MAIN module to declare __all__ containing
    every public class and "main", to exclude underscore names from __all__,
    and to name its scaffold _COMPATIBILITY_REEXPORTS. ml_model_proposal_agent.py
    declares NEITHER today; result_interpretation_agent.py declares both
    (__all__ :80, _COMPATIBILITY_REEXPORTS :102) — the precedent to copy.

Chosen ruling: name the module `evidence_rendering.py` (no underscore) and, in
the SAME commit that creates it (C2), add the `__all__` +
`_COMPATIBILITY_REEXPORTS` declarations to ml_model_proposal_agent.py following
the interpreter's shape. This turns four additional structural guards ON for the
proposer node rather than off, which is the direction §6 asks for.

Validation: tests/unit/nodes/test_node_public_boundary.py green at C2 head with
the proposer newly INSIDE _decomposed_nodes() — recorded with the before/after
node set.
```

### 17.2 Guard-disposition table (C0 — every §2.8 guard, with its flipping commit)

| # | guard | anchor at base | disposition | flipping commit | status |
|---|---|---|---|---|---|
| G1 | `TestP3sArchitectureIsUntouched::test_the_helper_signature_did_not_change` (`tests/unit/nodes/test_step10_p2a_c4_proposer_top_n.py:194-201`) | pins `select_candidate_models(interpretation, strategy)` | **RETIRE** — replaced by the typed-signature test; the SEMANTICS it protected (declared identity · never assume · order-free fallback) re-pinned on the typed path | **C2** | `[ ]` |
| G2 | `TestP3sArchitectureIsUntouched::test_no_typed_evidence_reader_was_introduced` (`:203-211`, asserts zero `ClassDef` in `proposal_helpers.py`) | no reader type before P3 | **RETIRE** — its stated purpose arrives; successor = the ONE-authority census | **C1** | `[ ]` |
| G3 | PB-3 goldens (`goldens/pb3_*`, 9 files) | pipeline prompt bytes on the 10/18-key fixture | **KEEP UNCHANGED** as the parity baseline; C0 adds the full-coverage set beside them | — | `[x]` green at C0 |
| G4 | PB-4 / S1-E goldens + `test_step01b_legacy_reasoning_golden.py` | legacy COMMIT bytes + legacy reasoning SYSTEM bytes | **KEEP** — legacy is byte-exact THROUGH the adapter | C3 acceptance | `[x]` green at C0 |
| G5 | WF-3 components key set (`wf3_proposer_components_key_sets.json`) | `_audit_proposer_components` 11-key breakdown | **KEEP UNCHANGED** — the audit reads `accumulated`, whose shape is preserved (§4.3) | — | `[x]` green at C0 |
| G6 | 09a ordering-operand invariant (`test_step09a_c6_evidence_projection.py`) | no ordering expression takes a secondary operand | **SCOPE-EXTENDED** to the proposer files, plant-proven | **C0** | `[x]` done |
| G7 | P2a C4 behavioral fixtures (DAVIS inversion · Pets · TIDMAD · absent-identity `all`) | `top_n` semantics | **KEEP UNMODIFIED** — must stay green across C2's mechanism swap | — | `[x]` green at C0 |
| G8 | `test_health_evidence_block.py` (incl. the malformed-history `ValueError` matching `model 'model_a'`) | flag-gated health rendering | **UPGRADE in C2**: rendering parity preserved; the malformed-entry failure MOVES from render-time to projection-time (typed validation) — declared behaviour delta, fail-closed earlier | **C2** | `[ ]` |
| G9 | `test_health_prompt_parity.py:33-34` — subscripts `inp.interpretation["…"]` as a dict before asserting the golden | the flag-OFF legacy prompt | **UPGRADE in C3** — the two subscripts become typed reads; the golden itself stays byte-identical | **C3** | `[ ]` |
| G10 | `test_node_public_boundary.py` decomposed-node rules 4/5/6 | currently DORMANT for the proposer (zero private modules) | **ACTIVATED in C2** by IR-P3-5 | **C2** | `[ ]` |
| G11 | P2a ordering scanner (`tests/unit/execute_tools/test_step10_p2a_c0_ordering_scanner.py`) | the production ordering surface is EMPTY | **KEEP GREEN, NOT WIDENED** (Q-P3-4 ruling); blind-spot paragraph added to its docstring | **C0** (note) / stays green through C2 | `[x]` note added |

### 17.3 C0 — COMPLETE (`[x]` with evidence)

Commit scope: tests + goldens + this ledger. **Zero production diffs** —
`git status --porcelain` before the commit listed only
`tests/**`, `goldens/**` and this design document.

- [x] **Full-coverage interpretation fixture** —
      `tests/unit/agent/ml_model_proposal_agent/test_step10_p3_c0_baselines.py`,
      `full_coverage_interpretation()`. Built from a REAL
      `InterpretationOutput(...).model_dump(mode="json")` rather than a
      hand-written dict, so it cannot drift from the producer's shape. That
      choice paid immediately: three successive `ValidationError`s
      (`AggregateScalars` shape · one row per declared file · Σ`linear_weight`
      ≈ 1.0) proved a hand-written stub would NOT have been a
      production-shaped dump. Populates **18/18** whitelist keys (asserted
      against the LIVE production tuple, extracted by AST — not a copied
      list), the legacy-only live reads (`best_valid_denoising_score`,
      `best_config`), the health-evidence trio, `metric_identity`
      (**DAVIS-shaped `lower`**), and REAL secondaries.
- [x] **Legacy-absence fixture** — `legacy_absence_interpretation()`: keys
      MISSING, not empty, asserted as such.
- [x] **Baseline goldens — 12 captured** at `c5f95ff0`, clean tree, via an
      explicit developer capture (Step-00 §17 rule 3; tests never write
      goldens): `p3c0_full_{comparison,causal,proposing}_{explore,exploit}_system.txt`
      (6) · `p3c0_full_{comparison,causal,proposing}_user.txt` (3) ·
      `p3c0_absent_comparison_user.txt` · `p3c0_full_legacy_reasoning_user.txt`
      · `p3c0_absent_legacy_reasoning_user.txt`.
      **Byte-stability**: two independent captures produced identical
      sha256 for all 12. **No environment leakage**: `grep -E "/home/|/tmp/|<user>"`
      over all 12 → no match (§7 C0 failure-case 6 cleared).
      **Mode-invariance** of the three user prompts asserted DURING capture,
      not merely in the test.
- [x] **Raw-reader census** —
      `tests/unit/nodes/test_step10_p3_proposer_evidence_census.py`. AST, not
      grep. Pins **40** (node module) + **12** (helpers), matching the
      hand-counted §2.2 inventory exactly. Anti-vacuity: **5 planted shapes**
      (`interpretation.get` · `interp.get` · `interpretation[...]` ·
      `inp.interpretation.get` · `self.interpretation[...]`) each caught when
      planted into REAL module source; a precision test proves
      `accumulated.get` / `entry[...]` / `interp_summary.get` are NOT counted.
- [x] **Ordering-operand invariant scope extension** — `PROPOSER_FILES`
      (4 entries) added to `test_step09a_c6_evidence_projection.py`;
      `SCANNED_FILES` and `test_the_scope_extension_is_live` both extended, so
      a listed-but-never-opened file cannot pass.
      **LIVE on-disk plant-and-catch**: a secondary-keyed `order.best(...)`
      appended to `nodes/proposal_helpers.py` turned the invariant **RED**
      with `{'nodes/proposal_helpers.py': ["781: order.best(models, key=lambda
      m: m['secondary_metric_results'][0]['scalar'])"]}`; after revert
      **GREEN**, tree clean (`git status --porcelain nodes/proposal_helpers.py`
      empty).
- [x] **Q-P3-3 negative fixture landed EARLY** (C0, not C4): seven forbidden
      tokens asserted absent from every pipeline system+user prompt and from
      the legacy prompt, with `test_the_probe_would_notice` proving the tokens
      ARE present upstream — so the assertion cannot pass vacuously.
- [x] **Guard-disposition table** — §17.2 above.
- [x] **Scanner blind-spot note (F-P3-1)** — a "MEASURED instance of the first
      bullet" section added to the P2a scanner's module docstring, naming the
      site, the mechanism (`_score` call indirection defeating the same-scope
      one-hop alias rule), the Q-P3-4 disposition (MIGRATE the site, do NOT
      widen the scanner), and the general lesson. Per the F-P2b-4 per-census
      rule; the scanner's own tests stay green and untouched.

**Validation (C0).**

| command | result |
|---|---|
| `pytest tests/unit/agent/ml_model_proposal_agent tests/unit/nodes tests/unit/agent/result_interpretation_agent/test_step09a_c6_evidence_projection.py tests/unit/execute_tools/test_step10_p2a_c0_ordering_scanner.py -q` | **742 passed**, 9.80 s, exit 0 (verdict read from the log file, not a wrapper status) |
| `ruff check` + `ruff format --check` over the 4 touched/created test modules | clean (3 auto-fixed `RUF100`, 1 reformat, both re-verified) |
| `pyright` over the new modules | **COULD NOT RUN LOCALLY** — the vendored pyright fails on this box's Node runtime. Recorded rather than claimed; the exact-head PR CI is the authority for the type check (repository rule: never claim local validation the environment cannot perform) |

### 17.4 C1 — COMPLETE (`[x]` with evidence)

The contract EXISTS and both production entrypoints populate it, while both
old readers still work off the dict. This is the ONE declared dual-carrier
intermediate state, closed by C2/C3 inside this PR.

- [x] **`VocabEntry` relocated VERBATIM** to `agent/schemas/vocab.py` (new,
      63 LOC); `agent/schemas/proposal.py` re-exports it via `import` (never a
      copy — asserted by object identity); `agent/schemas/interpretation.py:32`
      re-pointed, which is the ONE import line outside the new module and
      removes the backwards producer→consumer edge. Verbatim proven by a
      declaration test: the 10 field names in order, `tier` default
      `"candidate"`, `pattern` default `None`, `related_to` default-factory
      `[]`. All five live importer modules re-imported for real.
- [x] **`ProposerInterpretationEvidence`** — `agent/schemas/proposer_evidence.py`
      (new). Frozen, `extra="forbid"`, **30 fields**. The boundary is asserted
      against the LIVE producer schema rather than a copied list:
      carried ∪ refused = all 42 upstream fields, carried ∩ refused = ∅, and
      **every refusal carries a stated reason** (`NOT_CARRIED`, 12 entries).
      A new upstream field that is neither carried nor refused turns this RED —
      the §12 review trigger, made executable. `DEAD_READS` records the two
      names the legacy renderer asked for that the producer never declared,
      with a test asserting they are still undeclared upstream (so the "dead
      read" premise itself is re-checked, not assumed).
- [x] **`build_proposer_evidence(Mapping) -> ProposerInterpretationEvidence`** —
      takes the MAPPING, which is what makes the second caller possible at all.
      Unknown upstream keys are filtered before validation, so a NEWER producer
      cannot break an older node (tested) — necessary because the model is
      `extra="forbid"`.
- [x] **`metric_identity` populated ONLY via `metric_identity_from_mapping`** —
      the one transported-identity validator. Six malformed shapes (unknown
      direction · missing id · empty id · non-mapping · `None` · `int`) all
      project to `None`, never a raise and never a default direction; an
      anti-vacuity case proves a VALID identity still lands with its real
      direction, so a projection hardcoding `None` would fail.
- [x] **Protocol populates the typed field** beside the dict
      (`ml_result_interp_to_ml_model_propose.py`), from the same dump.
- [x] **CLI populates it through the SAME call** (`main()`), on the loaded
      artifact.
- [x] **Both entrypoints produce ONE value** — the equality test round-trips
      through the FILESYSTEM (`model_dump_json` written and re-read) rather
      than reusing a dict, so the claim is about the real CLI path; a second
      test proves the equality is not trivially true.
- [x] **Import-cycle probe** — `proposal → proposer_evidence → interpretation`
      imported in one process. Per **IR-P3-2** this records the ABSENCE of a
      cycle: with §4.1's frozen field types the new module needs
      `evaluation_metric` / `score_table` / `health_feedback`, none of which
      imports `agent.schemas.proposal`.
- [x] **G2 RETIRED** — `test_no_typed_evidence_reader_was_introduced`
      (`test_step10_p2a_c4_proposer_top_n.py:203-211`) removed, replaced in
      place by a comment naming its successor. Its PURPOSE is inherited by
      `TestTheProjectionHasExactlyOneAuthority`, which survives the type
      existing: `build_proposer_evidence` and `ProposerInterpretationEvidence`
      are each defined exactly once across six production directories, with a
      plant proving the scan reports a second definition.
- [x] **`ProposalInput.interpretation_evidence` added, OPTIONAL** per
      **IR-P3-4**, with the C3 flip named in its own description.
- [x] **Ordering-operand invariant** extended to
      `agent/schemas/proposer_evidence.py` in the commit that created it.
- [x] **Zero prompt-semantic delta** — every PB-3 / PB-4 / S1-E and P3-C0
      golden green, unmodified: nothing reads the new field yet.

**Declared envelope delta (found by a guard, not by review).** The Step-09.5a
differential oracle
(`tests/unit/workflows/test_step09_5a_c0_oracle.py`) went RED: the proposer's
run input gained a key. That is the oracle working — it exists to make an
additive change to a node's input envelope *declared rather than discovered* —
and its module docstring already carries a "Declared deltas" protocol with
P2b C2 as the precedent. Disposition: **measured first, re-baselined second.**
The old golden was preserved and diffed against the new one: **exactly ONE
difference, `.node_calls.proposal.run_inputs[0].interpretation_evidence:
ADDED`**, with zero changed and zero removed values. Re-baselined through the
module's own sanctioned mechanism (`SIDERIUS_REWRITE_STEP095A_ORACLE=1`, not by
deleting the file), and the delta is now recorded in the oracle's declared-delta
list with its reason.

**Validation (C1).**

| command | result |
|---|---|
| `pytest tests/unit/agent/ml_model_proposal_agent/test_step10_p3_c1_projection.py -q` | **32 passed** (first run, no fixes needed) |
| `pytest tests/unit/agent/ml_model_proposal_agent tests/unit/agent/protocols tests/unit/nodes tests/unit/agent/result_interpretation_agent -q` | **1387 passed** |
| every `VocabEntry`-importing test module + `tests/unit/agent/schemas` + `tests/unit/workflows` | 1306 passed / 1 failed → the oracle above; green after the declared re-baseline |
| `ruff check` + `ruff format --check` over all 8 touched files | clean |
| `pyright` | still NOT runnable locally (Node runtime); exact-head CI is the authority |

### 17.5 C2 — COMPLETE (`[x]` with evidence)

The production path consumes the typed value; the whitelist finally gets its
pin; P2a's threading is replaced by the mechanism its own docstring requested;
and the F-P3-1 direction site is migrated onto the existing order authority.

- [x] **Whitelist serializer relocated and pinned** —
      `INTERPRETATION_SUMMARY_KEYS` + `build_interpretation_summary` in the new
      private module. Parity is a DIFFERENTIAL, not a claim: the C2 test builds
      the block both ways over the same dump and requires deep equality AND
      key-order equality, over three fixtures proven to exercise three
      different key subsets. The oracle is written out rather than imported —
      the production comprehension no longer exists, and comparing against a
      compatibility alias of the new code would be the self-referential parity
      trap.
- [x] **Direct pipeline reads → typed fields**; candidate summaries keep
      DICT-shaped `score_table` (the §4.3 hazard: `build_candidate_markdown_block`
      dispatches on `isinstance(table, dict)` and would render
      "_Score table unavailable._" for a typed object) — asserted directly.
- [x] **`select_candidate_models(evidence, strategy)` /
      `resolve_exploration_mode(evidence, pipeline)`** typed;
      `_interpretation_order` DELETED and replaced by `evidence_order`, exactly
      as its own docstring instructed; `_guess_source` dropped its unused
      `interpretation` parameter in passing.
- [x] **`top_n` comparison UNCHANGED** — all 20 P2a C4 tests green with their
      fixture DATA untouched; only the carrier moved (a shared `_evidence()`
      helper wraps the same payload). If a P2a expectation had needed editing,
      the comparison semantics would have moved, which P3 may not do.
- [x] **Health block relocated and typed** — `render_healthgate_evidence_block`;
      the malformed-history failure MOVED from render-time to projection-time
      (guard G8's declared delta). `ValidationError` subclasses `ValueError`, so
      the caller-visible failure CLASS is unchanged; a reachability test proves
      the projection now yields TYPED history entries, so the renderer is not
      quietly guarding them again.
- [x] **F-P3-1 clamp migrated (Q-P3-4)** — `clamp_comparative_analysis` and
      `clamp_and_backstop_accumulated` take `order: MetricOrder | None`,
      **keyword-only and REQUIRED with no default** (a silent default would
      drop the score draw by omission). `_score`'s `-inf` sentinel became
      `order.worst_sentinel` — `-inf` is "worst" only under `higher`; under
      `lower` it is the BEST value, so a missing score would have been promoted
      ahead of every real measurement. Fixtures: DAVIS lower (lowest retained,
      known worst clamped OUT, with the pre-migration counterfactual
      hand-computed), higher regime (highest retained), the two directions
      disagreeing on ONE pool, missing-score-sorts-worst under BOTH directions,
      absent identity (score draw SKIPPED, recency-only, and *different* from
      the lower result), the `n <= top_k` early return unchanged in all three
      regimes, and `TypeError` when `order` is omitted.
- [x] **The 4 clamp call sites threaded** (main stage loop · boldness retry ·
      causal-correction retry · proposing stage).
- [x] **Node public boundary ACTIVATED (IR-P3-5)** — the proposer joined
      `_decomposed_nodes()` (2 → **3** nodes) with `evidence_rendering.py`;
      `__all__` + `_COMPATIBILITY_REEXPORTS` added following the interpreter's
      precedent. Four structural guards now apply to this node that did not
      before.
- [x] **Raw-reader census: 40 + 12 → 28 + 0.** The helpers module is fully
      typed; the node's remainder is exactly the legacy reader (26) and the
      CLI's two prints — both C3's.
- [x] **Structure (§6)**: `_run_pipeline` **666 → 643 LOC**, branch-ish
      **83 → 83** — did not grow, as required. Node module 2,383 → 2,327;
      `evidence_rendering.py` 205; helpers 777 → 851 (the clamp's absent-order
      branch and the migration docstrings).

**Two defects this commit's guards caught, both worth keeping.**

*The two-carrier divergence, caught by the C0 goldens.* The C0 test helper
updated `interpretation` but not `interpretation_evidence`, so the node read
the PB-3 fixture's evidence while the test believed it was rendering the
full-coverage one — visible as PB-3's candidates and score table appearing
under this module's fixture. It is a small, exact instance of the defect the
whole PR removes: while two carriers of one fact exist they can disagree, and
the disagreement is silent. C3 deletes the raw field, after which this cannot
be written wrongly.

*Fixture rot, caught by the fail-closed projection.* PB-3's fixture (and
`test_score_table_passthrough`'s) carried an ABBREVIATED score table —
`{"rendered_markdown": ...}` with no `rows`/`aggregate`/`s_max_global`/
`reference_source` — a shape `ScoreComparisonTable` forbids and the producer
cannot emit. It survived only because the old path mined the dump with
`.get()` and read one key. Triaged per the Step-00 §19.3 ladder as **fixture
rot: fix the fixture**, and the decisive evidence that it is a repair rather
than a re-baseline is that **all 9 PB-3 goldens are byte-identical afterwards**
— the table never reaches the prompt (`_render_stage_user_prompt` drops it from
the JSON region and `strip_heavy_fields_for_json` strips it from candidates).
The same finding at C0 had already shown a hand-written stub is not a
production-shaped dump; this is the same lesson on an older fixture.

**Test disposition (C2 portion).** 46 `ProposalInput` constructions across 21
files gained `interpretation_evidence=build_proposer_evidence(<same dump>)` —
mechanical, because production builds both from one source. Two files needed
hand work (a conditional-expression argument and an in-function import anchor)
and were reverted and redone rather than patched over. The clamp's callers in
`test_proposal_helpers.py` (10 cases) and `test_prior_stage_truncation.py` (5
call sites) now pass an explicit `HIGHER_ORDER` — the regime those
expectations were always written under — and **all pass unchanged**, which is
the parity half of the F-P3-1 migration. G1 (`test_the_helper_signature_did_not_change`)
RETIRED and replaced in place by `test_the_helper_reads_the_typed_evidence`.

**Validation (C2).**

| command | result |
|---|---|
| `pytest tests/unit/agent/ml_model_proposal_agent tests/unit/nodes tests/unit/agent/protocols -q` | **840 passed** |
| `pytest .../test_step10_p3_c0_baselines.py -q` | **13 passed** — every C0 golden byte-identical across the migration, on BOTH fixtures and both modes |
| `pytest .../test_step00_prompt_goldens.py -q` | **6 passed** — PB-3/PB-4/WF-3 byte-identical |
| `pytest .../test_step10_p3_c2_pipeline_and_clamp.py -q` | **19 passed** |
| `pytest tests/unit/nodes/test_node_public_boundary.py -q` | **23 passed** with the proposer newly inside the decomposed-node set |
| `ruff check` + `ruff format --check` | clean across all touched files |

### 17.6 C3 — COMPLETE (`[x]` with evidence)

One reader remains, and §11.2's acceptance is now true BY CONSTRUCTION: the
dict has no field to read.

- [x] **Legacy adapter** — `render_legacy_interpretation_section(evidence)` in
      the private rendering module; `_build_reasoning_prompt` splices it and
      reads no raw mapping. **IR-P3-6** (below) records why only the
      interpretation REGION moved rather than the whole function.
- [x] **Two DEAD reads deleted** — `per_file_comparison`,
      `efficiency_comparison`. Re-verified at head that
      `InterpretationOutput` declares neither and that **no commit ever added
      one** (`git log -S` over the schema is empty), so both branches were
      unreachable in production. Byte parity unaffected; parent non-goal 7
      authorises repairing a dead read on a line the change already touches.
- [x] **Standalone CLI converged** — `main()` builds evidence with
      `build_proposer_evidence` and prints from it; it constructs no raw dict.
- [x] **`ProposalInput.interpretation` REMOVED**;
      **`.per_model_score_tables` REMOVED**; **`interpretation_evidence` is now
      REQUIRED** — asserted both as a schema flag and behaviourally (a
      construction without it raises).
- [x] **Protocol stops populating both** carriers; its docstring now names the
      typed field.
- [x] **Raw-reader census = ZERO** on both modules, and the census gained the
      STRUCTURAL half of the claim: zero could also mean "nobody happens to
      read it today", so it now also asserts the raw field and the dead mirror
      are gone from the schema and the evidence is required. The 5 plant
      shapes still turn it RED.
- [x] **`scripts/` sweep** — re-verified at head: no script reads
      `ProposalInput.interpretation`, and
      `scripts/render_proposer_prompts_for_audit.py` builds its input THROUGH
      `local_full_context`, so it inherits the projection with no edit. §2.1's
      "they ride the protocol" holds.
- [x] **Convergence proven at the PROMPT boundary** — C1 proved the two
      entrypoints build EQUAL values; equal values could still be rendered by
      two drifting readers. The C3 module renders the legacy prompt from an
      in-memory dump and from a persisted artifact and requires the BYTES to
      match, on both the full-coverage and the legacy fixtures, with an
      anti-vacuity case proving two different dumps render differently.
- [x] **Reachability of the splice** — the adapter's output must appear
      VERBATIM in the assembled prompt. Without it, the node could stop calling
      the adapter and a renderer-only test would stay green: that is exactly
      the P3-V1 incident recorded on this surface (a block wired into one
      branch, never reaching the other).
- [x] **Legacy byte parity** — PB-4, S1-E, `reasoning_prompt_structured_evidence`
      and both C0 legacy goldens unchanged.

**IR-P3-6 — the legacy renderer's INTERPRETATION REGION moved, not the whole
function.**

```text
Question:
  §4.4 says `_build_reasoning_prompt` "becomes a renderer over
  ProposerInterpretationEvidence (relocated to the private rendering module)".
  Moving the WHOLE function is not possible as stated.

Source evidence:
  * the function also renders ProposalInput CONTEXT — hardware, data scope,
    constraints, previous failures, gate exhaustion, trial validity, human
    advice — through `_render_hardware_context_block`,
    `_render_data_scope_block`, `_format_recent_gate_exhaustions_block` and
    `_format_recent_trial_validity_block`, all of which live in the node's MAIN
    module and are also used by `_run_pipeline`;
  * `tests/unit/nodes/test_node_public_boundary.py` rule 3 forbids a private
    submodule from importing its own node's main module — moving the whole
    function would have forced either that import (a cycle) or a much larger
    relocation of shared renderers, in the commit whose stated scope is
    "reader unification only, zero prompt-semantic changes".

Chosen ruling: move the interpretation-derived REGION (contiguous in the
source, and the only part that reads evidence) as
`render_legacy_interpretation_section`; leave input-context assembly in the
node. The split is by OWNERSHIP — evidence rendering vs input-context
sequencing — which is §6's stated criterion and is where the seam already lay.
`_truncate_description` moved with the region (it is only used there) and is
re-exported under its old name for existing importers.

Validation: legacy goldens byte-identical; the boundary test green with the
proposer inside `_decomposed_nodes()`; the splice proven reachable.
```

**A finding worth keeping: the dead reads had a TEST.**
`test_prompt_includes_enriched_interpretation_fields` parametrized
`per_file_comparison` and `efficiency_comparison` and asserted their headings
appear. The test passed — for an input it invented. Because the carrier was
`dict[str, Any]`, a fixture could feed a name the producer has never declared,
so two unreachable branches looked maintained and covered. Both parametrizations
were removed with the branches, with the reason recorded in place, and the fact
stays executable in the C1 module (both names still absent from the producer
schema) and in C3 (a dump carrying them renders nothing, because the typed
value cannot hold an undeclared name). This is the clearest available argument
for the whole PR: a `dict[str, Any]` boundary lets tests certify behaviour that
production cannot reach.

### 17.7 C4 — COMPLETE (`[x]` with evidence)

The proposer is now TOLD the run's metric direction and SHOWN a
direction-correct example. This is the ONLY commit in P3 that intentionally
changes LLM-facing semantics.

- [x] **D1 — the metric-context statement.** `{metric_context_block}` added to
      the COMPARISON and CAUSAL base templates (the two stages that rank or
      author); the PROPOSING stage declares neither placeholder and gets
      nothing, since it does neither. Rendered by
      `render_metric_context_block`, whose direction WORDS come from the
      existing authority chain `render_metric_identity_line` →
      `render_metric_direction_words` → `MetricOrder.direction_words`.
      Absent identity renders the canonical `METRIC_IDENTITY_UNAVAILABLE`
      phrase plus explicit instructions to use no direction language and make
      no ranking claim.
      **IR-P3-3 applied**: the `.id`-reading sibling is used because the frozen
      field type is `MetricIdentityKey`; same sentence, same authority.
- [x] **D2 — the authoring example, rendered per direction.** The template's
      hard-coded `falsifiable_prediction` sub-block became
      `{falsifiable_prediction_example}`. The moves are computed by
      `MetricOrder.toward_better` / `toward_worse`, so the renderer never
      decides which way is up.
      **Backward parity is exact**: under `higher` it reproduces the previous
      literal byte-for-byte (`1.5 → 2.5`, threshold `1.2`), so a TIDMAD-shaped
      run sees the numbers it always saw. Under `lower` it inverts to
      `1.5 → 0.5` with the threshold at `1.8` — **ABOVE** current, the refuted
      side. Absent identity omits the numeric example entirely.
      The `'denoising_score'` literal has left the framework template — the one
      proposer task-science migration §3 authorises, because D2 owns that
      example.
- [x] **D3 — SOTA defined by direction.** A static rule 7 in
      `comparison_stage.md`: SOTA is BEST under the stated direction, not the
      largest number; under a lower metric it is the LOWEST score; and if the
      block says the direction is unavailable, name no SOTA at all. It
      REFERENCES D1's block rather than restating a direction — a static rule
      naming a direction itself would be a second declaration site.
- [x] **`threshold_for_refutation` description corrected** (`proposal.py`) —
      the old wording ("below this value … threshold < current") is correct
      only in the higher regime. Documentation-only and recorded as such: the
      description is NOT sent to the model, since `LLMBridge.generate` attaches
      no schema.

**The exact prompt-byte delta inventory (C3 head → C4 head).** Every LLM-facing
surface was captured on the full-coverage fixture and compared against its
C3-head golden:

| surface | verdict |
|---|---|
| `proposing` system (explore) | **UNCHANGED** |
| `proposing` system (exploit) | **UNCHANGED** |
| `comparison` user | **UNCHANGED** |
| `causal` user | **UNCHANGED** |
| `proposing` user | **UNCHANGED** |
| **legacy** reasoning user | **UNCHANGED** |
| `comparison` system (explore) | changed: +17 / −0 lines — D1 block + D3 rule 7 |
| `comparison` system (exploit) | changed: +17 / −0 lines — D1 block + D3 rule 7 |
| `causal` system (explore) | changed: +11 / −3 lines — D1 block + D2's 4 example lines |
| `causal` system (exploit) | changed: +11 / −3 lines — D1 block + D2's 4 example lines |

**Six surfaces byte-identical, four changed, and every changed line belongs to
D1, D2 or D3** — the diffs were read line by line before the goldens were
regenerated, not after. The same enumeration was repeated on the PB-3 fixture
(which declares NO identity) and shows the same four surfaces changing into the
ABSENCE state: canonical unavailable phrase, zero direction words, numeric
example omitted. 8 goldens regenerated in this commit (4 P3-C0 + 4 PB-3), each
with its diff inspected.

**Three-task grammar fixtures, hand-written.** TIDMAD higher · Pets higher ·
DAVIS **lower** · absent identity. Expected text is written out, never
generated from the renderer — a fixture that asked the code what it produces
would pass for any direction including the wrong one. DAVIS is the falsifier:
every assertion about it is the arithmetic opposite of TIDMAD's on the same
inputs, and a cross-check asserts `predicted` and `threshold` always sit on
OPPOSITE sides of `current` in all three tracks. The absence state is scanned
for six direction words and must contain none.

**Wiring guards.** Each placeholder appears exactly once in each template that
declares it and ZERO times in `proposing_stage.md`; no assembled prompt ships
an unsubstituted `{...}` token (checked on the real captures, both modes,
because `str.replace` ships a typo'd key literally); and the mindset override
does NOT displace either block, since both live above
`{# EXPLORATION_MODE_BLOCK #}` in the base template.

**C-P3-2 re-checked structurally**: an AST scan over the rendering module finds
no comparison of `direction` against `"higher"`/`"lower"` — the renderers ask
`MetricOrder` and never re-read the declaration.

**Validation (C4).** `pytest tests/unit/agent/ml_model_proposal_agent
tests/unit/nodes tests/unit/agent/protocols -q` → **879 passed**;
`ruff check` + `ruff format --check` clean.

### 17.8 Gate-1 readiness packet (written BEFORE launch, per §8.2)

| field | value |
|---|---|
| candidate executable SHA | `dd4a18cbc3a6ce7254b4473bd6d6c2309f3347f5` (C4 head) |
| working tree | CLEAN at packet time (`git status --porcelain` empty) |
| harness | `scripts/step10_p3_gate1.py` |
| command | `./.venv/bin/python scripts/step10_p3_gate1.py --out <evidence_dir>` |
| provider / model | openai / **gpt-5.5** — the Gate-config policy's `openai_tiered_pro.json` model for every proposer role |
| execution shape | the **PREFERRED** shape (§8.2): ONE production-shaped proposer run through the real `MLModelProposalAgent.run()` stage path — comparison → causal → proposing |
| max real calls | **3**, enforced MECHANICALLY: the recording bridge raises `CallCapExceeded` on the 4th boundary crossing, so a retry cannot silently overspend |
| expected wall time | ~2-5 minutes (gate standard's Gate-1 estimate) |
| expected cost | ~$0.05-0.20 |
| evidence written to | `gate1_evidence.json` (verdicts + the decisive fields) and `gate1_calls.json` (every prompt and every response, verbatim) |
| Gate 2 | NOT REQUIRED, NOT RUN. Real training / inference / GPU: NOT RUN |

**Fixture (DAVIS-shaped, lower-is-better).** `metric_identity =
{global_mse, lower}`; three candidates with unambiguous, well-separated
scores: `alpha_net 0.0210` (worst) · `beta_net 0.0172` (**the SOTA**) ·
`gamma_net 0.0186`. Two fixture properties are deliberate and load-bearing:
names are NEUTRAL, so a model cannot score a pass off a name like "best"
instead of the numbers and the stated direction; and the best model is NOT
first in declaration order, so "picked the first" and "picked the best" are
distinguishable outcomes.

**Acceptance A — comparison / SOTA interpretation.** From the PERSISTED
comparison-stage artifact: `sota_model_type == "beta_net"` AND `sota_score`
== 0.0172 AND the worst model was not named. Naming `alpha_net` — the
numerically largest — is the higher-is-better assumption this Gate exists to
detect.

**Acceptance B — causal / prediction authoring.** From the PERSISTED causal
artifact: the `falsifiable_prediction` is schema-valid; `predicted_value <
current_value` (better is LOWER); `threshold_for_refutation > current_value`
(the REFUTED side); and threshold and prediction sit on OPPOSITE sides of
current.

**Deterministic prerequisites, all green at this SHA.**

* `pytest tests/unit/agent/ml_model_proposal_agent tests/unit/nodes
  tests/unit/agent/protocols -q` → **879 passed**;
* C4's three-task grammar fixtures (TIDMAD · Pets · DAVIS · absent identity);
* the C0/PB-3 golden set, with the C4 delta enumerated surface by surface;
* the raw-reader census at ZERO with its five plants;
* the 09a ordering-operand invariant over the extended proposer scope;
* the P2a ordering scanner green and un-widened.

**The evaluators are proven DISCRIMINATIVE before spending a call** — a Gate
whose predicates cannot fail proves nothing. Replayed against hand-written
wrong answers: naming the highest score FAILS A; naming the middle score FAILS
A; a prediction moving UP FAILS B; a threshold BELOW current FAILS B; and the
exact higher-regime copy (up + threshold below) FAILS B on both direction
checks. A stubbed full-harness dry run confirmed the 3-call sequence, that both
artifacts are captured, and that the assembled prompts carry D1's
"(lower is better)" and D2's downward example — so a real failure will be the
model's behaviour, not the harness's.

**Failure taxonomy (frozen).** A wrong model behaviour on either surface is a
REAL Gate FAILURE — never a flake, never a blind rerun. The disposition is to
diagnose the grammar, make the smallest contract-preserving correction, and
treat that correction as a NEW candidate with its own bounded Gate. Only a
genuine provider/network/API failure that produced no trustworthy behavioural
result may be INCONCLUSIVE, and that permits ONE bounded rerun on the UNCHANGED
candidate. A harness or code fault is a FAIL, not an INCONCLUSIVE.

### 17.9 Gate 1 — TWO candidates, verdict **PASS** on the second

Both runs used the PREFERRED shape: one production-shaped proposer run through
the real `MLModelProposalAgent.run()` path, comparison → causal → proposing,
**3 real calls each**, gpt-5.5, verdicts read from the PERSISTED stage
artifacts. Total real LLM calls spent on P3: **6** (2 candidates × 3).

#### Attempt 1 — candidate `b94b2da1` — **FAIL** (real model behaviour)

Evidence: `/home/klz/Data/SIDEREIS_DATA/step10_p3_gate1/20260820_232456/`
(`gate1_evidence.json`, `gate1_calls.json`). Wall time 160 s.

| surface | verdict | what the model did |
|---|---|---|
| **A — comparison / SOTA** | **PASS** | named `beta_net` (0.0172, the LOWEST) as SOTA under the lower-is-better metric, with the matching score, and did NOT name the numerically largest. **D1 and D3 work on a real model.** |
| **B — causal / authoring** | **FAIL** | `current 0.0172 → predicted 0.0159` — the RIGHT direction, so D2's rendered example was read and followed — but `threshold_for_refutation = 0.0170`, BETWEEN the prediction and the current value instead of on the refuted side |

Classified a **REAL model-behaviour failure**, not a flake: no blind rerun.

**Diagnosis (from the persisted prompt, not from guessing).** The causal system
prompt was inspected and the D2 example had rendered CORRECTLY —
`1.5 → 0.5, threshold 1.8`, above current. So the example was not the gap. The
model's own rationale shows a coherent alternative reading of the FIELD NAME:
the threshold as "the minimum improvement I must achieve, or I was wrong". That
is a sensible reading; it is simply not this system's, which is that the
threshold marks the REFUTED side of `current_value`.

**The gap was an under-implemented frozen design item, not a design error.**
§4.5's D2 requires "one sentence aligns the wording with the unchanged v2
evaluator". C4 implemented D2's NUMBERS and omitted its SENTENCE. Three numbers
in a JSON block do not teach a semantic — nothing in the prompt said what the
field means.

**Correction (smallest contract-preserving, `70a9bd96`).** The aligning sentence
now renders in the metric-context block, because prose cannot live inside a JSON
example and both are C4 surfaces, so NO new LLM-facing surface is created. It
uses only the direction authority's own words — `antonym` for the refuted side,
`comparative` for what confirms — so it reads "put it on the **higher** side"
under `lower` and "**lower** side" under `higher`. It also names the WRONG
reading explicitly, because a capable model actually reached for it. Two
deterministic tests pin it in both regimes plus an inversion check; the delta was
re-enumerated and the same six surfaces stayed byte-identical.

#### Attempt 2 — candidate `70a9bd9677c9291f7f72db761b51c755115d95c9` — **PASS**

Evidence:
`/home/klz/Data/SIDEREIS_DATA/step10_p3_gate1/20260820_233103_candidate2/`.
Wall time 139 s, 3/3 calls, `run_error: null`.

| surface | verdict | evidence |
|---|---|---|
| **A — comparison / SOTA** | **PASS** | `sota_model_type = "beta_net"`, `sota_score = 0.0172` — the LOWEST of `{alpha 0.0210, beta 0.0172, gamma 0.0186}`; the worst model was not named |
| **B — causal / authoring** | **PASS** | schema-valid; `current 0.0172 → predicted 0.0159` (toward BETTER = LOWER); `threshold_for_refutation = 0.0181` — **ABOVE** current, the refuted side; all four checks true |

The model's rationale reasons explicitly in the metric's own terms ("a reduction
from 0.0172 to 0.0159 is a ~7.6% improvement"), which is the behaviour D1/D2
exist to produce.

**Why this PASS is informative rather than tautological.** Same model, same
fixture, same harness; the ONLY change was the aligning sentence, and the one
failing check flipped. The evaluators were proven discriminative BEFORE any call
was spent (naming the highest or the middle score fails A; an upward prediction,
a threshold below current, or the exact higher-regime copy fails B), and the
first attempt is a live demonstration that acceptance B can fail on a real
model. A Gate that had only ever returned PASS would not have shown that.

**Gate 2: NOT REQUIRED, NOT RUN.** Real training, real inference, GPU: **NOT
RUN** — P3 changes no training/runtime scientific behaviour.

### 17.10 C5 — closure

**Node `.md` synced** (`nodes/ml_model_proposal_agent/ml_model_proposal_agent.md`),
with every documented claim quoted against merged source rather than asserted:
`interpretation_evidence` REQUIRED = True · `interpretation` absent = True ·
`per_model_score_tables` absent = True · evidence field count = 30 ·
`{metric_context_block}` present once in `comparison_stage.md` and
`causal_reasoning_stage.md` and ZERO times in `proposing_stage.md`. The input
table now documents the typed contract and its projection authority; the
per-model-score-tables mirror row is deleted; the CLI and Python-API examples
show `build_proposer_evidence`; and four Key-behavioral-notes entries record the
one-reader architecture, the node's decomposition, the D1/D2/D3 direction
grammar (including the absence state and the legacy path carrying none of it),
and why secondary metrics are not proposer evidence.

**Standing guards at head.**

| guard | state |
|---|---|
| raw-reader census over both proposer modules | **0 + 0**, with 5 plant shapes proven RED and a precision case proving unrelated mapping reads are not counted |
| the raw carrier itself | GONE — `ProposalInput` has no `interpretation` and no `per_model_score_tables`; `interpretation_evidence` is REQUIRED |
| ONE projection authority | `build_proposer_evidence` and `ProposerInterpretationEvidence` each defined exactly once across six production directories; plant proves the scan reports a second |
| 09a ordering-operand invariant | green over the extended proposer scope, with the live on-disk plant recorded in §17.3 |
| P2a ordering scanner | green and **NOT widened** (Q-P3-4); its docstring records the F-P3-1 blind spot |
| node public boundary | green with the proposer newly inside `_decomposed_nodes()` (2 → 3) |
| Q-P3-3 secondary negative fixture | green, with the anti-vacuity probe proving the tokens ARE upstream |
| C4 diff-surface enumeration | 6 surfaces byte-identical, 4 changed, every changed line D1/D2/D3 |

**Ordering closure (C-P3-2).** New ordering semantics: **ZERO**. New ordering
authorities: **ZERO**. New metric-direction derivation authorities: **ZERO** —
re-checked structurally by an AST scan over the rendering module for any
comparison of `direction` against `"higher"`/`"lower"`. ONE already-existing
site was MIGRATED (F-P3-1). `MetricOrder`, the reconciliation authority, the
`top_n` comparison and the P2a scanner's precision contract are all unchanged.

**P3/P5 boundary held.** Zero `ChainState` fields, zero digest readers, zero
restore paths, zero `accumulated_key_findings` or `vocab_link_confirmations`
lifecycle. The evidence value is built per invocation.

### 17.11 Validation provenance — two gaps closed (operator review, 2026-08-21)

The operator's review of this ledger accepted the P3 implementation and its
validation quality, and named two provenance gaps. Both were defects in what
this ledger RECORDED, not in what was run — which is exactly the kind of gap
worth closing, because a claim nobody can re-derive from the document is not
evidence.

#### Gap 1 — the readiness packet names `dd4a18cb`; Gate attempt 1 is recorded as `b94b2da1`

§17.8 pins the candidate as the C4 head `dd4a18cb`; §17.9 records attempt 1 as
`b94b2da1`. Those are two different SHAs, so "the packet validated candidate A
and the Gate ran candidate B" was a fair challenge. **The executable trees are
identical**, proven by git tree hashes rather than by inspection:

```text
git diff --name-only dd4a18cb b94b2da1
  docs/.../pr_10_p3_proposer_typed_evidence.md      (this ledger)
  scripts/step10_p3_gate1.py                        (the Gate harness itself)

git diff --stat dd4a18cb b94b2da1 -- agent/ nodes/ workflows/ core/ \
                                     execute_tools/ ml_models/ configs/
  (empty)

per-directory tree hashes, dd4a18cb vs b94b2da1:
  agent           IDENTICAL  6e898bed3b63769481b3adc88ba300522f26542c
  nodes           IDENTICAL  adfdbaa313399ba8a57cb6429579ba930725f3cc
  workflows       IDENTICAL  a2c2a9c60a96b728d96fcfece6be6c6bd86d2089
  core            IDENTICAL  06cef3085fd34672ec3bff22305ec2c3ac878bb6
  execute_tools   IDENTICAL  49e2170f1a89bfd23b0045bfb21e54853ec688aa
  ml_models       IDENTICAL  aa82a6898e342880c4702d5f0dc0d009458b3abc
  configs         IDENTICAL  7a4c8dc1f4b740b0b3a6ae2c02ebc260bc7dbc3b
```

The only non-doc file added between them is the Gate harness, which no
production module imports. So `b94b2da1` IS the packet's candidate plus the
instrument used to measure it. **Ruling for future packets: pin the candidate
SHA at the commit the Gate actually runs from, or state the tree-identity proof
in the packet itself.** §17.8's row should be read as "executable candidate
`dd4a18cb` ≡ run SHA `b94b2da1`".

#### Gap 2 — candidate 2's deterministic prerequisites, with exact-SHA provenance

The frozen taxonomy requires: correction → NEW candidate → deterministic
validation → its own bounded Gate. The validation WAS run before attempt 2, but
§17.9 described its content without giving a command, a count or a SHA. Closed
by re-running it against a named commit rather than against a remembered tree:

```text
tree under test: 6cc945a5765c8b6d5a5a2e791552e2a8510fbd9c

git diff --name-only 70a9bd96 HEAD -- '*.py'                  -> EMPTY
git diff --name-only 70a9bd96 HEAD -- 'agent/prompt_templates/**' -> EMPTY
git diff --name-only 70a9bd96 HEAD
  docs/.../pr_10_p3_proposer_typed_evidence.md
  nodes/ml_model_proposal_agent/ml_model_proposal_agent.md

pytest tests/unit/agent/ml_model_proposal_agent \
       tests/unit/nodes \
       tests/unit/agent/protocols \
       tests/unit/execute_tools/test_step10_p2a_c0_ordering_scanner.py \
       tests/unit/agent/result_interpretation_agent/test_step09a_c6_evidence_projection.py -q
  -> 947 passed in 30.11s, exit 0
```

**ZERO Python and ZERO prompt-template bytes differ between Gate candidate
`70a9bd96` and this tree**, so the 947 are exact-candidate evidence, not
approximate. The suite covers every owner of the single prompt delta that
distinguishes candidate 2 from candidate 1: the C4 grammar module (both
regimes plus the inversion check), the C0/PB-3 golden set that pins the
unchanged surfaces, the raw-reader census, the P2a ordering scanner and the
09a ordering-operand invariant.

(The earlier 881-passed run recorded in §17.7 was executed on the working tree
that BECAME `70a9bd96`, with no edits between it and the commit. That is true
but not re-derivable from this document, which is the whole point of the gap —
the 947 above supersede it as the citable evidence.)

#### Gap 3 — terminal exact-head CI

Open by construction at the time of the operator's review, and recorded in
§17.12 below once the final head is settled. Local `pyright` cannot run on this
host (the vendored pyright fails on its Node runtime), so the type check is
owned exclusively by that CI run — which is precisely why it is the gating
artifact and not a formality.

### 17.12 Adversarial debt review (operator-requested, 2026-08-21)

Two independent reviewers audited the whole diff against `c5f95ff0` — one on
production design, one on test architecture — with the brief: *did P3 introduce
new technical debt, or solve things in hacky ways?* A broad local sweep
(`tests/unit`, 9,435 passed) ran alongside. Between them they found **three
live test failures on the branch** and a set of real design and test defects.
Everything actionable was fixed; nothing was argued away.

#### Three failures the targeted validation missed

| failure | cause | disposition |
|---|---|---|
| `test_step09_5a_c0_oracle.py` RED | **C3 removed two `ProposalInput` fields and never applied the declared delta the C1 docstring had promised.** C3's validation ran the proposer, nodes and protocol suites only, so the file stayed red through three later commits | Re-baselined per the oracle's own protocol: delta MEASURED first (**exactly two REMOVED keys**, zero changed, zero added), then declared in its docstring — including *how* it was missed |
| `test_step09b_c4_prediction_rendering.py::test_the_proposer_calls_the_same_renderer` RED | the guard pinned the FILE (`ml_model_proposal_agent.py`); C3 relocated the track-record call into the node-private module | Guard re-pointed at the node PACKAGE. Pinning a file made a pure relocation look like a regression |
| `test_step06_c5_boundary_and_structure.py` RED | **the Gate harness itself executed `"lower"` twice.** `scripts/` is production-scanned, so a hand-typed direction there is a third direction authority — the exact defect Step 06's C5 guard exists to catch | Harness rewired to read its identity from the REAL DAVIS pack declaration (`examples/davis_future_prediction/declared/metric_mse.json`) through `metric_spec_from_declaration`, the same route `run_davis_gate2.py` takes. Direction now lives in DATA. It also made "DAVIS-shaped" literally true, and the acceptance checks now ask `MetricOrder` instead of hardcoding `<`/`>` |

The lesson is recorded in the oracle's docstring rather than only here: **targeted
validation must include the guards a change is KNOWN to move.** C1's own
docstring named the C3 delta one paragraph above the test that then went red.

#### Production findings fixed

* **The no-identity authoring example taught a type error.** It put prose in
  three `float`-typed slots (`"current_value": "<the SOTA's current value>"`).
  The with-identity example uses numbers *precisely because* a model copies the
  shape it is shown — and Gate 1 demonstrated that on this population — so the
  same hazard pointed the other way would have produced string-valued
  predictions, `ValidationError`, and burnt causal-correction retries in the
  degraded regime. Placeholders now read `REPLACE WITH A NUMBER (not a string)`.
* **D3's rule contradicted the stage's mandatory output format.** "Do not name a
  SOTA at all" against an output contract that declares `sota_model_type` /
  `sota_score` unconditionally left the model to invent a resolution — omit,
  null, or apologise — and whatever it chose rode into every later stage. The
  rule now names the exact shape: emit both keys as `null` and explain in
  `sota_mechanism`.
* **The clamp's `order is None` branch was a smell** (independently flagged by
  the reviewer and by self-review): a `_rank` that raised
  `AssertionError("unreachable")` purely to bind a name, a `captured_order`
  alias that existed only to narrow a type, and `MetricOrder.rank` called
  *inside* a sort key — O(n² log n) in the comparison pool. Replaced by
  `_ranks_by_order`, which returns `None` for "no ranking happened" and
  otherwise computes the rank map ONCE, shared by Draw A and the truncation so
  they cannot disagree. All 74 clamp/truncation tests green unchanged.
* **`_ABSENCE_IS_NONE` was dead code carrying a false claim** — zero references,
  and its comment asserted `model_types`/`model_descriptions` are treated
  identically when absent or empty, which `build_interpretation_summary`
  contradicts. Deleted.
* **The evidence-dump round-trip trap is now named** in
  `build_proposer_evidence`: an interpretation spells the identity
  `{metric_id, direction}` while `MetricIdentityKey` dumps `{id, direction}`, so
  feeding an evidence dump back in would silently yield `metric_identity=None`.
  No caller does this; the docstring means the first one who tries finds the
  answer instead of the symptom.

#### Test findings fixed

* **An anti-vacuity test that tested nothing.** The one-authority plant
  re-implemented the scan inline and asserted ONE hit — it could not fail unless
  `ast` broke. `_definitions_in` is now injectable, the plant runs through the
  REAL scan over real production sources, both symbols are covered, and a file
  that fails to parse is a hard failure instead of a silent skip (a skip is how
  a census reports "one owner" having never looked).
* **The serializer "oracle" was not independent.** It iterated
  `INTERPRETATION_SUMMARY_KEYS` — the constant the code under test iterates — so
  a dropped, added or reordered key would have moved both sides together and the
  key-order assertion could never fire. The 18 keys are now transcribed from the
  pre-P3 source, with a separate test pinning the production constant against
  the transcription so the two failure modes read differently.
* **Docstring overclaims corrected**, because a sentence a future reader trusts
  is itself a liability: the census now states plainly that it is name-shaped
  and cannot see an alias (and that the structural half is what closes that
  hole); the C4 structural check is renamed to what it actually owns, pointing
  at Step 06's C5 guard for the broad claim; the `model_types` divergence is
  labelled a DECLARED delta rather than falsely "covered by the differential";
  and a triple-asserted "the field is required" lost its schema read-back.

#### Recorded, not fixed — carried debt

**The typed migration stops one layer deep.** `accumulated` and `candidates`
remain plain dicts keyed by strings, so `select_candidate_models` re-serializes
`ScoreComparisonTable` back to a dict and `_jsonable` sniffs `model_dump`. This
is deliberate and documented in `evidence_rendering.py`: those shapes are
golden-pinned prompt bytes and the downstream helpers dispatch on
`isinstance(x, dict)`. But it means "one typed value" is true at the DECLARATION
boundary and not yet through the consumption plumbing, and a future evidence
field still travels the last hop as a string key. **Carried to Step 12** with
the rest of the composition work; recorded here so nobody reads §17 and
concludes the migration is finished.

Three smaller items were judged not worth churning this PR further and are
recorded so they are findings rather than surprises:

* **The proposer test harness has outgrown "a test module".** Five P3 modules
  import fixtures and private recorders from `test_step00_prompt_goldens.py`
  through `test_step10_p3_c0_baselines.py`, and one `parametrize` calls a
  dataset-config-touching fixture at COLLECTION time. It works, and the
  coupling is honest, but a rename in `step00` now breaks six files and a
  dataset-config fault becomes a collection error in five. The shared harness
  belongs in `tests/helpers/` beside `golden.py`. Maintenance debt, not
  correctness.
* **`evidence_order` lives in `nodes/proposal_helpers.py`** — outside the node
  package, so the node-boundary rule cannot govern it — while its natural
  siblings are in the node-private rendering module, and the two C4 renderers
  construct `MetricOrder(identity)` inline rather than through it. No direction
  can diverge (all three read the same validated identity from the same typed
  value), but "the one function that turns evidence into an order" is not quite
  what the code says. `proposal_helpers`' location is pre-existing structure
  debt; P3 grew it slightly rather than shrinking it.
* **The legacy path deliberately gets none of D1/D2/D3.** So legacy-mode runs
  still author with no stated direction. That is the frozen §4.5 decision —
  legacy authors no prediction at all and its byte parity is the compatibility
  value §11.2 protects — and it is documented in the node's `.md`. Named here
  too, because "fixed in pipeline mode, preserved in legacy mode" should be an
  accepted asymmetry rather than an assumed one.

### 17.13 Gate 1 — re-run on the FINAL head after the review fixes

The adversarial-review fixes moved two things the Gate depends on: D3's rule 7
was reworded (it is IN the comparison prompt the Gate exercises), and the
harness itself was rewired to read its identity from the DAVIS pack declaration
instead of a hand-typed direction. Under the exact-head rule the attempt-2
evidence therefore no longer covers the shipped code, so the Gate was run again
rather than carried forward.

| field | value |
|---|---|
| candidate | **`5311a25a7678be61ce8526e7065f2c0ff049e927`** — the final executable head |
| calls | **3 / 3** (comparison → causal → proposing), `run_error: null` |
| wall time | 154 s |
| model | gpt-5.5 |
| identity | **`mse`, `lower`** — read from `examples/davis_future_prediction/declared/metric_mse.json`, so the Gate now runs the identity DAVIS actually ships |
| evidence | `/home/klz/Data/SIDEREIS_DATA/step10_p3_gate1/20260821_000807_candidate3_final/` |

| surface | verdict | evidence |
|---|---|---|
| **A — comparison / SOTA** | **PASS** | `sota_model_type = "beta_net"`, `sota_score = 0.0172` — the LOWEST of `{alpha 0.0210, beta 0.0172, gamma 0.0186}`, chosen on the stated direction rather than on magnitude, with neutral names and the best model deliberately not first in declaration order |
| **B — causal / authoring** | **PASS** | schema-valid; `0.0172 → 0.0159` (toward BETTER = LOWER); `threshold_for_refutation = 0.0182` — on the REFUTED side; all four checks true, and the two direction checks now ask `MetricOrder` rather than hardcoding `<` / `>` |

**Total real LLM spend for P3: 9 calls** across three candidates (3 × 3), of
which one candidate genuinely FAILED and was corrected rather than re-run. The
Gate contract's `≤ 3 calls per candidate` held throughout, mechanically.

### 17.14 Terminal exact-head CI

The first PR CI (run **32455095534**, head `6cc945a5`) is retained as evidence
rather than hidden, because it is informative: **lint PASS · ruff-format PASS ·
pyright PASS**, and unit failed on **exactly the three tests** the adversarial
review and the broad local sweep had independently identified — 3 failed /
11,432 passed. It is the run that proves the type check this host cannot
perform is green on P3's code, and that nothing beyond those three was wrong.

**Canonical terminal run: CI `32457848717`, tested SHA
`31cdabaa3d720c1b796bb20202700bd309664eb9` — SUCCESS.** lint PASS · ruff-format PASS · **pyright PASS** ·
unit PASS. Tested SHA == final PR HEAD, verified rather than assumed. The
verdict was read from the job log, not from a wrapper's exit status.

Recorded here AFTER the merge on purpose: writing it before would have required
a trailing commit that moves the head it is trying to certify, which is the
self-referential SHA chase the validation rules forbid.

**Merged**: PR #245, squash `254cbaa1466125873d6c7a72f59a7d25fd2c5619`; merged master verified byte-identical
to the validated head `31cdabaa3d720c1b796bb20202700bd309664eb9`.
