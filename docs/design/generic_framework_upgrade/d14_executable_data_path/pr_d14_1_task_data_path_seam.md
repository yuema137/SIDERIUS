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
