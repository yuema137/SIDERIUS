# Step 10 — Orchestration & run-scoped task binding (parent design)

## 0. Status, provenance and source anchor

**REVISION 2 — FROZEN. OPERATOR APPROVED — PARENT SEMANTICS ONLY.
IMPLEMENTATION IN PROGRESS — 4 of 7 children merged (P1 · P4 · P2a · P2b).**

**P2b (S3) — COMPLETE / MERGED 2026-08-21.** PR #244, squash **`5a2ecfd1`**;
final executable head `f6a73afd` (exact-head CI **32439134908 SUCCESS**), final
PR head `41eeff60` (docs-only provenance sync, its own exact-head CI
**32444963507 SUCCESS** — full suite 11,318 passed / 33 skipped, ruff +
ruff-format + pyright + unit all green); merged master byte-identical to the
validated head. **A task's declared OBSERVATIONAL secondary metrics now travel
the whole lifecycle** — optional manifest `secondary_metrics:` resolved by the
SAME `_compose_metric` authority (no duplicated fail-closed branch) → a
ContextVar bound on `bind_run_task_composition`'s existing ExitStack →
evaluated by the extracted `_evaluate_secondary_metrics` boundary wherever the
PRIMARY evaluates (Q-P2b-1: no round-type branch anywhere) → the three record
carriers the 09a receiving side itself reserved, plus `secondary_metric_specs`
stamped on BOTH the healthy and degraded output branches → projected against
the declared stamp → carried across a quiet iteration → rendered by the 09b
renderer, reused with an EMPTY diff. The frozen exception taxonomy holds with
its ORDER load-bearing (`ScopeViolationError` subclasses `ValueError`, so it is
caught first and RE-RAISED; a crash is diagnostic provenance and never a
fourth scientific state). **Attempt parity deep-equal on nine lifecycle
surfaces** with and without secondaries bound, one of them crashing.
**Three-task closure through the real chain**: TIDMAD writes no secondary
record key at all and renders zero lines (fingerprint byte-identical to its
pre-P2b sha); Pets carries exactly `macro_f1`; DAVIS carries `psnr` (higher)
and `mae` (lower) beside a `lower` `mse` primary, scored and refused/crashed.
Gate 1 and Gate 2 both NOT REQUIRED and neither was run.

**Two findings future work must not lose.** **F-P2b-4** — the Step-09a
evaluator census used ANCHORED symbol regexes and was blind to a leading
underscore, so it would have reported "no production module evaluates a
secondary metric" while `_evaluate_secondary_metrics` did: a guard green for
the wrong reason. Fixed in P2b by stating the predicate once over the whole
name and sharing it with its probe. **The same anchored-census pattern may
exist elsewhere and is recorded as separate test-infrastructure debt — audit
each census when its area is next touched, never as a repo-wide sweep.**
**M11** — a mutation survived P2b's first pass because the carry fixture
hand-built its own cache, leaving the `_stats` WRITE untested; closed by a
healthy-run → produced-cache → quiet-run round-trip.

**P1 (S1 + S7) — COMPLETE / MERGED 2026-08-20.** PR #241, squash
**`bcb17e45`**; final PR head `ffad7029`; exact-head CI **32415952195
SUCCESS**; landed master byte-identical to the validated head. A run is now
handed one explicit, typed, fail-closed `RunTaskComposition` resolved ONCE at
the launcher edge and carried on `WorkflowRunBindings` (24 → 25 fields);
`run_workflow` is 28 → **21** parameters (the nine restored kwargs collapsed
into one `RestoredState`, closing 09.5a's C4b hand-off). The subprocess
transport has its first emitter; the composed semantic fingerprint pins the
run-invariants lock (ABSENT, never null, for legacy runs); `campaign_artifacts`
takes its task semantics as parameters. **Exact un-composed LLM parity PROVEN**
(16 calls, manifest sha256 `476d5d7c…778a` on both sides, zero differences) —
so **Gate 1 and Gate 2 were both NOT REQUIRED and neither was run**. Four
tasks compose through one loader, and an AST census over 307 production files
still finds **zero** task-identity dispatch — class (b) = 0 HELD.

**NEXT = P2a IMPLEMENTATION, in a fresh session.** P2a completed its
post-P1-merge reconciliation the same day and is **REVISION 3 — FROZEN,
operator approved 2026-08-20** (source anchor `bcb17e45`; all discrepancies
class A/B, semantic contradictions 0). The freeze's semantic rulings:
Q-P2a-3 = **PROMOTE** `reconcile_metric_spec` to
`execute_tools/evaluation_metric.py` (one shared reconciliation authority;
bound-spec-vs-artifact-stamp CONFLICT fails closed — a bound spec is an
input, never permission to ignore a stamp); Q-P2a-1 = identity-unavailable
`top_n` falls back to the EXISTING order-free `all` semantics (no new
first-N policy, never labelled top/best); Q-P2a-2 = ONE canonical
identity-unavailable formatter beside the reconciliation authority; plus the
frozen framework-wide metric contract (identity ≠ direction; ranking
requires reconciled IDENTITY, never direction alone) and per-ARTIFACT
unrankable semantics (one missing-identity artifact never poisons a
compatible corpus). Gate 1 and Gate 2 both NOT REQUIRED. Open questions: 0;
adversarial review 25/25.

**POST-STEP-09.5a-MERGE RECONCILIATION — PASS (2026-08-20).
Merged-master anchor `2393aacc`. Semantic contradictions: 0.
REVISION 2 STANDS. → READY FOR OPERATOR REVIEW.** See **§0.3**.

This is a **PARENT** design: mandate, ownership, semantic contracts,
acceptance and PR decomposition. Per-commit implementation plans belong to the
child designs, and **no child design may freeze yet** — see §0.2.

Revision 2 applies the operator review ruling of 2026-08-20 to the reviewed
Revision-1 draft (`3bc76652`). The rev-1 direction was APPROVED; the mandate,
the source audit (§3) and the structural contract are unchanged. What changed:
the child decomposition is **seven**, not six (P2 split into P2a/P2b); five
previously-open questions are RESOLVED by ruling; three boundary statements
were repaired (Step-10↔Step-12 for the task description, the physical data
root as Step-11-owned, `campaign_artifacts` never becoming carried state); two
dispositions that rev 1 deliberately left open — the proposer legacy path and
the runner retirement — are now FROZEN.

### 0.0 Operator rulings — FROZEN 2026-08-20

| id | question | ruling |
|---|---|---|
| **Q-10-1** | PR decomposition | **REVISE — seven children.** Split rev-1's P2 into **P2a** (golden `MetricOrder` closure) and **P2b** (secondary observational transport): different failure classes, independently changing owners. P1 stays ONE child and must **not** be split into composition value / default migration / binding transport, because that would leave an explicit binding that stops at a process boundary, or a mix of explicit and ambient authorities. Rev 1's "splitting P2 would migrate direction twice" argument is **explicitly not load-bearing** — P2a owns the primary ordering migration and P2b must not duplicate it |
| **Q-10-2** | a persisted artifact with no `metric_spec` | **A — refuse to RANK.** Inspectable YES · raw/scalar display YES · ranking or "best" NO · a visible, named *"metric direction unavailable / `metric_spec` absent"* REQUIRED · assumed higher-is-better **FORBIDDEN** · hard-failing the whole consumer **NO** |
| **Q-10-3** | `vocab_link_confirmations` | **A — ACTIVATE.** Producer → committed digest → projection → `ChainState` → next-iteration `InterpretationInput` → the ≥ 3-run promotion condition, genuinely reachable. Its primary reachability owner is a **deterministic lifecycle test with temporal depth ≥ 3**, NOT a 3-iteration real Gate |
| **Q-10-4** | Pets `log_loss` / D16 | **A.** Step 10 transports every metric VALID under the existing Step-06 identity contract and does **not** modify `_is_loss_shaped`. D16 stays an explicitly named **Step-06-owned** future correction; Pets's `log_loss` intent stays documented, not deleted. Pets's Step-10 secondary acceptance is `macro_f1`; DAVIS supplies the mixed-direction discrimination |
| **Q-10-5** | the hand-written Pets/DAVIS runners | **B — retire as alternate production paths** once P6 proves the generic loop covers the same semantic claims. Every retired claim must name its surviving owner first. Small fixtures, data preparation, narrow Health helpers and test utilities may survive **only** with a distinct failure class |
| **Q-10-6** | `accumulated_key_findings` | **A — promote into `ChainState`.** Its union-shaped projection may stay unique; its lifecycle ownership must match the other carried state. Owned by **P5** |

**Open operator questions: 0.**

| field | value |
|---|---|
| roadmap step | §12 "Orchestration binding", roadmap step **10** (`siderius_generic_framework_upgrade.md` §15.1) |
| canonical filename | fixed by roadmap §19: `step_10_orchestration_task_binding.md` |
| drafted | 2026-08-20 |
| drafting source anchor (historical — every `§3` citation was measured here) | branch `step09-5a-workflow-run-state-prerequisite`, head `0ff8b461` (PR #240, **then unmerged**) |
| **reconciled source anchor (CURRENT authority)** | **merged `master` = `2393aacc`** — the PR #240 squash. All `§3` line references were re-measured against it on 2026-08-20; see **§0.3** |
| authority order | operator rulings > current source > frozen Step-09.5 audit > roadmap §15.1/§22.12 > merged Step 01–09 child contracts |

### 0.1 Prerequisite state — recorded truthfully, not aspirationally

**Updated 2026-08-20 after the PR #240 merge.** The "at drafting time" column is
preserved because §3's measurements were taken under it; the "now" column is the
current truth.

| milestone | state at drafting time | **state now (2026-08-20, post-merge)** |
|---|---|---|
| Step 09 (Interpretation) | COMPLETE — MERGED (PRs #238, #239) | unchanged |
| Step 09.5 (structural + test-topology audit) | COMPLETE — **REVISION 2 FROZEN**; verdict *STRUCTURAL PREREQUISITE REQUIRED* | unchanged |
| Step 09.5a (workflow run-state prerequisite) | **IMPLEMENTATION IN PROGRESS** — PR **#240** open; C0/C1/C2/C4 complete, **C3 INCOMPLETE** (§3.0), C5 partially recorded; Gate 1 NOT REQUIRED (waiver closed by proven exact LLM-facing parity); **Gate 2 PENDING**; **merge NOT authorized** | **COMPLETE — MERGED.** Squash **`2393aacc`**; final executable head `52ed46b1`, final PR head `a5e176be`, exact-head CI **32394478272 SUCCESS** (10,837 passed / 32 skipped, pyright 0 errors); merged master byte-identical to the validated head. **C3 is CLOSED** — see §0.3 and §3.0. **Gate 1 NOT REQUIRED** (exact parity re-proven on the final head); **Gate 2 PASS** (3 iterations, zero watchdog kills, the full producer → digest → ONE read authority → projections → next-iteration-consumer chain archived) |
| **Step 10 (this document)** | **NOT STARTED.** Parent design MAY be drafted now; semantic implementation is BLOCKED until Step 09.5a merges | **NOT STARTED.** The 09.5a merge **satisfies the sequencing precondition** of roadmap §15.1b/§15.1c. What now gates child freezes is only §0.2's own reconciliation obligation — **discharged in §0.3** — plus operator review |

### 0.2 What this document may and may not freeze

Frozen Step-09.5 §24 permits parent-level Step-10 reasoning in parallel with
Step 09.5a and **forbids freezing an implementation-owning child design against
the pre-09.5a source topology** — a child design names exact functions,
signatures and line-anchored call paths, and freezing one against
`run_workflow`'s 99-parameter signature would freeze it against a signature
Step 09.5a is replacing. This is the same sequencing error the project avoided
in 07b, where the C7 decomposition became an operator scope amendment *inside*
the PR rather than a design frozen against the pre-refactor shape.

Therefore **Revision 2 freezes**:

* the mandate and the semantic ownership boundaries;
* the genericity invariants;
* the three-task contract matrix;
* the scope → child ownership map (§4.1) and the **seven-child** parent-level
  decomposition with its sequencing;
* structural, functional and preservation acceptance;
* the validation strategy by failure class;
* the six operator rulings of §0.0.

**Revision 2 does NOT freeze**:

* exact child module names;
* exact function or class names;
* source line anchors as future implementation authority;
* child per-commit plans;
* **any implementation-owning child design.**

**Reconciliation obligation (binding, survives the freeze).** No child design
may freeze before Step 09.5a merges. After it merges, the Step-10
touch-surface census in §3 is re-run against merged master and symbol/module
locations are reconciled. Then:

```text
only lines / symbol locations / mechanical call sites moved
    → parent REVISION 2 stays FROZEN; the child design uses current source

a parent-level SEMANTIC boundary or an accepted child ownership no longer holds
    → REOPEN the parent as REVISION 3
```

Stale freeze text is reopened, never defended.

### 0.3 POST-STEP-09.5a-MERGE RECONCILIATION — **PASS. REVISION 2 STANDS.**

**Performed 2026-08-20 against merged master `2393aacc`** (the PR #240 squash),
in a fresh context, from git and source rather than from the conversation that
produced Revision 2. This discharges the §0.2 reconciliation obligation.

| | |
|---|---|
| merged-master anchor | **`2393aacc`** |
| prerequisite | Step 09.5a **MERGED** — PR #240, final PR head `a5e176be`, exact-head CI **32394478272 SUCCESS**, merged master byte-identical to the validated head |
| method | the whole of §3 re-measured claim-by-claim: 4 claim sets, ~70 individual citations, three independent read-only auditors on non-overlapping surfaces + direct verification by the author of every load-bearing or contradicting result |
| **verdict** | **PASS — parent REVISION 2 remains FROZEN and semantically valid** |
| category **C** (parent semantic contradiction) | **0** |
| semantic ownership changes | **0** |
| child decomposition changes | **0** — still seven: P1 · P2a · P2b · P3 · P4 · P5 · P6 |
| scope→child map changes | **0** — S1→P1 · S7→P1 · S2→P2a · S3→P2b · S4→P3 · S6→P4 · S5→P5 · S8→P6 |
| acceptance-criteria changes | **0 semantic**; A gained a reproducible denominator + an AST-shape requirement |

#### 0.3.1 What actually changed in the source

Only **two** files differ between the drafting anchor `0ff8b461` and merged
master in a way §3 cites: `workflows/model_exploration.py` (+150/−52, the C3
closure `52ed46b1`) and `core/runtime_control/adaptive.py` (a diagnostic
message repair, cited nowhere in §3). Everything else §3 names is
byte-unchanged — including
`tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py`, which
holds the direction census.

#### 0.3.2 Discrepancy register — every item, classified

**A = mechanical only** (lines/symbols moved; parent freeze unaffected).
**B = semantic but already consistent** (landed topology helps; ownership unchanged).
**C = parent semantic contradiction** (would force REVISION 3).

| # | § | discrepancy | class |
|---|---|---|---|
| 1 | 3.0 | `WorkflowRunBindings` **now adopted** — 1 production construction (`model_exploration.py:1777`), 50 carrier reads, adoption guard with a caught planted offender, ledger C3 `[x]` | **B** |
| 2 | 2 | `WorkflowRunBindings` is **24** frozen fields (12 class-A + 9 startup-derived + 3 capability refs), not the "12 + 3" rev 2 described | **A** |
| 3 | 3.3 | direction sites 1/2/3 moved `2599-2603`→`2655-2659`, `2610-2615`→`2666-2671`, `2654-2657`→`2714-2718`; all three still raw and unmigrated | **A** |
| 4 | 3.3 | the census holds **4** of the nine code sites, not five; **6 of 11** sites are unseen, not four | **A** (recount; *strengthens* the finding) |
| 5 | 3.1 / 3.8 | `derive_tidmad_metric` has **3** production call sites, not one (`:541` run-scoped + `sandbox_executor.py:2009` legacy shim + `denoising_score_single.py:180` subprocess re-derivation) | **A** (enriches P1's surface; ownership unchanged) |
| 6 | 3.2 | `{TASK_DESCRIPTION}` reaches **6 templates in 3 families**, not "all agent system prompts"; **no `{FORWARD_CONTRACT}` literal exists** — proposer/implementor use `{task_background_block}` / `render_forward_contract()` | **A** (constrains P1's interface; ownership unchanged) |
| 7 | 3.6 | the prediction track record **is** rendered in production — `rendering.py:980`, the interpreter's synthesis prompt. Rev 2's "never called in production at all" is withdrawn; its **direction-agnosticism**, the half the argument rests on, is re-verified | **A** |
| 8 | 3.8 | `bind_task_data_path` has **3** production callers; the third (`train_engine_sandbox.py:1968`) is the **child side**, unreachable because `transport_argv` still has zero emitters | **A** (*strengthens* — P1's emission has a live consumer waiting) |
| 9 | 3.8 | the "461 files / 851 occurrences" denominator is **not reproducible**; replaced by **303 / 750** under the repo's own `_production_files()` definition. Class (b) = 0 **re-confirmed by a stronger AST census** | **A** |
| 10 | 3.4 | TIDMAD does have `examples/tidmad/resolved/metric_spec.json` — a CI-regenerated read-only projection the runtime never reads. "Derived, no *authority* file" is right; "no declaration file" was literally wrong | **A** |
| 11 | 3.7 / 10 | `ChainState` now lives at `core/chain_state.py:46`; `InterpretationInput` construction `1884-1929`→`1934-1978`; `accumulated_key_findings` read `2057-2069`→`2107-2115`; `prediction_memory` closure `2563-2577`→`2619-2633`; `run_pets_gate2.py:154`→`:155`; `evaluation.py` unit dict `125-132`→`124-131`; `ordering.py` plain-dict read at `:294`; `render_secondary_metrics` `298-315`→`298-332`; `task_config.py` cache `43-50`→`43-46` | **A** |

**Nothing in the register is class C.** Every item is a moved line, a corrected
count, or a finding that came out *larger* than rev 2 recorded. Four of them
(#1, #4, #8, #9) make the design's own case stronger rather than weaker.

#### 0.3.3 Facts re-verified UNCHANGED (the load-bearing set)

Every item below was re-measured and holds exactly: the two hand-written
composition edges (`run_pets_gate2.py` 269 lines, `run_davis_gate2.py` 274
lines) and their three bindings each; neither runner touching `run_workflow`,
`restore_prior_state`, the proposer, the interpreter or `ChainState`; **all
six** implicit TIDMAD defaults still implicit and still unreachable by any
operator flag (`--task_health`, `--task_interpretation`, `--task_blocks`,
`--task_id`, `--task_name`, `--task_pack` = **0 hits** across every `*.py` and
`*.sh`); `transport_argv`'s zero production emitters against three parsing
children; all nine direction sites still raw plus both prose sites; the
proposer's **40 + 11** `.get(` reads, its 18-key whitelist, its two dead legacy
reads, `MetricSpec`/`MetricOrder`/`metric_identity` = **0/0/0** across its three
modules, and the `reverse=True` at `proposal_helpers.py:88`; the entire
secondary-metric receiving side plus the `secondary_metrics=[]` hardcode and the
exact four-line cache-carry asymmetry; all three Health per-check-NAME tables
with the `5` vs `25` threshold disagreement intact and none of Pets's or DAVIS's
check names present in any of them; `vocab_link_confirmations` inert at every
one of its six links; `campaign_artifacts` with no schema field, one production
consumer, zero manifest readers and all three task-coupling residues; and
`_is_loss_shaped` unchanged with Pets's `log_loss` still D16-blocked.

#### 0.3.4 Substrate metrics — 09.5a ledger vs merged master

The 09.5a ledger's §37.3 "after" column was measured **before** its own C3
closure landed, so merged master differs. Merged master is authoritative:

| metric | 09.5a ledger §37.3 | **merged master `2393aacc`** |
|---|---:|---:|
| `workflows/model_exploration.py` LOC | 2,891 | **2,950** |
| `run_workflow` lines | 1,316 | **1,375** |
| **`run_workflow` parameters** | **28** | **28** ✓ |
| `core/resume.py` LOC | 1,506 | **1,505** |
| **committed-digest I/O authorities** | **1** | **1** ✓ (`core/committed_digests.py`, 159 LOC, one production caller: `core/resume.py:1353`) |
| `ChainState` fields | 11 | **11** ✓ (`core/chain_state.py:46`) |
| `WorkflowLaunchConfig` fields | 72 | **72** ✓ (4 production construction sites) |
| `WorkflowRunBindings` fields | 24 | **24** ✓ (**1** production construction) |

The two Class-A counts that were the *point* of Step 09.5a — **28 parameters**
and **1 digest reader** — are both confirmed at merged master. The LOC
increases come from the C3 closure adding the carrier construction and its
50 attributed reads, and were never acceptance criteria.

*(Branch-node counts are omitted deliberately: they are not comparable across
counting conventions. Measured here with `If/For/While/Try/ExceptHandler/With/
BoolOp/IfExp` = 117, +`comprehension` = 127, bare `If` = 56 — all far under the
pyright ceiling of 258 that motivated the responsibility rule.)*

#### 0.3.5 Consequence

**No parent-level semantic boundary, genericity invariant, child ownership,
acceptance criterion or Step-11/Step-12 boundary was contradicted.** Revision 2
stays **FROZEN**; §3's source truth, counts and locations are updated in place
above, each correction marked. The next gate is **operator review of this
parent**, then the detailed **P1** child design against merged master.

---

## 1. Mandate — what Step 10 owns, and why it exists

### 1.1 The problem in one paragraph

Steps 01–09 turned nine task-semantic concerns into declared, typed contracts:
dataset topology, model/loss contract, candidate creation, tuner data
selection, resource pricing, execution contracts, the metric interface, tuner
policy and training diagnostics, Health families, and interpretation blocks.
Every one of those contracts is **generic at its own seam**. What no step has
yet owned is the seam *above* them: **who binds a task's semantics for a run,
and how the orchestration loop receives them.** Today that answer is a mix of
launcher defaults, module-level pulls, a per-task Gate script per contrast
task, and — in the last three surfaces of the chain loop — a raw `>` that
silently means *higher is better*. Step 10 is the milestone that makes the
answer *one* answer.

### 1.2 The mandate

> **Task and run semantics are bound ONCE at the composition / launcher edge,
> and the generic workflow consumes them as typed values. The workflow, the
> resume path, and the chain-level nodes never rediscover task identity,
> metric direction, task data semantics, Health semantics or interpretation
> semantics for themselves.**

Concretely, Step 10 converts orchestration from *"the loop knows what TIDMAD
is"* into *"the loop is handed what this run is"*.

### 1.3 Roadmap-assigned final effect (quoted, then re-audited)

Roadmap §15.1's Step-10 row states the final effect as:

> Task binding lives at the launcher; §12's OWN surfaces (workflow binding,
> `campaign_artifacts`, orchestration inputs to resume) carry zero TIDMAD
> residue — §9's core-infra residue (sandbox dirs/globs, runtime-control
> fallbacks) clears at step 11.

and §22.12 adds *"workflow/resume best-score comparisons consume the metric
handle (D1 CORE consumers outside the tuner)"* plus *"a second bound task
initializes the loop"*. The inherited semantic debt the roadmap lists as due
here: production secondary-metric transport (Q-09-7 = B), `evaluation.py`
per-check-NAME tables, resume/dashboard direction literals,
`vocab_link_confirmations` carry, and the proposer prediction-authoring
grammar.

**The Step-09.5 audit is an INPUT, not the scope.** §3 of this document
re-audits current source and records where the inherited list was confirmed,
where it was found larger than recorded, and where an item turned out to be a
different problem than its label suggests.

### 1.4 Semantic owner

**Step 10's semantic owner is: run-scoped task composition and the
orchestration-level consumption of already-declared task semantics.**

It is *not* the owner of any of those semantics. It does not decide what a
metric means (Step 06), what a Health check measures (Step 08), what
interpretation says (Step 09), or how a dataset is read (Step 02 / D14). It
decides **who supplies them for this run, and how they travel.**

### 1.5 Why this cannot be deferred

Three independent forces make Step 10 the next milestone rather than a
cleanup:

1. **The contrast tasks currently bypass the chain.** Pets and DAVIS execute
   through dedicated Gate runner scripts, not through the exploration loop.
   Every genericity claim made about the loop is therefore, today, a
   TIDMAD-only claim.
2. **Two declared features are inert.** `vocab_link_confirmations` and
   secondary-metric transport are schema-present and production-dead; each
   iteration pays for machinery no consumer can reach. A fake live contract
   gets more expensive the longer it stands.
3. **Step 11 and Step 12 both consume Step-10 interfaces.** Step 11 makes
   spawn/IPC/limits task-free; Step 12 graduates a task package out of tree.
   Neither can be specified against a launcher that binds TIDMAD implicitly.

---

## 2. Binding upstream contracts (recovered, not redesigned)

**Rule for the whole of Step 10: do not design a parallel replacement for an
existing contract.** Every row below is a contract Step 10 *consumes*. Where
Step 10 changes anything in a row, the change is named explicitly in the last
column; a blank means the contract is used exactly as it stands.

| contract | owner step | what it already guarantees | Step-10 relationship |
|---|---|---|---|
| **`TaskDataPath`** | D14 | Protocol + typed request values + fail-closed registry keyed on binding PRESENCE (never task name) + run-scoped binding + explicit subprocess transport | **the precedent to converge toward** (§6.2); not modified, not duplicated |
| **`DatasetProfile` / `SampleSet`** | 02 | dataset topology, geometry, selection, groups, input identity resolve from the run profile | consumed; Step 10 does not touch selection semantics |
| **`ModelIOContract`** | 03 | classes, dtype, output forms declared per task | consumed |
| **`DeliverableSpec`** | 05c | naming, cleanup matching, channel-group identity, persisted storage representation | consumed |
| **`EvaluationMetric` + `ScoreabilityContract`** | 06 | metrics are named instances behind one handle; scoreability is checked BEFORE arithmetic; refusal is structured (`NotScoreableResult`) | consumed; Step 10 adds *secondary* instances beside the primary, never a second handle |
| **`MetricSpec` / `MetricOrder`** | 06 / 07b | `MetricSpec.direction` is the ONE declaration (`MetricDirection = Literal["higher","lower"]`, `evaluation_metric.py:111`); `MetricOrder` is the ONE interpreter of it (`execute_tools/metric_order.py:59`) with `is_better` / `is_at_least` / `best` / `worst` / `rank` / `worst_sentinel` / `best_sentinel` / `toward_better` / `toward_worse` / `direction_words` | **consumed and extended to the last unmigrated consumers.** No new direction enum, helper, boolean or comparator may be introduced (§8) |
| **`TrainingObjective` / `TrainingHistory` / `TrainingDiagnosis`** | 07a | typed training evidence, persisted, hidden from planner + reflector | consumed |
| **Health** (`health_policy` + task health config + view capabilities) | 08a/b/c | typed `CheckVerdict`; checks declare their inputs; roster/thresholds/prose are task-owned; external plugins register through the public API; three binding states (`LEGACY_OMITTED` / `EXPLICIT_NONE` / explicit path) | consumed; Step 10 owns only the **residual central name tables** (§13) |
| **`InterpretationTaskBlocks`** | 09b | four framework keys, task-owned prose, absent ⇒ nothing rendered; caller-supplied value on `InterpretationInput.task_blocks` | consumed; Step 10 owns **who the caller is** |
| **`SecondaryMetricEvidence`** | 09a | frozen carrier: `spec` (its OWN direction) + exclusive `result` / `refusal`, `status ∈ {scored, refused, unavailable}`; observational, never ordering | **activated** by Step 10 (§9); the carrier itself is not redesigned |
| **Prediction semantics v1/v2** | 09a | `metric_order_signsafe_v2`; v1 pool frozen and carried; accuracy v2-only and labelled; `unevaluated` in no pool | consumed; Step 10 owns the proposer-side **authoring** grammar only (§11) |
| **`WorkflowRunBindings` / `WorkflowLaunchConfig` / `ChainState` / committed-digest authority** | 09.5a | typed run-scoped authorities; a transit-config boundary; one writable authority per carried value; ONE digest read/parse path. **Measured at merged master `2393aacc`**: `WorkflowRunBindings` (`workflows/run_bindings.py`) frozen, **24** fields, **1** production construction (`model_exploration.py:1777`), 50 carrier reads · `WorkflowLaunchConfig` (`workflows/run_config.py`) frozen, **72** fields · `ChainState` (`core/chain_state.py:46`) mutable, **11** fields · `core/committed_digests.py` (159 LOC) the **ONE** read/parse authority feeding four pure `project_*` functions in `core/resume.py` | **the structural substrate** (§10). Step 10 adds values to existing carriers; it does not add a carrier |

**Two contracts Step 10 explicitly does NOT get to reinterpret**, because a
frozen document already answers them:

* `RestoredState` crosses the launcher boundary; `ChainState` **never crosses a
  subprocess boundary** (09.5a §16). A Step-10 value that must reach a
  subprocess travels by the same explicit transport `TaskDataPath` uses — not
  by widening `ChainState`.
* Secondaries are **observational** (Q-09-7 = B). Step 10 activates their
  transport; it does not grant them a vote.

---

## 3. Current source reality — re-audited at `0ff8b461`

This section is the **evidence base**. Every claim is a source citation, and
every claim that revises the inherited debt list says so explicitly. §20's
decomposition is derived from this section, not from the audit's labels.

### 3.0 A prerequisite finding — surfaced by THIS audit, owned by Step 09.5a — **NOW CLOSED**

> **STATUS: CLOSED at merged master `2393aacc`** (re-verified 2026-08-20, §0.3).
> The finding below is preserved as the historical record of what this audit
> found and why it was reported rather than absorbed. **The reader should not
> act on its present tense.** What is true now:
>
> | | at `0ff8b461` (below) | at merged master `2393aacc` |
> |---|---|---|
> | production `WorkflowRunBindings(` sites | **0** | **1** — `workflows/model_exploration.py:1777`, constructed ONCE after the startup side-effects that derive the invariants, hardware context and resolved scope |
> | carrier reads | none | **50** `bindings.<field>` occurrences over **17** distinct fields; no bare local read of a carrier-owned authority survives after construction |
> | `WorkflowRunBindings` shape | 12 authorities + 3 capability refs described | **24 frozen fields** = 12 class-A + **9 startup-derived** + 3 audited capability refs |
> | guard | none | `TestRunBindingsProductionAdoption` (`tests/unit/workflows/test_step09_5a_c5_structural_censuses.py`) — asserts a production construction exists *at all*, that it is constructed exactly once, and that 12 named authorities are never read as bare locals afterwards. **Planted offender CAUGHT.** |
> | 09.5a ledger C3 row | unchecked | **`[x]`** |
>
> Step 09.5a closed this in commit `52ed46b1` ("C3 closure: `WorkflowRunBindings`
> becomes a REAL production boundary") with the C0 differential oracle still
> deep-equal — the strongest available evidence that the closure is
> behaviour-preserving. **Consequence for Step 10: none of §6, §10, §20 or the
> child ownership map changes.** The substrate P1 was designed to build on now
> genuinely exists, so the risk this finding named (R8) is discharged rather
> than carried. The reporting route worked exactly as §0.2 intended: a Step-10
> audit found a prerequisite gap, the prerequisite fixed it, and Step 10
> absorbed no scope.

Auditing the Step-09.5a substrate for §10 turned up a gap in Step 09.5a itself,
and it is recorded here because a Step-10 design that assumes the carrier is
adopted would be building on something that is not there.

**`WorkflowRunBindings` is defined, ownership-guarded and unit-tested, and has
ZERO production construction sites.** A repository grep for
`WorkflowRunBindings(` outside `tests/` returns nothing; the only constructor
call in the tree is `tests/unit/workflows/test_step09_5a_c2_carriers.py:76`.
`run_workflow` still declares the 12 run-scoped authorities, the 3 capability
references and the 9 restored chain-state seeds as **individual parameters**
(28 total, verified against the live signature). The 99 → 28 reduction is
therefore entirely `WorkflowLaunchConfig`'s 72 transit fields plus `ChainState`
— both of which **are** adopted (`ChainState.from_restored` at
`workflows/model_exploration.py:1765`; `WorkflowLaunchConfig` at `:1375`,
`:1495`, `:2868` and in the launcher).

That is a deviation from Step 09.5a's own frozen text: its §13 says
*"`WorkflowRunBindings` is **constructed inside `run_workflow`** from the
class-A inputs"*, and its C3 scope line reads *"Bindings constructed at
startup"*. The design ledger's **C3 row is still unchecked**, which is
consistent.

**Consequences, stated plainly:**

* **This is Step 09.5a's to close, not Step 10's.** Step 10 must not
  "adopt the carrier in passing" — that would move a prerequisite's scope into
  the milestone the prerequisite exists to protect. *(This is what happened:
  09.5a closed it in `52ed46b1`; Step 10 absorbed nothing.)*
* **Step-10 child designs must not freeze against the current signature** —
  already forbidden by §0.2, and this is the concrete reason why.
* Everything §6 and §10 of this document say about *where a Step-10 binding
  lands* remains correct, because it rests on the carrier's **contract** (which
  is frozen, guarded and tested), not on its current adoption.

### 3.1 The composition edge already exists — three times, written by hand

This is the single most important finding, and it reframes Step 10 from
*"invent a binding mechanism"* to *"make the mechanism that already works a
production interface"*.

| task | who composes the run | how the metric is bound | how the data path is bound | how Health is bound |
|---|---|---|---|---|
| **TIDMAD** | the production chain (`run_workflow` → tuner) | `derive_tidmad_metric(run_profile, run_deliverable_spec)` at `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:541` — the one **run-scoped Regime-A** derivation (see the correction below: there are **three** production call sites in total) | `TaskDataPath` registry, default binding | omitted binding ⇒ `LEGACY_OMITTED` ⇒ TIDMAD task health config |
| **Oxford-IIIT Pet** | `scripts/run_pets_gate2.py` (269 lines) | `metric_spec_from_declaration(json.loads(declared/metric_accuracy.json))` → `AccuracyMetric(spec)` (`:229-234`) | `with bind_task_data_path(impl):` (`:144`) | `run_health_stage(..., task_health_binding=PACK_ROOT/"declared"/"task_health.yaml")` (`:248-253`) — state C, explicit |
| **DAVIS** | `scripts/run_davis_gate2.py` (274 lines) | same shape, `declared/metric_mse.json` (`:226`) | same | same |

Read the right-hand three columns as one row and the Step-10 interface is
already visible: **a run needs an explicit, typed binding per semantic family,
and a task supplies each one by declaration.** The two contrast runners prove
the shape works on real data; what they are missing is (a) a production home,
(b) the exploration loop, and (c) a single place to state the whole set.

Two residues in those runners are diagnostic rather than incidental:

* `scripts/run_pets_gate2.py:155` passes `sample_set={}` with the comment
  *"legacy TIDMAD argument; the seam path ignores it"* — a generic execution
  entrypoint still carrying a TIDMAD-shaped parameter.
* Neither runner touches `run_workflow`, `restore_prior_state`, the proposer,
  the interpreter or `ChainState`. **Every genericity claim about the
  orchestration loop is, today, a TIDMAD-only claim** — §1.5 item 1, now
  measured. *(Re-verified at merged master: a combined grep of both scripts for
  `run_workflow|restore_prior_state|ChainState|proposal_agent|result_interpretation`
  returns zero matches.)*

**Correction, post-merge 2026-08-20 — `derive_tidmad_metric` has THREE
production call sites, not one.** Rev 2 called `:541` "the **one** Regime-A
derivation site". Measured on merged master:

| # | site | what it is |
|---|---|---|
| 1 | `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:541` | the **run-scoped Regime-A binding** — unconditional (AST: zero enclosing control nodes) |
| 2 | `core/sandbox_executor.py:2009` | `metric if metric is not None else derive_tidmad_metric(resolve_dataset_profile())` — a **legacy-caller compatibility shim** |
| 3 | `execute_tools/denoising_score_single.py:180` | the **scoring subprocess** re-deriving the same instance from `--dataset_profile_json`, exactly as the Step-06 contract specifies |

The repository's own census
(`tests/unit/agent/result_interpretation_agent/test_step09a_c2_metric_spec_contract.py:437-443`)
pins **four** production modules, and has always done so; rev 2's sentence was
simply too narrow. **What survives unchanged**: `:541` is the one place a *run*
chooses its metric, which is what S1/P1 owns. **What P1 gains**: two further
sites it must account for rather than discover — site 2 is a fallback P1 must
either bind or fail closed on, and site 3 is a **subprocess** re-derivation,
i.e. the same "binding must cross the process boundary" problem §20.5 uses to
argue P1 does not split. Ownership is unchanged; P1's known surface is more
complete.

### 3.2 The task's own description reaches every LLM node through a module-level cached global

`workflows/task_config.py` loads `configs/task_config.yaml` (default path
constant at `:41`) and caches the parsed result in a **module-level cache**
(`_CACHE` at `:46`, comment `:43-45`). `configs/task_config.yaml` calls itself *"Single source of truth
for task-level configuration"* and carries exactly two top-level run-defining
values: `task_description` (`:10`) and `forward_contract` (`:20`).

**Measured consumer surface (post-merge correction, 2026-08-20).** Rev 2
repeated the YAML's own comment — *"all agent system prompts"* and
`{FORWARD_CONTRACT}` — and both are inaccurate. Measured:

| value | how it actually reaches prompts |
|---|---|
| `task_description` | the literal `{TASK_DESCRIPTION}` placeholder appears in **six templates across three families**: the planner (`agent/prompts.py:66`, substituted `agent/llm_bridge.py:1001`), the interpreter (`rendering.py:48` `PER_MODEL_SYSTEM_PROMPT` subst `:144`, and `:664` `SYNTHESIS_SYSTEM_PROMPT` subst `:754`), and literature review (`paper_extract_system.md:12`, `search_decision_system.md:12`, `synthesis_system.md:9`). It is **not** in the reflector prompt, and **not** in the proposer/implementor — those receive it through `{task_background_block}`, filled by `_render_task_background()` (`ml_model_proposal_agent.py:477`, `ml_model_implementor.py:1107`) |
| `forward_contract` | **no `{FORWARD_CONTRACT}` literal exists in any production template.** The lowercase `{forward_contract}` appears once (`agent/prompt_templates/proposal/proposing_stage.md:131`, filled `ml_model_proposal_agent.py:1772`); otherwise the block is composed by `render_forward_contract()` (`ml_model_proposal_agent.py:424`, `ml_model_implementor.py:1035`, `:1151`). The consumer set — proposer + implementor — is as rev 2 stated |

**Why this matters to P1 rather than being pedantry**: the binding P1 must
supply is consumed through **two different mechanisms** (a direct placeholder
substitution and a rendered block), across **four** node families, not one
uniform `{TASK_DESCRIPTION}` substitution. A P1 design that assumes a single
placeholder would migrate the planner and interpreter and silently leave the
proposer and implementor on the module global. Ownership is unchanged; the
interface is more constrained than rev 2 described.

This is a **single-task authority by construction**: one process serves one
task, chosen by a default path, cached globally, with no run-scoped binding.
Both contrast packs record it as such — `examples/*/STATUS.md` lists
*"pack-level runtime task binding | single-task authority
`configs/task_config.yaml` | not representable | **Step 12**"*.

**Boundary consequence, stated precisely** (operator ruling §10, 2026-08-20 —
this corrects a looser rev-1 reading of the packs' own "→ Step 12" note):

* **Step 10 makes `task_description` and `forward_contract` explicit generic
  RUN BINDINGS**, supplied at the composition edge like every other Step-10
  binding. A composed Step-10 run must **not** depend on the module-global
  singleton as its *semantic authority*.
* The singleton may survive as a **legacy compatibility adapter** until
  Step 12 — a way to obtain the value, never the authority for it.
* **Step 12 owns the SOURCE of the whole binding set**: one out-of-tree task
  package supplying every Step-10 binding through a unified composition root.

The packs' *"not representable → Step 12"* rows describe **pack-level**
declaration, which is genuinely Step 12's. They do **not** license Step 10 to
leave the run's task identity resolved from a cached module global. The
freeze-time test of §24 applies: Step 12 must be able to supply this exact
interface's value from an external package **without changing the interface**.

### 3.3 Metric direction — the remaining raw-comparison sites, and the guard that half-sees them

`MetricSpec.direction` (`execute_tools/evaluation_metric.py:368-370`, vocabulary
`MetricDirection = Literal["higher","lower"]` at `:111`) is the one declaration;
`MetricOrder` (`execute_tools/metric_order.py:59`) is the one interpreter, and
it already exposes everything Step 10 needs — `is_better`, `is_at_least`,
`best`, `worst`, `rank`, `worst_sentinel`, `best_sentinel`, `toward_better`,
`toward_worse`, `direction_words`, `comparison_symbol`. The tuner (5 of its 10
modules, 31 references in `policy.py` alone) and the interpreter (all 21 sites,
Step 09a) are migrated.

**Nine unmigrated production sites remain, and they are direction-sensitive on
the golden metric:**

| # | site | what it decides |
|---|---|---|
| 1 | `workflows/model_exploration.py:2655-2659` (the `>` at `:2657`) | raw-formal progress tracker → `state.best_score_overall` |
| 2 | `workflows/model_exploration.py:2666-2671` (the `>` at `:2669`) | **chain formal incumbent advance** (`chain_formal_incumbent_reference`) |
| 3 | `workflows/model_exploration.py:2714-2718` (the `>=` at `:2717`) | early-stop `target_score` check |
| 4 | `core/resume.py:441-455` (`_pick_best`) | within-iteration incumbent selection on resume |
| 5 | `execute_tools/per_file_best.py:481-483` (`_row_beats`) | per-file best-row selection, linear space |
| 6 | `dashboard/data_sources/local_json.py:245` | top-N ranking (`reverse=True`) |
| 7 | `dashboard/data_sources/local_json.py:195-197` | `best_agent_score` / `best_run_name` |
| 8 | `scripts/build_diagnostic_summary.py:113` | diagnostic-summary best round (`max(...)`) |
| 9 | `scripts/finalize_recovered_diagnostic_round.py:233` | OOM-recovery finalizer best round |

Plus two prose sites that *state* a direction: `dashboard/data_sources/base.py:119`
and `dashboard/api/router.py:233-234` (*"ranked by denoising_score descending
(higher is better)"*).

**Revision to the inherited list — this is larger than recorded.** The
Step-09.5 audit's touch map lists *three* literal sites and calls the row
**SAFE TO EXTEND**. The repository's own executable census
(`tests/unit/execute_tools/test_step06_c5_boundary_and_structure.py:160-178`,
`NOT_REACHED_DIRECTION_CONSUMERS`) holds **5 entries** — **four** of the nine
code sites (1, 4, 5, 6) plus one prose site (`base.py`).
**Sites 2, 3, 7, 8, 9 and the `router.py` prose are in neither** — six of the
eleven. Site 2 is the highest-consequence of them all: it advances the chain's
formal incumbent, and it sits ten lines below a site the census does track.

*(Post-merge correction, 2026-08-20: rev 2 said the census listed "five of the
nine plus one prose site" and named three missing code sites. Re-measured, the
census names **four** code sites and **five** are missing. The gap this finding
exists to name is LARGER than rev 2 recorded, not smaller — the argument is
strengthened, and the S2/P2a ownership is unchanged. The census file itself is
byte-identical between `0ff8b461` and merged master; only the recount changed.)*

That gap is itself a Step-10 finding: *the census that is supposed to hold this
debt still cannot see all of it.* Step 10 must replace the presence-list
mechanism with a scanner that finds the shape (09a-C3's AST scanner is the
existing stronger instrument; audit item **TB-4**), or it will migrate exactly
the sites someone once remembered to list.

**Explicitly NOT in scope, and pinned as such** (verified direction-insensitive):
`policy.py:557`'s `min(same_loss_finals)` — a training loss, deliberately not
routed; runtime/memory/timing extrema throughout `core/runtime_control/`;
`iter_idx` / `round_index` / `exp_id` tie-breaks; `abs(delta) >= threshold`
change-magnitude filters; and `scoring_helpers.py:458-460`'s within-metric
impact ranking.

### 3.4 Secondary metrics — declared by two tasks, evaluated by nobody, and asymmetric on carry

The receiving side is complete and frozen (Step 09a): `SecondaryMetricEvidence`
(`agent/schemas/interpretation.py:114`) carries `spec` — *its own* direction —
plus mutually exclusive `result` / `refusal`, with
`status ∈ {scored, refused, unavailable}`; `ModelRunSummary.secondary_metrics`
(`:561-571`) and `InterpretationOutput.per_model_secondary_metrics`
(`:1272-1278`) transport it; `render_secondary_metrics`
(`agent/prompt_templates/interpretation/rendering.py:298-332`, sole caller `:539`)
renders it.

The producing side is deliberately empty: `nodes/result_interpretation_agent/evidence.py:486`
hardcodes `secondary_metrics=[]` with the reason stated in the code — no
record-level carrier exists, *"reading undeclared keys off a record would be a
hidden contract, and inventing values would be worse."*

**What the tasks already declare** (and note that nothing in a pack marks which
metric is primary — the *consumer* names the filename):

| task | primary | declared secondaries | evaluated today |
|---|---|---|---|
| TIDMAD | `tidmad_denoising_score` **higher** (derived at runtime; no `declared/` directory and no authority file — `examples/tidmad/resolved/metric_spec.json` exists but is a CI-regenerated read-only PROJECTION the runtime never reads) | none | — |
| Pets | `accuracy` **higher** (`declared/metric_accuracy.json`) | `macro_f1` **higher** | no |
| DAVIS | `mse` **lower** (`declared/metric_mse.json`) | `psnr` **higher**, `mae` **lower** | no |

DAVIS is the case the carrier's *"its OWN direction"* wording exists for: a
`lower` primary with a `higher` secondary already sits in one pack.

**The cache-carry asymmetry — confirmed, and located to twenty lines.**
`nodes/result_interpretation_agent/result_interpretation_agent.py:345-365`:
`per_model_failure_counts` is built from `inp.summaries` **and then back-filled
from the per-model `_stats` cache** (`:353-358`), because `failure_counts` is
written into `_stats` at `:526-530`. `per_model_secondary_metrics` (`:361-365`)
has **neither half** — no `_stats` key, no cache fallback. The moment Step 10
populates secondaries, a model that goes quiet for one iteration (the
Stability-Filter reuse path at `:455-470`, which makes no LLM call) keeps its
failure counts and its golden score and silently loses its secondaries.
**Step 10 must close this in the same change that activates the transport** —
audit finding **B-6**.

One more precedent to match, found in passing: the golden score is already
carried in **two** shapes — `best_denoising_score` in `_stats` for cache
ranking (`nodes/interpretation_helpers.py:760`, `:783`) and `best_score_table`
re-read as a plain dict (`nodes/result_interpretation_agent/ordering.py:294`, inside
the cache loop `:290-293`).
A secondary carrier has two precedents, not one, and must not become a third.

**A declaration Step 10 cannot currently transport.** Pets's third intended
secondary, `log_loss`, **cannot be declared at all**: `_is_loss_shaped`
(`execute_tools/evaluation_metric.py:116-129`) refuses any identifier whose
tokens include `loss`, and `examples/oxford_iiit_pet/STATUS.md` records the
refusal as intentional and assigns the resolution to **D16**. This is an open
**RULED — Q-10-4 = A** (§0.0): Step 10 transports every metric valid under the
existing Step-06 identity contract, does **not** modify `_is_loss_shaped`, and
carries D16 forward as a named Step-06-owned correction. The intent is not
deleted to make Step 10 look complete.

### 3.5 Health — the residual central name tables, and why they are the *last* Health item

Step 08 finished the Health *ownership* migration: rosters, thresholds,
`peek_samples`, value scale and prose are task-owned
(`configs/task_health/<task>.yaml` or a pack's `declared/task_health.yaml`),
`configs/health_checks.yaml` is framework policy only, external plugins
register checks **and** view providers through the public API, and each check
declares its inputs as data — `CheckInputDeclaration`
(`execute_tools/health_checks/schemas.py:880`) with, among others,
`threshold_parameter_names` (`:927`), which every shipped check already
populates (`output_diversity.py:64` → `("min_unique_int8_values",)`,
`sample_dispersion_floor.py:65` → `("min_dispersion",)`,
`categorical_distinct_symbols.py:51` → `("min_distinct_symbols",)`, and `()`
for recording-only checks).

**What did not migrate: `execute_tools/health_checks/evaluation.py`, which
still holds three tables keyed on TIDMAD's check NAMES.**

| table | site | shape |
|---|---|---|
| threshold rendering | `evaluation.py:84-107` (`_threshold`) | `if check_name == "output_diversity": … elif "output_std" … elif "amplitude_collapse" …` — each branch also hardcodes the config KEY, the comparison OPERATOR, the UNIT, and a DEFAULT VALUE (`5`, `1.0`, `0.95`) |
| per-file metric naming | `evaluation.py:117-124` | dict of six check names → metric names |
| per-file unit | `evaluation.py:124-131` | dict of six check names → units |

**The failure mode is silence, not a crash.** A task-owned check whose name is
absent — Pets's `categorical_distinct_symbols`, DAVIS's
`sample_dispersion_floor` under its own gate id — falls through every table to
`None`: no threshold is recorded in the persisted evidence, no per-file metric
name, no unit. The gate still fires and still blocks correctly; its *evidence*
is quietly poorer than TIDMAD's. That is exactly the class of defect that
survives a test suite.

**A second, smaller finding:** those default values (`5`, `1.0`, `0.95`) are a
**second declaration** of constants Step 08b moved into task config. Two
declarations of one threshold is the duplicate-authority shape, even when both
currently agree.

**The migration is declaration-driven and it is genuinely small.** The check's
own declaration already names its threshold parameters; what the tables add
beyond that is the operator symbol, the unit and the rendered metric name.
Those belong on the check (which knows them) rather than in a central table
(which must be edited per task). Note the boundary this crosses, and state it
plainly rather than hiding it: **extending `CheckInputDeclaration`'s shape once
is framework work and is allowed** (§7's distinction — a new *capability* may
need framework work; a new *task instance* may not). What must be true
afterwards is that adding a task-specific check requires editing **no** central
table.

### 3.6 The proposer — no typed reader at all, and one live direction defect

**There is no typed proposer-side reader to consolidate; there are two untyped
ones.** `ProposalInput.interpretation` is a **raw `dict[str, Any]`**
(`agent/schemas/proposal.py:650`), filled by the protocol with
`output.model_dump()`
(`agent/schemas/protocols/ml_result_interp_to_ml_model_propose.py:172`). The
proposer performs **40** `.get(` reads against that dict in its node module and
**11** more in `nodes/proposal_helpers.py`.

| | LEGACY reader | PIPELINE reader |
|---|---|---|
| entry | `_build_reasoning_prompt(inp)` `ml_model_proposal_agent.py:1086-1309` | `_run_pipeline(inp)` `:1575-2240` |
| shape | flat markdown prompt | an 18-key **whitelist projection** into `accumulated["interpretation_summary"]` (`:1669-1699`) + 5 direct reads (`:1620-1626`) |
| dispatch | `:1471-1477` — `_run_pipeline(inp) if has_pipeline else _run_legacy(inp)` | |

**Production uses PIPELINE.** All three shipped tiered LLM configs and the
`--provider/--model_id` fallback build a `ProposalLLMConfig`, which makes
`workflows/model_exploration.py:207` return a real `ReasoningPipelineConfig`.
Legacy is reachable only via `llm_config=None` and the node's standalone CLI.
This branch's own C5c parity capture ran in pipeline mode, independently
confirming it.

**Measured drift between the two readers** — LEGACY-only:
`best_valid_denoising_score`, `best_config`, `per_file_comparison`,
`efficiency_comparison`; PIPELINE-only: `model_knowledge_cache`,
`prediction_pool_sizes`, `prediction_evaluation_semantics`. Two of the
legacy-only reads are **dead** — `InterpretationOutput` has no
`per_file_comparison` and no `efficiency_comparison` field, yet `:1180` and
`:1184` branch on them. The source itself records **two drift incidents found
by a live Gate rather than by review** (`:1257-1263` and its mirror at
`:1741-1746`).

**A correction to the inherited label.** The audit calls this *"direction-blind
proposer comparison"* and points at the prediction track record. Measured, the
track record is **not** the offender: `render_prediction_track_record`
(`agent/prompt_templates/interpretation/rendering.py:335-418`) takes no spec,
makes no comparison, and counts its own denominator over
`COMPARABLE_OUTCOMES` of the same pool it reports — it is direction-*agnostic*
by construction, and Q-09a-3's v1/v2 pairing defect is already closed there.
**Correction, post-merge 2026-08-20**: rev 2 added *"it is also called only
from the legacy path (`:1157-1163`), so production never renders it at all"*.
The first half is true **within the proposer**; the second half is **FALSE
repo-wide**. There are **two** production call sites:
`nodes/ml_model_proposal_agent/ml_model_proposal_agent.py:1157` (the legacy
proposer path, genuinely unreached in production) **and**
`agent/prompt_templates/interpretation/rendering.py:980`, inside the
interpreter's own `_build_synthesis_prompt` (`:761-989`) — which production
*does* render every iteration. Step 09b's "version-aware in BOTH consumer
nodes" is exactly this pair.

**Nothing in the design moves.** The load-bearing half of the claim was that
the track record is direction-**agnostic** — re-verified: its five keyword-only
parameters include no spec, and scanning `:335-418` for
`reverse=True|max(|sorted(|>|>=|<|MetricOrder|MetricSpec|is_better` returns
**none**. So it is still not the proposer's direction defect, the real defect
is still the one `reverse=True` at `proposal_helpers.py:88`, and S4/P2a
ownership is unchanged. What is withdrawn is only the incidental "never
rendered in production" aside — and §27.3's second bullet is corrected to
match.

**The real direction defect is one line, on the production path** —
`nodes/proposal_helpers.py:84-89`:

```python
if method == "top_n":
    n = params.get("n", 10)
    # Sort by best_score descending, take top N
    scored = [m for m in all_models if m["best_score"] is not None]
    scored.sort(key=lambda m: m["best_score"], reverse=True)
    return scored[:n]
```

`MetricSpec` / `MetricOrder` / `metric_identity` occur **zero** times in
`ml_model_proposal_agent.py`, `proposal_helpers.py` and `proposal.py`.
`InterpretationOutput.metric_identity` exists and the proposer never reads it.
**Under a minimised metric this selects the WORST N models as candidates** —
DAVIS, exactly. It is a tenth site for §3.3's list and the one with the largest
scientific consequence.

**Test coverage confirms the shape of the risk**: the track record is tested on
the legacy path only; the 18-key whitelist is pinned only by the PB-3 goldens,
whose fixture contains 8 of the keys and **none of the four prediction keys**;
and a repo-wide grep for `prediction_pool_sizes` / `prediction_evaluation_semantics`
under the proposer's tests returns **0 hits** — deleting whitelist lines
`:1685-1694` would leave every proposer and interpreter unit test green.

### 3.7 `vocab_link_confirmations` and `campaign_artifacts` — one inert feature and one mislabelled item

**`vocab_link_confirmations` — producer and persistence work; BOTH halves of the
return transport are missing.**

| link | state |
|---|---|
| schema | `InterpretationInput.vocab_link_confirmations` `agent/schemas/interpretation.py:677-682`; `InterpretationOutput…` `:1155-1161` |
| producer | `result_interpretation_agent.py:850-861` (`update_vocab_link_confirmations`), written into both the normal (`:967`) and degraded (`:1074`) output |
| persistence | **YES** — it is inside the committed digest at `{workspace}/iter_NNN/iteration_NNN/interpretation_iter_NNN.json`, exactly the path `core/committed_digests.py:94-114` reads |
| resume projection | **NO** — `core/resume.py` contains **0** occurrences of the name; no `project_*`, no `RestoredState` field |
| in-process carry | **NO** — `workflows/model_exploration.py` contains **0**; `ChainState` (now `core/chain_state.py:46`) has **11** fields and none is this one |
| consumer | the interpreter itself, `:857` — and the workflow's sole production `InterpretationInput(...)` (`model_exploration.py:1934-1978`) simply does not pass the field |

**Consequence, measured rather than argued.** `existing_confirmations` is always
`{}`; one iteration appends at most one `run_name`; the promotion guard requires
`len(run_names) >= min_runs` with `min_runs=3`
(`nodes/interpretation_helpers.py:657-658`) — so **`VocabEntry.related_to`
promotion is unreachable in production**. This branch's own differential oracle
records `vocab_link_confirmations = {}` at both the interpretation and proposal
call sites. The only place the carry exists is a hand-wired integration test
(`tests/integration/workflows/test_vocab_accumulation.py:1067`) that is not in
CI.

**`campaign_artifacts` — the roadmap item and the source object are not the same
thing.** There is **no schema field** named `campaign_artifacts` anywhere. The
name refers to `core/campaign_artifacts.py` (174 lines), whose only production
consumer is `scripts/run_comparison.py` — a Phase-1 baseline **reuse** mechanism
whose state medium is the filesystem and whose reuse decision reads
`summary_*.json`, not the manifest it writes. `campaign_manifest.json` has
**zero readers in the repository**: write-only provenance. `run_comparison.py`
never calls `run_workflow`; it launches the tuner directly, so this module has
**no relationship to the exploration loop's iteration boundary** at all.

**Therefore the roadmap's "campaign_artifacts transport/integration" item is
re-scoped, not adopted as written** (§4 S7). What is genuinely Step-10-shaped
inside that module is its **task-coupling residue in generic core**: `:39`
requires a `denoising_score` key, `:53` resolves the declared health-peek set
via `resolve_dataset_profile()`, and `:106-111` imports the `TIDMAD` singleton
for the full-scope default.

### 3.8 The six implicit TIDMAD defaults — the measured shape of "not bound"

A census over the production tree found **zero** branches or tables on task
identity: no `== "tidmad"`, no `if "pets" in …`, no `{"tidmad": …, "pets": …}`
dispatch anywhere in production. That is a genuine strength and Step 10 must
preserve it.

**Denominator corrected, post-merge 2026-08-20.** Rev 2 quoted "461 production
files (851 task-name occurrences)". That pair is **not reproducible under any
natural definition** on merged master and is withdrawn. Re-measured, with the
definition stated so it stays checkable — the repository's **own**
`_production_files()` set (`nodes agent core execute_tools ml_models workflows
scripts dashboard`), match set `tidmad|pets|davis|oxford_iiit_pet`,
case-insensitive:

| definition | files | occurrences |
|---|---|---|
| **`*.py` under the repo's own 8 production dirs (CANONICAL)** | **303** | **750** |
| `*.py` repo-wide minus `.venv/ tests/ docs/ examples/ agent_generated/` | 389 | 794 |
| all file types under the 8 production dirs | 351 | 776 |
| ~~rev 2's quoted figure~~ | ~~461~~ | ~~851~~ |

**The conclusion survives an independently stronger instrument.** The re-audit
did not re-run rev 2's grep; it ran an **AST** census over the 303 production
`.py` files, matching `Compare` against a task-name string literal (including
membership tuples/lists/sets), `Dict` literals with task-name keys, `Subscript`
with a task-name string key, and `MatchValue` on a task-name literal. Results:
`== "tidmad"` / `!= "tidmad"` / `in ("tidmad", …)` = **0** · `if "pets" in …` =
**0** · `.startswith` / `.endswith` on a task name = **0** · `match`/`case` on a
task name = **0** · `{"tidmad": …, "pets": …}` dispatch tables = **0** ·
variables named `task_name` / `task_id` = **0**. **Class (b) = 0 CONFIRMED.**

Two AST hits surfaced and both are **non-counterexamples**, named here so a
future census does not rediscover them as findings:

* `execute_tools/evaluation_metric.py:636` —
  `_SCOREABILITY_CONTRACT_TYPES = {"deliverable_presence": …, "tidmad_denoised_h5": TidmadScoreabilityContract}`.
  Keyed on **`contract_id`**, not task identity; there is no `pets`/`davis`
  sibling key and the lookup fails closed on an unknown id. A declaration
  vocabulary, not a task dispatch — **but it is the one place a task word
  appears as a framework-owned table key**, so §26.1 B's "no per-task entry in a
  framework table" must be read against it deliberately rather than by
  accident.
* `execute_tools/data_paths.py:59` — `TIDMAD_DATA_DIR = _config["tidmad_data_dir"]`,
  a YAML config-key read, not a branch. Step-11-owned (§3.8 default 6).

Two textual near-misses that a regex census would flag and an AST census
correctly does not: `ml_hyperparameter_tune_agent.py:875`'s
`print("=== TIDMAD Agent Activated ===")` banner, and `pets_data_path.py:143`'s
`lines[0] != PETS_MANIFEST_HEADER` — a comparison against a **named constant**,
inside the Pets implementation itself. **This is the anti-vacuity lesson for
§26.1 A**: the guard must be AST-shaped, and it must not count a banner string
or an implementation's own self-check as a task branch.

What exists instead is **six independent implicit defaults**, one per semantic
family, none reachable from an operator flag — a grep for `--task_health`,
`--task_interpretation`, `--task_blocks`, `--task_id`, `--task_name`,
`--task_pack` across every `*.py` and `*.sh` returns **zero hits**:

| # | family | default site | how it is reached |
|---|---|---|---|
| 1 | task data path | `execute_tools/task_data_path.py:279` — `_REGISTRY.get(TIDMAD_COMPATIBILITY_ID)` when the binding context is `None` | the chain never binds |
| 2 | dataset profile | `execute_tools/dataset_config.py:613` — `_ACTIVE_PROFILE.get() or TIDMAD_PROFILE` | ambient acquisition in the tuner |
| 3 | task health config | `_composition.py:89` `LEGACY_DEFAULT_TASK_HEALTH_CONFIG` | `core/run_invariants.py:380-385` omits the keyword; `load_health_gates_config` has **no binding parameter at all** |
| 4 | metric | `ml_hyperparameter_tune_agent.py:541` — `derive_tidmad_metric(...)`, unconditional (not even a default) | the one **run-scoped** Regime-A derivation; two further production sites exist (`sandbox_executor.py:2009` legacy shim, `denoising_score_single.py:180` subprocess re-derivation) — see §3.1's correction |
| 5 | interpretation blocks | `agent/prompt_templates/interpretation/task_blocks.py:34,62` | both production callers pass no path — `workflows/model_exploration.py:1978` and `nodes/result_interpretation_agent/result_interpretation_agent.py:1247`, both zero-arg |
| 6 | physical data root | `execute_tools/data_paths.py:115` — `explicit or TIDMAD_DATA_DIR` | the sandbox ignores `--data_dir` outright | **⚠ STEP-11-OWNED — see below** |

**Default 6 is NOT Step 10's, and P1 must not claim it** (operator ruling §11,
2026-08-20). The six defaults are not one kind of thing, and conflating them
would either overclaim P1 or absorb Step 11:

| Step 10 owns | Step 11 owns |
|---|---|
| logical / run **task binding** (defaults 1–5) | **sandbox data-root resolution** (default 6) |
| `TaskDataPath` **identity and capability** | sandbox directory mechanics, cleanup, globs |
| explicit run-level data **semantics** | **physical-path fallback behaviour** |
| **emitting** the already-defined binding transport | IPC, rlimits, spawn mechanics |

So: **P1 makes five of the six defaults explicit and fail-closed; the physical
data root remains named Step-11 infrastructure debt.**

**Default 4's ownership split, stated precisely** *(R-2, operator-authorized
correction 2026-08-20 — resolves the apparent conflict with the roadmap's
"tuner Regime-A binding → Step 12" debt line)*: P1 makes the metric explicit
on **COMPOSED** runs via a bound-metric seam consumed at the tuner's existing
acquisition site; `derive_tidmad_metric` remains the bounded **UN-COMPOSED**
legacy adapter; **Step 12 owns the eventual legacy-adapter removal** together
with the final external composition root. P1 touching the tuner's acquisition
at the existing `:541`-equivalent site is therefore NOT a Step-12 scope
violation. P6 may use the currently
supported physical execution path while still proving that task *semantics* are
bound generically — the two claims are independent. The forward rule of §24
still binds in full: **no "make it generic later" debt is allowed for an
interface Step 10 itself introduces** — but Step 10 does not absorb Step 11's
implementation to satisfy it.

**And the seam that was built for this is unreachable.** `transport_argv`
(`task_data_path.py:347-354`) has **zero production callers** — the flag is
*parsed* by all three subprocess children (`train_engine_sandbox.py:1850`,
`inference_single.py:100`, `denoising_score_single.py:107`) and **emitted by
nobody**, so every child takes the regime-A TIDMAD branch.
`bind_task_data_path` (`task_data_path.py:314`) has **three** production callers,
and the third is the important one: `scripts/run_pets_gate2.py:144` and
`scripts/run_davis_gate2.py:136` are the two Gate-2 harnesses, and
**`execute_tools/train_engine_sandbox.py:1968` is the CHILD side of the
transport**, guarded by `if args.task_data_path_id is not None:` (`:1967`) and
falling to `contextlib.nullcontext()` (`:1972`) otherwise. Because
`transport_argv` has zero production emitters, that guard is **always false in
production** and the child always takes regime A.
**The architecture is complete and operationally dead** — the parent end is
built, the child end is built and waiting, and nothing joins them. That is
precisely the gap §4 S1 and S8 exist to close, and it means P1's emission work
has a live consumer to land against rather than one to write.

*(Post-merge correction, 2026-08-20: rev 2 said "exactly two production
callers". There are three; the third is unreachable for the reason above, so
the conclusion is unchanged and the finding is slightly strengthened.)*

**Finally, a live latent defect worth naming now.** §3.5's tables are already
wrong for two shipped tasks: Pets declares `categorical_distinct_symbols` /
`categorical_dominant_fraction` and DAVIS declares `sample_dispersion_floor`,
and **none is in any of the three tables**. It has not bitten only because
`scripts/_gate2_health_stage.py:103` calls `runner.evaluate_gate` directly,
bypassing `evaluation.py`. The moment either task routes through the tuner —
which is Step 10 S8 — their persisted health evidence goes blank. Separately,
`evaluation.py:89`'s fallback default for `min_unique_int8_values` is **5**
while `configs/task_health/tidmad.yaml:43` declares **25**: two declarations of
one threshold, already disagreeing.

---

## 4. Scope — what Step 10 does

Eight scope items. Each names its **semantic owner**, the **authority that
becomes canonical**, and the **legacy authority that disappears**. An item with
no disappearing authority is an *activation*, and is marked as such.

| # | scope item | authority that becomes canonical | legacy authority that disappears |
|---|---|---|---|
| **S1** | **Run-scoped task composition at the launcher/composition edge** — a run is handed an explicit, typed, fail-closed set of task bindings (data path · metric · Health family · interpretation blocks · task description/forward contract) instead of resolving them from defaults and module globals | one composition value, bound once, carried on the Step-09.5a immutable bindings | the module-level cached `configs/task_config.yaml` singleton as the *only* way task identity enters a run; the implicit `LEGACY_OMITTED` Health default as the *production* path |
| **S2** | **Metric/direction migration of the last nine golden-metric comparison sites** (§3.3) plus the two prose sites | `MetricOrder`, unchanged | the raw `>` / `>=` / `max` / `reverse=True` at those sites; the presence-list census that cannot see four of them |
| **S3** | **Production secondary-metric transport** — declaration → run-scoped binding → evaluation → record → interpretation, including the cache-carry symmetry fix | `SecondaryMetricEvidence`, unchanged; a record-level carrier; the existing metric handle | *activation* — nothing disappears, but the `secondary_metrics=[]` hardcode and the asymmetric `_stats` carry both go |
| **S4** | **Proposer evidence + direction ownership** — one typed reader of interpretation evidence; direction-aware comparison and prediction-authoring grammar | one proposer-side typed evidence reader; `MetricOrder` | the second, independently drifting untyped reader (see §11 for the deprecate-vs-isolate decision) |
| **S5** | **Interpretation-derived carried state** — `vocab_link_confirmations` **ACTIVATED** end-to-end (Q-10-3 = A) **and** `accumulated_key_findings` normalized into `ChainState` (Q-10-6 = A) | the ONE committed-digest read authority + typed projections + `ChainState` ownership | *activation + normalization*: the inert transport gap goes; the last bare cross-iteration `run_workflow` parameter goes |
| **S6** | **Health evidence declaration migration** (§3.5) — *scope-completeness correction, operator 2026-08-20: the boundary is SEMANTIC, not an implementation enumeration. Residual framework-owned per-check Health evidence metadata **that is derivable from the task/check declaration** becomes declaration-derived. It does NOT automatically include surfaces requiring new declaration capabilities* | the check's own `CheckInputDeclaration` | the per-check-NAME tables and duplicated defaults in `evaluation.py`, **plus `agent/schemas/health_feedback.py`'s `_WORST_STAT_BY_METRIC` and its `unit == "count"` exactness literal** |
| **S7** | **Task-coupling residue in generic-core campaign functionality** — where `core/campaign_artifacts.py` needs metric, task-data or scope semantics it consumes the **run-supplied bound authority** instead of rediscovering TIDMAD (§3.7: `:39` requires a `denoising_score` key, `:53` resolves the declared health-peek set via `resolve_dataset_profile()`, `:106-111` imports the `TIDMAD` singleton) | the run's bound authorities | the ambient TIDMAD pulls inside generic core |
| **S8** | **Three-task executable closure** — Pets and DAVIS initialize and run the exploration loop through the S1 composition, with correct direction, metric transport and persistence | the same generic path TIDMAD uses | the two hand-written per-task Gate runner scripts as the *only* way a contrast task executes |

### 4.1 Scope → child ownership map (FROZEN — no orphan scope item)

Every scope item has **exactly one** owning child. This map is frozen at parent
level; if the post-merge reconciliation changes it, it is revised **before** any
child freezes.

| scope item | owning child |
|---|---|
| **S1** run-scoped composition / launcher binding | **P1** |
| **S7** `campaign_artifacts` generic-core task-coupling residue | **P1** |
| **S2** primary metric / direction closure | **P2a** |
| **S3** secondary metric production transport | **P2b** |
| **S4** proposer typed evidence + prediction authoring | **P3** |
| **S6** Health evidence declaration migration | **P4** |
| **S5** `vocab_link_confirmations` activation + `accumulated_key_findings` normalization | **P5** |
| **S8** three-task executable closure | **P6** |

### 4.2 What `campaign_artifacts` explicitly does NOT become

Rev 1 correctly measured that `campaign_artifacts` is **not** a schema field and
**not** iteration-carried state (§3.7), and then loosely grouped it under
"orchestration artifacts travelling on the Step-09.5a substrate". That wording
is withdrawn. Frozen:

* `campaign_manifest.json` remains **filesystem provenance / reuse state**;
* it does **not** become `ChainState`;
* it does **not** acquire a committed-digest projection merely because Step 10
  touches orchestration;
* what Step 10 owns here is only the **task-coupling repair**, assigned to P1.

---

## 5. Explicit non-goals

Naming these is load-bearing: three of them are the difference between Step 10
and Step 12, and one is the difference between Step 10 and a rewrite.

1. **The SOURCE of the binding set — the out-of-tree task package and the
   unified composition root.** Step 12. Step 10 makes the *set of bindings*
   explicit, typed and externally supplyable; Step 12 makes one out-of-tree
   package supply the whole set with zero SIDERIUS edits, and owns the
   acceptance test that proves it (roadmap §22.24.3). Note the split carefully:
   Step 10 does **not** defer the *interface* for any binding it introduces
   (§3.2, §24) — it defers only where the set comes from.
2. **Execution infrastructure.** Sandbox data-root resolution, sandbox
   directory mechanics, physical-path fallback behaviour, cleanup globs,
   spawn/IPC, rlimits, runtime-control fallbacks and calibration precedence are
   **Step 11** (§23). Step 10 *emits* an already-defined binding transport; it
   does not redesign the transport, and it does not claim to remove Step 11's
   physical-path fallbacks.
3. **Any task's science.** Not what a metric measures, not what a Health check
   means, not what the interpreter says, not how a dataset is read.
4. **Tuner policy, round/attempt semantics, retry, watchdog or admission.**
   Untouched. The `resolved_action` stale-attempt hazard and the 07c
   validation-pricing debt are separately owned and are *not* Step-10 items
   merely because Step 10 is adjacent to them.
5. **The frozen TIDMAD metric formula and the frozen prediction v1 pool.**
   Byte-identical, both.
6. **A new run-state carrier.** Step 09.5a's three carriers are the *sole*
   workflow run-state boundaries. Step 10 adds fields with declared owners to
   the existing carriers; it does not introduce a fourth.
7. **Broad structural cleanup.** The Step-09.5 class-C list
   (`interpretation_helpers.py` grab-bag, the duplicated 5 % band, the stale CI
   selector docstrings, dead proposer reads) is not Step-10 scope. A class-C
   item may be repaired *in passing* only when a Step-10 change already touches
   that exact line.
8. **A second `TaskDataPath`-shaped system, or one giant registry.** §6.2.
9. **D16** (the loss-shaped metric-identity rule). Surfaced as an open question
   (Q-10-4 = A) because Pets's `log_loss` secondary cannot be declared through
   it. Step 10 does not modify the rule; D16 stays a named Step-06-owned
   correction and does not block Step 10, because DAVIS already supplies the
   mixed-direction discrimination.

---

## 6. The run-scoped composition / binding model

### 6.1 The rule

> **Task and run semantics are bound ONCE, at the composition edge, and are
> then carried as typed values. Nothing downstream rediscovers them.**

```text
  external/user task configuration  +  plugin references
                    │
                    ▼
        run-scoped composition / binding      ← ONE place, fail-closed
                    │            (produces typed values, not names)
                    ▼
              generic workflow                ← Step 09.5a carriers
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
      nodes      resume     execution
        └────── consume typed values ───────┘
```

The exact class name is deliberately **not frozen** — it must be chosen against
merged-master topology (§0.2). What *is* frozen is its shape:

* **it produces values, never names.** A bound metric is a `MetricSpec` +
  handle, not the string `"tidmad"`. A bound Health family is a resolved
  config, not a task label.
* **it is run-scoped and immutable**, and it therefore lands on
  `WorkflowRunBindings` — which already exists for exactly this purpose
  (Step-09.5a §22: *"`WorkflowRunBindings` gives Step 10 a typed place for
  launcher-supplied task binding to land"*).
* **it fails closed.** An unknown, missing or misspelled binding reference is
  an error at composition time, before any I/O. **It never falls back to
  TIDMAD.**
* **it does not own the semantics it binds.** It resolves references into the
  authorities Steps 02–09 already built, and stops.

### 6.2 Why `TaskDataPath` is the precedent — and why Step 10 must not clone it

`execute_tools/task_data_path.py` is the audit's named healthy counter-example
(§6.6, 364 LOC). Its properties, and what each one buys:

| property | what it prevents |
|---|---|
| a **Protocol** with typed request values | callers passing dicts and drifting |
| a registry keyed on **binding PRESENCE**, never on task name | task identity becoming control flow |
| **run-scoped binding** (`with bind_task_data_path(impl):`) | a global that one process can only ever hold one of |
| **explicit subprocess transport** | state travelling by convention |
| **fail-closed** on an absent binding | a silent TIDMAD default |

**Use the principle; do not build a second one.** Step 10 does not create
`TaskMetricPath`, `TaskHealthPath` and `TaskInterpretationPath` as three more
registries — each of those families *already* has its own resolution authority
(the metric handle; Health's three binding states and plugin registration;
`InterpretationTaskBlocks` as a caller-supplied value). What Step 10 adds is the
**one place where the whole set is bound for a run**, and the guarantee that
each family's existing authority is what actually resolves it.

Equally: **no one giant generic registry.** A single `TASKS = {...}` table —
however typed — is the §11 anti-pattern wearing a type annotation.

### 6.3 What the loop must stop doing

| the loop currently rediscovers | from | after Step 10 |
|---|---|---|
| task description / forward contract | module-level cached global (`workflows/task_config.py:41-50`) | received as a bound value |
| metric direction | raw `>` at nine sites (§3.3) | `MetricOrder` from the bound `MetricSpec` |
| Health family | omitted binding ⇒ TIDMAD default | explicitly bound; omission is an error in a composed run |
| interpretation task blocks | the bounded default-path constant | explicitly bound (the adapter remains for the legacy path until Step 12) |

---

## 7. Generic config + plugin extensibility (a first-class Step-10 constraint)

### 7.1 The requirement

For every semantic surface Step 10 owns, adding a **new task instance** must
require *configuration and externally supplied plugin references only*. It must
not require:

* editing a SIDERIUS central registry or a central import list;
* adding `if task == …` or a task enum member;
* editing a framework-owned per-task mapping table;
* modifying workflow orchestration, resume, metric-order, Health core, or
  proposer core merely to recognise task identity.

Unknown or misspelled references **fail closed**, and never silently resolve to
TIDMAD.

### 7.2 The distinction that keeps this honest

| kind of change | framework work? |
|---|---|
| a new **task instance** that fits existing capabilities (new config + plugins implementing existing protocols) | **NO — zero infrastructure source edits** |
| a genuinely new **plugin backend or capability** (a view capability that does not exist, a metric aggregation nothing implements, a data modality with no reader protocol) | **YES, legitimately** — this is the framework growing a new capability, not recognising a new task |

Step 08's precedent is exactly this: the built-in check import list is *"the
built-ins' bootstrap, NOT the extension path"*, and external checks register
through the public API. Step 10 must be able to say the same sentence about
every interface it introduces.

### 7.3 The measurable form of the claim

For a conforming new task on Step-10-owned interfaces:

```text
infrastructure source edits required   : 0
task-name branches added              : 0
central task registry/table edits     : 0
workflow orchestration edits          : 0
resume edits                          : 0
```

This is an acceptance criterion (§26 C), proven by an executable extension
proof, not by inspection.

---

## 8. Metric / direction integration

**No new authority.** `MetricSpec.direction` declares; `MetricOrder` interprets;
nothing else may. Step 10 introduces no direction enum, no
`higher_is_better` boolean, no comparator helper, no second ordering module.

**What changes:** the nine sites in §3.3 acquire the run's `MetricOrder`, and
the two prose sites render `direction_words` instead of stating *"higher is
better"*.

**Where each site gets its order from** — this is the part that must be designed
rather than assumed, because three of the nine are outside the workflow process:

| site group | source of the order |
|---|---|
| `workflows/model_exploration.py` (3 sites) | acquisition precedence *(R-3, operator-authorized correction 2026-08-20)*: **composed run ⇒ the composed/bound spec; otherwise ⇒ the artifact-stamped/reconciled spec** (the pattern the workflow already uses for `_cap_knowledge_cache`: `MetricOrder(run_metric_spec) if run_metric_spec is not None else None`); **no spec anywhere ⇒ Q-10-2 refusal**. No second metric-identity derivation |
| `core/resume.py:_pick_best` | the restoring run's bound spec; a restored record whose spec is absent is a **named refusal**, exactly as `InterpretationInput` fails closed (Step 09a) — never a re-derivation |
| `execute_tools/per_file_best.py:_row_beats` | the metric identity it already imports; the spec must reach it explicitly |
| `dashboard/*` (3 sites incl. prose) | the dashboard reads persisted artifacts, so the direction must be **read from what was persisted**, not assumed. If a persisted record carries no spec, the dashboard must say so rather than rank |
| `scripts/*` (2 diagnostic sites) | same as the dashboard |

**A persisted artifact with no `metric_spec` — RULED, Q-10-2 = A (FROZEN).**
A legacy artifact predating `metric_spec` persistence carries no declared
direction. The frozen behaviour:

| behaviour | required |
|---|---|
| artifact remains inspectable | **YES** |
| raw / scalar values displayed | **YES** |
| ranking, sorting or "best" selection | **NO — unavailable** |
| a visible, named *"metric direction unavailable / `metric_spec` absent"* | **REQUIRED** |
| assuming higher-is-better | **FORBIDDEN** |
| hard-failing the whole dashboard or script | **NO** |

There is no hidden compatibility assumption anywhere on this path. And the
forward half of the ruling is an acceptance criterion in its own right: **every
newly persisted artifact must carry enough metric identity for a future
consumer to rank correctly.**

**The census must get stronger, not merely longer.** §3.3 showed the current
presence-list census misses four live sites. Step 10 replaces the mechanism
with the AST scanner 09a-C3 already built (audit **TB-4**), aimed at the
post-migration surface. This is a coverage upgrade; nothing is retired.

### 8.1 P2a acceptance (FROZEN)

P2a — **Golden `MetricOrder` Closure** — owns **all** currently measured
direction-sensitive golden-metric sites, including
`nodes/proposal_helpers.py`'s production `top_n` cut, which is a shared
ordering decision and is therefore best owned at the ordering layer rather than
inside the proposer's evidence child.

1. **one** `MetricSpec.direction` declaration; **one** `MetricOrder`
   interpreter;
2. **zero** raw task-dependent `>` / `<` / `max` / `min` / `reverse=True`
   decisions on the golden metric;
3. the **stronger AST scanner** replaces the presence list (§3.3 measured that
   the presence list misses four live sites);
4. TIDMAD negative-valued **higher**; Pets **higher**; DAVIS **lower** — each
   with **hand-computed** expectations, never values produced by the code under
   test;
5. Q-10-2's no-`metric_spec` behaviour implemented at every consumer of
   persisted artifacts;
6. no new direction enum, boolean, helper or comparator is introduced.

**P2b must not duplicate any part of this migration.**

**CLOSED — P2a MERGED 2026-08-21 (PR #242, squash `e094fa26`).** S2 is
delivered: the production golden-metric ordering surface went from **12
measured sites to 0** (the C0 scanner found two chain-fold sites in
`core/resume.py` that §3.3's audit had missed — bounded expansion inside the
already-owned resume selection class), `reconcile_metric_spec` is PROMOTED to
`execute_tools/evaluation_metric.py` as the ONE reconciliation authority (one
engine, two granularity entry points: full spec / persisted
`(metric_id, direction)`), every consumer of persisted artifacts implements
the four-case unrankable semantics, the proposer's `top_n` cut follows the
declared direction with the Q-P2a-1 order-free `all` fallback, and the AST
scanner stands guard with direct + alias plant-and-catch proven at the final
head. Acceptance criterion 6 held with ONE reviewed deviation: **D-P2a-4
ACCEPTED/BOUNDED** — `MetricOrder`'s ordering behaviour/body is unchanged and
no second comparator exists; only its accepted declaration annotation widened
to admit the §4.4 minimum comparison identity. **F-P2a-4 RESOLVED** — P2a
adds zero TIDMAD derivation sites (CI caught an attempted fallback; it was
deleted, never census-widened). Exact-head CI 32431989276 SUCCESS on
`b50bec6a`; merged master byte-identical to the validated head; post-P4
reconciliation was MERGE-BASED (merge commit `553bd66c`, 0 conflicts, force
push not used). Evidence: `pr_10_p2a_golden_metric_order_closure.md` §13.

---

## 9. Secondary-metric transport

### 9.1 The frozen ordering rule, first

> **Secondaries are observational. They never select the primary winner** — not
> incumbent selection, not active-model selection, not cache capping, not the
> prediction default, not prediction evaluation. Changing that requires an
> explicitly separate future policy decision, and Step 10 is not it.

This is Step 09a's frozen invariant, already pinned by an executable test that
no ordering expression takes a secondary as an operand. Step 10 keeps that test
green *after* the values become real — which is precisely when it starts
earning its cost.

### 9.2 The lifecycle Step 10 must freeze

| stage | what must be decided | constraint |
|---|---|---|
| **declaration** | which declared metrics are secondary | today nothing in a pack marks primary vs secondary — the consumer names a filename (§3.4). Step 10 must make the *task* declare the relation, not the caller |
| **run-scoped binding** | secondaries bound once, beside the primary | same composition edge as §6; each carries its OWN direction |
| **evaluation** | who evaluates, and when | through the existing metric handle, beside the primary, with the same scoreability-before-arithmetic order |
| **record transport** | the record-level carrier `evidence.py:480-486` names as missing | additive; frozen record names unchanged |
| **persistence / carry** | `_stats` write **and** cache read-back | **must be symmetric with `failure_counts` from the first commit** (§3.4, audit B-6) |
| **interpretation availability** | already built (`ModelRunSummary.secondary_metrics`) | the builder stops hardcoding `[]` |
| **named absence / refusal** | `unavailable` vs `refused` | both already typed; a declared-but-unevaluated secondary is a **named absence**, never a silent omission and never a number |

### 9.3 Per-task expectations

| task | secondaries | what the Gate/test must show |
|---|---|---|
| TIDMAD | none | the *absence* path: no secondary block rendered, nothing carried, no behaviour change |
| Pets | `macro_f1` (higher) | present-secondary path with the SAME direction as its primary |
| DAVIS | `psnr` (higher), `mae` (lower) | the **discriminating** case: a `lower` primary with a `higher` secondary, plus a declared-but-unavailable third state |

DAVIS's L1 fixture already exercises exactly this shape (`psnr` scored, `mae`
declared-but-unavailable). Step 10's job is to make the production path produce
what that fixture asserts.

**Pets contributes `macro_f1` and only `macro_f1`** (Q-10-4 = A). Its third
intended secondary `log_loss` is not declarable under the Step-06 identity rule
(`_is_loss_shaped`, §3.4), Step 10 **does not modify that rule**, and the
intent is **not deleted from project documentation** to make Step 10 look
complete — D16 stays an explicitly named Step-06-owned future correction.
Step 10 is not blocked on it, because DAVIS already supplies the
mixed-direction discrimination that matters.

### 9.4 P2b acceptance (FROZEN)

**CLOSED — P2b MERGED 2026-08-21 (PR #244, squash `5a2ecfd1`).** S3 is
delivered: all eight criteria below are met at the merged head, with the
evidence recorded in the child ledger §15 (76 checked, 0 open). Criterion 5's
cache-carry symmetry (audit B-6) is closed in this same child as required —
`_stats` write AND validated read-back, asserted on ONE fixture that checks
`failure_counts` and `secondary_metrics` in a single block. Criterion 7 is
proven by the Step-09a ordering-operand invariant staying green after the
values became real, with its scanned surface EXTENDED over P2b's production
lifecycle in C0 (before any behaviour changed) and executable plants in each
of the five files P2b actually modified. Criterion 8 holds: zero P2a sites
re-migrated, no second order authority, and `metric_order.py` has an empty
diff since the freeze commit.

P2b — **Secondary Metric Production Transport** — owns declaration, run
binding, evaluation, record transport, persistence and cache carry,
interpretation availability, and the named refused/unavailable states.

1. the **task** declares which metrics are secondary (today nothing in a pack
   marks the relation — the consumer names a filename);
2. secondaries are **bound once**, at the same composition edge, each carrying
   its **own** direction;
3. evaluated through the **existing** metric handle, with scoreability checked
   before arithmetic;
4. transported on an additive record-level carrier; frozen record names
   unchanged;
5. **cache-carry symmetry with `failure_counts` closed in the same child** —
   `_stats` write **and** cache read-back, so a model that goes quiet for one
   iteration does not lose its secondaries while keeping its failure counts;
6. rendered where declared; a declared-but-unevaluated secondary is a **named
   absence**, never a silent omission and never a number;
7. **zero influence on primary ordering**, proven by keeping Step 09a's
   ordering-operand invariant green *after* the values become real;
8. **P2b introduces no second metric-order authority** and does not re-migrate
   any P2a site.

---

## 10. Resume / `ChainState` integration

**The substrate is Step 09.5a's, and Step 10 adds to it rather than beside it.**

Four rules, all derived from frozen text:

1. **No fourth carrier.** `WorkflowRunBindings` (immutable authorities),
   `WorkflowLaunchConfig` (transit config), `ChainState` (cross-iteration
   mutable) are the sole workflow run-state boundaries. A new Step-10 value
   joins one of them, with a declared owner, and the derived ownership guard
   keeps it honest.
2. **No fifth resume loader.** Anything newly carried across iterations reads
   through `read_committed_digests` — ONE open, ONE parse, ONE readability
   verdict — and gets its own **projection** with its own merge rule and its own
   failure policy. That is the shape `core/resume.py`'s four projections already
   have:

   | projection | merge rule | failure policy |
   |---|---|---|
   | `project_knowledge` | **split**: vocab latest-wins, findings chronological **union** (dedup, first wins) | drops the bad entry, keeps the digest |
   | `project_fingerprint_history` | latest-wins, whole-dict | **raises** — *"refusing to drop deterministic gate evidence silently"* |
   | `project_prediction_memory` | latest-wins, whole-object | **raises** — *"an accuracy statistic assembled from half a pool is worse than none"* |
   | `project_knowledge_cache` | latest-wins, defensive copy; an empty dict on disk **does** overwrite | no validator, deliberately the weakest |

   A new projection must state which of those it is, and why.
3. **`ChainState` never crosses a subprocess boundary** (09.5a §16).
   `RestoredState` is the transport type across the launcher edge. A Step-10
   value that must reach a subprocess uses explicit argv/IPC transport — the way
   `TaskDataPath` does — not a widened `ChainState`.
4. **Single writer.** Amendment C: exactly one writable authority per carried
   value. The `prediction_memory` loop closure
   (`workflows/model_exploration.py:2619-2633`, read side `:1938-1951`) is the
   pattern to copy — it
   re-reads the digest the interpreter just wrote *"so the in-process loop and
   the chain-subprocess restore agree by construction rather than by two
   independent accumulations."*

**`accumulated_key_findings` — RULED, Q-10-6 = A (FROZEN).** It is the only
union projection and the only carried value with **no `ChainState` field**,
remaining a bare `run_workflow` parameter (declared `:1396`) read directly from
the closure at `:2107-2115`. It is
**promoted into `ChainState`**, owned by **P5**. Its projection **may stay
unique** — chronological union, dedup, first-occurrence wins — because merge
shape and lifecycle ownership are different concerns; what may not persist is a
cross-iteration value whose lifecycle ownership differs from every sibling's
solely because its merge rule is unusual.

**And one Step-09.5a hand-off is explicitly waiting here** (recorded in its C4b
ledger row): the launcher unpacks `RestoredState` into nine separate kwargs.
Collapsing those into a single `RestoredState` parameter honours §16 — it is
resume's own type, not a workflow type — and it changes the launcher's
orchestration inputs, which is Step 10's surface, not Step 09.5a's.

---

## 11. Proposer evidence and direction ownership

### 11.1 The decision this parent must make

Given §3.6, the honest statement of the problem is **not** "two readers should
become one". It is: *the proposer has no typed contract with the interpreter at
all, and it grew two untyped readers of one `model_dump()` dict.*

**Decision (freezable at parent level): the authority becomes a typed,
proposer-facing evidence contract — a value the protocol produces, not a dict
the proposer mines.** The reasons are measured, not stylistic:

* every field added must currently be wired **twice**, and the source records
  two occasions where it was wired once and the production path silently missed
  it;
* two of the legacy reads are dead against the live schema and nothing catches
  it;
* the pipeline whitelist can lose four prediction keys with every test staying
  green.

A typed contract makes all three of those a type error or a failing owner test
rather than an incident found by a Gate.

### 11.2 The legacy / pipeline disposition — FROZEN (operator ruling §5, 2026-08-20)

Rev 1 left "deprecate vs isolate" open. It is now decided, and the decision
separates two things that were being conflated — an **entrypoint** and a
**semantic reader**:

> **Retain the reachable legacy/standalone entrypoint for compatibility.
> Remove the duplicated semantic reader.**

Concretely:

1. **Both** the legacy path and the pipeline path consume **ONE typed
   proposer-facing evidence value**, produced by the protocol.
2. They **may render or use that value differently** — different prompts,
   different shapes, different subsets.
3. They **must not** independently mine `InterpretationOutput.model_dump()` /
   a raw `dict[str, Any]` with separate `.get()` contracts.
4. **No new interpretation evidence field may ever again need wiring into two
   readers.** That is the executable form of the rule, and the acceptance
   criterion.
5. If the legacy path must keep byte-exact prompt compatibility, it uses an
   **adapter from the typed value into the legacy renderer**. Prompt bytes are
   preserved through an adapter — never by preserving raw-dict semantic
   ownership.

**What must NOT happen:** no new evidence field may be added to either untyped
reader before the typed contract exists. Adding a secondary-metric block to two
dicts is precisely how this debt was created, and P2b lands before P3.

### 11.3 Direction

`nodes/proposal_helpers.py:84-89`'s `reverse=True` is migrated to `MetricOrder`
with the rest of §8's list. Under DAVIS it currently selects the worst N
candidates, and that must be an executable test with a hand-computed
expectation, not a code review.

The prediction-**authoring** grammar (what the proposer is asked to predict, and
in what direction-safe terms) is the remaining half of the roadmap's
"proposer prediction-authoring grammar" item and belongs with the typed
contract, because it is the same child's evidence surface.

---

## 12. P5 — Interpretation Carried-State Closure

Rev 1 scoped this section as a single open decision about
`vocab_link_confirmations`. Revision 2 reframes it, per the operator ruling, as
**one coherent semantic owner: interpretation-derived cross-iteration state.**
That owner holds two items whose lifecycles are the same shape and whose
current defects are the same defect seen from two sides — a carried value whose
lifecycle ownership was never decided.

### 12.1 `vocab_link_confirmations` — ACTIVATE (Q-10-3 = A, FROZEN)

The contract retains useful intended cross-iteration semantics, so it is made
**genuinely reachable** rather than retired:

```text
producer  →  committed digest  →  projection  →  ChainState
          →  next-iteration InterpretationInput
          →  the ≥ 3-run promotion condition
```

Every link is required. §3.7 measured that **both halves of the return
transport are missing** (no projection, no workflow carry), which is why
"add a field" is not the work.

**The evidence ruling matters as much as the activation ruling.** `min_runs=3`
does **not** imply a 3-iteration real Gate:

| owner | claim it proves |
|---|---|
| **deterministic lifecycle / integration test with temporal depth ≥ 3** — the PRIMARY owner | a confirmation produced in iteration *n* survives digest → projection → carrier → consumer and reaches `related_to` promotion at the third run |
| a real Gate | **only** if the current gate standard assigns a genuinely unique failure class that deterministic evidence cannot prove |

Temporal depth is a property of the *test*, not of the GPU.

### 12.2 `accumulated_key_findings` — normalize into `ChainState` (Q-10-6 = A)

§10's ruling, owned here: lifecycle ownership becomes consistent with its nine
siblings; the union merge rule stays unique and documented.

### 12.3 P5 constraints

* uses **the ONE** Step-09.5a committed-digest read authority — no fifth or
  sixth loader;
* introduces **no** new run-state carrier;
* each projection states its merge rule and its failure policy explicitly, in
  the shape §10's four existing projections already have;
* **acceptance proves reachability, not presence** — a test that fails when
  production stops carrying the value. A field that exists is not a feature
  that works; that distinction is this child's entire reason for existing.

---

## 13. Health / `evaluation.py` residual debt

Scope **(corrected for completeness, operator 2026-08-20 — see
`pr_10_p4_health_evidence_declaration.md` §12, C-P4-1)**: residual
framework-owned per-check Health evidence metadata **that is derivable from the
task/check declaration** becomes declaration-derived.

Explicitly included:

* §3.5's three per-check-NAME tables in `evaluation.py`, plus the
  `channel0001_prefix_peek` sampling-method literal at `:158` and the stale
  duplicated defaults at `:89`/`:96`/`:103`;
* `agent/schemas/health_feedback.py:110-117` `_WORST_STAT_BY_METRIC` — the
  already-declared per-check comparison operator hard-coded a second time,
  reached on the live path via `nodes/result_interpretation_agent/evidence.py:267-268`;
* `agent/schemas/health_feedback.py:417`'s `unit == "count"` exactness literal.

Explicitly **excluded** — surfaces that would require a NEW declaration
capability rather than a derivation from declarations already present. Two are
named, with owners frozen (Q-P4-3 = defer both):

* **HD-T5** — `_RECORDING_KEY_METRICS` (`health_feedback.py:124-133`): a Health
  *representative-evidence* declaration capability (which recorded observation
  scalars a check exposes as `key_metrics`);
* **HD-T6** — `_COLLAPSE_ADVICE_BY_CHECK` (`agent/prompts.py:24-32`) and its
  call sites (`agent/llm_bridge.py:1005`/`:1009`): a Health *LLM-advice*
  declaration capability, with its own Gate-1 and prompt-parity disposition.

Owner for both: **named post-Step-10 Health-capability debt / a future
dedicated Health-extensibility PR.** NOT P6 — its contract is final executable
closure and it adds no new scientific semantics; it may verify the generic path
and report these as a remaining optional limitation, nothing more. NOT assumed
to be Step 12 — Step 12 externalizes a task package's SOURCE, and may only do so
once an interface exists.

This is a completeness correction to the existing S6 owner. It does not change
the P4 semantic owner, the seven-child decomposition, scientific Health
semantics, the public result schema, P4/P2a parallelism, or any frozen parent
ruling. §4.1's ownership map row already read "Health evidence declaration
migration" and is unchanged.

**Target: declaration-driven.** The check already declares
`threshold_parameter_names`; what the tables add — the comparison operator, the
unit, and the rendered metric name — belongs on the check too, because the check
is what knows them.

**Constraints:**

* **No Health scientific semantics change.** This is an ownership migration.
  Verdicts, actions, severity resolution and thresholds stay bit-identical for
  TIDMAD.
* **A task-specific check must require no central-table edit** — the acceptance
  form of the claim, proven by routing Pets's and DAVIS's declared families
  through `evaluation.py` and finding complete persisted evidence.
* **Extending `CheckInputDeclaration` once is allowed** (§7.2): a new
  *capability*, not a new *task*.
* The `:89` / `tidmad.yaml:43` disagreement (5 vs 25) is repaired **as part of
  removing the duplicate**, never by editing one of the two to match.

**CLOSED — P4 MERGED 2026-08-20 (PR #243, squash `79833db8`).** S6 is
delivered: the per-check-NAME tables, the duplicated defaults, the TIDMAD
sampling literal, the metrics-key cascade, `_WORST_STAT_BY_METRIC` and the
unit-exactness literal are all gone; each check declares its own evidence and
`evaluation.py` now sits in the health-core census GENERIC partition.
Contrast tasks get complete evidence at BOTH hops. **HD-T5 and HD-T6 remain
named, unimplemented post-Step-10 Health-capability debt** — not P6's, and not
assumed to be Step 12's.

**RESOLVED (operator, 2026-08-20).** The P4 post-P1 reconciliation found that
the failure class this section defines is not contained by `evaluation.py`:
after the migration a Pets or DAVIS failure would persist a complete threshold
row and STILL produce no collapse fingerprint, because its metric name is
absent from `_WORST_STAT_BY_METRIC` — the same silence, one hop later. Per §4.1
("if the post-merge reconciliation changes it, it is revised **before** any
child freezes") the operator applied the scope-completeness correction recorded
above, and **P4 is FROZEN at REVISION 3**. Evidence and rulings:
`pr_10_p4_health_evidence_declaration.md` §2.2 / §12.

---

## 14. Three-task contract matrix

The purpose of this table is a single claim: **same infrastructure, different
values.** Where a cell is not yet true, it says so — an aspirational matrix
would be worthless.

| concern | TIDMAD | Pets | DAVIS | generic authority | true today? |
|---|---|---|---|---|---|
| task data path | `tidmad` impl | `oxford_iiit_pet` impl | `davis_future_prediction` impl | `TaskDataPath` protocol + fail-closed registry | impls ✅ / **binding reachable only in Gate scripts** ❌ |
| subprocess transport of the binding | regime-A default | — | — | `transport_argv` + child resolvers | **zero emitters** ❌ |
| dataset semantics | `DatasetProfile` (resolved) | manifest scope | clip manifest scope | Step-02 profile / scope | ✅ for TIDMAD; contrast tasks use pack manifests |
| model I/O contract | `[B,T] int → [B,256,T]` | `[B,3,144,144] f32 → [B,37] f32`, categorical, 37 classes | `[B,3,8,128,224] → [B,3,4,128,224]`, continuous | `ModelIOContract` | ✅ all three declared |
| objective | CE / focal family | CE | MAE family (`smooth_l1` realised) | `TrainingObjective` + `LossConfig` | ✅ |
| primary metric | `tidmad_denoising_score` **higher** (negative-valued) | `accuracy` **higher** | `mse` **LOWER** | `MetricSpec` + `MetricOrder` | ✅ declared; ❌ 10 raw-comparison sites remain |
| secondaries | none | `macro_f1` (higher) | `psnr` (higher), `mae` (lower) | `SecondaryMetricEvidence` | declared ✅ / **never evaluated** ❌ |
| Health family | `configs/task_health/tidmad.yaml`, 6 checks | pack `declared/task_health.yaml`, 2 blocking gates + pack view provider | pack `declared/task_health.yaml`, 1 blocking gate + pack view provider | task health config + public `register` / `register_view_provider` | ✅ bound in Gate scripts; ❌ chain always takes `LEGACY_OMITTED` |
| Health evidence persistence | complete | **blank** (names absent from the tables) | **blank** | `evaluation.py` ← should be the check declaration | ❌ |
| interpretation blocks | `configs/task_interpretation/tidmad.yaml` (3 of 4 keys; `prediction_guidance` genuinely absent) | none declared ⇒ nothing rendered | none declared ⇒ nothing rendered | `InterpretationTaskBlocks` | ✅ contract; ❌ default-path constant is the only binding |
| task description / forward contract | `configs/task_config.yaml` | pack-level declaration is Step 12's; **the RUN BINDING is Step 10's** (P1) | same | a Step-10 run binding; the singleton survives only as a legacy adapter | ❌ today it is a module-global cached singleton and the semantic authority |
| resume / carry | digest + 4 projections | same protocol | same protocol | `read_committed_digests` + `ChainState` | ✅ mechanism; contrast tasks never enter it |
| proposer evidence | untyped dict, 2 readers | same | same | (Step 10 creates it) | ❌ |

**The pattern to read out of the right-hand column**: the *declarations* are
essentially complete for all three tasks; what is missing is almost entirely
**binding and transport** — which is exactly Step 10's mandate, and good
evidence that the milestone is correctly scoped.

**The design test, applied to every Step-10 interface:** if an interface can
only be explained as *"here is what TIDMAD passes"*, and cannot be explained for
a 37-way classifier and a lower-is-better spatiotemporal regressor in the same
breath, it is not yet generic. Pets and DAVIS enter at design time, not at smoke
time.

---

## 15. TIDMAD acceptance

**Preservation, stated as behaviour rather than as bytes** (bytes where they are
genuinely frozen):

1. The frozen metric formula, `denoising_score` / `file_vector` / `score_table`
   names, and the prediction v1 pool: **unchanged**.
2. A TIDMAD chain run through the new composition produces the same persisted
   artifacts, statuses, iteration ordering, retry semantics and resume policy as
   before.
3. LLM-facing parity: any prompt delta is **declared and owned** (the
   direction-word rendering at the two dashboard-style prose sites is *not*
   LLM-facing; the proposer's typed-evidence change **is**, and the child that
   makes it owns a Gate-1 disposition).
4. TIDMAD's Health verdicts, actions and thresholds: **bit-identical**, with the
   `evaluation.py` migration proven by a verdict-manifest comparison the way 08a
   and 08b did it.
5. TIDMAD's *absent* secondaries render nothing and carry nothing.

---

## 16. Pets acceptance (classification, higher-is-better)

1. A Pets run **initializes and executes the exploration loop** through the same
   generic composition TIDMAD uses — not through `scripts/run_pets_gate2.py`.
2. `accuracy` higher-is-better is correct at every migrated ordering site.
3. `macro_f1` — **and only `macro_f1`** — is transported as a **secondary**, is
   present in the interpreter's evidence, and provably **cannot** affect winner
   selection. Pets's third intended secondary `log_loss` is **not declarable**
   under the Step-06 identity rule; per Q-10-4 = A the rule is unchanged, the
   intent stays recorded in the pack's `STATUS.md`, and **D16 remains an OPEN
   Step-06-owned correction**. Step 10 is not blocked on it.
4. Its declared Health family binds explicitly (state C, never `LEGACY_OMITTED`)
   and its persisted evidence is **complete** — thresholds, per-file metric
   names and units present, which is the executable form of §13.
5. Its `ModelIOContract` (categorical, 37 classes) flows through the same path.
6. **No model-quality requirement.** The known D14-2 constant-prediction
   collapse is acceptable and is in fact useful — it exercises the blocking
   gates.

---

## 17. DAVIS acceptance (spatiotemporal regression, lower-is-better)

DAVIS is the **discriminating** track: under a direction defect it does not
degrade, it inverts.

1. Loop execution through the same generic composition.
2. `mse` **lower**-is-better correct at every migrated site — with
   `nodes/proposal_helpers.py`'s `top_n` cut named explicitly, since it
   currently selects the worst N.
3. Secondaries in **two** states from one task: `psnr` (higher) scored, and a
   declared-but-unavailable third metric rendered as a **named absence**, never
   as a number — the shape its L1 fixture already asserts.
4. Its declared Health family binds explicitly; evidence complete.
5. Its `ModelIOContract` (continuous, `class_cardinality is None`) flows through
   the same path.
6. No model-quality requirement.

---

## 18. Extensibility — what adding task N costs

**Growth model:**

```text
task N  =  configuration
         + plugins implementing existing protocols
         + task-owned resources (manifests, declarations)

framework  =  UNCHANGED for ordinary task addition
```

**Quantified, for Step-10-owned interfaces, when the task fits existing
framework capabilities:**

```text
infrastructure source edits   : 0
task-name branches added      : 0
central registry/table edits  : 0
workflow orchestration edits  : 0
resume edits                  : 0
```

**The distinction that keeps this from being a slogan** (§7.2): a genuinely new
plugin *backend* or *capability* — a view capability nothing implements, a
metric aggregation that does not exist, a data modality with no reader protocol
— **may legitimately require framework work**. A new task *instance* using
existing capabilities **may not**.

**Fail-closed is part of the contract.** An unknown or misspelled reference
produces a named error listing what is registered. It never resolves to TIDMAD.
`TaskDataPath`'s truth table is the model: *"Explicitly bound tasks never fall
back to the TIDMAD compatibility path"*, and *"Unknown ids fail closed."*

**What is still Step 12** after all of this: the out-of-tree task **package** —
one reference supplying the whole set, from a directory SIDERIUS does not ship.
Step 10 makes the set explicit and bindable; Step 12 makes it external.

---

## 19. Module and responsibility architecture (binding for Step 10)

Step 10 must not recreate the debt Step 09.5 just measured. The rules below are
**responsibility-based**; LOC appears only as a *trigger*, never as a verdict.

### 19.1 The prohibitions

* no new god file;
* no new giant context object (a "bag of everything the run needs" is the
  99-parameter signature with a type annotation);
* no new 100-argument function;
* no helper dumping ground (`*_helpers.py` that accretes unrelated functions —
  the audit's C-1);
* no central task registry accumulating scientific semantics;
* no function that grows by repeatedly appending independent workflow phases.

### 19.2 Why LOC is not the criterion

The audit is explicit, and its own contrast case proves it:
`agent/schemas/hyperparam_tuning.py` is 3,000+ lines and was **not** flagged —
it is a coherent family of schemas whose largest function is 83 lines.
`run_workflow` at 1,572 lines **was** flagged, because five independently
changing owners shared one scope. **A 700-line coherent parser can be healthy; a
250-line function with five semantic owners is not.**

### 19.3 The structure preflight — BINDING at every child freeze

Each child design must carry, as an explicit artefact produced **before** it
freezes:

| preflight item | what it records |
|---|---|
| changed production files | the full list |
| current LOC + responsibility inventory | per file, per responsibility — not LOC alone |
| materially changed functions | which, and how |
| branch / argument growth | measured, not estimated |
| semantic owner count | per changed function and per changed file |
| proposed module placement | where new code lands, and why there |

```text
inventory every production file the child materially grows
  → inventory every materially changed function
  → name the semantic owner(s) of each
  → if adding the child would put two independently-changing semantic owners
    into one existing file or function:
      PERFORM THE MINIMUM COHERENT DECOMPOSITION FIRST,
      inside that child's own implementation plan
  → then add the new semantics
```

**Do not add semantics and promise cleanup later.** This ordering is the whole
point: 07b's C7 became an operator scope amendment *inside* the PR because the
decomposition was discovered during implementation. Step 10 does it at design
time.

**And decomposition means ownership, not arithmetic.** Splitting one
1,000-line function into five 200-line functions that still share the same
mixed ownership is not a decomposition — it is the same complexity in five
places, which the project has already named as a failure mode.

### 19.4 Review triggers (quantitative, non-binding individually)

Any of these **triggers an ownership review**; none of them alone fails a child:
material LOC growth in one file; a large branch-node increase in one function; a
growing argument count; several phase banners in one body; multiple persistence
or record constructors in one scope; more than one semantic owner named in the
inventory.

### 19.5 The accepted healthy shape

```text
one obvious orchestration entrypoint
  + coherent private modules / services / typed contracts
  + a public boundary that is an executable rule
```

The tuner node's post-07b-C7 layout is the worked precedent: a public
`<node>.py` + `<node>.md` over eight private modules on a one-way acyclic graph,
with `tests/unit/nodes/test_node_public_boundary.py` making the boundary
executable.

---

## 20. Child decomposition — SEVEN children (parent-level FROZEN)

### 20.1 Method — ownership first, count last

The question is **not** "how many PRs" but "how many semantic owners, and what
depends on whose public contract". The boundaries below come from §3's
measurements and from the operator's Q-10-1 ruling. The **parent-level**
decomposition — which children exist, what each owns, and their order — is
FROZEN. The **implementation-owning child designs** are not (§0.2).

### 20.2 The ownership graph (seven children — FROZEN at parent level)

```text
              ┌──────────────────────────────────────────┐
              │ P1  Run-Scoped Task Composition/Binding  │   (new authority)
              │     S1 + S7                              │
              └────────────────────┬─────────────────────┘
                                   │  everything below binds through it
        ┌──────────────────┬───────┴────────┬──────────────────┐
        ▼                  ▼                ▼                  ▼
┌───────────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────────────┐
│ P2a  Golden   │  │ P4  Health   │  │ P5  Interp. │  │                  │
│ MetricOrder   │  │ Evidence     │  │ Carried-    │  │  (P4 and P5 run  │
│ Closure  S2   │  │ Declaration  │  │ State       │  │   in parallel    │
└───────┬───────┘  │ Migration S6 │  │ Closure  S5 │  │   once their own │
        │          └──────────────┘  └─────────────┘  │   deps are met)  │
        ▼                                             └──────────────────┘
┌───────────────────────────┐
│ P2b  Secondary Metric     │
│ Production Transport  S3  │
└───────────┬───────────────┘
            ▼
┌───────────────────────────┐
│ P3  Proposer Typed        │
│ Evidence + Authoring  S4  │
└───────────┬───────────────┘
            │
            ▼   (after P1, P2a, P2b, P3, P4, P5 — ALL of them)
┌──────────────────────────────────────────────┐
│ P6  Three-Task Full-Chain Executable Closure │
│     S8 — adds NO new scientific semantics    │
└──────────────────────────────────────────────┘
```

### 20.3 The seven children

| id | scope | one semantic owner? | independently reviewable / testable? | depends on |
|---|---|---|---|---|
| **P1** | **Run-Scoped Task Composition / Binding** — the composition value and its fail-closed resolution; five of the six implicit defaults becoming explicit (the sixth is Step-11's, §3.8); the existing task-binding transport actually **emitted**; `RestoredState` as one launcher parameter; the `campaign_artifacts` task-coupling repair | **yes** — ONE run composition authority | yes / yes | Step 09.5a merged, incl. its C3 closure — **BOTH SATISFIED** (squash `2393aacc`; C3 closed in `52ed46b1`, §3.0) |
| **P2a** | **Golden `MetricOrder` Closure** — every measured direction-sensitive golden-metric site, including the production `top_n` cut; the stronger AST scanner; Q-10-2's no-`metric_spec` behaviour | **yes** — primary ordering semantics | yes / yes | P1 (the run's spec must be bound to be consumed) |
| **P2b** | **Secondary Metric Production Transport** — declaration, run binding, evaluation, record transport, persistence + cache-carry symmetry, interpretation availability, named refusal/absence | **yes** — observational secondary evidence | yes / yes | P1; **P2a** (so the primary migration is never duplicated) |
| **P3** | **Proposer Typed Evidence + Prediction Authoring** — one typed proposer-facing evidence value consumed by BOTH entrypoints; the legacy renderer fed through an adapter; direction-aware authoring grammar | **yes** — proposer↔interpreter evidence | yes / yes | P2b (so no evidence field is ever wired into two readers) |
| **P4** | **Health Evidence Declaration Migration** — the three per-check-NAME tables become declaration-driven; the duplicated default constant removed | **yes** — Health evidence persistence | yes / yes | independent; needs P1 only to *demonstrate* on a second task |
| **P5** | **Interpretation Carried-State Closure** — `vocab_link_confirmations` ACTIVATED end-to-end; `accumulated_key_findings` normalized into `ChainState`; both projections and their merge rules; producer→consumer reachability | **yes** — interpretation-derived cross-iteration state | yes / yes | P1 (needs the carry substrate) |
| **P6** | **Three-Task Full-Chain Executable Closure** — TIDMAD, Pets and DAVIS all traverse the FINAL generic orchestration contracts; the hand-written runners retired per Q-10-5 = B | **yes** — multi-task execution evidence | yes / yes | **P1, P2a, P2b, P3, P4, P5 — all of them** |

### 20.4 Why P2 SPLITS (Q-10-1, and rev 1 was wrong here)

Rev 1 argued that splitting metric direction from secondary transport would
"migrate direction twice". **That argument is withdrawn — it is not
load-bearing.** P2a owns the primary ordering migration outright; P2b consumes
the result and is forbidden from re-migrating any of it. What remains after
removing the bad argument is the real distinction:

| | P2a | P2b |
|---|---|---|
| what it decides | which model is **better** | what is **observed** about a model |
| failure if wrong | the wrong model wins — a scientific inversion | evidence is missing or misleading — never a wrong winner |
| ordering participation | **is** the ordering | **forbidden** from ordering |
| changes when… | a direction-sensitive consumer is added | a task declares a new secondary |

Two failure classes, two independently changing owners. They share
`MetricSpec`, and sharing a type is not sharing an owner.

### 20.5 Why P1 does NOT split

The composition value, the migration of the implicit defaults, and the emission
of the existing binding transport are **the same authority seen at three
depths**. Splitting them would leave, at the intermediate head, either an
explicit binding that **stops at the process boundary** (bound in-process,
ambient in every subprocess) or a run in which **some authorities are explicit
and others ambient** — both of which are worse than the state P1 replaces.
P1 is one child with one semantic owner.

### 20.6 Why the others stay separate

* **P3 separate** — a node-boundary redesign with its own Gate-1 exposure.
  Merging it into P2 would produce one PR that changes both what is compared
  and what the LLM is told; that is the shape review cannot hold.
* **P4 separate** — small, self-contained, no dependency on the composition
  value, and its own failure class (persisted evidence completeness).
* **P5 separate** — one coherent owner (interpretation-derived carried state)
  whose failure class is *reachability*, which no other child tests.
* **P6 separate and LAST** — it is **evidence**, not new semantics. Running the
  three-task closure before the proposer evidence contract is migrated and then
  calling Step 10 generic would be exactly the claim this design refuses.

### 20.7 The rule every child must satisfy

```text
establish ONE authority
  → migrate its consumers
  → remove the superseded authority
  → leave master semantically coherent
```

**And the anti-rule:** do not split a producer from its required consumer if
the intermediate repository would contain a fake, unreachable or duplicated
feature. This is why P2b carries secondaries all the way to the interpreter in
one child, and why P5 must not land "a field" without its consumer.

### 20.8 Sequencing — FROZEN at parent level

```text
P1  →  P2a  →  P2b  →  P3                    ┐
                                              ├→  P6   (LAST, always)
P4  ┐                                         │
P5  ┘  in parallel, once their own deps hold  ┘
```

**P6 is last, unconditionally** — unless the post-merge reconciliation proves a
child was removed from Step 10 entirely. Seven children is the frozen
parent-level decomposition; the *implementation-owning* child designs remain
NOT FROZEN until Step 09.5a merges, master is re-audited, symbol and module
locations are reconciled, and these boundaries survive that reconciliation.

---

## 21. Intermediate-repository coherence

A child boundary is only legitimate if master is *semantically coherent* after
it merges. Checked explicitly for each candidate:

| after this child merges | is master coherent? | why |
|---|---|---|
| **P1** | yes | every Step-10-owned semantic family is bound explicitly; TIDMAD binds to exactly what it binds implicitly today, so behaviour is unchanged and nothing is half-built. The binding does not stop at the process boundary, because emission is in the same child |
| **P2a** | yes | direction is consumed everywhere it is decided; no consumer is left half-migrated, and no second ordering authority exists at any point |
| **P2b** | yes | secondaries are declared, bound, evaluated, persisted, carried **and** rendered in the same change — no populated-but-unreachable field, and no unfilled live contract, exists at any intermediate head |
| **P3** | yes | one typed evidence value, both entrypoints migrated onto it, the legacy renderer fed through an adapter; the duplicated raw-dict reader is gone rather than deprecated-in-place |
| **P4** | yes | evidence persistence is declaration-driven for every check, including TIDMAD's six, with verdicts bit-identical |
| **P5** | yes | producer→digest→projection→carrier→consumer is closed for both items in one change, and proven reachable rather than present |
| **P6** | yes | adds evidence, removes a bypass, retires an alternate orchestration path whose every claim has a named surviving owner |

**The one ordering that would break coherence, and is therefore forbidden:**
landing a secondary-metric *record field* in one child and its *evaluation and
consumption* in another. The intermediate repository would declare a live
contract nothing fills — the precise failure `vocab_link_confirmations` is
today, and the reason §14 of Step 09a refused to populate it early.

---

## 22. Validation strategy — by failure class

**No repeated broad suites.** Each claim gets its *cheapest authoritative*
owner; a Gate is used only where cheaper evidence genuinely cannot prove the
claim.

| failure class | cheapest authoritative owner | why nothing cheaper suffices |
|---|---|---|
| a binding resolves to the wrong implementation, or silently to TIDMAD | deterministic unit tests over the composition value, incl. unknown/misspelled/absent references | no execution needed |
| a task-name branch or central table reappears | **structural census** (AST), with a planted offender | behaviour is identical either way — no test can see it |
| a direction site was missed | AST scanner over the post-migration surface (09a-C3's, not the presence list) — §3.3 proved the presence list misses live sites | a list can only find what someone remembered |
| direction is wrong for a task | three-task L1 fixtures with **hand-computed** literals, incl. DAVIS lower-is-better and TIDMAD negative-valued higher-is-better | a fixture computed by the code under test proves nothing |
| a secondary influenced ordering | the existing executable invariant (no ordering expression takes a secondary as operand), kept green **after** values become real | — |
| a carried value stops reaching its consumer | deterministic cross-iteration lifecycle test over the digest→projection→carrier→consumer chain | this is the `vocab_link_confirmations` failure class exactly |
| persisted Health evidence is blank for a task | contract test asserting completeness for a **non-TIDMAD** check name | TIDMAD passes today and would hide it |
| the binding never reaches a subprocess | reachability test that fails when the parent stops emitting the flag | `transport_argv`'s zero callers is this failure, undetected |
| the real multi-task lifecycle breaks | **Gate 2**, per the current gate standard | nothing cheaper models real data + GPU + resume together |
| an LLM-facing delta appears | prompt-byte parity, else **Gate 1** — per child, per the standard | — |

**Gate assignment is not made here.** Each child takes its Gate disposition from
`docs/gates/gate_testing_standard.md` and roadmap §17.0 at freeze time, with the
assignment row quoted. Two things are already clear, and are recorded as
expectations rather than assignments:

* **P3 is the child most likely to require Gate 1**, because it changes what the
  proposer is told.
* **P6 is Gate-2-shaped by construction** — it *is* the multi-task execution
  evidence.

**Explicitly forbidden: TIDMAD-only Gate evidence used to support a genericity
claim.** §22.13's multi-track governance and the D14/08c precedent both apply —
a claim about a generic interface needs evidence from a task that would break if
the interface were not generic.

**CI economy is unchanged**: targeted tests + structural guards during
implementation; **ONE** exact-head CI per final child head.


### 22.1 Per-child evidence ownership (FROZEN)

| child | primary evidence owner | explicitly NOT required |
|---|---|---|
| **P1** | deterministic composition tests (resolution, fail-closed on unknown/absent/misspelled) + structural census + a reachability test for the emitted transport + **REQUIRED: exact LLM-facing byte parity of the UN-COMPOSED path** (call count · order · labels · methods · system bytes · user bytes · structured inputs). A byte delta is a **preservation FAILURE to diagnose and fix** — a real Gate 1 is NOT a substitute for broken deterministic parity. If implementation discovers an *intentional* LLM-facing semantic change is necessary, that is a MATERIAL DEVIATION → operator stop. Expected posture: parity PASS ⇒ Gate 1 NOT REQUIRED *(R-1, operator-authorized correction 2026-08-20)* | a real Gate — nothing here needs GPU or real data, and parity is mandatory rather than Gate-substitutable |
| **P2a** | three-task L1 fixtures with hand-computed literals + the AST scanner | a Gate; direction is deterministic |
| **P2b** | deterministic transport + carry-symmetry tests + the ordering-operand invariant kept green | a Gate |
| **P3** | typed-contract tests on **both** entrypoints + prompt-byte parity for the legacy adapter | Gate 1 **only if** parity cannot be proven — this is the child most likely to need it |
| **P4** | completeness contract test on a **non-TIDMAD** check name + a TIDMAD verdict-manifest comparison | a Gate |
| **P5** | **deterministic lifecycle test with temporal depth ≥ 3** — the primary owner | **a 3-iteration real Gate is NOT automatically required** (Q-10-3); only if the gate standard names a unique failure class deterministic evidence cannot prove |
| **P6** | **Gate 2** — the final real multi-task executable evidence | — |

**Two rules that bind every child:**

* **No TIDMAD-only Gate may support a genericity claim.** P6 must include real
  contrast-task evidence sufficient to prove the generic interface; roadmap
  §22.13's multi-track governance and the D14/08c precedent both apply.
* **Targeted owners during development; ONE canonical exact-head CI per child.**
  No repeated full local suite by habit.

**Gate assignment itself is not made here.** Each child takes its disposition
from `docs/gates/gate_testing_standard.md` and roadmap §17.0 at freeze time,
with the assignment row quoted.

### 22.2 Runner retirement is an evidence transfer, not a deletion (Q-10-5 = B)

P6 retires the hand-written Pets/DAVIS full-execution runners **as alternate
production paths**. The required order is non-negotiable:

```text
enumerate EVERY distinct claim the runner currently proves
  → name the surviving P6 / generic-loop owner for each claim
  → only then retire the alternate orchestration path
```

**May survive** — small reusable fixtures, data preparation, narrow Health
helpers, test utilities — **only** where each owns a distinct failure class and
is no longer an alternate orchestration path. Hundreds of lines of duplicate
orchestration may **not** be retained under the label "harness". Leaving a
generic loop path plus two hand-written full task execution paths to drift
indefinitely is the outcome this ruling exists to prevent.

---

## 23. Step-11 boundary — what Step 10 deliberately leaves

Step 11 owns **execution infrastructure**: spawn/IPC/rlimits, sandbox
directories and cleanup globs, runtime-control fallbacks, and calibration
precedence (with the env override preserved).

| item | why it is Step 11, not Step 10 |
|---|---|
| `core/sandbox_executor.py`'s TIDMAD data-dir handling (it ignores `--data_dir`) | infrastructure resolution, not run composition |
| cleanup globs and sandbox dir layout | deliverable/infra mechanics |
| runtime-control fallbacks and calibration precedence | measurement infrastructure; 07c/RT debt is separately owned |
| rlimit role defaults | infrastructure |

**The one edge Step 10 touches deliberately**: it must **emit** the task-binding
transport that Step 11's children already parse (`--task_data_path_id`, parsed
in all three children, emitted by nobody). That is *using* the existing
transport, not redesigning it. If emitting it turns out to require reshaping the
argv builder, that reshaping is Step 11's and Step 10 records the finding rather
than absorbing it.

---

## 24. Step-12 boundary — what Step 10 must NOT claim

| Step 10 claims | Step 12 claims |
|---|---|
| every interface Step 10 introduces or modifies supports TIDMAD, Pets and DAVIS through the SAME contract with **zero task-identity branch** | an entirely **out-of-tree** task package supplies the full set and runs the complete system with **zero SIDERIUS core edits** |
| a conforming new task binding for a Step-10-owned interface needs config/plugin declaration only | one **reference** supplies the whole set — the unified composition root across all plugin families |
| the set of run bindings is explicit, typed and fail-closed | where that set comes from, externally |

**Concretely deferred to Step 12**: the out-of-tree task **package** as the
SOURCE of the whole binding set; the unified composition root; and the
`core/resume.py:61` private import of
`workflows.model_exploration._add_plugin_to_registries`.

**Explicitly NOT deferred** (operator ruling §10, correcting rev 1): the
`task_description` / `forward_contract` **interface**. Step 10 makes it an
explicit generic run binding; the `configs/task_config.yaml` module-global
singleton may survive only as a **legacy compatibility adapter**, never as the
semantic authority for a composed Step-10 run. Step 12 does not "make
`task_description` generic later" — it makes the SOURCE of every already-generic
binding external and unified.

**The forward obligation, stated as a rule**: *no "we will make it generic
later" debt is acceptable for an interface Step 10 itself introduces.* If a
Step-10 interface would have to be replaced by Step 12 rather than extended by
it, the interface is wrong and must be redesigned before it freezes.

**The test to apply at each child's freeze**: can Step 12 supply this
interface's values from an external package without changing the interface? If
not, why not — in writing.

---

## 25. Risks

| # | risk | why it is credible here | mitigation |
|---|---|---|---|
| R1 | **The composition value becomes the new 99-parameter bag.** | It is the natural place to put "everything a run needs", and the project has done this before. | §19's prohibitions; the composition value holds **bound authorities only**, and the derived ownership guard already refuses chain-state fields. A per-child ownership inventory before freeze. |
| R2 | **A central task table appears disguised as composition.** | A dict keyed by task id is the shortest path to "bind three tasks". | §11's invariant + a structural census with a planted offender. The registry is keyed on **binding presence** and on ids the implementations declare about themselves. |
| R3 | **Direction migration misses a site.** | §3.3 measured that the current census misses four live sites, one of them the chain incumbent advance. | Replace the presence list with the AST scanner; DAVIS's lower-is-better fixtures make a miss *inverting*, not silent. |
| R4 | **Secondaries silently acquire a vote.** | Once values are real, "use the best macro_f1" is one plausible-looking line away. | Keep 09a's ordering-operand invariant green after activation; it is the cheapest possible owner. |
| R5 | **Activating a feature that should be retired** (`vocab_link_confirmations`). | Implementations prefer building to deleting. | It is an operator question (Q-10-3), not an implementation choice. |
| R6 | **Step 10 quietly becomes Step 12.** | The last mile from "explicit binding set" to "one external reference" looks small. | §24's boundary table + the freeze-time question; the packs' own Step-12 assignments are the check. |
| R7 | **Pets/DAVIS remain fixtures.** | The cheap path is to keep the Gate runner scripts and add L1 fixtures. | P6 is a separate child whose acceptance is loop execution, and §22 forbids TIDMAD-only evidence for a genericity claim. |
| R8 | **The prerequisite is assumed rather than verified.** | §3.0 found `WorkflowRunBindings` unadopted *after* it had been described as landed. | §0.2's reconciliation obligation: re-run the census against merged master before any child freezes. **DISCHARGED 2026-08-20** — the census ran against merged master `2393aacc` (§0.3), the carrier is adopted and guarded, and the risk is now *retired* rather than mitigated. The mechanism stays in force for every child freeze. |
| R9 | **Health evidence regresses for TIDMAD during the table migration.** | Three tables, six checks, one refactor. | Verdict-manifest comparison, the mechanism 08a/08b already used. |
| R10 | **Retiring the Gate runner scripts loses real evidence.** | They are the only executable Pets/DAVIS path today. | Q-10-5 = B with §22.2's discipline: enumerate every claim, name each surviving owner, *then* retire. Nothing survives as an unlabelled "harness" without a distinct failure class. |
| R11 | **P2b re-migrates ordering, creating a second direction authority.** | Secondaries carry their own direction, so the temptation to add "a small ordering helper for secondaries" is real. | §9.4 item 8 forbids it explicitly; §26 D and the AST census make it detectable. |
| R12 | **P6 runs before the semantics it is supposed to prove.** | It is the most satisfying child and the easiest to pull forward. | §20.3 / §20.8 make its dependency on **all six** predecessors unconditional; rev-1's incomplete dependency list is corrected as adversarial item 27. |

---

## 26. Acceptance criteria (parent-level, freezable)

### 26.1 Structural

* **A.** No new task-name branch in generic infrastructure. The census that
  measures **class (b) = 0** stays at 0, and gains an anti-vacuity guard. Its
  denominator must be **stated and reproducible** — currently **303 production
  `.py` files / 750 task-name occurrences** under the repository's own
  `_production_files()` definition (§3.8; rev 2's unreproducible 461/851 is
  withdrawn). The guard must be **AST-shaped**, not regex-shaped: §3.8 records
  two textual near-misses (a banner string, an implementation's own named-constant
  self-check) that a regex census flags and an AST census correctly does not.
* **B.** No new central task-specific registry, table or import list. Extending
  a *declaration* is allowed; adding a per-task entry to a framework-owned table
  is not.
* **C.** For every Step-10-owned interface, a conforming new task instance needs
  **zero** infrastructure source edits — proven by an executable extension
  proof, in the shape 08b already established.
* **D.** Existing authorities are reused, never duplicated: one `MetricOrder`,
  one metric handle, one `TaskDataPath`, one Health registration path, one
  committed-digest reader.
* **E.** Step-09.5a's three carriers remain the **sole** workflow run-state
  boundaries; no fourth carrier, no fifth resume loader.
* **F.** One semantic owner per task-binding / metric-order / carried-state
  concept, named in each child's inventory.
* **G.** Every child carries the **§19.3 structure preflight** at freeze —
  changed files, LOC + responsibility inventory, materially changed functions,
  branch/argument growth, semantic owner count, proposed module placement — and
  performs the minimum coherent decomposition **first** where two
  independently-changing owners would otherwise share a file or function.
* **H.** No child leaves a newly-created mixed-responsibility hotspot for the
  next child.
* **I.** Step 12 can consume every Step-10 interface without replacing it, with
  the freeze-time question of §24 answered in writing.

### 26.2 Functional

* **J.** Every direction-sensitive golden-metric decision consumes `MetricOrder`;
  the AST census finds zero unmigrated sites; TIDMAD (negative-valued, higher),
  Pets (higher) and DAVIS (**lower**) are each proven correct with hand-computed
  literals.
* **K.** Secondaries are declared by the task, bound per run, evaluated,
  persisted, carried **symmetrically with `failure_counts`**, rendered, and
  provably unable to affect ordering. TIDMAD's absence renders nothing.
* **L.** `vocab_link_confirmations` is **ACTIVATED** (Q-10-3 = A) and proven
  **reachable** — producer → digest → projection → `ChainState` → next-iteration
  input → the ≥ 3-run promotion condition — by a deterministic lifecycle test of
  temporal depth ≥ 3. Presence is not evidence; a test that fails when
  production stops carrying the value is. `accumulated_key_findings` is carried
  by `ChainState` like its siblings (Q-10-6 = A).
* **M.** Health evidence is complete for a non-TIDMAD check name with **no
  central table edit**, and TIDMAD's verdicts are bit-identical.
* **N.** The task binding reaches subprocesses: a reachability test fails when
  the parent stops emitting it.
* **O.** Pets and DAVIS each initialize and execute the exploration loop through
  the same generic composition, with correct binding, execution, direction,
  metric transport, persistence and resume. **No model-quality threshold is an
  acceptance criterion anywhere.**

* **Q.** A persisted artifact carrying no `metric_spec` stays **inspectable**
  and is **never ranked**, with a visible named explanation and no assumed
  direction, and without hard-failing the consumer (Q-10-2 = A). Every **newly**
  persisted artifact carries enough metric identity for a future consumer to
  rank correctly.
* **R.** Before any hand-written task runner is retired, **every distinct claim
  it proves is enumerated and each has a named surviving owner** (Q-10-5 = B).
  What survives owns a distinct failure class and is not an alternate
  orchestration path.

### 26.3 Preservation

* **P.** TIDMAD's persisted artifacts, statuses, ordering, retry and resume
  semantics are unchanged; the frozen metric formula and frozen names are
  byte-identical; every LLM-facing delta is declared, owned and Gate-dispositioned.
* **S.** The Step-06 metric-identity rule (`_is_loss_shaped`) is **not modified
  by Step 10** (Q-10-4 = A), and Pets's `log_loss` intent remains recorded
  against D16 rather than deleted.

---

## 27. Adversarial self-review

Thirty-three challenges: the twenty-five of Revision 1, re-run against the
revised text, plus the eight the operator's ruling required. **PASS** = the
design prevents it; **CORRECTED** = the review changed the design;
**RESOLVED BY RULING** = an operator ruling closed it.

### 27.1 The Revision-1 twenty-five, re-run

| # | challenge | verdict | evidence / what changed |
|---|---|---|---|
| 1 | Is TIDMAD secretly still the default/fallback task? | **CORRECTED** (rev 1) | §3.8 measured **six** implicit defaults, not one. Rev 2 further splits them: five are P1's, the physical data root is Step-11's (§3.8, §23) |
| 2 | Does a fourth task require editing infrastructure? | **PASS** | §7.3 / §18: 0 edits, with §7.2's capability-vs-instance distinction making the claim falsifiable |
| 3 | Did I create a central task registry disguised as composition? | **PASS** | §6.2 forbids a second `TaskDataPath` and one giant registry; §26 B + R2 make it executable |
| 4 | Does task identity control behaviour? | **PASS** | §11 invariant; census currently measures class (b) = 0 |
| 5 | Did I duplicate `TaskDataPath` / `MetricOrder` / Health / plugin authority? | **PASS** | §2, §26 D; §9.4 item 8 explicitly forbids P2b introducing a second order authority |
| 6 | Did I invent a second run-state carrier? | **PASS** | §10 rule 1; §12.3; §26 E |
| 7 | Did I put mutable state into the bindings / launch config? | **PASS** | the derived guard is not weakened by any child |
| 8 | Did I add another resume loader? | **PASS** | §10 rule 2; §12.3 — P5 uses the ONE authority |
| 9 | Do Pets and DAVIS really use the same path, or are they only fixtures? | **CORRECTED** (rev 1) | measured: two hand-written runners that never touch `run_workflow`. Rev 2 adds the retirement discipline (§22.2) so the duplication ends rather than persists |
| 10 | Does lower-is-better DAVIS expose any raw `max`/`>`? | **CORRECTED** (rev 1) | `proposal_helpers.py:84-89` found on the production path; rev 2 assigns it to **P2a**, not P3, because it is a shared ordering decision |
| 11 | Do secondaries accidentally affect winner selection? | **PASS** | §9.1, §9.4 item 7, §26 K |
| 12 | Does the proposer still have two independently drifting readers? | **RESOLVED BY RULING** | §11.2 is now frozen: ONE typed value, both entrypoints, adapter for legacy bytes, no raw-dict semantic ownership |
| 13 | Is `vocab_link_confirmations` actually reachable after the proposed work? | **RESOLVED BY RULING** | Q-10-3 = A. §12.1 requires every link and names the deterministic depth-≥ 3 owner |
| 14 | Did Health extensibility require editing central check-name tables? | **CORRECTED** (rev 1) | it still does today and is already latent for two shipped tasks; §13 + §26 M make completeness on a non-TIDMAD name the acceptance form |
| 15 | Did I create a giant orchestration module? | **PASS** | §19.1 + §19.3's binding preflight |
| 16 | Did I create a giant "context" object? | **PASS** | R1; the composition value holds bound authorities only |
| 17 | Are modules divided by semantic ownership rather than LOC? | **PASS** | §19.2's contrast case; §19.3's closing rule on arithmetic splitting |
| 18 | Does any proposed child mix several independently-changing owners? | **CORRECTED** (rev 2) | rev 1's P2 did — ordering and observation. Split into P2a/P2b (§20.4) |
| 19 | Does splitting children create temporary fake/unreachable contracts? | **PASS** | §21 checks each child; §20.7's anti-rule; the one forbidden ordering is named |
| 20 | Can Step 12 reuse Step-10 interfaces without replacing them? | **CORRECTED** (rev 2) | rev 1 left `task_description` ambiguous — Step 12 would have had to replace the interface. §3.2 / §24 repair it |
| 21 | Did I accidentally implement Step-11 execution concerns? | **CORRECTED** (rev 2) | rev 1's "six defaults" implied P1 removes the physical-path fallback. §3.8's split table and §23 return it to Step 11 |
| 22 | Did I claim full out-of-tree graduation before Step 12? | **PASS** | §18 closing paragraph; §24 |
| 23 | Are acceptance criteria functional rather than model-quality thresholds? | **PASS** | §16.6, §17.6, §26 O — none anywhere |
| 24 | Is every Step-09.5 class-B finding assigned honestly? | **PASS** (rev 1's CORRECTED stands) | B-1 → P3 · B-2 → P2a · B-3 → P4 · B-5 → not adopted, stays class B · B-6 → P2b as a same-child constraint. **B-4 (launcher width) remains honestly UNSOLVED** — P1 makes binding explicit and does not decompose an 85-argument parser; the audit did not require it |
| 25 | Does every new interface support config/plugin-only ordinary extension? | **PASS** | §7; §26 C requires an executable proof |

### 27.2 The eight attacks the ruling required

| # | attack | verdict | answer |
|---|---|---|---|
| 26 | **Is the P2a/P2b separation real, or two halves of one job?** | **PASS** | §20.4's table: different decisions (which is better vs what is observed), different failure consequences (a scientific inversion vs missing evidence), opposite ordering participation (is the ordering vs forbidden from it), different change triggers. They share `MetricSpec`; sharing a type is not sharing an owner. P2b is explicitly forbidden from re-migrating P2a's sites |
| 27 | **Is P6's dependency list complete?** | **CORRECTED** | Rev 1 listed P6 as depending on P1, P2, P4 — omitting the proposer child. §20.3 / §20.8 now require **all six** predecessors, unconditionally. Running the three-task closure before the evidence contract migrates and calling Step 10 generic is exactly the claim this design refuses |
| 28 | **Does the Step-10 / Step-12 task-description boundary still leak?** | **CORRECTED** | Rev 1 read the packs' "→ Step 12" rows as deferring the *interface*. §3.2 and §24 now separate interface from source: Step 10 makes it an explicit run binding; the singleton survives only as a legacy adapter; Step 12 externalises the SOURCE. The freeze-time test answers **YES** |
| 29 | **Does `campaign_artifacts` become `ChainState` by accident?** | **CORRECTED** | Rev 1's S7 wording grouped it under "artifacts travelling on the Step-09.5a substrate". §4.2 withdraws that: filesystem provenance stays filesystem provenance, gains no digest projection, and only the task-coupling residue is Step-10 scope, assigned to P1 |
| 30 | **Does P1 overclaim the physical data root?** | **CORRECTED** | §3.8's split table: P1 makes **five** of six defaults explicit; the sixth is named Step-11 infrastructure debt. P6 may use the currently supported physical execution path while still proving semantics are bound generically |
| 31 | **Does the legacy proposer path really share the typed evidence, or is it grandfathered?** | **PASS** | §11.2 items 1–5: the entrypoint is retained, the **reader** is not. Byte-exact prompts are preserved by an adapter over the typed value, never by preserving raw-dict ownership. Item 4 is the executable form: no field may ever again need wiring into two readers |
| 32 | **Is every S1–S8 item assigned to exactly one child?** | **PASS** | §4.1's map: S1→P1, S7→P1, S2→P2a, S3→P2b, S4→P3, S6→P4, S5→P5, S8→P6. Eight items, seven children, **zero orphans** and zero shared ownership |
| 33 | **Does P5's ≥ 3-iteration requirement quietly become a heavy real Gate?** | **PASS** | §12.1 and §22.1 both state it: the PRIMARY owner is a deterministic lifecycle test with temporal depth ≥ 3. Temporal depth is a property of the test, not of the GPU. A real Gate is used only if the gate standard names a unique failure class deterministic evidence cannot prove |

**Score: 33/33 addressed — 20 PASS, 11 CORRECTED, 2 RESOLVED BY RULING.
Material contradictions: 0. Open operator questions: 0.**

### 27.3 Two corrections Revision 1 made that Revision 2 preserves

* **`campaign_artifacts` is not what its roadmap label implies.** No such schema
  field exists; the module is a `run_comparison.py`-only Phase-1 reuse mechanism
  that never touches the iteration boundary. Re-scoped, not adopted as written.
* **The prediction track record is not the proposer's direction defect.** It is
  direction-agnostic by construction — re-verified at merged master: no spec
  parameter and no comparison operator anywhere in its body. The real defect is
  one `reverse=True` on the production path (`proposal_helpers.py:88`), now
  owned by P2a. *(Post-merge correction: rev 2 also said it "is not called in
  production at all". That is wrong — the interpreter calls it at
  `rendering.py:980` on every iteration; only the proposer's call at
  `ml_model_proposal_agent.py:1157` is unreached. The direction-agnosticism,
  which is the half this bullet rests on, is unaffected.)*

### 27.4 Post-merge adversarial re-run (2026-08-20, against merged master `2393aacc`)

The §0.3 reconciliation re-ran the adversarial review from scratch against
merged source. **28 attacks, 28 closed: 24 PASS · 4 CORRECTED · 0 MATERIAL
CONTRADICTION.** Every CORRECTED item is a source-fact repair already applied
in §3; none moved a boundary.

| # | attack | verdict | evidence at merged master |
|---|---|---|---|
| 1 | Is TIDMAD still an implicit default? | **PASS** | Yes — and that is the *problem statement*, not a design leak. All six defaults re-verified implicit; zero operator flags exist to override any of them. P1 removes five, Step 11 owns the sixth |
| 2 | Does a fourth ordinary task require infra edits? | **PASS** | §7.3 / §18 / §26 C unchanged; the 08b out-of-tree extension proof is the established shape |
| 3 | Did composition become a task table? | **PASS** | §6.2 + §26 B. §3.8's re-audit surfaced the ONE framework table holding a task word — `_SCOREABILITY_CONTRACT_TYPES` keyed on `contract_id` — and named it explicitly so §26 B is read against it deliberately |
| 4 | Does task identity control behaviour? | **PASS** | class (b) = **0**, re-confirmed by an AST census stronger than the original grep (§3.8) |
| 5 | Is `TaskDataPath` duplicated? | **PASS** | one registry, one protocol; §3.8 re-verified both ends of the transport exist and only the join is missing |
| 6 | Is `MetricOrder` duplicated? | **PASS** | one interpreter (`execute_tools/metric_order.py:59`); §9.4 item 8 forbids P2b adding a second |
| 7 | Is Health authority duplicated? | **PASS** | one registration path; P4 removes the residual central tables rather than adding an authority |
| 8 | Is there a fourth run-state carrier? | **PASS** | exactly three, re-measured 24 / 72 / 11; §10 rule 1 + §26 E |
| 9 | Is there another committed-digest loader? | **PASS** | `core/committed_digests.py` is the ONE reader with **one** production caller (`core/resume.py:1353`); four pure projections downstream |
| 10 | Are mutable fields hiding in immutable bindings? | **PASS** | both frozen carriers derive their deny-list from `chain_state_field_names()` at `__post_init__`; two planted offenders CAUGHT in 09.5a |
| 11 | Does DAVIS expose a higher-is-better assumption? | **CORRECTED** | re-verified `mse` **lower** / `psnr` higher / `mae` lower. And re-measured, the exposure is **larger** than rev 2 recorded: 6 of 11 direction sites are invisible to the census, not four (§3.3 #4) |
| 12 | Can secondaries influence winner selection? | **PASS** | §9.1 / §9.4 item 7 / §26 K; producing side still `secondary_metrics=[]`, so the invariant is green today and must stay green after activation |
| 13 | Do proposer legacy and pipeline paths still mine raw dicts separately? | **PASS** | yes, still — **40 + 11** `.get(` re-counted exactly; §11.2's ruling stands unchanged |
| 14 | Is `vocab_link_confirmations` truly reachable? | **PASS** | still inert at merged master: 0 in `core/`, 0 in `model_exploration.py`, absent from all 11 `ChainState` fields, not passed at `model_exploration.py:1934-1978`. P5 owns activation |
| 15 | Does `accumulated_key_findings` use `ChainState`? | **PASS** | no — still a bare `run_workflow` param (`:1396`) read at `:2107-2115`, absent from `ChainState`. Q-10-6 = A, owned by P5 |
| 16 | Does Health require central task/check-name edits? | **PASS** | yes, still — all three tables re-verified, none naming any Pets or DAVIS check, and the `5` vs `25` duplicate-threshold disagreement intact. P4 owns it |
| 17 | Is campaign provenance confused with `ChainState`? | **PASS** | §4.2 unchanged; re-verified no schema field, one production consumer, **zero** manifest readers |
| 18 | Did Step 10 absorb Step-11 execution mechanics? | **PASS** | §3.8 default 6 and §23 unchanged; `TidmadSandbox.__init__` re-verified to take no `data_dir` at all, confirming this is infrastructure resolution, not run composition |
| 19 | Does Step 12 reuse rather than replace Step-10 interfaces? | **CORRECTED** | §24 unchanged, but §3.2's re-audit found the `task_description` interface reaches prompts through **two mechanisms across four node families**, not one placeholder. Step 12 can still supply the same interface; P1's job is more constrained |
| 20 | Do Pets/DAVIS truly enter the final exploration loop? | **PASS** | not today — re-verified zero matches for `run_workflow`/`restore_prior_state`/`ChainState`/proposer/interpreter in either runner. P6 owns it and is LAST |
| 21 | Are task-specific runners retired only after ownership transfers? | **PASS** | §22.2 / Q-10-5 = B unchanged |
| 22 | Does any child create a mixed-responsibility hotspot? | **PASS** | §19.3's preflight is binding at every child freeze and has not been run for any child yet — correctly, since no child may freeze before this review |
| 23 | Does P2a/P2b separation still reflect source ownership? | **PASS** | yes: the ordering sites (§3.3) and the secondary transport (§3.4) are disjoint source surfaces with disjoint failure classes |
| 24 | Is P6 actually last? | **PASS** | §20.3 / §20.8 — depends on all six, unconditionally |
| 25 | Does every Step-10-owned interface admit config/plugin-only extension? | **PASS** | §7 / §26 C unchanged |
| 26 | Is every parent scope item assigned exactly one child? | **PASS** | §4.1 re-checked: 8 items, 7 children, 0 orphans, 0 shared |
| 27 | Did post-09.5a topology invalidate any frozen parent assumption? | **PASS** | **no.** The one assumption at risk — that the carrier substrate exists — was the *only* thing 09.5a changed, and it changed from absent to present (§3.0). Nothing else §3 cites moved semantically |
| 28 | Are any source counts or stale paths still quoted as current facts? | **CORRECTED** | this attack found the most: the 461/851 denominator, `derive_tidmad_metric`'s call-site count, the census recount, `bind_task_data_path`'s caller count, the `{FORWARD_CONTRACT}` token, the track record's production reachability, and ten line-anchor drifts. **All repaired in §3 and registered in §0.3.2.** |

**Two attacks from the operator's list are answered elsewhere and are recorded
here so the list is complete rather than silently short**: the *runtime
verifier / Health-isolation / `validation_max_samples`* findings from 09.5a are
**named 09.5a debt and explicitly NOT Step-10 scope** (§28), and the *watchdog*
finding is closed as a Gate posture defect with 07c demonstrably not regressed
— neither is reopened here.

**Cumulative adversarial position: 33 (rev 2) + 28 (post-merge) = 61 challenges
recorded, 0 material contradictions.**

---

## 28. Operator questions — ALL RESOLVED

**Open: 0.** Every question rev 1 raised was answered by the operator ruling of
2026-08-20 and is recorded in §0.0. Their consequences are implemented in this
revision at:

| id | ruling | where it lands |
|---|---|---|
| Q-10-1 | seven children; P2 splits; P1 does not | §20 (whole section), §4.1 |
| Q-10-2 | A — refuse to rank; visible named explanation | §8, §26 J/Q |
| Q-10-3 | A — ACTIVATE, deterministic depth-≥ 3 owner | §12.1, §22.1, §26 L |
| Q-10-4 | A — no Step-06 rule change; D16 stays open | §9.3, §16.3 |
| Q-10-5 | B — retire the runners after claim transfer | §22.2, §26 R |
| Q-10-6 | A — `accumulated_key_findings` → `ChainState` | §10, §12.2 |

**One item is deliberately carried as a NAMED EXTERNAL OPEN QUESTION, and it is
not Step 10's**: **D16** — the Step-06 loss-shaped metric-identity rule that
makes Pets's `log_loss` secondary undeclarable. It is recorded here so it is not
lost, and it does not block Step 10.

**Two findings were carried for other owners; one is now CLOSED:**

* ~~**Step 09.5a C3** (§3.0) — `WorkflowRunBindings` unadopted.~~ **CLOSED.**
  Reported through PR #240 and repaired *there*, in commit `52ed46b1`, exactly
  as intended: the carrier is now constructed once at
  `workflows/model_exploration.py:1777` and is the source of truth for 50 reads,
  with a dedicated adoption guard and the C0 differential oracle still deep-equal.
  Step 10 absorbed no scope. See §3.0's status block and §0.3.
* **Audit class-B item B-4** — launcher width (85 CLI args / 780-line
  `build_parser`). Honestly unsolved by Step 10 and honestly not required by the
  audit.

**Three findings from the Step-09.5a Gate are NAMED DEBT and explicitly NOT
Step-10 scope** (recorded 2026-08-20 during the post-merge reconciliation, so
that proximity of discovery is not mistaken for assignment of ownership). None
of them is assigned to Step 10 anywhere in the repository today, and none may
be absorbed into a Step-10 child:

| finding | owner | why not Step 10 |
|---|---|---|
| the **runtime verifier** expresses its caps in *steps* while its evidence minimum is expressed in *time*, so a very fast phase may never verify | runtime-control (RT / 07c lineage) | a measurement-infrastructure concern; §23 puts runtime-control fallbacks in Step 11 and the RT debt is separately owned |
| **Gate-standard / Health-isolation tension** — a Gate small enough to be functional may be structurally incompatible with scientific Health acceptance; 09.5a's lifecycle Gate used supported Health isolation for its own failure class | the gate standard (`docs/gates/gate_testing_standard.md`) | a Gate-methodology question, not a task-binding one. Each Step-10 child still takes its Gate disposition from the standard at freeze time (§22) |
| **`validation_max_samples`** — its effective cost is model-geometry-dependent | runtime-control / admission (the §7e pre-run validation-pricing debt) | already an OPEN named debt with a stated owner; approximating it from the training measurement by a fixed ratio is explicitly forbidden |

**And the watchdog finding is CLOSED, not carried.** The Step-09.5a forensics
established that **Step 07c is NOT regressed**: measurement-backed validation
predictions were published, the live deadline moved materially in response, and
provider replay reconciled exactly with the runtime-control arithmetic. The
repeated kills came from **Gate posture/configuration**, and the one narrow
reporting defect found (a diagnostic naming a SATISFIED condition as the
failure) was repaired and has landed. **Step 10 does not reopen 07c**, and this
is not Step-10 scope.

---

## 29. Document status

**REVISION 2 — FROZEN. OPERATOR APPROVED — PARENT SEMANTICS ONLY.**

| | |
|---|---|
| revision | **2 — FROZEN**, post-merge reconciliation **PASS** (§0.3); **three targeted corrections R-1/R-2/R-3 applied 2026-08-20 (operator-authorized; acceptance/wording only — §22.1 P1 parity obligation, §3.8 default-4 ownership split, §8 order-acquisition precedence). Freeze unchanged; NOT Revision 3** |
| child designs status | **P1 REVISION 2 FROZEN → IMPLEMENTED → MERGED 2026-08-20 (squash `bcb17e45`, PR #241, CI 32415952195)** · **P2a REVISION 3 FROZEN → IMPLEMENTED → MERGED 2026-08-21 (PR #242, squash `e094fa26`, exact-head CI 32431989276 SUCCESS on `b50bec6a`; merged master byte-identical to the validated head; final operator review PASS)** — the golden-metric ordering surface went **12 measured sites → 0** (the C0 AST scanner found 2 chain-fold sites in `core/resume.py` invisible to every prior audit); `reconcile_metric_spec` PROMOTED to `execute_tools/evaluation_metric.py` as the ONE reconciliation authority (one engine, spec-level + record-level `(metric_id, direction)` entry points); four-case unrankable semantics at every persisted-artifact consumer; proposer `top_n` direction-aware with the Q-P2a-1 order-free `all` fallback; scanner = standing guard, direct + alias plants RED at the final head. **D-P2a-4 ACCEPTED/BOUNDED** (`MetricOrder` body unchanged; only the accepted declaration annotation widened to the §4.4 minimum identity); **F-P2a-4 RESOLVED** (zero TIDMAD derivation sites added — CI caught the attempt, the derivation was deleted, never census-widened); five test-fixture generations upgraded to carry persisted identity. Post-P4 reconciliation MERGE-BASED (merge `553bd66c`, 0 conflicts, force push NOT used, honoring the repo guardrail); Gate 1/2 NOT REQUIRED, not run · **P2b REVISION 3 FROZEN → IMPLEMENTED → MERGED 2026-08-21 (PR #244, squash `5a2ecfd1`; final executable head `f6a73afd` CI 32439134908 SUCCESS, final PR head `41eeff60` CI 32444963507 SUCCESS with 11,318 passed / 33 skipped; merged master byte-identical to the validated head; operator final review PASS)** `pr_10_p2b_secondary_metric_transport.md` — architecture review PASS on rev 2 (post-P2a/P4 reconciliation: PROVISIONALs resolved; the record/output carrier adopts the THREE names the 09a receiving side itself reserves — `secondary_metric_results` / `secondary_metric_refusals` / `secondary_metric_specs`; eight-section all-`[ ]` commit plans C0–C4). Rulings: **Q-P2b-1 = WHEREVER_PRIMARY_EVALUATES** (no round-type branch); **Q-P2b-2 RESOLVED with the scope-violation correction** — NotScoreableError → typed refusal · ScopeViolationError → RE-RAISE to the existing outer handler, never downgraded · other Exception → `secondary_metric_errors` dict (diagnostic provenance, no new model, stderr/log surface only, projects `unavailable`), 'observational' explicitly bounded to ordinary secondary outcomes; **Q-P2b-3 = _STATS_SUFFICIENT** — digest NOT widened, and the false 'P5 territory' default-ownership wording removed; **C-P2b-1**: zero-secondary serialization audited (output `model_dump()` serializes empty defaults) ⇒ SEMANTIC emptiness frozen, no cosmetic byte-identity machinery. Gate 1 + Gate 2 NOT REQUIRED (frozen), and neither was run. Open questions 0; contradictions 0. **DELIVERED**: the composition/binding/evaluation/transport/projection/carry/render lifecycle end-to-end, six IR-P2b rulings, two ACCEPTED bounded deviations (G5 re-pointed to the commit that trips it; four out-of-scope baselines carried the frozen §4.7 additive-empty serialization delta, applied key-by-key and never regenerated), and findings F-P2b-1..4 — of which **F-P2b-4** (anchored-symbol censuses blind to a name prefix) is carried forward as separate test-infrastructure debt, deliberately NOT swept repo-wide** · **P3 / P5 DRAFT rev 1 (2026-08-20, anchor `d7d94740`)** — P3 `pr_10_p3_proposer_typed_evidence.md` (one typed proposer evidence value produced by the protocol; direction-safe prediction-authoring grammar as the declared intentional LLM delta; reconciles after P2a+P2b) · **P4 REVISION 3 — FROZEN → IMPLEMENTED → MERGED 2026-08-20 (PR #243, squash `79833db8`, exact-head CI 32426702255 SUCCESS on `d73e39e3`; merged master byte-identical to the validated head; independent final review PASS)** `pr_10_p4_health_evidence_declaration.md` (post-P1 reconciliation at `64446b2b`; `evaluation.py`'s name-keyed tables + duplicated defaults + sampling literal become per-check declarations, and `evaluation.py` moves into the health-core census's GENERIC partition as the executable acceptance. Rulings: **Q-P4-1 = (a) fallback-only `check_default` label**, shipped TIDMAD rows byte-identical; **Q-P4-2 = YES**, `_WORST_STAT_BY_METRIC` + the unit-exactness literal absorbed as DERIVATIONS from the declared operator/unit — a table deleted, no field added, never a relocated map (R-7); **Q-P4-3 = DEFER BOTH**, HD-T5 / HD-T6 named post-Step-10 Health-capability debt, explicitly NOT P6 and NOT assumed Step 12; **C-P4-1 resolved** by the §13 scope-completeness correction — semantic owner, child decomposition, scientific Health semantics, public schema and P4/P2a parallelism all UNCHANGED. Adversarial 23 CLOSED / 2 CORRECTED / 0 open; 0 contradictions; Gate 1 + Gate 2 NOT REQUIRED; **SAFE TO IMPLEMENT IN PARALLEL WITH P2a**, competing semantic owners = 0) · P5 `pr_10_p5_interpretation_carried_state.md` (both parent-assigned values ride the sibling lifecycle; confirmations aggregation SOURCE-derived: producer-side keyed union ⇒ latest-wins projection; freezes after P3) · **P6 SKELETON ONLY** `pr_10_p6_three_task_closure_skeleton.md` (detailed design BLOCKED until P1/P2a/P2b/P3/P4/P5 merge) — `step_10_orchestration_task_binding/` |
| source anchor | **merged master `2393aacc`** |
| Step-10 implementation | **NOT STARTED** |
| prerequisite | Step 09.5a **MERGED** (PR #240) — the §15.1b/§15.1c block is **LIFTED** |
| child designs | **NOT FROZEN** — the §0.2 reconciliation is now discharged; what remains is **operator review**, then P1 |
| open operator questions | **0** |
| material contradictions | **0** |
| adversarial review | **33/33** (rev 2) **+ 28/28** (post-merge, §27.4) = **61 challenges, 0 contradictions** |
| children | **7** — P1 · P2a · P2b · P3 · P4 · P5 · P6 (**unchanged by the reconciliation**) |
| scope items | **8**, each with exactly one owner (§4.1), zero orphans |
| **next action** | **OPERATOR REVIEW OF THIS PARENT**, then the detailed **P1** child design against merged master |

**What this freeze covers**: parent semantic scope, ownership, acceptance, and
the parent-level seven-child decomposition with its sequencing.

**What it does NOT cover**: exact child module names, exact function names,
source line anchors as future implementation authority, child per-commit plans,
and any implementation-owning child design.

**Reopening rule (§0.2)**: if the post-merge reconciliation finds only moved
lines, symbols or mechanical call sites, this revision stays frozen and the
child design uses current source. If a parent-level semantic boundary or an
accepted child ownership no longer holds, the parent is reopened as
**REVISION 3** rather than defended as stale freeze text.

**The rule was applied, not assumed.** The reconciliation ran (§0.3) and found
**11 discrepancies, 10 mechanical and 1 already-consistent, and 0 semantic
contradictions**. Four of them made the design's own findings larger rather
than smaller. Under the rule's own first branch, **REVISION 2 stays FROZEN** —
this is a verdict reached by re-measurement, not a freeze defended by silence.
Had any ownership boundary moved, this document would say REVISION 3.
