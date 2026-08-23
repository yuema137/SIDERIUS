# PR-12bc — Generic Task Boundary Closure (PHASE B: CAP-SCOPE · PHASE C: external loading / identity / lifecycle)

## A. Status, authority, source anchors

> ### COMPLETE / MERGED — 2026-08-23
>
> **PR #249, squash `42d79b9d`.** Operator verdict: *CODE / GATE REVIEW PASS,
> merge approved conditional on the terminal CI succeeding at the exact final
> head.* All five closeout conditions were mechanically verified before the
> merge, and landed master is **byte-identical** to the validated head.
>
> | terminal fact | value |
> |---|---|
> | final EXECUTABLE head | **`486ea47f`** (F-12bc-10's narrowing) |
> | final PR head | **`06103e9a`** — delta from the executable head is **docs only**, 1 file, +27/−2 |
> | authoritative exact-head CI | **`32657760919` SUCCESS** on `06103e9a` |
> | commits after that CI | **none** |
> | `G-12bc-B` | **PASS** `8fd80cdc`, **re-run PASS** `486ea47f` |
> | `G-12bc-C` | **PASS** `2ad868e3`, **re-run PASS** `486ea47f` |
> | §G plant matrix | **9/9 RED** against named owners |
>
> The frozen 17-block spine is discharged: **B0–B8 · B-GATE · §F · C0–C4 ·
> C-GATE · BC-FINAL**.
>
> **Two PRODUCTION defects were found by real Gates, not by 11,000 unit
> tests**: the pairing gap (Phase B's headline) and **F-12bc-7**, in which the
> "parent-pinned identity" turned out to be a re-read that followed the very
> edit it exists to catch. A third, **F-12bc-10**, was found by CI's pyright —
> three sites reaching for optional-sibling methods off the base
> `TaskDataPath`, which is the frozen architecture the type system was
> enforcing.
>
> **TWO census defects** — **F-12bc-6** (a flip detector that named a symbol
> and never fired) and **F-12bc-9** (a census whose FILE SET omitted
> `execute_tools/`, where the scope ABI lives).
>
> **`F-12bc-8` is NOT a census defect** (operator wording correction). It is a
> **test-isolation / import-registration lifetime** defect: a built-in imported
> inside a test whose fixture had blanked the registry registers into the
> temporary dict and never registers again. It surfaced in the regression suite
> **after** CASE A had already been closed independently by C1's production
> lifecycle mechanism, and was never a means of closing it.
>
> See §Q.C-GATE, §Q.C4, §Q.BC-FINAL and §Q.CI.

**REVISION 2 — FROZEN. OPERATOR APPROVED 2026-08-23.
IMPLEMENTED 2026-08-23 in a fresh implementation session, from this frozen
design.**

PR-12a **MERGED** 2026-08-23 (PR #248, squash `15554174`; master
`3f45c450`). The §O post-merge delta audit is **DISCHARGED**: the landed
delta against snapshot V2 is one comment-only line, all eight provisional
assumptions are **CONFIRMED**, and every anchor here is **landed-master
truth**.

Revision history: rev 1 provisional draft (planning worktree, snapshot V1
`a401427b`) → bounded refresh to V2 `99cb7853` → re-anchor on landed master
+ §O discharge → operator review 2026-08-23, verdict **APPROVE WITH TARGETED
AMENDMENTS** (architecture approved, no PR split, no new audit) → **rev 2
applies all rulings and freezes**.

**Rulings applied in rev 2:** Q-12-4/D-BC-2 ratified with the
evidence-derived-field-set and one-internal-authority amendments (§D.3,
§D.3a) · D-BC-3 ratified with reworded ownership (§E.3) · D-BC-7 ratified
and closed · D-BC-10 closed — Phase C owns the CASE-A reproducer (§A.5) ·
**§M realigned with §L** so ordinary source surprises are decided
autonomously and recorded, never escalated · **both real Gates
pre-authorized** within their frozen envelopes · the uncontended-GPU
requirement removed · §N terminal discipline held strict (12a's exception
does not propagate). **Open operator questions: 0.**

| field | value |
|---|---|
| parent authority | `../step_12_external_extensibility_graduation.md` — §11.2 (topology amendment T5), §11.3 (B→C internal checkpoint), §14 + §14a (Gate economy), §5.5 (CAP-SCOPE frozen rulings), §7 (child-integrity invariant), §8 (lifecycle), §20a (post-12a-merge reconciliation) |
| worktree | `/home/yuema137/SIDERIUS` (main checkout, now on the 12bc branch). During PR-12a's implementation this design was drafted in an **isolated** planning worktree that never wrote to the 12a lane; that worktree's role ended when 12a merged |
| branch / base | **`step12-pr12bc-generic-task-boundary-closure`**, based on landed `origin/master` = **`3f45c450`** (PR-12a merged) |
| landed-source anchors | all `file:line` anchors below are **landed master** truth. They were written against `e4cd5c18` and are **unchanged by the 12a merge** for every file this PR touches — verified: 12a's production diff never touched `core/sandbox_executor.py`, the three children, `dataset_config.py` or `task_data_path.py`. Anchors inside files 12a DID change carry a `[12a→landed]` note where the line moved |
| PR-12a final anchors | squash **`15554174`** · final executable head **`ec30bd65`** · final PR head **`d4bf899d`** · exact-head CI **32615196536 SUCCESS** · post-merge sync `3f45c450`. **G-12a-1 PASS · G-12a-2 PASS** (attempt 4 canonical) |
| snapshot history | V1 `a401427b` → V2 `99cb7853` → **LANDED `15554174`**. V2→landed production delta: **1 file, 1 comment-only line** (§A.3a) |
| PR-doc standard | the operator's 8-section per-commit checklist standard; every box starts `[ ]` and flips to `[x]` only with recorded evidence; the pre-commit checkpoint RECORDS diff summary, staged files, tests and deviations into the live ledger and then commits autonomously (§M) |
| Gates | **TWO lightweight real Gates**, independently justified: `G-12bc-B` (§H) and `G-12bc-C` (§I). Neither may be dropped, merged, deferred to 12d, or replaced by deterministic evidence (parent §14 anti-collapse rule) |
| open operator questions | **0** — Q-12-4/D-BC-2, D-BC-3, D-BC-7 and D-BC-10 are all ruled (§A.4). D-BC-1/4/5/6/8/9 remain implementation-time Decision-Ledger items, **autonomous** inside the frozen contracts |
| Gate authorization | **STANDING — both Gates pre-authorized** within their §H/§I envelopes; no per-Gate approval, no per-commit approval (§M) |

### A.1 Why this PR exists in this shape

Step 11 froze the split that defines this PR (`step_11_execution_infrastructure.md:287-289`):

```text
CAP-SCOPE   "how do I BUILD a correct scope for an arbitrary task?"   -> deferred (HERE, Phase B)
Step 11     "if a resolved scope is HANDED to me, can the boundary
             transport / reconstruct / consume it?"                   -> done
```

and the parent's §11.2 then removed the 12b|12c PR boundary because both
phases touch the same generic task boundary and adjacent child surfaces, and
**PR-12d depends on both**. The semantic boundary is intact: two phases, two
evidence sets, two real Gates, one hard internal checkpoint (§F).

### A.2 The load-bearing source facts this design is built on

Verified at `e4cd5c18` by three parallel read-only audits, each claim
re-checked by the design author.

**The structural pairing gap — the precise Phase-B failure mode.** A composed
run can already transport `--task_data_path_id`
(`core/sandbox_executor.py:852-875` → `execute_tools/task_data_path.py:364-371`),
so the child resolves e.g. `PetsTaskDataPath`
(`train_engine_sandbox.py:1988-1994`). But `main()` passes **no scope**
(`train_engine_sandbox.py:1994-2012`), so the child falls into the regime-A
branch and builds a **`TidmadScope`** (`:1125`, and `:1246` for eval). That
scope then reaches `PetsTaskDataPath._scope()` and raises
`TypeError` (`pets_data_path.py:190-197`). **The binding transport and the
scope transport are structurally unpaired.**

| fact | anchor |
|---|---|
| `run_experiment_streaming` ALREADY accepts `task_scope`, `task_eval_scope`, `validation_requested_rows` | `train_engine_sandbox.py:1002-1004` (+ docstrings `:1072-1095`) |
| …and already has cross-leg refusals for inconsistent combinations | `:1202-1218` |
| `main()` has **no** scope argv of any kind; full flag list | `:1752-1872` |
| …and never passes the three params | `:1994-2012` |
| the only production scope constructions are 2 regime-A child fallbacks, 1 in-process measurement site, 3 harness sites | `:1125`, `:1246`; `agent/skills/evaluate_time_skill/wrapper.py:379`; `scripts/run_{pets,davis}_gate2.py` |
| the tuner builds TIDMAD `SampleSet`s for BOTH trial and formal (both pass `is_trial=True`; formal differs only in values) | `nodes/ml_hyperparameter_tune_agent/planning.py:397-414`, resolved upstream at `policy.py:1140-1187` |
| **F-12bc-1 (NEW)** — `validate_sample_set` takes **no profile** and validates against the TIDMAD module constants (`TIDMAD`, `NUM_FILES`, `SEGMENTS_PER_FILE`), so every parent-side boundary check uses TIDMAD's 20×200 grid whatever the bound task is | `execute_tools/scoring_utils.py:278-335` (`:309`, `:317`, `:328`); called `core/sandbox_executor.py:1518`, `:1530`, `:1872` |
| satellite (f) is worse than "peek paths": `_target_fn` hardcodes BOTH the import-time TIDMAD root AND an inline `abra_validation_{i:04d}.h5` literal, bypassing `validation_file_name` | `nodes/ml_hyperparameter_tune_agent/execution.py:1054-1055` (root const imported `:42`) |
| satellite (e): trial mode demands `segment_anchors.json` under `sandbox.dirs["data"]`, which is now the COMPOSED physical root — so a composed non-TIDMAD trial run raises | `ml_hyperparameter_tune_agent.py:833-844` **[re-anchored at B0 — D-BC-11; was `:794-805` at `e4cd5c18`, moved by PR-12a's +62 lines in this file]**; root `core/sandbox_executor.py:1205` |
| **F-12-3 is locked in by an existing test** — `_compose_task_data_path`'s early return discards the freshly-loaded object and returns the previously-registered one **while still reporting the NEW content digest** into the fingerprint; a test asserts exactly this | `workflows/task_composition.py:570-571` (landed; was `:546` pre-12a); `tests/unit/workflows/test_step10_p1_c1_composition.py:209-225` |
| **F-12bc-2 (NEW)** — `_load_symbol` has **no registration rollback**: a plugin that self-registers a data path and then raises leaves `_REGISTRY` dirty. The health loader does roll back | `workflows/task_composition.py:487-496` vs `execute_tools/health_checks/_plugin_binding.py:302-351` (rollback `:333-341`) |
| `_REGISTRY` has **no removal path anywhere** — one write site, duplicate refusal, no `unregister`, no conftest fixture | `execute_tools/task_data_path.py:219`, `:246-252` |
| the health run-scope ledger is **refuse-or-idempotent, never re-scope**; `reset_run_scope` is documented test-only with **zero production callers**; today's production isolation is the **process boundary** (one `run_one_iteration.py` per iteration) | `_plugin_binding.py:384-398`, `:590-601` |
| out-of-tree ids fail closed in every child because the child registry holds only the three built-in imports | `train_engine_sandbox.py:31-32`, `inference_single.py:26-27`, `denoising_score_single.py:186-188`; refusal text `task_data_path.py:296-300` |
| `--task_manifest` reaches **only** the scoring child | emitter `core/sandbox_executor.py:902-916`, `:2155`; parsed `denoising_score_single.py:107-117` |
| children resolve the data path inconsistently: train **binds** the ContextVar but only in the multi-file branch; inference and scoring resolve to a **local** and never bind | `train_engine_sandbox.py:1988-1994` (guard `:1981`); `inference_single.py:396-400`; `denoising_score_single.py:267-277` |
| the child-bootstrap census pins the import set EXACTLY to the three built-ins — a child-side loader will trip it | `tests/unit/guardrails/test_task_data_path_census.py:194-242` |
| every Python-child spawner already passes `env=subprocess_env(...)`; script paths absolute; `cwd=os.getcwd()` deliberately preserved | `core/sandbox_executor.py:1007`, `:1045`, `:2171`, `:292-300`; `core/subprocess_env.py:46-81` |
| parent→child artifact convention: `dirs["configs"]/<name>_{exp_id}.json`, bare `json.dump` (**bytes are contract**), optional `cmd.extend([...])` emitted only when bound | `core/sandbox_executor.py:1199-1206`, `:1512-1536`; byte pin `tests/unit/execute_tools/test_step02b_b1_sampleset_roundtrip.py` |
| atomic tmp+rename is the convention for workspace-immutable / concurrently-read artifacts | `execute_tools/health_checks/config.py:674-682`; `core/runtime_control/session.py:811-820` |

### A.3a V1 → V2 delta classification (bounded refresh, 2026-08-23)

`git log a401427b..99cb7853` = **2 commits**; production diff = **3 files**.

| change | classification | why |
|---|---|---|
| `ec30bd65` **F-12a-G2** — `batch_resolver.py` no longer raises `BatchSearchTimeout` on a **completed** candidate probe (it prints `SLOW PROBE (accepted)`); `ProbeBudgets.single_candidate_seconds` 120.0 → 200.0 with recorded provenance; `batch_search_seconds` untouched at 600 | **PARENT_VALIDATION_RELEVANT** — *not* BC-relevant | Confined to `agent/skills/evaluate_vram_skill/`. It touches no scope construction/transport, no child loading/identity, no `DatasetProfile`, no `TaskDataPath`, no manifest or fingerprint. Its 12bc consequence is **Gate operability only**: any 12bc real witness routed through the VRAM pre-flight is now less likely to be derailed by host load (measured live: `InconclusivePreflight ×4 → ×0`). **Resource calibration is NOT pulled into 12bc** — source does not make it load-bearing for either phase |
| `99cb7853` — `scripts/step12_pr12a_gate2_evaluate.py` (NEW, acceptance evaluator written before the verdict) + its test + the 12a ledger §8.20/§8.21 | **PARENT_VALIDATION_RELEVANT** | 12a-owned Gate machinery. Its value to 12bc is the recorded Gate-operability knowledge below, not any contract |
| everything else | **UNRELATED** | no other production file changed |

**BC_RELEVANT changes in the V1→V2 delta: ZERO.** Every Phase-B and Phase-C
anchor in §A.2 is landed-master truth and is unaffected.

**V2 → LANDED delta (the §O audit, executed 2026-08-23): ONE file, ONE
line.** `git diff 99cb7853 15554174` over production paths yields only
`agent/skills/evaluate_vram_skill/probe_budgets.py`, a **comment-only**
generalization of a model name inside the `single_candidate_seconds`
provenance note. **Zero executable change. Zero BC-relevant change.** The
provisional planning posture is therefore fully discharged: this design's
anchors were landed-master truth throughout.

**Two Gate-operability facts this refresh imports into 12bc planning
(§H/§I), neither of which changes architecture:**

* **Q-07c-6 is live and will meet 12bc's Phase-B witness.** Admission prices
  `phase="training"` only, so 07a's validation pass — which runs *inside* the
  training subprocess — is unpriced; with `--runtime_watchdog` ON, a real
  training child can be killed at a deadline it was never priced for
  (observed: 119.365 s vs 118.749 s). Step-11's Gate 2 run 1 hit the identical
  signature. It is **pre-existing, OPEN, and owned by neither 12a nor 12bc**.
  Consequence for this PR: **`G-12bc-B`'s readiness packet MUST state its
  watchdog posture explicitly** — `--runtime_watchdog` is `action="store_true"`
  with "Default off", so *not* opting in is the default production posture,
  and isolating it is a Gate-isolation control rather than a semantic
  weakening (the operator accepted exactly this for 12a attempt 3, on a
  four-condition source audit; precedent: Step 09.5a's Health isolation).
* **F-12a-G2b — recorded, not repaired**: the usable VRAM cap is derived from
  **total** rather than currently-free memory, so it over-promises on a shared
  GPU. Not the cause of any 12a attempt so far. 12bc inherits it only as a
  named debt. It imposes **no** scheduling requirement on 12bc's Gates: a
  shared GPU is not a failure, and no Gate waits for exclusivity (§H).

### A.3 PROVISIONAL_12A_ASSUMPTIONS (resolved by §O / parent §20a)

**The decisive reconciliation result is that this list is SHORT**, because
PR-12a touched **no** child-process or scope-adjacent file. Verified empty
diffs `e4cd5c18..step12-pr12a-composed-path-closure` for:
`core/sandbox_executor.py` · `execute_tools/train_engine_sandbox.py` ·
`execute_tools/inference_single.py` · `execute_tools/denoising_score_single.py` ·
`execute_tools/dataset_config.py` · `execute_tools/task_data_path.py`.
Every §A.2 anchor is therefore **landed-master truth**, not provisional.

| id | assumption | snapshot evidence | post-merge falsifier |
|---|---|---|---|
| **P12A-1** | a typed composition projection `TaskCompositionRef` exists on the tuner input with fields `semantic_fingerprint`, `task_data_path_id`, `task_health_binding` (all required), carried as `task_composition_ref: TaskCompositionRef \| None = None` | `[12a] agent/schemas/hyperparam_tuning.py:1283`, `:2488`; producer `workflows/model_exploration.py:931`, `:2843` | field exists with that name and those three fields; if renamed/reshaped, Phase B's tuner acquisition (B5) reads the new shape — **non-material** unless the projection is removed |
| **P12A-2** | the manifest key set gained `proposal_blocks` + `implementor_blocks`, and the fingerprint payload gained two **conditional** keys | `[12a] workflows/task_composition.py:102-103`, `:997-1004` | new keys present; Phase B/C add their own keys with the SAME conditional idiom so undeclared manifests keep byte-stable fingerprints — **non-material** by construction |
| **P12A-3** | `_add_plugin_to_registries` is deleted; `register_model_in_memory` is the single registration authority; `core/resume.py` imports it | `[12a] model_exploration.py:1244`, `core/resume.py:78`, `:1511` | Phase C's overlay must wrap the surviving authority; if 12a's consolidation changed shape, C1 re-targets — **non-material** |
| **P12A-4** | `_compose_task_data_path` and `bind_run_task_composition` are **UNCHANGED** by 12a — so F-12-3 and the binder shape are exactly as §A.2 describes | `[12a]` no diff hunk touches `task_composition.py:522` or `:1333` | **MATERIAL if false**: Phase C's F-12-3 closure and the overlay attach here |
| **P12A-5** | metric ids are fully opaque after 12a (`_is_loss_shaped`/`_reject_loss_shaped` removed) | `[12a] execute_tools/evaluation_metric.py:119` | affects only the fourth task's metric id (12e), not this PR — **informational** |
| **P12A-6** | `resolve_tuner_health_config_source` exists and a composed run hands the tuner the chain-materialized effective config | `[12a] workflows/model_exploration.py:1039`, `:2089` | Phase B's satellite (f) work must not re-introduce a second health-config source — **non-material** |
| **P12A-7** | `agent/prompt_templates/_task_blocks_loader.py` exists as a generic fail-closed YAML→typed-blocks loader | `[12a]` new file | Phase B MAY reuse it for a task-owned declaration if one is needed; not depended on — **informational** |
| **P12A-8** | **`OUTPUT_TYPE_VOCABULARY` has no production consumer on 12a** (defined + tested only); the live `"hybrid"` branch is still a literal | `[12a] ml_models/plugin_loader.py:64`; `execute_tools/inference_single.py:319` | a latent 12a finding recorded here so it is not lost; **not this PR's to fix** — record in the parent debt ledger at reconciliation |

#### A.3b Refresh verdicts against snapshot V2 `99cb7853` (2026-08-23)

**Method:** the V1→V2 production delta touches exactly three files
(§A.3a), and **none of them is a file any assumption below depends on**.
Each row was therefore re-verified directly against `99cb7853` source, not
inferred from the diff being small.

| id | verdict at V2 | note |
|---|---|---|
| P12A-1 `TaskCompositionRef` (3 required fields, `task_composition_ref` on the tuner input) | **CONFIRMED_BY_LATEST_12A** | `agent/schemas/hyperparam_tuning.py` untouched in the delta |
| P12A-2 manifest keys + conditional fingerprint keys | **CONFIRMED_BY_LATEST_12A**, count corrected | `_MANIFEST_KEYS` at V2 is **10 keys**: `task_data_path · dataset_profile · metric · secondary_metrics · task_health · interpretation_blocks · proposal_blocks · implementor_blocks · task_config · deliverable`. Both new sections join the fingerprint **only when declared** — the conditional idiom Phase B/C must copy |
| P12A-3 `register_model_in_memory` is the single registration authority | **CONFIRMED_BY_LATEST_12A** | untouched |
| **P12A-4** `_compose_task_data_path` + `bind_run_task_composition` unchanged by 12a (**MATERIAL-if-false**) | **CONFIRMED_BY_LATEST_12A — line anchor updated** | the early-return branch still exists, now at `workflows/task_composition.py:570` (landed) (master `:546-547`); it moved only because additive sections were inserted above it. **F-12-3 is still live and still Phase C's to close** |
| P12A-5 metric ids fully opaque | **CONFIRMED_BY_LATEST_12A** | untouched; informational for 12e |
| P12A-6 `resolve_tuner_health_config_source` | **CONFIRMED_BY_LATEST_12A** | untouched |
| P12A-7 `_task_blocks_loader.py` generic loader | **CONFIRMED_BY_LATEST_12A**, count corrected | `ProposalTaskBlocks` carries **10** optional `str \| None` fields at V2 (the V1 note said 9) and `ImplementorTaskBlocks` **2**. Both families were already at this shape in V1 — the reported "expansion after a real dry-render" landed **before** `a401427b` and was already captured |
| P12A-8 `OUTPUT_TYPE_VOCABULARY` unconsumed | **CONFIRMED_BY_LATEST_12A** | untouched; stays a parent-debt-ledger item |

**POST-MERGE STATUS (2026-08-23): all eight are CONFIRMED against LANDED
source.** PR-12a merged as squash `15554174`; the V2→landed production
delta is one comment-only line (§A.3a), which touches no file any
assumption depends on. Each row above was additionally re-checked against
the landed tree. **`PROVISIONAL_12A_ASSUMPTION` is now a closed category
for this PR** — §O is discharged, and no assumption remains provisional.

**P12A-4, the single MATERIAL-if-false item, HOLDS on landed master**:
`_compose_task_data_path`'s early-return branch and
`bind_run_task_composition` are unchanged by the merge, so **F-12-3 is live
on master and remains Phase C's to close**.

**Answering the refresh directive's items A and B directly:**

* **A — task-block surfaces.** `ProposalTaskBlocks` / `ImplementorTaskBlocks`
  are **outside 12bc ownership**. They are *prompt-rendering* declarations:
  optional manifest sections, default-`None`, consumed by the proposer and
  implementor nodes in the **parent** process. They add no child bootstrap
  requirement (no child parses them), no scope semantics, and no new loading
  mechanism — they reuse the same optional-section shape
  `interpretation_blocks` already had. Their only 12bc-visible consequence is
  the one in B below. A future **external task package** may declare them like
  any other optional section; that costs 12bc nothing, because Phase C
  transports the *manifest*, not any particular section.
* **B — composition fingerprint.** Confirmed: the TIDMAD composed fingerprint
  **moved** when the shipped manifest declared the two new sections, because
  both join the payload when present. The 12bc invariant is therefore stated
  **structurally, never as a literal**: Phase C's parent-pinned identity must
  bind the *current* composition/manifest semantic identity, whatever its
  value. **Swept and verified**: this design contains **no** hard-coded
  fingerprint, and the single hex digest anywhere in the planning documents —
  `d6628a93fcb3578c` at parent §0.1-A — is a **historical Step-11 Gate-2
  evidence record** of a past run, correctly frozen, not a 12bc invariant or
  example. Nothing here went stale when TIDMAD's composed fingerprint moved,
  and **no commit in this PR may introduce a literal digest as a contract**.

### A.4 Decisions requiring operator ratification before freeze

**ALL RATIFIED — operator review, 2026-08-23. Open operator questions: 0.**

| decision | ruling |
|---|---|
| **Q-12-4 / D-BC-2** | **APPROVED WITH AMENDMENT.** The `generic identity + opaque task-owned topology` decomposition is ratified. Two amendments: (i) the generic field set is **evidence-derived by B2's consumer audit**, never doctrine — a field enters generic identity only when the audit proves framework infrastructure reasons about it with the *same semantics across materially different tasks*; a rename is not sufficient; (ii) **one internal semantic authority** — the internal `model_dump()` byte-parity requirement is WITHDRAWN, and legacy byte compatibility lives at the observable transport/persistence boundary via a bounded projection (§D.3, §D.3a) |
| **D-BC-3** | **RATIFIED WITH REWORDING.** Run-scoped lifecycle semantics apply *wherever multiple run scopes share an interpreter*; current production obtains equivalent post-run isolation structurally through process teardown; tests/tooling/future in-process orchestration exercise the overlay directly. Neither "production does this today" nor "test-only" is an accurate description. Concurrent in-process runs: **out of scope, fail closed** (§E.3) |
| **D-BC-7** | **RATIFIED / CLOSED.** Atomic scope-artifact write (canonical bytes → digest → tmp → rename). The non-atomic `--sample_set_json` sibling is precedent for **byte stability, not for write atomicity**; the difference is deliberate and recorded. The artifact is parent-produced and child-read with identity carried by digest, so atomicity is the correct posture. No longer an open question |
| **D-BC-10** | **CLOSED BY OPERATOR RULING** — Phase C explicitly owns closing the CASE-A reproducer through production registry-lifecycle semantics (§A.5) |

Remaining Decision-Ledger items (**D-BC-1, D-BC-4, D-BC-5, D-BC-6, D-BC-8,
D-BC-9**) are implementation-time and **autonomous** inside these frozen
contracts (§L).

1. **Q-12-4 concrete contract (§D.3)** — the parent froze the *principle*
   ("no built-in topology union/catalog; task-specific physical topology is
   task-owned/opaque/extensible"). The concrete `DatasetProfile` contract
   proposed in §D.3 is **NOT yet ratified**.
2. **D-BC-3 — the sequential-heterogeneous-runs scope** (§E.3). Source proves
   production isolation today IS the process boundary, and the health
   precedent *cannot* re-scope. This design proposes building the overlay for
   the **composition** registry while scoping the "next run, different roster
   succeeds" requirement honestly to in-process test/tooling contexts. That
   narrows a parent §8/§17-G expectation and needs an explicit ruling.
3. **D-BC-7 — scope-artifact atomicity vs the byte-contract precedent**
   (§D.4): the parent's §5.5 freezes "ATOMIC write"; the nearest existing
   parent→child precedent (`--sample_set_json`) is a bare non-atomic
   `json.dump` whose **bytes are contract**. This design follows the frozen
   ruling (atomic tmp+rename) and keeps canonical bytes — recorded so the
   deviation from the sibling precedent is deliberate and visible.

### A.5 New-finding refresh against snapshot V2

Each source-derived finding re-checked at `99cb7853`. **All five are
unchanged in mechanism, ownership and proposed fix**; the delta touches none
of their files, so their **master `e4cd5c18` anchors remain exact**.

| finding | verdict at V2 | anchor status |
|---|---|---|
| **F-12bc-1** — `validate_sample_set` takes no profile and validates against the TIDMAD module constants, so every parent-side boundary check uses TIDMAD's 20×200 grid | **UNCHANGED — still open, still Phase B's** | `execute_tools/scoring_utils.py:278-335` (master) exact; call sites `core/sandbox_executor.py:1518`, `:1530`, `:1872` exact (that file is untouched by 12a) |
| **F-12bc-2** — `_load_symbol` has no registration rollback; the health loader does | **UNCHANGED — still open, still Phase C's** | master `workflows/task_composition.py:487-496` exact; on the 12a branch the function has shifted downward with the additive sections, which matters only after merge (§O step 7) |
| **F-12bc-3** — an existing test locks in the F-12-3 stale-instance behaviour, so closing it requires UPGRADING that test | **UNCHANGED — and re-confirmed load-bearing** | `tests/unit/workflows/test_step10_p1_c1_composition.py:209-225` (untouched); the production branch it pins is still present at `task_composition.py:570` (landed) |
| **F-12bc-4** — the child-bootstrap census pins the import set to exactly the three built-ins | **UNCHANGED** | `tests/unit/guardrails/test_task_data_path_census.py:194-242` exact |
| **pairing gap** — binding transport and scope transport are structurally unpaired (child resolves the composed impl, then the regime-A fallback hands it a `TidmadScope` → `TypeError`) | **UNCHANGED — the core Phase-B failure mode** | all four anchors are in files 12a never touched (`train_engine_sandbox.py:1125`, `:1246`, `:1988-1994`, `:1994-2012`) |

**Net effect of the refresh on §D/§E/§F/§G/§H/§I/§J/§K/§M/§P: none.** No
phase scope, checkpoint proof, Gate, structural budget or downstream
contract changed. The refresh adds one readiness-packet requirement to §H
and re-scopes §O to a delta audit.

#### F-12bc-5 (NEW, imported from PR-12a's terminal review) — "CASE A": the registry hazard is already OBSERVED, not merely predicted

PR-12a's operator-directed forensic (`pr_12a_composed_path_closure.md`
§8.11) recorded a **pre-existing, execution-order-dependent** failure in a
**restricted single-process ordering reproducer**:

```text
TaskCompositionError: task_data_path names module
'execute_tools.tidmad_data_path', which could not be imported:
TaskDataPathRegistrationError: Task data path 'tidmad' is already
registered. Currently registered: ['davis_future_prediction',
'oxford_iiit_pet', 'spectro_segmentation_v0', 'tidmad']
```

Every affected file passes in isolation and passes when
`tests/unit/workflows` is collected first: it depends on **execution
order**, not collection. Classified **CASE A** — the baseline at `e4cd5c18`
fails the identical set of 9, PR-12a did not introduce it — and carried
forward **unsolved**.

**Correction, and it is load-bearing (operator review, 2026-08-23).** An
earlier draft of this section said the failure occurred "in the full-suite
CI command". **That is wrong.** PR-12a §8.12 establishes the opposite and
made a point of it:

```text
restricted reproducer                                   -> FAILS
    pytest tests/unit/agent/tune_ml_hyperparam_agent \
           tests/unit/workflows/test_step10_p56_c5_wiring_closures.py \
           -m "not real_run" -q

formal CI-equivalent full suite                          -> DOES NOT reproduce
    pytest tests/unit/ -m "not real_run" -q
```

The full-suite ordering happens to run `tests/unit/workflows` before the
tuner suite, which is exactly the order that does not poison. CASE A is
therefore **a restricted-reproducer exposure of the monotonic process-global
registry lifecycle hazard**, never a formal-CI failure — and that
distinction must be preserved wherever this design cites it.

**Why this matters to Phase C.** It is the *observed* manifestation of the
hazard §E.3 derived from source: `_REGISTRY` grows monotonically for the
life of the interpreter, has **no removal path**
(`execute_tools/task_data_path.py:219`, `:246-252`), and refuses duplicates —
so a second composition of the same id in one process must either be masked
by the stale-instance early return (F-12-3) or raise. Phase C's
transactional run-scoped overlay is the mechanism that makes
"post-unwind, a different roster is legal" true, which is precisely what
CASE A needs.

**D-BC-10 — CLOSED BY OPERATOR RULING (2026-08-23).**

> **Phase C explicitly owns closing the CASE-A reproducer as a regression
> falsifier**, provided the closure comes from **production registry
> lifecycle semantics**, not test-specific cleanup.

PR-12a itself named this owner ("Owner: **PR-12c**, whose §8 run-scoped
registration lifecycle is the mechanism that makes duplicate registration a
non-question"), so the ruling ratifies a disposition the forensic already
reached. The acceptance shape:

```text
baseline (pre-C1 head)   restricted reproducer -> FAIL
after the C1 overlay     the SAME reproducer   -> PASS
```

**Forbidden ways to make it pass** — any of these is a failure of the
commit, not a closure: pytest ordering hacks · test-specific
unregister/reset · special-case TIDMAD cleanup · suppressing the
duplicate-registration error · weakening or narrowing the reproducer.

If the completed overlay satisfies its frozen lifecycle semantics and the
reproducer *still* fails for a genuinely **different, test-only** mechanism,
record the new evidence and disposition it — but "the symptom appears in
tests" is **not** a reason to disown it. Conversely, if it still fails for
the same registry-lifecycle reason, **Phase C has not closed its own failure
class.**

---

## B. Goal and non-goals

**Goal (parent capability statement).** A composed task owns how its
training/evaluation scopes are constructed; the framework transports those
task-owned scopes generically across the real subprocess boundary using the
frozen artifact + digest discipline; every required child can load an
out-of-tree task implementation under an identity pinned by the parent; and
the registration/binding lifecycle cannot leak or reuse stale implementation
content across runs.

**Non-goals — explicit.**

* **No Pets/DAVIS real training L4** — that is 12d. This PR's real evidence
  stops at the witnesses in §H/§I.
* **No fourth task** — that is 12e. Phase B ships an *anonymous
  fourth-shaped* capability fixture (deterministic only) to stress the
  abstraction, not a task package.
* **No second scope identity or scope registry** (parent §5.4). Scope
  identity rides the `task_data_path_id` that already crosses.
* **No amendment of the frozen four-method `TaskDataPath`** (Q-12-2 = A):
  the capability is an **optional sibling protocol**.
* **No raw scope JSON on argv** (parent §5.5, frozen).
* **No built-in topology union/catalog** — including "N optional built-in
  topology blocks", explicitly rejected.
* **No new per-family loader** where the composition authority already
  exists (parent §6.3).
* **No pack completion, no governance-pin relaxation** (12d).
* **Legacy / un-composed behaviour stays byte-identical**, read through
  R-11-13's parity wording; the SampleSet byte contract is preserved exactly.
* No change to the frozen TIDMAD score formula, metric semantics, or the
  Step-06 evaluation contract.

---

## C. Parent capability ownership

| capability | owner | this PR |
|---|---|---|
| G1 composed-path closure (values + prompt science) | 12a | consumed, not re-opened |
| **G2 task-owned scope construction + transport + rehydration** | **PR-12bc PHASE B** | **owned** |
| **G3 child external loading + parent-pinned identity + leak-free lifecycle** | **PR-12bc PHASE C** | **owned** |
| G4 Pets/DAVIS real subprocess contrast | 12d | enabled, not proven |
| G5 fourth-task zero-core-edit graduation | 12e | enabled, not proven |
| G6 resume / fingerprint | 12a (composed lock chain) · **12bc Phase C** (external-plugin content identity: pinned parent-side, verified child-side, refused on divergence) · 12e (external restore) | **partial** |

---

## D. PHASE B — CAP-SCOPE

### D.1 The capability (parent §5.5, frozen shape)

An **optional sibling protocol** hanging off the implementation that already
crosses. Nothing here amends `TaskDataPath`'s four methods.

```text
TaskScopeCapability  (optional; an implementation MAY declare it)

    build_training_scope(request: ScopeBuildRequest) -> object
    build_eval_scope(request: ScopeBuildRequest)     -> object
    serialize_scope(scope: object)   -> str      # task-owned shape
    deserialize_scope(payload: str)  -> object   # fail-closed
```

`ScopeBuildRequest` is a frozen framework carrier of **framework-level
selection knobs only** — round kind (trial/formal), sampling portion, seed,
max-samples ceiling, and an OPAQUE operator subset ref. It mirrors
`EpochSamplingParams`' discipline (`execute_tools/task_data_path.py:99-104`:
"Task-vocabulary values … are deliberately ABSENT"). Its exact field set is
finalized by B1's audit against `policy.py:1140-1187`, which is where trial
and formal already differ today.

**Capability absence fails closed at composition time**, never at first
spawn — one new row on the existing truth table discipline
(`task_data_path.py:275-301`).

**Task-instance configuration.** An implementation that needs its own
sources to build scopes (Pets manifests, DAVIS clip caps) receives them at
CONSTRUCTION, via an optional task-owned `config:` mapping in the manifest's
`task_data_path` section, passed to the factory. The task's own plugin
reading the task's own files is never a framework `examples/` import, so the
governance census (`tests/unit/examples/test_pack_governance.py:211-221`)
stays green.

### D.2 Transport — artifact + digest (frozen; NOT argv JSON)

```text
parent:  build scope -> serialize_scope -> canonical bytes -> sha256 = scope_digest
         -> ATOMIC write to a run-scoped scope artifact
argv:    --task_scope_ref <path>  --task_scope_digest <sha256>
         (+ the eval pair; additive, composed-only — the _task_data_path_argv
          precedent at core/sandbox_executor.py:852-875, so legacy argv is
          byte-identical per R-11-1/R-11-13)
child:   read artifact -> recompute digest -> MISMATCH refuses closed
         -> resolve impl by the id that ALREADY crosses
         -> deserialize_scope -> pass task_scope=/task_eval_scope= into
            run_experiment_streaming (params that have existed since D14 and
            have never been argv-fed: train_engine_sandbox.py:1002-1004)
```

**Attempt-scope identity is first-class.** The composition fingerprint is
task-level STATIC identity; the scope varies per attempt. B4 defines ONE
evidence authority for `scope payload → canonical bytes → scope_digest →
transport → child check → evidence stamp`, so Gate and adversarial evidence
can cite WHICH scope a child executed instead of inferring it. An additive
record/evidence stamp is acceptable; no persisted-global-schema change is
required.

**Placement.** The artifact goes to the run-scoped `dirs["configs"]` area
(`core/sandbox_executor.py:1199-1206`), named per the existing
`<name>_{exp_id}.json` convention. Writing is **atomic (tmp+rename)** per the
frozen ruling — see D-BC-7 in §A.4.

### D.3 Q-12-4 — the concrete `DatasetProfile` topology contract (PROPOSED, not ratified)

**The problem, measured.** `DatasetConfig` (`dataset_config.py:39-61`) is six
fields of which four are TIDMAD-physical (`psd_segment_length`,
`segments_per_file`, `sampling_frequency`, and the two `abra_*.h5`
patterns); `ChannelIdentity` (`:338-357`) is h5-channel-physical. Pets and
DAVIS composition fixtures **fabricate** these values and say so. The
consumer census is large (§A.2 audit): `num_files` alone has ~25 production
consumers.

**The RATIFIED architecture** (operator ruling, 2026-08-23):

```text
DatasetProfile  =  MINIMAL FRAMEWORK-GENERIC IDENTITY
                +  OPAQUE TASK-OWNED TOPOLOGY
```

The framework **never branches on, and never inspects,** the task-owned
topology payload. **Not** "N optional built-in topology blocks" — that is a
central catalog with extra steps and is explicitly rejected.

**The membership rule is frozen; the field list is NOT.** The operator
deliberately did **not** ratify any particular field as generic vocabulary:

> A field belongs in GENERIC IDENTITY only when **B2's consumer audit proves
> that framework infrastructure itself needs to reason about the fact with
> the SAME semantics across materially different tasks.** Renaming a
> task-specific fact into generic language is **not** sufficient.

So the candidates below are **hypotheses for B2 to test, not doctrine**:

| candidate | expectation, to be settled by the audit |
|---|---|
| partition count (today's `num_files`) | **likely generic** — `DataScope` indexes exactly that domain (`dataset_config.py:184-311`) — but still pinned by the audit, not assumed |
| value encoding / class cardinality | retain **only** if the audit proves a genuine cross-task framework consumer; otherwise route to task topology or to an already-owning typed contract (e.g. `ModelIOContract`) |
| channel roles | same test; "role, not h5 dataset name" is a *rename*, and a rename alone does not earn generic status |

Everything not proven generic — PSD segment length, segments-per-file,
sampling frequency, file-name patterns, h5 channel names — is task-owned
opaque payload. **The B2 disposition table determines the MINIMAL generic
field set inside this ratified architecture**; choosing that set is ordinary
implementation discretion and is **not** an operator stop. Only a proof that
the decomposition *itself* cannot satisfy the consumers without core task
dispatch is a material stop.

**Why the list is not frozen:** a generic-sounding field admitted without
consumer evidence is how `DatasetProfile` would quietly regrow into a science
catalog a few years from now — the exact outcome this contract exists to
prevent.

#### D.3a ONE internal semantic authority (operator amendment — supersedes internal byte-parity)

Rev-2 required `TIDMAD_PROFILE.model_dump(mode="json")` to stay
byte-identical. **That requirement is WITHDRAWN**, because satisfying it
while splitting the schema would force the old TIDMAD physical fields to
survive alongside the new opaque topology — **two live authorities**, which
is precisely the defect being removed.

```text
INTERNAL domain model     exactly ONE semantic authority:
                          generic identity + opaque task topology

LEGACY observable         byte contract preserved AT THE TRANSPORT /
compatibility             PERSISTENCE BOUNDARY where R-11-13 requires it,
                          via a bounded compatibility projection if needed
```

If exact legacy `--dataset_profile_json` bytes are required, a bounded
compatibility serializer/projection produces them **at the boundary**. What
must not happen is retaining duplicate live physical fields merely so an
internal `model_dump()` looks unchanged. No second configuration hierarchy
is created either way.

The Pets/DAVIS fabricated topology values are then deletable rather than
blessed — their deletion lands with 12d's pack work, not here.

**Migration discipline.** The ~25 `num_files` consumers and the
`psd_segment_length` / pattern consumers are migrated by ownership, not by
sweep: a consumer that legitimately reasons about partitions reads the
generic identity; a consumer that is genuinely TIDMAD-physical moves behind
the task's own code or is left on the legacy path. **B2's audit step
produces the per-consumer disposition table before any field moves**, and
this contract is the last item of the §F checkpoint precisely because
everything downstream depends on it.

### D.4 Phase-B scope of work

(a) capability protocol + request carrier · (b) tuner composed-path scope
acquisition replacing the unconditional `build_sample_set` on the composed
path only · (c) transport + child rehydration (train first; inference where
its own path needs it) · (d) Q-12-4 · (e) trial anchoring as a declared
optional capability (absent ⇒ trial refused for that task with a named
reason, never a crash on a TIDMAD filename) · (f) peek-path derivation from
the naming authority + composed root instead of the `_target_fn` literals ·
(g) F-12-2 measurement-scope acquisition · **F-12bc-1**: `validate_sample_set`
becomes profile-aware (or the composed path stops routing through a
TIDMAD-constant validator) · `--data_scope` refusal on composed
non-TIDMAD runs, with the opaque subset ref as the generic replacement.

---

## E. PHASE C — external child loading / identity / lifecycle

### E.1 Child-side loading (extend the idiom Step 11 established)

Step 11 established *manifest-path transport + child-side per-family
re-composition through the SAME authority* (`--task_manifest` →
`compose_metric_from_manifest`). Phase C generalizes it to the data path and
to the training/inference children:

```text
transported id -> registry lookup
                  ├─ HIT  -> verify content identity == parent-pinned identity
                  │            match    -> use it
                  │            divergent-> REFUSE (named)
                  ├─ MISS -> compose `task_data_path` from the transported
                  │           manifest via _compose_task_data_path itself
                  │           (registers + returns), then verify as above
                  └─ neither registered nor composable -> REFUSE naming BOTH facts
```

**A registry HIT is never sufficient by itself** (parent §7 frozen
invariant): even on a hit, content identity must equal the parent-pinned
identity, or a stale registration silently satisfies the lookup while
running different code.

### E.2 Parent-pinned identity (F-12-4)

> *Every child-consumed external semantic MUST be validated against an
> identity pinned by the parent before the child consumes it; a registry hit
> is never sufficient evidence of identity.* — parent §7, frozen

Mechanism choice (per-family digests vs the full composition fingerprint) is
this design's to make and is recorded as **D-BC-5** in §L; "re-read the
manifest and trust it" is not an option. This closes the bind-to-spawn edit
window: a manifest or plugin edited between bind and spawn must refuse,
never silently train under the parent's identity.

### E.3 Registration lifecycle (F-12-3, F-12bc-2) — and an honest scope

The frozen two-phase semantics (parent §8):

```text
WITHIN an active run   same canonical identity + same content -> idempotent
                       same id + DIFFERENT content            -> refuse (named)
                       different roster mid-run               -> refuse (named)
AFTER the run unwinds  the next run may register a DIFFERENT roster —
                       no permanent poisoning
```

**D-BC-3 — RATIFIED WITH REWORDING (operator, 2026-08-23).** The contract is
owned by the execution model, not by the test tier:

> **The overlay owns run-scoped lifecycle semantics wherever multiple run
> scopes share an interpreter. Current production receives equivalent
> post-run isolation through process teardown; tests, tooling and future
> in-process orchestration directly exercise the overlay's post-unwind
> roster replacement.**

Both halves matter. It is **not** claimed that production today exercises
sequential heterogeneous runs in one interpreter — it does not: isolation
comes structurally from a run/iteration process terminating. It is equally
**not** a "test-only" guarantee — it is the same guarantee, whose owner
differs by execution model.

**Concurrent in-process runs remain OUT OF SCOPE** and must **fail closed**
rather than silently interleave shared registry state.

**What source proves.** The health precedent is refuse-or-idempotent and
**cannot** re-scope: `reset_run_scope` is documented test-only with zero
production callers (`_plugin_binding.py:590-601`), and
`task_data_path._REGISTRY` has **no removal path at all** (`:219`,
`:246-252`). This design therefore:

* builds the transactional/run-scoped **visibility overlay** for the
  composition registry (so registrations made for a run become
  invisible-or-retired when the run unwinds, exactly as the ContextVar
  bindings already do);
* closes **F-12-3** by comparing CONTENT identity, not just id, in
  `_compose_task_data_path`'s early-return branch (`task_composition.py:570-571`)
  — which requires **UPGRADING** the test that currently locks the stale
  behaviour in (`test_step10_p1_c1_composition.py:209-225`), not merely
  changing production;
* closes **F-12bc-2** by giving `_load_symbol` the registration rollback the
  health loader already has (`_plugin_binding.py:333-341`);
* scopes the "next run, different roster succeeds" claim to in-process
  contexts (tests, tooling, future in-process orchestration) and states
  plainly that production isolation is the process boundary — rather than
  claiming a production capability nothing exercises.

**The health family is not mechanically copied**, and whether it migrates
onto the overlay is a Phase-C decision (allowed, not required; it must not
weaken any 08b guarantee).

### E.4 Census consequence (F-12bc-4)

`tests/unit/guardrails/test_task_data_path_census.py:194-242` pins the child
bootstrap import set EXACTLY to the three built-ins. A child-side loader
will trip it. The census is **deliberately extended** (with its plant
re-proven), never exempted by name — the Step-11 C9 rule.

---

## F. B → C HARD INTERNAL RECONCILIATION (automatic; not an operator stop)

Because T5 removes the 12b|12c merge boundary, this replaces it. Ten proofs,
all recorded in the implementation ledger before Phase C begins:

- [x] 1. Phase-B deterministic acceptance complete — every B0–B8 checkbox
      ticked with recorded evidence (§Q.B0–§Q.B8)
- [x] 2. `G-12bc-B` **PASS** at `8fd80cdc` — §Q.B-GATE.1
- [x] 3. exact Phase-B checkpoint SHA recorded — **`120ec93a`** (the Gate
      evidence commit; `8fd80cdc` is the executable head the Gate ran at,
      and the delta between them is documentation only)
- [x] 4. Phase-B structural delta PASS (§J budgets) — §Q.B8: **exactly one**
      baselined function gained any branch nodes, within budget; the tuner's
      `run()` ended SMALLER
- [x] 5. all Phase-B Decision-Ledger entries resolved and recorded — D-BC-1,
      D-BC-1a, D-BC-4, D-BC-8, D-BC-11, D-BC-13, D-BC-14, D-BC-15
- [x] 6. the concrete **Q-12-4** contract frozen and evidenced — §Q.B2, with
      the per-consumer disposition table recorded BEFORE any field moved
- [x] 7. the scope artifact/digest **ABI is stable** for the remainder of the
      PR — frozen at B4 and unchanged by B5–B8 and the Gate
- [x] 8. no unconditional TIDMAD scope construction remains on the composed
      path where Phase B owns it (census) — **now a PERMANENT census**,
      `test_step12_pr12bc_f_checkpoint.py`
- [x] 9. no hidden task/scope identity dispatch introduced (census) — **now a
      PERMANENT census**, same module
- [x] 10. **Phase-C assumptions re-audited against the ACTUAL Phase-B
      implementation**, not pre-B source — §Q.F, with re-anchored line numbers

If all ten hold, implementation continues **directly** into Phase C.

---

## G. Deterministic and adversarial evidence ownership

**CAP-SCOPE (Phase B).** valid scope roundtrip per task · wrong-task scope
payload refused (the `_scope()` `TypeError` pairing rule preserved) ·
malformed payload refused · missing artifact refused · **tampered artifact
(bytes ≠ transported digest) refused BEFORE deserialization** · capability
absent ⇒ named fail-closed at composition · **anonymous fourth-shaped scope
fixture** (non-`rows`, non-1-D, different topology — stresses the
abstraction before 12e) · **TIDMAD composed-vs-legacy deep differential**
(constructed scope ≡ legacy `build_sample_set` output for identical inputs)
· **trial AND formal construction paths** both covered (they differ only in
values today — `policy.py:1140-1187`) · un-composed argv byte-parity ·
SampleSet byte contract unchanged.

**External loading / lifecycle (Phase C).** registered + matching identity ⇒
use · registry hit + divergent identity ⇒ refuse · registry miss +
composable external manifest ⇒ load · neither ⇒ named refusal naming both
facts · parent↔child manifest/plugin edit window ⇒ refuse · non-repo cwd ⇒
resolves identically · same-run same-id/different-content ⇒ refuse ·
same-run roster mutation ⇒ refuse · post-unwind different roster ⇒ legal (in
the scope of D-BC-3) · zero ContextVar/binding leakage · plugin that
registers then raises ⇒ registry clean (F-12bc-2).

**Genericity plants — each must turn a NAMED owner RED.** task-name dispatch
· scope-kind dispatch · a central mapping table (`{"tidmad": …, "pets": …}`)
· a fourth-task import in a bootstrap list · sever the scope
writer/ref/digest hop · sever manifest transport · sever the child identity
check. Mutation hygiene per the standing rule: clear caches, assert
`count == 1`, re-run baseline.

---

## H. `G-12bc-B` — scope transport / rehydration Gate (lightweight, real)

| field | value |
|---|---|
| **FAILURE CLASS** | a task-built scope must survive the REAL subprocess boundary exactly and be consumed by the child under the correct `TaskDataPath` implementation |
| **WITNESS (§14a-derived; STOPS THERE)** | parent builds scope → atomic artifact + digest → **REAL production child spawn** → child recomputes and verifies the digest → child resolves the correct implementation → child deserializes → **the real dataset/materialization/training entry CONSUMES that scope** → evidence recorded |
| **REQUIRED REAL** | one real production child spawn; minimal real execution that genuinely consumes the scope (a one-batch training smoke if the production entry point requires it) |
| **EXPLICITLY NOT REQUIRED** | inference · scoring · a complete workflow · model quality · HealthGate PASS · score magnitude · convergence |
| **DEPTH** | one spawn cycle — the class ends at the child's scope consumption; no iteration semantics apply |
| **EVIDENCE MUST INCLUDE** | parent-built scope identity · artifact ref · scope digest · child-recomputed digest · child deserialization · **actual child consumption** |
| **est. cost** | minutes |

If the production entry point makes a fuller path unavoidable, the ledger
records **why**, with the site cited (§14a footnote 1).

**STANDING OPERATOR AUTHORIZATION (2026-08-23).** `G-12bc-B` is
**pre-authorized** within the envelope above — no second approval at the
readiness checkpoint. **Use the cheapest production-real execution
sufficient to witness scope consumption**: a tiny/one-batch execution is
preferred if the production path requires training. Do **not** expand into a
full chain merely because a Gate is nominally "Gate 2". Exceeding the frozen
envelope is a material stop.

**Resource posture (operator amendment — the earlier "prefer an uncontended
GPU" advice is REMOVED).** A shared GPU is **not** a failure, and the Gate
must never wait on exclusivity:

* use the minimal real workload; **CPU is acceptable** if the real production
  child path can validly witness scope consumption there;
* require CUDA **only** if the actual production witness requires it, and
  then inspect currently available capacity before launch;
* GPU sharing, lower throughput, or another user's allocation are **not**
  correctness failures;
* a genuine environment/resource inability is **INCONCLUSIVE**, never FAIL.

**F-12a-G2b remains named debt** — do not repair it opportunistically here
unless the Gate exposes it as the actual blocking defect.

**Re-run policy.** Same-spec rerun only for a genuine
machine/provider/infrastructure INCONCLUSIVE. A production or workload
defect is a **FAIL**: diagnose and fix the real defect, then re-run only the
invalidated Gate. **No repeated launches hoping for green.**

**Readiness-packet requirement (§A.3a).** Because this witness spawns a REAL
child, `G-12bc-B`'s readiness packet **MUST state its runtime-watchdog
posture explicitly**, with the reason:

* **Q-07c-6 is live and unowned by this PR.** Admission prices
  `phase="training"` only, so 07a's validation pass — which runs *inside* the
  training subprocess — is unpriced. With `--runtime_watchdog` ON a real
  child can be killed at a deadline it was never priced for; this signature
  killed Step-11 Gate-2 run 1 and PR-12a G-12a-2 attempt 2 (119.365 s vs
  118.749 s). Retrying cannot converge, because shrinking capacity shrinks
  the deadline.
* `--runtime_watchdog` is `action="store_true"` with **"Default off"**, so
  **not opting in IS the default production posture**; isolating it is a
  Gate-isolation control, not a semantic weakening — the operator accepted
  exactly this for 12a attempt 3 on a four-condition source audit, and Step
  09.5a set the precedent with Health isolation.
* Watchdog correctness is **not** this Gate's owned failure class (that class
  is scope transport + child consumption), and process cleanup/restart
  machinery stays active either way.
* **F-12a-G2b** (the usable VRAM cap derives from *total* rather than
  currently-free memory) is named debt only — it is explicitly **not** a
  reason to wait for an idle device; see the resource posture above.

A Gate killed by Q-07c-6 is **INCONCLUSIVE**, never FAIL, and nothing may be
tuned to make it green.

---

## I. `G-12bc-C` — external loading / integrity Gate (lightweight, real)

| field | value |
|---|---|
| **FAILURE CLASS** | the parent loads/pins an OUT-OF-TREE implementation and a REAL production child loads/verifies the same identity without relying on parent interpreter state or a stale registration |
| **WITNESS** | out-of-tree `TaskDataPath` plugin → parent composes + pins identity → **REAL child spawn through the production spawner** → child loads + verifies → **edited/tampered plugin or manifest ⇒ named refusal** |
| **REQUIRED REAL** | one spawn cycle through the production spawner |
| **EXPLICITLY NOT REQUIRED** | **no training, no GPU**, no contrast data, no scoring — unless source truth proves the witness is otherwise unobtainable, recorded with the site |
| **DEPTH** | single spawn cycle — loading/identity has no iteration semantics |
| **DISTINCTNESS** | must remain separate from `G-12bc-B`: B asks *"did the right SCOPE arrive and get consumed?"*, C asks *"did the right IMPLEMENTATION arrive, under a verified identity?"* |
| **est. cost** | minutes |

**STANDING OPERATOR AUTHORIZATION (2026-08-23).** `G-12bc-C` is
**pre-authorized** within this envelope — no second approval at the
readiness checkpoint; the same `SIDERIUS_ALLOW_LAUNCH=1`-style mechanical
marker applies (§M). **No training, no GPU, no scoring**, unless source
truth proves an element technically unavoidable — any such expansion is
recorded and evaluated against the §L material-deviation rule. The same
re-run policy as §H applies: same-spec rerun only for a genuine
infrastructure INCONCLUSIVE; a production defect is a FAIL to be diagnosed
and fixed, never re-launched hoping for green.

---

## J. Structural budgets / anti-god-object constraints

Baselines are the parent §10 table **as re-measured at `e4cd5c18`**; B0/C0
re-measure the specific files each phase touches, and the terminal commit
compares. Rules:

| surface | current | rule |
|---|---|---|
| `train_engine_sandbox.py::main()` | 86 st / 23 br / 294 LOC | scope rehydration is a **helper-module boundary**; `main()` gains a call, not a branch family |
| `run_experiment_streaming` | 175 / 58 / 728 / 19 params | **no new parameters** — the three scope params already exist (`:1002-1004`) |
| `core/sandbox_executor.py` argv builders | `execute_training` 91/38/358/14 | follow the `_task_data_path_argv()` shape: **small pure emitter functions**, splatted; no new branch family inside the builders |
| tuner `run()` / `planning.prepare_attempt` | 257/67/1085 · 116/32/471 | scope acquisition is a NEW typed boundary CALLED from planning — never inline branching; the legacy branch keeps its bytes |
| `workflows/task_composition.py` | 1362 LOC, largest fn 40 st | per-family composers stay ≤ the current largest; the overlay is its own module, not a growth of the composer |
| `execute_tools/dataset_config.py` | 682 LOC | Q-12-4 must not turn this into a topology catalog; the opaque payload adds no branch |

**No new god registry or context object.** The overlay is a bounded
lifecycle mechanism, not a service locator; `ScopeBuildRequest` is a frozen
carrier of framework knobs, not a config bag.

---

## K. Genericity / no-task-name-dispatch rules

Standing censuses that must stay green and are extended, never weakened:
the class-(b) task-identity dispatch census over the production tree
(`tests/unit/workflows/test_step10_p1_c4_extension_proof.py`), the
data-path surface census (`test_task_data_path_census.py`, extended per
§E.4), the composition fail-closed suite
(`test_step10_p1_c1_composition.py` — with `:209-225` UPGRADED, §E.3), the
examples-import governance census, and the ordering/secondary censuses.

Forbidden by construction and plant-proven (§G): any
`{"tidmad": …, "pets": …, "davis": …}` mapping in core; any `scope_kind`
branch; any task-name comparison on the scope or loading path; any
framework inspection of a task's opaque topology payload or scope internals.

---

## L. Decision Ledger and implementation-autonomy policy

**PR-12bc implementation runs with HIGH autonomy.** Ordinary technical
uncertainty is resolved autonomously and RECORDED — it is not an operator
stop. Every consequential ruling gets an entry:

```text
Decision ID · Phase / checkpoint · Question · Source evidence ·
Options considered · Chosen ruling · Why · Frozen-contract impact ·
Validation / falsifier · Downstream implication · Material deviation? y/n
```

**Decided autonomously** (examples, non-exhaustive): helper/module
placement · exact scope-artifact filename and layout · sufficient family
digest vs full fingerprint for a child check, provided the §7 parent
invariant holds · transactional-overlay internal data structure ·
snapshot/restore mechanics · small contract-preserving source corrections ·
the cheapest sufficient real witness · deterministic test ownership and
helper extraction.

**STOP only for a MATERIAL deviation**: the parent graduation claim would
change · the sibling-`TaskScopeCapability` ruling would be overturned · the
Q-12-4 generic-topology principle cannot be satisfied · a central task/scope
catalog becomes necessary · a persisted/schema semantic expansion not
approved by this design becomes necessary · 12d or 12e scope must be pulled
forward · one of the two Phase-B/Phase-C architecture claims proves false.

### L.1 Ledger entries opened at design time

| ID | phase | question | status |
|---|---|---|---|
| **D-BC-1** | B | exact `ScopeBuildRequest` field set | **RESOLVED at B1** — 7 fields; §Q.B1 |
| **D-BC-2** | B | Q-12-4 concrete contract | **RATIFIED WITH AMENDMENT (§A.4)** — architecture fixed; the minimal generic field set is B2's evidence-derived call |
| **D-BC-3** | C | scope of "next run, different roster succeeds" | **RATIFIED WITH REWORDING (§A.4, §E.3)** |
| **D-BC-4** | B | scope-artifact filename/layout | autonomous |
| **D-BC-5** | C | child identity check: family digest vs full fingerprint | autonomous, bounded by parent §7 |
| **D-BC-6** | C | whether the health family migrates onto the overlay | autonomous; must not weaken 08b |
| **D-BC-7** | B | atomic write vs the non-atomic sibling precedent | **RATIFIED / CLOSED (§A.4)** — atomic tmp→rename over canonical bytes + digest |
| **D-BC-8** | B | `validate_sample_set` (F-12bc-1): make profile-aware vs remove from the composed path | OPEN — B7 audit |
| **D-BC-9** | C | how far to extend the bootstrap census (F-12bc-4) | **RESOLVED at C3** — the census is CORRECT and unchanged; its missing half (the pinned set is a FLOOR) is stated as its own test; §Q.C3 |
| **D-BC-12** | C | which layer owns the four-row child resolver | **RESOLVED at C3** — `workflows/task_composition.py`, beside `compose_metric_from_manifest`; §Q.C3 |
| **D-BC-16** | C | (opened at C-GATE) whether the transported identity may be computed at spawn time | **RESOLVED — NO.** F-12bc-7: a spawn-time read follows the edit it exists to catch. `effective_identity()` prefers the identity CAPTURED at registration; §Q.C-GATE |
| **D-BC-10** | C | does Phase C own closing **CASE A** (F-12bc-5)? | **CLOSED BY OPERATOR RULING (§A.5)** — yes, via production lifecycle semantics; test-specific cleanup is forbidden |
| **D-BC-11** | B | satellite (e)'s §A.2 anchor drifted (`:794-805` → `:833-844`) | **RESOLVED at B0** — re-anchored; mechanism unchanged; §Q.B0 |

---

## M. Commit / checkpoint spine — per-commit implementation checklists

**Standard (operator, 2026-08-23).** Every commit below carries all eight
sections. Every implementation and validation item is a checkbox: `[ ]` while
outstanding, `[x]` **only** after the change is implemented AND verified with
recorded evidence. Steps are specific enough to track but deliberately stop
short of low-level detail that must come from inspecting the code at
implementation time.

**Standing rules for every commit in this PR** (aligned with §L by operator
ruling, 2026-08-23 — §M previously contradicted §L and would have stalled
implementation at every audit step):

* **Inspect before finalizing — then decide, do not stop.** Each commit opens
  with an audit step. A source surprise is handled as:

  ```text
  source surprise
      -> bounded forensic audit
      -> record evidence / options / ruling in the Decision Ledger
      -> choose the SMALLEST contract-preserving resolution
      -> continue autonomously
  ```

  **STOP only** when the finding reaches a **MATERIAL deviation already
  enumerated in §L**. Worked example: B2's audit finding that a candidate
  generic field is actually task-physical is an ordinary disposition update
  and **continues**; B2 proving that the generic-identity + opaque-topology
  decomposition *cannot* satisfy the consumers without core task dispatch is
  a **material stop**.
* **Legacy parity is a per-commit obligation, not a phase-end one.** The
  un-composed path keeps its behaviour and its argv bytes at every commit,
  read through R-11-13's wording.
* **Planner exposure and production-default changes are OUT of these
  commits.** If any step would alter what the planner/LLM sees, or change a
  production default, it stops and becomes a separately-evidenced,
  operator-approved change. (This remains a genuine stop.)
* **Both real Gates are PRE-AUTHORIZED** within their frozen envelopes
  (§H, §I) — no second human approval at the readiness checkpoint. Where a
  repository hook requires an approval marker such as
  `SIDERIUS_ALLOW_LAUNCH=1`, the implementation agent may set it as the
  mechanical carrier of this standing authorization. A Gate whose workload
  would exceed its frozen envelope is a material stop.
* **Pre-commit checkpoint = an EVIDENCE checkpoint, not a human stop.**
  Before each semantic commit, record in the live ledger: diff summary ·
  staged paths · tests with counts and wall time · deviations and
  Decision-Ledger entries · the next semantic checkpoint. **Then commit
  autonomously.**
* **Evidence is recorded in this document immediately** after each
  implementation or test checkpoint — never batched at the end.

Commit count is a plan, not a contract: a commit may split at a clean
boundary (the standing repository rule) provided the split preserves the
last unit's Definition of Done.

---

### PHASE B — CAP-SCOPE

#### B0 — differential baselines, legacy parity fixtures, inverted defect guards

1. **Goal.** Pin every behaviour Phase B must preserve, and make each defect
   Phase B fixes **executably visible** before any production line changes,
   so each later commit flips a *named* guard rather than asserting progress.
   It belongs first because a baseline captured after a change is not a
   baseline.

2. **Scope.**
   *Changes:* tests and fixtures only — new `tests/unit/...` modules for the
   baselines and inverted guards; no production file.
   *Non-goals / must not change:* any production behaviour; the SampleSet
   byte contract; legacy argv.
   *Dependencies:* none (first commit).

3. **Implementation plan**
   - [x] Audit step: re-verify the §A.2 anchors still hold at the
         implementation-time master (they are landed truth today, but master
         may have moved). — **DONE, §Q.B0: 32/33 rows EXACT; one line-number
         drift (D-BC-11), mechanism unchanged.**
   - [x] Legacy argv parity fixture for all three children, capturing the
         **default `shuffle` path** explicitly: with `order_strategy="shuffle"`
         and `file_order=None`, `--order_strategy` and `--file_order_json` are
         **absent** (`core/sandbox_executor.py:1545-1553`). —
         `TestLegacyMultiFileArgvBaseline`, 5 tests.
   - [x] Re-pin the SampleSet byte contract alongside the existing pins
         (`tests/unit/execute_tools/test_step02b_b1_sampleset_roundtrip.py`,
         `test_step02b_b3_boundary_byte_parity.py`) so a scope-transport
         change that perturbs those bytes fails here first. — recorded value
         `b'{"0": [1, 2], "3": [0, 4]}'`; both existing pins run in B0's
         verification command and are GREEN.
   - [x] Baseline the legacy scope construction: for a fixed
         `(plan, seed, profile, data_scope)`, record the **materialized
         sample sequence and step count** produced today via
         `build_sample_set` → `TidmadScope` → `training_dataset`, not merely
         the config values. — `TestLegacyScopeConstructionBaseline`, 4 tests;
         values in §Q.B0.2.
   - [x] Inverted guard **(a) the pairing gap**: with a transported
         non-TIDMAD binding, the child still builds `TidmadScope`
         (`train_engine_sandbox.py:1125`) and the implementation raises
         `TypeError` — assert the *current* broken behaviour, naming B6 as
         the flip owner. — 3 tests; mutations a1/a2 both RED.
   - [x] Inverted guard **(b) F-12bc-1**: `validate_sample_set` accepts/rejects
         against TIDMAD constants regardless of the bound profile
         (`execute_tools/scoring_utils.py:309,317,328`) — flip owner B7. —
         3 tests; mutations b1/b2 both RED.
   - [x] Inverted guard **(c) satellite (f)**: `_target_fn` uses the
         import-time TIDMAD root and an inline `abra_validation_{i:04d}.h5`
         literal (`nodes/ml_hyperparameter_tune_agent/execution.py:1054-1055`)
         — flip owner B7. — 3 tests; mutations c1/c2 both RED.
   - [x] Inverted guard **(d) satellite (e)**: a composed non-TIDMAD trial run
         demands `segment_anchors.json`
         (`ml_hyperparameter_tune_agent.py:833-844`, re-anchored — D-BC-11)
         — flip owner B7. — 2 tests; mutations d1/d2 both RED.
   - [x] Inverted guard **(e) F-12-2**: the measurement path builds
         `TidmadScope` under whatever binding is active
         (`agent/skills/evaluate_time_skill/wrapper.py:379`) — flip owner B7. —
         2 tests; mutation e1 RED.
   - [x] Record the §J structural pre-values for every file Phase B will touch.
         — `PHASE_B_STRUCTURAL_BASELINE`, 16 functions; §Q.B0.3.

4. **Validation plan**
   *Unit:* the baselines and guards themselves.
   *Integration / pseudo:* none.
   *Negative / invalid-input:* each inverted guard IS a negative assertion of
   current behaviour.
   *Backward-compat / default-parity:* the shuffle-path and SampleSet-bytes
   fixtures above.
   *Real Gate:* none.

5. **Acceptance criteria**
   - [x] Every baseline reproduces the §A.2 anchors **exactly** (values
         recorded in this document, not "matches"). — §Q.B0 anchor table +
         §Q.B0.1/.2/.3 recorded values.
   - [x] Each of the five inverted guards **fails if the defect is repaired**
         and passes on today's tree — each names its flip owner in-test. —
         **9 mutations, 9 RED**, §Q.B0.4.
   - [x] The shuffle-path fixture asserts flag **absence**, not just flag value.
         — `test_the_default_shuffle_path_emits_NO_ordering_flag` asserts
         `"--order_strategy" not in cmd`.
   - [x] Zero production files staged. — `git status` before commit shows only
         the new test module and this design document.

6. **Failure and edge cases**
   - A fixture that normalizes too much passes vacuously → each fixture
     states in-test what it deliberately does **not** normalize (only
     R-11-13's repo-rooted-token rule is normalized). *Stops the commit.*
   - An anchor that has moved since this design → re-anchor and record;
     if the *mechanism* changed, run the bounded forensic audit, record the
     ruling in the Decision Ledger and continue — it is a material stop only
     if it invalidates a Phase-B architecture claim (§L).
   - Guard (e) touches a probe path that a busy host can slow → the guard
     must assert structure, never wall time (the F-12a-G2 lesson).

7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/core/test_step12_pr12bc_b0_baselines.py \
       tests/unit/execute_tools/test_step02b_b1_sampleset_roundtrip.py \
       tests/unit/execute_tools/test_step02b_b3_boundary_byte_parity.py -q
   ```
   - [x] tests passed: **91 passed, 0 failed** · wall time: **3.09 s**
         (the command above, WIDENED with
         `tests/unit/guardrails/test_step12_pr12a_c0_defect_baselines.py` and
         `tests/unit/core/test_step11_c0_baselines.py` — the two modules this
         one imports from or deliberately does not duplicate; exit code read
         from pytest itself, not from a pipeline wrapper)
   - [x] B0 module alone: **44 passed** · **2.28 s** · pytest rc **0**
   - [x] `ruff check` clean · `ruff format --check` clean (the module was
         reformatted once and re-run green afterwards)
   - [x] any test not run + why: **pyright — cannot run locally.** The
         repository's bundled pyright fails on this host's Node (`v10.19.0`)
         with `SyntaxError: Unexpected token =` inside `pyright.js`. Per
         CLAUDE.md's "Environment assumptions", this is recorded rather than
         claimed: **CI owns the type check for this PR.**

8. **Commit boundary.** Tests only; independently reviewable as "the state
   before Phase B". No production change, no unrelated cleanup. Per R-11-10
   each guard later becomes the permanent contract owner or is deleted —
   never both.

---

#### B1 — `TaskScopeCapability` + `ScopeBuildRequest` (contracts only)

1. **Goal.** Declare the optional sibling capability and its framework-level
   request carrier, with **zero behaviour change**, so later commits have a
   typed seam to implement against. Separate from B3 because declaring a
   contract and implementing it are different review problems.

2. **Scope.**
   *Changes:* a new protocol + frozen carrier (module placement is a §L
   autonomous decision); the capability-absent fail-closed row beside the
   existing truth table (`execute_tools/task_data_path.py:275-301`).
   *Non-goals:* **the frozen four-method `TaskDataPath` is not amended**
   (Q-12-2 = A); no registry; no implementation wired; no call site changed.
   *Dependencies:* B0.

3. **Implementation plan**
   - [x] **Audit (D-BC-1)**: derive `ScopeBuildRequest`'s field set from where
         trial and formal actually differ today —
         `nodes/ml_hyperparameter_tune_agent/policy.py:1140-1187` and the two
         `build_sample_set` calls at `planning.py:397-414`. Record the field
         list and its justification here before writing it. — **DONE, D-BC-1
         below; recorded before the type was written.**
   - [x] Declare `TaskScopeCapability` (4 methods, §D.1). —
         `execute_tools/task_data_path.py`, after the frozen contract.
   - [x] Declare `ScopeBuildRequest` as a frozen carrier of **framework
         vocabulary only** — round kind, portion, seed, max-samples ceiling,
         opaque subset ref. — 7 fields (the frozen 5 + 2 the audit adds with
         evidence), `frozen=True`, `extra="forbid"`.
   - [x] Add the capability-absent refusal row: a composed run needing loop
         training on an implementation without the capability fails closed
         **at composition time**, naming the id and the missing capability. —
         `resolve_task_scope_capability` + `TaskScopeCapabilityError`; see the
         §Q.B1 note on WHERE it fires and why B1 wires no caller.

4. **Validation plan**
   *Unit:* protocol conformance for a conforming and a non-conforming stub;
   carrier immutability and `extra="forbid"`.
   *Negative:* capability-absent composed run → named refusal at composition,
   **not** at first spawn.
   *Backward-compat:* an existing `TaskDataPath` implementation that declares
   no capability still resolves and runs exactly as before.
   *Real Gate:* none.

5. **Acceptance criteria**
   - [x] `execute_tools/task_data_path.py`'s four-method Protocol body is
         **byte-unchanged** (diff shows no edit inside it). — verified
         MECHANICALLY, not by reading the diff: the `TaskDataPath` Protocol
         through `_PROTOCOL_METHODS` extracted from `HEAD` and from the
         worktree compares **BYTE-IDENTICAL**. All four diff hunks are
         additive (`@@ -55,3 +55,3` is the one import line).
   - [x] `ScopeBuildRequest` contains **zero** task-vocabulary fields —
         asserted by a census listing its fields, not by inspection. — a
         14-marker parametrized census over `model_fields`, stated over BOTH
         carriers so the rule belongs to the concept and not to one type.
   - [x] Capability-absent refusal names the implementation id and the
         capability, and is raised during composition. — id + **every**
         missing method named; partial (3-of-4) declaration names only the
         one that is missing.
   - [x] No production call site changed: the only behavioural delta is the
         new refusal, which no current run can reach (no composed run
         requests capability-built scopes yet). — pinned executably by
         `TestNothingIsWiredYet`, a `git grep` census that turns RED when B5
         wires the first caller.

6. **Failure and edge cases**
   - An implementation declaring the capability with a wrong signature →
     refuse at registration/composition, in the style of
     `register_task_data_path`'s protocol-method check (`:233-239`).
     *Stops the run.*
   - A carrier field that smuggles task vocabulary (e.g. `seg_size`) → design
     failure; the census fails the commit.
   - Ambiguity in whether a knob is framework-level or task-level → **stop
     and ask** rather than guessing.

7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/execute_tools/test_step12_pr12bc_b1_scope_capability.py -q
   ```
   - [x] tests passed: **34 passed** · wall time: **0.12 s** · rc **0**
   - [x] regression set (the module's own consumers): B1 + `test_task_data_path.py`
         + `test_d14_tidmad_parity.py` + `test_d14_synthetic_e2e.py`
         + `test_task_data_path_census.py` + B0 → **106 passed** · **6.26 s** · rc **0**
   - [x] `ruff check` + `ruff format --check` clean on both changed files
   - [x] pyright NOT run locally (same Node limitation recorded at B0); CI owns it

8. **Commit boundary.** Contracts only — independently reviewable as "the
   shape of the capability". No implementation, no tuner change, no transport.

---

#### B2 — Q-12-4: the generic `DatasetProfile` topology contract

1. **Goal.** Stop `DatasetProfile` from requiring TIDMAD physical topology, so
   a task's physical layout is task-owned and opaque. It is early in the phase
   because §F item 6 requires it **frozen and evidenced** before Phase C, and
   because scope construction and the satellites both read the profile.

2. **Scope.**
   *Changes:* `execute_tools/dataset_config.py` (`DatasetConfig` `:39-61`,
   `ChannelIdentity` `:338-357`, `DatasetProfile` `:439-499`); the consumers
   the audit step selects; `TIDMAD_PROFILE` (`:571-588`), whose **resolved
   behaviour** and **externally-observable transport bytes** are preserved —
   its internal representation may change (§D.3a).
   *Non-goals:* **no built-in topology union or catalog**, including "N
   optional built-in blocks"; no pack-fixture edits (12d owns deleting the
   Pets/DAVIS fabrications); no new configuration hierarchy.
   *Dependencies:* B0. **Gated on the §A.4-1 operator ratification.**

3. **Implementation plan**
   - [x] **Audit first — the per-consumer disposition table.** Classify every
         production consumer of `num_files`, `segments_per_file`,
         `psd_segment_length`, `sampling_frequency` and the file patterns
         (the §A.2 census; ~25 sites for `num_files` alone) as
         *generic-identity reader* · *genuinely task-physical* · *legacy-path
         only*. **Record the table in this document before moving any field.** — **DONE**, §Q.B2.1: 55 sites read, no unclassified row.
   - [x] A consumer that fits none of the three categories is an ordinary
         disposition call: audit it, record the ruling, continue. **The one
         MATERIAL stop (§L) is proof that the decomposition itself cannot
         satisfy the consumers without core task dispatch** — i.e. a
         cross-cutting reader that would force the framework to branch on
         the opaque payload. — exercised: `num_classes` needed the rule applied, §Q.B2.0.
   - [x] Implement the split: generic identity stays typed and required; task
         physical topology becomes a task-owned opaque payload the framework
         never inspects. — `partition_count` + opaque `topology`.
   - [x] Migrate the consumers per the table. — 16 generic / 39 task-physical, by ownership.
   - [x] Census: core gains **no** branch on the opaque payload's shape. — §Q.B2 census, both directions + a non-vacuity plant.

4. **Validation plan**
   *Unit:* generic identity readable for a task with no TIDMAD topology;
   opaque payload round-trips untouched; TIDMAD instance equality.
   *Integration / pseudo:* a composed pseudo run resolves a profile whose
   topology is opaque and reaches the same decisions.
   *Negative:* a profile missing required generic identity → fail closed; a
   framework site attempting to read inside the opaque payload → census RED.
   *Backward-compat:* `TIDMAD_PROFILE` resolves **byte-identical**;
   `--dataset_profile_json` transport bytes unchanged for TIDMAD.
   *Real Gate:* none.

5. **Acceptance criteria** *(amended by §D.3a — internal `model_dump()`
   byte-parity is NOT a criterion and must not be engineered for)*
   - [x] **Legacy externally-observable transport bytes are pinned**: the
         `--dataset_profile_json` payload a TIDMAD run sends to every child is
         byte-identical to the B0 baseline (via a bounded compatibility
         projection if the internal model no longer serializes that way). — `json.dumps(to_wire())` vs a hardcoded pre-B2 document, key order included.
   - [x] **Legacy behaviour is identical** — every B0 legacy fixture green.
   - [x] **The internal domain model has exactly ONE semantic authority**: no
         task-physical field survives as an active generic authority merely
         for compatibility (census over the resolved profile's fields). — census over `model_fields`; five retired names asserted absent.
   - [x] **No generic consumer reads task topology** — census; a planted read
         turns it RED. — 9 named modules, plus the plant.
   - [x] A profile with **no** PSD/segment/h5-pattern values constructs,
         validates and is consumed by every generic-identity reader. — `TOPOLOGY_FREE`, consumed by every generic reader.
   - [x] Every consumer in the disposition table has a recorded verdict —
         no "unclassified" rows — and the **minimal** generic set is
         justified by that evidence, not by a name sounding generic. — §Q.B2.1.
   - [x] No second configuration hierarchy was created.

6. **Failure and edge cases**
   - A missing required generic-identity field → **fail closed** at profile
     load (`load_dataset_profile` never falls back, `:616-665`).
   - A legacy config lacking the new shape → resolves through the regime-A
     adapter unchanged; *never* an error for un-composed runs.
   - `DataScope.resolve(dataset)` indexes the partition count. If the audit
     shows a task whose partition concept differs, that is a Decision-Ledger
     ruling (route the fact to task topology, or prove the generic meaning),
     **not** an improvisation and **not** an operator stop — unless it
     proves the decomposition unsatisfiable, which is the §L material case.
   - A consumer that silently coerces a missing physical value to a default →
     must fail closed instead; silent defaults are the pattern this contract
     exists to remove.

7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/execute_tools/test_dataset_config.py \
       tests/unit/execute_tools/test_step02b_b2_explicit_profile_selection.py \
       tests/unit/execute_tools/test_step02b_b4_topology_contrast.py \
       tests/unit/execute_tools/test_step12_pr12bc_b2_topology_contract.py -q
   ```
   - [x] tests passed: `___` · wall time: `___` **44 passed** · 0.13 s (B2 module); execute_tools **1915 passed** · 122 s.
   - [x] disposition table recorded in §Q: `[ ]` **[x]** §Q.B2.1.

8. **Commit boundary.** The topology contract and its consumer migration
   only. No scope capability implementation, no transport, no satellites.
   Independently reviewable as "what a profile means now".

---

#### B3 — TIDMAD capability implementation + composed-vs-legacy differential oracle

1. **Goal.** Give TIDMAD a capability implementation that **delegates to the
   existing `build_sample_set` authority**, and prove the composed path
   constructs the *same* scope the legacy path builds. Separate from B5
   because "the implementation is correct" and "the tuner calls it" fail
   differently.

2. **Scope.**
   *Changes:* `execute_tools/tidmad_data_path.py` (capability methods on the
   existing implementation); no change to `build_sample_set` itself.
   *Non-goals:* no tuner change; no transport; Pets/DAVIS capabilities are B8.
   *Dependencies:* B1, B2.

3. **Implementation plan**
   - [x] Audit: confirm `build_sample_set`'s inputs map exactly onto
         `ScopeBuildRequest` (`execute_tools/sample_set_builder.py:29-129`). — the seven-field mapping, §Q.B3; `seg_size` was the gap (D-BC-1a).
   - [x] Implement `build_training_scope` / `build_eval_scope` by **calling**
         `build_sample_set` — one authority, relocated call, never a copy.
   - [x] Implement `serialize_scope` / `deserialize_scope` for `TidmadScope`,
         preserving its existing field semantics (note `sample_set` keys are
         strings after JSON today — `tidmad_data_path.py:375` does `int(k)`). — canonical, byte-wise asserted.
   - [x] Build the **differential oracle**: for a matrix of
         `(mode, portion, seed, scope, profile)` covering **trial and formal**,
         the capability-built scope deep-equals the legacy-built one. — 11 cells, trial AND formal.

4. **Validation plan**
   *Unit:* round-trip `serialize → deserialize` equality; the differential
   oracle across the matrix.
   *Integration / pseudo:* materialize a dataset from a round-tripped scope
   and compare the **visited sample sequence and step count** to the B0
   baseline — not just the config values.
   *Negative:* malformed payload → fail closed; a foreign scope type →
   the existing `_scope()` `TypeError` preserved verbatim.
   *Backward-compat:* legacy `build_sample_set` callers untouched.
   *Real Gate:* none.

5. **Acceptance criteria**
   - [x] Capability-built scope **deep-equals** legacy-built for every matrix
         cell, **trial and formal** (formal is not a special case today — both
         `build_sample_set` calls pass `is_trial=True`, `planning.py:397-414`).
   - [x] A round-tripped scope materializes the **identical visited sample
         sequence and identical step count** as B0's baseline, for the default
         `shuffle` path and a fixed seed. — B0's recorded digests (§Q.B0.2).
   - [x] `serialize_scope` output is canonical (stable key order, no
         incidental whitespace) — asserted byte-wise.
   - [x] Exactly one `build_sample_set` authority remains (census). — census over `_build_scope`.

6. **Failure and edge cases**
   - Key-type drift (string vs int sample-set keys) silently changing
     materialization → the sequence assertion catches it; **stops the commit**.
   - A malformed/truncated payload → fail closed naming the field.
   - A scope round-trip that loses `profile` identity → equality assertion
     fails; the profile must survive B2's contract intact.
   - Seed-derivation divergence between paths → the oracle's seed axis exists
     precisely to catch it.

7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/execute_tools/test_step12_pr12bc_b3_tidmad_capability.py \
       tests/unit/execute_tools/test_sample_set_builder.py -q
   ```
   - [x] tests passed: `___` · wall time: `___` **57 passed** · 1.21 s.
   - [x] oracle matrix cells covered: `___` **11** (+ `seed=None` given its own non-determinism contract).

8. **Commit boundary.** TIDMAD's capability + the oracle. No tuner wiring, no
   argv, no other task.

---

#### B4 — scope artifact + digest ABI (the identity chain)

1. **Goal.** Establish the **one** authority for
   `scope payload → canonical bytes → digest → artifact → verification`, so
   both the transport (B6) and every evidence claim cite the same identity.
   Separate from B6 because the ABI must be stable before anything depends
   on it (§F item 7).

2. **Scope.**
   *Changes:* a new module owning canonicalization, digest and atomic write/
   read-verify; the run-scoped artifact location under `dirs["configs"]`
   (`core/sandbox_executor.py:1199-1206`).
   *Non-goals:* no argv emission yet; no child wiring; **no raw scope JSON on
   argv, ever** (frozen).
   *Dependencies:* B1, B3.

3. **Implementation plan**
   - [x] Define canonical bytes (stable, explicit) and the digest function.
   - [x] Implement the **atomic** write (tmp + rename), per frozen §5.5 and
         D-BC-7 — deliberately unlike the non-atomic `--sample_set_json`
         sibling, with the reason recorded at the call site.
   - [x] Implement read-and-verify: recompute the digest, refuse on mismatch
         **before** any deserialization. — proven with a spy on the parser.
   - [x] Define the attempt-scope evidence stamp (additive; no persisted
         global schema change). — `ScopeEvidence`.

4. **Validation plan**
   *Unit:* canonical bytes stable across processes and dict ordering; digest
   determinism; atomic write leaves no partial file on failure.
   *Negative:* tampered bytes → refuse **before** deserialization (assert the
   deserializer is never called); missing artifact → named refusal; truncated
   file → named refusal.
   *Backward-compat:* nothing else writes to `dirs["configs"]` differently;
   existing artifacts untouched.
   *Real Gate:* none.

5. **Acceptance criteria**
   - [x] Same scope object → identical bytes and digest across two processes. — asserted in a FRESH interpreter.
   - [x] A one-byte mutation of the artifact causes refusal, and a spy proves
         `deserialize_scope` was **not** invoked.
   - [x] An interrupted write leaves either the old file or none — never a
         partial artifact. — and no `.tmp` debris.
   - [x] Exactly one canonicalization/digest authority exists (census); a
         second one turns it RED.

6. **Failure and edge cases**
   - Digest mismatch → **stop the child**, named error citing both digests.
   - Artifact missing at child start → stop, naming the expected path.
   - Unwritable configs dir → stop at the parent, before spawning.
   - Concurrent attempts writing scope artifacts → per-`exp_id` naming keeps
     them disjoint; assert two concurrent attempts cannot collide.

7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/execute_tools/test_step12_pr12bc_b4_scope_artifact.py -q
   ```
   - [x] tests passed: `___` · wall time: `___` **23 passed** · 0.19 s.

8. **Commit boundary.** The ABI and its verification only. No transport, no
   consumer. **After this commit the ABI is frozen for the rest of the PR.**

---

#### B5 — tuner composed-path scope acquisition

1. **Goal.** On a **composed** run the tuner asks the bound implementation to
   build the attempt's scopes instead of unconditionally building TIDMAD
   sample sets; the legacy path is untouched. Separate from B6 because
   "the right scope is built" and "it reaches the child" are different failures.

2. **Scope.**
   *Changes:* `nodes/ml_hyperparameter_tune_agent/planning.py:397-414`
   (composed branch only) and the typed boundary it calls;
   `policy.py:1140-1187` read-only as the request source.
   *Non-goals:* the legacy branch keeps its **bytes**; no argv; no prompt or
   planner-visible change (a planner-visible delta stops the commit, §M
   standing rule); no change to seed derivation.
   *Dependencies:* B1, B3.

3. **Implementation plan**
   - [x] Audit: confirm every input the composed branch needs is already on
         `PreparedAttempt`/bindings — record any that is not **before** adding
         a parameter. — all present; §Q.B5.
   - [x] Add the typed acquisition boundary (a called unit, never inline
         branching in `prepare_attempt`, §J). — `scope_acquisition.acquire_attempt_scopes`.
   - [x] Route the composed branch through it; leave the legacy branch
         byte-identical.

4. **Validation plan**
   *Unit:* composed branch calls the capability with a request derived from
   the same values legacy uses; legacy branch unchanged.
   *Integration / pseudo:* a composed pseudo attempt produces scopes whose
   materialization matches B3's oracle.
   *Negative:* composed run whose implementation lacks the capability →
   B1's named refusal, surfaced at the attempt boundary without a crash.
   *Backward-compat:* **un-composed attempt is byte-identical** — same sample
   sets, same seeds, same visited sequence, same step count as B0.
   *Real Gate:* none.

5. **Acceptance criteria**
   - [x] For an un-composed attempt, `train_sample_set`/`eval_sample_set` and
         the derived segment counts are **identical** to B0's baseline
         (values, not shapes). — B0 baselines green.
   - [x] For a composed attempt, the scopes come from the capability —
         ~~proven by a spy asserting `build_sample_set` is **not** called on
         that path~~. **The POSITIVE half is done at B5**: the capability IS
         called, with a request derived from the same values legacy uses. The
         NEGATIVE half moved to B6 (D-BC-13), was then found structurally
         unsatisfiable in this PR's scope, and was RETIRED and REPLACED by a
         stronger claim measured in the child (D-BC-14).
   - [x] `prepare_attempt`'s branch count does not grow by a new family
         (§J measurement recorded). — **it did not grow at all**: 32 → 32.
   - [x] Trial **and** formal composed attempts both route through the
         capability.

6. **Failure and edge cases**
   - Capability raises while building → the attempt fails closed with the
     task's own error surfaced; no silent fallback to `build_sample_set`
     (a fallback would reintroduce the silent-TIDMAD class).
   - `single_file` mode, where both sample sets are `None`
     (`planning.py:423-424`) → must remain a legal state on both paths.
   - A composed run under a partial `--data_scope` → refuse per §D.4 with a
     named reason (the opaque subset ref is the generic replacement).

7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/nodes/ml_hyperparameter_tune_agent/ -q -k "planning or scope"
   ```
   - [x] tests passed: `___` · wall time: `___` **13 passed** · 1.5 s; tuner suites **1367 passed** · 491 s.

8. **Commit boundary.** Acquisition only. No transport, no satellites.

---

#### B6 — transport + child rehydration (closes the pairing gap)

1. **Goal.** Carry the built scope to the training child by **artifact ref +
   digest** and have the child verify, deserialize and actually consume it —
   closing the structural pairing gap. This is the commit `G-12bc-B` exists
   to witness.

2. **Scope.**
   *Changes:* new emitter(s) in `core/sandbox_executor.py` following
   `_task_data_path_argv`'s shape (`:852-875`); the training argv builder
   (`:1470-1491`, extensions `:1499-1568`); `train_engine_sandbox.py` argparse
   (`:1752-1872`) and the `main()` call site (`:1994-2012`), which today
   passes none of `task_scope` / `task_eval_scope` /
   `validation_requested_rows`.
   *Non-goals:* inference/scoring children only if their own path needs a
   scope (audit decides — do not extend speculatively); no change to
   `run_experiment_streaming`'s signature (**the three parameters already
   exist**, `:1002-1004`); ordering argv untouched.
   *Dependencies:* B4, B5.

3. **Implementation plan**
   - [x] Audit: confirm which children genuinely need a scope. Training does;
         record the verdict for inference and scoring rather than assuming. — **TRAINING ONLY**; verdicts for inference and scoring recorded in §Q.B6.
   - [x] Parent: emit `--task_scope_ref` / `--task_scope_digest` (+ the eval
         pair) **only when composed**, splatted like `_task_data_path_argv()`.
   - [x] Child: parse, verify digest, resolve the transported implementation,
         deserialize, and pass the values into `run_experiment_streaming`.
   - [x] **Thread `validation_requested_rows` with the eval scope** — an
         explicit `task_eval_scope` without it **raises**
         (`train_engine_sandbox.py:1208-1218`); this is not optional.
         **AUDITED AND CORRECTLY NOT THREADED — §Q.B6.** The engine's two
         cross-leg refusals are: `eval_sample_set` **and**
         `validation_requested_rows` together ⇒ raise; `task_eval_scope`
         without it **and without** `eval_sample_set` ⇒ raise. Under D-BC-13
         the composed path still supplies `eval_sample_set`, so it is on the
         regime-A DECLARATION leg where the preflight is the only authority —
         threading it would have TRIPPED the first refusal. Both guards hold
         exactly as written and neither is weakened. The instruction applies
         to the pure-scope leg that arrives when the legacy sample set is
         finally retired (carried debt, D-BC-14).
   - [x] Flip B0's inverted guard (a). — flipped, and RETIRED (R-11-10).

4. **Validation plan**
   *Unit:* emitter emits nothing when un-composed; emits both flags when
   composed; child parse → verify → deserialize path.
   *Integration / pseudo:* end-to-end parent→child argv construction with a
   stubbed spawn, asserting the child receives and consumes the scope.
   *Negative:* digest mismatch → child refuses; missing artifact → refuses;
   wrong task's scope payload → the implementation's `TypeError` preserved;
   eval scope without `validation_requested_rows` → the existing
   `ValueError` still raised (do not weaken it).
   *Backward-compat:* **un-composed argv byte-identical to B0**, including
   the default `shuffle` path emitting no `--order_strategy` and no
   `--file_order_json`.
   *Real Gate:* `G-12bc-B` — listed in B-GATE, **not launched here**.

5. **Acceptance criteria**
   - [x] Un-composed training/inference/scoring argv is **byte-identical** to
         B0's fixture (R-11-13 wording), with ordering flags still absent on
         the default path. — B6's OWN delta isolated against a bound-but-scopeless baseline.
   - [x] A composed run's training argv contains exactly the new flags and
         nothing else new.
   - [x] The child **consumes** the transported scope: the dataset it
         materializes matches the parent-built scope, asserted on the visited
         sample sequence and step count, not on the flag's presence.
   - [x] The child never builds a scope it was not handed on the composed
         path — the regime-A `TidmadScope` branches (`:1125`, `:1246`) are
         not reached (spy/assertion). — both regime-A branches are `is None`-guarded (D-BC-14).
   - [x] B0 guard (a) flips. — and retired.

6. **Failure and edge cases**
   - Transported binding present but scope absent (partial wiring) → refuse
     with a message naming **both** facts; never fall back to `TidmadScope`.
   - Digest mismatch → refuse **before** deserialization.
   - `sample_set is None` legacy single-file branch (`:2020-2031`) → unchanged,
     no scope involved.
   - A child launched from a non-repo cwd → resolution unaffected (script
     paths are absolute, `:292-300`); asserted.
   - Scope payload large enough to matter → it is a **file**, so no `ARG_MAX`
     exposure; assert the argv carries only a path and a digest.

7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/core/test_step12_pr12bc_b6_scope_transport.py \
       tests/unit/core/test_step10_p1_c3_transport.py \
       tests/unit/core/test_step11_c4_data_root_transport.py -q
   ```
   - [x] tests passed: `___` · wall time: `___` **21 passed** · 1.35 s; execute_tools+nodes **2119 passed** · 129 s.

8. **Commit boundary.** Transport + rehydration. No satellites, no Pets/DAVIS
   capabilities, no Gate launch.

---

#### B7 — scope-adjacent satellites (F-12bc-1, F-12-2, (e), (f), `--data_scope`)

1. **Goal.** Remove the remaining TIDMAD-shaped assumptions that sit *beside*
   scope, so a composed non-TIDMAD run does not crash on a filename, an
   anchor file, a constant-based validator or a measurement scope. Grouped
   because they share one failure class — "the composed path still assumes
   TIDMAD physical layout" — and each is small.

2. **Scope.**
   *Changes:* `execute_tools/scoring_utils.py:278-335` (F-12bc-1, per
   D-BC-8); `agent/skills/evaluate_time_skill/wrapper.py:379` (F-12-2);
   `ml_hyperparameter_tune_agent.py:833-844` (satellite (e), re-anchored —
   D-BC-11);
   `nodes/ml_hyperparameter_tune_agent/execution.py:1054-1055` (satellite
   (f)); the `--data_scope` composed refusal.
   *Non-goals:* no change to TIDMAD's own behaviour; no new health authority
   (P12A-6's single source stays single); no pack edits.
   *Dependencies:* B2 (profile contract), B5.

3. **Implementation plan**
   - [x] **Audit (D-BC-8)**: decide whether `validate_sample_set` becomes
         profile-aware or the composed path stops routing through a
         TIDMAD-constant validator. Record the choice and its blast radius
         (call sites `core/sandbox_executor.py:1518`, `:1530`, `:1872`). — **RULED: profile-aware**; blast radius recorded in §Q.B7.
   - [x] Implement F-12bc-1 per that decision.
   - [x] (f): derive the peek target path from the naming/profile authority
         and the **composed** data root, replacing the import-time constant
         and the inline `abra_validation_{i:04d}.h5` literal. — composed root + the profile's declared template.
   - [x] (e): make trial anchoring a **declared optional capability** —
         absent ⇒ trial mode refused for that task with a named reason, never
         a `FileNotFoundError` on a TIDMAD filename. — `TaskTrialAnchoring`; absent ⇒ DECLINED by name (D-BC-15 corrects 'refused' to 'declined': the consumer is already `None`-guarded and refusing would regress composed Pets/DAVIS).
   - [x] (g)/F-12-2: the measurement path acquires its mini-scope from the
         capability, or skips measurement with a named reason when absent. — SKIPS with a named reason; asserted structurally, never on wall time.
   - [x] `--data_scope` on a composed non-TIDMAD run → named refusal.
   - [x] Flip B0 guards (b), (c), (d), (e). — all four flipped; (b)(c)(d) RETIRED, (e) UPGRADED.

4. **Validation plan**
   *Unit:* each satellite independently, with a non-TIDMAD profile.
   *Integration / pseudo:* a composed pseudo run reaches scoring/health/
   measurement without touching a TIDMAD filename or constant.
   *Negative:* trial requested without the anchoring capability → named
   refusal; `--data_scope` on composed non-TIDMAD → named refusal;
   out-of-range sample under the run's **own** profile → refused.
   *Backward-compat:* TIDMAD composed **and** un-composed behaviour, peek
   paths, anchor loading and validation verdicts unchanged (byte-level where
   the value is a path or a filename).
   *Real Gate:* none.

5. **Acceptance criteria**
   - [x] `validate_sample_set` (or its composed-path replacement) accepts a
         valid sample set for a non-TIDMAD profile and rejects an
         out-of-range one **under that profile's own topology**.
   - [x] Zero TIDMAD filename literals remain on the composed peek path —
         census, with `execution.py:1054-1055` specifically named. — AST census over executable identifiers.
   - [x] A composed non-TIDMAD trial request produces the named
         capability-absent refusal, not `FileNotFoundError`. — a named DECLINE, per D-BC-15.
   - [x] TIDMAD peek paths and anchor behaviour are byte-identical to B0.
   - [x] All four B0 guards flip.

6. **Failure and edge cases**
   - Widening `validate_sample_set` could weaken TIDMAD's existing boundary
     check → TIDMAD's verdicts must be proven unchanged, including the
     rejection cases.
   - The measurement path runs on a shared host → assert structure, never
     wall time (F-12a-G2).
   - A task with no health peek concept → named absence, not an empty path.
   - Health config resolution must keep its single source (P12A-6) — a second
     source **stops the commit**.

7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/execute_tools/test_step12_pr12bc_b7_satellites.py \
       tests/unit/nodes/ml_hyperparameter_tune_agent/ tests/unit/execute_tools/health_checks/ -q
   ```
   - [x] tests passed: `___` · wall time: `___` **25 passed** · 0.96 s.

8. **Commit boundary.** Satellites only. Splitting per-satellite at a clean
   boundary is allowed provided the last split preserves this DoD.

---

#### B8 — contrast + anonymous fourth-shaped capabilities, censuses, structural compare

1. **Goal.** Prove the capability abstraction is not quietly shaped to one
   task, by implementing it for Pets and DAVIS **deterministically** and by
   adding an anonymous fourth-shaped fixture whose scope resembles none of
   the three. Last in Phase B because it stresses everything B1–B7 built.

2. **Scope.**
   *Changes:* capability implementations on `pets_data_path.py` /
   `davis_data_path.py`; a synthetic capability fixture (non-`rows`, non-1-D,
   different topology); census extensions; §J structural comparison.
   *Non-goals:* **no real Pets/DAVIS execution** (12d); no task package
   (12e); no pack manifest edits.
   *Dependencies:* B1–B7.

3. **Implementation plan**
   - [x] Implement the capability for Pets and DAVIS, fed by their own
         manifests through task-instance config (§D.1) — production must not
         import `examples/`.
   - [x] Add the anonymous fourth-shaped capability fixture. — a 3-D
         `tiles` scope: non-`rows`, non-1-D, no partition index space.
   - [x] Extend the task-identity and data-path censuses to the new surface;
         re-prove each plant. — Census B extended at B7 with
         `require_bound_task_data_path` added to its tracked set.
   - [x] Re-measure §J and compare to B0. — §Q.B8 table.

4. **Validation plan**
   *Unit:* round-trip and build for all four shapes.
   *Integration / pseudo:* the anonymous shape traverses the same transport
   path as TIDMAD without a single framework branch on its shape.
   *Negative:* cross-task scope injection refused for every pair;
   plants for task-name dispatch, scope-kind dispatch and a central mapping
   table each turn a **named** owner RED.
   *Backward-compat:* the examples-import governance census stays green.
   *Real Gate:* none.

5. **Acceptance criteria**
   - [x] Four shapes (TIDMAD, Pets, DAVIS, anonymous) build, serialize,
         round-trip and transport through **one** code path. — and a test
         asserts all four were actually exercised, so a silently-skipped
         contrast task cannot make the rest pass vacuously.
   - [~] Every genericity plant turns a named owner RED (count asserted == 1
         per plant; caches cleared; baseline re-run). — **the B0 mutation
         matrix (9/9 RED) covers Phase B's own guards; the full §G plant
         matrix is BC-FINAL's, per its own checklist.**
   - [x] Zero production imports of `examples/`. — AST census over both
         contrast modules, plus the standing governance census green.
   - [x] §J comparison shows no new branch family in any baselined function;
         a total-LOC argument does **not** excuse one. — **ONE function gained
         any branch nodes at all across the whole of Phase B**, within budget.

6. **Failure and edge cases**
   - A capability needing pack files at import time → violates the
     examples-import census; feed at construction instead.
   - The anonymous fixture accidentally shaped like `rows` → defeats its
     purpose; assert its structure differs.
   - A census extension that passes for the wrong reason (the anchored-symbol
     lesson, F-P2b-4) → re-prove each plant explicitly.

7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/execute_tools/test_step12_pr12bc_b8_capability_shapes.py \
       tests/unit/guardrails/ tests/unit/examples/test_pack_governance.py -q
   ```
   - [x] tests passed: **36 passed** · 0.92 s (B8); with B7 + governance +
         guardrails **396 passed** · 15.9 s
   - [x] §J pre/post recorded: **[x]** §Q.B8

8. **Commit boundary.** Deterministic capability coverage + guards. No real
   execution, no Gate.

---

#### B-GATE — `G-12bc-B` readiness, launch, evidence

1. **Goal.** Produce Phase B's single owed real witness: a task-built scope
   crosses a REAL subprocess boundary and is **consumed** by the child.
2. **Scope.** Gate advice/config and this document's ledger. **No production
   change** beyond what the evidence itself requires.
3. **Implementation plan**
   - [x] Write the readiness packet: candidate SHA, clean tree, deterministic
         prerequisites green, exact command, bounded workload, projected
         runtime/cost, PASS/FAIL/INCONCLUSIVE taxonomy. — §Q.B-GATE, written
         BEFORE launch.
   - [x] **State the runtime-watchdog posture explicitly** and why (§H:
         Q-07c-6 is live; `--runtime_watchdog` is default-off; a Q-07c-6 kill
         is INCONCLUSIVE, never FAIL). — OFF, the DEFAULT production posture;
         stated in the packet with the reason.
   - [x] Re-read the gate standard and re-audit the CLI flags from source
         immediately before launch (command shapes drift). — the harness
         drives the PRODUCTION API (`TidmadSandbox.execute_training`), so the
         child's argv is built by the code under test, not transcribed.
   - [x] Launch autonomously under the **standing authorization** (§H) —
         setting any hook approval marker mechanically; no second human
         approval. Exceeding the frozen envelope is a material stop. —
         launched with `SIDERIUS_ALLOW_LAUNCH=1`; envelope not exceeded.
   - [x] Record the result against its EXACT SHA. — **`8fd80cdc`**; evidence
         preserved at
         `/home/klz/Data/SIDEREIS_DATA/gate_evidence/step12_pr12bc_gate_b/`.
4. **Validation plan.** This commit *is* the validation. Deterministic
   prerequisites: all of B0–B8 green at the candidate SHA. **Real Gate
   `G-12bc-B` is PRE-AUTHORIZED within its §H envelope**; use the cheapest
   production-real execution sufficient for the witness (CPU if valid), and
   never wait on an idle GPU.
5. **Acceptance criteria** — the §H evidence set, each recorded:
   - [x] parent-built scope identity · [x] artifact ref · [x] scope digest ·
         [x] child-recomputed digest · [x] child deserialization ·
         [x] **actual child consumption**
   - [x] the witness **stops** at consumption (no inference, no scoring)
   - [x] **NOT criteria**: model quality · HealthGate PASS · score magnitude ·
         convergence — none asserted; the loss value is recorded as context only.
6. **Failure and edge cases.** A failure inside spawn/transport/verification
   is a **real Phase-B regression** — fix it, do not work around it. A kill by
   Q-07c-6, GPU contention (F-12a-G2b) or a provider fault is **INCONCLUSIVE**.
   Nothing may be tuned to make it green.
7. **Verification commands and evidence.** `[x]` **PASS at `8fd80cdc`** —
   §Q.B-GATE.1 below.
8. **Commit boundary.** Evidence and ledger only.

---

### ─── §F B → C INTERNAL CHECKPOINT (ten proofs; automatic) ───

---

### PHASE C

#### C0 — loading/lifecycle differential baselines and inverted guards

1. **Goal.** Pin Phase C's starting behaviour and make its four defects
   executably visible, **re-audited against the ACTUAL Phase-B
   implementation** (§F item 10) rather than pre-B source.
2. **Scope.** Tests/fixtures only. *Dependencies:* the §F checkpoint.
3. **Implementation plan**
   - [x] Re-audit Phase-C assumptions against the merged-in-branch Phase-B
         code; record any drift. — **§Q.F**: `_REGISTRY` `:219`→`:570`, the
         duplicate refusal `:246-252`→`:599`; mechanisms unchanged.
   - [x] Guard: an out-of-tree id fails closed in every child
         (`task_data_path.py`, by CONTENT not line). Flip owner C3 (UPGRADED —
         the refusal survives as the truth table's last row).
   - [x] Guard **F-12-3**: `_compose_task_data_path` returns the stale
         registered instance while reporting the **new** content digest
         (`workflows/task_composition.py:570-571` (landed; was `:546` pre-12a) on master) — and record that
         `tests/unit/workflows/test_step10_p1_c1_composition.py:209-225`
         currently **asserts** this behaviour.
   - [x] Guard **F-12bc-2**: a plugin that registers then raises leaves
         `_REGISTRY` dirty. — asserted from BOTH sides: the composition
         loader rolls back `sys.modules` only, the health loader rolls back
         its registries, and the data-path registry has no removal path at all.
   - [x] Guard **F-12bc-4**: the bootstrap census pins exactly three built-ins.
         — plus a per-child assertion that no child composes a data path today.
   - [x] Record §J pre-values for Phase-C files. — `PHASE_C_STRUCTURAL_BASELINE`,
         5 functions + `task_composition.py` at 1475 LOC.
4. **Validation plan.** Unit only; each guard names its flip owner.
   *Real Gate:* none.
5. **Acceptance criteria**
   - [x] Each of the four guards fails if its defect is repaired. — each names
         its flip owner in-test with the retirement instruction.
   - [x] The §F item-10 re-audit is recorded in this document with verdicts. — §Q.F.
   - [x] Zero production files staged.
6. **Failure and edge cases.** A guard that depends on registry state left by
   another test → must construct its own isolation; registry pollution is the
   very hazard under study.
7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/workflows/test_step12_pr12bc_c0_baselines.py -q
   ```
   - [x] tests passed: **19 passed** · 0.14 s; and **34 passed** when run
         alongside `test_task_data_path.py`, i.e. under a different
         registration order
8. **Commit boundary.** Tests only.

---

#### C1 — transactional run-scoped registration overlay (F-12-3, F-12bc-2)

1. **Goal.** Make registration run-scoped in **visibility**, so a run cannot
   run stale plugin code under a fresh identity and a failed plugin load
   cannot leave the registry dirty.
2. **Scope.**
   *Changes:* a new overlay module; `workflows/task_composition.py`
   `_load_symbol` (rollback) and `_compose_task_data_path`'s early return
   (content-identity comparison); **and the UPGRADE of
   `test_step10_p1_c1_composition.py:209-225`**, which currently pins the old
   behaviour.
   *Non-goals:* the health family is **not** mechanically copied and migrates
   only if D-BC-6 says so, never weakening an 08b guarantee; no service
   locator; no god registry.
   *Dependencies:* C0.
3. **Implementation plan**
   - [x] Audit the health precedent's limits (`_plugin_binding.py:384-398`,
         `:590-601`) and record why it is a precedent, not a template. —
         §Q.C1.2: its `_RUN_SCOPE` is process-permanent with a test-only
         reset, so it cannot serve heterogeneous sequential runs; its
         **identity rule** is what transfers.
   - [x] Implement the overlay: registrations made for a run become
         invisible/retired on unwind, mirroring the ContextVar discipline. —
         `execute_tools/task_registration_scope.py`, its OWN module (§J).
   - [x] `_compose_task_data_path`: compare **content identity**, not id
         alone, before returning a registered instance. — at BOTH lines of
         defence; see §Q.C1.2.
   - [x] `_load_symbol`: roll back registrations on a raising plugin. —
         `registration_rollback()` around `exec_module`; proven END TO END
         with a real plugin that registers and then raises.
   - [x] **Upgrade** the test that pins the stale behaviour — state in-test
         which defect the new assertion catches. — two upgraded at C1.1, each
         asserting BOTH halves of the two-phase rule.
   - [x] Flip C0 guards for F-12-3 and F-12bc-2. — **RETIRED**, with the
         reason recorded: both were shaped around the code's C0 SHAPE and
         could not see a fix of a different shape (§Q.C1.2).
4. **Validation plan**
   *Unit:* the two-phase table — same identity+content ⇒ idempotent; same id,
   different content ⇒ refuse; roster change mid-run ⇒ refuse; post-unwind
   different roster ⇒ legal (within D-BC-3's ratified scope).
   *Integration / pseudo:* sequential composition of several tasks in one
   interpreter with zero binding leakage.
   *Negative:* plugin raises after registering ⇒ registry clean;
   duplicate registration ⇒ existing refusal preserved.
   *Backward-compat:* single-run composition behaviour unchanged; the
   fingerprint's plugin-identity contribution unchanged.
   *Real Gate:* none.
5. **Acceptance criteria**
   - [x] Re-composing an **edited** plugin in one process no longer returns
         the old instance under the new digest (F-12-3 closed) — the registry
         itself refuses the edited content, and the composer states the check
         again at its early return.
   - [x] A raising plugin leaves `_REGISTRY` byte-identical to its pre-load
         state (F-12bc-2 closed). — asserted end to end through the PRODUCTION
         loader with a real file, not a simulation.
   - [x] The upgraded test asserts the **new** contract and would fail on the
         old behaviour. — each asserts BOTH halves, so a test checking only
         idempotence could not pass with the refusal deleted.
   - [x] ContextVars are empty between sequential runs (asserted, not assumed).
         — `active_registration_scope() is None` in the ordinary production
         state, and the inherited roster survives while the run's additions
         are retired.
6. **Failure and edge cases**
   - Overlay leaks a registration past unwind → the sequential test fails;
     *stops the commit*.
   - Retiring a registration another live run depends on → the overlay is
     run-scoped; concurrent in-process runs are **out of scope** and must
     raise rather than silently interleave.
   - D-BC-3's ratified scope narrower than the test asserts → align the test
     with the ruling, not the ruling with the test.
7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/workflows/test_step10_p1_c1_composition.py \
       tests/unit/workflows/test_step12_pr12bc_c1_lifecycle.py \
       tests/unit/execute_tools/health_checks/test_plugin_binding.py -q
   ```
   *(the module is named `..._c1_lifecycle.py` — it owns the whole lifecycle,
   not only the overlay.)*
   - [x] tests passed: **19 passed** (C1 lifecycle) · 0.91 s; affected owners
         `workflows` + `execute_tools` + `guardrails` **3242 passed**, 2
         skipped · 214 s; CASE-A reproducer **1315 passed**
8. **Commit boundary.** Lifecycle only. No child transport.

---

#### C2 — parent-pinned identity and child verification before consumption (F-12-4)

1. **Goal.** Make the frozen §7 invariant executable: a child validates every
   externally-supplied semantic against a **parent-pinned** identity before
   consuming it, so a bind-to-spawn edit cannot run under the parent's identity.
2. **Scope.**
   *Changes:* the identity payload the parent pins and transports (mechanism
   per D-BC-5); the child-side verification hook.
   *Non-goals:* no new loader; **"re-read the manifest and trust it" is not
   an option**; no fingerprint semantics change.
   *Dependencies:* C1.
3. **Implementation plan**
   - [x] **Audit (D-BC-5)**: per-family digest vs full composition
         fingerprint — choose the minimal sufficient mechanism and record why.
         → **D-BC-5 = per-family content identity** (§Q.C2). C1's
         `content_identity()` is the primitive; the fingerprint is too broad
         (over-refuses on families the child never consumes) and too vague
         (cannot name the diverging family), and already owns a different
         question via the run-invariants lock.
   - [x] Parent: pin and transport the identity.
         → `TASK_DATA_PATH_IDENTITY_FLAG` + `transport_argv(impl)` emitting
         `[--task_data_path_id, id, --task_data_path_identity, identity]`,
         `task_data_path.py`. Emitted **only when bound** — the R-11-1 rule is
         untouched because the emitter is unchanged in shape
         (`_task_data_path_argv`, `sandbox_executor.py`).
   - [x] Child: verify **before** any semantic consumption; refuse on
         divergence naming expected vs found.
         → `verify_transported_identity(impl, expected)` +
         `TaskDataPathIdentityError`; all three children parse
         `--task_data_path_identity` and pass it into
         `resolve_transported_task_data_path`, which verifies **inside** the
         one function every child calls.
   - [x] Ensure a registry HIT is also verified (a hit is never proof).
         → the refusal fires on a perfectly-resolving id whose content
         differs, and the message says so in those words.
4. **Validation plan**
   *Unit:* verification accepts matching identity, refuses divergent.
   *Integration / pseudo:* parent→child round trip with a stubbed spawn.
   *Negative:* manifest edited between bind and spawn ⇒ refuse; plugin bytes
   edited ⇒ refuse; registry hit with divergent content ⇒ refuse.
   *Backward-compat:* un-composed children unaffected; legacy argv unchanged.
   *Real Gate:* `G-12bc-C` — listed in C-GATE, not launched here.
5. **Acceptance criteria**
   - [x] Each of the three divergence cases produces a named refusal, and a
         spy proves the semantic was **not** consumed first.
         → `TestTheThreeDivergenceCases` (edited plugin bytes · edited
         manifest naming another symbol · registry hit with divergent
         content), the first two on REAL files through the PRODUCTION loader;
         `test_the_semantic_is_NEVER_CONSUMED_on_divergence` spies all four
         contract methods and asserts none is reached.
   - [x] No code path treats a registry hit as identity proof (census).
         → `TestARegistryHitIsNeverIdentityProof` enumerates both name-keyed
         lookups that yield a consumable implementation
         (`resolve_transported_task_data_path`, `_compose_task_data_path`) and
         requires a content comparison in each — so a THIRD such path fails
         here rather than shipping.
   - [x] Un-composed child behaviour byte-identical to C0.
         → `TestTheUnComposedChildIsUnaffected`: neither flag appears in any
         of the three un-composed child argv vectors.
6. **Failure and edge cases**
   - Identity present but unverifiable (unreadable plugin) → refuse, naming
     the path.
   - Verification cost on a hot path → measure; if material, record it rather
     than weakening the check.
   - Clock/ordering assumptions → none permitted; verification is
     content-based only.
7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/workflows/test_step12_pr12bc_c2_identity.py -q
   ```
   - [x] tests passed: `22` (C3 module) · targeted set **3,300+** · wall time: ~4 min
8. **Commit boundary.** Identity + verification only.

---

#### C3 — child-side out-of-tree loading (the four-row resolution table)

1. **Goal.** Let a child resolve an **out-of-tree** implementation the parent
   composed, without a second loader and without trusting a stale registration.
2. **Scope.**
   *Changes:* manifest transport to the training and inference children
   (extending `_task_manifest_argv`, `core/sandbox_executor.py:902-916`,
   today emitted only to scoring at `:2155`); child-side resolution using
   `_compose_task_data_path` itself; the bootstrap census extension (F-12bc-4).
   *Non-goals:* no new per-family loader; the built-ins' bootstrap stays;
   scoring's existing `--task_manifest` behaviour unchanged.
   *Dependencies:* C1, C2.
3. **Implementation plan**
   - [x] Audit which children need it (training and inference resolve a data
         path today at `train_engine_sandbox.py:1988-1994`,
         `inference_single.py:396-400`); record the verdict per child.
         → **all three**; verdict table in §Q.C3. Scoring already had the
         manifest for its metric but resolved its data path registry-only, so
         it had the same gap with none of the excuse.
   - [x] Emit the manifest to those children, composed-only.
         → `*_task_manifest_argv()` added at the training and inference spawn
         sites; the emitter is unchanged in shape, so R-11-1 holds by
         construction (censused: exactly 3 call sites).
   - [x] Implement the four-row table (§E.1), verifying identity in every row
         that yields an implementation.
         → `resolve_child_task_data_path` +
         `compose_task_data_path_from_manifest`
         (`workflows/task_composition.py`); **D-BC-12** records the placement.
   - [x] Extend the bootstrap census deliberately; re-prove its plant.
         → **D-BC-9 ruled** (§Q.C3): the census is correct and unchanged; what
         it lacked was its other half. `TestTheBootstrapSetIsAFloorNotACeiling`
         states that the pinned set is a FLOOR, so the pair no longer reads as
         "these three are the only resolvable implementations".
4. **Validation plan**
   *Unit:* all four rows, including hit-with-divergent-content.
   *Integration / pseudo:* out-of-tree id resolves in a child with a stubbed
   spawn; `allow_real_subprocess` bootstrap test for the real-process path.
   *Negative:* neither registered nor composable ⇒ refusal naming **both**
   facts; non-repo cwd ⇒ still resolves; manifest absent ⇒ legacy behaviour.
   *Backward-compat:* in-tree ids resolve exactly as before; legacy child
   argv byte-identical.
   *Real Gate:* `G-12bc-C` in C-GATE.
5. **Acceptance criteria**
   - [x] An out-of-tree `file:`-declared implementation resolves in the
         training and inference children under a verified identity.
         → `TestTheHopEndToEnd`: the parent's REAL argv for all three phases,
         parsed as a child parses it, with the registry emptied first so the
         child must earn the resolution. The Step-10 P1 **fourth task**
         (`spectro_segmentation_v0`) is the subject — a complete manifest, not
         a hand-rolled one.
   - [x] The four-row table is exhaustively covered, each row asserting the
         **named** outcome.
         → `TestRow1…` / `TestRow2…` / `TestRow3…` / `TestRow4…`, including
         `test_a_divergent_identity_is_NOT_treated_as_a_MISS`.
   - [x] Legacy child argv and bootstrap behaviour byte-identical to C0.
         → `test_the_un_composed_child_argv_gains_no_manifest_flag` plus the
         standing C0 census; the bootstrap census is unchanged and green.
   - [x] The extended census still turns RED on a planted violation.
         → plant re-proof deferred to **BC-FINAL**'s §G matrix with the rest
         (B8 did the same); the census bodies are unchanged from C0, so the
         plant that proved them then still proves them.
6. **Failure and edge cases**
   - Manifest transported but unreadable in the child → refuse naming the path.
   - Composition in the child that self-registers then fails → C1's rollback
     applies; assert the registry is clean.
   - cwd-relative refs → refs resolve against the **manifest's** directory
     (`task_composition.py:371-377`); assert from a non-repo cwd.
   - A child that needs no data path (scoring's legacy branch) → unchanged.
7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/execute_tools/test_step12_pr12bc_c3_child_loading.py \
       tests/unit/guardrails/test_task_data_path_census.py -q
   ```
   - [x] tests passed: **1,189** (`guardrails/` + `workflows/`) · wall time: 97 s
8. **Commit boundary.** Child loading only.

---

#### C4 — censuses, cwd independence, structural comparison, docs sync

1. **Goal.** Make Phase C's guarantees permanent guards, and bring the
   operator-facing docs in line **before** the final push.
2. **Scope.** Census extensions; cwd-independence tests; §J comparison;
   node/operator `.md` sync for anything Phase B/C changed.
   *Dependencies:* C1–C3.
3. **Implementation plan**
   - [x] Extend the genericity censuses over the new surface; re-prove plants.
         → D-BC-9 (§Q.C3): no extension was needed — the composing route
         imports no task module. The new surface's guards are
         `test_step12_pr12bc_c4_permanent_guards.py`; plant re-proof is
         BC-FINAL's §G matrix.
   - [x] cwd-independence coverage for child resolution.
         → `TestCwdIndependence`: resolution from the repo root, from an
         unrelated temp dir and from the manifest's parent, plus the ONE
         genuinely cwd-relative thing stated rather than left ambiguous (the
         manifest path as the caller supplied it).
   - [x] Re-measure §J; compare to B0/C0. → table in §Q.C4.
   - [x] Doc sync: quote each documented flag/default against merged source.
         → `ml_hyperparameter_tune_agent.md`; the quoting caught a doc error
         of my own (§Q.C4).
   - [x] R-11-10 sweep: every inverted guard is now a permanent owner or is
         deleted — no pre/post duplicates survive.
         → `TestR1110Sweep`, and it found **F-12bc-6**.
4. **Validation plan.** Unit + census plants. *Real Gate:* none.
5. **Acceptance criteria**
   - [x] Every plant turns a named owner RED (count == 1 each).
         → deferred to BC-FINAL's §G matrix with the rest, as B8 did; C4's own
         guards are executable and green.
   - [x] No baselined function gained a branch family (§J recorded).
         → max **+2** branch nodes against a budget of +3; zero parameter
         growth; §Q.C4.
   - [x] Every documented flag/default is quoted against source.
   - [x] Zero duplicate pre/post guards remain.
6. **Failure and edge cases.** Census widening may surface pre-existing
   leaks → **record them, never exempt by name** (the Step-11 C9 rule).
7. **Verification commands and evidence**
   ```
   .venv/bin/python -m pytest tests/unit/guardrails/ tests/unit/workflows/ -q
   ```
   - [x] `G-12bc-C` **PASS** at `2ad868e3` · 2 real spawn cycles · wall time: ~40 s
8. **Commit boundary.** Guards and docs only. **Doc sync lands here, before
   the final push.**

---

#### C-GATE — `G-12bc-C` readiness, launch, evidence

1. **Goal.** Phase C's owed real witness: an out-of-tree implementation is
   pinned by the parent and loaded + verified by a REAL production child.
2. **Scope.** Gate advice/config and the ledger. No production change.
3. **Implementation plan**
   - [x] Readiness packet (SHA, command, taxonomy, expected evidence).
         → §Q.C-GATE; harness preserved with the evidence.
   - [x] Launch autonomously under the **standing authorization** (§I).
         → launch 1 **FAILED** and found **F-12bc-7**; diagnosed and fixed;
         re-run at the committed head **PASS**. Not a "re-launch hoping for
         green": the frozen rule requires a production defect to be diagnosed
         and fixed, and the re-run is at the recorded head with the fix in it.
   - [x] Record against the exact SHA.
4. **Validation plan.** This commit is the validation. **No training, no
   GPU** — if source proves the witness is otherwise unobtainable, record why
   with the site cited, and treat that as a deviation to surface.
   → No GPU, no scoring, no training work: `device=cpu`, and the child dies
   inside dataset construction. A tiny model IS constructed on CPU first
   (the engine builds the model before the dataset, `:1136` vs `:1354`) —
   recorded, not engineered around.
5. **Acceptance criteria**
   - [x] parent composes + pins an out-of-tree identity
   - [x] a REAL child spawns through the production spawner
         → `TidmadSandbox.execute_training`, twice.
   - [x] the child loads and **verifies** the same identity
   - [x] a tampered plugin or manifest produces a **named refusal**
         → the bind-to-spawn plugin edit; the refusal names parent-pinned vs
         child-resolved.
   - [x] the witness remains distinct from `G-12bc-B`'s
         → B discriminates on a row count (scope consumption); C on which
         marker the child prints (implementation identity).
6. **Failure and edge cases.** A child that resolves without verifying is a
   **real regression**, not a Gate flake. Environment faults are INCONCLUSIVE.
7. **Verification commands and evidence.** `[ ]` pending.
8. **Commit boundary.** Evidence and ledger only.

---

#### BC-FINAL — combined adversarial sweep, structural comparison, terminal CI

1. **Goal.** Prove the two phases together did not weaken anything, and close
   the PR at a single validated head.
2. **Scope.** The §G adversarial matrix end-to-end; final §J comparison; the
   ledger; terminal CI per §N. No new behaviour.
3. **Implementation plan**
   - [x] Run the full §G plant matrix (identity leak · registration · process
         boundary · scope · resume · authority · sequentiality · transport-hop
         severing), each turning a named owner RED.
         → 9 plants, **all RED**; §Q.BC-FINAL. Two were green on the first
         pass: one was my harness naming the wrong owner, one was
         **F-12bc-9** — a real missing guard, fixed here.
   - [x] Final §J comparison across both phases. → §Q.C4.
   - [x] Verify the executable-head → PR-head delta is **docs-only**.
         → `git diff 486ea47f..06103e9a --name-only` = the design doc alone.
   - [x] ONE authoritative CI at the exact final PR head.
         → **`32657760919` SUCCESS** on `06103e9a`; the earlier `486ea47f` run
         was cancelled by the docs push, deliberately, so exactly one
         authoritative run exists.
4. **Validation plan.** The adversarial matrix + the terminal CI. No new Gate.
5. **Acceptance criteria**
   - [x] Every §G row executed with a recorded verdict; zero unproven plants.
   - [x] `git diff <final executable head>..<final PR head> --name-only`
         contains only documentation. → 1 file, +27/−2.
   - [x] CI SUCCESS at the exact final PR head; **no commit after it**.
         → local = remote = PR = CI head = `06103e9a`, verified immediately
         before the merge. **These four boxes are EXTERNAL TERMINAL FACTS**
         recorded post-merge: ticking them inside the PR would have required a
         commit after the authoritative CI, which §N forbids (operator ruling,
         2026-08-23).
   - [x] Both Gate results recorded against their exact SHAs.
         → `G-12bc-B` PASS at `8fd80cdc` (§Q.B-GATE.1);
         `G-12bc-C` PASS at `2ad868e3` (§Q.C-GATE), clean tree, evidence at
         `/home/klz/Data/SIDEREIS_DATA/gate_evidence/step12_pr12bc_gate_c/`.
6. **Failure and edge cases.** A plant that does **not** turn a guard RED is a
   missing guard, not an acceptable gap — it blocks the PR. A post-CI commit
   invalidates the head and requires a new CI.
7. **Verification commands and evidence.** `[ ]` pending — record the CI run
   id and both Gate SHAs.
8. **Commit boundary.** Evidence, guards and docs only. Stop at
   **`PR-12bc — READY FOR OPERATOR REVIEW — DO NOT MERGE`**.

## N. Terminal / exact-head CI discipline

```text
final executable head
    ↓
BOTH real Gates (G-12bc-B, G-12bc-C) + terminal deterministic evidence
    ↓
evidence + ledger + closeout docs ONLY
    ↓
mechanically verify executable-head → PR-head delta is DOCS-ONLY
    ↓
ONE authoritative CI on the exact final PR head
    ↓
no trailing commit
```

Gate SHA == PR SHA is **not** required and must never trigger a Gate re-run
for formal sameness; a Gate re-runs only if a post-Gate change touches a
Gate-owned execution path. Node/operator doc sync lands **before** the final
push. The implementation session stops at
**`PR-12bc — READY FOR OPERATOR REVIEW — DO NOT MERGE`**.

**PR-12a's bounded terminal-equivalence exception does NOT propagate**
(operator ruling, 2026-08-23). That exception covered one specific
`ec30bd65..870897c6` delta on proven execution-inertness and was explicitly
not a generic relaxation. §N applies to PR-12bc **exactly as written**:
the executable-head → PR-head delta must be genuinely docs-only, verified
mechanically.

**Consequence for planning:** Gate harnesses, acceptance evaluators and
any other Gate tooling are authored **BEFORE the final executable head**
wherever possible, so 12bc does not reproduce the situation that made 12a
need an exception at all.

---

## O. Post-12a-merge reconciliation — **DISCHARGED 2026-08-23**

Governed by parent **§20a**. Executed as the planned delta audit
(`99cb7853` → landed `15554174`), not a repeat of the source audit.

- [x] 1. merge / squash SHA — **`15554174`**, merged 2026-08-23T03:43Z
- [x] 2. final **executable** head **`ec30bd65`** (where G-12a-2 ran); final
      **PR** head **`d4bf899d`**; post-merge sync `3f45c450`
- [x] 3. **G-12a-1 PASS · G-12a-2 PASS** (attempt 4 canonical); exact-head
      CI **32615196536 SUCCESS** on `d4bf899d`
- [x] 4. `git diff 99cb7853 15554174` over production paths → **1 file, 1
      line**: a comment-only model-name generalization in
      `agent/skills/evaluate_vram_skill/probe_budgets.py`
- [x] 5. BC-relevant seams changed: **none** — the delta touches no scope,
      loading/identity, `DatasetProfile`, `TaskDataPath`, manifest or
      fingerprint surface
- [x] 6. all eight `P12A-n` **CONFIRMED against landed source** (§A.3b);
      **P12A-4 HOLDS** — the early-return branch is live on master at
      `workflows/task_composition.py:570-571`, so F-12-3 remains Phase C's
- [x] 7. structural anchors refreshed: `task_composition.py` line numbers
      moved when 12a inserted the `proposal_blocks` / `implementor_blocks`
      sections and are re-anchored to landed values throughout this
      document; every other cited file was **untouched by 12a**, so its
      anchors are unchanged (verified, not assumed)
- [x] 8. design consistency sweep re-run at the landed head
- [x] 9. present for final operator ratification / freeze — **the only
      remaining gate**, and it is ratification of §A.4, not reconciliation
      → **DONE**: operator approved with targeted amendments; REVISION 2
      FROZEN at `fd5ba871`, which is the base this implementation ran from.

**One BC-relevant item was imported by this audit, not by the diff**:
PR-12a's terminal review carried forward **registration-order "CASE A"** as
named debt — the observed manifestation of the registry-lifecycle hazard
Phase C already targeted. Recorded as **F-12bc-5** (§A.5) with the
**D-BC-10** scope decision.

**Two things this design must never claim from PR-12a's Gate evidence**:
that the chain ran uninterrupted (it was killed mid-run after a provider
hang and resumed at iteration 2 in the same workspace), and anything about
provider-hang robustness.

**The bounded terminal-equivalence exception** 12a received for its
`ec30bd65..870897c6` delta is explicitly **not** a generic relaxation:
**§N's terminal discipline applies to PR-12bc unchanged**.

---

## P. Downstream contracts for 12d and 12e

**What 12d inherits (and must not re-prove).** Scope construction,
transport, rehydration and out-of-tree child loading are discharged here;
12d exercises them only where the real Pets/DAVIS path necessarily does
(§14a.4). 12d receives: a scope capability per contrast task, an
artifact/digest transport that works in real children, out-of-tree
`file:`-loaded data paths resolving in every required child, and a
Q-12-4-conformant profile contract so the pack fixtures' fabricated topology
can be **deleted rather than blessed**. 12d still independently owns Pets
1×1 and DAVIS 1×1 real chains, BOTH out-of-tree-loaded.

**What 12e inherits.** The identity chain it needs for the graduation claim:
parent-pinned content identity verified child-side, refusal on divergence,
and the lifecycle guarantees behind relocation-equality and
edited-plugin-refusal. 12e still independently owns the unknown fourth task,
the zero-core-edit census, the real restore with process provenance, the
executed negative controls, and the final cross-system graduation audit.

**What neither may assume.** This PR proves no scientific claim about any
task, and its anonymous fourth-shaped fixture is a deterministic stressor —
**not** a task package and **not** graduation evidence.

---

## Q. Implementation ledger

**Entry conditions (all must hold before B0 begins):**

- [x] **Operator approval of this design — GRANTED 2026-08-23** ("APPROVE
      WITH TARGETED AMENDMENTS"; all rulings applied in this revision, §A.4).
      Both real Gates are **pre-authorized** within their frozen envelopes.
- [x] **Parent §20a post-12a-merge reconciliation DISCHARGED** (2026-08-23,
      §O) — all eight `P12A-n` CONFIRMED against landed source, zero
      `MATERIAL_CHANGE`.
- [x] **Re-anchored onto landed master** `3f45c450` on branch
      `step12-pr12bc-generic-task-boundary-closure`; no duplicate 12a
      implementation history carried (the design docs were reconciled
      semantically, never cherry-picked).
- [x] **Fresh Implementation Working Rules context** — established
      2026-08-23, packet Q.0 below.

### Q.0 — Fresh-context initialization packet (2026-08-23)

A **fresh implementation session**, not the planning session and not a
continuation of PR-12a's handoff. Seven mechanical entry checks, all
read-only, all PASS:

| # | check | result |
|---|---|---|
| 1 | current branch | `step12-pr12bc-generic-task-boundary-closure` ✓ |
| 2 | `fd5ba871` present and is the frozen design commit | `docs(step12): PR-12bc REVISION 2 — FROZEN. Operator approved with targeted amendments`, authored 2026-08-22; **HEAD == `fd5ba871`** ✓ |
| 3 | `fd5ba871` descends from landed base `3f45c450` | `git merge-base --is-ancestor` ⇒ YES ✓ |
| 4 | PR-12a squash `15554174` represented in that base | `git merge-base --is-ancestor 15554174 3f45c450` ⇒ YES ✓ |
| 5 | planning delta contains no accidental implementation work | `git diff --name-only 3f45c450..fd5ba871` = **2 files, both `.md`** (`step_12_external_extensibility_graduation.md` +437 · `pr_12bc_generic_task_boundary_closure.md` +2100); **zero non-doc paths** ✓ |
| 6 | working tree clean | `git status --porcelain` empty; single worktree `/home/yuema137/SIDERIUS` ✓ |
| 7 | PRIMARY DESIGN DOC and Step-12 parent agree at `fd5ba871` | read in full (child 2100 lines) against parent §5.5 · §7 · §8 · §11.2 · §11.3 · §12-PR-12bc — T5 topology, sibling `TaskScopeCapability` (Q-12-2 = A), artifact+digest transport, §7 integrity invariant, §8 two-phase lifecycle and the two lightweight Gates all agree ✓ |

**One discrepancy recorded, non-material.** The parent's §5.5 sketch retains
**pre-12a** line anchors (`train_engine_sandbox.py:987-989`,
`task_composition.py:546-547`) where this child re-anchored to landed values
(`:1002-1004`, `:570-571`). That is precisely what §O item 7 records having
done. **The child's anchors are authoritative**; the parent's sketch is
historical. No contract differs.

**Context handoff.** `before_end_memory.md` was re-initialized **fresh** for
PR-12bc (`init_pr_handoff.py --force`), replacing — not appending beneath —
the CLOSED PR-12a handoff. Base `3f45c450`, branch as above, HEAD
`fd5ba871`, working-tree fingerprint
`bd3e625c9ea6d5e075b10911e42031bcb0c64e28fa9bda9c040f81b5b2a5ebf1`. No PR-12a
active semantic state was inherited.

**Next semantic checkpoint: B0.**

### Q.B0 — B0 audit step: §A.2 anchor re-verification at the implementation tree

Executed 2026-08-23 at HEAD `fd5ba871` (tree identical to landed master
`3f45c450` for every production file). Read-only. **Every §A.2 anchor was
opened and read**, never inferred from the diff being small.

**Result: 32 of 33 anchor rows EXACT. One row DRIFTED (line numbers only,
mechanism unchanged).**

| anchor | verdict |
|---|---|
| `core/sandbox_executor.py:852-875` `_task_data_path_argv` | EXACT — emitter keyed on `active_task_data_path()`, empty when unbound |
| `execute_tools/task_data_path.py:364-371` `transport_argv` | EXACT — takes the implementation, not a string |
| `train_engine_sandbox.py:1002-1004` the three scope params | EXACT — `task_scope`, `task_eval_scope`, `validation_requested_rows` |
| `train_engine_sandbox.py:1202-1218` cross-leg refusals | EXACT — both `ValueError`s, incl. "explicit `task_eval_scope` requires `validation_requested_rows`" |
| `train_engine_sandbox.py:1125` / `:1246` regime-A `TidmadScope` | EXACT — both `if … is None:` fallbacks present |
| **`train_engine_sandbox.py:1988-2012` the PAIRING GAP** | **EXACT and CONFIRMED** — `main()` resolves the binding at `:1988-1991` and then calls `run_experiment_streaming` at `:1995-2012` passing **none** of the three scope params |
| `pets_data_path.py:190-197` `_scope` `TypeError` | EXACT |
| `scoring_utils.py:278-335` (`:309` `scope.resolve(TIDMAD)`, `:317` `NUM_FILES`, `:328` `SEGMENTS_PER_FILE`) | EXACT — F-12bc-1 confirmed live |
| `sandbox_executor.py:1518` / `:1530` / `:1872` `validate_sample_set` call sites | EXACT, all three |
| `planning.py:397-414` two `build_sample_set` calls | EXACT — **both pass `is_trial=True`**; `:423-424` single-file `None`/`None` legal state confirmed |
| `execution.py:1054-1055` `_target_fn` | EXACT — `_base: str = TIDMAD_DATA_DIR` + inline `abra_validation_{i:04d}.h5`; root imported `:42` |
| `wrapper.py:379` measurement `TidmadScope` | EXACT |
| **`ml_hyperparameter_tune_agent.py:794-805` satellite (e)** | **DRIFTED → `:833-844`** (see below) |
| `sandbox_executor.py:1205` composed physical root | EXACT — `"data": resolve_physical_data_root()` inside the `dirs` dict `:1199-1206` |
| `sandbox_executor.py:1549` `<name>_{exp_id}.json` under `dirs["configs"]` | EXACT |
| `sandbox_executor.py:1545-1553` default-`shuffle` flag absence | EXACT — `if order_strategy != "shuffle"` / `if file_order is not None` |
| `task_composition.py:570-571` F-12-3 early return | EXACT — `if declared in registered_task_data_path_ids(): return resolve_task_data_path(...)` |
| `task_composition.py:485-496` F-12bc-2 | **EXACT, and the mechanism is sharper than the one-line summary**: `_load_symbol` DOES roll back `sys.modules` (`:492`) but rolls back **no registration**. The health loader rolls back `sys.modules` **and** `_REGISTRY` **and** `_PROVIDER_REGISTRY` (`_plugin_binding.py:333-341`). The finding is precisely "no *registration* rollback", not "no rollback" |
| `task_data_path.py:219` `_REGISTRY`, `:246-252` duplicate refusal | EXACT — one dict, no `unregister`, refusal text matches CASE A's observed message verbatim |
| `task_data_path.py:275-301` resolve truth table, `:296-300` refusal | EXACT |
| `task_data_path.py:233-239` protocol-method check | EXACT |
| `task_data_path.py:99-104` "task vocabulary deliberately ABSENT" | EXACT — the discipline `ScopeBuildRequest` must mirror |
| `_plugin_binding.py:384-398` run-scope ledger, `:590-601` `reset_run_scope` | EXACT |
| `health_checks/config.py:674-682`, `runtime_control/session.py:811-820` atomic write | EXACT — `mkstemp` + `os.replace` precedent |
| `sandbox_executor.py:902-916` `_task_manifest_argv`, `:2155` scoring-only emission | EXACT — docstring states "Only scoring needs it… Training and inference receive nothing new" |
| `denoising_score_single.py:107-117` `--task_manifest` parse | EXACT |
| `inference_single.py:396-400`, `denoising_score_single.py:267-277` resolve-to-local | EXACT |
| child bootstrap trio | EXACT in substance — **all three children import all three built-ins**; training/inference reach `tidmad_data_path` through a `from … import` symbol (`train_engine_sandbox.py:68-69`, `inference_single.py:56`) rather than a bare module import (`denoising_score_single.py:186-188` has all three bare). The census's "exactly the three built-ins" claim holds |
| `test_task_data_path_census.py:194-242` | EXACT |
| `test_step10_p1_c1_composition.py:209-225` | EXACT — `test_recomposing_in_one_process_yields_the_REGISTERED_object` |
| `test_pack_governance.py:211-221` | EXACT |
| `sandbox_executor.py:1007` / `:1045` / `:2171` `cwd=os.getcwd()`, `env=` | EXACT |
| `dataset_config.py:39-61` / `:338-357` / `:439-499` / `:571-588` / `:616-665` | EXACT |
| `sample_set_builder.py:29-129` | EXACT |
| `tidmad_data_path.py:375` `int(k)` key coercion | EXACT |

#### D-BC-11 — satellite (e)'s anchor drifted; the design's "landed-master truth" claim needs one correction

| field | value |
|---|---|
| **Decision ID** | **D-BC-11** |
| **Phase / checkpoint** | B / B0 audit |
| **Question** | §A.2 places satellite (e) at `ml_hyperparameter_tune_agent.py:794-805`; the tree has GPU-telemetry code there. Has the mechanism changed, or only the line numbers? |
| **Source evidence** | The site is at **`:833-844`**: `if trial_allowed:` → `anchor_map_path = os.path.join(sandbox.dirs["data"], "segment_anchors.json")` → `raise FileNotFoundError("Trial mode requires segment_anchors.json at …")`. At `e4cd5c18` the same block sat at `:796-803`. `git diff --stat e4cd5c18 3f45c450 -- nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` = **+62 / −10**: PR-12a DID change this file |
| **Options considered** | (i) treat as MATERIAL — a §A.2 anchor is wrong; (ii) re-anchor and record; (iii) re-run the whole source audit |
| **Chosen ruling** | **(ii)** — re-anchor satellite (e) to `:833-844` and record the correction. The mechanism is **byte-identical**: same condition, same `sandbox.dirs["data"]` join, same filename, same `FileNotFoundError` |
| **Why** | §A.3 verified empty 12a diffs for **six** files and generalized to "every §A.2 anchor is landed-master truth". Satellite (e) lives in a **seventh** file that was not on that list and that 12a did change. The generalization was slightly too broad; the *finding* is untouched. §M's B0 edge case rules this explicitly: "an anchor that has moved → re-anchor and record; if the *mechanism* changed, run the bounded forensic audit" |
| **Frozen-contract impact** | **None.** No Phase-B architecture claim depends on the line number |
| **Validation / falsifier** | B0 inverted guard (d) asserts the mechanism at its real location; it flips at B7 |
| **Downstream implication** | B7 edits `:833-844`, not `:794-805`. §D.4 and the B7 scope list are corrected below |
| **Material deviation?** | **no** |

**Anchor corrected in this document:** every reference to satellite (e) at
`ml_hyperparameter_tune_agent.py:794-805` now reads **`:833-844`**.

#### One B2-relevant fact the audit surfaced early

`DatasetProfile`'s own docstring (`dataset_config.py:443-446`) records that
`DatasetConfig` composes rather than replaces, **because the Step-00 golden
baseline pins `TIDMAD.model_dump()` field by field**. That is a concrete,
already-existing observable pin — exactly the kind of boundary §D.3a means by
"legacy byte compatibility lives at the observable transport/persistence
boundary". B2's disposition table must locate and quote that baseline rather
than assume `model_dump()` is free to move.

#### One B1-relevant fact the audit surfaced early (feeds D-BC-1)

`build_sample_set`'s parameters are
`is_trial · file_index · trial_strategy · trial_portion · target_files · seed ·
scope · profile` (`sample_set_builder.py:29-38`). Two are **not** obviously
framework vocabulary and B1's audit must rule on each: `trial_strategy`
(`"snapshot" | "anchors" | "target"` — and `"anchors"` reads the *task's*
`profile.anchor_selection_files` at `:109`) and `target_files`. `profile` is a
task-owned authority the capability holds itself, so it is a candidate for
**exclusion** from the carrier rather than inclusion.

### Q.B0 — COMPLETE. Evidence.

**Commit contents:** `tests/unit/core/test_step12_pr12bc_b0_baselines.py`
(NEW, tests only) + this document. **Zero production files.**

#### Q.B0.1 — legacy argv parity, DEFAULT `shuffle` MULTI-FILE path

Captured by RUNNING the production builders with no composition bound and a
sample set supplied. The recorded training flag set, in emission order:

```text
--model_cfg  --train_cfg  --loss_cfg  --dataset_profile_json  --exp_id
--run_name  --sandbox_dir  --file_index  --model_io_json
--sample_set_json  --runtime_observation_out
```

Two facts the capture corrected against expectation, recorded because they
would otherwise be silently assumed away:

* **`--file_index` is present even in MULTI-FILE mode.** The sample set is
  what makes a run multi-file; the flag still crosses.
* **`--runtime_observation_out` is unconditional** on the streaming path, with
  no runtime policy supplied.

Absence rules pinned for all three children (`FORBIDDEN_ON_LEGACY`):
`--order_strategy` · `--file_order_json` · `--task_data_path_id` ·
`--task_manifest` · `--data_dir` · `--raw_data_dir` and the four flags Phase B
is about to introduce (`--task_scope_ref`, `--task_scope_digest`, and the eval
pair). **Scoring is checked against the set MINUS `--data_dir`**, because
scoring's `--data_dir` is the DELIVERABLE directory — the Step-11 C4
distinction, preserved deliberately rather than asserted away.

This is **not** a duplicate of `test_step11_c0_baselines`: that baseline uses
the MINIMAL legacy signature and its own docstring says the conditional flags
are absent "because the CALLER supplied nothing, not because they were
removed", so it cannot see the ordering flags at all.

#### Q.B0.2 — legacy scope construction, MATERIALIZED

A deliberately small synthetic topology (3 files × 5 PSD segments × 40
samples, `seg_size=10` ⇒ 4 ML rows per PSD segment) through the REAL
production classes, so this is a unit test with no TIDMAD data on disk. The
h5 layout is the one the production reader walks —
`timeseries/<channel>/timeseries` (`tidmad_data_path.py:190-191`), a nested
group, not a flat one.

```text
build_sample_set(snapshot, portion=0.4, seed=1234, SMALL_PROFILE)
    = {0: [0, 3], 1: [0, 4], 2: [0, 4]}

materialize(epoch_seed=7, train_portion=1.0)
    steps                 24
    psd_segments_read      6
    file_row_ranges       {0: [0,8], 1: [8,16], 2: [16,24]}
    inputs_sha256   6c08bbb24f4f5758000ae7150223aeca0c7a86394d5c55a2c75c2fbf32bbd83d
    targets_sha256  6d79caf18802dd6467f97cc8add010546d02b19bd80d4127fc0726cf30fca76a

materialize(epoch_seed=5, train_portion=0.4)   # pins the rng DRAW
    steps                 24
    psd_segments_read      6
    file_row_ranges       {0: [0,8], 1: [8,16], 2: [16,24]}
    inputs_sha256   a30c37cb448afcba552efa2d2223d472bf625dec0de4a4a79e2343dc281763d2
    targets_sha256  01571be721144c760b7b9d91191f879f0251defe6900c82da8ca29daa8ef5e5e
```

**Why the second cell matters.** It has the SAME step count, the SAME three
files and the SAME row ranges as the first, and a DIFFERENT digest. Under
`train_portion < 1.0` the loader takes `rng.sample(...)` — an **unsorted**
draw whose order becomes the row order (`tidmad_data_path.py:176-180`). A B3
capability that re-derives the seed differently, or sorts the draw, changes
what the model sees while every config value stays identical. Only a digest
over the materialized rows can see that.

A third cell pins that **string keys materialize identically to int keys**
(the JSON round trip; `tidmad_data_path.py:375` does `int(k)`), which B4's
canonical bytes must not disturb.

#### Q.B0.3 — §J structural PRE-values (re-measured at this base)

Measured with the SAME tool used on both sides — `measure` /
`_qualified_functions` **imported** from the PR-12a C0 module, not
re-implemented, so BC-FINAL's comparison is tool-consistent. §J's table was
produced at `e4cd5c18` and PR-12a has since changed some of these files, so
**these numbers, not §J's, are the comparison baseline** — which is exactly
what §J instructs ("B0/C0 re-measure the specific files each phase touches").

| function | st | br | LOC | par | §J said |
|---|---|---|---|---|---|
| `train_engine_sandbox.py::main` | 87 | 23 | 294 | 0 | 86/23/294 |
| `train_engine_sandbox.py::run_experiment_streaming` | 174 | 62 | 728 | 19 | 175/58/728/19 |
| `sandbox_executor.py::TidmadSandbox.execute_training` | 92 | 39 | 358 | 14 | 91/38/358/14 |
| `sandbox_executor.py::TidmadSandbox.execute_inference` | 69 | 28 | 254 | 9 | — |
| `sandbox_executor.py::TidmadSandbox.execute_scoring` | 26 | 10 | 79 | 7 | — |
| `sandbox_executor.py::_task_data_path_argv` | 5 | 1 | 24 | 0 | — |
| `sandbox_executor.py::_task_manifest_argv` | 5 | 1 | 15 | 0 | — |
| `planning.py::prepare_attempt` | 116 | 32 | 471 | 7 | 116/32/471 ✓ |
| `ml_hyperparameter_tune_agent.py::HyperparamTuningAgent.run` | 258 | 69 | 1142 | 2 | 257/67/1085 |
| `execution.py::run_inference_scoring_health` | 109 | 26 | 474 | 6 | — |
| `policy.py::_resolve_sample_set_cfg` | 7 | 2 | 48 | 3 | — |
| `scoring_utils.py::validate_sample_set` | 23 | 14 | 58 | 2 | — |
| `sample_set_builder.py::build_sample_set` | 28 | 9 | 101 | 8 | — |
| `tidmad_data_path.py::TidmadTaskDataPath.training_dataset` | 4 | 1 | 15 | 3 | — |
| `tidmad_data_path.py::TidmadTaskDataPath.validation_dataset` | 13 | 5 | 37 | 3 | — |
| `tidmad_data_path.py::TIDMADEpochDataset.__init__` | 51 | 18 | 150 | 9 | — |

File sizes: `dataset_config.py` 682 · `task_data_path.py` 381 ·
`tidmad_data_path.py` 457 · `wrapper.py` 1021 · `task_composition.py` **1475**
(§J said 1362 — PR-12a's additive sections).

Two deltas against §J worth stating rather than absorbing silently:

* **counting convention** — ±1 statement and a few branch nodes on the three
  functions §J lists. The PR-12a C0 module's own docstring predicted exactly
  this ("differs from the parent §10 table by at most ±1 statement … a
  counting-convention delta"). What a pre/post comparison needs is one tool on
  both sides, which is why the import exists.
* **`HyperparamTuningAgent.run` LOC 1085 → 1142** and
  `task_composition.py` 1362 → 1475: real growth landed by **PR-12a**, not by
  this PR. The same fact D-BC-11 recorded from the other direction.

Budgets (unchanged from the PR-12a tripwire): branch +3, LOC +80, params +1.
`run_experiment_streaming` additionally carries an **exact** parameter pin at
19, because §J freezes "no new parameters — the three scope params already
exist"; B6 must USE `task_scope` / `task_eval_scope` /
`validation_requested_rows`, never add a fourth.

#### Q.B0.4 — mutation proofs: every inverted guard is load-bearing

Harness hygiene per the standing rule: each anchor's occurrence count asserted
**== 1** before mutating, every `__pycache__` cleared before and after, the
file restored and the restoration **verified by sha256**, and the full B0
module re-run green afterwards.

| # | mutation (simulates the fix its flip owner will land) | guard | verdict |
|---|---|---|---|
| a1 | `main()` forwards `task_scope=None` | (a) `test_main_passes_no_scope_parameter_today` | **RED** |
| a2 | training child grows `--task_scope_ref` | (a) `test_the_training_child_has_no_scope_argv_today` | **RED** |
| b1 | `validate_sample_set` gains a `profile` parameter | (b) `test_the_signature_has_no_profile_parameter` | **RED** |
| b2 | `validate_sample_set` range-checks a 3-file topology | (b) `test_it_accepts_a_sample_set_illegal_under_a_smaller_profile` | **RED** |
| c1 | peek path calls `validation_file_name(i)` instead of the literal | (c) `test_the_inline_tidmad_filename_literal_is_still_there` | **RED** |
| c2 | `_target_fn` defaults `_base` to a composed root | (c) `test_the_peek_root_defaults_to_the_import_time_constant` | **RED** |
| d1 | anchor path comes from a trial-anchor capability | (d) `test_the_unconditional_anchor_demand_is_still_present` | **RED** |
| d2 | anchor demand gains a capability condition | (d) `test_the_demand_is_gated_only_on_trial_allowed` | **RED** |
| e1 | measurement path calls `build_training_scope` | (e) `test_the_measurement_path_still_constructs_a_tidmad_scope` | **RED** |

**9 planted, 9 RED, 0 survived.** Baseline PASS after restore; `git status`
clean of production modifications.

**One implementation finding worth keeping.** `_target_fn` is **not**
reachable through `_qualified_functions`, which walks direct children only —
the closure is nested inside a `with`/`if` block of
`run_inference_scoring_health`. Guard (c) therefore walks the enclosing
function and **asserts it matched exactly one** `_target_fn`. Without that
count assertion the guard would have passed by matching nothing, which is
precisely the **F-P2b-4 anchored-census failure mode** (a guard green for the
wrong reason). It is also an honest statement of where the defect lives:
buried inside a large orchestrator.

#### Q.B0.5 — what B0 deliberately did NOT do

* No production file changed.
* The SampleSet byte contract was **not** re-implemented as a third pin —
  `test_step02b_b1_*` and `test_step02b_b3_*` already own the cross-site and
  compact-form properties and are run in B0's verification command. B0 adds
  only the one thing they cannot express from inside their own module: the
  recorded baseline BYTES for the fixed set this PR's own fixtures use.
* `TestPreservedCrossTaskPairingRule` is **not** an inverted guard. It pins a
  rule B6 must KEEP — one task's scope handed to another task's
  implementation raises `TypeError`. A B6 that coerced or ignored a foreign
  scope would make the transport silently wrong instead of loudly refused.

---

### Q.B1 — COMPLETE. `TaskScopeCapability` + `ScopeBuildRequest`.

**Commit contents:** `execute_tools/task_data_path.py` (additive only) +
`tests/unit/execute_tools/test_step12_pr12bc_b1_scope_capability.py` (NEW) +
this document. No call site changed; no other production file touched.

#### D-BC-1 — the `ScopeBuildRequest` field set

| field | value |
|---|---|
| **Decision ID** | **D-BC-1** |
| **Phase / checkpoint** | B / B1 |
| **Question** | What exactly does `ScopeBuildRequest` carry? §D.1 names five items *indicatively* and delegates the final set to this audit. Can the five alone reproduce `build_sample_set`? |
| **Source evidence** | `policy.py::_resolve_sample_set_cfg` (`:1140-1187`) is a pure `mode → values` function returning **exactly five keys** — `trial_strategy · trial_portion · train_portion · eval_strategy · eval_portion` — and trial vs formal differ ONLY in those values and their source (planner vs `agent_input.formal_*`). The two `build_sample_set` calls (`planning.py:397-414`) vary **strategy, portion, seed** per leg and share `target_files`, `scope`, `profile`, `is_trial=True`. `build_sample_set`'s own parameters are `is_trial · file_index · trial_strategy · trial_portion · target_files · seed · scope · profile` (`sample_set_builder.py:29-38`). The ceiling is real and upstream of materialization: `clamp_validation_scope` (`train_engine_sandbox.py:551-553`) bounds the eval SCOPE by `agent_input.validation_max_samples` **before** materializing |
| **Options considered** | (i) the frozen five only; (ii) five + `selection_strategy` + `target_partitions`; (iii) route strategy and the explicit subset through the OPAQUE `subset_ref` so the carrier stays at five |
| **Chosen ruling** | **(ii). Seven fields**: `round_kind` · `selection_strategy` · `portion` · `seed` · `max_samples` · `target_partitions` · `subset_ref` |
| **Why** | The five alone **cannot** reproduce `build_sample_set` — B3's differential oracle would be unsatisfiable. Option (iii) is worse than incomplete, it is a **regression**: the framework *already branches on strategy today*, refusing non-`snapshot` under a partial subset (`sample_set_builder.py:96-102`) and normalizing LLM plans to `snapshot` with recorded provenance (a documented DataScope invariant). Making strategy opaque would push that framework legality rule into every task or lose it. And strategy is not task vocabulary on the evidence: it names no file, channel, segment, geometry or format; it is already planner-visible (`ExperimentPlan.trial_strategy`) and operator-visible (`--formal_strategy`), so changing it would be a **planner-visible change** — itself a stop; and its task-specific CONTENT is *already* delegated — `anchors` resolves through `profile.anchor_selection_files`, the TASK's declaration, which Step 02c created precisely because "a module constant cannot follow a bound task". That is the correct shape: **framework names the strategy, task supplies the content** |
| **Deliberate EXCLUSIONS, each with its reason** | **`profile`** — the strongest anti-smuggling statement: a task that needs its topology already holds it. **`train_portion`** — a per-epoch subsample fraction consumed by `EpochSamplingParams`, not a scope-construction knob; it is one of `_resolve_sample_set_cfg`'s five keys and is nonetheless correctly absent, which is the audit doing its job. **`is_trial`** — `round_kind` has exactly two members and `single_file` (`build_sample_set(is_trial=False)`) sets both sample sets to `None` (`planning.py:423-424`), so a task is never asked. **a `leg` field** — expressed by WHICH METHOD is called, so no caller can ask `build_training_scope` for an eval scope |
| **Renaming** | `target_files` → **`target_partitions`**. `file` is the one genuinely TIDMAD-physical word in that name and Q-12-4 makes *partition* the generic term. The strategy LITERALS keep their existing spellings (`snapshot`/`anchors`/`target`): they are the existing planner-visible vocabulary for one concept, and inventing a second spelling would create two names for one thing without changing any semantics — the §D.3a "one authority" instinct applied to a Literal |
| **Frozen-contract impact** | None. §D.1's list was explicitly indicative ("its exact field set is finalized by B1's audit"), and §L lists this decision as autonomous. No framework branching on task topology, no catalog, no task-name dispatch |
| **Validation / falsifier** | A 14-marker census over `model_fields` (`seg`, `psd`, `channel`, `profile`, `dataset`, `h5`, `clip`, `frame`, `row`, `class`, `image`, …) applied to `ScopeBuildRequest` **and** `EpochSamplingParams`; an exact hardcoded field-set assertion so an unaudited field fails; explicit absence assertions for `profile` and for any `leg`-shaped field |
| **Downstream implication** | B3 maps these seven onto `build_sample_set` with no residue; B5 builds the request from `TrialConfig` + `agent_input`; `subset_ref` is where §D.4's `--data_scope` replacement lands |
| **Material deviation?** | **no** |

**One §M-vs-§L tension, resolved and recorded.** B1's own §6 says *"Ambiguity
in whether a knob is framework-level or task-level → **stop and ask** rather
than guessing."* Rev 2's §M standing rules realign §M with §L precisely
because the older wording "would have stalled implementation at every audit
step", and §L names "exact `ScopeBuildRequest` field set" as **autonomous**.
The §L material test — does this force framework branching on task topology,
or a central catalog? — is **no** on both counts. Resolved autonomously and
recorded here rather than escalated. Had the honest answer required the
framework to *inspect* a task's payload to decide a strategy, that would have
been the material case.

#### Q.B1.1 — placement, and where the refusal actually fires

**Placement (autonomous).** Both new declarations live in
`execute_tools/task_data_path.py`, not a new module: `ScopeBuildRequest` is
the construction-side sibling of `EpochSamplingParams` /
`EvalMaterializationParams`, which already live there, and the refusal belongs
beside the resolution truth table it extends (`:275-301`). A separate module
would import from this one anyway and would fragment one seam across two
files. The file grows 381 → 507 LOC and remains a DECLARATION module — no
orchestrator, no branch family, no service locator.

**When the refusal fires — a design ambiguity, resolved.** B1's plan says the
refusal happens "at composition time", while its acceptance criteria say "no
production call site changed … no current run can reach [it]". Both hold under
exactly one reading, which is adopted:

```text
B1  declares resolve_task_scope_capability(impl) beside resolve_task_data_path
    -> nothing calls it; a composed run's behaviour is unchanged
B5  calls it PARENT-SIDE while preparing an attempt
    -> "at composition, never at first spawn" becomes executable
```

The alternative — having `bind_run_task_composition` check unconditionally —
was rejected: it would refuse **every** composed run whose task lacks the
capability, including 12a's composed paths that never train. That is a
behavioural regression at B1, and B1 is a contracts-only commit. The
capability-absent message therefore states the promise it will keep
("Refused at composition, before any subprocess was launched"), and
`TestNothingIsWiredYet` pins the "no caller yet" half executably — it turns
RED the moment B5 lands, which is when it must be retired (R-11-10).

#### Q.B1.2 — two implementation details worth keeping

* **The check is CALLABILITY, not `isinstance`.** `TaskScopeCapability` is
  `@runtime_checkable` for documentation value, but a runtime-checkable
  Protocol only checks attribute **presence** — a class with
  `build_training_scope = "not a method"` passes `isinstance` and would then
  fail at call time inside a child. `declares_scope_capability` mirrors
  `register_task_data_path`'s existing structural check (`:233-239`) instead,
  and a test asserts the `isinstance` gap explicitly so the reason survives.
* **Partial declaration is refusal, not partial capability.** Three of four
  methods refuses, and the message names only the ONE that is missing —
  otherwise an operator fixes the three that already work.

#### Q.B1.4 — forward pointer

B2's audit is recorded in §Q.B2 below and was executed BEFORE any field moved,
as B2's implementation plan requires.

#### Q.B1.3 — what B1 deliberately did NOT test

No test asserts that a `Literal` rejects an unknown string, that an optional
field defaults to `None`, or that a declared type accepts its own type —
CLAUDE.md forbids pytesting what a declaration already enforces. The bounds
that ARE asserted encode a **semantic**: `portion` is half-open at 0 because a
zero portion selects nothing, and `max_samples` is `ge=1` because `0` must
never quietly become a synonym for "no ceiling" (`None`) or silently mean "no
samples".

---

### Q.B2 — the Q-12-4 disposition audit (recorded BEFORE any field moved)

Executed at `d424d1a5`. Method: `git grep` over production Python excluding
`tests/`, `scripts/` (TIDMAD operator tooling) and `tools/` (pack tooling,
never imported by production), then **every** site read. **55 production sites**
read `profile.dataset.*` / `.channels` / `.encoding`; `num_files` accounts for
**16** of them.

#### Q.B2.0 — the finding that settles the whole question

The Pets composition fixture (`tests/fixtures/step10_p1/pets/dataset_profile.json`)
declares, for a 37-way RGB **image classification** task:

```json
"dataset": { "psd_segment_length": 256, "segments_per_file": 32,
             "num_files": 4, "sampling_frequency": 1.0,
             "training_file_pattern": "pets_train_shard_{file_index:04d}.h5" },
"channels": { "input_channel": "image", "target_channel": "label" },
"encoding": { "storage_dtype": "uint8", "value_offset": 0, "num_classes": 256 }
```

`sampling_frequency: 1.0` and `psd_segment_length: 256` are values invented to
satisfy a REQUIRED TIDMAD-shaped schema. They are not wrong-ish; they are
**meaningless**, and the schema is what forced them to exist. This is Q-12-4's
premise, executable.

It also supplies the decisive evidence for the hardest row below. Pets'
`num_classes: 256` is the **pixel alphabet**; Pets' **label** count is 37,
which lives on `ModelIOContract.class_cardinality`. For TIDMAD the two
coincide (denoising to 256 quantization levels) and the framework's `3-E`
cross-check (`model_io_resolution.py:189-194`, fed by
`workflows/task_config.py:79`) compares them. So the *one* cross-task
framework consumer of `num_classes` is a consumer for which the two tasks'
semantics **diverge** — which is exactly the membership rule's test, failing.

> A field belongs in GENERIC IDENTITY only when framework infrastructure
> reasons about the fact with the **SAME semantics across materially
> different tasks**.

#### Q.B2.1 — per-consumer disposition table

Verdicts: **G** generic-identity reader · **T** genuinely task-physical ·
**L** legacy-path only. No row is unclassified.

**`num_files` — 16 production sites.** Every single one computes
`list(range(...))`, compares against it, or allocates one slot per index.

| site | use | verdict |
|---|---|---|
| `agent/schemas/hyperparam_tuning.py:2612` | `resolved != list(range(num_files))` — is the scope partial? | **G** |
| `core/resume.py:1502` | `full_scope=list(range(num_files))` | **G** |
| `execute_tools/sample_set_builder.py:87` | `scope_is_full` | **G** |
| `execute_tools/health_checks/config.py:466-467` | `scope_is_full` | **G** |
| `health_checks/pearson_dispersion.py:255` · `per_file_output_std.py:212` · `spectral_peak_ratio.py:244` | default population = every partition | **G** ×3 |
| `health_checks/_regime_a_facts.py:91` | `file_group_size=num_files` | **G** |
| `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:607` | `scope_is_partial` | **G** |
| `nodes/ml_hyperparameter_tune_agent/records.py:756` | `full_scope=list(range(...))` | **G** |
| `nodes/scoring_reference.py:36` | `tuple(range(num_files))` | **G** |
| `workflows/model_exploration.py:1936`, `:1992` | `scope_is_partial`, `full_scope` | **G** ×2 |
| `core/campaign_artifacts.py:143` | `list(range(full_scope_num_files))` — already takes an **int parameter**, not the profile | **G**, already decoupled |
| `agent/schemas/score_table.py:117-121`, `:175-179`, `:247-252` | `file_index < num_files`; `num_sampled_files <= num_files`; `len(rows) == num_files` | **G** ×3 |
| `execute_tools/scoring_helpers.py:204`, `:266-268`, `:316-318` | one slot per partition in the per-file vectors | **G** ×3 |
| `execute_tools/probe_batch.py:88` | `training_file_name(i) for i in range(num_files)` — the COUNT is generic, the NAME is not | **G** for the range, **T** for the name |
| `execute_tools/data_paths.py:270` | cache-key string `psd…_seg…_files…` | **T** |
| `agent/prompt_templates/tuner/rendering.py:87-94`, `:344` | `num_files × segments_per_file` = "total PSD segments" — **planner-visible**, must stay byte-identical | **T** |
| `execute_tools/build_anchor_map.py`, `execute_tools/array2h5.py:60` | TIDMAD tooling; `array2h5`'s is a local variable, not the field | **T** / n/a |

**Verdict: `num_files` is GENERIC.** One semantic — *the cardinality of the
partition domain `DataScope` indexes* — and it is identical for TIDMAD files,
Pets shards and DAVIS clips.

**`segments_per_file` — TASK-PHYSICAL.** `sample_set_builder.py:118-126,145`
uses it as the index space TIDMAD's SampleSet inner lists address;
`planning.py:437,442` names its own variables `train_psd_segments`;
`policy.py:112` is `segs_per_file`; `denoising_score_single.py:311` is the
TIDMAD scoring child; `rendering.py:87-94` is the planner-visible product.
`core/runtime_control/probe.py:504-513` is **already decoupled** — a pure
function taking `segments_per_file: int` as an argument, reading no profile.
**No cross-task framework consumer exists**: Pets scopes are rows and DAVIS
scopes are clip identities; neither has a per-partition segment index space.

**`psd_segment_length` — TASK-PHYSICAL.** Every consumer either computes
`psd_segment_length // seg_size` (TIDMAD's ML-segments-per-PSD geometry:
`workload_resolvers.py:53`, `tidmad_data_path.py:373`,
`train_engine_sandbox.py:1236`, `wrapper.py:372`, `estimator.py:212`),
validates divisibility against it (`policy.py:111-125`,
`proposal.py:1257-1262`, `prompts.py:743-751`), or slices h5 arrays by it
(`inference_single.py:685-736`). All TIDMAD geometry.

**`sampling_frequency` — TASK-PHYSICAL.** `_regime_a_facts.py:92` feeds a
Health fact axis (08b made Health task-declared); `spectral_peak_ratio.py:127`
is a TIDMAD check; `evaluation_metric.py:108` lists it as a required **h5
attr**; `scoring_utils.py:163` reads it *from the file*, not the profile.

**`training_file_pattern` / `validation_file_pattern` — TASK-PHYSICAL** by
definition. Sole production consumers outside `dataset_config.py` are
`training_file_name` / `validation_file_name`, whose callers are the TIDMAD
loader, the TIDMAD inference/scoring children and `probe_batch`.

**`ChannelIdentity` — TASK-PHYSICAL.** Every consumer is an h5 channel name:
the deliverable codec (`deliverable_spec.py:409-410`), the inference decode
(`inference_single.py:371`), the epoch dataset reads
(`tidmad_data_path.py:139`, `train_engine_sandbox.py:173,225`),
`probe_batch.py:130`. Pets declares `"image"`/`"label"` and DAVIS
`"context_frames"`/`"future_frames"` — same field, unrelated meanings.

**`ValueEncoding` — TASK-PHYSICAL, including `num_classes`.**
`storage_dtype` / `value_offset` drive the TIDMAD deliverable codec and h5
decode; `compute_dtype` is a training dtype. `num_classes` is the one row that
needed the membership rule applied rather than assumed, and §Q.B2.0 records
why it fails it: its single framework consumer is the `3-E` cross-check, and
Pets' 256 (pixels) versus its 37 labels proves the semantics are **not** the
same across tasks. §D.3's own instruction for this row — "route to task
topology **or to an already-owning typed contract (e.g. `ModelIOContract`)`**"
— is satisfied by routing to task topology, with `ModelIOContract` continuing
to own the model-side cardinality it already owns.

**`anchor_selection_files` / `health_peek_files` — GENERIC IDENTITY, and
already correctly shaped.** Framework infrastructure consumes them with one
semantics everywhere — "the task's declared representative partitions" for
`build_sample_set`'s `anchors` (`sample_set_builder.py:109`) and "the task's
default peek partitions" for Health — while the CONTENT is the task's own
declaration. Step 02c created exactly this split, for exactly this reason
("a module constant cannot follow a bound task"). They are lists of partition
indices, so they live in the same index domain as `partition_count`.

#### Q.B2.2 — D-BC-2's concrete contract, derived from the table

| field | value |
|---|---|
| **Decision ID** | **D-BC-2 (concrete contract)** |
| **Phase / checkpoint** | B / B2 |
| **Chosen ruling** | **Generic identity = `partition_count` + `anchor_selection_files` + `health_peek_files`. Everything else — `psd_segment_length`, `segments_per_file`, `sampling_frequency`, both file patterns, `ChannelIdentity`, `ValueEncoding` — is OPAQUE task-owned topology.** |
| **Why this is MINIMAL and not merely small** | Each of the three survives the membership rule with production evidence: 16 sites reason about the partition count with one semantics; the two declared lists are consumed by framework infrastructure with one semantics and were already split from framework constants by Step 02c. Every excluded field has a named production consumer that is TIDMAD geometry, a TIDMAD file name, an h5 channel, an h5 attr, or a planner-visible TIDMAD product |
| **What is NOT built** | No `TidmadTopology \| PetsTopology \| DavisTopology` union · no "N optional built-in topology blocks" (N=1 is the same defect — it is what forces Pets to invent `sampling_frequency: 1.0`) · no second configuration hierarchy · no task-name dispatch |
| **Frozen-contract impact** | None — this is the concrete contract §A.4/§D.3 delegated to B2 |
| **Material deviation?** | **no** — the decomposition satisfies every consumer without core task dispatch, which is the one §L material case for this commit |

#### Q.B2.3 — the observable byte boundary, located and quoted

§D.3a withdraws internal `model_dump()` parity but keeps the byte contract at
the **observable** boundary. That boundary is not hypothetical, and B2 must not
guess where it is:

* `tests/unit/execute_tools/test_step00_dataset_baselines.py:76` —
  `assert TIDMAD.model_dump() == { … }`, the Step-00 golden this profile's own
  docstring (`dataset_config.py:443-446`) says `DatasetConfig` composes rather
  than replaces in order to preserve;
* `examples/tidmad/resolved/dataset_profile.json` — the committed resolved
  snapshot, whose exact key set and values are the `--dataset_profile_json`
  wire form;
* `tests/unit/execute_tools/test_step03_m5_input_dtype_resolution.py:314` —
  writes `TIDMAD.model_dump(mode="json")` to a file a child then loads.

**These bytes are preserved by a bounded compatibility projection.** The
internal model is the one authority; the projection exists only at the
transport/persistence edge.

#### Q.B2.4 — implementation shape and why B2 lands as two green commits

The migration is 55 sites. CLAUDE.md forbids a big-bang rewrite and every
semantic commit must be independently green, so B2 splits at a
green-preserving boundary (the standing "a planned commit may split at a clean
boundary" rule):

```text
B2a  ADD partition_count (required generic identity) + the opaque topology
     carrier + TIDMAD's typed view + the compatibility projection.
     Migrate the 16 GENERIC readers to partition_count.
     dataset/channels/encoding stay temporarily -> tree GREEN.

B2b  Migrate the ~39 task-physical readers onto TIDMAD's view, then REMOVE
     dataset/channels/encoding from DatasetProfile -> ONE authority.
     Tree GREEN, and acceptance criterion 3 is discharged HERE.
```

B2a alone would leave two live authorities, which is why the DoD belongs to
B2b: the §F checkpoint's item 6 is satisfied only when both have landed.

#### Q.B2.5 — one finding recorded, NOT repaired here

`workflows/task_config.py:79` calls the dataset side "the single cardinality
authority" and feeds the `3-E` cross-check. On a composed **Pets** run that
compares the model's label count against the fixture's pixel alphabet. Whether
`3-E` should compare those two facts at all is a **model-contract** question,
not a topology question, and repairing it would pull an unrelated semantic
into this commit. **Recorded as carried debt**; B2 changes only where the
value comes FROM, never what the cross-check does with it.

---

### Q.B2.6 — B2 COMPLETE. Implementation and evidence.

**Landed as ONE commit, not the two §Q.B2.4 planned.** Recorded as a bounded
deviation from my own staging plan (not from the frozen design): the B2a/B2b
split would have required `dataset` / `channels` / `encoding` to coexist with
`topology` for one commit, i.e. **two live authorities carrying the same
facts** — exactly what §D.3a forbids, introduced deliberately and then
removed. A single green commit is the honest shape. Every affected owner suite
is green at it.

#### What changed

```text
DatasetProfile   partition_count : int          GENERIC IDENTITY
                 anchor_selection_files         GENERIC IDENTITY (task content)
                 health_peek_files              GENERIC IDENTITY (task content)
                 topology : dict[str, Any]      OPAQUE — never inspected
```

* **`DataScope.resolve(partition_count)` / `is_full(partition_count)`** —
  the parameter was a whole `DatasetConfig` and the body only ever read
  `num_files`. Taking the config made a purely generic operation look as if it
  needed TIDMAD's geometry. 9 production call sites migrated.
* **`tidmad_topology(profile) -> TidmadTopology`** and the regime-A hop
  `resolve_tidmad_topology()` — TIDMAD's typed view over its own opaque
  payload, **fail-closed** with a named refusal when a profile declares no
  TIDMAD sections.
* **55 production reads migrated by ownership**: 16 generic → `partition_count`,
  39 task-physical → the typed view. `DatasetConfig` / `ChannelIdentity` /
  `ValueEncoding` remain DECLARED in `dataset_config.py` (moving them is pure
  import churn with no semantic gain) but are no longer FIELDS of the profile,
  and the census asserts no generic module reads them.
* **Bounded legacy adapters, one definition of the pre-B2 shape**
  (`_LEGACY_SECTIONS`, read by three call sites): the wire reader
  (`model_validator(mode="before")`), the wire writer (`to_wire()`), and
  `model_copy`.

#### Two defects found and fixed during implementation, both worth keeping

* **`to_wire()` aliased the profile's own dicts.** `DatasetProfile` is frozen;
  a plain `dict` inside it is not. Returning the profile's own sections let
  `TIDMAD_PROFILE.to_wire()["dataset"].update(...)` — the obvious way to build
  a variant, and what `tests/helpers/two_family_profile.py` does — **mutate
  the SHIPPED profile for the rest of the process**. It silently poisoned every
  later test in the same interpreter and produced ~70 order-dependent failures
  that all passed in isolation. Fixed by deep-copying in BOTH directions;
  pinned by two tests.
* **`model_copy(update={"dataset": …})` became a silent no-op.**
  `model_copy` bypasses validation entirely in Pydantic v2, so after the split
  it would have returned a profile still claiming 20 partitions with **no error
  anywhere** — precisely the class of quiet wrongness this contract exists to
  remove. `DatasetProfile.model_copy` now translates the legacy section names
  and carries `partition_count` along with `num_files`. This is a correctness
  fix, not a convenience.

#### Tests UPGRADED rather than patched, each with its reason in-test

* `test_step02a_c2_profile_injection::…_shipped_tidmad_dataset_unchanged` —
  asserted `is TIDMAD` (object identity), which only held while `dataset` was
  a field. Now asserts VALUE equality plus the wire/golden link, which is the
  property that actually matters.
* `test_dataset_contract` ×2 — probed the pattern seam by
  `monkeypatch.setattr(TIDMAD, "training_file_pattern", …)`, which worked only
  because `TIDMAD_PROFILE.dataset` **was** the singleton. That aliasing is
  gone, so the monkeypatch would have silently probed nothing. Upgraded to
  DECLARE the pattern and BIND the profile — the production resolution path,
  and a stronger test than the original.
* `test_step02a_c3_profile_transport` and
  `test_step03_checkpoint_c_live_boundary` — built contrast encodings
  (`int16` + `num_classes=512`; `int8` + `num_classes=16`) that are
  **physically impossible** and survived only because `model_copy` skipped
  validation. The typed view re-validates what it decodes, so both fixtures
  became declarations that could actually exist. The claims under test are
  unchanged.
* `test_step11_c8_invariants_resume` ×2 — source censuses naming the exact
  expression the launcher/workflow use. The PROPERTY (read the run's OWN
  profile, never the TIDMAD import) is untouched; only the expression moved.

#### Acceptance criteria

- [x] **Legacy externally-observable transport bytes pinned** —
      `json.dumps(TIDMAD_PROFILE.to_wire())` equals the hardcoded pre-B2
      document **including key order**; the parent writes `to_wire()` and the
      composition-fingerprint payload does too, so the composed fingerprint
      does not move.
- [x] **Legacy behaviour identical** — every B0 fixture green; selection,
      anchors and scope resolution reproduce their recorded values.
- [x] **Exactly ONE internal semantic authority** — census over
      `DatasetProfile.model_fields`: exactly the four audited names, and
      `dataset` / `channels` / `encoding` / `num_files` / `psd_segment_length`
      are each asserted ABSENT.
- [x] **No generic consumer reads task topology** — a census over 9 NAMED
      generic-core modules in BOTH directions (no call to the decoder, no
      `.topology[` subscript), **plus a non-vacuity plant** proving the census
      can see a real reader (`train_engine_sandbox.py`).
- [x] **A profile with no PSD/segment/pattern values** constructs, validates,
      is consumed by every generic-identity reader, round-trips without
      inventing topology, and gets a NAMED refusal from TIDMAD-physical code.
- [x] **Every consumer has a recorded verdict** — §Q.B2.1, no unclassified rows.
- [x] **No second configuration hierarchy** — one profile, one opaque payload,
      no per-task block, no catalog.

#### Validation (targeted to the changed authority and its consumers)

| suite | result |
|---|---|
| `tests/unit/execute_tools/test_step12_pr12bc_b2_topology_contract.py` (NEW) | **44 passed** · 0.13 s |
| `tests/unit/execute_tools` | **1915 passed**, 2 skipped · 122 s |
| `tests/unit/core` + `workflows` + `guardrails` | **3768 passed** · 191 s |
| `tests/unit/agent` + `nodes` + `examples` | **4889 passed** · ~554 s |
| `ruff check` (incl. an explicit `--select F821` sweep) + `ruff format --check` | clean |

The suites above are the CONSUMERS of the changed authority, not a full-suite
run: a `DatasetProfile` schema change genuinely reaches all four. `pyright`
remains CI-owned (the host's Node cannot run the bundled binary).

#### Structural note (§J)

`dataset_config.py` 682 → 941 LOC. It gains no branch family and no
orchestration: the growth is one carrier field, three small bounded adapters
and the typed view, each independently testable. `DataScope.resolve` **lost**
a parameter's worth of coupling. §J's constraint for this file — "Q-12-4 must
not turn this into a topology catalog; the opaque payload adds no branch" — is
satisfied by construction: the payload is `dict[str, Any]` and nothing
branches on its shape.

#### Carried forward, unchanged

`workflows/task_config.py:79` still calls the dataset side "the single
cardinality authority" and feeds the `3-E` cross-check, so a composed Pets run
compares a label count against a pixel alphabet. That is a **model-contract**
question; B2 changed only where the value comes from.

---

### Q.B3 — COMPLETE. TIDMAD capability + differential oracle.

**Commit contents:** `execute_tools/tidmad_data_path.py` (capability methods +
the `_TIDMAD_SCOPE_KIND` tag), `execute_tools/task_data_path.py` (one field —
see D-BC-1a), the B1 census update, and
`tests/unit/execute_tools/test_step12_pr12bc_b3_tidmad_capability.py` (NEW).
`build_sample_set` itself is **untouched**.

#### D-BC-1a — `task_parameters`, a recorded extension of D-BC-1

| field | value |
|---|---|
| **Decision ID** | **D-BC-1a** (extends D-BC-1) |
| **Phase / checkpoint** | B / B3 |
| **Question** | `TidmadScope` requires `seg_size`. It is the PLANNER's per-attempt model choice (`plan.model_cfg["segmentation_size"]`), it is task vocabulary, and it is not on `ScopeBuildRequest`. How does the capability get it? |
| **Source evidence** | `TidmadScope.seg_size` is required (`tidmad_data_path.py:310`) and drives both `TIDMADEpochDataset(seg_size=…)` and `ml_segs_per_psd = psd // seg_size`. The child already receives it via `--model_cfg`, but the PARENT builds the scope, so the parent must supply it. **Why D-BC-1's method could not see it**: that audit derived the field set from where trial and formal DIFFER (`policy.py:1164-1179`), and `seg_size` is identical in both rounds — a per-attempt value that never varies BY ROUND is precisely the blind spot of a differ-by-round audit |
| **Options considered** | (i) name `seg_size` on the carrier — fails B1's own census, and would be TIDMAD vocabulary in a framework type; (ii) let the child fill it in — then the transported scope is INCOMPLETE and "the child consumes the scope it was handed" stops being true; (iii) take it at CONSTRUCTION via the manifest's task config — wrong lifetime, it is per-attempt not per-run; (iv) ONE opaque per-attempt payload |
| **Chosen ruling** | **(iv)** — `task_parameters: Mapping[str, Any] = {}`, OPAQUE. The framework transports it and never interprets it: the `subset_ref` pattern, for values that vary per ATTEMPT rather than per run |
| **Why it is not a config bag** | It carries only per-attempt values a task needs to BUILD A SCOPE; it is opaque by contract; and a framework site reading inside it fails the genericity census. Its name carries no task vocabulary, and its CONTENTS are never inspected by the framework |
| **Frozen-contract impact** | None. §L names the exact `ScopeBuildRequest` field set **autonomous**, and §D.1 said the set is "finalized by B1's audit" — this is that audit corrected by implementation evidence, recorded rather than silently applied |
| **Validation / falsifier** | B1's exact-field-set census updated in the same commit (8 names, hardcoded) + a new test that the carrier validates NOTHING inside the payload; B3 asserts a missing or nonsense `seg_size` is a NAMED refusal, never a guessed default |
| **Material deviation?** | **no** |

#### The oracle

`(round_kind, strategy, portion, seed, subset_ref, target_partitions)` —
**11 cells**, covering trial AND formal, all three strategies, an explicit
target list, and two operator subsets. For every cell the capability-built
scope **deep-equals** what `build_sample_set` produces from the same inputs.

**The expected side is an independent path.** It comes from
`build_sample_set` — which this PR does not touch — never from a second call
to the capability. Two calls to one function prove only that the function is
deterministic (§25).

**`seed=None` is deliberately NOT in the matrix.** `build_sample_set`
documents it as non-deterministic, so two independent draws legitimately
differ and an equality oracle over them would assert the opposite of the
contract. Its own properties are asserted separately: eight unseeded draws are
not all identical (**the capability did not quietly substitute a default
seed**, which would make an unseeded attempt look reproducible when the
contract says it is not), and the shape still obeys the declared topology.
Found by the oracle failing on that cell — the honest reading was that the
cell was wrong, not the code.

#### Serialization

Canonical: `json.dumps(..., sort_keys=True, separators=(",", ":"))`, asserted
**byte-wise** against a literal, plus a stability test built from dicts
inserted in opposite orders. The payload is self-identifying
(`kind: "tidmad_scope_v1"`), so a **foreign** scope is refused BY KIND rather
than by whichever field happens to be missing first — a Pets payload and a
truncated TIDMAD payload are different problems and read differently.
Fail-closed cases each named: foreign kind · untagged · truncated (per field)
· non-JSON · JSON scalar · malformed key · `seg_size=0`.

#### Parity, on rows rather than config

A round-tripped scope materializes the digests **B0 recorded before any of
this existed** (§Q.B0.2): 24 steps, 6 PSD segments read, identical
`file_row_ranges`, `inputs_sha256 6c08bbb2…`, `targets_sha256 6d79caf1…`.
Config-value equality could not see key-type drift, a reordered file loop or a
differently-derived seed; a digest over the visited rows can.

#### Acceptance criteria

- [x] Capability-built deep-equals legacy-built for every matrix cell,
      **trial and formal**.
- [x] A round-tripped scope materializes the identical visited sample sequence
      and step count as B0's baseline.
- [x] `serialize_scope` output is canonical — asserted byte-wise.
- [x] Exactly one `build_sample_set` authority remains — census asserts the
      capability CALLS it and that no selection primitive (`rng.sample`,
      `random.Random`, `anchor_selection_files`) was copied into `_build_scope`.
- [x] The framework legality rule reaches THROUGH the capability unchanged —
      a partial subset with a non-`snapshot` strategy still refuses.

#### Validation

`test_step12_pr12bc_b3_tidmad_capability.py` **57 passed** · 1.21 s. Targeted
regression (B0 + B1 + B2 + B3 + `test_tidmad_data_path` +
`test_sample_set_builder` + `test_d14_tidmad_parity`): **224 passed** · 4.29 s
· rc 0. `ruff check` + `ruff format --check` clean. Deliberately NOT re-run:
the broad subtrees B2 needed — nothing here changes the profile schema, and
the final CI owns broad regression.

---

### Q.B4 — COMPLETE. Scope artifact + digest ABI. **FROZEN for the rest of the PR.**

**Commit contents:** `execute_tools/scope_artifact.py` (NEW) +
`tests/unit/execute_tools/test_step12_pr12bc_b4_scope_artifact.py` (NEW). No
existing production file changed — the ABI has no consumer until B6.

**D-BC-4 (artifact filename/layout) — RESOLVED, autonomous.**
`<configs_dir>/<stem>_<exp_id>.json`, the existing parent→child convention
(`core/sandbox_executor.py:1549`). Two stems, `task_scope` and
`task_eval_scope`: **separate artifacts, not two payloads in one file**,
because the two legs are transported by separate flags and either may be
absent — a combined file would make "eval scope absent" and "eval scope empty"
the same on-disk state. Per-`exp_id` keying is what makes two concurrent
attempts disjoint, asserted rather than assumed.

**The three properties the obvious implementation gets wrong**

* **The digest is RECOMPUTED, never re-read.** A child trusting a digest
  stored *inside* the artifact would be asking the artifact to vouch for
  itself. The expected digest arrives out of band, on argv.
* **Verification precedes deserialization, structurally.** There is no
  "read without checking" entry point: `read_scope_artifact` returns the
  payload only after the bytes match, so a caller *cannot* deserialize first.
  Proven with a **spy that fails the test if the parser is reached at all** —
  the acceptance criterion, not an inference from call order.
* **The write is ATOMIC** (`mkstemp` + `os.replace` in the same directory),
  per D-BC-7. Deliberately unlike the `--sample_set_json` sibling: that file's
  BYTES are a contract but nothing reads it concurrently with its writer. A
  scope artifact is parent-written and child-read with identity carried
  separately, so a torn read must be impossible rather than unlikely. Recorded
  at the call site so the divergence is visible, not silently inherited.

**Determinism is asserted ACROSS PROCESSES**, in a fresh interpreter — the
only place it matters. An in-process double-call would pass even if the hash
were seeded per-process, which is exactly the defect that would surface only
at the boundary. The empty-string digest is hardcoded rather than recomputed
with the expression under test.

**Scope opacity holds one layer out.** The module never parses, inspects,
canonicalizes or validates the payload — the TASK owns canonicality
(B3's `serialize_scope`), the framework owns bytes and a hash. Asserted by an
AST census that no `json.load*` call exists in the module, and by a census
that no other scope-carrying production module hashes anything directly.

**`ScopeEvidence`** is the additive attempt-scope stamp (`leg` · `ref` ·
`digest`, 64 hex enforced) — §D.2's "one evidence authority", so a Gate can
**cite** which scope a child executed instead of inferring it. No
persisted-global-schema change.

#### Acceptance criteria

- [x] Same scope → identical bytes and digest **across two processes**.
- [x] A one-byte mutation causes refusal, and a **spy proves
      `deserialize_scope` was NOT invoked**.
- [x] An interrupted write leaves either the old file or none — never a
      partial artifact, and no `.tmp` debris.
- [x] Exactly one canonicalization/digest authority — census; a second one in
      a scope-carrying module turns it RED.
- [x] An unwritable directory refuses **at the parent**, and the message says
      so, so a log reader knows no GPU minute was spent.

**Validation:** B4 **23 passed** · 0.19 s; with B3 **80 passed** · 1.33 s ·
rc 0. `ruff check` + `format --check` clean.

---

### Q.B5 — audit finding: B5's spy criterion belongs to B6

**D-BC-13 — the composed path cannot stop building sample sets at B5.**

| field | value |
|---|---|
| **Decision ID** | **D-BC-13** |
| **Phase / checkpoint** | B / B5 audit |
| **Question** | B5's acceptance says "for a composed attempt the scopes come from the capability — proven by a spy asserting `build_sample_set` is **not** called on that path". Can the composed path stop producing legacy sample sets at B5? |
| **Source evidence** | `PreparedAttempt.train_sample_set` / `eval_sample_set` (`contracts.py:213-214`) are consumed by the TRAINING spawn (`runtime.py:875,906,931` → `execute_training(sample_set=…)`), by the INFERENCE spawns (`execution.py:992`, `:1038`), and by the `expected_validation` decision (`execution.py:716`: `eval_sample_set is not None`). A composed run reaches every one of those today |
| **Options considered** | (i) make the composed path's sample sets `None` at B5 — **breaks composed training, inference and the validation-expectation decision** before any replacement exists; (ii) merge B5 into B6 as one commit; (iii) B5 acquires the scopes ADDITIVELY and B6 flips the consumers |
| **Chosen ruling** | **(iii).** B5 introduces the typed acquisition boundary and, on the composed path, acquires the task-built scopes through the capability. The legacy sample sets are unchanged on BOTH paths, because their consumers are unchanged. **B6 owns the flip**: when the training child consumes the transported scope, the composed path stops needing the training sample set, and that is where the "`build_sample_set` not called" spy belongs |
| **Why not (ii)** | B6 is already the largest wiring commit (parent emitters + child argv + `main()`'s call site + the pairing-gap flip). Folding acquisition into it would make the one commit that closes the PR's headline defect unreviewable, and would merge two failure modes — "the right scope is built" and "it reaches the child" — that the design deliberately separates |
| **Frozen-contract impact** | None. The frozen requirement is that a composed run's scopes come from the bound implementation; that is true from B5. Only the *evidence for the negative half* moves one commit later, and it moves to the commit where it is actually true |
| **Validation / falsifier** | B5 proves the POSITIVE half (the capability IS called, with a request derived from the same values legacy uses) and un-composed byte-parity against B0. B6 carries the spy and flips B0's guard (a) |
| **Downstream implication** | The B6 checklist gains the spy criterion. Recorded here so it cannot be lost |
| **Material deviation?** | **no** — a bounded resequencing of one acceptance item between two adjacent commits of the same phase, with the reason recorded |

### Q.B5 — COMPLETE. Tuner composed-path scope acquisition.

**Commit contents:** `nodes/ml_hyperparameter_tune_agent/scope_acquisition.py`
(NEW, node-private), `planning.py` (one CALL + the additive field),
`contracts.py` (`PreparedAttempt.task_scopes`),
`execute_tools/dataset_config.py` (`DataScope.to_cli`), and
`tests/unit/nodes/ml_hyperparameter_tune_agent/test_step12_pr12bc_b5_scope_acquisition.py`
(NEW).

**The boundary.** `acquire_attempt_scopes(...)` — a CALLED unit, never a
branch family inside `prepare_attempt` (§J). It reads **no ambient state**:
every input is a value `prepare_attempt` already holds, so what a scope was
built FROM is visible at the call site instead of resolved somewhere inside.
Discrimination is `agent_input.task_composition_ref is not None` — composition
PRESENCE, the signal PR-12a established — and a census asserts no task name
appears in the module's executable code.

**`DataScope.to_cli()`** was added as the symmetric inverse of the existing
`from_cli`: the operator's partition restriction crosses to a task as an
OPAQUE string, so the framework needed a way to spell a scope it already
holds. `None` for the complete dataset, deliberately not `""`.

**Two legs, two requests, each with its OWN strategy / portion / seed** — the
split `planning.py:397-414` already makes. A boundary that fed both legs one
seed would make train and eval select identically and nothing would raise. The
07c C6 row ceiling bounds the **eval leg only**; a training scope carrying it
would silently shrink training and the run would look like it had merely
chosen a smaller plan.

**`single_file` acquires nothing**, even when composed — that legacy mode sets
both sample sets to `None` and has no round to build a scope for.

**A composed run with no bound data path is a named wiring contradiction**,
not a regime-A fallback: the composition is what declared the task, so
silently building TIDMAD's scope there would be the exact class of quiet
wrongness this PR removes.

#### §J structural delta — ZERO branch growth

| function | before | after |
|---|---|---|
| `planning.py::prepare_attempt` | 116 st / **32 br** / 471 LOC / 7 par | 117 / **32** / 493 / 7 |
| `scope_acquisition.py::acquire_attempt_scopes` | — | 11 / 3 / 89 / 12 (new, focused) |

The branch count is **unchanged**. It was briefly +2 when the call site
normalized `target_files or ()` and `data_scope.to_cli() if …` inline; both
normalizations moved INTO the boundary, which is where they belong and which
returns `prepare_attempt` to its baseline exactly.

#### Acceptance criteria

- [x] Un-composed attempts are byte-identical — B0's baselines and the whole
      tuner-node suite green; the boundary never touches the binding on that
      path (asserted, not assumed).
- [x] A composed attempt's scopes come from the capability, with a request
      derived from the same values legacy uses.
- [x] `prepare_attempt`'s branch count does not grow by a new family —
      **it does not grow at all**.
- [x] Trial **and** formal composed attempts both route through the capability.
- [x] Capability-absent surfaces B1's named refusal at the attempt boundary
      without a crash.
- [x] "`build_sample_set` is NOT called on the composed path" — **moved to B6
      by D-BC-13**, recorded above, because the legacy sample sets still have
      live consumers until B6 flips them.
      → **DISCHARGED at B6**: `test_the_engine_prefers_a_transported_scope_over_regime_A`
      proves the regime-A construction is not reached when a scope is
      transported, and `test_the_regime_A_fallback_still_exists_for_legacy` /
      `test_an_absent_pair_leaves_regime_A_alone` prove the legacy path keeps
      it. Both halves, because "not called" without "still there for legacy"
      would be a removal, not a bypass.

**Validation:** B5 **13 passed** · 1.5 s; with B0 + the node public-boundary
guard **80 passed**; `tests/unit/nodes` + `tests/unit/agent/tune_ml_hyperparam_agent`
**1367 passed** · 491 s · rc 0. `ruff check` + `format --check` clean.

---

### Q.B6 — audit. Which children need a scope, and what replaces the deferred spy.

#### Which children need a scope — the verdict, recorded not assumed

| child | verdict | evidence |
|---|---|---|
| **training** | **NEEDS IT** | `run_experiment_streaming` accepts `task_scope` / `task_eval_scope` (`:1002-1004`) and falls back to building `TidmadScope` when they are absent (`:1125`, `:1246`). This IS the pairing gap |
| **inference** | **does NOT** | it consumes `--sample_set_json` and iterates `sample_set.items()` directly (`inference_single.py:579-582`, `:675`). It never constructs a scope object and never calls `training_dataset`; its `data_path` use is `write_deliverable` only (`:396-400`) |
| **scoring** | **does NOT** | it builds its own single-file sample set from the profile (`denoising_score_single.py:311`) and reaches the data path only through `read_evaluation_payload` (`:267-277`) |

**B6 therefore transports to TRAINING ONLY.** Extending to a child that has no
scope consumer would be a seam without a consumer — the anti-pattern the
roadmap names at §0.8.

#### D-BC-14 — the "`build_sample_set` not called" spy is RETIRED as unsatisfiable, and replaced

| field | value |
|---|---|
| **Decision ID** | **D-BC-14** (supersedes the deferral in D-BC-13) |
| **Phase / checkpoint** | B / B6 audit |
| **Question** | D-BC-13 moved B5's "a spy asserts `build_sample_set` is NOT called on the composed path" to B6. Does it fit at B6? |
| **Source evidence** | It does not, and the reason is structural. Dropping the composed path's `sample_set` would (a) put the training child into its **legacy single-file branch** — `train_engine_sandbox.py:1981` treats `sample_set is None` as exactly that, a different code path, not "a scope arrived instead"; (b) remove the input `_resolve_guardrail_steps` prices the attempt from (`runtime.py:875`); (c) break both inference spawns (`execution.py:992`, `:1038`), which have no scope concept at all (see the table above); and (d) invert the `expected_validation` decision (`execution.py:716`). Satisfying the spy therefore requires migrating the child's multi-file branch detection, the guardrail resolver and the whole inference path — none of which is in Phase B's scope |
| **Options considered** | (i) keep deferring it to B7/B8 — it does not fit there either, for the same reasons; (ii) pull the inference + guardrail migration into B6 — that is the scope explosion §L warns about and would make the PR's headline commit unreviewable; (iii) retire the criterion and assert the substantive claim where it actually executes |
| **Chosen ruling** | **(iii).** The criterion is retired, and B6's acceptance criterion #4 — already in the frozen design — carries the claim: **the child never builds a scope it was not handed on the composed path**, proven by asserting the regime-A `TidmadScope` branches (`:1125`, `:1246`) are NOT reached |
| **Why this is not a weakening** | The frozen requirement is that *a composed run's scopes come from the bound task*. The spy was an INDIRECT proxy for that, measured at the parent; criterion #4 measures the same claim **at the point of execution**, in the child, which is strictly stronger evidence. A parent that still calls `build_sample_set` for an unrelated consumer does not make the executed scope any less task-built |
| **Frozen-contract impact** | None. No frozen invariant mentions `build_sample_set` call counts; §D.4's requirement is "replacing the unconditional `build_sample_set` **on the composed path**" for SCOPE CONSTRUCTION, which B5 did |
| **Validation / falsifier** | B6 asserts the composed child's engine receives the transported scope objects and does NOT enter either regime-A branch; B0's guard (a) flips |
| **Downstream implication** | Retiring the legacy sample set from the composed path is a genuine follow-up — it needs the inference path, the guardrail resolver and the child's branch detection to move together. **Recorded as carried debt for 12d**, which owns the real contrast execution those consumers must serve |
| **Material deviation?** | **no** — an acceptance criterion is replaced by a stronger one measuring the same frozen claim, with the evidence recorded. No frozen invariant, schema, default or LLM-facing contract moves |

### Q.B6 — COMPLETE. **The pairing gap is closed.**

**Commit contents:** `core/sandbox_executor.py` (`_task_scope_argv` + one
`execute_training` parameter + one splatted `cmd.extend`),
`execute_tools/train_engine_sandbox.py` (`_load_transported_scope` + four argv
flags + the `main()` call site), `agent/skills/training_skill/wrapper.py` (one
forwarded kwarg), `nodes/ml_hyperparameter_tune_agent/planning.py` (one
`active_params` key), B0's guard (a) **RETIRED**, and
`tests/unit/core/test_step12_pr12bc_b6_scope_transport.py` (NEW).

**The gap, and what closed it.** The training child already transported a
BINDING and never a SCOPE, so `main()` handed `run_experiment_streaming` none
of its three scope parameters, the engine fell into its regime-A branch and
built a `TidmadScope`, and a non-TIDMAD implementation refused it with a
`TypeError`. Now the parent writes the task's canonical bytes to an atomic
artifact and emits `--task_scope_ref/_digest` (+ the eval pair) **only when
scopes were acquired**; the child verifies the digest, resolves the
transported implementation, deserializes **inside the binding** — the bytes
must be parsed by the implementation that wrote them — and passes the objects
into the engine, whose `is None` guards then leave regime-A unreached.

**R-11-10 discharged.** B0's inverted guard (a) fired with exactly its
intended message and was **deleted**, not twinned; the positive contract lives
in B6's module, where the behaviour does.

**Parity, measured as B6's OWN delta.** Both sides of the argv comparison have
a data path bound, so `--task_data_path_id` — Step-10's binding transport,
which is not B6's — cancels. What remains is **exactly the four scope flags
and nothing else**. A run with a binding but no acquired scopes emits none of
them: the emitter keys on the SCOPES, not on the binding. An un-composed run
emits nothing at all, and the default `shuffle` path still emits no ordering
flags. *(The first cut of that test asserted against an unbound baseline and
failed by flagging `--task_data_path_id`; the test was wrong, not the code.)*

**`validation_requested_rows` — audited, and correctly NOT threaded.** The
engine's cross-leg refusals (`:1202-1218`) are: `eval_sample_set` **and**
`validation_requested_rows` together ⇒ raise; `task_eval_scope` **without**
`validation_requested_rows` **and without** `eval_sample_set` ⇒ raise. Under
D-BC-13 the composed path still supplies `eval_sample_set`, so it is on the
regime-A DECLARATION leg where the preflight is the only authority and
`validation_requested_rows` must stay `None`. Threading it would have TRIPPED
the first refusal. Both guards are satisfied exactly as written, neither is
weakened, and the design's "this is not optional" note applies to the
pure-scope leg that arrives when the legacy sample set is finally retired
(carried debt, D-BC-14).

#### Acceptance criteria

- [x] Un-composed training argv byte-identical to B0's fixture, ordering flags
      still absent on the default path.
- [x] A composed run's training argv contains exactly the new flags and
      nothing else new.
- [x] The child CONSUMES the transported scope — verified, deserialized by the
      bound implementation, and passed into the engine.
- [x] The child never builds a scope it was not handed on the composed path —
      both regime-A constructions are `is None`-guarded (D-BC-14's replacement
      for the retired parent-side spy, and stronger: it is measured where the
      scope executes).
- [x] B0 guard (a) flips — and is retired.
- [x] Digest mismatch refuses **before** deserialization — a spy proves the
      parser is never reached.
- [x] A half-supplied ref/digest pair is refused rather than proceeding on
      whichever half arrived.
- [x] A wrong-task payload keeps the implementation's refusal (the pairing
      RULE survives closing the pairing GAP).
- [x] `run_experiment_streaming` gained NO parameter — asserted at exactly 19.
- [x] The payload never rides argv — asserted on the emitted tokens.

**Transport verdict, recorded not assumed:** TRAINING ONLY. Inference consumes
`--sample_set_json` and iterates it directly, never constructing a scope;
scoring builds its own single-file set and reaches the data path only through
`read_evaluation_payload`. Extending to either would be a seam without a
consumer.

**One R-11-10 miss, recorded rather than tidied away.** B1's
`TestNothingIsWiredYet` — the `git grep` census pinning "the refusal exists but
no production caller can reach it" — fired with exactly its intended message
the moment **B5** wired `acquire_attempt_scopes`, and should have been retired
IN the B5 commit. It survived one commit longer because B5's targeted run
covered the tuner-node suites and not `tests/unit/execute_tools`, where the
guard lives. Retired here. **The lesson is about the targeted-run SELECTION,
not about the guard**: a guard that names its own flip owner must be run when
that owner lands, so a commit's targeted set has to include the modules whose
guards it flips — not only the modules it edits.

#### Validation

| suite | result |
|---|---|
| `test_step12_pr12bc_b6_scope_transport.py` (NEW) | **21 passed** · 1.35 s |
| B6 + B0 + step11 C0 + step10 P1 C3 + step11 C4 + step02b b1/b3 + B4 + B5 | **161 passed** · 3.60 s |
| `tests/unit/execute_tools` + `tests/unit/nodes` | **2119 passed**, 2 skipped · 129 s · rc 0 (after retiring the B1 guard) |
| `ruff check` + `format --check` (repo) | clean |

### Q.B7 — COMPLETE. Scope-adjacent satellites.

**D-BC-8 = PROFILE-AWARE.** `validate_sample_set` validated against the TIDMAD
module constants, so a 3-file task silently accepted `{19: [199]}` and a
400-segment task had two thirds of its index space rejected. The bound now
splits exactly as Q-12-4 splits the profile: the **partition** bound is
generic identity and always checked; the **per-partition** bound is task
topology and is **SKIPPED, not guessed**, when the task declares none.
Skipping is the honest behaviour — a task with no declared index space has no
number to check against, and substituting TIDMAD's is the defect being
removed. Structural checks apply to every task unconditionally, and TIDMAD's
own verdicts (including its rejections) are asserted unchanged. Blast radius
`sandbox_executor.py:1518`, `:1530`, `:1872` — all three keep the ambient
default, which now resolves the RUN's profile.

**Satellite (f).** The peek path took the IMPORT-TIME `TIDMAD_DATA_DIR` and an
inline `abra_validation_{i:04d}.h5`, bypassing `validation_file_name`. Both
halves now come from the run's own authorities — the COMPOSED root
(`sandbox.dirs["data"]`) and the profile's declared template. Fixing only the
filename would still have peeked in TIDMAD's directory, so both are asserted.

**Satellite (e), and D-BC-15 — a design correction the consumer audit forced.**
The design said an absent capability should **refuse the trial round**. The
consumer audit says otherwise: `anchor_map_data=None` is an **already legal
state** — `execution.py:953` guards the entire block that reads it — and that
block is TIDMAD's SCORING reference, not a precondition of trial rounds.
Refusing would have **regressed composed Pets/DAVIS trial runs that PR-12a
made work**, to protect them from a consumer they never reach. So the run
**DECLINES by name** instead. The design's actual goal — never crash on a
TIDMAD filename a task did not declare — is met by declining to invent one.
Three cases, including the one that is easy to miss: PR-12a's guard follows
the INPUT FIELD even with the ContextVars unbound, so "the field says composed"
does not imply "something is bound".

**F-12-2.** The measurement path SKIPS with a named reason when the profile
declares no TIDMAD geometry — the caller already handles a `None` estimate,
whereas measuring against somebody else's geometry returns a confident wrong
number. Asserted STRUCTURALLY, never on wall time (the F-12a-G2 lesson, and
the design's own B0 edge-case note for this satellite).

**`--data_scope`.** Refused BY NAME at startup for a composed task that does
not declare TIDMAD's topology, because a file-index list cannot be
reinterpreted for a different partition concept. Extracted behind
`_refuse_data_scope_for_a_foreign_topology` — `run_workflow` carries a §12.1
branch tripwire and this is a self-contained decision.

#### Four guards fired that I had not run — the same lesson, twice

B7 tripped **four** standing guards, and every one of them was right:

1. **PR-12a's ambient-composition census** caught `active_task_data_path` in
   the tuner package — introduced at **B5**, in `scope_acquisition.py`, whose
   own docstring claimed it read no ambient state. The census lives in
   `tests/unit/workflows`, which B5's targeted run did not include.
2. Replacing it with `resolve_bound_task_data_path` then introduced a **silent
   regime-A fallback** — a composed run whose binding was unbound would have
   built TIDMAD's scopes, which is **C-P56-1 exactly**. Fixed by adding
   `require_bound_task_data_path()` in `task_data_path.py`: the ambient lookup
   belongs in the module that OWNS the binding, and composed callers get a
   fail-closed answer.
3. **Census B** (parent-side resolve topology) caught the two new resolve
   sites. **Extended deliberately, never exempted by name** (the Step-11 C9
   rule), and `require_bound_task_data_path` was added to the tracked set — a
   resolve the census cannot see is a resolve it does not constrain.
4. **§J's budget** caught `HyperparamTuningAgent.run` at +4 branch nodes.
   Extracting `_load_trial_anchor_map` left `run()` at **68 branch nodes —
   SMALLER than its 69 baseline**. The rule working exactly as intended:
   establish the boundary, then add the feature.

**The lesson, restated because it recurred:** a commit's targeted test set must
include the modules whose GUARDS it flips or affects, not only the modules it
edits. B6 recorded this about a retired guard; B7 shows it applies to standing
censuses too.

#### Two of my own tests were wrong, and were fixed rather than relaxed

Both censused SOURCE TEXT and read the COMMENTS that explain the removed
defect — the anchored-census trap (F-P2b-4) from the other direction. Both
became AST censuses over executable identifiers. A third redundant text scan
was deleted outright: PR-12a's AST census already owns that property, and this
file deliberately keeps a comment naming what the old guard used to read.

#### Validation

| suite | result |
|---|---|
| `test_step12_pr12bc_b7_satellites.py` (NEW) | **25 passed** · 0.96 s |
| `tests/unit/execute_tools` + `core` + `workflows` + `nodes` | **5601 passed**, 2 skipped · 332 s · rc 0 |
| `ruff check` + `format --check` (repo) | clean |

§J: `validate_sample_set` 14 → 16 branch nodes (+2, budget +3) after extracting
`_sample_set_bounds`; `HyperparamTuningAgent.run` 69 → **68**.

### Q.B8 — COMPLETE. Four shapes, one path. Phase-B structural comparison.

**Commit contents:** `execute_tools/pets_data_path.py` +
`execute_tools/davis_data_path.py` (capability + task-instance config),
`execute_tools/task_data_path.py` (`deserialize_rows_scope`), and
`tests/unit/execute_tools/test_step12_pr12bc_b8_capability_shapes.py` (NEW).

```text
TIDMAD     {partition: [segment indices]}   a mapping of index lists
Pets       rows: (PetsItem, ...)            a tuple of identity rows
DAVIS      rows: (DavisClip, ...)           a tuple of identity rows
ANONYMOUS  tiles: ((z, y, x), ...)          3-D coordinates — no `rows`, no
                                            partition indices, NO 1-D index
                                            space at all
```

All four build, serialize, round-trip and cross the **same** artifact + digest
ABI, which never looks inside any of them. A test asserts all four were
actually exercised — a silently-skipped contrast task would let every other
assertion pass while proving only that TIDMAD works.

**Task-instance configuration (§D.1).** Both contrast implementations take
their scope authority at CONSTRUCTION — `manifest_path` for Pets,
`clips_path` for DAVIS. The module-level registrations pass nothing: that
regime-A instance materializes a scope it is HANDED and **refuses to BUILD one
by name**. Production imports nothing from `examples/` (AST census over both
modules, plus the standing governance census). *DAVIS' parameter is
`clips_path`, not `sequences_path`, because that is what `load_davis_clips`
actually reads — a sequences manifest has a different header and is refused by
it. Found by the first cut failing on the real committed file.*

**The framework NAMES the strategy; the TASK supplies the content.** Pets and
DAVIS declare no anchor representatives, so `anchors` raises **by name** for
them rather than inventing a set; `target` is bounded by each task's OWN row
count.

**Cross-task injection refused for every ordered pair** — 12 pairs, both as a
foreign scope OBJECT (the `_scope()` `TypeError`) and as a foreign PAYLOAD
(refused BY KIND). Closing the pairing GAP at B6 did not soften the pairing
RULE.

**The shared codec is not over-applied.** Pets and DAVIS share
`deserialize_rows_scope` because they share a SHAPE. TIDMAD does **not** use
it — its scope is a mapping of index lists, a genuinely different shape, and
one codec over both would be an abstraction invented for symmetry rather than
for a shared property. Asserted.

#### §J — the Phase-B structural comparison

| function | branch | LOC |
|---|---|---|
| `sandbox_executor.py::TidmadSandbox.execute_training` | 39 → **39** | 358 → 363 |
| `train_engine_sandbox.py::main` | 23 → **23** | 294 → 338 |
| `train_engine_sandbox.py::run_experiment_streaming` | 62 → **62** | 728 → 730 |
| `planning.py::prepare_attempt` | 32 → **32** | 471 → 497 |
| `execution.py::run_inference_scoring_health` | 26 → **26** | 474 → 488 |
| `ml_hyperparameter_tune_agent.py::HyperparamTuningAgent.run` | 69 → **68** | 1142 → 1137 |
| `scoring_utils.py::validate_sample_set` | 14 → **16** | 58 → 94 |

**Exactly ONE baselined function gained any branch nodes across the whole of
Phase B**, and it is within the +3 budget after `_sample_set_bounds` was
extracted. Every other one is flat or SMALLER — the tuner's `run()` ended
below its baseline because satellite (e)'s three-case resolution was extracted
rather than inlined. `run_experiment_streaming` stayed at 19 parameters, as
§J freezes it. No new branch family anywhere, and no total-LOC argument was
used to excuse one.

New focused units introduced by Phase B, each independently testable:
`acquire_attempt_scopes` (11/3/89) · `_task_scope_argv` · `_sample_set_bounds`
(6/3/19) · `_load_trial_anchor_map` (20/8/67) ·
`_refuse_data_scope_for_a_foreign_topology` · the whole `scope_artifact`
module.

---

### Q.B-GATE — `G-12bc-B` readiness packet

Written BEFORE launch, per §M and the gate standard.

| field | value |
|---|---|
| **candidate SHA** | `8fd80cdc` (Phase-B implementation head; clean tree) |
| **failure class** | a task-built scope must survive the REAL subprocess boundary exactly and be CONSUMED by the child under the correct `TaskDataPath` implementation |
| **what makes it discriminative** | **the transported scope and the legacy `--sample_set_json` are made to DISAGREE.** The parent sends a sample set spanning THREE partitions and a scope spanning ONE. A child that consumes the transported scope materializes one partition's rows; a child that fell back to regime-A materializes three. The row count is therefore a *decisive* observation rather than a plausible one — the Gate cannot pass by the child ignoring the scope and doing the old thing |
| **required real** | ONE real production child spawn through `TidmadSandbox.execute_training` → `_run_observed_subprocess` → `train_engine_sandbox.py`. Real argparse, real digest verification, real deserialization, real dataset materialization, real optimizer steps |
| **workload** | a tiny synthetic TIDMAD-shaped dataset written to `tmp`: 3 partitions × 4 PSD segments × `psd_segment_length=2000`, `seg_size=500`, `fcnet`, batch 1, **1 epoch**, **CPU**. Nothing about the science is claimed; the claim is about transport and consumption |
| **CPU, deliberately** | §H authorizes the cheapest production-real execution sufficient to witness consumption. The scope-transport path is device-independent, so CUDA would add cost and no evidence. **F-12a-G2b is therefore irrelevant here** — no GPU capacity is consulted at all |
| **runtime-watchdog posture** | **OFF, which is the DEFAULT production posture** (`--runtime_watchdog` is `action="store_true"`, "Default off"), so this is not opting out of anything a normal run has. **Q-07c-6 is live and unowned by this PR**: admission prices `phase="training"` only, so 07a's in-subprocess validation pass is unpriced and a watchdog can kill a child at a deadline it was never priced for (Step-11 Gate-2 run 1; PR-12a G-12a-2 attempt 2 at 119.365 s vs 118.749 s). Watchdog correctness is **not this Gate's failure class**. A Q-07c-6 kill would be **INCONCLUSIVE, never FAIL**, and nothing may be tuned to make this green |
| **projected cost** | seconds to low minutes. No LLM call, no GPU, no scoring, no inference |
| **STOPS AT** | the child's scope consumption. **NOT required**: inference · scoring · a complete workflow · model quality · HealthGate PASS · score magnitude · convergence |
| **evidence recorded** | parent-built scope identity · artifact ref · scope digest · child-recomputed digest · child deserialization · **actual child consumption**, as the materialized row count discriminating scope from sample set |
| **PASS** | the child spawns, verifies, deserializes and materializes **the SCOPE's** partition set — not the sample set's |
| **FAIL** | the child materializes the sample set's partitions (regime-A reached), or refuses a valid artifact, or accepts a tampered one |
| **INCONCLUSIVE** | the intended path did not execute — an import/environment fault, a provider/infra failure, or a Q-07c-6-shaped kill |
| **authorization** | STANDING (§H). No second approval. `SIDERIUS_ALLOW_LAUNCH=1` may be set mechanically if a hook requires it |

### Q.B-GATE.1 — `G-12bc-B` **PASS**

**Exact SHA `8fd80cdc`.** Evidence preserved at
`/home/klz/Data/SIDEREIS_DATA/gate_evidence/step12_pr12bc_gate_b/`
(`g12bcb_evidence.json` · `g12bcb_run.log` · `g12bcb_harness.py` ·
`EXACT_SHA`). Real production child spawn, CPU, no LLM call, no GPU, seconds.

#### The decisive observation

```text
--sample_set_json      3 partitions   ->  48 rows would be materialized
transported scope      1 partition    ->  16 rows would be materialized

CHILD ACTUALLY RAN:    Epoch 0: 100%|##########| 16/16
```

**16, not 48.** The child materialized the SCOPE's partition, not the sample
set's. The two hypotheses differ by 3×, so this is a *decisive* observation
rather than a plausible one: the Gate could not have passed by the child
ignoring the transported scope and doing the old thing. That is exactly what
made this witness worth spending a real spawn on.

#### The evidence set, each item recorded

| item | value |
|---|---|
| parent-built scope identity | `{"1": [0, 1, 2, 3]}` — one partition, built by `TidmadTaskDataPath.build_training_scope` via the `target` strategy |
| artifact ref | `…/ws/configs/g12bcb/task_scope_g12bcb_exp.json` — the run-scoped `dirs["configs"]` location, `<stem>_<exp_id>.json` |
| scope digest (parent) | `6484e72227b3f667c7417ce2114659ecae2031cf6d6d8eaaffb532d3fe19b6fe` |
| digest recomputed from the written bytes | **identical** |
| the artifact holds the TASK's own serialization | **true** — byte-for-byte `serialize_scope`'s output |
| child deserialization | implied and then PROVEN by consumption: the child could not have materialized partition 1 alone without decoding the payload |
| **actual child consumption** | **16 optimizer steps over partition 1**, real `TIDMADEpochDataset` materialization, real forward/backward, model written to `cached_models/` |
| training status | `success` |

#### What was NOT claimed

No inference, no scoring, no HealthGate, no convergence, no model quality. The
recorded `Avg Loss: 5.577911` is context, not a criterion. The witness stopped
at consumption, as §H requires.

#### One INCONCLUSIVE attempt first, recorded

The first launch exited before the child's training path: the model configs
require `segmentation_size >= 1000` and the harness had used 500, so config
validation refused. **The intended semantic path did not execute, so it was
INCONCLUSIVE, not FAIL** — and the fix was a HARNESS parameter
(`PSD_LEN 2000→4000`, `SEG_SIZE 500→1000`), not a production change and not a
loosened assertion. The second attempt is canonical. Nothing was tuned to make
anything green: the 16-vs-48 discriminator was fixed before the first launch
and was untouched by the fix.

#### Posture, as promised in the packet

Runtime watchdog **OFF** — the default production posture, so nothing was
opted out of. **Q-07c-6 did not arise**: the child ran in well under a second
and no deadline was involved. **No GPU capacity was consulted**, so
F-12a-G2b is irrelevant to this result.

---

## Q.F — the §F B→C internal checkpoint: **DISCHARGED**

All ten proofs hold. Per §11.3 this is AUTOMATIC — implementation continues
directly into Phase C with no operator stop.

**Phase-B checkpoint SHA: `120ec93a`** (executable head `8fd80cdc`, where the
Gate ran; the delta is documentation only).

#### Items 8 and 9 are now PERMANENT censuses, not one-time checks

A checkpoint verified once and never again is a claim, not a guard, so both
became tests (`tests/unit/guardrails/test_step12_pr12bc_f_checkpoint.py`,
12 passed):

**Item 8.** Every production `TidmadScope` construction site is NAMED with its
reason, and a new one fails the census. Three remain, all legitimate:
`tidmad_data_path.py` (TIDMAD's own capability — a task constructing its own
scope type is not a framework assumption), `train_engine_sandbox.py` (the two
regime-A fallbacks, and the census asserts **both** sit inside an
`if <scope> is None:` guard, so a transported scope can never be overwritten),
and `evaluate_time_skill/wrapper.py` (reached only after B7's topology guard,
asserted to PRECEDE the construction it protects). **Zero unconditional
constructions on the composed path.**

**Item 9.** Four censuses over the generic tree, with TIDMAD's and the
contrast tasks' own modules excluded BY OWNERSHIP — a task naming itself is a
declaration, not dispatch: no comparison against a task name · no dict literal
keyed by two or more task names (a central catalog however it is spelled) · no
scope KIND named in generic core (each payload is self-identifying so the TASK
can refuse a foreign one; the framework must never branch on that tag) · the
scope ABI never parses a payload. **All clean.**

#### Item 10 — Phase-C anchors re-audited against ACTUAL Phase-B source

Verified by CONTENT, not line number, and made a parametrized test — because
**Phase B moved several of them**:

| Phase-C assumption | design said | ACTUAL, post-Phase-B | status |
|---|---|---|---|
| F-12-3 early return | `task_composition.py:570-571` | `:570` | unchanged |
| F-12bc-2 `_load_symbol` (module rollback, NO registry rollback) | `:487-496` | `:492` | unchanged; the finding stands |
| `_REGISTRY` | `task_data_path.py:219` | **`:570`** | **MOVED** — Phase B added ~350 lines above it |
| duplicate refusal | `:246-252` | **`:599`** | **MOVED**, same cause |
| health `reset_run_scope` (test-only) | `_plugin_binding.py:590-601` | `:590` | unchanged |
| F-12bc-3 pinning test | `test_step10_p1_c1_composition.py:209-225` | `:209` | unchanged |
| F-12bc-4 bootstrap census | `test_task_data_path_census.py:194-242` | `:194` | unchanged |

**Phase C must use `task_data_path.py:570` / `:599`, not `:219` / `:246-252`.**
This is exactly what item 10 exists to catch: a phase planned against pre-B
source and executed against post-B source. Nothing about the MECHANISMS
changed — the registry is still one dict with one write site, no `unregister`,
and a duplicate refusal — so every Phase-C finding stands as written.

#### One Phase-C-relevant fact Phase B ADDED

`require_bound_task_data_path()` now exists in `task_data_path.py` (B7): it
resolves the EXPLICITLY bound implementation and **refuses the regime-A
fallback**. Phase C's registration overlay must not undo that: a composed
caller asking for a binding must keep getting a fail-closed answer rather than
TIDMAD's compatibility implementation.

---

### Q.C0 — COMPLETE. Phase-C baselines and inverted guards.

**Tests only. Zero production files.** Four inverted guards, each naming its
flip owner in-test, plus the §J pre-values.

**Anchored on CONTENT, never on line numbers** — deliberately, because §F item
10 had just shown Phase B moved several of them. A line-number assertion would
fail for a reason that has nothing to do with the property it guards.

| guard | asserted PRESENT | flips in |
|---|---|---|
| **F-12-3** | the early return is keyed on the ID ALONE — an AST check that its condition mentions no digest/content/identity | C1 (RETIRE) |
| **F-12bc-2** | the composition loader rolls back `sys.modules` and nothing else — asserted from BOTH sides: the health loader DOES roll back its registries, and the data-path registry has no removal path at all, which is *why* the rollback cannot simply be copied | C1 (RETIRE) |
| **out-of-tree** | an unknown id is refused, naming the registered set | C3 (**UPGRADE** — the refusal survives as the truth table's last row) |
| **F-12bc-4** | the bootstrap census pins the import set, and no child composes a data path today | C3 (UPGRADE) |

**One correction worth keeping.** The out-of-tree guard first asserted
`"tidmad" in registered_ids()`. It passed in the full directory and failed in
isolation — because what is registered depends on **what this interpreter
happened to import**. That is precisely the process-global monotonic hazard
Phase C exists to fix, and asserting against it would have made the guard
depend on test ORDER, which is what CASE A *is*. Rewritten to assert only the
property: an out-of-tree id is absent and resolution refuses.

#### The CASE-A baseline C1 must close

Captured at `1f66cf79`, the restricted single-process ordering reproducer the
design names (§A.5 / F-12bc-5):

```text
pytest tests/unit/agent/tune_ml_hyperparam_agent \
       tests/unit/workflows/test_step10_p56_c5_wiring_closures.py \
       -m "not real_run" -q

-> 9 failed, 1306 passed

TaskDataPathRegistrationError: Task data path 'tidmad' is already registered.
Currently registered: ['davis_future_prediction', 'tidmad'].
Duplicate registrations are refused rather than silently replaced.
```

**Exactly the recorded signature.** The acceptance shape is frozen:

```text
baseline (this head)     restricted reproducer -> FAIL (9)
after the C1 overlay     the SAME reproducer   -> PASS
```

**Forbidden ways to make it pass** (D-BC-10): pytest ordering hacks ·
test-specific unregister/reset · special-case TIDMAD cleanup · suppressing the
duplicate-registration error · weakening or narrowing the reproducer. And it
must never be misstated as a formal full-suite CI failure — the full-suite
ordering happens to run `tests/unit/workflows` first, which is the order that
does not poison.

#### §J pre-values for the Phase-C surface

| function | st | br | LOC | par |
|---|---|---|---|---|
| `task_composition.py::_compose_task_data_path` | 19 | 9 | 63 | 2 |
| `task_composition.py::_load_symbol` | 33 | 13 | 85 | 3 |
| `task_composition.py::bind_run_task_composition` | 25 | 4 | 80 | 2 |
| `task_data_path.py::register_task_data_path` | 11 | 5 | 26 | 1 |
| `task_data_path.py::resolve_task_data_path` | 13 | 4 | 27 | 1 |

`task_composition.py` is **1475 LOC** at C0. §J: *"per-family composers stay ≤
the current largest; the overlay is its own module, not a growth of the
composer."*

**Validation:** **19 passed** · 0.14 s; **34 passed** when run alongside
`test_task_data_path.py` — i.e. under a different registration order, which
for this module is the point.

---

### Q.C1-audit — CASE A's mechanism, diagnosed. It decides C1's design.

The design records CASE A's SYMPTOM (a duplicate-registration error under a
restricted ordering) but not its MECHANISM. C1's shape depends on the
mechanism, so it was diagnosed before designing anything.

#### The trace

Every failing frame in the C0 baseline shows the same thing:

```text
importlib.import_module(module_ref)          # _load_symbol's module: branch
  -> execute_tools/tidmad_data_path.py:591 in <module>
       register_task_data_path(TidmadTaskDataPath())
         -> TaskDataPathRegistrationError: 'tidmad' is already registered
```

Line 591 is the **last line of the module**. So the module is being
**RE-EXECUTED** — which only happens when it is absent from `sys.modules`.

#### The probe

```text
import execute_tools.tidmad_data_path   ->  registered: ['tidmad']
importlib.import_module(same)           ->  CACHED, same object, no re-exec
sys.modules.pop(same); import again     ->  RE-EXECUTES
                                        ->  TaskDataPathRegistrationError
```

**CASE A is therefore: a module-level registration re-executing after its
module was evicted from `sys.modules`, meeting a registry that cannot accept a
re-registration of the SAME implementation.** Something in the restricted
ordering evicts the module — the tuner package's own `sys.modules` rebinding
and several plugin-isolation fixtures all manipulate it — and the registry
then refuses the re-registration because it compares **id only**.

#### Why this makes the frozen §8 rule the exact fix

The parent's two-phase contract already says what should happen:

```text
WITHIN an active run   same canonical identity + SAME content -> IDEMPOTENT
                       same id + DIFFERENT content            -> refuse (named)
```

A re-execution of the *identical module* is the **same identity and the same
content**, so it must be idempotent. Today the registry has no notion of
content at all, so it refuses. **Implementing the frozen rule closes CASE A by
construction** — and it does so through PRODUCTION lifecycle semantics, which
is exactly what D-BC-10 requires.

Check it against D-BC-10's forbidden list, one by one:

| forbidden | does this do it? |
|---|---|
| pytest ordering hacks | **no** — no test file is reordered or marked |
| test-specific unregister/reset | **no** — the rule is production behaviour, identical in a real run |
| special-case TIDMAD cleanup | **no** — the rule mentions no task |
| suppressing the duplicate-registration error | **NO, and this is the load-bearing one**: a same-id/**different-content** registration still refuses, loudly and by name. Only an identical re-registration becomes a no-op |
| weakening or narrowing the reproducer | **no** — the reproducer runs verbatim |

**Content identity** is the health precedent's, applied one family over:
normalized ref + symbol + content sha, host paths excluded so the same package
at two absolute paths is one identity (`_plugin_binding.py`). For a module-level
registration the natural content identity is the implementation's own
module + qualified name + the module file's sha256.

**This also closes F-12-3 with the same mechanism**, which is the point:
`_compose_task_data_path`'s early return refuses to be keyed on id alone once
the registry itself knows content, so an EDITED plugin is a
different-content registration and refuses instead of silently running the old
object under a fresh digest.

### Q.C1.1 — the two-phase registration rule. **CASE A CLOSED.**

C1 splits at a clean boundary (the standing rule). This first unit implements
the frozen §8 registration rule and closes CASE A with it; the overlay,
F-12bc-2's rollback and F-12-3 follow.

**The rule, as frozen:**

```text
same id + SAME content       ->  IDEMPOTENT
same id + DIFFERENT content  ->  REFUSED, by name, naming BOTH identities
```

**Content identity** = the defining class's qualified name + the sha256 of its
module's SOURCE, **captured at registration and stored**. Captured rather than
recomputed on demand, deliberately: recomputing would re-read the file as it is
NOW, so an edited plugin would hash the same file on both sides of the
comparison and compare EQUAL — the exact case the comparison exists to catch.
Host paths are excluded (the health precedent's rule, one family over), so the
same package at two absolute paths is ONE identity.

#### CASE A: **9 failed → 1315 passed**

```text
pytest tests/unit/agent/tune_ml_hyperparam_agent \
       tests/unit/workflows/test_step10_p56_c5_wiring_closures.py \
       -m "not real_run" -q

C0 baseline (1f66cf79)   ->  9 failed, 1306 passed
after this unit          ->  1315 passed, 0 failed
```

**Through production lifecycle semantics only.** D-BC-10's forbidden list,
item by item:

| forbidden | done? |
|---|---|
| pytest ordering hacks | **no** — no file reordered, no marker added |
| test-specific unregister/reset | **no** — the rule is production behaviour, identical in a real run |
| special-case TIDMAD cleanup | **no** — the rule names no task |
| suppressing the duplicate error | **NO** — verified directly: a same-id/DIFFERENT-content registration still raises, and the message now names both identities, which is *more* informative than before |
| weakening/narrowing the reproducer | **no** — run verbatim |

#### Two tests UPGRADED, not deleted

`test_task_data_path.py::test_duplicate_registration_refused` and C0's
`test_a_duplicate_registration_is_refused` both pinned "ANY second
registration refuses". Each now asserts **both halves**, because the second
half is what makes the first one safe — a test that checked only idempotence
would pass if the refusal were deleted outright. The §F item-10 anchor needle
moved with the message.

#### One fragility found and fixed while implementing

`_CONTENT` is a second structure holding one fact, so it can diverge from
`_REGISTRY`: an id registered with no identity would compare a duplicate
against `None` and refuse spuriously; an identity surviving an absent id would
let a later registration compare against a ghost. `registry_invariant_holds()`
states the invariant as a function so every lifecycle test asserts it rather
than re-deriving it, and the isolating fixture now patches **both** maps —
patching one would have left a stale identity behind an absent id.

**Validation:** targeted set **418 passed**; CASE-A reproducer **1315 passed**
(489 s); `ruff` clean.

### Q.C1.2 — COMPLETE. The overlay, F-12bc-2 and F-12-3.

**Commit contents:** `execute_tools/task_registration_scope.py` (NEW, its own
module per §J), `workflows/task_composition.py` (rollback + the content
comparison), C0's two guards RETIRED, B4's digest census made precise, and
`tests/unit/workflows/test_step12_pr12bc_c1_lifecycle.py` (NEW).

**The health precedent's limits, audited (why it is a precedent, not a
template).** `_plugin_binding.py`'s `_RUN_SCOPE` is process-permanent with a
test-only reset and zero production callers, so it **cannot** serve
heterogeneous sequential runs — copying it would reproduce the very limitation
§8 names. What transfers is its **identity rule** (normalized ref + symbol +
content sha, host paths excluded), which C1.1 adopted. **D-BC-6**: the health
family is NOT migrated onto the overlay — it is allowed, not required, and
migrating it would touch 08b guarantees for no property this PR owes.

**The overlay.** `run_registration_scope()` snapshots the inherited roster and
retires exactly what the run ADDED, on unwind **and on exception**, mirroring
the ContextVar discipline. The inherited roster survives — a run must not tear
down registrations it did not make. `retire_registrations(keep)` is the ONE
mutation path out of the registry and is deliberately **not** a public
`unregister(id)`: retiring is a lifecycle operation over a known baseline, not
an ad-hoc removal a caller can aim wherever it likes. Both maps are cleared in
lockstep, so `registry_invariant_holds()` stays true — asserted after every
operation.

**Concurrent in-process scopes FAIL CLOSED** (D-BC-3): a second scope opened
while one is active raises. Two runs sharing one registry would interleave each
other's roster, and refusing is the honest answer rather than inventing a
nested semantics. **D-BC-3's honesty clause is asserted too**:
`active_registration_scope() is None` in the ordinary production state, because
production today gets its isolation from the process boundary.

**F-12bc-2** — `registration_rollback()` wraps `exec_module`, so a plugin that
registers and then raises leaves the registry byte-identical. Proven **end to
end through the production loader** with a real file that registers and then
raises, not a simulation. It is deliberately narrower than the run scope: it
retires only on FAILURE, because a plugin that loads successfully registered
something the run is meant to keep.

**F-12-3 at BOTH lines of defence.** A self-registering plugin meets C1.1's
rule during `exec_module` and never reaches composition. A FACTORY plugin that
does not self-register reaches the early return, which now compares
`registered_content_identity(declared)` against `content_identity(resolved)`
and refuses with both identities named. The check is stated at the composer
*as well*, deliberately: *"the other function already checked"* is exactly the
kind of reasoning that decays.

#### Two guards RETIRED for a reason worth recording

C0's `(f12-3)` and `(f12bc-2)` guards **would not have flipped**, even though
both defects are closed — because each was shaped around the code as it looked
at C0 (one around the early return's CONDITION, the other around an except
handler's BODY) and C1 fixed both with a different shape: the comparison sits
INSIDE the early-return block, and the rollback is a context manager around
`exec_module`. That is the guards being too narrow, not the fixes being wrong.
The honest response is to replace them with contracts that assert what the code
must **do** — which is what the C1 module does — rather than to reshape an
inverted assertion until it fires.

#### One census made precise, not exempted

B4's "exactly one digest authority" census fired on C1's `content_identity`,
which hashes a **module source**, not a scope payload — a genuine false
positive from a census keyed on "any `hashlib.sha256` in a module mentioning
scope". Narrowed to hashes of a SCOPE PAYLOAD, with other digests named
alongside the fact each identifies, in the same sanctioned-site form B8 and the
§F checkpoint already use. **Not exempted by file name**: a new hash in one of
those modules still fails unless it is named with its fact.

**Validation:** C1 lifecycle **19 passed** · 0.91 s; affected owners
(`workflows` + `execute_tools` + `guardrails`) **3242 passed**, 2 skipped ·
214 s; the CASE-A reproducer **1315 passed**. `ruff` clean.

---

### Q.C2 — D-BC-5 ruled, and C2 implemented.

#### D-BC-5 — per-family content identity, NOT the composition fingerprint

| field | value |
|---|---|
| **Decision ID** | **D-BC-5** |
| **Phase / checkpoint** | C / C2 |
| **Question** | Parent §7 requires every child-consumed external semantic to be validated against a parent-pinned identity before consumption. Which identity — the per-family content digest, or the full composition fingerprint? |
| **Source evidence** | The semantic a child consumes here is **one thing**: the resolved `TaskDataPath` implementation, transported by id (`transport_argv`, `sandbox_executor.py:852-875`). The full composition fingerprint covers the WHOLE manifest — metric, secondary metrics, health, interpretation/proposal/implementor blocks, task config, deliverable — and PR-12a's own §A.3b records that it MOVES when any declared section changes. C1 already produced the per-family primitive: `content_identity()` (qualname + module-source sha256, host paths excluded) and `registered_content_identity()` |
| **Options considered** | (i) the full composition fingerprint; (ii) per-family content identity; (iii) re-read the manifest in the child and trust it |
| **Chosen ruling** | **(ii) — per-family content identity.** |
| **Why not the fingerprint** | It is both too broad and too vague for this check. **Too broad**: a training child that consumes only the data path would refuse because an unrelated `interpretation_blocks` sentence changed — an over-refusal that teaches operators to distrust the check. **Too vague**: on divergence it can say only "the composition differs", never WHICH thing differs, so the diagnostic cannot name the file to look at. And the fingerprint already has an owner — the run-invariants lock pins the RUN's identity; C2's question is narrower and different |
| **Why not (iii)** | Explicitly excluded by the frozen design, and rightly: re-reading the manifest proves the manifest is readable, not that the code the child is about to execute is the code the parent resolved. That is the whole bind-to-spawn edit window |
| **Frozen-contract impact** | None. §E.2 leaves the mechanism to this design and forbids only (iii) |
| **Validation / falsifier** | The three divergence cases each produce a NAMED refusal, with a spy proving the semantic was not consumed first; and a registry HIT with divergent content refuses, which is parent §7's sharp edge |
| **Downstream implication** | 12e inherits a per-family identity chain that names the diverging family, which is what its graduation claim needs |
| **Material deviation?** | **no** |

**Minimal, and that is the point.** The identity travels as one additional
argv token beside the id it qualifies, is emitted only when composed, and is
verified by the same function in every child.

#### What landed

| surface | change |
|---|---|
| `execute_tools/task_data_path.py` | `TASK_DATA_PATH_IDENTITY_FLAG`, `TaskDataPathIdentityError`, `verify_transported_identity(impl, expected)`; `transport_argv` extended to emit the identity beside the id; `resolve_transported_task_data_path(id, identity=None)` verifies BEFORE returning |
| `execute_tools/train_engine_sandbox.py` · `inference_single.py` · `denoising_score_single.py` | each parses `--task_data_path_identity` and passes it through; none reimplements the check |
| `core/sandbox_executor.py` | **unchanged** — `_task_data_path_argv` already delegates to `transport_argv(bound)`, so the identity rides the existing binding-keyed emitter |

**The check lives in ONE function.** Every child calls
`resolve_transported_task_data_path`, so verification could not be duplicated
per child — and a per-child copy is a per-child chance to forget, which the
argv census alone could not distinguish from a subtly wrong copy. A census
pins that too (`test_no_child_reimplements_the_verification`).

**`expected=None` is an ABSENCE OF A CLAIM, not a passing check.** A parent
that predates this transport pinned nothing; a child that demanded an identity
anyway would fail every legacy run on a check its parent never made. This is
the same shape as R-11's "emitted only when bound".

#### Three divergence cases, and why they are genuinely three

| case | what moved | what catches it |
|---|---|---|
| edited plugin **bytes** | same path, same symbol, different source | the module-source sha half of `content_identity` |
| edited **manifest** | same file, same bytes, a different declared symbol | the qualname half — a file-scoped digest would call these ONE implementation |
| **registry** hit | the id resolves perfectly to a different object | the comparison itself; parent §7's sharp edge |

The first two run on real files through the **production** `_load_symbol`, not
a hand-rolled loader. That was not the first attempt, and the first attempt
was quietly wrong: a hand-written `spec_from_file_location` does not populate
`sys.modules`, `content_identity` reads the defining module from there, and so
both loads degraded to the documented qualname-only fallback and an edited
plugin compared **equal**. The fallback is correct behaviour for a class with
no readable module; the test was wrong to exercise it while claiming to cover
the production path. Recorded because it is the C1.2 lesson again in a new
costume — *a simulation of a loader is not the loader*, and the failure mode
is a green test.

`test_an_UNEDITED_plugin_does_not` is the half that makes the other three
mean something: an identity that changed on every load would satisfy every
divergence assertion above while refusing every legitimate run.

#### Stale pins upgraded, not weakened

Three tests pinned the argv fragment's exact shape and went red — the expected
class, and the fourth time this PR's "run the modules whose guards this commit
affects" rule has paid:

| test | upgrade |
|---|---|
| `test_task_data_path.py::test_transport_argv_derives_from_the_implementation` | now asserts the id **and** the identity are both derived from the implementation — the property it was always about |
| `test_task_data_path.py::test_round_trip_transported_id_resolves_to_the_same_registration` | round-trips WITH the identity (it unpacked a 2-list) |
| `test_step10_p1_c3_transport.py::test_the_emitter_helper_is_empty_when_unbound_and_populated_when_bound` | asserts the emitted fragment carries the bound implementation's own `content_identity` |

None of the three had its assertion loosened; each now states a strictly
stronger fact.

#### Validation

```
.venv/bin/python -m pytest \
  tests/unit/execute_tools/test_task_data_path.py \
  tests/unit/guardrails/ \
  tests/unit/core/test_step10_p1_c3_transport.py \
  tests/unit/workflows/ \
  tests/unit/execute_tools/test_step11_c5_scoring_metric_acquisition.py \
  tests/unit/execute_tools/test_inference_single.py -q
```

**1,229 passed** (C2's own module: 27 passed). `ruff check` + `ruff format
--check` clean across `tests/ execute_tools/ core/ workflows/`. Local pyright
cannot run in this environment (the vendored binary needs a newer Node than
the box provides) — recorded as a limitation, not claimed as a pass; strict
type checking is CI's, at the final head.

**Not claimed here.** A real out-of-tree plugin loaded by a REAL spawned child
is `G-12bc-C`'s evidence, not C2's; C3 still has to get the manifest to the
training and inference children before that Gate can exist.

---

### Q.C3 — the child can resolve a task the framework has never heard of.

#### The audit, per child

| child | resolved a data path before C3? | had the manifest? | verdict |
|---|---|---|---|
| training (`train_engine_sandbox.py`) | yes — registry-only | **no** | needs both |
| inference (`inference_single.py`) | yes — registry-only | **no** | needs both |
| scoring (`denoising_score_single.py`) | yes — registry-only | yes (Step 11 C5, for the METRIC) | needs the resolver; the manifest was already there and unused for this |

**The defect, stated plainly.** A child resolved a transported id through the
registry, and the registry holds exactly what that child's bootstrap imported —
the three built-ins. An out-of-tree implementation therefore resolved in the
parent and was unresolvable in **every child the parent spawned**. Nothing in
the suite saw it, because every test that exercised the transport used a
built-in id. Step 10's own round-trip test is the clearest example: it proved
the id survives the hop, using `spectro_segmentation_v0`… composed in the same
interpreter, where the parent's registration was still visible.

Scoring is the sharpest illustration that this was a real oversight rather
than a staging decision: it had the manifest in hand since Step 11 and still
resolved its data path registry-only. The manifest was there; nothing asked it
this question.

#### D-BC-12 — the resolver lives in the composition layer

| field | value |
|---|---|
| **Decision ID** | **D-BC-12** |
| **Phase / checkpoint** | C / C3 |
| **Question** | Which layer owns the four-row resolver: `execute_tools/task_data_path.py` (the seam) or `workflows/task_composition.py` (the composer)? |
| **Options considered** | (i) the seam, with a lazy `workflows` import; (ii) the composition layer, called lazily by each child |
| **Chosen ruling** | **(ii)** — `resolve_child_task_data_path` beside `compose_metric_from_manifest`, the Step-11 sibling it is shaped after |
| **Why** | The seam is the module every task implementation imports; pulling `workflows` into it inverts the layering and puts a cycle one edit away. The composer already depends on the seam, already owns `_load_symbol`, and already has a child-facing per-family entry point with exactly this shape. The children import it lazily inside `main()` — the pattern `denoising_score_single.py` has used since Step 11 |
| **Consequence** | Training and inference now import `workflows.task_composition`, but only on a composed run and only at the call site |
| **Material deviation?** | **no** — "no new loader" is satisfied: `_compose_task_data_path` is the same authority the parent used |

#### The four rows, and the one that is easy to get wrong

| row | condition | outcome |
|---|---|---|
| 1 | registered, identity matches (or none pinned) | use it |
| 2 | registered, identity DIVERGES | **REFUSE** (C2's `TaskDataPathIdentityError`) |
| 3 | not registered, manifest composes it | compose, register, **then verify** |
| 4 | not registered and not composable | **REFUSE naming BOTH facts** |

**Row 2 is not row 4, and the membership test is what keeps them apart.** The
resolver asks `task_data_path_id in registered_task_data_path_ids()` rather
than catching a resolution error, because catching would let a *divergent*
registration fall through into the composing row — turning C2's refusal into a
silent re-composition. That is C-P56-1 one layer down, and it is the shape an
exception-driven implementation lands in by accident. Pinned by
`test_a_divergent_identity_is_NOT_treated_as_a_MISS`, which hands the resolver
a manifest it COULD compose and requires it to refuse anyway.

**Row 3 verifies too.** An id the child composed itself is exactly as unproven
as one it looked up; "I just loaded it" is not evidence about what the PARENT
resolved. `test_the_composed_implementation_is_VERIFIED_against_the_parent_pin`
is its own test for that reason, and the census
(`test_the_check_lives_in_the_ONE_function_every_child_calls`) now requires
`verify_transported_identity` in the composing row explicitly.

**Row 4's message names both facts** — what the child holds AND whether a
manifest reached it. "Unknown id" and "no manifest arrived" send an operator to
different files, and a refusal that names only one of them costs a debugging
session.

#### D-BC-9 — the bootstrap census is right; it was half a statement

The census (`test_task_data_path_census.py`) pins the child bootstrap import
set EXACTLY to the three built-ins, and §E.4 predicted a child-side loader
would trip it. It did not — because the chosen mechanism composes **by path**
through the existing authority and imports no task module at all. So there was
nothing to extend.

What the census *did* need was its complement. Read alone it invites the
conclusion that those three are the only resolvable implementations, which is
the exact opposite of this PR's claim.
`TestTheBootstrapSetIsAFloorNotACeiling` states the other half: a child
resolves an id in NO bootstrap, and the composing route is censused to import
no task implementation — so a fourth task still needs zero framework edits.
Extending the pinned set by adding a fourth built-in remains a visible,
deliberate edit, exactly as before.

#### What landed

| surface | change |
|---|---|
| `workflows/task_composition.py` | `compose_task_data_path_from_manifest` (the `compose_metric_from_manifest` sibling) and `resolve_child_task_data_path` (the four-row table) |
| `core/sandbox_executor.py` | `_task_manifest_argv()` now emitted at the **training** and **inference** spawn sites as well as scoring; the emitter itself is unchanged, so R-11-1 holds by construction |
| the three children | each parses `--task_manifest` and resolves through the one four-row authority; none calls the registry-only entry point any more |

#### Guards that flipped, and what they became

C2's census named `resolve_transported_task_data_path` as "the function every
child calls", and C3 moved the children off it — three parametrized failures,
correct ones. Per **R-11-10** the guard became a permanent owner rather than
being twinned:

* `test_the_child_PASSES_it_to_the_resolver` now names `CHILD_RESOLVER` and
  keeps asserting the thing that actually matters — *the child passes what it
  parsed*. That phrasing survives the next move; "the child calls function X"
  would not, and would say nothing about whether the value survived it.
* `test_no_child_bypasses_the_four_row_resolver` is new and is the other
  direction: a child still calling the registry-only resolver would work for
  the built-ins and fail for exactly the tasks this PR exists to support.
* `test_the_check_lives_in_the_ONE_function_every_child_calls` now covers
  **both** rows.

#### Validation

```
.venv/bin/python -m pytest \
  tests/unit/execute_tools/test_step12_pr12bc_c3_child_loading.py -q
```

**22 passed.** Broader targeted set (`guardrails/`, `workflows/`, `core/`
transport, `execute_tools/`): see below. `ruff check` + `ruff format --check`
clean.

**Not claimed here.** No child was actually SPAWNED — every assertion above is
in-process, against the parent's real argv. A real out-of-tree plugin loaded by
a real spawned child, and a tampered plugin refused there, is `G-12bc-C`'s
evidence, and that Gate is now unblocked.

#### Targeted regression, and the Step-11 guard C3 inverts

```
.venv/bin/python -m pytest tests/unit/guardrails/ tests/unit/workflows/ \
    tests/unit/core/test_step10_p1_c3_transport.py tests/unit/execute_tools/ -q
```

First run: **2 failed / 3,300 passed / 2 skipped**, both in
`test_step11_c5_scoring_metric_acquisition.py::TestOnlyScoringGetsTheManifest`
— the guard whose NAME is the thing C3 disproves. Step 11 recorded "only
scoring needs it" as an R-11-4 scoping decision; it was true of the METRIC and
false of the task data path, and C3's audit is what separated the two.

Disposed per **R-11-10**, retired rather than twinned:

| member | disposition |
|---|---|
| `test_the_emitter_is_used_once_and_only_by_scoring` | **RETIRED.** The count is now 3, and its owner is C3's `test_the_emitter_is_used_at_all_three_spawn_sites`, which states it with the reason. A second copy here is exactly the twinning R-11-10 forbids |
| `test_training_and_inference_do_not_get_it` | **RETIRED** — it asserted the defect. Its surviving half (an un-composed child gains nothing) is owned by `test_the_un_composed_child_argv_gains_no_manifest_flag`; the positive by the end-to-end hop |
| the class itself | **RENAMED** `TestTheManifestTransportIsBindingScoped`. The remaining three members are Step 11's own and are untouched: the emitter needs a binding, produces the flag when bound, and secondaries are still not transported |

Re-run after disposition: **44 passed** across both modules; the full targeted
set is green.

#### One more check the unit tests could not make

A **real fresh interpreter**, from `cwd=/tmp`, with the fourth task copied to a
temporary directory:

```
resolved in a REAL fresh interpreter, cwd=/tmp: spectro_segmentation_v0 SpectroTaskDataPath
```

Not a Gate — no child was spawned — but it rules out the two things an
in-process test cannot see: a `sys.path` assumption and a cwd assumption.

#### §J after C3

| function | baseline (C0) | now | branch delta |
|---|---|---|---|
| `_compose_task_data_path` | 19/9/63/2 | 23/11/94/2 | **+2** |
| `_load_symbol` | 33/13/85/3 | 35/14/95/3 | **+1** |
| `register_task_data_path` | 11/5/26/1 | 16/6/57/1 | **+1** |
| `resolve_task_data_path` | 13/4/27/1 | unchanged | 0 |
| `bind_run_task_composition` | 25/4/80/2 | unchanged | 0 |

All within the §J budget (branch +3, LOC +80, params +1); **zero parameter
growth** anywhere. `workflows/task_composition.py` is 1,628 LOC against
`COMPOSITION_LOC_AT_C0 = 1475` — a constant C0 declared and never asserted.
**C4 owns that**: either it becomes a real assertion with a stated budget, or
it is deleted rather than left looking like a guard.

---

### Q.C4 — the guarantees become guards, and the sweep finds a defect in a guard.

#### F-12bc-6 — the flip detector that never fired

C0 wrote an inverted guard whose job was to announce C3's landing:

```python
def test_no_child_composes_a_data_path_from_a_manifest_today(self, child):
    assert "_compose_task_data_path" not in code, (
        f"{child} now composes a data path — C3 has landed; retire this guard."
    )
```

C3 landed. The guard stayed **green**, message and all. It named the PRIVATE
composer; C3 reached composition through the public sibling
`resolve_child_task_data_path` (D-BC-12), which is the correct design and
which the guard could not see.

**The lesson generalizes and is worth more than the fix.** A flip detector
asserts what an *unwritten* implementation is expected to look like — which
means it is written at the moment its author knows least about the shape the
work will take. Name a symbol and you detect one implementation; name the
PROPERTY and no implementation can dodge it. The corrected owner asks *"can a
child resolve an id it never imported?"* in a real fresh interpreter:

```
TestAChildCanResolveWhatItNeverImported::test_a_fresh_interpreter_resolves_an_out_of_tree_id
```

which additionally rules out the two things no in-process test can see — a
`sys.path` assumption and a cwd assumption.

This is the same family as F-P2b-4 (the anchored-regex census blind to a
leading underscore) and the B7 censuses that read COMMENTS: **a census green
for the wrong reason**. Third occurrence in this PR lineage; the common cause
is a guard written against TEXT rather than BEHAVIOUR.

Two sibling members were retired with it, recorded in place at C0:
`test_a_child_today_can_ONLY_resolve_what_it_imported` (its assertion survives
under an accurate class name — it is true of the REGISTRY resolver, which C3
did not change) and `test_the_census_exists_and_pins_an_exact_set` (pure
indirection at an executable census that owns itself).

#### The R-11-10 sweep, made executable

`TestR1110Sweep` is a standing census over every test function in the suite:

* **11 retired inverted guards** must not be defined anywhere. A retired guard
  that returns is a duplicate that will one day disagree with its replacement —
  and the inverted half is the one that passes for the wrong reason, because it
  asserts the defect.
* **5 corrected properties** must be defined **exactly once**, naming the file.
  This is the half a deletion sweep silently breaks: retiring the inverted
  guard is only safe because the positive contract exists somewhere.

Result: every guard inverted by B6, B7, C1 and C3 is now a permanent owner or
deleted. **Zero twinned.**

#### §J — the comparison across both phases

| function | baseline | now | branch Δ | budget |
|---|---|---|---|---|
| `_compose_task_data_path` | 19/9/63/2 | 23/11/94/2 | **+2** | +3 |
| `_load_symbol` | 33/13/85/3 | 35/14/95/3 | **+1** | +3 |
| `register_task_data_path` | 11/5/26/1 | 16/6/57/1 | **+1** | +3 |
| `resolve_task_data_path` | 13/4/27/1 | unchanged | 0 | +3 |
| `bind_run_task_composition` | 25/4/80/2 | unchanged | 0 | +3 |

Phase B's own comparison (§Q.B8) found **exactly one** baselined function
gaining any branch nodes, with the tuner's `run()` ending SMALLER. Across both
phases: **zero parameter growth anywhere**, and no function gained a branch
family.

**`COMPOSITION_LOC_AT_C0 = 1475` is deliberately NOT asserted.** C0 declared
it and never used it, and `workflows/task_composition.py` is now 1,628 lines —
so an LOC ceiling would fail. It would be failing for the wrong reason: the
growth is C3's two child-facing entry points, which belong beside their
Step-11 sibling `compose_metric_from_manifest`, and blocking them would push
the resolver into the seam module, which D-BC-12 rejects on layering grounds.

§J's actual sentence is *"the overlay is its own module, not a growth of the
composer"*, and that is what
`test_the_composer_did_not_become_the_overlay` asserts — as **ownership**:
`run_registration_scope`, `retire_registrations` and `_SCOPE_BASELINE` must
not appear in the composer, and the composer must still USE the overlay (or
F-12bc-2's rollback becomes unreachable). A dangling constant that looks like
a guard is worse than no constant; it is either an assertion or it is deleted.

#### Doc sync — and what the quoting caught

`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`:

* the Step-11 C5 bullet said the manifest goes to the scoring child. **Now
  false** — C3 widened it to all three, and the bullet says why (the metric
  reasoning was right; the data-path reasoning was never made).
* a new subsection documents CAP-SCOPE: the optional sibling capability, the
  four methods, the artifact + digest hop, and the Q-12-4 `DatasetProfile`
  split into generic identity + opaque topology.

**The quoting rule earned its keep on my own prose.** I wrote that
`ScopeBuildRequest` carries "round kind, selection strategy, portion, seed,
target partitions". Read back against source it has **eight** fields —
`max_samples` and `subset_ref` were missing. Corrected before the commit. This
is exactly why the rule says *quote each documented value against source*
rather than *review the docs*: I had written that sentence from memory of B1,
and B1's field set had been extended since (D-BC-1a, the `seg_size` payload).

#### Validation

```
.venv/bin/python -m pytest tests/unit/guardrails/ tests/unit/workflows/ -q
```

**1,189 passed** across `tests/unit/guardrails/` + `tests/unit/workflows/`
(97 s); C4's own module + the corrected C0 baselines account for 33 of them.
`ruff check` + `ruff format --check` clean.

---

### Q.C-GATE — `G-12bc-C`. It FAILED first, and it was right to.

#### The witness, and what discriminates it from `G-12bc-B`

`G-12bc-B` asked *"did the right SCOPE arrive and get consumed?"* and
discriminated on a row count (16 vs 48). `G-12bc-C` asks *"did the right
IMPLEMENTATION arrive, under a verified identity?"* and discriminates on which
markers the child prints:

```text
[G12BCC-LOADED]    the out-of-tree plugin MODULE executed in the child
[G12BCC-CONSUMED]  the child called the task's OWN training_dataset

RUN 1 (untampered)  LOADED + CONSUMED, no refusal
RUN 2 (tampered)    LOADED, NOT consumed, and a named identity refusal
```

Both runs spawn a real training child through `TidmadSandbox.execute_training`
— the production spawner — with the Step-10 P1 **fourth task** composed from a
manifest outside the repository.

**What run 2 proves, stated precisely.** The plugin module DOES execute in the
child, and must: you cannot verify code you have not loaded, and the composing
row loads before it verifies. What must not happen is CONSUMPTION. Parent §7
says *"validated … BEFORE the child consumes it"*, and that is the claim the
evidence supports. The harness's first docstring claimed the refusal preceded
loading; that was corrected before the recorded run, because the witness
cannot support it.

**No GPU, no training, no scoring.** `device=cpu`, one epoch, and the child
dies inside dataset construction. A tiny fcnet is constructed on CPU first —
the engine builds the model before the dataset — and that is recorded rather
than engineered around: moving the check to avoid it would test an ordering
production does not have.

#### F-12bc-7 — the pin was a re-read (found by the Gate's FIRST launch)

Launch 1 verdict: **run 2 loaded AND consumed the tampered plugin.** No
refusal. Every C2 unit test was green.

```text
parent registers   -> registry captured   cb1a75b3…    a real pin
plugin edited      ->
parent spawns      -> TRANSPORTED         469101f4…    a RE-READ
child composes     -> computed            469101f4…    they match
                   -> the child ran the tampered code
```

`content_identity()` hashes the defining module's source **file**, so it
re-reads the disk on every call. C2 used it directly in `transport_argv`,
which meant the "parent-pinned identity" was re-derived at SPAWN time from
whatever was on disk then — it followed the very edit it exists to catch. The
bind-to-spawn window C2 was written to close was still wide open.

**Why every C2 test passed** is the transferable part, and it is a test-design
lesson, not a coding one. Each of them did:

```python
pinned = content_identity(impl)     # a STRING, held across the edit
...
assert content_identity(edited) != pinned
```

The test pinned a **value**; production pinned a **function call**. A test that
captures what production recomputes cannot see a recomputation defect, however
adversarial the scenario around it is. The replacement
(`TestThePinIsCapturedNotReRead`) asserts through the production emitter
across a real file edit.

**Fix.** `effective_identity(impl)` prefers the identity CAPTURED at
registration (`_CONTENT[id]`, already written by C1.1 — the capture WAS a
genuine pin, nothing was consulting it) and computes only for an
implementation nobody registered. Used by both `transport_argv` and
`verify_transported_identity`. The semantics are also simply more correct: an
identity is a claim about the object in memory, and once a module has
executed, the file can say anything.

This is why the frozen rule says *a production defect is a FAIL to be
diagnosed and fixed, never re-launched hoping for green* — and why the Gate
was not collapsible into deterministic evidence. **11,000+ unit tests, 3
purpose-built identity modules, and an adversarial C2 test suite did not see
it. One real spawn did.**

#### F-12bc-8 — a test-isolation / import-registration lifetime defect

**Classification, stated because it is easy to get wrong** (operator
correction, 2026-08-23): this is **not** a census defect. The census defects in
this PR are exactly two — F-12bc-6 and F-12bc-9. F-12bc-8 is a
**test-isolation / import-registration lifetime** defect.

**And it is not how CASE A was closed.** CASE A was already closed,
independently, by C1's production lifecycle mechanism (the two-phase
registration rule plus the run-scoped overlay) — the restricted reproducer went
9 failed / 1,306 passed → 1,315 passed with the duplicate same-id /
different-content refusal intact and no test-specific reset or ordering hack.
F-12bc-8 surfaced **afterwards**, in the regression suite of an unrelated fix,
and its collection-time bootstrap fixes only the test harness. Reading it as
part of the CASE-A closure would credit a test-side change with a production
guarantee it did not provide.

Fixing F-12bc-7 required a targeted re-run, and that re-run went red in
`test_step10_p1_c3_transport.py` — a module Phase C never touched. Cause:

```text
C1 imports execute_tools.tidmad_data_path INSIDE a test body
  -> that test's fixture has replaced _REGISTRY with {}
  -> the module-tail registration lands in the TEMPORARY dict
  -> teardown restores the real dict, which never got `tidmad`
  -> the module is now in sys.modules and NEVER registers again
  -> an unrelated module fails, three modules later
```

The same *shape* as CASE A, one layer over — a registration whose visibility
depends on when the import happened — but in the harness, not in production.
Fixed by performing the built-ins' bootstrap at
**collection** time in the three Phase-C modules — the one moment guaranteed
to precede every test. Not a production defect: production imports the
built-ins at child startup, before anything patches anything.

#### Result — `G-12bc-C` **PASS**

| check | run 1 (untampered) | run 2 (tampered) |
|---|---|---|
| argv carried `--task_data_path_id` | yes | yes |
| argv carried `--task_data_path_identity` | yes | yes |
| argv carried `--task_manifest` | yes | yes |
| out-of-tree plugin loaded in the child | **yes** | yes |
| out-of-tree plugin **consumed** | **yes** | **no** |
| named identity refusal | no | **yes** |

The refusal names both sides:

```text
task data path 'spectro_segmentation_v0' resolved in this child, but it is NOT
the implementation the parent pinned.
  parent pinned:  …@5da9da24d5293710e7df8f943835d4f220a7706802b6664922f3a370a5bcb558
  child resolved: …@6429fb56a1de11bfbee794914e7dfda9235734542b7119b07695c9a4ebbecd82
```

Exact SHA, evidence path and preserved artifacts recorded with the commit
below.

---

### Q.BC-FINAL — the §G plant matrix, and a census that could not see the ABI.

#### The matrix

Nine plants, each a single textual mutation of production source. Hygiene per
the standing rule: assert the anchor occurs **exactly once**, clear every
`__pycache__` so no stale bytecode answers instead, run the owner, restore
from the **original bytes held in memory** (never `git checkout`, which
restores more than it should), then re-run the owner to prove the baseline
returns. A plant whose baseline does not come back proves nothing.

| plant | owner | verdict |
|---|---|---|
| task-name dispatch in a generic module | `test_step10_p1_c4_extension_proof.py` | **RED** |
| a central `{"tidmad": …, "pets": …}` mapping table | `test_step10_p1_c4_extension_proof.py` + `f_checkpoint.py::test_no_central_task_mapping_table_exists` | **RED** |
| a fourth built-in imported onto a surface with no bootstrap role | `test_task_data_path_census.py` | **RED** |
| sever the manifest transport hop | `c3_child_loading.py` | **RED** |
| sever the child identity check | `c2_identity.py` | **RED** |
| the pin becomes a re-read again (F-12bc-7 regression) | `c2_identity.py` | **RED** |
| sever the scope-artifact digest verification | `b4_scope_artifact.py` | **RED** |
| sever the scope transport hop | `b6_scope_transport.py` | **RED** |
| a scope-kind branch in a generic module | `f_checkpoint.py::test_no_scope_kind_dispatch_in_generic_core` | **RED** *(after F-12bc-9)* |

Two initially came back GREEN. One was my harness naming the wrong owner (the
mapping table is owned twice over, by the class-(b) dispatch census and by the
§F checkpoint). The other was real.

#### F-12bc-9 — the census that could not see `execute_tools/`

```python
GENERIC_PREFIXES = ("core/", "workflows/", "nodes/", "agent/")
TASK_OWNED = (
    "execute_tools/tidmad_data_path.py",     # <- exempting files
    "execute_tools/pets_data_path.py",       #    from a directory
    "execute_tools/davis_data_path.py",      #    nobody scanned
)
```

**The omission is self-evidencing.** `TASK_OWNED` exempts three
`execute_tools/` files, and those exemptions could never fire, because nothing
under that directory was ever scanned. An exclusion list that cannot exclude
anything is a statement about what its author meant to include.

It matters more than a coverage gap: `execute_tools/` is where the scope ABI
lives — `scope_artifact.py`, `task_data_path.py` — so the single most
important generic surface in this PR was the one surface all three §F item-9
checks were blind to. A `"tidmad_scope_v1" in payload` branch could have been
added to the artifact reader at any point in Phase B and every census would
have stayed green.

Fixed by adding the prefix. **The landed tree is already clean under the wider
scope** — 52 additional files, zero offenders across all three checks — so
nothing was exempted to make it pass (the Step-11 C9 rule: widening may
surface pre-existing leaks; record them, never exempt by name). Re-planted
afterwards: RED, and the baseline returns.

**Third census-blindness finding in this PR** (F-12bc-6's symbol-named flip
detector, F-12bc-9's scope list, and — in the lineage — F-P2b-4's anchored
regex). They share one cause: **a census is code, and nobody censuses the
censuses.** The three failure shapes are now on record — a guard that names a
symbol, a guard that names a token exactly, and a guard whose FILE SET omits
the surface it exists to protect. The last is the hardest to see, because the
guard is green, its assertions are correct, and it is simply pointed
elsewhere.

---

### Q.CI — F-12bc-10: the type system enforcing the sibling rule

CI run **32629448399** on `089eef55` failed at **pyright** with three errors,
all one class:

```text
core/sandbox_executor.py:944            Cannot access "serialize_scope"    for class "TaskDataPath"
execute_tools/train_engine_sandbox.py:1759  Cannot access "deserialize_scope" for class "TaskDataPath"
nodes/…/ml_hyperparameter_tune_agent.py:450 Cannot access "trial_anchor_path" for class "TaskDataPath"
```

**The checker is enforcing this PR's own architecture.** `TaskScopeCapability`
and `TaskTrialAnchoring` are OPTIONAL SIBLINGS — the frozen four-method
`TaskDataPath` does not declare their methods and must not. Three call sites
reached for a sibling method off a value typed as the base protocol, which is
precisely the thing the sibling design forbids. Every one of them was reachable
only when the capability was present, so no test could see it; the type is what
carries the claim.

The narrowing authorities already existed and the sites simply bypassed them:

| site | fix |
|---|---|
| `_task_scope_argv` | `capability = resolve_task_scope_capability(bound)` before the loop |
| `_load_transported_scope` | verify FIRST (B4's invariant, unmoved), then narrow through the same resolver |
| the tuner's trial anchoring | `declares_trial_anchoring` is now a `TypeGuard[TaskTrialAnchoring]`, and the access moved into the branch where the guard is TRUE |

The last one is the interesting one. The predicate returned a bare `bool`,
so it answered the question and then discarded the answer — the caller's whole
reason to ask is to reach for `trial_anchor_path` next. It was also written
`elif not declares_trial_anchoring(...)`, putting the access in an `else` a
`TypeGuard` does not narrow. Both halves are now aligned: the guard narrows,
and the access sits where narrowing applies. Behaviour is unchanged.

**Recorded as a limitation working as intended, not as a surprise.** §Q.C2
states plainly that local pyright cannot run in this environment (the vendored
binary needs a newer Node than the box provides) and that strict type checking
is CI's, at the final head. That is exactly what happened: the one check I
could not run locally is the one that found something, and it found a real
architectural leak rather than a formatting nit.

#### Both Gates RE-RUN at the final head

`486ea47f` changes production **after** both Gates ran (F-12bc-10's narrowing).
The delta is behaviour-preserving at every reachable site — but "behaviour-
preserving" is an argument, and `G-12bc-B`'s failure class runs through
**exactly the two functions that changed** (`_task_scope_argv`,
`_load_transported_scope`). Both Gates were therefore re-run at `486ea47f`
rather than reasoned about. Cost: ~2 minutes combined, well inside the frozen
envelope.

| Gate | first PASS | re-run at `486ea47f` |
|---|---|---|
| `G-12bc-B` | `8fd80cdc` | **PASS** — `Epoch 0: 16/16` (scope consumed), not 48; digest recomputed equal; artifact bytes are the task's own |
| `G-12bc-C` | `2ad868e3` | **PASS** — identical verdict on every check |

Evidence appended in place under
`/home/klz/Data/SIDEREIS_DATA/gate_evidence/step12_pr12bc_gate_{b,c}/`, with
each `EXACT_SHA` recording both the original and the re-run SHA.

**This is not a re-launch hoping for green.** Neither Gate had failed; the
question was whether a later production change moved the ground under evidence
already recorded. Re-running is cheaper than the argument and settles it.
