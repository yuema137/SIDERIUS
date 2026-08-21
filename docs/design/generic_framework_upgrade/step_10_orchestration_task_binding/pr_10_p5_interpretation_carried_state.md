# Step 10 / P5 — Interpretation Carried-State Closure

## 0. Status

**DRAFT rev 1 — ARCHITECTURE REVIEW PASSED (operator, 2026-08-20).
NOT FROZEN. IMPLEMENTATION NOT STARTED.** Lifecycle semantics are STABLE in
this draft; the proposer consumer wiring is **`PROVISIONAL(P3)`** and the
draft **must reconcile after P3 merges** before freeze.

**Operator architecture-review verdict (2026-08-20), recorded verbatim**:
lifecycle coherent; the P3 consumer wiring being explicitly provisional is
confirmed as the intended shape; **no second digest/state authority** — the
one-projection-over-the-existing-reader + existing-carrier-fields design
passed the review's duplicate-authority check. The verdict is a direction
confirmation, NOT a freeze: Q-P5-1 remains OPEN and the freeze happens after
the P3-merge reconciliation.

| field | value |
|---|---|
| parent | Step-10 parent REVISION 2 (frozen), §3.7 / §10 / §12 (Q-10-3 = A, Q-10-6 = A — both FROZEN); owns scope item **S5** |
| source anchor | merged `master` = **`d7d94740`** (production tree == P1 squash `bcb17e45`). All lifecycle sites re-verified at this anchor |
| depends on | **P1 merged** (the carry substrate: `RestoredState` as ONE launcher parameter, the ChainState loop) — satisfied. **P3** for the final proposer consumer boundary (draft in parallel; freeze/implement AFTER P3 — §31 policy) |
| downstream | **P6** (the closure runs with carried state live) |
| Gate disposition | proposed: **NO Gate** — the parent's own ruling: "temporal depth is a property of the *test*, not of the GPU" (§12.1). Deterministic ≥ 3-iteration lifecycle proof is the PRIMARY owner. Quoted against the gate standard at freeze |
| open operator questions | **1** (§13) |

---

## 1. Parent contract (recovered, binding)

* **§12 (reframed by rev 2)**: ONE semantic owner — interpretation-derived
  cross-iteration state — holding exactly TWO parent-assigned values:
  `vocab_link_confirmations` (ACTIVATE, Q-10-3 = A) and
  `accumulated_key_findings` (normalize into `ChainState`, Q-10-6 = A).
  P5 is NOT "persist all `InterpretationOutput`".
* **§12.1**: every link of
  `producer → committed digest → projection → ChainState →
  next-iteration InterpretationInput → the ≥ 3-run promotion condition`
  is required; §3.7 measured BOTH return-transport halves missing.
* **§12.3 constraints**: uses THE ONE Step-09.5a committed-digest read
  authority (no fifth loader); NO new run-state carrier; each projection
  states its merge rule and failure policy in the shape of the four existing
  ones; **acceptance proves reachability, not presence**.
* **§10 rule 4 (single writer)**: the `prediction_memory` loop closure —
  "read straight off the digest the interpreter just wrote, so the
  in-process loop and the chain-subprocess restore agree by construction" —
  is the named pattern to copy.
* **§4.2**: `campaign_artifacts` never becomes `ChainState`.

---

## 2. Current source audit (measured at `d7d94740`)

### 2.1 `vocab_link_confirmations` — the working half and the missing half

| link | state | site |
|---|---|---|
| schema | ✅ | `InterpretationInput.vocab_link_confirmations` (`agent/schemas/interpretation.py:677-682`, default `{}`); `InterpretationOutput…` (`:1155-1161`) |
| producer | ✅ | `update_vocab_link_confirmations` (`nodes/interpretation_helpers.py:587-…`), called at `result_interpretation_agent.py:851` with `existing_confirmations=inp.vocab_link_confirmations`; written into the normal digest (`:967`) AND the degraded digest (`:1074`, carries the input through unchanged) |
| committed persistence | ✅ | inside the interpretation digest — exactly what `core/committed_digests.py` reads |
| resume projection | ❌ | `core/resume.py`: **0** occurrences; no `RestoredState` field |
| in-process carry | ❌ | `ChainState` (11 fields — re-verified) has no field; `workflows/model_exploration.py`: **0** occurrences |
| consumer wiring | ❌ | the workflow's production `InterpretationInput(...)` does not pass the field → the interpreter always receives `{}` |

**Consequence (measured)**: `existing_confirmations` is always `{}`; one
iteration appends at most one `run_name`; the promotion guard requires
`len(run_names) >= min_runs` with `min_runs=3` — **`VocabEntry.related_to`
promotion is unreachable in production.**

**The aggregation rule is SOURCE-DETERMINED — no invention needed** (operator
§23's question answered from the producer, read in full):

* shape: `dict["feature:capability" → list[run_name]]`;
* update: on `prediction_outcome == "confirmed"` only, each proposed link
  appends `run_name` to its key **iff not already present** — a KEYED UNION
  with per-key run-name dedup, append order preserved; `partial`/`refuted`/
  `None` leave counts unchanged;
* accumulation happens **inside the producer**: the output mapping already
  contains the deep-copied carry-in plus this run's additions. Therefore the
  cross-iteration projection is **LATEST-WINS on the whole dict** — the
  newest committed digest's mapping IS the accumulated state. The projection
  must not re-merge (double-merging is idempotent here thanks to the dedup,
  but it would be a second accumulation authority — exactly what §10 rule 4
  forbids).

### 2.2 `accumulated_key_findings` — normalized transport, unchanged semantics

| link | state | site |
|---|---|---|
| producer | ✅ | the interpreter's digest `key_findings` (normal `:941`; degraded `:475`) |
| projection | ✅ | `project_knowledge` (`core/resume.py:777-…`) — **chronological UNION across every parseable digest, dedup by string, first-occurrence wins**; soft-fail warn-and-skip per digest |
| `RestoredState` | ✅ | field exists (default `[]`) |
| workflow | ⚠️ | P1 C5's unpack: a bare LOCAL from `restored_state.accumulated_key_findings` (`model_exploration.py:1865`), consumed ONCE at `:2186-2205` (an `ExpertContextItem`, `source_ref="prior_iters_key_findings"`, surfaced to the proposer) — **no ChainState field, no in-process accumulation** (the local is never updated in-loop) |

The Q-10-6 = A defect is lifecycle-ownership inconsistency: the only carried
value living as a bare local rather than on the carrier. The union MERGE
RULE is correct and stays unique (parent §10: "merge shape and lifecycle
ownership are different concerns").

### 2.3 The substrate P5 lands on (P1-merged truth)

`RestoredState` crosses the launcher edge as ONE parameter
(`restored_state=state`); the workflow unpacks once (`:1849-1871` region);
`ChainState.from_restored` seeds the carrier; the `prediction_memory` loop
closure at `:2710-2721` reads straight off the just-written interpretation
output. **P5 adds fields to existing carriers and one projection to the
existing authority — no new mechanism anywhere.**

An important census interaction, checked now rather than discovered later:
P1's ownership censuses derive deny-lists from `chain_state_field_names()`
(the composition and bindings guards) and pin the RETIRED `run_workflow`
kwargs (`accumulated_key_findings` among them). Adding a **ChainState
FIELD** named `accumulated_key_findings` extends the derived deny-lists
automatically (correct — a binding/composition must never carry it) and does
NOT collide with the retired-kwargs census (which checks the `run_workflow`
signature, not the carrier). Both censuses were re-read to confirm.

### 2.4 Lifecycle table (the §28 deliverable)

| value | producer | committed carrier | read authority | projection (merge rule / failure policy) | ChainState field | update rule (in-process) | restore | consumer | upstream-sensitive |
|---|---|---|---|---|---|---|---|---|---|
| `vocab_link_confirmations` | `update_vocab_link_confirmations` via the interpreter | interpretation digest (both branches) | `read_committed_digests` (THE one) | **NEW `project_vocab_link_confirmations`: latest-wins whole-dict** (accumulation lives in the producer, §2.1); failure policy §4.2 | NEW `current_vocab_link_confirmations: dict[str, list[str]]` | loop closure: read the just-written output's mapping (the `prediction_memory` pattern) | `RestoredState` gains the field, default `{}` (legacy digests without the key ⇒ `{}` — explicit backward-compatible default) | next iteration's `InterpretationInput.vocab_link_confirmations` (the workflow finally passes it) | consumer spelling stable; only the PROPOSER-visible surface (if any) is `PROVISIONAL(P3)` |
| `accumulated_key_findings` | interpreter digest `key_findings` | same digest | same | EXISTING `project_knowledge` — union/dedup/first-wins, warn-and-skip (UNCHANGED) | NEW `accumulated_key_findings: list[str]` | loop closure: append the just-written output's `key_findings` not already present (SAME union/first-wins rule, applied in-process) | existing `RestoredState` field (unchanged) | the existing `:2186-2205` ExpertContextItem block, reading the ChainState field | the block's future migration into P3's typed evidence is `PROVISIONAL(P3)`; P5 keeps the existing surface |

---

## 3. Goal / final effect

> Both parent-assigned interpretation-derived values ride the SAME lifecycle
> their nine ChainState siblings ride: produced by the interpreter, committed
> in the digest, projected by the one read authority, carried on
> `ChainState`, restored through `RestoredState`, and consumed next
> iteration — with `related_to` promotion reachable at the third confirming
> run, proven by a deterministic three-iteration test that FAILS when any
> link is severed.

**Non-goals**: any other `InterpretationOutput` field; reinterpreting
findings or confirmations (transport only); the promotion rule itself
(`min_runs=3` and the keyed-union semantics are the producer's, untouched);
a proposer reader (P3's); digest schema widening beyond the field the
producer already writes; `campaign_artifacts` anywhere near `ChainState`.

---

## 4. Design decisions (load-bearing)

### 4.1 Single writer, per value

* `current_vocab_link_confirmations`: written at exactly TWO places — the
  `from_restored` seed and the iteration-end loop closure reading the
  just-written output. The interpreter's own accumulation stays inside the
  producer; the workflow never merges.
* `accumulated_key_findings`: same two places; the in-process append applies
  the SAME rule the projection applies (first-occurrence wins), so an
  uninterrupted in-process trajectory and a per-iteration chain restore
  produce EQUAL state by construction — the §10-rule-4 property, and the
  resume-equality acceptance test's exact claim.

### 4.2 The new projection's failure policy (stated per §12.3)

`project_vocab_link_confirmations`: latest-wins whole-dict; malformed value
⇒ **raise** — the `prediction_memory` precedent's rationale transfers
directly: promotion state assembled from a stale mapping silently DELAYS or
mislabels scientific graduation, and "an accuracy statistic assembled from
half a pool is worse than none" is the same argument one level up. (The
alternative — warn-and-keep-older, `knowledge_cache`'s policy — is
conservative but silently changes WHEN a relationship graduates.) This is a
design decision with a named precedent, not an operator question; flagged
here so the freeze review can overturn it cheaply.

Shape validation: `dict[str, list[str]]` with string members; a digest
missing the key projects `{}` (legacy digests predate the activation — an
explicit compatible default, never fabricated history).

### 4.3 One deliberate behaviour delta, declared

Chain-mode production (`max_iterations=1` per subprocess) is
behaviour-IDENTICAL for `accumulated_key_findings` (the value still arrives
via restore) and behaviour-NEW only in that confirmations now actually
arrive. **In-process multi-iteration runs** change deliberately: iteration
N+1's proposer context now sees iteration N's findings (today it sees none,
because the bare local is never updated). That is Q-10-6 = A's point —
in-process and chain trajectories stop disagreeing — and it is declared as
the delta rather than smuggled.

### 4.4 What P5 does NOT wire (the P3 boundary, mirrored from P3 §9)

P5 delivers state to (a) the next iteration's `InterpretationInput` and (b)
the EXISTING workflow-level ExpertContextItem block. Whether/how these
values additionally surface inside P3's typed proposer evidence is P3's
extension point; P5 marks that wiring `PROVISIONAL(P3)` and will consume the
typed boundary rather than adding a reader. P5 never bypasses P3 once P3
exists — and P5 freezes AFTER P3 merges precisely so this is checked against
real code, not intentions.

---

## 5. Three-task control

The lifecycle is task-free: digests, projections and carriers never inspect
task identity. TIDMAD exercises it in production; Pets/DAVIS traverse the
identical path when P6 runs them (their interpreters produce the same
schema); a fourth task inherits it with zero edits (P1's census already
guards the surface). Absence states: a task whose predictions are never
`confirmed` accumulates nothing — the empty mapping is first-class.

## 6. Structure preflight

| file | now | P5 change | owners after |
|---|---|---|---|
| `core/resume.py` | 4 projections + restore | +1 pure projection + 1 `RestoredState` field | unchanged set |
| `core/chain_state.py` | 11 fields | +2 fields (guards auto-extend) | unchanged |
| `workflows/model_exploration.py` | post-P1 | +pass the field into `InterpretationInput`; +2 loop-closure blocks beside `prediction_memory`'s; NO new phase | unchanged set |
| `agent/schemas/interpretation.py` | — | none (both fields already exist) | — |
| `nodes/interpretation_helpers.py` | — | none (producer untouched) | — |

## 7. Commit decomposition — FIVE commits, full plans

**Status of this section**: the commit BOUNDARIES are stable; every checklist
below starts `[ ]` and is checked only against recorded evidence. The plans are
written against source inspected at the anchor below, not from memory —
`core/resume.py`, `core/chain_state.py`, `nodes/interpretation_helpers.py`,
`nodes/result_interpretation_agent/result_interpretation_agent.py`,
`agent/schemas/interpretation.py` and `workflows/model_exploration.py` were all
read while writing them. Line anchors are evidence of what was inspected, never
implementation authority.

**Measured source facts these plans rest on** (re-verify at implementation
start; a moved line is not a material deviation, a moved BEHAVIOUR is):

| fact | where |
|---|---|
| the producer already works | `nodes/interpretation_helpers.py:587` `update_vocab_link_confirmations(prev_vocab_links, prediction_outcome, run_name, existing_confirmations, runtime_vocab, min_runs=3) -> (updated_confirmations, updated_vocab, newly_promoted_pairs)`; only `confirmed` counts; promotion at ≥ 3 DISTINCT runs |
| it is already called | `result_interpretation_agent.py:902`, reading `inp.vocab_link_confirmations` at `:908` |
| the value is already persisted | written to the output at `:1018` and to the digest at `:1125` |
| both schema fields already exist | `InterpretationInput.vocab_link_confirmations` `interpretation.py:677`; `InterpretationOutput.vocab_link_confirmations` `:1155` |
| **the missing half** | `RestoredState` (`core/resume.py:119`, fields `:203-215`) carries `accumulated_key_findings` but has **no** `vocab_link_confirmations` field, and no projection produces one |
| the four existing projections | `project_knowledge` `:886` (chronological union, dedup, SOFT-fail), `project_fingerprint_history` `:951`, `project_prediction_memory` `:1004` (latest-wins, RAISES on a corrupted record), `project_knowledge_cache` `:1052` |
| the restore wiring precedent | `restore_prior_state` `:1207`; `state.runtime_vocab, state.accumulated_key_findings = project_knowledge(digest_reads)` at `:1480` |
| the carry precedent, end to end | `ChainState.current_prediction_memory` (`chain_state.py:100`), `from_restored(..., restored_prediction_memory=...)` (`:131-139`), workflow read at `model_exploration.py:1959/1975`, loop-closure write at `:2795` |
| the findings consumer block | `model_exploration.py:2278-2292` — builds the `prior_iters` `ExpertContextItem` |

**Per-commit rules.** Semantic commits are autonomous inside the frozen design.
Before each: inspect the diff scope, run the cheapest authoritative validation,
update this ledger, commit. No full local suite before the final head; ONE
exact-head CI at the end. **Every commit must run the guards it is KNOWN to
move** — P3's C3 skipped `tests/unit/workflows/` and left the Step-09.5a oracle
red for three commits, which is precisely the failure this rule prevents.

---

### C0 — lifecycle baseline: pin the CURRENT broken state

**1. Goal.**
Make the defect executable before fixing it. Today `vocab_link_confirmations`
is produced, returned and persisted — and then dropped: nothing projects it,
nothing carries it, and the next iteration's `InterpretationInput` receives
`{}`. So a link confirmed in three distinct runs can never reach the promotion
threshold across a restart, and in a resumed chain it cannot reach it at all.
This commit records that behaviour as a baseline so C1-C3 are diffs against
evidence rather than against belief.

It belongs here and nowhere else: once C1 adds the carrier the broken state is
unreproducible, and a baseline captured after the fix proves nothing.

**2. Scope.**
Tests and goldens only. **Zero production edits** — the commit is a scope error
if `git diff --stat` shows anything outside `tests/` and `docs/`.
Depends on: nothing.

**3. Implementation plan.**
- [ ] Producer accumulation golden: drive `update_vocab_link_confirmations`
      over a FIXED outcome sequence (confirmed / partial / refuted / confirmed
      from distinct `run_name`s) and pin the returned
      `(confirmations, vocab, newly_promoted)` at each step, including that
      `partial` and `refuted` change nothing and that the same `run_name`
      cannot confirm twice.
- [ ] Promotion-threshold golden: pin that promotion happens at exactly
      `min_runs` DISTINCT runs — not 2, not the same run 3 times.
- [ ] **The broken-lifecycle census**, executable and named: assert that
      `RestoredState` has NO `vocab_link_confirmations` field, that no
      `project_*` function produces one, and that a restored chain therefore
      hands the interpreter `{}`. This test is INVERTED in C1/C2, not deleted.
- [ ] Multi-iteration baseline: three pseudo-mode iterations in one process
      with a link proposed in iter 1 and confirmed in three distinct runs;
      record that it does NOT promote today. This is the exact scenario C2
      turns green, so capture it now with its current (wrong) result.
- [ ] Record the guard-disposition table in the ledger: every existing test
      this PR will turn red, and the commit that flips each.

**4. Validation plan.**
* Unit: the goldens above; deterministic, no I/O beyond `tmp_path`.
* Negative/invalid: malformed digest payloads (missing key, non-dict,
  unreadable) recorded as they behave TODAY, so C1's projection has a
  before-picture to preserve or deliberately change.
* Backward-compat/parity: none needed — nothing changes.
* Gate tests: **NONE.** Gate 1 and Gate 2 are NOT REQUIRED for P5 (§8) and must
  not be launched.

**5. Acceptance criteria.**
- [ ] `git diff --stat` on the commit shows only `tests/` and `docs/`.
- [ ] The broken-lifecycle census PASSES on the unmodified tree, i.e. it
      genuinely asserts the current absence rather than the desired presence.
- [ ] The 3-iteration baseline records `related_to` WITHOUT the confirmed
      capability, and the test states that this is the defect, not the target.
- [ ] Goldens are byte-stable across two independent runs.

**6. Failure and edge cases.**
* A golden that embeds a `tmp_path`, a timestamp or a set-iteration order is a
  broken baseline — capture deterministically or not at all.
* `min_runs` is a DEFAULT (3): the goldens must pass it explicitly where the
  claim is about the threshold, so a future default change is visible.

**7. Verification commands and evidence.**
```text
pytest tests/unit/core tests/unit/agent/result_interpretation_agent \
       tests/unit/workflows -q
```
- [ ] counts + wall time recorded in the ledger
- [ ] any test that could not run recorded WITH the reason (never "passed")

**8. Commit boundary.**
Independently reviewable as "here is the defect, executable". Contains no
production change and no cleanup.

---

### C1 — the projection and the carriers (inert)

**1. Goal.**
Give the value a way home: one projection over the already-read digests, one
`RestoredState` field, and the ChainState carrier — with nothing yet consuming
them. Separated from C2 so the reviewer can check the projection's failure
policy against its four siblings without the loop wiring in the same diff.

**2. Scope.**
* `core/resume.py` — `project_vocab_link_confirmations`, the new
  `RestoredState` field, the assignment in `restore_prior_state` beside the
  `project_knowledge` line (`:1480`).
* `core/chain_state.py` — the carrier field and its `from_restored` parameter,
  following `current_prediction_memory` exactly (`:100`, `:131-139`).
* **Non-goals**: no workflow change, no `InterpretationInput` change, no
  consumer. The producer is untouched.
* Depends on C0.

**3. Implementation plan.**
- [ ] Implement `project_vocab_link_confirmations(reads) -> dict[str, list[str]]`
      with the rule the design ALREADY decided — **latest-wins whole-dict**
      (§2.4, §4.2). It is not re-opened here: accumulation lives in the
      PRODUCER (§2.1), so each digest already carries the full cumulative
      mapping and a union across digests would double-count nothing but would
      resurrect pairs a later iteration legitimately dropped. Implement it and
      make the choice OBSERVABLE in a test over disagreeing digests; if
      implementation surfaces evidence against it, that is a §4.2 freeze-review
      item, not a silent change.
- [ ] Failure policy exactly as §4.2 states: malformed value ⇒ **raise**
      (the `project_prediction_memory` precedent — promotion state assembled
      from a stale mapping silently delays or mislabels graduation); a digest
      MISSING the key ⇒ `{}` (legacy digests predate activation — a compatible
      default, never fabricated history); shape `dict[str, list[str]]` with
      string members.
- [ ] Add `RestoredState.vocab_link_confirmations` (additive, defaulted).
- [ ] Wire it in `restore_prior_state` beside `:1480`.
- [ ] Add the ChainState field + `from_restored` seeding.
- [ ] INVERT C0's broken-lifecycle census: the field and the projection must
      now EXIST. Do not delete the test.

**4. Validation plan.**
* Unit: projection over (a) no digests, (b) one digest, (c) several digests
  that agree, (d) several that DISAGREE — (d) is what makes latest-wins
  observable rather than incidental, and it must assert the LATER digest's
  mapping wins outright, including a pair the later digest no longer carries.
* Negative/invalid: missing key ⇒ `{}` (no warning); malformed value ⇒ RAISES
  per §4.2, asserted by type and message rather than by "it failed";
  unreadable digest ⇒ the same warning shape the siblings emit.
* Backward-compat: a legacy digest with no `vocab_link_confirmations` key
  restores `{}` and warns nothing.
* Integration/pseudo: none required yet — nothing consumes it.
* Gate: **NONE.**

**5. Acceptance criteria.**
- [ ] `RestoredState` and `ChainState` each carry the value; `from_restored`
      seeds it.
- [ ] The projection is the ONLY producer of a restored confirmations mapping
      (census: no second reader of that digest key outside the interpreter).
- [ ] Behaviour is UNCHANGED end to end: the 3-iteration baseline from C0 still
      records no promotion, because nothing consumes the carrier yet. This is
      the declared inert state.
- [ ] `pyright` clean over the touched modules (recorded as CI-owned if it
      cannot run locally — never claimed).

**6. Failure and edge cases.**
* Digests disagreeing on the same pair — latest-wins, and the test must show
  the earlier value is DISCARDED rather than merged.
* A confirmation list containing duplicates of one `run_name` — the PRODUCER
  dedups by run (`update_vocab_link_confirmations` treats a run as confirming
  once); the projection must not re-dedup, or the two would be two authorities
  on the promotion count. Assert the projection passes the list through.
* Non-string keys / non-list values in a hand-edited digest ⇒ raise, per §4.2.
* A digest whose mapping is EMPTY (`{}`) is a legitimate state, not a missing
  key: it must not be confused with absence, or a chain that legitimately
  cleared its confirmations would silently resurrect them.

**7. Verification commands and evidence.**
```text
pytest tests/unit/core -q
pytest tests/unit/core/test_resume.py tests/unit/workflows -q
```
- [ ] counts + wall time recorded
- [ ] the Step-09.5a workflow oracle run explicitly — `RestoredState` and
      `ChainState` are inside its envelope, so this commit is KNOWN to be able
      to move it; if it moves, DECLARE the delta in its docstring

**8. Commit boundary.**
Carrier layer only. No consumer, no loop change, no prompt byte moves.

---

### C2 — close the loop and wire the consumer

**1. Goal.**
Make the value actually travel: iteration-end write into ChainState, and the
workflow passing it into the next `InterpretationInput`. This is the commit
where the defect stops.

**2. Scope.**
* `workflows/model_exploration.py` — the iteration-end closure (pattern:
  `:2795`), the restored seed (pattern: `:1959/1975`), and passing the value
  into `InterpretationInput`.
* **Non-goals**: the producer's semantics, the promotion rule, `min_runs`, the
  findings half, prompts.
* Depends on C1.

**3. Implementation plan.**
- [ ] Iteration-end: write the interpreter's returned confirmations into
      ChainState, mirroring the `prediction_memory` closure exactly.
- [ ] Startup: seed ChainState from `RestoredState` on resume.
- [ ] Pass ChainState's value into `InterpretationInput.vocab_link_confirmations`
      (the field already exists — `interpretation.py:677`).
- [ ] **The ≥ 3-iteration reachability test lands HERE**: three pseudo-mode
      iterations in ONE process; a link proposed in iter 1 and confirmed by
      three DISTINCT runs promotes into `related_to` at iter 3.
- [ ] **Mutation proof, one per link**: sever the projection, the seed, the
      closure, and the input pass INDEPENDENTLY; each severing must turn the
      reachability test RED. A carry with four links needs four proofs — a
      single end-to-end green cannot tell which hop is load-bearing.
- [ ] Flip C0's 3-iteration baseline from "records the defect" to "records the
      fix", citing the commit.

**4. Validation plan.**
* Unit: the closure writes what the interpreter returned, unmodified.
* Integration/pseudo: the 3-iteration in-process reachability test.
* Negative: a chain where NO prediction is `confirmed` accumulates nothing and
  promotes nothing (the empty mapping is first-class, not an error).
* Backward-compat/parity: a single-iteration chain behaves exactly as before;
  the §4.3 declared behaviour delta is the ONLY intended difference and must be
  stated in the ledger with its before/after.
* Gate: **NONE.**

**5. Acceptance criteria.**
- [ ] The 3-iteration test promotes the capability into `related_to` at
      iteration 3 and NOT at iteration 2 — the threshold is observable, not
      just the endpoint.
- [ ] Each of the four severing mutations turns it RED, recorded individually.
- [ ] Prompts are unchanged except where the findings block already renders,
      and that difference is the declared §4.3 delta.
- [ ] No new digest key: the digest already carries the value, so the digest
      bytes must not move.

**6. Failure and edge cases.**
* Resume mid-chain — covered by C3, but C2 must not make it worse.
* An iteration that produces no interpretation (a skipped or failed round):
  the closure must not clobber accumulated state with `{}`.
* Same `run_name` appearing in two iterations — dedup semantics must match the
  producer's, or promotion counts drift.

**7. Verification commands and evidence.**
```text
pytest tests/unit/workflows tests/unit/core \
       tests/unit/agent/result_interpretation_agent -q
pytest tests/integration/workflows/test_vocab_accumulation.py -q   # if applicable
```
- [ ] counts + wall time recorded
- [ ] the Step-09.5a oracle run explicitly; any envelope delta DECLARED

**8. Commit boundary.**
Loop + consumer only. No projection changes, no producer changes.

---

### C3 — resume equality

**1. Goal.**
Prove the carried value survives a restart, which is the whole point: the
defect's worst form is that a resumed chain can never promote at all.

**2. Scope.**
Tests plus whatever narrow fix they expose. Depends on C2.

**3. Implementation plan.**
- [ ] Uninterrupted-vs-resumed equality: run 3 iterations straight through, and
      run 3 with a stop-after-commit / restore / continue in the middle; assert
      both carried values deep-equal at the end.
- [ ] Legacy-digest fixtures: digests written before this feature restore `{}`
      (or the union of what exists — whichever C1 chose) and never crash.
- [ ] Single-writer census: exactly one site writes the ChainState carrier;
      plant a second writer and prove RED.

**4. Validation plan.**
* Integration/pseudo: the two trajectories above.
* Negative: restore from a digest set with a corrupted middle entry — assert
  the C1 failure policy end to end, not just at the projection.
* Backward-compat: resuming a chain committed BEFORE this feature must not
  raise and must not fabricate confirmations.
* Gate: **NONE.**

**5. Acceptance criteria.**
- [ ] The two trajectories are deep-equal on both carried values.
- [ ] The planted second writer turns the census RED; reverted, it is green and
      the tree is clean.
- [ ] A pre-feature digest set restores without warning noise beyond the
      declared policy.

**6. Failure and edge cases.**
* Partial commit (digest written, iteration not finished).
* Digest ordering: ascending is assumed by the siblings — assert it rather
  than inherit it.

**7. Verification commands and evidence.**
```text
pytest tests/unit/core tests/unit/workflows -q
```
- [ ] counts + wall time recorded

**8. Commit boundary.**
Resume evidence only.

---

### C4 — closure

**1. Goal.**
The standing guards hold at the final head, the operator surface is current,
and the PR is reviewable.

**2. Scope.**
Censuses, docs (`core/resume.py` docstrings, any node `.md` the carry touches),
the ledger, the PR, ONE exact-head CI. Depends on C0-C3.

**3. Implementation plan.**
- [ ] Census: no FIFTH digest loader — plant a duplicate reader, prove RED.
- [ ] Census: no new carrier field beyond the declared one;
      `campaign_artifacts` untouched.
- [ ] Docs synced, with every documented claim QUOTED against merged source
      rather than asserted.
- [ ] Ledger closed: all checklists `[x]` with evidence, deviations recorded,
      carried debt named.

**4. Validation plan.**
* All prior commits' targeted suites green at head, recorded per commit rather
  than re-run wholesale.
* ONE exact-head CI: lint · ruff-format · pyright · unit, all PASS, with the
  run id and the tested SHA recorded and the verdict read FROM THE LOG.
* Gate: **NONE** — and the ledger must say so explicitly rather than leaving it
  unmentioned.

**5. Acceptance criteria.**
- [ ] `CI tested SHA == final PR HEAD`.
- [ ] Working tree clean.
- [ ] Every checklist item above is `[x]` with evidence, or explicitly recorded
      as not done and why.

**6. Failure and edge cases.**
* A CI failure is diagnosed and fixed, not re-run hopefully.
* A docs-only commit AFTER the canonical CI would move the head — fold docs in
  BEFORE the final push.

**7. Verification commands and evidence.**
- [ ] CI run id, tested SHA, and each step's result recorded in the ledger.

**8. Commit boundary.**
Closure only. STOP at **READY FOR OPERATOR REVIEW — DO NOT MERGE**.

## 8. Validation strategy / Gate disposition

Deterministic owners: producer-accumulation unit goldens; projection unit
tests incl. malformed-raise and missing-key `{}`; the three-iteration
reachability test with per-link severing mutations; uninterrupted-vs-resumed
equality; the census set. **Gate 1 NOT REQUIRED; Gate 2 NOT REQUIRED** —
the parent's §12.1 table assigns the claim to deterministic temporal-depth
evidence, and every property here is projection/carry/restore determinism.
A real Gate would be the LESS faithful owner.

## 9. Preservation invariants

The producer's semantics byte-identical (promotion rule, dedup, ordering);
`project_knowledge`'s findings-half rule unchanged; the four existing
projections untouched; digest bytes unchanged (both fields were ALREADY
written — activation adds no digest key); prompts unchanged except where
the findings block already renders (its content timing changes only in the
declared §4.3 in-process case); `RestoredState` additive; launcher signature
untouched (P1's single parameter absorbs the new field silently).

## 10. Failure / edge cases

| case | behaviour |
|---|---|
| legacy digest without `vocab_link_confirmations` | projects `{}`; never fabricated |
| malformed confirmations value in a digest | projection raises (§4.2) — restore's existing soft-fail wrapper decides run-level handling exactly as for `prediction_memory` |
| degraded interpretation iteration | the degraded digest carries the INPUT mapping through unchanged (`:1074`) — no loss, no double count |
| duplicate confirmation from the same run_name | producer dedups (existing); latest-wins projection cannot double-count |
| feature absent from runtime vocab at promotion time | producer already skips (`vocab_by_name.get` miss) — unchanged |

## 11. Risk register

| risk | mitigation |
|---|---|
| a second accumulation authority (workflow merging digests) | latest-wins projection + the single-writer census; the producer is the ONLY merger |
| the reachability test passes by fixture accident | per-link severing mutations — each hop's deletion must independently fail it |
| in-process delta surprises a consumer | §4.3 declares it; the equality test pins the new agreed behaviour |
| P3 lands a competing consumer path | freeze ordering (P5 after P3) + P3's §9 mirror statement |

## 12. Dependency / parallelism (the §31 map, P5's row)

Draft now; **freeze and implement AFTER P3 merges** (main lane
P1→P2a→P2b→P3→P5→P6). Technically parallel with P4 (no shared owner —
re-verified: P4 touches health schemas/evaluation; P5 touches
resume/chain-state/workflow closures); the default remains sequential with
P3 per the operator's §31.

## 13. Open operator questions

| id | question | proposal |
|---|---|---|
| **Q-P5-1** | The new projection's malformed-value policy: raise (proposed, the `prediction_memory` precedent — §4.2) or warn-and-keep-older (the `knowledge_cache` precedent)? | raise — silently delaying/mislabeling scientific graduation is the exact failure the sibling's rationale names. Dispositioned at freeze |

## 14. Post-P3 reconciliation obligations (before freeze)

1. Re-audit the consumer surfaces at post-P3 master (the findings
   ExpertContextItem block may have moved into the typed-evidence rendering;
   P5 then consumes the typed boundary, not the block).
2. Confirm P3 added no carrier field or digest reader (its §9 promise).
3. Re-verify §2's line anchors; quote the gate standard; disposition Q-P5-1.

### 14.1 What P3 actually landed (MERGED 2026-08-21, squash `254cbaa1`)

Recorded so the reconciliation starts from merged truth rather than from the
draft's expectations. **All three obligations above still stand and are NOT
discharged by this note** — they must be re-run against master in a fresh
session, reading source, before P5 freezes.

* **P3 kept its §9 promise.** It added ZERO `ChainState` fields, ZERO digest
  readers, ZERO restore paths, and no `accumulated_key_findings` or
  `vocab_link_confirmations` lifecycle. Obligation 2 is expected to confirm
  cleanly, but it must still be CHECKED, not assumed.
* **The consumer boundary P5 will use now exists.**
  `ProposalInput.interpretation_evidence: ProposerInterpretationEvidence`
  (REQUIRED) is built by the ONE projection
  `agent/schemas/proposer_evidence.py::build_proposer_evidence(Mapping)`. The
  raw `interpretation` dict is REMOVED, so P5 could not add a raw reader even
  if it wanted to — §4.4's "P5 never bypasses P3" is now structural.
* **`vocab_link_confirmations` is explicitly REFUSED by that boundary**, by
  name and with a reason: `NOT_CARRIED["vocab_link_confirmations"] = "P5's
  cross-iteration lifecycle, not P3's"`. A partition test asserts carried ∪
  refused covers all 42 upstream fields, so **if P5 decides the proposer should
  see confirmations, adding the field is a deliberate, test-visible act** — it
  cannot arrive incidentally. That is the extension surface §4.4 anticipated,
  and it is now a real one.
* **The findings ExpertContextItem block did NOT move.** It is still assembled
  in `workflows/model_exploration.py` from the workflow's own
  `accumulated_key_findings`, and `expert_context` is a separate
  `ProposalInput` channel that P3 deliberately left alone. Obligation 1's
  "may have moved" resolves to *did not* — but re-verify the line anchors,
  because P3 moved a great deal of nearby code.
* **A P3 lesson that applies directly to P5's C1.** P3's C3 removed two
  `ProposalInput` fields and left the Step-09.5a workflow oracle RED for three
  commits, because its targeted validation did not include
  `tests/unit/workflows/`. P5's C1 adds a `RestoredState` field and a
  `ChainState` field — both INSIDE that oracle's envelope — so C1 must run it
  explicitly and DECLARE any delta, exactly as §7's C1 verification section
  now requires.

## 15. Adversarial self-review (draft-stage)

| attack | answer |
|---|---|
| Duplicate digest loader? | one NEW pure projection over the EXISTING `read_committed_digests`; census + planted duplicate RED |
| Duplicate state carrier? | two fields on ChainState/RestoredState; no new object; P1's carrier censuses auto-extend |
| Unclear single writer? | §4.1: seed + loop closure, per value; planted second writer RED |
| `campaign_artifacts` promoted? | untouched; census asserts no ChainState field references it |
| Aggregation rule invented? | §2.1 derives it from the producer, read in full; the projection deliberately does NOT re-merge |
| Resume divergence? | C3's uninterrupted-vs-resumed deep-equality is the acceptance |
| Legacy evidence fabricated? | missing keys ⇒ explicit empty defaults; degraded digests carry through |
| P3 consumer bypassed? | §4.4 + freeze ordering + P3's mirrored §9 |
