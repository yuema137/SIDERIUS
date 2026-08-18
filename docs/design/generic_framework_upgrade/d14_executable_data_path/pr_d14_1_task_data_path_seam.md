# D14-1 — The TaskDataPath seam: TIDMAD relocated at byte parity — child design

## 0. Status

**FROZEN — rev 2, 2026-08-18** (parent authority:
`../d14_executable_data_path.md`, FROZEN rev 3). Operator verdict on rev 1:
**APPROVED TO IMPLEMENT AFTER THREE CHILD-LEVEL CORRECTIONS** — no further
operator review. Rev 2 applies them: (1) transport-authority clarification
(no operator-facing task-selection knob; the internal subprocess argument
carries only the already-resolved binding), (2) the fail-closed resolver
truth table (legacy regime-A compatibility is discriminated by BINDING
SEMANTICS, never by task name), (3) parity evidence frozen BEFORE relocation
(C2 split into C2a evidence-only / C2b move-only) plus the Gate-2 baseline
captured before any behavioural relocation. The §8 pass re-run against the
operator's five named traps closes clean. Implementation proceeds
autonomously from C1, stopping only on a parent §7 condition or at
`D14-1 PR — READY FOR OPERATOR REVIEW`.

Source audited at `e5e28864`: `train_engine_sandbox.py` (:295-449 the class;
:905-935 the validation-family site + exact-materialization check; :1442-1460
the per-epoch training site), `inference_single.py` (:654-687, :854-863 read;
the `derive_tidmad_deliverable_spec` → `create_abra_file` write),
`dataset_config.py:591-672` (the ContextVar binding pattern),
`deliverable_spec.py`, `models_sandbox.py::MODEL_REGISTRY`.

## 1. What this PR delivers (from the parent, not re-decided)

The four-method `TaskDataPath` contract + fail-closed registry; TIDMAD's
executable path relocated behind it at **byte parity**; the full-surface
synthetic second implementation; the fail-closed negative; the no-dual-path
AST census; the guardrail token-set extension. No Pets/DAVIS code, no profile
change, no `examples/` change. **CLI, stated honestly (correction 1): an
internal subprocess CLI transport argument is added; no new operator-facing
configuration surface.**

## 2. Module homes and the one structural move

```text
execute_tools/task_data_path.py        NEW — contract (typed Protocol),
                                       registry, fail-closed resolution,
                                       run-scoped binding (ContextVar, the
                                       dataset_config.py:591 pattern) +
                                       explicit subprocess transport arg
execute_tools/tidmad_data_path.py      NEW — the TIDMAD implementation:
                                       TIDMADEpochDataset MOVED VERBATIM here
                                       (one git-visible move, bytes unchanged
                                       within the file), + codec delegation to
                                       derive_tidmad_deliverable_spec /
                                       create_abra_file (imports, not copies)
execute_tools/train_engine_sandbox.py  re-exports TIDMADEpochDataset from the
                                       new home (compat alias, so every
                                       existing import keeps working); its two
                                       construction sites become seam calls
execute_tools/inference_single.py      read loop + writer become seam calls
```

Why the class moves rather than the implementation importing it in place:
`tidmad_data_path` importing from `train_engine_sandbox` while the engine
imports the registry would be circular. The verbatim move + compat re-export
is the Q-07c-1 pattern (one owner, no shim logic) and keeps parity reviewable
as a pure relocation diff.

## 3. The contract, concretely (types finalized here per the parent's MUTABLE list)

```python
class TaskDataPath(Protocol):
    task_data_path_id: ClassVar[str]

    def training_dataset(self, scope: object, params: EpochSamplingParams) -> Dataset: ...
    def validation_dataset(self, scope: object, params: EvalMaterializationParams) -> Dataset: ...
    def write_deliverable(self, outputs: TaskOutputBatchIter, request: DeliverableWriteRequest) -> None: ...
    def read_evaluation_payload(self, request: EvaluationReadRequest) -> object: ...
```

* `scope` is **opaque** (parent). The two `*Params` carriers hold only the
  framework-level sampling/validation-posture knobs the call sites pass today
  — epoch seed, `train_portion`, `max_samples` / `validation_max_samples`
  ceilings, data_dir — so no knob is silently dropped in relocation. They are
  small frozen dataclasses, not a config hierarchy (§20.6).
* Datasets yield `(model_input, supervision_target)` per Amendment 1. For
  TIDMAD both happen to be the same int windows (a denoising autoencoder-style
  task) — which is exactly why the **synthetic** implementation must have
  target ≠ output representation, or the seam would never meet the asymmetry.
* **Exact-materialization stays task-owned.** The :905-935 check reads
  `file_row_ranges` — TIDMAD per-file vocabulary. It RELOCATES INTO the TIDMAD
  implementation's `validation_dataset` (same `ValidationScopeError`, same
  message, same trigger conditions — parity-asserted). The 07a invariant
  ("declared scope materializes exactly, fail closed") becomes each
  implementation's obligation, stated in the contract's docstring; Pets/DAVIS
  discharge it against their manifests at D14-2/3. The framework does not
  gain a scope-vocabulary-aware checker (issue #225's boundary).

## 4. Binding and resolution (fail-closed, Amendment 3 + corrections 1–2)

### 4.1 One configuration authority (correction 1 — FROZEN)

```text
task / run configuration  ->  resolve run-scoped TaskDataPath  ->  internal
subprocess transport (--task_data_path_id, the --dataset_profile_json
precedent)  ->  child-process binding
```

**No new operator-facing task-selection CLI knob.** The internal argument
exists SOLELY to carry the already-resolved binding across a process
boundary; it is emitted by the parent from the resolved binding and is never
an independent source of truth. A focused test proves the transported id
equals the resolved binding, and that no normal launcher/operator surface
supplies it independently (the launcher argv census gains this token as a
forbidden operator flag).

### 4.2 The resolver truth table (correction 2 — FROZEN)

| binding context | id | result |
|---|---|---|
| **legacy frozen regime-A** (NO explicit task-binding context exists — today's every campaign) | absent | TIDMAD compatibility implementation |
| **explicit / new task binding** (a binding context object is present) | absent | **FAIL CLOSED** |
| any | known registered id | that implementation |
| any | unknown id | **FAIL CLOSED** (`TaskDataPathResolutionError` naming the id and the registered set) |
| registration time | malformed implementation / missing protocol methods | **refused at registration**, before any execution |

**The discriminator is the PRESENCE of an explicit binding context, never a
task name** — no `if task_name == "tidmad"` anywhere. Concretely: the
resolver takes `TaskBindingContext | None`; `None` IS the legacy regime-A
compatibility path (the launch surfaces that predate task binding), and a
context object whose data-path id is absent fails closed. A future Pets run
necessarily constructs a binding context, so a missed binding step FAILS
rather than silently training on TIDMAD's path.

Required deterministic tests (all three, C1): legacy `None` context →
TIDMAD-compat id resolved · synthetic explicit context with absent id → RED
with the naming diagnostic · synthetic context with unknown id → RED.
`bind_task_data_path(impl)` ContextVar carries the resolved binding
in-process (the `dataset_config.py:591` pattern).

## 5. Commit plan (this child freezes it)

| commit | content | validation gate before the next |
|---|---|---|
| **C1** | `task_data_path.py`: contract, registry, fail-closed resolution, binding + transport. The synthetic implementation (test-registered) with target-representation ≠ output-representation. NO production call-site change | unit: registration/resolution/fail-closed matrix; the synthetic Dataset yields the asymmetric pair; ruff |
| **C2a** | **PRE-RELOCATION EVIDENCE ONLY — no relocation.** Capture and COMMIT the immutable parity manifest from the current head: training iteration-order hashes across the frozen epoch/portion/freeze grid, validation counts/ranges/hash, deliverable byte sha256, expected run/scoring record content — each entry recording the source commit SHA, fixture hashes, and the generation command. **Plus the ONE bounded TIDMAD Gate-2 BASELINE run at this pre-relocation head** (exact commit + posture + evidence location persisted for C6's comparison) | the manifest file is committed and thereafter BYTE-IMMUTABLE for the life of the PR; a test pins its sha and its recorded source commit |
| **C2b** | class moved verbatim into `tidmad_data_path.py` + compat re-export + codec delegation. **Compared against the frozen C2a manifest** — expected values are READ from the committed artifact, never recomputed | manifest byte-unchanged (its pin test); parity green against it; import graph acyclic; every existing `TIDMADEpochDataset` import still resolves |
| **C3** | trainer sites :910/:1448 → seam calls; exact-materialization check relocated into the TIDMAD impl | parity oracle re-run; `ValidationScopeError` trigger parity (the 07a tests already pin it — they must pass UNCHANGED); 07a/07c suites green |
| **C4** | inference read loop + deliverable writer → seam (`write_deliverable`, `read_evaluation_payload`); scoring read path through the payload | deliverable byte parity; scoring records identical on the fixture; step06 two-route oracle green |
| **C5** | full-surface synthetic end-to-end through `run_experiment_streaming`; the fail-closed negative; guardrail token-set extension (`tidmad|pet|davis` on the data-path surface); the **no-dual-path AST census** | census reports zero direct constructions/codec deps outside `tidmad_data_path.py`; delete-the-hop mutation (bypass the registry → census + e2e fail) |
| **C6** | docs sync (engine/module docs; this child's ledger §9); the ONE bounded **Gate 2** run through the relocated path at the final executable head; parent §15.1-row note deferred to the D14-3 milestone close | Gate 2 PASS = the evidence PAIR (C2a baseline vs this run, same posture) answers "did relocating execution behind TaskDataPath preserve the real TIDMAD lifecycle and scientific outputs?" — records/deliverable/score identity, no new warnings on the kill/cleanup path. Unit parity owns deterministic byte equivalence; Gate 2 owns the real lifecycle |

Per-commit validation is targeted only (the #221 rule); the full suite runs
once via exact-head CI at the single push.

## 6. Parity oracle — precise definition

On the committed two-family fixture, fixed seeds, PRE captured at `e5e28864`:

1. training epoch streams: sha256 over the concatenated `(model_input,
   supervision_target)` tensor bytes **in iteration order**, 2 epochs ×
   both `freeze_subsample` settings × `train_portion ∈ {None, 0.5}`;
2. validation materialization: row count + per-file ranges + the same hash;
3. deliverable: file bytes sha256 after a fixed-output write;
4. records: `run_output` + scoring record deep-equal (the #221 serialization
   oracle already guards the byte form).

Any diff at any commit = stop that commit, not "explain later".

**Self-reference prohibition (correction 3 — FROZEN).** Expected values live
ONLY in the committed C2a manifest. No parity test may compute
`expected = <implementation>(…)` at runtime — and in particular the compat
re-export means "the old implementation" IS the new one after C2b, so an
old-vs-new runtime comparison would silently compare the new code with
itself. The #221 self-referential-expectation guardrail plus the manifest's
sha-pin test enforce this mechanically.

## 7. Test-layer ownership (parent §H, applied)

UNIT: contract/registry/fail-closed matrix; parity oracles; census; the
synthetic e2e (in-process, deterministic — structural genericity, not a fake
Gate-2). GATE 1: none. GATE 2: one bounded TIDMAD run (C6). CI: the #221
selector routes `execute_tools/` changes; this PR touches a hub-adjacent
surface so a full-suite PR run is expected and correct.

## 8. Adversarial self-review (child)

* **Params carriers becoming a config hierarchy?** They mirror EXISTING call
  arguments only; anything new is a stop. Checked against §20.6 — they are
  function-argument dataclasses, never serialized to config.
* **The compat re-export becoming a permanent dual path?** The census
  deliberately counts *constructions and codec calls*, not imports — the
  alias is import-compat only; constructing through it at a generic call site
  still fails the census.
* **Exact-materialization relocation weakening 07a?** The 07a tests pin the
  error and its trigger; they must pass unchanged — the behaviour moves, the
  contract does not. If any 07a test needs editing, that is a §7 parent stop
  (a Step-07 public contract change), not a test fix.
* **The synthetic task accidentally TIDMAD-shaped?** Its data is generated
  in-memory (no HDF5, no files-and-segments), its scope is a plain list of
  string ids, its target is a scalar while its output is a vector — three
  independent axes away from TIDMAD.
* **Circular imports** — resolved structurally by the class move (§2); C2's
  gate asserts acyclicity.

### 8.1 Rev-2 pass — the operator's five named traps

| trap | closed by |
|---|---|
| dual configuration authority | §4.1: the transport argument is emitted from the resolved binding only; the launcher argv census forbids it as an operator flag; one authority chain, test-pinned |
| silent missing-binding → TIDMAD | §4.2: the truth table keys on the PRESENCE of a binding context, so an explicit task with a missed binding step fails closed; three deterministic tests required at C1 |
| self-referential parity expectations | §6: expected values only from the committed C2a manifest, sha-pinned; runtime recomputation prohibited |
| "old implementation" parity secretly running the NEW code through the re-export | same mechanism — after C2b there is no independent old implementation to call, which is exactly why the evidence must predate the move; the manifest's recorded source SHA proves it does |
| Gate-2 baseline captured after behavioural relocation | C2a runs the baseline BEFORE any call-site change (C3/C4), with commit + posture + evidence persisted; C6 runs the single counterpart |

No parent conflict found. **Child FROZEN at rev 2; implementation begins at
C1.**

## 9. Ledger

(appended per commit during implementation)

### C1 — contract, fail-closed registry, synthetic implementation (landed)

`execute_tools/task_data_path.py` (new, ~330 lines) +
`tests/unit/execute_tools/test_task_data_path.py` (15 cases). No production
call-site change, as frozen.

**Implemented exactly as §3/§4:** the four-method `runtime_checkable`
Protocol; frozen Pydantic param carriers mirroring only existing call-site
knobs (task vocabulary — `seg_size`, the profile — deliberately absent);
registration-time refusal of malformed implementations naming the missing
methods; the §4.2 truth table row-for-row with diagnostics naming the id and
the registered set; the `bind_task_data_path` ContextVar
(`dataset_config.py:591` pattern); `transport_argv(impl)` taking the
IMPLEMENTATION so the transported id cannot differ from the binding
(correction 1 enforced by signature); `resolve_transported_task_data_path`
treating a transported id as an EXPLICIT binding so transit corruption fails
closed.

**The three REQUIRED deterministic tests are in and green** (legacy `None` →
compat id; explicit context + absent id → RED with "never fall back";
unknown id → RED naming both sides), plus the row-1 edge (regime-A with no
registered compat implementation fails loudly rather than no-op).

**The synthetic implementation meets Amendment 1's strengthening
measurably:** float32 `[4]` model input, scalar `int` target (not a tensor),
simulated `[2]` output — shape, rank and dtype all differ; the full
four-method surface round-trips in-process (deliverable = JSONL, payload
read back equal). C5 upgrades this to the `run_experiment_streaming` e2e.

One C1-level note for C2b: the TIDMAD stand-in used by the truth-table tests
registers under `TIDMAD_COMPATIBILITY_ID` from inside the tests — when the
real implementation lands and registers at import, those tests keep their
isolated-registry fixture and are unaffected.

Validation: 15 passed · ruff check + format clean. Commit: (this commit).

### C2a (part 1) — the frozen pre-relocation parity manifest (landed)

`tests/unit/execute_tools/goldens/d14_tidmad_parity_manifest.json`, generated
from **`a715b84e`** (C1's head — `TIDMADEpochDataset` still at its original
site) by the recorded command
`.venv/bin/python -m tests.helpers.d14_tidmad_parity --write`; capture helper
`tests/helpers/d14_tidmad_parity.py`; oracle tests
`test_d14_tidmad_parity.py` (2): the manifest's own sha256 pinned as a
hardcoded literal (`341b232c…`) with the recorded pre-relocation commit
asserted, and the deep-compare of the current implementation against the
committed evidence — fixture hashes first, so a drifted fixture is never
misattributed as a dataset regression. Double-run green (determinism).

**Recorded deviation (scope of the manifest).** The child's C2a list named
run/scoring record content as a fourth evidence family. Not duplicated here:
those bytes are already golden-pinned by their own suites (REC goldens, the
scoring suites, the #221 serialization oracle), which must pass UNCHANGED
through the relocation — a second copy would be a second authority for the
same bytes, the exact defect class #221 §10 retired. The manifest owns the
three families no other suite pins at this granularity: training streams
(seed×portion grid), validation materialization, deliverable bytes.


### C2a (part 2) — Gate-2 BASELINE spec (written BEFORE the run, directive §10)

**Claim.** At the pre-relocation head (`c1871029`), the real TIDMAD lifecycle
— real HDF5 data → real GPU training → R3 validation → inference →
deliverable → scoring — completes through the CURRENT direct-construction
data path, producing the record/deliverable/score identity that C6's
relocated-path run will be compared against. This is the "before" of the
evidence pair; without it, C6 could only compare against itself.

**Why this subset is still discriminative.** The claim is the DATA PATH
lifecycle, not LLM behaviour (Gate 1 = NOT REQUIRED for D14, directive §12) —
so the LLM is the stub (`--is_pseudo_llm`, production `StubLLMBridge`) while
training/validation/inference/scoring stay REAL on the real 5090. One
iteration × one trial round exercises every stage the claim names once.

**Bounded configuration** (≤10 min target; cold start, no `--seed_paths`;
DS8-paired partial scope; watchdog left at default OFF — it is not part of
this claim and 07c owns its pricing):

```bash
SIDERIUS_ALLOW_LAUNCH=1 bash sdsc_submission_scripts/run_chain.sh \
  --mode lilab --workspace /home/klz/Data/SIDEREIS_DATA/d14_gate2_baseline_20260818 \
  --run_name d14b --num_iterations 1 --model wavenet \
  --is_pseudo_llm --llm_config llm_configs/openai_tiered_pro.json \
  --max_rounds 1 --max_proposal_attempts 3 --max_epochs 1 \
  --data_scope 15-19 --health_gate_files 15,16,17,18,19 \
  --trial_portion 0.02 --train_portion 1.0 --eval_portion 0.01 \
  --trial_time_budget_minutes 5 --trial_vram_budget_gb 12 \
  --no-force_formal_round --progress_bar --cleanup_denoised
```

**Expected success evidence:** chain rc=0 · ≥1 record with real
`training_history` (R2+R3), real `timing.*`, a scored trial
(`denoising_score` present) · the run_output validates · evidence preserved
at the workspace (never deleted). **Failure** = any lifecycle stage absent;
**inconclusive** = infrastructure-only interruption, diagnosed before any
rerun.

### C2a (part 2) — Gate-2 BASELINE post-run record: **PASS** (2026-08-18)

**Executable head** = `c1871029` exactly as the spec claims: the run happened
at HEAD `cd663333`, which is `c1871029` + one docs-only commit (this spec
section; `git show --stat` = 1 design-doc file, 38 insertions).

**Canonical invocation** (deviations from the spec command above, all
launcher-level, none touching the claim): the spec named three flags the
chain parser does not have — `--model` (the pseudo-LLM chain proposes its own
arch; no such chain flag), `--progress_bar`, `--cleanup_denoised` (neither in
`_chain_common.sh`) — dropped; the log was placed OUTSIDE the workspace
(`chain_attempt5.log` beside `ws/`, not inside it); and `--start_iter 1` was
pinned (see the FINDING below). Everything else ran verbatim: cold start,
`--data_scope 15-19` paired with `--health_gate_files 15,16,17,18,19`,
`--is_pseudo_llm`, 1 iteration × 1 trial round, `--max_epochs 1`,
portions 0.02/1.0/0.01, `--trial_vram_budget_gb 12`,
`--no-force_formal_round`, watchdog default OFF, real RTX 5090.

**FINDING (launch-attempt audit, 5 attempts).** 1–2: unknown flags above,
caught by the parser before any run. 3: "Workspace not empty" — the chain log
had been placed inside `ws/`. 4: **rc=0 with ZERO iterations executed** —
`iter 1 → MISSING`, empty workspace. SOURCE AUDIT: the pre-created `ws/`
routed `run_chain.sh::resolve_start_iter` into the auto-resume inspector;
`START_ITER=$(inspect_run_state.py … --next-iter)` captures stdout, and
importing `core.resume` (→ `core.sandbox_executor` → `models_sandbox` module
tail → `ml_models/plugin_loader.py:153` bare `print`) emits 98
`[PluginLoader]` lines on stdout at import time; the polluted `START_ITER`
broke every numeric test (`integer expression expected` in the log) and the
iteration loop ran nothing while the wrapper still exited 0. WHY IT MATTERS:
any resumed campaign silently no-ops with rc=0. DECISION: production defect,
resume-path-only, out of D14 scope → **issue #226**; baseline unblocked with
the documented manual pin `--start_iter 1` (`run_chain.sh:247` returns before
the inspector). Attempt 4's `chain.log` retained beside the evidence as the
diagnostic artifact. 5: PASS.

**Semantic evidence (rc was NOT the verdict):**

* `run_output_iter_001.json` **validates as `HyperparamTuningOutput`**
  (status=`completed`, completed_rounds=1, 1 record).
* Record `stub_arch_001_a_iter_001_001`: `is_trial=True`,
  `denoising_score=-1.5272668194789296` (scored trial PRESENT),
  `timing = train 76.1 s / inference 6.3 s / scoring 14.5 s` (all real),
  `training_history` R2+R3 REAL: `train_objective=[4.96249]`,
  `validation_objective=[4.99998]` (5 000 ML segments),
  `validation_seconds=[63.57]`, `epochs_completed=1`,
  `comparability=established`.
* Record status `failed_mode_collapse` = a HealthGate FIRING on the 1-epoch
  stub arch — the real gate lifecycle working, not a missing stage; the chain
  manifest's `status=no_records` is next-iteration ADMISSION semantics.
  Every stage the claim names ran: real HDF5 → GPU train → R3 validation →
  inference → deliverable → scoring.

**Wall time:** chain exit 11:56:35; run-artifact write window
11:54:47 → 11:56:34 (107 s); launch→exit ≈ ≤6 min — inside the ≤10 min bound.

**Evidence location (preserved, never deleted):**
`/home/klz/Data/SIDEREIS_DATA/d14_gate2_baseline_20260818/`
(`ws/` + `chain_attempt5.log` + attempt-4 `chain.log`).

**C6 comparison contract:** the relocated-path run must reach the SAME
lifecycle stages with the same record shape (R2+R3 rows, timing keys, a
scored trial, validating run_output). Float equality across gate runs is NOT
expected (CUDA nondeterminism); byte-level parity is owned solely by the
immutable C2a manifest.

### C2b — relocation landed (2026-08-18)

`execute_tools/tidmad_data_path.py` NEW: `TIDMADEpochDataset` moved VERBATIM
(the 174-line class block is byte-identical — embedded-block sha256
`b407be14860196b0…`, asserted mechanically during the move); per-module
`_h5_dataset` copy (the established inference_single/scoring_utils pattern —
importing the engine's would recreate the cycle the move avoids);
`TidmadScope` (task-owned opaque scope: sample_set + seg_size + profile);
`TidmadTaskDataPath` delegating all four methods (datasets → the moved class;
write → naming authority + stale-file removal + flatten/storage-cast +
`create_abra_file(..., indexed=False, storage=spec.storage)`, byte-matching
the two audited writer sites; read → exact naming round-trip resolution to
`{file_index: path}`); module-tail registration under
`TIDMAD_COMPATIBILITY_ID` (inert until C3/C4). The engine re-exports via an
explicit `as` alias, so all three pre-existing importers (parity helper,
step02b roundtrip test, `evaluate_time_skill/wrapper.py:336`) resolve to the
ONE moved class — identity asserted.

**Recorded decisions.**
1. **Carrier fill-in (pre-authorized by C1's committed docstring):**
   `model_type: str` added to `DeliverableWriteRequest` and
   `EvaluationReadRequest` — the writer-site audit showed
   `DeliverableNaming.name` requires it; per-file identity stays OUT of the
   framework carriers (it travels in the task-owned outputs items /
   resolved payload keys — TIDMAD vocabulary).
2. **No `from __future__ import annotations` in the new module:** under lazy
   annotations ruff UP037 forces de-quoting an annotation INSIDE the moved
   block, breaking byte parity. Eager annotations keep the block verbatim;
   noted in the module docstring.
3. **pyright could not run locally** (pyright-python Node loader crash —
   the known environment limitation). Static typing is validated by
   exact-head CI at the single push; not claimed locally.

**Validation:** manifest byte-unchanged (its pin test); parity green against
it through BOTH surfaces — direct construction (the C2a oracle now resolving
through the re-export) and the NEW seam-delegation suite
`test_tidmad_data_path.py` (5 tests: all four grid cells' stream hashes, the
validation rows/ranges/hash, deliverable byte-sha vs the manifest across a
DIFFERENT filename, exact-round-trip payload resolution incl. foreign-file
exclusion, foreign-scope TypeError). Blast-radius suites green in the same
run — the monkeypatch sites (`test_rt2b_streaming_preamble`,
`test_step07a_c1_validation_pass`) and attribute constructions
(`test_dataset_contract`) all operate on the one moved class object through
the alias. **68 passed / 0 failed** across the 7 targeted suites; ruff
check + format clean on all touched files.

### C3 — trainer construction sites behind the seam (landed 2026-08-18)

Both engine sites are seam calls; `TIDMADEpochDataset(` constructions now
exist ONLY in `tidmad_data_path.py`. **Zero test files edited** — the frozen
07a condition. Mechanics:

* `run_experiment_streaming` resolves ONE `data_path =
  resolve_bound_task_data_path()` per run (§4.1 one-authority: the binding,
  never a parameter — an impl parameter would be a second authority) and
  gains opaque `task_scope` / `task_eval_scope` params (`None` = regime-A
  assembly of `TidmadScope` from the legacy arguments — discrimination by
  PRESENCE, the truth-table pattern, never task name).
* Per-epoch site → `data_path.training_dataset(task_scope,
  EpochSamplingParams(data_dir, epoch_seed, train_portion, max_samples))`;
  the impl reconstructs `random.Random(epoch_seed)` — stream-identical,
  pinned per manifest grid cell. `epoch_rng` local dropped (its only use).
* `_validation_pass` (module-private, one caller, no direct test callers —
  audited) now takes `data_path` + `task_eval_scope` + `data_dir`; the
  construction AND the exact-materialization check moved into
  `TidmadTaskDataPath.validation_dataset` — same `ValidationScopeError`,
  same message bytes, same dual total+per-file comparison; the requested
  side is the same `len(segments) × ml_segs_per_psd` arithmetic the engine
  preflight uses. `_requested_validation_rows` deleted (its only consumer
  relocated). Engine preflight checks (missing file / short file / zero
  rows) STAY engine-side, unchanged.
* `ValidationScopeError` moved to `task_data_path.py` (the seam contract
  module — the obligation's failure type lives beside the obligation; every
  implementation raises it in its own vocabulary) with an engine `as`
  re-export; the 07a/07c suites import it through both paths unchanged.
* Engine argv gains internal `--task_data_path_id` (child side of the §4.1
  transport, the `--dataset_profile_json` two-case rule: SUPPLIED+unknown →
  fail closed; ABSENT → regime-A). Nothing emits it in production yet —
  regime-A campaigns are untouched end-to-end.

**FINDING (defect caught during C3, by the 07c guard).** First assembly
point for the regime-A eval scope was BEFORE the 07c C6 clamp, freezing the
PRE-clamp scope; `TrainingHistory` failed closed
(`validation_samples (24) != validation_requested_samples (10)`) in the
three `TestTheClampInARealRun` cases. SOURCE AUDIT: `clamp_validation_scope`
rebinds `eval_sample_set` at run start (:1182); the eval scope must be
assembled from the EFFECTIVE post-clamp set. DECISION: assembly moved beside
the final preflight; training-scope assembly stays early (`sample_set` is
never reshaped). The failing tests were the invariant WORKING — production
fixed, tests untouched.

**Validation:** 153 passed / 0 failed — 07a validation-pass suite UNCHANGED
(trigger parity incl. "materialized 16 ML rows"), 07c envelope + persistence
timing, rt2b/rt2c, ordering, dtype boundary, workload envelope, both parity
oracles, C1 suite. ruff check + format clean. pyright: CI-owned (local
runner broken, see C2b note).

**Known TIDMAD-vocabulary residue deliberately left (not C3 scope, recorded):**
sequential ordering reads `dataset.file_row_ranges` (attribute access on the
returned dataset — census counts constructions/codec calls, not attributes);
the legacy single-file `TIDMADDataset` path in `main()`; `main()`'s
TIDMAD-shaped argv. These are the engine-genericization seams for later
steps, not D14-1 relocation targets.

### C4 — inference writer + scoring read behind the seam (landed 2026-08-18)

**Ownership reading that sized this commit (parent §3.1, quoted):** the
deliverable NAMING/layout authority is explicitly NOT TaskDataPath's ("It
does NOT own … what the deliverable is named/laid out (the task's
deliverable authority)"), so `derive_tidmad_deliverable_spec` staying in the
two children for storage representation, logging names and the reuse probe's
addressing is parent-sanctioned. What relocated is the CODEC: the byte
writer, the deliverable reader, and the scoring-side payload resolution.

* **inference_single**: both run-identified writer sites (streaming loop +
  single-file agent mode) are `data_path.write_deliverable([(file_index,
  denoised, injected)], DeliverableWriteRequest(...))` — the impl resolves
  the SAME authority name, removes the stale file, and performs the
  identical flatten/storage-cast ABRA write (byte parity pinned by the
  manifest-backed delegation suite). The Phase-6.7-Fix-2 free-before-write
  ordering is preserved (del/gc precede the seam call) and its AST guard
  now recognizes the seam write. `_is_complete_trial_output` MOVED verbatim
  to `tidmad_data_path.is_complete_trial_output` (a deliverable READER
  belongs with the codec — its own 05c docstring says it is a reader) with
  an inference alias so the 05c test import and every call site are
  unchanged. Child transport honored (`--task_data_path_id`, two-case rule);
  the seam calls run under `bind_dataset_profile(dataset_profile)` so the
  impl derives the spec from the profile THIS child transported, never the
  ambient default.
* **denoising_score_single (agent mode)**: the deliverable path now comes
  from `read_evaluation_payload` — "the scoring read path through the
  payload". A file the payload lacks falls back to the authority-derived
  EXPECTED path, so the Step-06 scoreability contract still owns the
  structured missing-deliverable refusal (failure mode byte-identical; the
  impl returns `{}` for a missing directory for the same reason —
  documented on the method). `fix`/`none` modes keep local authority naming
  (no run/exp identity; not the production data path). Registration via the
  recorded side-effect import (`# noqa: F401` — the canonical registration-
  import idiom, not a lint bypass; the module tail IS the used effect).
* **Recorded C4 exemptions (for C5's census scope):** the fix-mode
  single-file writer keeps `create_abra_file` (baseline deliverables carry
  no run/exp identity, which the request requires); non-data-path importers
  of `create_abra_file` to be dispositioned when the census is written —
  `scripts/score_tidmad_official_*.py` (operator tooling),
  `core/sandbox_executor.py`, `execute_tools/evaluation_metric.py`,
  `execute_tools/deliverable_spec.py` (audit at C5).

**One test updated, with diagnosis:** `test_inference_single.py::
TestTrialModeDelPlacement` — its DETECTOR looked for a bare
`create_abra_file` name in the trial loop; its own failure message says
"refactor may have moved it; update this test". The protected property
(canonical 6-name `del` BEFORE the deliverable write) is unchanged and still
asserted; the detector now also matches `.write_deliverable` inside a
`with`. Not a 07a-frozen test.

**Validation:** 256 passed / 0 failed across the C4 battery — inference
(incl. checkpoint loading, rt2d verification), all six 05c deliverable
suites, all four step06 suites (the two-route subprocess oracle among them),
the three scoring suites, workload resolvers, both parity oracles, C1/C2b
suites. ruff check + format clean. pyright: CI-owned.

### C5 — synthetic e2e, fail-closed negative, guardrails, census (landed 2026-08-18)

* **`tests/unit/execute_tools/test_d14_synthetic_e2e.py` (3 tests)** — the
  full-surface synthetic task (in-memory pairs, list-of-string-ids scope,
  scalar-int target vs `[2]`-float output; its own `ModelIOContract`
  declaring float32 `[B,4]`→`[B,2]`, since the contract — not any TIDMAD
  default — is the engine's dtype authority) trains through the PRODUCTION
  `run_experiment_streaming` body under `bind_task_data_path`, then
  completes outputs → deliverable → payload; a determinism pair; and THE
  deterministic negative — the same synthetic scope under regime-A (a
  missed binding) raises `TypeError("…TidmadScope…")` from TIDMAD's scope
  check with nothing persisted: never a silent train on TIDMAD's path.
  In-process and unit-owned (#221 layers): structural genericity, not a
  fake Gate 2.
* **`tests/unit/guardrails/test_task_data_path_census.py` (5 tests)** —
  (1) `TIDMADEpochDataset` constructions: EXACT pinned counts, owner-only
  (tidmad_data_path = 2); (2) `create_abra_file` calls: tidmad_data_path =
  1, inference fix-mode = 1, zero anywhere else (counts, not imports —
  child §8; the earlier "importer" suspects were prose mentions only);
  (3) delete-the-hop static detector (engine resolves the binding, seam
  methods invoked in all three callers); (4) §4.1: `task_data_path_id`
  forbidden in every launcher `*.sh` — the transport is parent-emitted
  only; (5) task-identity guardrail — zero comparisons against
  `tidmad|pet|pets|davis` literals on the five data-path surface files
  (the surface list grows at D14-2/3).
* **FINDING (the census's first run caught a live dual path).** The
  GPU-warmup timing probe `agent/skills/evaluate_time_skill/wrapper.py`
  still constructed `TIDMADEpochDataset` directly. Relocated through the
  seam (`resolve_bound_task_data_path().training_dataset(TidmadScope(...),
  EpochSamplingParams(epoch_seed=0, train_portion=1.0, ...))` — the
  `random.Random(0)` reconstruction is stream-identical), so under a
  future non-TIDMAD binding the probe refuses loudly instead of silently
  timing TIDMAD data. Blast radius green (57 passed across the four
  consumer suites).
* **Delete-the-hop MUTATION PROOF** (hygiene per the standing memory:
  occurrence count asserted == 1, `__pycache__` cleared, git-revert,
  baseline re-run): mutating the engine's
  `data_path = resolve_bound_task_data_path()` into a direct
  `TidmadTaskDataPath()` bypass turned RED the census detector AND both
  positive e2e tests (`3 failed`); after byte-exact revert, all 8 green.
  Exactly the child's acceptance: "bypass the registry → census + e2e
  fail".

**Validation:** census 5/5 + e2e 3/3 green; wrapper consumer suites 57
passed; ruff check + format clean on every touched file.

### C6 (part 1) — Gate-2 RELOCATED-PATH spec (written BEFORE the run, directive §10)

**Claim.** At the final executable head (this commit — C2b→C5 landed, plus
the `workload_resolvers` ownership-docstring sync), the SAME real TIDMAD
lifecycle the C2a baseline exercised — real HDF5 → GPU train → R3
validation → inference → deliverable → scoring — completes THROUGH the
relocated TaskDataPath route: regime-A resolution → `TidmadTaskDataPath` →
moved `TIDMADEpochDataset` / seam deliverable write / payload-resolved
scoring read. PASS answers the child §5 C6 question: relocation preserved
the real lifecycle and scientific outputs.

**Posture: IDENTICAL to the C2a baseline** (its canonical invocation, new
workspace): cold start; `--start_iter 1` pinned (issue #226 workaround —
launcher-level, unchanged); `--data_scope 15-19` +
`--health_gate_files 15,16,17,18,19`; `--is_pseudo_llm` (Gate 1 NOT
REQUIRED — D14 has no LLM-facing change); 1 iteration × 1 trial round;
`--max_epochs 1`; portions 0.02/1.0/0.01; `--trial_vram_budget_gb 12`;
`--no-force_formal_round`; watchdog default OFF; real RTX 5090; ≤10 min.
Workspace `/home/klz/Data/SIDEREIS_DATA/d14_gate2_relocated_20260818/ws`,
log beside it.

**Success evidence (the PAIR comparison, C2a §"C6 comparison contract"):**
chain rc=0 AND semantically: run_output validates as
`HyperparamTuningOutput`; ≥1 scored trial record (`denoising_score`
present, real `timing.*`, `training_history` with real R2+R3 rows,
`comparability=established`); the SAME lifecycle stages as the baseline
with the same record shape; no new warnings on the kill/cleanup path.
Float equality across the two gate runs is NOT expected (CUDA
nondeterminism); byte-level parity is owned by the immutable C2a manifest
(unit suites). **Failure** = any baseline-reached stage absent or a record
shape delta; **inconclusive** = infrastructure-only interruption, diagnosed
before any rerun.

### C6 (part 2) — Gate-2 RELOCATED-PATH post-run record: **PASS** (2026-08-18)

Executable head `05fbbe89` (C2b→C5 + the ownership-docstring sync; the spec
section above is in the same commit). Launched with the identical canonical
invocation (new workspace, `--run_name d14r`); chain rc=0 — and the verdict
is the PAIR, not the rc:

| surface | C2a baseline (pre-relocation, `c1871029`) | C6 relocated (`05fbbe89`) |
|---|---|---|
| chain verdict | `CHAIN COMPLETE`, iter 1 manifest | `CHAIN COMPLETE`, iter 1 manifest |
| run_output | validates; `completed`; 1 round; 1 record | validates; `completed`; 1 round; 1 record |
| record | trial `failed_mode_collapse` (HealthGate fired) | trial `failed_mode_collapse` (same gate) |
| `denoising_score` | −1.5273 (present) | −0.9484 (present) |
| `timing` (s) | train 76.1 / infer 6.3 / score 14.5 | train 118.2 / infer 9.3 / score 12.9 |
| `training_history` | R2=[4.9625], R3=[4.99998] @5000 rows | R2=[4.9689], R3=[4.9790] @5000 rows |
| comparability | `established` | `established` |
| warnings/tracebacks | 1 traceback / 0 warnings / 0 errors | 1 traceback / 0 warnings / 0 errors |

Every lifecycle stage the baseline reached, the relocated route reached —
real HDF5 → GPU train (through `TidmadTaskDataPath.training_dataset`) → R3
(through `validation_dataset` incl. the relocated exact-materialization
check) → inference → seam deliverable write → payload-resolved scoring —
with the same record shape. Scores/timings differ as floats exactly as the
contract predicts (CUDA nondeterminism; timing also GPU-contention-bound);
byte-level determinism is owned by the manifest-backed unit parity.

**The one traceback is PAIR-IDENTICAL and PRE-EXISTING** (present in the
pre-relocation baseline log at the same site): the warmup probe's
`KeyError: 'segmentation_size'` under the pseudo-LLM stub plan — a caught,
designed fallback to the static formula ("warmup skipped"), stub-plan-only
(real plans carry the key). Not introduced, not widened, not material —
recorded here, no issue filed.

**Wall time:** run-artifact window 12:48:04 → 12:50:41 (156 s); launch→exit
well inside the ≤10 min bound. **Evidence preserved:**
`/home/klz/Data/SIDEREIS_DATA/d14_gate2_relocated_20260818/` (`ws/` +
`chain.log`), beside the baseline pair member.

**Answer to the C6 question:** relocating execution behind `TaskDataPath`
preserved the real TIDMAD lifecycle and scientific outputs. **PASS.**

### Pre-push verification — parallel chunks + integration differential (2026-08-18)

Broad local coverage per the standing rule (parallel chunks, never a serial
full suite; the full suite itself is exact-head CI's at the single push):

| chunk | result |
|---|---|
| `tests/unit/execute_tools/` (whole dir) | **1174 passed / 1 skipped** |
| `tests/unit/nodes/ + tests/unit/agent/` | **4138 passed** |
| `tests/integration/` (pseudo mode) | 185 passed / 128 skipped / **11 failed + 4 errors** |

**Every integration failure dispositioned — ZERO D14-1 regressions:**

* 13 of 15 reproduce at master `2f79762e` verbatim (clean worktree):
  fixture schema drift (`DatasetProfile` now requires
  `anchor_selection_files`/`health_peek_files`;
  `BootstrapDependencies.measurement_capability`), a patch target the 07b C7
  decomposition moved (`get_gates_for_position`), an empty-ForwardContract
  proposal fixture, and the data-scope tuner fixture family → **issue #227**
  (integration rot; CI is unit-only by design so rot is silent).
* `test_step06…two_real_routes_agree` — **pre-existing FLAKY**: 3×
  replication at master = 2 fail / 1 pass (branch 3/3 fail;
  indistinguishable at n=3). Mechanism: unseeded fixture training
  (no `torch.manual_seed`; `base_seed = hash(exp_id)` is
  PYTHONHASHSEED-random) sometimes collapses the 1-epoch model to an exact
  constant (deliverable std=0.000) → grand mean nonpositive → in-process
  `-inf` vs subprocess-JSON `None` (`coerce_nonfinite_to_none`) — a REAL
  two-route representational divergence on non-finite scores → **issue
  #228**. The C4-relevant fact: the deliverable itself passes the
  acceptance contract and the pass-through channel is byte-consistent —
  the writer relocation is not implicated.
* `test_g2_forecast…probed_batch` — **pre-existing,
  ENVIRONMENT-CONDITIONAL**: master in a clean worktree (no untracked
  `tidmad_data_config.yaml`) PASSES; copy this machine's yaml into the
  SAME master worktree → FAILS identically (probe capability defaults to
  `TIDMAD_DATA_DIR` → live probe launches → F-1a "no dataset directory"
  → evidence-channel termination). The differential's first reading
  ("branch-only failure") was an artifact of the worktree lacking the
  untracked config — refuted by the controlled rerun → **issue #229**.

**Methodology note (kept honest):** the initial single-run differential
misclassified two pre-existing defects as branch regressions; replication
(3×) and the config-controlled rerun refuted both. No production or test
code was changed in response to any of the 15.


### FINAL STATE — D14-1 (terminal closeout, 2026-08-18)

**Draft PR #230**, branch `d14-1-task-data-path-seam`, head **`77faff4d`**;
**exact-head CI run 32184157986 SUCCESS** (lint + pyright + unit). The one
commit after the first CI failure fixes five pyright sites at the seam's
`len()` / `file_row_ranges` consumers — runtime no-ops, 50 parity tests
green.

Acceptance, all met: byte-parity manifest immutable and green through BOTH
the re-export and the seam delegation · **Gate-2 evidence PAIR PASS**
(pre-relocation baseline `c1871029` vs relocated `05fbbe89`, identical
posture, same lifecycle stages and record shape, warning census identical)
· synthetic full-surface e2e + fail-closed negative · no-dual-path census
with the delete-the-hop mutation proof · 07a suites unchanged (zero test
edits at C3). Not merged; merge order #230 → #231 → #232 is the operator's.
