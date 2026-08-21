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
- [x] Producer accumulation golden: drive `update_vocab_link_confirmations`
      over a FIXED outcome sequence (confirmed / partial / refuted /
      confirmed, distinct `run_name`s, a repeated `run_name`) pinning the
      returned `(confirmations, vocab, newly_promoted)` at each step —
      including that `partial`/`refuted` change nothing, a run cannot confirm
      twice, and promotion fires at exactly `min_runs` DISTINCT runs
      (`min_runs` passed explicitly where the claim is about the threshold).
      → `tests/unit/agent/result_interpretation_agent/test_step10_p56_c0_producer_baseline.py`,
      `TestProducerAccumulationTrajectory` (4 tests). **Unique failure class
      established first** (CLAUDE.md test rule): `test_vocab_feedback.py`
      :965-1160 already covers per-call semantics with 13 SINGLE-call tests, so
      this golden owns the one thing they structurally cannot — the
      **trajectory**, feeding each call's output back in as the next call's
      `existing_confirmations`. It fails iff the producer ever returns a DELTA
      instead of the cumulative map, which is the exact premise §2.1's
      latest-wins projection rests on and which every single-call test would
      survive. Also pins the §2.1 whole-map re-scan (an old key promoting later,
      once its feature appears).
- [x] The broken-lifecycle census, executable and named: `RestoredState` has
      NO `vocab_link_confirmations` field; no `project_*` produces one; the
      production `InterpretationInput(...)` does not pass it. INVERTED by
      C1/C2, never deleted.
      → `tests/unit/workflows/test_step10_p56_c0_broken_lifecycle.py` (8 tests).
      Splits by the commit that flips it: `TestResumeHalfIsMissing` (C1) ·
      `TestWorkflowHalfIsMissing` (C2). The `InterpretationInput` half is an
      **AST census over the real construction site**, not a grep — exactly one
      call node in `run_workflow`, 19 keywords, the field absent. Field counts
      pinned at the §2.3 measurements (RestoredState 15 · ChainState 11) so a
      silent widening is visible here too.
- [x] The cold-start drop pin (DD-2's before-picture): a cold-start
      interpreter invocation with a non-empty input mapping returns an output
      whose mapping is `{}` — recorded as the defect, with the test docstring
      naming §7.3.
      → `TestColdStartDropsTheCarriedMapping` (2 tests), same file as the
      producer golden. Its twin asserts the DEGRADED branch (`:1125`) already
      carries the mapping through — the asymmetry DD-2 removes, made executable
      rather than asserted in prose.
- [x] Findings-amnesia baseline: a 3-iteration in-process pseudo drive
      records that iteration 3's expert-context block equals iteration 1's
      (no accumulation) — the §5 DD-1 before-picture.
      → `tests/unit/workflows/test_step10_p56_c0_multi_iteration_baseline.py`,
      `TestFindingsNeverAccumulateInProcess` (3 tests), driving the REAL
      `run_workflow` for 3 iterations with the five agent classes stubbed.
      **Sharper than the design anticipated**: with nothing restored the bare
      local is `None`, so the `ExpertContextItem(kind="findings")` block never
      renders AT ALL — iteration 3 does not merely repeat iteration 1's block,
      it receives no findings block in any iteration, while iterations 1 and 2
      produced real findings. Carries its own anti-vacuity test (the loop
      really ran 3 iterations and really produced findings to forget).
- [x] 3-iteration confirmations baseline: a link confirmed in three distinct
      runs does NOT promote today (the exact scenario C2 turns green).
      → same file, `TestConfirmationsNeverReachTheNextIteration` (3 tests):
      every iteration's `InterpretationInput.vocab_link_confirmations` is `{}`
      even though the interpreter returned a cumulative 3-run mapping, plus the
      named scientific consequence (`min_runs=3` unreachable) and an
      anti-vacuity test proving the emptiness is a TRANSPORT failure rather
      than an absent producer.
- [x] Three-task loop baseline: drive `run_workflow` (pseudo LLM, stub
      sandbox) once under the Pets fixture composition and once under DAVIS,
      recording CURRENT behaviour — including that TIDMAD reference numbers
      DO leak into the prompt tables today (the W4 before-picture) — as
      baselines C5/C6 flip. If a drive cannot complete today, record the
      exact failure point as the baseline instead (an honest baseline is
      whatever today does).
      → `tests/unit/workflows/test_step10_p56_c0_three_task_baseline.py`
      (10 tests). **Composed TIDMAD completes one iteration; composed Pets and
      DAVIS CANNOT START** — the exact failure point is recorded as
      **F-P56-2** (§22.4), a blocking wiring defect §2.5 did not list, found
      precisely because this is the first time a contrast composition traversed
      `run_workflow` itself. W4's before-picture is recorded separately and
      **confirms §2.5's wording**: the leak is silent, not a crash, because
      Pets (4 files) and DAVIS (3) both declare FEWER files than the 20 TIDMAD
      ships references for, so every `_fine_indices()` lookup hits an existing
      TIDMAD artifact. The un-composed 20-reference behaviour is pinned in the
      same class as the half C5 must NOT change.
      Also records a binding **C6 constraint**: one process may bind exactly
      one Health plugin set, so the C6 parametrized driver must
      `reset_run_scope()` between tasks (the established fixture shape) or it
      passes only for whichever task runs first.
- [x] Malformed/legacy digest payloads (missing key, non-dict, unreadable)
      recorded as they behave TODAY, so C1 has a before-picture.
      → `TestMalformedPayloadsAreInertToday` (2 tests) in the broken-lifecycle
      census. Records the honest before-picture: because **no reader exists**,
      five distinct garbage shapes under the key (bare string · list · str
      value · non-str members · non-str key) are completely INERT — all four
      existing projections tolerate them and nothing raises. This is what makes
      C1's `raise` demonstrably NEW behaviour rather than a pre-existing one.
- [x] The guard-disposition table in this ledger: every existing test this PR
      will turn red, with the commit that flips each (known set: the
      broken-lifecycle census itself; the c4 single-writer reachability
      parametrization gains 2 fields at C2/C3; the c2 carriers floor; the
      Step-09.5a oracle envelope if any `ProposalInput`/workflow surface
      moves; `test_vocab_accumulation.py` H.4's hand-threading note).
      → **§22.6**, 18 rows. Adds one guard interaction §2.3 did not name: the
      single-writer census's `_bare_local_writes` will flag the EXISTING bare
      local `accumulated_key_findings` (`model_exploration.py:1942`) the moment
      C3 declares the `ChainState` field, so C3 must RENAME the unpack row to
      `restored_accumulated_key_findings` (the sibling convention), not merely
      stop reading it. Written into the plan rather than discovered mid-commit.
- [x] Roadmap residual-debt check, recorded in this ledger: grep the
      dashboard/resume surfaces for any remaining direction-word LITERAL
      (the roadmap's "resume/dashboard direction literals" line); record
      each hit with its owner — outside this child unless a commit here
      touches that exact line.
      → **§22.3: the debt is already CLOSED.** `core/resume.py` has zero
      direction literals of any form; `dashboard/` has zero live ones. The
      single grep hit (`dashboard/data_sources/base.py:124`) is a P2a-C3
      docstring *recording* the historical correction, and its method reads
      direction from each record's persisted metric identity. Nothing
      outstanding, nothing owed by this child.
- [x] Byte-stability: every golden identical across two independent runs.
      → 30/30 passed on two independent invocations (11.48 s · 14.33 s). Every
      expectation in C0 is a hardcoded in-module literal, not a written golden
      file, so there is no `tmp_path`, timestamp or set-iteration order to leak
      into a baseline.

**4. Validation plan.**
* Unit: the goldens above; deterministic, `tmp_path` only.
* Integration/pseudo: the two 3-iteration baselines + the two loop drives.
* Negative/invalid: the malformed-digest recordings.
* Backward-compat: none needed — nothing changes.
* Gate: **NONE** (no real LLM, no training; Gates are C8's only).

**5. Acceptance criteria.**
- [x] `git diff --stat` shows only `tests/` and `docs/`. → verified via
      `git status --porcelain` filtered against `^(tests/|docs/)`: **no path
      outside them**. Four new test files + this ledger. ZERO production edits.
- [x] The broken-lifecycle census PASSES on the unmodified tree (it asserts
      absence, not desired presence). → 8/8 green with production untouched.
- [x] Both 3-iteration baselines record the DEFECT (no promotion; no
      accumulation) with docstrings saying so. → 6/6 green, each class
      docstring naming the commit that flips it (C2 / C3) and each carrying an
      anti-vacuity test so the defect cannot be recorded by an inert drive.
- [x] The loop baselines record today's behaviour (or today's exact failure
      point) for Pets and DAVIS compositions. → composed TIDMAD completes;
      composed Pets/DAVIS record the exact failure point (**F-P56-2**, §22.4)
      with its provenance asserted from the raised error.
- [x] Goldens byte-stable across two runs. → 30/30 twice.

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
- [x] counts + wall time recorded here

  | run | result |
  |---|---|
  | the four new C0 files | **30 passed**, 11.48 s (and 12.76 s / 14.33 s on re-runs) |
  | + the three Step-09.5a guards (`c4_single_writer`, `c2_carriers`, `c0_oracle`) | **68 passed**, 13.32 s — the oracle envelope is UNMOVED and the single-writer reachability parametrization still covers 11 fields, both expected at C0 (no carrier added) |
  | `ruff check` + `ruff format --check` over all four files | PASS (import ordering auto-fixed, no rule disabled) |

- [x] any test that could not run recorded WITH the reason (never "passed")
  * **pyright: NOT RUN LOCALLY — cannot be.** `node --version` is **v10.19.0**;
    the bundled pyright requires a newer Node and aborts with a `SyntaxError`
    inside `pyright.js` before analysing anything. This is exactly the
    limitation CLAUDE.md's "Environment assumptions" names, so it is recorded
    rather than claimed: **static type checking of this PR is CI-owned**, and
    the C8 exact-head CI is its evidence. No other test was skipped.

**8. Commit boundary.**
Independently reviewable as "here are the defects and today's behaviour,
executable". No production change, no cleanup. Diff summary + staged list
recorded here before committing.

**Staged at commit time** (production diff empty, by construction):

```text
A  tests/unit/agent/result_interpretation_agent/test_step10_p56_c0_producer_baseline.py
A  tests/unit/workflows/test_step10_p56_c0_broken_lifecycle.py
A  tests/unit/workflows/test_step10_p56_c0_multi_iteration_baseline.py
A  tests/unit/workflows/test_step10_p56_c0_three_task_baseline.py
M  docs/design/generic_framework_upgrade/step_10_orchestration_task_binding/
     pr_10_p5_6_lifecycle_and_three_task_closure.md
```

**C0 VERDICT: COMPLETE.** 30 baseline tests; one blocking production defect
found and recorded (**F-P56-2**); the guard-disposition table opened with one
interaction §2.3 had not named (the C3 bare-local rename).

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
- [x] Implement the projection with §7.1's frozen rule: latest-wins
      whole-dict; missing key ⇒ `{}`; malformed ⇒ raise (§8.2's exact policy,
      message naming the digest, the `prediction_memory` precedent's shape);
      unusable digest ⇒ the sibling `digest_unusable_message` warn-and-skip.
      → `core/resume.py::project_vocab_link_confirmations`, placed between
      `project_prediction_memory` and `project_knowledge_cache`. The
      warn-and-skip uses the shared `digest_unusable_message` with its own
      carry-over label `"vocab-link-confirmations"` — the one thing that varies
      between the sibling messages, so an operator can tell which value was
      affected.
- [x] Shape validation `dict[str, list[str]]` with string members; the
      projection passes run lists through UNVALIDATED for dedup (the producer
      is the only promotion-count authority) — pinned by a pass-through
      assertion.
      → `test_run_lists_pass_through_without_dedup` stores a duplicate the
      producer would never write and asserts it survives verbatim. Also pinned:
      the projection copies rather than aliases the payload.
- [x] Add `RestoredState.vocab_link_confirmations` (additive, defaulted) +
      the docstring row. → 15 → **16** fields; docstring row states the
      latest-wins rule AND why (the producer already accumulates).
- [x] Wire the assignment beside `:1480`. → one line after
      `state.prediction_memory = project_prediction_memory(digest_reads)`.
- [x] INVERT C0's broken-lifecycle census resume half: the field and the
      projection must now EXIST (the workflow half stays asserted-absent
      until C2).
      → `TestResumeHalfIsMissing`'s three tests inverted **in place**, each
      docstring recording what it replaced. Its third test was strengthened
      while inverting: the "only non-interpreter reader" claim is now an **AST
      census** (`_digest_payload_reads`) over subscript, `.get()` AND `in`
      forms, asserting exactly one owning function — a substring check would
      have been satisfied by a mention in a docstring.

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
- [x] `RestoredState` carries the value; `restore_prior_state` assigns it.
      → 16 fields; one assignment beside `prediction_memory`'s.
- [x] The projection is the ONLY non-interpreter reader of the digest key
      (grep census recorded). → **AST** census, not grep:
      `_digest_payload_reads` returns exactly
      `["project_vocab_link_confirmations"]` over subscript / `.get()` / `in`
      forms across the whole module.
- [x] End-to-end behaviour UNCHANGED: C0's 3-iteration baseline still records
      no promotion (declared inert state). → C0's multi-iteration baselines
      stay green untouched; the value is restored and consumed by nothing,
      which is C1's declared inert state.
- [x] The Step-09.5a oracle run explicitly (RestoredState is inside its
      envelope); any delta DECLARED in its docstring, none expected.
      → run at this head: **PASS, delta = NONE**, as predicted (a 1-iteration
      snapshot restores `{}` and no node envelope moves). No re-baseline.
- [x] pyright clean over touched modules (or recorded CI-owned).
      → **recorded CI-owned**; see C0's note — local Node is v10.19.0 and the
      bundled pyright aborts before analysing.

**Validation record.**

| run | result |
|---|---|
| `tests/unit/core/test_step10_p56_c1_confirmations_projection.py` | **17 passed**, 3.70 s |
| targeted resume + oracle + census (`test_resume` · `test_step09_5a_c1_digest_authority` · `test_step09a_c5_prediction_transport` · `test_cold_start_resume` · the C1 projection · the Step-09.5a oracle · the C0 census) | **134 passed**, 4.69 s |
| `pytest tests/unit/core -q` (the §13 C1 command) | **2493 passed, 0 failed**, 164.53 s — see the flake note below |
| `ruff check` + `ruff format --check` on `core/resume.py` + the touched tests | PASS |

**Flake diagnosed, not assumed (recorded because the harness lied about it).**
The FIRST `tests/unit/core` run reported `1 failed` —
`test_gpu_measurement_runner.py::TestAWorkerThatLeavesNoReport::
test_a_hung_worker_is_killed_at_the_deadline` — while the background-task
notification reported **"exit code 0"** (that is the WRAPPER's status, the
CLAUDE.md-documented trap; the verdict was read from the log). Diagnosis before
any action, per the diagnose-before-fixing rule:

* the test asserts a real process GROUP is reaped within `deadline_seconds=0.4`
  after spawning a grandchild — pure subprocess timing;
* C1's diff touches only `core/resume.py`'s new pure projection, one dataclass
  field and one assignment, none of which can influence process reaping;
* it passes **3/3 in isolation** on the same tree;
* the failing run had a SECOND pytest process running concurrently on the same
  machine (a targeted suite launched while this one was backgrounded) — a
  specific, sufficient cause for missing a 0.4 s reaping deadline.

Re-run **uncontended: 2493 passed, 0 failed**. Classified as a load-sensitive
pre-existing flake in an unrelated subsystem, NOT a C1 regression and NOT this
child's to fix. Practical lesson for the rest of this PR: **do not run two
pytest processes concurrently** — timing-sensitive tests elsewhere in the suite
will report false failures.

Two sibling guards were specifically checked because the fifth projection
could plausibly have moved them, and neither did:
`test_step09_5a_c1_digest_authority.py::TestOneReadPerDigestPerPass` still
counts **one** file open per digest for the whole pass (projections are pure
over the already-read `DigestRead`s), and `TestWarningMultiplicityIsPreserved`
still holds because it counts warnings per carry-over LABEL rather than as a
fixed total — the new `"vocab-link-confirmations"` label is a fifth
per-value warning, which is the documented shape.

**6. Failure and edge cases.**
* Digest ordering: ascending committed order is assumed by the siblings —
  asserted here, not inherited.
  → [x] `test_ascending_digest_order_is_what_latest_means` projects the same
  two digests in both orders and asserts the results DIFFER, so "latest" is
  pinned to the order rather than to the content.
* Non-string keys / non-list values / non-string members ⇒ raise (§8.2).
  → [x] five parametrized shapes, each asserted by message fragment AND by the
  digest provenance (`iter 003`, the filename) so a correct refusal for the
  wrong reason is not accepted. Plus the case that matters most: a malformed
  LATER digest refuses instead of silently keeping the earlier mapping.
* Duplicate run_name inside a stored list ⇒ passes through (producer-owned).
  → [x] asserted; the projection also copies rather than aliases the payload.

**7. Verification commands and evidence.**
```text
pytest tests/unit/core -q
pytest tests/unit/workflows/test_step09_5a_c0_oracle.py -q
```
- [x] counts + wall time recorded — see the validation record above
      (`tests/unit/core` **2493 passed / 0 failed**, 164.53 s; oracle PASS with
      delta NONE; 17 + 134 targeted).

**8. Commit boundary.**
Resume substrate only. No carrier, no consumer, no loop change.

**C1 VERDICT: COMPLETE.** Production diff = `core/resume.py` only (+1
projection, +1 `RestoredState` field, +1 assignment). `ChainState`, the
workflow and the producer are untouched, so C0's multi-iteration baselines
still record the defect — the declared inert state.

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
- [x] ChainState field + `from_restored` seeding (defensive copy, the
      sibling idiom). → `current_vocab_link_confirmations`, 11 → **12** fields;
      the seed deep-copies per key (`{k: list(v)}`), since the loop replaces the
      whole mapping each iteration.
- [x] Workflow seed + closure + input pass — three sites, each mirroring its
      named precedent line. → unpack `:1960` · `from_restored` kwarg `:1979` ·
      `InterpretationInput` kwarg `:2124` · closure `:2822` (beside
      `current_prediction_memory`'s at `:2795`).
- [x] DD-2 in the producer's cold-start branch:
      `vocab_link_confirmations=dict(inp.vocab_link_confirmations)`; flip
      C0's cold-start drop pin to the carry-through expectation.
      → done; the flip also gained an alias test (the degraded branch's
      `dict(...)` idiom is matched exactly). **Parity premise verified from
      source, not assumed**: `InterpretationOutput.model_dump_json()` already
      emits `vocab_link_confirmations: {}` today, so for every pre-P5 caller
      (whose input is `{}`) the cold-start digest bytes are unchanged.
- [x] The ≥ 3-iteration reachability test (§7.4): promotion at iteration 3,
      NOT at 2 — the threshold observable, not just the endpoint.
      → `tests/unit/workflows/test_step10_p56_c2_confirmations_reachability.py`
      (**19 tests**), S5's frozen primary evidence owner. It drives the REAL
      `run_workflow` with the REAL producer (`update_vocab_link_confirmations`)
      over whatever the workflow carried in — a stub echoing a pre-computed
      mapping would have proven transport while ASSUMING the accumulation the
      promotion depends on. `promoted == [[], [], [KEY]]`, plus an independent
      2-iteration drive for the negative half.
- [x] **Mutation proof, one per link**: sever the projection assignment, the
      seed, the closure, and the input pass INDEPENDENTLY; each severing
      turns the reachability test RED; each recorded individually
      (count==1-site discipline, caches cleared — the mutation-hygiene
      memory). → **all four RED**; table in §22.8.
- [x] Flip C0's 3-iteration confirmations baseline from records-the-defect to
      records-the-fix, citing this commit. → `TestConfirmationsNeverReachTheNextIteration`
      inverted in place; it now owns the narrower TRANSPORT claim (latest-wins,
      verbatim, not re-merged) while reachability moves to the module above.
- [x] INVERT the remaining (workflow) half of the broken-lifecycle census.
      → done, and extended with a positive single-writer assertion for THIS
      value: exactly one `state.current_vocab_link_confirmations = ...`
      attribute write exists (the closure); the seed is a keyword argument.

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
- [x] Reachability green with all four severing mutations individually RED.
      → §22.8; 19 tests green, four mutations RED, all restored sha-verified.
- [x] No new digest key: digest bytes unchanged for every pre-P5 content
      state (the field was already serialized). → verified from source: a
      cold-start `InterpretationOutput` already serializes
      `vocab_link_confirmations: {}`, so DD-2 changes no bytes when the input
      is empty (the pre-P5 case).
- [x] Prompt templates byte-identical (goldens); the only value-level change
      is the activation itself. → the Step-09.5a oracle and the interpreter
      prompt goldens are green unchanged; the mapping is structured state and
      renders into no template.
- [x] The dedup drift case pinned: the same `run_name` confirming in two
      iterations counts ONCE (producer semantics preserved through the
      carry). → pinned TWICE: in-process (three iterations under one run name
      stay at one entry) and **across the restore boundary**, where a restored
      name repeated this iteration still yields two distinct runs and does NOT
      promote. That second case was found by a genuine test failure — the
      first draft restored `["model_a","model_b"]` and then confirmed
      `model_a` again, expecting promotion; the producer correctly deduped.
      The near-miss is now an explicit assertion rather than a silent fix.

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
- [x] counts + wall time recorded; oracle delta declared or "none"
      → **1212 passed / 0 failed**, 114.80 s (`tests/unit/workflows` +
      `tests/unit/agent/result_interpretation_agent` + the C1 projection +
      `test_resume` + `test_cold_start_resume`). **Oracle delta: NONE** — no
      re-baseline. The single-writer census, its reachability
      parametrization (now 12 fields) and the c2 carriers floor are all green.
      `ruff check` + `ruff format --check` PASS. pyright CI-owned.

**8. Commit boundary.**
One value's complete travel. No findings change, no projection change.

**C2 VERDICT: COMPLETE.** The defect stops here: the value crosses iterations,
promotion is reachable, and the threshold is observable.

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
- [x] Field + seeding (`list(...)` copy). → `ChainState.accumulated_key_findings`,
      12 → **13** fields; copied not aliased, because unlike its two
      one-direction siblings the loop APPENDS to this one.
- [x] The append closure: for each of `interpretation.key_findings`, append
      iff non-empty `str` and not already present — the `project_knowledge`
      rule verbatim (`:926-929`), stated in a comment referencing it. → done.
- [x] Consumer block reads the carrier; bare local removed from the unpack
      (the unpack row stays for `RestoredState` → seed only).
      → **IR-P56-1 (§22.5)**: the row is RENAMED to
      `restored_accumulated_key_findings`, not merely re-purposed. The three
      use sites read `state.accumulated_key_findings` directly rather than
      through a convenience local — a local of that name would itself be the
      duplicate-writer shape the census forbids (caught while implementing,
      after a first draft reintroduced exactly that).
- [x] Flip C0's findings-amnesia baseline to the accumulation expectation,
      citing this commit. → rendered-block counts go `[0, 0, 0]` → **`[0, 1, 1]`**;
      iteration 1 legitimately renders none (no PRIOR history — the existing
      empty guard, not amnesia), and iteration 3 now contains iterations 1
      and 2's findings and NOT its own.
- [x] Pin the rendered block bytes for a FIXED findings list (golden) —
      proving normalization moved ownership, not bytes. → exact hardcoded
      string, F-P56-1 INCLUDED and made executable (`3 prior iter(s)` for three
      findings from one restored history), plus the item's `source` /
      `source_ref` metadata.

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
- [x] The block's bytes for a fixed list are IDENTICAL pre/post (golden).
- [x] The 3-iteration accumulation test green; the amnesia baseline flipped.
      → `test_step10_p56_c3_findings_accumulation.py`, **16 tests**.
- [x] Exactly two write sites for the new field (census). → the
      `from_restored` seed (in `chain_state.py`) and the loop closure. The
      closure APPENDS in place rather than re-assigning, which is the shape §6
      specifies for a union; `model_exploration.py` therefore contains zero
      `state.accumulated_key_findings = ...` assignments, and the Step-09.5a
      reachability parametrization (which looks for `state.<field>` in any
      form) covers it.
- [x] The retired local has zero remaining reads (grep recorded). → AST
      census: zero bare `accumulated_key_findings = ...` assignments remain in
      `run_workflow`, and the renamed row is asserted present.

**The union rule is proven APPLIED, not re-implemented.** `TestTheUnionRule`
is a **differential** over seven input classes (distinct · all-duplicates ·
overlapping · quiet iteration · never-any-findings · duplicate-within-one-
iteration · empty-strings-filtered): for EVERY prefix of the drive it compares
the rendered block's bullets against `project_knowledge`'s own output on the
same digests, by exact list equality — covering membership, dedup and order in
one assertion. A hand-written expectation would have passed even if the closure
and the projection drifted together, which is the specific way an in-process
trajectory and a chain restore would silently diverge.

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
- [x] counts + wall time recorded

  | run | result |
  |---|---|
  | `test_step10_p56_c3_findings_accumulation.py` | **16 passed**, 23.39 s |
  | the four P5+P6 modules + the four standing guards (`c4_single_writer`, `c2_carriers`, `c0_oracle`, `p1_c5_launcher`) | **102 passed**, 46.11 s |
  | `tests/unit/workflows` + `tests/unit/agent/result_interpretation_agent` + C1 projection + `test_resume` + `test_cold_start_resume` | **1229 passed / 0 failed**, 107.36 s |
  | `ruff check` + `ruff format --check` | PASS |

  **Oracle delta: NONE** — no re-baseline. pyright CI-owned.

  One stale pin caught by this commit's own run and fixed: this PR's C2 census
  asserted `len(chain_state_field_names()) == 12`, which C3's thirteenth field
  invalidated. The pin was working; it now also asserts both new carrier NAMES
  are present, so the count cannot be satisfied by the wrong field. Recorded in
  the §22.6 table — a count pin must be re-checked by every commit that adds a
  carrier.

**8. Commit boundary.**
The second value's normalization. No confirmations change.

**C3 VERDICT: COMPLETE.** The S5 lifecycle now has both carried values on
`ChainState`; C4 proves the two trajectories agree.

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
- [x] Uninterrupted-vs-resumed equality: 3 iterations straight vs
      stop-after-commit / `restore_prior_state` / continue; deep-equal on
      BOTH carried values at the end.
      → `tests/unit/workflows/test_step10_p56_c4_resume_equality.py`
      (**13 tests**). Both trajectories go through the SAME production entry
      point and differ only in how they are cut up: A = one call with
      `max_iterations=3`; B = three calls with `max_iterations=1`, each
      preceded by a REAL `restore_prior_state` over the digests its
      predecessors committed. The interpreter stub persists through the
      storage the WORKFLOW handed it, so the digest path is resolved from
      production config rather than hardcoded, and the chain runner's
      manifests are written the way `test_cold_start_resume` writes them
      (`run_workflow` does not write them — `run_one_iteration` does).
- [x] Legacy fixtures: pre-activation digests restore `{}` + the existing
      findings union; zero crash, zero fabrication. → plus a `recwarn`
      assertion that no confirmations warning is emitted: an absent key is a
      compatible default, not a fault, and must not add operator noise.
- [x] Corrupted-middle-digest: the §8.2 raise surfaces through restore's
      existing wrapper exactly as `prediction_memory`'s does (end-to-end, not
      just at the projection). → asserted end-to-end precisely because a
      wrapper that swallowed it would leave the projection's own tests green.
      Its counterpart is also pinned: an UNREADABLE file is warn-and-skip, so
      one bad artifact does not make a chain unresumable.
- [x] Single-writer census extension proof: plant a second writer for each
      new field → RED; revert; tree clean. → planted into a COPY of the
      function rather than into the real file, so the detector is proven to
      bite with nothing left on the tree; the real file is then asserted
      clean for both fields.
- [x] Single-reader census: plant a second digest-key reader outside the
      interpreter → RED; revert. → same technique, reusing the AST census
      `_digest_payload_reads`: the clean source yields exactly
      `["project_vocab_link_confirmations"]`, and a planted `.get()` reader
      appears alongside it.
- [x] Disposition `test_vocab_accumulation.py` H.4 (outside CI): docstring
      updated — its hand-threading now mirrors the PRODUCTION wiring instead
      of substituting for it; it KEEPS its node-level accumulation-semantics
      ownership (recorded per the test-disposition rule; no CI change).
      → done, naming the hop that now exists and its two owning modules. The
      test still passes in pseudo mode (verified; it is `dual_mode` and CI
      runs `tests/unit/` only).

**4. Validation plan.**
* Integration/pseudo: the two trajectories; the corrupted-restore negative.
* Backward-compat: the legacy fixtures.
* Gate: **NONE.**

**5. Acceptance criteria.**
- [x] Deep-equality on both values, both trajectories.
- [x] Every plant individually RED, reverted, recorded.
- [x] A pre-activation digest set restores with no warning beyond the
      declared policy.

**The equality is proven NON-VACUOUS**, which matters more than the equality
itself: two trajectories that each forgot everything would be trivially equal —
and that is exactly the state this PR started from. A dedicated test asserts
the resumed trajectory's confirmations really grew across the process boundary
(`{}` → `{KEY: [run_a]}` → `{KEY: [run_a, run_b]}`) and its findings really
accumulated, plus a harness-level check that iteration 3 restored state written
to DISK by iterations 1 and 2 rather than carried in memory.

**S5 IS DETERMINISTICALLY CLOSED AT THIS HEAD.** Both carried values complete
the full lifecycle — producer → digest → projection → `RestoredState` →
`ChainState` → consumer — reachability-proven with four severing mutations and
resume-equal. Per §14 this claim is NOT deferred to, or diluted by, Gate 2.

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
- [x] counts + wall time recorded

  | run | result |
  |---|---|
  | `test_step10_p56_c4_resume_equality.py` | **13 passed**, 14.73 s |
  | `pytest tests/unit/workflows tests/unit/core -q` (the §13 C4 command) | **3066 passed / 0 failed**, 344.18 s |
  | `test_vocab_accumulation.py::test_scientific_accuracy_and_vocab_links_accumulate` (H.4, pseudo mode, outside CI) | **1 passed**, 2.49 s |
  | `ruff check` + `ruff format --check` over `core/ workflows/ nodes/ tests/` | PASS |

  pyright CI-owned. Run uncontended (no second pytest process), per the C1
  flake lesson.

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

**W6 is added to this commit** by the operator's approval of IR-P56-2. The six
now read as ONE family — *legacy-fallback removal from composed mode*:

```text
W1  chain composition argv
W2  shipped TIDMAD composition
W3  child in-tree data-path resolution
W4  no implicit legacy TIDMAD reference science in composed mode
W5  composed scoring uses the bound metric
W6  composed Health classification uses the bound run Health requirements
```

- [x] W1: parser entry + default + `build_app_args` forwarding (both lilab
      and SDSC paths); `--task_composition` documented in the usage block.
      → three edits to `_chain_common.sh` (default `TASK_COMPOSITION=""` ·
      case arm · guarded `build_app_args` forward) plus the `run_chain.sh`
      usage block, a worked composed example, and the launch banner.
      **The SDSC leg needed NO edit** — `submit_one_iteration.slurm` owns four
      flags and forwards every other token verbatim through its `*)` arm; that
      is asserted rather than assumed. 48 existing launch-surface/chain-parity
      tests stay green.
- [x] W2: the shipped manifest, mirroring
      `tests/fixtures/step10_p1/tidmad/composition.yaml` against the shipped
      TIDMAD assets; a deterministic test asserts composed-TIDMAD ≡
      legacy-TIDMAD on the COMPOSITION INVARIANTS only (binding identity,
      fingerprint stability, zero secondary bytes, metric/scorer semantics,
      Health declaration, lifecycle) — per C-P56-1 the legacy-only implicit
      reference table is NOT in the parity set.
      → `configs/task_composition/tidmad.yaml`, beside `configs/task_health/`
      and `configs/task_interpretation/`. **Its semantic fingerprint is
      IDENTICAL to the P1 fixture's** — the strongest available equivalence,
      since the fingerprint is what the run-invariants lock pins, so the
      shipped manifest is provably the fixture relocated rather than a
      re-specification.
- [x] W3: the two missing built-in imports per child, in the declared
      "built-ins' bootstrap" comment shape; a test resolves all three
      transported ids in a child-shaped process.
      → added to all three children. Verified at RUNTIME for
      `train_engine_sandbox` and `inference_single` (importing either
      registers `tidmad` + `oxford_iiit_pet` + `davis_future_prediction`).
      **`denoising_score_single` is source-censused instead, and the reason is
      recorded rather than glossed**: it calls `parser.parse_args()` at MODULE
      level (`:116`), so it is a script, not an importable module — a plain
      import hangs. Its bootstrap is additionally exercised by the Gate's real
      scoring subprocess. An unknown id still fails closed (asserted): W3
      widened the built-ins, it did not add a fallback.
- [x] W4 per the frozen C-P56-1 rule: the guard keys on **composition
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
      → the predicate is **`active_task_data_path() is None`**, chosen
      deliberately: P1 documents it as the "is this run explicitly bound?"
      accessor WITHOUT the compatibility fallback, so it answers composition
      presence without ever naming or inspecting a task. Tests (2)(3)(4) are
      ONE parametrized assertion because there IS no per-task branch — that
      is the property. Test (5) walks the guard's AST and fails if its test
      expression mentions `TIDMAD_METRIC_ID`, `tidmad`, `denoising_score` or
      `s_max`. The composed branch also SKIPS the score-table build
      explicitly (`reference_scores is not None`) rather than letting the
      existing `try/except` swallow it — otherwise a composed run would log a
      build failure every round for a state that is by design.
- [x] W5: the mutation-backed pin (§10.5).
      → two pins. An AST assertion that the acquisition is
      `resolve_bound_run_metric() or derive_tidmad_metric(...)` with the BOUND
      value as the FIRST operand (reversing them would silently score every
      composed run under TIDMAD's metric), plus a rebinding mutation showing
      the resolved identity move `None` → `tidmad_denoising_score`/`higher` →
      `mse`/`lower`. The standing note that the subprocess re-derivation is
      legacy-path-only is asserted, not just written.
- [x] **W6 (added by IR-P56-2, operator-approved)**: the run's Health
      declaration is resolved ONCE at the composition edge
      (`resolve_run_scientific_gate_ids`) and consumed downstream as a
      RESOLVED VALUE through the pre-existing keyword-only seam
      (`classify_candidate_health(*, required_gate_ids=...)`).
      → 19 tests. Legacy parity (`LEGACY_OMITTED` delegates to the untouched
      resolver; `required_gate_ids=None` is the unchanged default); each
      composition resolves its OWN family (TIDMAD 3 gates · Pets 2 · DAVIS 1,
      hand-written expectations); contrast tasks share NO gate with TIDMAD's
      set; **the anti-vacuity test the operator required** — the same Pets
      record judged against TIDMAD's requirements returns UNKNOWN rather than
      VALID, so a classifier that merely accepted the value without consuming
      it would be RED; and **five sequential-run orderings** (pets→davis,
      davis→pets, pets→tidmad, tidmad→pets, davis→tidmad) proving no
      cross-run contamination, with its own anti-vacuity twin showing the
      process-global invariant is still enforced when no run boundary is
      crossed.
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

**Validation record.**

| run | result |
|---|---|
| `test_step10_p56_c5_wiring_closures.py` (W1–W5) | **22 passed** |
| `test_step10_p56_c5_w6_composed_health.py` (W6) | **19 passed** |
| launch-surface + chain-consistency + SDSC forwarding guards | **48 passed** |
| `bash -n` on both chain scripts | PASS |
| broad: `workflows` + `tune_ml_hyperparam_agent` + `result_interpretation_agent` + `health_checks` + `sdsc_submission_scripts` + `scripts` + `guardrails` | **4453 passed**, 2 failed → both were THIS PR's own guards firing correctly (below) |

**Both C5 failures were guards working, and neither was relaxed.**

1. `test_the_workflow_delta_stayed_sibling_shaped` — the §12.1 tripwire I
   wrote at C2. W6 added one `IfExp` (135 → 136), so the pin moved. Re-measured
   and updated WITH the decomposition, not loosened to a range: the addition is
   `task_composition.task_health_binding if task_composition is not None else
   LEGACY_OMITTED`, the same composed/un-composed conditional shape every other
   fork in this function already uses.
2. `test_pr3_l2p_preflight::test_preflight_all_invariants` —
   `no_production_file_modified`, naming exactly the ten uncommitted C5
   production files. This is the CLAUDE.md-documented guard: *"Run the full
   suite on a work-in-progress tree and it reports a failure naming the files
   you are editing. That is the guard working."* The prescribed fix is to
   commit the semantic checkpoint and re-run — **never** to relax the guard.

**C5 VERDICT: COMPLETE.** Six closures; a composed run is launchable from the
operator surface for the first time, and carries no implicit legacy TIDMAD
science — not reference tables (W4) and not Health requirements (W6).

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
- [x] The TIDMAD composed drive: composed ≡ legacy on the loop's observable
      lifecycle COMPOSITION INVARIANTS (statuses, per-iteration artifacts,
      zero secondary bytes); the implicit legacy reference block ABSENT with
      the named absence, per C-P56-1.
- [x] The Pets drive: loop initializes and traverses interpret → propose →
      implement → validate → plan under `accuracy`/higher; exactly
      `macro_f1` observational in evidence; implicit legacy reference block
      ABSENT (C-P56-1); Health binding state C reaches the tuner context (no
      `LEGACY_OMITTED`); real verdict evidence stays runner-owned (§10.4) —
      asserted as BINDING, not verdicts.
- [x] The DAVIS drive, ≥ 2 iterations: `mse`/lower live end-to-end;
      `psnr`/higher + `mae`/lower observational; confirmations + findings
      carried across the boundary; the carried values contain nothing
      direction-shaped (structural assertion: run-name lists and strings
      only).
      → plus an explicit **inversion probe**: the drive is shown to FAIL when
      the direction expectation is flipped, so the falsifier is demonstrably
      discriminating rather than merely green.
- [x] The same-path proof: all three drives call `run_workflow` itself with
      only the composition differing — asserted structurally (one driver
      helper, parametrized by manifest; no per-task branches in the driver).
      → asserted over the AST of `drive` itself: no task NAME constant may
      appear in it, and `run_workflow` (never `run_bounded_pseudo_iteration`)
      must be the entry call. The second check is AST-based because a
      substring search matched this module's own prose about what it does not
      use — a self-referential green caught while implementing.
- [x] The typed-boundary proof: the drives construct proposer input ONLY via
      the protocol (the raw-read census scope extended over any new test
      helper). → `ProposalInput.interpretation_evidence` present and the
      P3-removed `interpretation` attribute absent, for all three tasks; plus
      a per-task assertion that no declared secondary's id appears anywhere in
      the proposer's evidence (Q-P3-3 held on the two tasks that HAVE
      secondaries, not just asserted in the abstract).
- [x] Census scope extension: the task-identity dispatch census and the
      ordering-operand invariant re-run with this PR's touched files in
      scope; plants re-verified RED in at least one newly-touched file.
      → the census covers `model_exploration.py`, `chain_state.py`,
      `resume.py` and `candidate_eligibility.py`; a planted
      `if task_id == 'oxford_iiit_pet'` in a parsed COPY is detected (nothing
      written to disk).
- [x] Fixture honesty: the Pets/DAVIS fixture-comment "P6 owns driving Pets
      through the exploration loop" updated to name CAP-SCOPE and this
      child's actual closure depth.
      → both headers now separate the two claims explicitly: ORCHESTRATION
      closure DONE; real task-correct TRAINING **not delivered**, requiring
      CAP-SCOPE, with Step 12 barred from claiming contrast L4 while it is
      open, and real execution evidence pointed at the retained runners.

**A seed-consistency finding, recorded because it shaped the drives.** The C0
composed drives seeded a TIDMAD-stamped tuning output; under an `accuracy` or
`mse` composition, P2a's reconciliation correctly REFUSES it. The C6 driver
therefore writes a seed stamped with the composition's OWN metric spec. That is
not a workaround — feeding a mismatched seed would have tested P2a's refusal
rather than the orchestration.

**4. Validation plan.**
* Integration/pseudo: the three drives (the pseudo-full-loop tier — no API
  key, no GPU).
* Negative: a composition-bound drive with a deliberately wrong-direction
  assertion fixture proves the drive WOULD catch an inversion (anti-vacuity
  for the DAVIS falsifier).
* Backward-compat: the un-composed pseudo loop test still green unchanged.
* Gate: **NONE here.**

**5. Acceptance criteria.**
- [x] All three drives green through ONE parametrized path; the DAVIS drive
      crosses ≥ 2 iterations with both carried values live and equal to the
      single-process expectation.
- [x] Class (b) task-identity dispatch still 0 with the extended scope;
      plants RED.
- [x] C0's loop baselines flipped with their deltas attributed (W4 flip; any
      baseline failure point now passing, or explicitly re-recorded).

**Anti-vacuity for the whole matrix**: every drive asserts the run-invariants
lock carries the composition's semantic fingerprint, so a drive that silently
fell back to un-composed behaviour cannot pass.

**C6 VERDICT: COMPLETE — ORCHESTRATION closure only.** Three materially
different tasks traverse the ONE `run_workflow` under their own declared
direction, secondaries, Health family and typed proposer boundary, with the
carried lifecycle live. **This is NOT contrast-track L4 and is not evidence of
task-correct contrast training**, which remains CAP-SCOPE (§10.2).

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
- [x] counts + wall time recorded

  | run | result |
  |---|---|
  | `test_step10_p56_c6_three_task_closure.py` | **32 passed**, 15.30 s |
  | + `test_step10_p1_c1_composition.py` (fixture-header change) | **82 passed**, 18.40 s |
  | `tests/unit/workflows` + `result_interpretation_agent` + `execute_tools/health_checks` | **1965 passed / 0 failed**, 130.81 s |
  | `ruff check` + `ruff format --check` | PASS |

  The drives are the pseudo-full-loop tier: no API key, no GPU, no subprocess.
  pyright CI-owned.

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
- [x] Line-by-line claims audit of both runners against §10.4's table;
      corrections recorded here if the table missed a claim.
      → §10.4's table verified against both sources; no claim was missed. The
      disposition it licenses is applied below.
- [x] **The §10.6 freshness audit, per retained track**: record the evidence
      provenance (SHA · artifact · result), compute the semantic dependency
      diff from the evidence SHA to the implementation candidate over the
      runner's real-execution surface, and record the verdict — evidence
      REMAINS AUTHORITATIVE (no rerun) or the affected bounded runner is
      rerun BEFORE the retained-evidence claim is made. No rerun for
      reassurance; no timeless reuse by assumption.
      → **RERUN TRIGGERED for BOTH tracks, and both now reproduce BIT-EQUAL.**
      Full record in §22.9.
- [x] Docstring relabel: "L3 real-execution evidence harness; orchestration
      claims owned by the generic-loop closure tests (named); full
      retirement blocked on CAP-SCOPE (named)". → both runners.
- [x] `STATUS.md` rows updated in both packs. → each gains a "Runner role and
      L3 evidence freshness" section carrying the full audit table.
- [x] The parent-§22.2 required order recorded as satisfied-with-deferral in
      this ledger, with each retained claim's distinct failure class stated.
      → §22.9's disposition table.

**4. Validation plan.**
* Unit: the existing runner-adjacent tests still green (no behaviour change).
* Real execution: ONLY a §10.6-triggered bounded runner rerun, if the
  dependency diff demands one (~25 s per runner on the 5090; not a Gate — no
  LLM involved). The verdict either way is recorded with the diff evidence.
* Gate: **NONE.**

**5. Acceptance criteria.**
- [x] Every §10.4 row verified or corrected against source, recorded.
- [x] The §10.6 freshness verdict recorded per track, with the dependency
      diff as evidence (and the bounded rerun's result, if one was
      triggered). → §22.9.
- [x] No repository text still describes the runners as the way a contrast
      task executes its lifecycle (grep recorded). → the surviving hits are
      historical SOURCE-AUDIT citations in design docs (line references such
      as "`run_pets_gate2.py:144`" recording where a binding lived at the time
      of that audit). Those are accurate history, not role claims, and are
      deliberately not rewritten.

**C7 VERDICT: COMPLETE.** Q-10-5 = B is discharged: every claim enumerated,
orchestration claims transferred to owners that exist, retained claims named
with their distinct failure class, both runners relabelled, and the retained
evidence proven CURRENT by rerun rather than assumed.

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
instantiated at **3 iterations, 1 round** (AMENDED 2026-08-21, operator
decision — see §22.19/F-P56-4; originally 2, which cold start makes
unsatisfiable). The ≥ 3-iteration PROMOTION property remains
deterministic-owned (§14) and this Gate makes no promotion claim — the
third iteration exists solely so Layer A's findings witness has one real
restore to cross.

**Gate scope (the standard's required fields; CORRECTED 2026-08-21 — see
§22.18).** The governing authority is
`docs/gates/gate_testing_standard.md` → "Gate scope ownership — DO NOT
BLINDLY EXPAND"; this section only instantiates it.

| field | value |
|---|---|
| **FAILURE CLASS UNDER TEST** | composed-run lifecycle closure: state produced in iteration 1 is persisted, survives a REAL process boundary and chain restore, and is CONSUMED by a LATER iteration's proposer — under a run-scoped task composition executing for the first time. (Under cold start the consuming iteration is the THIRD; see F-P56-4 §22.19 for why it cannot be the second.) |
| **REQUIRED REAL COMPONENTS** | real LLM · real candidate generation + implementation · real training · real validation/inference/scoring · real persistence · real process boundary · real restore · real iteration-2 consumption |
| **NON-REQUIRED SCIENTIFIC QUALITY** | **HealthGate PASS · absence of output collapse · output diversity · score magnitude or sign · convergence · incumbent improvement · any benchmark threshold.** None is owned by P5+P6, and a poor or collapsed candidate is acceptable evidence |
| **MAXIMUM TEMPORAL DEPTH** | **3 iterations × 1 round** (AMENDED 2026-08-21 — operator decision; was 2, which F-P56-4 proved unsatisfiable) |
| **EXTRA DEPTH JUSTIFICATION** | the standard's depth table gives "cross-iteration behaviour or resume → ≥ 2 iterations" as a FLOOR. Layer A needs 3 under COLD START, and the reason is structural, not preference: the loop appends an iteration's findings only AFTER that iteration's proposer has read (`model_exploration.py:2210 → :2335 → :2425 → :2888`), and a cold-start iteration 1 has no prior output for its interpreter to read. So findings ABOUT iteration 1's real experiment are produced by iteration 2 and can only reach a proposer at iteration 3. **This run still makes NO promotion claim** — the ≥ 3-iteration promotion property stays deterministic-owned (§14), and Layer B is unchanged (`{}` ⇒ record the equality, claim no reachability) |
| **ISOLATION** | blocking HealthGate behaviour is disabled for the Gate workload via the EXISTING production switch `--no-health_gate_enabled` (`_chain_common.sh:81`, DS6c), with `--result_authority diagnostic`. **No Health semantics, thresholds, config or tests are changed**; HealthGate keeps its own owners |

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

  **"Usable" CORRECTED (2026-08-21, §22.18).** Usable means *structurally
  valid, genuinely produced from the completed real experiment, and
  substantive enough to distinguish the lifecycle boundary*. It does
  **NOT** mean a positive scientific result, good model performance, a
  HealthGate PASS, or successful optimisation. A NEGATIVE finding is fully
  legitimate evidence — "the candidate trained and scored but produced
  low-diversity outputs", "the candidate underperformed", "the candidate
  collapsed" all qualify. The lifecycle Gate needs a REAL finding that can
  be persisted and restored, not a scientifically successful candidate.
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

---

## 22. Implementation ledger (LIVE — opened 2026-08-21)

Implementation session record. §13's per-commit checklists are the primary
status surface; this section carries the preflight, the rulings (IR-P56-N),
the guard-disposition table, the structure tripwire measurements and the
Gate/CI provenance.

### 22.1 Implementation identity

| field | value |
|---|---|
| implementation branch | `step10-p5-6-lifecycle-three-task-closure-impl` |
| implementation base | `3aa5c1de` (== `origin/master` at session start; freeze SHA) |
| freeze authority | `3aa5c1de` — REVISION 2 FROZEN, operator approved |
| source anchor | `ec6257fb` — **re-verified valid**: `git diff --name-only ec6257fb 3aa5c1de` returns ONLY `.md`/`docs/` paths, so the production tree at the implementation base is **byte-identical** to the tree every §2 measurement was taken on |
| merged prerequisites | P1 `bcb17e45` · P2a `e094fa26` · P2b `5a2ecfd1` · P3 `254cbaa1` · P4 `79833db8` — all present in `origin/master` history |
| current checkpoint | C0 `d141d967` · C1 `e774b1c6` · C2 `11b1e33b` · C3 `bfb762b2` · C4 `6e73aa26` · C5 `68b604c9` · C6 `c9031369` · C7 COMPLETE; C8 (Gate 2) next |

### 22.2 Source preflight (re-measured at the implementation base)

Every §2/§12 anchor re-measured from source before any edit. **Zero drift** —
expected, since the production tree is byte-identical to the source anchor.

| measurement | §2/§12 value | re-measured | verdict |
|---|---|---|---|
| `workflows/model_exploration.py` LOC | 3,167 | 3,167 | ✅ |
| `run_workflow` span / LOC | `:1457-2945` / 1,489 | `:1457-2945` / 1,489 | ✅ |
| `run_workflow` branch-ish AST nodes | 130 (If 57 · IfExp 28 · BoolOp 23 · For 12 · With 8 · Try/Except 2) | **130** — If 57 · IfExp 28 · BoolOp 23 · For 12 · With 8 · Try 1 · ExceptHandler 1 | ✅ exact |
| `core/resume.py` LOC | 1,630 | 1,630 | ✅ |
| `core/chain_state.py` LOC | 188 | 188 | ✅ |
| `result_interpretation_agent.py` LOC | 1,331 | 1,331 | ✅ |
| `ChainState` field count | 11 | 11 | ✅ |
| `RestoredState` field count | 15 | 15 | ✅ |
| `vocab_link_confirmations` in `workflows/` | 0 | **0** | ✅ severed |
| `vocab_link_confirmations` in `core/` | 0 | **0** | ✅ severed |
| producer body | `interpretation_helpers.py:587-679` | `:587-679` — keyed union, per-key run-name dedup, `min_runs` default 3, deep-copy of caller's dict, whole-map promotion re-scan | ✅ as designed |
| interpreter branches | normal `:1018` · degraded `:1125` · cold start `:210-237` (field ABSENT) | identical; the cold-start `InterpretationOutput(...)` at `:211-237` carries **no** `vocab_link_confirmations` kwarg | ✅ DD-2 confirmed |
| sibling projections | `:886` · `:951` · `:1004` · `:1052`; one digest read `:1478` | identical; `project_prediction_memory` `:1039-1047` is the raise precedent §8.2 names | ✅ |
| findings bare local | `model_exploration.py:1942`, consumer `:2278-2292` | identical; `:2275` still names the dead `core.resume.load_latest_knowledge` | ✅ |
| loop-closure pattern | `:2791-2805` | identical | ✅ |
| `InterpretationInput(...)` | `:2097-2151` | identical; no confirmations kwarg | ✅ |

**Structure tripwire baseline recorded (§12.1)**: `run_workflow` **1,489 LOC ·
130 branch-ish nodes**. The counting set is exactly §12's (If · IfExp · BoolOp ·
For · While · With · Try · ExceptHandler); a naive count that also includes
`Assert` reports 131 — the one `Assert` in `run_workflow` is excluded so PRE and
POST are measured on the same set.

### 22.3 C0 residual-debt check — roadmap "resume/dashboard direction literals"

Required by C0's checklist. Result: **the debt is already CLOSED at this head**;
no hit is a live direction literal, and nothing is owed by this child.

* `core/resume.py` — **0** direction-word literals of any form.
* `dashboard/` — **0** live literals. The single grep hit,
  `dashboard/data_sources/base.py:124`, is a P2a-C3 docstring *recording* the
  historical correction ("this docstring used to say 'descending (higher is
  better)', which was true only of TIDMAD"); the surrounding method reads the
  direction from each record's persisted metric identity.

Owner: **none outstanding** — the roadmap line was discharged by P2a C3. No
line here is touched by this child.

### 22.4 Findings

#### F-P56-2 — a composed CONTRAST run cannot start: generic core binds the LEGACY task-health family at Step 0 (found in C0)

**Status: OPEN — disposition owed by C5/C6. Not CAP-SCOPE.**

C0's composed `run_workflow` drives found a **blocking production defect** that
§2.5's audit did not list among W1–W5, because no test had ever driven a
contrast composition through `run_workflow` itself (§2.5 measures exactly that:
"no real composed chain run has ever executed").

**The measured ordering** (traced, not inferred):

```text
run_workflow:1729   "Step 0: Loading existing tuning outputs..."
  -> nodes/result_interpretation_agent/evidence.py:471
       tuning_output_to_model_run_summary
  -> candidate_eligibility.py:194  classify_candidate_health
  -> candidate_eligibility.py:145  required_blocking_gate_ids
  -> candidate_eligibility.py:121  resolve_scientific_gate_ids(config_path=None)
  -> config.py:400                 load_health_gates_config(None)
  -> config.py:567                 load_composed_health_config(None)   # no task binding
  -> config.py:528                 _load_task_binding(LEGACY_OMITTED)
  ==> binds configs/task_health/tidmad.yaml, plugins = ()   [PROCESS-GLOBAL]

run_workflow:1786   build_run_invariants(..., task_health_binding=<composition's>)
  -> config.py:611  materialize_effective_config
  ==> requests examples/oxford_iiit_pet/declared/task_health.yaml + its plugins
  ==> HealthPluginRunScopeError — REFUSED
```

**Why it was invisible until now.** The run-scope guard is *correct* (Step 08b:
one process evaluates one run's checks). The defect is that generic core
resolves the **legacy TIDMAD** task-health binding at Step 0, before the
composition is consulted. That is harmless for an un-composed run (both
resolutions are TIDMAD's, plugins `()` both times ⇒ the guard's idempotent
branch) and for composed **TIDMAD** (same file, same canonical identity) — so
**Gate 2's composed-TIDMAD run is NOT affected**. It bites only when a
composition names a different Health family, i.e. exactly Pets and DAVIS.

**Classification.** This is the **same family as W4** — generic core implicitly
resolving legacy TIDMAD science in a composed run — and therefore squarely
inside **C-P56-1**'s frozen rule ("ANY COMPOSED RUN: do NOT implicitly load the
legacy TIDMAD … science"). It is *wiring*, not capability: nothing about
task-owned scope construction or contrast training is involved, so it is **not
CAP-SCOPE** and must not be deferred there. It blocks C6's frozen deliverable
(three compositions through ONE `run_workflow`), so C6 cannot be delivered
without a disposition.

**Recorded in C0, fixed later** — C0 is baselines only (zero production edits).
The baseline
(`tests/unit/workflows/test_step10_p56_c0_three_task_baseline.py::
TestComposedLoopDriveBaseline::test_a_composed_contrast_run_cannot_start_today`)
asserts the exact failure with its provenance and is **flipped by C5/C6**.

**Candidate dispositions, to be decided at C5 with full source evidence** (none
chosen yet; the frozen non-goals forbid reopening P4's Health declarations and
forbid changing phase ordering casually):
1. make the candidate-eligibility path consult the bound composition rather
   than defaulting to `LEGACY_OMITTED`;
2. materialize the run-invariants/effective config **before** Step 0, so every
   later reader takes the documented "read the pinned effective file" path
   (CLAUDE.md's stated Health-config design) — this is a phase-ordering change
   and needs explicit justification;
3. carry the composition's `task_health_binding` to `load_health_gates_config`
   at this call site only.

Each is bounded; the choice is an implementation ruling, not a frozen-contract
change, so it is resolved autonomously at C5 and recorded as IR-P56-N — unless
the audit shows every contract-preserving option requires changing a frozen
contract, which would be a material deviation.

### 22.5 Implementation rulings (IR-P56-N)

#### IR-P56-1 — C3 RENAMES the findings unpack row rather than re-purposing it

**Question.** §13 C3 says "bare local removed from the unpack (the unpack row
stays for `RestoredState` → seed only)". Does the row keep the name
`accumulated_key_findings`?

**Source evidence.** `tests/unit/workflows/test_step09_5a_c4_single_writer.py`
`::_bare_local_writes` flags any bare assignment whose target name appears in
`chain_state_field_names()`. The moment C3 declares
`ChainState.accumulated_key_findings`, the pre-existing unpack row at
`model_exploration.py:1942` — `accumulated_key_findings = restored_state...` —
becomes exactly the duplicate-writer shape Step 09.5a's Amendment C exists to
prevent, and the guard turns RED.

**Options considered.** (a) keep the name and relax the census — rejected, it
would disable the guard for every future carried value; (b) delete the row and
read `restored_state` inline at the `from_restored` call — rejected, it breaks
the P1 C5 unpack-once contract and its exact-set guard; (c) **rename to
`restored_accumulated_key_findings`**, matching all eight siblings
(`restored_runtime_vocab`, `restored_prediction_memory`, …).

**Ruling: (c).** It is the sibling convention, it satisfies both guards without
weakening either, and it is a pure rename with no behavioural content.

**Second-order consequence, found while implementing.** A first draft
reintroduced the collision inside the consumer block as a convenience local
(`accumulated_key_findings = state.accumulated_key_findings`). That is the same
forbidden shape one scope down. The three use sites read the carrier directly
instead.

**Validation.** `test_step09_5a_c4_single_writer.py` and
`test_step10_p1_c5_launcher.py` green; a dedicated AST census
(`test_the_retired_bare_local_has_no_remaining_reads`) asserts zero bare
assignments of the old name remain and that the renamed row is present.

#### IR-P56-2 — F-P56-2 is fixed HERE, as W6, through the existing explicit-parameter seam

**Question.** F-P56-2 (§22.4) blocks C6's frozen three-task deliverable. Is its
fix this child's, or upstream debt owned by the Health family (parent §20.6)?

**Source evidence (audited, not assumed).**

* The binding happens as a SIDE EFFECT of merely READING gate roles:
  `candidate_eligibility.resolve_scientific_gate_ids(config_path=None)` →
  `load_health_gates_config(None)` → `load_composed_health_config(None)` →
  `_load_task_binding(LEGACY_OMITTED)` → resolves
  `configs/task_health/tidmad.yaml` and binds its plugin set process-globally.
* **Re-ordering alone does NOT fix it** — tested by reasoning through the
  guard: if materialization ran first and bound the task's family, the later
  zero-arg load would request TIDMAD's `()` against a recorded `(pets_views,)`
  and be refused just the same. The failure would move, not disappear.
* `load_health_gates_config`'s `_CACHED_GATES` is only populated by the
  zero-arg path, so materialization never primes it.
* P1 deliberately did **not** bind Health ambiently
  (`task_composition.py:1052-1056`): *"Binding a ContextVar for a value that
  already has an explicit path would create a second way for it to arrive,
  which is the ambiguity this whole milestone removes."*
* CLAUDE.md states the intended design: the run materializes the effective
  config and *"every path-based loader reads that file"*.
* The explicit seam ALREADY EXISTS and is already keyword-only and defaulted:
  `classify_candidate_health(record, *, required_gate_ids=None)` and
  `resolve_scientific_gate_ids(config_path)`.

**Options considered.**

| # | option | verdict |
|---|---|---|
| A | bind Health ambiently so the zero-arg loader sees the composition | **REJECTED** — directly contradicts P1's frozen non-ambient decision and re-creates the second arrival path that milestone removed |
| B | re-order `run_workflow` so materialization precedes Step 0 | **REJECTED** — does not fix it (above); would also be a phase-ordering change |
| C | thread the run's effective config through the EXISTING keyword-only seam to the eligibility call | **CHOSEN** |
| D | record as upstream Health-family debt and narrow C6 | **REJECTED** — C6's frozen deliverable is three compositions through ONE `run_workflow`; delivering it only for runs without seeds would overclaim, and the design's own C6 rule says a gap the drives expose is *"fixed under an existing W-item's ownership or recorded against CAP-SCOPE"* — this is neither task-scope construction nor training, so it is not CAP-SCOPE |

**Ruling: C — fixed here as W6, inside W4's family.** It is the SAME rule
C-P56-1 froze, applied to Health rather than reference scores: *ANY composed
run must not implicitly load legacy TIDMAD science.* It is bounded wiring, not
a semantic change: additive, keyword-only, defaulted, no ambient binding, no
task-identity branch, and it moves no Health semantics. Per the Implementation
Working Rules' material-deviation test, no frozen contract changes, so this is
resolved autonomously rather than escalated.

**Operator visibility (stated, not buried).** This is the one place where this
child touches a family it does not own. It is recorded here, in W6, and in the
PR body, so the review can overturn it cheaply — the alternative (D) is a
one-line scope narrowing of C6 plus a debt entry, and nothing else in the PR
depends on the choice.

**Validation.** C0's baseline
(`test_a_composed_contrast_run_cannot_start_today`) is FLIPPED by W6; the
composed Pets and DAVIS drives in C6 are what prove it end-to-end.

### 22.6 Guard-disposition table (opened in C0)

Every existing guard this PR is KNOWN to move, and the commit that moves it.
Re-checked per commit; an unflipped baseline at C8 is a ledger error.

| guard | what happens | flipped/handled by |
|---|---|---|
| `test_step10_p56_c0_broken_lifecycle.py::TestResumeHalfIsMissing` (this PR's own) | asserts the projection + `RestoredState` field are ABSENT | **C1 inverts** |
| `…::TestWorkflowHalfIsMissing` | asserts `ChainState`/workflow/`InterpretationInput` do not carry it; pins RestoredState 15 / ChainState 11 | **C2 inverts** |
| `…::TestMalformedPayloadsAreInertToday` | five garbage shapes raise nothing | **C1** (present-but-malformed ⇒ raise) |
| `test_step10_p56_c0_producer_baseline.py::TestColdStartDropsTheCarriedMapping` | cold start returns `{}` | **C2** (DD-2 carry-through) |
| `test_step10_p56_c0_multi_iteration_baseline.py::TestFindingsNeverAccumulate…` | no findings block ever renders | **C3** |
| `…::TestConfirmationsNeverReachTheNextIteration` | every iteration receives `{}` | **C2** |
| `test_step10_p56_c0_three_task_baseline.py::…test_a_composed_contrast_run_cannot_start_today` | F-P56-2 | **C5/C6** |
| `…::TestTidmadReferenceScoresLeakIntoComposedRuns` (contrast half) | TIDMAD refs load under a contrast composition | **C5** (W4 / C-P56-1) |
| `…::test_an_uncomposed_run_loads_them_too_and_must_keep_doing_so` | legacy path loads 20 refs | **must STAY green** (C-P56-1's other half) |
| `test_step09_5a_c4_single_writer.py` reachability parametrization | auto-gains one case per new `ChainState` field; RED until `run_workflow` references `state.<field>` | **C2** (+1), **C3** (+1) — this is why C1 adds NO carrier |
| `test_step09_5a_c4_single_writer.py::test_no_carried_value_has_a_surviving_bare_local_writer` | `accumulated_key_findings` is a bare local at `model_exploration.py:1942` **and** would become a `ChainState` field ⇒ instant duplicate-writer RED | **C3** — see IR note below |
| `test_step09_5a_c2_carriers.py:68` (`len(...) >= 11`) | floor only | additive, stays green |
| `test_step10_p1_c5_launcher.py::…unpacks_every_one_of_the_…_fields` | **EXACT** set of nine `restored_state.*` reads | **C2 → ten.** Kept exact, not relaxed to a floor: the defect it owns is a typo reading the WRONG field name, which only an exact set catches. *(Missing from the first draft of this table — added when the guard fired.)* |
| this PR's own `TestWorkflowHalfIsMissing::test_chain_state_now_carries_the_confirmations_map` | pins the ChainState field COUNT | **C2 → 12, C3 → 13.** A count pin must be re-checked by every commit that adds a carrier; C3's run is what caught it. Now also asserts both new carrier names are present, so the count cannot be satisfied by the wrong field. |
| `test_step09_5a_c2_carriers.py` bindings/launch deny-lists | derive from `chain_state_field_names()`; new fields extend them automatically | stays green (correct: a binding must never carry them) |
| `test_step09_5a_c0_oracle.py` envelope golden | 1-iteration snapshot; both new values are `{}`/`[]` there, so **no delta is expected** — but it is run per commit and any delta is DECLARED in its docstring, never re-baselined silently (the P3 C3 lesson) | run at C1/C2/C3/C5/C6 |
| `test_step10_p3_proposer_evidence_census.py` (raw-read census `{node: 0, helpers: 0}`) | no `InterpretationOutput` field added, evidence not widened | stays green |
| `test_step10_p3_c1_projection.py` carried∪refused partition | unchanged — `NOT_CARRIED` keeps refusing confirmations | stays green |
| `test_step10_p1_c4_extension_proof.py` task-identity dispatch census (class (b) = 0) | scope extended over this PR's touched files | **C6** re-runs + plants |
| `tests/integration/workflows/test_vocab_accumulation.py` H.4 | hand-threads the carry; **outside CI** (CI runs `tests/unit/` only) | **C4** dispositions the docstring; keeps node-level ownership |

**Noted for C3 (write it into the commit, not discovered during it)**: adding
`ChainState.accumulated_key_findings` makes the EXISTING bare local at
`model_exploration.py:1942` an immediate duplicate-writer offender, because
`_bare_local_writes` flags any bare assignment whose name `ChainState` also
declares. The unpack row must therefore be **renamed** to the sibling
convention (`restored_accumulated_key_findings`, matching
`restored_runtime_vocab` / `restored_prediction_memory` / …) feeding
`from_restored`, not merely kept. §13 C3's "bare local removed from the unpack"
is satisfied by that rename.

### 22.9 C7 — runner claims and the §10.6 evidence-freshness audit

**Claim disposition (Q-10-5 = B).** §10.4's table verified line-by-line against
both runner sources; nothing was missed.

| claim | disposition |
|---|---|
| binding resolves · direction correct · secondaries observational · Health binds state C | **TRANSFERRED** → C6's generic-loop drives + the standing censuses |
| real JPEG / frame decode → tensors | **RETAINED** — no generic owner until CAP-SCOPE |
| production training engine on real data (real R2/R3, `comparability` stamped) | RETAINED |
| real inference + real deliverable codec round-trip on real bytes | RETAINED |
| real metric handle on a real deliverable | RETAINED |
| pack Health family on a FRESH real deliverable | RETAINED |
| DAVIS last-frame-copy baseline comparison | RETAINED |
| "the way a contrast task runs" | **RETIRED as a label** — both docstrings and both `STATUS.md`s now say *L3 real-execution evidence harness*, name C6 as the orchestration owner, and name CAP-SCOPE as the retirement blocker |

**The freshness audit — the rerun was REQUIRED, not optional.**

The dependency diff `ede11fd5..HEAD` over the runners' real-execution surface
returned **20 changed files**, including the very Health checks each pack
exercises — `categorical_distinct_symbols` and `categorical_dominant_fraction`
(Pets), `sample_dispersion_floor` (DAVIS), all touched by P4's declaration
migration — plus `evaluation_metric.py` and `task_data_path.py`. Under §10.6
that is unambiguously *"a semantics-bearing production dependency DID change"*,
so the prior evidence could not be claimed current by inspection.

Both bounded runners were rerun (real GPU, real data, **no LLM** — not a Gate;
explicitly authorised by C7's validation plan):

| | Pets | DAVIS |
|---|---|---|
| prior | `step08c_pets_gate2_20260818` @ `ede11fd5`, PASS | `step08c_davis_gate2_20260818` @ `ede11fd5`, PASS |
| rerun | `step10_p56_c7_pets_20260821` @ `c9031369`, **PASS** | `step10_p56_c7_davis_20260821` @ `c9031369`, **PASS** |
| headline | accuracy `0.02702702702702703` — **BIT-EQUAL** (= chance 1/37) | `mse` `0.017289766656259548` — **BIT-EQUAL**, still under baseline `0.017392322972086136` |
| Health | both blocking gates: same `check_verdicts`, same `resolved_action` (`invalidate_round`) — the real D14 collapse reproduced exactly | `davis_dispersion_blocking` `passed` / `continue`; dispersion `0.2156402715035823` — **BIT-EQUAL** |

**Verdict: the changed dependencies were behaviour-preserving for both tracks
— established by rerunning, not by inspection.** The retained L3 evidence is
CURRENT at the candidate head.

### 22.10 Gate-2 readiness packet (written BEFORE launch, §15.2)

**Candidate.** `93b83625` — the C7 head. Working tree **CLEAN** (`git status
--porcelain` empty at packet time; the advice file below is added and committed
with the Gate evidence).

**Pre-launch re-reads (the §15.2 rule-4 requirement, done not assumed).**

* `docs/gates/gate_testing_standard.md` re-read: canonical cold-start command
  (§"Canonical command"), the 2026-08-16 BINDING model-size policy (4 GiB
  **enforcement** + an **advice file** — *"Both halves are required, and
  neither works alone"*), the depth row *"cross-iteration behaviour or resume
  | ≥ 2 iterations"*, the no-`tee` rule, and the auto-resolved `--data_dir`.
* Actual CLI re-read from source: every flag below verified present in
  `_chain_common.sh`'s parser, **including this PR's own `--task_composition`**.
* `--runtime_watchdog` is included. The 07a Gate-2 incident (the watchdog
  killing runs inside the un-priced validation pass) was closed by **07c**,
  merged as `52bd98ba` — verified in history rather than assumed.

**Exact command.**

```bash
bash sdsc_submission_scripts/run_chain.sh \
    --mode lilab \
    --workspace /home/klz/Data/SIDEREIS_DATA/step10_p56_gate2_<stamp> \
    --run_name p56_gate2 \
    --task_composition configs/task_composition/tidmad.yaml \
    --num_iterations 2 \
    --max_rounds 1 \
    --max_proposal_attempts 3 \
    --max_epochs 1 \
    --data_scope 4-9 \
    --health_gate_files 4,5,6,7,8,9 \
    --validation_max_portion 0.01 \
    --validation_max_train_samples 2000 \
    --validation_max_phase_seconds 900 \
    --runtime_watchdog \
    --no-force_formal_round \
    --trial_vram_budget_gb 4 \
    --formal_vram_budget_gb 4 \
    --advice advice/gate/gate_p56_composed_lifecycle_advice.json \
    --llm_config llm_configs/openai_tiered_pro.json
```

Deltas from the canonical command, each justified: `--num_iterations 2` (the
depth row; **NOT 3** — the ≥ 3-iteration promotion property is
deterministic-owned and a 3-iteration real Gate would duplicate that owner);
`--task_composition` (the whole point — this is the first real composed run);
4 GiB budgets + `--advice` (the binding 2026-08-16 policy). Cold-start: **no
`--seed_paths`**. No `--data_dir` (launcher resolves it). No `tee`.

**Workload / projection.** 2 iterations × 1 round × ≤ 3 proposal attempts,
1 epoch, 6-file partial scope (4–9) with the paired `--health_gate_files`.
Real LLM (`openai_tiered_pro`), real training, real inference, real scoring,
real chain restore between iterations. Projected wall time **≈ 20–40 min**,
inside the pre-authorised ≤ ~1 h envelope; ordinary single-GPU (RTX 5090,
32 GiB) and ordinary API spend. Non-destructive: a fresh workspace under
`SIDEREIS_DATA`, no existing evidence touched.

**Deterministic prerequisites: GREEN at the candidate.** 189 passed across all
C0–C7 owners (the four lifecycle modules, both C5 wiring modules, C6's
three-task closure, C1's projection, C0's producer baseline) plus the
Step-09.5a oracle and single-writer censuses.

**PASS criteria — ALL from persisted artifacts, never from an exit code.**

1. **Composed**: the run-invariants lock carries the composition's semantic
   fingerprint. (Without this, nothing else about the run is composed.)
2. **A — findings, the REQUIRED non-vacuous witness.** Iteration 1 produces
   ≥ 1 usable `key_findings` entry, present in its committed interpretation
   artifact; after the REAL restore, iteration 2's proposer `expert_context`
   contains those exact finding(s). **If iteration 1 produces no usable
   finding, the Gate MUST NOT PASS** — the workload did not exercise the
   carried-context boundary. That is a FAIL, not "inconclusive".
3. **B — confirmations, the exact-restore MECHANISM.** Iteration 1's output
   mapping deep-equals iteration 2's restored `InterpretationInput` mapping.
   Non-empty ⇒ record the stronger evidence. `{}` ⇒ record the equality and
   claim **NO** non-empty reachability — that property's owner remains the
   deterministic ≥ 3-iteration test plus its four severing mutations.
4. Real training / inference / scoring each executed with finite results.

**FAIL / INCONCLUSIVE taxonomy.** A code, workflow, science or lifecycle
failure is **FAIL** — diagnose, fix within the frozen contract, and the fix
creates a NEW candidate requiring its deterministic prerequisites again. A
non-discriminating workload (criterion 2 unmet) is **FAIL**. Only a genuine
provider/network/service failure leaving no trustworthy behavioural evidence
may be **INCONCLUSIVE**; a bad command shape, a missing artifact or an
implementation-caused training failure may not.

**What this Gate does NOT own (stated here so the closeout cannot drift).**
It is composed **TIDMAD**, whose Health family is the same file the legacy
path resolves — so it **cannot discriminate W6's Pets/DAVIS genericity and
must never be credited with it** (operator ruling). W6's owners are the
deterministic TIDMAD/Pets/DAVIS binding tests, the wrong-family anti-vacuity
test and the sequential run-scope evidence. Likewise, per the parent, **no
TIDMAD-only Gate may support a genericity claim**: that belongs to the
censuses and C6's three-task drives.

**Authorisation.** Pre-authorised by the frozen design (§15.2) and the
operator's C8 ruling; inside the envelope, so launched autonomously with no
further stop.

### 22.11 Gate 2 — ATTEMPT 1: **FAIL** (real defect found), and W7

**Verdict: FAIL.** Classified per the frozen taxonomy as a real
code/lifecycle failure — NOT "inconclusive". The composed chain refused to
start, before any LLM spend.

```text
run_one_iteration.py:1985  run_workflow
  -> model_exploration.py:1819  build_run_invariants
  -> config.py:667  materialize_effective_config
ValueError: health_checks_effective.yaml mismatch ... source YAML content
           drifted since materialization
```

**Diagnosis (reproduced, not inferred).** The workspace was FRESH, so "drifted"
was impossible in the sense the message means. Materializing the same inputs
twice — once with the legacy binding, once with the composition's — differs in
exactly ONE line:

```diff
-task_health_binding: legacy_default
+task_health_binding: explicit
```

and the workspace file carried the **legacy** sha (`abced734…`), proving
something materialized it BEFORE `run_workflow` had the composition. That
caller is `run_one_iteration.compute_expected_invariants` (`:1465`), whose own
docstring asserts *"idempotent — `run_workflow`'s pre-flight recomputes the
identical body sha"*. **P1 gave `run_workflow` a `task_health_binding` and did
not give it to this earlier pre-flight**, so the claim silently stopped being
true for composed runs: two documents, two shas, and the workspace-immutability
check correctly refused.

**Why no test caught it.** The module CLI resolves its composition before its
only materialization, so that path was always consistent. **Nothing drove the
REAL chain runner under a composition** — which is precisely the failure class
§15.2 says this Gate uniquely owns, found on its first execution.

**W7 — the fix (same family as W1–W6: a composed run's pre-flight silently
using the legacy binding).** The composition is resolved ONCE, before the
pre-flight, and the SAME binding is passed to both materializations.
ACTIVATION stays exactly where P1 put it; composing is pure resolution.
`None` reproduces pre-W7 behaviour exactly.

Verified: composed materializations now agree; legacy materializations agree
AND the legacy sha is **unchanged at `abced734…`** — the very value the failed
run wrote, so the un-composed path is provably untouched.

Regression coverage (`TestW7PreflightAndWorkflowAgree`, 6 tests): the
double-materialization regression; an anti-vacuity test proving the two
bindings really DO produce different documents (otherwise the first test would
pass trivially); the legacy-sha parity pin; and two source-level checks — that
the runner passes the binding, and that the composition is resolved BEFORE the
pre-flight, since ordering is the fix's substance.

**A new candidate.** Per the taxonomy, the fix moves the head, so Gate 2
attempt 2 runs against a NEW candidate with its deterministic prerequisites
re-verified. Attempt 1 is retained here as evidence, not deleted.

### 22.12 Gate 2 — ATTEMPT 2: **FAIL** (two findings), W7 completed

**Verdict: FAIL.** Two distinct problems, one a defect and one a workload
sizing issue. The run got much further than attempt 1 — W7's first half held,
the composed materialization succeeded, a real LLM proposed and implemented a
real candidate, and real training ran.

**Finding 1 — W7 was INCOMPLETE, and it was my error.** Iteration 2 refused:

```text
run-invariants lock violation:
  task_composition_fingerprint: locked='d6628a93…' vs this run=None
```

`build_run_invariants` takes **two** composition-derived arguments, and
`run_workflow` passes both. W7's first cut threaded `task_health_binding` alone
and forgot `task_composition_fingerprint`, so iteration 1's workflow wrote a
lock containing the fingerprint and iteration 2's pre-flight computed `None`
against it. Same defect class as W7 itself, one argument over.

**Fixed STRUCTURALLY rather than by adding the missing argument.**
`compute_expected_invariants` now takes the **composition object** and derives
every composition-dependent invariant itself, so the two call sites cannot
diverge again. Added a **census** comparing the composition-derived keyword
SETS at both `build_run_invariants` call sites — asserting the two names would
have carried the same blind spot the next time a third is added. The census is
verified to FAIL on the first cut (`{task_health_binding}` vs
`{task_composition_fingerprint, task_health_binding}`).

**Finding 2 — RETRACTED. There is no runtime-control defect.**

```text
Previous assumption:
    the ~0.17 s repeated overshoot suggested a small fixed-cost
    under-pricing defect in runtime control.

Audit evidence:
    the watchdog deadline is max(estimated_deadline, floor_seconds),
    with floor_seconds = 60.0 (core/runtime_control/session.py:98,
    "prevents degenerate deadlines for near-zero estimates").
    `deadline, source = min(candidates, ...)` then
    `return max(deadline, floor_seconds), source` — so `source` labels the
    winning CANDIDATE, not the returned number. The verified estimate was
    below the floor; 60.0 was therefore the FLOOR, not the priced estimate.
    The suspiciously round 60.0 was the tell.

Corrected understanding:
    no runtime-control pricing defect is established.
    The workload simply takes slightly more than the production 60 s
    minimum deadline.

Validation consequence:
    the adjacent runtime-control debt is RETRACTED — it is not carried
    forward and must not appear in the PR body or any status document.
    Do not change or disable the watchdog.
    Gate workload may be reduced only through a valid knob that reduces
    actual executed work while preserving the frozen Gate failure class.
```

Because the floor is FIXED, reducing real work lowers the actual runtime while
the deadline stays pinned at 60 s — so the Gate's own bounding lever genuinely
applies here. The earlier worry that "deadline and workload shrink together, so
it cannot help" does not hold in a floor-dominated regime.

**The response** is the Gate's OWN legitimate bounding lever — *"the Gate
harness owns the amount of REAL WORK a resolved plan may execute"*. No deadline
was enlarged and the watchdog was not disabled: either would be tuning the
instrument to get the reading.

### 22.13 Gate 2 — ATTEMPT 3: **FAIL / invalid Gate launch configuration**

| | |
|---|---|
| executable SHA | `498fbd4b` |
| verdict | **FAIL** |
| failure class | **invalid Gate launch configuration** — not a product FAIL, not a provider INCONCLUSIVE |
| reason | `--validation_max_portion 0.002` violates `eval_portion: ge=0.01` (`agent/schemas/hyperparam_tuning.py:921`); Pydantic rejected every plan, 192 rejections across both iterations |
| action | terminated at ~17 min rather than left to burn the remaining attempts |
| **useful lifecycle evidence** | **NONE** — none of those 17 minutes counts toward Gate coverage |

`--validation_max_portion` was never an available lever: `0.01` is the floor and
is exactly what attempt 2 already used.

### 22.14 Gate 2 — ATTEMPT 4: launch discipline

**Evidence identity = executable SHA + resolved Gate configuration.** Attempt 4
is not a "blind rerun of attempt 3": the production candidate is unchanged in
substance, but the bounded workload is corrected and newly validated.

| | |
|---|---|
| executable SHA | `dbe60e29` (C7 head + W7 complete + this ledger correction; production code identical to `498fbd4b`) |
| `--validation_max_portion` | `0.01` — the schema floor, valid |
| `--validation_max_train_samples` | `2000 → 400` |
| watchdog | **ON**, `floor_seconds` production default, deadline logic **unchanged** |
| iterations / rounds | 2 / 1 |

**The lever was verified against source before relaunch, not assumed.**
`validation_max_train_samples` is declared as *"Absolute ceiling on the ML
segments one training epoch may contain, applied where the epoch is BUILT — so
fewer segments are read and fewer optimizer steps exist, before any of them
run… Clamps, never rejects"* (`core/runtime_control/session.py:215`), and its
production consumer is `execute_tools/train_engine_sandbox.py:1171`
(`max_train_samples`, applied where the epoch is built). So it reduces REAL
executed work — not an estimate input, not logging metadata, not an unconsumed
advice field.

**400 remains a faithful functional smoke**: real dataset, real batching, real
forward/backward, real optimizer steps (~100 at batch 4), real validation, real
inference, real metric scoring. Fewer steps, not a hollowed-out path.

**Pre-launch checklist, all confirmed**: attempt 3 fully terminated (chain and
runner, no orphan child) · candidate SHA exact · tree clean · final command
recorded · `eval_portion` schema-valid · the train-sample cap verified to reduce
REAL work · watchdog ON · deadline logic unchanged · 2 iterations · 1 round ·
composed TIDMAD fingerprint expected · deterministic prerequisites green (194
passed at the candidate) · findings non-vacuity acceptance unchanged ·
confirmations restore acceptance unchanged. Zero schema rejections observed
after launch.

### 22.15 Runtime-control forensic audit (operator-ordered, read-only)

**Gate 2 relaunches PAUSED. Zero production edits in this phase.** Attempt 4
was terminated on the operator's instruction; chain and runner processes
confirmed gone, no orphan training/inference/LLM child, tree clean.

#### Correction to this ledger's own earlier claim

```text
Previous assumption:
    attempt 3 produced "192 rejections".

Audit evidence:
    192 is the count of the SUBSTRING "greater_than_equal", which Pydantic
    prints once per field error plus a URL line. The actual event count is
    15 planning attempts, each raising ONE ValidationError carrying THREE
    field errors (trial_portion, train_portion, eval_portion).

Corrected understanding:
    the burn was 15 LLM planning calls, not 192 rejections.

Validation consequence:
    the magnitude claim is corrected; the DEFECT is unchanged and is if
    anything clearer — 15 identical deterministic failures is still a full
    retry-budget burn on a state that cannot succeed.
```

#### The exact multiplication (derived from source, not from the log)

```text
ml_hyperparameter_tune_agent.py:1097
    while completed_rounds < max_rounds and consecutive_fails < max_fail_rounds:

ml_hyperparameter_tune_agent.py:1099-1100
    is_formal_round = completed_rounds == max_rounds - 1      # --max_rounds 1 => TRUE on round 1
    N = attempts_per_formal_round_setting if is_formal_round else attempts_per_round_setting

defaults: attempts_per_formal_round = 5   max_fail_rounds = 3
```

A failed round does **not** increment `completed_rounds`, so the outer `while`
repeats until `consecutive_fails` reaches 3:

```text
per iteration : 3 fail-rounds x 5 attempts        = 15 planning attempts
whole Gate    : x 2 iterations                    = up to 30
observed      : 15 before manual termination
log confirms  : "Round 1 exhausted all 5 attempt(s) ... (consecutive_fail_rounds=1/3)" then 2/3
```

Note `--max_rounds 1` makes round 1 the FORMAL round, so the budget is
`attempts_per_formal_round` (5), NOT the chain's `ATTEMPTS_PER_ROUND=3`.

#### Why replanning could never fix it

`planning.py:311-313` applies the operator's `--validation_max_portion` as a
hard `min()` clamp to all three portions **after** the LLM plan resolves:

```python
cfg_trial_portion = min(cfg_trial_portion, _ceiling)
cfg_train_portion = min(cfg_train_portion, _ceiling)
cfg_eval_portion  = min(cfg_eval_portion, _ceiling)
```

With `_ceiling = 0.002`, every plan is clamped to 0.002 and `TrialConfig`
(`planning.py:348`) rejects all three against `ge=0.01`. **No plan the LLM can
author can satisfy the schema**, which is precisely why 15 LLM calls were spent
on a state with zero success probability.

#### The precedent that already exists

The same catch block (`ml_hyperparameter_tune_agent.py:1382-1395`) already
implements the correct behaviour for a sibling failure class:

```python
if isinstance(e, PlanOverridesError):
    # FU-10 — deterministic operator-configuration error;
    # retrying cannot change it and recording it as an
    # attempt failure would burn the retry budget.
    raise
```

A clamp-induced `ValidationError` is the SAME class — deterministic operator
configuration, unfixable by retry — but falls through to the generic
`print(f"Loop Error: {e}")` path and burns the budget. A constraint on any
repair is recorded in that comment: the branch was folded into this handler
because *"one more clause on this try pushes run() past pyright's
complexity-analysis ceiling"*.

#### The watchdog half — NO defect; the Gate used the WRONG LEVER

Attempt 4 is the decisive experiment. With
`--validation_max_train_samples 2000 -> 400` the timeouts were **60.166 s and
60.114 s** — statistically identical to attempt 2's 60.166/60.172. Cutting the
TRAINING cap moved the runtime by ~0.05 s.

The model's own round-2 reasoning names the cause: *"the round failed because
full validation over 30000 segments exceeded the watchdog"*. It is the
**validation** pass, and `validation_max_train_samples` does not bound it.

The correct lever exists, is CLI-exposed, and 07c created it for exactly this
mistake — `core/runtime_control/session.py:236`:

> *"`validation_max_samples` … Absolute ceiling on the ML segments one
> VALIDATION pass may contain … ORTHOGONAL to `validation_max_train_samples`:
> that one bounds training rows, this one bounds validation rows, and neither
> constrains the other. **It exists because 07a's Gate 2 ran validation at 7.5x
> the training epoch — the training ceiling could not bound it, because it does
> not bound that set.**"*

`--validation_max_samples` is parsed at `_chain_common.sh:363` and forwarded at
`:483`. **It was simply not used.** The canonical Gate command in
`docs/gates/gate_testing_standard.md:187` omits it and line 233 calls the
TRAINING cap *"the Gate's primary sizing mechanism"* — which is what led the
Gate configuration astray.

#### Provenance (observability)

`core/sandbox_executor.py:493-494` returns `max(deadline, floor_seconds)` while
`source` names the winning CANDIDATE, so a floor-dominated deadline still
reports `source=verified_components`. Confirmed misleading; execution semantics
are correct.

#### Watchdog trace — three additions, each verified directly

**(a) The floor cannot be expressed in provenance at all.** `grep '"floor"'`
over `core/` and `nodes/` returns **nothing**: there is no `"floor"` source
sentinel. `sandbox_executor.py:495-496` binds `source` from `min(candidates)`
and then rewrites only the first tuple element with `max(deadline, floor)`, so
the pair returned is `(60.0, "verified_components")` even when the estimate was
far below 60. `floor_seconds` never reaches `kill_info`, the operator message,
or the persisted `memory.watchdog_*` triple. **No test pins what `source` says
when the floor wins** — `test_watchdog.py:169` and
`test_pr07c_validation_pricing.py:248` both discard it as `_source`.

**(b) This exact signature is already documented — twice.** 07a's Gate attempts
002/003 were killed at *"deadline 60.0 s = floor"*
(`pr_07a_training_history_diagnosis.md:1235-1237`), and 07c's design says
plainly: *"their enforced deadline was **60.0 s = the floor itself**, i.e. their
predicted sum was below 60 and only the floor carried them that far"*
(`pr_07c_tuner_measurement.md:3043-3045`). So the pattern this Gate hit is a
KNOWN one, and 07c even mandates a masking check because `source` alone is
insufficient. The effective multiplier is `1.0` on the default path
(`session.py:160-170`; the 1.5/2.0/3.5 postures are launch-config only), so the
estimate is unmultiplied.

**(c) NEW FINDING — F-RC-6: the escalation feedback that would break the loop
is gated OUT of it.** The "model too large — reduce model size" advisory
(Trigger B, `feedback.py:232-243`, message `:503-507`) only considers records
with `status in {"skipped_oom_risk", "skipped_time_risk"}` (`feedback.py:64`).
A watchdog kill is recorded with **`"status": "error"`**
(`ml_hyperparameter_tune_agent.py:1404`). **A wall-clock-timeout burst
therefore never trips Trigger B and never produces the shrink advisory** — the
one piece of structured feedback designed to end exactly this loop. The planner
receives only the free-text `memory_update` *"Do not repeat the failing
configuration unchanged"* (`:1424-1427`), which is prose, not enforcement.

**Retry-ownership conclusion, refined.** `WallClockTimeoutError` is caught by
name nowhere; it is absorbed by the single broad `except Exception` at
`ml_hyperparameter_tune_agent.py:1380`, and the next `attempt_in_round` DOES
call `brain.plan()` afresh. So the retry is not a blind re-execution, and the
design intends it — §4 of `runtime_estimation_and_watchdog.md:588-602` decided
*"timeout counts toward the attempt budget; the round continues to its next
attempt"*, with *"the planner sees the timeout with its config in memory"* as
the mechanism that makes the next attempt cheaper. That mechanism was observed
working in 07a (attempts 001→004 shrank until one fit) — **at a cost of three
wasted attempts**, and with Trigger B silently unavailable throughout.

**Therefore the identical-timeout retry verdict stands as NO DEFECT**, with one
qualification worth carrying: the loop's designed exit depends on LLM
discretion, and the structured signal meant to steer it (F-RC-6) never fires
for this failure class.

#### Invalid-config trace — the decisive repair finding, and two corrections

**THE FAIL-FAST GUARD ALREADY EXISTS AND WAS NOT APPLIED TO THIS FLAG.**
`run_one_iteration.py:92-108` defines `_portion_floor`, an argparse `type=`
validator whose own docstring names precisely the failure this Gate hit:

> *"expected a float in [0.01, 1.0] … The 0.01 floor matches the Pydantic
> schema … Failing here at argparse-time keeps the iteration from spending
> tokens on Interpretation only to crash inside the Proposer's Pydantic
> validator."*

```text
--trial_portion            type=_portion_floor   :871   GUARDED
--eval_portion             type=_portion_floor   :878   GUARDED
--validation_max_portion   type=float            :1116  UNGUARDED   <-- the gap
```

Two further layers could also have caught it and did not:
`HyperparamTuningInput.validation_max_portion` declares `gt=0.0, le=1.0`
(`hyperparam_tuning.py:1959-1961`) rather than `ge=0.01`, so the schema that
KNOWS the downstream floor does not enforce it; and `validate_runtime_config`
(`:2443`), documented as running *"BEFORE any LLM call or file I/O"*, does not
cross-check the ceiling against `TrialConfig`'s portion bounds.

**Corrections to this ledger's own arithmetic.**

```text
Previous assumption:
    proposal attempts (3) were part of the multiplication.

Audit evidence:
    an AST walk of the loop nesting shows the tuner call sits OUTSIDE the
    proposal loop --
        2312 -> [FunctionDef 1467, For 2095, For 2312]   proposal loop
        2784 -> [FunctionDef 1467, For 2095]             _tune_agent.run
    so max_proposal_attempts is NOT a multiplier.

Corrected understanding:
    attempt-level raises = 2 iterations x 3 fail-rounds x 5 formal attempts
                         = 30 (uninterrupted); 17 occurred before SIGTERM.
    Artifact evidence: iter_001 holds exactly 15 records (001-015, a fully
    exhausted iteration), iter_002 holds 2, all 17 classified
    ('error', 'ValidationError').
    The ~192 grep hits = 17 raises x 3 clamped fields x 2 stdout emissions
    x 2 tokens per field error, plus headers.
```

```text
Previous assumption:
    the run was trial-mode.

Audit evidence:
    --max_rounds 1 makes round 1 the FORMAL round
    (ml_hyperparameter_tune_agent.py:1099-1100), so N =
    attempts_per_formal_round = 5, and the clamped value was
    formal_eval_portion = 1.0 -> 0.002.

Corrected understanding:
    the harness manufactured the violation from the operator ceiling; the
    LLM's own ExperimentPlan.eval_portion (ge=0.01, :1084) was always legal.
    The planner is blameless, which is why the memory note "Do not repeat the
    failing configuration unchanged" was unactionable -- the planner never
    chose 0.002.
```

**F-RC-1 repair, now precisely bounded.** The cheapest correct fix is the
one-word precedent already used by two sibling flags:
`type=float` -> `type=_portion_floor` at `run_one_iteration.py:1116`. It fails
at argv time, before any LLM/GPU spend, with a message that already explains
the floor. Optionally hardening `HyperparamTuningInput.validation_max_portion`
to `ge=0.01` closes the same gap one layer in. Routing `ValidationError` into
the `PlanOverridesError` non-retryable branch remains a valid defence-in-depth
second layer, but is no longer required to stop THIS burn.

### 22.16 Gate-discovered GENERIC prerequisite fixes (NOT P5+P6 semantics)

The forensic audit (§22.15) produced bounded generic defects that are **not**
S5/S8 scope. They are recorded here for provenance only and are deliberately
NOT numbered into the W-series — a reviewer must be able to see at a glance
that this PR did not quietly absorb unrelated runtime-control work.

#### F-RC-1 — incomplete early enforcement of the executable portion floor

**One root defect, several instances.** Not four unrelated CLI edits:

```text
root cause:
    an operator-facing portion bound WEAKER than the downstream executable
    TrialConfig bound (ge=0.01) that consumes it

originally observed:
    validation_max_portion            (clamped onto all three portions)

structural census additionally found:
    formal_portion                    -> TrialConfig.trial_portion
    formal_eval_portion               -> TrialConfig.eval_portion
    (+ CLI-side looseness on train_portion / formal_train_portion, whose
     schemas already declared ge=0.01)
```

**Why it stayed latent for so long** — the trial/formal asymmetry, worth
keeping because it explains why THIS Gate configuration was the one to expose
it:

```text
trial mode   portions come from the LLM's ExperimentPlan, which already
             declares ge=0.01 -> the planner is structurally protected

formal mode  operator-provided values feed TrialConfig DIRECTLY
             (policy.py:1164-1170) -> weak CLI/intermediate bounds become
             observable

and `--max_rounds 1` makes round 1 the FORMAL round.
```

**The repair, at both boundaries.** Schema: `validation_max_portion`
`gt=0.0`→`ge=0.01`; `formal_portion` `ge=0.0`→`ge=0.01`; `formal_eval_portion`
`gt=0.0`→`ge=0.01`. CLI: the existing `_portion_floor` authority applied to
`--validation_max_portion`, `--train_portion`, `--formal_portion`,
`--formal_train_portion`, `--formal_eval_portion`.

**No third validation authority was created.** `validate_runtime_config` owns
dataset-RESOLVED validation; portion bounds are dataset-independent and belong
to the typed boundary. A test pins that it never grows one, so the two
authorities cannot drift into three.

**The structural guard tests a CONTRACT, not a naming pattern** (operator
correction). The rule is *"an operator flag must not be LOOSER at argv time
than the executable floor of the schema field it populates"* — it reads each
target's bound from the LIVE schema and requires `_portion_floor` exactly when
that target declares `ge=0.01`. A naming rule ("everything ending in
`_portion`") would wrongly reject a future flag whose target legitimately
allows `ge=0.0`. Today the two sets coincide; the contract version keeps
testing the right thing when they stop.

**The guard was DISCRIMINATING on first run** — it failed immediately, naming
four flags beyond the reported one:

```text
{'--train_portion': 'float', '--formal_portion': 'float',
 '--formal_train_portion': 'float', '--formal_eval_portion': 'float'}
```

That first-RED is the evidence it is not decorative. Each was then traced
through `_resolve_sample_set_cfg` to its actual target before being fixed —
no blanket edit on a name match.

**Validation.** 28 targeted tests. Broad regression across `tests/unit/scripts`
+ `tests/unit/sdsc_submission_scripts` + `tests/unit/agent/tune_ml_hyperparam_agent`:
**2279 passed**, 900.83 s, with ONE failure — `test_pr3_l2p_preflight`'s
`no_production_file_modified`, naming precisely the two uncommitted production
files, i.e. the documented clean-tree guard whose prescribed fix is the commit
itself. Shipped defaults verified still legal (anti-regression).

**Gate 1 remains NOT REQUIRED**: no LLM-facing prompt template and no
proposal-affecting schema changed. `HyperparamTuningInput` is the runtime/config
admission contract, not the proposer's schema.

#### F-RC-6 — an ACTUAL watchdog kill now reaches the architectural-feedback trigger

**Defect.** `_collect_disallowed_patterns` — the mechanism that tells the next
proposer *"this architecture is too expensive"* — consulted only PREDICTED gate
skips (`status in {"skipped_oom_risk", "skipped_time_risk"}`). An attempt that
was admitted, EXECUTED and then killed by the watchdog is recorded with
`status="error"`, so it was excluded: the one structured signal designed to end
a "too slow" loop was unavailable for the very failure that proves the
candidate is too slow. Observed in the real Gate: three consecutive kills, zero
architectural feedback.

**Discriminator: the EXISTING typed `failure_type == "wall_clock_timeout"`**,
never `status == "error"`. `_classify_attempt_failure` (`runtime.py:518`)
already emits it and its docstring says *"Downstream feedback keys off this
name"*. **No new taxonomy, no persisted-schema change, no retry-state-machine
change** — so the material-finding stop condition was not reached. A code bug,
a schema violation and an OOM all share `status="error"` and must NOT be read
as architectural evidence; four neighbouring `failure_type`s are asserted to
stay out.

**CATEGORICAL, not factor-tested — and it must be.** The watchdog kills AT the
deadline, so `elapsed / deadline` is ~1.003 by construction (60.166 s against
60.0 s in the run that found this) and could never clear
`TIME_FACTOR_THRESHOLD = 5.0`. That threshold separates a marginal PREDICTION
overshoot from a structural one; for a real kill there is nothing to separate —
the attempt demonstrably did not finish. **Routing timeouts through the factor
test would have been a silent no-op**, and a test pins exactly that.

**Validation.** 15 tests: the four required lanes (predicted skip fires · actual
timeout fires · ordinary error does NOT · success does NOT), four neighbouring
failure types held out, mixed record sets, and the anti-vacuity the operator
required — the timeout produces the SAME structured tags a predicted skip
produces for the same model, compared against a HARDCODED expected tag list
rather than "non-empty". Severing mutation **RED** (4 tests), restored
sha-verified.

**A fixture defect caught by the pre-existing lane.** The first draft used an
invented `wavenet_deep_stack`, which the tagger's narrow vocabulary
(`recurrent_over_T` / `dense_attention_over_T` / `scan_over_T`) matches NOT AT
ALL — every assertion would have been vacuously green. The *unchanged*
predicted-skip test failing is what exposed it; the fixture now uses a model
verified against the live tagger.

#### F-RC-4 — DEFERRED (observability only)

Watchdog provenance can report `source=verified_components` while the returned
deadline is the floor (`sandbox_executor.py:495-496`; no `"floor"` sentinel
exists). Execution semantics are CORRECT. Recorded as debt; **not** fixed in
these prerequisites and **not** a Gate blocker.

### 22.7 Deviations

*(none — no frozen contract has been changed)*

### 22.8 C2 severing mutations (§7.4's four-link proof)

Run with full hygiene: exactly ONE site replaced per mutation (count asserted
before mutating), `__pycache__` cleared before and after, restore from an
in-memory CONTENT backup with the file's sha256 re-verified, tree confirmed
clean afterwards.

| # | hop severed | site | verdict | first test RED |
|---|---|---|---|---|
| M1 | digest → `RestoredState` (the projection ASSIGNMENT) | `core/resume.py` | **RED** (1 failed / 18 passed) | `test_restore_prior_state_really_reads_the_digest` |
| M2 | `RestoredState` → `ChainState` seed | `model_exploration.py` | **RED** (2 failed / 17) | `test_a_restored_mapping_seeds_the_first_iteration` |
| M3 | `ChainState` → `InterpretationInput` pass | `model_exploration.py` | **RED** (7 failed / 12) | `test_the_mapping_accumulates_one_distinct_run_per_iteration` |
| M4 | interpreter output → `ChainState` loop closure | `model_exploration.py` | **RED** (5 failed / 14) | `test_the_mapping_accumulates_one_distinct_run_per_iteration` |

**M1 initially SURVIVED, and that was a real coverage gap, not a hygiene
problem.** The reachability harness hands `run_workflow` a `RestoredState`
directly and never calls `restore_prior_state`, and C1's projection tests call
the projection directly — so *nothing* exercised the assignment line joining
them. A test writing a real committed iteration (run_output + manifest +
digest) and restoring through `restore_prior_state` was added; M1 then turned
RED. Without re-running the mutation after the first survival, the PR would
have shipped a hop with four tests around it and none on it.

**Process finding, recorded so it is not repeated.** The first mutation script
reverted with `git checkout -- <file>`, which discarded the *uncommitted* C2
edits to `model_exploration.py` (M3/M4 then reported "0 sites" — the tell).
The edits were reconstructed and re-verified green before the mutations were
re-run. Mutation reverts must restore from a content backup, never from git,
whenever the file under mutation has uncommitted work. This is the third
failure mode in the mutation-hygiene family, alongside stale `.pyc` and
wrong-site targeting.

### 22.17 Adversarial review (Phase 8–16), and what survived verification

Two independent read-only reviews ran against the frozen candidate
`671e2c3f` in an isolated worktree while Gate 2 and CI ran. **Every
load-bearing claim below was re-verified by the main agent before being
accepted or dismissed** — the reviews are input, not verdicts.

| # | claim | verified disposition |
|---|---|---|
| C1 | five un-threaded `is_valid_candidate` / `classify_candidate_health` sites in the tuner still resolve the LEGACY gate set, so a composed run diverges mid-flight | **NOT A BLOCKER.** Probe: composed TIDMAD and legacy resolve the IDENTICAL set `['amplitude_collapse_blocking','output_diversity_blocking','output_std_blocking']`. No divergence, no scope conflict, Gate 2 valid. Divergence is reachable only for composed CONTRAST runs, which cannot execute the tuner until CAP-SCOPE — already recorded as a named boundary in the C5 commit. **DEBT, already recorded.** |
| B1 | a composed TIDMAD run's prompts differ from an un-composed run's (no 42-file reference table) | **FALSE POSITIVE against the frozen design.** This is **C-P56-1**, the operator's own ruling: "Declared consequence, not a regression … implicit legacy reference science is forbidden in composed mode." Real behaviour, already decided. |
| C1(c) | `core/resume.py:435` is a third health-config authority | **PRE-EXISTING.** This PR changed 0 lines there. |
| E1 | C6's `test_no_implicit_legacy_reference_science_reaches_any_composed_run` never calls `drive()` despite claiming to observe the guard "through the loop" | **CONFIRMED, and worse than reported** — the claim is *unimplementable* in that harness, because the driver mocks `HyperparamTuningAgent` so `load_reference_scores()` never executes. Removed; real owner named. |
| — | three further false-assurance tests + two exact duplicates | **CONFIRMED.** See commit `f88f3e27`. |

**Fixed in `f88f3e27` (tests only, no production touched):** the vacuous
W4 test; a tautological "falsifier" that asserted `direction == "lower"`
then required asserting `== "higher"` to raise (a theorem of
`str.__eq__` — no production mutation could turn it red), replaced by a
cross-task differential which **immediately caught a real constraint**
(Health plugin registration is process-global; crossing tasks needs
`reset_run_scope()`); two plant tests that re-implemented their detectors
inline and so proved only that a COPY bites; and a second copy of
Step-09.5a's `_bare_local_writes` that could drift from the census
actually guarding the repository.

#### F-P56-3 — the composed binding reaches only the CHAIN-LEVEL invariants lock

Found by reading attempt 5's artifacts, not by either review.

`build_run_invariants` takes `task_health_binding` / 
`task_composition_fingerprint` with **default `None`**, and there are
**three** call sites in the composed path, not the two W7's census
compares:

| site | composition-derived kwargs |
|---|---|
| `sdsc_submission_scripts/run_one_iteration.py:1500` | **yes** (W7) |
| `workflows/model_exploration.py:1819` | no |
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:604` | no |

Observable in attempt 5: the chain-level lock carries the COMPOSED health
sha `2b804d73…` and `task_composition_fingerprint d6628a93…` (W7 working,
fingerprint identical to the P1 fixture), while the per-model lock carries
the LEGACY sha `abced734…`.

**Consequence today is nil for behaviour and non-nil for resume safety.**
For TIDMAD the two documents resolve the same gate IDs (probe above), and
the three locks live in different workspaces so nothing aborts. But a
composition change is pinned only at the chain level: an inner lock would
not detect it.

**NOT fixed in this child, deliberately.** Threading the binding into the
workflow and tuner sites changes what two additional entry points lock —
a semantic change to run-invariants comparison, on a surface the frozen
§12.1 tripwire binds. Recorded OPEN for operator scheduling; per the
standing rule, adjacency is not a schedule.

### 22.18 Gate-contract audit (operator-ordered, 2026-08-21) — HealthGate is NOT a Gate-2 dependency

**Why the audit happened.** Gate attempts 5-7 stopped being evidence about
P5+P6 and became evidence about Gate harness design. The operator's
diagnosis, accepted in full: attempts 1-2 caught real production defects
(W7, composition invariants); attempts 3-4 were launch-parameter errors;
but attempts 5-7 were **workload engineering** — attempt 5 collapsed on too
little data, attempt 6 was refused by the RT5 step guardrail on too much,
and each was answered with more specific model/loss/epoch advice. That is
coaching a model to pass a quality threshold, not validating
infrastructure.

**Question 1 — does the frozen contract require a HealthGate PASS?**
**NO.** `healthgate` / `health gate` / `blocking` / `invalidate` appear
**zero times** in §15.2 (the whole Gate-2 ruling). The frozen PASS
criteria are the composed execution chain plus the two-layer evidence
contract, whose witness is a **usable key finding** — "usable" meaning
true and specific about a REAL completed experiment, not produced by a
GOOD model.

**What attempt 5 actually showed.** Every clause of the contract was met
except the witness: real LLM, real candidate, real implementation, real
training, real validation, real inference, real scoring (finite score
`-2.9048`), under a real composition with `task_composition_fingerprint`
pinned in the chain-level lock. It then failed for a reason the contract
does not name — output collapse tripped a BLOCKING HealthGate, the ROUND
was invalidated, no record was committed, and the finding had no digest to
travel through. The interpretation it produced ("trained and scored, but
low output diversity") would itself have been a perfectly legitimate
finding.

**The defect was in the Gate harness, not in P5+P6**: a quality gate
irrelevant to the feature under test was left as a BLOCKING dependency, so
Gate 2's outcome was decided by three variables it does not test —
whether the LLM proposes a well-training model, whether a tiny smoke
workload suffices, and whether a Health threshold is met.

**Resolution (operator option A).** Use the existing production-supported
subsystem switch; change NO Health semantics.

| change | rationale |
|---|---|
| `--no-health_gate_enabled` | model quality no longer gates the lifecycle test (`_chain_common.sh:81` documents this as the DS6c switch) |
| drop `--health_gate_files` | meaningless with the subsystem off; the DS8 pairing rule is gated on `health_gate_enabled` (`model_exploration.py:1812`) |
| `--result_authority diagnostic` | honest: the run certifies no science |
| `--formal_train_portion 0.25` | workload volume owned by the HARNESS, not by advice prose |
| advice reverted | all Gate-specific model/loss/epoch coaching removed |

**Two mechanisms checked rather than assumed:**

* **`--healthgate_mode observe_only` is NOT usable here.** It is a
  DECLARATION that must match the config, not a switch: declaring it while
  gates still enforce is itself refused (`launch_policy.py`, "gates still
  [enforce]"). Using it would require authoring a non-enforcing health
  config — i.e. changing Health semantics, which the operator excluded.
* **`diagnostic` does not suppress the evidence.** `core/resume.py:822`
  KEEPS a non-authoritative record and only bars chain-incumbent
  promotion, so record → interpretation → findings → digest → restore →
  iteration-2 context all still occur.

**This is test ISOLATION restored, not a relaxed test.** HealthGate
thresholds keep their own owners (deterministic unit evidence, the 08c
real-runner Gate-2 PASSes for Pets and DAVIS). P5+P6's Gate tests P5+P6.

**Observation recorded, NOT fixed:** the launch-policy vocabulary has no
term for "subsystem disabled" — both `blocking` and `observe_only`
describe the CONFIG's gates, so a run with health gates off must still
declare `blocking`, and only `result_authority=diagnostic` carries the
honesty. A third declared value would fix it; out of scope here.

### 22.19 F-P56-4 — the frozen Gate shape cannot satisfy its own Layer A (BLOCKING, operator decision required)

**Found by executing the corrected Gate (attempt 8), not by review.** This
is a defect in the FROZEN §15.2 contract, not a workload problem, and no
amount of workload tuning can fix it.

**The three requirements are mutually unsatisfiable:**

1. **cold-start** — mandatory for every real-training Gate run (operator
   rule 2026-07-27, no `--seed_paths`);
2. **exactly 2 iterations** (§15.2, "deliberately NOT 3");
3. **Layer A** — "iteration 1 must produce at least one usable key
   finding … after the REAL chain restore, iteration 2's proposer
   `expert_context` must contain the exact prior finding(s)".

**Why.** The loop order is fixed and was verified in source:
`interpret` (`model_exploration.py:2210`) → proposer READS
`state.accumulated_key_findings` (`:2335`) → `propose` (`:2425`) →
**closure appends THIS iteration's findings only afterwards** (`:2888`).
So an iteration's findings can only reach the NEXT iteration's proposer.

Iteration 1's interpreter runs BEFORE iteration 1 has any result of its
own, and under **cold start there is no prior output at all** — so it
produces nothing to carry. The findings ABOUT iteration 1's experiment are
produced by **iteration 2's** interpreter, and could only reach a proposer
at **iteration 3**, which the frozen shape does not run.

**Why the deterministic tests did not catch it — and this is the
lesson.** `test_step10_p56_c0_multi_iteration_baseline.py:76` calls
`_write_tuning_output(tmp_path, "punet")`, **seeding a prior tuning output
before iteration 1**. That is what gives iteration 1's interpreter
something to interpret and produces the `[0,1,1]` render counts. The
deterministic harness is **seeded**; the real Gate is **cold-start by
mandatory rule**. The two disagree on the one precondition Layer A depends
on, and nothing compared them.

**Executed evidence (attempt 8, workspace
`step10_p56_gate2_a8_20260821_123858`):** iteration 1 completed a REAL
experiment — `manifest.json status=completed`,
`best_score=-1.7906921066744612`, real training (`Epoch 0`, validation on
9,375 ML segments), inference and scoring, under the composition. Its
interpreter ran (Conclusion / Key Factor / Discovery all present). Then:

```text
12:51:59  iter_002/accumulated_findings_iter_002.json
          {"iter_index": 2, "consumed_by": "iter_002",
           "source_iters": [1], "count": 0, "findings": []}
12:52:24  iter_002/.../interpretation_iter_002.json
          key_findings = 3 substantive findings ABOUT iteration 1's
          -1.7906921066744612 result
```

The restore MECHANISM worked and recorded its provenance — it consumed
iteration 1 and said so. Iteration 1 simply had no finding to give.

**This is NOT a P5+P6 lifecycle defect.** The carry machinery executed
correctly; the Gate shape gives it nothing to carry.

**Options (operator's call — NOT taken autonomously):**

| # | option | cost | cold-start rule |
|---|---|---|---|
| **A** | **3 iterations cold-start** — iteration 2's interpreter produces findings from iteration 1's REAL result; iteration 3's proposer receives them across a REAL restore | ~1 extra iteration (~13 min) | **respected** |
| B | 2 iterations WITH `--seed_paths` | none | **violated** — needs an explicit operator exception |

**A is recommended.** §15.2's "deliberately NOT 3" rationale is explicitly
about the ≥ 3-iteration **promotion** property (Layer B / confirmations)
being deterministic-owned — a 3-iteration run makes no promotion claim, it
merely gives the findings carry ONE real restore to cross. Option A also
keeps `vocab_link_confirmations` behaviour unchanged (`{}` observed in
attempt 8; the frozen contract already says `{}` ⇒ record the equality and
claim NO reachability).

**Gate 2 therefore remains OPEN.** Attempt 8 is real, valuable evidence of
composed execution — including the C-P56-1 guard observed live in a
production prompt ("Reference scores: NOT LOADED — this run is COMPOSED")
— but it does not satisfy Layer A, and under the frozen rule a Gate whose
witness is absent MUST NOT PASS.

### 22.20 Gate 2 — ATTEMPT 8/9: **PASS** on the corrected contract (evidence SHA `d3001007`)

Cold-start composed TIDMAD chain, **3 iterations × 1 round** (depth amended
per F-P56-4), real LLM + real training + real inference + real scoring,
blocking HealthGate isolated via `--no-health_gate_enabled` +
`--result_authority diagnostic` (§22.18). Workspace
`step10_p56_gate2_a8_20260821_123858`.

| iteration | manifest | score |
|---|---|---|
| 1 | `completed` | `-1.7906921066744612` |
| 2 | `completed` | `-1.8144883477572284` |
| 3 | `completed` | `-1.2859566864990437` |

**Functional criteria** — chain exited 0; real candidates `v3 → v4 → v5`
generated, validated and registered; real training (`Epoch 0`, validation
on 9,375 ML segments); real inference; real scoring producing finite
results; composed binding pinned (`task_composition_fingerprint
d6628a93…`).

**C-P56-1 observed LIVE in a production prompt** — evidence no
deterministic test can produce:

```text
Reference scores: NOT LOADED — this run is COMPOSED. The legacy TIDMAD
reference tables are task-specific science and are never loaded
implicitly for a composed run
```

**Layer A — SATISFIED.**

```text
iter_002  source_iters [1]     count 0   <- structural: cold-start iter 1
                                            had no prior output to interpret
iter_003  source_iters [1, 2]  count 5   <- the witness
[CHAIN] Restored 2 prior plugin(s) from iters [1, 2]
```

The sidecar is a LOG, not the channel (`run_one_iteration.py:1957-1959`
says so), so the witness was taken from the CONSUMER. Iteration 3's
proposer artifact AUTHORED, in three separate fields:

* `falsifiable_prediction.current_value = -1.7906921066744612` — iteration
  1's exact score as its prediction baseline;
* `inherited_components` — "v3 used nn.Embedding(256,16) and completed a
  valid **73,280-parameter** run" — the comma-formatted count that exists
  only in carried finding [1]'s prose, not in any numeric field;
* `proposed_vocab_links` — "The 10-block v3 scored -1.7906921066744612
  versus the otherwise similar 8-block…" — cross-iteration synthesis.

Iteration 3 is a SEPARATE PROCESS from iteration 1, and the proposer's
only channel is its typed input. **Layer B**: `{}` in both digests —
equality recorded, **NO** non-empty reachability claimed; that property's
owner remains the deterministic ≥ 3-iteration test + the four severing
mutations, exactly as frozen.

**Not a PASS criterion, recorded as observation**: iteration 3, the only
one whose proposer received carried findings, produced the best score of
the three. The Gate does not grade that.

### 22.21 Third adversarial strand — dispositions

| finding | verdict |
|---|---|
| W7 removed a crash manifest — composition resolved outside the `write_manifest(crashed=True)` handler, and the failure brake is fail-OPEN on a missing manifest, so a malformed `--task_composition` would crash every iteration without ever halting the chain | **CONFIRMED, FIXED** (`7bff5fee`) — a real regression introduced by this PR |
| the findings union had TWO implementations while its comment claimed "Applied, not re-implemented" | **CONFIRMED, FIXED** — `core.resume.union_key_findings` is the ONE authority; both consumers call it; structural guard mutation-proven (`77dc52fb`) |
| the task-name census is blind to `ast.Import`, so the three subprocess entrypoints could name every built-in and still pass while listed in `_DATA_PATH_SURFACE` | **CONFIRMED, FIXED** — bootstrap set pinned by exact-set equality (the F-P2b-4 shape) |
| `pillow` on the training/inference/scoring path but only a transitive dependency | **CONFIRMED, FIXED** |
| the confirmations-projection docstring says a key-less digest projects `{}`; the code SKIPS it (latest digest CARRYING the key wins) | **CONFIRMED, FIXED** |
| an un-threaded legacy classifier CRASHES (`HealthPluginRunScopeError`) or CLOBBERS `_TASK_FACTS` under a composed binding | **NOT REPRODUCED.** Probed against the real composed Pets binding: gate ids resolve to the Pets family, the legacy classifier returns `False` without raising, and `TaskHealthFacts(encoding_family='categorical_labels', symbol_cardinality=37)` is byte-identical before and after. The reporter's repro used a FABRICATED plugin-less task plus a pre-loaded plugin set. The mechanism is real in principle; no binding that exists triggers it. Disposition unchanged: **DEBT**, bounded by CAP-SCOPE |
| the tuner reads the ambient `active_task_data_path()` ContextVar instead of a declared input field (W4) | **ACCEPTED AS DEBT, not fixed.** Making it a declared field is a schema change to `HyperparamTuningInput` on a Gate-owned surface, and the frozen design specifies the guard as written. Recorded for Step 12 with the node-boundary rule cited |

**A lesson worth keeping.** The differential test
`test_the_closure_matches_the_projection_exactly` PASSED under the
mutation that re-inlined the dedup (1 failed / 16 passed; the failure was
the new structural guard). A differential can only catch a divergence
AFTER someone writes a second body that DISAGREES — it is blind to a
second body that agrees today and drifts tomorrow. That is precisely how
the duplicate authority survived review with a comment asserting the
opposite.

### 22.22 Adversarial review — CLOSED

**Three independent read-only strands**, all complete: (1) production diff
hunk-by-hunk; (2) test topology and redundancy; (3) structure growth,
semantic drift and genericity. Every load-bearing claim was re-verified by
the implementing agent before acceptance or dismissal — the strands are
input, never verdicts.

**Disposition tally**

| severity | raised | outcome |
|---|---|---|
| BLOCKER | 1 | **0 upheld** — probe showed composed TIDMAD and legacy resolve an IDENTICAL blocking gate set; contrast case is the recorded CAP-SCOPE boundary |
| MUST_FIX | 3 | **2 fixed** (crash manifest, vacuous W4 test) · **1 not reproduced** (`_TASK_FACTS` clobber / plugin crash — see §22.21) |
| SHOULD_FIX | 6 | **5 fixed** · **1 accepted as DEBT** (ambient ContextVar read in the tuner; schema change on a Gate-owned surface, Step 12) |
| NIT | 5 | **4 fixed** · 1 defensive-branch note recorded |
| FALSE_ALARM / pre-existing | 4 | recorded, no action |

**UNRESOLVED BLOCKER = 0. UNRESOLVED MUST_FIX = 0.**

**Structural before/after** (AST-measured independently, matching the
recorded §12.1 tripwire):

```text
run_workflow          LOC 1489 -> 1564   branch-ish 130 -> 136   stmt 365 -> 371
HyperparamTuningAgent.run     stmt 253 -> 256   branch 65 -> 66
tuning_output_to_model_run_summary   stmt 49 -> 49   branch 39 -> 39
```

The "sibling-shaped" claim is **PARTIALLY TRUE and now recorded as such**:
`vocab_link_confirmations` is genuinely parallel to `prediction_memory` at
all four hops; `accumulated_key_findings` was NOT (it accumulates, and it
had introduced a merge rule into `run_workflow`). That asymmetry is why
the union rule was extracted to ONE authority — after the fix, the closure
is a single call and the merge rule no longer lives in the orchestrator.

**Workflow parity conclusion.** Sixteen hunks classified; **fourteen are
pure ADDITIONS** of carried state whose un-composed/legacy path is
byte-identical. Three are intended behaviour changes, each declared:
the consumer reading `state.` instead of a stale bare local (Q-10-6 = A,
the fix itself), the W4 composition guard (C-P56-1), and the two
out-of-frozen-design prerequisites F-RC-1/F-RC-6. Loop-closure ordering
audited and CLEAN: every early exit (`Break :2573`, `Break :2583`,
`Continue :2602`) precedes all three closures, so no carried value can be
skipped independently of the others; one writer per value confirmed.

**Test consolidation.** Removable-with-no-lost-failure-class was assessed
at ~26-28 of 219 new tests, concentrated in one module. Acted on the
cases where the redundancy was EXACT or the test was actively misleading:
two byte-identical duplicates removed, one tautology replaced by a
cross-task differential, one unimplementable claim removed with its real
owner named, two plants repaired to call the detector under test, and one
copied AST helper replaced by an import. The remaining
parametrization-padding proposals were NOT acted on — thinning a
boundary-value parametrization is a judgement call with no failure class
at stake, and this PR is not the place to spend it.

### 22.23 Gate 2 — FINAL-HEAD RUN: **PASS** (terminal evidence, SHA `f150a625`)

Operator ruling 2026-08-21: the earlier PASS at `d3001007` could not serve
as terminal evidence, because the adversarial fixes changed
`core/resume.py`'s projection and `run_workflow`'s loop closure — the
direct owners of the Layer-A witness. ONE rerun at the final head, using
the exact already-corrected configuration; no further workload or
model-quality tuning of any kind.

Workspace `step10_p56_gate2_final_20260821_135242`, cold start, composed
TIDMAD, 3 iterations x 1 round, ~1 h 25 m.

| iteration | manifest | score |
|---|---|---|
| 1 | `completed` | `-1.229119191657453` |
| 2 | `completed` | `-2.3141293095046374` |
| 3 | `completed` | `-2.030707698335928` |

**Functional criteria** — chain exited 0; **zero** `Loop Error`, **zero**
tracebacks; real candidates `v5 → v6 → v7`; real training (`Epoch 0`,
validation on 10,000 ML segments); real inference; real scoring, all three
finite. `task_composition_fingerprint`
`d6628a93fcb3578ca32812f39246f2b51abeecbd24d21df56856ea0ef9c56d3a` pinned
in the chain lock — byte-identical to the P1 fixture. `health_gate_enabled:
false` recorded in the lock, i.e. the declared isolation is in the
artifact, not merely in the launch command.

**C-P56-1 observed live 3 times** in production prompts
(`Reference scores: NOT LOADED — this run is COMPOSED`).

**Layer A — SATISFIED, and the cold-start structure reproduced exactly:**

```text
iter_002  source_iters [1]     count 0   <- F-P56-4's prediction, confirmed
iter_003  source_iters [1, 2]  count 5   <- the witness
```

Taken from the CONSUMER, not the sidecar log: iteration 3's proposer
AUTHORED iteration 1's exact score `-1.229119191657453` in BOTH
`inherited_components` and `falsifiable_prediction`, and referenced the
prior candidates `v5` and `v6`. Iteration 3 is a separate process; the
proposer's only channel is its typed input.

**Layer B** — `{}` in both digests. Equality recorded; **NO** non-empty
reachability claimed. Owner remains the deterministic >= 3-iteration test
plus the four severing mutations, exactly as frozen.

**Not a PASS criterion**: iteration 1 scored best. The Gate does not grade
model quality (§22.18).

#### Gate evidence transfers to the final head — the argument, as a diff

`f150a625` (Gate SHA) → final head contains **no executable production
change**:

```text
core/resume.py            6 lines  — signature typed Iterable[object] | None,
                                     its import, and a removed type: ignore.
                                     The loop body is BYTE-IDENTICAL and
                                     annotations are not runtime-enforced.
uv.lock                   2 lines  — the pillow entry only, no version churn
<child design doc>       docs
<c2 tripwire test>       test      — the recorded branch-ish number 136 -> 132
```

Per the standing rule this preserves the Gate result: nothing in that delta
can affect a Gate-owned lifecycle / composition / persistence / restore
execution path. **Gate 2 is CLOSED** and must not be rerun unless
production semantics change again.

**Why the tripwire number moved DOWN.** Extracting the union rule removed
the `For` + `If` + two `BoolOp` nodes the inline dedup had cost, so
`run_workflow` is four branch nodes SIMPLER than when the design was
frozen (136 → 132). The test failed on the stale expectation, which is the
tripwire working; both the number and its justification were corrected,
because the old comment defended a design the review improved on.
