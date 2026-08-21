# Step 10 / P3 — Proposer Typed Evidence + Prediction Authoring

## 0. Status

**REVISION 2 — POST-P2a/P2b RECONCILIATION COMPLETE. NOT FROZEN.
READY FOR OPERATOR FREEZE. IMPLEMENTATION NOT STARTED.**

Revision 2 supersedes DRAFT rev 1 (`2b59235f`, architecture-review PASSED
2026-08-20). Every `PROVISIONAL(P2a)` / `PROVISIONAL(P2b)` marker is resolved
against merged source; §13 is the full reconciliation table. Three findings
of this reconciliation changed the design materially and are flagged here so
the freeze review reads them first:

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
   the WORST models' evidence into later-stage prompts. Disposition is
   operator question Q-P3-4.

| field | value |
|---|---|
| parent | Step-10 parent REVISION 2 (FROZEN), §3.6 / §11 / §11.2 (ruling FROZEN) / §11.3 / §20.6 / §22.1; owns scope item **S4** |
| source anchor | merged `master` = **`06291e5f`** (post-P2b status sync; production tree == the P2b squash `5a2ecfd1`). Every §2 line anchor was measured here in this session. Line anchors are evidence, not implementation authority |
| depends on | **P2a MERGED** (`e094fa26` — ordering closed; the C4 threading note addressed to P3 is in source at `proposal_helpers.py:36-43`) and **P2b MERGED** (`5a2ecfd1` — secondaries real; **its diff touches ZERO proposer files**, verified §2.4) — **both satisfied** |
| downstream | **P5** consumes the typed boundary this child creates (its consumer wiring is `PROVISIONAL(P3)` on its side; P5 freezes AFTER P3 merges); **P6** runs the loop through it |
| Gate disposition | **Gate 1 REQUIRED — ONE bounded run (≤ 3 real calls)** on the intentional authoring-grammar delta, standard row quoted in §8.2. **Gate 2 NOT REQUIRED** (§8.3). Both rulings source-grounded in this revision; confirmed at freeze |
| open operator questions | **3** (§14): Q-P3-2 Gate-1 confirmation · Q-P3-3 secondary consumption · Q-P3-4 F-P3-1 inclusion — each with a measured recommendation. Q-P3-1 is RESOLVED BY SOURCE |

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

Disposition: **Q-P3-4** (§14) — recommended INCLUDE in P3, bounded, because
the fix's mechanism IS P3's typed evidence (the same identity, through the
same reader, with the Q-P2a-1 absence rule), and the file is P3's own
primary surface. The scanner itself is NOT extended (its one-hop precision
contract is deliberate and stays); the site's standing guard is a
DAVIS-lower behavioral fixture (§7 C2), and the blind-spot class is recorded
in the scanner's docstring per the F-P2b-4 rule (per-census, when touched).

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
| clamp draw `:521,:555` | `best_score` descending | order-aware retention from the typed identity; absent ⇒ recency-only (Q-P2a-1 shape) | Q-P3-4 (C2 if approved) |

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
| secondary production/evaluation/persistence/rendering | **P2b (merged) / 09b** | consumes at most (Q-P3-3: recommended NOT consumed) |
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
`per_model_secondary_metrics` (Q-P3-3 — a RESERVED name documented in the
model's docstring, the 09a reserved-names precedent P2b itself consumed;
adding it later is one field + one renderer behind the single reader, which
is §11.2 rule 4 working as designed); `is_degraded`, `evolution_stats`,
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

### 4.6 Secondary evidence — the explicit decision (Q-P3-3)

**Recommended: the proposer does NOT consume secondary evidence in P3; the
typed value documents `per_model_secondary_metrics` as a RESERVED name.**
Grounds, all measured:

* P2b's operator-approved planner rationale (§2.4) names the exact hazard —
  a second, differently-directed number beside the optimised one invites a
  trade-off, "exactly the vote secondaries must never get" — and the
  comparison stage (which picks the SOTA to build on) is the
  optimization-adjacent surface where that temptation would land.
* The interpreter ALREADY synthesizes secondary observations into
  `key_findings` / `take_home_message` (it renders all three secondary
  states since 09b/P2b), and those channels ARE projected — the proposer
  receives secondary-informed science without raw differently-directed
  numbers.
* Every typed field requires a demonstrated consumer; today there is none,
  and inventing a rendering to justify a field is the producer-copy failure
  mode this design's own §3 forbids.

If the operator rules CONSUME instead, the frozen shape is pre-declared so
the ruling is cheap: the field `per_model_secondary_metrics:
dict[str, list[SecondaryMetricEvidence]]` (default `{}`), projected only
when the dump carries entries; rendered ONLY by 09b's
`render_secondary_metrics` (all three states, each metric's OWN direction,
never the primary's); crash diagnostics stay excluded (they project as
`unavailable` upstream and P3 adds no crash channel); zero ordering
participation, guarded by the C0-extended invariant either way.

**Either way, the invariant scope-extension and the DAVIS negative
assertion (§5) land**: under the recommendation, the three-task fixture
asserts secondaries EXIST upstream and appear NOWHERE in proposer evidence
or prompt bytes.

### 4.7 F-P3-1 — the clamp fix (Q-P3-4, recommended IN)

If included: `clamp_and_backstop_accumulated` and
`clamp_comparative_analysis` gain a keyword-only `order: MetricOrder | None`
supplied by `_run_pipeline` from the typed evidence (the same identity the
`top_n` cut reads). Draw A becomes "the 3 BEST by `order`"; `_score`'s
missing-value sentinel becomes `order.worst_sentinel`; the final-truncation
sort keys follow the same order. `order is None` (absent identity) ⇒ the
score draw is SKIPPED and retention is recency-only — the Q-P2a-1 shape:
no metric ranking happens without identity, and nothing is labelled "best".
Ties and the recency draw are direction-independent and preserved
byte-for-byte. Standing guard: hand-computed DAVIS-lower and TIDMAD-higher
retention fixtures plus an absent-identity fixture (§7 C2); the P2a scanner
is deliberately NOT extended (§2.7.1).

If excluded by ruling: the site is recorded as named Step-10 direction debt
in the parent's §0 debt list at P3's post-merge sync, with this section as
the audit of record.

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
| clamp retention (if Q-P3-4 IN) | best-3 = highest | highest | **best-3 = LOWEST mse; the worst model's entry is clamped OUT — hand-computed** | YES |
| `top_n` cut (P2a, pinned) | unchanged bytes | unchanged | unchanged (already direction-aware) | YES |
| secondaries upstream (P2b) | none | `macro_f1` | `psnr` (higher) + `mae` (lower) | evidence + prompt bytes contain ZERO of them (Q-P3-3 recommendation) — the NEGATIVE assertion, asserted on the DAVIS fixture where the temptation is real |
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

### C2 — pipeline reader onto the typed value (+ helpers, + health block, + Q-P3-4)

**1. Goal.** The production path consumes the typed value; the whitelist
finally gets its pin; the P2a threading is replaced by the mechanism its
docstring requested.

**2. Scope.** `_run_pipeline`'s evidence assembly; the new private rendering
module (serializer + health block move); `proposal_helpers.py`
(`select_candidate_models`, `resolve_exploration_mode` typed;
`_interpretation_order` DELETED; `_guess_source` drops its unused parameter
in passing; clamp per Q-P3-4's ruling); `run()`'s print. Depends on C1.

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
- [ ] Q-P3-4 (if IN): the clamp order-parameter per §4.7 with the
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
DAVIS clamp fixture proves the worst model's entry is clamped OUT (if
Q-P3-4 IN); `_run_pipeline` LOC/branch count did not grow (measured, in the
ledger).

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
- [ ] **Gate 1 (operator-approved before launch)**: ONE bounded run, ≤ 3
      real calls — the causal stage on a DAVIS-shaped `lower` fixture and a
      TIDMAD-shaped `higher` fixture (+ one absence call if budget allows).
      PASS = schema-valid `FalsifiablePrediction` whose `predicted_value`
      lies toward-better of `current_value` under the fixture's direction
      and whose threshold lies on the refuted side; the absence call uses no
      direction language. Verdict read from persisted artifacts.
- [ ] Node `.md` sync quoting each documented flag/default against merged
      source; ledger closed (all checklists evidenced).
- [ ] Push ONCE; the formal PR's automatic CI on the final head is the ONE
      canonical run; verdict from the log.

**4-5. Validation / acceptance.** All prior commits' targeted suites green
at head (recorded per commit, not re-run wholesale); Gate 1 PASS recorded
with call count and artifact paths; CI run id + SHA in the ledger.

**6. Failure/edge cases.** A Gate model that ignores the grammar under
`lower` is a REAL finding (prompt insufficiency), not a test flake — the
disposition is a grammar revision + re-run, recorded, never a pass-by-rerun.

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

### 8.2 Gate 1 — REQUIRED (ONE bounded run; Q-P3-2 confirms at freeze)

The standard's assignment rows
(`docs/gates/gate_testing_standard.md` "Gate assignment by commit type"):
*"Prompt placeholder substitution → Unit only + optional Gate 1"* and *"New
LLM-facing system prompt → Gate 1"*. C4 is between the rows: not a new
system prompt, but more than mechanical substitution — it changes the
INSTRUCTIONAL semantics that steer prediction authoring, and the failure
class "a real model follows lower-is-better authoring instructions" is
LLM-behavioral: deterministic fixtures prove the instructions are correct,
not that a model obeys them. No prior proposer Gate has ever run a `lower`
regime; the parent pre-named P3 "the child most likely to require Gate 1"
(§22, §22.1), and 09b's five-call Gate on the interpreter's
direction-correct reading is the precedent on the consuming side. Ruling:
**the optional Gate is EXERCISED — ONE bounded run, ≤ 3 calls, C5's plan.**
Everything outside D1/D2/D3 is parity-owned and gets no Gate.

### 8.3 Gate 2 — NOT REQUIRED

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
its P2a fixtures untouched; `MetricOrder` and the reconciliation authority
untouched (P3 adds ZERO ordering/derivation sites — the P2a scanner stays
green over P3's whole diff); the frozen D1 record names untouched; no
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
| dump with secondaries present | projected NOWHERE (Q-P3-3 rec.); prompt bytes free of them — asserted |
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
| Gate-1 model disobeys the lower grammar | a real finding → grammar revision + re-run, recorded (C5); never re-run-to-green |
| P5 lands a competing consumer path | freeze ordering (P5 after P3) + §9's mirror statement |
| F-P3-1 ruled OUT and forgotten | §4.7's else-branch: named debt in the parent §0 at the post-merge sync, with §2.7.1 as the audit of record |

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

---

## 14. Open operator questions (each with a measured recommendation)

| id | question | recommendation |
|---|---|---|
| **Q-P3-2** | Confirm the Gate-1 ruling: ONE bounded real-LLM run (≤ 3 calls) on the D1/D2 authoring surface — or deterministic rendering fixtures alone? | **REQUIRED** — §8.2's grounds: the standard's optional-Gate row exercised because instruction-following under a `lower` regime is LLM-behavioral and has never been exercised by any prior proposer Gate; the parent pre-named this child for it |
| **Q-P3-3** | Does proposer-facing evidence include P2b's secondary observations at all? | **NO for P3** — P2b's planner-exposure rationale applies to the SOTA-choosing stage; the interpreter's findings channel already carries secondary-informed science; reserved-name extension point declared so a future YES is one field behind one reader (§4.6). The negative assertion + invariant scope-extension land either way |
| **Q-P3-4** | Is F-P3-1 (the clamp's descending retention draw) fixed inside P3, or recorded as named Step-10 direction debt? | **INCLUDE, bounded** — parent acceptance criterion **J** ("every direction-sensitive golden-metric decision consumes `MetricOrder`; … zero unmigrated sites") cannot close for Step 10 with a known unmigrated site left as debt; the fix's mechanism is P3's own typed identity on P3's own file, with Q-P2a-1's absence rule; excluding it ships DAVIS evidence curation inverted through P5/P6 development. The D-P2a-1 precedent (newly-measured sites absorbed into the already-approved direction scope) applies (§4.7) |

Q-P3-1 (rev 1) is RESOLVED BY SOURCE (§0 item 1) and is not an operator
question.

---

## 15. Adversarial self-review

| attack | answer |
|---|---|
| A proposer path still bypasses the projection? | After C3 the raw field does not exist; the CLI calls the same function; census + plant stand guard; no other production module reads `ProposalInput.interpretation` (measured §2.1) |
| Production and standalone read the same artifact differently? | One function, one Mapping input shape, equality-tested on identical bytes from C1; the persisted artifact IS `model_dump_json` (§4.2) |
| Lower-is-better becomes higher through wording? | D1 states direction from the ONE wording authority; D2's DAVIS fixture falsifies an upward example; the §2.6 vocabulary audit classifies every remaining "best/improve" as direction-safe |
| A secondary influences ranking? | none is projected (Q-P3-3 rec.); the ordering-operand invariant is scope-extended to the proposer files with a live plant; under a future YES the same invariant already covers the surface |
| A secondary inherits the primary direction? | no secondary renders in P3; the pre-declared future shape mandates `render_secondary_metrics`, which asks each spec's OWN order (09b, unchanged) |
| Direction re-derived from a name/sign/task? | the ONLY identity source is `metric_identity_from_mapping` over the digest's provenance; zero new `MetricOrder` construction sites outside the evidence path; the P2a scanner stays green over the whole diff |
| Unavailable/refused presented as scored? | absent identity renders the canonical phrase and suppresses examples/ranking (D1/D2 absence states; `top_n`/clamp fallbacks); the projection never fabricates a value for an absent key (None rule) |
| A crash diagnostic masquerades as science? | no crash carrier is projected (§4.1's exclusion list; secondary errors excluded with Q-P3-3) |
| Raw `InterpretationOutput` leaks past the boundary? | the value embeds only declared fields; the protocol passes the dump ONLY into `build_proposer_evidence`; a whole-object field would fail §4.1's non-goal review trigger and the census |
| The schema mirrors the producer and defines no boundary? | 30 carried / 12 refused / 2 dead-dropped, each refusal named with a reason (§4.1) — the asymmetry is the boundary |
| P3 implemented P5 lifecycle? | zero carrier/digest/restore/ChainState changes (§9; §10's invariant list) |
| P3 widened Step-12 composition/package semantics? | zero composition-root, manifest, or task-package edits; the task-science prompt content byte-preserved and its ownership left with the roadmap's Step-10/12 line (§1, §3) |
| Tests green for the wrong reason? | the whitelist finally gets a FULL-coverage golden (the parent measured 8/18 keys and zero prediction keys pinned today); the C0 plant/mutation steps prove each census can go RED; the clamp's guard is behavioral because the AST census provably cannot see the site (§2.7.1) |
| The intermediate states are incoherent? | C1's dual-population state is the ONE declared intermediate, closed by C2/C3 inside the same PR (parent §20.7's anti-rule satisfied — no fake/unreachable feature at any commit boundary) |

---

## 16. Definition of done

All §7 checklists `[x]` with evidence; censuses standing; Gate 1 PASS per
§8.2 (operator-approved launch); node `.md` synced; ONE exact-head CI green
with run id + SHA recorded; STOP at **READY FOR OPERATOR REVIEW — DO NOT
MERGE**. Post-merge status sync (parent §0 · roadmap Step-10 row · CLAUDE.md
current-state) is a separate follow-up commit, per Step-10 practice.
