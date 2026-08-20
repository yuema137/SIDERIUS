# Step 10 / P2a — Golden `MetricOrder` Closure

## 0. Status

**DRAFT rev 2 — FOR OPERATOR REVIEW. NOT FROZEN. IMPLEMENTATION NOT
STARTED.** Parent semantics complete; **implementation details subject to
post-P1-merge reconciliation** (upstream-sensitive items are labelled
`PROVISIONAL(P1)` throughout).

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
| source anchor | merged `master` = **`2393aacc`**. Line anchors are facts of this anchor and are expected to move under P1 — they are evidence, not implementation authority |
| depends on | **P1 merged** (the run's bound `MetricSpec` must exist to be consumed). P2b depends on this child, not vice versa |
| Gate disposition | proposed: NO Gate — direction is deterministic; three-task hand-computed fixtures + the structural scanner are the owners (parent §22.1). Quoted against the gate standard at freeze |
| open operator questions | **3** (§11) — Q-P2a-3 is NEW in rev 2 and BLOCKS C1 |

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

## 2. Current source audit — the complete ordering surface (at `2393aacc`)

### 2.1 The ten code sites + two prose sites

| # | site (current line) | what it decides | order source after P2a |
|---|---|---|---|
| 1 | `workflows/model_exploration.py:2655-2659` (`>` at `:2657`) | raw-formal progress → `state.best_score_overall` | in-run spec — `PROVISIONAL(P1)`: composed ⇒ `bindings.task_composition.metric.spec`; legacy ⇒ the compared `tune_output.metric_spec` (09a stamp); both absent ⇒ refusal (§4.2) |
| 2 | `workflows/model_exploration.py:2666-2671` (`>` at `:2669`) | **chain formal incumbent advance** | same |
| 3 | `workflows/model_exploration.py:2714-2718` (`>=` at `:2717`) | early-stop `target_score` | same; `is_at_least` |
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

### 4.1 Order acquisition precedence (the one genuinely new rule)

For a consumer inside a live run:

```text
composed run        → MetricOrder(bindings.task_composition.metric.spec)   PROVISIONAL(P1)
legacy run          → MetricOrder(spec stamped on the compared artifact(s))
                      (HyperparamTuningOutput.metric_spec, 09a; reconciled
                       across artifacts by the existing reconcile_metric_spec)
no spec anywhere    → REFUSAL: the comparison does not happen; the consumer
                      takes its Q-10-2 branch (§4.2)
```

Mixed specs across compared artifacts fail closed through
`reconcile_metric_spec`'s existing behaviour — P2a adds no second
reconciliation.

### 4.2 Q-10-2 refusal shapes, per consumer

| consumer | refusal behaviour |
|---|---|
| workflow sites 1–3 | a legacy record with no spec cannot advance the incumbent/best tracker: the update is skipped with a printed named notice (once per run), never an assumed direction. (In practice unreachable post-09a — every scored output is stamped — but the branch must exist and be tested) |
| resume `_pick_best` | records without spec ⇒ that iteration restores **no incumbent** (named notice); restore continues otherwise — never hard-fails |
| dashboard | unranked listing + the literal *"metric direction unavailable (`metric_spec` absent)"* string; raw scalars still displayed |
| diagnostic scripts | same string to stderr; summary marks `best: unavailable` |
| proposer `top_n` | no spec in the evidence ⇒ **NO metric-based ranking is performed.** Whether the proposer then continues with a bounded, score-order-INDEPENDENT candidate set or refuses to propose is Q-P2a-1 (OPEN); whatever the disposition, the result is never labelled "best"/"top N", and the named notice always fires — never a silently inverted cut |

### 4.3 Site 5 monotonicity note (recorded, not silently assumed)

`per_file_best` compares **linear-space** values derived from the golden
score. Ordering by `MetricOrder` on linear values is valid iff the
linearization is monotone increasing (TIDMAD's is: log base > 1). P2a states
this as an executable assumption beside the site (assert/comment + test),
so a future metric with a non-monotone transform fails loudly rather than
ranking wrongly.

### 4.4 Persisted-identity source for artifact consumers

Dashboard/scripts read persisted records. Post-06/09a records carry
`metric_result.direction` (`evaluation_metric.py:404-406`) and outputs carry
`metric_spec` — the consumers read what is persisted, never re-derive.
The forward half of Q-10-2 (every newly persisted artifact carries enough
identity to rank) is **already satisfied** by `metric_result`; P2a adds a
test pinning it, not a new field.

### 4.5 PROVISIONAL(P1) items — to reconcile before freeze

Exact spelling of the workflow acquisition (`bindings.task_composition…`);
whether `restore_prior_state` receives the spec as a parameter or reads the
launcher's composed value; module placement of the shared refusal-notice
helper (candidate: `execute_tools/metric_order.py` as a small function — NOT
a new module). None of these changes the semantics above.

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
* **Anti-vacuity**: a planted raw `>` on `denoising_score` in a scratch
  production module must turn the scanner RED (recorded plant-and-catch);
  the migrated sites' absence keeps it green.
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

## 7. Commit decomposition (provisional pending P1 reconciliation)

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

**Line anchors**: re-verified at the P1 implementation head `0f1e41d0`
(2026-08-20). Sites 4–10 and both prose sites are at the exact lines §2.1
records. The three workflow sites MOVED under P1 (which inserted ~89 lines
above them): site 1 `:2657 → :2744`, site 2 `:2669 → :2756`, site 3
`:2717 → :2804`. `InterpretationOutput.metric_identity` (site 10's order
source) is confirmed present. **These are evidence at a pre-merge head, not
implementation authority — re-verify at the true P2a base.**

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
- [ ] Enumerate the production file set the scanner walks; state whether it
      includes `workflows/task_composition.py` (P1-added) and `dashboard/`,
      and record the count.
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
- [ ] Plant-and-catch: a raw `>` on `denoising_score` in a scratch
      production module turns the scanner RED. Revert; record.

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

### C1 — in-run sites (1, 2, 3) + the order-acquisition precedence

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
- [ ] Implement §4.1 precedence: composed run ⇒ the P1-bound spec
      (`PROVISIONAL(P1)` spelling); legacy ⇒ the artifact-stamped spec via
      the existing `reconcile_metric_spec`; neither ⇒ refusal.
- [ ] Migrate site 1 and site 2 to `order.is_better`, site 3 to
      `order.is_at_least`.
- [ ] Implement the workflow refusal branch: skip the update, print the
      named notice once per run, never assume a direction.
- [ ] Update the scanner allowlist / expected set in the SAME commit, and
      retire the `NOT_REACHED_DIRECTION_CONSUMERS` rows these three sites
      empty, each citing this commit.

**4. Validation plan.**
* Unit: acquisition precedence — composed, legacy-stamped, and
  neither — one test each, asserting WHICH spec was used, not merely that a
  comparison happened.
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
- [ ] Site 4: records without a spec ⇒ that iteration restores NO incumbent
      + named notice; the restore continues.
- [ ] Site 5: record the linear-space monotonicity assumption (§4.3) as an
      executable assertion beside the comparison, so a future non-monotone
      transform fails loudly rather than ranking wrongly.
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
- [ ] A spec-less iteration restores NO incumbent, emits the named notice,
      and does not abort the restore.
- [ ] The monotonicity assertion fires on a synthetic non-monotone transform.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| all records spec-less | no incumbent restored; named notice; restore continues (never a hard failure) |
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
- [ ] Implement the Q-10-2 display state: unranked listing + the verbatim
      *"metric direction unavailable (`metric_spec` absent)"* string; raw
      scalars still shown.
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
- [ ] Absent-identity corpus renders the verbatim unavailable string, shows
      NO rank, and still displays raw scalars.
- [ ] TIDMAD corpus: ranking order and prose byte-identical to pre-migration.
- [ ] No prompt template or LLM-facing byte changes (pinned by grep — these
      are dashboard/API strings, not prompts).

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| corpus mixing two metric identities | fail closed with a named diagnostic; never rank across incomparable metrics |
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
* UNCHANGED: the `all` method; the reader architecture (that is P3 — this
  commit changes ONE helper's comparison); every prompt template.
* Depends on: C1's refusal helper; **Q-P2a-1 dispositioned** (see §11).

**3. Implementation plan.**
- [ ] Read the full strategy helper, including the `all` branch and every
      caller, before editing.
- [ ] Thread the evidence's metric identity to the helper WITHOUT building a
      typed reader (P3's scope) — record exactly how, so P3 can replace the
      mechanism without re-litigating the semantics.
- [ ] Migrate the cut to `MetricOrder`.
- [ ] Implement the absent-identity branch per the Q-P2a-1 disposition. What
      is already frozen: NO metric-based ranking happens, the result is never
      labelled "best"/"top N", and the named notice always fires.
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
- [ ] Absent identity: no ranking is performed, the named notice fires, and
      the result is not labelled "best"/"top N" anywhere it is rendered.

**6. Failure and edge cases.**
| case | required behaviour |
|---|---|
| absent metric identity | Q-P2a-1 branch; never a silently inverted cut; never a first-N cut wearing a top-N name |
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

## 10. Upstream-sensitive assumptions (re-audit after P1 merge)

1. `PROVISIONAL(P1)` — the composed-spec spelling and whether resume receives
   the spec by parameter.
2. Workflow site line numbers (P1 edits `model_exploration.py`).
3. The scanner's production-file set (P1 adds `workflows/task_composition.py`).

### 10.1 Anchor re-verification at the P1 implementation head (2026-08-20)

Performed while P1 awaited review, so the §7 commit plans were written
against inspected code rather than remembered code. **Head inspected:
`0f1e41d0` (P1 branch, NOT merged) — this is evidence at a pre-merge head and
is re-verified again at the true P2a base.**

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

### 10.2 ONE ambiguity the inspection DID surface — Q-P2a-3 (NEW, OPEN)

**`reconcile_metric_spec` lives inside a NODE, not a shared module.**
Measured: `nodes/result_interpretation_agent/evidence.py:58`. §4.1 and C1's
plan both say the legacy branch reconciles artifact-stamped specs "via the
existing `reconcile_metric_spec`" — but that would have
`workflows/model_exploration.py` import a function from the interpreter
node's internals.

Why this is not a detail to settle during implementation: the repository has
an executable rule that a node's private modules are never imported from
outside it (`tests/unit/nodes/test_node_public_boundary.py`, established by
07b's C7). Whether `evidence.py` is inside that boundary — and if it is,
whether the right move is to promote the reconciliation to a shared authority
or to have the workflow acquire its spec another way — is a **layer-ownership
decision**, which is exactly the class §7's rules say to stop on rather than
resolve silently.

**Q-P2a-3 (OPEN, for freeze):** where does the shared spec-reconciliation
authority live once a non-node consumer needs it? Options: (a) the workflow
reads only the composed/bound spec and never reconciles, leaving
reconciliation to the interpreter (smallest change; needs a check that sites
1–3 never compare artifacts from different runs); (b) promote
`reconcile_metric_spec` beside `MetricOrder` in `execute_tools/`, with the
node importing it from there (one authority, one move, touches a merged
node); (c) something else. **Do not implement C1 until this is dispositioned
— the §4.1 precedence text depends on the answer.**

## 11. Open operator questions

| id | question | proposal |
|---|---|---|
| **Q-P2a-1** | Site 10's refusal fallback shape | **OPEN / PROVISIONAL (operator ruling 2026-08-20: do NOT disposition until post-P1 reconciliation).** What is already frozen semantically: **absent metric identity means NO metric-based ranking happens at all.** If the proposer continues with a bounded candidate set, any cap must be **independent of score ordering** (e.g. declaration order / stable identity order) and must **never be described or labelled as "best"/"top N"** — a first-N cut must not wear a top-N name. The exact fallback (order-free cap vs refuse-to-propose) is dispositioned at freeze |
| **Q-P2a-2** | Should the refusal notice string be one shared constant (one authority for the Q-10-2 wording) or per-consumer text? | one shared constant beside `MetricOrder` |
| **Q-P2a-3** | Where does the shared spec-reconciliation authority live, now that a non-node consumer (the workflow, sites 1–3) needs it? `reconcile_metric_spec` is measured at `nodes/result_interpretation_agent/evidence.py:58`, and the repository forbids importing a node's private modules from outside it | **OPEN — raised by the rev-2 code inspection (§10.2), not by rev 1.** Blocks C1. Proposal offered but NOT selected: prefer (a) — the workflow reads only the bound/stamped spec and never reconciles — IF it can be shown that sites 1–3 never compare artifacts from different runs; otherwise (b), promote the function beside `MetricOrder` |

## 12. Adversarial self-review (draft-stage)

| attack | answer |
|---|---|
| Second direction authority? | none — every migration calls `MetricOrder`; the scanner + §8.1 item 6 census |
| Does P2a re-derive metric identity? | no — §4.1 consumes bound/stamped specs only |
| Does the scanner ban legitimate `max`? | precision fixtures for every §2.2 class are part of its own test suite |
| Can P2a merge with P2b absent? | yes — nothing here touches secondaries; master stays coherent (parent §21) |
| Did P2a touch the proposer's reader architecture? | no — one helper's comparison only; the reader is P3 |
