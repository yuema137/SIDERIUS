# Step 10 / P5+P6 — Lifecycle Closure + Three-Task Closure

## 0. Status

**REVISION 2 — FROZEN. OPERATOR APPROVED (final freeze review, 2026-08-21).
IMPLEMENTATION NOT STARTED. Open operator questions: 0.**

Revision 2 applies the operator's final freeze review of DRAFT rev 1
(architecture / consolidation / lifecycle / validation-topology all PASS; no
redesign, no re-split) — the rulings and seven bounded corrections, recorded
verbatim in §19:

| ruling / correction | disposition |
|---|---|
| **Q-P56-1** | **B — roadmap-depth Step-10 closure.** CAP-SCOPE becomes an explicit REQUIRED prerequisite for contrast-track L4 (§10.2); parent §16.1/§17.1/§26.O amended |
| **Q-P5-1** | **APPROVED — malformed ⇒ RAISE** (§8.2); no longer overturnable, question count 0 |
| **C-P56-1** | **W4 must NOT branch on `TIDMAD_METRIC_ID`** in generic composed mode — the rule is composition-presence, never metric identity: legacy/un-composed byte-for-byte; ANY composed run carries NO implicit legacy reference science (§10.5) |
| Gate 1 | **NOT REQUIRED**, flip condition frozen (§15.1) |
| Gate 2 | **REQUIRED** — composed TIDMAD, 2 iterations × 1 round, **AUTONOMOUS launch inside the pre-authorized ≤ ~1 h envelope** (the pre-Gate operator stop is DELETED), with the **non-vacuous two-layer restore-evidence contract** (§15.2) |
| retained Pets/DAVIS L3 evidence | **freshness contract** — provenance + semantic dependency diff, bounded rerun only if a semantics-bearing dependency changed (§10.6, C7) |
| C6 honesty | Pets/DAVIS closure is **ORCHESTRATION closure**, never contrast L4; the pseudo fixture's training/data-selection content is NOT evidence of task-correct contrast training scope (§10.3, C6) |
| structure | ruling accepted (no proactive decomposition) + the **implementation tripwire** frozen (§12.1) |

This document is the ONE authoritative design for the remaining Step-10
implementation work. It supersedes and replaces BOTH prior drafts:

| superseded doc | its final state | disposition |
|---|---|---|
| `pr_10_p5_interpretation_carried_state.md` | DRAFT rev 1, architecture-review PASSED, `PROVISIONAL(P3)`, never frozen | content reconciled into §5–§9 and §13 (C0–C4); file REMOVED in the consolidation commit (§18 maps every section) |
| `pr_10_p6_three_task_closure_skeleton.md` | SKELETON ONLY, detailed design deliberately blocked until the semantic children merged | content reconciled into §10–§11 and §13 (C5–C8); file REMOVED in the consolidation commit (§18 maps every section) |

**Consolidation authority**: operator instruction 2026-08-21 — merge the two
remaining children into ONE implementation child once P3 merged, with a fresh
source audit rather than a mechanical concatenation. Recorded as a
parent-level topology amendment in the parent's §20 (docs/design
consolidation, not a semantic ownership change: S5 and S8 keep their frozen
definitions and now share one owning implementation child).

| field | value |
|---|---|
| parent | Step-10 parent REVISION 2 (frozen) + the 2026-08-21 consolidation amendment (§20.9) + the Q-P56-1 = B acceptance amendment (parent §16.1/§17.1/§26.O); owns scope items **S5** (interpretation-derived carried state) and **S8** (three-task executable closure, delivered at the §10.2 depth) |
| source anchor | merged `master` = **`ec6257fb`** (== `origin/master` at audit time; production tree == P3 squash `254cbaa1` + the docs-only sync). Every §2 measurement was taken at this anchor; the rev-2 freeze corrections are docs-only, so the anchor is unchanged |
| depends on | P1 `bcb17e45` · P2a `e094fa26` · P2b `5a2ecfd1` · P3 `254cbaa1` · P4 `79833db8` — **ALL MERGED**; nothing else |
| downstream | Step 11 (physical data root, argv-builder reshaping); Step 12 (out-of-tree packages, composition root, contrast L4 — **gated on CAP-SCOPE, §10.2**); a future generic reference-evidence capability seam if any composed task ever needs declared reference/SOTA context (§10.5, C-P56-1) |
| Gate disposition | **Gate 1 NOT REQUIRED · Gate 2 REQUIRED** (one bounded composed-TIDMAD chain, 2 iterations × 1 round, autonomous inside the pre-authorized envelope, non-vacuous restore evidence) — rows quoted and the execution contract frozen in §15 |
| open operator questions | **0** — Q-P56-1 RESOLVED = B and Q-P5-1 APPROVED (raise), both by the operator's final freeze review 2026-08-21 (§19) |
| freeze blockers | **none** — REVISION 2 is FROZEN |

### 0.1 What "consolidated" means here, precisely

* The **semantic owners are unchanged**: S5 and S8 exactly as the parent froze
  them. No scope item moved, split, or grew.
* The **implementation vehicle changed**: one PR, one commit sequence
  (§13 C0–C8), one exact-head CI, one Gate disposition — instead of two PRs
  whose second would begin by re-auditing the surfaces the first just touched.
* The **acceptance story is now one sequence**:
  `state contract → persist/carry → restore/resume → multi-iteration →
  three-task closure` — the lifecycle half (old P5) builds the machinery the
  closure half (old P6) is the first to exercise across iterations and tasks.

---

## 1. Parent contract (recovered, binding)

Quoted or tightly paraphrased from the frozen parent; nothing here is new.

* **§12 / Q-10-3 = A (FROZEN)**: `vocab_link_confirmations` is **ACTIVATED** —
  `producer → committed digest → projection → ChainState → next-iteration
  InterpretationInput → the ≥ 3-run promotion condition`, every link required.
  Its primary reachability owner is a **deterministic lifecycle test with
  temporal depth ≥ 3, NOT a 3-iteration real Gate** ("temporal depth is a
  property of the *test*, not of the GPU").
* **§12.2 / Q-10-6 = A (FROZEN)**: `accumulated_key_findings` is promoted into
  `ChainState`; its union merge rule may stay unique; its lifecycle ownership
  must match its siblings.
* **§12.3 constraints**: the ONE Step-09.5a committed-digest read authority (no
  fifth loader); NO new run-state carrier; each projection states its merge
  rule and failure policy in the shape of the four existing ones; **acceptance
  proves reachability, not presence**.
* **§10 rules**: no fourth carrier; no fifth resume loader; `ChainState` never
  crosses a subprocess boundary (`RestoredState` is the transport type);
  single writer per carried value, with the `prediction_memory` loop closure as
  the named pattern ("read straight off the digest the interpreter just wrote,
  so the in-process loop and the chain-subprocess restore agree by
  construction").
* **§4.2**: `campaign_artifacts` never becomes `ChainState`.
* **S8 / §14–§17**: same infrastructure, different values; TIDMAD is the
  preservation control; Pets is the higher-is-better classification contrast;
  DAVIS is the **lower-is-better discriminating** track; **no model-quality
  requirement anywhere**.
* **§20.6 / skeleton §3**: the closure child "adds NO new scientific semantic
  contract. If the closure discovers a missing one (a value a task needs that
  no upstream child bound, a declaration the framework cannot express), that is
  upstream debt owned by the child that owns the family — it is recorded and
  fixed there, never hidden as P6 runner logic."
* **Q-10-5 = B (FROZEN)**: the hand-written Pets/DAVIS runners retire as
  alternate production paths **only after every distinct claim they own has
  been enumerated and transferred** to a named surviving owner. What survives
  owns a distinct failure class.
* **§22.1 (FROZEN)**: P5's primary evidence owner = the deterministic
  temporal-depth-≥ 3 lifecycle test; P6's = **Gate 2**. "No TIDMAD-only Gate
  may support a **genericity** claim."
* **§19.3**: the structure preflight is BINDING at freeze (§12 here).
* **Inherited hand-offs recorded by the merged children** (each verified in
  §2/§10): P1 §12 → (a) composed-metric scoring for non-TIDMAD loop runs
  ("or the seam-scoring route"), (b) child-side availability of out-of-tree
  data-path plugins ("belongs to P6/Step 12"), (c) runner retirement
  (Q-10-5); P4 → contrast-task Health evidence completeness is DELIVERED, and
  the Gate runners' direct `runner.evaluate_gate` bypass is retired by P6 per
  Q-10-5 = B; P4 → HD-T5/HD-T6 are **NOT** this child's; P3 §9 → carried
  values reach the proposer only through the typed value's declared extension
  surface.
* **Roadmap ladder (§22.10, binding)**: L3 = integrated task execution;
  **L4 = full agent workflow**. The roadmap's Step-12 row: "first point at
  which Tracks B and C MUST demonstrate full declared composition +
  end-to-end execution (L3→L4)". The roadmap's Step-10 row's contrast rung:
  "launcher-binding axis: a second bound task **initializes** the loop".
  §10.2 shows why this matters.

---

## 2. Current source audit (measured at `ec6257fb`)

Three independent read-only audits on non-overlapping surfaces (lifecycle ·
P3 boundary · three-task machinery), every load-bearing claim re-verified
directly by the author. Line anchors are evidence of what was inspected,
never implementation authority.

### 2.1 `vocab_link_confirmations` — producer works, BOTH transport halves still missing

| link | state | site |
|---|---|---|
| schema | ✅ | `InterpretationInput.vocab_link_confirmations` (`agent/schemas/interpretation.py:677-682`, `dict[str, list[str]]`, `default_factory=dict`); `InterpretationOutput…` (`:1155-1161`, same shape). Both field descriptions promise a carry-forward **no production code implements** |
| producer | ✅ | `update_vocab_link_confirmations` (`nodes/interpretation_helpers.py:587`, body `:626-679`), called at `result_interpretation_agent.py:901-912` with `existing_confirmations=inp.vocab_link_confirmations` (`:908`), `min_runs=3` hardcoded at the call |
| persistence | ✅ | the output IS the digest (`model_dump_json` to `interpretation_{run_name}.json` — exactly what `core/committed_digests.py:117` reads). Normal branch writes the updated mapping (`:1018`); degraded branch carries the INPUT mapping through verbatim (`:1125`, shallow `dict(...)`) |
| **cold-start branch** | ⚠️ **NEW FINDING** | the cold-start early return (`result_interpretation_agent.py:210-237`) constructs `InterpretationOutput` **without** the field → schema default `{}`. Today harmless (the input is always `{}`); after activation it is the one producer branch that can clobber a restored mapping. §7.3 decides this (DD-2) |
| resume projection | ❌ | `core/resume.py`: **0** occurrences; `RestoredState` (`:119`, **15 fields**, `:203-236`) has no such field; no projection produces one |
| in-process carry | ❌ | `ChainState` (`core/chain_state.py:46`, **11 fields**) has no field; `workflows/model_exploration.py`: **0** occurrences |
| consumer wiring | ❌ | the production `InterpretationInput(...)` (`model_exploration.py:2097-2151`, 19 fields passed) does not pass it — the interpreter always receives `{}` |

**Consequence (measured)**: `existing_confirmations` is always `{}`; one
iteration appends at most one `run_name`; promotion requires
`len(run_names) >= min_runs` with `min_runs=3` — **`VocabEntry.related_to`
promotion is unreachable in production.** The only place the carry exists is
the hand-threaded dual-mode integration test
(`tests/integration/workflows/test_vocab_accumulation.py:1067`, H.4) — a test
outside CI certifying a wiring production does not have.

**Producer semantics (SOURCE-DETERMINED — the aggregation rule is not
invented here):**

* shape: `dict["feature:capability" → list[run_name]]`;
* update: only the exact outcome string `"confirmed"` with a truthy
  `run_name` counts (`:630`); each proposed link appends `run_name` iff not
  already in that key's list (`:639`) — a KEYED UNION with per-key run-name
  dedup, append order preserved; `partial` / `refuted` / `None` change
  nothing;
* the helper deep-copies the incoming mapping (`:627`) — the caller's dict is
  never mutated;
* promotion (`:657-676`): `len(run_names) >= min_runs` AND the feature
  resolves in `runtime_vocab` AND the capability is not already in
  `related_to`; the loop re-scans the WHOLE map every call, so an old key can
  promote later once its feature appears;
* accumulation happens **inside the producer** — each normal digest already
  carries the full cumulative mapping. Therefore the cross-iteration
  projection is **LATEST-WINS on the whole dict**; a workflow-side re-merge
  would be a second accumulation authority (§10 rule 4's exact prohibition).

### 2.2 `accumulated_key_findings` — a truncated, read-only lifecycle

| link | state | site |
|---|---|---|
| producer | ✅ | the digest's `key_findings` (normal `:992` from the synthesis LLM; degraded `:1098` = `[]`; cold start `:215-217` = one fixed sentence) |
| projection | ✅ | `project_knowledge` (`core/resume.py:886`) — findings half: **chronological union, dedup by string, first-occurrence wins** (`:926-929`); soft-fail warn-and-skip per unusable digest; non-`str`/empty members silently filtered, no warning |
| `RestoredState` | ✅ | field exists (`:207`, `list[str]`, default `[]`); assigned at `:1480` (`state.runtime_vocab, state.accumulated_key_findings = project_knowledge(digest_reads)`) |
| workflow | ⚠️ | P1 C5's unpack: a bare LOCAL (`model_exploration.py:1942`), **never updated in-loop**, consumed at `:2278-2292` — the `ExpertContextItem(source="prior_iters", kind="findings", source_ref="prior_iters_key_findings")` rebuilt per proposal attempt. The preceding comment (`:2271-2277`) still cites `core.resume.load_latest_knowledge`, a function that **no longer exists** |
| `ChainState` | ❌ | no field — the only carried value whose lifecycle ownership differs from every sibling's (the Q-10-6 defect, verbatim) |

Consequence for in-process multi-iteration runs: iteration 3's proposer sees
exactly the accumulated block iteration 1 saw — the current iteration's own
findings never join it (contrast `state.current_prediction_memory`, closed at
`:2791-2805`).

One pre-existing prompt defect, recorded and PRESERVED (F-P56-1): the block
labels the FINDINGS count as an ITER count — `"Accumulated key findings from
{len(accumulated_key_findings)} prior iter(s)"` (`:2286-2287`). Fixing the
label is an LLM-facing byte change outside this child's declared deltas; it
stays byte-identical and is recorded as a one-line prompt-hygiene debt.

### 2.3 The substrate (verified, post-P1/P3)

* `RestoredState` — `core/resume.py:119`, **15 fields** (`:203-236`),
  transport type across the launcher edge (ONE `restored_state` parameter).
* The four projections and their frozen failure-policy spectrum
  (`core/resume.py`): `project_knowledge` `:886` (split rule; warn-and-drop) ·
  `project_fingerprint_history` `:951` (latest-wins; **raises**) ·
  `project_prediction_memory` `:1004` (latest-wins; **raises** — "an accuracy
  statistic assembled from half a pool is worse than none") ·
  `project_knowledge_cache` `:1052` (latest-wins; weakest, empty dict DOES
  overwrite). One digest read: `read_committed_digests`
  (`core/committed_digests.py:117`), called once at `resume.py:1478`.
* `ChainState` — `core/chain_state.py:46`, 11 fields; `from_restored`
  (`:128-168`, 9 keyword-only params); `chain_state_field_names()` (`:185`)
  feeds the derived FORBIDDEN sets of `workflows/run_bindings.py:132-134` and
  `workflows/task_composition.py:220-222`.
* Guard interactions measured NOW, not discovered later:
  * `tests/unit/workflows/test_step09_5a_c2_carriers.py:71` asserts
    `len(fields) >= 11` — +2 fields pass;
  * `tests/unit/workflows/test_step09_5a_c4_single_writer.py` censuses the
    literal spelling `f"state.{field} ="` and **parametrizes reachability over
    every ChainState field** — so a ChainState field with NO workflow
    reference turns RED. **A carrier-only "inert" commit that adds ChainState
    fields is impossible**; §13's C1/C2/C3 boundaries are drawn around this
    measured fact;
  * P1's composition/bindings guards derive deny-lists from
    `chain_state_field_names()` — the two new fields extend them
    automatically (correct: a binding must never carry them);
  * the Step-09.5a workflow oracle envelope covers `RestoredState`/`ChainState`
    — the P3 lesson (its C3 left the oracle RED for three commits) makes
    running it per-commit MANDATORY here.
* The loop-closure pattern to copy: `state.current_prediction_memory = ...`
  (`model_exploration.py:2791-2805`), reading straight off the just-written
  interpretation; siblings at `:2808` (`previous_proposal_data`) and
  `:2809-2817` (runtime vocab).

### 2.4 The P3 boundary (what this child consumes, verified)

* `ProposerInterpretationEvidence` — `agent/schemas/proposer_evidence.py:101`,
  **30 fields**, frozen, `extra="forbid"`; built ONLY by
  `build_proposer_evidence(Mapping)` (`:171`); consumed by BOTH entrypoints
  (protocol `ml_result_interp_to_ml_model_propose.py:181`; standalone CLI
  `ml_model_proposal_agent.py:2148`).
* `NOT_CARRIED` (`:80-93`, 12 entries) **refuses `vocab_link_confirmations`
  by name**: `"P5's cross-iteration lifecycle, not P3's"` (`:88`). The
  partition test (`test_step10_p3_c1_projection.py:55-79`) enumerates the
  42 upstream fields from the LIVE schema — carried ∪ refused must cover them
  exactly. **This child adds NO `InterpretationOutput` field, so the partition
  is untouched**; if a future decision ever surfaces confirmations to the
  proposer, it is a deliberate, test-visible act on this declared surface.
* `key_findings` IS carried on the evidence (`:149`) — the current-iteration
  findings already reach the proposer through the typed value. The
  CROSS-ITERATION union reaches the proposer through the SEPARATE
  `expert_context` channel (`ProposalInput.expert_context`,
  `agent/schemas/proposal.py:827`; `ExpertContextItem.kind` literal includes
  `"findings"`, documented at `:251-255` as exactly this chain-mode carry).
  P3 deliberately left that channel alone; this child keeps it as the
  consumer surface (§9).
* `ProposalInput.interpretation` and `per_model_score_tables` are REMOVED;
  `interpretation_evidence` is the only REQUIRED field. The raw-read census
  (`test_step10_p3_proposer_evidence_census.py`, expected `{node: 0,
  helpers: 0}`) and the ordering-operand invariant (extended over 5 proposer
  files incl. `proposer_evidence.py` and the protocol) are standing guards
  this child must keep green.
* **P3 kept its §9 promise — verified from git, discharging the old P5 §14
  obligation 2**: `git show 254cbaa1 --stat` touches **zero `core/` files**;
  `ChainState` still 11 fields, `RestoredState` untouched, no digest reader
  added, `vocab_link_confirmations` occurrences in `workflows/` still 0.

### 2.5 The three-task machinery (what exists TODAY, and what does not)

**The composed production path** (P1, merged): a manifest
(`task_data_path` · `dataset_profile` · `metric` · `secondary_metrics?` ·
`task_health` · `interpretation_blocks?` · `task_config`; unknown keys
refused) → `compose_run_task_bindings` (`workflows/task_composition.py:891`) →
`RunTaskComposition` of **resolved objects** → `bind_run_task_composition`
(`:1030`; enters `bind_task_config` on its ExitStack `:1075`) →
`run_workflow(task_composition=...)` (`model_exploration.py:1494`;
`verify_composition_is_bound` `:1606`; invariants stamped `:1810-1814`).

**Where the composition can and cannot be launched:**

| surface | `--task_composition`? | anchor |
|---|---|---|
| `sdsc_submission_scripts/run_one_iteration.py` | ✅ | `:1058-1073`, bound at `:1979-1986` |
| `workflows/model_exploration.py` module CLI | ✅ | `:3109-3117`, bound at `:3139-3143` |
| **`sdsc_submission_scripts/run_chain.sh` / `_chain_common.sh`** | ❌ **absent** | grep = 0; `build_app_args` (`_chain_common.sh:426`) has no entry — **the operator's multi-iteration chain cannot launch a composed run today** |
| `scripts/run_comparison.py` | ❌ (legacy baseline harness; NOT the chain) | — |

**No shipped composition manifest exists** — `configs/task_composition/` does
not exist; the only manifests are the four test fixtures under
`tests/fixtures/step10_p1/{tidmad,pets,davis,fourth_task}/composition.yaml`.
Consequently **no real composed chain run has ever executed** (P1 proved
un-composed byte parity and ran no Gate; P2b's "three-task closure through
the real chain" is `tests/unit/workflows/test_step10_p2b_c4_three_task_lifecycle.py`
driving `run_bounded_pseudo_iteration`, not `run_workflow`; P3's Gate 1 was a
proposer-only probe).

**The hand-written runners** (`scripts/run_pets_gate2.py` 269 LOC ·
`scripts/run_davis_gate2.py` 274 LOC · shared `scripts/_gate2_health_stage.py`
124 LOC): real training → inference → deliverable codec → metric → Health, all
**in-process Python calls** (`run_experiment_streaming` as a function, never a
subprocess), **zero LLM** (grep-proven), never touching `run_workflow`,
`restore_prior_state`, the proposer, the interpreter or `ChainState`. They
construct the seam scopes THEMSELVES from the pack manifests
(`PetsScope(rows=...)`, `run_pets_gate2.py:161-163`). Real 08c evidence:
Pets train 3.75 s / DAVIS 7.33 s on the RTX 5090 — the L3 real-execution
evidence for both contrast tracks.

**The blocking finding — contrast-task loop TRAINING is a missing declared
capability, not a wiring gap** (full consequence in §10.2):

| # | fact | anchor |
|---|---|---|
| a | the frozen four-method `TaskDataPath` contract takes `scope: object` **built by the caller**; "Task-vocabulary values — TIDMAD's seg_size, its DatasetProfile — are deliberately ABSENT: an implementation obtains its own vocabulary through its own authorities at binding time" | `execute_tools/task_data_path.py:100-103`, `:172-204` |
| b | the tuner builds a TIDMAD `SampleSet` unconditionally, trial and formal | `nodes/ml_hyperparameter_tune_agent/planning.py:397-413` |
| c | `run_experiment_streaming` accepts a generic `task_scope`/`task_eval_scope` (`train_engine_sandbox.py:987-989`) but the training subprocess `__main__` (`:1976-1991`) has **no argv for them** — a child with a transported `pets` binding still builds `TidmadScope` |
| d | `DatasetProfile` requires TIDMAD topology (`segments_per_file`, `.h5` patterns, `psd_segment_length` — `execute_tools/dataset_config.py:45-63`); the Pets/DAVIS composition fixtures **fabricate** those values and say so: "COMPOSITION fixtures, not a claim that Pets is loop-executable" (`tests/fixtures/step10_p1/pets/composition.yaml:3-6`) |
| e | trial mode requires TIDMAD's `segment_anchors.json` or raises (`ml_hyperparameter_tune_agent.py:777-785`) |
| f | the tuner's Health context builds TIDMAD peek paths — `_target_fn(i, _base=TIDMAD_DATA_DIR) → abra_validation_{i:04d}.h5` (`execution.py:42,1043-1044`) — invisible to the task-identity census (no task-NAME dispatch) |

**Step-10-owned gaps that ARE wiring (all bounded, all closed by this
child):**

| # | gap | anchor | closed in |
|---|---|---|---|
| W1 | chain launcher cannot pass `--task_composition` | `_chain_common.sh:426`, defaults block `:44-140` | C5 |
| W2 | no shipped TIDMAD composition manifest | `find configs -name "composition*"` = 0 | C5 |
| W3 | subprocess children bootstrap ONLY the TIDMAD data-path built-in (`train_engine_sandbox.py:53-54`, `inference_single.py:41`, `denoising_score_single.py:161`), so a transported in-tree `pets`/`davis` id fails resolution in the child even though all three impls are in-tree production modules (`execute_tools/{tidmad,pets,davis}_data_path.py`) and the parent-side emitter exists (P1 C3, `core/sandbox_executor.py:839-862`) | audit D-4 | C5 |
| W4 | `load_reference_scores()` loads 42 TIDMAD reference JSONs **unconditionally** (`ml_hyperparameter_tune_agent.py:795`) — a composed non-TIDMAD run would silently inject TIDMAD's `s_max`/baseline/ground-truth numbers into every prompt table: silent wrong science, not a crash | audit D-6 | C5 |
| W5 | composed-metric scoring: the in-process route (`sandbox.evaluate_metric`, `execution.py:979-985`) honors `resolve_bound_run_metric()` (`ml_hyperparameter_tune_agent.py:549`) — **already correct for chain runs**, which take that route; the subprocess route (`denoising_score_single.py:180` re-derives TIDMAD at module level) is reached only by the legacy single-file path. P1 hand-off (a) is therefore closed **by construction** and needs a PIN, not a fix | audit D-5 | C5 (pin) |

**Genericity guards already standing** (kept green, not rebuilt): the broad
task-identity-dispatch census (`test_step10_p1_c4_extension_proof.py:117-145`,
9 production dirs, 4 AST dispatch shapes, class (b) = 0); the 7-file
data-path-surface census (`test_task_data_path_census.py`); the
examples-import governance census (`test_pack_governance.py:211-221`, zero
production dependency on `examples/` — which also means production can never
read the packs' manifests to build scopes, part of why (a)–(f) is a
capability); P1's out-of-tree fourth-task composition proof.

### 2.6 Discharge of the old P5 draft's §14 obligations

| obligation | verdict |
|---|---|
| 1 — re-audit consumer surfaces at post-P3 master | **DONE** (§2.2, §2.4): the findings `ExpertContextItem` block did NOT move into typed evidence — it is workflow-owned at `:2278-2292` feeding `expert_context`; the typed value carries only the current iteration's `key_findings` |
| 2 — confirm P3 added no carrier field or digest reader | **DONE** (§2.4, git-proven): zero `core/` files in the P3 squash |
| 3 — re-verify §2 anchors; quote the gate standard; disposition Q-P5-1 | **DONE**: anchors re-measured at `ec6257fb` (every moved line updated above); gate rows quoted in §15; Q-P5-1 resolved in §8.2 |

---

## 3. Why P5 and P6 are one child

The consolidation question the operator posed: *does Step-10's remaining
lifecycle work have meaningful independent acceptance BEFORE the three-task
closure?* Audited answer: **no final acceptance boundary worth a separate PR
remains**, for measured reasons:

1. **The lifecycle's full-composition proof was always the closure's job.**
   The old P5 draft's own downstream row reads "P6 — the closure runs with
   carried state live". A separate P5 PR would merge machinery whose
   whole-graph composition is only proven one PR later; the merged child
   proves it in the same commit sequence (C6 drives the loop with carried
   state live; the Gate carries it through a real restore).
2. **A separate P6 would begin by re-auditing exactly the surfaces P5 just
   touched.** P6's skeleton mandated "a fresh source audit of the merged
   topology" as its first act; with P5 merged separately, that audit would
   re-measure `resume.py`/`chain_state.py`/`model_exploration.py` days after
   P5 changed them. One child = one audit (§2), one baseline (C0).
3. **Neither half introduces semantics the other doesn't exercise.** P5's
   only consumers are the interpreter input and the proposer's
   expert-context block; the three-task drives are the first multi-task
   traversal of both. P6 adds no new semantic contract at all (parent §20.6).
4. **Steel-man for keeping them separate, answered**: (a) *review size* — the
   merged child is 9 commits (§13), inside the precedent range (P1 = 7,
   P3 = 6 + Gate), and review decomposition ≠ CI decomposition (one exact-head
   CI either way); (b) *a Gate failure would stall the finished lifecycle
   work* — true, but the Gate exercises the lifecycle itself (carried state
   through a real restore), so the coupling is evidentiary, not accidental;
   (c) *the parent froze SEVEN children* — addressed by the operator's
   2026-08-21 topology amendment, recorded in the parent §20 following the
   C-P4-1 / R-1..R-3 precedent (targeted operator amendments applied in
   place, freeze otherwise unchanged). Semantic ownership and the S-item
   definitions did not move.

**The one boundary the consolidation does NOT blur**: the deterministic
lifecycle evidence (S5's frozen primary owner) is never diluted into "the
Gate will show it". §14 assigns every claim exactly one owner; the Gate owns
only what nothing cheaper can (§15).

---

## 4. Semantic owner and non-goals

**ONE semantic owner: Step-10 cross-iteration state closure and final
three-task workflow closure** — making the already-merged Step-10 contracts
(composition, ordering, secondary transport, typed proposer evidence, Health
declarations) survive across iterations, restarts, and all three example
tasks, through the ONE generic path.

It owns:

* the complete lifecycle of `vocab_link_confirmations` (activation) and
  `accumulated_key_findings` (normalization) — carriers, projection, closure,
  restore, consumers;
* the composed-chain **operator surface** (`run_chain.sh` forwarding, the
  shipped TIDMAD manifest);
* the Step-10-owned wiring closures W1–W5 (§2.5);
* the three-task **orchestration closure** through `run_workflow` itself, and
  the census evidence that keeps the generic path task-free;
* the runner-claims enumeration and the retirement/relabel it licenses
  (Q-10-5 = B);
* the terminal Step-10 acceptance sweep and its Gate.

It must NOT reopen (each verified untouched by §13's plans):

* P1 composition semantics, the manifest schema, the fingerprint/lock rules;
* P2a ordering semantics, `MetricOrder`, the reconciliation authority, the
  scanner's precision contract;
* P2b secondary evaluation semantics, the exception-taxonomy order, §4.7's
  semantic emptiness;
* P3's evidence schema and projection (no `InterpretationOutput` field is
  added; `NOT_CARRIED` keeps refusing confirmations; the prediction grammar
  D1/D2/D3 untouched);
* P4 Health declarations; HD-T5/HD-T6 stay named debt;
* the producer's promotion rule (`min_runs=3`, keyed union, dedup — the
  transport is activated, the science is untouched);
* Step-11 surfaces (physical data root, sandbox mechanics, argv-builder
  redesign);
* Step-12 surfaces (out-of-tree packages, composition root, contrast L4 —
  §10.2/§11);
* tuner policy, round/attempt semantics, retry, watchdog, admission;
* the frozen TIDMAD metric formula, frozen names, the v1 prediction pool.

---

## 5. The lifecycle state contract

The complete per-value contract — §2's measurements turned into the frozen
design. Both values ride the SAME lifecycle their nine ChainState siblings
ride; neither introduces a new mechanism anywhere.

| | `vocab_link_confirmations` | `accumulated_key_findings` |
|---|---|---|
| semantic meaning | cumulative map `"feature:capability" → [run_name…]` of CONFIRMED prediction outcomes; the promotion counter for `VocabEntry.related_to` | the chronological union of every iteration's synthesized `key_findings`, dedup by string, first-occurrence wins — full historical facts, NOT a compacted summary |
| producer | `update_vocab_link_confirmations` via the interpreter (untouched) | the interpreter's digest `key_findings` (untouched) |
| committed carrier | the interpretation digest (all THREE branches after DD-2 — §7.3) | same digest (already, all branches) |
| read authority | `read_committed_digests` — THE one | same |
| projection | **NEW** `project_vocab_link_confirmations`: latest-wins whole-dict; malformed ⇒ **raise** (§8.2); missing key ⇒ `{}` | EXISTING `project_knowledge` findings half — UNCHANGED |
| `RestoredState` | **NEW** field, default `{}` | existing field (unchanged) |
| `ChainState` | **NEW** `current_vocab_link_confirmations: dict[str, list[str]]` | **NEW** `accumulated_key_findings: list[str]` |
| in-process update rule | loop closure reads the just-written output's mapping whole (LATEST-WINS — accumulation lives in the producer) | loop closure appends the just-written output's `key_findings` not already present (SAME union/first-wins rule as the projection) |
| single writer (§10 rule 4) | exactly two sites: the `from_restored` seed + the one loop closure | same two sites |
| restore | `RestoredState` → `from_restored` seed | same |
| consumer | next iteration's `InterpretationInput.vocab_link_confirmations` (the workflow finally passes it) | the existing `:2278-2292` ExpertContextItem block, now reading the ChainState field |
| first iteration | `{}` — first-class, not an error | `[]` — the block renders nothing (existing guard) |
| quiet/failed iteration | degraded digest carries the input through (`:1125`); a round with no interpretation writes no digest and the closure does not run — state unchanged either way | degraded digest's `key_findings=[]` unions to a no-op; same no-digest rule |
| subprocess boundary | never crosses as `ChainState` (§10 rule 3) — chain transport is digest → restore, exactly like every sibling | same |
| task coupling | none — the lifecycle never inspects task identity; DAVIS's `lower` direction never touches it (run_names and strings carry no ordering) | none |

**The declared behaviour delta (DD-1, carried from the old draft's §4.3)**:
chain-mode production (1 iteration per subprocess) is behaviour-identical for
findings (still restored) and behaviour-NEW only in that confirmations now
actually arrive. **In-process multi-iteration runs** change deliberately:
iteration N+1's proposer context now includes iteration N's findings (today
it sees none), and iteration N+1's interpreter receives the accumulated
confirmations. That is Q-10-6 = A's point — the two trajectories stop
disagreeing — and C4's equality test pins the new agreement.

---

## 6. `accumulated_key_findings` — normalization

* **Ownership move only.** The union merge rule, the projection, the digest
  content and the consumer block's rendered bytes are all UNCHANGED. What
  changes: the bare local becomes `state.accumulated_key_findings`, seeded by
  `from_restored`, appended by one loop closure beside `:2791-2805`'s
  pattern, read by the block at `:2278-2292`.
* **The in-process append applies the projection's exact rule** (append only
  non-empty `str`s not already present, order preserved) so an uninterrupted
  in-process trajectory and a per-iteration chain restore produce EQUAL state
  by construction — C4's acceptance.
* No dedup-rule drift is possible: the projection is not re-implemented; the
  closure is four lines against the just-returned `interpretation.key_findings`.
* No max-size/truncation rule exists today and none is added — the proposer
  prompt's existing clamp machinery is the size authority downstream
  (unchanged).
* The stale `:2271-2277` comment (dead `load_latest_knowledge` reference) is
  corrected in passing — C3 touches exactly those lines (parent non-goal 7's
  in-passing allowance).
* F-P56-1 (the iter-count label defect) stays byte-identical (§2.2).

## 7. `vocab_link_confirmations` — activation

### 7.1 The projection

`project_vocab_link_confirmations(reads: Sequence[DigestRead]) ->
dict[str, list[str]]`, beside the four siblings in `core/resume.py`:

* **latest-wins whole-dict** — §2.1 derives it from the producer: each normal
  digest already carries the full cumulative mapping; a union across digests
  would resurrect pairs a later iteration legitimately dropped, and would be
  a second accumulation authority;
* a digest MISSING the key ⇒ `{}` (legacy digests predate activation — an
  explicit compatible default, never fabricated history);
* present-but-malformed ⇒ **raise** (§8.2, Q-P5-1 resolution);
* shape validation: `dict[str, list[str]]`, string members; an EMPTY mapping
  is a legitimate value, distinct from an absent key;
* the projection must NOT re-dedup run lists — the producer is the only
  authority on the promotion count (a pass-through assertion pins this).

### 7.2 The carry and the consumer

`RestoredState.vocab_link_confirmations` (default `{}`) →
`ChainState.current_vocab_link_confirmations` via `from_restored` → the
workflow passes it into `InterpretationInput.vocab_link_confirmations`
(the field exists, `interpretation.py:677`) → the producer accumulates → the
loop closure writes the returned mapping back to the carrier whole
(the `prediction_memory` pattern, and the single-writer census's exact
`state.current_vocab_link_confirmations = ...` spelling).

### 7.3 DD-2 — producer branch symmetry (the cold-start clobber, closed at the source)

§2.1's new finding: the cold-start early return builds an output without the
field. Once the closure reads the just-written output unconditionally, a
cold-start iteration in a workspace whose restored mapping is non-empty would
clobber it with `{}`. Whether that state is reachable depends on a distant
workflow condition (`is_cold_start = (not new_summaries) and (not
state.model_knowledge_cache)`, `model_exploration.py:2086`, versus what the
digests that carried the confirmations also carried) — an invariant too
fragile to lean a lifecycle on.

**Decision**: make the producer's three branches symmetric — the cold-start
return gains `vocab_link_confirmations=dict(inp.vocab_link_confirmations)`,
exactly the degraded branch's carry-through (`:1125`). The closure's
unconditional read is then safe by LOCAL construction.

* Parity: for every pre-P5 caller the input is `{}`, and the field's
  `default_factory=dict` already serializes `{}` into the digest — the
  cold-start digest bytes are IDENTICAL for all existing runs. The only
  behavior change is the pathological restored-cold-start case, which is the
  fix.
* This is a deliberate, bounded deviation from the old draft's "producer
  untouched" non-goal, forced by a measured defect; the promotion science is
  still untouched.

### 7.4 Reachability acceptance (Q-10-3's frozen shape)

The ≥ 3-iteration deterministic test: three pseudo-mode iterations in ONE
process; a link proposed in iteration 1 and confirmed by three DISTINCT
run_names promotes into `related_to` at iteration 3 and NOT at iteration 2.
Then **one severing mutation per link** — projection, seed, closure, input
pass — each independently turns it RED (a four-link carry needs four proofs).
C4 adds the uninterrupted-vs-resumed deep-equality twin.

---

## 8. Persistence / resume semantics

### 8.1 The full state table (every carried value × every situation)

| situation | `vocab_link_confirmations` | `accumulated_key_findings` |
|---|---|---|
| fresh run | `{}` / `[]` (defaults; no digest exists) | same |
| normal next iteration (in-process) | closure writes the output's mapping | closure unions the output's findings |
| quiet iteration (no new confirmations / no new findings) | producer returns the carry-in unchanged → closure writes an equal value | union no-op |
| failed round, degraded interpretation | degraded digest carries the INPUT through (`:1125`) — no loss, no double count | `key_findings=[]` — union no-op |
| failed round, NO digest written | closure does not run (no interpretation object) — state unchanged | same |
| cold-start iteration | DD-2 carry-through — state unchanged | the fixed cold-start sentence joins the union (existing content, now carried) |
| process restart / resume | projection over committed digests → `RestoredState` → seed; equality with the in-process trajectory is C4's acceptance | same (existing projection) |
| legacy digests (pre-activation) | missing key ⇒ `{}`, no warning, never fabricated | already-carried (no change) |
| malformed digest VALUE | **raise** (§8.2) — restore's existing wrapper semantics, exactly `prediction_memory`'s | existing warn-and-drop per entry (unchanged) |
| unusable digest (unreadable/corrupt JSON) | the sibling warn-and-skip shape (`digest_unusable_message`) | same (existing) |

No value is loaded by two subsystems: the projection is the only reader of
the digest key outside the interpreter (censused, C4), and each ChainState
field has exactly two write sites (seed + closure — the single-writer census
extended automatically).

### 8.2 Q-P5-1 — RESOLVED and OPERATOR-APPROVED (freeze review 2026-08-21): malformed confirmations ⇒ RAISE

The old draft's single open question, resolved with the named precedent and
**approved by the operator at the final freeze review** — no longer
overturnable prose, a frozen ruling: the projection **raises** on a
present-but-malformed value, `project_prediction_memory`'s policy
(`resume.py:1039-1047`) — this is PROMOTION state, and silently keeping an
older partial mapping can change WHEN a scientific vocabulary relationship
graduates; "an accuracy statistic assembled from half a pool is worse than
none" is the same argument one level up. Frozen alongside it: a missing
pre-activation key ⇒ `{}`; an unreadable/corrupt digest ⇒ the existing
digest-unusable handling; the latest valid present mapping wins whole-dict.
The parent's §10 rule 2 requires exactly this statement ("which of those it
is, and why"), which this section is.

---

## 9. P3 consumer wiring — what this child delivers to which surface

* **The interpreter** (the confirmations consumer): receives the carried
  mapping through the EXISTING `InterpretationInput` field. No prompt
  template changes; the mapping is structured state (grep-proven absent from
  every prompt template), whose only LLM-visible effect is `related_to`
  promotions surfacing in the already-rendered runtime vocab.
* **The proposer** (the findings consumer): the cross-iteration union keeps
  arriving through `expert_context` — the channel P3 documented for exactly
  this (`kind="findings"`). The typed evidence value is NOT widened;
  `NOT_CARRIED` keeps refusing `vocab_link_confirmations`; the partition test
  stays untouched. §11.2's rule holds by construction: no evidence field is
  wired anywhere twice, because no evidence field is added.
* **Raw secondaries cannot leak through the lifecycle** (an old-P6 attack,
  answered structurally): the carried values are run-name lists and
  synthesized finding STRINGS — the exact channel Q-P3-3 designates as
  legitimate; no secondary VALUE has a path into either carrier, and the
  standing prompt-absence probes plus the ordering-operand invariant stay
  green over the whole diff.

---

## 10. Three-task closure

### 10.1 The claim being closed, stated honestly

**Same generic framework path, materially different task semantics** — TIDMAD
(1-D denoising, negative-valued `higher` primary, no secondaries), Pets
(37-way RGB classification, `accuracy` higher + `macro_f1` observational),
DAVIS (spatiotemporal regression, **`mse` lower** + `psnr` higher / `mae`
lower) — each bound through the ONE composition, traversing the ONE
`run_workflow`, with direction, secondaries, Health binding, typed proposer
evidence and carried state all live, and zero task-identity branches.

### 10.2 The capability finding (the load-bearing discovery of this design)

§2.5 (a)–(f) measure that the tune phase's DATA SELECTION cannot express a
non-TIDMAD task: the frozen seam takes caller-built scopes and deliberately
excludes task vocabulary; the tuner builds TIDMAD `SampleSet`s
unconditionally; no argv transports a generic scope; `DatasetProfile` cannot
honestly describe Pets/DAVIS; trial mode requires TIDMAD's anchor map; the
tuner's Health peek paths are TIDMAD-shaped. Production is also
census-forbidden from reading the packs' manifests (the only place the
contrast rows/clips are enumerated).

Therefore **real contrast-task training THROUGH THE LOOP requires a new
declared capability — task-owned scope construction** (a task-supplied
authority that materializes the task's own scope from split/portion/seed) —
which would extend the FROZEN four-method D14 contract and redesign tuner
data selection. By the parent's own rules this is exactly "a declaration the
framework cannot express … upstream debt owned by the child that owns the
family — recorded and fixed there, never hidden as P6 runner logic"
(skeleton §3), and §7.2's "genuinely new plugin backend or capability — may
legitimately require framework work".

**And the roadmap already schedules it**: the maturity ladder puts the
contrast tracks' L4 climb ("full agent workflow") at **Step 12** — "first
point at which Tracks B and C MUST demonstrate full declared composition +
end-to-end execution (L3→L4)" — while the roadmap's Step-10 contrast rung is
"a second bound task **initializes** the loop". The frozen parent's
§16.1/§17.1 wording ("initializes and executes the exploration loop")
overreached the roadmap's own ladder. **Q-P56-1 = B — RULED by the operator
at the final freeze review (2026-08-21, §19)**: Step 10 closes at the
roadmap's actual maturity depth, and the parent's §16.1/§17.1/§26.O wording
is amended accordingly (applied to the parent in the same freeze commit).

**The delivered Step-10 contrast depth (frozen wording, per the ruling)**:
composition resolves; generic `run_workflow` orchestration
initializes/traverses under pseudo execution; direction / secondaries /
Health binding / P3 typed boundary / carried lifecycle are exercised;
retained L3 runners own real task-data execution; real task-correct loop
training remains CAP-SCOPE.

**CAP-SCOPE — NOT a vague optional debt (operator constraint, frozen)**:

```text
CAP-SCOPE
= task-owned scope construction + loop-executable contrast training
= the REQUIRED enabling capability before Pets/DAVIS may be declared
  L4 / full-agent-workflow complete
```

It covers §2.5 (a)–(f) as one capability family with one future design;
owner: the data-path/dataset family. It may be implemented by a dedicated
post-Step-10 capability PR **or** by Step 12's L3→L4 work — but **Step 12
MUST NOT claim contrast-track L4 completion while CAP-SCOPE remains open**
(recorded as an explicit prerequisite on the roadmap's Step-12 row in the
same freeze commit). Explicitly NOT this child's, and never silently moved.

### 10.3 The closure matrix (Q-P56-1 = B, RULED)

| task | binding | orchestration closure (this child, deterministic) | real execution | carried state |
|---|---|---|---|---|
| **TIDMAD** | the SHIPPED manifest (W2) through `run_chain.sh` (W1) | full-loop drive (C6): composed run ≡ legacy on the **composition invariants** (metric/scorer semantics, binding, Health declaration, zero-secondary semantics, lifecycle); per **C-P56-1** the legacy-only implicit reference table is NOT part of composed-mode parity — a composed run carries the named absence | **Gate 2 (§15): the FIRST real composed chain run** — 2 iterations, real LLM/training/inference/scoring, carried state through a REAL restore with the §15.2 non-vacuous evidence contract | live in both |
| **Pets** | its manifest (fixture-derived), health family state C | full-loop drive: loop initializes and runs interpret → propose → implement → validate → plan under `accuracy`/higher with exactly `macro_f1` observational; NO implicit legacy reference science (C-P56-1); binding reaches the tuner; no `LEGACY_OMITTED` | L3 real-execution evidence stays with its runner (retained per §10.4, freshness-audited per §10.6); loop training = CAP-SCOPE | the same task-free contract (nothing task-shaped can enter the carriers) |
| **DAVIS** | its manifest, health family state C | full-loop drive **≥ 2 iterations with carried state live** — the direction falsifier: a `lower` primary end-to-end with confirmations/findings carried, proving the lifecycle encodes no higher-is-better assumption; deliberate wrong-direction anti-vacuity probe | same as Pets | the discriminating case |

The drives go through **`run_workflow` itself** (pseudo LLM responses, the
stub sandbox — the pseudo-full-loop tier), never through a per-task
hand-written driver and never through the bounded-iteration helper — which is
what makes "same framework path" a fact rather than a fixture arrangement,
and forces the P3 typed boundary (the protocol constructs `ProposalInput`)
on every task.

**The orthogonal coverage is FROZEN as designed (operator ruling §19) — do
NOT require three identical expensive runs:**

```text
TIDMAD   preservation / mature-track control — composed orchestration,
         real Gate 2, 2 real iterations, real restore  (deepest REAL evidence)
Pets     classification / higher / observational-secondary contrast —
         composed pseudo orchestration + retained L3 real evidence
DAVIS    strongest discriminating track — lower primary, mixed-direction
         secondaries, ≥ 2 pseudo iterations with carried state live,
         wrong-direction anti-vacuity probe + retained L3 real evidence
```

Pets is deliberately NOT required to run ≥ 2 iterations: temporal carry is
already owned three times over (the deterministic ≥ 3-iteration lifecycle
tests, DAVIS's ≥ 2 pseudo iterations, TIDMAD's 2 real Gate iterations).
Requiring it of Pets would duplicate owners, not add information.

**C6 honesty rule (frozen verbatim)**: *C6 MUST NOT label its Pets/DAVIS
pseudo sandbox inputs as task-correct training scope. It proves
orchestration semantics only.* The pseudo fixture's training/data-selection
content is NOT evidence of task-correct contrast training scope — that is
CAP-SCOPE's, and every claim surface (§10, §13 C6, §14, §17, §21, parent,
roadmap, CLAUDE.md) says "orchestration closure", never "contrast L4" or
"real three-task full training closure".

### 10.4 Runner claims — enumeration and disposition (Q-10-5 = B)

Every distinct claim the two runners + shared health stage own, each with its
surviving owner. The enumeration is design-complete here; C7 verifies it
against the runner sources line-by-line before acting.

| claim | surviving owner after this child |
|---|---|
| the loop/orchestration claims (binding resolves, direction correct, secondaries observational, Health binds state C) | **TRANSFERRED** → C6 deterministic drives + the standing censuses |
| real JPEG/frame decode → tensor parity | **RETAINED by the runners** (L3 real-execution evidence; no generic owner until CAP-SCOPE) |
| deliverable codec round-trip on real bytes | RETAINED (same) |
| `comparability == "established"` on real R2/R3 curves | RETAINED (same) |
| real Health verdicts on the real Pets collapse artifact (`cc847026…` fixture lineage) | RETAINED (08c evidence + runner) |
| the DAVIS last-frame-copy baseline comparison | RETAINED (same) |
| direct `runner.evaluate_gate` orchestration as an ALTERNATE production path | **RETIRED as a label**: the runners are re-labeled L3 real-execution evidence harnesses (docstring + STATUS.md), no longer described anywhere as the way a contrast task "runs"; full script retirement happens when CAP-SCOPE gives every retained claim a generic owner |

This satisfies Q-10-5 = B's own precondition exactly: nothing retires before
its claims have owners; what survives owns a distinct failure class (real
task-data execution) and is no longer an alternate ORCHESTRATION path.

### 10.5 Wiring closures (W1–W5) — the specific deltas

* **W1**: `_chain_common.sh` gains `--task_composition` (default empty) and
  `build_app_args` forwards it; both lilab and SDSC submit paths carry it;
  `run_chain.sh` usage text updated. A misspelled/unreadable manifest fails
  at `compose_run_task_bindings` before any LLM spend (existing fail-closed
  behaviour, now reachable from the operator surface).
* **W2**: `configs/task_composition/tidmad.yaml` — the canonical shipped
  manifest, mirroring the P1 fixture, referencing the existing resolved
  TIDMAD assets (`configs/task_health/tidmad.yaml`,
  `configs/task_interpretation/tidmad.yaml`, the resolved profile/metric).
  Composed-TIDMAD ≡ legacy-TIDMAD is asserted deterministically (C5) before
  the Gate runs on it — **on the composition invariants only**: metric/scorer
  semantics, task binding, Health declaration, zero-secondary semantics,
  lifecycle behaviour and the other frozen generic invariants. Per C-P56-1
  the legacy-only implicit reference table is explicitly NOT part of
  composed-mode parity.
* **W3**: the three subprocess children import all three in-tree data-path
  built-ins (the Step-08 "built-ins' bootstrap, NOT the extension path"
  pattern, verbatim); out-of-tree plugin availability in children stays
  Step 12's (P1 hand-off (b) split).
* **W4 — as corrected by C-P56-1 (operator freeze correction, 2026-08-21)**.
  DRAFT rev 1 proposed conditioning `load_reference_scores()` on the bound
  metric identity being `TIDMAD_METRIC_ID`. **That shape is REJECTED and must
  not be implemented**: a metric-id check guarding a TIDMAD-only legacy
  science table is still a task/science identity branch inside generic
  orchestration — one the existing task-name census cannot even see. The
  frozen rule keys on **composition PRESENCE only**:

  ```text
  LEGACY / UN-COMPOSED RUN:
      preserve the existing TIDMAD reference-score behaviour byte-for-byte.

  ANY COMPOSED RUN (TIDMAD, Pets, DAVIS, any future task):
      do NOT implicitly load the legacy TIDMAD reference-score table —
      a named absence and a log line, never implicit legacy science.
  ```

  No generic-core branch on a task name, on `TIDMAD_METRIC_ID`, on a
  TIDMAD-specific score sign/range, or on any other task-identity surrogate.
  If a future composed task genuinely needs reference/SOTA evidence, that is
  a **generic declared reference-evidence capability** (config/plugin seam)
  owned by a future design — NOT invented in this child, and never inferred
  by core from a metric id. **Declared consequence, not a regression**: a
  composed run's tuner/interpreter/proposer prompts carry the named absence
  where legacy runs carry the 42-file reference table — there is no prior
  composed baseline to regress against (this Gate is the first composed
  run), prompt TEMPLATES are unchanged, and the legacy path is byte-for-byte
  preserved, so the Gate-1 flip condition is NOT triggered.
  **Recorded as C-P56-1 — implicit legacy reference science is forbidden in
  composed mode.**
* **W5**: a pin, not a fix — a test proving the chain scoring route consumes
  `resolve_bound_run_metric()` under a composed binding (mutation: rebind a
  different metric, the scored value moves), plus a standing note that the
  subprocess re-derivation at `denoising_score_single.py:180` is legacy-path
  only.

### 10.6 Retained Pets/DAVIS L3 evidence — the freshness contract (operator correction, frozen)

The retained real-execution evidence (08c runners) may be reused, but **not
timelessly by assumption**. Before terminal closure (owned by C7, recorded in
the ledger and the §14 matrix), for EACH retained real-execution track:

```text
record the last successful real-evidence provenance:
    commit SHA · artifact/run location · the relevant result

audit the semantic dependency diff from that evidence SHA to the final
implementation candidate, over the runner's real-execution surface:
    task data path · decode · training · inference · deliverable codec ·
    metric · Health declarations/stage · the runner itself

if NO semantics-bearing dependency changed:
    the prior L3 evidence remains authoritative — DO NOT rerun merely
    for reassurance

if a semantics-bearing production dependency DID change:
    rerun ONLY the affected bounded real runner before claiming current
    L3 evidence
```

This is an evidence-freshness audit, not an automatic expensive rerun.
Known starting provenance (verified this session): Pets
`/home/klz/Data/SIDEREIS_DATA/step08c_pets_gate2_20260818/gate_evidence.json`
(train 3.75 s) · DAVIS
`/home/klz/Data/SIDEREIS_DATA/step08c_davis_gate2_20260818/gate_evidence.json`
(train 7.33 s, dispersion `0.2156402715035823`), both at the 08c head
`ede11fd5` — C7 re-verifies and records the diff verdict.

---

## 11. Genericity / fourth-task boundary

* **Step 10's proof already landed and stays green**: P1's C4 out-of-tree
  fourth-task composition proof (plugin files named in zero production
  sources) + the class (b) = 0 AST census over the 9 production dirs. This
  child adds NO new fourth-task machinery; C6 extends the censuses' scope to
  the files it touches and re-runs the plants.
* **The lifecycle is fourth-task-free by construction**: carriers, projection
  and closures never see task identity; the census set (dispatch census +
  the new-file scope extension) is the executable form.
* **Step 12 owns**: the out-of-tree task PACKAGE as the source of the whole
  binding set; the unified composition root; contrast L4 — **gated on
  CAP-SCOPE, which Step 12 MUST close (or find closed) before claiming
  contrast-track L4 (§10.2, frozen prerequisite)**; child-side out-of-tree
  plugin registration. This child must remain extendable-not-replaceable by
  Step 12 (§24's freeze-time question): every interface it touches is either
  an existing family's seam or a value on the existing composition — nothing
  Step 12 would need to undo.

---

## 12. Structure preflight (parent §19.3 — measured, not estimated)

| file | LOC now | materially changed function(s) | semantic owners now | this child adds | placement verdict |
|---|---|---|---|---|---|
| `workflows/model_exploration.py` | 3,167 | `run_workflow` `:1457-2945` (1,489 LOC; iteration loop `:2050-2922` = 873 lines; **130 branch-ish AST nodes** — If 57 · IfExp 28 · BoolOp 23 · For 12 · With 8 · Try/Except 2) | loop orchestration (post-09.5a/P1 shape) | 2 loop closures (~15 lines each, beside `:2791-2805`), 1 `InterpretationInput` kwarg, 2 `from_restored` kwargs, the consumer block reading the carrier | **no new phase, no new branching responsibility** — the `prediction_memory` shape exactly; far under the 258 ceiling; NOT a decomposition trigger |
| `core/resume.py` | 1,630 | +1 pure projection (+~40 lines), +1 `RestoredState` field, +1 assignment beside `:1480` | resume/restore | sibling-shaped only | unchanged owner set |
| `core/chain_state.py` | 188 | +2 fields, +2 `from_restored` params | the mutable carrier | additive | unchanged |
| `nodes/result_interpretation_agent/result_interpretation_agent.py` | 1,331 | the cold-start return gains one kwarg (DD-2) | interpreter node | 1 line | unchanged |
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` | (post-C7 layout) | the reference-scores call site `:795` gains the W4 condition | tuner node main file | ~6 lines, no new responsibility | unchanged; the C7 public-boundary rule respected (edit the main file's call, not a private module from outside) |
| `sdsc_submission_scripts/_chain_common.sh` + `run_chain.sh` | 828 + 347 | arg parser + `build_app_args` + defaults block | operator chain surface | 1 flag, whitelisted-parser style | unchanged |
| training/inference/scoring children | — | +2 bootstrap imports each (W3) | subprocess entry | additive | unchanged |
| `configs/task_composition/tidmad.yaml` | NEW | — | shipped task composition values | 1 small YAML | beside `configs/task_health/tidmad.yaml` — the established per-family home |

No file gains a second independently-changing semantic owner; no extraction
is REQUIRED. The known hotspot (`run_workflow`) receives only the
sibling-shaped carry pattern that was specifically designed to avoid growing
it, and its branch count stays far under the measured ceiling. **No
structural decomposition is performed in this child** — doing one "while
here" would violate the bounded in-passing rule.

### 12.1 Implementation tripwire (operator-frozen, 2026-08-21)

The no-proactive-decomposition ruling is ACCEPTED — and it is paired with a
binding tripwire on the implementation session:

```text
run_workflow's delta remains SIBLING-SHAPED:
    seed · input pass · state closure · consumer read

no new workflow phase;
no new branch family;
no task-specific dispatch;
no new mutable local accumulator;
no new semantic owner.

record PRE and POST:  run_workflow LOC · branch-ish AST count
                      (baseline: 1,489 LOC · 130 nodes, §12)

if implementation requires MATERIALLY more logic/branching than the frozen
shape:
    STOP adding inline complexity;
    re-run the §19.3 structure preflight;
    choose a responsibility-preserving workflow-local extraction if needed.

no unrelated cleanup.
```

---

## 13. Commit decomposition — NINE commits (C0–C8), full plans

**Status**: boundaries stable; every checklist starts `[ ]` and is checked
only against recorded evidence. Semantic commits are autonomous inside the
frozen design. Before each: inspect the diff scope, run the cheapest
authoritative validation, update this ledger, commit. No full local suite
before the final head; **ONE exact-head CI at the end**. Every commit runs
the guards it is KNOWN to move — explicitly including the Step-09.5a
workflow oracle and the single-writer/reachability censuses whenever
`RestoredState`/`ChainState`/`model_exploration.py` are touched (the P3 C3
lesson). Commits C5–C8 implement the **Q-P56-1 = B shape as RULED** (§19);
the whole plan is now ruling-complete — no contingent scope remains.

---

### C0 — baselines: pin the CURRENT broken state and the CURRENT three-task behaviour

**1. Goal.**
Make every defect executable before fixing it: the confirmations lifecycle is
severed (nothing projects, carries or passes the value), the findings local
never accumulates in-process, and the three-task loop behaviour under
composition has never been recorded. C1–C6 must be diffs against evidence,
not belief. It belongs here and nowhere else: once C1–C3 land, the broken
states are unreproducible.

**2. Scope.**
Tests, goldens and this ledger only. **Zero production edits** — the commit
is a scope error if `git diff --stat` shows anything outside `tests/` and
`docs/`. Depends on: nothing.

**3. Implementation plan.**
- [ ] Producer accumulation golden: drive `update_vocab_link_confirmations`
      over a FIXED outcome sequence (confirmed / partial / refuted /
      confirmed, distinct `run_name`s, a repeated `run_name`) pinning the
      returned `(confirmations, vocab, newly_promoted)` at each step —
      including that `partial`/`refuted` change nothing, a run cannot confirm
      twice, and promotion fires at exactly `min_runs` DISTINCT runs
      (`min_runs` passed explicitly where the claim is about the threshold).
- [ ] The broken-lifecycle census, executable and named: `RestoredState` has
      NO `vocab_link_confirmations` field; no `project_*` produces one; the
      production `InterpretationInput(...)` does not pass it. INVERTED by
      C1/C2, never deleted.
- [ ] The cold-start drop pin (DD-2's before-picture): a cold-start
      interpreter invocation with a non-empty input mapping returns an output
      whose mapping is `{}` — recorded as the defect, with the test docstring
      naming §7.3.
- [ ] Findings-amnesia baseline: a 3-iteration in-process pseudo drive
      records that iteration 3's expert-context block equals iteration 1's
      (no accumulation) — the §5 DD-1 before-picture.
- [ ] 3-iteration confirmations baseline: a link confirmed in three distinct
      runs does NOT promote today (the exact scenario C2 turns green).
- [ ] Three-task loop baseline: drive `run_workflow` (pseudo LLM, stub
      sandbox) once under the Pets fixture composition and once under DAVIS,
      recording CURRENT behaviour — including that TIDMAD reference numbers
      DO leak into the prompt tables today (the W4 before-picture) — as
      baselines C5/C6 flip. If a drive cannot complete today, record the
      exact failure point as the baseline instead (an honest baseline is
      whatever today does).
- [ ] Malformed/legacy digest payloads (missing key, non-dict, unreadable)
      recorded as they behave TODAY, so C1 has a before-picture.
- [ ] The guard-disposition table in this ledger: every existing test this PR
      will turn red, with the commit that flips each (known set: the
      broken-lifecycle census itself; the c4 single-writer reachability
      parametrization gains 2 fields at C2/C3; the c2 carriers floor; the
      Step-09.5a oracle envelope if any `ProposalInput`/workflow surface
      moves; `test_vocab_accumulation.py` H.4's hand-threading note).
- [ ] Roadmap residual-debt check, recorded in this ledger: grep the
      dashboard/resume surfaces for any remaining direction-word LITERAL
      (the roadmap's "resume/dashboard direction literals" line); record
      each hit with its owner — outside this child unless a commit here
      touches that exact line.
- [ ] Byte-stability: every golden identical across two independent runs.

**4. Validation plan.**
* Unit: the goldens above; deterministic, `tmp_path` only.
* Integration/pseudo: the two 3-iteration baselines + the two loop drives.
* Negative/invalid: the malformed-digest recordings.
* Backward-compat: none needed — nothing changes.
* Gate: **NONE** (no real LLM, no training; Gates are C8's only).

**5. Acceptance criteria.**
- [ ] `git diff --stat` shows only `tests/` and `docs/`.
- [ ] The broken-lifecycle census PASSES on the unmodified tree (it asserts
      absence, not desired presence).
- [ ] Both 3-iteration baselines record the DEFECT (no promotion; no
      accumulation) with docstrings saying so.
- [ ] The loop baselines record today's behaviour (or today's exact failure
      point) for Pets and DAVIS compositions.
- [ ] Goldens byte-stable across two runs.

**6. Failure and edge cases.**
* A golden embedding `tmp_path`, a timestamp or set-iteration order is a
  broken baseline — capture deterministically or not at all.
* The pseudo drives must pin their fixture provenance (which composition
  fixture, which pseudo-response set) so C6 diffs are attributable.

**7. Verification commands and evidence.**
```text
pytest tests/unit/core tests/unit/agent/result_interpretation_agent \
       tests/unit/workflows -q        # targeted; plus the new files
```
- [ ] counts + wall time recorded here
- [ ] any test that could not run recorded WITH the reason (never "passed")

**8. Commit boundary.**
Independently reviewable as "here are the defects and today's behaviour,
executable". No production change, no cleanup. Diff summary + staged list
recorded here before committing.

---

### C1 — the confirmations projection + `RestoredState` (resume substrate, inert)

**1. Goal.**
Give the value its resume half: one projection over the already-read digests
and one `RestoredState` field — with nothing consuming them, so the reviewer
checks the failure policy against the four siblings in isolation.
**Deliberately excludes `ChainState`** (§2.3's measured guard: a ChainState
field with no workflow reference turns the reachability parametrization RED,
so carrier + workflow land together in C2/C3).

**2. Scope.**
* `core/resume.py` — `project_vocab_link_confirmations`, the `RestoredState`
  field (default `{}`), the assignment in `restore_prior_state` beside
  `:1480`.
* Non-goals: no `ChainState` change, no workflow change, no consumer, no
  producer change. Depends on C0.

**3. Implementation plan.**
- [ ] Implement the projection with §7.1's frozen rule: latest-wins
      whole-dict; missing key ⇒ `{}`; malformed ⇒ raise (§8.2's exact policy,
      message naming the digest, the `prediction_memory` precedent's shape);
      unusable digest ⇒ the sibling `digest_unusable_message` warn-and-skip.
- [ ] Shape validation `dict[str, list[str]]` with string members; the
      projection passes run lists through UNVALIDATED for dedup (the producer
      is the only promotion-count authority) — pinned by a pass-through
      assertion.
- [ ] Add `RestoredState.vocab_link_confirmations` (additive, defaulted) +
      the docstring row.
- [ ] Wire the assignment beside `:1480`.
- [ ] INVERT C0's broken-lifecycle census resume half: the field and the
      projection must now EXIST (the workflow half stays asserted-absent
      until C2).

**4. Validation plan.**
* Unit: projection over (a) no digests, (b) one, (c) several agreeing,
  (d) several DISAGREEING — (d) must assert the LATER digest's mapping wins
  OUTRIGHT, including a pair the later digest no longer carries (what makes
  latest-wins observable); (e) an EMPTY `{}` in the latest digest OVERWRITES
  an earlier non-empty one (a legitimately cleared state must not resurrect).
* Negative/invalid: missing key ⇒ `{}` silently; malformed value ⇒ raises,
  asserted by type AND message fragment; unreadable digest ⇒ sibling warning
  shape.
* Backward-compat: a pre-activation digest set restores `{}` with no warning
  noise.
* Gate: **NONE.**

**5. Acceptance criteria.**
- [ ] `RestoredState` carries the value; `restore_prior_state` assigns it.
- [ ] The projection is the ONLY non-interpreter reader of the digest key
      (grep census recorded).
- [ ] End-to-end behaviour UNCHANGED: C0's 3-iteration baseline still records
      no promotion (declared inert state).
- [ ] The Step-09.5a oracle run explicitly (RestoredState is inside its
      envelope); any delta DECLARED in its docstring, none expected.
- [ ] pyright clean over touched modules (or recorded CI-owned).

**6. Failure and edge cases.**
* Digest ordering: ascending committed order is assumed by the siblings —
  asserted here, not inherited.
* Non-string keys / non-list values / non-string members ⇒ raise (§8.2).
* Duplicate run_name inside a stored list ⇒ passes through (producer-owned).

**7. Verification commands and evidence.**
```text
pytest tests/unit/core -q
pytest tests/unit/workflows/test_step09_5a_c0_oracle.py -q
```
- [ ] counts + wall time recorded

**8. Commit boundary.**
Resume substrate only. No carrier, no consumer, no loop change.

---

### C2 — confirmations travel end-to-end (carrier + closure + consumer + DD-2 + reachability)

**1. Goal.**
The commit where the defect stops: the value crosses iterations. ChainState
carrier + seed, the loop closure, the `InterpretationInput` pass, the
producer's cold-start symmetry, and the ≥ 3-iteration reachability proof with
per-link severing.

**2. Scope.**
* `core/chain_state.py` — `current_vocab_link_confirmations` + the
  `from_restored` param (the `current_prediction_memory` shape, `:100`,
  `:128-168`).
* `workflows/model_exploration.py` — the seed (inside `:1968-1977`'s
  construction), the closure beside `:2791-2805` (spelled
  `state.current_vocab_link_confirmations = ...` — the census's literal), the
  `InterpretationInput` kwarg at `:2097-2151`.
* `nodes/result_interpretation_agent/result_interpretation_agent.py` — DD-2:
  the cold-start return gains the carry-through kwarg (§7.3).
* Non-goals: the producer's promotion semantics, `min_runs`, the findings
  half, prompts. Depends on C1.

**3. Implementation plan.**
- [ ] ChainState field + `from_restored` seeding (defensive copy, the
      sibling idiom).
- [ ] Workflow seed + closure + input pass — three sites, each mirroring its
      named precedent line.
- [ ] DD-2 in the producer's cold-start branch:
      `vocab_link_confirmations=dict(inp.vocab_link_confirmations)`; flip
      C0's cold-start drop pin to the carry-through expectation.
- [ ] The ≥ 3-iteration reachability test (§7.4): promotion at iteration 3,
      NOT at 2 — the threshold observable, not just the endpoint.
- [ ] **Mutation proof, one per link**: sever the projection assignment, the
      seed, the closure, and the input pass INDEPENDENTLY; each severing
      turns the reachability test RED; each recorded individually
      (count==1-site discipline, caches cleared — the mutation-hygiene
      memory).
- [ ] Flip C0's 3-iteration confirmations baseline from records-the-defect to
      records-the-fix, citing this commit.
- [ ] INVERT the remaining (workflow) half of the broken-lifecycle census.

**4. Validation plan.**
* Unit: the closure writes exactly what the interpreter returned; the seed
  copies; DD-2's three-branch symmetry (normal=updated, degraded=verbatim,
  cold-start=verbatim).
* Integration/pseudo: the reachability test; a no-confirmed-outcome chain
  accumulates nothing and promotes nothing (empty mapping first-class).
* Negative: an iteration with no interpretation object leaves state
  untouched.
* Backward-compat/parity: single-iteration chain behaviour identical except
  the §5 DD-1 declared delta (stated in this ledger with before/after); the
  cold-start digest bytes IDENTICAL for every `{}` input (DD-2 parity).
* Gate: **NONE.**
* Known guard flips (run them): the single-writer census + reachability
  parametrization (now 12 fields); the c2 carriers floor; the Step-09.5a
  oracle — deltas DECLARED if any.

**5. Acceptance criteria.**
- [ ] Reachability green with all four severing mutations individually RED.
- [ ] No new digest key: digest bytes unchanged for every pre-P5 content
      state (the field was already serialized).
- [ ] Prompt templates byte-identical (goldens); the only value-level change
      is the activation itself.
- [ ] The dedup drift case pinned: the same `run_name` confirming in two
      iterations counts ONCE (producer semantics preserved through the
      carry).

**6. Failure and edge cases.**
* A closure that clobbers on a skipped/failed round — covered by the
  no-interpretation negative.
* Cold-start with restored state — DD-2's exact case, now safe by local
  construction.
* Resume mid-chain — C4's; this commit must not make it worse.

**7. Verification commands and evidence.**
```text
pytest tests/unit/workflows tests/unit/core \
       tests/unit/agent/result_interpretation_agent -q
pytest tests/unit/workflows/test_step09_5a_c4_single_writer.py \
       tests/unit/workflows/test_step09_5a_c0_oracle.py -q
```
- [ ] counts + wall time recorded; oracle delta declared or "none"

**8. Commit boundary.**
One value's complete travel. No findings change, no projection change.

---

### C3 — findings normalize onto `ChainState`

**1. Goal.**
Q-10-6 = A: the last bare cross-iteration local becomes a carried sibling —
`ChainState.accumulated_key_findings`, seeded from `RestoredState`, unioned
in-loop, read by the existing consumer block. The in-process amnesia (§2.2)
ends, as the DECLARED DD-1 delta.

**2. Scope.**
* `core/chain_state.py` — the field + `from_restored` param.
* `workflows/model_exploration.py` — the seed, the append closure beside the
  C2 closure, the consumer block (`:2278-2292`) reading
  `state.accumulated_key_findings`, the bare local retired; the stale
  `:2271-2277` comment corrected in passing (it names a dead function and
  sits on the exact lines touched).
* Non-goals: the union rule (unchanged, applied not re-implemented), the
  block's rendered BYTES (F-P56-1 stays), `project_knowledge`, prompts.
  Depends on C2 (shares the closure neighborhood; sequenced to keep diffs
  clean).

**3. Implementation plan.**
- [ ] Field + seeding (`list(...)` copy).
- [ ] The append closure: for each of `interpretation.key_findings`, append
      iff non-empty `str` and not already present — the `project_knowledge`
      rule verbatim (`:926-929`), stated in a comment referencing it.
- [ ] Consumer block reads the carrier; bare local removed from the unpack
      (the unpack row stays for `RestoredState` → seed only).
- [ ] Flip C0's findings-amnesia baseline to the accumulation expectation,
      citing this commit.
- [ ] Pin the rendered block bytes for a FIXED findings list (golden) —
      proving normalization moved ownership, not bytes.

**4. Validation plan.**
* Unit: append-rule parity with `project_knowledge` on the same fixture
  (duplicates, empty strings, non-str filtered identically).
* Integration/pseudo: 3-iteration drive — iteration 3's block contains
  iterations 1 and 2's findings exactly once each, order preserved.
* Negative: degraded (`[]`) and cold-start (the fixed sentence) iterations
  union correctly; a quiet iteration is a no-op.
* Backward-compat: chain-mode (1 iter/process) behaviour identical — the
  block's content comes from the same union it always restored.
* Gate: **NONE.**
* Guard flips: single-writer/reachability (13 fields now); oracle; c2 floor.

**5. Acceptance criteria.**
- [ ] The block's bytes for a fixed list are IDENTICAL pre/post (golden).
- [ ] The 3-iteration accumulation test green; the amnesia baseline flipped.
- [ ] Exactly two write sites for the new field (census).
- [ ] The retired local has zero remaining reads (grep recorded).

**6. Failure and edge cases.**
* Double-append on resume: restored union + re-union of the same digests must
  stay deduped (first-wins makes it idempotent — asserted, not assumed).
* An LLM returning duplicate findings within one iteration — deduped by the
  same rule.

**7. Verification commands and evidence.**
```text
pytest tests/unit/workflows tests/unit/core -q
pytest tests/unit/workflows/test_step09_5a_c4_single_writer.py \
       tests/unit/workflows/test_step09_5a_c0_oracle.py -q
```
- [ ] counts + wall time recorded

**8. Commit boundary.**
The second value's normalization. No confirmations change.

---

### C4 — resume equality + lifecycle censuses (both values)

**1. Goal.**
Prove the whole point: an uninterrupted in-process trajectory and a
stop/restore/continue trajectory produce EQUAL carried state; legacy digests
restore cleanly; exactly one writer per value; the digest key has exactly one
non-interpreter reader.

**2. Scope.**
Tests plus whatever narrow fix they expose (any production fix found here is
diagnosed per the diagnose-before-fixing rule and recorded). Depends on
C2+C3.

**3. Implementation plan.**
- [ ] Uninterrupted-vs-resumed equality: 3 iterations straight vs
      stop-after-commit / `restore_prior_state` / continue; deep-equal on
      BOTH carried values at the end.
- [ ] Legacy fixtures: pre-activation digests restore `{}` + the existing
      findings union; zero crash, zero fabrication.
- [ ] Corrupted-middle-digest: the §8.2 raise surfaces through restore's
      existing wrapper exactly as `prediction_memory`'s does (end-to-end, not
      just at the projection).
- [ ] Single-writer census extension proof: plant a second writer for each
      new field → RED; revert; tree clean.
- [ ] Single-reader census: plant a second digest-key reader outside the
      interpreter → RED; revert.
- [ ] Disposition `test_vocab_accumulation.py` H.4 (outside CI): docstring
      updated — its hand-threading now mirrors the PRODUCTION wiring instead
      of substituting for it; it KEEPS its node-level accumulation-semantics
      ownership (recorded per the test-disposition rule; no CI change).

**4. Validation plan.**
* Integration/pseudo: the two trajectories; the corrupted-restore negative.
* Backward-compat: the legacy fixtures.
* Gate: **NONE.**

**5. Acceptance criteria.**
- [ ] Deep-equality on both values, both trajectories.
- [ ] Every plant individually RED, reverted, recorded.
- [ ] A pre-activation digest set restores with no warning beyond the
      declared policy.

**6. Failure and edge cases.**
* Partial commit (digest written, iteration incomplete) — restore reflects
  the digest; the equality test's stop point is AFTER commit by design, and
  the mid-write case is the digest authority's existing contract (not
  re-tested here).
* Digest ordering asserted (C1) — reused.

**7. Verification commands and evidence.**
```text
pytest tests/unit/core tests/unit/workflows -q
```
- [ ] counts + wall time recorded

**8. Commit boundary.**
Lifecycle evidence closed. The S5 half of the child is COMPLETE at this
head (deterministic owners all green).

---

### C5 — composed-chain wiring closures (W1–W5)

**1. Goal.**
Make a composed run launchable and honest end-to-end from the OPERATOR
surface: the chain forwards the manifest; a canonical TIDMAD manifest ships;
subprocess children can resolve every in-tree binding; a composed
non-TIDMAD run stops silently borrowing TIDMAD reference science; the
composed-metric chain scoring route is pinned.

**2. Scope.**
* `sdsc_submission_scripts/_chain_common.sh` (+`run_chain.sh` usage text) —
  W1.
* `configs/task_composition/tidmad.yaml` — W2.
* `execute_tools/train_engine_sandbox.py`, `inference_single.py`,
  `denoising_score_single.py` — W3 bootstrap imports.
* `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:795`
  region — W4 condition.
* Tests — W5 pin.
* Non-goals: any seam/tuner data-selection change (CAP-SCOPE), any manifest
  schema change, Slurm submission mechanics beyond arg forwarding.
  Depends on: nothing in C1–C4 (parallel-safe), sequenced here to keep the
  lifecycle half contiguous.

**3. Implementation plan.**
- [ ] W1: parser entry + default + `build_app_args` forwarding (both lilab
      and SDSC paths); `--task_composition` documented in the usage block.
- [ ] W2: the shipped manifest, mirroring
      `tests/fixtures/step10_p1/tidmad/composition.yaml` against the shipped
      TIDMAD assets; a deterministic test asserts composed-TIDMAD ≡
      legacy-TIDMAD on the COMPOSITION INVARIANTS only (binding identity,
      fingerprint stability, zero secondary bytes, metric/scorer semantics,
      Health declaration, lifecycle) — per C-P56-1 the legacy-only implicit
      reference table is NOT in the parity set.
- [ ] W3: the two missing built-in imports per child, in the declared
      "built-ins' bootstrap" comment shape; a test resolves all three
      transported ids in a child-shaped process.
- [ ] W4 per the frozen C-P56-1 rule: the guard keys on **composition
      PRESENCE only** — an ACTIVE composition ⇒ NO implicit legacy
      reference-score loading (named absence + log line); legacy/un-composed
      ⇒ byte-for-byte unchanged. Five required tests:
      (1) legacy/un-composed preserves the existing 42-reference behaviour
      exactly; (2) composed TIDMAD has NO implicit legacy reference table;
      (3) composed Pets has none; (4) composed DAVIS has none;
      (5) **no TIDMAD metric-identity conditional is introduced into generic
      core** — an executable assertion over the diff (no new
      `TIDMAD_METRIC_ID` / task-name / score-sign conditional in
      orchestration/tuner core). C0's leak baseline flips here.
- [ ] W5: the mutation-backed pin (§10.5).
- [ ] Negative: a misspelled manifest path through the CHAIN surface fails
      closed before any LLM spend, with the composing error surfaced.

**4. Validation plan.**
* Unit: W2 invariant-set equivalence; W4's five C-P56-1 tests (legacy
  byte-for-byte; composed TIDMAD/Pets/DAVIS each reference-free; no
  metric-identity conditional in generic core); W3 resolution; W5 pin.
* Shell: a `bash -n` + an args-construction test in the existing
  launch-surface-parity family for W1.
* Negative/invalid: unknown manifest, unreadable manifest, manifest naming an
  unknown id — all through the chain surface.
* Backward-compat: an UN-composed chain launch builds byte-identical child
  argv (the P1 conditional-emitter property re-asserted at this surface).
* Gate: **NONE here** (C8 owns the real run).

**5. Acceptance criteria.**
- [ ] A composed TIDMAD chain command is constructible end-to-end from
      `run_chain.sh` (args-construction evidence, no real spend).
- [ ] Legacy chain argv byte-identical (test).
- [ ] All three in-tree ids resolve in child-shaped processes.
- [ ] The W4 leak baseline flipped; LEGACY reference behaviour byte-identical;
      ALL composed runs (TIDMAD included) carry the named absence, per
      C-P56-1.

**6. Failure and edge cases.**
* An SDSC submission path that silently drops the flag — both paths tested.
* A manifest referencing a missing shipped asset — fail-closed at compose
  time (existing behaviour, asserted from the new surface).
* W4 must not consult task identity in ANY form — not task names, not
  `TIDMAD_METRIC_ID`, not score sign/range (C-P56-1). The guard reads
  composition PRESENCE only; the dispatch census stays green over the diff
  and test (5) pins the surrogate-branch forms the census cannot see.

**7. Verification commands and evidence.**
```text
pytest tests/unit/sdsc_submission_scripts tests/unit/workflows \
       tests/unit/agent/tune_ml_hyperparam_agent -q   # targeted selections
bash -n sdsc_submission_scripts/run_chain.sh sdsc_submission_scripts/_chain_common.sh
```
- [ ] counts + wall time recorded

**8. Commit boundary.**
Operator-surface + wiring closures only. No lifecycle change, no seam
change.

---

### C6 — three-task orchestration closure through `run_workflow`

**1. Goal.**
The §10.3 matrix's deterministic column becomes executable: all three
compositions drive the ONE `run_workflow` (pseudo LLM, stub sandbox), with
direction, secondaries, Health binding, typed proposer evidence and carried
state asserted per task — DAVIS at ≥ 2 iterations with carried state live as
the lower-is-better falsifier — and the genericity censuses extended over
every file this PR touched. **Frozen honesty rule (§10.3): C6 MUST NOT label
its Pets/DAVIS pseudo sandbox inputs as task-correct training scope — it
proves ORCHESTRATION semantics only; task-correct contrast training is
CAP-SCOPE.**

**2. Scope.**
Tests + fixture-honesty docs. Production: none expected; any gap the drives
expose is diagnosed first and either fixed under an existing W-item's
ownership or recorded against CAP-SCOPE — never patched with task logic.
Depends on C2–C5.

**3. Implementation plan.**
- [ ] The TIDMAD composed drive: composed ≡ legacy on the loop's observable
      lifecycle COMPOSITION INVARIANTS (statuses, per-iteration artifacts,
      zero secondary bytes); the implicit legacy reference block ABSENT with
      the named absence, per C-P56-1.
- [ ] The Pets drive: loop initializes and traverses interpret → propose →
      implement → validate → plan under `accuracy`/higher; exactly
      `macro_f1` observational in evidence; implicit legacy reference block
      ABSENT (C-P56-1); Health binding state C reaches the tuner context (no
      `LEGACY_OMITTED`); real verdict evidence stays runner-owned (§10.4) —
      asserted as BINDING, not verdicts.
- [ ] The DAVIS drive, ≥ 2 iterations: `mse`/lower live end-to-end;
      `psnr`/higher + `mae`/lower observational; confirmations + findings
      carried across the boundary; the carried values contain nothing
      direction-shaped (structural assertion: run-name lists and strings
      only).
- [ ] The same-path proof: all three drives call `run_workflow` itself with
      only the composition differing — asserted structurally (one driver
      helper, parametrized by manifest; no per-task branches in the driver).
- [ ] The typed-boundary proof: the drives construct proposer input ONLY via
      the protocol (the raw-read census scope extended over any new test
      helper).
- [ ] Census scope extension: the task-identity dispatch census and the
      ordering-operand invariant re-run with this PR's touched files in
      scope; plants re-verified RED in at least one newly-touched file.
- [ ] Fixture honesty: the Pets/DAVIS fixture-comment "P6 owns driving Pets
      through the exploration loop" updated to name CAP-SCOPE and this
      child's actual closure depth.

**4. Validation plan.**
* Integration/pseudo: the three drives (the pseudo-full-loop tier — no API
  key, no GPU).
* Negative: a composition-bound drive with a deliberately wrong-direction
  assertion fixture proves the drive WOULD catch an inversion (anti-vacuity
  for the DAVIS falsifier).
* Backward-compat: the un-composed pseudo loop test still green unchanged.
* Gate: **NONE here.**

**5. Acceptance criteria.**
- [ ] All three drives green through ONE parametrized path; the DAVIS drive
      crosses ≥ 2 iterations with both carried values live and equal to the
      single-process expectation.
- [ ] Class (b) task-identity dispatch still 0 with the extended scope;
      plants RED.
- [ ] C0's loop baselines flipped with their deltas attributed (W4 flip; any
      baseline failure point now passing, or explicitly re-recorded).

**6. Failure and edge cases.**
* Trial-mode TIDMAD machinery (anchor maps, preflight fixtures) needed by
  the pseudo tuner — reuse the P2b C4 fixture arrangement; a drive must
  never stub AROUND `run_workflow` itself.
* A drive green only because health was disabled — the binding assertion
  makes that impossible (state C is asserted).
* Pseudo-response drift across the three tasks — one response set per task,
  provenance pinned in C0.

**7. Verification commands and evidence.**
```text
pytest tests/integration -q -k "three_task or full_exploration"   # pseudo tier
pytest tests/unit/workflows -q
```
- [ ] counts + wall time recorded

**8. Commit boundary.**
Deterministic closure evidence only. Production untouched (or the touched
W-item named).

---

### C7 — runner claims: enumeration, transfer, relabel

**1. Goal.**
Discharge Q-10-5 = B's precondition and its licensed half: every claim the
runners own enumerated from their sources, orchestration claims transferred
to C6's owners, real-execution claims RETAINED with the runners relabeled as
L3 evidence harnesses — no longer alternate orchestration paths.

**2. Scope.**
`scripts/run_pets_gate2.py` / `run_davis_gate2.py` docstrings + the packs'
`STATUS.md` + this ledger. `_gate2_health_stage.py` unchanged (it remains the
retained harnesses' health stage). Non-goals: deleting any script (blocked on
CAP-SCOPE per §10.4); changing runner behaviour. Depends on C6.

**3. Implementation plan.**
- [ ] Line-by-line claims audit of both runners against §10.4's table;
      corrections recorded here if the table missed a claim.
- [ ] **The §10.6 freshness audit, per retained track**: record the evidence
      provenance (SHA · artifact · result), compute the semantic dependency
      diff from the evidence SHA to the implementation candidate over the
      runner's real-execution surface, and record the verdict — evidence
      REMAINS AUTHORITATIVE (no rerun) or the affected bounded runner is
      rerun BEFORE the retained-evidence claim is made. No rerun for
      reassurance; no timeless reuse by assumption.
- [ ] Docstring relabel: "L3 real-execution evidence harness; orchestration
      claims owned by the generic-loop closure tests (named); full
      retirement blocked on CAP-SCOPE (named)".
- [ ] `STATUS.md` rows updated in both packs.
- [ ] The parent-§22.2 required order recorded as satisfied-with-deferral in
      this ledger, with each retained claim's distinct failure class stated.

**4. Validation plan.**
* Unit: the existing runner-adjacent tests still green (no behaviour change).
* Real execution: ONLY a §10.6-triggered bounded runner rerun, if the
  dependency diff demands one (~25 s per runner on the 5090; not a Gate — no
  LLM involved). The verdict either way is recorded with the diff evidence.
* Gate: **NONE.**

**5. Acceptance criteria.**
- [ ] Every §10.4 row verified or corrected against source, recorded.
- [ ] The §10.6 freshness verdict recorded per track, with the dependency
      diff as evidence (and the bounded rerun's result, if one was
      triggered).
- [ ] No repository text still describes the runners as the way a contrast
      task executes its lifecycle (grep recorded).

**6. Failure and edge cases.**
* A claim discovered with NO owner on either side — recorded as a finding
  and assigned (to C6's owners if orchestration-shaped, to CAP-SCOPE if
  execution-shaped); never silently dropped.

**7. Verification commands and evidence.**
```text
pytest tests/unit/scripts tests/unit/guardrails -q
grep -rn "run_pets_gate2\|run_davis_gate2" docs/ examples/ --include="*.md"
```
- [ ] outputs recorded

**8. Commit boundary.**
Docs/label-only + ledger. Independently reviewable as the Q-10-5 discharge
record.

---

### C8 — closure: Gate 2, docs sync, ledger, ONE exact-head CI

**1. Goal.**
The terminal evidence: the FIRST real composed chain run (Gate 2, §15),
operator docs current, censuses green at the final head, PR ready.

**2. Scope.**
Gate execution + its advice file; docs (`run_chain.sh` operator docs /
`docs/running_chain_test.md`; the tuner + interpreter node `.md`s for the
touched flags/fields; `resume.py` docstrings); the parent/roadmap/CLAUDE.md
status sync; this ledger; the PR. Depends on C0–C7.

**3. Implementation plan.**
- [ ] Re-read the gate standard and re-audit flag parsing from source
      immediately before launch (the §15 rulings' own rule 4).
- [ ] Gate 2 readiness packet written BEFORE launch — §15.2's exact shape:
      command · bounds · candidate SHA · clean-tree proof · deterministic
      prerequisites green · exact workload · projected runtime and cost ·
      the PASS / FAIL / INCONCLUSIVE taxonomy incl. the §15.2 non-vacuous
      evidence contract and its non-discriminating-workload FAIL rule.
- [ ] **Launch AUTONOMOUSLY** — the Gate is pre-authorized by this frozen
      design (§15.2's execution contract): if non-destructive AND projected
      total wall time ≤ ~1 h AND inside the normal GPU/API/cost envelope,
      launch without a further operator stop. Return to the operator ONLY if
      the projection materially exceeds that envelope or a frozen-contract
      change would be needed.
- [ ] Execute; verdict read from persisted artifacts and the log, never a
      wrapper exit code; the §15.2 two-layer restore evidence extracted from
      the persisted iteration artifacts and recorded here.
- [ ] Node/skill doc sync with each documented flag/default QUOTED against
      merged source (the pre-merge doc rule).
- [ ] Ledger closed: all checklists `[x]` with evidence or explicitly
      recorded not-done + why; deviations table; carried debt named
      (CAP-SCOPE, F-P56-1, the H.4 out-of-CI note).
- [ ] ONE exact-head CI on the final head; run id + tested SHA recorded;
      verdict from the log.

**4. Validation plan.**
* Gate 2 per §15 (REQUIRED, bounded, exactly 2 iterations × 1 round,
  composed TIDMAD — NOT expanded to 3: the ≥ 3-iteration property is
  deterministic-owned and must not be duplicated by the Gate).
* All prior targeted suites green at head, recorded per commit, not re-run
  wholesale.
* Gate 1: **NOT REQUIRED** (§15.1) — not launched unless its flip condition
  was triggered.

**5. Acceptance criteria.**
- [ ] Gate 2 PASS per the standard's functional criteria + the child's
      boundary evidence, ALL from persisted artifacts: the run was COMPOSED
      (fingerprint in the lock) **and** the §15.2 two-layer restore evidence
      holds — (A) iteration 1 produced ≥ 1 usable key finding, present in
      its committed interpretation artifact, and iteration 2's proposer
      `expert_context` contains those exact prior finding(s) through the
      `accumulated_key_findings` lifecycle (**if iteration 1 produced no
      usable finding, the Gate MUST NOT PASS** — a non-discriminating
      workload, not evidence); (B) iteration 1's output confirmations
      mapping deep-equals iteration 2's restored `InterpretationInput`
      mapping, provenance artifact-visible — recorded as stronger evidence
      if non-empty, and if `{}`, recorded WITHOUT any claim that the Gate
      proved non-empty confirmations reachability (that owner stays the
      deterministic ≥ 3-iteration test + four severing mutations).
- [ ] `CI tested SHA == final PR HEAD`; working tree clean.
- [ ] STOP at **READY FOR OPERATOR REVIEW — DO NOT MERGE**.

**6. Failure and edge cases.**
* A Gate failure is diagnosed from artifacts and fixed, never re-run
  hopefully; a fix moves the head and CI re-runs.
* No docs-only commits after the canonical CI (fold docs BEFORE the final
  push).

**7. Verification commands and evidence.**
- [ ] Gate command + workspace + artifacts location + verdict recorded here.
- [ ] CI run id, SHA, per-step results recorded here.

**8. Commit boundary.**
Closure only.

---

## 14. Validation matrix — one primary owner per claim

| claim | primary owner | commit |
|---|---|---|
| producer accumulation/promotion semantics preserved | unit goldens | C0 |
| projection merge rule + failure policy | unit (disagreeing digests; malformed raise; missing-key `{}`) | C1 |
| confirmations reach promotion across iterations | **deterministic ≥ 3-iteration reachability + 4 severing mutations** (S5's frozen owner) | C2 |
| producer branch symmetry (DD-2) | unit, three branches | C2 |
| findings accumulate in-process; bytes unmoved | pseudo 3-iteration + rendered-block golden | C3 |
| uninterrupted ≡ resumed | deep-equality twin trajectories | C4 |
| legacy absence / malformed state | legacy + corrupted fixtures end-to-end | C1/C4 |
| single writer / single reader | planted-offender censuses | C4 |
| chain launches a composed run; legacy argv byte-identical | args-construction + parity tests | C5 |
| children resolve all in-tree bindings | child-shaped resolution test | C5 |
| no implicit legacy reference science in ANY composed run; legacy path byte-for-byte; no metric-identity conditional in generic core (C-P56-1) | the five W4 tests | C5 |
| chain scoring consumes the bound metric | W5 mutation pin | C5 |
| three tasks traverse ONE `run_workflow`; direction/secondaries/health-binding/carried-state per task | parametrized pseudo drives (incl. the DAVIS ≥ 2-iteration falsifier + anti-vacuity inversion probe) | C6 |
| zero task-identity branches, extended scope | AST census + plants | C6 |
| runner claims each have a named owner | the C7 audit record | C7 |
| retained Pets/DAVIS L3 evidence is FRESH | the §10.6 provenance + dependency-diff audit (bounded rerun only if a semantics-bearing dependency changed) | C7 |
| the real composed chain lifecycle (real LLM/training/restore, with the NON-VACUOUS §15.2 two-layer restore witness) | **Gate 2** — the only claim nothing cheaper owns | C8 |
| repository-wide regression at the final head | ONE exact-head CI | C8 |

No claim has two expensive owners; no Gate duplicates a deterministic owner.

## 15. Gate rulings (assignment rows quoted, decided separately)

### 15.1 Gate 1 — NOT REQUIRED

Assignment rows (quoted from `docs/gates/gate_testing_standard.md`):
*"New LLM-facing system prompt | Gate 1"* and *"New agent node or workflow
wiring | Gate 1"*.

* No new or changed LLM-facing system prompt exists anywhere in this child:
  prompt TEMPLATES are byte-pinned by goldens (C2/C3); the confirmations
  mapping renders into no prompt (grep-proven, §9); the only LLM-visible
  changes are VALUES flowing through existing slots — the activation working,
  whose correctness owner is the deterministic lifecycle evidence per the
  FROZEN Q-10-3 ruling ("NOT a 3-iteration real Gate").
* The "workflow wiring" row is acknowledged and discharged: the wiring
  changes are exactly the deterministic-parity-covered carry pattern, and the
  REQUIRED Gate 2 already exercises the live values against a real LLM
  (iteration 2's interpreter receives a real restored mapping), so a separate
  Gate 1 would duplicate evidence the mandatory Gate produces.
* **Flip condition**: if implementation must change any prompt TEMPLATE bytes
  or a proposal-affecting schema, Gate 1 becomes REQUIRED (per the standard's
  row) before C8.

### 15.2 Gate 2 — REQUIRED: one bounded composed-TIDMAD chain, 2 iterations × 1 round

Assignment row (quoted): *"Checkpoint (end of feature) | Gate 2"*. Depth row
(quoted): *"cross-iteration behaviour or resume | ≥ 2 iterations"* —
instantiated at exactly **2 iterations, 1 round**, and deliberately NOT 3:
the ≥ 3-iteration promotion property is deterministic-owned (§14) and a
3-iteration real Gate would duplicate that owner, not add evidence.

**What it uniquely proves** (nothing cheaper can): the COMPOSED production
path has never executed for real (§2.5) — this Gate is its first real
execution: real LLM → real candidate → real training/inference/scoring under
an explicit composition, across a REAL chain restore that carries the new
state. Shape: the canonical bounded command (cold-start, no `--seed_paths`,
partial-scope pairing, `openai_tiered_pro.json` + the 4 GiB advice file, no
`tee`) with `--num_iterations 2 --max_rounds 1` and
`--task_composition configs/task_composition/tidmad.yaml`. Per C-P56-1 the
run's prompts carry the named absence of the legacy reference table — the
rule working, not a regression. PASS = the standard's functional criteria +
the two-layer evidence contract below.

**Execution contract (operator-frozen, 2026-08-21) — the Gate is
PRE-AUTHORIZED by this frozen design; there is NO separate pre-launch
operator stop.** Before launch the implementation session MUST: re-read the
current gate standard; re-read the actual current CLI/flags from source;
write the Gate-readiness packet; record the candidate SHA; prove the working
tree clean; record the deterministic prerequisites green; record the exact
workload; project runtime and cost; record the PASS / FAIL / INCONCLUSIVE
taxonomy. Then:

```text
non-destructive
AND projected total wall time <= ~1 hour
AND inside the normal GPU/API/cost envelope
    -> LAUNCH AUTONOMOUSLY. Do NOT stop for another approval.

materially exceeding that envelope, a new GPU allocation, unusual API
spend, or a frozen-contract change needed
    -> operator stop (the only one).
```

**The two-layer restore-evidence contract (non-vacuous by construction).**
`{} == {}` proves nothing; the Gate must inspect BOTH carried values from
persisted artifacts:

* **A — `accumulated_key_findings` is the REQUIRED non-vacuous witness.**
  Iteration 1 must produce at least one usable key finding, present in its
  committed interpretation artifact; after the REAL chain restore, iteration
  2's proposer `expert_context` must contain the exact prior finding(s) —
  the discriminating `real LLM → digest → restore → ChainState → proposer`
  proof. **If iteration 1 produces no usable finding, the Gate did NOT
  exercise the required carried-context boundary and MUST NOT PASS** — a
  non-discriminating workload / Gate failure, never "inconclusive evidence".
* **B — `vocab_link_confirmations` proves the exact restore MECHANISM.**
  Iteration 1's output mapping must deep-equal iteration 2's restored
  `InterpretationInput` mapping, with artifact-visible provenance. Non-empty
  ⇒ record the stronger evidence; `{}` ⇒ record the equality but claim NO
  non-empty-reachability — that scientific property's owner stays the
  deterministic ≥ 3-iteration test + the four independent severing
  mutations. The Gate proves the REAL restore mechanism; deterministic
  evidence proves non-empty promotion reachability. The owners stay
  separate.

**Corpus ruling under the FROZEN multi-track governance** (roadmap §22.13 /
§17.0.2, quoted): *"When a Gate IS required, its corpus MUST cover every
persistent validation track … that has reached executable maturity (L2+ …)
at the affected seam — TIDMAD always, plus Image and Spatiotemporal when
executable there; a not-yet-executable track contributes its highest honest
lower-level evidence and the design records why full Gate execution is
unavailable."* The affected real-execution seam is the **exploration-loop
chain path**, where the contrast tracks are NOT executable (§10.2's
capability finding — recorded here as the required "why"). They contribute
their highest honest evidence instead: the C6 deterministic loop drives plus
their retained L3 runner evidence (real training/inference/scoring/Health,
08c). **The genericity claim is NOT supported by the TIDMAD Gate** — its
owners are the censuses and the three-task drives (§14), keeping the
parent's "no TIDMAD-only Gate may support a genericity claim" satisfied by
assignment, not by hope.

**Forward note (ruling B applied)**: when CAP-SCOPE lands and the contrast
tracks become loop-executable, the real contrast-task chain Gate belongs to
THAT work (a dedicated capability PR or Step 12's L3→L4 climb) — never
retro-fitted into this child.

## 16. Failure / edge cases (cross-commit view)

| case | behaviour |
|---|---|
| legacy digest without the confirmations key | projects `{}`; never fabricated |
| malformed confirmations value | projection raises (§8.2); restore's wrapper decides run-level handling exactly as for `prediction_memory` |
| degraded iteration | input mapping carried through (`:1125`); findings `[]` union no-op |
| cold-start iteration | DD-2 carry-through; digest bytes identical for every pre-P5 input |
| round with no interpretation | closures do not run; state unchanged |
| same `run_name` confirming twice | producer dedups; latest-wins projection cannot double-count |
| feature absent from vocab at promotion time | producer skips (existing) |
| empty mapping vs missing key | distinct: `{}` is a legitimate cleared state and OVERWRITES on latest-wins |
| chain launch with a bad manifest | fail-closed at compose time, before LLM spend, from the operator surface |
| ANY composed run (TIDMAD included) | no implicit legacy reference science — named absence (C-P56-1); binding resolution in children (W3); the tune phase's REAL contrast training refusal is CAP-SCOPE's documented boundary |
| legacy / un-composed run | reference-score behaviour byte-for-byte unchanged (C-P56-1's other half) |
| resume of a pre-P5 workspace | restores with defaults; the invariants lock is untouched by this child (no new lock key) |

## 17. Risk register

| # | risk | mitigation |
|---|---|---|
| R1 | a second accumulation authority (workflow merging digests) | latest-wins projection + producer-owned accumulation + the single-writer/reader plants (C4) |
| R2 | reachability passes by fixture accident | four independent severing mutations, recorded individually |
| R3 | the in-process delta (DD-1) surprises a consumer | declared in §5; the equality test pins the new agreed behaviour |
| R4 | the three-task drives pass by avoiding the real path | one parametrized driver over `run_workflow` itself; protocol-only proposer input; anti-vacuity inversion probe |
| R5 | C5's chain-surface change breaks legacy launches | byte-identical legacy argv test + `bash -n` + launch-surface-parity family |
| R6 | W4 hides a legacy-TIDMAD regression, or smuggles a task-identity surrogate branch | the five C-P56-1 tests: legacy byte-for-byte; every composed run reference-free; an executable no-metric-identity-conditional assertion over the diff (the census-invisible surrogate form the operator's review caught) |
| R7 | the Gate discovers a composed-path defect late | C5's deterministic composed≡legacy equivalence runs long before C8; the Gate is confirmation, not discovery |
| R8 | scope creep toward CAP-SCOPE ("just make Pets train") | §10.2's boundary is explicit; C6's plan forbids task-logic patches; any gap is diagnosed → W-item or CAP-SCOPE |
| R9 | the census extension misses a newly-added module | C6 requires a RED plant in at least one newly-touched file |
| R10 | guard flips missed mid-PR (the P3 C3 failure) | the C0 guard-disposition table + every commit's "known flips" list + the oracle run wherever the envelope is touched |

## 18. Reconciliation of the old P5 / P6 documents

Every section of both superseded docs, dispositioned. (KEEP = adopted
verbatim-in-substance; REWRITE = adopted with corrections; SUPERSEDED =
replaced by a stronger source-grounded treatment; DELETE = dropped with
reason.)

**`pr_10_p5_interpretation_carried_state.md` (DRAFT rev 1):**

| old section | disposition | destination / reason |
|---|---|---|
| §0 status, `PROVISIONAL(P3)` | SUPERSEDED | §0 — P3 merged; the provisional wiring resolved to "typed value untouched, expert_context stays" (§9) |
| §1 parent contract | KEEP | §1 |
| §2 source audit (anchors at `d7d94740`) | REWRITE | §2 — re-measured at `ec6257fb`; moved anchors updated (`InterpretationInput` `:1934-1978`→`:2097-2151`; closure `:2710-2721`→`:2791-2805`; consumer `:2186-2205`→`:2278-2292`; `RestoredState` 15 fields `:203-236`); the **cold-start drop** finding is NEW |
| §2.1 aggregation rule derivation | KEEP | §2.1/§7.1 — re-verified against the producer body |
| §3 goal / non-goals | REWRITE | §4/§5 — "producer untouched" non-goal amended by DD-2 (declared, bounded) |
| §4.1 single writer | KEEP | §5/§8 |
| §4.2 failure policy + Q-P5-1 | REWRITE | §8.2 — RESOLVED (raise), no longer an open question |
| §4.3 declared delta | KEEP | §5 (DD-1) |
| §4.4 P3 boundary | SUPERSEDED | §9 — now structural fact, not intention (NOT_CARRIED verified) |
| §5 three-task control | SUPERSEDED | §10 — the closure half now owns it with real machinery |
| §6 structure preflight | REWRITE | §12 — re-measured (3,167 LOC; 130 branch nodes; the reachability-census constraint reshapes C1/C2) |
| §7 five commits C0–C4 | REWRITE | §13 C0–C4 — same evidence properties; boundaries redrawn around the measured reachability-census constraint (ChainState fields cannot land inert) and DD-2 |
| §8 validation / NO-Gate ruling | REWRITE | §14/§15 — the S5 deterministic ownership is unchanged; the child-level Gate posture now includes the closure half's Gate 2 |
| §9 preservation invariants | KEEP | §4/§16 |
| §10 edge cases | KEEP | §16 (+ cold-start row) |
| §11 risks | KEEP | §17 (merged) |
| §12 dependency map | SUPERSEDED | §0 — all dependencies merged |
| §13 Q-P5-1 | SUPERSEDED | §8.2 |
| §14/§14.1 post-P3 obligations | SUPERSEDED | §2.6 — all three DISCHARGED with evidence |
| §15 adversarial (draft-stage) | SUPERSEDED | §20 — re-run larger |

**`pr_10_p6_three_task_closure_skeleton.md`:**

| old section | disposition | destination / reason |
|---|---|---|
| §0 status ("blocked until the semantic children land") | SUPERSEDED | §0 — the condition is met (5 merged; the sixth semantic half is THIS child's C0–C4) |
| §1 purpose ("evidence, not new semantics") | KEEP | §1/§4 — held, with §10.2's discovery routed per its own rule |
| §2 dependency | SUPERSEDED | §0 |
| §3 no-new-semantic-contract rule | KEEP | §1/§10.2 — it is the rule that DECIDES the capability finding's ownership |
| §4 genericity claim + the three inherited hand-offs | REWRITE | §10/§2.5 — each hand-off verified and narrowed: (a) closed by construction + W5 pin; (b) split (in-tree = W3 here; out-of-tree = Step 12); (c) = C7 |
| §5 runner retirement | REWRITE | §10.4/C7 — enumeration concrete; retirement partially deferred per Q-10-5 = B's own precondition |
| §6 expected evidence | REWRITE | §10.3/§14 — honest depth per the capability finding + Q-P56-1 |
| §7 Gate posture TBD | SUPERSEDED | §15 — decided with quoted rows |
| §8 stop condition | SUPERSEDED | discharged: this IS the fresh-audit design it demanded |

**Stale content found in both and dropped**: the P6 skeleton's implicit
assumption that all remaining gaps were transport-shaped (the capability
finding corrects it); the P5 draft's `:1018`/`:1125` "output and digest"
phrasing (they are one object, two branches); the P5 draft's expectation that
`tests/integration/workflows/test_vocab_accumulation.py` might be "flipped"
wholesale (its H.4 keeps node-level ownership; §13-C4 dispositions it).

## 19. Operator freeze rulings (final freeze review, 2026-08-21) — QUESTIONS: 0

The operator reviewed DRAFT rev 1 in full (C0–C8, the validation matrix,
both Gate rulings, the three tracks, Q-P56-1, CAP-SCOPE, the structure
preflight) and returned: **architecture PASS · consolidation PASS ·
lifecycle PASS · validation topology PASS — no redesign, no re-split** —
plus the rulings and seven bounded corrections below, all applied in this
Revision 2.

### 19.1 Q-P56-1 — RESOLVED: **B — roadmap-depth Step-10 closure**

The measured capability gap is REAL (§2.5 (a)–(f): the frozen
caller-built-scope seam `task_data_path.py:100-103`; TIDMAD-only tuner
sample-set construction `planning.py:397-413`; no scope argv
`train_engine_sandbox.py:1976-1991`; the TIDMAD-shaped `DatasetProfile`
`dataset_config.py:45-63` with self-declared fabricated contrast fixtures;
the trial anchor-map requirement; the TIDMAD peek literal; the governance
census forbidding production from reading pack manifests). Options A (absorb
— extends a frozen D14 contract inside the terminal closure child across
≥ 4 upstream families) and C (a new prerequisite capability child) were
considered and rejected; **B is the ruling**: Step 10 delivers at the
roadmap's actual maturity depth (§10.2's frozen wording), the parent's
§16.1/§17.1/§26.O overclaim is amended, and **CAP-SCOPE is frozen as the
REQUIRED enabling capability before Pets/DAVIS may be declared L4 complete —
Step 12 MUST NOT claim contrast-track L4 while CAP-SCOPE remains open**
(§10.2; recorded on the roadmap's Step-12 row). Never silently moved.

### 19.2 Q-P5-1 — RESOLVED / APPROVED: malformed confirmations ⇒ RAISE

§8.2's ruling approved as frozen: promotion state fails closed; missing
pre-activation key ⇒ `{}`; unreadable digest ⇒ existing unusable handling;
latest valid mapping wins whole-dict.

### 19.3 C-P56-1 — implicit legacy reference science is FORBIDDEN in composed mode

The operator's load-bearing catch on DRAFT rev 1: W4's proposed
`TIDMAD_METRIC_ID` condition was a task/science identity branch in generic
core — invisible to the task-name census — and is REJECTED. The frozen rule
(§10.5): legacy/un-composed byte-for-byte; ANY composed run carries the
named absence; no generic-core branch on task name, `TIDMAD_METRIC_ID`,
score sign/range or any identity surrogate; a future composed task needing
reference/SOTA evidence requires a future GENERIC declared capability seam,
not invented here. Composed-mode parity claims narrowed to the composition
invariants (§10.5 W2, §13 C5/C6).

### 19.4 Gate rulings

* **Gate 1 NOT REQUIRED** (§15.1), flip condition frozen; never run for
  reassurance.
* **Gate 2 REQUIRED** (§15.2): composed TIDMAD, real LLM + real
  training/inference/scoring, exactly 2 iterations × 1 round (never 3 — the
  ≥ 3-iteration property is deterministic-owned); **pre-authorized
  AUTONOMOUS launch** inside the ≤ ~1 h / normal-budget envelope (the
  pre-Gate operator stop is DELETED as contradicting the standing
  Implementation Working Rules); the **non-vacuous two-layer
  restore-evidence contract** (findings = the required real witness, with
  the no-usable-finding ⇒ MUST NOT PASS rule; confirmations = exact-restore
  mechanism proof, never a non-empty-reachability claim when `{}`).

### 19.5 Three-task topology, freshness, honesty, structure

* The **orthogonal coverage is frozen** (§10.3): TIDMAD deepest-real ·
  Pets classification/higher/secondary contrast · DAVIS strongest
  discriminating falsifier; Pets deliberately NOT required to run
  ≥ 2 iterations; ONE parametrized C6 driver, composition the only
  variable.
* The retained Pets/DAVIS L3 evidence carries the **freshness contract**
  (§10.6, C7) — provenance + semantic dependency diff; bounded rerun only
  when a semantics-bearing dependency changed; never a rerun for
  reassurance, never timeless reuse.
* **C6 honesty rule** frozen verbatim (§10.3): orchestration closure only,
  never contrast L4.
* The C0–C4 lifecycle validation set is **APPROVED AS DESIGNED** and must
  not be weakened or duplicated by a real Gate.
* The structure ruling is accepted with the **§12.1 tripwire** frozen.

**Open required operator questions: 0. Material contradictions: 0.
Unresolved PROVISIONAL semantics: 0.**

## 20. Adversarial self-review

The operator-required attack list, answered from source (§ references are
this document's):

| attack | answer |
|---|---|
| Can `accumulated_key_findings` exist in memory but disappear on resume? | No — the projection is the EXISTING union over committed digests; C4's twin-trajectory equality is the acceptance, and the closure applies the projection's own rule so the trajectories agree by construction |
| Can `vocab_link_confirmations` reach iteration 2 but not 3? | Only by severing a specific hop — and each of the four hops has its own mutation proof (C2); the reachability test asserts promotion at 3 and NOT at 2 |
| Can fresh-run and resume construct different state semantics? | No — one projection, one seed path, one closure; C4 deep-equality; no second loader (census) |
| Can a quiet iteration erase prior findings? | No — findings closure is a union (no-op on empty); confirmations closure writes the producer's carry-through (equal value); a no-digest round runs no closure |
| Can a failed iteration incorrectly advance carried state? | No — degraded carries input through verbatim (verified `:1125`); DD-2 extends the same rule to cold start; nothing else writes |
| Can the same semantic live in ChainState AND another artifact with two writers? | No — the digest is the persistence LOG, ChainState the in-process carrier, exactly the sibling architecture; the planted second-writer/second-reader censuses are C4 acceptance |
| Can TIDMAD pass while Pets/DAVIS fail because a field is task-specific? | The carriers hold run-name lists and strings — structurally task-free; the DAVIS ≥ 2-iteration drive is the executable form; the extended dispatch census the structural form |
| Can DAVIS inherit a hidden higher-is-better assumption from carried state? | Nothing ordered enters the carriers (no scores, no directions); the DAVIS falsifier drive + the C6 anti-vacuity inversion probe make a violation observable |
| Can raw secondary values leak into proposer state through the lifecycle? | No path exists: the carried values are the Q-P3-3-legitimate synthesized channel; `NOT_CARRIED` still refuses both raw carriers; the prompt-absence probes and the ordering-operand invariant stay green over the diff |
| Can P5/6 accidentally implement Step-12 task-package semantics? | §11's boundary + W3's explicit in-tree/out-of-tree split + CAP-SCOPE explicitly NOT silently Step 12 |
| Can three-task tests pass via per-task hand-written runners instead of the generic path? | C6's structural assertion: one parametrized driver over `run_workflow` itself; the retained runners are relabeled evidence harnesses and own no orchestration claim (C7) |
| Can a "three-task closure" test avoid the P3 typed boundary? | No — driving `run_workflow` forces the protocol's `build_proposer_evidence`; the raw-read census scope covers the new helpers |
| Can a census be green because its scope misses a newly extracted module? | C6 requires a RED plant in at least one newly-touched file; no module extraction is planned at all (§12) |
| Are any proposed Gates duplicating deterministic evidence? | §14 assigns one owner per claim; the single Gate owns exactly the one claim (real composed-chain lifecycle) with no deterministic owner; Gate 1 explicitly ruled out as duplicative |
| Does any step grow `model_exploration.py`/`resume.py` into a worse mixed structure? | §12: sibling-shaped additions only, measured branch headroom, no new phase, no new owner; the structure preflight is the binding record |
| Can the consolidation itself hide an unreviewable mega-PR? | 9 commits, each with the 8-section plan and its own boundary; review decomposition preserved; ONE CI per the validation-economy rule |
| Can C0's baselines go stale before C6 flips them? | Each baseline names the commit that flips it (the guard-disposition table); an unflipped baseline at C8 is a ledger error, checked in C8's closure list |
| Can the Gate pass while the composition silently didn't bind? | C8's PASS criteria include the composed fingerprint in the run-invariants lock and the §15.2 two-layer restore evidence — artifact-verified, not assumed |
| Can the Gate's restore evidence pass VACUOUSLY on empty carried state? | Not anymore — **CORRECTED by the operator's freeze review**: `{} == {}` is excluded by contract; findings are the required non-vacuous witness (no usable iteration-1 finding ⇒ the Gate MUST NOT PASS), and an empty confirmations equality is recorded without any reachability claim (§15.2) |
| Can generic core keep a task-science identity branch the census cannot see? | The one proposed instance (W4's `TIDMAD_METRIC_ID` condition) was **caught by the operator's review and REJECTED (C-P56-1)**: the guard keys on composition presence only, and C5's test (5) pins that no metric-identity/surrogate conditional enters generic core — covering exactly the shape the AST task-name census is blind to |
| Can retained L3 evidence silently go stale under this PR's own changes? | No — the §10.6 freshness contract: provenance recorded, semantic dependency diff computed, bounded rerun triggered iff a semantics-bearing dependency changed (C7 acceptance) |

## 21. Definition of done

* [ ] C0–C8 all `[x]` with recorded evidence (counts, wall times, guard
      flips, mutation records).
* [ ] Both carried values: producer → digest → projection → `RestoredState` →
      `ChainState` → consumer, reachability-proven (severing mutations) and
      resume-equal.
* [ ] The composed chain launchable from the operator surface; legacy argv
      byte-identical; the shipped TIDMAD manifest canonical.
* [ ] Three-task orchestration closure green through ONE parametrized
      `run_workflow` path; class (b) = 0 with extended scope; DAVIS
      ≥ 2-iteration carried-state falsifier green.
* [ ] W1–W5 each closed with their paired negative/parity evidence — W4 per
      the C-P56-1 rule with all FIVE tests (legacy byte-for-byte; composed
      TIDMAD/Pets/DAVIS reference-free; no metric-identity conditional in
      generic core).
* [ ] Runner claims enumerated; orchestration claims transferred; retained
      claims named with their failure classes; relabels landed; **the §10.6
      freshness verdict recorded per retained track** (bounded rerun result
      included if one was triggered).
* [ ] Gate 2 PASS on the composed chain with the **§15.2 two-layer
      non-vacuous restore evidence** (findings witness mandatory;
      confirmations exact-restore provenance recorded); launched
      autonomously inside the pre-authorized envelope; Gate 1 not run (or
      its flip condition documented as triggered and PASS).
* [ ] The §12.1 structure tripwire held: pre/post `run_workflow` LOC +
      branch counts recorded; delta sibling-shaped.
* [ ] ONE exact-head CI SUCCESS on the final PR head; tree clean.
* [ ] Carried debt recorded, not hidden: **CAP-SCOPE (§10.2 — the REQUIRED
      prerequisite for contrast-track L4; Step 12 may not claim L4 past
      it)**, F-P56-1 (§2.2), the H.4 out-of-CI note (C4), HD-T5/HD-T6
      (unchanged, P4's), and the C0 residual-debt check's recorded hits for
      the roadmap's "resume/dashboard direction literals" line (owner
      outside this child unless a touched line repaired one in passing).
* [ ] Parent §20 amendment, §4.1 map, roadmap Step-10 row and CLAUDE.md all
      reflect the consolidated topology and this child's outcome.
* [ ] STOP at **READY FOR OPERATOR REVIEW — DO NOT MERGE**.
