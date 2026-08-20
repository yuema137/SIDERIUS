# Step 10 / P3 — Proposer Typed Evidence + Prediction Authoring

## 0. Status

**DRAFT rev 1 — ARCHITECTURE REVIEW PASSED (operator, 2026-08-20).
NOT FROZEN. IMPLEMENTATION NOT STARTED.** Semantic design complete;
**implementation topology subject to post-P2a-merge AND post-P2b-merge
reconciliation** (upstream-sensitive items labelled `PROVISIONAL(P2a)` /
`PROVISIONAL(P2b)`).

**Operator architecture-review verdict (2026-08-20), recorded verbatim**:
architecture coherent; open questions explicitly listed (Q-P3-1 / Q-P3-2
remain OPEN for freeze); **reconcile after P2b** (the binding gate — P2b
merging implies P2a merged under the frozen sequencing). The verdict is a
direction confirmation, NOT a freeze: the freeze happens in its own session
after the P2b-merge reconciliation, with the open questions dispositioned.

| field | value |
|---|---|
| parent | Step-10 parent REVISION 2 (frozen), §3.6 / §11 / §11.2 (ruling FROZEN) / §11.3; owns scope item **S4** |
| source anchor | merged `master` = **`d7d94740`** (production tree == the P1 squash `bcb17e45`). Line anchors are evidence, not implementation authority |
| depends on | **P2a merged** (ordering closed — P3 re-migrates nothing) and **P2b merged** (parent §11.2: "no new evidence field may be added to either untyped reader before the typed contract exists… P2b lands before P3") |
| downstream | **P5** consumes the typed boundary this child creates (its consumer wiring is `PROVISIONAL(P3)` on its side); **P6** runs the loop through it |
| Gate disposition | **proposed, PROVISIONAL until freeze**: deterministic parity for every surface EXCEPT the declared intentional prediction-authoring deltas; **ONE bounded Gate 1** (≤ 3 real calls) for the direction-safe authoring grammar — the parent names P3 "the child most likely to need it" (§22.1). Quoted against the gate standard at freeze |
| open operator questions | **2** (§12) |

**Frozen by the parent regardless of this draft's fate** (§11.2, operator
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
  node's standalone CLI.
* **§11.2 (FROZEN)**: retain the reachable legacy/standalone ENTRYPOINT;
  remove the duplicated semantic READER. Acceptance is the executable rule
  that no new evidence field can require wiring into two readers.
* **§11.3**: the one production direction defect (`proposal_helpers.py`
  `top_n`) is **P2a's** to migrate; the prediction-AUTHORING grammar is
  P3's, "because it is the same child's evidence surface".
* **§20.6**: P3 is separate because it is a node-boundary redesign with its
  own Gate-1 exposure.
* Q-10-2 heritage (P2a §4.0): identity ≠ direction; the proposer never
  re-derives either.

---

## 2. Current source audit (measured at `d7d94740`)

### 2.1 The input surface

`ProposalInput.interpretation: dict[str, Any]`
(`agent/schemas/proposal.py:650`), populated by the protocol with the FULL
dump: `"interpretation": output.model_dump()`
(`agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py:172`). The
standalone CLI (`ml_model_proposal_agent.py:2310-2322`) reads
`interpretation_{run_name}.json` from disk into the same raw dict.

### 2.2 The two readers — reads measured, not estimated

Dispatch: `:1471-1477` — `_run_pipeline(inp) if has_pipeline else
_run_legacy(inp)`. Interpretation-specific raw reads: **40** in the node
module, **11** in `nodes/proposal_helpers.py` (measured
`interp*.get(`/`interpretation[` at the anchor).

| reader | entry | shape | reads |
|---|---|---|---|
| LEGACY | `_build_reasoning_prompt` `:1086-1309` (via `_run_legacy` `:1503`) | flat markdown prompt | its own `.get()` set, incl. **two DEAD reads** — `per_file_comparison` (`:1180`) and `efficiency_comparison` (`:1184`), fields `InterpretationOutput` does not declare (re-verified: absent from the schema) — plus legacy-only `best_valid_denoising_score` (`:1108`) and `best_config` (`:1227`) |
| PIPELINE | `_run_pipeline` `:1575+` | an **18-key whitelist** into `accumulated["interpretation_summary"]` (`:1669-1699`; the 18 keys re-counted and confirmed at the anchor) + **5 direct reads** (`model_knowledge_cache`, `model_descriptions`, `per_model_best_valid`, `per_model_score_tables`, `model_types` — `:1620-1626`) | production path |

Measured drift (parent §3.6, re-confirmed): LEGACY-only reads exist that
PIPELINE never sees and vice versa (`prediction_pool_sizes`,
`prediction_evaluation_semantics` are PIPELINE-only). The source itself
records two drift incidents found by live Gates rather than review
(`:1257-1263`, `:1741-1746`). Deleting whitelist lines would leave every
proposer unit test green (parent §3.6's coverage finding) — the whitelist is
effectively unpinned.

### 2.3 Prediction authoring — the un-migrated half, located precisely

The EVALUATION half is done (09a): `evaluate_prediction`
(`nodes/result_interpretation_agent/prediction.py:98`) takes a REQUIRED
keyword-only `order: MetricOrder` and labels via `order.is_better(actual,
sota)` (`:202`) under `metric_order_signsafe_v2`. The AUTHORING half still
assumes higher-is-better in TWO places:

1. **The schema description**
   (`agent/schemas/proposal.py`, `FalsifiablePrediction.threshold_for_refutation`):
   *"**Below** this value, the hypothesis is considered refuted … if
   predicting improvement, threshold < current"*. Under a `lower` metric,
   refutation is ABOVE the threshold; an LLM reading this description (it is
   part of the structured-generation contract) is instructed to author an
   inverted band.
2. **The prompt example**
   (`agent/prompt_templates/proposal/causal_reasoning_stage.md:106-113`):
   `current_value: 1.5, predicted_value: 2.5, threshold_for_refutation: 1.2`
   — an upward improvement with a below-current threshold, copied by
   pattern-matching models. The `_explore`/`_exploit` variants carry the same
   grammar sections.

What is already direction-safe and must NOT be re-touched: `boldness`
(`abs(predicted − current)/max(|current|, 1e-6)` — magnitude, not
direction); the `_prediction_differs_from_current` validator; the v2
evaluator and its versioned pools; `render_prediction_track_record`
(direction-agnostic by construction, parent §3.6's correction).

`MetricSpec` / `MetricOrder` / `metric_identity` occur **zero** times in the
proposer's three modules today; `InterpretationOutput.metric_identity`
exists and is never read there. `PROVISIONAL(P2a)`: P2a C4 threads the
evidence's metric identity to the `top_n` helper *"WITHOUT building a typed
reader (P3's scope) — record exactly how, so P3 can replace the mechanism
without re-litigating the semantics"*. P3 replaces exactly that threading.

### 2.4 Source-site table (audit → disposition)

| source site | current input shape | semantic value extracted | current owner | target owner after P3 | upstream dep | disposition |
|---|---|---|---|---|---|---|
| protocol `:172` | `InterpretationOutput` → `model_dump()` | everything | protocol (untyped) | protocol builds the TYPED value | — | REWRITE: the protocol's one mapping produces `ProposerInterpretationEvidence` (name `PROVISIONAL(P3)`) |
| pipeline whitelist `:1669-1699` | raw dict, 18 keys | run stats, findings, prediction record, vocab health | `_run_pipeline` | the typed value's fields, serialized by ONE renderer | P2b (four prediction keys are version-aware; secondaries may join later) | MIGRATE onto the typed value; bytes preserved (§5.4) |
| pipeline direct reads `:1620-1626` | raw dict, 5 keys | cache/descriptions/per-model bests/tables | `_run_pipeline` | typed fields | — | MIGRATE |
| legacy reader `:1086-1309` | raw dict | its own set + 2 DEAD + 2 legacy-only | `_build_reasoning_prompt` | an ADAPTER from the typed value into the legacy renderer | — | MIGRATE via adapter; DEAD reads deleted (they can never fire — the schema has no such fields); legacy-only LIVE reads become typed fields |
| helpers (11 reads) | raw dict fragments | strategy/candidate context | `proposal_helpers.py` | typed fields (incl. the P2a-threaded metric identity) | P2a | MIGRATE; the `top_n` COMPARISON itself is P2a's and is not re-touched |
| standalone CLI `:2310+` | JSON file → raw dict | same as node | `main()` | the SAME projection function applied to the loaded output | — | MIGRATE (entrypoint retained, §11.2) |
| authoring grammar (schema description + 3 stage templates) | prose | prediction band semantics | schema + templates | direction-safe rendering from the evidence's metric identity | P2a (`MetricOrder` wording authority) | REWRITE (INTENTIONAL LLM-facing delta, declared) |

---

## 3. Goal / semantic owner / boundary

**One semantic owner: the proposer-facing interpretation-evidence contract.**

After P3: the protocol produces ONE narrow typed value; both entrypoints and
the helpers consume it; the raw `interpretation` dict field is GONE from
`ProposalInput`; the legacy prompt is produced by an adapter over the typed
value at byte parity; prediction authoring renders direction-safe grammar
from the evidence's metric identity; and a planted new raw semantic reader
turns a census RED.

**Not a producer-schema copy** (operator §6): the typed value is a
CONSUMER-VIEW projection — the union of both readers' LIVE reads, nothing
more. `InterpretationOutput` is not duplicated, not subclassed, not passed
wholesale. Measured basis for the field set: 18 whitelist keys + 5 direct
reads + the legacy-only LIVE reads (`best_valid_denoising_score`,
`best_config`) + the metric identity (P2a's threading absorbed) − the 2 DEAD
reads. Exact field list is fixed at implementation from this audit table,
not invented.

Proposed public boundary (names `PROVISIONAL(P3)`, shape not):

```text
agent/schemas/proposer_evidence.py            (NEW, ONE owner)
    ProposerInterpretationEvidence            frozen typed value (the projection)
    build_proposer_evidence(InterpretationOutput | validated dump) -> value
        — the ONE projection authority; called by the protocol (production)
          and by the standalone CLI path (same function, same value)

ProposalInput.interpretation_evidence: ProposerInterpretationEvidence
    (replaces `interpretation: dict[str, Any]` — removed, not deprecated)
```

**Non-goals**: the `top_n` comparison (P2a, merged before this); secondary
metric production (P2b); persistence/carry lifecycle (P5 — §9's boundary);
`MetricOrder` itself; the interpreter's own schemas and renderers; the
reflector; any change to the v2 evaluation semantics or the versioned pools.

---

## 4. Design decisions (load-bearing)

### 4.1 The projection lives in the schema layer; the protocol calls it

The repository's own architecture rule says the protocol is the only place
field mapping happens. The projection FUNCTION therefore has one home the
protocol calls, so the standalone CLI (which loads a persisted
interpretation JSON, not an in-memory output) reaches the identical value
through the identical function. Two callers, one construction path —
that is the executable §11.2 rule.

### 4.2 The legacy adapter — bytes through the type

`_build_reasoning_prompt` becomes a renderer over
`ProposerInterpretationEvidence` via an adapter that reproduces today's
prompt BYTES for today's inputs (goldens captured at C0). The two DEAD reads
are deleted — provably unreachable (the schema never carried the fields), so
byte parity is unaffected. Legacy-only LIVE reads become typed fields so the
adapter needs no side-channel.

### 4.3 The pipeline whitelist — serialization preserved

The 18-key JSON block embedded in pipeline prompts is reproduced from the
typed value by ONE serializer with the SAME key set, same ordering, same
`is not None` filtering — byte parity on the un-changed surfaces is the
acceptance, and the whitelist finally gets a pin (its four prediction keys
currently have zero test coverage; parent §3.6).

### 4.4 Direction-safe prediction authoring — the declared intentional delta

The authoring grammar becomes a rendered block parameterized by the
evidence's metric identity (id + direction), using `MetricOrder`'s existing
wording authority (`direction_words`, `toward_better` — no new vocabulary):

* the `threshold_for_refutation` schema description is rewritten
  direction-neutrally ("on the refuted side of `current_value` for this
  run's metric direction; the rendered task context states which side that
  is");
* the stage templates' example block is rendered per-direction (an upward
  example under `higher`, a downward example under `lower`) rather than
  hardcoding the upward one;
* authored predictions remain evaluated by the UNCHANGED v2 evaluator — the
  authoring instructions align with `evaluate_prediction`'s semantics
  (confirmed = `order.is_better(actual, sota)`), closing the roadmap's
  "proposer prediction-authoring grammar" item.

**These are INTENTIONAL LLM-facing deltas** — enumerated byte-diff surfaces,
declared in the ledger, with everything outside them at exact parity.

### 4.5 Where the metric identity comes from

`InterpretationOutput.metric_identity` (exists, never read by the proposer
today) — projected into the typed value. Absent identity (legacy artifact)
is a NAMED absence on the typed value; the authoring renderer then emits the
Q-10-2-style unavailable state (the canonical formatter, P2a's) and
direction-specific example text is omitted rather than defaulted —
`PROVISIONAL(P2a)` for the formatter's exact import.

### 4.6 Extension points, not features

The typed value declares where future evidence lands so it never needs a
second reader: secondaries (`PROVISIONAL(P2b)` — projected from
`per_model_secondary_metrics` when P2b's values are real; observational
rendering only, never ordering) and P5's carried values (§9). Neither is
implemented here beyond the extension point.

---

## 5. Three-task control

| concern | TIDMAD | Pets | DAVIS | same framework path? |
|---|---|---|---|---|
| evidence projection | full stats + prediction record | same shape (its own values) | same | YES — one projection, no task branch |
| metric identity in evidence | `tidmad_denoising_score`/higher | `accuracy`/higher | `mse`/**lower** | YES — a value, not a branch |
| authoring example rendered | upward | upward | **downward** | YES — rendered from direction words |
| absent identity (legacy artifact) | named absence; no direction language | same | same | YES |

Fourth task: composes via P1; its interpretation output projects through the
same function; zero framework edits (inherits P1's census).

## 6. Structure preflight (parent §19.3)

| file | now | P3 change | owners after |
|---|---|---|---|
| `agent/schemas/proposer_evidence.py` | — (new) | the typed value + projection, est. 200-350 LOC | ONE |
| `agent/schemas/proposal.py` | large | field swap on `ProposalInput`; `FalsifiablePrediction` description rewrite | unchanged set |
| `agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py` | ~200 | maps through the projection | unchanged |
| `nodes/ml_model_proposal_agent/ml_model_proposal_agent.py` | ~2,400 | readers consume the typed value; legacy adapter; NO new phase | unchanged set — **if the reader migration would grow `_run_pipeline` rather than shrink it, extract the evidence-rendering boundary FIRST** |
| `nodes/proposal_helpers.py` | ~120 | 11 reads → typed fields | unchanged |
| stage templates ×3 | — | direction-parameterized grammar block | unchanged |

## 7. Proposed commit decomposition (PROVISIONAL until post-P2a/P2b reconciliation)

Six semantic commits, autonomous, all-`[ ]` until verified evidence:

* **C0** — baselines: legacy prompt goldens + pipeline whitelist-JSON goldens
  (both entrypoints, current bytes); raw-reader census (the 40+11 reads
  enumerated executably); plant-and-catch for a new raw reader.
* **C1** — the typed value + projection + protocol migration (schema layer
  only; both old readers still work off the dict — the ONE intermediate
  state where both exist, closed in C2/C3 within the same PR).
* **C2** — pipeline reader onto the typed value; whitelist serializer byte
  parity vs C0 goldens; helpers' 11 reads migrated (P2a's identity threading
  replaced by the typed field, comparison untouched).
* **C3** — legacy adapter + standalone CLI onto the same projection; legacy
  prompt bytes == C0 goldens; DEAD reads deleted; `ProposalInput.interpretation`
  REMOVED; raw-reader census flips to zero.
* **C4** — direction-safe authoring: schema description rewrite + rendered
  grammar block + absent-identity state; the declared byte-diff surfaces
  enumerated; three-task rendering fixtures (upward/upward/downward +
  absence).
* **C5** — closure: censuses (one projection authority; zero raw readers;
  plant RED), bounded Gate 1 per the frozen disposition, docs/ledger, ONE
  exact-head CI.

## 8. Validation strategy / Gate disposition

Deterministic owners: projection unit tests (round-trip from a real
`InterpretationOutput` fixture); byte-parity goldens for BOTH entrypoints on
un-changed surfaces; the enumerated intentional-delta diff; three-task
authoring fixtures with hand-written expected text; the raw-reader AST
census + plant; schema tests for the named-absence state.

**Gate 1 (PROVISIONAL)**: ONE bounded run (≤ 3 calls): a real model authors
a prediction under a `lower` fixture and under `higher`; PASS = well-formed
`FalsifiablePrediction` whose `predicted_value`/`threshold_for_refutation`
sit on the correct sides per the v2 evaluator's semantics. Only the
authoring surface — everything else is parity-owned. Gate 2: NOT REQUIRED
(no real-data/GPU class).

## 9. Cross-child boundary — P3 ↔ P5 (CRITICAL, mirrored in the P5 draft)

* P3 owns: the consumer-facing TYPE and projection.
* P5 owns: which interpretation-derived values SURVIVE iterations, their
  persistence/restore/carry.
* P3 creates NO persistence mechanism; the typed value is built per
  invocation from the interpretation output the workflow already hands over.
* P5 creates NO proposer reader; when P5's carried values must reach the
  proposer, they arrive through THIS typed value's declared extension point
  (P5 marks that wiring `PROVISIONAL(P3)`).

## 10. Preservation invariants

Un-changed-surface prompt bytes exact (both entrypoints); dispatch
`:1471-1477` untouched; proposal OUTPUT schema untouched (except the
description prose of `threshold_for_refutation`, which is input-side
grammar); v2 evaluator + pools untouched; `top_n` comparison untouched
(P2a's); no ordering expression gains a secondary operand.

## 11. Risk register

| risk | mitigation |
|---|---|
| the typed value becomes `InterpretationOutput` v2 | field set derived from the measured read union ONLY; §3's non-goal; review trigger on field count |
| a third reader appears during migration | C0 census + plant precedes any migration |
| legacy byte drift | adapter goldens captured BEFORE C1 |
| authoring delta leaks beyond its declared surface | enumerated diff surfaces; parity everywhere else |
| P2b fields wired into the old dict first | sequencing: P2b lands BEFORE P3 (parent §11.2) — reconciliation checks P2b touched no proposer reader |

## 12. Open operator questions

| id | question | proposal |
|---|---|---|
| **Q-P3-1** | Does the LEGACY entrypoint also receive the direction-safe authoring grammar, or does byte-exact legacy parity win there (grammar change = pipeline-only)? | pipeline-only: legacy keeps byte parity (its value is compatibility); the grammar fix rides the production path. The legacy path's prediction is evaluated by the same v2 evaluator either way |
| **Q-P3-2** | Is the bounded Gate 1 REQUIRED at freeze, or does the deterministic three-task authoring fixture suffice (rendered-instruction correctness) with no real-LLM evidence? | keep the ONE bounded Gate 1 — "does a real model follow lower-is-better authoring instructions" is genuinely LLM-behavioral, and this is the child the parent pre-named for it |

## 13. Post-upstream reconciliation obligations (before freeze)

1. Re-audit §2 at post-P2a/P2b master (helpers' threading shape from P2a C4;
   whether P2b touched any proposer surface — it must not have).
2. Re-count both readers' key sets (P2b adds interpretation fields).
3. Confirm the canonical unavailable formatter's home (P2a C1) and import.
4. Quote the gate standard for the Gate-1 disposition; disposition Q-P3-1/2.

## 14. Adversarial self-review (draft-stage)

| attack | answer |
|---|---|
| Second proposer semantic reader survives? | C3 removes the dict field itself — a second reader has nothing to read; census + plant |
| Raw dict mining returns later? | the §11.2 executable rule: census stays as a standing guard |
| Typed value duplicates `InterpretationOutput`? | consumer-view union of measured LIVE reads only; two dead reads dropped prove it is not a copy |
| Higher-is-better leak in authoring? | the DAVIS downward fixture + the schema-description rewrite; evaluator alignment stated |
| Secondary becomes ordering authority? | P3 renders observationally at most; the 09a operand invariant stays green over P3's diff |
| Hidden persistence mechanism? | §9: none; the value is per-invocation |
| Giant context object? | the value is a projection with a measured field basis, not a bag; preflight guards the node files |
