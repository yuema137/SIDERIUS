# Step 10 / P2a — Golden `MetricOrder` Closure

## 0. Status

**REVISION 3 — FROZEN. OPERATOR APPROVED (2026-08-20).
IMPLEMENTATION NOT STARTED. Open operator questions: 0.
Material contradictions: 0.**

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
- [ ] Enumerate the production file set the scanner walks — it MUST include
      `workflows/task_composition.py` (P1-added, verified zero ordering
      shapes at `bcb17e45`) and `dashboard/` — and record the count.
- [ ] State the standing-guard contract at the scanner module's top: it is
      exhaustive for the CURRENT known carrier shapes only, and a future
      primary-score carrier shape must extend it in the same change (§5).
- [ ] Implement the flagged shapes: `Compare(Gt|GtE|Lt|LtE)`,
      `sorted`/`list.sort(reverse=True)`, and `max()`/`min()` whose operand
      mentions a golden-score name (`denoising_score`, `best_score`,
      `best_formal_denoising_score`, `best_valid_denoising_score`,
      `best_linear`, and `score` when bound from a record's
      `denoising_score` key — same-function assignment tracking only, no
      interprocedural analysis).
- [ ] Implement the allowlist with a MANDATORY reason per entry, and a
      self-check that fails on a reasonless entry.
- [ ] Self-calibrate: the scanner must report EXACTLY the §2.1 sites at the
      base. Record the byte-exact output in this ledger.
- [ ] Capture pre-migration goldens: for each of sites 1–5, a fixture
      sequence and the ordered list of pairwise decisions it produces.
- [ ] Plant-and-catch, TWO plants (§5): a direct raw `>` on
      `denoising_score` in a scratch production module, AND the local-alias
      offender (`primary_score = record["denoising_score"]` then
      `primary_score > incumbent`). Both RED; revert; record. The alias
      plant proves same-function assignment tracking is real.

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
- [ ] Scanner output at base == the §2.1 site list EXACTLY: 10 code sites,
      0 unexpected, 0 missing. The list is recorded verbatim in the ledger.
- [ ] Every §2.2 precision fixture is NOT flagged (asserted individually, so
      a regression names which class broke).
- [ ] The planted raw `>` turns the scanner RED, and its removal turns it
      green again — both recorded.
- [ ] Goldens for sites 1–5 record the DECISION SEQUENCE (ordered pairwise
      outcomes), not only the selected element.
- [ ] Zero production files changed in this commit (`git diff --stat`
      recorded).

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| a production file fails to parse | scanner REPORTS it (fail-closed); a silently skipped file is an invisible site |
| a golden-score name appears in a comment or string | NOT flagged — the census is AST-shaped (the parent's §3.8 anti-vacuity lesson) |
| `score` bound from something other than a record's `denoising_score` | NOT flagged; dataflow-lite is same-function only, and the limit is stated rather than approximated |
| a site legitimately outside `MetricOrder` | allowlisted WITH a reason; a reasonless entry fails the self-check |

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest <scanner test module> -q` — record count + wall time.
- [ ] Scanner base output — record verbatim.
- [ ] `git diff --stat` — record (must show no production file).
- [ ] `ruff check` + `ruff format --check` on touched files.

**8. Commit boundary.** Test-only; independently reviewable as "the
instrument and the baseline". No production migration, no presence-list
retirement, no unrelated cleanup. Before committing: show the diff summary,
staged file list, test counts, and any deviation from this plan.

---

### C1 — reconciliation authority promotion + in-run sites (1, 2, 3)

**1. Goal.** The three decisions a LIVE run makes about the golden metric —
raw-formal best tracking, chain formal incumbent advance, and the
`target_score` early stop — stop assuming higher-is-better. These three
belong together because they share one new rule (§4.1's acquisition
precedence) and one refusal branch; splitting them would leave an
intermediate head where a run advances its incumbent by one direction rule
and stops early by another.

**2. Scope.**
* `workflows/model_exploration.py` — sites 1–3 (at the P1 head: `:2744`,
  `:2756`, `:2804`; re-verify at the true base).
* The §4.1 acquisition helper and the shared Q-10-2 refusal notice
  (placement per §4.5; candidate is a small function beside `MetricOrder` —
  NOT a new module).
* UNCHANGED: tie-break rules, validity filters, the round/retry semantics,
  every non-golden comparison in the same functions, and all LLM-facing
  bytes (these three sites feed no prompt).
* Depends on: C0 (goldens + scanner).

**3. Implementation plan.**
- [ ] Re-verify the three line anchors and read each comparison in full
      before editing.
- [ ] **PROMOTE the reconciliation authority first (Q-P2a-3)**: move
      `reconcile_metric_spec`'s semantics from
      `nodes/result_interpretation_agent/evidence.py:58` to
      `execute_tools/evaluation_metric.py`, generalized to accept the
      available identities (bound spec and/or stamped specs); the
      interpreter node imports the shared authority; its refusal semantics
      (partial stamping ⇒ refuse, mixed ⇒ refuse) preserved EXACTLY; a
      census pins exactly ONE reconciliation implementation.
- [ ] Implement §4.1 reconciliation at sites 1–3: collect bound
      (`bindings.task_composition.metric.spec`) + the compared output's
      stamp → reconcile → `MetricOrder`; bound-vs-stamp CONFLICT fails
      closed; nothing available ⇒ §4.2 unrankable branch.
- [ ] Implement the canonical metric-identity-unavailable message/formatter
      beside the reconciliation authority (Q-P2a-2); every consumer renders
      THIS formatter's output.
- [ ] Migrate site 1 and site 2 to `order.is_better`, site 3 to
      `order.is_at_least`.
- [ ] Implement the workflow refusal branch: skip the update, print the
      named notice once per run, never assume a direction.
- [ ] Update the scanner allowlist / expected set in the SAME commit, and
      retire the `NOT_REACHED_DIRECTION_CONSUMERS` rows these three sites
      empty, each citing this commit.

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
- [ ] DAVIS fixture (`lower`): the incumbent advances on a DECREASE
      (`0.0174 → 0.0172` advances; `0.0172 → 0.0210` does not), and the
      recorded decision sequence matches the hand-computed literal exactly.
- [ ] TIDMAD fixture (`higher`, negative values): decision sequence
      byte-equal to the C0 golden.
- [ ] `target_score` under `lower`: `0.0172` satisfies `target 0.0173`;
      `0.0174` does not.
- [ ] Refusal: the named notice string appears VERBATIM, fires once per run,
      and the tracker is left unchanged (asserted on the tracker, not only on
      stdout).
- [ ] The scanner no longer reports sites 1–3 and still reports the rest.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| legacy record with no `metric_spec` | skip the update + named notice; never assume a direction; never hard-fail the run |
| mixed specs across compared artifacts | existing `reconcile_metric_spec` refusal, unchanged — P2a adds no second reconciliation |
| `None` / NaN scores | existing validity filters run BEFORE ordering and are not weakened |
| composed run whose bound spec disagrees with an artifact stamp | fail closed through the existing reconciliation; do NOT silently prefer one |

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/workflows -q` — record count + wall time.
- [ ] The three-task fixture module — record count.
- [ ] Decision-sequence goldens — record the compared literals.
- [ ] Any command that could not be run — record WHY; never claim it passed.

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
- [ ] Read both functions in full, including every tie-break branch below
      the score comparison.
- [ ] Migrate ONLY the score comparison in each; leave every tie branch
      textually untouched.
- [ ] Site 4, per §4.2a (PER-RECORD, not per-iteration): rank the
      compatible-identity subset; missing-identity records individually
      excluded with the named state; no rankable records ⇒ no incumbent +
      named notice, restore continues; conflicting KNOWN identities ⇒ fail
      closed per the existing restore soft-failure policy. The identity
      inputs are the output's own `metric_spec` stamp + per-record
      `metric_result`, reconciled through the SHARED authority.
- [ ] Site 5, per the §4.3 ruling: migrate the score comparison to
      `MetricOrder`; document the CURRENT transform's monotonicity beside
      the site and pin it with a hand-computed fixture (linear ranking ==
      log ranking for `_log` base 5.27 on TIDMAD-shaped values). NO generic
      monotonicity assertion is added — a future non-monotone display
      transform is a named future capability requirement of the metric
      interface, recorded, not faked here.
- [ ] Retire the census rows these two sites empty, citing this commit.

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
- [ ] Under `lower`, `_pick_best` selects the MINIMUM and `_row_beats`
      prefers the smaller `best_linear`.
- [ ] Every tie fixture's outcome is byte-equal to its C0 golden, asserted
      per tie class so a regression names which rule broke.
- [ ] Resume four-case matrix (§4.2a): all-known ranks; known+missing ranks
      the known subset and excludes the missing rows INDIVIDUALLY;
      all-missing restores no incumbent with the named notice and the
      restore continues; conflicting-known fails closed per the existing
      soft-failure policy — each case asserted on the restored incumbent,
      not on stdout alone.
- [ ] The site-5 monotonicity fixture pins linear-order == log-order for the
      CURRENT transform with hand-computed literals.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| all records spec-less | no incumbent restored; named notice; restore continues (never a hard failure) |
| SOME records spec-less | the compatible subset is ranked; missing rows are individually unranked — one legacy row never poisons the corpus (§4.2 case B) |
| conflicting KNOWN identities in one pool | fail closed per the existing restore soft-failure policy; never a silent pick (§4.2 case D) |
| equal scores | existing tie-break, unchanged and asserted |
| legacy rows with no round provenance | existing persisted-over-legacy rule, unchanged |
| non-monotone linearization | the site-5 assertion FAILS LOUDLY rather than ranking on a transformed value |

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/core/test_resume.py tests/unit/execute_tools -q -k "best or resume"` — count + wall time.
- [ ] Tie-class golden comparison — record per class.

**8. Commit boundary.** Two helpers + their census rows. No consumer of
either is modified. Show diff summary, staged files, counts, deviations
before committing.

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
- [ ] Read each of the four call sites and confirm which persisted field
      carries identity for that corpus (`metric_result.direction` on records;
      `metric_spec` on outputs — §4.4).
- [ ] Migrate ranking/extrema to `MetricOrder` built from persisted
      identity.
- [ ] Implement the §4.2 four-case display semantics PER ARTIFACT: the
      compatible subset ranks; each missing-identity row shows the canonical
      unavailable state (Q-P2a-2 formatter) and no rank, raw scalar still
      shown; all-missing shows no ranking; conflicting-known refuses the
      ranking view with the named diagnostic. One legacy row never poisons
      the corpus.
- [ ] Replace both prose sites with `direction_words`-derived text.
- [ ] Retire the census rows these sites empty, citing this commit.

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
- [ ] `lower` corpus ranks ASCENDING and `best_agent_score` is the MINIMUM.
- [ ] Mixed corpus (case B): the known-identity rows rank; the absent row is
      individually unranked with the canonical state; the ranked rows'
      order is unaffected by the absent row's scalar.
- [ ] All-absent corpus (case C) renders the canonical unavailable state,
      shows NO rank, and still displays raw scalars.
- [ ] Conflicting corpus (case D) refuses with the named diagnostic and
      ranks nothing across the conflict.
- [ ] TIDMAD corpus: ranking order and prose byte-identical to pre-migration.
- [ ] No prompt template or LLM-facing byte changes (pinned by grep — these
      are dashboard/API strings, not prompts).

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| corpus mixing two KNOWN metric identities | fail closed with a named diagnostic; never rank across incomparable metrics (§4.2 case D) |
| corpus mixing known + ABSENT identity | rank the known subset; the absent rows are individually unranked (§4.2 case B) — absence is not a conflict |
| record with identity, score `None` | existing filter; not a refusal case |
| empty corpus | current behaviour preserved |
| legacy pre-06 records (no `metric_result`) | Q-10-2 refusal path, not an exception |

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/dashboard tests/unit/scripts -q` — count + wall time. Both directories VERIFIED present (3 and 26 modules); the site-6/7 owner is `tests/unit/dashboard/test_local_json.py`.
- [ ] Prose parity grep — record the compared strings.

**8. Commit boundary.** Read-only artifact consumers + their prose. No
in-run behaviour, no proposer. Show diff summary, staged files, counts,
deviations before committing.

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
- [ ] Read the full strategy helper, including the `all` branch and every
      caller, before editing.
- [ ] Thread the evidence's metric identity to the helper WITHOUT building a
      typed reader (P3's scope) — record exactly how, so P3 can replace the
      mechanism without re-litigating the semantics.
- [ ] Migrate the cut to `MetricOrder`.
- [ ] Implement the absent-identity branch per the RESOLVED Q-P2a-1: named
      notice → the existing `all` semantics. NO metric-based ranking
      happens; the result is never labelled "best"/"top N"; no new
      selection policy is introduced.
- [ ] Retire the census row this site empties, citing this commit.

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
- [ ] DAVIS `[0.0174, 0.0172, 0.0210]`, `top_n(2)` returns exactly
      `{0.0172, 0.0174}` — the inversion this commit exists to fix.
- [ ] Pets `[0.027, 0.61, 0.33]`, `top_n(2)` returns exactly `{0.61, 0.33}`.
- [ ] TIDMAD fixture: returned list byte-equal to pre-migration, in order.
- [ ] Absent identity: the named notice fires, the returned candidate set
      IS the existing `all` path's result (asserted equal against a direct
      `all` invocation on the same fixture), and nothing labels it
      "best"/"top N" anywhere it is rendered.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| absent metric identity | named notice + the EXISTING `all` semantics (Q-P2a-1 RESOLVED); never a silently inverted cut; never a first-N cut wearing a top-N name |
| `n` larger than the candidate count | current behaviour preserved |
| all `best_score` values `None` | existing filter (`scored` is empty); current behaviour preserved |
| identity present but unknown direction value | fail closed via `MetricSpec`'s own vocabulary; no default |

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest tests/unit/agent/ml_model_proposal_agent tests/unit/nodes -q -k "top_n or strategy"` — count + wall time. Both directories VERIFIED present (39 and 4 modules). **Note for the implementation session**: no existing test module is named for `proposal_helpers`, so C4 likely CREATES the owner rather than extending one — confirm before assuming a home for the inversion test.
- [ ] Inversion-test literals — record.

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
- [ ] Verify every retired row cites the commit that emptied it.
- [ ] Remove the presence list; the scanner is the sole standing guard.
- [ ] Docs sync: update any touched node/skill `.md`, quoting each changed
      behaviour against merged source. **`docs/running_chain_test.md` does
      NOT exist** — P1 found it to be a stale design anchor, and there is no
      canonical launcher-flag reference document; the repository's precedent
      is that a subsystem's own design doc is its operator surface. Confirm
      which `.md` files actually exist before planning edits to them.
- [ ] Tick every checklist item above with its recorded evidence.

**4. Validation plan.**
* Unit: the scanner reports ZERO unallowlisted sites.
* Negative: re-run the C0 plant-and-catch at the final head — the scanner
  must still be able to fail.
* Backward-compat: N/A (no production change).
* Real-training Gate: **NONE.**

**5. Acceptance criteria.**
- [ ] Scanner green with zero unallowlisted sites at the final head.
- [ ] `NOT_REACHED_DIRECTION_CONSUMERS` no longer exists, and no test
      references it.
- [ ] Plant-and-catch still RED at the final head (the guard is live, not
      vacuous).
- [ ] Every C0–C5 checklist item is `[x]` with evidence, or explicitly
      recorded as not-run WITH the reason.
- [ ] ONE exact-head CI on the final PR head; run id and tested SHA recorded.

**6. Failure and edge cases.** A row with no citing commit ⇒ STOP: it means a
site was never migrated. A scanner that reports zero sites AND zero
allowlist entries ⇒ suspect vacuity; the plant-and-catch is what
distinguishes the two.

**7. Verification commands and evidence.**
- [ ] `.venv/bin/python -m pytest <scanner module> tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py -q` — count + wall time.
- [ ] Exact-head CI run id + `headSha` — record both.

**8. Commit boundary.** Census + docs + ledger. No production change, no
unrelated cleanup. This is the last commit before READY FOR OPERATOR REVIEW.

---

## 8. Preservation invariants

TIDMAD ordering decisions byte-identical on recorded fixtures (higher +
negative values); tie-breaks unchanged; no LLM-facing surface changes (the
prose sites are dashboard/API text, not prompts — pinned by grep in C3);
`MetricOrder` module unchanged; the tuner untouched.

## 9. Failure / edge cases

Mixed specs across a comparison (existing `reconcile_metric_spec` failure
surfaces — pinned); NaN/None scores (existing validity filters run BEFORE
ordering and are not weakened); empty candidate sets (current behaviour
preserved); a future non-monotone linearization (site-5 assertion fires).

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
| 19 | Did P2a create another metric-order enum/helper/comparator? | **CLOSED** — `MetricOrder` unchanged; the scanner + the §8.1 census forbid a second interpreter |
| 20 | Did P2a put reconciliation inside MetricOrder incorrectly? | **CLOSED** — §4.1a places it beside `MetricSpec` in `evaluation_metric.py`, with the responsibility split stated |
| 21 | Does the site-5 monotonicity claim match actual executable capability? | **CLOSED** — §4.3: the ranked values ARE the persisted per-file evidence; only the CURRENT transform's monotonicity is documented+tested; no generic assertion is faked; future non-monotone transforms are a named capability requirement |
| 22 | Can the scanner detect at least one alias-shaped offender? | **CLOSED** — §5 requires TWO plants, direct + local alias, both RED |
| 23 | Are future new score-carrier shapes required to extend the scanner? | **CLOSED** — §5's narrowed standing-guard contract, stated at the scanner module's top |
| 24 | Did the P1 merge introduce any new ordering surface? | **CLOSED** — §10.3 re-scan: exactly the known 10 code sites; `task_composition.py` carries zero ordering shapes |
| 25 | Can P2a merge with P2b absent and leave master coherent? | **CLOSED** — nothing here touches secondaries; every commit leaves the un-migrated remainder on its legacy behaviour (parent §21) |

**Open operator questions: 0. Material contradictions: 0.**

---

*END — REVISION 3 — FROZEN, operator approved 2026-08-20 (post-P1-merge
reconciliation + semantic rulings applied). Source anchor `bcb17e45`.
Implementation status at the freeze commit: NOT STARTED. Gate 1 NOT
REQUIRED; Gate 2 NOT REQUIRED. P2a implementation begins in a FRESH session
from a newly filled Implementation Working Rules contract; P2b remains DRAFT
and reconciles after P2a merges.*
