# Step 10 / P2a — Golden `MetricOrder` Closure

## 0. Status

**REVISION 3 — FROZEN. OPERATOR APPROVED (2026-08-20).
Open operator questions: 0. Material contradictions: 0.**

*(The line "IMPLEMENTATION NOT STARTED" above described the state AT THE
FREEZE COMMIT and is preserved as history in the closing note; the current
lifecycle is the separate field below. Revision 3's semantic rulings are
unchanged by anything in §0.1 or §13 — implementation records evidence
against them, it does not amend them.)*

### 0.1 Current lifecycle (live — updated after the freeze)

```text
lifecycle           : MERGED / CLOSED (2026-08-21)
PR                  : #242 — MERGED (squash)
final PR head       : b50bec6a
exact-head CI       : 32431989276 SUCCESS on b50bec6a — lint, ruff-format,
                      pyright, unit all PASS (verdict read from the log)
squash SHA          : e094fa26
origin/master       : e094fa26 — verified byte-identical to the validated
                      PR head b50bec6a
final review        : operator verdict PASS — APPROVED TO MERGE
                      (post-P4 merge-based reconciliation; force push not
                      used; merge commit 553bd66c; 0 conflicts)
ordering surface    : 12 measured sites at the base  ->  0
D-P2a-4             : ACCEPTED / BOUNDED (final operator disposition —
                      ordering behavior/body unchanged; only the accepted
                      declaration/identity annotation widened; §13.7)
F-P2a-4             : RESOLVED (zero TIDMAD derivation sites added;
                      direction never re-derived from task identity,
                      metric name, or TIDMAD history)
open operator items : 0
```

**Post-freeze wording corrections (semantics unchanged).** Four passages
still carried rev-1/rev-2 phrasing that Revision 3 had already superseded, or
that the delivered implementation made untrue. Each is corrected IN PLACE
with the superseded text quoted, so the history stays legible:

| § | was | now |
|---|---|---|
| C1 goal | "§4.1's acquisition **precedence**" | §4.1's metric-identity **reconciliation** rule (§4.1 was always correct; the C1 prose lagged it) |
| C1 scope | helper "beside `MetricOrder`" | owned by `execute_tools/evaluation_metric.py` beside `MetricSpec` (Q-P2a-2 / Q-P2a-3 resolved it the other way) |
| §8 | "`MetricOrder` module unchanged" | the precise preserved invariant: BODY unchanged, only the accepted identity annotation widened (D-P2a-4), measured |
| §9 + C2 table + attack 21 | future non-monotone transform "site-5 assertion fires" | **no generic monotonicity assertion exists**; only the CURRENT transform is tested; a non-monotone future transform is a future metric-interface capability |

### 0.2 Dependency state — P4 (source reconciliation only)

`P4` merged in PARALLEL with this child and is recorded here so the rebase
base is auditable. **P4 is NOT a semantic prerequisite for P2a, and this
records no dependency edge P4 → P2a.**

```text
P4 : PR #243, MERGED (squash 79833db8), post-merge status sync 9f475980
     shared changed files with P2a : 0   (measured, §13.7)
     semantic overlap              : 0
```

Revision 3 is the POST-P1-MERGE reconciliation + freeze (operator mandate
2026-08-20). It contains real semantic clarification beyond line
reconciliation, which is why it is a revision and not an erratum:

* **the frozen metric contract** (§4.0): every primary metric used for
  selection/ranking/early-stop carries `metric_id` + `direction`; direction
  is NEVER inferred from name, sign, range, task or TIDMAD history; and
  **identity ≠ direction** — same direction never proves two artifacts
  comparable;
* **acquisition is RECONCILIATION, not precedence** (§4.1): all AVAILABLE
  identities (bound + stamped) are reconciled to exactly ONE compatible
  identity; a bound spec is an authoritative INPUT, never permission to
  ignore a conflicting artifact stamp;
* **Q-P2a-3 RESOLVED — PROMOTE**: metric-spec reconciliation moves from the
  interpreter node to a shared owner beside the metric-identity semantics in
  `execute_tools/evaluation_metric.py`; exactly ONE implementation remains,
  and it is deliberately NOT placed in `MetricOrder` ("are these the same
  metric?" and "which value is better?" are different responsibilities);
* **per-artifact unrankable semantics** (§4.2): one missing-identity
  artifact never poisons a compatible corpus; four frozen cases (all-known ·
  known+missing · all-missing · conflicting-known);
* **Q-P2a-1 RESOLVED**: proposer `top_n` with no usable identity falls back
  to the EXISTING order-free `all` semantics — no new "first-N" selection
  policy is invented, and the result is never labelled top/best;
* **Q-P2a-2 RESOLVED**: one canonical metric-identity-unavailable
  message/formatter, owned beside the reconciliation authority (not inside
  `MetricOrder`);
* **site 5 ruled on source truth** (§4.3): the ranked values ARE the
  persisted per-file evidence; the CURRENT transform's monotonicity is
  documented and tested as a TIDMAD fact, not faked as a generic framework
  contract.

Post-P1 reconciliation verdict: **all discrepancies class A/B (mechanical /
source-shape); class C (semantic contradiction) = 0.** See §10.2/§10.3.

**Rev 2 (2026-08-20) changes the PLAN's form, not its semantics.** §7's
commit decomposition was six terse bullet lists; it is now six full
per-commit specifications in the required eight-section shape — goal (and why
this commit rather than another) · scope (files, functions, non-goals,
dependencies) · `[ ]` implementation steps · validation plan split into
unit / integration-pseudo / negative / backward-compatibility, with any
real-training Gate listed SEPARATELY and never launched without operator
approval · exact observable acceptance criteria · failure and edge cases with
their required dispositions · verification commands whose counts and wall
times are recorded after running · and an explicit commit-boundary statement.

Two rules now bind every commit in §7. **Checklists start all-`[ ]`** and a
`[x]` is written only after implementation AND verification, with the
evidence beside it. **Ordering is validated on the actual visited comparison
sequence**, never the final winner alone — a wrong comparator picks the right
winner on any fixture whose maximum happens to come first.

§7's plans were written against **inspected** code, not remembered code: all
twelve surfaces were re-verified (§10.1), which found the three workflow
anchors moved under P1 and the other nine exactly where §2.1 records them. No
ambiguity or scope growth was found, so no operator question was raised.
Semantics, scope, the two open questions and the Gate disposition are
unchanged from rev 1.

| field | value |
|---|---|
| parent | Step-10 parent REVISION 2 (frozen), §3.3 / §8 / §8.1; owns scope item **S2** |
| source anchor | merged `master` = **`bcb17e45`** (the P1 squash). All twelve surfaces re-verified at this anchor (§10.3); line numbers are evidence, not implementation authority |
| depends on | **P1 MERGED 2026-08-20** (PR #241, squash `bcb17e45`) — the bound metric exists as `bindings.task_composition.metric` and via `resolve_bound_run_metric()`. P2b depends on this child, not vice versa |
| Gate disposition | **FROZEN: Gate 1 NOT REQUIRED · Gate 2 NOT REQUIRED** (operator ruling 2026-08-20). Direction is deterministic; hand-computed `MetricOrder` fixtures, comparison-SEQUENCE parity, persisted-identity fixtures, mixed/missing-identity cases, the AST scanner and plant-and-catch are the authoritative owners — real LLM/GPU evidence is LESS direct than these. A newly discovered non-deterministic failure class during implementation is a MATERIAL DEVIATION, never an autonomously invented Gate |
| open operator questions | **0** — Q-P2a-1 / Q-P2a-2 / Q-P2a-3 all RESOLVED by operator ruling 2026-08-20 (§11) |

**Frozen in this draft regardless of P1's final shape** (operator §10):
P2a does **NOT** derive metric identity anywhere; it consumes the P1-bound
metric authority (or an artifact's own persisted identity), and introduces
**no** second direction enum, boolean, helper or comparator.

---

## 1. Parent contract (recovered, binding)

* `MetricSpec.direction` is the ONE declaration
  (`execute_tools/evaluation_metric.py:111` vocabulary, `:368-370` field);
  `MetricOrder` (`execute_tools/metric_order.py:59`) is the ONE interpreter —
  `is_better` / `is_at_least` / `best` / `worst` / `rank` / `worst_sentinel` /
  `best_sentinel` / `toward_better` / `toward_worse` / `direction_words` /
  `comparison_symbol`.
* **Q-10-2 = A (frozen)**: a persisted artifact with no `metric_spec` stays
  inspectable, is **never ranked**, shows a visible named
  *"metric direction unavailable / `metric_spec` absent"*, never assumes
  higher-is-better, and never hard-fails the whole consumer.
* §8.1 acceptance: zero raw task-dependent `>` / `<` / `max` / `min` /
  `reverse=True` on the golden metric; the stronger AST scanner replaces the
  presence list; three-task hand-computed literals; no new authority.

---

## 2. Current source audit — the complete ordering surface (audited at `2393aacc`; RE-VERIFIED at merged `bcb17e45`, §10.3)

### 2.1 The ten code sites + two prose sites

**Re-verified at merged master `bcb17e45` (post-P1, §10.3): the surface is
EXACTLY these twelve — no site appeared, none disappeared; only the three
workflow line numbers moved (P1 inserted ~89 lines above them). P1's own new
code (`workflows/task_composition.py` included) contains ZERO golden-score
ordering shapes.**

| # | site (current line) | what it decides | order source after P2a |
|---|---|---|---|
| 1 | `workflows/model_exploration.py` (`>` at `:2744` @ `bcb17e45`) | raw-formal progress → `state.best_score_overall` | §4.1 RECONCILIATION over the available identities: bound `bindings.task_composition.metric.spec` (composed) + the compared `tune_output.metric_spec` stamp; conflict ⇒ fail closed; none ⇒ §4.2 |
| 2 | `workflows/model_exploration.py` (`>` at `:2756` @ `bcb17e45`) | **chain formal incumbent advance** | same |
| 3 | `workflows/model_exploration.py` (`>=` at `:2804` @ `bcb17e45`) | early-stop `target_score` | same; `is_at_least` |
| 4 | `core/resume.py:441-455` `_pick_best` (`>` at `:451`) | within-iteration incumbent on resume | the restoring run's spec; recordless-spec ⇒ named refusal (never re-derivation) |
| 5 | `execute_tools/per_file_best.py:481-490` `_row_beats` (`>` at `:483`) | per-file best row, **linear space** | the metric identity the module already imports; §4.3 monotonicity note |
| 6 | `dashboard/data_sources/local_json.py:245` (`reverse=True`) | top-N ranking | persisted identity (§4.4); absent ⇒ Q-10-2 refusal |
| 7 | `dashboard/data_sources/local_json.py:195-197` | `best_agent_score` / `best_run_name` | same |
| 8 | `scripts/build_diagnostic_summary.py:113` (`max`) | diagnostic best round | same |
| 9 | `scripts/finalize_recovered_diagnostic_round.py:233` (`max`) | OOM-recovery best round | same |
| 10 | `nodes/proposal_helpers.py:84-89` (`reverse=True` at `:88`) | **production `top_n` candidate cut** — under DAVIS selects the WORST N | the interpretation evidence's metric identity (`InterpretationOutput.metric_identity`, which the proposer today never reads) — owned HERE, not in P3, because it is a shared ordering decision (parent §8.1) |
| P-1 | `dashboard/data_sources/base.py:119` | prose "higher is better" | `direction_words` / Q-10-2 wording |
| P-2 | `dashboard/api/router.py:233-234` | prose | same |

Tie rules at sites 4 and 5 (lexicographic `exp_id`; earliest iteration;
persisted-round provenance) are **direction-independent and preserved
byte-for-byte** — P2a migrates only the score comparison itself.

> **ERRATUM (measured at C0, 2026-08-20) — the code surface is TWELVE, not
> ten.** The C0 structural scanner found two further golden-metric ordering
> decisions this table does not list: `core/resume.py:1314`
> (`formal_cand['score'] > state.chain_best_valid_formal_score`) and `:1324`
> (`trial_cand['score'] > state.chain_best_trial_score`) — the CHAIN-level
> incumbent fold in `restore_prior_state`, one level above site 4, which it
> calls. Both were audited to their source and are genuine primary-metric
> comparisons. They were invisible to every earlier audit for the same reason
> site 2 was: their comparison text contains no golden-score NAME. Classified
> BOUNDED (they fall inside the already-approved "make resume primary-score
> selection direction-aware" scope and need no new authority); **C2 migrates
> them together with sites 4 and 5.** Full audit, evidence and classification:
> §13.1 deviation D-P2a-1. The frozen SEMANTICS of this section are unchanged —
> only its count, which was an audit measurement rather than a ruling.

### 2.2 Pinned NOT-direction-sensitive (must stay unrouted)

`policy.py:557` `min(same_loss_finals)` (a LOSS, lower by definition — its C2
rung pins it); `scoring_helpers.py:458-460` within-metric impact ranking;
runtime/memory/timing extrema in `core/runtime_control/`; index/`exp_id`
tie-breaks; `abs(delta)` magnitude filters. The scanner (§5) must not flag
these — that is its precision contract.

### 2.3 The census gap this child closes

`NOT_REACHED_DIRECTION_CONSUMERS`
(`tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py:160-178`)
names **4 of the 10** code sites + 1 prose site; **six of twelve surfaces are
invisible to it**, including site 2 (the chain incumbent) and site 10 (the
top-N cut). A presence list can only find what someone remembered — replaced
per §5.

---

## 3. Goal / semantic owner / scope

**One semantic owner: primary golden-metric ordering.** After P2a, every
production decision of "which value is better on the golden metric" asks
`MetricOrder`; prose states `direction_words`; consumers of persisted
artifacts without metric identity refuse to rank per Q-10-2; and a
shape-based structural scanner holds the whole surface so an eleventh site
cannot appear silently.

**Non-goals**: secondary metrics entirely (P2b); the proposer's typed
evidence reader (P3 — P2a changes ONE helper's comparison, not the reader
architecture); `MetricOrder` itself (unchanged, no new methods expected —
if one proves necessary it is a named framework-capability change per parent
§7.2); the same-loss `final_loss` rank; any tuner site (all 21 migrated in
07b/09a).

---

## 4. Design

### 4.0 The frozen metric contract (FROZEN, framework-wide)

The rule the single-task TIDMAD era kept implicit, now explicit:

> Every PRIMARY metric used for model selection, incumbent tracking,
> best-model tracking, ranking, early stopping or top-N selection MUST carry
> enough metadata to determine **metric identity** and **optimization
> direction** — minimally `metric_id` + `direction ∈ {higher, lower}`.
> Direction is NEVER inferred from the metric's name, the score's sign, its
> numeric range, the current task, or historical TIDMAD defaults. Every
> generic "which score is better?" decision asks `MetricOrder` constructed
> from the declared direction; no raw task-dependent `>`/`<`/`max`/`min`/
> `reverse=True` may independently encode primary-metric preference.

Anchor examples: TIDMAD is higher-is-better with negative values (−1 beats
−3); Pets accuracy is higher; DAVIS MSE is lower (0.0172 beats 0.0174).

**Identity and direction are NOT the same thing — this distinction is
binding.** Direction answers "higher or lower?"; identity answers "what
metric is this?". Accuracy, PSNR and the TIDMAD score are all `higher`, and
none is comparable to the others. Therefore `direction == "higher"` is NEVER
sufficient proof that two persisted artifacts are comparable: **ranking
across artifacts requires a compatible reconciled metric identity, not
merely matching direction.**

**Persisted identity — measured source truth at `bcb17e45`, no schema
addition required** (§4.4 details): `HyperparamTuningOutput.metric_spec`
carries the FULL `MetricSpec` (09a stamp; `None` on legacy outputs), and
`ExperimentRecord.metric_result` carries `metric_id` + `direction` (Step 06;
`None` on legacy/unscored records). The dashboard/diagnostic summary files
persist FULL record dicts, so they carry `metric_result` too. The existing
fields ARE the identity source; P2a adds none and invents no second metric
schema.

### 4.1 Order acquisition is RECONCILIATION, not precedence (FROZEN)

Rev 2 said "composed → bound spec; legacy → artifact spec". That reads as
permission for a bound spec to shadow a conflicting artifact stamp, which is
exactly the silent inconsistency this child exists to kill. Frozen instead:

```text
collect all AVAILABLE metric identities relevant to the comparison
    (composed run: the bound MetricSpec is one authoritative INPUT,
     plus artifact-stamped specs where present;
     legacy run: artifact-stamped specs only)
        →
shared reconciliation (ONE implementation, §4.1a)
        →
exactly one compatible MetricSpec / identity
        →
MetricOrder(spec)
```

The complete truth table:

| bound | artifact stamps | outcome |
|---|---|---|
| A | A | A |
| A | absent | A |
| A | **B** | **FAIL CLOSED** for that ranking operation — a bound spec is never permission to ignore a conflicting persisted stamp |
| none | all A | A |
| none | all absent | **no ranking** — the consumer takes its §4.2 unrankable state |
| none | **A and B** | **FAIL CLOSED** for that ranking operation |

### 4.1a Q-P2a-3 RESOLVED — reconciliation is PROMOTED to a shared owner

`reconcile_metric_spec` currently lives in
`nodes/result_interpretation_agent/evidence.py:58` — node-private by
ownership, and generic workflow code may not import node internals
(`tests/unit/nodes/test_node_public_boundary.py`). **Operator ruling:
PROMOTE.** The rejected alternative — "a composed run trusts the bound spec
and skips reconciliation" — is rejected because bound-A/artifact-B is a real
inconsistency that must fail closed, not go unobserved.

* **New owner: `execute_tools/evaluation_metric.py`** — beside `MetricSpec`
  and `metric_spec_from_declaration`, the module that already owns metric
  identity semantics. Deliberately NOT `MetricOrder`: reconciliation asks
  "are these the SAME metric?"; `MetricOrder` asks "for this already-known
  metric, which value is better?" — separate responsibilities.
* The promoted function generalizes the existing one: it accepts the
  available identities (a bound spec and/or stamped specs) and returns one
  compatible identity or raises the fail-closed refusal.
* The interpreter node IMPORTS the shared authority after the promotion; its
  existing contract-error semantics (partial stamping is a refusal; mixed
  specs are a refusal) are PRESERVED, not weakened. **Exactly ONE
  reconciliation implementation exists afterwards** — pinned by census.

Mixed specs across compared artifacts fail closed through this ONE
reconciliation — P2a adds no second.

### 4.2 Q-10-2 — per-ARTIFACT unrankable semantics (FROZEN)

An artifact without sufficient metric identity **remains inspectable, may
display its raw scalar, and may appear in non-ranking views** — but it must
NOT be called best, must NOT receive a metric-based rank, and must NOT
participate in metric-based selection.

**One missing-identity artifact never poisons a compatible corpus.** The
four frozen cases, applied consistently to resume, dashboard, diagnostic
scripts and every other artifact consumer:

| case | corpus | behaviour |
|---|---|---|
| **A** all known, compatible | A:MSE · B:MSE · C:MSE | rank normally |
| **B** known + missing | A:MSE · B:absent · C:MSE | A and C are ranked against each other; B stays inspectable but UNRANKED, with the visible named metric-identity-unavailable state |
| **C** all missing | A:absent · B:absent | no rankable artifact; raw values may still be shown; named state visible |
| **D** conflicting known | A:MSE · B:accuracy | REFUSE that cross-artifact ranking operation — fail closed with a named diagnostic; never pretend they share a metric |

Per consumer:

| consumer | behaviour |
|---|---|
| workflow sites 1–3 | reconciliation per §4.1 over the bound spec + the compared output's stamp. Case-B/C inputs (a spec-less record) cannot advance the incumbent/best tracker: the update is skipped with a printed named notice (once per run), never an assumed direction. Case D fails closed. (In practice unreachable post-09a — every scored output is stamped — but the branches must exist and be tested) |
| resume `_pick_best` | **per-record, not per-iteration** (§4.2a) — rank the compatible-identity subset; missing-identity records are individually excluded with the named state; no rankable records ⇒ no incumbent + named notice; conflicting KNOWN identities ⇒ fail closed per the existing restore soft-failure policy, never a silent pick |
| dashboard | rank the compatible subset; each missing-identity row shows the canonical unavailable state and no rank; raw scalars still displayed; conflicting known identities ⇒ the ranking view refuses with the named diagnostic |
| diagnostic scripts | same four-case rule; the canonical message to stderr; `best: unavailable` only when case C/D leaves nothing rankable |
| proposer `top_n` | **Q-P2a-1 RESOLVED (operator ruling 2026-08-20): fall back to the EXISTING order-free `all` semantics.** No usable identity ⇒ the named unavailable notice fires, NO metric-based ranking happens, and the candidate set is produced by the existing `all` path under whatever independent safety/token bounds that path already owns. A new "first N by declaration order" policy is explicitly REJECTED — it would be a new selection policy owned by P2a for no scientific reason. The result is never described as "top N"/"best N"/"best candidates", because no metric ranking happened |

### 4.2a Resume semantics, restated precisely (supersedes rev 2's wording)

Rev 2 said "records without spec ⇒ that iteration restores no incumbent" —
too broad when only SOME records lack identity. Frozen:

* rank only the subset carrying a compatible metric identity;
* missing-identity records are INDIVIDUALLY excluded from metric ranking;
* no rankable records remaining ⇒ restore no incumbent + named notice;
* compatible known records remaining ⇒ the incumbent is chosen among them;
* multiple conflicting KNOWN identities ⇒ fail closed per the existing
  restore soft-failure policy — never silently choose one;
* every direction-independent tie-break is preserved byte-for-byte.

### 4.3 Site 5 — RULED on source truth (no fake generic contract)

Measured at `bcb17e45`: `_RowCandidate.best_linear` is populated directly
from the persisted `file_vector` entries (`per_file_best.py:306-343`) — the
per-file values ARE stored in linear space, and the log form is a DERIVED
display (`"best_log_score": _log(self.best_linear)`, `:453`). There is no
separate "canonical per-file golden value" to prefer: the metric's
`per_sample` is a pointer to this same `file_vector`. So the PREFERRED
option ("compare in canonical space") and the current code coincide — the
ranked values are the persisted per-file evidence itself.

**Frozen ruling**: `_row_beats` migrates its score comparison to
`MetricOrder`; the validity of ranking these values rests on the CURRENT
transform's deterministic monotonicity (log base 5.27 > 1 ⇒ strictly
increasing ⇒ linear order == log order), which is **documented and TESTED as
a property of THIS transform** — a hand-computed fixture pinning that the
linear ranking equals the log ranking on TIDMAD-shaped values. P2a does
**NOT** claim a generic framework capability to assert arbitrary future
transform monotonicity: no such contract exists in source, and pretending
one does would be a fake guard. A future metric whose per-sample values need
a non-monotone display transform is recorded as a **future capability
requirement** (a new declaration on the metric, owned by the metric
interface), not guarded here.

### 4.4 Persisted-identity source — EXACT fields (measured at `bcb17e45`)

| consumer | what it reads | identity available | completeness |
|---|---|---|---|
| resume `_pick_best` | `parsed.all_records` of a VALIDATED `HyperparamTuningOutput` (`core/resume.py:634-643`) | the OUTPUT's `metric_spec` (full spec, 09a) is in scope at the pool-construction site; records also carry `metric_result` (`metric_id` + `direction`, Step 06) | FULL identity present post-09a; `None` on legacy |
| dashboard / diagnostic scripts | summary JSON = FULL record dicts (`LocalRecorder.save_record` appends `safe_record` verbatim, `sandbox_executor.py:344-366`) | `metric_result.metric_id` + `metric_result.direction` per record | comparison identity (id+direction) present post-06; absent on legacy/unscored records |
| workflow sites 1–3 | the live `tune_output` + the bound composition | `tune_output.metric_spec` (full) + `bindings.task_composition.metric.spec` (full) | FULL |
| proposer `top_n` | interpretation evidence | `InterpretationOutput.metric_identity` (id + direction; confirmed present) | comparison identity |
| `per_file_best` | records + the module's imported metric id | `metric_result` per record; `TIDMAD_METRIC_ID` import | comparison identity |

**Conclusion (frozen)**: `metric_id` + `direction` is the minimum comparison
identity, it is ALREADY persisted everywhere a P2a consumer ranks, and
consumers read what is persisted — never re-derive. **No schema addition is
required and no second metric schema is invented.** Reconciliation (§4.1)
operates on these existing fields; the full-spec sources (output stamp,
bound composition) reconcile as full specs, and record-level consumers
reconcile on `(metric_id, direction)`.

The forward half of Q-10-2 (every newly persisted artifact carries enough
identity to rank) is **already satisfied**; P2a adds tests pinning it, not a
new field.

### 4.5 PROVISIONAL(P1) items — RESOLVED at `bcb17e45`

* **Workflow acquisition spelling**: the composed bound spec is
  `bindings.task_composition.metric.spec` (the workflow holds `bindings`;
  `RunTaskComposition.metric: EvaluationMetric` is P1-landed). The
  run-scoped seam `resolve_bound_run_metric()` also exists and is active for
  the whole composed region; the workflow uses the bindings spelling because
  it already holds the carrier, and either resolves to the SAME object.
* **Resume**: `restore_prior_state` needs NO new parameter — the pool is
  built from a validated `HyperparamTuningOutput` whose own `metric_spec`
  stamp is in scope at the ranking site (§4.4). Reconciliation happens over
  those stamps.
* **Q-P2a-2 RESOLVED (operator ruling 2026-08-20)**: ONE canonical
  metric-identity-unavailable message/formatter, owned **beside the shared
  reconciliation authority in `execute_tools/evaluation_metric.py`** —
  identity reconciliation and identity-unavailable representation belong
  together. Deliberately NOT in `MetricOrder`, which stays focused on
  ordering a known metric.

---

## 5. The structural scanner (replaces the presence list)

**Shape-based, allowlist-anchored, precision-first** (operator §8: no noisy
bans of all `>`):

* **Instrument**: extend the 09a-C3 approach (AST walk over production
  files) into a dedicated scanner test module owned by P2a.
* **What it flags**: `Compare(Gt|GtE|Lt|LtE)`, `sorted/list.sort` with
  `reverse=True`, and `max()/min()` whose operand expression mentions a
  **golden-score name**: `denoising_score`, `best_score`,
  `best_formal_denoising_score`, `best_valid_denoising_score`,
  `best_linear`, `score` when bound from a record's `denoising_score` key
  (dataflow-lite: same-function assignment tracking only — no
  interprocedural analysis).
* **What it must NOT flag** (precision contract, each with a pinned
  fixture): loss names (`*loss*`), runtime/memory/timing names, indices
  (`iter_idx`, `round_index`, `exp_id`), `abs(...)` magnitude filters, and
  comparisons against named constants.
* **Allowlist**: sites legitimately outside `MetricOrder` (the pinned §2.2
  set) are enumerated with reasons; the allowlist is the ONLY suppression
  mechanism, and an entry without a reason fails the scanner's own
  self-check.
* **Anti-vacuity, TWO plants required** (operator ruling 2026-08-20): a
  direct known-score-name offender (`if x["denoising_score"] > y: …`) AND a
  local alias/dataflow offender —

  ```python
  primary_score = record["denoising_score"]
  if primary_score > incumbent:
      ...
  ```

  — both must turn the scanner RED (recorded plant-and-catch). The alias
  plant is what proves the same-function assignment tracking is real rather
  than string matching. No cross-function dataflow is built or claimed.
* **Standing-guard claim, narrowed (frozen)**: the scanner is exhaustive for
  the CURRENT known primary-score carrier shapes (the golden-score name set
  + same-function aliases of a record's `denoising_score`) over the
  production surfaces P2a owns — including `workflows/task_composition.py`,
  which P1 added to the production set. It is NOT a guarantee over carrier
  shapes that do not yet exist: **introducing a future primary-score carrier
  shape REQUIRES extending the scanner's vocabulary/shape rules in the same
  change**, and the scanner module states this contract at its top.
* The old `NOT_REACHED_DIRECTION_CONSUMERS` rows are retired **by** the
  migration commits that empty them (each row's removal cites the commit),
  never deleted ahead of it.

---

## 6. Three-task acceptance (hand-computed, never code-derived)

| case | fixture | pinned expectation |
|---|---|---|
| TIDMAD negative-valued higher | scores `[-3.2, -1.4, -7.9]` | best `-1.4`, worst `-7.9`; incumbent advances on `-1.4 → -0.9`, not on `-1.4 → -2.0` |
| Pets higher | `[0.027, 0.61, 0.33]` | best `0.61`; `top_n(2)` = `{0.61, 0.33}` |
| DAVIS lower | `[0.0174, 0.0172, 0.0210]` | best `0.0172`; **`top_n(2)` = `{0.0172, 0.0174}` — the inversion test for site 10**; early-stop `target 0.0173` satisfied by `0.0172` (`is_at_least` under `lower`), not by `0.0174` |
| ties | equal scores | tie-breaks unchanged: lexicographic `exp_id` (site 4), earliest iteration (site 5) — asserted equal to pre-migration behaviour on the same fixture |
| refusal | spec-less record beside spec-carrying ones | Q-10-2 branch per §4.2, named string asserted verbatim |

Every expectation is a hand-computed literal in the test file.

---

## 7. Commit decomposition (SIX commits — RECONCILED against merged P1 and FROZEN; distinct failure classes, kept per operator ruling)

**Per-commit rules** (corrected 2026-08-20 — per-commit operator approval was
a process error): **semantic commits are autonomous** — before each commit,
inspect the diff scope, run the cheapest authoritative targeted validation,
update this ledger, commit if coherent; pause only for a genuine material
deviation or at the terminal READY FOR OPERATOR REVIEW. Targeted suites only;
ONE exact-head CI at the final head.

**Checklists start all-`[ ]`.** A `[x]` is written only after the change is
implemented AND verified, with the evidence recorded beside it. No item is
pre-checked and no evidence is invented ahead of the run.

**Ordering evidence rule, binding for every commit below**: an ordering
change is validated on the **actual visited comparison sequence** — the
ordered list of pairwise decisions a fixture drives — never on the final
winner alone. A wrong comparator can pick the right winner on a fixture whose
maximum is also its first element, and the TIDMAD-parity claim is worth
nothing if it only checks the endpoint.

**Line anchors**: verified at the P1 head `0f1e41d0` and RE-CONFIRMED at the
merged anchor **`bcb17e45`** (byte-identical production tree, §10.3). Sites
4–10 and both prose sites are at the exact lines §2.1 records; the three
workflow sites are at `:2744` / `:2756` / `:2804`.
`InterpretationOutput.metric_identity` (site 10's order source) is confirmed
present. Line numbers remain evidence, not implementation authority.

---

### C0 — the structural scanner + pre-migration ordering goldens

**1. Goal.** Build the instrument BEFORE migrating anything, and freeze what
the ten sites decide today. Two distinct problems: (a) `NOT_REACHED_DIRECTION_CONSUMERS`
is a presence list that names 4 of 10 code sites, so six surfaces — including
the chain incumbent and the proposer's top-N cut — are invisible to it
(§2.3); (b) "TIDMAD behaviour is unchanged" is unprovable after the fact
unless the pre-migration decision sequences are captured first. Both belong
here because every later commit is measured against them, and a scanner
written after a migration cannot distinguish a site that was migrated from
one that was never found.

**2. Scope.**
* NEW: a scanner test module owned by P2a (AST walk over the production file
  set, extending the 09a-C3 approach) + its precision fixtures.
* NEW: pre-migration ordering goldens for sites 1–5 (recorded decision
  sequences, not just winners).
* UNCHANGED: every production file. This commit edits no production source.
* Non-goal: retiring any `NOT_REACHED_DIRECTION_CONSUMERS` row — each row is
  retired BY the commit that empties it (§5), never ahead of it.
* Depends on: nothing (first commit).

**3. Implementation plan.**
- [x] Enumerate the production file set the scanner walks — it MUST include
      `workflows/task_composition.py` (P1-added, verified zero ordering
      shapes at `bcb17e45`) and `dashboard/` — and record the count.
      **DONE**: `PRODUCTION_DIRS` = the nine §10.3 directories (`agent`,
      `core`, `dashboard`, `execute_tools`, `ml_models`, `nodes`, `scripts`,
      `sdsc_submission_scripts`, `workflows`); **307 files** walked.
      `workflows/task_composition.py` is inside the walk and carries zero
      ordering shapes, confirming §10.3's finding independently.
      `test_the_scanner_reads_the_whole_production_tree` pins both the file
      floor and that EVERY declared directory produced files, so a collapsed
      walk cannot pass as a clean census.
- [x] State the standing-guard contract at the scanner module's top: it is
      exhaustive for the CURRENT known carrier shapes only, and a future
      primary-score carrier shape must extend it in the same change (§5).
      **DONE**: module docstring section *"The standing-guard contract
      (BINDING — read before extending anything)"*, naming the three explicit
      limits (no interprocedural analysis; one-hop shape-restricted aliasing;
      no coverage of shapes that do not yet exist).
- [x] Implement the flagged shapes: `Compare(Gt|GtE|Lt|LtE)`,
      `sorted`/`list.sort(reverse=True)`, and `max()`/`min()` whose operand
      mentions a golden-score name (`denoising_score`, `best_score`,
      `best_formal_denoising_score`, `best_valid_denoising_score`,
      `best_linear`, and `score` when bound from a record's
      `denoising_score` key — same-function assignment tracking only, no
      interprocedural analysis).
      **DONE**, with two bounded refinements recorded in §13.1:
      (a) `GOLDEN_SCORE_NAMES` also carries the three chain-level tracker
      names, without which sites 11/12 are invisible;
      (b) a sort/extremum is judged on its `key=` expression (or its
      positional operand when there is no `key`) rather than on `reverse=True`
      alone — an ASCENDING sort by a golden score is exactly as
      direction-bound as a descending one, and restricting to `reverse=True`
      would have left that shape unguarded.
- [x] Implement the allowlist with a MANDATORY reason per entry, and a
      self-check that fails on a reasonless entry.
      **DONE**: `PRECISION_EXCLUSIONS` — five entries (`loss`, `abs`, `len`,
      `authority_call`, `unkeyed_sort`), each with a stated reason;
      `test_every_allowlist_entry_carries_a_reason` fails on an empty reason
      AND on one shorter than 40 characters, so a placeholder reason is not a
      way past the self-check.
- [x] Self-calibrate: the scanner must report EXACTLY the §2.1 sites at the
      base. Record the byte-exact output in this ledger.
      **DONE — and this is where the surface turned out to be LARGER than
      §2.1 records.** Verbatim output in §13.1; **12 code sites**, not 10.
      The two extra are `core/resume.py:1314` and `:1324`. See §13.1 for the
      audit and the bounded-deviation classification.
- [x] Capture pre-migration goldens: for each of sites 1–5, a fixture
      sequence and the ordered list of pairwise decisions it produces.
      **DONE**: `tests/unit/execute_tools/test_step10_p2a_c0_ordering_goldens.py`
      + the frozen manifest
      `tests/unit/execute_tools/goldens/step10_p2a_c0_ordering_sequences.json`
      (stamped with the capture commit). Sites 4 and 5 are captured by
      EXECUTING the current production functions (`_pick_best` over growing
      prefixes; `_row_beats` pairwise over nine probes covering every tie
      class); sites 1–3 are inline folds not callable in isolation at the
      base, so their goldens are hand-computed trajectories PLUS the
      direction-blind counterfactual trajectory the raw comparator produces
      on the same DAVIS input. Every expectation is a hand-computed literal;
      the production capture is the cross-check, and it agreed on the first
      run.
- [x] Plant-and-catch, TWO plants (§5): a direct raw `>` on
      `denoising_score` in a scratch production module, AND the local-alias
      offender (`primary_score = record["denoising_score"]` then
      `primary_score > incumbent`). Both RED; revert; record. The alias
      plant proves same-function assignment tracking is real.
      **DONE** — both RED, each naming exactly one offender; scratch module
      deleted and the census green again. Transcript in §13.1.

**4. Validation plan.**
* Unit: one precision fixture per §2.2 class the scanner must NOT flag —
  loss names, runtime/memory/timing extrema, index and `exp_id` tie-breaks,
  `abs(...)` magnitude filters, comparisons against named constants.
* Unit: one detection fixture per flagged shape.
* Negative/invalid: an allowlist entry with no reason ⇒ the scanner's own
  self-check fails; a malformed production file ⇒ the scanner reports the
  file rather than silently skipping it (a skipped file is an invisible
  site).
* Backward-compat / parity: N/A — no production change. The goldens
  CAPTURED here are what later commits compare against.
* Real-training Gate: **NONE. Not required and must not be launched.**

**5. Acceptance criteria.**
- [x] Scanner output at base == the §2.1 site list EXACTLY: 10 code sites,
      0 unexpected, 0 missing. The list is recorded verbatim in the ledger.
      **MET WITH A CORRECTION, recorded rather than absorbed**: the scanner
      reports the ten §2.1 code sites AND two more the frozen table does not
      name (`core/resume.py:1314`, `:1324`). 0 unexpected after audit, 0
      missing. The criterion's INTENT — the census is exact in both
      directions and every row is accounted for — is met by
      `EXPECTED_ORDERING_SURFACE`, which carries all twelve rows with their
      migrating commit. The literal "10" is superseded by measurement; §13.1
      records the audit that establishes the two extra rows are genuine
      golden-metric ordering decisions and not scanner noise.
- [x] Every §2.2 precision fixture is NOT flagged (asserted individually, so
      a regression names which class broke).
      **DONE**: twelve individually-named precision tests in
      `TestThePrecisionContract` — loss names (two: a `final_loss` extremum
      and the live `min(same_loss_finals)` pin), runtime/memory extrema,
      `iter_idx`/`exp_id` tie-breaks, `round_index`, `abs(...)` magnitude
      filters, an `abs`-bound distance ALIAS, a count cap against a named
      constant, an unkeyed `sorted(names)`, a golden name inside a comment
      and a string, the authority's own calls, and a local `score` bound from
      a non-golden source.
- [x] The planted raw `>` turns the scanner RED, and its removal turns it
      green again — both recorded.
      **DONE** for BOTH plants; transcript and the green-after-revert run in
      §13.1.
- [x] Goldens for sites 1–5 record the DECISION SEQUENCE (ordered pairwise
      outcomes), not only the selected element.
      **DONE**: site 4 = the incumbent `exp_id` after each prefix
      (`('exp_a','exp_b','exp_b')` TIDMAD; `('exp_m','exp_b','exp_b')` tie);
      site 5 = the ordered nine-element boolean verdict list; sites 1–3 = the
      decision list AND the trajectory it folds to, under all three tasks
      plus the direction-blind counterfactual. `_fold` cross-checks that each
      decision list and its trajectory describe the same fold, so a
      transcription slip in the literals fails here rather than becoming a
      golden that C1 faithfully reproduces while both are wrong.
- [x] Zero production files changed in this commit (`git diff --stat`
      recorded).
      **DONE**: `git diff --stat 64446b2b` is EMPTY. `git status --short`
      shows three untracked files, all under `tests/unit/execute_tools/`.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| a production file fails to parse | scanner REPORTS it (fail-closed); a silently skipped file is an invisible site |
| a golden-score name appears in a comment or string | NOT flagged — the census is AST-shaped (the parent's §3.8 anti-vacuity lesson) |
| `score` bound from something other than a record's `denoising_score` | NOT flagged; dataflow-lite is same-function only, and the limit is stated rather than approximated |
| a site legitimately outside `MetricOrder` | allowlisted WITH a reason; a reasonless entry fails the self-check |

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest <scanner test module> -q` — record count + wall time.
      **`tests/unit/execute_tools/test_step10_p2a_c0_ordering_scanner.py`
      + `..._c0_ordering_goldens.py` + the existing
      `test_step06_c5_boundary_and_structure.py` (the presence list this
      eventually replaces, run to prove C0 does not disturb it):
      64 passed in 4.41s, exit 0.**
- [x] Scanner base output — record verbatim. **§13.1.**
- [x] `git diff --stat` — record (must show no production file). **EMPTY.**
- [x] `ruff check` + `ruff format --check` on touched files.
      **`All checks passed!` / `2 files already formatted`.**
- [x] pyright on the touched files — **NOT RUN LOCALLY, and not claimed.**
      The vendored pyright 1.1.409 cannot start under this machine's Node
      `v10.19.0` (`SyntaxError: Unexpected token =` from `vendor.js`). Per the
      repository's environment-assumptions rule this check is CI-owned for
      this PR; it is NOT reported as locally green.

**8. Commit boundary.** Test-only; independently reviewable as "the
instrument and the baseline". No production migration, no presence-list
retirement, no unrelated cleanup. Before committing: show the diff summary,
staged file list, test counts, and any deviation from this plan.

---

### C1 — reconciliation authority promotion + in-run sites (1, 2, 3)

**1. Goal.** The three decisions a LIVE run makes about the golden metric —
raw-formal best tracking, chain formal incumbent advance, and the
`target_score` early stop — stop assuming higher-is-better. These three
belong together because they share one new rule (§4.1's **metric-identity
reconciliation rule**) and one refusal branch; splitting them would leave an
intermediate head where a run advances its incumbent by one direction rule
and stops early by another.

*(Wording corrected post-implementation: rev 1/2 called this "acquisition
precedence". Revision 3's whole point is that acquisition is
**RECONCILIATION, not precedence** — a bound spec is an authoritative INPUT,
never permission to shadow a conflicting artifact stamp. The frozen ruling in
§4.1 was already correct; this sentence had not been updated to match it.)*

**2. Scope.**
* `workflows/model_exploration.py` — sites 1–3 (at the P1 head: `:2744`,
  `:2756`, `:2804`; re-verify at the true base).
* The §4.1 reconciliation call and the shared Q-10-2 refusal notice.
  **Owner (frozen, Q-P2a-2 / Q-P2a-3): `execute_tools/evaluation_metric.py`,
  beside `MetricSpec` and the metric-identity semantics** — NOT beside
  `MetricOrder`, which owns ordering only. *(Rev 1/2 floated "a small
  function beside `MetricOrder`" as a placement candidate; Revision 3
  resolved it the other way, and §4.5/§4.1a are the binding text. Delivered
  as `reconcile_metric_specs` / `reconcile_metric_identity` and
  `metric_identity_unavailable_notice`, all in `evaluation_metric.py`.)*
* UNCHANGED: tie-break rules, validity filters, the round/retry semantics,
  every non-golden comparison in the same functions, and all LLM-facing
  bytes (these three sites feed no prompt).
* Depends on: C0 (goldens + scanner).

**3. Implementation plan.**
- [x] Re-verify the three line anchors and read each comparison in full
      before editing. **DONE** — `:2744` / `:2756` / `:2804` at the base,
      exactly as §2.1 records; each read in full context first.
- [x] **PROMOTE the reconciliation authority first (Q-P2a-3)**: move
      `reconcile_metric_spec`'s semantics from
      `nodes/result_interpretation_agent/evidence.py:58` to
      `execute_tools/evaluation_metric.py`, generalized to accept the
      available identities (bound spec and/or stamped specs); the
      interpreter node imports the shared authority; its refusal semantics
      (partial stamping ⇒ refuse, mixed ⇒ refuse) preserved EXACTLY; a
      census pins exactly ONE reconciliation implementation.
      **DONE** — see §13.2 for the signature decision. The shared authority
      is `reconcile_metric_specs(stamped, *, bound=None, bound_label=...)`
      over `StampedMetricSpec(label, spec)` pairs, raising
      `MetricIdentityConflictError`. **Semantics preserved is MEASURED, not
      asserted**: the 28 pre-existing tests in
      `test_step09a_c2_metric_spec_contract.py` pass UNCHANGED, including the
      ones matching refusal message text verbatim.
- [x] Implement §4.1 reconciliation at sites 1–3: collect bound
      (`bindings.task_composition.metric.spec`) + the compared output's
      stamp → reconcile → `MetricOrder`; bound-vs-stamp CONFLICT fails
      closed; nothing available ⇒ §4.2 unrankable branch.
      **DONE** — `_acquire_iteration_order(bindings, tune_output)` in
      `workflows/model_exploration.py`, called ONCE per iteration so all three
      decisions rank on the same metric by construction.
- [x] Implement the canonical metric-identity-unavailable message/formatter
      beside the reconciliation authority (Q-P2a-2); every consumer renders
      THIS formatter's output.
      **DONE** — `METRIC_IDENTITY_UNAVAILABLE` (the parent's frozen Q-10-2
      phrasing) + `metric_identity_unavailable_notice(context, detail=...)`
      in `execute_tools/evaluation_metric.py`. Pinned NOT to live in
      `MetricOrder` by `test_the_notice_is_not_defined_in_metric_order`.
- [x] Migrate site 1 and site 2 to `order.is_better`, site 3 to
      `order.is_at_least`. **DONE.**
- [x] Implement the workflow refusal branch: skip the update, print the
      named notice once per run, never assume a direction.
      **DONE**, with one bounded semantic decision recorded in §13.2: the
      unrankable branch skips the BOOTSTRAP too, not merely the comparison.
- [x] Update the scanner allowlist / expected set in the SAME commit, and
      retire the `NOT_REACHED_DIRECTION_CONSUMERS` rows these three sites
      empty, each citing this commit.
      **DONE** — the three rows moved from `EXPECTED_ORDERING_SURFACE` to
      `MIGRATED_SITES` (each recording the before → after transition), and
      the `workflows/model_exploration.py` row moved from
      `NOT_REACHED_DIRECTION_CONSUMERS` to `MIGRATED_TO_THE_ORDER_AUTHORITY`
      in `test_step06_c5_boundary_and_structure.py`, following that file's
      own established convention (retire by MOVING, so the guard inverts and
      the migration leaves a trace, rather than by deleting).

**4. Validation plan.**
* Unit: the §4.1 truth table — all SIX rows (bound+same, bound+absent,
  bound+CONFLICT, unbound+all-same, unbound+all-absent,
  unbound+conflicting), asserting WHICH spec was used or WHICH refusal
  fired, not merely that a comparison happened.
* Unit: single-authority census — the promoted function is the only
  reconciliation implementation; the node imports it; a planted second
  implementation turns the census RED.
* Integration/pseudo: a pseudo-mode loop segment driven by the three-task
  fixtures (§6), asserting the incumbent trajectory.
* Negative/invalid: spec-less record beside spec-carrying ones ⇒ the refusal
  branch fires with the verbatim named string; mixed specs ⇒ the existing
  `reconcile_metric_spec` failure surface, unchanged.
* Backward-compat / parity: the TIDMAD fixture's **visited decision
  sequence** is byte-equal to the C0 golden — every pairwise outcome, in
  order, not just the final incumbent.
* Real-training Gate: **NONE. Not required; must not be launched.**

**5. Acceptance criteria.**
- [x] DAVIS fixture (`lower`): the incumbent advances on a DECREASE
      (`0.0174 → 0.0172` advances; `0.0172 → 0.0210` does not), and the
      recorded decision sequence matches the hand-computed literal exactly.
      **DONE** — `test_davis_lower_advances_on_a_DECREASE`: decisions
      `(True, True, False)`, trajectory `(0.0174, 0.0172, 0.0172)`, final
      `0.0172`. Paired with
      `test_davis_no_longer_produces_the_direction_blind_trajectory`, which
      asserts the result is NOT the C0-frozen counterfactual
      `(0.0174, 0.0174, 0.0210)` — so the commit is shown to have CHANGED
      behaviour, not merely to still pass.
- [x] TIDMAD fixture (`higher`, negative values): decision sequence
      byte-equal to the C0 golden.
      **DONE** — decisions `(True, True, False)`, trajectory
      `(-3.2, -1.4, -1.4)`, both compared against the C0 constants by import
      rather than by restatement.
- [x] `target_score` under `lower`: `0.0172` satisfies `target 0.0173`;
      `0.0174` does not. **DONE** —
      `test_davis_target_is_satisfied_by_the_smaller_score`, plus a TIDMAD
      counterpart and an exact-hit case under BOTH directions.
- [x] Refusal: the named notice string appears VERBATIM, fires once per run,
      and the tracker is left unchanged (asserted on the tracker, not only on
      stdout).
      **DONE** — `test_it_prints_once_and_records_every_affected_context`
      asserts the canonical phrase appears EXACTLY once across three
      unrankable iterations and that all three are still counted. The
      tracker-unchanged half is asserted structurally: the production branch
      cannot reach either assignment when `_iter_order is None`, and
      `test_no_identity_anywhere_yields_the_unrankable_state` pins that the
      acquisition returns `None` in that state.
- [x] The scanner no longer reports sites 1–3 and still reports the rest.
      **DONE** — census went 12 → 9; the three `workflows/model_exploration.py`
      rows are gone and every other row is still reported.
      `test_no_retired_site_is_still_live` pins that a retirement corresponds
      to a real migration, and `test_the_whole_surface_is_accounted_for` pins
      pending + retired == 12 so the total cannot drift.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| legacy record with no `metric_spec` | skip the update + named notice; never assume a direction; never hard-fail the run |
| mixed specs across compared artifacts | existing `reconcile_metric_spec` refusal, unchanged — P2a adds no second reconciliation |
| `None` / NaN scores | existing validity filters run BEFORE ordering and are not weakened |
| composed run whose bound spec disagrees with an artifact stamp | fail closed through the existing reconciliation; do NOT silently prefer one |

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/workflows -q` — record count + wall time.
      **Run WIDER than planned**, because the promotion changes a module four
      areas import:
      `pytest tests/unit/execute_tools tests/unit/workflows
      tests/unit/agent/result_interpretation_agent tests/unit/nodes -q`
      → **2736 passed, 1 skipped, 0 failed in 151.20s**, exit 0 (verdict read
      from the log, not from the wrapper's status).
- [x] The three-task fixture module — record count.
      **`tests/unit/execute_tools/test_step10_p2a_c1_reconciliation.py`:
      31 passed in 1.86s.**
- [x] Decision-sequence goldens — record the compared literals.
      TIDMAD `(True, True, False)` / `(-3.2, -1.4, -1.4)`;
      Pets `(True, True, False)` / `(0.027, 0.61, 0.61)`;
      DAVIS `(True, True, False)` / `(0.0174, 0.0172, 0.0172)`;
      DAVIS direction-blind counterfactual `(0.0174, 0.0174, 0.0210)`,
      asserted NOT produced.
- [x] Any command that could not be run — record WHY; never claim it passed.
      **pyright**: not runnable locally (Node `v10.19.0`); CI-owned, unchanged
      from C0 and NOT claimed green.

**8. Commit boundary.** Sites 1–3 + the shared acquisition/refusal helper +
the census rows those sites empty. No dashboard, no scripts, no proposer, no
resume. Before committing: show the diff summary, staged files, test counts,
and deviations.

---

### C2 — resume `_pick_best` + `per_file_best._row_beats` (sites 4, 5)

**1. Goal.** Two selection helpers whose comparison is direction-dependent
but whose TIE rules are not. They share a hazard: each is a small pure
function with rich tie-breaking, so a careless migration silently changes tie
behaviour while looking like a one-line change.

**2. Scope.**
* `core/resume.py::_pick_best` (`:441-455`, `>` at `:451` — verified).
* `execute_tools/per_file_best.py::_row_beats` (`:481-490`, `>` at `:483` —
  verified).
* UNCHANGED and asserted: lexicographic `exp_id` tie-break (site 4);
  earliest-iteration, persisted-over-legacy and round-index tie-breaks
  (site 5); the caller walks; the restore soft-fail policy.
* Depends on: C0 goldens, C1's shared refusal helper.

**3. Implementation plan.**
- [x] Read both functions in full, including every tie-break branch below
      the score comparison. **DONE** — `_pick_best` (`:441-455`) and
      `_row_beats` (`:481-497`), plus `_pick_best`'s single caller
      `_candidates_from_persisted_verdicts` (`:643`) and both `_consider`
      call sites.
- [x] Migrate ONLY the score comparison in each; leave every tie branch
      textually untouched. **DONE** — the four `_row_beats` tie branches and
      `_pick_best`'s `exp_id` branch are byte-unchanged; parity measured per
      tie class (see §13.3).
- [x] Site 4, per §4.2a (PER-RECORD, not per-iteration): rank the
      compatible-identity subset; missing-identity records individually
      excluded with the named state; no rankable records ⇒ no incumbent +
      named notice, restore continues; conflicting KNOWN identities ⇒ fail
      closed per the existing restore soft-failure policy. The identity
      inputs are the output's own `metric_spec` stamp + per-record
      `metric_result`, reconciled through the SHARED authority.
      **DONE** — `_rankable_pool(records, parsed, *, context)`. Required
      splitting the ONE reconciliation engine across two granularities
      (record `(id, direction)` vs full spec) WITHOUT creating a second
      implementation; see §13.3's engine decision. Two findings recorded
      there: F-P2a-1 (the Step-06 boundary guard caught a duplicated
      direction vocabulary in P2a's own first draft) and F-P2a-2 (the
      existing resume suite cannot see this path at all — 134 calls, 0
      reaching `_pick_best`, still green).
- [x] **ADDED (deviation D-P2a-1): the two chain-fold sites**
      (`core/resume.py:1314`, `:1324`) migrate here too — same file, same
      responsibility, and the chain fold consumes `_pick_best`'s result one
      level up. `_chain_fold_order(parsed)` reconciles per iteration from
      that iteration's output stamp; an unstamped output is a NAMED refusal
      that leaves the chain incumbent untouched rather than advancing it on
      an assumed direction.
- [x] Site 5, per the §4.3 ruling: migrate the score comparison to
      `MetricOrder`; document the CURRENT transform's monotonicity beside
      the site and pin it with a hand-computed fixture (linear ranking ==
      log ranking for `_log` base 5.27 on TIDMAD-shaped values). NO generic
      monotonicity assertion is added — a future non-monotone display
      transform is a named future capability requirement of the metric
      interface, recorded, not faked here.
      **DONE** — the ruling is written into `_row_beats`'s docstring, and
      `TestTheCurrentTransformIsMonotone` pins `LOG_BASE == 5.27 > 1`, the
      pairwise linear==log equivalence, and a demonstration that a base
      below 1 would invert. No generic capability is claimed.
- [x] Retire the census rows these two sites empty, citing this commit.
      **DONE** — four rows (not two: the chain fold added two), moved to
      `MIGRATED_SITES` and `MIGRATED_TO_THE_ORDER_AUTHORITY`.

**4. Validation plan.**
* Unit: both helpers under `higher` and `lower` fixtures, asserting the
  selected record AND the visited comparison sequence.
* Unit: every tie class, asserted byte-equal to the C0 golden.
* Negative/invalid: resume fixture with (a) all specs absent, (b) some
  absent, (c) mixed specs.
* Backward-compat / parity: TIDMAD fixtures produce byte-identical
  selections and tie outcomes.
* Real-training Gate: **NONE.**

**5. Acceptance criteria.**
- [x] Under `lower`, `_pick_best` selects the MINIMUM and `_row_beats`
      prefers the smaller `best_linear`.
      **DONE** — the TIDMAD pool `[a:-3.2, b:-1.4, c:-7.9]` gives trajectory
      `('exp_a','exp_b','exp_b')` under `higher` and
      `('exp_a','exp_a','exp_c')` under `lower`, asserted to DIFFER so the
      fixture is proven discriminative; `_row_beats(4.0 vs 9.0)` is `True`
      under `lower` and `False` under `higher`.
- [x] Every tie fixture's outcome is byte-equal to its C0 golden, asserted
      per tie class so a regression names which rule broke.
      **DONE** — all nine `ROW_BEATS_PROBES` reproduce under `higher`
      (mismatches reported BY NAME), and the seven direction-independent
      probes are separately asserted IDENTICAL under `lower` while exactly
      the two score probes invert. `_pick_best`'s tie trajectory is equal
      under both directions.
- [x] Resume four-case matrix (§4.2a): all-known ranks; known+missing ranks
      the known subset and excludes the missing rows INDIVIDUALLY;
      all-missing restores no incumbent with the named notice and the
      restore continues; conflicting-known fails closed per the existing
      soft-failure policy — each case asserted on the restored incumbent,
      not on stdout alone.
      **DONE** — `TestTheResumeIdentityMatrix`, six cases. Case B is the
      sharp one: the identity-less row carries the numerically BEST score
      (`-0.1`) and must still lose, which is asserted on the selected
      record rather than on the notice.
- [x] The site-5 monotonicity fixture pins linear-order == log-order for the
      CURRENT transform with hand-computed literals.
      **DONE** — `_log(1.0) == 0.0`, `_log(5.27) ≈ 1.0`, pairwise
      equivalence over six hand-chosen values, and a base-0.5 demonstration
      that the property is specific to THIS base.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| all records spec-less | no incumbent restored; named notice; restore continues (never a hard failure) |
| SOME records spec-less | the compatible subset is ranked; missing rows are individually unranked — one legacy row never poisons the corpus (§4.2 case B) |
| conflicting KNOWN identities in one pool | fail closed per the existing restore soft-failure policy; never a silent pick (§4.2 case D) |
| equal scores | existing tie-break, unchanged and asserted |
| legacy rows with no round provenance | existing persisted-over-legacy rule, unchanged |
| non-monotone linearization | **NOT detected, and deliberately so** (§4.3, §9). No generic monotonicity guard exists; what is tested is that the CURRENT transform is monotone. A future non-monotone display transform is a future metric-interface capability requirement, not something P2a catches. *(Rev 1/2 claimed "the site-5 assertion FAILS LOUDLY" — corrected post-implementation; that assertion was never built, because building it would have been the fake generic guard §4.3 rejects.)* |

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/core/test_resume.py tests/unit/execute_tools -q -k "best or resume"` — count + wall time.
      **Run WIDER**, because C2 touches `evaluation_metric`, `resume` and
      `per_file_best`, which `scripts/` also consumes:
      `pytest tests/unit/execute_tools tests/unit/core tests/unit/workflows
      tests/unit/scripts -q` — result recorded in §13.3.
      Focused runs: C2 module **29 passed in 1.36s**; C2 module + both
      censuses **83 passed in 6.17s**;
      `test_per_file_best.py` + `test_resume.py` **89 passed in 1.56s**.
- [x] Tie-class golden comparison — record per class. **Recorded in §13.3**
      ("Tie parity — measured per class"): 9/9 reproduce under `higher`;
      7 direction-independent probes identical under `lower`; exactly 2
      score probes invert.
- [x] Reachability probe — **ADDED, not in the original plan.** Measured that
      the pre-existing resume suite reaches `_pick_best` ZERO times after
      this change and stays green (finding F-P2a-2), which is why C2 adds
      `TestTheResumePathIsActuallyReached`.

**8. Commit boundary.** Two helpers + their census rows. No consumer of
either is modified. Show diff summary, staged files, counts, deviations
before committing.

**ACTUAL boundary**: four sites, not two — the two D-P2a-1 chain-fold sites
are in the same file and the same responsibility, and splitting them out would
have left an intermediate head where resume ranked one level by direction and
the level above it by a raw `>`. The reconciliation engine also gained its
record-granularity entry point here, because that is the commit that first
needs it.

---

### C3 — artifact consumers: dashboard + diagnostic scripts (sites 6–9, prose P-1/P-2)

**1. Goal.** Consumers that read PERSISTED artifacts, where the run that
produced them is long gone. They share one order source (persisted identity,
§4.4) and one display contract (Q-10-2's visible refusal), which is why they
are one commit.

**2. Scope.**
* `dashboard/data_sources/local_json.py` — site 6 (`:245`, `reverse=True`)
  and site 7 (`:194-197`, the `score > best_score` scan feeding
  `best_agent_score` / `best_run_name`).
* `scripts/build_diagnostic_summary.py:113` and
  `scripts/finalize_recovered_diagnostic_round.py:233` (both `max(...)`).
* Prose: `dashboard/data_sources/base.py:119`, `dashboard/api/router.py:234`
  — both currently say "higher is better" literally.
* UNCHANGED: raw scalar display, record schemas, API response shape apart
  from the documented unavailable-state string.
* Depends on: C1's refusal-notice constant (Q-P2a-2).

**3. Implementation plan.**
- [x] Read each of the four call sites and confirm which persisted field
      carries identity for that corpus (`metric_result.direction` on records;
      `metric_spec` on outputs — §4.4).
      **DONE** — all four read RECORD dicts, so `metric_result` is the only
      identity available at every one of them (the dashboard reads
      `summary_*.json` record arrays, never outputs). Confirmed on disk
      before editing.
- [x] Migrate ranking/extrema to `MetricOrder` built from persisted
      identity. **DONE** via the shared `execute_tools/persisted_ranking.py`;
      required deviation **D-P2a-4** (§13.4) because `MetricOrder` accepted
      only a full `MetricSpec` while §4.4 says these consumers hold only
      `(id, direction)`.
- [x] Implement the §4.2 four-case display semantics PER ARTIFACT: the
      compatible subset ranks; each missing-identity row shows the canonical
      unavailable state (Q-P2a-2 formatter) and no rank, raw scalar still
      shown; all-missing shows no ranking; conflicting-known refuses the
      ranking view with the named diagnostic. One legacy row never poisons
      the corpus.
      **DONE** — the per-consumer matrix is tabulated in §13.4 and asserted
      end to end over real temp workspaces.
- [x] Replace both prose sites with direction-aware text.
      **DONE.** *Deviation (bounded, wording only)*: the plan said
      "`direction_words`-derived". Both sites are STATIC docstrings on an
      abstract method and a FastAPI route — neither has a `MetricOrder` in
      scope, and neither renders per-request. Rendering `direction_words`
      there would have required constructing an order per corpus purely to
      format a docstring, which is not what those strings are. They now
      state that ranking follows the metric each record DECLARES — the same
      guarantee, expressed where no order object exists. `direction_words`
      remains available and unused-by-these-two.
- [x] Retire the census rows these sites empty, citing this commit.
      **DONE** — four rows retired; `NOT_REACHED_DIRECTION_CONSUMERS` is now
      EMPTY, and the Step-06 live-route census moved `local_json.py` into
      `MIGRATED_CONSUMERS`.

**4. Validation plan.**
* Unit: dashboard data-source tests over three corpora — `higher`, `lower`,
  and absent-identity.
* Unit: both scripts over fixture record sets, same three corpora.
* Negative/invalid: a corpus MIXING identities ⇒ fail closed, not "pick the
  first"; a record with identity but a `None` score ⇒ existing filter.
* Backward-compat / parity: a TIDMAD corpus produces byte-identical ranking
  and byte-identical prose to pre-migration (the prose parity matters — these
  strings are operator-facing).
* Real-training Gate: **NONE.**

**5. Acceptance criteria.**
- [x] `lower` corpus ranks ASCENDING and `best_agent_score` is the MINIMUM.
      **DONE** — DAVIS `[0.0174, 0.0172, 0.0210]` returns
      `[0.0172, 0.0174, 0.0210]` with `rank == 1` on the first, and
      `best_agent_score == 0.0172`. `best_run_name` is asserted separately so
      it cannot drift from the score it names.
- [x] Mixed corpus (case B): the known-identity rows rank; the absent row is
      individually unranked with the canonical state; the ranked rows'
      order is unaffected by the absent row's scalar.
      **DONE** — and the absent row carries `99.0`, the numerically LARGEST
      score in the corpus, so a consumer that ranked it anyway fails on the
      result rather than merely on a missing notice.
- [x] All-absent corpus (case C) renders the canonical unavailable state,
      shows NO rank, and still displays raw scalars.
      **DONE** — both rows returned, `rank is None` on each, note on each,
      raw scores `{-3.2, -1.4}` still present.
- [x] Conflicting corpus (case D) refuses with the named diagnostic and
      ranks nothing across the conflict.
      **DONE** — the diagnostic names BOTH metric ids.
- [x] TIDMAD corpus: ranking order and prose byte-identical to pre-migration.
      **Ranking: DONE** — the TIDMAD corpus (including the negative regime)
      returns `[-1.4, -3.2, -7.9]`, and the pre-existing
      `tests/unit/dashboard/test_local_json.py` suite passes with its
      assertions unchanged. **Prose: DELIBERATELY NOT byte-identical** — the
      two prose sites are the P-1/P-2 surfaces this commit exists to change;
      their old sentence stated a direction true only of TIDMAD, and its
      ABSENCE is now the assertion.
- [x] No prompt template or LLM-facing byte changes (pinned by grep — these
      are dashboard/API strings, not prompts).
      **DONE** — `git diff --stat HEAD -- agent/prompt_templates/ nodes/` is
      EMPTY for this commit.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| corpus mixing two KNOWN metric identities | fail closed with a named diagnostic; never rank across incomparable metrics (§4.2 case D) |
| corpus mixing known + ABSENT identity | rank the known subset; the absent rows are individually unranked (§4.2 case B) — absence is not a conflict |
| record with identity, score `None` | existing filter; not a refusal case |
| empty corpus | current behaviour preserved |
| legacy pre-06 records (no `metric_result`) | Q-10-2 refusal path, not an exception |

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/dashboard tests/unit/scripts -q` — count + wall time.
      Focused: C3 module + `tests/unit/dashboard` + both Step-06 censuses —
      **99 passed, 1 skipped in 4.47s**. C3 module alone: **22 passed**.
      Broad regression recorded in §13.4.
- [x] Prose parity grep — record the compared strings.
      The retired sentence, asserted ABSENT from both files:
      `"ranked by denoising_score descending (higher is better)"`.
      Present instead: *"ranked best-first on the metric the records
      DECLARE they were scored under"* (`base.py`) and *"the ordering
      direction comes from each record's persisted metric identity rather
      than being assumed"* (`router.py`).

**8. Commit boundary.** Read-only artifact consumers + their prose. No
in-run behaviour, no proposer. Show diff summary, staged files, counts,
deviations before committing.

**ACTUAL boundary**: as planned, PLUS one new shared module
(`execute_tools/persisted_ranking.py` — the alternative was three copies of
the same fail-closed rule) and one annotation on `MetricOrder`
(deviation D-P2a-4). No in-run behaviour, no proposer, no prompts.

---

### C4 — proposer `top_n` (site 10)

**1. Goal.** The one site where a wrong direction changes what the SYSTEM
DOES rather than what it displays: under a `lower` metric,
`scored.sort(key=..., reverse=True)` at `nodes/proposal_helpers.py:88`
selects the WORST N candidates and hands them to the proposer as the best.
Its own commit because it is the only behaviour-changing consumer and it
carries the one open question (Q-P2a-1).

**2. Scope.**
* `nodes/proposal_helpers.py:84-89` — the `top_n` branch only.
* Order source: the interpretation evidence's metric identity
  (`InterpretationOutput.metric_identity` — **confirmed present**), which the
  proposer today never reads.
* UNCHANGED: the `all` method (which the fallback REUSES); the reader
  architecture (that is P3 — this commit changes ONE helper's comparison);
  every prompt template.
* Depends on: C1's promoted reconciliation + canonical formatter.
* **Q-P2a-1 RESOLVED (operator ruling 2026-08-20)**: identity unavailable ⇒
  the named notice fires and the helper takes the EXISTING order-free `all`
  path, under whatever independent safety/token bounds that path already
  owns. No new "first N by declaration order" policy — that would be a new
  selection policy owned by P2a for no scientific reason. The result is
  never labelled "top N"/"best N"/"best candidates".

**3. Implementation plan.**
- [x] Read the full strategy helper, including the `all` branch and every
      caller, before editing. **DONE** — one production caller,
      `ml_model_proposal_agent.py:1602`:
      `select_candidate_models(inp.interpretation, pipeline.model_selection)`.
- [x] Thread the evidence's metric identity to the helper WITHOUT building a
      typed reader (P3's scope) — record exactly how, so P3 can replace the
      mechanism without re-litigating the semantics.
      **DONE, and the answer is that NO threading was required.** The helper
      already receives the whole serialized `InterpretationOutput`, and
      `metric_identity` (Step 09a's ordering PROVENANCE) has been sitting in
      that dict all along — the proposer simply never read it. C4 therefore
      adds a READ, not a parameter, not a call-site argument, not a reader.
      Recorded at `_interpretation_order`'s docstring as an explicit note to
      P3: supply the same identity through the typed reader and delete that
      function; the semantics to preserve are "read the declared identity,
      never assume a direction, fall back to order-free `all` when absent".
      Pinned by `test_the_helper_signature_did_not_change`.
- [x] Migrate the cut to `MetricOrder`. **DONE** — `sorted(key=order.rank(...))`,
      which needs no second reading of `direction` and keeps ties in
      discovery order exactly as the stable `reverse=True` sort did.
- [x] Implement the absent-identity branch per the RESOLVED Q-P2a-1: named
      notice → the existing `all` semantics. NO metric-based ranking
      happens; the result is never labelled "best"/"top N"; no new
      selection policy is introduced. **DONE.**
- [x] Retire the census row this site empties, citing this commit.
      **DONE — and it was the LAST one.** `EXPECTED_ORDERING_SURFACE` is now
      EMPTY: the production ordering surface reports **0 sites**.

**4. Validation plan.**
* Unit: the DAVIS worst-N inversion test — the parent's named executable
  requirement (§11.3) — with hand-computed literals.
* Unit: Pets and TIDMAD fixtures produce the SAME cut as pre-migration.
* Negative/invalid: absent identity ⇒ the Q-P2a-1 branch; fewer candidates
  than `n`; all scores `None`; empty candidate set.
* Backward-compat / parity: under `higher`, the returned candidate LIST is
  byte-equal to pre-migration, including order.
* Real-training Gate: **NONE.** Gate 1 is NOT proposed for this child (§0);
  if the disposition of Q-P2a-1 turned out to require real-LLM evidence,
  that is a scope change requiring operator approval, not an autonomous run.

**5. Acceptance criteria.**
- [x] DAVIS `[0.0174, 0.0172, 0.0210]`, `top_n(2)` returns exactly
      `{0.0172, 0.0174}` — the inversion this commit exists to fix.
      **DONE** — returns `["b", "a"]` = `{0.0172, 0.0174}`. Asserted three
      ways: the selected pair; that the WORST model (`0.0210`) is absent; and
      that the result DIFFERS from the hand-computed pre-migration cut
      `["c", "a"]`, so the fix is shown to have moved something.
- [x] Pets `[0.027, 0.61, 0.33]`, `top_n(2)` returns exactly `{0.61, 0.33}`.
      **DONE** — `["good", "mid"]`.
- [x] TIDMAD fixture: returned list byte-equal to pre-migration, in order.
      **DONE** — asserted equal to `sorted(..., reverse=True)` over the full
      set, in the negative-value regime.
- [x] Absent identity: the named notice fires, the returned candidate set
      IS the existing `all` path's result (asserted equal against a direct
      `all` invocation on the same fixture), and nothing labels it
      "best"/"top N" anywhere it is rendered.
      **DONE** — equality against a direct `all` invocation; the result has
      **3** entries where `n=2`, which is what distinguishes the ruled
      behaviour from the REJECTED first-N policy; the notice contains the
      canonical phrase and "NOT ranked"; and no returned candidate carries a
      `rank` or any `top_`/`best_n` key. A malformed direction and a missing
      `metric_id` take the same fallback rather than guessing.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| absent metric identity | named notice + the EXISTING `all` semantics (Q-P2a-1 RESOLVED); never a silently inverted cut; never a first-N cut wearing a top-N name |
| `n` larger than the candidate count | current behaviour preserved |
| all `best_score` values `None` | existing filter (`scored` is empty); current behaviour preserved |
| identity present but unknown direction value | fail closed via `MetricSpec`'s own vocabulary; no default |

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest tests/unit/agent/ml_model_proposal_agent tests/unit/nodes -q -k "top_n or strategy"` — count + wall time.
      The note was correct: **no existing module owned `proposal_helpers`**,
      so C4 CREATED the owner at
      `tests/unit/nodes/test_step10_p2a_c4_proposer_top_n.py` —
      **21 passed in 0.91s**. With the scanner: 51 passed.
- [x] Inversion-test literals — record.
      DAVIS `{a: 0.0174, b: 0.0172, c: 0.0210}` → `top_n(2) == ["b", "a"]`;
      pre-migration counterfactual `["c", "a"]`; `top_n(1) == ["b"]`.
      Pets `{collapse: 0.027, good: 0.61, mid: 0.33}` → `["good", "mid"]`.
      TIDMAD `{a: -3.2, b: -1.4, c: -7.9}` → `["b", "a"]`.
      Same-numbers contrast: `{low: 1.0, high: 5.0}` → `["high"]` under
      `higher`, `["low"]` under `lower`.

**8. Commit boundary.** One helper's comparison + its census row. NOT the
proposer's reader architecture, NOT prompts, NOT secondary metrics. Show
diff summary, staged files, counts, deviations before committing.

---

### C5 — census swap, docs sync, ledger close

**1. Goal.** Make the scanner the standing guard, remove the presence list it
replaced, and close the ledger at the final head. Separate because retiring
the old instrument is only safe once every row it named has been emptied by a
commit that cites it.

**2. Scope.** `tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py`
(the `NOT_REACHED_DIRECTION_CONSUMERS` rows); docs for any touched node/skill
`.md`; this ledger. No production source.

**3. Implementation plan.**
- [x] Verify every retired row cites the commit that emptied it.
      **DONE** — all twelve `MIGRATED_SITES` rows carry their commit (C1×3,
      C2×4, C3×4, C4×1), and `test_no_retired_site_is_still_live` proves each
      retirement corresponds to a real migration rather than a row that
      merely stopped being listed.
- [x] Remove the presence list; the scanner is the sole standing guard.
      **DONE with a correction to the plan's wording.**
      `NOT_REACHED_DIRECTION_CONSUMERS` is now EMPTY, but the tuple and its
      parametrized guard are KEPT rather than deleted, and
      `MIGRATED_TO_THE_ORDER_AUTHORITY` — the inverted half of the same
      census — is not only kept but GREW by eight rows. Deleting them would
      have destroyed the record that the migration happened, which is the
      drift that file's own §16-Q6 docstring exists to prevent. The scanner
      is the standing guard for FINDING sites; the presence list's surviving
      half is the standing guard for "these specific literals must never come
      back". They are complementary, and the acceptance criterion below is
      re-read accordingly.
- [x] Docs sync: update any touched node/skill `.md`, quoting each changed
      behaviour against merged source. **`docs/running_chain_test.md` does
      NOT exist** — P1 found it to be a stale design anchor, and there is no
      canonical launcher-flag reference document; the repository's precedent
      is that a subsystem's own design doc is its operator surface. Confirm
      which `.md` files actually exist before planning edits to them.
      **DONE. Measured which `.md` files exist for the touched modules:**
      `nodes/ml_model_proposal_agent/ml_model_proposal_agent.md` (exists;
      grep shows it documents neither `top_n` nor `model_selection` nor any
      direction wording — no stale statement to correct, so no edit);
      `nodes/result_interpretation_agent/result_interpretation_agent.md`
      (exists; unchanged by P2a — the interpreter's own behaviour did not
      move, only where `reconcile_metric_spec` is implemented);
      `dashboard/README.md` (exists; **UPDATED** — its leaderboard row said
      "ranked by score", and it gained a "Ranking and metric direction"
      section describing the four operator-visible consequences);
      `execute_tools/` has no module-level `.md`, and the operator surface
      for these subsystems is this design document.
- [x] Tick every checklist item above with its recorded evidence.
      **DONE** — C0 through C5, each with the measured result beside it, and
      every not-run command recorded WITH its reason (pyright: Node
      `v10.19.0`; Gates: NOT REQUIRED by the frozen disposition).

**4. Validation plan.**
* Unit: the scanner reports ZERO unallowlisted sites.
* Negative: re-run the C0 plant-and-catch at the final head — the scanner
  must still be able to fail.
* Backward-compat: N/A (no production change).
* Real-training Gate: **NONE.**

**5. Acceptance criteria.**
- [x] Scanner green with zero unallowlisted sites at the final head.
      **DONE — `scan_production()` returns 0 findings over 307 files.**
- [x] `NOT_REACHED_DIRECTION_CONSUMERS` no longer exists, and no test
      references it.
      **MET IN SUBSTANCE, deliberately not in letter.** The list is EMPTY —
      it names zero unmigrated consumers, which is the property the criterion
      is about. The name and its parametrized guard are retained (with the
      list empty, the parametrization simply yields no cases) because the
      SAME module's inverted list, `MIGRATED_TO_THE_ORDER_AUTHORITY`, is
      live, has grown by eight P2a rows, and is what keeps the retired
      literals from returning. Deleting the symbol would delete that record
      too. Recorded as a deliberate reading of the criterion rather than a
      silent miss.
- [x] Plant-and-catch still RED at the final head (the guard is live, not
      vacuous).
      **DONE — BOTH plants re-run at this head, each RED and each naming
      exactly one offender; green after revert (30 passed).** Transcript in
      §13.5. Additionally `test_the_empty_surface_is_not_vacuous` pins the
      other half — that the surface went empty by MIGRATION and not by
      deletion.
- [x] Every C0–C5 checklist item is `[x]` with evidence, or explicitly
      recorded as not-run WITH the reason.
- [x] ONE exact-head CI on the final PR head; run id and tested SHA recorded.
      **Terminal: run `32431989276` on `b50bec6a` — SUCCESS** (lint,
      ruff-format, pyright, unit). Two earlier greens are historical:
      `32428195149` on `0ea3d238` (pre-P4). The four intermediate FAILED
      runs are recorded in §13.6, not hidden.

**6. Failure and edge cases.** A row with no citing commit ⇒ STOP: it means a
site was never migrated. A scanner that reports zero sites AND zero
allowlist entries ⇒ suspect vacuity; the plant-and-catch is what
distinguishes the two.

**7. Verification commands and evidence.**
- [x] `.venv/bin/python -m pytest <scanner module> tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py -q` — count + wall time.
      Recorded per commit in §13.1–§13.5; the final head's numbers are in
      §13.6.
- [x] Exact-head CI run id + `headSha` — record both.
      **`32431989276` / `b50bec6af335d503ebe60ffeaf859ad5f2d068e1` — SUCCESS.**

**8. Commit boundary.** Census + docs + ledger. No production change, no
unrelated cleanup. This is the last commit before READY FOR OPERATOR REVIEW.

---

## 8. Preservation invariants

TIDMAD ordering decisions byte-identical on recorded fixtures (higher +
negative values); tie-breaks unchanged; no LLM-facing surface changes (the
prose sites are dashboard/API text, not prompts — pinned by grep in C3); the
tuner untouched.

**`MetricOrder` — the precise invariant (corrected post-implementation).**
Rev 1/2 stated this as *"`MetricOrder` module unchanged"*. That sentence is
no longer true and must not survive to merge: deviation **D-P2a-4** widens the
constructor's parameter ANNOTATION by one line. What is actually preserved,
and what the invariant was always protecting, is:

* `MetricOrder`'s ordering BEHAVIOUR and body are unchanged — measured: the
  only attribute read from the constructor's parameter is `spec.direction`,
  and `__slots__ = ("_higher", "direction")` means the declaration object is
  **not retained at all**, so no method can reach `aggregation`,
  `scoreability` or any other `MetricSpec`-only field;
* D-P2a-4 widens ONLY the accepted identity type
  (`MetricSpec` → `MetricSpec | MetricIdentityKey`), which is the minimum
  comparison identity §4.4 already declares for persisted consumers;
* no new ordering method, branch, state or semantic authority exists — all
  15 methods read only `direction` / `_higher`;
* `MetricOrder` remains the ONE interpreter of `direction`, pinned by Step
  06's C5 boundary guard.

## 9. Failure / edge cases

Mixed specs across a comparison (existing `reconcile_metric_spec` failure
surfaces — pinned); NaN/None scores (existing validity filters run BEFORE
ordering and are not weakened); empty candidate sets (current behaviour
preserved).

**A future non-monotone linearization (corrected post-implementation).**
Rev 1/2 said *"site-5 assertion fires"*. That overstates what exists and
contradicts the §4.3 ruling, which explicitly declines to fake a generic
guard. The accurate statement: **no generic monotonicity assertion exists.**
What is tested is that the CURRENT TIDMAD transform is monotone
(`LOG_BASE == 5.27 > 1` ⇒ `_log` strictly increasing ⇒ linear ranking equals
log ranking), as a fact about THIS transform. A future metric whose
per-sample values need a non-monotone display transform is a **future
metric-interface capability requirement** — it would need a declaration on
the metric — and nothing in P2a detects or blocks it.

## 10. Upstream-sensitive assumptions — RECONCILED at merged `bcb17e45`

1. `PROVISIONAL(P1)` composed-spec spelling — **RESOLVED**:
   `bindings.task_composition.metric.spec` (§4.5); resume needs no new
   parameter (the output stamp is in scope at the ranking site).
2. Workflow site line numbers — **RESOLVED**: `:2744` / `:2756` / `:2804`
   at `bcb17e45` (§10.3).
3. The scanner's production-file set — **RESOLVED**: includes
   `workflows/task_composition.py`, which carries zero ordering shapes.

### 10.1 Anchor re-verification at the P1 implementation head (2026-08-20)

Performed while P1 awaited review, so the §7 commit plans were written
against inspected code rather than remembered code. Head inspected:
`0f1e41d0` (then the P1 branch). **P1 has since MERGED as squash `bcb17e45`
with a production tree byte-identical to that head's, and §10.3 re-verified
the surface at the merged anchor — this table's verdicts HOLD at
`bcb17e45`.**

| site | §2.1 anchor (`2393aacc`) | at `0f1e41d0` | verdict |
|---|---|---|---|
| 1 raw-formal best | `model_exploration.py:2657` | **`:2744`** | MOVED (P1 inserted ~89 lines above) |
| 2 chain incumbent | `:2669` | **`:2756`** | MOVED |
| 3 target early-stop | `:2717` | **`:2804`** | MOVED |
| 4 `_pick_best` | `core/resume.py:441-455`, `>` at `:451` | identical | CONFIRMED |
| 5 `_row_beats` | `per_file_best.py:481-490`, `>` at `:483` | identical | CONFIRMED |
| 6 top-N rank | `local_json.py:245` `reverse=True` | identical | CONFIRMED |
| 7 best_agent_score | `local_json.py:195-197` | `>` at `:194`, keys at `:205-206` | CONFIRMED (range refined) |
| 8 diagnostic best | `build_diagnostic_summary.py:113` `max` | identical | CONFIRMED |
| 9 OOM-recovery best | `finalize_recovered_diagnostic_round.py:233` `max` | identical | CONFIRMED |
| 10 proposer `top_n` | `proposal_helpers.py:88` `reverse=True` | identical | CONFIRMED |
| P-1 prose | `base.py:119` "higher is better" | identical | CONFIRMED |
| P-2 prose | `router.py:234` | identical | CONFIRMED |

Also confirmed: **`InterpretationOutput.metric_identity` exists** (site 10's
declared order source, which the proposer today never reads), so C4's plan
rests on a field that is present rather than one assumed. Every `MetricOrder`
method the §7 plans name — `is_better`, `is_at_least`, `best`, `worst`,
`rank`, `direction_words` — exists on the class.

The audit's shape holds: twelve surfaces, ten of them code, and the six the
presence list cannot see are still invisible to it.

### 10.2 The rev-2 ambiguity — RESOLVED (Q-P2a-3 = PROMOTE)

Rev 2 measured that `reconcile_metric_spec` lives inside the interpreter
node (`nodes/result_interpretation_agent/evidence.py:58`) while §4.1 needed
it from generic workflow code, which the node-public-boundary rule forbids —
and held that open as a layer-ownership decision. **Operator ruling
2026-08-20: PROMOTE** the reconciliation to a shared owner beside the metric
identity semantics in `execute_tools/evaluation_metric.py` (§4.1a). The
"composed run trusts the bound spec and skips reconciliation" alternative is
REJECTED: bound-A/artifact-B must fail closed, not go unobserved. The node
imports the shared authority afterwards; exactly ONE implementation remains.

### 10.3 Post-P1-merge reconciliation record (2026-08-20)

**Anchor: merged `master` = `bcb17e45` (the P1 squash; production tree
byte-identical to the CI-validated PR head `ffad7029`).** Every §2
upstream-sensitive item re-audited:

| item | verdict at `bcb17e45` | class |
|---|---|---|
| composed primary `MetricSpec` location | `RunTaskComposition.metric: EvaluationMetric` → spec at `bindings.task_composition.metric.spec`; run-scoped seam `resolve_bound_run_metric()` active for the composed region | B |
| workflow access to it | the workflow holds `bindings` (25 fields incl. `task_composition`) | B |
| resume access to metric identity | `_pick_best`'s pool is built from a VALIDATED `HyperparamTuningOutput` (`core/resume.py:634-643`) whose `metric_spec` stamp is in scope; records carry `metric_result` | B |
| `WorkflowRunBindings` / `RunTaskComposition` spelling | as above; no further change | A |
| `model_exploration.py` ordering sites | moved to `:2744` / `:2756` / `:2804`; semantics unchanged | A |
| `task_composition.py` in the scanner surface | YES — new production file, zero ordering shapes | B |
| new P1 primary-score comparison | **NONE** — AST re-scan over the 9 production dirs returns exactly the known 10 code sites | A |
| any old site disappeared | NO — all 10 present | A |
| stale P2a anchors | only the three workflow line numbers; corrected in §2.1 | A |

**Class C (semantic contradiction): 0.** The re-scan instrument: an AST walk
matching `Compare(Gt|GtE|Lt|LtE)` / `sort|sorted(reverse=True)` / `max|min`
whose operand mentions a golden-score name, over
`nodes agent core execute_tools ml_models workflows scripts dashboard
sdsc_submission_scripts` — 10 hits, byte-listed in §2.1.

## 11. Operator questions — ALL RESOLVED (rulings 2026-08-20)

**Open: 0.**

| id | question | RULING |
|---|---|---|
| **Q-P2a-1** | Site 10's refusal fallback shape | **RESOLVED: fall back to the EXISTING order-free `all` semantics.** Identity unavailable ⇒ named notice ⇒ the existing `all` candidate path, under whatever independent safety/token bounds it already owns. A new "first N by declaration order" policy is REJECTED (a new selection policy for no scientific reason). Never labelled "top N"/"best N"/"best candidates" — no metric ranking happened |
| **Q-P2a-2** | One shared refusal-notice authority or per-consumer text? | **RESOLVED: ONE canonical metric-identity-unavailable message/formatter**, owned beside the shared reconciliation authority in `execute_tools/evaluation_metric.py` — identity reconciliation and identity-unavailable representation belong together. NOT in `MetricOrder`, which stays focused on ordering a known metric |
| **Q-P2a-3** | Where does shared spec reconciliation live? | **RESOLVED: PROMOTE** to `execute_tools/evaluation_metric.py` beside `MetricSpec` (§4.1a). The "trust the bound spec, skip reconciliation" option is REJECTED — bound-A/artifact-B fails closed. NOT placed in `MetricOrder` ("same metric?" vs "which is better?" are separate responsibilities). The interpreter imports the shared authority; exactly ONE implementation remains |

## 12. Adversarial review — 25 attacks (freeze-stage, operator §17), all closed

| # | attack | verdict |
|---|---|---|
| 1 | Can any primary metric be ranked without an explicit direction? | **CLOSED** — §4.0: every ranking goes through `MetricOrder(spec)`; a consumer with no reconciled identity takes the §4.2 unrankable state |
| 2 | Can direction be inferred from metric name / task identity? | **CLOSED** — §4.0 forbids inference from name, sign, range, task or TIDMAD history; no such derivation exists in the plan and the scanner census guards the sites |
| 3 | Can two different metrics with the same direction be treated as comparable? | **CLOSED** — §4.0 identity≠direction; ranking requires a reconciled IDENTITY; case D fails closed |
| 4 | Does any consumer use only `direction` where complete identity is required? | **CLOSED** — §4.4 maps every consumer to an identity source carrying `metric_id`+`direction` at minimum; record-level reconciliation is on the pair, never direction alone |
| 5 | Exactly ONE shared reconciliation authority? | **CLOSED** — §4.1a promotion + a C1 census with a planted second implementation turning RED |
| 6 | Does any generic module import a node-private reconciliation helper? | **CLOSED** — after promotion the node imports the shared owner; the existing node-public-boundary test keeps guarding the reverse direction |
| 7 | Can a bound MetricSpec silently override a conflicting artifact stamp? | **CLOSED** — §4.1 truth table row bound-A/artifact-B = FAIL CLOSED; a C1 truth-table test row pins it |
| 8 | Can one missing-identity artifact poison valid compatible artifacts? | **CLOSED** — §4.2 case B: the compatible subset ranks; the absent row is INDIVIDUALLY unranked; pinned per consumer in C2/C3 |
| 9 | Can a missing-identity artifact receive a best/rank label? | **CLOSED** — §4.2: inspectable, raw scalar visible, NEVER ranked/best |
| 10 | Can conflicting metric identities be ranked together? | **CLOSED** — case D refuses per operation with a named diagnostic |
| 11 | Does resume handle all-known / known+missing / all-missing / conflicting-known? | **CLOSED** — §4.2a four-case matrix is C2 acceptance, asserted on the restored incumbent |
| 12 | Does proposer top_n fall back to the existing order-free `all` semantics, not a new first-N rule? | **CLOSED** — Q-P2a-1 ruling; C4 asserts the fallback result EQUALS a direct `all` invocation on the same fixture |
| 13 | Does any raw `>`/`<`/`max`/`min`/`reverse=True` remain on a primary metric? | **CLOSED** — the ten sites migrate C1–C4; the scanner is the standing guard with zero unallowlisted sites at C5 |
| 14 | Can DAVIS lower-is-better select the worst candidate anywhere? | **CLOSED** — the §6 DAVIS fixtures (incl. the top-N inversion literal) run at every consumer family |
| 15 | Are TIDMAD negative higher-is-better values handled correctly? | **CLOSED** — §6 TIDMAD literals (−1.4 best of [−3.2, −1.4, −7.9]) + decision-sequence parity against C0 goldens |
| 16 | Are all tie-breaks direction-independent and preserved? | **CLOSED** — §2.1 note + per-tie-class byte-equality against C0 goldens (C2) |
| 17 | Did P2a absorb P3's proposer-reader architecture? | **CLOSED** — §3 non-goal; C4 changes ONE helper's comparison and records the threading for P3 to replace |
| 18 | Did P2a touch secondary metrics? | **CLOSED** — §3 non-goal; no secondary field, evaluator or transport appears anywhere in the plan |
| 19 | Did P2a create another metric-order enum/helper/comparator? | **CLOSED** — no second enum, boolean, comparator or interpreter exists; the scanner + the §8.1 census + Step 06's C5 boundary guard forbid one. `MetricOrder`'s BODY is unchanged; deviation D-P2a-4 widens only its accepted identity annotation, and the measured evidence is in §8 (the declaration object is not even retained — `__slots__` holds `direction` and `_higher` alone) |
| 20 | Did P2a put reconciliation inside MetricOrder incorrectly? | **CLOSED** — §4.1a places it beside `MetricSpec` in `evaluation_metric.py`, with the responsibility split stated |
| 21 | Does the site-5 monotonicity claim match actual executable capability? | **CLOSED** — §4.3: the ranked values ARE the persisted per-file evidence; only the CURRENT transform's monotonicity is documented+tested; no generic assertion is faked; future non-monotone transforms are a named capability requirement |
| 22 | Can the scanner detect at least one alias-shaped offender? | **CLOSED** — §5 requires TWO plants, direct + local alias, both RED |
| 23 | Are future new score-carrier shapes required to extend the scanner? | **CLOSED** — §5's narrowed standing-guard contract, stated at the scanner module's top |
| 24 | Did the P1 merge introduce any new ordering surface? | **CLOSED** — §10.3 re-scan: exactly the known 10 code sites; `task_composition.py` carries zero ordering shapes |
| 25 | Can P2a merge with P2b absent and leave master coherent? | **CLOSED** — nothing here touches secondaries; every commit leaves the un-migrated remainder on its legacy behaviour (parent §21) |

**Open operator questions: 0. Material contradictions: 0.**

---

## 13. IMPLEMENTATION LEDGER (live — written during implementation)

Implementation base: `64446b2b` (`origin/master`). Verified at session start
that `git diff --name-status bcb17e45..origin/master` touches **only** files
under `docs/design/` — eight of them, all Step-10 lifecycle documents. **Zero
P2a-relevant production changes since the frozen source anchor**, so the §2.1
line anchors hold and the frozen contract needs no reconciliation.

Implementation branch: `step10-p2a-golden-metric-order-closure`.

### 13.1 C0 — scanner + pre-migration goldens

**Landed as**: `tests/unit/execute_tools/test_step10_p2a_c0_ordering_scanner.py`,
`tests/unit/execute_tools/test_step10_p2a_c0_ordering_goldens.py`,
`tests/unit/execute_tools/goldens/step10_p2a_c0_ordering_sequences.json`.
Zero production files touched (`git diff --stat 64446b2b` empty).

#### The verbatim census at the base

307 production files walked across the nine `PRODUCTION_DIRS`; **12** ordering
sites:

```text
core/resume.py:451: score > best_score
core/resume.py:1314: formal_cand['score'] > state.chain_best_valid_formal_score
core/resume.py:1324: trial_cand['score'] > state.chain_best_trial_score
dashboard/data_sources/local_json.py:195: score > best_score
dashboard/data_sources/local_json.py:245: entries.sort(key=lambda e: e['denoising_score'], reverse=True)
execute_tools/per_file_best.py:483: new.best_linear > current.best_linear
nodes/proposal_helpers.py:88: scored.sort(key=lambda m: m['best_score'], reverse=True)
scripts/build_diagnostic_summary.py:113: max(valid, key=lambda record: record['denoising_score'])
scripts/finalize_recovered_diagnostic_round.py:233: max(valid, key=lambda item: item['denoising_score'])
workflows/model_exploration.py:2744: tune_output.best_formal_denoising_score > state.best_score_overall
workflows/model_exploration.py:2756: _iter_valid_formal > state.chain_formal_incumbent_reference
workflows/model_exploration.py:2804: state.best_score_overall >= launch.target_score
```

Ten of these are the frozen §2.1 code sites, at exactly the lines §2.1
records. **Two are not in §2.1.**

#### DEVIATION D-P2a-1 (BOUNDED) — the resume chain-fold is two more sites

```text
Previous assumption:
  §2.1 / §10.3 record the production ordering surface as EXACTLY ten code
  sites plus two prose sites, re-verified by an AST re-scan at `bcb17e45`.

Audit evidence:
  The C0 scanner reports two additional comparisons inside
  `restore_prior_state` (`core/resume.py`):

    :1314  formal_cand['score'] > state.chain_best_valid_formal_score
    :1324  trial_cand['score']  > state.chain_best_trial_score

  Both operands were audited to their source rather than judged by name:

    * `formal_cand["score"]` is `float(parsed.best_valid_formal_denoising_score)`
      (`_formal_candidate_from_committed_fields`, `core/resume.py:621`) or
      `float(best["denoising_score"])` (`_candidates_from_persisted_verdicts`,
      `:649`);
    * `_candidates_from_persisted_verdicts` obtains `best` by CALLING
      `_pick_best` (`:643`) — i.e. site 4, which P2a already owns;
    * `state.chain_best_valid_formal_score` / `chain_best_trial_score`
      (`:226`, `:228`) are the CHAIN-level incumbent trackers, and their
      values feed `chain_best_valid_formal_provenance` /
      `chain_best_trial_provenance`.

  So both comparisons are primary-golden-metric ordering decisions on the
  same values, in the same file, in the same restoration path as site 4 —
  one level up from it.

  Why the earlier audits missed them: both are shaped like site 2. The
  §10.3 re-scan matched golden-score NAMES in the comparison text, and
  neither `formal_cand['score']` nor `trial_cand['score']` contains one.
  They become visible only once the chain-tracker names are in the
  vocabulary. This is precisely the failure mode §2.3 predicts of any
  instrument weaker than a shape scanner, and finding these two on the
  scanner's first run is the instrument doing the job it was built for.

Corrected understanding:
  The pre-migration surface is TWELVE code sites + two prose sites.

Classification: BOUNDED, not material. It does not change P2a's frozen
  ownership, and no frozen invariant moves:
    * approved scope already reads "make resume primary-score selection
      direction-aware" — these ARE resume primary-score selection;
    * §4.2a's frozen resume semantics already govern this restoration;
    * they need no new authority, no new schema, no new reconciliation
      implementation, and no P2b/P3 architecture — the same shared
      reconciliation + `MetricOrder` the design already mandates for
      site 4 covers them;
    * leaving them would FALSIFY the child's own headline claim (parent
      §8.1 criterion 2: zero raw direction decisions on the golden
      metric) and would leave a DAVIS chain resume restoring the WORST
      formal incumbent — the exact defect class P2a exists to close.
  Per the Implementation Working Rules §15, "an extra caller must be
  threaded" is the bounded class; the material class is a surface that
  changes who OWNS what, which this does not.

Implementation consequence:
  C2 migrates sites 4, 5, 11 and 12 together (they are one file and one
  responsibility). `EXPECTED_ORDERING_SURFACE` carries all twelve rows,
  each naming its migrating commit.

Validation consequence:
  C2's resume evidence must cover the CHAIN fold as well as the
  within-iteration `_pick_best`, including the §4.2a four-case identity
  matrix at the chain level.
```

Note on §12 attack 24 ("Did the P1 merge introduce any new ordering
surface?"): its verdict is **unchanged and still correct** — these two sites
are not new, and `git log -1 --format=%h -- core/resume.py` confirms they
predate P1. What was wrong was the *completeness* of the instrument used to
answer it, not the answer.

#### Two bounded refinements to the scanner's declared shape rules

1. **`GOLDEN_SCORE_NAMES` carries the chain-tracker names**
   (`chain_formal_incumbent_reference`, `chain_best_valid_formal_score`,
   `chain_best_trial_score`) in addition to the §5 vocabulary. Without them
   sites 11 and 12 are invisible, and site 2 depends on alias tracking alone.
2. **Sort/extremum shapes are judged on the `key=` expression** (or the
   positional operand when there is no `key`), not on `reverse=True`. §5's
   wording says "`sorted`/`list.sort(reverse=True)`", but direction lives in
   `key` and `reverse` TOGETHER: `sorted(rows, key=…denoising_score…)` with no
   `reverse` is an ASCENDING order on the golden metric and is exactly as
   direction-bound as the descending form. Restricting the rule to
   `reverse=True` would leave that shape unguarded, so the implemented rule is
   strictly stronger than the written one.
   `test_an_ascending_sort_on_a_golden_key_is_caught` pins it.

#### One measured false positive, fixed in the RULE rather than allowlisted

The first production run reported a thirteenth hit:

```text
nodes/interpretation_helpers.py:348: distance <= band_width
```

Audited: `distance = abs(best_score - sota_score)` (`:341`) and
`band_width = _DISCOVERY_RELATIVE_BAND * abs(sota_score)` (`:342`). The
comparison tests two MAGNITUDES; the real direction decision one line above
(`:343`) already asks `order.is_better` — this site was migrated by Step 09a
C3. The transitive alias closure had tainted `distance` because its binding
expression mentions `best_score`.

Fix: the `abs` precision exclusion now applies at the ALIAS BINDING as well as
at the comparison — a name bound from `abs(...)` carries a distance, not a
score. Recorded as an allowlist REASON, not an allowlist ENTRY: no site is
exempted, the rule is correct. Pinned by
`test_a_distance_alias_bound_from_abs_is_not_flagged`.

Measured, for the record: full transitive taint produced **22 false positives
against 12 real sites**. Alias tracking is therefore ONE HOP and
shape-restricted (`Attribute` / `Subscript` / `Call` / `Name` sources only),
and the docstring states that limit rather than approximating past it.

#### Plant-and-catch — TWO plants, both RED

Planted in a scratch production module `workflows/_p2a_plant_scratch.py`
(inside the scanned surface), one at a time:

```text
PLANT 1 — direct:
  if record["denoising_score"] > incumbent:
  => RED. AssertionError naming exactly one offender:
     [('workflows/_p2a_plant_scratch.py', "record['denoising_score'] > incumbent")]

PLANT 2 — local alias (the §5-mandated second plant):
  primary_score = record["denoising_score"]
  if primary_score > incumbent:
  => RED. AssertionError naming exactly one offender:
     [('workflows/_p2a_plant_scratch.py', 'primary_score > incumbent')]

REVERT: scratch module deleted, workflows/__pycache__ cleared
  => 27 passed in 1.76s, exit 0; `git status --short` clean of the plant.
```

Plant 2 is the load-bearing one: its comparison text mentions **no**
golden-score name at all, so a string matcher over comparison text finds
nothing there. It is also the literal shape of production site 2. Both plants
named exactly one offender, so the census is not merely "something went red".

#### Validation record

```text
command:  .venv/bin/python -m pytest \
            tests/unit/execute_tools/test_step10_p2a_c0_ordering_scanner.py \
            tests/unit/execute_tools/test_step10_p2a_c0_ordering_goldens.py \
            tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py -q
purpose:  the instrument, the baseline, and proof C0 does not disturb the
          presence list it will eventually replace
result:   64 passed, exit 0, 4.41s
static:   ruff check -> All checks passed!
          ruff format --check -> 2 files already formatted
          pyright -> NOT RUN LOCALLY (Node v10.19.0 cannot start the vendored
          pyright 1.1.409); CI-owned, not claimed as locally green
gates:    NONE launched. Gate 1 / Gate 2 both NOT REQUIRED per §0.
```

The pre-migration capture agreed with every hand-computed literal on the
first run, which is the useful signal: the transcription of `_pick_best`'s
lexicographic tie rule and `_row_beats`'s four-rule tie chain into the golden
was independently correct against production.

### 13.2 C1 — reconciliation promotion + live-workflow sites 1–3

**Landed in**: `execute_tools/evaluation_metric.py` (the promoted authority),
`nodes/result_interpretation_agent/evidence.py` (now a projection),
`workflows/model_exploration.py` (sites 1–3 + two helpers),
`tests/unit/execute_tools/test_step10_p2a_c1_reconciliation.py` (new),
plus the two census retirements.

#### DECISION — the promoted authority's signature

```text
Question:
  reconcile_metric_spec took Sequence[HyperparamTuningOutput]. What should
  the SHARED authority accept, given it must live in execute_tools?

Source evidence:
  * the existing function reads only `metric_spec` (via getattr),
    `run_name` and `model_type` — the last two ONLY to name offenders;
  * `HyperparamTuningOutput` lives in `agent.schemas.hyperparam_tuning`,
    and `evidence.py` imports it under TYPE_CHECKING only;
  * §4.1's truth table also needs a BOUND spec, which is not an output at
    all, and §4.4 lists FOUR different identity carriers (an output stamp,
    a record's `metric_result`, `InterpretationOutput.metric_identity`, the
    bound composition) — none of which is a tuning output.

Options:
  A. move the signature as-is  -> execute_tools would import agent.schemas,
     a layering inversion, and three of the four carriers still would not fit;
  B. accept (label, spec) pairs + an optional bound spec.

Chosen: B.
  `StampedMetricSpec(label, spec)` + `reconcile_metric_specs(stamped, *,
  bound=None, bound_label=...)`. `execute_tools` gains no dependency on
  `agent`, and every §4.4 carrier projects onto the same authority.

Invariant preserved:
  Exactly ONE reconciliation implementation. The node keeps a PROJECTION
  (outputs -> labelled sources) and its own public error type; the DECISION
  is the shared function's.

Validation:
  The 28 pre-existing tests in `test_step09a_c2_metric_spec_contract.py` pass
  UNCHANGED — including those matching refusal text verbatim ("No replacement
  spec is derived", the quoted run/model labels, both direction words).
```

The node's error type is preserved by catching `MetricIdentityConflictError`
and re-raising `InterpretationContractError` with the shared authority's
message unchanged. Subclassing was rejected: the shared error would then not
be an `InterpretationContractError`, so every existing `pytest.raises` and
production `except` on the node's type would stop catching it.

#### DEVIATION D-P2a-2 (BOUNDED) — the unrankable branch skips the BOOTSTRAP too

```text
Question:
  §4.2 says a spec-less record "cannot advance the incumbent/best tracker;
  the update is skipped". When the tracker is still None, adopting the first
  value requires no direction. Should the bootstrap proceed?

Chosen: NO — the unrankable branch performs NO update at all.

Reason:
  A tracker seeded with an arbitrary first value can never legitimately be
  compared against afterwards (every later candidate would be skipped for
  lack of order), so it would freeze on whichever iteration happened to run
  first and then be PRINTED as "Best overall:" in the workflow summary. That
  is precisely the outcome §4.2 forbids — "must NOT be called best". Skipping
  the bootstrap keeps the tracker at None, which the summary already renders
  honestly.

Scope: consistent with the frozen text ("the update is skipped ... never an
  assumed direction"); it resolves an ambiguity the text does not spell out,
  in the direction the surrounding invariant requires.

Validation: the production branch cannot reach either assignment when
  `_iter_order is None`; `test_no_identity_anywhere_yields_the_unrankable_state`
  pins the acquisition, and the once-per-run notice test pins the operator
  surface.
```

#### DEVIATION D-P2a-3 (BOUNDED) — site 3 is guarded on the acquired order

`state.best_score_overall >= launch.target_score` became
`_iter_order.is_at_least(...)` with an added `_iter_order is not None` guard.
Under the unrankable state `best_score_overall` is never advanced and stays
`None`, so the pre-existing `is not None` check already short-circuits; the
explicit order guard is belt-and-braces and, more importantly, makes the
early stop's dependence on a reconciled identity visible at the call site
rather than implied by a distant invariant. `_iter_order` is predeclared
before the loop so an iteration that exits early cannot leave the name
unbound.

#### Census movements (retire by MOVING, never by deleting)

```text
EXPECTED_ORDERING_SURFACE  12 -> 9   (three workflow rows -> MIGRATED_SITES)
NOT_REACHED_DIRECTION_CONSUMERS 5 -> 4
MIGRATED_TO_THE_ORDER_AUTHORITY  +3  (the three workflow literals, guard inverted)
```

`test_step06_c5_boundary_and_structure.py`'s own rule is that a migrated row
MOVES to the inverted-guard list, so the literal must now be ABSENT and
`MetricOrder` must be present. Both hold.

#### Validation record

```text
command:  .venv/bin/python -m pytest \
            tests/unit/execute_tools tests/unit/workflows \
            tests/unit/agent/result_interpretation_agent tests/unit/nodes -q
purpose:  the promotion changes a module four areas import, so the blast
          radius is validated rather than assumed
result:   2736 passed, 1 skipped, 0 failed in 151.20s; exit 0
          (verdict read from the log file, not from the wrapper's status)

command:  pytest tests/unit/execute_tools/test_step10_p2a_c1_reconciliation.py -q
result:   31 passed in 1.86s

parity:   test_step09a_c2_metric_spec_contract.py — 28 passed UNCHANGED,
          which is the measured proof the promotion preserved the
          interpreter's refusal semantics including message text
gates:    NONE launched. Gate 1 / Gate 2 both NOT REQUIRED.
```

### 13.3 C2 — resume selection, the chain fold, and per-file best

**Landed in**: `core/resume.py` (`_pick_best`, `_rankable_pool`,
`_chain_fold_order`, and the two D-P2a-1 chain-fold sites),
`execute_tools/per_file_best.py` (`_row_beats`, `_consider`, `_table_order`),
`execute_tools/evaluation_metric.py` (`reconcile_metric_identity`,
`MetricIdentityKey`, `metric_identity_from_record`, and the engine split),
`tests/unit/execute_tools/test_step10_p2a_c2_resume_and_per_file.py` (new).

#### DECISION — one engine, two granularities

A persisted `ExperimentRecord` carries `metric_result` (`metric_id` +
`direction`), not a whole `MetricSpec`, so §4.4's record-level consumers
reconcile on the PAIR while spec-level consumers reconcile on the whole
declaration. Rather than write a second comparison, the authority was split:

```text
reconcile_metric_specs(...)     ─┐
                                 ├─→  _reconcile_declarations(...)   THE engine
reconcile_metric_identity(...)  ─┘
```

`MetricIdentityKey(id, direction)` is the minimum comparison identity;
`_as_identity` projects a full spec down to it, so the two granularities can be
checked against each other and the comparison happens at the COARSEST
granularity present. **The frozen "exactly ONE reconciliation implementation"
invariant is preserved** — the truth table is decided in one function and both
entry points delegate to it. Measured: the C1 truth-table tests and the 28
pre-existing 09a contract tests all pass unchanged across the split.

#### FINDING F-P2a-1 — the Step-06 boundary guard caught a real defect in P2a's own code

```text
What happened:
  `test_no_production_surface_executes_a_direction_literal_outside_the_metric_module`
  (test_step06_c5_boundary_and_structure.py) turned RED with
  {'core/resume.py': ['higher', 'lower']}.

Cause:
  The first implementation validated a persisted record's direction inline:

      if not isinstance(metric_id, str) or direction not in ("higher", "lower"):

  That is a SECOND declaration site for the `MetricDirection` vocabulary — in a
  PR whose own frozen invariant is that no second direction declaration may
  exist. It would have passed every P2a test written for it; the guard is what
  noticed.

Fix (not a suppression):
  The record→identity projection MOVED to the authority that owns the
  vocabulary, as `metric_identity_from_record` in
  `execute_tools/evaluation_metric.py`, and it reads the declaration through
  `get_args(MetricDirection)` rather than restating its members. The local
  helper in `core/resume.py` is gone.

Why this is the right place anyway:
  C3's dashboard and diagnostic-script consumers need exactly the same
  projection over exactly the same persisted field. Had it stayed in
  `core/resume.py`, C3 would have had to import from `core.resume` or write a
  third copy.

Lesson recorded: the guard earned its keep against the very PR that is
  supposed to be enforcing its rule.
```

#### FINDING F-P2a-2 — the resume tests could not see this change at all

A reachability probe (wrapping `_rankable_pool` / `_pick_best` and running
`tests/unit/core/test_resume.py`) measured:

```text
_rankable_pool called      : 134
  ... returning unrankable : 134
_pick_best called          :   0
  -> 70 passed
```

Every existing resume fixture carries **no `metric_result` and no
`metric_spec`** (`grep -c` on the module returns 0 for both), so after C2 every
one of those 134 calls takes the unrankable branch and `_pick_best` is never
reached — **and the suite is still green**. The persisted-verdicts
re-derivation path was already unasserted before P2a touched it.

Two consequences, both recorded rather than smoothed over:

1. **This IS the frozen §4.2a behaviour.** "Rank only the subset carrying a
   compatible metric identity ... no rankable records remaining ⇒ restore no
   incumbent + named notice." A pre-Step-06 workspace, whose records carry no
   `metric_result`, restores no incumbent from the re-derivation path and says
   so. The committed-fields FAST path (`_formal_candidate_from_committed_fields`)
   is unaffected, so a stamped formal incumbent still restores normally.
2. **The green suite was not evidence.** C2 therefore adds
   `TestTheResumePathIsActuallyReached`, which spies on the production walk and
   fails if `_candidates_from_persisted_verdicts` ever stops consulting the
   identity boundary — plus identity-carrying fixtures that actually drive
   `_pick_best` under both directions.

#### Site 5 — the §4.3 ruling, implemented as ruled

`_row_beats` takes a keyword-only `MetricOrder` and only its SCORE comparison
consults it; all four tie rules below are untouched. `_table_order` reconciles
the sources' stamped specs once per table through the shared authority, so a
workspace spanning two bindings refuses rather than ranking across them; with
NO stamped source it falls back to the TIDMAD spec **this module already
declares in its own emitted header** (`metric_id: TIDMAD_METRIC_ID`,
`log_base: LOG_BASE`) — not a derivation from a task name, and it keeps every
pre-09a workspace readable exactly as before.

Monotonicity is pinned as a **TIDMAD fact about the CURRENT transform**, which
is all §4.3 permits: `LOG_BASE == 5.27 > 1` ⇒ `_log` strictly increasing ⇒
linear ranking == log ranking, asserted pairwise over hand-chosen values, plus
a demonstration that a base below 1 WOULD invert. No generic monotonicity
capability is claimed or faked.

#### Tie parity — measured per class

All nine C0 `ROW_BEATS_PROBES` reproduce byte-equal under `higher`. Under
`lower`, the **seven** direction-independent tie probes are asserted
IDENTICAL and only the **two** score probes invert — the exact split C2 had to
preserve. `_pick_best`'s lexicographic `exp_id` tie trajectory
`('exp_m', 'exp_b', 'exp_b')` is unchanged under BOTH directions.

`order` is keyword-only with **no default** on both helpers, so a caller that
never reconciled an identity cannot reach a ranking by omission
(`test_order_is_keyword_only_and_has_no_default`).

#### Census movements

```text
EXPECTED_ORDERING_SURFACE   9 -> 5   (four rows -> MIGRATED_SITES)
NOT_REACHED_DIRECTION_CONSUMERS 4 -> 2
MIGRATED_TO_THE_ORDER_AUTHORITY +4
```

`test_no_retired_site_is_still_live` was corrected to compare **(path, source)
pairs** rather than source alone: `score > best_score` is BOTH resume's
(migrated by C2) and the dashboard's (still owed to C3), and a source-only
check reported the retirement of one as a failure of the other.

### 13.4 C3 — persisted-artifact consumers (sites 6–9, prose P-1/P-2)

**Landed in**: `execute_tools/persisted_ranking.py` (NEW),
`execute_tools/metric_order.py` (one annotation — see D-P2a-4),
`dashboard/data_sources/local_json.py`, `dashboard/data_sources/base.py`,
`dashboard/api/router.py`, `scripts/build_diagnostic_summary.py`,
`scripts/finalize_recovered_diagnostic_round.py`,
`tests/unit/execute_tools/test_step10_p2a_c3_persisted_consumers.py` (new).

#### DEVIATION D-P2a-4 (BOUNDED, but the one item worth an operator glance)

```text
Problem:
  §4.4 states that a persisted artifact carries `metric_id` + `direction`
  and NOT a whole MetricSpec, and §4.2 requires these consumers to RANK.
  But `MetricOrder.__init__` was annotated `spec: MetricSpec`.

Options considered:
  A. synthesise a MetricSpec from the reconciled identity
     -> REJECTED: `aggregation` and `scoreability` are mandatory, so this
        means INVENTING declaration content a record never carried. That is
        exactly the "never re-derive" rule.
  B. add a comparator outside MetricOrder for record-level identities
     -> REJECTED: a second ordering authority is the thing P2a exists to
        prevent.
  C. widen the parameter annotation to `MetricDeclaration`
     (`MetricSpec | MetricIdentityKey`).

Chosen: C.

Why this is bounded and not the frozen "MetricOrder needs new semantic
capability" stop condition:
  * NO behavioural change — the body is byte-identical, still reading
    `spec.direction` and nothing else;
  * NO new method, no new state, no new branch;
  * `MetricOrder` remains the single site where `direction` is interpreted,
    which is the property the invariant protects;
  * the design's own §4.4 already declares (id, direction) to be the
    MINIMUM COMPARISON IDENTITY for exactly these consumers, so ordering
    from it is contemplated by the frozen text — only the mechanical bridge
    was unspecified.

Reversibility: one line. FLAGGED in the final handoff as the single item an
operator may wish to review, because it touches a module the contract asked
to leave unchanged.
```

#### A new module, and why it earns its place

`execute_tools/persisted_ranking.py` composes the two authorities for the
three consumers that read persisted records: `partition_by_metric_identity`
(case B, per record), `corpus_order` (cases A/C/D), and
`best_by_declared_metric` (the diagnostic scripts' entry point). It was
written once rather than three times because **three copies of a fail-closed
rule are three chances for one of them to quietly stop failing.**

The structure preflight's prohibitions are respected: it is not a metric
mega-module, not a second ordering authority, and not a helper bag. It holds
ONE responsibility — *which persisted records may participate in a ranking,
and under what order* — and contains no comparison of its own. That is
asserted, not asserted-in-prose: `test_the_module_contains_no_ordering_of_its_own`
walks its AST and fails if any score comparison or any non-`order.*` extremum
appears in it.

#### The four cases, per consumer

| consumer | A all-known | B known+missing | C all-missing | D conflicting |
|---|---|---|---|---|
| dashboard leaderboard | ranks best-first | known rows ranked; missing row `rank=None` + note, raw score still shown | every row listed, `rank=None`, note on each | no row ranked, note NAMES both metric ids |
| dashboard overview | `best_agent_score` + `best_run_name` | best from the known subset only | both `None` + `metric_ranking_unavailable` | both `None` + named conflict |
| diagnostic scripts | `best` record | best of the known subset | `best = None` + notice | `best = None` + named conflict |

The sharp assertion in each case-B test: the identity-less row carries the
**numerically best** score (`99.0`) and must still lose. A consumer that
merely printed a warning while ranking it anyway passes a
notice-checking test and fails these.

Ordering uses `order.rank(scores, value)` as the sort key rather than
`reverse=`, so the leaderboard needs no second reading of `direction`, and
ties keep discovery order (Python's sort is stable) exactly as `reverse=True`
did.

#### Prose (P-1, P-2)

Both sites said *"ranked by denoising_score descending (higher is better)"* —
true only of TIDMAD. They now describe ranking best-first on the metric the
records declare, and document the unranked-row contract. Pinned by
`TestTheOperatorProseStatesNoFixedDirection`, which asserts the old sentence
is GONE from both files.

#### FINDING F-P2a-3 — a third fixture generation had the same gap

`tests/unit/dashboard/test_local_json.py`'s `_make_record` also predated
`metric_result`, so four tests failed the same way the resume ones did. Same
disposition: upgrade the FIXTURE (it now stamps the identity a real
post-Step-06 record carries, and takes `metric_identity=None` to build a
legacy row deliberately), never the assertion. Three separate fixture
generations — resume, resume-incumbent, dashboard — all predated the field
the design says is "already persisted everywhere a P2a consumer ranks"
(§4.4). That statement is true of PRODUCTION records and was not true of the
test corpus; the ledger records the distinction because a reader of §4.4
would otherwise expect no fixture work at all.

#### Census movements

```text
EXPECTED_ORDERING_SURFACE        5 -> 1   (only the C4 proposer cut remains)
NOT_REACHED_DIRECTION_CONSUMERS  2 -> 0   (EMPTY — every D1 consumer reached)
MIGRATED_TO_THE_ORDER_AUTHORITY  +4
FORBIDDEN_CONSUMERS (Step 06 live-route)  local_json.py -> MIGRATED_CONSUMERS
```

`test_the_migrated_consumers_no_longer_hold_their_literal` asserted the literal
string `MetricOrder` appears in every migrated file. C3's consumers reach the
authority INDIRECTLY through `persisted_ranking`, so the guard gained a
per-row `_AUTHORITY_MARKERS` map — the property stays ASSERTED (each row
declares how it reaches the authority) rather than becoming an unchecked
exemption. `dashboard/data_sources/base.py` is a prose-only row and declares
`"metric identity"`.

### 13.5 C4 + C5 — the proposer cut, and the surface closed

**Landed in**: `nodes/proposal_helpers.py`,
`execute_tools/evaluation_metric.py` (one validator generalized),
`tests/unit/nodes/test_step10_p2a_c4_proposer_top_n.py` (NEW — it creates the
owner, exactly as the plan predicted it would need to), and the scanner's
retirement to standing-guard status.

#### The threading question had a better answer than the plan assumed

The plan asked C4 to "thread the evidence's metric identity to the helper".
Source audit found threading unnecessary: `select_candidate_models` already
receives the whole serialized `InterpretationOutput`, and
`metric_identity` — Step 09a's ordering PROVENANCE — has been in that dict
since 09a merged. **The proposer simply never read it.** So C4 adds a READ,
and the helper's signature is unchanged (pinned by
`test_the_helper_signature_did_not_change`). That is the narrowest possible
form of this commit, and it leaves P3's reader architecture completely
untouched (`test_no_typed_evidence_reader_was_introduced` asserts the module
still defines zero classes).

#### One more vocabulary near-miss, caught before it landed

The first draft of `_interpretation_order` validated the digest's direction
against a local `_KNOWN_DIRECTIONS` constant — the same defect as F-P2a-1, in
a different file. Rather than let Step 06's C5 guard catch it a second time,
the validator was generalized instead: `metric_identity_from_record` now
delegates to `metric_identity_from_mapping`, the ONE validator for a
transported `(metric_id, direction)` pair whatever shape carries it, still
reading the vocabulary through `get_args(MetricDirection)`. Two shapes, one
validator — the same pattern as the reconciliation engine's two entry points.

#### C5 — the surface is closed

```text
production ordering sites at the implementation base : 12
production ordering sites at this head               :  0
```

`EXPECTED_ORDERING_SURFACE` is EMPTY and `NOT_REACHED_DIRECTION_CONSUMERS` is
EMPTY. Both tuples are KEPT rather than deleted, so the censuses still name
the concept and a future unmigrated site has an obvious home.

**An empty census is exactly the case that can lie**, so the design requires
the plant-and-catch to distinguish "nothing to find" from "no longer looking".
Both halves are now asserted:

* *detection* — the two plants re-run at THIS head, one at a time, in a
  scratch production module inside the scanned surface:

  ```text
  direct : record["denoising_score"] > incumbent
           => RED, naming ('workflows/_p2a_final_plant.py',
                           "record['denoising_score'] > incumbent")
  alias  : primary_score = record["denoising_score"]; primary_score > incumbent
           => RED, naming ('workflows/_p2a_final_plant.py',
                           'primary_score > incumbent')
  revert => 30 passed; `git status` clean of the plant
  ```

* *non-deletion* — `test_the_empty_surface_is_not_vacuous` asserts the
  migrated files really do consult the order authority (directly, or through
  the shared composer), so a surface emptied by DELETING the code fails
  rather than passing.

### 13.6 Terminal validation — what the exact-head CI caught

The first two CI runs FAILED, and both failures were real defects in this
PR's own work that local targeted validation could not have found. Recorded in
full because "CI went red twice" is the useful part of this ledger, not a
footnote.

#### Run 1 — `32426331908` on `4ab53096`: **FAILURE**, 2 pyright errors

Exactly the class this PR flagged from C0 onward as CI-owned: the vendored
pyright 1.1.409 cannot start under this machine's Node `v10.19.0`, so the type
check was never claimed green locally.

```text
dashboard/data_sources/local_json.py:214
  corpus_order takes a Sequence and was handed a generator
execute_tools/evaluation_metric.py:955
  `direction not in get_args(MetricDirection)` is the correct RUNTIME check,
  but get_args returns tuple[Any, ...] so pyright cannot narrow through it
```

Fixed in `38a75f43`. The second fix is worth stating: the obvious way to
satisfy the checker — spelling `("higher", "lower")` inline — is exactly the
second direction vocabulary this PR exists to prevent, and F-P2a-1 had already
caught that same shape once. A `cast` asserting only what the runtime check
established is the correct tool, and it is commented as such.

#### Run 2 — `32426558739` on `38a75f43`: **FAILURE**, 8 unit tests

All eight in areas the local regression block did not cover
(`tests/unit/agent/ml_model_proposal_agent`,
`tests/unit/sdsc_submission_scripts`, plus one Step-09a census). Two distinct
causes.

**FINDING F-P2a-4 — P2a added a FIFTH production TIDMAD-derivation site.**
The serious one.

```text
FAILED test_step09a_c2_metric_spec_contract.py::
  TestStep09AddsNoProductionMetricDerivationSite::
  test_the_production_derivation_call_sites_are_exactly_the_expected_four
```

C2's `_table_order` fell back to `derive_tidmad_metric_spec(TIDMAD_PROFILE)`
when no source carried a stamp, on the reasoning that `per_file_best` already
emits `metric_id: TIDMAD_METRIC_ID` in its own table header. **That reasoning
was wrong, and it violated a FROZEN invariant of this very child** — §0:
*"P2a does NOT derive metric identity anywhere."* Step 09a's executable census
pins the exact set of production modules permitted to derive the TIDMAD
metric, and the fallback made this a fifth.

Emitting a metric's NAME is not the same as being entitled to invent its
DIRECTION. The fix removes the derivation entirely: `_table_order` now
reconciles over both sources §4.4 actually names for this module — each
iteration's stamped `MetricSpec` **and** each scored record's persisted
`metric_result` — and returns `None` when nothing declares an identity, in
which case the table emits its header and provenance but selects no rows and
says why. The census is restored untouched; the code changed.

**F-P2a-3, generations four and five.** The remaining six failures were the
same fixture gap already recorded three times: `FAKE_INTERPRETATION` and the
`test_proposal_helpers` fixture carry no `metric_identity` (so `top_n` took the
Q-P2a-1 unranked fallback instead of the cut those tests assert), and
`_p1_record` / `_p1_tune_output` in the sdsc chain-incumbent tests carry
neither `metric_result` nor `metric_spec` (so the chain fold correctly refused
to restore an incumbent). Same disposition every time: **upgrade the FIXTURE
to what a real post-Step-06/09a artifact carries, never the assertion**, with
the refusal keeping its own dedicated coverage.

Running total: **five** separate fixture generations predated the identity
fields — resume, resume-incumbent, dashboard, per-file-best, proposer/sdsc.
§4.4's "already persisted everywhere a P2a consumer ranks" is a true statement
about PRODUCTION records and was not true of the test corpus, and that gap is
the single largest source of work in this PR.

#### What this says about the validation plan

The frozen §7 plans named per-commit targeted suites, and those suites were
run and were green. They did not cover `tests/unit/agent/ml_model_proposal_agent`
or `tests/unit/sdsc_submission_scripts`, because nothing in the C2/C3 diffs
pointed at them — the coupling is through PERSISTED RECORD SHAPE, not through
imports. The exact-head CI is what closed that gap, which is precisely the
division of labour the repository's validation-economy rule describes: targeted
suites during implementation, ONE canonical broad run at the final head.

### 13.7 POST-P4 RECONCILIATION + FINAL REVIEW (2026-08-20)

P4 merged in parallel. This section records the independent final review, the
D-P2a-4 disposition, and the reconciliation onto post-P4 master. **No frozen
semantic ruling is amended here** — only evidence, dispositions, and the
wording corrections listed in §0.1.

#### Independent review at `0ea3d238` — twelve items, all verified from source

| # | claim | measured |
|---|---|---|
| A | ordering surface closed | **0 sites / 308 production files** (12 at the base) |
| B | exactly one reconciliation authority | census green; one engine `_reconcile_declarations`, two typed entry points |
| C | no P2a site derives TIDMAD identity | 09a derivation-site census green (3 tests); `per_file_best` mentions `derive_tidmad_metric_spec` only inside a docstring explaining its REMOVAL |
| D | four-case identity semantics | C2/C3 matrices green |
| E | resume tie behaviour | all nine C0 probes reproduce; 7 direction-independent probes identical under both directions, exactly 2 invert |
| F | per-file-best | 19 tests green; acquisition = stamps + `metric_result` → shared reconciliation → order or `None` |
| G | dashboard / diagnostic ranking | C3 module + dashboard suite green |
| H | proposer `top_n` DAVIS inversion | `top_n(2)` = best two; counterfactual asserted different |
| I | scanner anti-vacuity | direct + alias plants both RED at the final head, green after revert |
| J | no P3 typed reader | `nodes/proposal_helpers.py` defines **zero classes** |
| K | no secondary-metric work | **0** occurrences of `secondary_metric` in the whole diff |
| L | no LLM-facing change | zero bytes under `agent/prompt_templates/`; the only node file touched is `evidence.py` (the reconciliation projection) |

The C0 discovery (10 planned → 12 measured sites) is NOT reopened: both extra
sites are primary-score decisions inside `restore_prior_state`, the resume
selection failure class P2a already owns, and `_candidates_from_persisted_verdicts`
literally calls `_pick_best`.

#### D-P2a-4 — FINAL DISPOSITION: **ACCEPTED / BOUNDED**

The complete production diff to `execute_tools/metric_order.py` is: one import
line, the `Args:` docstring, an explanatory note, and

```python
-    def __init__(self, spec: MetricSpec) -> None:
+    def __init__(self, spec: MetricDeclaration) -> None:
```

The body is byte-identical. The eight required checks, each measured by AST
inspection rather than asserted:

| # | check | evidence | verdict |
|---|---|---|---|
| 1 | body/runtime behaviour unchanged | diff touches no statement | **PASS** |
| 2 | reads only `direction` | the ONLY attribute read from the parameter is `spec.direction` | **PASS** |
| 3 | no method assumes a `MetricSpec`-only field | `__slots__ = ("_higher", "direction")` — **the declaration object is never retained**, so no method CAN reach `aggregation`/`scoreability` | **PASS** |
| 4 | no new ordering branch/method/state | all 15 methods read only `direction`/`_higher` (`rank` delegates to `is_better`) | **PASS** |
| 5 | no second comparator | Step-06 C5 + reconciliation censuses green | **PASS** |
| 6 | no fake `MetricSpec` synthesized | the single `MetricSpec(` construction in production is the pre-existing `derive_tidmad_metric_spec`, untouched by P2a | **PASS** |
| 7 | no new persisted schema | `MetricIdentityKey` is a runtime `NamedTuple`; it appears on no Pydantic model and in no artifact | **PASS** |
| 8 | `MetricOrder` remains the ONE interpreter | Step 06 C5 boundary guard green | **PASS** |

Check 3 is the decisive one: because `__slots__` excludes the spec, a
`MetricIdentityKey` is sufficient for **every** method by construction, not by
review diligence. The stale §8 sentence that contradicted this is corrected
rather than the code reverted (§0.1).

#### F-P2a-4 re-verified

No executable `derive_tidmad_metric_spec` or equivalent direction derivation
remains in `per_file_best`; the acquisition path is stamps + `metric_result`
→ shared reconciliation → order, or `None` with the named unavailable state.
The 09a derivation-site census passes with its expected set **unchanged** —
P2a adds zero derivation sites. Emitting a metric's NAME in a header does not
grant authority to invent its direction.

#### stdout contract re-verified

`test_cli_print_only_writes_canonical_json_to_stdout` passes; the byte-exact
contract holds. Every P2a diagnostic goes to **stderr** — `per_file_best` via
`file=sys.stderr`, `persisted_ranking` via `_notify`. Fixed at the source, not
worked around in the test.

#### Reconciliation onto post-P4 master — MERGE-BASED (final strategy)

```text
strategy           : MERGE origin/master INTO the PR branch
                     (force push NOT used — see the correction note below)
old remote P2a head: 0ea3d238
merged master      : 9f475980  (P4 squash 79833db8 is its parent)
shared files       : 0   (P4 touched 24, P2a touches 30, intersection EMPTY)
textual conflicts  : NONE
semantic conflicts : NONE
merge commit       : 553bd66c  (both parents preserved; 0ea3d238 remains an
                     ancestor, so the remote updates by NORMAL push)
```

**Strategy correction, recorded rather than smoothed over.** A REBASE onto
`9f475980` was performed first (all 10 commits replayed conflict-free, rebased
head `a2056ff1`, then `77990a0a` with the validation record). Publishing it
required a force push — and `.claude/settings.local.json` carries a standing
DENY on `git push --f*`. That denial is an intentional repository guardrail,
and the operator ruled it must not be bypassed, relaxed, respelled, or evaded
by closing/recreating the PR. The rebase was therefore SUPERSEDED by this
merge-based reconciliation: the rebased state was preserved as the local
safety ref `p2a-post-p4-rebased-backup` (`77990a0a`), the branch was restored
to its remote history, `origin/master` was merged in, and the post-review
document corrections were brought over as one dedicated docs commit rather
than by replaying implementation commits.

**Tree-equivalence audit (rebased candidate vs merge-based candidate).**
`git diff p2a-post-p4-rebased-backup` against the final merge-based tree is
**EMPTY** — the two candidates are byte-identical in content, production and
docs alike; only the Git ancestry differs. The §5 expectation ("do NOT assume
ancestry equivalence implies tree equivalence") was checked, not assumed.

Conflict-freedom had been proven BEFORE any ref moved: a trial merge in a
detached scratch worktree reported *"Automatic merge went well"*, and the
combined tree was checked from both sides —

```text
git diff origin/master -- execute_tools/health_checks/   -> EMPTY  (P4 intact)
git diff <p2a-head>    -- metric_order.py persisted_ranking.py
                          proposal_helpers.py resume.py   -> EMPTY  (P2a intact)
```

Post-merge re-verification: ordering surface **0 / 308 files**;
`origin/master` and `0ea3d238` are BOTH ancestors of the merge head;
`execute_tools/health_checks/` is byte-identical to master, so P2a touches
none of P4's Health surface.

#### Targeted post-reconciliation validation

Run once at the rebased candidate, and again (compact authoritative slice) at
the merge-based head. Because the two candidates' trees are **byte-identical**
(the audit above), the broad result transfers by construction; the second run
is direct evidence at the actual final tree rather than an inference.

```text
broad (at the rebased candidate; tree byte-identical to the merge head):
  command : pytest tests/unit/{execute_tools,core,dashboard,nodes,scripts,
                                sdsc_submission_scripts,
                                agent/ml_model_proposal_agent,
                                agent/result_interpretation_agent} -q
  result  : 6540 passed, 2 skipped, 0 failed in 339.30s
  static  : ruff check -> All checks passed
            ruff format --check -> 1081 files already formatted

direct (at the merge-based tree):
  scanner + goldens + reconciliation + resume/per_file_best + persisted
  consumers + proposer top_n + Step-06/09a censuses + stdout contract +
  P4 structural guards — counts recorded beside the final CI in the PR body
  surface : 0 ordering sites / 308 production files
```

This span deliberately covers BOTH children's owners — P2a's authorities plus
the areas the pre-reconciliation CI runs proved were coupled through persisted
record shape (`ml_model_proposal_agent`, `sdsc_submission_scripts`) — so the
combined tree is evidence, not an assumption. Gate 1, Gate 2, real LLM and
training/GPU: NOT REQUIRED, NOT RUN, unchanged from the frozen disposition.

---

*END — REVISION 3 — FROZEN, operator approved 2026-08-20 (post-P1-merge
reconciliation + semantic rulings applied). Source anchor `bcb17e45`.
Implementation status AT THE FREEZE COMMIT: NOT STARTED — the current
lifecycle is §0.1. Gate 1 NOT REQUIRED; Gate 2 NOT REQUIRED. P2b remains
DRAFT and reconciles after P2a merges.*
