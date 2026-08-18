# D14-1 — The TaskDataPath seam: TIDMAD relocated at byte parity — child design

## 0. Status

**DRAFT rev 1 — self-frozen after the adversarial pass in §8 (parent
authority: `../d14_executable_data_path.md`, FROZEN rev 3).** Under the
parent's autonomy grant this child does not require a separate operator
review; implementation proceeds after §8 closes clean, stopping only on a
parent §7 condition or at PR-ready review.

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
AST census; the guardrail token-set extension. No Pets/DAVIS code, no CLI
change, no profile change, no `examples/` change.

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

## 4. Binding and resolution (fail-closed, Amendment 3)

`bind_task_data_path(impl)` ContextVar for in-process scope;
`--task_data_path_id` explicit transport into subprocesses (the
`--dataset_profile_json` precedent) — **absent id = regime-A compatibility →
TIDMAD; present-but-unknown id = `TaskDataPathResolutionError` naming the id
and the registered set.** Invalid implementations (missing methods) are
refused at registration, not at first use.

## 5. Commit plan (this child freezes it)

| commit | content | validation gate before the next |
|---|---|---|
| **C1** | `task_data_path.py`: contract, registry, fail-closed resolution, binding + transport. The synthetic implementation (test-registered) with target-representation ≠ output-representation. NO production call-site change | unit: registration/resolution/fail-closed matrix; the synthetic Dataset yields the asymmetric pair; ruff |
| **C2** | `tidmad_data_path.py`: class moved verbatim + compat re-export + codec delegation. **Parity oracle captured PRE-move on the two-family fixture** (epoch batch-stream hashes at fixed seed, validation-family selection, deliverable bytes) and asserted POST | the oracle is the gate; import graph acyclic; every existing `TIDMADEpochDataset` import still resolves |
| **C3** | trainer sites :910/:1448 → seam calls; exact-materialization check relocated into the TIDMAD impl | parity oracle re-run; `ValidationScopeError` trigger parity (the 07a tests already pin it — they must pass UNCHANGED); 07a/07c suites green |
| **C4** | inference read loop + deliverable writer → seam (`write_deliverable`, `read_evaluation_payload`); scoring read path through the payload | deliverable byte parity; scoring records identical on the fixture; step06 two-route oracle green |
| **C5** | full-surface synthetic end-to-end through `run_experiment_streaming`; the fail-closed negative; guardrail token-set extension (`tidmad|pet|davis` on the data-path surface); the **no-dual-path AST census** | census reports zero direct constructions/codec deps outside `tidmad_data_path.py`; delete-the-hop mutation (bypass the registry → census + e2e fail) |
| **C6** | docs sync (engine/module docs; this child's ledger §9); bounded **Gate 2** TIDMAD run through the relocated path; parent §15.1-row note deferred to the D14-3 milestone close | Gate 2 PASS criteria: run completes, records/deliverable/score byte-consistent with the pre-relocation baseline run at the same posture, no new warnings on the kill/cleanup path |

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

No parent conflict found. **Child self-frozen; implementation begins at C1.**

## 9. Ledger

(appended per commit during implementation)
