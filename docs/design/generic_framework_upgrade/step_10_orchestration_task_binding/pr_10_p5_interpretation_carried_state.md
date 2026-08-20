# Step 10 / P5 — Interpretation Carried-State Closure

## 0. Status

**DRAFT rev 1 — FOR OPERATOR REVIEW. NOT FROZEN. IMPLEMENTATION NOT
STARTED.** Lifecycle semantics are STABLE in this draft; the proposer
consumer wiring is **`PROVISIONAL(P3)`** and the draft **must reconcile
after P3 merges** before freeze.

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

## 7. Proposed commit decomposition (PROVISIONAL until post-P3 reconciliation)

* **C0** — lifecycle baseline: an executable census pinning the CURRENT
  broken state (no projection, no carrier field, `{}` at the consumer — the
  differential oracle already records it) + goldens of the producer's
  accumulation on a fixed outcome sequence.
* **C1** — projection + carriers: `project_vocab_link_confirmations` (+ its
  failure-policy tests), `RestoredState.vocab_link_confirmations`,
  the two ChainState fields, `from_restored` seeding. Inert until C2 (the
  one intermediate state, closed in the same PR).
* **C2** — the loop closures + consumer wiring: both iteration-end blocks
  (the `prediction_memory` pattern); the workflow passes confirmations into
  `InterpretationInput`; the findings consumer block reads the ChainState
  field. **The ≥ 3-iteration deterministic reachability test lands HERE**:
  three pseudo-mode iterations in one process; a link proposed in iter 1 and
  confirmed in three distinct runs promotes into `related_to` at iter 3;
  severing ANY link (projection, seed, closure, input pass) turns it RED —
  proven by mutation, one per link.
* **C3** — resume equality: run 3 iterations uninterrupted vs stop-after-
  commit/restore/continue; both carried values deep-equal between the two
  trajectories; legacy-digest fixtures (missing keys ⇒ `{}` / union of what
  exists); the single-writer census (planted second writer RED).
* **C4** — closure: censuses (no fifth loader — planted duplicate reader
  RED; no new carrier; `campaign_artifacts` untouched), docs/ledger, ONE
  exact-head CI.

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
