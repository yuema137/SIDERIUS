# PR-12e — Out-of-tree graduation + final systems validation

## A. Status, authority, source anchors

**DRAFT — READY FOR POST-PR-12d LANDED-SOURCE RECONCILIATION.
NOT YET FROZEN. DO NOT IMPLEMENT.**

> **PR-12d is NOT merged.** `origin/master` is `cfaa5572`; 12d is implementing
> on its own branch (D0 · DP · D1 · D2 · D3 landed at the time of writing).
> Per the parent's own rule — reinforced by what 12bc taught — **a downstream
> design must not freeze against a source topology it is about to stop
> inheriting.** This draft is therefore written against 12d's **FROZEN
> downstream contract**, every source-dependent assumption is tagged
> `PROVISIONAL_12D`, and §T is the mandatory delta reconciliation that must
> discharge before freeze review.
>
> **This session's isolation:** planning happens in the dedicated worktree
> `/home/yuema137/siderius-step12e-planning` on branch
> `step12-pr12e-out-of-tree-graduation`, based on landed master. The 12d
> implementation checkout was **never written** — 12d's frozen design and the
> amended parent were read read-only via `git show`.

| field | value |
|---|---|
| parent authority | `../step_12_external_extensibility_graduation.md` — §1 (graduation statement, G5/G6), §12-PR-12e, §14a.3 (`G-12e`), §16 (fourth-task **selection criteria**, frozen), §17 (adversarial matrix), §18 (zero-core-edit acceptance, executable), **§18a (final validation matrix — the terminal economy contract)**, §19 (debt triage), §11.1 (inter-PR checkpoint) |
| upstream child | `pr_12d_contrast_subprocess_closure.md` §P — the downstream contract 12e inherits; and `pr_12bc_generic_task_boundary_closure.md` §P — where 12e's identity/provenance obligations originate |
| worktree base | landed master **`cfaa5572`** |
| parent revision read | the version on `step12-pr12d-contrast-subprocess-closure` (carries 12d's scope amendment, the pre-freeze audit findings and the withdrawn-T6 record). **It is not yet on master**; §T re-reads it after 12d merges |
| PR-doc standard | the operator's 8-section per-block checklist; every box `[ ]`; `[x]` only with recorded evidence |
| open operator questions | **0.** **Q-12e-1 RULED = Candidate 1** (variable-length event-sequence scoring, §D) and **Q-12e-2 RULED = (a)** (leave the dashboard's legacy `agent/`-layout half alone, labelled legacy; §V.13b) — both operator, 2026-08-23 |
| real-validation cost envelope (operator-confirmed, 2026-08-23) | reconciliation+freeze ~20–45m · implementation critical path **~1.5–3h** · `G-12e` healthy 2×1 **~20–50m** (agent-chain LLM/provider latency dominates, not the seconds-scale training) · E-AUDIT+closeout ~25–50m · CI ~15–30m+ · **typical reconciliation → READY FOR REVIEW ≈ 2.5–4h; up to ~5h is still normal** (a `Q-07c-6` retry, provider latency, CI queue). **Diagnose — don't just wait — only past ~5h with no genuine cause** (source surprise, defect, provider outage, authorized second `G-12e` launch, CI queue): check for unexpected serialization, dashboard scope creep, checkpoint/audit replay, duplicate cross-workstream implementation, or an agent idling on the operator with no §N STOP fired |

**Freeze standard applied here.** This document freezes semantic ownership,
the task-package contract, the zero-core-edit definition, invariants,
scope/non-goals, negative falsifiers, validation owners, failure classes,
Gate topology, evidence-invalidation rules, the parallelization envelope,
STOP conditions and terminal discipline. It deliberately leaves to
implementation: exact helper and class names, local module splits, test
filenames, commit count, subprocess-helper reuse mechanics, worktree names,
and the scheduling of sub-agents inside the frozen envelope. **Mechanics may
be discovered; acceptance may not.**

---

## B. The exact graduation claim

Taken verbatim from parent §1 and the roadmap's §22.24.3 form — **not
paraphrased, because the wording is the acceptance**:

> **A materially new scientific task package OUTSIDE the SIDERIUS source tree
> can declare all task-owned semantics through the supported public
> mechanisms and run the normal composed workflow — parent process AND every
> required child process — with ZERO SIDERIUS production-source edits.**
>
> *"SIDERIUS supports a task-package protocol; TIDMAD, Pets and DAVIS are
> three packages using it."*

12e owns **G5** outright and the **third leg of G6** (external-package restore
across a real restart, relocation equality, edited-plugin refusal). G1–G4 and
G6's first two legs are discharged by 12a / 12bc / 12d and are **cited, never
re-proven** (§H).

### B.1 What "success" looks like, and what it must not become

**PR-12e is a GRADUATION PROOF, not the next genericization campaign.** Its
implementation surface should be dominated by things that are *not* SIDERIUS
production source: an external package, censuses, negative controls, evidence,
docs.

**If the source audit finds that graduation still needs a broad
train/infer/score genericization campaign, that is a MATERIAL finding, not
12e's scope** (§N). It means either 12d did not close the generic runtime
boundary it was scoped to close, or the parent contract underestimated a
genuinely new capability. Parent §12-PR-12e point 3 already froze the
consequence:

```text
12e BLOCKS -> a bounded corrective PR against the owning (merged) subsystem
           -> re-validate ONLY the invalidated downstream evidence
           -> return to 12e
```

**12e never patches the gap itself, and there is no "follow-up commit" into a
merged PR's history.**

---

## C. Source audit — what exists, what 12e inherits, what it must not assume

### C.1 Inherited and DISCHARGED (cite; do not re-prove)

| from | discharged capability | 12e's use |
|---|---|---|
| **12a** | composed path resolves zero implicit TIDMAD semantics; composed lock/fingerprint/resume chain (its `G-12a-2` witness); #234 fail-closed plugin contract; D16 removed so a `loss`-token metric id is declarable | the fourth task may declare `…_loss` as its PRIMARY id (§16 criterion) without a framework change |
| **12bc / B** | `TaskScopeCapability` as an optional sibling; scope artifact + sha256 verified **before** deserialization; `DatasetProfile` = generic identity + opaque topology | the package supplies its own scope shape; §16 requires a vocabulary that is **not** `rows` of (id, label) |
| **12bc / C** | a child resolves a task the framework has never heard of, by composing the transported manifest through the SAME authority the parent used; parent-pinned content identity **captured at registration**, verified child-side, refused on divergence | the whole out-of-tree loading premise, and G6's identity leg |
| **12d** (`PROVISIONAL_12D`) | the composed runtime is generic **below the composition edge**: run-scoped plugin availability/propagation/provenance (seam P) · configured task instances (seam A) · attempt-scope authority (seam B) · child transport + generic inference iteration (seam C) · generic scoring handoff, task-owned metrics and objective (seam D) · deliverable identity **narrowed** (seam E) | **everything that makes a fourth task executable at all** |

### C.2 Two facts 12e must NOT re-derive (12d §P, verbatim)

* **Identity pinning covers the `task_data_path` family only.** The metric and
  deliverable-naming families are re-composed child-side with **no parent
  pin** — deliberate, pinned by `test_step12_pr12bc_c2_identity.py:477`.
  12e's identity negative controls must target the family that *has* a pin;
  asserting a pin on the families that deliberately lack one would fail for
  the wrong reason.
* **`run_registration_scope` has zero production callers.** CASE A's
  production protection rests entirely on the two-phase content-equality rule,
  because production runs one `run_one_iteration.py` process per iteration.
  **Any in-process multi-run scenario 12e designs (§17 row G) must treat this
  as an open edge**, not assume the overlay protects it.

### C.3 What 12e must not assume

- [ ] **Do not assume 12d closed everything it scoped.** §T's delta
      reconciliation is what converts `PROVISIONAL_12D` into `CONFIRMED`.
- [ ] **Do not treat 12bc's anonymous fourth-shaped fixture
      (`spectro_segmentation_v0`) as a graduation vehicle.** Parent §16 is
      explicit: it is a composition fixture, *and its name is already burned
      into the census* — reusing it would make the zero-core-edit census
      vacuous.
- [ ] **Do not assume the three prior tasks need re-running.** Parent §18a
      already froze the opposite (§H).

### C.4 Non-goals

* **No reimplementation of 12d's generic train/infer/score closure.**
* **No fourth-task-specific core branch**, no central task registry/catalog,
  no generic schema growth merely to name the fourth task.
* **No production import from the external package**, and no hidden copying of
  package files into repository core.
* **No re-running three prior full real Gates by default** (§H).
* **No benchmark or scientific-quality claim** about the fourth task.
* **No broad repository cleanup**, no second execution architecture, no
  duplicate plugin-resolution or scorer path.
* **No new prompt family** — the package supplies its own blocks through the
  existing declared surface.
* **No extra Gate because a checklist has another row.**

---

## D. Fourth-task selection — Q-12e-1, the ONE operator decision

**Parent §16 froze the CRITERIA and deliberately did not select.** Ten
criteria, each tied to the assumption it falsifies. This design's job is to
present the **minimum operator choice**, not to invent a task.

The governing principle from §16: **maximize PROTOCOL CONTRAST, not scientific
difficulty.** Two criteria bound the cost hard — *"synthetic, deterministically
generatable by a script INSIDE the package"* and *"CPU-trainable in minutes"*
— so the fourth task must be **cheap by construction**. It exists to falsify
protocol assumptions, not to be a research contribution.

### D.1 Candidates, scored against all ten frozen criteria

| §16 criterion | **Candidate 1 — variable-length event-sequence scoring** | Candidate 2 — grouped tabular ranking |
|---|---|---|
| lives outside the repo, arbitrary path, **no file under SIDERIUS** | ✅ generated + installed at an arbitrary path | ✅ same |
| topology unlike all three tracks | ✅ **variable-length integer sequences grouped by entity** — §16 names this shape explicitly | ✅ **tabular groups** — §16 also names this |
| scope vocabulary NOT `rows` of (id, label) | ✅ `groups: ((entity_id, span_offsets), …)` | ✅ `partitions: ((group_key, row_span), …)` |
| primary metric id contains a `loss` token, direction **lower** | ✅ `sequence_nll_loss`, lower | ✅ `rank_hinge_loss`, lower |
| ≥1 observational secondary, OPPOSITE direction | ✅ `hit_rate_at_1`, higher | ✅ `ndcg_at_5`, higher |
| model roster = its own plugin ONLY | ✅ embedding-bag + small GRU; no builtin fits `[B,T]→[B,256,T]` | ✅ small MLP over group features |
| deliverable format none of the three use | ✅ **JSONL** (vs `.h5` / `.csv` / `.npz`) | ✅ **Parquet or JSONL** |
| health = `EXPLICIT_NONE` **or** one external check | ✅ `EXPLICIT_NONE` — the binding state the three tracks exercise least | ✅ same |
| synthetic, script-generated inside the package, CPU-trainable in minutes | ✅ deterministic generator, seeded; seconds of CPU training | ✅ same |
| task_description / forward contract / interpretation + proposer blocks supplied by the package | ✅ all declared in-package | ✅ same |

**Both satisfy all ten.** The design author's recommendation is **Candidate 1**,
on one discriminating ground: **variable length**. Pets and DAVIS are both
fixed-shape; TIDMAD is fixed-shape per partition. A variable-length sequence
task is the only candidate here that stresses *"residual `DatasetProfile`/scope
shape assumptions"* along an axis **no existing track exercises at all**, which
is precisely what §16's second criterion exists to falsify.

> **⚖️ CONTRAST CLAIM CORRECTED — operator ruling 2026-08-24 (§U.8 item 3).**
> The framework has **no collation seam at all** (`collate_fn`,
> `pad_sequence`, `PackedSequence` occur **zero** times repo-wide, including
> `tests/`), so a genuinely ragged batch cannot cross the boundary and
> **12e does NOT add one.** What this candidate proves is therefore stated
> exactly as:
>
> **variable-length raw/event-sequence task semantics with PACKAGE-OWNED
> topology adaptation** — *never* "native framework-level ragged batching".
>
> The package pads deterministically in its own code and **keeps variable
> length real in the scope vocabulary, the deliverable and the metric
> denominator**. The framework never learns how to pad an event sequence,
> which is correct composability rather than a shortfall. Every claim below
> should be read against that boundary.

**Q-12e-1 — RULED (operator, 2026-08-23): Candidate 1 — variable-length
event-sequence scoring.** All ten §16 rows are satisfied (the table above);
the deciding argument is that **variable length** is the one protocol
dimension none of TIDMAD (fixed-shape per partition), Pets (fixed `[3,144,144]`)
or DAVIS (fixed `[3,8,128,224]`→`[3,4,128,224]`) exercises at all — so this
candidate maximizes **protocol contrast**, not scientific difficulty, which is
exactly what §16 asks for. **Everything else in this document is
selection-independent** and remains unchanged by this ruling: the package
contract, census, negative controls, restore contract, Gate topology and
parallelization envelope are written against the *criteria*, not against a
particular task.

### D.2 What the selected package MUST ship (the frozen package contract)

Independent of which candidate is chosen:

```text
<pkg>/                         ← arbitrary path, ZERO files under SIDERIUS
  composition.yaml             ← the operator entrypoint; declares every family
  declared/
    dataset_profile.json       ← generic identity + OPAQUE topology
    task_config.yaml           ← task_description + forward contract (+ model_io)
    metric_<primary>.json      ← id contains a `loss` token, direction lower
    metric_<secondary>.json    ← opposite direction, observational
    task_health.yaml | none    ← EXPLICIT_NONE or one external check
    interpretation_blocks.yaml
    proposal_blocks.yaml
    implementor_blocks.yaml
  plugins/
    <pkg>_data_path.py         ← TaskDataPath + TaskScopeCapability
    <pkg>_metric.py            ← EvaluationMetric implementations
    <pkg>_model.py             ← PLUGIN_MODEL_TYPE / _CONFIG_CLASS / _MODEL_CLASS / _OUTPUT_TYPE
    <pkg>_objective.py         ← if the task needs a task-owned objective
  data/
    generate.py                ← deterministic, seeded, no download
    manifests/ + SHA256SUMS    ← identity-level, checksum-pinned
  README.md                    ← how an external author reproduces it
```

**The package is simultaneously three things** (parent §16 closing line): the
graduation vehicle, the negative-control vehicle (§J), and the census subject
(§I). That triple duty is why one package suffices and no second external
artifact is needed.

### D.3 Package identity contract — AMENDED by operator ruling (2026-08-24, §U.8 item 4)

Added because F-12e-C-1 proved the gap on a real artifact: a package-local
helper reached only by a **runtime import** entered neither half of the
identity chain, so editing it left the composition fingerprint bit-identical
and the resume returned `validated`.

> **Every PACKAGE-LOCAL, BEHAVIOUR-BEARING source file must EITHER enter a
> supported declared identity mechanism, OR be inlined into a declared,
> identity-bearing component.**

**The scope words are load-bearing.** *Package-local* and *behaviour-bearing* —
this is **not** a requirement to enumerate the Python standard library or
third-party dependencies. It covers the files the package itself ships that
decide what the task does.

Two required package-side falsifiers, and they must be a **pair**:

```text
mutate every package-local behaviour-bearing file  ->  fingerprint MUST change
same package bytes at a different absolute path    ->  fingerprint MUST NOT change
```

The second is not decoration: it preserves **Q-P1-2** — identity is keyed on
**content, never on absolute path**, so two checkouts of the same package are
the same scientific run. A "fix" satisfying only the first would break
relocation equality (N3) while looking rigorous.

**Recompute through the production entry point in a fresh subprocess on both
sides.** A test that captures a fingerprint as a string across the mutation
proves nothing — the F-12bc-7 lesson, which this project has now met three
times.

**Explicitly NOT required of 12e**: automatic framework-side fingerprinting of
an arbitrary transitive Python import graph. That is **named framework debt**
(§U.8 item 4), and any future implementation of it must still hash CONTENTS,
never locations.

**This contract does not, and cannot, cover a package's OBJECTIVE** — see
F-12e-A-1: `_compose_loss_plugins` declares a *directory* and the loss is
resolved *by name* at training time, so no package-side declaration reaches it.
A package-local hash bolted on here would **hide** the hole rather than close
it, which is why workstream A declined to add one.

**Ownership, per §U.9**: the objective declaration / selection / semantic
identity seam is **PR-12d's** (DAVIS's frozen exact-L1 acceptance requires it),
and **`C12-I` is the independent VERIFIER** that landed 12d actually closed it —
not a separate PR. **This paragraph stays as written until that verification
runs**: today the gap is open, and a design document must not describe a gap as
closed before the evidence exists.

---

## E. Semantic authority map

| authority | owner | 12e's relationship |
|---|---|---|
| composition root / manifest vocabulary | `workflows/task_composition.py` | **CONSUMES ONLY.** A fourth task needing a new manifest key is a §N STOP |
| `TaskDataPath` + `TaskScopeCapability` | `execute_tools/task_data_path.py` | consumes; the package implements both |
| metric handle + composition | `execute_tools/evaluation_metric.py` | consumes; the package supplies implementations **out of tree** |
| run-scoped plugin binding / propagation / provenance | 12d seam P (`PROVISIONAL_12D`) | **consumes — and its provenance output is what proves which plugin executed** |
| deliverable identity | 12d seam E, narrowed (`PROVISIONAL_12D`) | consumes; the package owns its JSONL/Parquet artifact semantics |
| run invariants / lock / fingerprint / resume | `core/run_invariants.py`, `core/resume.py` | consumes; **G6's third leg is proving these hold for an EXTERNAL package** |
| zero-core-edit census | **12e OWNS** (new standing guard, §I) | writes `tests/` only |
| adversarial rows A(part) + E | **12e OWNS** (§J) | writes `tests/` only |
| the external package itself | **12e OWNS — outside the repository** | writes **zero** files under SIDERIUS |

**The single most important line in this table**: 12e's largest deliverable —
the package — has a write set that is **entirely outside the repository**.
That is not a convenience; it is the claim.

---

## F. Semantic dependency DAG — what must exist before what

```text
 [landed 12d]
      │
      ▼
 (T) delta reconciliation ─────────────────────────────────┐
      │                                                    │
      ├──────────────┬───────────────────┬─────────────────┤
      ▼              ▼                   ▼                 │
 (E1) package    (E3) census        (E4-neg) negative      │
 contract        contract            control contracts     │
 frozen          frozen              frozen                │
      │              │                   │                 │
      ▼              │                   │                 │
 (E2) package    ────┤                   │                 │
 EXISTS              │                   │                 │
      │              │                   │                 │
      ├──────────────┴───────────────────┤                 │
      │        (census + negatives need a REAL subject)     │
      ▼                                                    │
 (E5) deterministic + integration proof of the package     │
      │        through the composition root (no spawn)      │
      ▼                                                    │
 (E-GATE) real graduation run  ── 2×1, real restart ────────┤
      │   ├─ zero-core-edit census executed at the run SHA   │
      │   ├─ executed negative controls (cheap witnesses)    │
      │   └─ restore + process provenance                    │
      ▼                                                     │
 (E-AUDIT) post-Step-12 cross-system graduation audit ◄──────┘
      │        (needs ALL evidence complete)
      ▼
 (E-FINAL) docs + terminal exact-head CI
```

**Three hard semantic edges, and nothing else is truly serial:**

1. **The package must EXIST before it can be executed, censused or attacked.**
   E2 gates E5, E-GATE, and the *execution* half of §I/§J.
2. **A restore witness needs a restorable state**, so the restart leg cannot
   precede iteration 1 — this is why `G-12e` is 2×1 and not 1×1 (parent §12
   point 4: *"the 2×1 stays, for the restore claim alone"*).
3. **The graduation audit needs all evidence complete**, by definition.

Everything else — contracts, census machinery, negative-control harnesses,
the restore harness — can be authored **before or beside** the package,
against the frozen contracts. That is what §G exploits.

---

## G. Parallel execution DAG, and the read/write sets that justify it

### G.1 The DAG

```text
                        landed PR-12d
                              │
                    (T) delta reconciliation          ← INTEGRATION OWNER, serial
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   WORKSTREAM A          WORKSTREAM B          WORKSTREAM C
   external package      zero-core-edit        restore / process
   construction          census + negative     provenance harness
   (E1 → E2)             controls (E3, E4)     (E4-restore)
        │                     │                     │
   writes: OUTSIDE       writes: tests/        writes: tests/
   the repo ONLY         census module         restore module
        │                     │                     │
        └─────────────────────┼─────────────────────┘
                              ▼
                   INTEGRATION CHECKPOINT (⛔ I)
                   the package meets the census
                   and the negatives, deterministically
                              │
                              ▼
                   (E-GATE) real graduation witness   ← INTEGRATION OWNER
                              │
                              ▼
                   (E-AUDIT) graduation audit
                              │
                              ▼
                   (E-FINAL) docs + ONE exact-head CI
```

### G.2 Per-workstream read/write sets

| | **A — package** | **B — census + negatives** | **C — restore/provenance** |
|---|---|---|---|
| **semantic deps** | E1's frozen package contract | §I census contract; §J matrix | §K restore contract |
| **read set** | the public protocol surfaces (`task_data_path`, `evaluation_metric`, composition manifest vocabulary, plugin contracts) | production dir list; census helpers; the package's declared identifiers (late) | `core/run_invariants.py`, `core/resume.py`, gate-evidence helpers |
| **write set** | **`<pkg>/` — entirely OUTSIDE the repository** | `tests/unit/guardrails/` (census) + `tests/unit/workflows/` (composition negatives) | `tests/` restore module + the Gate evidence harness |
| **shared authorities** | **none inside the repo** | census helper module *(shared with C — partitioned, see G.3)* | evidence harness *(shared with B — partitioned)* |
| **validation owner** | the package's own tests, run from the package | the census module | the restore module |
| `READ_ONLY_PARALLEL` | ✅ | ✅ | ✅ |
| `IMPLEMENTATION_PARALLEL` | ✅ **fully — zero repo write set** | ✅ after partition | ✅ after partition |
| `VALIDATION_PARALLEL` | ✅ | ✅ | ⚠️ the *real* restore leg is serial (Gate) |
| **integration point** | ⛔ I | ⛔ I | ⛔ I + E-GATE |

### G.3 The one genuine collision, and how it is partitioned

**B and C both want to touch the Gate-evidence harness**, and both may want a
shared "resolve the package's declared identifiers" helper.

Frozen partition — **one owner per shared artifact, the other consumes**:

- [ ] **B owns** the census module *and* the identifier-extraction helper.
      C consumes it read-only.
- [ ] **C owns** the Gate-evidence harness extension (process provenance,
      restore assertions). B consumes it read-only.
- [ ] Neither implements a private copy of the other's helper. **A duplicated
      helper is a merge-cost defect, not parallelism.**

**No workstream may edit SIDERIUS production source.** If any of them needs
to, that is the §N STOP trigger firing — and it is *diagnostic*, because the
graduation claim is exactly that no such edit is needed.

### G.4 The optimization target

**Shortest reliable critical path**, not maximum concurrent agents. The
critical path is:

```text
T  →  E1  →  E2  →  ⛔I  →  E-GATE  →  E-AUDIT  →  E-FINAL
```

B and C are **entirely off the critical path** if started at T. Their only
cost is the integration checkpoint. Parallelism here is cheap *because* A's
write set is outside the repository — there is nothing to merge.

---

## H. Validation economy — the table, and why 12e adds exactly ONE real Gate

**Parent §18a already froze this**, and its preamble is the governing
sentence: *"every cell names its MINIMAL independent evidence owner; no
Cartesian sweep … `standing` = an already-green census **cited, not
re-proven**."*

| claim / failure class | cheapest sufficient deterministic witness | integration witness | real witness needed? | why cheaper evidence is insufficient | evidence owner | invalidated by |
|---|---|---|---|---|---|---|
| the package composes through the real composition root | unit: `compose_run_task_bindings(<pkg>/composition.yaml)` resolves every family | ⛔I | **no** | composition is in-process by construction | B | any change to the manifest vocabulary |
| every declared family resolves to the package's own implementation | unit per family, asserting the RESOLVED object's identity | ⛔I | **no** | identity is checkable in-process | B | a change to `_compose_*` |
| the scope round-trips through the artifact+digest ABI | det oracle against the package's scope shape | ⛔I | **no** | 12bc's `G-12bc-B` already witnessed the real hop | A | a change to `scope_artifact` |
| **children resolve the out-of-tree package and execute** | — | — | **YES** | no in-process test crosses a real spawn boundary; 12bc's C-Gate carried no scope, 12d's tracks are in-tree packs | **`G-12e`** | any change to spawn/env/transport |
| **real restore consumes iteration-1 state in a FRESH process** | — | — | **YES** | semantic latency: a second process must read the first's committed state (F-P56-4) | **`G-12e` (2×1)** | a change to lock/resume/fingerprint |
| **zero SIDERIUS production-source edits** | census: `git status --porcelain` + sha256 manifest over the nine production dirs + identifier-absence census | ⛔I (dry) | **YES — measured AT the run** | §18 requires the census before AND after the *real* run; a dry census proves nothing about what a run creates | B, executed in `G-12e` | any production change |
| negative: package removed ⇒ named refusal | det + **cheap C-class subprocess** | ⛔I | **cheap only** | §14a.4: *never one training chain per control* | B | a change to composition refusal |
| negative: edited plugin ⇒ identity refusal | det + cheap subprocess | ⛔I | **cheap only** | the refusal happens **before** training | B | a change to identity verification |
| negative: relocation equality ⇒ legal | det (identity excludes host paths) + cheap subprocess | ⛔I | **cheap only** | same | B | a change to `content_identity` |
| negative: cross-task resume ⇒ refused | det | ⛔I | **no** | pure lock/fingerprint comparison | C | a change to run invariants |
| **which plugin implementations actually executed** | — | — | **YES** | provenance is a runtime fact | **`G-12e`** (via 12d seam P) | a change to seam P |
| TIDMAD / Pets / DAVIS non-regression | deterministic + integration; **their real Gates are CITED** | terminal CI | **no — by parent §18a** | see the escalation rule below | standing | see below |

### H.1 The regression-escalation rule for TIDMAD / Pets / DAVIS

**Default: cited, not re-run.** `G-12a-2`, `G-12bc-B`, `G-12bc-C` and
`G-12d`'s two tracks are already-recorded real evidence at their own SHAs.

**A prior track is escalated to a fresh real witness ONLY when all three
hold:**

1. 12e changes a **common runtime path** that task traverses;
2. deterministic/integration evidence **cannot** prove non-regression;
3. the design **names the exact failure class** requiring the real witness.

**Under the zero-core-edit claim, condition (1) should be FALSE by
construction** — if 12e changes no production source, no prior track's runtime
path moved. **So an escalation request is itself evidence that the graduation
claim is failing**, and it routes to §N before it routes to a Gate.

If escalation ever is required, it uses the **cheapest bounded changed-path
witness**, never a full chain.

### H.2 Real-validation topology — FROZEN

```text
Gate 1                              0   (12e changes no prompts; pinned by parity)
G-12e  fourth task, 2 x 1           1   real LLM + real small training + real restart
executed negative controls          0 additional training chains
                                        (deterministic or cheap C-class subprocess)
TIDMAD / Pets / DAVIS real re-runs  0   (parent §18a: cited, not re-proven)
authoritative exact-head CI         1
                                   ───
total real launches                 1   (+ at most 1 bounded re-launch, §L.3)
```

**Any proposed real Gate without a named irreducible failure class is
challenged and removed.** The three that survive scrutiny — child resolution
of an out-of-tree package, real restore in a fresh process, and provenance of
what actually executed — are **all provable by the SAME single 2×1 run**,
which is why 12e's real cost is one launch.

---

## I. The zero-infrastructure-edit census contract

Parent §18 froze this as **executable, not asserted**. This section makes its
boundaries precise enough that the census cannot pass for the wrong reason.

### I.1 What counts as infrastructure source

| category | paths | may 12e change it? |
|---|---|---|
| **INFRASTRUCTURE SOURCE** | the nine production dirs pinned by `PRODUCTION_DIRS` (`test_step10_p1_c4_extension_proof.py:43-53`) | **NO — zero edits. This is the claim.** |
| task-package files | `<pkg>/…`, at an arbitrary path **outside** the repository | **YES — this is 12e's deliverable** |
| tests / guards / censuses | `tests/` | **YES** |
| documentation | `docs/` | **YES** |
| evidence / gate advice | the recorded evidence set | **YES** |

**The package lives genuinely outside the repository.** Not in `examples/`,
not in `tests/fixtures/`, not in a dedicated in-repo "external" folder — an
arbitrary checkout path. §16's first criterion is *"no file under SIDERIUS"*,
and an in-repo package would make relocation-equality untestable and the
census self-satisfying.

### I.2 The measurement

Frozen procedure, following §18 exactly:

- [ ] **Baseline SHA** — the candidate head, `git status --porcelain` **empty**.
- [ ] **sha256 manifest** over the nine production dirs, recorded.
- [ ] **Run** the normal operator surface only —
      `run_chain.sh … --task_composition <pkg>/composition.yaml --data_dir <pkg data>`
      plus the documented plugin-dir surface (12d seam P, `PROVISIONAL_12D`).
- [ ] **Final SHA / tree comparison** — `git status --porcelain` empty
      **after** the run, and the sha256 manifest **equal** before/after.
- [ ] **Generated files excluded** by construction: the run writes to the
      workspace, not the repo. **If the run creates a repo file, the census
      fails — that is the point**, so there is no exclusion list to argue over.

### I.3 The semantic half — what a grep-only census would miss

A byte-equality census proves nothing about *hidden accommodation*. The
census must also be semantic enough to catch each of these, each with its own
plant:

- [ ] **task-name branches** — the fourth task's name, task id, scope class
      name, metric id, and package name appear in **ZERO** production source
      (the `TestTheFourthTaskIsUnknownToTheFramework` shape, re-pointed).
- [ ] **central task catalog additions** — no id→behaviour mapping table.
- [ ] **infrastructure imports from the external package** — no production
      module imports anything under `<pkg>/`.
- [ ] **hidden fallback to TIDMAD** — a composed run that fails to resolve a
      package family must refuse, not silently resolve TIDMAD's default.
- [ ] **fourth-task semantics copied into generic core** — no constant,
      threshold or shape from the package appears in production.
- [ ] **special-case launcher / scorer behaviour** — no branch keyed on the
      package's identity in any launcher or scoring path.
- [ ] **task-specific schema growth** — no manifest key, enum member or
      record field added to name the fourth task.

**Anti-vacuity, per parent §17's meta row:** every plant asserts `count == 1`,
caches cleared, baseline re-run. A census that turns red for two reasons at
once is not a census.

### I.4 The census's own negative control

§18 point 5, frozen: **with the package path removed, the same command must
fail closed with the composition's named error.** Without this, a census could
pass on a run that never actually depended on the external package.

---

## J. Executed negative-control matrix

Parent §12-PR-12e point 4 requires these **EXECUTED against the real package**
— but §14a.4 bounds *how*: **each is discharged by a deterministic proof or by
the cheap C-class real-subprocess witness, and must not spawn its own training
chain.** *"Executed against the real package" is a statement about the ARTIFACT
under test, not a licence to re-burn the full workflow per control.*

| # | control | failure class | earliest expected refusal point | witness class | required evidence | why no training run |
|---|---|---|---|---|---|---|
| N1 | **package removed** | composition cannot resolve a declared family | composition root, before any spawn | det + cheap subprocess | the composition's **named** error; run exits non-zero | the refusal precedes training entirely |
| N2 | **plugin edited after the identity pin** | content identity divergence | child-side identity verification, before consumption | det + cheap subprocess | `TaskDataPathIdentityError`-class refusal naming BOTH identities | 12bc's `G-12bc-C` already proved the real-child shape; only the *artifact* changes |
| N3 | **package relocated, content unchanged** | false-positive identity refusal | must **NOT** refuse | det + cheap subprocess | run proceeds; identity equal because host paths are excluded | relocation equality is a pure identity property |
| N4 | **content mismatch under the same id** | two implementations claiming one id | registration, two-phase rule | det | `TaskDataPathRegistrationError` naming both contents | in-process by construction |
| N5 | **missing required declaration** | incomplete package | composition, named by family | det | error names the **family**, not a generic parse failure | pre-spawn |
| N6 | **task-id collision with a built-in** | id namespace | registration | det | named refusal, never silent replacement | pre-spawn |
| N7 | **invalid task-owned config** | malformed `config:` mapping (12d seam A) | composition | det | named refusal; **never silently ignored** | pre-spawn |
| N8 | **parent/child semantic identity mismatch** | transport severed or tampered | child, before consumption | det + cheap subprocess | child fails closed naming both facts | 12bc row C, extended to the real package |
| N9 | **hidden fallback attempt** | a family fails to resolve and TIDMAD's default is used | composition / scoring | det plant | census RED | this is a census plant, not a run |
| N10 | **resume against an incompatible package identity** | cross-task or edited-package resume | startup, run-invariants lock | det | fail-closed with the recorded mismatch | lock comparison is pure |
| N11 | **task-name-specific bypass plant** | someone accommodates the fourth task in core | census | det plant | §I census RED, `count == 1` | census plant |

**Three of these (N1, N2, N3) are the parent's explicitly named executed
controls** — package removal, edited-plugin refusal, relocation equality. They
are executed **against the real package**, using the cheap subprocess witness,
**inside `G-12e`'s evidence set but NOT as additional training chains**.

**Owner:** workstream B, except N10 (workstream C, restore family).

---

## K. Restore / process-provenance contract

**This is G6's third leg and the sole reason `G-12e` is 2×1 rather than 1×1.**

Parent §12-PR-12e point 4, frozen: *"The restore is proven REAL, not asserted
from the CLI's iteration count … the evidence records process provenance
(PIDs / process boundaries) showing iteration 2 ran in a fresh process
consuming iteration 1's committed state."*

- [ ] **Iteration 1** produces a committed, restorable state: the run-invariants
      lock, the composition fingerprint including the **external package's**
      content identity, and the iteration's records.
- [ ] **Iteration 2 runs in a genuinely FRESH process.** The evidence records
      process provenance — PIDs or equivalent process boundaries — proving the
      second iteration is not a continuation of the first's interpreter.
      **The CLI's iteration counter is not evidence.**
- [ ] **Iteration 2 consumes iteration 1's committed state**, and the semantic
      package identity is **the same value** across the boundary.
- [ ] **The identity that crosses is the one CAPTURED at registration**, never
      a fresh read of the plugin file — the F-12bc-7 lesson. A test that holds
      the digest as a string across the boundary would certify nothing; the
      assertion must go through the production path.
- [ ] **N10's cross-identity refusal** is proven deterministically beside it,
      so the positive and negative halves of the resume claim are both owned.

**Why this cannot be folded into iteration 1:** semantic latency. A restore
witness requires a second process reading the first's *committed* state — the
F-P56-4 rule that Step-10 established and that 12a's `G-12a-2` already obeys.
1×1 never re-reads its own lock.

**Why it CAN be folded into the SAME track** (answering the prompt's explicit
question): yes. The restore continuation is iteration 2 of the same bounded
run, not a second Gate. One launch, two iterations, one evidence set.

---

## L. `G-12e` — the real graduation Gate

### L.1 What one run proves

A single bounded 2×1 track carries every load-bearing real claim, because they
all traverse the same production path honestly:

```text
package lives out of tree           →  composition root resolves it
data-path plugin loads              →  model plugin loads
metric plugin loads                 →  objective (if task-owned) loads
health declaration honoured         →  no infrastructure edit was needed
normal train → infer → score        →  children resolve package identities
provenance proves what executed     →  task-owned deliverable written & read
task's scorer executes              →  primary (loss-token id, lower) reported
                                       secondary (opposite direction) reported
iteration 1 commits state           →  iteration 2, FRESH process, restores it
                                    →  process provenance recorded
```

**These are not separate failure classes requiring separate runs** — they are
sequential stages of one honest production execution. Splitting them would
re-burn the same path.

### L.2 Acceptance

- [ ] Workflow **exit 0**; real children spawned; training, inference and
      scoring executed.
- [ ] Records + lock stamped with **the package's** metric id and semantic
      fingerprint.
- [ ] Child argv captured, proving generic contracts carried the package's
      identity.
- [ ] `git status --porcelain` empty **before AND after**; sha256 manifest
      over the nine production dirs **equal**.
- [ ] Identifier-absence census green with the package's identifiers added.
- [ ] Iteration 2 restored iteration 1's state in a **fresh process**, with
      provenance.
- [ ] N1/N2/N3 executed against the real package, by cheap witnesses.
- [ ] **NOT criteria:** model quality · benchmark improvement · convergence ·
      HealthGate PASS · score magnitude · LLM response quality.

### L.3 Cost envelope and retry policy

Priced from **canonical workload**, not from historical environment failures:

| | value |
|---|---|
| expected workload | §16 requires synthetic, deterministically generated, **CPU-trainable in minutes** — no download, no GPU dependency |
| expected training | seconds to low minutes per iteration |
| restore continuation | iteration 2 of the same track |
| **physical launches** | **1 canonical**, maximum **2** |
| second launch permitted for | a genuine infrastructure/provider **INCONCLUSIVE**, re-run same-spec; **or** verification after a genuine production defect was diagnosed and fixed |
| third launch | **operator STOP** |
| GPU / API exposure | GPU optional by design; the LLM leg is the residual provider exposure |
| environment posture | written into the readiness packet **before** the first launch (the L2 lesson: across `G-12a-2`'s four attempts, **none** was defeated by its own code) |
| `Q-07c-6` | admission prices `phase="training"` only; a watchdog kill is **INCONCLUSIVE, never FAIL** |

**A failed environment launch is never justification for designing a larger
Gate.** Readiness preflight exists to reduce retries, not to grow scope.

**Do not conflate the number of validation TRACKS with the number of physical
launches** — 12e has one required track and at most two launches.

---

## M. Structural / god-file audit

**Expected production write set: ZERO** (§O). Therefore 12e creates **no new
structural hazard in any production module**, and this section's honest
conclusion is a check, not a refactor.

- [ ] **No production main file is touched**, so no node's public boundary or
      orchestration role moves.
- [ ] **No universal "external task context" god object** is created — the
      package declares through the existing per-family surfaces.
- [ ] **No task semantics are centralized** — that would fail §I's census.
- [ ] The new **test-side** modules (census, negative controls, restore
      harness) are independent units with one owner each (§G.3), not one
      omnibus "graduation test" module.
- [ ] **No unrelated cleanup.** A structural refactor is justified here only
      if a 12e responsibility would otherwise worsen an already-measured
      hazard — and with a zero production write set, none can.

**If the source audit finds 12e must touch a production module, this section
is re-derived and §N fires first.**

---

## N. Material deviation / STOP conditions

**STOP for an operator ruling before freeze — do NOT silently absorb any of
these into a larger 12e:**

- [ ] graduation requires **task-name dispatch**;
- [ ] it requires a **central task catalog**;
- [ ] it requires a **new closed task-semantic enum** that must grow for the
      fourth task (the shape §D's `loss`-token criterion and 12d's A3 ruling
      both exist to prevent);
- [ ] it requires **duplicated task semantics** in generic core;
- [ ] it requires a **new execution architecture** or a second plugin/scorer
      path;
- [ ] it requires **substantial common-runtime genericization that 12d was
      expected to close** — this is the §B.1 finding, and it routes to a
      bounded corrective PR against the owning subsystem, never into 12e;
- [ ] it requires **changing TIDMAD / Pets / DAVIS scientific contracts**;
- [ ] it requires **modifying established Step-12 protocol ownership**;
- [ ] it requires **more real validation than the distinct failure classes
      justify**;
- [ ] the package **cannot be made genuinely out of tree**;
- [ ] **zero infrastructure-source edits cannot be proven honestly.**

---

## O. Expected infrastructure-source production edits

**TARGET: ZERO. The target is the claim.**

| expected production edit | classification | disposition |
|---|---|---|
| *(none anticipated)* | — | — |

**Every required change must be classified before it is written:**

| class | meaning | disposition |
|---|---|---|
| **A** | a 12d defect / incomplete closure | **STOP** → bounded corrective PR against 12d's landed subsystem; 12e re-validates only the invalidated evidence and returns |
| **B** | a true new capability absent from the Step-12 design | **STOP** → operator ruling; the parent contract underestimated something |
| **C** | task-package-local implementation | ✅ allowed — it lives outside the repository |
| **D** | test / harness only | ✅ allowed |
| **E** | documentation / evidence only | ✅ allowed |

**Any A or B that materially expands production infrastructure goes to the
operator BEFORE freeze.** **PR-12e becoming large is itself diagnostic
information** — it means the graduation premise is not yet true.

---

## P. Implementation sequence and parallelization envelope

| block | content | workstream | parallel class | semantic deps |
|---|---|---|---|---|
| **T** | post-12d delta reconciliation (§T) | integration owner | serial | landed 12d |
| **E1** | freeze the package contract + resolve **Q-12e-1**; author the census and negative-control **contracts** | A(+B) | `READ_ONLY_PARALLEL` | T |
| **E2** | build the external package | **A** | `IMPLEMENTATION_PARALLEL` — write set entirely outside the repo | E1 |
| **E3** | the zero-core-edit census (§I) as a standing guard | **B** | `IMPLEMENTATION_PARALLEL` | E1 |
| **E4** | negative-control suite (§J) + restore/provenance harness (§K) | **B** / **C** | `IMPLEMENTATION_PARALLEL` after the §G.3 partition | E1 |
| **E5** | deterministic + integration proof of the package through the composition root | A + B | `VALIDATION_PARALLEL` | E2, E3, E4 |
| **⛔ I** | **INTEGRATION CHECKPOINT** — evidence aggregation (§Q) | integration owner | serial | E5 |
| **E-GATE** | `G-12e`: 2×1 real graduation run + executed negatives + census at the run SHA | integration owner | serial | ⛔ I |
| **E-AUDIT** | post-Step-12 cross-system graduation audit (parent §12 point 2) | integration owner | serial | E-GATE |
| **E-FINAL** | docs (task-package protocol guide + objective-kind promotion procedure, audit item #14) + terminal exact-head CI | integration owner | serial | E-AUDIT |

**Block count is not frozen.** Refine from source during T; avoid
mixed-responsibility blocks. Each expands to the operator's 8-section form at
implementation, filling only paths, commands, counts, wall times and evidence
SHAs.

### P.1 The integration owner

**ONE integration owner / canonical branch owner**, responsible for: canonical
source truth · dependency satisfaction · integrating the isolated workstreams
· detecting overlapping core edits · deciding which evidence integration
invalidates · the final executable HEAD · the real Gate launch · graduation
evidence · terminal CI.

**Sub-agents and worktrees own bounded workstreams. They do not independently
certify Step-12 graduation.**

### P.2 Guardrails that keep parallelism from costing more than it saves

Before two implementation workstreams run concurrently, ALL must hold:

- [ ] disjoint or explicitly partitioned write sets (§G.2, §G.3);
- [ ] stable upstream interfaces (the contracts frozen at E1);
- [ ] one integration owner;
- [ ] a bounded merge strategy;
- [ ] **no duplicate implementation of a shared helper** — one owns it, the
      other consumes read-only.

**If two workstreams both need to edit the same file, one owns the change and
the other prepares tests/fixtures/read-only analysis.** They never
independently implement conflicting solutions.

---

## Q. Checkpoints as evidence aggregators, and the evidence-validity matrix

**FROZEN RULE: a checkpoint MUST reuse still-valid predecessor evidence.** It
may add validation only for a genuinely cross-block property, final integrated
wiring, or a property no predecessor owns. **A checkpoint must NOT
automatically rerun every predecessor's suite.**

### Q.1 ⛔ INTEGRATION CHECKPOINT

- [ ] The package resolves through the real composition root, every family to
      its **own** implementation.
- [ ] The census runs **dry** against the package's identifiers and is green.
- [ ] Every §J negative control that does not need a real run is discharged.
- [ ] **Cross-block property, owned by no predecessor:** the package the
      census inspects and the package the negatives attack are **the same
      artifact** the Gate will execute — asserted by content identity, not by
      path convention.
- [ ] `E2`'s, `E3`'s and `E4`'s own suites are **cited at their producing
      SHAs**, not re-run, unless the invalidation matrix says otherwise.

### Q.2 Evidence-validity matrix

| evidence | owning block | producing SHA | depends on | invalidated by |
|---|---|---|---|---|
| package composes; families resolve | E2/E5 | `___` | manifest vocabulary; 12d seam A | a change to `_compose_*` or to the package's declarations |
| scope round-trip oracle | E2 | `___` | scope artifact ABI | a change to `scope_artifact` or the package's scope shape |
| census dry-green | E3 | `___` | production dir list; package identifiers | any production change; a package rename |
| negative controls N4–N7, N9–N11 | E4 | `___` | composition + registry refusal paths | a change to those refusal paths |
| restore harness (deterministic half) | E4 | `___` | run invariants / resume | a change to lock or fingerprint |
| **census executed at the run SHA** | E-GATE | `___` | the whole run | **any commit after the Gate** |
| N1/N2/N3 executed against the real package | E-GATE | `___` | the package artifact | a package edit |
| real restore + process provenance | E-GATE | `___` | iteration-1 state | any change to resume semantics |
| graduation audit | E-AUDIT | `___` | ALL of the above | any later evidence change |

**Rerun by invalidation, never by ceremony.** If a block's inputs did not
change, its evidence stands at its producing SHA.

---

## R. Terminal exact-head CI discipline

```text
final EXECUTABLE head
  → the required real graduation evidence recorded against that SHA
  → docs / evidence-only closeout
  → final PR head
  → ONE authoritative exact-head CI
  → NO commit after that CI
  → PR-12e — READY FOR OPERATOR REVIEW — DO NOT MERGE
```

- [ ] Broad repository regression happens **once**, at the exact final PR head.
- [ ] **No repeated local full suites** unless a concrete source finding makes
      one necessary.
- [ ] No manual `workflow_dispatch`.
- [ ] **Post-merge (separate, and only after explicit merge approval):** verify
      the landed **tree** is semantically identical to the validated head — the
      repository squash-merges, so commit SHAs necessarily differ and
      **SHA equality is not the check**.

---

## S. Downstream contract — the final Step-12 closure

12e is the last child. Its closure obligations (parent §12-PR-12e point 2):

- [ ] the **§18a final validation matrix** executed and recorded;
- [ ] the **post-Step-12 cross-system graduation audit**: the §3
      extensibility matrix, the structural delta against §10's baselines, the
      §19 debt ledger, the §18 census, and the four-task evidence inventory —
      each **re-verified against current state**, not re-run as a workload;
- [ ] **only after that audit is recorded** may the roadmap's Step-12 row be
      marked COMPLETE; then §15.1 row updates;
- [ ] operator docs: the **task-package protocol guide** and the
      **objective-kind promotion procedure** (audit item #14);
- [ ] the §19 **named post-roadmap debt** list carried forward unchanged —
      12e does not silently absorb deferred items, **plus one new item this PR
      adds**: **the dashboard's legacy `agent/`-layout primary half remains
      undiscoverable for chain runs** (F-12e-UX-6) — Q-12e-2 = (a) ruled this
      OUT of 12e's scope; re-pointing its discovery at the chain layout (§V.13b
      option (b)) is named debt for a future PR, not silently dropped and not
      silently absorbed here.

**E-AUDIT scope, frozen (operator-required consistency fix, 2026-08-23):**
parent §12 point 2's word "re-run" describes what the AUDIT does to the
*matrix/ledger/census*, not what it does to *evidence*. **E-AUDIT is a
current-state census / evidence-aggregation audit, not a replay of historical
Gates or predecessor validation suites. Standing evidence is CITED unless its
own invalidation condition fired** (§Q.2's evidence-validity matrix is the
mechanism). This closes the same door §T already closes for reconciliation
(*"do not repeat a full historical audit if landed source matches the
recorded contract"*) — stated here too because E-AUDIT is the LAST place in
Step 12 an implementer could quietly re-open it.

---

## T. Post-12d reconciliation — REQUIRED before freeze

This draft is written against 12d's frozen **contract**, not its landed
implementation. Before freeze review:

> **⚖️ ENTRY CONDITIONS — operator, 2026-08-24. The operative list is §U.12's;
> §U.9 and §U.11 supersede §U.8 items 1, 5 and 6.** §T opens on **FOUR**
> conditions, not one:
>
> ```text
> LANDED PR-12d  +  FINAL ATOMIC C12-P CORE  +  C12-P-P PROMPT CLOSURE
>                +  LANDED-SOURCE C12-I GREEN
> ```
>
> There is **no separate `C12-I` production landing** — 12d owns that seam
> because DAVIS's frozen exact-L1 acceptance requires it, and `C12-I` is a
> **verifier that must be allowed to return NO**.

- [ ] 12d merged; record squash / final executable / final PR SHAs, its Gate
      results and the authoritative CI. **Also record how 12d closed the
      objective declaration / selection / semantic-identity seam**, since 12e's
      N2 and §K depend on it.
- [ ] **`C12-P` FINAL ATOMIC closure** — scope **B1 · B2 · B3 · B4 · B5 · B6 ·
      B7 · B11** (§U.11; B8 excluded from production-fix scope).
      **⛔ BLOCKING CHECK before reconciling anything: confirm the head being
      consumed is the FINAL atomic `C12-P` source, and that B6 is NOT enabled
      without complete B5 protection.** B6 masks B5; a partially-landed head
      would switch the runtime-control subsystem on for composed runs while
      beginning to write TIDMAD-identified calibration into a machine-global
      store — **looking more correct while being strictly worse.** Do not
      sample an intermediate head merely because it is green.
      Then reconcile 12e's own findings against what actually landed: several
      are currently *observable only because* those defects exist — e.g. the
      TIDMAD-only time-budget asymmetry the TIDMAD pack documents (§U.2's
      F-12e-KICK-9) should be re-read, and **possibly removed**, once time
      budgets are safe for every composed task.
- [ ] **Do not over-claim B5.** After `C12-P`, the honest statement is *"a
      foreign task no longer writes mis-identified calibration"* — **NOT**
      *"composed tasks have measurement identity"*. General
      measurement-identity extensibility stays **future debt** (§U.11).
- [ ] **Do not describe B8 as "fixed"** anywhere. Required wording: **NOT
      CURRENTLY REACHABLE**, latent under future transported-scope / runtime
      changes, covered by a reachability sentinel. It is protected by an argv
      accident, not a guard, and `D3` will make it live.
- [ ] **`C12-P-P` prompt closure landed** (§U.12). **`G-12e` may not run before
      BOTH `C12-P` units are complete.** 12e changes no prompt bytes, so §H.2's
      Gate 1 = 0 still holds — but **12e can only prove it introduced no prompt
      science, not that the prompts were clean to begin with.** Without
      `C12-P-P`, a passing `G-12e` would be consistent with the planner and
      proposer quietly feeding the external task TIDMAD-only constraints, and
      **nothing in the run would say so.** Re-read §H.2's parity pin against
      landed prompt bytes after it lands.
- [ ] **`C12-I` verification EXECUTED against landed 12d** — the five criteria
      in §U.9, run through the production entry point, not asserted. **A
      verifier that cannot return NO is decoration**: if any criterion fails,
      that is a finding against landed 12d routing to a bounded corrective per
      §B.1 — never into 12e, and never quietly downgraded to debt because the
      verification was expected to pass.
- [ ] **THEN re-state §J's N2 and §K's edited-package claim**, and remove
      workstream A's named objective exemption (§U.5). Today those claims hold
      for the `task_data_path` family and are **false for the objective**; they
      may only be broadened once the verification has actually run.
- [ ] **Delta reconciliation, not archaeology.** Re-read each
      `PROVISIONAL_12D` assumption against landed source and classify it
      `CONFIRMED` / `UPDATED_NONMATERIAL` / `MATERIAL`:
      - seam P's plugin binding, propagation semantics and the **provenance
        surface** `G-12e` depends on;
      - seam A's `config:` mechanism the package's manifest will use;
      - seam D's task-owned metric and objective route — **the package
        declares a `loss`-token primary and a task-owned objective, so 12d's
        A2-b/A3 closures are load-bearing for 12e**;
      - seam E's narrowed deliverable identity — the package's JSONL/Parquet
        artifact depends on it;
      - the B0–B11 register's final disposition.
- [ ] **Do not repeat a full historical audit if landed source matches the
      recorded contract.**
- [ ] Re-read the parent at its merged revision (this draft read it from the
      12d branch).
- [ ] Re-run the internal consistency sweep; then submit for freeze review.

**Only a `MATERIAL` change invalidating a block's premise warrants
re-planning.** A `MATERIAL` finding that 12d left the runtime ungeneric is
§B.1 / §N, not extra 12e scope.

---

## U. Implementation ledger

*(empty — CANONICAL implementation has not started; no box above is checked.)*

**Entry conditions:** 12d merged · §T reconciliation discharged · **Q-12e-1
ruled** · this design frozen by the operator · a fresh Implementation Working
Rules context.

### U.0 SPECULATIVE PRE-IMPLEMENTATION — kickoff ledger (2026-08-24)

> **STATUS: SPECULATIVE / DISCARDABLE. NOT FROZEN. DO NOT MERGE. DO NOT CLAIM
> READY FOR OPERATOR REVIEW. `G-12e` HAS NOT RUN AND IS FORBIDDEN UNTIL FREEZE.**
>
> Authorized by the operator to overlap independent 12e work with 12d's
> remaining validation, purely to reduce wall-clock time. **Nothing recorded in
> §U.0 is accepted 12e work.** Only landed post-12d source may become final
> authority, via §T. Every box elsewhere in this document remains `[ ]`.

**Source anchors.**

| field | value |
|---|---|
| `SPECULATIVE_12D_BASE_SHA` | **`bbc35d76`** — the 12d branch's committed HEAD at kickoff (B12's third applicability rule). A snapshot dependency anchor, **not** authority. Deliberately not rebased onto 12d's moving HEAD. |
| 12d branch / checkout | `step12-pr12d-contrast-subprocess-closure` in `/home/yuema137/SIDERIUS` — **read-only from this session**, never written |
| 12d changed-path census vs its anchor `cfaa5572` | 120 files, +21,169 / −1,014; heaviest in `tests/unit/execute_tools` (15), `execute_tools` (13), `tests/unit/workflows` (12), `nodes/ml_hyperparameter_tune_agent` (9) |
| 12d ACTIVE write set at kickoff | `agent/skills/evaluate_vram_skill/`, `agent/skills/model_io_probe_skill.py`, `nodes/ml_hyperparameter_tune_agent/runtime.py`, **`examples/{oxford_iiit_pet,davis_future_prediction}/declared/task_config.yaml`**, and its own tests |
| 12d open blockers at kickoff | B12/F-12d-25 closed at `bbc35d76` by the bounded option-B applicability rule; the TIDMAD `run_baseline` legacy defect remains OWNED BY 12d on `fix/run-baseline-datascope-parity` |
| planning worktree (design-only) | `/home/yuema137/siderius-step12e-planning` — unchanged in role |

**F-12e-KICK-1 — `origin/master` is 2 commits AHEAD of the 12d branch, and both
are documentation commits that collide with workstream D's subject.**
`17b9853a` (documentation-system refresh) and `c991d6f6` (SVG figures) rewrote
the root `README.md` and `AGENTS.md`, rewrote **all three example READMEs**, and
added an entire `docs/` system — `docs/concepts/task-package.md`,
`docs/guides/define-a-task.md`, `docs/getting-started/first-run.md`,
`docs/reference/entrypoints.md`. Consequences, recorded now so §T does not have
to rediscover them:

- **§V's audit predates them.** F-12e-UX-1 (public quickstart embeds a
  lab-local path) and F-12e-UX-5 (`AGENTS.md:104` cites a deleted runbook) were
  measured against `cfaa5572` and **must be re-verified against master's
  rewritten files** before either is treated as still-live.
- **§S's "task-package protocol guide" deliverable may be partly discharged
  already** by `docs/concepts/task-package.md` + `docs/guides/define-a-task.md`.
  12e should extend, not duplicate.
- **§V.14a's per-pack README table is stale** (it records 57/64/61 lines;
  master now has 68/79/76).
- **DAVIS's README has a genuine three-way divergence** — base 85, master 76,
  common ancestor 61. Both sides edited it. That merge is real work, assigned
  to D3 explicitly.

**F-12e-KICK-2 — a worktree imports its OWN source, verified empirically, not
assumed.** The venv's editable install hard-pins every package to
`/home/yuema137/SIDERIUS/...` via a `MetaPathFinder`. Tested rather than
reasoned about: `_EditableFinder` sits **last** in `sys.meta_path`, after
`PathFinder`, so with cwd at a worktree root the worktree's own modules win
(`execute_tools`, `core`, `workflows` all confirmed resolving locally, and
`tests/unit/examples/` runs 309 passed there). **Every workstream is instructed
to run `/home/yuema137/SIDERIUS/.venv/bin/python` with cwd at its own worktree.**
Without that check, this session would have been the CLAUDE.md portability
failure verbatim — a green suite validating a different clone.

**F-12e-KICK-3 — `examples/<pack>/` cannot host a `.py` entrypoint.**
`tests/unit/examples/test_pack_governance.py` guard (b) forbids any `.py` under
`examples/` outside `examples/<pack>/plugins/`, checked against BOTH the
filesystem and `git ls-files`; guard (c) is permanent (production never imports
`examples` or `tools.example_packs`). **The frozen entrypoint form is therefore
`examples/<pack>/quickstart.sh`** — which also matches §V.14c's "reuse, do not
invent", since the launcher it wraps (`run_chain.sh`) is itself shell. No guard
is re-scoped.

**F-12e-KICK-4 — the speculative worktrees have no `.claude/` and therefore no
launch hook.** `.claude/` is gitignored, so `git worktree add` does not
populate it: the `require_launch_approval` hook and its authorization ledger
exist ONLY in `/home/yuema137/SIDERIUS`. A real launch from a speculative
worktree would face **no mechanical guard**. This is recorded as a safety fact,
not exploited: `G-12e` is forbidden in this phase regardless, and when it is
eventually authorized the launch must happen where the hook is actually active,
under an explicit human-authored ledger entry with existing `used` counts
preserved. Also absent from worktrees: `tidmad_data_config.yaml` (falls back to
the template with a warning) and `.env`.

**F-12e-KICK-5 — 12d's F-12d-26 lands on 12e's entrypoint contract, and the
chain path was checked rather than assumed.** Mid-kickoff, 12d recorded
(`a9b943d5`) that **`--is_trial` does not mean "this round is a trial"; it
means "trials are ALLOWED", and it is the only input that can yield
`mode="formal"`** (`planning.py:302-307`; `trial_allowed = agent_input.is_trial`
at `ml_hyperparameter_tune_agent.py:823`). Omitting it falls through to
`single_file` — the legacy TIDMAD path — with a **silent** cascade:
`AttemptScopes()` empty so the composed scope capability is never called though
both packs implement it (`scope_acquisition.py:229`), `file_index` forced to
TIDMAD's 6, scoring resolving `SUBPROCESS_LEGACY` instead of `TASK_OWNED`
(`policy.py:1257-1261`), and every `--formal_*` knob ignored. Every Pets/DAVIS
Gate attempt to that point had run that way.

**Reach into 12e, verified in source rather than inferred:** the defect lives on
the **direct node CLI**, which is what 12d's D8a.1 Gate commands used. The
**chain** path 12e's entrypoints wrap — `run_chain.sh` →
`sdsc_submission_scripts/run_one_iteration.py` — **defaults `--is_trial` to
True** (`:857-860`), so `trial_allowed` is true and the composed route is
reached. ⇒ the frozen `quickstart.sh` contract is SAFE **as specified**, and
three constraints are now binding on D1/D2/D3: keep wrapping `run_chain.sh` and
never the direct node CLI; never pass `--no-is_trial` (it looks like "formal is
more rigorous" and is actually the legacy single-file path); and treat 12d's
pre-correction D8a.1 commands as known-wrong if read for reference. A guard
assertion naming F-12d-26 was requested in each pack's test.

**The generalizable lesson, worth carrying past 12e:** a run that silently
substitutes the legacy TIDMAD route for the task's own route **exits 0**. A test
that asserts only "the workflow ran" cannot tell the two apart — the assertion
must be that the TASK-OWNED route was taken (the task's scope capability was
really called; scoring resolved `TASK_OWNED`). This is the false-PASS shape
`G-12e`'s acceptance must be written against, and workstream A was told to build
its package's composition test that way.

**F-12e-KICK-6 — two §V findings re-verified against master's rewritten docs;
one is STALE and one MOVED SOMEWHERE WORSE.** Discharging part of
F-12e-KICK-1's obligation immediately, so 12e does not "fix" what is already
fixed:

- **F-12e-UX-1 is STALE — already fixed on `origin/master`.** The README's
  published chain invocation no longer embeds `/home/klz/Data/SIDEREIS_DATA/…`.
  Master `README.md:106-112` now publishes a **portable, composed, bounded,
  dry-runnable** command using `/path/to/workspace` and `/path/to/tidmad/data`
  placeholders with `--task_composition configs/task_composition/tidmad.yaml
  --num_iterations 1 --max_rounds 1 --dry-run`. **§V.14c's premise that the
  example entrypoint "must not inherit" a lab-local published path is
  discharged at the source**; what remains for D is to be *consistent* with
  this canonical shape rather than to invent a competing dialect.
- **`--dry-run` is real and is the right probe** — verified in code, not in the
  README that advertises it: `run_chain.sh:41` *"walk the chain, print exact
  commands, no side effects"*, implemented at `:164`, `:193`, `:335`. Because it
  **prints the exact commands**, a pack's regression test can assert the
  resolved invocation reaches `--task_composition configs/task_composition/
  <pack>.yaml` and never the direct node CLI or a Gate harness — a far stronger
  witness than `bash -n`. All three D streams were redirected onto it.
- **F-12e-UX-5 half-moved, and the surviving half is worse.** `AGENTS.md` no
  longer cites the deleted `docs/running_chain_test.md` — but **`CLAUDE.md:284`
  still does**, and the file still does not exist on master. The doc-sync rule
  that binds *every* node/skill PR therefore names a missing file. Severity is
  higher than the original finding, because `CLAUDE.md` is governing
  instructions rather than a reference doc. **Recorded as an integration-owner
  finding; no stream was authorized to fix it** (it is neither on 12e's claim
  path nor inside any workstream's write set) — it goes to §S's debt list or to
  a separate bounded docs correction, at the operator's discretion.

**Method note, and it is the same one §V.14i already recorded:** all three of
these were re-checked **against source**, and the `--dry-run` claim in
particular was first read from a README and only *then* confirmed in
`run_chain.sh`. A README is documentation, not evidence.

**AMBIGUITY-1 + AMBIGUITY-2 — flagged for operator confirmation at freeze, NOT
silently resolved.** §I/§O state the production write set is ZERO ("the target
is the claim"), while §V.13b classifies three `dashboard/` items as REQUIRED and
§V.15 gives workstream R a `dashboard/` write set. Read together these conflict
unless the census's scope is stated precisely. **Provisional resolution adopted
for this speculative phase, to be ratified or overruled at freeze:**

- §I.2's measurement is literally **run-scoped** — the tree is compared before
  and after *the run*, at one SHA — so it measures *"executing the fourth task
  modifies no repository file"*, **not** *"the PR's diff touches no production
  file"*. §I.3's semantic half forbids **task-specific** production content.
- A **task-agnostic** view-layer delta violates neither: removing a hardcoded
  higher-is-better assumption is *anti*-task-specific by construction.
- Placement is therefore chosen to keep the production delta minimal and
  honest: the ONE semantic projection lives in **`execute_tools/run_report.py`**
  (production, task-agnostic, pure — so the dashboard can consume the same
  authority, satisfying §V.5); its CLI and static renderer live in
  **`tools/run_report/`** (`tools/` is deliberately NOT one of the nine
  production dirs, and production never imports it); the example entrypoints
  live in `examples/<pack>/` (also not production).
- ⇒ **12e's entire production write set is `execute_tools/run_report.py` (new)
  plus three named `dashboard/` items.** Everything else is `tests/`, `docs/`,
  `examples/`, `tools/`, or outside the repository.

**Frozen shared contracts, set by the integration owner BEFORE dispatch** (§G.3
/ §P.2: one owner per shared artifact, the others consume read-only):

| contract | owner | consumers |
|---|---|---|
| `python -m tools.run_report --workspace <ws> --out <dir>` (also `--run-output <file>`); writes `index.html` + figures + `report.json`; **named** non-zero error when nothing is consumable | **R** | D1, D2, D3 — publish this exact string in their READMEs |
| projection reads **`run_output_{run}.json`**, never `summary_{run}.json` (settled by source, §V.13c) | **R** | all |
| `examples/<pack>/quickstart.sh` — thin `.sh` adapter over `run_chain.sh --task_composition configs/task_composition/<pack>.yaml`; repo root from `BASH_SOURCE`; workspace + data root REQUIRED with no lab-local default; bounded knobs are the F-12e-UX-2 set, **never `--data_scope`** | **integration owner** | D1, D2, D3 |
| census module + identifier-extraction helper | **B** | C (read-only) |
| Gate-evidence harness extension (process provenance, restore assertions) | **C** | B (read-only) |
| the external package artifact | **A** | B, C (identifiers parameterized; skip cleanly while absent) |

**Workstream ownership and write sets — disjoint by construction.**

| stream | worktree / branch | write set |
|---|---|---|
| **A** external package | `/home/yuema137/siderius-12e-A` `step12-pr12e-A-package` (reference only) | **`/home/yuema137/siderius-task-eventseq/` — its OWN git repo, ZERO files under any SIDERIUS checkout** |
| **B** census + negatives | `/home/yuema137/siderius-12e-B` `step12-pr12e-B-census` | `tests/unit/guardrails/`, `tests/unit/workflows/` |
| **C** restore / provenance | `/home/yuema137/siderius-12e-C` `step12-pr12e-C-restore` | `tests/` restore + evidence harness |
| **D1** TIDMAD | `/home/yuema137/siderius-12e-D1` `step12-pr12e-D1-tidmad` | `examples/tidmad/**` + one new test |
| **D2** Pets | `/home/yuema137/siderius-12e-D2` `step12-pr12e-D2-pets` | `examples/oxford_iiit_pet/**` (**not `declared/`**) + one new test |
| **D3** DAVIS | `/home/yuema137/siderius-12e-D3` `step12-pr12e-D3-davis` | `examples/davis_future_prediction/**` (**not `declared/`**) + one new test |
| **R** report + dashboard | `/home/yuema137/siderius-12e-R` `step12-pr12e-R-report` | `execute_tools/run_report.py`, `tools/run_report/`, three `dashboard/` items, own tests |

`declared/` is withheld from D2/D3 because 12d is **actively** editing exactly
those two files (F-12d-23's `model_io` declarations). **No duplicate 12d
repair** is permitted in any stream: an observed 12d defect is recorded
`OBSERVED / OWNER: PR-12d / NO DUPLICATE REPAIR` and left alone.

**Validation posture for the speculative phase:** deterministic tests, cheap
subprocess witnesses, bounded integration, and report projection from
**preserved real artifacts** only. **Zero** new real runs — no TIDMAD, Pets or
DAVIS Gate, and **no `G-12e`**. The full repository suite is not run; targeted
tests only. §H.1's escalation rule and §V.7's hierarchy are unchanged.

**Exit from §U.0:** when 12d lands, §T's delta reconciliation converts
`PROVISIONAL_12D` to `CONFIRMED` / `UPDATED_NONMATERIAL` / `MATERIAL`, each
speculative stream is classified `ACCEPT AS-IS` / `REBASE-ADAPT` / `DISCARD`,
the design is frozen, and only then are accepted commits transplanted onto
landed source and §U proper begins.

### U.1 ⛔ §N MATERIAL STOP — the reachable-path audit fired the §B.1 condition

> **STOP FOR AN OPERATOR RULING. NOTHING BELOW HAS BEEN REPAIRED, AND NOTHING
> BELOW MAY BE ABSORBED INTO 12e WITHOUT THAT RULING.** §N's trigger
> *"it requires substantial common-runtime genericization that 12d was expected
> to close"* has fired. §B.1 already froze the consequence: this routes to a
> **bounded corrective PR against the owning subsystem — never into 12e** — and
> **12e becoming large is itself diagnostic information.**

**How it was found, and why that matters.** Before dispatching any Gate, the
integration owner ran the §15 reachable-path audit as a **read-only** sweep of
the composed production route, explicitly modelled on 12d's two most expensive
lessons: **B12/F-12d-25** (a *thirteenth* blocker absent from a frozen
twelve-item register — the pre-phase GPU probe was an un-composed **fourth
child**) and **F-12d-26** (a composed run silently falling into the legacy
TIDMAD path **and exiting 0**). The audit's brief was: *find the fourteenth
blocker on paper, for free.* **It found nine.**

**Independently re-verified by the integration owner** — an agent's report is
not evidence, and these three were re-derived from source and by execution
before any of this was recorded:

- **B3 — `ProposalOutput` validates EVERY task's `segmentation_size` against
  TIDMAD's `psd_segment_length`, ungated.** `agent/schemas/proposal.py:28`
  imports `TIDMAD as DATASET_CONFIG` at module scope and `:1257-1265` raises
  when `psd % seg != 0`. **Executed:** with `psd_segment_length = 10_000_000`,
  Pets' own declared `144` leaves remainder **64 ⇒ REJECTED**; `512` leaves
  128 ⇒ rejected; **DAVIS's `128` passes only by arithmetic coincidence**
  (`10^7 = 2^7·5^7`, and `128 = 2^7`). The tuner's copy of this same rule *is*
  composition-gated (`planning.py:433` + `policy.py:122`); the proposer's is
  not.
- **B1 — the wall-time pre-flight is TIDMAD-only.** **Executed** against the
  real `examples/oxford_iiit_pet/declared/dataset_profile.json`:
  `resolve_training_workload(...)` raises `ValueError: this dataset profile
  declares no TIDMAD topology (missing ['dataset','channels','encoding'])` for
  every `sample_set` shape tried. Reachability confirmed at
  `execution.py:411-438`: the gate runs `if chosen_time_budget is not None:`
  and an `"error"` status becomes `raise RuntimeError("Time check error: …")`.
  ⇒ **with either time budget set — i.e. CLAUDE.md's own standard launch
  command — a composed non-TIDMAD run dies at `[Pre-flight 2/2]`, before
  training.** 12d's launches escaped it only because a `None` budget skips the
  gate entirely.
- **B5 — composed runs write duration-calibration records under TIDMAD's
  identity into a MACHINE-GLOBAL store.** `runtime.py:1592` calls
  `resolve_tidmad_measurement_capability(dataset_root=data_dir)`
  **unconditionally** from generic orchestration and feeds
  `IdentityContext(task_identity=…, data_shape_class=…)`; the guard at `:1600`
  tests only that the fields are *non-blank*, never that the task IS TIDMAD.
  The registry root is `~/.siderius/<schema>`
  (`calibration_registry.py:114-116`) — outside the workspace, shared across
  every run on the machine. **Nothing fails, the Gate passes, and a later
  TIDMAD run reads a foreign task's timings as its own.**

**The full set, as reported** (B1/B3/B5 verified above; the remainder recorded
as the auditor's findings pending confirmation, and explicitly labelled as
such):

| # | finding | severity | at the Gate | silent? |
|---|---|---|---|---|
| **B1** | wall-time pre-flight is TIDMAD-only (`workload_resolvers.py:56,163`; `evaluate_time_skill/wrapper.py:818,1009`; `inference_skill/estimator.py:215`) | **CRITICAL** | dies at `[Pre-flight 2/2]` whenever a time budget is set | loud, **misattributed** as an execution-system failure |
| **B2** | VRAM pre-flight prices every composed candidate at TIDMAD's `T=40000` (`evaluate_vram_skill/wrapper.py:694` reads the RAW plan dict with a `40000` fallback while `:178` builds the model through the config CLASS, whose pack defaults are 144 / 128) | HIGH | any planned `batch_size ≥ 21` ⇒ `feasible=False`; the LLM is told to *"reduce segmentation_size"*, a knob the task does not use | the **divergence** is silent; the refusal is loud and wrong |
| **B3** | proposer's ungated TIDMAD divisibility rule | HIGH | chain dies at the proposer, before the tuner | loud, wrong error text |
| **B4** | a **second, ungated reachability of B12's batch builder** (`probe_production.py:247-253`, ambient `resolve_dataset_profile()`), reached from `runtime.py:814` | HIGH | `ProbeInfrastructureError` → ABORT | loud, misattributed |
| **B5** | machine-global calibration contaminated under TIDMAD's identity | **HIGH — highest by kind** | **nothing fails** | **SILENT, EXIT 0** |
| **B6** | composed inference produces no runtime evidence (`inference_single.py:746-748` returns before `record_phase_workload`) | MEDIUM | `--runtime_watchdog` is materially weaker than reported | **SILENT, EXIT 0** |
| **B7** | `--max_steps_per_attempt` inert for composed non-TIDMAD runs (`runtime.py:996` swallows the `ValueError`) | MEDIUM | the harness-owned hard bound does not exist | one `(non-fatal)` line |
| **B8** | ~~LLM-selectable `order_strategy="sequential"` crashes the composed training child~~ — **SUPERSEDED by §U.10: NOT CURRENTLY REACHABLE.** The components are real; the composition is not (`--order_strategy` sits inside the `if sample_set is not None:` argv block). **Latent, not fixed** — see §U.11's required wording | — | — | — |
| **B11** | three different TIDMAD-scale defaults for one concept — `40000`, `10000`, `40000/1000` — one of which (`planning.py:519`) is injected into the **task's own** opaque `task_parameters` | MEDIUM | never fires; visible only in artifacts | silent |

**The ordering trap, and why this audit paid for itself.** **B1 fires first and
MASKS B4** — the probe lane is only reached *through* the time check — and B3
fires earlier still if the proposer emits the key. B5, B6, B7 and B11 never
fire at all; they are visible only in the artifacts. ⇒ **a Gate-driven
discovery of this set would have cost at least three launches and would still
have missed the four silent ones.** That is precisely the §15 failure mode
("real launch → discover one legacy assumption → fix → launch again") the
audit exists to prevent, and it is the same shape as B12 one layer out.

**B9 — a separate finding, and it is a DESIGN question, not a defect.** There
is **no collation seam anywhere in the framework**: `collate_fn`,
`pad_sequence`, `pack_padded`, `PackedSequence` and `nested_tensor` occur
**zero** times repo-wide including `tests/`, and the frozen four-method
`TaskDataPath` has no collation method. `generic_inference.py:115` builds a
plain `DataLoader`, so the first heterogeneous batch raises
`RuntimeError: stack expects each tensor to be equal size`. Q-12e-1's ruled
Candidate 1 is *variable-length* by construction.

- **The graduation claim survives**: the package can pad inside its own
  `__getitem__`, which is task-owned code and needs **zero** production edits.
- **What is reduced is the CONTRAST value**, honestly stated: padding is
  framework-invisible — no declaration, no validation, no accounting — so 12e
  would prove *"a task that internally pads to a fixed length runs"*, while
  the genuinely new axis (ragged batches) stays unexercised. The grouped scope
  vocabulary, the JSONL deliverable and the `loss`-token lower-direction
  primary all still deliver real contrast.
- **This is an operator decision**, and it is deliberately NOT resolved here.
  Note that §V.12b's rule applies by analogy: a capability must not become a
  new framework semantic merely because it would make a demonstration nicer.

**What the integration owner did NOT do, deliberately:**

- **No production source was edited.** Not one line, in any workstream.
- **No 12d defect was repaired** — B10 (the mode fallthrough) is F-12d-26 and
  is marked `OWNER: PR-12d / NO DUPLICATE REPAIR`; the fix commit `a9b943d5`
  is simply not in this worktree's history.
- **No Gate was run**, and `G-12e` remains forbidden.
- **The seven workstreams were NOT halted.** Their deliverables — the external
  package, the census, the negative matrix, the restore harness, the three
  example quickstarts, the report projection — are valid **regardless of how
  B1–B11 are routed**, because none of them depends on those defects being
  fixed. Halting them would have converted a finding into lost wall-clock for
  no evidentiary gain.

**The question for the operator, stated plainly.** Almost every one of these
sits in **admission / pre-flight / runtime-control** — the same neighbourhood
as 12d's own B12, and the same neighbourhood as the still-open **Q-07c-6**
(*admission prices `phase="training"` only*). So the routing is genuinely
ambiguous and is not the implementer's call:

1. **Are B1–B8/B11 PR-12d's?** 12d is not merged, and its own contract is that
   *"the composed runtime is generic below the composition edge."* If so, 12e's
   zero-production-edit claim survives intact — but 12d grows again, after
   already absorbing a thirteenth blocker.
2. **Or a bounded corrective PR against the owning subsystem**, per §B.1 and
   parent §12-PR-12e point 3, sequenced between 12d and 12e?
3. **Or does the parent contract underestimate a genuine capability** —
   pre-flight/admission being task-aware at all — making this a **class B**
   §O finding requiring its own design?

**What must not happen is 12e silently absorbing them**, which is exactly what
§N exists to prevent, and exactly what "PR-12e becoming large is itself
diagnostic information" is meant to catch. **12e's own claim is unchanged and
still testable**: whether it is *provable* depends on which of the three routes
the operator picks, because with B1–B4 live a composed fourth task cannot reach
training at all under the standard launch command.

**Standing reminder for the implementation session:** the largest deliverable
of this PR — the external package — has a write set **entirely outside the
repository**. If you find yourself editing SIDERIUS production source, stop
and read §N. That edit is not progress; it is the counter-evidence.

---

### U.2 Workstream D — the three example packs (speculative, complete)

**All three packs now have ONE documented run command, and it is the command
their regression test drives.** Branches `step12-pr12e-D{1,2,3}-*` off
`bbc35d76`; write sets exactly as partitioned; `declared/` untouched;
**zero production-source edits in any of the three.**

| | TIDMAD (D1) | Pets (D2) | DAVIS (D3) |
|---|---|---|---|
| entrypoint | `examples/tidmad/quickstart.sh` | `.../oxford_iiit_pet/quickstart.sh` | `.../davis_future_prediction/quickstart.sh` |
| data prep | **documents POINTING, not downloading** — no fetcher is shipped for TIDMAD and none was invented | existing `tools.example_packs.fetch_oxford_iiit_pet` | existing `tools.example_packs.fetch_davis` |
| tests | 11 passed / 1 skipped | 12 passed / 1 skipped | 16 passed / 1 skipped |
| the 1 skip, in all three | `tools/run_report` absent — workstream R owns it; the skip tightens automatically at integration | | |

**The reconciled flag contract (integration owner, verified against source).**
Three agents working from one frozen *shape* still produced three different
*flag sets* — the predictable cost of parallel authorship, and the reason the
shared contract had to be re-derived once evidence existed rather than guessed
up front:

- **`--start_iter 1` is REQUIRED in all three.** `--auto_resume` defaults ON
  (`_chain_common.sh:173`); on an **existing** workspace `run_chain.sh:277-278`
  takes `START_ITER` from `inspect_run_state.py --next-iter`, whose capture
  CLAUDE.md already documents as **corrupted by plugin-loader stdout**. D2
  reproduced the consequence end-to-end: the loop walks **zero** iterations,
  and because `run_chain.sh:336` prints `"… ${NUM_ITERATIONS} iterations
  walked"` **from `NUM_ITERATIONS` rather than from what was walked**, the
  chain announces success and **exits 0**. A published quickstart without it
  silently no-ops on any re-run.
  **The test for it is vacuous unless the fixture creates an empty-but-existing
  workspace** — a non-existent one short-circuits to `START_ITER=1` at
  `run_chain.sh:269`. D2 caught that hole in its own fixture by self-review;
  D1's dry-run verification had exactly that blind spot.
- **`--llm_config …/openai_tiered_pro.json` in all three** — chain default is
  `LLM_CONFIG=""`, app default `None` (`run_one_iteration.py:1030`), so
  omitting it silently drops per-node routing.
- **`--healthgate_mode` / `--result_authority` in none** — verified already the
  defaults (`_chain_common.sh:67-68`); a published command must not carry
  tokens that mean nothing.
- **Portions are per-pack with a stated reason.** Pets pins `1.0` because the
  chain default `0.1` would cut its bounded 370-image subset to 37 and stop the
  documented 37-class collapse reproducing; DAVIS uses `0.1` +
  `--validation_max_samples 8`.

**F-12e-KICK-9 — the time-budget asymmetry, and it is B1 wearing ordinary
clothes.** D1 independently added `--trial_time_budget_minutes 20
--formal_time_budget_minutes 60`, matching CLAUDE.md's standard command. That
is **correct for TIDMAD and unsafe for the other two**, because
`execution.py:411` runs the wall-time pre-flight `if chosen_time_budget is not
None` and it reaches the TIDMAD-only resolver (§U.1 B1). **TIDMAD's pack is the
only one of the three that may carry those flags today.** D1 was asked to state
*why* in its README so the asymmetry does not read as an oversight and get
"helpfully" copied into Pets or DAVIS. **No workaround was added and no
production line was touched** — B1 remains an open §U.1 finding. This is a
useful concrete demonstration that B1 is not theoretical: an agent reasoning
only from the repository's own documented standard command walked straight into
it.

**F-12e-KICK-10 — a cross-worktree write actually happened, and the partition
is what caught it.** D3's DAVIS `quickstart.sh` content appeared briefly in
**D2's** worktree. D2 detected it, preserved the foreign content, and
reconstructed its own file. **Verified end state: both worktrees correct** —
each script exists, is mode 755, is committed, binds its own manifest, and
mentions the other's task **zero** times in both directions. D2's *recovery*
was right; its *inference* that D3 had therefore shipped nothing was **wrong**,
and was corrected from the repository rather than accepted. Two lessons worth
keeping: **one owner per file is what made the clobber detectable at all** (D2
noticed because it owned that path), and **a sibling's report about a third
party is a claim, not evidence** — the same rule already applied to §U.1's
audit.

**Findings recorded, not repaired** (each outside the finder's write set):
`docs/getting-started/first-run.md`'s Level 3 states the per-pack command *"is
planned by PR-12e … will not publish that command until it exists"* — now false
for all three, and **independently flagged by all three streams**;
`examples/tidmad/resolved/README.md` carries a stale "the runtime does not read
this" absolute that is **generated** by
`tools/example_packs/projection.py::render_resolved_banner` and pinned
byte-exactly, so it belongs to the generator's owner; `STATUS.md`'s "no
launcher, by design" lines; and `_chain_common.sh:95-97`'s stale `--data_dir`
comment.

**D's integration checkpoint — executed, and it is the §Q.1 shape.** The three
branches were trial-merged into the speculative integration branch:
**all three merged cleanly, no conflicts**, and the combined write set is
exactly **12 files — nine under `examples/`, three new test modules — and ZERO
production files.** Combined `tests/unit/examples/` on the merged tree:
**348 passed, 3 skipped**, pytest's own exit status read from the log rather
than from a pipeline (the three skips are the `tools/run_report` guards, which
tighten automatically when R lands).

Two **cross-block properties that no single stream could own** were checked on
the merged tree, because each stream can only ever verify its own half:

- **Cross-pack independence holds in all six directions** — zero references to
  any sibling pack's path from any pack. Each stream asserted this for itself;
  only the merged tree can assert it mutually. (D2 found and removed an
  inherited `examples/tidmad/` reference in its own first draft, so this was
  not hypothetical.)
- **All three publish the SAME report command form**,
  `python -m tools.run_report --workspace … --out …`. Had they diverged, R's
  single module would have had to satisfy three shapes — which is precisely the
  failure the contract was frozen before dispatch to prevent.

**A worked example of why one owner per shared contract is worth the up-front
cost**: D2's follow-up removed `--healthgate_mode blocking` as a redundant
default, then noticed that **removing it moved an ownership boundary** — the
pack's README promises the two blocking gates fire and the Step-08 collapse
evidence reproduces, and that promise now rests on a launcher default the pack
no longer states. It added an assertion on the **resolved child argv** and
proved the assertion non-vacuous by driving `--healthgate_mode observe_only`
through the pass-through path. So if the launcher's default ever changes, the
example stops demonstrating the health system **as a red test** rather than as
a quietly weaker example. That is the right instinct: *a published example's
demonstration promise is a contract, and inheriting a value is not the same as
guarding it.*

**WORKSTREAM D — CLOSED (speculative).** After the contract reconciliation all
three branches were re-merged: **clean, 352 passed / 3 skipped** (exit status
read from the log), write set still exactly **12 files and ZERO production
files**, and all three now emit `--start_iter` and `--llm_config` and none
emits the redundant health-gate flag.

**F-12e-KICK-12 — `--start_iter 1` got a LIVE reproduction, twice, and the
second one had to PLANT the hazard.** The structural reading was right, but
the two streams that proved it did something better than assert it:

- D3 removed the flag and ran the published command against an existing empty
  workspace: `START_ITER` captured `"[PluginLoader] Loaded plugin: '…' … 1"`,
  `seq` reported *invalid floating point argument*, **the loop walked zero
  iterations, and the chain printed "DRY-RUN COMPLETE — 1 iterations walked"
  with rc=0.** Exactly the documented corruption, now witnessed.
- D1 went further and noticed its guard would be **vacuous on a clean
  checkout**: `agent_generated/models/` is gitignored, so the plugin-loader
  banner that corrupts the capture **does not exist there**, and a hopeful
  assertion would pass for the wrong reason forever. It planted the corruption
  with a shim interpreter that pollutes the inspector's stdout. *The hazard's
  own precondition was environment-dependent, so the test had to supply it.*

Both also recorded that pinning `1` converts a re-run against a **non-empty**
workspace into the **loud** stale-fresh refusal at `run_chain.sh:310` — so the
flag does not merely paper over the corruption, it restores the intended loud
failure.

**F-12e-KICK-13 — `git checkout --` restores from the INDEX and silently
reverts uncommitted work.** It destroyed a stream's in-progress edits once
during a mutation proof. This is the third item of
`feedback_mutation_proof_hygiene` reproducing in the wild; the working rule is
**stage before mutating**. Recorded because mutation proofs are now standard
practice here and this failure looks like "the mutation had no effect."

**SCHEDULED FOLLOW-UP — issue #267, absorbed into D's existing write set
(operator, 2026-08-24).** It lands **after PR-12d's D-FINAL performs its STATUS
L4 promotion**, and it is deliberately small:

- [ ] **mirror the Pets STATUS cleanup for DAVIS** — D2 amended
      `examples/oxford_iiit_pet/STATUS.md`'s stale "no launcher, by design"
      line (`e250363d`); **D3 deliberately did NOT** touch DAVIS's, recording
      that *"PR-12d owns `STATUS.md` maturity promotion and a conflict there is
      expensive"*. **That deferral was correct and now has a scheduled home.**
- [ ] remove the stale **"no launcher"** and **"no clip manifest"** statements —
      D3 recorded that the latter was **already false before 12e touched
      anything** (`clips.csv` has existed since D14-3), so this cleans a
      pre-existing untruth, not one 12e introduced;
- [ ] **preserve** the new composed-launch README (do not regress §U.2's work);
- [ ] add a small **README ↔ STATUS consistency assertion** *if it stays
      bounded* — the honest guard against exactly this class: a maturity
      document asserting an absence the pack no longer has.

**Explicitly NOT absorbed here**: #253 / #254 and the broader arXiv identity
work; and the **broken-link / docs cluster**, which remains **post-Step-12 docs
work**. Recorded so the boundary cannot erode by proximity — the same rule
`feedback_adjacent_debt_is_not_scheduled` states: adjacent debt found nearby is
a finding, not the next task.

**F-12e-KICK-11 — a worktree test run is NOT comparable to a main-checkout run,
and this must be known before any integration verdict.** D1 measured **51
pre-existing failures in `tests/unit/sdsc_submission_scripts/` in any git
worktree**, because those tests resolve `${REPO}/.venv/bin/python` and a
worktree has no `.venv` (§U.0 F-12e-KICK-2's other half). **Verified by a stash
comparison — 478 passed / 51 failed with and without the stream's work** — not
asserted. Integration must not read those 51 as a regression, and the terminal
CI (which runs in the main checkout) is unaffected.

### U.3 Workstream C — restore / process provenance (speculative, complete)

Branch `step12-pr12e-C-restore`, head `d3370711`, six files, **2,301 lines, all
under `tests/`. Zero production edits — and that absence is itself the §O
signal.** 37 cases in the C modules; with adjacent regression (12bc c1/c2,
step10 p1 c1, run-invariants, step11 c8 resume, resume): **255 passed / 1
skipped / 0 failed**, so no registry cross-contamination.

**§K, honestly split between what is proven NOW and what stays `G-12e`-only:**
iteration-2 freshness is **fully mechanised** — recorder, process ledger,
discriminator and a Gate call site that `runpy`s the iteration **in the
recorded interpreter**; an in-process *or forked* "iteration 2" FAILs. What
`G-12e` still owns is only that a REAL composed chain produced the state and
was wired through that call site. §K bullet 4's child-argv half is honestly
marked `UNPROVEN` rather than claimed.

**F-12e-C-1 — an out-of-tree package's HELPER MODULE does not enter the
identity chain. Confirmed at the mechanism, not just observed.** Workstream A's
`plugins/_eventseq_data_path.py` imports its sibling `plugins/_eventseq_corpus.py`
at runtime. That file is neither a manifest-declared `file:` ref nor a scanned
model plugin (underscore-prefixed; both directory scanners skip `_` members).
**Measured: editing it leaves the composition fingerprint BIT-IDENTICAL** —
`d94025b1…beda40d` before and after — **and `ensure_run_invariants` returns
`validated`.** The integration owner confirmed the mechanism independently in
`compute_semantic_fingerprint` (`workflows/task_composition.py:1335`): its
`plugins` term hashes `ResolvedPluginRef.canonical_identity()` — **declared
refs only** — while `content_identity` hashes *the defining module's own
source*. **A file reached only by a runtime import falls between the two.**

⇒ **"an external package can be edited and the resume refuses" is FALSE for any
such file**, and that is a realistic structure: external authors split code
across modules. It weakens §K's edited-package-resume claim and negative
control **N2**, and it was found only because the harness was pointed at a
**real** artifact rather than a fixture.

**Disposition, split so neither half hides the other:**

- **12e's own evidence is made sound by a PACKAGE-CONTRACT requirement, not a
  production edit.** Proposed §D.2 amendment, flagged for ratification at
  freeze alongside AMBIGUITY-1/-2: *every file a package ships that
  participates in behaviour must be declared or inlined; a file reachable only
  by a runtime import from a declared plugin is OUTSIDE the identity chain.*
  Workstream A was asked to inline or declare, **and to add a test that edits a
  byte of every non-declaration file it ships and asserts the fingerprint
  changes for each** — a file that cannot move the fingerprint must be named,
  not silently tolerated.
- **The framework-side gap is NAMED DEBT, not 12e's to fix.** Covering
  transitively-loaded package files is a production change, and any fix must
  preserve Q-P1-2 (paths are deliberately excluded so two checkouts of the same
  package at different absolute paths are the same scientific run) — so it must
  hash CONTENTS, never locations.

**F-12e-C-2 — two names for one concept, caught before it could silently halve
the evidence.** C had invented `SIDERIUS_PR12E_PACKAGE_ROOT` while B used
`SIDERIUS_12E_PACKAGE_ROOT`. C adopted B's and deleted its own second variable.
Worth recording because the failure mode is quiet: an operator setting one name
would watch half the Gate's evidence **skip**, not fail. One integration action
remains at ⛔I — promote B's `package_root_from_env` out of a test module so a
helper does not import a test.

**F-12e-C-3 — 12bc's own F-12bc-7 guard is satisfied by a CONSTANT.**
`TestThePinIsCapturedNotReRead` asserts `transport_argv(impl)[3]` is unchanged
across an edit — and **degrading `content_identity` to return the bare qualname
leaves all four of its cases GREEN** (mutation-verified). C's replacement
computes the sha256 **in the test, from bytes the test wrote**, and requires the
production emitter to have produced *that*; the same mutation turns all four of
its cases red. Stated honestly: repo-wide the mutation is not invisible — the
divergence-side test catches it — but **the emission site had no guard.** This
is `feedback_test_captures_what_production_recomputes` reproducing inside the
very guard written to prevent it.

**F-12e-C-4 — the registration capture does NOT cross a process restart, and
this is the architectural fact the restore claim rests on.** The in-process
content cache dies with the interpreter, so iteration 2's "capture" is a fresh
read of whatever is on disk when it registers. **A restore check keyed on it
compares two fresh reads and stays green through tampering** — F-12bc-7 one
boundary out, and a live hazard precisely because an evaluator asking *"did the
two iterations agree on the package identity?"* would naturally reach for it.
**The only carrier that actually crosses the restart boundary is the lock's
`task_composition_fingerprint`** — which is exactly why F-12e-C-1 matters
rather than being cosmetic.

**N10 — PASS deterministically, including against A's real package**, each case
running compose → `build_run_invariants` → `ensure_run_invariants` in a **real
second interpreter**. That is not decoration: the two-phase registration rule
refuses an edited package a second time within one interpreter, so the
in-process version of this test **cannot exist**. The refusal names exactly one
drifted field (`task_composition_fingerprint`), so it fires for the right
reason, with an unedited-package positive control. Both halves existed before
and **the joint did not** — `test_step10_p1_c1_composition` compares two
compositions *this* process performed, and `test_step10_p1_c2_consumption` uses
hand-written `"fingerprint-A"` / `"fingerprint-B"` strings. Step 10's W7 was a
defect in exactly that gap.

**Environment honesty**: pyright **excludes `tests/`**, so none of C's 2,301
lines is type-checked by CI, and it cannot run locally regardless (node
v10.19.0). Recorded rather than glossed, per CLAUDE.md's environment-assumptions
rule.

### U.4 Workstream R — report projection + bounded dashboard delta (speculative, complete)

Branch `step12-pr12e-R-report`, five commits (four from the stream, one from
the integration owner). **The persistence layer really was already rich and
typed while the reporting layer was absent** — §V.12's headline is confirmed by
building against it.

**The ONE semantic projection** is `execute_tools/run_report.py`, entry point
`build_report(*, workspace=None, run_outputs=None) -> RunReport`, with frozen
`extra="forbid"` types throughout and `RunReport.model_dump_json()` **being**
`report.json`, so workstream D consumes it directly. The CLI and static
renderer live in `tools/run_report/`, honouring the frozen flags. It exits
**3** with a **named** error on stderr (`no_run_output_found` /
`no_run_output_consumable` / `workspace_not_a_directory` /
`run_output_unreadable` / `run_output_malformed_json` / `run_output_invalid`)
and **creates no output directory on failure**; a corrupt artifact beside good
ones is skipped into `report.unreadable` rather than being fatal.

**Class-A coverage**: per-epoch train + validation objective labelled by the
typed `objective_kind` (never "loss"), R2/R3 comparability + reason, the
`MetricSpec` including direction, secondaries in scored/refused/**named-absent**
states, `TrainingDiagnosis` through 07b's existing line authority, health gates
with `check_verdicts` **and** the computed `display_label` (§V.13d's trap
avoided), all 13 statuses with `failure_attribution`, reproducibility identity
from the lock, and a **direction-aware** best-so-far. **All seven class-B
candidates were refused and recorded in `RunReport.gaps`. Zero new persisted
fields.**

**F-12e-R-1 — Q-09-7 = B is confirmed by measurement, not by assumption.** A
byte scan of **16,019 JSON artifacts found ZERO populated secondary metrics
anywhere**: the transport landed, no evaluator ever writes one. ⇒ the secondary
panel is exercised only in its named-absence state, and that limitation is
stated rather than papered over with a fabricated fixture (§V.6's rule).

**The dashboard delta is +257/−21 and stops exactly where §V.13b said.**
UX-9 was fixed **before** UX-3, in that order, because the direction was being
dropped at the API mirror before it could reach the browser — `models.py` gains
a metric-identity mirror and reconciles server-side; `app.js` gains **one**
`orderFor()` direction authority that the three comparison sites and both axis
labels fold through, and **a series with no identity gets no best-curve and no
stars** rather than a guess. Five wire cases were verified on real records
(higher / lower / mixed⇒refusal / legacy⇒refusal / partial⇒ranked with a named
exclusion). UX-4's null series is fixed with the legacy fallback preserved.
**UX-8's census extension was proved against the ACTUAL pre-fix bytes** via
`git show HEAD:` — it reports all six historical sites at their audited line
numbers, so it is not green for the wrong reason.

**F-12e-R-2 — §V's own citations have DRIFTED, and the claims survive but the
line numbers do not.** Re-verified exact: `models.py:103`, the five `app.js`
sites, `index.html:95`, `local_json.py:66,69`, `router.py:565,600`,
`run_comparison.py:1190`, `pyproject.toml:15,18` with zero imports, the
duplicate `file_vector` declaration, `health_checks/schemas.py:607-624`,
`inspect_run_state.py:361`, the P2a `rglob`. **Moved:**
`training_history.py` 148/151/133 → **182/185/167** · the tuner's
"validation is the gate" comment 1577-1579 → **1601-1603** ·
`records.py:1017` → **1020** · composed reference-score suppression 963-977 →
**989-1000** · `execution.py:1246-1251` → **1317-1327** · the chain-layout
writer 2802 → **2777** · MetricOrder acquisition 3104 → **3079**. §T should
refresh these rather than trusting them.

**Two defects R's own tests caught in R's own code**, both worth keeping as
examples:

- **`resolve_run_order` skipped the partition step**, so a run mixing scored
  and unscored records was refused *wholesale*. Reproduced on a real artifact —
  `step09_5a_gate2_TERMINAL_PASS` iter_002, 15 records, 14 `error_training`,
  1 `success` — which lost its ranking, best-so-far and direction label
  entirely. **The 3-run fixture could not reveal it because every record in it
  is scored.** A fixture drawn from the happy path cannot see a partition bug.
- **`json.JSONDecodeError` was unreachable** after `model_validate_json`
  (pydantic v2 reports JSON syntax errors as `ValidationError`), so
  `run_output_malformed_json` could **never fire**. A named error that cannot
  occur is worse than no error. Split into parse-then-validate.

**F-12e-R-3 — the CI selector shared the very blindness the census fixes, and
the obvious repair traded one red test for another.** The new `.js`/`.html`
census derives no import edge, and the selector's `_production_files()` indexes
only py/md/txt/sh/json/jsonl/yaml — so **a change to `app.js` would not have
run the guard whose entire purpose is to constrain `app.js`.** R correctly
declined the fix (`tools/ci_selection/manifest.py` is outside its write set and
is a `FULL_SUITE_TRIGGER`) and handed it up.

The integration owner found the proposed broad entry (`"dashboard/"`)
**incomplete**: `resolver.py:295` consults `AREA_OWNERS` only `if not direct`,
so **any** directory scan covering a file that nothing imports **suppresses**
that file's area suite. `dashboard/main.py` is exactly such a file, and the
broad entry turned `test_an_area_owned_module_selects_its_area_not_everything`
RED while turning the reachability test green — **one failure traded for
another.** Baseline established by stashing the edit and re-running, not
assumed. **Scoping the entry to `dashboard/static/`** keeps the census
reachable and leaves every area fallback intact:
`tests/unit/tools/ci_selection/` **21 passed**. The underlying behaviour — *an
explicit directory scan REPLACES rather than AUGMENTS the area owner, and only
for files nothing imports* — is **recorded as a finding, not repaired.**

**F-12e-R-4 — `ruff check .` FAILS at PR-12d's current HEAD, and CI runs
exactly that command.** `tests/unit/execute_tools/test_step12_pr12d_task_owned_secondaries.py:160`
raises RUF012 (mutable default class attribute), introduced by 12d's own
`f740811c`. Verified by the integration owner at 12d's HEAD `3923b27d`:
`Found 1 error`, and `.github/workflows/ci.yml:64` runs `uv run ruff check .`
over the whole repository including `tests/`. **OWNER: PR-12d / NO DUPLICATE
REPAIR** — surfaced only because 12d would otherwise spend a CI run to learn it.

**F-12e-R-5 — new debt, not scheduled**: `LeaderboardEntry.rank` is a required
`int` while `local_json.py` emits `rank=None` for unrankable rows, so
`GET /api/models/{model}/leaderboard` would **500**, and its `metric_ranking`
note is dropped by Pydantic. Masked today only because the UI never calls that
endpoint — the same "unreachable therefore invisible" shape as §V.13b's other
two recorded-but-unscheduled dashboard defects.

**A process hazard worth naming**: R reported that the shared scratchpad
directory *"had briefly served me another workstream's log"*. With seven
concurrent writers a shared temp path is a cross-contamination channel for
**evidence**, which is worse than for code because a wrong log is read as a
result. R verified its run came from its own worktree. Future parallel sessions
should give each stream its own scratchpad subdirectory.

### U.5 Workstream A — the external fourth-task package (speculative, complete)

**`/home/yuema137/siderius-task-eventseq` — its own git repo, head `bc53a290`,
ZERO files under any SIDERIUS checkout, and ZERO SIDERIUS production edits were
needed.** Task id **`session_event_stream`**. Independently verified by the
integration owner: `session_event_stream`, `eventseq`, `sequence_nll_loss`,
`hit_rate_at_1` and `span_offsets` each appear in **0** files across the nine
production dirs.

**It runs, and the smoke asserts on HELD-OUT evidence** so a memorising model
cannot pass: 15 epochs, CPU, 2.3 s — `sequence_nll_loss` **2.349** vs 3.135
uniform, `hit_rate_at_1` **0.465** vs 0.043 chance. 64 tests pass, and pass
**identically from an unrelated absolute path with a byte-identical
fingerprint** (relocation equality, N3, on the real artifact).
`test_task_owned_route.py` asserts the capability is genuinely invoked and
scoring resolves `TASK_OWNED`, **and reproduces the F-12d-26 `single_file`
bypass as a discriminating counterfactual** — exactly the "assert the
TASK-OWNED route was taken, not that the run succeeded" rule.

**F-12e-C-1 is CLOSED, by INLINING.** The helper module is deleted and its
readers moved into the declared `task_data_path` file that the fingerprint
pins. A **rejected** the "declare the helper" option for a reason worth
keeping: **no manifest slot content-pins an arbitrary file**, and the two slots
that would accept one (`metric.implementation`, `model_plugins`) load it with
the wrong semantics. Its new census mutates one semantic byte per shipped
file, recomputing the fingerprint through `compose_run_task_bindings` **in a
fresh subprocess on both sides** — nothing captured across the mutation — and
**asserts its own coverage table against the files on disk**, so the table
cannot rot. Re-planting the hole as a new undeclared runtime-loaded module
turns the census RED with the fingerprint measurably unchanged
(`941e255f…` before and after).

**F-12e-A-1 — LOSS PLUGINS ARE OUTSIDE THE COMPOSITION FINGERPRINT, and a
package CANNOT close this one.** Verified at the source by the integration
owner: `_compose_loss_plugins` (`workflows/task_composition.py:1074`) returns
**`(roots_tuple, resolved_root_or_None)` — a DIRECTORY**, and
`compute_semantic_fingerprint` has **no loss term at any position**. Its
docstring states the intent plainly: *"a loss is resolved BY NAME at training
time through `LossConfig.loss_name`"*.

⇒ **Editing a package's task-owned objective does NOT fail a resume closed.**
This is F-12e-C-1's sibling and it is strictly worse: C-1 the package could
close by restructuring; **A-1 no package-side declaration can reach.** It
weakens N2 and §K for every package shipping a task-owned objective — which
includes A's package **and DAVIS's** (`davis_exact_l1_loss.py`).

**A deliberately did NOT add a package-local hash check**, and said why: *that
would hide the gap while looking like diligence.* It is the census's single
named exemption, asserted so the list cannot rot silently. **The correct
disposition is NAMED FRAMEWORK DEBT alongside F-12e-C-1**, and both belong in
the same operator decision, because together they define how much *"an edited
external package is refused"* actually means today.

**Four framework constraints A worked WITHIN — each a finding, none a blocker:**

- **No `collate_fn` seam (B9, confirmed from the consumer side).** A presents a
  fixed padded window and **keeps variable length genuinely real in the scope
  vocabulary, the deliverable and the metric denominator.** So the protocol
  contrast is **partially preserved** rather than lost — better than §U.1's
  conservative reading, and the honest statement is now: *ragged batches remain
  unexercised; variable-length scope/deliverable/metric semantics are
  exercised.*
- **`_SCOREABILITY_CONTRACT_TYPES` is a CLOSED vocabulary**
  (`execute_tools/evaluation_metric.py:687`) — an external task cannot supply
  its own contract class. `deliverable_presence` sufficed here, so it is a
  constraint, not yet a blocker.
- **`TaskTrialAnchoring` is unusable by a non-TIDMAD task** — its return value
  is fed to a TIDMAD-shaped `load_anchor_map`
  (`ml_hyperparameter_tune_agent.py:448,464`). A declines to declare it; the
  tuner prints "trial anchoring SKIPPED" and continues. **A correctly-shaped
  NOT_APPLICABLE, which is the §15 audit's acceptable answer.**
- **`ScopeBuildRequest` carries no dataset profile** by design, so anchor
  representatives are declared in `task_data_path.config`.

**F-12e-A-2 — a package must not register at module level, and the reason
generalizes.** A's declared file is executed **twice** per composed run (once
for the `task_data_path` symbol, once from the metrics module) because plugin
module names are keyed on `(logical ref, SYMBOL)`
(`workflows/task_composition.py:436`). A module-level
`register_task_data_path` would offer the same id under a different module
qualname on the second execution. It doesn't need to — `_compose_task_data_path`
registers what it composes, parent-side and in every child — and the side
benefit is that the registry then holds the **configured** instance rather than
a bare anchor, which is the shape ruling A1 had to work around for Pets/DAVIS.

**Two more observed, not repaired**: two checkouts composed in one process
rebind the same `sys.modules` entry (harmless in production — one process per
iteration — but it constrains package structure); and **the plugin loader
prints to stdout during composition**, the same class as the `START_ITER`
corruption of §U.2, which A worked around with a sentinel line.

**Hygiene worth adopting fleet-wide**: `PYTHONDONTWRITEBYTECODE=1`. Early runs
wrote `__pycache__` into the reference checkout; A removed it and then
prevented it. Stale bytecode is the first item of
`feedback_mutation_proof_hygiene`, and every mutation proof in this PR depends
on not having it.

### U.6 Workstream B — census + executed negative matrix (speculative, complete)

Branch `step12-pr12e-B-census`, three commits, **write set exactly two files,
both under `tests/`. Zero production edits.** Unbound: 130 passed / 9 skipped;
**bound to the real package**: 137 passed / 2 skipped.

**The census binds its needles FROM THE PACKAGE, never from a list in the test
file** — `task_data_path.id`, every `symbol:`, every `file:` stem, `.py` stems
under every `dir:`-scanned plugin directory, every `require:` entry,
module-level identity constants read via `ast` **from source bytes**, metric
declaration ids, and the package directory name. An unset env var **skips with
a reason**; set-but-broken **raises**, never skips. §I.2 is executable from a
shell as `snapshot` / `verify`, and **`verify` FAILs when the BASELINE was
dirty**, so a Gate cannot launder a dirty tree by snapshotting it.

**Blindness-shape immunity, each proven rather than asserted** — and this is
the fifth time this project has had to design against these four:

- **F-12bc-6** (named a symbol, went stale) — needles are extracted at census
  time, so a rename follows automatically; pinned by
  `test_the_needles_come_from_the_package_not_from_this_file`.
- **F-12bc-9** (file set omitted a directory) — `PRODUCTION_DIRS` is
  **imported and asserted to be the same object** (never forked), the walk is
  cross-checked against `git ls-files` (an independent tool), and a plant is
  placed in **all nine** dirs.
- **F-P2b-4** (anchored regex blind to a leading `_`) — per-word normalized
  matching; `_eventseq` / `EventSeq` / `event-seq` / `event.seq` are one needle.
- **F-12e-UX-8** (`rglob("*.py")` vs `app.js`) — **no suffix filter at all**,
  and the cost of the alternative is quantified: a `*.py` census sees **3 of 16
  files** in `sdsc_submission_scripts`.
- Plus a fifth of its own: it **reads source bytes and never imports**, so no
  stale-`.pyc` hazard, guarded by `TestTheCensusReadsBytesNotImports`. Plants
  live in `tmp_path` mirrors, so no `git checkout` hazard either — the two
  remaining items of `feedback_mutation_proof_hygiene`, both closed by
  construction.

**N1–N9 and N11 are all discharged deterministically AND executed against the
real package** (`bc53a290`), cross-process rows using a cheap C-class witness —
a fresh interpreter calling the same `resolve_child_task_data_path` authority
every real child calls. **Zero training chains, zero launchers, zero GPU**,
exactly as §14a.4 requires. N3 correctly asserts **no refusal**. N2 additionally
proves the parent pin **does not follow the edit** (F-12bc-7) via
`transport_argv`, with a different PID and no protocol method reached.

**Four defects the REAL package turned out of B's own guards** — the same
lesson as F-12e-C-1, from the other side: *a guard validated only against a
fixture is validated against the fixture.*

1. Needle extraction was **blind to `dir:`-scanned plugins, `require:` lists
   and module-level identity constants — 9 → 16 needles.** It had been green
   while hunting two-thirds of what matters.
2. The widening then scavenged generic words (`classifier`, `mean`, …);
   constants must now be compound tokens.
3. N4 was coupled to the *package's authoring style* — it asserted on refusal
   vocabulary that changes with how the package registers. Now counts
   identities, not words.
4. N6 **skipped silently** when its rewrite found nothing. Now fails loudly.

**F-12e-B-1 — the controls read the package LIVE, so Gate evidence MUST name a
pinned package commit.** An early bound run showed `1 failed / 6 skipped` and
the next showed `42 passed`. That was **not flakiness**: workstream A edited a
plugin mid-run. Recorded as a standing requirement, not a curiosity — a census
whose subject can change under it produces a verdict about no particular
artifact.

**F-12e-B-2 — the copied-constant net is VACUOUS for this package, and it says
so.** A's package has no int ≥ 1000 and no float with ≥ 3 decimals, so that net
**skips with a named reason** rather than passing. The claim is carried by the
identifier census plus manifest equality instead. **A net that cannot fire must
announce it** — silently passing is the vacuity §I.3's anti-vacuity rule exists
to prevent.

**OBSERVED / OWNER: PR-12d / NO DUPLICATE REPAIR** —
`tests/unit/workflows/test_step12_pr12d_checkpoint_b.py` leaves DAVIS's health
view provider registered, so
`test_health_core_census.py::…::test_three_tasks_compose_disjointly_and_state_a_is_byte_stable`
**fails when both run in one process**. **Reproduced on a tree with neither
12e-B module present**, and bisected to that exact file. Same family as
F-12bc-8 (a registration-lifetime / test-isolation defect, not a census
defect). Also minor and unrepaired: `_compose_task_data_path`'s comment claims
"the registration performed above" while registration happens in the `else`
branch below, making its `except TaskDataPathRegistrationError` unreachable for
duplicates — a stale comment, not a behavioural defect.

### U.7 Integration state — all seven streams merged

**All seven branches merge cleanly into the speculative integration branch.**
Final integrated write set: **41 files**, of which exactly **five are
production** — `dashboard/api/models.py`, `dashboard/api/router.py`,
`dashboard/static/app.js`, `dashboard/static/index.html`,
`execute_tools/run_report.py` — precisely the set AMBIGUITY-1/-2 bounded, with
nothing added. The largest deliverable, the task package itself, is **outside
the repository entirely**.

Non-production: `examples/` (9), `tests/` (18 incl. fixtures and two helpers),
`tools/run_report/` (5), `tools/ci_selection/` (1).

**Integration verification — the 11 failures are ALL pre-existing, established
by controlled comparison rather than by inspection.** The broad affected-area
run on the merged tree reported **11 failed / 6835 passed**. Rather than
diagnose them one by one — or, worse, "fix" them — the baseline was measured:

| run | result |
|---|---|
| merged integration branch | **11 failed / 6835 passed** |
| **base `bbc35d76`, zero 12e changes, same command** | **11 failed / 6676 passed** |
| `diff` of the two FAILED name lists | **EMPTY — byte-identical** |
| the same four files in the **main checkout** (12d's live tree) | **94 passed, 0 failed** |

⇒ **Zero of the 11 are caused by 12e**, and **12e adds 159 passing tests and no
failures**. Three fail in *any* worktree even in isolation and pass in the main
checkout — the F-12e-KICK-11 family (gitignored local config a worktree lacks:
one is a subprocess-stderr byte comparison, the other a `TypeError: 'NoneType'
object is not subscriptable`). The remaining eight appear **only** in the large
batch run and are ordering/registry-pollution dependent — the class workstream
B independently bisected to a 12d test module (§U.6).

**The method is the point, and it is the same rule three times over in this
PR**: a red suite is not evidence of a regression until the baseline has been
measured with the same command on the same environment. Reporting "11 failed"
without that comparison would have manufactured a crisis; diagnosing them
individually would have burned an hour on defects 12e does not own.

**And the wrapper's exit status lied again.** The background run reported
**exit code 0** while the log said `11 failed`. That is the third occurrence in
this project's recorded history — `feedback_read_full_pytest_log` exists
because of the first two. **The verdict was taken from the log, every time.**

### U.8 ⚖️ OPERATOR RULING on the §U.1 STOP — 2026-08-24

> **⚠️ PARTIALLY SUPERSEDED — read §U.9, §U.10 and §U.11 first.**
> **Item 1's scope is NARROWED by §U.11**: `C12-P` covers **B1 · B2 · B3 · B4 ·
> B5 · B6 · B7 · B11** — **B8 is excluded from production-fix scope** (§U.10
> found it not currently reachable). **Item 5's separate `C12-I` production
> landing is WITHDRAWN** (§U.9) — the objective identity seam is owned by
> PR-12d, and `C12-I` is an **independent verifier**. **Item 6's 12d
> notification is discharged and now stale — it must not be resent.** Items 2,
> 3, 4 and 7 stand unchanged. **§U.8 is retained as the audit trail of how the
> routing was reasoned; §U.9 + §U.11 are the operative records.**

**The STOP is UPHELD as valid**, and routed. The governing sentence:

> **The STOP blocks final freeze / canonical acceptance / `G-12e`. It does NOT
> roll back independent speculative work already completed.**

**The newly discovered defects are absorbed by NEITHER 12d NOR 12e.** Two
**bounded corrective prerequisite units** are inserted between landed 12d and
canonical 12e, and **they are parallel to each other**:

```text
                   PR-12d LAND
                        │
          ┌─────────────┴─────────────┐
          ▼                           ▼
       C12-P                       C12-I
 admission / preflight        objective identity
          │                           │
          └─────────────┬─────────────┘
                        ▼
               12e §T reconciliation
                        ▼
                FINAL 12e FREEZE
                        ▼
                     G-12e
```

**Why neither owner was right, in the operator's reasoning** — worth recording
because it is the general rule, not a one-off: *absorbing them into 12e would
make its zero-production-edit graduation claim lose focus and turn 12e back
into a genericization campaign; absorbing them into 12d would extend an
already-enormous PR with a whole new preflight/admission surface that only
12e's systematic audit discovered.* **A finding's discoverer is not
automatically its owner, and neither is the nearest open PR.**

| # | ruling |
|---|---|
| **1** | **B1–B8/B11 → `C12-P` — Composed Admission / Preflight Closure.** Not 12d, not 12e. Scope = the CONFIRMED generic admission/preflight/applicability/runtime defects. **B10 stays `OWNER: PR-12d` and must not be duplicated.** A CONFIRMED matrix is required **before** implementation — reachable path · invariant violated · loud or silent · existing applicability seam · minimal corrective behaviour · write set · deterministic falsifier. **No task catalog, no task-name dispatch.** |
| **2** | **B1 → immediate operational blocker ALERT to PR-12d — not an ownership transfer.** One question: *do the remaining frozen Pets/DAVIS launch commands set a non-null time budget?* **YES** ⇒ B1 is on 12d's own remaining acceptance path and 12d closes that specific blocker before launching. **NO** ⇒ 12d records it, does **not** expand scope, and `C12-P` owns it. |
| **3** | **B9 CLOSED BY DESIGN RULING — no production change, no new framework collation seam.** |
| **4** | **F-12e-C-1 — package-contract closure APPROVED** (see the §D.2 amendment). Automatic transitive-import fingerprinting is **named framework debt**, not 12e's. |
| **5** | **F-12e-A-1 → `C12-I` — External Objective / Semantic Identity Closure. NOT acceptable as debt.** |
| **6** | **Both 12d regressions notified immediately**; neither repaired here. |
| **7** | **Retain all completed speculative A/B/C/D/R work.** `G-12e` prohibited · final freeze prohibited · READY-FOR-REVIEW prohibited. |

**Ruling 3, stated precisely, because the difference is the whole point.**
PR-12e proves:

> **variable-length raw/event-sequence task semantics with PACKAGE-OWNED
> topology adaptation**

and explicitly **does NOT** prove:

> ~~native framework-level ragged batching~~

The package performs deterministic package-owned padding in its own code; the
framework never learns how to pad an event sequence, **and that is correct
composability rather than a shortfall**. The contrast axes 12e genuinely proves
are unchanged and remain substantial: variable-length source records · grouped
/ entity scope vocabulary · JSONL deliverable · task-owned sequence objective ·
LOWER primary direction · opposite-direction observational secondary ·
out-of-tree model/data/metric semantics. **This wording is now the acceptance;
§D and §B.1's claim text are corrected to match, and any later text asserting
native ragged-batch support is a regression against this ruling.**

**`C12-I`'s acceptance, frozen by the ruling** — deliberately small, and
deliberately NOT satisfiable by a package-local hash:

```text
identical objective content at two paths   -> SAME semantic identity
objective content mutated by one byte      -> DIFFERENT identity
resume after an objective mutation         -> LOUD refusal
existing / built-in objective behaviour    -> UNCHANGED
task-name or package-name dispatch         -> forbidden
```

The operator's reason for refusing the cheap fix is the one that matters:
**12e's claim is that _supported framework mechanisms_ provide reproducible
identity and refusal — not that this particular demo package bolted on its own
integrity system.** Workstream A had already declined to add that hash, for the
same reason, before the ruling existed.

**Why `C12-P` and `C12-I` are two PRs and not one**: they are different
authorities — `C12-P` is admission / preflight / applicability / runtime state;
`C12-I` is semantic identity / fingerprint / restore. Merging them would reduce
parallelism, not increase coherence.

**Status of this document after the ruling**: §T's entry conditions now read
*12d landed **AND** `C12-P` landed **AND** `C12-I` landed*. Everything in
§U.0–§U.7 stands as recorded speculative work.

### U.9 ⚖️ OPERATOR DEPENDENCY UPDATE — the operative topology

**Supersedes §U.8 items 5 and 6.** Two changes, both narrowing 12e's critical
path rather than widening it.

**1. The objective identity seam moves to PR-12d, because 12d already needs
it.** DAVIS's **frozen exact-L1 acceptance** requires the bounded authoritative
objective *declaration / selection / semantic identity* seam. F-12e-A-1 is
therefore not a downstream corrective at all — it is a prerequisite 12d must
close for its own frozen acceptance. **`C12-I` is withdrawn as a production
landing and becomes an INDEPENDENT VERIFIER.**

**2. The 12d notification is discharged.** PR-12d reports the previously
surfaced cross-session regressions **closed**. The three-item notice is
**stale and must not be resent.** For **B1**, keep only the dependency record —
**do not rebroadcast broad audit noise**; 12d has been instructed to verify B1
against **the exact next DAVIS launch command**, which is the right granularity
(the earlier question generalized over "remaining frozen commands", and one
concrete command is what actually decides it).

**The operative topology:**

```text
                      PR-12d LAND
              (now also owns the objective
               identity seam, for DAVIS L1)
                           │
             ┌─────────────┴─────────────┐
             ▼                           ▼
       C12-P canonical            C12-I as VERIFIER
          closure                 (no production landing)
   admission / preflight        does landed 12d satisfy the
   (B1-B7, B11; NOT B8)         objective identity claim?
             │                           │
             └─────────────┬─────────────┘
                           ▼
                  12e §T reconciliation
                           ▼
                   FINAL 12e FREEZE
                           ▼
                        G-12e   ← remains BLOCKED until the above reconcile
```

**What `C12-I`-as-verifier means, stated so it can actually fail.** A verifier
that cannot return NO is decoration. Its criteria are §U.8's unchanged, now
applied *to landed 12d* rather than implemented as a new PR:

```text
identical objective content at two paths   -> SAME semantic identity
objective content mutated by one byte      -> DIFFERENT identity
resume after an objective mutation         -> LOUD refusal
existing / built-in objective behaviour    -> UNCHANGED
task-name or package-name dispatch         -> absent
```

- **All five hold on landed 12d** ⇒ the claim is closed, **no separate landing**,
  and §J's N2 / §K's edited-package claim can finally be stated without the
  objective-shaped exception they carry today.
- **Any one fails** ⇒ that is a *finding against landed 12d*, and it routes the
  way §B.1 already froze — a bounded corrective against the owning subsystem —
  **not** into 12e, and **not** silently downgraded to debt because the
  verifier was expected to pass.

**The verification is largely already built, which is why this narrows rather
than widens.** Workstream C's harness (§U.3) recomputes identity **through the
production entry point in a fresh second interpreter** and already proves the
N10 refusal against A's real package; workstream A's census (§U.5) mutates one
semantic byte per shipped file and recomputes the fingerprint in a **fresh
subprocess on both sides**, with the objective currently its **one named
exemption**. **When 12d lands the seam, that exemption is exactly what the
verifier removes** — the assertion already exists in negative form.

**Retained from §U.8** (scope later narrowed by §U.11 to **B1–B7 · B11**, B8
excluded): the `C12-P` routing (items 1–2); **B9 closed
by design ruling, no production change** (item 3); the §D.3 package identity
contract (item 4); and item 7 — **speculative A/B/C/D/R work retained,
`G-12e` prohibited, final freeze prohibited, READY-FOR-REVIEW prohibited.**

**One honest consequence for §D.3.** Its closing paragraph says the package
contract "does not, and cannot, cover a package's OBJECTIVE … That is `C12-I`'s
job." That remains true *today*; after 12d lands the seam it becomes **12d's
closed claim, verified independently**. The paragraph is left standing until
the verification runs — **a design document should not describe a gap as closed
before the evidence exists.**

### U.10 `C12-P` CONFIRMATION MATRIX — verified, and it changes the scope

Produced read-only per §U.8 item 1, against the integration tree (`bbc35d76`
is an ancestor; the verifier disclosed the drift rather than assuming). Pure
imports and pure calls only, under `PYTHONDONTWRITEBYTECODE=1`, against the
**real** Pets and DAVIS declared profiles. **One row did not survive.**

| row | verdict | fires today on a composed contrast run? |
|---|---|---|
| **B1** wall-time preflight TIDMAD-only | **CONFIRMED (executed)** — its 3 extra sites confirmed but **shadowed** | **YES — ends the attempt** |
| **B2** VRAM preflight prices at TIDMAD's `T` | **CONFIRMED (executed)**; threshold **21 is exactly right**; conditional on the plan omitting the key | **YES** — first gate that can reject |
| **B3** proposer's ungated divisibility rule | **CONFIRMED (executed)** | **YES** — at the proposer node |
| **B4** second probe reachability | **SETTLED: it RAISES**, never a silent TIDMAD read | NO — **masked by B1** |
| **B5** TIDMAD identity into `~/.siderius/` | **CONFIRMED**; identity values executed | NO — **both lanes masked** |
| **B6** composed inference has no runtime evidence | **CONFIRMED, and MATERIALLY UNDERSTATED** | **YES, silently** |
| **B7** `--max_steps_per_attempt` inert | **CONFIRMED (executed)** | **YES, silently** — first in the attempt |
| **B8** `sequential` crashes training | **NOT CONFIRMED as reachable** — latent | NO |
| **B11** three TIDMAD-scale defaults | **CONFIRMED and BROADER** — 3 values, **11** sites | partly, silently |

**The single most consequential finding, and it is larger than the row that
led to it.** B6 was scoped as "composed inference emits no runtime evidence".
The reported early return is real but **redundant**; the load-bearing gate is
in the **parent**: `core/sandbox_executor.py:1528-1587` is ONE
`if sample_set is not None:` block containing `--runtime_observation_out`,
`--runtime_policy_json` **and** the **training** watchdog (`:1597`), with the
inference equivalents at `:1905`/`:1946`. A composed contrast run has
`sample_set = None`, so it gets **no observation sidecar, no runtime policy, no
in-subprocess admission and no watchdog on EITHER phase** — while
`--runtime_watchdog` is accepted and the policy is built. **A task-shaped value
is acting as the feature flag for a task-neutral subsystem**, and nothing logs
that the subsystem is off.

**The sharpest ordering constraint: B5 must land WITH OR BEFORE B6.** B5's
calibration lane is masked only by `runtime.py:1575 if not rv_block: return`,
and `rv_block` is empty precisely *because* B6 suppresses the sidecar. **Fixing
B6 alone makes B5 go live immediately** — writing `task_identity="tidmad_denoise"`
records into machine-global `~/.siderius/runtime_calibration_v2` for every
composed run. This is the discover-fix-relaunch treadmill in miniature, and it
is exactly what a matrix built before implementation exists to prevent.

**Masking map** (implementation order follows from it): B1 masks **B4** and
**B5 lane 1** · B1's own primary site (`wrapper.py:769`) masks its three extra
sites (`:818`, `:1009`, `inference_skill/estimator.py:215`) — all inside the
same `try`, so **fixing only the primary moves the identical error ~50 lines
and must be one commit** · **B6 masks B5 lane 2** · an unrelated argv gate
masks **B8**.

**Recommended order**: B7 + B11 (independent, silent, cheapest) → B2
(independent; first gate that can reject) → **B1 + its three shadowed sites as
ONE commit**, which unmasks B4 and B5 lane 1 → B4 + B5 lane 1 **in the same
PR** → B5 lane 2 → **B6 last** (largest edit; unmasks B5 lane 2) → B8 recorded,
not fixed.

**B8 is REMOVED from `C12-P`'s implementation scope — a good outcome.** Every
*component* of the claim is true (`typing.cast` is a runtime no-op;
`_PetsManifestDataset` has no `file_row_ranges`; `order_strategy` is
LLM-selectable and `validate_ordering_against_scope` does not refuse it), but
the *composition* is not: `--order_strategy` and `--file_order_json` live
**inside the same `if sample_set is not None:` block**, so the flag never
crosses the process boundary and the child takes its `"shuffle"` default.
**But this is an argv accident, not a designed protection** — `planning.py:451-456`
names the `D3` follow-up that flips training onto the transported scope, and
**the moment `sample_set` stops being `None` there, B8 goes live with no other
change.** Record it with a test that PINS the masking, so the protection cannot
disappear silently.

**Two qualifications on "no new mechanism needed", both stated loudly:**

- **B3** must move a module-level `from … import TIDMAD as DATASET_CONFIG` to a
  validation-time `resolve_dataset_profile()` — sanctioned by that function's
  own docstring for exactly this case (a Pydantic validator has no caller to
  thread a parameter through), but a larger edit than the others. The proposer
  is **the last ungated copy of a rule the tuner already gates** at
  `planning.py:435`.
- **B5's COMPLETE fix — a composed task declaring its own measurement identity —
  IS A NEW CAPABILITY FAMILY and is OUT OF `C12-P` SCOPE.** The bounded fix is
  refuse-by-declaration: derive no calibration when the task declares no
  measurement identity. **Do not invent an identity.** The full capability is
  post-`C12-P` debt, exactly as B12 recorded its own Option A.

**Three cross-cutting findings not in the nine:**

- **`evaluate_time_skill/wrapper.py:383-387` is a NON-CONFORMING applicability
  check** — `try/except ValueError` around `tidmad_topology`, the exact
  anti-pattern `dataset_config.py:826-838` and `runtime.py:251-261` forbid
  (*"a miss is a membership test, never an exception to catch"*). It would
  silently reclassify a **malformed TIDMAD** profile as inapplicable. Same
  class as 12bc's row-2-vs-row-4 rule, one subsystem over. Cheap to fix inside
  B1's commit.
- **DAVIS survives B3 by ARITHMETIC COINCIDENCE** (`10_000_000 % 128 == 0`).
  ⇒ **any B3 regression test written against DAVIS alone is vacuous.** It must
  use Pets' 144.
- **`resolve_scoring_workload` has no production caller**, so scoring
  contributes no watchdog term for **TIDMAD either**. Flagged so `C12-P` does
  not accidentally claim it; whether that is intentional is an open question.

**Four questions the verifier honestly could not settle**, each with the exact
cheap action that would: (1) **B2's firing frequency** — does a real planner
omit `segmentation_size`? A grep over persisted `plan_*.json` under the
preserved Gate artifacts settles it, no launch; if always present, B2 is latent
rather than live, though the divergence and the miscalibrated cap remain.
(2) whether scoring's absent watchdog term is intentional. (3) **whether `D3`
lands before `C12-P`** — if it does, **B8 must be promoted from "record" to
"fix"**. (4) whether `run_profile` is in lexical scope at B5's call site
(affects the write set, not the verdict).

### U.11 ⚖️ OPERATOR — `C12-P` scope ACCEPTED; dependency and claim boundaries

The §U.10 matrix is **accepted**. **No `C12-P` production repair is absorbed
into PR-12e.** What follows are 12e's *dependency and evidence* records.

**Confirmed `C12-P` production corrective scope: B1 · B2 · B3 · B4 · B5 · B6 ·
B7 · B11.** **B8 is removed from production-fix scope.**

**⛔ B5 + B6 ARE ONE ATOMIC CANONICAL DEPENDENCY — the sharpest reconciliation
hazard in this PR.**

```text
B6 currently MASKS B5.
Repairing B6 without complete B5 protection ACTIVATES incorrect
TIDMAD-identified calibration writes for foreign composed tasks.
```

⇒ **PR-12e must NOT reconcile against any `C12-P` INTERMEDIATE head where B6 is
enabled without complete B5 protection. Only the FINAL ATOMIC `C12-P` source
may be consumed.** This is a real hazard rather than a formality: a
partially-landed `C12-P` would look *more* correct than its predecessor (the
runtime-control subsystem finally switched on for composed runs) while silently
beginning to contaminate a machine-global store outside every workspace. **A
reconciliation that samples a green intermediate head would be reconciling
against a state strictly worse than the one it replaced.** §T carries this as a
blocking check.

**B6 — corrected root cause, recorded because the original wording understated
it.** The defect is **not** "composed inference forgets to record a workload".
It is:

> **A composed run's `sample_set=None` currently suppresses the task-neutral
> runtime observation / policy / child admission / watchdog machinery.**

A task-shaped value gates a task-neutral subsystem, across **both** phases, and
`--runtime_watchdog` is accepted while nothing is armed. **No PR-12e workaround
is to be added** — 12e observes this, it does not route around it.

**B5 — claim boundary, and the distinction must survive §T.** `C12-P` will
**NOT** invent general task-owned measurement identity. Its bounded behaviour
is **fail-closed**:

> a task with no applicable declared calibration / measurement identity **must
> not export calibration under a fabricated TIDMAD identity**.

**General measurement-identity extensibility remains FUTURE DEBT.** After
`C12-P` lands, the honest statement is *"a foreign task no longer writes
mis-identified calibration"* — **not** *"composed tasks have calibration
identity"*. Collapsing those two is exactly the over-claim §T exists to catch.

**B8 — REQUIRED WORDING. It must never be described as "fixed".**

> **NOT CURRENTLY REACHABLE** — latent under future transported-scope /
> runtime changes, covered by a **reachability sentinel / debt note**.

The distinction is load-bearing: B8 is protected today by an **argv accident**
(`--order_strategy` sitting inside the `if sample_set is not None:` block), not
by a designed guard. `planning.py:451-456`'s `D3` follow-up flips training onto
the transported scope, and **at that moment B8 becomes live with no other
change**. The sentinel exists to pin the masking so the accident cannot
disappear silently; calling it "fixed" would retire the sentinel's reason for
existing.

**Execution permission — unchanged.** Speculative A/B/C/D/R **retained** ·
**#267** remains queued inside D after 12d's D-FINAL · **`G-12e` forbidden** ·
**final freeze forbidden** · **READY FOR OPERATOR REVIEW forbidden**. Canonical
continuation stays: landed 12d **+** final atomic `C12-P` closure **+** `C12-I`
verification of landed 12d's objective identity → §T → freeze → `G-12e`.
**Only source-independent closeout work continues.**

### U.12 ⚖️ OPERATOR — `C12-P-P` added; the canonical dependency set

A remaining `C12-P` audit question is ruled: **the confirmed LLM-facing TIDMAD
prompt contamination is NOT absorbed into the mechanical `C12-P` core.** It
becomes a bounded child unit under the same top-level session:

> **`C12-P-P` — Composed Prompt Contamination Closure**

**Canonical dependency set — this is now the operative list:**

```text
LANDED PR-12d
    +  FINAL ATOMIC C12-P CORE      (B1 B2 B3 B4 B5 B6 B7 B11; B5+B6 atomic)
    +  C12-P-P PROMPT CLOSURE
    +  LANDED-SOURCE C12-I GREEN    (objective identity, verified not assumed)
        ->  §T reconciliation  ->  final freeze  ->  G-12e
```

**⛔ `G-12e` must NOT run before BOTH `C12-P` units are complete.**

**Why this is a genuine prerequisite and not tidiness.** 12e's graduation claim
is that an out-of-tree task runs the composed workflow **resolving zero
implicit TIDMAD semantics**. Prompts are the one surface where that can leak
**invisibly**: a Gate could pass, exit 0, and produce a plausible scientific
trajectory while the planner and proposer were quietly handing the external
task TIDMAD-only constraints. **The graduation evidence would be contaminated
at exactly the point it is being proven** — and unlike a crash, nothing in the
run would say so. This is C-P56-1's failure mode one layer up from where Step
10 closed it.

**The 12e-side coupling, stated because it is easy to miss.** §H.2 still holds
that **12e itself requires Gate 1 = 0** — 12e changes no prompt bytes, pinned
by parity. That remains true. **But 12e's Gate-1-free posture now DEPENDS on
`C12-P-P` having landed**: 12e can prove *it* introduced no prompt science, and
cannot prove the prompts were clean to begin with. Those are different claims,
and only the second one makes `G-12e`'s evidence meaningful.

**Gate economy across the two units — a clean worked example of the parent's
"Gate count by failure class" rule:**

| unit | Gate 1 | Gate 2 | why |
|---|---|---|---|
| **`C12-P` core** | **NOT REQUIRED** | one **bounded Pets changed-path witness** | mechanical applicability/admission changes; deterministic falsifiers own the rest |
| **`C12-P-P`** | **REQUIRED, bounded** | — | **it changes LLM-facing prompt BYTES**, and byte-parity cannot answer whether a real model still receives foreign science |
| **PR-12e** | **0** (§H.2, parity-pinned) | `G-12e` 2×1 | 12e changes no prompts and no production runtime |

**Already-recorded evidence that this contamination class is real**, so
`C12-P-P` is not speculative: **B3** (§U.10) is a prompt-adjacent instance —
the proposer's ungated TIDMAD divisibility rule rejects a valid contrast
`segmentation_size`, and the verifier noted the refusal is *"fed back through
`previous_failures`, so a real LLM is asked to 'fix' a value that was
correct."* That is foreign science reaching the model through the framework's
own feedback channel.

**No PR-12e production workaround is requested, and none will be added.**
12e observes and depends; it does not route around. **Source-independent
closeout only.**

## V. Step-12 Example Productization and Visualization Graduation

**ADDITIVE requirement (operator, 2026-08-23).** This section belongs to 12e
and is **not** moved backward into 12d's frozen implementation contract.

### V.0 The claim split — what 12d proves, and what 12e adds

Stating this explicitly is what stops 12e from re-proving 12d.

| | claim |
|---|---|
| **After PR-12d** | **FRAMEWORK / ENGINEERING CLAIM** — TIDMAD, Pets and DAVIS each have real L4 workflow evidence through the generic composed production path |
| **After PR-12e** | **PROJECT / USER-FACING GRADUATION CLAIM** — (i) the three persistent example packs are complete, self-contained *at the task-package level*, independently runnable through obvious documented public entrypoints, and produce inspectable results and visualizations, serving simultaneously as **tutorials · executable regression assets · genericity evidence**; **and** (ii) an unknown out-of-tree fourth task proves the protocol extends with zero infrastructure-source edits |

The target user experience, stated as the acceptance:

```text
git clone
  → read examples/<task>/README
  → prepare or point to data
  → run ONE obvious documented command
  → a bounded SIDERIUS workflow runs
  → inspect a summary + plots/report
```

…**without** needing to understand internal test harnesses, Gate scripts,
private lab paths, undocumented framework internals, or another example pack.

### V.1 Two findings the design author verified directly (audit-independent)

**F-12e-UX-1 — the public quickstart currently embeds a lab-local path.**
`README.md`'s documented chain invocation is
`bash sdsc_submission_scripts/run_chain.sh --mode lilab --workspace /home/klz/Data/SIDEREIS_DATA/exploration_chain_v1 …`.
A published quickstart must not require a path that exists on one machine.
**§5's rule is violated today**, and the fix is a documentation/contract
change, not a code change: the *validation environment path* and the
*documented external-user data-preparation contract* must be separated.

**F-12e-UX-2 — the bounded quickstart mechanism already exists, and
`--data_scope` is NOT it.** 12bc's B7 froze that `--data_scope` is **refused by
name** for a composed task that does not declare TIDMAD's topology, so it
cannot bound a Pets/DAVIS/fourth-task quickstart. The controls that *do* reach
a composed task's scope capability are already task-agnostic and already on the
chain launcher:

| knob | reaches | effect |
|---|---|---|
| `--trial_portion` / `--formal_portion` | `ScopeBuildRequest.portion` | fraction of the task's own scope |
| `--validation_max_samples` | `ScopeBuildRequest.max_samples` | hard ceiling on the eval leg |
| ~~`--target_files`~~ | ~~`ScopeBuildRequest.target_partitions`~~ | **THIS ROW WAS WRONG — CORRECTED 2026-08-24, see below** |
| `--num_iterations` · `--max_rounds` · `--max_epochs` | workflow depth | bounded exploration |

**Correction (F-12e-KICK-8, verified at both layers).** `--target_files` is a
**deprecated no-op** and reaches nothing: `sdsc_submission_scripts/_chain_common.sh:373`
parses it, and `:498` states verbatim *"DS7 — `--trial_strategy` /
`--target_files` are deprecated no-ops: still parsed (so existing invocations
don't break) but no longer forwarded"* — it never enters `APP_ARGS`;
`run_one_iteration.py:1648-1650` independently warns they are *"deprecated and
IGNORED"*. **The working bounded-quickstart set is therefore
`--trial_portion` / `--formal_portion`, `--validation_max_samples`, and
`--num_iterations` / `--max_rounds` / `--max_epochs`.** Publishing the retired
flag would have taught every example's users a bounding mechanism that silently
does nothing — worse than omitting it. Found by the DAVIS stream while
implementing against this very table.

**A second verified fact from the same source read, worth keeping**: the chain
parser has **no case at all** for `--no-is_trial`, so it is an "Unknown arg"
hard exit. That is an *independent* second reason F-12d-26 (§U.0's
F-12e-KICK-5) cannot bite the chain launcher — the flag cannot even be passed.
The guard assertion is kept anyway: two independent reasons a silent defect
cannot reach you is the right amount for a defect that exits 0.

⇒ **The bounded quickstart is a parameterization of the normal production
surface, not a bypass.** No example-only execution control may be added
(§4's rule), and none is needed.

### V.2 The entrypoint contract — FROZEN semantics, mechanics deferred

```text
ONE obvious user entrypoint per example
      ↓  (a THIN adapter — no logic of its own)
the normal SIDERIUS composition root
      ↓
the normal production workflow
      ↓
the SAME task declarations / plugins / configs that CI and the Gates validated
```

**Frozen prohibitions.** The example entrypoint must never become: a second
execution architecture · an example-only orchestrator · a hidden Gate wrapper
· a task-name branch in generic core · a duplicate implementation of the
production launcher.

**Frozen requirement.** *The command a user copies from the README is the same
command the example's regression test exercises.* There must not be a README
command A, a CI helper B and a Gate script C that traverse subtly different
paths. Internal Gate tooling may **wrap** the public entrypoint or exercise
the same lower-level production path, but must not define separate example
semantics.

**Deferred to implementation (§20's rule):** the entrypoint's filename and
form, whether an existing launcher abstraction is reused or a thin per-pack
adapter is added, and the exact flag set. **The audit decides this**, not this
document — the repository already has two operator CLIs (the single-tuner node
CLI and `run_chain.sh` / `run_one_iteration.py`), and reuse is preferred over
invention.

### V.3 Self-contained — the boundary, frozen

**Self-contained means: all code, config, plugin, declaration, provenance and
documentation needed to UNDERSTAND and BIND the task lives in that example
pack.** It does **not** mean committing raw data.

Raw TIDMAD / Pets / DAVIS datasets are **never** copied into git to make an
example "self-contained" — the existing data-lifecycle rule stands unchanged.
Each example README must make the boundary obvious and in this order:

```text
repo-shipped assets  →  external data dependency  →  preparation command
  →  expected prepared-data location / selection mechanism
  →  run command  →  expected output location  →  visualization command
```

**No hidden lab-server path may be required by the public quickstart contract**
(F-12e-UX-1).

### V.4 Ownership boundary for visualization — FROZEN

| | owns |
|---|---|
| **GENERIC** (framework) | training / validation objective history · primary-metric trajectory · secondary-metric trajectory · iteration status · best-so-far trajectory · generic run and provenance summary |
| **TASK-LOCAL** (the example / package) | domain-specific inputs and outputs · image / video / waveform / spectrum presentation · task-specific qualitative comparisons |

**The framework must never contain `if task == tidmad: plot spectrum`.**
Task-local visualization is reached through the example/package boundary or
invoked by the example's report layer — **never by task dispatch in generic
core**, which would fail §I's census on its own terms.

**Before inventing a visualization plugin family, audit the existing extension
mechanisms.** A new capability family requires the normal material-deviation
justification (§N); *plotting being convenient is not one*.

**Two semantic rules that are easy to get wrong, frozen here:**

- [ ] **Do not label every training objective "loss".** Display the actual
      objective identity the framework already types (`objective_kind`). For
      DAVIS, training MAE/L1 and terminal MSE / PSNR / MAE stay semantically
      distinct **even where the mathematics overlaps** — the three-lifecycle-roles
      distinction §22.9a froze.
- [ ] **Respect metric direction.** For a LOWER-is-better metric, "improvement"
      and "best-so-far" must not be computed or plotted with HIGHER-is-better
      semantics. The direction comes from the run's `MetricSpec`, never from a
      convention in the view.

### V.5 ONE semantic projection, multiple presentation consumers — FROZEN

```text
authoritative persisted run artifacts
            │
            ▼
   ONE semantic report projection      ← the only place semantics are read
            │
     ┌──────┴───────┐
     ▼              ▼
 static report   dashboard
 (portable)      (interactive)
```

- [ ] **A mature example must NOT require the dashboard to be understood.**
      There must be a lightweight way to produce or view the essential
      visualizations from a completed run.
- [ ] **The dashboard consumes the SAME projection.** There must not be one
      data model for static example plots and a second, unrelated one for the
      dashboard.
- [ ] **The dashboard is a VIEW, never a semantic authority.** It must not own
      metric direction · objective meaning · task identity ·
      training-history interpretation · run validity · model/plugin identity ·
      health semantics · composition semantics. It may query, project,
      aggregate for presentation, and render.
- [ ] **Format is source-derived, not chosen here** (§20): PNG/SVG, a
      lightweight HTML report, a report directory, or an existing
      framework-native reporting abstraction — the audit decides.

### V.6 Visualization must use REAL production artifacts — FROZEN

```text
user runs example → workflow produces artifacts → report/dashboard READS those
                                                   artifacts → plots reflect
                                                   what really happened
```

**Never:** a separate demo script fabricating example-looking curves. No
demo-only synthetic histories exist to make a plot attractive.

**If a desired view needs information that is not persisted today**, classify
before acting:

| class | meaning | disposition |
|---|---|---|
| **A** | already semantically owned, merely not persisted / not projected | ✅ a legitimate 12e projection gap |
| **B** | not part of the framework contract at all | **STOP** — it must not silently become a new framework semantic to improve a plot |

### V.7 Validation economy for productization — FROZEN

**Do NOT add three more expensive real full-agent Gates to prove entrypoints
and visualization.** The hierarchy:

| tier | proves | cost |
|---|---|---|
| **deterministic** | entrypoint / config resolution · report generation from KNOWN production artifacts · visualization correctness · no cross-example dependency | free |
| **bounded integration** | the documented example command reaches the correct production launcher; output artifacts are consumable by the report layer | cheap |
| **inherited real evidence** | full workflow reality for TIDMAD / Pets / DAVIS — **12d's `G-12d` tracks and 12a/12bc's Gates, cited** | already spent |
| **new real evidence** | only where 12e changes a runtime surface not sufficiently covered — **plus the independently required fourth-task graduation witness** | one launch (§L) |

**The decisive economy fact:** 12a, 12bc and 12d's Gates leave **preserved real
artifacts** for all three mature tasks, and `G-12e` produces them for the
fourth. **The report layer can therefore be developed and validated entirely
against already-recorded real artifacts — zero new runs.** That is what makes
this addition cheap.

**Do not rerun a full Pets / DAVIS / TIDMAD workflow merely because its README
or its visualization changed.** §H.1's escalation rule applies unchanged.

### V.8 Material-deviation triggers specific to this addition

- [ ] visualization requires **task dispatch in generic core**;
- [ ] it requires a **new capability family** merely to render;
- [ ] a desired view needs a **class-B** semantic that is not in the framework
      contract;
- [ ] the dashboard **cannot** consume the authoritative records without
      replacement — a **broad dashboard rewrite is OUT OF SCOPE** and is a
      material scope finding that returns to the operator;
- [ ] making an example self-contained would require **committing raw data**;
- [ ] the public quickstart cannot be made free of machine-specific paths.

### V.9 Audit-dependent content — PENDING

The following are deliberately empty until the read-only audits land, and are
marked **POST-12d RECONCILIATION REQUIRED** where they depend on 12d's final
tree (Pets/DAVIS pack completion is 12d's D5/D6):

- [x] **V.9a** current source-grounded maturity of all three examples — **§V.14**;
      *(original wording:* current source-grounded maturity of all three examples
      (the §2 A–L questions, per pack, with each surface classified
      `COMPLETE` / `FUNCTIONAL BUT INTERNAL` / `STALE` / `MISSING` /
      `DUPLICATED` / `TASK-SPECIFIC BY NECESSITY`);
- [x] **V.9b** the exact missing external-user surfaces — **§V.14b**;
- [x] **V.9c** the entrypoint strategy — **§V.14c**;
- [x] **V.9d** the data-preparation UX per pack — **§V.14b**;
- [x] **V.9e** the result/report contract — **DISCHARGED, §V.12**;
- [x] **V.9f** the dashboard source audit and the minimum required delta — **DISCHARGED, §V.13**;
- [x] **V.9g** the three-example acceptance matrix — **§V.10, filled**;
- [x] **V.9h** the parallel implementation envelope — **§V.15**.

### V.10 The three-example acceptance matrix — shape frozen, cells pending

Every cell must end as **`PASS`** or **`N/A WITH JUSTIFICATION`** — never an
unexplained blank.

**Baseline = the AUDITED state today** (§V.12–§V.14). Each cell must END as
**`PASS`** or **`N/A WITH JUSTIFICATION`** — never an unexplained blank.

| row | TIDMAD | Pets | DAVIS |
|---|---|---|---|
| L4 real workflow evidence inherited? | ✅ `G-12a-2` · `G-12bc-B` | ⏳ `G-12d` — **POST-12d** | ⏳ `G-12d` — **POST-12d** |
| independent README? | ⚠️ exists, **PR0-era identity doc** | ⚠️ same | ⚠️ same |
| data-preparation path documented + executable? | ❌ no script; 0 acquisition mentions | ❌ no script; 1 mention | ❌ no script; 1 mention |
| **ONE obvious run entrypoint?** | ❌ **none** | ❌ **none** | ❌ **none** |
| bounded quickstart mode? | ❌ not exposed (mechanism exists — F-12e-UX-2) | ❌ same | ❌ same |
| same production path as its validation? | ⚠️ its evidence is composed-chain; its README is not | ⏳ **POST-12d** | ⏳ **POST-12d** |
| no dependency on the other examples? | ✅ pack-local | ✅ pack-local | ✅ pack-local |
| training-history visualization? | ❌ persisted, **rendered by nothing** | ❌ same | ❌ same |
| iteration / metric trajectory? | ❌ only `/api/exploration/*`, direction-blind | ❌ same | ❌ same — **and inverted once composable (F-12e-UX-7g)** |
| task-specific qualitative visualization? | ❌ none (deliverables deleted by `--cleanup_denoised`) | ❌ none | ❌ none |
| generic run summary? | ⚠️ `inspect_run_state` = resume plumbing, not results | ⚠️ same | ⚠️ same |
| dashboard support? | ⚠️ legacy half only; chain runs unreachable (F-12e-UX-6) | ❌ **POST-12d** | ❌ **POST-12d**, and backwards |
| CI / regression owner? | ✅ `tests/unit/examples/` | ✅ same | ✅ same |
| fresh-workspace runnable? | ❌ no entrypoint | ❌ **POST-12d** | ❌ **POST-12d** |

Legend: ✅ already PASS · ⚠️ exists but not user-facing · ❌ missing ·
⏳ **POST-12d RECONCILIATION REQUIRED**.

**Reading the matrix honestly: the packs are complete as DECLARATIONS and
absent as PRODUCTS.** Every ❌ is a user-facing surface, none is a semantic
gap, and §V.12a established that the data behind every missing view is already
persisted. That is what makes this addition bounded.

### V.11 Definition of done for this addition

**12e cannot claim final Step-12 user-facing graduation merely because the
fourth-task Gate passes.** It must also establish that the three persistent
examples are genuinely usable artifacts for an external user — the journey in
§V.0, validated per example by a bounded acceptance test that **uses the same
command the documentation publishes**, in a fresh workspace, with no files
from either other example.

### V.12 The report contract — audit result

**The headline, and it is favourable: the persistence layer is already rich
and typed; the reporting layer is effectively absent.** That asymmetry is what
makes this addition cheap — almost everything a user-facing view needs is
already on disk in a Pydantic-validated form, so the work is **projection, not
new framework semantics** (class A, §V.6).

#### V.12a Persisted TODAY, rendered by NOTHING user-facing — the class-A surface

| information | persisted as | rendered today |
|---|---|---|
| **per-epoch training + validation objective** | `ExperimentRecord.training_history` → `TrainingHistory.train_objective` (`execute_tools/training_history.py:148`) and `.validation_objective` (`:151`) | **nothing** |
| the objective's typed identity | `TrainingHistory.objective_kind` (`:133`) | nothing |
| whether R2/R3 are comparable | `.comparability` (`:144`) + `comparability_reason` | nothing |
| the run's `MetricSpec` **including direction** | `HyperparamTuningOutput.metric_spec`; per record `metric_result.direction` | prompt renderers only |
| secondary metric results / refusals / errors | three record fields + `secondary_metric_specs` on the output | prompt renderers only |
| `TrainingDiagnosis` | `ExperimentRecord.training_diagnosis` | prompt renderers only |
| health-gate outcomes with per-check verdicts | `health_gate_results[]` | prompt renderers only |
| failures / skips with attribution | 13 statuses + `failure_attribution` | prompt renderers only — **and the dashboard filters them out** |
| reproducibility identity | `run_invariants_lock.json` (scope, health sha, composition fingerprint) | **nothing** |

**Every row above is class A** — already semantically owned, merely not
projected. This is the legitimate 12e work.

#### V.12b NOT persisted today — class-B candidates, to be REFUSED unless independently justified

per-step / per-batch loss (the epoch mean is kept, the batch list discarded) ·
per-epoch **training** seconds (only validation seconds are per-epoch) ·
per-sample score distribution · raw signals for a before/after plot (the
deliverables exist but `--cleanup_denoised` removes them) · GPU/VRAM time
series (present on **failure** records only) · a joinable **model-plugin
content identity** (records carry `model_type` — a NAME — and no digest) ·
a typed chain-iteration index on a record (recoverable only from the
directory name or `params["run_name"]`).

**None of these may become a new framework semantic to improve a plot**
(§V.6). If a view wants one, the view does without it, or the operator rules.
The one worth naming for a future step is the **model-plugin content
identity**: Step-12 pins *task*-plugin identity, not model-plugin identity —
a real asymmetry, but **out of 12e's scope** and not to be absorbed silently.

#### V.12c Three concrete defects the audit found

- **F-12e-UX-3 — the dashboard's Python half is direction-generic; its
  JavaScript half is not.** The backend routes ordering through `MetricOrder`
  (Step-10 P2a), but the frontend hardcodes higher-is-better in five places —
  `dashboard/static/app.js:154`, `:345` (`Math.max(best, score)`), `:372`
  (`score > best`), `:459`, `:503` — and labels the axis
  `'Denoising score (higher = better)'`, with `index.html:95` repeating
  *"Higher is better"*. **A lower-is-better run — DAVIS's `mse`, and the
  fourth task's `*_loss` primary by §16's criterion — renders a WRONG
  best-curve under a CONTRADICTING label.** This is the bounded "minimum
  generic consumer migration" §20 anticipates, not a rewrite.
- **F-12e-UX-4 — one dashboard chart plots an all-null series.** The frontend
  reads `r.results?.model_params`; the production `ExperimentRecord` carries
  **top-level** `model_params` and has no `results` key, so the mirror's
  default yields `None`.
- **F-12e-UX-5 — the operator runbook was deleted and is still cited.**
  `docs/running_chain_test.md` no longer exists, yet `AGENTS.md:104` still
  names it as *the* operator-surface doc that every node/skill PR must keep
  current, and three design docs cite line numbers inside it. **The doc-sync
  rule currently points at a missing file.**

#### V.12d Two assets that make the work cheap

- **The plotting dependency is already paid for and entirely unused.**
  `pyproject.toml:15` declares `matplotlib>=3.10.8` and `:18`
  `pandas>=3.0.1`, and a repo-wide search finds **zero** imports of either.
  A static report layer therefore adds **no new dependency** — and the
  absence of any existing plotting code means there is no legacy plotting
  convention to fight.
- **A typed, pure renderer family already exists and already crosses a node
  boundary.** `agent/prompt_templates/interpretation/rendering.py` and
  `.../tuner/rendering.py` expose pure functions over typed schema objects —
  metric identity, per-role diagnosis lines, secondaries, failure counts,
  direction words — and `render_prediction_track_record` is consumed from a
  *different node* (`nodes/ml_model_proposal_agent/evidence_rendering.py`),
  which proves the boundary holds.

  **But they are prompt renderers**: every function returns a prompt-line
  fragment, there is no page/table/figure concept, and residual TIDMAD nouns
  live inside them (`"Worst denoising score:"`, `"Training PSD segments"`).
  ⇒ **Reuse their single-authority layer — direction words, metric identity,
  diagnosis grammar — do NOT reuse their output shape, and do not extend them
  with a document concept.** The report projection is a sibling consumer of
  the same authorities, not a subclass of the prompt family.

#### V.12e What this settles for §V.5

The "ONE semantic projection" is **a projection over already-persisted typed
records** — not a new database, not a new persistence layer, and not a new
capability family. Its inputs exist; its authorities exist; what is missing is
only the projection and its two presentation consumers.

**No new persistence is authorized by this section.** A view that needs
something in §V.12b does without it or goes to the operator.

### V.13 The dashboard — audit result, and the bounded delta

**The operator's hypothesis was "the dashboard is old". Source says something
more specific and more actionable: half of it points at a layout the current
chain does not write.**

#### V.13a F-12e-UX-6 — the primary endpoints are structurally blind to chain runs

**VERIFIED.** Two on-disk layouts exist, and the dashboard's primary half
serves only the legacy one:

| | writer | path |
|---|---|---|
| **legacy layout** | `scripts/run_comparison.py:1190` — the ONLY writer of an `agent/` directory | `{model}/{run_name}/agent/summary_{run_name}_agent.json` |
| **chain layout** | `workflows/model_exploration.py:2802` | `{workspace}/iter_NNN/iteration_NNN/{model}/…` — **no `agent/` directory, ever** |

The dashboard's canonical path (`dashboard/data_sources/local_json.py:66,69`)
is the legacy one. ⇒ **`/api/models/{model}`, its run routes and its
leaderboard — the entire "model runs" half, including both charts — cannot see
a single chain run.** Every recent Gate 2, and everything Steps 10/11/12
exercise, is a chain run. Those are reachable only through
`/api/exploration/...`.

**This reclassifies the dashboard work.** It is not purely "update the data
projection": serving chain runs in the primary half would be a **discovery**
change. That distinction matters because §11 puts a broad rewrite out of
scope.

#### V.13b The bounded delta — three items, and one operator choice

| # | item | classification | cost |
|---|---|---|---|
| 1 | **Direction genericity in the frontend** (F-12e-UX-3): five hardcoded higher-is-better sites plus two contradicting labels | **REQUIRED** — a lower-is-better run is the fourth task's *guaranteed* shape (§16 mandates a `loss`-token primary, direction lower) | small |
| 2 | **The null-series chart** (F-12e-UX-4): `r.results?.model_params` vs the record's top-level `model_params` | **REQUIRED** — a chart that plots nothing is worse than no chart | trivial |
| 3 | **Point the report projection at the normalized source** (§V.13c) | **REQUIRED** | small |
| 4 | **The legacy `agent/`-layout half** | **RULED — Q-12e-2 = (a)** | zero |

**Q-12e-2 — RULED (operator, 2026-08-23): option (a) — leave the legacy
`agent/`-layout half in place, clearly labelled legacy. NOT (b), NOT (c).**

| option | consequence | ruling |
|---|---|---|
| **(a) leave it alone, label it legacy** | zero cost; the primary half stays blind to chain runs, and the exploration half is the only live surface. Honest, and §11-compliant | **RULED — this is 12e's scope** |
| **(b) re-point discovery at the chain layout** | the primary half becomes useful again — but it is a **discovery change**, i.e. real scope, and §11 warns against turning refresh into rewrite | **rejected for 12e — recorded as NAMED POST-STEP-12 DEBT** (§S), not silently dropped |
| **(c) retire the legacy half** | smallest surface, but `run_comparison.py` runs would lose their only view | **rejected — would break an existing consumer for no 12e-required reason** |

**Why (a):** the user-facing graduation claim is served by the **static
report** (§V.5) plus the exploration endpoints; making the legacy half
chain-aware is not required by any 12e claim, and §11 explicitly prefers
"enough modernization to faithfully visualize the current generic workflow"
over a rewrite. Rejecting (b) here is what keeps this from becoming the
"dashboard redevelopment" §11 exists to prevent. **12e's dashboard work is
therefore exactly the four items above table row 1–3 plus this ruling — no
discovery migration.**

Two further defects are recorded and **not** scheduled here, because neither
blocks a 12e claim: `GET /api/models/{model}/runs/baseline` **500s** after any
baseline run that tripped a blocking health gate (baseline records are written
by `run_comparison.py` without schema validation, and a
`"failed_mode_collapse"` status reaches `model_validate`); and the
`"baseline" in exp_id` substring heuristic — whose *need* is real
(`run_comparison.py:574-598` inserts a baseline-shaped row at element 0,
bypassing the sandbox) but whose *mechanism* is a substring test standing in
for a field.

#### V.13c Which file the projection reads — SETTLED BY SOURCE

This was going to be a design choice. Source settles it.

| | `summary_{run}.json` | `run_output_{run}.json` |
|---|---|---|
| shape | **RAW dict**, saved deliberately — *"validation is the gate, not the serializer: `model_dump()` drops extra keys, which would silently lose the §4 watchdog provenance"* (`ml_hyperparameter_tune_agent.py:1577-1579`) | **schema-normalized** — `HyperparamTuningOutput.model_validate(...).model_dump()` (`records.py:1017`) |
| key set | varies by builder; **declared keys are ABSENT, not null** | declared |
| non-finite values | raw | `coerce_nonfinite_to_none` at the storage boundary — with a comment naming *"the dashboard's `JSON.parse`"* as the reason |
| carries run identity | no | **yes** — `metric_spec`, `secondary_metric_specs`, `task_composition_fingerprint`, `health_config_sha256`, `resolved_data_scope` |

⇒ **The projection reads `run_output_{run}.json`.** A normalized,
identity-bearing source **already exists in a file the dashboard already
opens** (`router.py:565`, `:600`) and currently reads only five keys from.
Reading `summary_*.json` instead would force every consumer to cope with
absent-vs-null and with an unstable key set — and would throw away the metric
spec that §V.4's direction rule depends on.

**This is the single most useful thing the dashboard audit produced**: the
"one semantic projection" of §V.5 has an obvious, already-written, already-read
input, so the projection is a *read* of existing normalized state, not a new
persistence layer.

#### V.13d Two source-hygiene notes, precisely bounded

- `ExperimentRecord.file_vector` is declared **twice**
  (`agent/schemas/hyperparam_tuning.py:418` and `:659`). **Runtime impact:
  none** — Pydantic keeps one binding and the second wins. A source defect,
  not a behavioural one; stated precisely so it is not over-read into a
  correctness claim.
- `PersistedHealthGateResult.display_label` is a `@computed_field`
  (`health_checks/schemas.py:607-624`), so a persisted gate result carries one
  more serialized key than the declared field list suggests. A projection must
  not treat the declared list as the on-disk list.

#### V.13e Ownership, restated against what the audit found

The dashboard's **Python** half is already direction-generic (Step-10 P2a
routed its ordering through `MetricOrder`). Its **JavaScript** half is not.
That asymmetry is exactly the §V.5 rule being half-applied — and it is why the
rule is frozen: **the view must not own metric direction.** Item 1 of §V.13b
finishes what P2a started, on the other side of the wire.

### V.14 The three example packs — audit result

#### V.14a Current state, verified per pack

| | TIDMAD | Pets | DAVIS |
|---|---|---|---|
| files | 10 | 24 | 23 |
| top level | `data` `resolved` + 3 `.md` | `data` `declared` `expected` `plugins` + 3 `.md` | same as Pets |
| README | ✅ 57 lines | ✅ 64 lines | ✅ 61 lines |
| README era | **PR0** — *"What this pack demonstrates at PR0"* | **PR0** — *"What this pack contains at PR0"* | **PR0** |
| README's run section | `## Running the task` | `## What the framework can / cannot do with this task today` | same as Pets |
| **executable entrypoint** | **NONE** | **NONE** | **NONE** |
| **data-preparation script** | **NONE** | **NONE** | **NONE** |
| data acquisition mentioned | 0 times | 1 | 1 |

**The READMEs are pack-IDENTITY documents, not quickstarts.** They are honest —
Pets and DAVIS literally document what the framework *cannot* do with them —
but they are PR0-era, and no pack ships a way to run anything.

#### V.14b The missing external-user surfaces — the answer to §V.9b/§V.9d

For all three packs, uniformly:

- [ ] **no `ONE obvious run entrypoint`** — zero `.py` / `.sh` outside
      `plugins/`;
- [ ] **no executable data-preparation path** — nothing named
      generate/prepare/download in any pack;
- [ ] **the README is not a user journey** — it states identity and honest
      maturity, and stops;
- [ ] **no output-inspection story** — §V.12/§V.13 established there is no
      user-facing renderer for a composed run at all.

Everything else a pack needs to be *understood* is present: task statement,
declarations, provenance, identity manifests, plugins. **The gap is precisely
the user-facing half**, which is exactly what this addition owns.

`POST-12d RECONCILIATION REQUIRED`: 12d's D5/D6 add Pets/DAVIS composition
manifests, profiles and task configs and promote STATUS to L4. That closes the
*bindability* half. It does **not** add an entrypoint, a data-prep script or a
README rewrite — those remain 12e's.

#### V.14c Entrypoint strategy — reuse, do not invent

The repository already has the surface: `sdsc_submission_scripts/run_chain.sh`
→ `run_one_iteration.py`, driven by `--task_composition <manifest>`. After
12d's D5/D6 every pack has a manifest. **The example entrypoint is therefore a
THIN adapter that supplies this pack's manifest, its data root and the bounded
knobs of F-12e-UX-2 — nothing more.**

Its file/form stays source-derived (§20). What is frozen is the semantic:
**the command in the README is the command the regression test runs**, and it
reaches the normal composition root. Two repository facts constrain it:

- `README.md`'s published chain example embeds a lab-local `--workspace`
  (F-12e-UX-1) — the example entrypoint must not inherit that;
- the README's current "smoke test" is `pytest tests/unit/` — precisely the
  *"copy a command out of a unit test"* experience §19 forbids.

#### V.14d F-12e-UX-7 — rich rendering is SUPPRESSED for composed runs, by design

**This is the largest finding of the visualization sweep, and it is verified:**

```python
# nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:963-977
if agent_input.task_composition_ref is None:
    reference_scores = load_reference_scores()
else:
    reference_scores = None
    print("Reference scores: NOT LOADED — this run is COMPOSED. The legacy "
          "TIDMAD reference tables are task-specific science and are never "
          "loaded implicitly for a composed run; score-comparison tables are "
          "omitted for this run.")
```

…and `execution.py:1246-1251` gates `build_score_table` on
`reference_scores is not None`.

⇒ **The framework's current answer to "how do we render rich per-result
comparison generically?" is *omit*, not *render generically*.** Pets, DAVIS,
the fourth task **and a composed TIDMAD run** all produce **no score table at
all**. This is C-P56-1 being honoured correctly — the legacy table is TIDMAD
science and must not leak — but it means the composed path has **no rich
rendering to inherit**.

**Two consequences, both favourable:**

1. The generic report projection is **greenfield on the composed path** —
   there is no legacy generic renderer to conflict with or migrate.
2. It is still **class A** (§V.6): the DATA is fully persisted (§V.12a); only
   the *rendering* was suppressed, because the only renderer that existed was
   task science. §V.4's ownership split — generic owns trajectories,
   task-local owns domain presentation — is exactly what unblocks it.

#### V.14e F-12e-UX-8 — why the direction gap survived P2a: a census blind to `.js`

`tests/unit/execute_tools/test_step10_p2a_c0_ordering_scanner.py:383-386`
builds its file set as:

```python
for directory in PRODUCTION_DIRS:
    files += sorted((REPO_ROOT / directory).rglob("*.py"))
```

`dashboard/` **is** in `PRODUCTION_DIRS`; `app.js` **is not a `.py` file**.

**This is the `F-12bc-9` shape verbatim** — *a census whose FILE SET omits
where the code lives* — and it is the mechanical reason Step-10 P2a
genericized the dashboard's Python half while its JavaScript half kept
`Math.max(best, score)`. **The census extension is part of the fix, not an
optional extra**; otherwise the same gap reopens silently.

#### V.14f F-12e-UX-9 — fixing the five JS sites is NOT sufficient

`dashboard/api/models.py:103` sets `model_config = ConfigDict(extra="ignore")`,
and `metric_result` — the direction carrier — appears **zero** times in that
module. **The direction is dropped at the API mirror, before it ever reaches
the browser.** So the §V.13b item-1 delta is two-part and must be stated that
way: *carry direction across the wire, then use it.* A JS-only fix would leave
the frontend guessing from a field it cannot see.

Compounding it: the only two endpoints that ARE direction-aware
(`/models/{model}` overview and `/leaderboard`, which call
`metric_identity_from_record` / `order.is_better`) are **never called by the
UI**; the four `/api/exploration/*` endpoints the UI does use parse with a bare
`json.load` and contain zero direction references.

#### V.14g The POST-12d hazard — 12d ACTIVATES this defect

Today DAVIS cannot be composed, so nobody sees the chart. **After 12d makes it
composable and dashboard-readable, the first thing an external user sees is a
cumulative-best curve that is inverted, new-best markers on the WORST runs, and
a label asserting `Higher is better` — confidently, and silently.** The fourth
task inherits the same hazard by construction, because §16 *mandates* a
`loss`-token primary with direction `lower`.

⇒ **This is why item 1 of §V.13b is REQUIRED rather than nice-to-have**, and
why it is `POST-12d RECONCILIATION REQUIRED` in its own right: 12d closing the
composition gap is what turns a dormant defect into a user-visible one.

#### V.14h Two generic, live surfaces worth building on rather than replacing

- **`scripts/inspect_run_state.py:361 render_table`** — wired into production
  at `sdsc_submission_scripts/run_chain.sh:277`, and **direction-safe by
  delegating** to the tuner's already-selected best rather than re-ranking.
- **the chain console summary** — acquires `MetricOrder` at
  `workflows/model_exploration.py:3104` and **warns rather than guessing** when
  no metric identity reconciles.

Both are small, both are honest about direction, and both demonstrate the
pattern the report projection should follow: **delegate to the authority, or
decline by name.**

#### V.14i A method note worth keeping

The visualization audit **corrected itself twice**, and both errors were the
same shape: it first reported the dashboard as direction-generic *from
`dashboard/README.md` prose without opening `app.js`*, and its "no report
generators exist" sweep used a grep pattern too narrow to see
`render_comparison_table`, `render_table` and `provenance_lines`.

**Both are the census-blindness shape this project has now hit four times**
(F-12bc-6 named a symbol, F-12bc-9 omitted a directory, F-P2b-4 anchored a
regex, and F-12e-UX-8 omitted a file extension). Recorded here because the
same trap is live in this addition's own guards: **a report-projection census
that scans only `.py` will not see the presentation layer it exists to
constrain.**

### V.15 Parallel implementation envelope for this addition (§V.9h)

Folded into §G's DAG as **two further workstreams**. Named **D** and **R**
(not E) — the graduation blocks in §P are already numbered `E1`–`E5`, and
reusing the letter would let an implementer misread "workstream E" as "block
E-something". Both have write sets disjoint from A/B/C:

| | **D — example productization** | **R — report projection + dashboard delta** |
|---|---|---|
| semantic deps | the report contract (§V.12e); 12d's D5/D6 manifests | the report contract |
| read set | pack declarations; the chain launcher's flag surface | `run_output_*.json` schema; `MetricOrder`; the renderer authorities |
| **write set** | `examples/<pack>/` (README, thin entrypoint, data-prep) + `tests/unit/examples/` | the projection module + `dashboard/` + `tests/` |
| shared authority | **the report projection — owned by R, consumed read-only by D** | owns it |
| `READ_ONLY_PARALLEL` | ✅ | ✅ |
| `IMPLEMENTATION_PARALLEL` | ✅ **the three packs are mutually disjoint — TIDMAD, Pets and DAVIS UX can run as three concurrent units** | ✅ vs D, after the contract freezes |
| `VALIDATION_PARALLEL` | ✅ (deterministic + bounded integration only) | ✅ |
| integration point | ⛔ I | ⛔ I |

**The one serialization that matters:** the **report projection contract must
freeze before D and R implement** — it is the shared authority, and §G.3's
rule applies (one owner, one read-only consumer, never two implementations).
This is 12bc's L3 lesson: *freeze the contract first and the rest gets cheap.*

**No additional dependency on the `G-12e` Gate critical path.** D and R sit
beside A/B/C and off the `T → E1 → E2 → ⛔I → G-12e` path, and §V.7
established they need **zero new real runs** because they are validated
against preserved artifacts. **This is not the same as "no cost."** D/R may
still become the PR's wall-clock critical path — the path to `READY FOR
OPERATOR REVIEW` — if their implementation outlasts the graduation stream.
Track both; do not assume the shorter one determines when the PR is done.

**The combined execution DAG (operator-required consistency fix, 2026-08-23):**
before this fix, D/R appeared only inside §V, off the main §G diagram and
absent from §P's implementation-sequence table — an implementer reading §P
top-to-bottom could reasonably conclude the graduation stream finishes
*before* productization starts. It does not. The combined shape, all five
workstreams starting together at T:

```text
                              T
                              │
                    shared contracts (E1)
                              │
       ┌───────────┬──────────┼──────────┬───────────┐
       │           │          │          │           │
       A           B          C          D           R
   ext pkg     census +   restore /   example    report proj
              negatives   provenance  productiz.  + dashboard
       │           │          │          │           │
       └───────────┴──────────┼──────────┴───────────┘
                              │
                   ⛔ INTEGRATION CHECKPOINT
                              │
                          `G-12e`
                              │
                        E-AUDIT → E-FINAL
```

**A and B/C converge at the checkpoint because `G-12e` needs the package
census-clean and negative-control-proven; D and R converge there too, only
because it is the single named integration point — not because `G-12e`
consumes their output.** §P's block table is unchanged as the graduation
stream's own sequencing record; this diagram is the one an implementer should
read first.
