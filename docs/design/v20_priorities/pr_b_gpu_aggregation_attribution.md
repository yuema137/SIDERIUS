# PR B — Runtime GPU aggregate accounting and OOM attribution

**Status after the second operator review (2026-08-01):**

| Commit | State |
|---|---|
| **B-C1** | **IMPLEMENTED** `e75490f` — 36 tests, zero call sites, zero behaviour change |
| **B-C2a1** | **IMPLEMENTED** `90dcd24` — four call sites, zero semantic change |
| **B-C2a2** | **IMPLEMENTED** `f2e39a9` — plain path on `Popen`, 48 sites migrated, 6 retained; 1,979 passed, 0 escapes |
| **B-C2b** | **IMPLEMENTED** `2b6a5dd`/`33fa088`/`f1e91bf`/`a8d7824`/`accfeb9` — observer, four slots, `observed_peak`, device-identity provenance (FU-A-13 closed) |
| **B-C3** | **COMPLETE — CI green on exact head `5ba4a40`** (strict pyright included) — B-C3a `edf32b9` (interval counterfactual, 15-condition evidence gate, 91 tests + 6 mutation proofs); B-C3b wires it at the executor failure handler, gates both tuner shrink sites and adds the planner suppression note (64 tests + 4 mutation proofs, incl. production reachability) |
| **B-C4a0** | **REQUIRED PREREQUISITE** (operator, 2026-08-01) — extract the tuner control boundary B-C4 needs, so admission does not add branches to a `run()` that has no type-checking headroom left. Not started |
| **B-C4** | corrected; bootstrap resolved by **D-B5** (cold start belongs to PR C); awaiting re-review. **Blocked on B-C4a0** |

Parent scope: `docs/design/v20_priorities.md` §20.4 (start rule resolved
to REQUIRED on 2026-08-01).
Predecessor: `pr_a_isolated_preflight_wiring.md` — merged evidence in
§21–§24.

---

## 1. Why this PR exists

PR A removed the redundant memory the chain parent was holding. A6 then
measured what remains, and found the mechanism that is supposed to bound
it does not work — in two independent ways.

**1. Admission compares the wrong quantity.**

| A6 chain | pre-flight estimate | driver-visible peak | ratio |
|---|---|---|---|
| `wavenet` | 6.429 GB | **12,820 MiB = 12.52 GiB** | 1.95× |
| `punet` | 1.655 GB | 3,076 MiB = 3.00 GiB | 1.82× |

Chain A was admitted at 6.43 GB and then held 12.52 GiB — **past the
12 GiB per-attempt cap it was admitted under**. Admission predicts an
*allocated* peak; the host quota counts driver-visible *reserved*. So

```text
estimated <= 12 GiB   does NOT imply   driver-visible <= 12 GiB
```

Two samples do not establish a scaling constant, and PR B must therefore
**measure** the aggregate, never multiply an estimate by a factor.

**2. The pair ceiling is not enforced anywhere.**

`core/runtime_control/pair_admission.py` defines
`DEFAULT_PAIR_CEILING_GIB = 28.0` (`:45`) and a correct, tested
`evaluate_pair_admission` (`:150`). It has **zero Python callers** —
the only import in the tree is its own test
(`tests/unit/core/test_pair_admission.py:19`).

Two shell launchers do invoke its CLI —
`sdsc_submission_scripts/v19_queue_runner.sh:429` and
`v19_gate0_pair_runner.sh:311` — but both **suppress the result by
default**: the infeasible branch is guarded by
`if [ "${ALLOW_PAIR_CAP_OVERSUBSCRIPTION:-1}" != "1" ]`
(`v19_queue_runner.sh:433`), the variable is never set anywhere, and the
default path logs *"proceeding: the BINDING guard is the per-attempt
predicted-peak check"* (`:439`) — which finding 1 shows is not binding.

Both env vars the module reads are unset everywhere in the repo, so
`host_quota_gib()` always returns `None` and `pair_ceiling_gib()` always
returns the hardcoded 28.0. The quota-tightening branch (`:107-108`) has
never executed.

A6's pair was safe (15.52 GiB against 28 GiB) because the candidates
were small relative to the cap, not because anything made them so.
During A6 the only thing between the run and the host watchdog was an
external validation monitor that is not part of the product.

---

## 2. Objective and non-goals

**Objective.** Make the real, driver-visible GPU total controlled at
runtime, and make an OOM's cause correctly attributed before it can
influence an agent.

**In scope — exactly three things.**

1. Real driver-visible accounting: this chain's GPU process tree, the
   device total, and the remainder held by everything else.
2. A headroom check immediately before a GPU phase starts.
3. OOM attribution, with the agent-facing shrink instruction gated on it.

**Out of scope — restated so it cannot drift.** Automatic peer killing;
dynamic concurrency reshaping; a memory broker; a general GPU scheduler;
silent serial fallback; raising the 12 / 28 GiB or host-quota ceilings;
changing the pre-flight estimator itself; changing planner prompts beyond
suppressing a wrong signal; any change to training, inference or scoring
numerics.

**Sequenced, not deferred.** Changing `ALLOW_PAIR_CAP_OVERSUBSCRIPTION`
to fail-closed is authorized as PR B's **final** step (D-B4), and only
after B-G2 validates the new path. It is not in B-C1..B-C3, and if B-G2
does not run the default does not move.

---

## 3. Audit findings that shape the design

Performed 2026-08-01 against `feat/v20-pr-a-isolated-preflight`. Every
statement carries a file:line.

### 3.1 There is no peer identity anywhere in Python — resolved by D-B1

The launcher knows the pair (`v19_queue_runner.sh:412-413` builds
`ARCH_RUN` and `LOSS_RUN`) and **tells neither chain**: the launch
command at `:226-252` passes no peer flag, and there are zero `export`
statements in `_chain_common.sh`, `v19_queue_runner.sh` or
`v19_gate0_pair_runner.sh`. Concurrency is bounded by a bare constant
`MAX_CONC=2` (`:80`), not by resource accounting.

The one peer abstraction that exists in Python —
`calibration_policy.py:219` `sample_contention_window(..., expected_peer_pids=...)`
— is reachable only from `scripts/runtime_bootstrap.py` and
`scripts/runtime_campaign.py`, neither of which the chain invokes, and
peers there are operator-typed, never discovered
(`runtime_bootstrap.py:87-93`: *"peers are never inferred"*).

The only genuinely shared cross-process store is the calibration registry
under an advisory `flock`
(`core/runtime_control/calibration_registry.py:100,135`), rooted at
`~/.siderius` — a per-user calibration ledger with no memory-reservation
concept.

> **D-B1 — proposed: do not build a peer registry.**
>
> A headroom check does not need to know *who* holds the memory, only
> *how much is free*. `nvidia-smi` gives the device total and per-PID
> usage; our own tree is identifiable by ppid ancestry (the technique
> A6 validated). Everything else is "other", whether it is the paired
> chain, a foreign job, or a stray notebook.
>
> This avoids inventing cross-chain coordination — a new shared registry,
> its lock discipline, its staleness policy and its failure modes — which
> would be several times the size of the guard itself and would add a
> new distributed-state failure surface to fix a memory problem.
>
> **Cost of this choice, stated honestly:** without peer identity we can
> say "someone else holds 9 GiB", not "the loss chain holds 9 GiB". For
> the headroom decision that is sufficient. For attribution it yields
> `contention-attributable` but not `peer-` vs `foreign-`
> contention-attributable.
>
> **APPROVED 2026-08-01 — see §5 D-B1.** Peer-vs-foreign identity is a
> follow-up refinement, not a v1 requirement.

### 3.2 GPU child spawn points — two, not three

| Phase | Function | Launch lines | GPU? |
|---|---|---|---|
| training | `execute_training` `core/sandbox_executor.py:702` | watchdog `:834` / plain `:869` | **yes** |
| inference | `execute_inference` `:1000` | watchdog `:1129` / plain `:1164` | **yes** |
| scoring | `execute_scoring` `:1258` | `:1278` | **no — CPU-only** |

Scoring is CPU-only: zero `cuda`/`torch`/`device` hits in
`execute_tools/denoising_score_single.py`, and the role table agrees
(`sandbox_executor.py:93-95`, `"scoring": 24,  # CPU-only`). A headroom
check there would be a no-op, so PR B does not add one.

Clean insertion seams, each the complete pre-launch preamble:

- training `:827-829` — `print(...)`, `env = _subprocess_env(...)`,
  `preexec = _limited_preexec(...)`
- inference `:1124-1127` — same shape

> **Line numbers superseded by B-C2.** This audit predates the execution
> seam. The current insertion points are the observer construction sites
> — training `:1026`, inference `:1332` — each followed by two
> `_run_observed_subprocess` branches. The *finding* stands: two spawn
> points, not three, and scoring is CPU-only. See §B-C4 §3 for the
> re-verified locations.

**Asymmetry that dictates the interface.** Training's `try:` (`:745`) has
a generic `except Exception` (`:983`) that degrades a raise into
`{"status": "error", ...}`. Inference's `try:` (`:1123`) has **only**
`except subprocess.CalledProcessError` (`:1204`) — an exception raised at
the inference seam would propagate out of `execute_inference` uncaught.

> **Therefore the headroom check must return a status dict and never
> raise.** Both call sites already use an error-dict contract
> (`execute_training` returns 7 distinct statuses, `execute_inference`
> 4), so a new refusal status fits the existing shape.

`sandbox_executor.py` **never queries the GPU today** — grep for
`vram|hardware_context|nvidia|nvml|torch.cuda` returns only comments.
PR B introduces the first device visibility in that module.

### 3.3 OOM detection is split across four mechanisms

| # | Mechanism | Where | Detects |
|---|---|---|---|
| a | `_is_oom_failure` | `sandbox_executor.py:165-194` | **host RAM only** — `returncode == -9` or `\bMemoryError\b` |
| b | string match | tuner `:3261-3263`, `:3317-3319` | `"CUDA out of memory" in error_msg or "OutOfMemoryError" in error_msg` |
| c | `is_out_of_memory(exc)` | `probe.py:278-296` | correct exception-shape test, **not on the chain path** |
| d | `classify_host_memory_exception` | `probe_budgets.py:253-270` | host vs cuda, pre-flight worker only |

(a)'s word-boundary regex deliberately excludes `torch.OutOfMemoryError`
(docstring `:179-186`) — correct in itself, but it means the chain's only
CUDA-OOM detector is the **string match at (b)**.

**Two latent defects found, both relevant:**

- `"oom_host_ram"` is produced at `sandbox_executor.py:975`, `:1207`,
  `:1323` and has **no consumer anywhere**. The tuner branches only on
  `status == "error"` (`:3252`, `:3309`), so a SIGKILLed training child
  falls past every guard and proceeds to inference, which then fails the
  missing-sentinel check and is re-reported as a *silent training crash*
  (`:3325-3343`).
- `returncode == -9` is treated as host OOM, but **the host quota
  watchdog also kills by signal** — so a quota reap is currently filed as
  `oom_host_ram`, i.e. as a statement about the candidate.

### 3.4 The shrink instruction PR B must gate — CLOSED by B-C3b

> **Resolved.** Both literals now live behind `_oom_memory_wording`,
> which emits them only when the runtime attributed the failure to
> `candidate_gpu_capacity`. A reachability test asserts they appear
> nowhere else in the tuner, so a future call site cannot reintroduce
> the unconditional form. The audit finding below is retained because it
> is the clearest statement of what was wrong.

Two hardcoded string literals, written unconditionally whenever the
child's stderr contains `"CUDA out of memory"` — regardless of why:

```python
# nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:3293-3298
"discovery": "CUDA OOM — reduce model size, batch_size, or segmentation_size."
"memory_update": "This config exceeds GPU memory. Try smaller architecture."
# :3362-3368  (inference)
"CUDA OOM during inference — reduce batch_size or model size."
```

They reach the LLM verbatim: the record is `json.dumps`ed whole into the
planner prompt (`agent/prompts.py:922-925` → `:1135`), with the three
most recent records uncondensed. A standing instruction reinforces it
(`prompts.py:1139-1140`: *"Always follow the `memory.memory_update`
field"*).

**Precedent for suppression already exists**, written after the same
class of failure: `inconclusive_note` (`prompts.py:1018-1040`) — *"Do
NOT reduce model capacity … Only a MEASURED out-of-memory result … is
evidence about capacity."* PR B extends that pattern rather than
inventing one.

The nearest structural precedent for the vocabulary is
`NO_DOWNSIZING_AUTHORITY` (`isolated_probe.py:79-87`) with derived
properties `may_recommend_vram_downsizing` (`:300-303`).

### 3.5 Telemetry primitives that already exist

| Primitive | Where | Gives | Gap for PR B |
|---|---|---|---|
| `capture_contention_snapshot` | `probe.py:219-273` | device util + memory, compute PIDs, foreign PIDs, throttle | queries `--query-compute-apps=pid` **only** — no per-PID memory. `gpu_memory_used_gb` is actually GiB (`:265`) |
| `sample_worker_vram_gb(pgid)` | `probe_subprocess.py:128-155` | **per-PID `used_gpu_memory`, summed over a tree** | keyed on pgid; the pre-flight worker uses `start_new_session=True` so a session/pgid test misses it — ancestry is required |
| `ContentionSnapshot` | `probe.py:72-102` | frozen model, `telemetry_available` flag | not captured anywhere near training/inference |
| `evaluate_pair_admission` | `pair_admission.py:150` | ceiling arithmetic + reasons | zero callers |

Neither snapshot is taken before, during or after training, inference,
scoring, or the PR A pre-flight.

---

## 4. Commit plan

Five commits. Measurement first, then evidence, then attribution, then
enforcement — so that every gating decision added last is made from data
proven correct earlier.

---

### B-C1 — Driver-visible GPU accounting primitive

#### 1. Goal

Provide one tested way to answer *"how much GPU memory does this
process tree hold, how much does the device hold, and how much is held
by everything else"* — in driver-visible MiB, the quantity the host
quota counts.

It belongs first and alone because every later commit consumes it, and
because a measurement primitive can be landed with **zero behaviour
change**, making its own correctness reviewable in isolation.

#### 2. Scope

- **New**: `core/runtime_control/gpu_accounting.py` — pure functions
  plus one frozen Pydantic model.
- **New**: `tests/unit/core/test_gpu_accounting.py`.
- **Unchanged**: every existing module. No call sites are added in this
  commit.

Non-goals: no gating, no persistence, no attribution, no change to
`capture_contention_snapshot` (a sibling primitive kept as is; §6
records the overlap as a follow-up rather than a refactor here).

Dependencies: none.

#### 3. Implementation plan

- [ ] Read `probe_subprocess.py:128-155` `sample_worker_vram_gb` and
      `probe.py:219-273` `capture_contention_snapshot` in full before
      writing anything, and record which parts are reused verbatim
      versus re-implemented, with reasons.
- [ ] **Device identity — added after operator review 2026-08-01.**
      `sample(root_pid)` alone is ambiguous on a multi-GPU host:
      `--query-gpu` returns one row per device, compute-apps must be
      filtered per device, and a logical index under
      `CUDA_VISIBLE_DEVICES=0` need not be physical GPU 0. The signature
      is therefore `sample(root_pid, device_identity)`, and
      `DeviceIdentity` freezes:
      - physical **GPU UUID** — the primary key, preferred over any index
      - resolved device index
      - `CUDA_VISIBLE_DEVICES` as seen by this process
      - the GPU UUID the returned sample actually describes

      **Never "take the first row", and never sum across devices.**
      A sample whose UUID does not match the requested identity is a
      failure, not a fallback.
- [ ] Define `GpuAccountingSnapshot` (frozen, Pydantic): device used /
      total MiB, own-tree MiB, own PIDs with per-PID MiB, other MiB,
      other PID count, the `DeviceIdentity` above,
      `telemetry_available: bool`, and a units-explicit field naming
      convention (`_mib`, never a `_gb` field holding GiB — the bug at
      `probe.py:265`).
- [ ] **Make the accounting skew a field, not a comment.** The first
      draft said "record the skew" while the model had nowhere to put
      it. Add:
      - `per_pid_total_mib` — the sum over every listed compute app
      - `unattributed_mib` — device used minus that sum
      - `accounting_skew_mib` — the signed discrepancy, kept signed so a
        negative value (per-PID exceeding the device total, which the
        driver can transiently report) stays visible instead of being
        clamped into silence

      `other_mib` remains clamped at 0 for the *decision*; the skew
      field is what makes the clamp auditable rather than invisible.
- [ ] Implement ownership by **bounded ppid-ancestry walk**, not session
      id — the pre-flight worker runs with `start_new_session=True`
      (`isolated_probe.py:451`), so a session test would miss it. A6
      validated this technique.
- [ ] Implement `sample(root_pid: int) -> GpuAccountingSnapshot` using
      `nvidia-smi --query-gpu=memory.used,memory.total` and
      `--query-compute-apps=pid,used_gpu_memory`.
- [ ] Any failure to sample yields `telemetry_available=False` with all
      quantities `None` — never a zero, which would read as "nothing is
      held".
- [ ] Bound the subprocess call with an explicit timeout so a hung
      `nvidia-smi` cannot stall a training launch.

#### 4. Validation plan

**Unit** (no GPU; `nvidia-smi` invocation injected):
- [ ] parses a normal two-process listing correctly
- [ ] own-tree sum counts a grandchild (depth ≥ 2)
- [ ] own-tree sum counts a process in a **different session** (the
      pre-flight-worker shape)
- [ ] a PID that exits between the listing and the `/proc` read is
      dropped without raising
- [ ] `nvidia-smi` absent → `telemetry_available=False`, quantities
      `None`, no exception
- [ ] `nvidia-smi` non-zero exit → same
- [ ] `nvidia-smi` timeout → same, and the timeout is enforced
- [ ] malformed / partial CSV → same
- [ ] empty compute-apps (idle GPU) → device figures present, own-tree 0,
      other 0, `telemetry_available=True`
- [ ] `other_mib == device_used_mib - own_tree_mib` holds, and is
      clamped at 0 rather than going negative when the device total lags
      the per-PID listing

**Negative/invalid**: negative or non-integer PID; `/proc` unreadable.

**Backward-compatibility**: none required — nothing consumes this yet.

**Real-training Gate**: none.

#### 5. Acceptance criteria

- [ ] `GpuAccountingSnapshot` is constructible only in a consistent
      state (validator, as `PairAdmissionDecision` does at
      `pair_admission.py:137-147`).
- [ ] With a synthetic three-PID listing where two PIDs are descendants
      of `root_pid` and one is not, `own_tree_mib` equals the sum of
      exactly the two, and `other_mib` equals the third's usage.
- [ ] Every failure mode above returns `telemetry_available=False` and
      **no field is silently 0**.
- [ ] `git diff --stat` shows exactly two new files and no modified file.

#### 6. Failure and edge cases

| Case | Handling |
|---|---|
| `nvidia-smi` missing / non-zero / timeout / malformed | `telemetry_available=False`, quantities `None`. **Never** assume "0 held" |
| PID exits mid-sample | drop that row, continue |
| `/proc/<pid>/status` unreadable (permission) | treat as not-ours → counted in `other` (conservative: overstates the peer, never understates) |
| ancestry walk cycles or is very deep | hard hop bound (24, as A6 used) |
| device total < per-PID sum (accounting skew) | clamp `other_mib` at 0, record the skew |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/core/test_gpu_accounting.py -q
.venv/bin/ruff check core/runtime_control/gpu_accounting.py tests/unit/core/test_gpu_accounting.py
.venv/bin/ruff format --check core/runtime_control/gpu_accounting.py tests/unit/core/test_gpu_accounting.py
```
- [ ] test count and wall time recorded here after the run
- [ ] pyright: cannot run locally (Node availability unverified) —
      **CI only**, recorded, never claimed

#### 8. Commit boundary

Independently reviewable: a new module plus its tests, no call sites, no
behaviour change. Contains no cleanup of `capture_contention_snapshot`
and no follow-up work. Diff summary, staged file list and test output
shown before committing.

---

### B-C2a1 — Route GPU subprocesses through one execution seam

#### 1. Goal

Make all four GPU launches go through one function, so the observer in
B-C2b attaches once instead of at four call sites where a branch could
silently lose it. **Routing only**: both implementations underneath stay
exactly as they were.

#### 2. Why this is not one commit with the Popen migration

An earlier draft of B-C2a moved the plain branch to `Popen` in the same
change, on the reasoning that B-C2b needs the child PID. That was
implemented and then **measured**, and the measurement stopped it:

| Finding | Value |
|---|---|
| stubs aimed at `core.sandbox_executor.subprocess.run` | **58** |
| test files affected | **6** — `test_sandbox_executor.py` (25), `test_sandbox_rlimit.py` (12), `test_sandbox_executor_rt2b.py` (9), `test_sandbox_executor_rt2d.py` (4), `test_sandbox_scope.py` (3), `test_watchdog.py` (1) |
| assertions reading those mocks' `call_args` | **59** |
| observed consequence | **real `train_engine_sandbox.py` subprocesses launched out of the unit suite** |

That last row is the point. A stub aimed at a retired entry point does
not fail — it lets the real thing run, and the suite hangs instead of
erroring. PR A hit the identical shape when the pre-flight call site
moved; this was the same defect an order of magnitude larger. The
processes were terminated, the GPU returned to its 273 MiB baseline and
no orphan remained, but a multi-minute silent hang is exactly what a
"parity" commit must not be able to produce.

So the boundary the original B-C2a drew was too broad: it bundled a
test-infrastructure migration, an execution-mechanism change and (later)
a telemetry change, where any one could mask another. Three stages
instead:

```text
B-C2a1  route only            <- this commit, zero semantic change
B-C2a2  plain path -> Popen   <- owns the 58-stub migration
B-C2b   attach the observer   <- telemetry only
```

**The 58-site migration is not incidental test repair.** It is the
necessary consequence of changing a production execution seam, and it is
B-C2a2's declared work package.

#### 3. Scope

Four launch sites: training `:834`/`:869`, inference `:1129`/`:1164`.
The watchdog branch fires only when
`policy_obj is not None and policy_obj.watchdog.enabled and sample_set is not None`,
and the watchdog is **off by default**, so the plain branches are the
ordinary production path.

`_run_subprocess_with_watchdog` is generalized in place — renamed
`_run_observed_subprocess`, deadline made optional — rather than joined
by a second helper, which would leave two launch implementations to keep
in agreement.

Non-goals: no `Popen` migration, no telemetry, no stub migration, no
change to retry policy, candidate parameters, task numerics, status
interpretation, agent advice, or admission.

#### 4. The parity hazard that stays permanent

`subprocess.run` does not pass `start_new_session`; the watchdog passes
`start_new_session=True` because `killpg` needs its own group. Those are
different signal semantics: a child in the caller's process group
receives a terminal SIGINT, a child in its own session does not — and
the chain runs under `timeout --signal=INT`, so operator stop depends on
that signal reaching the work.

**The two modes must never be unified**, in this commit or in B-C2a2.
Pinned by a test rather than by intent.

#### 5. Test-safety guardrail (new)

`tests/unit/conftest.py` fails fast, with a `BaseException` subclass, if
any unit test is about to launch `train_engine_sandbox.py`,
`inference_single.py`, `denoising_score_single.py` or
`preflight_worker_main`.

It watches the **effect**, not the patch name, because both times this
defect appeared the tests *were* patching something — just no longer the
thing that runs. A name-based check would have missed both. It derives
from `BaseException` because `execute_training` wraps its body in a
generic `except Exception` that would otherwise degrade the guard into a
status dictionary.

Opt out with `@pytest.mark.allow_real_subprocess`, which makes an
intentional launch explicit and greppable.

#### 6. Acceptance — landed `90dcd24`

Recorded here 2026-08-01. These items previously lived only in the
superseded single-commit B-C2a section; condensing that section would
otherwise have left B-C2a1 with no acceptance evidence at all.

- [x] One seam, `_run_observed_subprocess`, generalized from the former
      `_run_subprocess_with_watchdog` with the deadline made optional
      rather than a second implementation added.
- [x] All four GPU launch sites (training × inference, watchdog × plain)
      routed through it — pinned by
      `TestSeamReachability::test_all_four_gpu_launches_go_through_the_seam`,
      which counts the call sites in the AST and names what a bypass
      would cost ("silently lose telemetry in B-C2b").
- [x] The only remaining direct `subprocess.run` is CPU-only scoring —
      pinned by `test_only_cpu_scoring_still_calls_subprocess_run`, so
      the seam cannot quietly fall back to it.
- [x] Command, environment, `preexec_fn` host-memory limit, `cwd`,
      `text` and timeout preserved — `TestSemanticsUnchanged`.
- [x] `start_new_session=True` kept **only** on the deadline path, so
      the non-deadline path does not create a process group and the
      watchdog's `killpg` still reaches the tree.
- [x] Watchdog kill, grace and escalation unchanged — `test_watchdog.py`.
- [x] The two modes are pinned apart by test, not by intent.

---

### B-C2a2 — Migrate the plain path to observable Popen

#### 1. Goal

Give the plain path a live child PID, which `subprocess.run` cannot
provide and B-C2b requires.

#### 2. Scope — this commit owns the full consequence

Counts per the §9 audit (48 to migrate of 54 inspected, not the 58/59
this section originally carried).

- [x] plain `subprocess.run` -> `Popen`, keeping `start_new_session=False`
- [x] `check=True`-equivalent `CalledProcessError`
- [x] stdout, stderr, cwd, env, preexec, text and timeout behaviour preserved
- [x] migrate the 48 stub sites across 6 files
- [x] rewrite the 4 `call_args` assertions (class B)
- [x] rewrite the 4 obsolete-implementation-detail tests (class D)
- [x] leave the 6 intentional direct `subprocess.run` sites untouched (class F)
- [x] prove rlimit and signal behaviour equivalent
- [x] prove no unit test can silently start real training or inference

Observation stays disabled; no GPU query.

#### 3. Implementation record — 2026-08-01

**Order followed**: safety net first (invert tripwires, write the
`Popen` parity test), then production, then tests in the audited order.

**The audit's predictions held exactly.** Switching production before
migrating anything produced **45 failures**, distributed
22 / 8 / 4 / 9 / 1 / 1 across the six files — precisely the audited
counts, and the three sites that did *not* fail were exactly the three
the audit flagged as vacuous (`scope:92`, `scope:106`, `rt2b:219`).
The B-C2a1 escape guard fired **135 times** during that run and **zero
real training subprocesses escaped**, in 26 s rather than a multi-minute
hang.

| File | sites | how |
|---|---|---|
| `test_sandbox_executor_rt2b.py` | 9 | retarget + shared `_fake_run` returns the 2-tuple |
| `test_sandbox_executor_rt2d.py` | 4 | same |
| `test_sandbox_rlimit.py` | 9 of 12 | retargeted **by which executor the test calls**, not by line; 3 scoring sites kept |
| `test_sandbox_scope.py` | 3 | retarget + de-vacuumed assertions |
| `test_sandbox_executor.py` | 22 of 25 | retarget + 4 class-B + 3 class-D; 3 scoring sites kept |
| `test_watchdog.py` | 1 | class-D rewrite + docstring |

**Deviations resolved autonomously, all bounded:**

1. **The class-D `stderr=PIPE` tests are rewritten, not deleted.** The
   kwarg is now below the seam, so asserting it would assert nothing.
   They now assert the property they existed to protect — a failed
   child's stderr reaches the caller's message — which survives any
   future launch change.
2. **`scope:92/:106` were the audit's vacuity case and needed more than
   a retarget.** `assert_not_called()` on the seam alone would go
   vacuous again on the next rewiring. They now patch **all three**
   launch primitives *for the duration of the call* and assert on each.
   A first attempt patched them *after* the call and asserted fresh
   mocks were unused — vacuous in exactly the way being fixed, caught
   and replaced before commit.
3. **Name collision damaged the scoring class.** `test_progress_bar_*`
   exists in three classes with an identical `self._run(...)` body, so a
   name-based substitution also hit CPU-only scoring. Detected by the
   suite, reverted; scoring's three sites and their `stdout`/`stderr`
   kwarg assertions are intact and still meaningful, because scoring
   keeps its direct `subprocess.run`.
4. **`test_watchdog.py`'s assertion had to change meaning.**
   `used == {"watchdog": 0, "run": 1}` asserted "the implementation
   underneath is still `subprocess.run`", false by construction now.
   Replaced with the durable property — the seam is entered with no
   `deadline_provider` — and the docstring rewritten, since it had
   instructed the reader that the removed assertion was intentional.
5. **Parity evidence rewritten against `Popen`, not dropped.**
   `check=True` has no `Popen` analogue; its replacement is the
   behavioural assertion that a non-zero exit still raises, plus a test
   that no `check` kwarg is smuggled through.

**Traps handled as audited**: the shared `_ok_result` feeding both
migrated inference and retained scoring was left alone and only the
training-only factory changed; the nine side-effect fakes kept their
bodies and changed only their return; the two raising fakes were
untouched; multi-line `return_value` blocks needed a second pass the
single-line regex missed.

#### 4. Test evidence — 2026-08-01

| Suite | Result |
|---|---|
| `tests/unit/core/` | **969 passed**, 25.89 s |
| `core` + `guardrails` + `evaluate_vram_skill` + `sdsc_submission_scripts` | **1,979 passed**, 1 skipped, 3 xfailed, 55.83 s |
| `ruff check` / `ruff format --check` | clean, 333 files |

- escape-guard firings after migration: **0**
- real training subprocesses escaped: **0**
- GPU: **273 MiB before and after** (baseline), no orphan
- strict pyright: **not run locally** (Node availability unverified) — CI only, recorded rather than claimed

---

### B-C2a (historical) — superseded, text removed 2026-08-01

The original single-commit plan for normalizing GPU subprocess launch.
It was split into **B-C2a1** (route every GPU child through one seam,
zero semantic change — `90dcd24`) and **B-C2a2** (migrate the plain path
from `subprocess.run` to `Popen` — `f2e39a9`), both landed. Splitting it
was the right call: it made the 48-site test migration attributable to
one small diff instead of hiding inside a telemetry change.

The full original text is preserved in git history at `897362e`, the
commit that performed the split. Nothing in it is still binding.


### B-C2b — Bounded in-flight GPU evidence

#### 1. Goal

Attach the GPU observer to the B-C2a seam and capture the four-slot
evidence bundle an attribution decision needs. Without it, the only
snapshot available is taken after the child has exited — by which point
the driver has reclaimed the candidate's memory and every OOM looks
like contention.

#### 2. Scope

The observer, its lifecycle, the four slots, and persistence on failure
records only. No attribution (B-C3), no admission (B-C4), no prompt
change.

Depends on B-C1 (the sampler) and B-C2a (the seam).

#### 2a. The four slots — frozen 2026-08-01

| Slot | When | What it may claim |
|---|---|---|
| `baseline_before_spawn` | before `Popen` | device totals, processes already present, free space, timestamp — **and nothing about the candidate** |
| `observed_peak` | the **whole snapshot** at maximum `own_tree_mib` | candidate-owned vs other |
| `last_while_alive` | last valid snapshot taken while the child was confirmed alive | candidate-owned vs other |
| `post_failure` | after the child exited or the failure was observed | what occupancy remains on the device |

**`baseline_before_spawn` must not pretend to belong to a child that
does not exist yet.** There is no child PID before `Popen`, so no
ownership split is possible, and the slot is typed to make that
impossible to express rather than left to discipline.

**Do not substitute the parent PID for the not-yet-existing child.** The
parent has other descendants — the pre-flight worker, a scoring process,
anything a concurrent phase left behind — and attributing those to the
candidate would inflate exactly the number attribution depends on.

Ownership splitting begins only after `Popen` returns a PID, and is
keyed on **that child's** ancestry.

`observed_peak` is one coherent snapshot, never a fieldwise maximum:
composing an own-peak, an other-peak and a device-free-minimum from
three instants would build a state the machine was never in and then
attribute against it.

#### 2b. It is `observed_peak`, not `peak`

Sampling cannot see between samples. A5's training phase was **8.0
seconds**; A6 reached 147 s only because `formal_portion 0.2` was a
deliberate validation deviation, and production trial rounds are back
at the seconds scale.

Coverage travels with the number, so a reader can judge what it is
worth:

```text
valid_sample_count
failed_sample_count
child_runtime_ms
first_valid_offset_ms
last_valid_offset_ms
sampling_policy
device_identity
```

Cadence is **typed configuration, not a runner constant**:

```text
GpuObservationPolicy
    fast_interval_ms      ~5 Hz  compatibility default
    fast_window_ms        15 s
    steady_interval_ms    ~1 Hz
    join_timeout_ms
```

Compatibility defaults give an 8 s phase roughly 40 samples while a long
phase does not pay 5 Hz of `nvidia-smi`. **Cadence is observation
policy, not admission policy** — it must not be co-located with the
12 / 28 GiB ceilings (§1.4.2: a measured fact, a configured policy and a
task interpretation are three different categories).

Storage stays fixed: four snapshots and the scalars above, regardless of
runtime.

> **`observed_peak` is a sampled lower bound, not a guaranteed
> instantaneous maximum.** B-C3 must not treat it alone as authoritative
> candidate demand; insufficient coverage, too few valid samples or a
> missing slot yields `unknown` attribution, never candidate blame.
> Authoritative demand comes from a PR C promoted measurement (D-B5).

#### 2b-bis. Persistence boundary — success measurements are NOT promoted

```text
success:  observer runs and cleans up; no new attempt-record field
failure:  the bounded evidence bundle is persisted
```

B-C2b supplies evidence **for failure attribution only**. It establishes
no registry, no promotion path and no cross-run applicability for a
successful run's measurement — that is PR C's subject (D-B5), and
building it here would create the second measurement authority D-B5
exists to prevent.

#### 2c. Observer lifecycle

A **parent-side thread**, started after `Popen` returns and the child
PID is known. Not child-side reporting: GPU accounting is generic
runtime infrastructure and must not require task code to cooperate
(§1.4).

Binding requirements:

- stops on **every** exit path — success, failure, timeout, exception;
- never delays child reaping beyond a bounded cleanup deadline;
- **never** makes training or inference fail because telemetry failed;
- never outlives the execution helper;
- reports telemetry failure explicitly rather than as zero usage.

#### 2d. Device identity provenance

`sandbox_executor.py` must not discover a device, assume GPU 0, take the
first `nvidia-smi` row, or aggregate devices. Identity is resolved once
near the orchestration boundary and passed down:

```text
resolved hardware config / HardwareSnapshot
  -> DeviceIdentity        (B-C1 model; adapter, not a second schema)
  -> tuner
  -> execute_training / execute_inference
  -> observed subprocess seam
  -> gpu_accounting.sample(...)
```

`DeviceIdentity` is an **explicit parameter**. Legacy call sites may
pass `None`, which means *telemetry unavailable* — and must **not**
trigger hidden rediscovery. Formal V20 paths will require a resolved
identity.

PR A's `HardwareSnapshot` is the current upstream source; it carries
`device_name` and `cuda_visible_devices` but **no UUID** (FU-A-13), so
the adapter must be explicit about what it cannot supply rather than
inventing an identity.

#### 3. Implementation record — checkpoints 1-3 done 2026-08-01

- [x] **Checkpoint 1** `DeviceBaselineSnapshot` + `sample_device_baseline`
      (`2b6a5dd`). Modelled as its **own type** rather than a
      `GpuAccountingSnapshot` with `own_tree_mib` left empty, because
      "candidate-owned is 0" and "the candidate does not exist yet" are
      different claims and a later attribution depends on telling them
      apart. The model has no `own_tree_mib` / `own_processes` /
      `other_mib` / `root_pid` field at all, and the sampler takes no
      `root_pid`, so substituting the parent PID is unexpressible rather
      than merely discouraged. **45 tests**, 0.11 s.
- [x] **Checkpoint 2** `gpu_observer.py` — `GpuObservationPolicy`,
      `GpuEvidenceBundle`, `GpuPhaseObserver` (`33fa088`). **26 tests**,
      0.25 s.
- [x] **Checkpoint 3** wired into the B-C2a seam, both branches.
- [x] **Checkpoint 4a** device identity by UUID (`a8d7824`) — **FU-A-13
      closed**. Production could not supply a real `DeviceIdentity`
      because the only upstream hardware record had no UUID, which would
      have left telemetry permanently unavailable and B-C3 built on a
      structurally empty evidence source: the exact "component exists,
      production cannot reach it" shape this PR was opened about.
      Fingerprint **versioned, not replaced** (v1 name-keyed, v2
      UUID-keyed); all new fields optional so pre-UUID manifests still
      load, verified by round-tripping a legacy JSON document. One
      adapter is the only translation point, asserted by a test that no
      rival `DeviceIdentity` constructor exists under `core/`. A record
      without a UUID yields `None` — degraded identity is never repaired
      by guessing, because device 0 or a name key would conflate two
      cards of the same model. **16 tests.**
- [x] **Checkpoint 4b** identity threaded and evidence persisted on
      failure. Resolved **once** at the orchestration boundary
      (`tuner:2179`) and passed explicitly; the executor never
      discovers. Attached to training and inference failure results and
      onto the two failure record builders, behind a new optional
      `ExperimentRecord.gpu_evidence` so every existing record still
      validates. Success results deliberately carry nothing.

**Design decision in checkpoint 3 — the observer is an argument, not a
third return value.** B-C2b needs evidence out of the seam, and the
obvious shape is to widen its return tuple. But that tuple is exactly
what the 48 migrated stubs across six files were just reshaped around,
and widening it would re-break every one of them for a reason unrelated
to what they test. The caller owns the observer, passes it in, and reads
`observer.bundle()` afterwards; the seam only drives the lifecycle.

`observer.stop()` is in a `finally`, so it runs on success, on a
non-zero exit and on any exception. The deadline branch stops it on both
the kill path and the natural-exit path.

**A defect the wiring exposed in B-C2a1's own guard.** The test-safety
guard replaced `subprocess.Popen` — a *class* — with a plain function,
so a test that subclasses `Popen` (a legitimate way to make
`communicate` raise) failed with a confusing `TypeError` rather than
running. A guard must not change the shape of what it guards, so it is
now a `Popen` **subclass**. Re-proved afterwards: an entirely unstubbed
`execute_training` raises `RealSubprocessEscape` in 0.80 s with no real
subprocess started.

#### 3a. Remaining implementation plan

- [ ] Attach the observer through the B-C2a seam only.
- [ ] Implement the four slots and the five coverage scalars.
- [ ] Implement the adaptive cadence as configuration.
- [ ] Implement the lifecycle guarantees of §2c.
- [ ] Thread `DeviceIdentity` per §2d; `None` means unavailable.
- [ ] Persist the bundle on failure/error records only.

#### 4. Validation plan

**Unit**
- [ ] observer stops cleanly on success, on child error, on timeout, and
      when the observer itself raises
- [ ] a child that fails does not fail *because* telemetry failed
- [ ] an 8-second phase yields multiple valid samples under the cadence
- [ ] `observed_peak` is one snapshot, not a fieldwise max — asserted by
      feeding samples whose maxima fall in different instants
- [ ] coverage scalars are recorded and consistent
- [ ] `DeviceIdentity=None` yields `telemetry_available=False` with **no**
      rediscovery attempt
- [ ] success records do **not** gain the bundle; failure records do
- [ ] a record without the field still validates

**Genericity (§1.4)**
- [ ] the seam and observer contain no task vocabulary and no fixed
      hardware ceiling
- [ ] the cadence is configurable, not a constant

**Real-training Gate**: none in this commit.

#### 5. Acceptance criteria

- [ ] With a scripted 8-second child, `valid_sample_count >= 20` and
      `observed_peak` is populated.
- [ ] Feeding a sample sequence whose `own_tree_mib` peak and
      `other_mib` peak occur at different instants, `observed_peak`
      equals the whole snapshot at the `own_tree_mib` maximum.
- [ ] Injecting an observer that raises leaves the child's own status
      dictionary unchanged.
- [ ] Success-path artifacts are byte-identical to B-C2a's.

#### 6. Failure and edge cases

| Case | Handling | Rationale |
|---|---|---|
| telemetry unavailable throughout | four slots recorded as unavailable | a gap is a gap; B-C3 turns it into `unknown` |
| child shorter than one sample interval | zero valid samples, recorded as such | honest coverage beats an invented number |
| observer raises | swallowed, recorded, child unaffected | telemetry must never be able to fail the science |
| `DeviceIdentity is None` | unavailable, no rediscovery | hidden rediscovery is how GPU 0 gets assumed |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/core/ tests/unit/guardrails/ -q
.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/ -q
```
- [ ] counts and wall time recorded after the run

#### 8. Commit boundary

Observation and evidence only. No attribution, no admission, no prompt.

---

### B-C3 — Attribution, and gating the agent-facing shrink signal

#### 0. Frozen decisions — operator, 2026-08-01

**Split into two commits** so the attribution arithmetic and the agent's
behaviour cannot mask one another:

```text
B-C3a  typed generic attribution + CUDA allocation adapter + fixtures
B-C3b  persist it, and gate the task-layer shrink wording on its authority
```

**Vocabulary, frozen:**

| Outcome | `may_recommend_resource_reduction` |
|---|---|
| `candidate_gpu_capacity` | **true — the only one** |
| `gpu_contention` | false |
| `host_memory_pressure` | false |
| `external_termination` | false |
| `unknown` | false |

The generic layer must never name `model size`, `batch_size`,
`segmentation_size`, denoising or TIDMAD. It returns typed authority;
the task layer decides what that authority *says*.

**Evidence-quality gate — every one is required** before a capacity or
contention verdict is permitted:

```text
 1. coverage_is_thin is false
 2. baseline_before_spawn available
 3. observed_peak available
 4. last_while_alive available
 5. all snapshots share one GPU UUID
 6. last sample is fresh per the policy
 7. telemetry available
 8. credible CUDA-OOM evidence exists
```

Any failure → `unknown`. `coverage_is_thin` is a **mandatory** trigger
but **not the only one**.

**Extended during B-C3a implementation (restart audit, 2026-08-01).**
The eight above are necessary but were not sufficient — the audit found
six paths that reached a verdict on evidence that could not support one,
every one of them biased toward the single outcome carrying authority.
The gate additionally requires:

```text
 9. the bundle validates as GpuEvidenceBundle (a mapping is
    re-validated, never read with getattr defaults)
10. observer_error is None
11. observer_join_timed_out is false
12. an observation policy was recorded
13. child_runtime_ms and last_valid_offset_ms were recorded
14. the bundle's own device agrees with its snapshots
15. device_used_mib <= device_total_mib
```

Rationale for the three least obvious. **(13)** the observer leaves
`child_runtime_ms` unset whenever `stop()` never ran — which is
precisely when a phase died abnormally, so treating missing timing as
"skip the freshness check" convicted on the stalest bundles the system
can produce. **(9)** `coverage_is_thin` is a computed property and is
absent from `model_dump()`, so attribute access against a stored record
would have refused every bundle forever while looking like healthy
caution. **(15)** a driver transient reporting `used > total` yields
negative free memory, which manufactures a candidate verdict out of
nothing.

**`observed_peak` alone never proves anything.** It is a sampled lower
bound: a small peak is not evidence of contention, and a large one is
not evidence of candidate capacity.

**Counterfactual, not a threshold.** No `other_mib > X`, no fixed
multiplier. A framework-specific adapter extracts
`attempted_allocation_mib` best-effort; the generic function consumes
that optional number and never parses framework text itself. On the last
fresh snapshot:

```text
current_free_mib      = device_total_mib - device_used_mib
free_without_other_mib = current_free_mib + other_mib

attempted is missing            -> unknown
attempted <= current_free       -> unknown   (fragmentation, skew, or
                                              something unobserved —
                                              do not guess)
current_free < attempted
             <= free_without_other -> gpu_contention
attempted > free_without_other  -> candidate_gpu_capacity
```

**Superseded 2026-08-01 (operator) — interval form.** The rule above
silently charged *unattributed* device memory to the candidate. The
driver reports how much of the device is in use; the per-process query
reports who is using it; the difference (`unattributed_mib` — driver
context, a graphics client, a process owned by another user) belongs to
nobody in particular. Crediting it to the candidate manufactures the
V19 verdict in a subtler form; crediting it to the peers manufactures
the opposite. It is therefore carried as an **uncertainty band**:

```text
current_free_mib
    = device_total_mib - device_used_mib
free_without_known_other_mib
    = current_free_mib + other_mib
free_without_all_possible_other_mib
    = current_free_mib + other_mib + unattributed_mib

attempted is missing                          -> unknown
attempted <= current_free                     -> unknown
current_free < attempted
             <= free_without_known_other      -> gpu_contention
free_without_known_other < attempted
             <= free_without_all_possible_other -> unknown
attempted > free_without_all_possible_other   -> candidate_gpu_capacity
```

The third interval is unknowable by construction: the verdict there
depends on who owns the unattributed memory, and that is not measured.
**Only the final case may blame the candidate**, and it holds even under
the reading most favourable to the candidate — that every unattributed
byte belonged to somebody else.

Corollary: `gpu_contention` does not need `unattributed_mib` (fitting
below the known bound implies fitting below the wider one), but
`candidate_gpu_capacity` does. When the figure is absent, a contention
verdict is still permitted and a candidate verdict is not.

Every input figure and the reasoning are preserved on the evidence, so
the verdict is auditable rather than asserted. Refusals record the
telemetry-health figures too (`valid_sample_count`, `failed_sample_count`,
`observer_error`, `coverage_is_thin`, timing) — a refusal that records
nothing cannot later be distinguished from a refusal that was wrong.

**Host and signal.** `returncode == -9` alone proves nothing, and the
existing `oom_host_ram` status is *evidence*, not an inherited verdict —
it may itself have been derived from `-9`. Corroborated host RSS /
cgroup / kernel-OOM evidence → `host_memory_pressure`; corroborated
watchdog, operator, quota or external signal → `external_termination`;
otherwise `unknown`. Neither host outcome carries downsizing authority,
and B-C3 builds no new host telemetry — it consumes what exists and
stays `unknown` when that is not enough.


#### 1. Goal

Classify a memory failure, and stop a contention-caused failure from
reaching the agent as a reason to shrink the model. This is the commit
that fixes the V19 misdiagnosis class.

It follows B-C2 because it consumes the captured context, and precedes
B-C4 because attribution must be right before refusals are issued.

#### 2. Scope

- **New** typed vocabulary, modelled on `PreflightOutcome` +
  `NO_DOWNSIZING_AUTHORITY` (`isolated_probe.py:56-87`).
- `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` —
  the two hardcoded shrink strings (`:3293-3298`, `:3362-3368`) become
  conditional on the attribution.
- `agent/prompts.py` — a suppression note for contention-attributed
  failures, following `inconclusive_note` (`:1018-1040`).
- Fix the `"oom_host_ram"` no-consumer defect (§3.3) **only** to the
  extent of classifying it; the deeper silent-crash re-routing at
  `:3325-3343` is recorded as a follow-up, not fixed here.
- Unchanged: no automatic resizing, no retry policy change.

Depends on B-C1, B-C2.

> **Scope split, per §0.** This section predates the a/b split and lists
> B-C3 as one commit. The vocabulary, gate, counterfactual and adapter
> are **B-C3a** (landed); the two tuner shrink strings, the prompt
> suppression note and record persistence are **B-C3b**.

#### 2a. The attribution rule is counterfactual, not a threshold

**Corrected 2026-08-01.** An isolated `other_mib > X` threshold is the
same mistake as a fixed `1.9×` multiplier in a different coordinate: it
asserts a constant where the code should ask a question. The question is
counterfactual:

```text
would this candidate have fitted had the other occupancy not been there?

  candidate's credible demand + safety margin
     fits within  (device_total - 0)
     but does NOT fit within  (device_total - other_occupancy)
  -> gpu_contention (frozen name; drafted as "contention-attributable")
```

> **Superseded by §0 — reconciled during B-C3a, 2026-08-01.** The list
> below is pre-freeze drafting and is retained for history. It made
> `observed_peak` an *arithmetic input* and added a "safety margin",
> neither of which survives: §0's counterfactual consumes
> `attempted_allocation_mib` against the free/other/unattributed
> figures, adds no margin and no multiplier, and treats `observed_peak`
> as an **evidence-presence and coverage** requirement only — consistent
> with §0's own "`observed_peak` alone never proves anything", since a
> sampled lower bound cannot be a term in a decision it cannot support.
> The phase identifier is likewise not a decision input; the generic
> layer does not know what a phase means (§8.4). Where this list and §0
> differ, **§0 governs.**

Deciding it requires all five of:

- the candidate's own `observed_peak` (a **lower bound** — B-C2b §2b),
  or an authoritative demand promoted by PR C (D-B5)
- other occupancy at the failure instant
- device total and free
- the last valid sample **before** the failure (§2a — the post-mortem
  cannot supply this)
- the phase that was running

**If any of these is missing, if sampling coverage was insufficient, or
if the counterfactual cannot be established either way, the outcome is
`unknown` — never `candidate_gpu_capacity`.** A single `observed_peak`
does not on its own convict a candidate: it is a sampled lower bound,
so "the observed peak was not large" is not evidence of contention
either. The asymmetry is deliberate: a wrong
candidate verdict tells an agent to shrink a model that was never too
large, which is exactly the V19 failure. A wrong `unknown` costs one
piece of feedback.

The rule has exactly three positive forms:

```text
demand fits the device total, but not (total - other)
  -> gpu_contention

demand does not fit the device total even with other removed
  -> candidate_gpu_capacity

neither statement can be established
  -> unknown
```

**Free memory alone proves nothing.** The V19 pair is the fixture, but
"9.20 GiB free → candidate" is not a valid inference on its own: a free
figure says nothing about the candidate's demand. The fixture must carry
all five inputs, and the candidate verdict requires demonstrating
`demand > total` — not merely observing that a lot was free.

#### 2b. The attribution enum — frozen

**Corrected 2026-08-01.** The first draft drifted across `host_kill`,
`host_quota_intervention`, `infrastructure_attributable` and "host OOM",
which are a mix of causes and consequences. One exhaustive, mutually
exclusive vocabulary:

| Outcome | Meaning | `may_recommend_resource_reduction` |
|---|---|---|
| `candidate_gpu_capacity` | demand exceeds the device even with the card to itself | **yes — the only one** |
| `gpu_contention` | would have fitted but for other occupancy | no |
| `host_memory_pressure` | host RAM exhausted, with cgroup/RSS evidence | no |
| `external_termination` | quota watchdog, operator kill, or other outside signal | no |
| `unknown` | the evidence does not settle it | no |

> **Naming reconciled during B-C3a implementation.** This section was
> drafted before §0 was frozen and said `contention` and
> `may_recommend_downsizing`. §0 is the operator-frozen vocabulary and
> wins: the member is `gpu_contention` and the authority flag is
> `may_recommend_resource_reduction`. The two spellings are the same
> thing; the frozen one is what the code declares. Occurrences of the
> draft spelling elsewhere in this section are historical drafting, not
> a second vocabulary.

Signal routing, stated so `-9` cannot silently become a verdict:

```text
returncode == -9, no corroboration          -> external_termination or unknown
returncode == -9 + host RSS/cgroup evidence -> host_memory_pressure
quota watchdog / operator kill              -> external_termination
telemetry insufficient                      -> unknown
```

`host_kill` is deliberately **not** a member: it names an event, not a
cause, and would collapse `host_memory_pressure` and
`external_termination` — the one case that is about the candidate's
host footprint and the one that is about the environment.

#### 3. Implementation plan

**B-C3a — landed.** New module
`core/runtime_control/failure_attribution.py` (451 lines). It imports
nothing from the task layer (only `re`, `collections.abc`, `typing`,
`pydantic`, and the sibling generic `gpu_observer`) and names no task
concept: the file contains no occurrence of `batch_size`,
`segmentation_size`, `model size`, `denois*` or `TIDMAD` **anywhere,
including docstrings and comments** — asserted by two source-level
tests, one over the raw text and one over every identifier position
(`ast.Name`, `Attribute.attr`, `keyword.arg`, `arg`, `alias`,
`FunctionDef`/`ClassDef`).

- [x] Define the outcome vocabulary and its authority set:
      `candidate_gpu_capacity` / `gpu_contention` /
      `host_memory_pressure` / `external_termination` / `unknown`, with a
      `may_recommend_resource_reduction` flag (only the first is true).
      → `FailureAttribution` `Literal` (`:48`) and
      `_MAY_RECOMMEND_REDUCTION` (`:57`).
      **Authority is enforced, not documented**: `AttributionResult`
      is a frozen model whose `model_post_init` rejects any instance
      whose flag disagrees with the frozen set, so a member added later
      cannot quietly acquire downsizing authority — it fails
      construction, in both directions.
      `may_recommend_resource_reduction(str)` (`:104`) serves callers
      holding only the string and denies authority to an unrecognised
      one rather than raising, which is the safe direction for a caller
      reading a legacy record.
- [x] Implement the counterfactual, in the **interval form** frozen on
      2026-08-01. **No `other_mib > X` constant, no multiplier, no
      safety factor.** → `attribute_gpu_failure` (`:254`).
      The framework-specific parse is confined to
      `extract_attempted_allocation_mib` (`:113`, `Tried to allocate N
      {KiB,MiB,GiB,TiB}`); the decision function parses nothing —
      asserted structurally, by checking that `re`, `_TRIED_TO_ALLOCATE`
      and `_UNIT_TO_MIB` appear nowhere in `attribute_gpu_failure`'s AST
      and that the pattern is referenced by the adapter alone. Missing
      or unsupported size (byte-valued, thousands-separated) →
      `unknown`, never zero.
- [x] **Constant guard rewritten after the restart audit.** The first
      version denylisted seven floats that could never have appeared and
      ignored integers entirely, so it could not have seen a `* 2`
      safety factor or an `other_mib > 12000` ceiling — a test that was
      guaranteed to pass. It is now an **allowlist** over every numeric
      constant in the module (ints `{1, 2, 3, 1024}`, floats
      `{1.0, 1024.0}`); any new number must be justified there or the
      guard fails. Verified by mutation: injecting `int(other * 0.85)`
      fails it.
- [x] **`_DEFAULT_FRESHNESS_MS` removed.** It was a hardcoded policy
      constant, and worse, it was *more permissive* (5000 ms) than the
      derived bound (3000 ms), so the degraded path was the looser one.
      The bound is now `_FRESHNESS_INTERVALS × steady_interval_ms`
      (`:64`) from the run's own recorded policy, and an unrecorded
      policy yields `unknown` instead of a fallback. A parametrised test
      pins the multiplier itself at two different cadences, so a silent
      change of the bound cannot leave a single large-gap test passing.
- [x] Gate the evidence before any verdict → `_gate_evidence_quality`
      (`:202`). All fifteen §0 conditions are required and each returns
      its own reason string, so a refusal says which condition failed
      rather than only that one did. `coverage_is_thin` is mandatory but
      not sufficient: a thick bundle whose snapshots disagree on GPU
      UUID, whose observer raised or would not stop, or whose last valid
      sample predates the child's end by more than the freshness bound,
      is also refused.
- [x] **Type the evidence instead of duck-typing it** →
      `_normalize_bundle` (`:162`). The first version took `Any` and
      read fields with `getattr(..., default)`. The audit showed the
      defaults split two ways: some fail closed, but
      `child_runtime_ms`/`last_valid_offset_ms` defaulting to `None`
      **skipped the freshness check entirely**, and a renamed
      `steady_interval_ms` would have silently widened the bound with no
      test failing. The parameter is now normalised to
      `GpuEvidenceBundle` — a mapping is re-validated (which recomputes
      the `coverage_is_thin` property that `model_dump()` omits), a
      foreign object is refused by type, and a malformed mapping is
      refused rather than coerced.
- [x] `attempted <= current_free` → `unknown`, not a verdict.
      The allocation should have fitted; the cause is unobserved
      (fragmentation, sampling skew). This is the branch where a
      threshold-based implementation would have guessed.
- [x] **Carry unattributed memory as an interval, not a rounding
      error.** `free_without_all_possible_other_mib` adds
      `unattributed_mib`, and the candidate may only be blamed above
      that bound. Between the two bounds the verdict depends on who owns
      memory nobody measured, so the outcome is `unknown`. Verified by
      mutation: deleting the `+ unattributed` term — i.e. silently
      charging that memory to the candidate, the V19 mistake in subtler
      form — fails four tests.
- [x] Route signals correctly. `returncode == -9` **alone proves
      nothing**: kernel host-OOM kill, an external quota watchdog, an
      operator kill and other system terminations are indistinguishable
      by signal. Require corroborating evidence — host-RSS near the
      limit for kernel OOM, the captured GPU/host context otherwise —
      and where none exists return `unknown` or
      `external_termination`, **never** candidate host OOM.
      → `attribute_process_termination` (`:270`). The return code is
      recorded on the evidence but is never itself a discriminator: the
      function branches only on the two corroboration flags. A `-9` with
      neither flag is `unknown`, and — deliberately — **so is a `-9`
      with both**: a kill explained two ways is not explained, and
      picking the more likely one is the guessing this commit exists to
      remove.
- [x] Consume `oom_host_ram` (which has no consumer today) but only as
      *evidence*, subject to the same corroboration rule — not as a
      verdict inherited from the executor. → the signature takes
      `host_memory_evidence: bool`, so the executor's status can only
      enter as one corroborating input. It cannot be promoted to a
      verdict, because the status may itself have been derived from the
      `-9` it is being used to explain.
**B-C3b — landed.**

- [x] **Attribute at the executor failure handler, not from the record**
      → `_with_failure_attribution` (`core/sandbox_executor.py`), called
      from both `execute_training` and `execute_inference`. This is the
      only point where the child's full stderr, the live evidence bundle
      and the return code coexist. The restart audit established that the
      attempted-allocation size is **not** recoverable downstream: the
      tuner cuts the message to `[-500:]`, and since
      `_format_subprocess_error` appends stdout *after* stderr, that
      window normally holds trainer progress output rather than the
      allocation line. Attribution rebuilt from a record would be
      attribution built on the wrong text. Never raises — telemetry must
      not fail the phase it watched.
- [x] **Arbitrate between the two classifiers.** A credible device-side
      OOM is a statement about the device; anything else is a statement
      about the process. Previously nothing chose, and the caller
      decided by which function it happened to call.
- [x] **Host evidence without laundering the signal** →
      `_has_host_memory_evidence`, deliberately **not** `_is_oom_failure`
      (which also returns True for `-9`). Only the `MemoryError`
      signature counts: RLIMIT_AS caught the allocation and Python
      raised. A guard test asserts `_is_oom_failure` appears nowhere in
      the attribution helper.
- [x] Make the two shrink strings conditional → `_oom_memory_wording`
      (tuner), one helper serving both the training and the inference
      site so they cannot drift. Extracted **because a mutation escaped**:
      reverting the inline gate left all 32 tests green, since the prompt
      tests build records by hand and never exercise the tuner's own
      record-building path.
- [x] Add the prompt suppression note → `unattributed_oom_note`
      (`agent/prompts.py`), following `inconclusive_note`, spliced into
      the rendered prompt. It fires for any `*_oom` record whose
      attribution lacks reduction authority. It **says so explicitly**
      rather than staying silent: the agent can still see the OOM in
      memory, and silence lets it infer the instruction the measurement
      refused to support.
- [x] Persist the attribution on the record → optional
      `failure_attribution` on `ExperimentRecord`, attached beside
      `gpu_evidence` at both sites.

#### 4. Validation plan

**Unit** — `tests/unit/core/test_failure_attribution.py`, **91 tests,
all passing** (0.13 s). The first version had 49; the restart audit
found four that could pass for the wrong reason, and they were rewritten
rather than extended:

| Weak test | Why it proved nothing | Replacement |
|---|---|---|
| `test_no_fixed_multiplier_or_ceiling_constant` | denylisted 7 floats that could never appear; blind to ints | allowlist over **every** numeric constant |
| `test_every_figure_is_preserved_for_audit` | asserted key presence only — passed if every value were `None` | asserts each figure's **value** |
| `test_the_parsing_lives_only_in_the_adapter` | forbade one exact literal in one function | structural: `re` / pattern / unit-table absent from the decision AST, pattern referenced by the adapter alone |
| two gate tests | asserted the outcome without the reason; `unknown` is the fallback, so any unrelated bug passes them | every gate test now asserts its own reason string |

Six tautological `may_recommend_resource_reduction is False` assertions
were also dropped: the model validator makes any other value
unconstructible, so they restated the type system.

**Negative proof (mutation).** Each guard was verified to fail when the
behaviour it protects is removed — a guard never observed failing is not
evidence:

| Mutation | Result |
|---|---|
| `_FRESHNESS_INTERVALS` 3 → 5 | 4 failed |
| inject `int(other * 0.85)` safety factor | 7 failed |
| delete the `used > total` guard | 1 failed |
| charge unattributed memory to the candidate | 4 failed |
| restore the fail-open freshness skip | 4 failed |
| task vocabulary in a docstring | 1 failed |


- [x] each outcome maps to the correct
      `may_recommend_resource_reduction`, and every disagreeing
      combination is rejected at construction (parametrised over all
      five members in both directions)
- [x] a CUDA OOM with `other_mib` ≈ 0 → `candidate_gpu_capacity`
- [x] a CUDA OOM with large `other_mib` → `gpu_contention`
- [x] `telemetry_available=False` on any one of the three snapshots →
      `unknown`
- [x] SIGKILL with corroborating host evidence → `host_memory_pressure`
- [x] SIGTERM/SIGKILL from outside → `external_termination`, never
      candidate
- [x] the vocabulary is exhaustive and closed — a member outside the
      `Literal` fails Pydantic validation rather than defaulting
- [x] the generic layer names no task concept, and declares none of the
      forbidden float constants (source-level assertions over the
      module's AST)

**Prompt-level** — `tests/unit/agent/tune_ml_hyperparam_agent/test_attribution_gating.py`,
**49 tests**; executor wiring in `tests/unit/core/test_failure_attribution_wiring.py`,
**15 tests**. Both passing.
- [x] the rendered planner prompt contains the shrink instruction for a
      candidate-attributed OOM and does **not** for a
      contention-attributed one — asserted on the rendered string, not
      on the record
- [x] all four non-authoritative outcomes get the suppression note; a
      candidate-attributed one does not
- [x] a legacy record with no attribution behaves as `unknown`
- [x] a mixed history notes only the unattributed records — the note is
      per-record, not per-run
- [x] **production reachability**: the shrink wording exists *only*
      inside `_oom_memory_wording`, and both failure sites call it with
      an explicit phase. Added after a mutation proved a call-site bypass
      was otherwise undetectable

> **A vacuous assertion caught during B-C3b.** The first version of the
> "shrink text absent" tests compared the full production literals,
> which contain an em-dash. `get_planner_user_prompt` renders history
> through `json.dumps(..., indent=2)` with the default
> `ensure_ascii=True`, so the em-dash is escaped to `\u2014` and the
> literal could **never** match — the absence assertions would have
> passed even if production emitted the shrink text. They now compare
> ASCII-only fragments, and a guard test pins those fragments to the
> real tuner source (rejoining implicitly concatenated literals, since
> the formatter wraps them) so they cannot drift back into vacuity.

**Negative** — covered:
- [x] OOM flagged but no bundle → `unknown`
- [x] bundle present but `attempted_allocation_mib` missing → `unknown`
- [x] snapshots describing two different GPU UUIDs → `unknown`
- [x] the bundle's own device disagrees with its snapshots → `unknown`
- [x] last valid sample older than the freshness bound → `unknown`
- [x] timing unrecorded, so freshness is unestablished → `unknown`
- [x] no observation policy recorded → `unknown` (not a default bound)
- [x] observer raised, or did not stop within its join timeout →
      `unknown`
- [x] `device_used_mib > device_total_mib` → `unknown`, never negative
      free memory
- [x] `unattributed_mib` absent → contention still permitted, candidate
      refused
- [x] a non-CUDA failure text (host `MemoryError`, bare non-zero exit) →
      `unknown`; neither says anything about the device
- [x] both host and external evidence present → `unknown`
- [x] a foreign object or malformed mapping as the bundle → `unknown`

**Real-training Gate**: none in this commit.

#### 5. Acceptance criteria

Reworded 2026-08-01: the original criteria were keyed on **free memory
alone**, which §2a itself says proves nothing — a free figure carries no
information about what the candidate demanded. Each now names the
attempted allocation that makes the verdict decidable.

- [ ] For a record attributed to contention, the string
      `"reduce model size"` does not appear anywhere in the rendered
      planner prompt. *(B-C3b)*
- [x] **V19 reconstructed contention fixture** — 125.94 MiB free of
      31.34 GiB with a peer holding 9,222 MiB, and an attempted 2,000
      MiB, classifies as `gpu_contention` with no reduction authority.
- [x] **V19 reconstructed capacity fixture** — 9.20 GiB free, nothing
      else on the card, attempted 11.31 GiB **taken through
      `extract_attempted_allocation_mib`** rather than hardcoded, so an
      adapter/decision unit mismatch cannot hide, classifies as
      `candidate_gpu_capacity`.
- [x] The same 9.20 GiB free figure with a 100 MiB attempted allocation
      classifies as `unknown` — free memory alone does not decide it.
- [x] No automatic parameter change is introduced — provable by diff:
      B-C3b changes only *wording* and adds one optional record field.
      No config value is written, no retry policy is altered, and no
      control flow is added. That is B-C4's business.

> **Honesty note on the fixtures — restart audit, 2026-08-01.** These
> are **reconstructions, not replays.** No captured CUDA OOM stderr
> exists anywhere in this repository: every `Tried to allocate` string
> in the tree is a test fixture, and the two real OOM events the project
> recorded (V19's 125.94 MiB free, and the 9.20 GiB case) preserved
> free-memory context but **never an attempted-allocation size**. The
> attempted figures above are therefore an explicit fixture assumption.
> These tests prove the frozen rule produces the right verdict on
> complete evidence. They do **not** prove the parser has been validated
> against historical production stderr — the supported message form
> (`Tried to allocate 11.31 GiB`) is attested by test evidence only.
> First real validation of the parser is B-G2's business.

#### 6. Failure and edge cases

| Case | Handling |
|---|---|
| snapshot unavailable | `unknown` → no shrink signal. Silence is safer than a wrong instruction |
| both candidate-large and peer-large | `unknown`, with both figures recorded; do not guess |
| host quota SIGTERM | `external_termination`; infrastructure failure, never candidate evidence |
| legacy record with no attribution | treated as `unknown` |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/ tests/unit/agent/ -q
.venv/bin/python -m pytest tests/unit/core/ -q
```

**B-C3a recorded results (2026-08-01):**

| Command | Result |
|---|---|
| `pytest tests/unit/core/test_failure_attribution.py -q` | **91 passed**, 0.13 s |
| `pytest tests/unit/core/ tests/unit/guardrails/ tests/unit/agent/evaluate_vram_skill/ -q` | **1839 passed, 1 skipped, 3 xfailed**, 49.4 s |
| `ruff check` (both files) | clean |
| `ruff format --check` (both files) | clean |
| strict pyright | **not run locally** — this box has Node v10.19.0 and the vendored pyright bundle crashes on it. CI-only; not claimed as locally validated. |

**B-C3b recorded results (2026-08-01):**

| Command | Result |
|---|---|
| `pytest tests/unit/agent/tune_ml_hyperparam_agent/test_attribution_gating.py -q` | **49 passed**, 1.0 s |
| `pytest tests/unit/core/test_failure_attribution_wiring.py -q` | **15 passed**, 0.10 s |
| `pytest tests/unit/core/ tests/unit/agent/ tests/unit/guardrails/ -q` | **4701 passed, 1 skipped, 3 xfailed**, 247 s |
| `ruff check .` / `ruff format --check .` | clean |
| strict pyright | **not run locally** (Node v10.19.0 crashes the vendored bundle) — CI-only |

**First CI run on the branch — FAILED, then fixed (PR #153, head `3c8d106`).**
Zero test failures; four strict-pyright errors, in a check that had never
executed against any of this branch's code because CI runs only on
`push: [master]` and `pull_request: [master]`. Both causes were real, and
neither was visible to any local check:

| Error | Cause | Fix |
|---|---|---|
| `gpu_observer.py:166,199,226` — `DeviceIdentity \| None` where `DeviceIdentity` is required | **B-C2b, not B-C3.** The guards test `self.enabled`, a *property*; pyright cannot narrow an Optional through one. Runtime-correct, type-unproven | narrow on the attribute into a local, at all three sites |
| `ml_hyperparameter_tune_agent.py:2083` — "Code is too complex to analyze" | **B-C3b's.** The two `if … is not None:` blocks added to `run()` pushed it past pyright's complexity ceiling | fold both failure sites' evidence attachment into `_attach_runtime_evidence`, removing four branches from `run()` |

The second is worth stating plainly: **a method too complex for the type
checker to analyse is a method nobody is type-checking.** Strict mode
does not degrade gracefully there — it gives up on the whole function,
so every annotation inside `run()` was going unverified.

**Second CI run — the observer errors cleared, the complexity one did
not.** Removing four branches was not enough, and measuring the method
across the branch explains why:

| Ref | `run()` branch nodes | CI |
|---|---|---|
| `origin/master` | 258 | green |
| `accfeb9` (B-C2b) | 261 | — |
| `a32653f` (B-C3b) | 263 | — |
| first fix attempt | 259 | **fail** |
| after extraction | **253** | — |

**Master sits exactly on pyright's ceiling.** It passes at 258 and fails
at 259 — one `if`. So this is not PR B's complexity; it is a 2,487-line
method with zero headroom, and PR B is merely the commit that arrived
first. Fixed by extracting `_build_training_failure_record` and
`_is_cuda_oom` from the blocks B-C3b already restructured — behaviour
identical, 253 branch nodes, five below the last known-good figure.

**Third CI run — GREEN.** Head `5ba4a40`, run `30724438915`,
`Lint + Type + Unit Tests` **pass** in 7m15s, strict pyright included.
This is the first time any of PR B's code has been type-checked at all,
and it is the completion condition for B-C3.

**This will recur.** B-C4 adds a refusal path to the tuner and will hit
the same wall. Filed as **FU-B-12**; the real fix is decomposing
`run()`, which is far outside PR B's scope and must not be smuggled into
it.

**Negative proof (mutation), B-C3b:**

| Mutation | Result |
|---|---|
| revert the authority gate inside `_oom_memory_wording` | 11 failed |
| bypass the helper, inlining the shrink literal at a call site | 3 failed |
| treat a missing attribution as authoritative | 1 failed |
| drop the suppression note from the rendered prompt | 7 failed |

The second and third are the ones that matter: **both escaped the first
version of the suite.** Bypassing the gate was invisible until a
reachability test was added, and the wording gate itself was untested
because the prompt tests build records by hand. A component that is
built, tested, and never actually called is the failure this codebase
keeps repeating; here it was caught by mutation rather than in
production.

- [x] counts and wall time recorded after the run

#### 8. Commit boundary

Reviewable as "classify, and stop a wrong signal". Contains no headroom
check and no launcher change.

---

### B-C4a0 — Extract the tuner control boundary (prerequisite)

**Operator decision, 2026-08-01.** FU-B-12 is promoted from follow-up to
a **required checkpoint before B-C4 may begin.** Audited 2026-08-02;
design below is the audit's conclusion.

#### 1. Why

Measured, not asserted:

```text
origin/master           258 branch nodes in run()   pyright passes
first PR B integration  259 branch nodes            pyright fails
```

`run()` has no safe complexity headroom. Past the ceiling pyright does
not degrade — it abandons the whole function, so every annotation inside
the tuner's main method goes unverified. B-C4 adds a refusal path to
exactly this method and would tip it over again.

#### 2. What the audit found

`run()` spans **:2155-4626**. Three nested levels carry state:

| Line | Loop | Carried across iterations |
|---|---|---|
| 2560 | `while` (rounds) | `completed_rounds`, `consecutive_fails`, `total_attempts`, `_gate_aborted`, `_scope_violation_reason`, `_evidence_channel_failure`, `physical_rejections_buffer` |
| 2605 | `for` (attempts) | `round_index`, `is_formal_round`, `round_succeeded`, `resolved_action` |
| 2613 | `try` (attempt body) | `failure_stage`, `exp_id`, `model_type`, `record_params`, `hypothesis` |

##### 2.1 Three hazards that make this a design problem, not a move

**(a) The post-loop `del` block is coupled to variable scope.**
`:4378-4391` runs seven `del`s under `suppress(NameError)` then
`gc.collect()`. If an extraction moves `train_results`, `score_results`,
`score_table`, `file_vector`, `final_scalar`, `reflect_results` or
`memory_history` into a helper's frame, each `del` silently becomes a
no-op and the object stays alive. That is **visible as RSS growth across
rounds and invisible to every test.** No surface binding one of those
seven names may be moved without moving its release.

**(b) `resolved_action` is written five levels deeper than it is read.**
Declared per round at `:2571`, written only at `:3622`/`:3642` inside
scoring, read after the attempt loop at `:4361`/`:4365`. It is therefore
"last attempt that reached scoring wins", and it is **never reset per
attempt**. B-C4 short-circuits attempts *before* scoring, which makes a
stale gate action from an earlier attempt in the same round more likely
to be the value read. **B-C4 must state explicitly what happens to it.**

**(c) `skipped_time_risk` already has three producers with different
meanings** — `:1762` guardrail, `:2026` in-subprocess rejection (consumes
an attempt), `:3317` time gate — and is consumed as a set with
`skipped_oom_risk` at `:1226`, `:1327`, `:1335`, `:1347`, `:1351` to
compute time factors. **Admission must not add a fourth producer**;
it reuses the existing skip vocabulary or declares a new member with its
consumers identified.

##### 2.2 Binding contracts any extraction must not break

1. **Mock interception.** Ten test files drive `run()` end-to-end across
   ~94 invocations, all patching the same names: `LLMBridge`,
   `TidmadSandbox`, `_run_skill`, `load_reference_scores`, plus
   `run_production_preflight`, `load_anchor_map`, `get_or_create`,
   `get_gates_for_position`, `build_sample_set`. A helper must call these
   as **module globals at call time** — never captured into a local, a
   default argument or a closure — or `unittest.mock.patch` stops
   intercepting and the tests silently exercise something else.
2. **`run_production_preflight` kwarg names are a hard contract**, pinned
   by the autouse `route_preflight_to_run_skill_stub`
   (`conftest.py:43-49`).
3. **Every `save_record` stays paired with
   `ExperimentRecord.model_validate` on the same dict** — all 9 sites do
   this today. A single unvalidated write makes the whole iteration
   unresumable (`resume.py:297-302`).
4. **`is_trial` and the trial-provenance block stay *conditionally*
   written** (`:4170-4183`). Absence means formal, both to `resume.py`
   and to `test_ordering_formal_branch.py:149-155`. Writing them
   unconditionally would be resume-compatible and still break that test —
   and writing `eval_strategy=None` on a *trial* record silently drops
   that candidate from the chain incumbent (`resume.py:663-670`).
5. **`logical_round` stays conditionally written** — unconditional writes
   flip `round_provenance` from `legacy_unknown` to `persisted`.
6. **`all_records` is `sandbox.get_summary()` verbatim** (`:4409`).
   There is no assembly seam, so any record-shape change propagates
   straight into `run_output_*.json` and into resume's incumbent
   reconstruction.
7. **`_oom_memory_wording`'s three shrink literals must stay inside that
   one function, and it must keep exactly two `phase=` call sites** —
   pinned by the B-C3b reachability tests
   (`test_attribution_gating.py:204-219`), which assert **exact set
   equality**. Extracting a failure surface that carries one of those
   literals, or that duplicates a call site, fails them.
8. **Convention**: match the existing 53 module-level helpers —
   `_`-prefixed, keyword-only past the first positional, explicit return
   annotation, and the recurring 9-field identity block (`exp_id`,
   `model_type`, `file_index`, `record_params`, `expert_advice_str`,
   `hypothesis`, `is_trial`, `round_index`, `attempt_in_round`).
   `sandbox`/`agent_input`/`plan`/`trial_config` stay un-annotated, as in
   `:1841`, `:1791`, `:1894`.

#### 3. What is extracted, and what deliberately is not

**Extract (five boundaries):**

| # | Boundary | Shape | Why it is safe |
|---|---|---|---|
| E1 | `_build_execution_failure_record(status, *, phase, …) -> dict` | pure builder | The inference block `:3450-3511` is the same algorithm as `_build_training_failure_record` (`:114`), and `error_scoring` (`:3689`) is a third copy. Collapsing them removes a real drift, not just lines |
| E2 | `_build_skip_record(kind, *, identity, probe) -> dict` | pure builder | `:3052-3083`, `:3141-3181`, `:3315-3360` are the same shape over the identity tuple; `3a`/`3e` are already extracted this way |
| E3 | `_emit_record(sandbox, record) -> None` | validate + save | Makes contract 3 structural instead of a convention repeated 9 times |
| E4 | `_stamp_runtime_evidence(record, status)` seam inside E3 | mutator | The one place admission can later attach evidence. Initially `status=None` for paths that do not stamp today, so behaviour is byte-identical |
| E5 | `_decide_round_outcome(...) -> RoundDecision` | pure decision | `:4329-4392` is loop arbitration over five already-extracted predicates; returns `BREAK_ITERATION \| SKIP_TO_FORMAL \| CONTINUE` and the caller keeps the `break`/mutation/prints |

**Deliberately NOT extracted:**

- **The shared attempt-failure handler `:4262-4327`.** It reads eight
  loop-locals whose values encode how far the attempt got, and re-`raise`s
  `PlanOverridesError` straight out of `run()`. Only its record builder
  moves. (Its local `failure_reason` at `:4280` shadows the
  gate-produced name — renamed to `_attempt_failure_reason`, a rename,
  not a restructure.)
- **Anything binding the seven `del`-ed names** — hazard (a).
- **The success-commit block `:4248-4260`** — pure loop control, nothing
  admission needs.
- **`run()`'s overall structure.** Not a rewrite. Five boundaries, not
  fifty.

#### 4. Why this is not "moving code"

Surfaces 1 and 2 (training/inference result handling) each mix a
subprocess call, two raising preamble helpers, a `break` that sets a
loop-carried flag, a `continue`, and timing locals read 300-700 lines
later. A helper that performed those exits would be a `goto` with a
function signature.

Instead they return a **typed decision** the caller dispatches on:

```text
PROCEED         -> fall through
RETRY_ATTEMPT   -> continue
TERMINATE_RUN   -> set _scope_violation_reason; break
```

mapping exactly onto today's three outcomes. Timing stays assigned in
the caller's frame, so `:3698`/`:4047` are untouched. This is the
existing `_check_and_record_guardrail_skip` / `_handle_in_subprocess_rejection`
pattern (`bool` → caller `continue`s), widened to three values because
these paths have a third outcome.

**Note on `:3410`:** today's `break` exits the *attempt* loop, and the
run terminates only because `_scope_violation_reason` is re-checked at
`:4332`. That two-step must be preserved exactly; it is easy to
"simplify" into a behaviour change.

#### 4a. Frozen constraints — operator, 2026-08-02

Approved with four hard constraints. These bind the implementation.

##### C1 — Ownership of the seven large objects stays in `run()`

`train_results`, `score_results`, `score_table`, `file_vector`,
`final_scalar`, `reflect_results` and `memory_history` remain owned by
`run()`'s frame and released by the existing `del` + `gc.collect()` block
at `:4378-4391`. B-C4a0 helpers:

- must not hold them via closure, default argument, or any long-lived
  object
- must not return a new container that includes them
- receive only the **minimal fields** needed to build a record
- must not change the timing of the existing cleanup

**Characterization test required**: prove that after a round, no new
helper retains a reference to any of the seven.

##### C2 — B-C4 may not read a stale `resolved_action`

B-C4a0 **records and preserves** today's behaviour and does not quietly
correct it inside a "pure refactor":

> current behaviour: the value written by the last attempt that reached
> scoring, never reset per attempt.

But B-C4's admission skip **must not read a value left by an earlier
attempt**. The typed decision therefore carries the current attempt's own
result:

```text
AttemptDecision
  transition            PROCEED | RETRY_ATTEMPT | TERMINATE_RUN
  resolved_action       GateAction | None
  action_was_produced   bool
  attempt_id            str
```

An admission refusal yields `resolved_action = None`,
`action_was_produced = False`. Downstream decisions read **this
attempt's typed result**, never the outer variable.

If that turns out to be impossible without changing an existing
non-admission path, **stop and re-review** rather than adjusting one.

##### C3 — Admission gets its own status, never `skipped_time_risk`

`skipped_time_risk` already carries three distinct meanings and feeds
five time-factor consumers. Admission does **not** join it. Frozen
vocabulary:

```text
status        = skipped_resource_admission
resource_type = gpu_memory
reason_code   = insufficient_headroom
              | measurement_unavailable
              | policy_unavailable
```

It means **the environment does not currently permit starting the
phase**. It is not a statement about the candidate and carries **no
authority to shrink it** — the same rule as §B-C3's attribution.

B-C4a0 builds only the builder and the typed surface. **Production
emission of this status is B-C4.**

##### C4 — Test substitutability must be preserved and proven

Every helper resolves `_run_skill`, `TidmadSandbox`,
`run_production_preflight` and every other patchable entry point **from
module globals at call time** — never captured into a local, a closure,
or a default argument.

**Reverse proof required**: changing any one call to a captured
reference must make a test **fail**. A suite that stays green while
bypassing the mock is the failure mode this constraint exists to
prevent.

#### 4b. In and out of scope for B-C4a0

**Implement**: E1 execution-failure record builder, E2 skip/refusal
record builder, E3 `_emit_record`, E4 runtime-evidence stamping seam,
E5 typed round/attempt decision, plus parity, reachability and
artifact-compatibility tests.

**Implementation record (2026-08-02):**

- [x] **E1** `_build_execution_failure_record(status, *, phase, …)`.
      Training and inference were two copies of one algorithm, and they
      had already drifted — the OOM test existed in two spellings until
      B-C3b's pyright repair. `phase` selects wording, the status pair
      and the inference-only silent-crash re-route; the three genuinely
      per-phase strings live in one `_PHASE_FAILURE_TEXT` table so the
      shared builder is honest rather than a near-miss. Pure: it builds
      and returns, nothing else.
- [x] **E3/E4** `_emit_record(sandbox, record, *, status=None)`. Stamp,
      validate, persist — in that order, in one place. All **8**
      remaining `model_validate` + `save_record` pairs routed through
      it (6 in `run()`, 2 in existing helpers). The pairing was a
      convention repeated at nine sites; one unvalidated write makes the
      whole iteration unresumable, so it is now structural. `status`
      defaults to `None`, which stamps nothing — byte-identical to what
      every non-executor path does today — and is the single seam a
      later admission refusal attaches to.
- [x] **Reachability retargeted, not weakened.** B-C3b asserted the gate
      via two literal `phase=` constants at `_oom_memory_wording` call
      sites; with one shared builder that call is `phase=phase` and the
      old assertion silently measured nothing. Replaced by a **chain**:
      `_build_execution_failure_record` is the *only* caller of the gate,
      **and** both production sites reach it with the two literal
      phases. Asserting only the second half would let a new site emit
      shrink wording without consulting the attribution at all. A third
      test asserts no `save_record` is reachable without validation.
- [x] **E2** `_build_skip_record(...)` — the three inline skip paths
      (schema violation, VRAM gate, time gate) were the same eight-key
      shape over the same nine-field identity block, differing in three
      strings and a few optional memory fields. `memory_extra` is applied
      **before** the position stamps, so each site's key order is
      unchanged. The conditional extras moved out of `run()` into
      `_vram_skip_memory_extra` / `_time_skip_memory_extra`.
- [x] **E5** `AttemptTransition` / `AttemptDecision` / `RoundDecision` +
      `_decide_round_outcome`. The round arbitration is now a pure
      function of four already-computed inputs; the `break`, the
      `completed_rounds` fast-forward and the operator prints stay in the
      caller. Ordering is pinned by test: a non-retryable termination
      outranks a gate action, because a scope violation is deterministic
      on retry.
- [x] **C1** cleanup-ownership guard — `test_control_boundary.py`
      asserts `run()` still binds and releases all seven transients, that
      a collection still runs, that **no** extracted helper so much as
      *names* one of them (a helper that never names them cannot capture
      one in a closure or return it in a container), and a weakref test
      that a built record does not pin its inputs.
- [x] **C2** `AttemptDecision` carries `resolved_action` **per attempt**,
      with `action_was_produced` distinguishing "produced none" from
      "produced CONTINUE". `AttemptDecision.admission_refused()` is the
      shape B-C4 must use: `resolved_action=None`,
      `action_was_produced=False`. Collapsing those two states is how a
      refusal would silently inherit a neighbouring attempt's verdict.
- [x] **C3** `RESOURCE_ADMISSION_STATUS` /
      `RESOURCE_ADMISSION_REASONS` + `_build_resource_admission_record`.
      An unknown `reason_code` raises rather than being recorded. A test
      asserts the builder has **no production caller** — if one appears
      before B-C4's review, that test is what says so.
- [x] **C4** module-global resolution, guarded from both directions: no
      helper captures a patchable name as a default argument, and no
      module-level alias freezes a binding.

**Negative proof (mutation) — every constraint verified to fail when
violated:**

| Mutation | Result |
|---|---|
| a helper names a cleanup-owned object | 1 failed |
| `run()` stops releasing `score_table` | 1 failed |
| helper captures `TidmadSandbox` as a default argument | 1 failed |
| module-level alias `_SANDBOX_ALIAS = TidmadSandbox` | 1 failed |
| an admission emitter appears before B-C4 | 1 failed |

`run()`: **2,361 lines, 245 branch nodes** — down from 2,487/261 when
PR B started, and 13 below master's 258, which is the last figure known
to pass. Headroom is the point; the number is not the acceptance
criterion.

**Do not implement**: GPU headroom arithmetic, measurement lookup, the
production call that refuses a phase, any new default, B-G1/B-G2, or any
real GPU/LLM run.

#### 5. Acceptance

The criterion is **not** a branch-node number, which would invite gaming:

> B-C4's refusal path can be implemented inside the extracted boundary,
> without adding a new family of admission-specific `if` branches to
> `run()`.

- [ ] behavioural parity tests for every extracted path
- [ ] mutation/revert evidence that those tests detect a bypass
- [ ] the seven `del`-ed names still bound in `run()`'s frame — asserted,
      not assumed
- [ ] mock-interception preserved: all ~94 `run()`-driving invocations
      still pass, and helpers call the patched names as module globals
- [ ] `test_attribution_gating.py` reachability tests still green,
      exactly two `phase=` call sites
- [ ] strict pyright green on the exact implementation head
- [ ] tuner, core, agent and guardrail suites green
- [ ] no real-subprocess escape, no GPU/LLM run, no default changed
- [ ] no admission logic in this commit

#### 6. Sequence

```text
B-C3 COMPLETE (CI green, 5ba4a40)
  -> B-C4a0: extract E1-E5, parity-proven
  -> B-C4:   implement pre-phase admission inside the boundary,
             and state what happens to resolved_action (hazard b)
```

---

### B-C4 — Pre-phase headroom check and production reachability

#### 1. Goal

Refuse to start a GPU phase that measurement says will not fit, and
prove the check is reachable from production — the failure mode this
whole document exists to prevent.

Last because it is the only commit that changes control flow, and it
depends on the accounting and attribution below it being correct.

#### 2. Scope

- `core/sandbox_executor.py` — a check at the training seam
  (`:1026`, observer construction) and the inference seam (`:1332`),
  before `Popen` on **both** the watchdog and plain branches,
  **returning a status dict, never raising** (§3.2). Line numbers
  re-verified 2026-08-02; the `:827-829` / `:1124-1127` this section
  used to cite were pre-B-C2.
- Reuse `evaluate_pair_admission` (`pair_admission.py:150`) for the
  ceiling arithmetic with **measured** members rather than configured
  caps, so the guard and the CLI answer the same function.
- `nodes/ml_hyperparameter_tune_agent/...` — consume the refusal through
  the **B-C4a0 boundary**: `_build_resource_admission_record` (built,
  deliberately caller-less) via `_emit_record`, and
  `AttemptDecision.admission_refused(...)` for the transition. Not a new
  family of `if`s in `run()`.
- **New**: `tests/unit/guardrails/test_gpu_guard_production_reachability.py`
  — AST-based, in the style of PR A's
  `test_preflight_production_reachability.py`.
- Unchanged: no peer killing, no concurrency reshaping, no threshold
  change, no scoring check.

Depends on B-C1, B-C2, B-C3.

#### 2a. Where the "requested memory" number comes from

**Corrected 2026-08-01.** The check must not take the pre-flight's
predicted *allocated* estimate and compare it against a driver-visible
ceiling. A6 proved those are different quantities (1.95× and 1.82×
apart), and doing so would rebuild the exact defect PR B exists to fix,
behind a new guard that looks like it is working.

Priority order for the requested figure, highest first:

| # | Source | Applicable when |
|---|---|---|
| 1 | driver-visible measurement of **this same candidate in this same phase** | a previous attempt of the identical config ran and was measured |
| 2 | a validated measurement whose applicability is explicit | the same architecture family, batch and segment length, recorded as such |
| 3 | a bounded live measurement of this candidate | obtainable within the phase's own budget |
| 4 | **nothing applicable** | → the check **cannot assert that it is safe** |

Case 4 is not "assume it fits". It is an admission that the guard has no
basis, and it is resolved by the telemetry policy below — not by
silently falling back to the allocated estimate.

The estimate keeps its existing job as a planning input. It is not
promoted to a resource fact by this commit.

#### 2a-bis. The bootstrap paradox — RESOLVED by D-B5 (Direction B)

> **Heading corrected 2026-08-02.** It read "UNRESOLVED, blocks B-C4"
> long after the resolution below was recorded, so the section announced
> a blocker that no longer existed. The analysis is retained; the verdict
> is at the end of this section and in §5 D-B5.

**Raised by operator review 2026-08-01.** The priority order above has a
circularity for a candidate that has never run:

```text
no applicable measurement
  -> the phase is not admitted
  -> the phase never runs
  -> no measurement is ever produced
  -> the phase is never admitted
```

This matters more here than it would elsewhere, because in this system
**every chain iteration proposes a new plugin architecture**. An unknown
candidate is the normal case, not the exception, so a rule that cannot
admit one would stop the chain rather than protect it.

This is admission *policy*, not an implementation detail, and B-C4 must
not begin until it is chosen.

**Direction A — controlled first measurement.** An unknown candidate's
first run is admitted into an exclusive measuring run: no other
occupancy on the device, protected by the per-attempt host watchdog,
result written to a registry, **not concurrent with another chain**.
Subsequent concurrent admissions then use a real measurement.

- Correct and self-contained: PR B can ship and function alone.
- Cost: the first attempt of each new candidate serializes. With two
  chains each proposing a new plugin per iteration, both would need an
  exclusive first measurement, so the pair alternates for that attempt.
  On A6's numbers (~147 s training at `formal_portion 0.2`) that is
  roughly one training duration of lost concurrency per chain per
  iteration — a real throughput cost, bounded and predictable.

**Direction B — defer to PR C's measurement registry.** B-C4 consumes
only validated, promoted measurements; with no applicable data, formal
mode refuses. First-measurement production belongs to PR C.

- Cleanest separation of responsibility.
- But **PR B would not be independently viable**: with every iteration
  proposing a new candidate, formal mode would refuse essentially all of
  them until PR C lands. PR B would ship a guard that blocks the system
  it is meant to protect.

**Direction C — reuse the pre-flight worker's own measurement.**
PR A already runs an isolated worker on the GPU *before* training
(`isolated_probe.py:451`), and that worker really allocates — its
in-process ancestor is what held 6,962 MiB in V19. B-C1's sampler could
measure that worker's driver-visible peak and use it as the tier-3
bounded live measurement, at no extra GPU work and no serialization.

- **Its validity is unproven and must not be assumed.** The worker's
  peak is not obviously predictive of training's: A6's `wavenet`
  estimated 6.43 GB and trained at 12.52 GiB, and the worker was too
  short to be captured by even 6.6 Hz sampling, so **we have zero data
  points** on worker-peak versus training-peak.
- Cheap to settle: sample the worker during one bounded run across a few
  candidates and compare. If the relationship is weak or
  architecture-dependent, Direction C is dead and costs nothing; if it
  holds, it removes the serialization cost entirely.

**Recommendation.** Adopt **Direction A** as the policy, because it is
the only one that makes PR B correct and independently viable, and run
the Direction C experiment separately as a possible optimization of
A's first step. Do **not** adopt Direction B alone.

**Explicitly rejected in all cases:**

```text
no measurement -> fall back to the allocated estimate
```

That is the defect PR B exists to remove, reintroduced behind a guard
that would then appear to be working.

> **RESOLVED 2026-08-01 — D-B5: Direction B.** Formal cold-start
> measurement belongs to PR C. See §5 D-B5.

#### 2b. Telemetry-unavailable policy — two modes, not one

**Corrected 2026-08-01.** "Proceed on unavailable telemetry" is a
reasonable compatibility posture and an unacceptable formal one. If real
occupancy cannot be measured, safety has not been demonstrated.

```text
trial mode                 telemetry unavailable -> proceed, with an
(spelled `trial`; the        explicit and recorded warning
 word "diagnostic" below
 describes what it does,
 not a config value)

formal V20 mode            telemetry unavailable -> refuse the phase as
                           an infrastructure condition, not a candidate
                           failure
```

The refusal in formal mode is classified as infrastructure and carries
**no candidate-downsizing authority** — the same rule as §B-C3. An
operator override remains available, must be announced and stamped into
the manifest as provenance, and **must not be used in the formal V20
Gate**.

Default selection between the modes lands with the fail-closed change in
this commit (D-B4), after B-G2.

#### 3. Implementation plan — per-commit, template applied 2026-08-02

**Audited before planning** (2026-08-02). The line numbers this section
previously carried (`:827-829`, `:1124-1127`) were pre-B-C2 and are
stale. The real seams are the observer construction points:
`core/sandbox_executor.py:1026` (training) and `:1332` (inference), each
followed by two `_run_observed_subprocess` branches (`:1033`/`:1072`,
`:1337`/`:1376`). `StubSandbox` subclasses `TidmadSandbox` at `:1561`
and overrides both methods — pseudo-mode must not be admitted or
refused, and that is a scope decision, not an accident.

B-C4 is split into four commits so the *decision*, the *wiring*, the
*agent-facing consequence* and the *guardrails* fail independently. The
D-B4 default flip is **not** among them: it lands only after B-G2, per
its own approval.

---

##### B-C4a — the admission decision, no call sites

**1. Goal.** A pure function that answers "may this phase start on this
device right now?" from measured occupancy, returning a typed decision
with its provenance. It belongs alone in a commit because a wrong
decision function and a wrong wiring produce the same symptom, and
separating them is what made B-C3's defects findable.

**2. Scope.**
- New `core/runtime_control/admission.py`: `AdmissionDecision`
  (Pydantic, frozen), `evaluate_gpu_admission(...)`.
- Consumes `GpuAccountingSnapshot` (B-C1) and reuses
  `evaluate_pair_admission` (`core/runtime_control/pair_admission.py:150`)
  for the ceiling arithmetic, with **measured** members — this candidate's
  applicable measured requirement and a member representing "everything
  else" from `other_mib` — so the guard and the CLI answer the same
  function. `PairMember.provenance` already distinguishes a measured
  peak from a configured cap; that field carries the distinction.
- **Non-goals**: no call site, no status emission, no default change, no
  measurement acquisition or promotion (D-B5 — that is PR C), no peer
  registry (D-B1).
- Depends on B-C1, B-C3a, B-C4a0.

**3. Implementation plan.** — **LANDED 2026-08-02**,
`core/runtime_control/admission.py` (233 lines).
- [x] Re-read `pair_admission.py:111-206` and `gpu_accounting.py:146-218`
      before writing. Confirmed `PairMember.predicted_peak_vram_gb`
      requires `> 0`, so an unknown requirement cannot be encoded as
      `0.0` — the type system already refuses the one shortcut that
      would silently admit everything.
- [x] `AdmissionDecision` (frozen) with `admitted`, `reason_code`,
      `requirement_source`, `reason`, `evidence`. A validator enforces
      the correspondence **in both directions**: an admission cannot
      carry a refusal reason, and a refusal cannot omit one — a phase
      refused for no recorded reason can be neither audited nor
      appealed.
- [x] `evaluate_gpu_admission(*, snapshot, requirement_mib,
      requirement_provenance, mode, run_name, ceiling_gib)`.
- [x] Formal + no authoritative requirement → `measurement_unavailable`.
- [x] Diagnostic + same → admit with `requirement_source="unavailable"`,
      so the run's own record shows the guard asserted nothing.
- [x] Telemetry unavailable → `policy_unavailable` (formal) /
      admit-with-no-safety-claim (trial).
- [x] Requirement exceeds measured headroom → `insufficient_headroom`.
- [x] Only `AUTHORITATIVE_PROVENANCE` (`measured`,
      `promoted_measurement`) counts. A predicted estimate is refused in
      formal mode rather than used — A6 measured 6.43 GB predicted
      against 12.52 GiB actually held.

**3a. One design point settled during implementation.** The effective
ceiling is `min(configured_policy, measured_device_capacity)`. Policy
may be stricter than the hardware; it may never be looser, because a
configured ceiling above the card's capacity would admit work the card
cannot hold. Both figures are recorded separately in the evidence, per
§1.4.2 — a configured ceiling is policy, a device total is a measured
fact, and collapsing them is exactly the conflation that rule forbids.

**3b. The asymmetry worth stating.** The two modes differ **only** where
safety is unproven. Where occupancy is measured and the requirement does
not fit, **both** modes refuse: headroom is a fact, not a posture, and a
trial run does not get to disbelieve arithmetic. The same applies
to impossible telemetry (`used > total`).

**4. Validation plan.**
- Unit: each `reason_code` reachable; formal vs trial divergence on
  identical inputs; `admitted=True` with a `reason_code` unconstructible;
  a `0`/negative/`None` requirement never admits by arithmetic accident.
- Negative: telemetry-unavailable snapshot; `used > total`; snapshot from
  a different device UUID than the caller expects.
- Backward-compat: none needed — no call site exists yet, which is the
  point of the split.
- Genericity: no task vocabulary, no hardware constant (the §1.4/§8 rule
  and the same AST guards used in `test_failure_attribution.py`).
- Real-training gate: **none in this commit.**

**5. Acceptance criteria.**
- [x] `evaluate_gpu_admission` has **zero production callers** —
      asserted against both `sandbox_executor.py` and the tuner.
- [x] A requirement that does not fit is refused with
      `insufficient_headroom` in **both** modes.
- [x] No applicable measurement → formal refuses
      `measurement_unavailable`; trial admits with
      `requirement_source="unavailable"`.
- [x] `admission.py` contains no task vocabulary and no numeric constant
      outside `{0, 1}` — AST-guarded by allowlist, because a denylist
      cannot see a constant nobody anticipated, which is how a 12/28 GiB
      literal would arrive.
- [x] Mutation-proved (5/5):

      | Mutation | Result |
      |---|---|
      | accept a predicted estimate as authoritative | 3 failed |
      | let a 0 MiB requirement through | 2 failed |
      | let configured policy exceed hardware capacity | 1 failed |
      | drop the `used > total` guard | 2 failed |
      | stop counting other occupancy | 1 failed |

**6. Failure and edge cases.**

| Case | Handling |
|---|---|
| requirement `None` | refuse in formal (`measurement_unavailable`); admit in trial mode. **Never** treat as 0 |
| requirement present but provenance says "estimate" | not authoritative — formal refuses |
| `telemetry_available=False` | `policy_unavailable` (formal) / warn (trial) |
| `device_used_mib > device_total_mib` | refuse; inconsistent telemetry is not a headroom figure |
| snapshot UUID ≠ expected device | refuse; a verdict about the wrong card is worse than none |
| ceiling misconfigured (`<= 0`) | `evaluate_pair_admission` already raises; let it, do not swallow |

**7. Verification commands and evidence.**
```bash
.venv/bin/python -m pytest tests/unit/core/test_admission.py -q
.venv/bin/python -m pytest tests/unit/core/ tests/unit/guardrails/ -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
- [x] `pytest tests/unit/core/test_admission.py -q` → **31 passed**, 0.12 s
- [x] `pytest tests/unit/core/ tests/unit/guardrails/ -q` →
      **1568 passed, 1 skipped, 3 xfailed**, 27.1 s
- [x] `ruff check .` / `ruff format --check .` → clean (635 files)
- [ ] strict pyright recorded from CI (it cannot run locally — Node
      v10.19.0 crashes the vendored bundle)

**8. Commit boundary.** Reviewable as "decide, and prove the decision".
No call site, no agent-facing text, no default. Diff summary and staged
file list shown before committing.

---

##### B-C4b — wire the check at both seams

**1. Goal.** Make the decision reachable from production, returning a
status dict rather than raising, so a refusal is a result the caller can
record — not an exception that unwinds a phase.

**2. Scope.**
- `core/sandbox_executor.py` — the check at the training seam (`:1026`)
  and the inference seam (`:1332`), **before** `Popen`.
- `StubSandbox` (`:1561`) **must not** be admitted or refused; pseudo
  mode has no device. State this explicitly rather than relying on the
  stub's overrides to bypass it by accident.
- **Non-goals**: no tuner change, no record, no prompt text, no default.
- Depends on B-C4a.

**3. Implementation plan.** — **LANDED 2026-08-02**,
`_admission_refusal` in `core/sandbox_executor.py:466`.
- [x] Re-read both seams before editing. Both have the identical shape —
      `_observer = _make_phase_observer(self)` followed by a
      watchdog/plain branch — so **one** gate placed between them covers
      both launch paths. A gate inside either branch would have been a
      hole that reads as coverage.
- [x] Wired at `:1079` (training) and `:1389` (inference).
- [x] Returns a refusal status dict and **never raises** — but
      **never fails open in formal mode either**. Corrected after
      operator review, 2026-08-02: the first version degraded *any*
      error to "proceed", which would have made formal mode silently
      permissive exactly when it is meant to protect. That is the
      fail-open posture this commit exists to remove, reintroduced in
      the error path.

      ```text
      sampler or gate raises
        -> converted to "no measurement obtained"
        -> handed to the admission policy
        -> trial:  proceed, warning recorded
           formal: refuse, measurement_unavailable
      ```

      Mode policy therefore has exactly **one** home:
      `evaluate_gpu_admission` gained a `sampling_error` parameter rather
      than the executor branching on mode itself. The single exception is
      a failure of the policy call itself, where the executor must decide
      without it — and there formal refuses rather than falling through
      to a launch.
- [x] No device identity → returns `None`, behaviour unchanged. That is
      the pre-PR-B path, and refusing there would break every machine
      without telemetry.
- [x] Pre-spawn occupancy comes from a plain `sample(os.getpid(), …)`:
      this phase's child does not exist yet, so the tree rooted at this
      process is what "ours" means and everything else on the card is
      somebody else's. Whatever this process tree already holds is
      **measured** and counted as ours. PR A's isolated worker made that
      figure small in practice, but **the logic does not assume it is
      zero** — pinned by a test that passes a parent already holding
      7,000 MiB and asserts it stays on the own side of the split, and
      by a structural test that the gate precedes every launch, so the
      sample cannot include the phase's own child.
- [x] Mode and requirement are read off the run
      (`admission_mode` default **`trial`**,
      `measured_requirement_mib`, `measured_requirement_provenance`).
      PR B produces no measurement (D-B5), so the default configuration
      admits and records that it asserted nothing. **No default moves in
      this commit** — that is D-B4, after B-G2.
- [x] `StubSandbox` confirmed unaffected **by test**, not by
      inspection: it overrides both methods and never calls the gate.

**3a. A stale invariant this commit retired, deliberately.**
`TestNoTelemetryYet::test_the_executor_does_not_query_the_gpu` was
written for B-C2a1, when the executor was routing alone and any
telemetry reference would have made a parity regression
un-attributable. It forbade `gpu_accounting` in the executor, and
survived B-C2b only because the observer is reached through
`gpu_observer`. B-C4b's approved design **requires** reading occupancy
before spawn, so that term was removed rather than worked around. The
test was **narrowed, not deleted**: the executor must still not contain
`nvidia-smi` or `DeviceIdentity`, because the telemetry backend belongs
to `gpu_accounting` and identity is resolved upstream — the executor
must not be able to choose which GPU it is talking about.

**4. Validation plan.**
- Unit: refusal returns before `Popen`; admission proceeds unchanged;
  the returned dict carries the decision's provenance.
- Parity: with admission in trial mode and telemetry present,
  every existing executor test behaves identically.
- Negative: a refusal must not leave an observer running, a baseline
  half-captured, or a `runtime_verification` sidecar written.
- Escape guard: the autouse `RealSubprocessEscape` guard must still
  intercept — a refusal path that bypasses `Popen` must not also bypass
  the guard's evidence.
- Real-training gate: **none in this commit.**

**5. Acceptance criteria.**
- [x] Admission is decided in **exactly one function**
      (`_admission_refusal`), and the tuner never decides it — B-C4a's
      "no caller yet" test was **retargeted, not deleted**, when B-C4b
      legitimately added the executor's call. Two call sites could
      disagree about the same device.
- [x] With a refusing decision injected, **`subprocess.Popen` is not
      called** — asserted at the launch boundary for both phases, not
      inferred from a returned status.
- [x] The gate is AST-proved to precede **both**
      `_run_observed_subprocess` calls in each method: exactly one gate,
      exactly two launches, gate line < both launch lines.
- [x] `StubSandbox` reaches neither the gate nor a refusal.
- [x] The tuner still does not consume the status — that is B-C4c, and
      a test says so.
- [x] Default mode is `trial`; flipping it to `formal` breaks a
      **behavioural** seam test, which is the parity evidence that the
      default is genuinely inert.
- [x] **Formal mode never fails open**: a sampler failure refuses with
      `measurement_unavailable`, launches nothing, and blames nothing;
      trial proceeds with the error recorded rather than discarded.
- [x] Mutation-proved (9/9): remove the training gate, remove the
      inference gate, move the gate after the launch, flip the default
      mode, add a second decision call in the executor, let the tuner
      decide admission itself, **restore the fail-open blanket
      `except`**, **let formal fall through when the policy itself
      fails**, **root the sample at PID 1 instead of this process** —
      each fails a named test.

**3c. Reason-code split — corrected by operator review, 2026-08-02.**
The first mapping had two cases the wrong way round.

```text
measurement_unavailable   no trustworthy device fact was obtained
  detail: sampler_error | telemetry_unavailable
        | inconsistent_accounting
        | device_identity_mismatch   (RESERVED — not emitted)

policy_unavailable        facts exist, but what is needed to DECIDE on
                          them does not — no applicable authoritative
                          requirement, no resolved ceiling
```

A successful query that *reports* unavailable telemetry, or returns
figures that cannot be true (`used > total`), is still a **measurement**
problem — it was previously filed as `policy_unavailable`. Conversely a
missing authoritative requirement, with occupancy measured perfectly
well, is a **policy** gap and was previously filed as
`measurement_unavailable`. `detail` is validated to be meaningful only
under `measurement_unavailable`, so a record cannot carry a measurement
detail against a policy refusal.

**`device_identity_mismatch` is reserved and has no producer.** Comparing
the snapshot's UUID against an expected device needs a caller-supplied
expectation this layer is not given, and adding that comparison would
widen B-C4b past its scope. It is declared so the vocabulary is fixed
before a producer exists — no test claims it is covered by a production
path.

**Mode validation — corrected again by operator review, 2026-08-02.**
An unrecognised posture must fail closed **without masquerading as a
deliberate `formal`**: otherwise a typo in the settings and an explicit
operator choice produce the same record, and the audit trail lies about
what was configured.

```text
mode absent          -> trial               (compatibility default)
mode = trial         -> trial
mode = formal        -> formal
mode = anything else -> refuse
                        reason_code = policy_unavailable
                        detail      = invalid_admission_mode
                        raw value kept in evidence
```

Validation lives in `evaluate_gpu_admission` (its `mode` parameter is
typed `str` and checked there), **not** in the executor — a caller that
resolved a wrong value onto a valid posture would be the same
conflation in a different place. A test asserts the executor passes the
raw value through untouched.

**Vocabulary settled: `trial | formal`, and `diagnostic` is invalid.**
Operator decision 2026-08-02, replacing the previous spelling. The audit
that raised it: nothing sets `admission_mode` — B-C4b introduced it —
while every other mode field in the project reads `trial | formal`
(`time_mode`, `active_mode`, `RuntimeMode.phase`). "Diagnostic"
describes what a trial round *does*; it is not a second configuration
word for the same policy. Accepting both would put **two spellings of
one posture** into every record that carries it, and provenance would
stop being able to say which policy ran. `diagnostic` is therefore
rejected as a misconfiguration, exactly like `formL`, and a test names
why.

**Absent and explicit `None` are distinguishable**, verified rather than
assumed: the `getattr` default is the string `"trial"`, so a missing
field resolves to the compatibility posture while an explicitly `None`
field is an invalid value. `getattr(..., None)` would merge the two and
make the tests claim a distinction production could not draw — pinned by
a behavioural test that drives both through the real gate and by a
structural test on the default literal.

Behaviour matrix, as frozen:

| | trial | formal |
|---|---|---|
| `measurement_unavailable` | warn, proceed | refuse |
| `policy_unavailable` | warn, proceed | refuse |
| `insufficient_headroom` | **refuse** | refuse |
| `invalid_admission_mode` | refuse | refuse |

Behaviour under both:

```text
trial  + measurement_unavailable -> warn and proceed
formal + measurement_unavailable -> refuse
formal + policy_unavailable      -> refuse
```

> **A bad proof, caught and redone.** The first attempt at the
> "second decision authority" mutation added an *aliased import*
> (`as _ega`) and never called it. The guard collects `ast.Call` nodes,
> so nothing fired — and the mutation passing looked exactly like a weak
> guard. It was the proof that was weak. Redone with a real call site,
> it fails as intended. A mutation that does not exercise the thing it
> claims to test is worse than no mutation, because it is recorded as
> evidence.

**6. Failure and edge cases.**

| Case | Handling |
|---|---|
| admission itself raises | must not fail the phase — catch, record, proceed as diagnostic. Telemetry may not break the science it watches (same rule as B-C2b) |
| device identity unavailable | no snapshot, so no decision — diagnostic behaviour, recorded |
| refusal on the inference seam after training succeeded | refuse the phase; the trained checkpoint is not discarded |
| watchdog/deadline branch vs plain branch | both must be gated identically, proven by test on each |

**7. Verification commands and evidence.**
```bash
.venv/bin/python -m pytest tests/unit/core/ -q
.venv/bin/python -m pytest tests/unit/agent/ tests/unit/guardrails/ -q
```
- [x] `pytest tests/unit/core/test_admission{,_wiring}.py -q` → **83 passed**, 0.23 s
- [x] `pytest tests/unit/core/ tests/unit/agent/ tests/unit/guardrails/ -q`
      → **4836 passed, 1 skipped, 3 xfailed**, 248 s, zero failures
- [x] `ruff check .` / `ruff format --check .` → clean (636 files)
- [ ] strict pyright recorded from CI

**8. Commit boundary.** Reviewable as "the check is reachable and
changes nothing when it admits". No agent-visible consequence yet.

---

##### B-C4c — consume the refusal in the tuner

**1. Goal.** Turn a refusal into a recorded skipped attempt that the
planner reads correctly — an infrastructure condition, never a verdict
about the candidate.

**2. Scope.**
- `nodes/ml_hyperparameter_tune_agent/...` — consume the refusal
  through the **B-C4a0 boundary**: `_build_resource_admission_record`
  (already written, currently caller-less) emitted via `_emit_record`,
  and `AttemptDecision.admission_refused(...)` for the transition.
- **Non-goals**: no new status (C3 froze
  `skipped_resource_admission`), no fourth producer of
  `skipped_time_risk`, no new branching family inside `run()`.
- Depends on B-C4b and B-C4a0.

**3. Implementation plan.**
- [ ] Re-read `_build_resource_admission_record` and
      `AttemptDecision.admission_refused` before wiring.
- [ ] Emit the record via `_emit_record`, so validation stays paired
      with persistence.
- [ ] Use `AttemptDecision.admission_refused(...)` so the attempt
      carries `resolved_action=None, action_was_produced=False`
      (constraint C2) — it must **not** read the round-scoped
      `resolved_action`, which holds whatever the last attempt that
      reached scoring wrote.
- [ ] Apply the frozen budget rule below: the refusal **consumes the
      current per-round attempt slot** and is **not** a candidate
      failure. Set `counts_toward_attempt_budget=True` and
      `counts_toward_completed_rounds=False` on the record, and do not
      increment any candidate-failure counter.
- [ ] Confirm the planner prompt suppresses shrink advice for this
      status via the existing B-C3b `unattributed_oom_note` path, or
      extend that note — do not write a second suppression mechanism.

**3a. Attempt-budget rule — FROZEN (operator, 2026-08-02).**

```text
GPU admission refusal
-> consumes the current per-round attempt slot
-> does NOT count as a candidate failure
-> produces no negative planner evidence
-> produces no downsizing advice
-> does not update the incumbent
-> does not automatically retry
```

Rationale: planning, pre-flight and admission really executed, so the
attempt slot really was used. Not consuming it risks an unbounded retry
loop whenever the device stays busy, and adding a separate admission
retry budget would widen PR B. **Consuming a control-flow budget is not
the same as blaming the candidate** — the two are deliberately
decoupled, exactly as `gpu_contention` consumes a failure without
carrying downsizing authority.

When every attempt in a round is refused:

```text
round outcome        = skipped_resource_admission
authoritative result = none
candidate failure    = false
```

Whether a queue later reschedules that work is **out of scope for PR B**.
This commit adds no immediate retry and no wait/backoff mechanism.

**4. Validation plan.**
- Unit: the record validates; `reason_code` and `resource_type` survive
  to disk; a legacy reader without the status is unaffected.
- Budget: a refused attempt consumes exactly one attempt slot; a round
  whose attempts are all refused ends with no authoritative result and
  **no** candidate-failure increment; no automatic retry is issued.
  to disk; a legacy reader without the status is unaffected.
- Prompt-level: **asserted on the rendered planner prompt** — no
  shrink instruction appears for a `skipped_resource_admission` record.
- Reachability: the builder now has exactly one production caller, and
  the "no emitter yet" test from B-C4a0 is **replaced**, not deleted.
- Resume: `core/resume.py` must treat the new status as non-success
  without excluding the iteration; verify against a real persisted
  record shape.
- Real-training gate: **none in this commit.**

**5. Acceptance criteria.**
- [ ] For a refused attempt, the rendered planner prompt contains
      neither `reduce model size, batch_size, or segmentation_size.`
      nor `This config exceeds GPU memory. Try smaller architecture.`
- [ ] The persisted record carries `status="skipped_resource_admission"`,
      `memory.resource_type`, `memory.reason_code`.
- [ ] `may_recommend_resource_reduction` is never true for it.
- [ ] A refused attempt advances `attempt_in_round` by exactly one, and
      `consecutive_fails` / any candidate-failure counter is unchanged —
      asserted on the counters, not on the record text.
- [ ] A round in which every attempt is refused produces no
      authoritative result, does not update the incumbent, and is not
      recorded as a candidate failure.
- [ ] No retry, sleep or backoff is introduced — provable by diff.
- [x] **Criterion corrected by operator review, 2026-08-02.** The
      original `<= 245` is replaced by what it was actually trying to
      say:

      > B-C4c must not put admission's record construction, policy
      > decisions or side effects back into `run()`. Only the thin
      > branches needed to complete the phase transition may be added.

      Recorded honestly rather than gamed:

      ```text
      B-C4a0 baseline : 245 branch nodes
      B-C4c result    : 247 branch nodes
      ```

      The two are `if _handle_admission_refusal(...): continue`, one per
      phase — the minimum a commit whose purpose is consuming a status
      at two call sites can cost, and identical in shape to the existing
      `_handle_in_subprocess_rejection`. Record construction, wording,
      reason vocabulary, budget accounting and emission all live in
      helpers. Extracting unrelated code to reach 245 would be the
      mechanical line-moving §1.5 forbids, so it was not done.

      **B-C4d must add no further `run()` branches** — it is tests only.
- [ ] Mutation: routing the refusal to `skipped_time_risk` fails a test.

**6. Failure and edge cases.**

| Case | Handling |
|---|---|
| every attempt in a round refused | round outcome `skipped_resource_admission`, no authoritative result, **not** a candidate failure. No retry or wait is added — rescheduling is out of PR B's scope |
| refusal on a formal round | recorded as infrastructure; must not corrupt the formal comparison |
| legacy record lacking the status | reads as before (`extra="ignore"`) |
| a refused attempt and a stale `resolved_action` | the typed decision wins; pinned by test |

**7. Verification commands and evidence.**
```bash
.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/ -q
.venv/bin/python -m pytest tests/unit/core/ tests/unit/agent/ tests/unit/guardrails/ -q
```
- [x] `pytest tests/unit/core/ tests/unit/agent/ tests/unit/guardrails/ -q`
      → **4843 passed, 1 skipped, 3 xfailed**, 247 s, zero failures
- [x] `ruff check .` / `ruff format --check .` → clean
- [x] Mutation-proved (6/6): remove the training consumption site,
      remove the inference consumption site, stop consuming the attempt
      slot, count a refusal as a completed round, hand-assemble the
      record through the generic skip builder, and let the executor
      build the agent-facing record — each fails a named test.

> **Two bad proofs, caught and redone.** `if False and handler(...)`
> leaves the call node in the AST, so a reachability guard still sees
> it and the mutation passes — the same shape as the earlier aliased
> import. AST-based guards must have the call **removed**, not disabled,
> or the mutation measures nothing and is filed as evidence anyway.

- [ ] strict pyright recorded from CI

**8. Commit boundary.** Reviewable as "a refusal reaches the agent, and
says the right thing". No default change.

---

##### B-C4d — the join contract, and consolidated revert evidence

**Scope changed by audit + operator approval, 2026-08-02.** The original
plan was a new AST guardrail file. An audit before writing it found that
**every assertion it would contain already exists**, added during
B-C4a/b/c:

| Planned assertion | Already asserted by |
|---|---|
| both production paths reach the gate | `test_the_gate_precedes_every_launch_in_that_method` (parametrised over both phases) |
| the gate precedes every GPU launch | same — one gate, two launches, gate line first |
| a refusal never starts `Popen` | `test_a_refusal_never_reaches_popen` (both phases) |
| the tuner routes through the handler | `test_the_tuner_consumes_it_through_the_approved_handler` |
| one builder, both phases | `test_the_builder_is_reached_only_from_the_approved_path`, `test_both_phases_consume_the_refusal` |
| no second decision point | `test_the_executor_gates_both_phases`, `test_the_tuner_never_decides_admission_itself` |
| no hand-assembled record | `test_nobody_hand_assembles_an_equivalent_record` |

Duplicating them would add maintenance surface and no evidence.

**What was genuinely unproven is the join.** Every test above drives one
side against a fixture the test wrote. The executor's *actual* output had
never been handed to the tuner's *actual* handler, so a drift in the
shape between them was invisible from either side:

```text
rename the `admission` key
  -> tuner's `status.get("admission") or {}` yields {}
  -> reason_code falls back to "policy_unavailable"
  -> a MEASURED capacity shortfall is recorded as a missing policy
  -> both unit suites stay green
```

That is this PR's own failure class — a correct measurement, wrongly
attributed — reappearing at a layer boundary.

**1. Join contract test** —
`tests/unit/core/test_admission_join_contract.py`, **22 tests**,
parametrised over training and inference. Nothing is rebuilt: only the
sampler is substituted, `evaluate_gpu_admission` runs for real, and the
resulting object is passed straight into `_handle_admission_refusal`.
Assertions are on the `ExperimentRecord` that emerges.

- [x] `reason_code` survives — `insufficient_headroom` does **not**
      become `policy_unavailable`
- [x] `detail` survives, including as `None`, so absent and
      not-applicable stay distinguishable
- [x] the audit figures survive verbatim (`mode`, `other_mib`,
      `requirement_mib`, `requirement_provenance`)
- [x] the reverse direction too: an invalid mode arrives as
      `policy_unavailable` / `invalid_admission_mode` with the raw value,
      never as a capacity shortfall
- [x] final status `skipped_resource_admission`, record validates
- [x] no shrink advice, no reduction authority
- [x] the budget accounting survives the join
- [x] no GPU subprocess started
- [x] a self-guard: the fixture is asserted to be genuinely refused, so
      the rest cannot pass vacuously against an empty run

**2. Consolidated revert evidence.** Every guard, what it protects, and
the real mutation that breaks it. **No `if False`, no unused alias** —
those leave the call node in the AST, so a reachability guard still sees
it and the mutation passes while measuring nothing.

| Guard | Protects | Mutation | Result |
|---|---|---|---|
| `test_the_reason_code_is_not_silently_downgraded` | the join's whole purpose | tuner ignores the incoming `reason_code` | **2 failed** |
| join suite | payload shape | rename executor key `admission` → `decision` | **10 failed** |
| join suite | payload completeness | drop `reason_code` from the executor payload | **6 failed** |
| `test_the_audit_figures_survive` | auditability | tuner passes `admission_evidence=None` | **6 failed** |
| `test_both_phases_consume_the_refusal` | reachability | delete the training consumption call site | **1 failed** |
| `test_the_gate_precedes_every_launch_in_that_method` | gate placement | move the gate after the launch | 2 failed (B-C4b) |
| `test_a_refusal_never_reaches_popen` | no launch on refusal | remove the training gate | 2 failed (B-C4b) |
| `test_the_executor_gates_both_phases` | one decision point | add a second `evaluate_gpu_admission` call | 1 failed (B-C4b) |
| `test_the_executor_does_not_build_the_agent_facing_record` | layer separation | executor builds the record | 1 failed (B-C4c) |
| `test_it_consumes_the_attempt_slot_but_not_a_round` | budget rule | `counts_toward_attempt_budget=False` | 1 failed (B-C4c) |
| `test_a_round_of_refusals_produces_no_authoritative_result` | round outcome | count a refusal as a completed round | 2 failed (B-C4c) |
| `test_the_builder_is_reached_only_from_the_approved_path` | one builder | hand-assemble via the generic skip builder | 9 failed (B-C4c) |

**Recorded results (2026-08-02):**

| Command | Result |
|---|---|
| `pytest tests/unit/core/test_admission_join_contract.py -q` | **22 passed**, 0.95 s |
| `pytest tests/unit/core/ tests/unit/agent/ tests/unit/guardrails/ -q` | **4866 passed, 1 skipped, 3 xfailed**, 246 s |
| `ruff check .` / `ruff format --check .` | clean, 637 files |
| strict pyright | CI-only (Node v10.19.0 locally) |

**3. Commit boundary.** Tests and documentation only. Zero production
code, zero new `run()` branches (still 247), zero default change, no
GPU/LLM run.

##### Not in B-C4

```text
D-B4 fail-closed default flip   -> only after B-G2, on the exact head
B-G1 / B-G2 real-training gates -> operator approval, not launched here
PR C measurement promotion      -> D-B5
```


#### 9. Commit boundary — B-C4 as a whole

The only control-flow change in PR B, and the only place a phase can be
refused. Split into four independently reviewable commits above.
Contains no vocabulary change (B-C3 froze it), no launcher default
change, and no measurement promotion (D-B5).

---

### B-C5 — Documentation sync — COMPLETE 2026-08-02

Per the operator rule (`CLAUDE.md`, 2026-07-28): every PR touching a node
or skill updates the relevant `.md` so CLI arguments, defaults and
behaviour explanations stay current, done as the last step before merge
and verified by quoting each claim against the merged source.

**Scope, from the diff rather than from memory.** `git diff 5c18946..HEAD`
touches exactly three directories: `core/`, `core/runtime_control/`,
`nodes/ml_hyperparameter_tune_agent/`. **No `agent/skills/` directory was
touched**, so no skill doc is in scope. `core/runtime_control/` is
generic infrastructure — not a node and not a skill — and is documented
by this design document; it gets no `.md`, and that is a decision rather
than an omission.

- [x] `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`
      — new "GPU admission and failure attribution (V20 PR B)" section:
      the `skipped_resource_admission` record and its three `memory`
      keys, the `trial | formal` posture with its behaviour matrix, the
      attempt-budget rule, the attribution vocabulary and its single
      authority, and the D-B5 cold-start cost. The ordering-provenance
      table's `not_executed` row enumerated the three pre-flight skip
      statuses and would have silently omitted the fourth — corrected.
      `all_records` now says admission-refused rounds appear there and
      carry no score.
- [x] `docs/running_chain_test.md` — a "Common pitfalls" row, because an
      operator reading run output would otherwise find records for
      phases that never started inexplicable. Names each `reason_code`
      and says plainly that `measurement_unavailable` in formal mode is
      **expected** until PR C lands, so it is not misread as a defect.
- [x] **No CLI argument was added or changed by PR B** — verified by
      `git diff … | grep add_argument`, which returns nothing. Stated
      explicitly in the node doc, since the doc-sync rule is written
      around CLI arguments and "none" is the honest answer.
- [x] Every documented claim quoted against merged source: accepted
      modes `{formal, trial}` (`admission.py:98`), default `trial`
      (`sandbox_executor.py:499`), the three reason codes
      (`admission.py:57-61`), the three `memory` keys
      (`ml_hyperparameter_tune_agent.py:482-484`), and the five
      attribution outcomes (`failure_attribution.py:48-54`).

---

## 4b. Cross-hardware bring-up and revalidation

**Added 2026-08-02** after the operator asked whether this workflow can
be repeated on an H100 host. The honest answer separates two claims:

> The architecture **allows** it — devices are UUID-keyed, ceilings come
> from configuration, and no measurement is silently reused across
> cards. That makes it *possible*. It does not make it *reproducible*
> until the operator sequence is written down, which is what
> `docs/running_chain_test.md` "New GPU host" now does.

### 4b.1 What binds a measurement

```text
normalized candidate config · phase · task · dataset/data-shape class
· runtime settings · measurement type · GPU UUID
```

All seven. **An RTX 5090 measurement is not an H100 measurement**, even
for a byte-identical candidate, and there is no "close enough" — the
tuple matches or it does not. Moving hardware therefore invalidates
every stored figure *for admission purposes*; it does not invalidate the
historical evidence itself, which stays true of the machine it was taken
on. A6's figures remain A6's figures.

### 4b.2 Per-host, per-candidate, neither

| Scope | Items | Repeat when |
|---|---|---|
| per host, once | GPU UUID, ceilings, host quota, concurrency, telemetry policy | new machine or GPU |
| per candidate + phase | driver-visible peak on that UUID | any config, batch, segment, portion, task or data-shape change |
| neither | the commands, the admission logic, the attribution vocabulary | never — **no production edit should be required to onboard a host** |

### 4b.3 Responsibility split, restated for new hardware

- **PR B** consumes an applicable authoritative measurement and enforces
  headroom. On a fresh host it has none, so `formal` refuses with
  `measurement_unavailable`. **That is the guard working**, and the
  bring-up doc says so explicitly so it is not read as a defect.
- **PR C** decides applicability and promotes. First-measurement
  acquisition on new hardware is its responsibility.
- `evaluate_vram_skill` measures a **predicted allocated peak** and
  promotes nothing. Now documented in
  `agent/skills/evaluate_vram_skill/evaluate_vram_skill.md`, created by
  this audit — the skill owning the most hardware-bound quantity in the
  system had no document at all.

### 4b.4 A concrete hazard the audit found

`DEFAULT_PAIR_CEILING_GIB = 28.0` (`pair_admission.py:45`) is a
compatibility default chosen for a 31.34 GiB RTX 5090. It is overridable
only through `SIDERIUS_PAIR_VRAM_CEILING_GIB`.

On an **80 GB H100 that default would silently cap the card at 28 GiB**
and refuse legitimate work as `insufficient_headroom` — a message that
reads as "the device is busy" rather than "your ceiling is
misconfigured". The effective ceiling is
`min(configured, measured capacity)`, so the hardware cannot rescue a
too-small configured value. The runbook now requires setting it
explicitly on any host whose card is not ~32 GiB.

This is exactly the §1.4 failure mode — a value that is *configured
policy* reading like a *framework constant* — surviving in a default
rather than in code.

### 4b.5 Not changed by this audit

No production code, no default, no new candidate injection, no registry.
Documentation only. The H100 sequence requires **no** production edit;
it requires configuration, a bounded measurement, and PR C.

---

## 4c. Real-validation scope — FROZEN 2026-08-02

### 4c.1 What B-G1/B-G2 exercise

Approved entry point: **not** `run_chain.sh`, but everything below it
real.

```text
real tuner
  -> existing sandbox_factory seam
  -> real TidmadSandbox
  -> real admission gate
  -> real training / inference launch boundary
```

A validation-only measurement fixture is permitted, and may enter
**only** through the existing measurement-consumer boundary.

**Explicitly forbidden**, because each would make the result describe
something other than production:

- `StubSandbox` or any fake executor
- calling the admission function directly and calling that a production
  test
- monkeypatching the gate, the sandbox, or `subprocess`
- a temporary registry or auto-promotion
- bypassing the tuner's real refusal-consumption path

Under those constraints B-G1/B-G2 demonstrate PR B's actual mechanism:
permit on applicable evidence, refuse before the GPU child starts when
headroom is insufficient, and record the refusal without blaming the
candidate.

### 4c.2 What they explicitly do NOT cover

```text
run_chain.sh -> configuration resolution -> tuner construction
             -> sandbox_factory
```

That launcher wiring is untested by B-G1/B-G2, and the final report must
say so rather than let "real training ran" imply "the launcher passes
the right things".

### 4c.3 B-G3 — production launcher reachability (NEW, required)

**Operator decision 2026-08-02.** A separate gate before the D-B4
default flip. It first *audits* whether `run_chain.sh` can already pass:

```text
GPU identity
trial | formal posture
hardware policy (ceiling, quota, concurrency, telemetry)
measurement source
admission configuration
```

- **If reachable**: add tests and a bounded smoke, nothing more.
- **If not reachable**: add the missing wiring as **general
  configuration**, never a validation-only special case. A path that
  exists only for a gate proves nothing about production.

Known starting point, from the B-G audit: nothing currently sets
`admission_mode`, `measured_requirement_mib` or
`measured_requirement_provenance` — there is no constructor parameter,
CLI flag or config field. So B-G3 is expected to find the second case,
and the seam it adds belongs with D-B4 rather than inside a validation
run.

The intended shape:

```text
run_chain.sh
  -> one typed config
  -> tuner / sandbox_factory
  -> DeviceIdentity
  -> admission posture
  -> hardware policy
  -> measurement SOURCE
  -> admission gate
```

**The boundary that matters most (operator, 2026-08-02): do NOT add a
bare `--measured_requirement_mib`.** A flag taking a raw number would let
an operator type a figure that then impersonates an authoritative
measurement in formal mode — the estimate-as-fact defect this PR exists
to remove, re-entering through the CLI instead of through the code.

Instead PR B accepts a **measurement reference** carrying its source and
applicability. Until PR C exists, the production formal path resolves no
authoritative measurement and therefore refuses with
`policy_unavailable` — which is the correct answer, produced by the real
launcher. The validation fixture used by B-G1/B-G2 stays explicitly a
test input and never becomes a promotion channel.

So B-G3 can demonstrate exactly two things:

1. `run_chain.sh` carries posture, device identity and hardware policy
   through to the gate;
2. with no authoritative measurement available, formal cold start
   refuses **from the real launcher path**.

It cannot yet demonstrate `run_chain.sh -> formal permit`. That needs a
genuinely promoted measurement and therefore waits for PR C.

### 4c.3a B-G3 audit result — NOT REACHABLE, and the gate is inert

**Read-only audit, 2026-08-02, head `29c4a72`.** No production code was
modified. §4c.3 anticipated "the second case"; the audit confirms it and
finds something stronger.

#### The gate cannot refuse anything in production today

Not "is misconfigured" — *cannot*. Three independent reasons, any one
sufficient:

| Input | Production value | Consequence |
|---|---|---|
| `device_identity` | discovered from `hardware_context`; `None` on any host without a reported UUID | `_admission_refusal` returns `None` at `sandbox_executor.py:530-534` — **the whole gate is skipped** |
| `admission_mode` | **never set by anything** → `getattr(sandbox, "admission_mode", "trial")` (`:536`) | permanently `trial`, even during a formal round |
| `measured_requirements` | **never set by anything** → `getattr(..., None)` (`:489`) → `_phase_requirement` returns `(None, None)` | no requirement for any phase |

`trial` + no requirement lands on `admission.py:320-325`: admit, and
record that the guard asserted nothing. **So the production admission
gate has never refused a phase and, as wired, never can.**

This sharpens D-B4. Flipping a default to fail-closed presumes the gate
can reach a closed state; today there is nothing to flip. B-G3 is not a
polish step before D-B4 — it is what makes D-B4 mean anything.

#### Three defects found in passing (production, not PR B)

1. **`--is_trial` is dead.** `run_one_iteration.py:1557` reads
   `is_trial=args.is_trial or True` — unconditionally `True`, so the flag
   cannot express `False`. `run_chain.sh` never forwards it anyway
   (`_chain_common.sh` has no `is_trial` at all), and
   `submit_one_iteration.slurm:143` hardcodes it. Posture is decided
   entirely by `plan.is_trial` from the planner and `--force_formal_round`.
2. **The SDSC path silently discards unknown flags.**
   `submit_one_iteration.slurm:102` ends its case with `*) shift ;;`, so
   only the ~14 named flags survive; `--data_scope`, every runtime-control
   flag and `--trial_vram_budget_gb` are dropped on `--mode sdsc`. **Any
   new B-G3 flag would silently do nothing there.** Environment variables
   survive (sbatch `--export=ALL`), argv does not.
3. **`_admission_refusal` never passes `ceiling_gib`.**
   `evaluate_gpu_admission` accepts it (`admission.py:184`) but the call
   site (`sandbox_executor.py:555-562`) omits it, so the ceiling reaches
   the gate only through `os.environ`. `run_chain.sh` sets neither
   `SIDERIUS_PAIR_VRAM_CEILING_GIB` nor `SIDERIUS_GPU_VRAM_QUOTA_MIB`.

Also: this doc's §4c.3 names singular `measured_requirement_mib` /
`_provenance`. The code moved to a **per-phase mapping**
(`sandbox.measured_requirements` keyed `training`/`inference`) in
`e506349`, and B-G0 proved why — 1,476 vs 2,716 MiB. The typed boundary
is therefore three things, not two: posture, a **per-phase** measurement
reference, and hardware policy.

### 4c.3b B-G3 design — follow the `RuntimeControlPolicy` pattern

The repository already solved this exact problem for runtime control.
B-G3 should not invent a mechanism; it should copy the one that works
(`session.py:115`, wired `_chain_common.sh:296` → `run_one_iteration.py:948`
→ `hyperparam_tuning.py:1463` → `_build_runtime_policy` at
`ml_hyperparameter_tune_agent.py:2196` → validated at the executor,
`sandbox_executor.py:1073`):

```text
shell flag -> CLI arg -> typed schema field -> caller assembles a dict
           -> validated into a frozen Pydantic model AT the executor
           -> phase/posture resolved in the caller, provenance retained
```

**Proposed boundary — `GpuAdmissionPolicy`** (frozen Pydantic, in
`core/runtime_control/admission.py` beside the decision it configures):

```text
mode:                 Literal["trial", "formal"]     posture, resolved from plan.is_trial
measurement_source:   str | None                     a REFERENCE, never a number
ceiling_gib:          float | None                   hardware policy, today env-only
device_uuid:          str | None                     optional explicit pin
```

**The hard boundary, restated from §4c.3 and unchanged: no bare
`--measured_requirement_mib`.** `measurement_source` names *where an
authoritative measurement would come from*. Until PR C exists it
resolves to nothing, so formal refuses `policy_unavailable` — the
correct answer, produced by the real launcher. A flag carrying a raw
integer would let a typed figure impersonate a measurement, which is the
defect this PR removes.

Posture must be **derived, not re-entered**: `admission_mode` should come
from the same `plan.is_trial` that already drives the time gate and the
VRAM budget pick (`ml_hyperparameter_tune_agent.py:3384`). Adding a
second, independent posture flag would let the two disagree, and the
disagreement would be invisible.

#### What B-G3 must deliver

```text
1. GpuAdmissionPolicy, typed and frozen, validated at the executor boundary
2. posture derived from plan.is_trial and carried to the sandbox per phase
3. hardware policy as real configuration; _admission_refusal passes ceiling_gib
4. a per-phase measurement REFERENCE that resolves to nothing pre-PR-C
5. flags forwarded through BOTH launcher paths -- including the slurm case arm
6. a cold-start smoke on the real launcher proving formal -> policy_unavailable
   with no GPU child
```

Item 5 is not bookkeeping: without the slurm case arm the feature works
on lilab and silently vanishes on SDSC, which is worse than absent
because it looks present.

#### The smoke can cost zero LLM budget

The budget is 9/9 exhausted, and B-G3's demonstration does not need a
real planner. `--is_pseudo_llm` swaps **only** the LLM bridge
(`run_one_iteration.py:1363-1366`); `--is_pseudo_training` is what swaps
in `StubSandbox` (`:1367-1370`). They are independent. So:

```text
run_chain.sh --is_pseudo_llm   (WITHOUT --is_pseudo_training)
  -> StubLLMBridge, real TidmadSandbox, real admission gate
  -> formal posture, no authoritative measurement
  -> policy_unavailable, zero candidate GPU children, zero LLM calls
```

That is precisely the one thing §4c.3 says B-G3 can demonstrate, at no
budget cost. It must **not** use `--is_pseudo_training`: a stub sandbox
would bypass the gate under test and prove nothing.

#### Scope boundary

B-G3 adds general configuration, never a validation-only path, and may
not be satisfied by `setattr`, by test injection, or by the existence of
a working harness (§4d.3d). The three defects in §4c.3a are production
bugs found in passing — they should be filed and fixed on their own
merits, not folded into B-G3 silently.

### 4c.3c FU-B-16 — the SDSC launcher argument census

**Audited 2026-08-02.** The count is exact, not approximate: measured
against head `8a9548d`, `_chain_common.sh::build_app_args` forwarded
**39** application flags and `submit_one_iteration.slurm` named **14**,
so **35 were silently discarded**. A run configured on the command line
executed with different settings on SDSC than on lilab, and nothing in
the log said so.

**warn-and-drop was withdrawn** (operator, 2026-08-02). Making the loss
visible does not make the requested configuration arrive.

#### Ownership rule

```text
owned by this layer   -> consume
owned downstream      -> forward unchanged
deprecated            -> reject with migration guidance
unknown at Python     -> rejected, loudly
```

A shell wrapper must not need to know the application CLI. Layers own:

| Layer | Owns |
|---|---|
| `sbatch` / slurm headers | partition, account, wall time, nodes, GPUs, memory, logs |
| `submit_one_iteration.slurm` | nothing of the application CLI. It **peeks** `--workspace`, `--iteration`, `--source_paths` for its banner and manifest check, records the value, and still forwards the tokens |
| `_chain_common.sh` | campaign/queue orchestration, and assembling application argv |
| `run_one_iteration.py` | **the single authoritative validator.** `parse_args()`, so an unknown token fails with a nonzero exit naming it |

#### Current state

```text
application flags the chain can forward : 41
known to run_one_iteration.py           : 41 / 41
peeked by the wrapper (and forwarded)   : 3
dropped by the wrapper                  : 0
scheduler-only, never sent to Python    : --partition --time --mem --gpus --cpus
```

`--` forwards everything after it verbatim, including tokens the wrapper
would otherwise interpret, and is the unambiguous interface. Bare
forwarding is retained so existing invocations are unaffected.

Defaults are appended only when the caller supplied neither the flag nor
its `--flag=value` form, so a `run_chain.sh` value always wins while a
direct `sbatch` invocation keeps its previous behaviour.
`--no-is_trial` suppresses the `--is_trial` default.

`SIDERIUS_PAIR_VRAM_CEILING_GIB` remains a compatibility input to the one
resolver; the executor now receives the resolved value explicitly.

#### Full census

| argument | owner | SDSC before | SDSC now |
|---|---|---|---|
| `--advice` | application | **DROPPED** | forwarded |
| `--allow_extreme_steps` | application | **DROPPED** | forwarded |
| `--data_dir` | application | **DROPPED** | forwarded |
| `--data_scope` | application | **DROPPED** | forwarded |
| `--debug_dump_prompts` | application | **DROPPED** | forwarded |
| `--degenerate_penalty_score` | application | **DROPPED** | forwarded |
| `--enable_chain_incumbent_formal_gates` | application | **DROPPED** | forwarded |
| `--enable_structured_health_feedback` | application | **DROPPED** | forwarded |
| `--file_order_override` | application | **DROPPED** | forwarded |
| `--formal_eval_portion` | application | **DROPPED** | forwarded |
| `--formal_time_budget_minutes` | application | **DROPPED** | forwarded |
| `--formal_vram_budget_gb` | application | **DROPPED** | forwarded |
| `--gpu_admission_measurement_source` | application | **DROPPED** | forwarded |
| `--gpu_pair_ceiling_gib` | application | **DROPPED** | forwarded |
| `--health_checks_config` | application | **DROPPED** | forwarded |
| `--health_feedback_history_max_entries_per_model` | application | **DROPPED** | forwarded |
| `--health_feedback_history_window_iterations` | application | **DROPPED** | forwarded |
| `--health_gate_files` | application | **DROPPED** | forwarded |
| `--human_advice_file` | application | **DROPPED** | forwarded |
| `--is_pseudo_llm` | application | **DROPPED** | forwarded |
| `--is_pseudo_training` | application | **DROPPED** | forwarded |
| `--llm_config` | application | **DROPPED** | forwarded |
| `--max_steps_per_attempt` | application | **DROPPED** | forwarded |
| `--min_formal_batch_size` | application | **DROPPED** | forwarded |
| `--ml_lit_review_enabled` | application | **DROPPED** | forwarded |
| `--no-force_formal_round` | application | **DROPPED** | forwarded |
| `--no-health_gate_enabled` | application | **DROPPED** | forwarded |
| `--order_strategy_override` | application | **DROPPED** | forwarded |
| `--plan_overrides` | application | **DROPPED** | forwarded |
| `--reflect_model_id` | application | **DROPPED** | forwarded |
| `--reflect_provider` | application | **DROPPED** | forwarded |
| `--runtime_formal_safety_factor` | application | **DROPPED** | forwarded |
| `--runtime_safety_factor` | application | **DROPPED** | forwarded |
| `--runtime_trial_safety_factor` | application | **DROPPED** | forwarded |
| `--runtime_watchdog` | application | **DROPPED** | forwarded |
| `--runtime_watchdog_floor_seconds` | application | **DROPPED** | forwarded |
| `--runtime_watchdog_safety_factor` | application | **DROPPED** | forwarded |
| `--sampling_seed` | application | **DROPPED** | forwarded |
| `--seed_paths` | application | **DROPPED** | forwarded |
| `--trial_time_budget_minutes` | application | **DROPPED** | forwarded |
| `--trial_vram_budget_gb` | application | **DROPPED** | forwarded |


#### Validation performed

Deterministic only. 29 tests drive the **real** parse and default-fill
blocks sliced out of the shipped script — argv preservation (value
flags, boolean flags, `--flag=value`, negative numbers, paths with
spaces, quoted strings, repeated flags, order), the peek-not-consume
property, default gap-filling, `--`, and lilab/SDSC parity. A census
test asserts every flag `build_app_args` can emit survives, and a parity
test asserts every forwarded flag is known to the Python parser.

Five mutation proofs: restoring `*) shift ;;` fails 18 tests, dropping a
forwarded value fails 11, consuming `--workspace` instead of peeking
fails 1, removing `--` fails 1, letting a default override an explicit
value fails 2.

**No SDSC cluster job was submitted.** Parity is established by argv
equivalence and shared parser resolution, not by a live Expanse run —
that remains an external execution decision.

**FU-B-16 is closed**: every current argument is classified, and the
silent-drop branch is gone.

### 4c.3d B-G3 — PASS (production launcher reachability)

**2026-08-02, `bg3_v2`,** head `ef8af29` (exact-head CI green, clean
tree). Evidence: `bg3_evidence_20260802_run2/`.

```text
launcher            run_one_iteration.py (real path, --is_pseudo_llm)
sandbox             real TidmadSandbox (NOT --is_pseudo_training)
posture             formal, derived from --no-is_trial -> plan.is_trial
device UUID         GPU-c30b6678-... propagated from hardware discovery
reason_code         policy_unavailable
requirement_mib     None (provenance None)
candidate children  0  -- 253 NVML samples, all NO_COMPUTE_APPS
device              273 MiB flat, first == last
artifacts           no checkpoint, no denoised output
LLM calls           0
```

The refusal carries the anti-blame wording and no shrink advice. **The
real launcher path reached the real gate and refused**, which is the one
thing §4c.3 says B-G3 can demonstrate before PR C.

**First attempt INCONCLUSIVE — smoke configuration, not a gate result.**
`bg3_evidence_20260802/`: every attempt was skipped by the §5 guardrail
(`formal batch_size 1 below min_formal_batch_size 4`) *before* admission,
so the gate was never reached — "iteration ended without ever training".
An unrelated pre-flight guardrail pre-empting the path under test is a
harness setup error, and the rerun set `--min_formal_batch_size 1`. No
other parameter changed and both runs are preserved.

#### One limitation, stated rather than glossed

**Ceiling propagation is proven deterministically, not by this record.**
A `policy_unavailable` refusal short-circuits before the ceiling enters
any arithmetic, and `AdmissionDecision.evidence` carries no `ceiling_gib`
key at all, so the run's own artifact cannot show which ceiling applied.
The launcher-to-gate hop is covered by unit tests
(`test_the_gate_passes_the_configured_ceiling`,
`test_parsing_a_ceiling_yields_a_float`) and the census tests, but a
future `insufficient_headroom` refusal would still not record the
ceiling it was judged against. Filed as **FU-B-17**.

Attempt count was 5, not 1: `attempts_per_formal_round` defaults to 5 and
the smoke did not pin it. Harmless here — every attempt refused
identically and none reached the GPU — but the B-G2 scenarios pin it and
this one should too if repeated.

### 4c.3e Enforcement is separate from posture (operator decision, 2026-08-02)

B-G3 made the consequence concrete: once the gate is reachable, **every
formal round refuses `policy_unavailable`**, because PR C — which would
supply the authoritative measurement — does not exist yet. Merging PR B
with enforcement active would stop formal training repository-wide in
the interval between the two PRs.

**The rejected alternative was mapping a formal round to `trial`** to
keep it running. That would make every record claim a posture the round
did not have. Provenance that lies is worse than a guard that does not
fire.

So enforcement became its own axis:

```text
phase        = trial | formal          -- what the round IS
enforcement  = observe_only | enforce  -- what we DO about a refusal
```

| | `observe_only` (compatibility default) | `enforce` |
|---|---|---|
| gate runs | yes | yes |
| decision produced | real | real |
| adverse decision | recorded as `would_refuse`, phase proceeds | phase stops, no GPU child |
| posture in the record | unchanged (`formal` stays `formal`) | unchanged |
| shrink advice | never | never |

**Enforcement comes only from the typed policy.** The legacy duck-typed
path — a bare `admission_mode` attribute, which is how the B-G harness
injects posture — keeps enforcing, because B-G1/B-G2 are evidence about
*that* path. A first implementation defaulted it to `observe_only` and
29 tests failed: it would have silently disarmed the gate for every
harness scenario while the suite still looked green.

An unrecognised enforcement value is **rejected**, never resolved:
mapping it to `observe_only` would disable a guard the operator asked
for, and to `enforce` would stop work they did not ask to stop.

After PR C supplies authoritative measurements, formal V20 configuration
must set `enforce` explicitly. Whether the repository-wide default also
moves is a separate, separately-validated production-default decision.

### 4c.3f D-B4 — pair-cap oversubscription denied by default

`ALLOW_PAIR_CAP_OVERSUBSCRIPTION:-1` meant "allow unless told
otherwise", so an infeasible pair launched and the host watchdog noticed
first — during C12 it did, and what it produced was a kill. Both
launchers now default to `:-0`.

```text
default              -> denied, disposition pair_infeasible_under_host_quota
explicit override    -> allowed, announced in four lines,
                        PAIR_OVERSUBSCRIPTION_OVERRIDE recorded
formal V20 Gate      -> override REFUSED,
                        pair_oversubscription_override_forbidden_in_gate
```

The Gate forbids it because a Gate run exists to produce a comparable,
defensible result; one that knowingly oversubscribes the host is
neither, and allowing it there would mean the strictest context in the
project had the weakest guarantee.

Unchanged and pinned by tests: the 28 GiB pair ceiling, the host-quota
variable, and the per-chain caps. D-B4 moves one default, not capacity.

### 4c.4 Condition on the default flip

```text
B-G1/B-G2 pass
+ B-G3 launcher reachability passes
-> only then may D-B4 fail-closed be considered
```

Strictly stronger than D-B4's original text, which required B-G2 alone.

---

## 4d. B-G1/B-G2 execution package — EXECUTED, ALL SCENARIOS PASS

Written against head `885ed33` (CI green, clean tree). **Revised
2026-08-02 after operator review.** **All four scenarios have now been
run** — B-G0 measurement pass (§4d.3g), B-G1 PASS (§4d.3i, after one
inconclusive harness-defect run, §4d.3h), B-G2a PASS (§4d.3k, after one
inconclusive attempt-budget run, §4d.3j), B-G2b PASS (§4d.3l). LLM
budget 9/9 exhausted. **B-G3 still blocks D-B4.**

### 4d.0 Two corrections to the first draft

**(1) B-G1 must run in `formal`, not `trial`.** The first draft used
`trial`, which admits when no measurement is available. So a B-G1 in
which the fixture never reached admission at all would still have
started training and been recorded as a pass — proving nothing about
whether the measurement was used. In `formal` a missing or inapplicable
fixture **refuses**, so the run cannot pass vacuously. B-G1 and B-G2a
then form a controlled pair differing only in whether the fixture is
present.

**(2) A validation-only 6 GiB ceiling, not the production 28 GiB.**
Verifying a protection mechanism by pushing the machine toward the limit
it protects is backwards: had the gate failed with a 17 GiB holder plus
wavenet, real occupancy would have reached ~29-30 GiB, close to the host
quota. Using PUNet against a lowered ceiling keeps worst-case occupancy
at ~7 GiB while testing exactly the same code path.

> **The 6 GiB ceiling is validation-only.** It exercises generic
> admission behaviour and neither changes nor validates the production
> `28.0` GiB default. Production configuration and launcher wiring are
> **B-G3 / D-B4's** subject, not this run's.

Set with **no code change**, via the existing override
(`pair_admission.py:52`):

```bash
export SIDERIUS_PAIR_VRAM_CEILING_GIB=6.0
```

### 4d.1 What this package does NOT cover

```text
run_chain.sh -> configuration resolution -> tuner construction
             -> sandbox_factory
```

These scenarios enter **below** the launcher. **B-G3 remains required
before D-B4** (§4c.3). "Real training ran" never means "the launcher
passes the right things".

### 4d.2 Step 0 — the validation script

The A5/A6 invocations call the tuner CLI, which constructs
`HyperparamTuningAgent()` with **no `sandbox_factory`**, so the CLI
cannot carry a fixture and no production field exists for one (§4c.3).

`scripts/bg_admission_validation.py` — **development, tests and CI
approved; GPU/LLM execution NOT yet approved.** It must:

- construct a real `HyperparamTuningAgent` and a real `TidmadSandbox`
- inject the fixture only through the existing sandbox consumer boundary
- stamp `validation_only=true`
- **never**: `StubSandbox`, monkeypatch the gate / executor /
  `subprocess`, create a registry, promote anything, or be reachable
  from `run_chain.sh` or a real campaign

### 4d.3 The fixture, and its exact-match precondition

| Field | Value |
|---|---|
| `requirement_mib` | **3,076** (PUNet training, A5 driver-visible, `pr_a…md:1828`) |
| `provenance` | `"measured"` |
| candidate | `punet`, A5 normalized config |
| phase | training |

**Checked BEFORE any GPU child starts**, against the candidate the
planner actually produced:

```text
normalized config hash · task identity · dataset/data-shape identity
· phase · batch size · segmentation size · GPU UUID
· measurement type · source workspace/artifact
```

Any mismatch → **INCONCLUSIVE**, no GPU child, **no re-planning and no
retry**. A shared model name is not applicability.

> The fixture is a **test input**, not a PR C promotion. It never enters
> a registry and never becomes an authoritative record.

### 4d.3b Harness implemented — and a gap it exposed

**Landed `e0d65ce`** (development/tests/CI only; no GPU, LLM or holder
has run). `scripts/bg_gpu_holder.py`,
`scripts/bg_admission_validation.py`, 41 synthetic tests, 5 mutation
proofs, `tests/unit` 6,433 passing.

#### The A5 fixture's real provenance — corrected

The path this document previously cited does **not exist**. Verified on
disk 2026-08-02:

| | |
|---|---|
| run workspace | `/home/klz/Data/SIDEREIS_DATA/a5_preflight_lifecycle_v1` |
| analysis artifact | `/home/klz/Data/SIDEREIS_DATA/a5_evidence_v2_20260801/analysis.txt` |
| recorded figure | `training peak 3076 MiB (59 samples)`; tree aggregate 3,076 MiB |
| config hash | `690878ab5c7d15eceab35ae431976031e65df8b6ff41f506869b0b30f236ac3b` |
| this host's GPU | `GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef`, RTX 5090, 32,607 MiB, **count = 1** |

#### The gap: A5 recorded no GPU UUID

`a5_preflight_lifecycle_v1_hardware.json` records per device only
`compute_capability, logical_index, name, total_memory_bytes`. **There is
no `uuid` field** — UUID recording was added in `a8d7824` (B-C2b),
*after* A5 ran.

So binding the fixture to `GPU-c30b6678-…` is an **inference** from
"same host, single GPU, same model", not a recorded fact. The inference
is strong. It is still an inference, and §4d.3 requires GPU UUID as an
applicability field precisely so that strong inferences are not accepted
in place of records — the same reasoning that rejects a shared model
name.

**This is the applicability rule finding its first real subject.** The
first attempt to *use* a historical measurement under it revealed that
the historical measurement lacks a required field. That is the rule
working, and it is worth recording as a general lesson: evidence
predating a provenance requirement does not retroactively satisfy it.

#### Options, for operator decision

| | Cost | Consequence |
|---|---|---|
| **(a)** accept the UUID binding as a labelled inference | none | B-G1's demonstration rests partly on an assumption the rule exists to forbid |
| **(b)** re-measure PUNet on the current UUID first | one short run | the fixture becomes fully recorded evidence, and the bring-up sequence is exercised on known hardware before the real cross-hardware move |

**Recommendation: (b).** B-G1's claim is "an applicable measurement
admits"; starting from a fixture whose applicability is partly assumed
weakens exactly what is being demonstrated.

> **DECIDED (operator, 2026-08-02): (b).** The A5 data stays as
> historical reference but **may not serve as the exact-match fixture**.
> A new bounded measurement is taken on the current UUID first.

### 4d.3c B-G0 — refresh the validation measurement (NEW prerequisite)

A bounded prerequisite, ahead of B-G1. It also rehearses the H100
bring-up sequence on known hardware — though its **result applies only
to this 5090 UUID** and carries nothing across to another card.

**Requirements:**

- same PUNet configuration and short-run shape as A5
- the GPU must be idle at start
- **exactly one run** — no parameter tuning, no automatic retry
- record the **actual** GPU UUID, not an inferred one
- record normalized config hash, phase, batch/segment, task, data shape
- record the driver-visible training **and** inference peaks
- save exact artifact and evidence paths
- stamp `validation_only=true`
- **no registry write, no promotion, no claim that PR C is satisfied**

**Sequence:**

```text
B-G0   refresh the measurement on this UUID
  ->  B-G1   formal permit
  ->  B-G2a  formal cold-start refusal
  ->  B-G2b  controlled-holder refusal
```

B-G0 produces a *validation fixture*, not an authoritative record.
Acquisition, applicability validation and promotion remain PR C's, and
running B-G0 does not shorten that.

### 4d.3d `_ValidationSandbox` — and what CI proved about B-G3

Strict pyright rejected the harness's first form, and the rejection was
substantive rather than stylistic:

```text
pyright:  cannot assign to attribute "admission_mode" —
          TidmadSandbox declares no such attribute
ruff B010: do not call setattr with a constant attribute name —
          use assignment
```

The two checkers disagreed about the mechanism and agreed about the
cause: **a value being set needs somewhere declared to live, and
production has nowhere.** The first repair silenced B010 with `noqa`,
which breaks the standing no-lint-bypass rule; it was replaced.

The harness now uses `_ValidationSandbox(TidmadSandbox)`, which
**declares** the three admission fields and **overrides nothing**. Every
phase still runs the production class's own code. Two tests make that
checkable rather than claimed:

- the subclass adds no methods and declares exactly
  `admission_mode`, `measured_requirement_mib`,
  `measured_requirement_provenance`;
- those fields are **absent** from production `TidmadSandbox` — adding
  them there is B-G3's work, and doing it from a validation harness
  would create the validation-only production entry point B-G3 exists to
  prevent.

**What this establishes about B-G3.** Production `TidmadSandbox` has no
typed admission-configuration boundary. That conclusion has now been
reached three independent ways on this branch — by the pre-B-G audit
(`grep` found no setter anywhere), by strict pyright (twice, on
different code), and by ruff. B-G3 must build that boundary properly. It
may not be satisfied by dynamic `setattr`, by test injection, or by the
existence of a working validation harness.

> **The harness running is not launcher reachability.**
> `_ValidationSandbox` exists solely for PR B's real validation. It is
> not a configuration entry point, `run_chain.sh` cannot reach it, and
> no result obtained through it may be reported as evidence that the
> launcher can drive admission.

### 4d.3e Two operational facts worth keeping

**PR 3's preflight requires a clean working tree.**
`scripts/pr3_l2_calibration/preflight.py:287-299` runs
`git diff --name-only` and refuses anything outside
`scripts/pr3_l2_calibration/`, `tests/`, `docs/`, `reports/` that is not
a `.md`. It allowlists by **path prefix**, so it cannot tell a
validation-only script under `scripts/` from a production one:

```text
uncommitted edit to scripts/bg_admission_validation.py
  -> no_production_file_modified fails
  -> commit -> passes
```

Confirmed by committing and re-running rather than by reasoning about
it. **This is the guard working** — it exists to stop a calibration run
against an uncommitted tree — and it is a known operational constraint,
not a defect in either the check or the harness. Anyone running a sweep
mid-edit will see it and should not "fix" it.

**B-G3's necessity is now established by evidence, not by plan.**
Production `TidmadSandbox` has no typed admission-configuration
boundary, reached three independent ways on this branch:

| Route | Finding |
|---|---|
| pre-B-G audit | `grep` found no setter for `admission_mode` or the measurement fields anywhere |
| strict pyright (twice) | cannot assign an undeclared attribute; `Any` reaching a `Literal` parameter |
| ruff B010 | `setattr` with a constant name is not safer than assignment |

`_ValidationSandbox` does **not** close that gap and must never be cited
as if it had. It is validation-only, unreachable from `run_chain.sh`,
and pinned by a test asserting the fields stay off the production class.

### 4d.3f Package corrected — three findings (operator review, 2026-08-02)

#### (1) B-G0 must be `trial`, not `formal` — it would have refused itself

The package had B-G0 running `formal` with no fixture. By the frozen
rule that is a **refusal**:

```text
formal + no authoritative measurement -> policy_unavailable -> no GPU phase
```

So B-G0 could never have produced the measurement it exists to collect.
A scenario that refuses itself.

**Corrected**: B-G0 runs **`trial`** — no fixture, idle GPU, one bounded
run, proceeding with a recorded warning and collecting the raw
measurement. Only B-G1, B-G2a and B-G2b use `formal`.

#### (2) 3,076 MiB is a planning reference, not a B-G0 result

The package stated the requirement as "from B-G0, not A5". **B-G0 has
not run.** Until it does, 3,076 MiB is A5's figure used for *planning*,
and no execution parameter may be derived from it as though measured on
this UUID.

The holder floor is therefore **computed after B-G0**, from its actual
result `R`:

```text
holder conclusive floor = 6,144 MiB - R
holder measured occupancy must be strictly greater
```

Only if B-G0 happens to reproduce `R = 3,076` does the floor become
3,068. **That must not be assumed.**

#### (3) NEW FINDING — admission resolves one requirement for both phases

`_admission_refusal(sandbox, *, phase)` takes `phase` for its message
and then reads a **single** `measured_requirement_mib`
(`sandbox_executor.py:519`) for both the training and the inference
gate.

A5 measured **training 3,076 MiB** and **inference 2,716 MiB** — a 13%
difference. So a run supplying one figure has the inference gate judged
against the training requirement, which is exactly the applicability
conflation §4d.3 forbids: a measurement of one phase answering for
another.

This is a **production gap in B-C4b**, not a harness bug. Neither the
audit nor strict pyright caught it, because it is semantic rather than
structural — the types are fine; the meaning is not.

Consequences to decide before B-G1:

| Option | Effect |
|---|---|
| per-phase requirement resolution in the gate | correct, but a production change — B-C4b/B-G3 territory |
| supply only a training fixture and accept the inference gate is judged on it | B-G1's permit would rest on the conflation the rule forbids |
| scope B-G1 to the training gate only | narrower claim, no production change, honest |

**Not chosen here.** B-G0 collects **both** peaks regardless, so the
decision can be made on real numbers.

#### Two-stage approval

```text
Stage 1 (seeking approval): B-G0 only
  trial, one bounded PUNet run, idle GPU
  -> returns this UUID's training AND inference measurements + fixture

Stage 2 (separate approval, after Stage 1's numbers):
  freeze holder floor/target from R
  -> B-G1 / B-G2a / B-G2b
```

The four scenarios are **not** launched as one sequence.

### 4d.3g B-G0 RESULT and the revised Stage 2 package

**B-G0 MEASUREMENT PASS** (2026-08-02, `bg0_measure_v2`).

| Phase | Driver-visible peak | Samples | Window |
|---|---|---|---|
| training | **1,476 MiB** | 77 | 9.9 s |
| inference | **2,716 MiB** | 15 | 1.8 s |

Cleanup to the 273 MiB baseline; no orphaned children. UUID
`GPU-c30b6678-ff2a-f8b4-d378-af9681c6ceef`. Config sha256
`944f9aaa5522…`. Fixture: `bg0_evidence_20260802/bg0_fixture.json`.

**Precision on "parent 0 MiB"** (corrected 2026-08-02 after an evidence
audit). The tuner parent (PID 2605432) never appears in NVML's
compute-app table, which is sound evidence that it held no device
memory. But it is *absence* evidence, not a labelled measurement: the
sampler classifies the parent by matching `ml_hyperparameter_tune_agent`
in `/proc/<pid>/cmdline`, and this run was launched as
`scripts/bg_admission_validation.py`, so **no `P0_TUNER_PARENT` sample
exists in the CSV at all.** The claim stands; the phrasing "measured 0
MiB" would not. Worth fixing in the sampler before B-G2.

The run ended `failed_mode_collapse` (19 unique int8 values against a
>25 diversity threshold). That does not affect the memory measurement —
both phases genuinely executed and were sampled — but **this run must
not be described as a successful scientific result.**

#### What B-G0 proved beyond its own numbers

**A5 measured 3,076 MiB for the same model name; B-G0 measured 1,476.**
Same host, same flags, same architecture — the planner chose a different
configuration, and the training requirement differed by **2.1x**. The
applicability rule is not a formality; a model name carries no
information about memory.

And measuring **both** phases exposed a production defect no static
check could see: admission read one requirement for both gates, so each
phase was judged by a measurement of the other (1.8x apart). Fixed in
`e506349`. The types were correct; the meaning was not.

#### Stage 2 — FROZEN

All `formal`, all PUNet, `SIDERIUS_PAIR_VRAM_CEILING_GIB=6.0`,
configuration pinned by full-group `plan_overrides` from B-G0's fixture.

| | Fixture | Holder | Expected |
|---|---|---|---|
| **B-G1** | exact match, both phases | none | training reads 1,476, inference reads 2,716, **both phases start** |
| **B-G2a** | none | none | `policy_unavailable`, no GPU child |
| **B-G2b** | exact match | measured **> 4,668**, target ~5,200, max 8,000 | training refused **before launch**, `insufficient_headroom`, no candidate child |

Holder floor derivation: `ceiling 6,144 - training 1,476 = 4,668`. The
earlier 4,000 target would have left the pair *under* the ceiling — an
inconclusive scenario that would have looked like a passing one.

### 4d.3h B-G1 first run — INCONCLUSIVE, VALIDATION HARNESS DEFECT

**2026-08-02, `bg1_permit_v1`.** Evidence:
`/home/klz/Data/SIDEREIS_DATA/bg1_evidence_20260802/`. Preserved
unchanged.

```text
PR B failure:        no
candidate failure:   no
admission failure:   no
config pinning:      confirmed working
GPU phase launched:  no
automatic rerun:     no
```

**What happened.** The validation precondition read `model_config` /
`train_config` / `loss_config` from the phase arguments. Those are the
*skill wrapper's* key names; the wrapper renames them to `m_cfg` /
`t_cfg` / `l_cfg` before calling the sandbox
(`agent/skills/training_skill/wrapper.py:5-23`). So the precondition got
`None` for all three and hashed `43d64649bd9c9f99` — the digest of
`{model_config: None, train_config: None, loss_config: None}` — on every
attempt. **A guard that refuses everything, which is as worthless as one
that accepts everything and harder to notice because it looks strict.**

**Config pinning demonstrably worked.** All three attempt records carry
config hash `944f9aaa55221106`, byte-identical to the B-G0 fixture, and
the three preflight specs agree (`realized_parameter_count 6762568`,
matching B-G0). `plan_overrides` reproduced the frozen configuration
exactly. The refusal was a false negative.

**A second defect, exposed by the first.** The harness returned an
ordinary `status="error"`, which `_run_skill`'s `except Exception`
(`ml_hyperparameter_tune_agent.py:1592`) converts into a retryable
training failure. The run therefore **re-planned three times** — three
fresh LLM calls — into `max_fail_rounds=3`, violating this section's own
"no re-planning, no retry". No production retry policy was wrong; the
harness had borrowed the training-error contract for something that is
not a training error.

**What the run does and does not establish.** Zero GPU children (814
NVML samples, all `NO_COMPUTE_APPS`; device pinned at 273 MiB for the
whole run; no sentinel, no denoised artifact; the only children were
three preflight workers holding no device memory). So the "no candidate
child" property held. But the exact-config gate was **never exercised**,
because it never read a real config — this run is not evidence that the
gate works.

#### Repair (validation-only)

| Defect | Fix |
|---|---|
| wrong parameter names | `PHASE_GROUPS` pinned to `inspect.signature` of the real methods |
| one digest for both phases | per-phase, per-group comparison; inference never asked for `t_cfg` |
| all-`None` hashed | absent group raises `HarnessError`; never normalized into a digest |
| `{}` treated as absent | `is None`, not falsiness — `{}` was supplied and is compared |
| mismatch retried | `ConfigMismatch`/`HarnessError` derive from `BaseException`, so `except Exception` cannot swallow them |
| phantom diff in evidence | `phase_config_diff` restricted to the phase's own groups |

No production file changed. Each fix carries a mutation proof (reverting
it fails 1, 3, 8, 1, and 1 test respectively).

### 4d.3i B-G1 rerun — PASS

**2026-08-02, `bg1_permit_v2`.** Evidence:
`/home/klz/Data/SIDEREIS_DATA/bg1_evidence_20260802_run2/`. Run at head
`4699c59` (exact-head CI green, clean tree).

```text
verdict:             PASS
admission:           permitted, both phases started
config pinning:      exact — 944f9aaa55221106
attempts:            1 (no retry, no re-planning)
candidate children:  before [] · after []
device:              273 MiB before and after
```

| Phase | Peak | Samples | Window | PID | B-G0 |
|---|---|---|---|---|---|
| training | **1,476 MiB** | 79 | 9.9 s | 2980899 | 1,476 ✓ |
| inference | **2,716 MiB** | 15 | 1.8 s | 2983085 | 2,716 ✓ |

Two independent runs agreeing to the MiB on both phases. The realized
config is `==` equal to the fixture group-by-group, so the repaired
precondition compared real values and permitted where the broken one
hashed three `None`s and refused. One planning cycle, one LLM call.

The run ended `failed_mode_collapse` (20 unique int8 values against the
>25 threshold), the same collapse as B-G0. Scientific output quality;
it does not bear on the admission result, and **this is not a
successful scientific run.**

Parent occupancy, stated precisely: the tuner parent (PID 2977940) never
appears in the NVML compute-apps record, so its driver-visible occupancy
was 0. The sampler emitted no `P0_TUNER_PARENT` role label — see
FU-B-15, now closed.

#### Two evidence gaps this run exposed, fixed before B-G2

Neither is a defect in admission, and neither invalidates B-G1.

1. **The permit path was silent.** Production logs only refusals, so
   "admitted" rested on the *absence* of a refusal — and a gate that
   never ran would look identical. The harness now calls production's
   own `_admission_refusal` and records `gate_evaluated`,
   `admission_result`, `reason_code`, `requirement_mib` and its
   provenance. It is recorded honestly as a **second** evaluation taken
   immediately before the production call, not as that call's return
   value.
2. **`realized` was stored only on mismatch.** The PASS above had to be
   confirmed by recomputing the hash from the experiment record
   *outside* the harness. Expected and realized configs, both hashes and
   the per-group diff are now written on every path, with a matching
   diff written as an explicit `{}` — absent and empty must not look
   alike.

**B-G1 is not re-run for these.** They change what future runs record,
not what this one did.

> **What B-G1 does and does not establish.** It shows the gate permitted
> a candidate whose measurement covers it, that both phases started, and
> that the per-phase requirements are the ones B-G0 measured. It does
> **not** by itself show the gate is deciding rather than defaulting —
> **B-G2a is the control for that**, which is why the two form a pair.

### 4d.3j B-G2a first run — INCONCLUSIVE, VALIDATION ATTEMPT-BUDGET DEVIATION

**2026-08-02, `bg2a_v1`.** Evidence:
`/home/klz/Data/SIDEREIS_DATA/bg2a_evidence_20260802/`. Preserved.

Not a PR B failure and not a candidate failure. The substantive
admission behaviour was correct on every axis:

```text
formal, no fixture loaded    gate_evaluated = true
reason_code                  policy_unavailable
requirement_mib              None
candidate GPU children       0  (1,609 NVML samples, all NO_COMPUTE_APPS)
device                       274 MiB flat, 161 samples
artifacts                    no checkpoint, no sentinel, no denoised output
candidate blame              none
```

The refusal record reads *"This is a statement about the machine at this
moment, NOT about the candidate. It is not evidence that the model was
too large"* and *"Do NOT reduce model capacity, batch size or
segmentation size in response to it."* The planner then **obeyed it**:
its round-3 reasoning cites the memory update and retains the
configuration. B-C3b's guard is load-bearing, not decorative.

**The deviation.** The harness left `max_fail_rounds` at production's
default of 3, so the scenario consumed **three attempt slots and three
planning calls** to re-derive one deterministic `policy_unavailable`. A
refusal is a statement about the machine; retrying is right for a
campaign, where the environment can change between rounds, and
meaningless inside a scenario whose purpose is to hold it fixed.

Corrected by pinning `max_fail_rounds=1` in the harness input — a
per-run value, not a default change. Production keeps 3
(`hyperparam_tuning.py:1058`, pinned by a test). Mutation proof:
removing the line fails the one-attempt test, and
`_compute_termination_state` at `max_fail_rounds=3` does not abort after
one failure, which is exactly why the first run retried.

### 4d.3k B-G2a rerun — PASS

**2026-08-02, `bg2a_v2`,** head `97bcbaf` (exact-head CI green, clean
tree). Evidence: `bg2a_evidence_20260802_run2/`.

```text
attempt count            1          LLM calls              1
gate_evaluated           true       admission_result       refused
reason_code              policy_unavailable
requirement_mib          None       provenance             None
candidate children       0          NVML samples           462, all NO_COMPUTE_APPS
device                   274 MiB flat (47 samples, first == last)
checkpoint/sentinel/h5   none       shrink advice          none
```

`fixture: None`, `expected_config: None` — the gate refused with no
measurement to consult, which is the point of the scenario.

**This is the control B-G1 could not supply.** B-G1 alone cannot
distinguish "the gate evaluated and permitted" from "the gate was
bypassed and the phase happened to start". B-G2a differs from B-G1 in
exactly one input — whether a fixture is present — and produces a
refusal with a recorded witness. Together they show the gate is
**deciding**, not defaulting.

### 4d.3l B-G2b — PASS

**2026-08-02, `bg2b_v1`,** same head. Evidence:
`bg2b_evidence_20260802/`.

```text
holder measured          5,360 MiB  (window 5,000-6,000, floor >4,668, max 8,000)
arithmetic               5,360 + 1,476 = 6,836 MiB = 6.68 GiB  >  6,144 MiB = 6.00 GiB
refusal message          "6.68 GiB predicted against a 6.00 GiB effective
                          ceiling - short by 0.68 GiB"
gate_evaluated           true       admission_result       refused
reason_code              insufficient_headroom
requirement_mib          1,476      provenance             measured
config match             realized == expected == 944f9aaa55221106, config_diff {}
attempt count            1          LLM calls              1
holder lifetime          600.6 s, self-released (see note)
device                   273 -> 5,638 -> 273 MiB (599 samples, first == last)
```

The requirement used is the **training** figure, 1,476 MiB, not
inference's 2,716 — the per-phase resolution from `e506349` working on
real hardware.

**Deviation, recorded not re-run.** The holder released at **600.6 s**
against a written `<= 600 s` bound. The overshoot is 0.6 s and is
consistent with sampling granularity and teardown timestamping rather
than a late release: the deadline is checked between allocation-loop
iterations, so the recorded `held_seconds` includes the final check and
free. It does not affect the memory-safety conclusion — the card
returned to its 273 MiB baseline and no candidate child ever existed —
and re-running to chase 0.6 s would spend LLM budget for no scientific
gain. Operator decision 2026-08-02: record and proceed.

**Three independent no-child proofs, as required:**

1. **`/proc` attribution** — `candidate_gpu_children()` empty before and
   after; the only children the run spawned were preflight workers.
2. **NVML PID attribution** — 5,881 samples across the whole scenario,
   and the set of PIDs ever holding device memory is exactly
   `{3392491}`, the holder. Every one of those rows is labelled `HOLDER`
   by registered PID, zero mislabelled — the FU-B-15 fix is what makes
   this a positive identification rather than an inference from a
   command-line guess.
3. **Artifact absence** — no checkpoint, no sentinel, no denoised HDF5.

The refusal carries the anti-blame wording and no shrink advice: *"This
is a statement about the machine at this moment, NOT about the
candidate"*, *"Do NOT reduce model capacity, batch size or segmentation
size."*

#### B-G2 cost and the frozen limits

```text
first B-G1 (harness defect)   3        first B-G2a (attempt-budget)   3
B-G1 rerun                    1        B-G2a rerun                    1
                                       B-G2b                          1
                                       ----------------------------------
                                       total                          9 / 9
```

Budget exactly exhausted. No further B-G scenario may run without new
authorization.

**What B-G1 + B-G2a + B-G2b establish together:** admission permits when
an applicable measurement covers the candidate, refuses
`policy_unavailable` when none exists, and refuses
`insufficient_headroom` when the device genuinely cannot hold the phase
— each with a recorded witness, each before any candidate child, each
without blaming the candidate.

**What they do not establish:** that `run_chain.sh` can drive any of
this. Every scenario entered below the launcher through the
`sandbox_factory` seam. **B-G3 remains required before D-B4**, and the
harness running is not launcher reachability.

#### Three preconditions, verified separately

1. **Config identity** — the *realized* config groups compared against
   the fixture **per group and per phase**, at GPU-phase entry, after
   the planner, after `plan_overrides`, after the `max_epochs` clamp.
   Observed, not predicted from the override dict.

   **Corrected 2026-08-02 (first B-G1, §4d.3h).** This previously read
   "sha256 of the realized `model_config` / `train_config` /
   `loss_config`" — a single whole-config digest over three fixed
   groups. That is phase-incorrect: `execute_inference` takes `m_cfg`
   and `l_cfg` but **no** `t_cfg` (`core/sandbox_executor.py:1339`), so
   the inference gate can never see a train config and must never be
   asked to match one. Training compares `m_cfg`/`t_cfg`/`l_cfg`;
   inference compares `m_cfg`/`l_cfg`. A digest can only say
   "different"; per-group comparison says *which*, which is what the
   evidence file needs. A phase-scoped digest is still recorded, but it
   is not the decision.

   A group that was never supplied is a **harness** fault, not a
   mismatch: it aborts with `HarnessError` rather than being normalized
   into a hash. A group supplied as `{}` was supplied, and is compared.
2. **Applicability** — task, data-shape class, phase, GPU UUID and
   measurement type checked independently. **A matching hash is not
   applicability.**
3. **Phase-specific requirement** — training and inference resolved
   separately, with no cross-phase fallback and no substitution of the
   larger figure.

Any mismatch → **INCONCLUSIVE**, zero GPU children, no re-planning, no
retry.

> **Scope, restated.** The exact-hash gate is a `_ValidationSandbox`
> precondition. It is **not** a `run_chain.sh` capability and does not
> substitute for **B-G3**, which still blocks D-B4.

### 4d.4 Preconditions (before every scenario)

```bash
nvidia-smi --query-compute-apps=pid,used_gpu_memory,gpu_uuid --format=csv   # header only
nvidia-smi --query-gpu=uuid,memory.used,memory.total --format=csv          # ~273 MiB baseline
pgrep -af "train_engine_sandbox.py|inference_single.py|preflight_worker_main|bg_gpu_holder"
```

Any occupant or survivor → **INCONCLUSIVE, do not start.**

### 4d.5 The three scenarios

All `formal`, all PUNet, all with `SIDERIUS_PAIR_VRAM_CEILING_GIB=6.0`.
**The only variable across B-G1 and B-G2b is `other_mib`.**

Arithmetic below uses B-G0's **measured** training requirement of 1,476
MiB. It previously used A5's 3,076 MiB estimate for the same model name;
§4d.3g supersedes that, and the 2.1× gap is exactly why the holder floor
moved (see §4d.6).

| | Fixture | Holder | Arithmetic | Expected |
|---|---|---|---|---|
| **B-G1** | yes | none | `1,476 < 6,144` | **admitted**, one real training + inference |
| **B-G2a** | **no** | none | n/a | `policy_unavailable`, no GPU child |
| **B-G2b** | yes | >4,668 MiB | `4,668 + 1,476 = 6,144` — holder must exceed this | `insufficient_headroom`, no GPU child |

Worst case if the gate failed entirely: ~7 GiB occupancy — far from the
host quota. That is the point of the lowered ceiling.

### 4d.6 Holder bounds (`scripts/bg_gpu_holder.py`, to be written)

```text
target occupancy      ~5,200 MiB MEASURED (driver-visible)
minimum effective     >  4,668 MiB   (below this, 1,476 + holder <= 6,144
                                      and the scenario is INCONCLUSIVE)
maximum allowed       <  8,000 MiB   (abort above; the scenario needs a
                                      bounded holder, not a large one)
lifetime              <= 600 s, self-terminating regardless of outcome
pinned to             the resolved GPU UUID, not an index
killed by             the validation script only; production code never
```

**Confirm the measured figure; never assume it.** A requested 4 GiB
tensor does not occupy 4 GiB once CUDA context and allocator overhead are
counted.

Cleanup: `pkill -f bg_gpu_holder` then re-check compute-apps and baseline.

### 4d.7 Proving no CANDIDATE child started

In B-G2b the holder legitimately appears in the GPU process table, so
the claim is **not** "no process on the GPU". It is **no candidate
training/inference child**. Record all of:

```text
tuner parent PID
holder PID and its measured MiB
every compute-app PID with its full command line
count of candidate training/inference PIDs == 0
no training sentinel and no denoised artifact for that exp_id
the refusal record came from the real tuner handler
```

A returned status dict is not evidence.

### 4d.8 Budget

```text
total wall clock   <= 45 min
holder lifetime    <= 10 min per instance
real training      exactly 1 (B-G1)
LLM calls          <= 9
cost               <  $0.60
automatic retry    NONE — a failed scenario stops and reports
```

### 4d.9 Verdict criteria

| | Condition |
|---|---|
| **PASS** | B-G1 admits and completes a real phase; B-G2a refuses `policy_unavailable`; B-G2b refuses `insufficient_headroom`; no candidate child in either refusal; GPU returns to baseline |
| **FAIL** | a candidate phase starts despite a refusal; a refusal blames the candidate or emits shrink advice; measured insufficient headroom is admitted; B-G1 refuses despite an exactly-matching fixture |
| **INCONCLUSIVE** | card not idle; fixture/candidate mismatch; holder outside `4,668 – 8,000` MiB; telemetry unavailable; any orphan; budget ceiling hit; **a validation-harness defect that prevents the gate from being exercised** |

**INCONCLUSIVE is not FAIL.** Re-run; never tune parameters to force a
verdict.

### 4d.10 Out of scope

No `run_chain.sh` coverage, no production default change, no registry,
no promotion, no H100 bring-up, no retry, no parameter tuning.

---

## 5. Operator decisions — RESOLVED 2026-08-01

### D-B1 — APPROVED: no cross-chain peer registry in v1

Do not build a shared registry, its lock discipline, its staleness
policy or its recovery path. Occupancy is classified as exactly two
things:

```text
candidate-owned
other / contending
```

Any failure with substantial non-candidate occupancy is
**contention-attributable** and carries **no candidate-downsizing
authority**.

Accepted cost, recorded rather than glossed: v1 cannot distinguish the
expected paired chain from a foreign process. That is the conservative
direction — it may mark a genuine candidate failure as unattributable,
but it will not punish a candidate for a neighbour's memory. Given that
the V19 misdiagnosis ran in the other direction, an unattributable
measurement is the cheaper error. Expected-peer versus foreign-peer
identity is a **follow-up refinement**, not a v1 requirement.

### D-B2 — APPROVED: include a narrow host-kill attribution fix

This is not adjacent scope. PR B's purpose is that a measured event is
correctly attributed, and "the environment killed the process" is
precisely the case that must never read as a candidate failure. In
scope:

- consume the existing `oom_host_ram` evidence, which today has **no
  consumer at all** (`sandbox_executor.py:975`, `:1207`, `:1323`);
- stop treating `returncode == -9` **alone** as candidate host OOM;
- distinguish kernel host OOM, host-quota/watchdog termination,
  candidate failure, and unknown;
- guarantee host/environment kills never become candidate evidence.

Out of scope: redesigning the subprocess failure system. The silent-
crash re-route at `tuner:3325-3343` stays **FU-B-3** — a real bug, a
different one.

### D-B3 — APPROVED: do not freeze an estimate-to-actual factor

A6's ~1.8–2.0× ratios are evidence that the current estimate cannot
protect the driver-visible quota. They are **not** evidence of a
universal linear factor: architecture, batch size, phase and caching
allocator behaviour all move it.

PR B decides from, in order: current driver-visible occupancy; current
other/contending occupancy; device free memory; and the candidate's own
measured peak where one exists. A safety factor is reconsidered only
after **B-G2** multi-case validation. **No hardcoded `1.9×` anywhere.**

### D-B5 — APPROVED: formal cold-start measurement belongs to PR C

Direction B of §B-C4 2a-bis. **PR B does not implement a second
measurement registry, promotion policy, or exclusive first-run
workflow**, and it does not quietly run an unknown candidate in formal
mode to measure it on the way past.

The reasoning is responsibility, not convenience: PR C already owns
deciding whether a measurement applies to a given candidate, task,
dataset, phase and hardware. A parallel acquisition-and-promotion path
inside PR B would create a **second measurement authority** — and two
authorities that can disagree about what counts as evidence is the shape
of defect this whole document was opened about. Whether an unknown
candidate is worth spending exclusive GPU time to measure is admission
and promotion policy, not GPU accounting.

```text
PR B                              PR C
measure runtime occupancy         obtain or import measurements
capture bounded evidence          validate applicability
attribute failures                promote to authoritative evidence
consume an applicable measured    supply the first trustworthy
  requirement                       measurement for formal admission
enforce pre-phase headroom
```

**Diagnostic / legacy mode**, when no applicable driver-visible
measurement exists:

```text
record measurement_unavailable
-> proceed with an explicit warning
-> capture bounded runtime evidence
-> do NOT automatically promote the resulting measurement
```

The measurement may be persisted as **raw evidence**. PR B must not
declare it authoritative or reusable across runs — that judgement is
PR C's.

**Formal V20 mode**, when no applicable *authoritative* measurement
exists:

```text
refuse the GPU phase as an infrastructure/admission condition
-> do not launch the subprocess
-> do not blame the candidate
-> emit no resource-downsizing advice
```

**Never** fall back to the allocated-memory estimate as though it were
driver-visible demand.

#### Consequences that must be stated plainly

```text
PR B does not solve formal cold-start measurement acquisition.

A formal candidate with no applicable authoritative driver-visible
measurement is refused until PR C supplies one.

Diagnostic runs may collect bounded measurements, but PR B neither
promotes them nor declares their cross-run applicability.
```

#### Dependency

```text
PR B may merge independently.

Formal V20 campaign launch requires BOTH
  PR B  runtime enforcement
  PR C  authoritative measurement production / promotion
```

This is the honest cost of Direction B, recorded rather than discovered
later: merging PR B does not by itself make a formal campaign launchable
with new candidates.

### D-B4 — APPROVED: fail-closed by default, but only after validation

The V20 target is:

```text
pair-cap oversubscription denied by default
```

Today's default is the opposite — `ALLOW_PAIR_CAP_OVERSUBSCRIPTION:-1`
(`v19_queue_runner.sh:433`) permits it, on the stated premise that *"the
BINDING guard is the per-attempt predicted-peak check"* (`:439`). A6
disproved that premise.

**Do not change the default in B-C1.** Sequence:

```text
B-C1 measurement
  → B-C2 evidence
  → B-C3 attribution
  → B-G2 bounded real validation
  → B-C4 flip the default to fail-closed
```

An explicit operator override remains available, but it must be visibly
announced, stamped into the manifest as provenance, never silently on by
default, and **never used in the formal V20 Gate**.

> Flipping the default is a production-default change. It is authorized
> here as PR B's final step *conditional on B-G2*, not as a free-standing
> permission — if B-G2 does not run, the default does not move.

---

## 6. Follow-ups this audit filed, not fixed here

| ID | Finding |
|---|---|
| **FU-B-17** | ~~`AdmissionDecision.evidence` carries no `ceiling_gib`~~ **CLOSED 2026-08-02.** The triple `configured_ceiling_gib` / `measured_device_capacity_gib` / `effective_ceiling_gib` is recorded as soon as the device figures are trustworthy, so a `policy_unavailable` refusal — which returns before the headroom block — is auditable too. Original finding: `AdmissionDecision.evidence` carried no `ceiling_gib`, so a refusal record cannot be audited for which aggregate ceiling it was judged against. Invisible for `policy_unavailable` (which short-circuits earlier) but material for `insufficient_headroom`, where the ceiling *is* the decision. Not fixed in B-G3: adding a key to the evidence dict changes a persisted production record shape, which is its own change with its own parity obligations. Found by the B-G3 smoke, 2026-08-02 |
| **FU-B-16** | ~~`submit_one_iteration.slurm` silently discarded every flag it did not name — 35 of 39 the chain forwards, including `--data_scope`, every runtime-control flag and both VRAM budgets — so a run executed with different settings on SDSC than on lilab.~~ **CLOSED 2026-08-02.** The wrapper now owns only what it needs, peeks `--workspace`/`--iteration`/`--source_paths` without consuming them, forwards everything else verbatim, and supports `--`. `run_one_iteration.py` is the single validator. Census and validation in §4c.3c |
| **FU-B-14** | `test_k9_invented_model_dual_mode.py::test_invented_model_type_triggers_k2_5_8_fallback_path` fails on clean `master`-line HEAD: `assert "Feasible" in stdout` (`:268`) — the gate prints no verdict line, stdout ending `Completed 2 research rounds. Loop terminated.` Confirmed **pre-existing and unrelated** to PR B: reproduced with the PR B diff stashed, identical message either way, and the diff touches only `scripts/bg_admission_validation.py` plus its unit test, neither of which K9 imports. **CI does not cover it** — the `Lint + Type + Unit Tests` job runs `tests/unit`, not `tests/integration`, so this has been failing invisibly. Not fixed here: unrelated to admission, and fixing it inside PR B would widen the PR past its scope. Found by the B-G1 restart audit's clean-tree sweep, 2026-08-02 |
| **FU-B-15** | ~~The GPU sampler classifies the tuner parent by matching `ml_hyperparameter_tune_agent` in `/proc/<pid>/cmdline`, so a run launched through `scripts/bg_admission_validation.py` produces **no `P0_TUNER_PARENT` sample at all**.~~ **CLOSED 2026-08-02.** The sampler is now in the repo as `scripts/bg_gpu_sampler.sh` — it was an uncommitted operator artifact, which is why the defect survived two runs — and classifies by registered PID first, name second. The harness writes `tuner_parent.pid`; a holder may write `holder.pid`; both are polled each iteration. An empty registration is explicitly guarded, because an empty value comparing equal to any PID would report every process as the parent and make the no-child proof worthless while still looking green |
| **FU-B-1** | `probe.py:265` names a GiB quantity `gpu_memory_used_gb`. Unit-lying field name in a memory-safety module |
| **FU-B-2** | `capture_contention_snapshot` queries `--query-compute-apps=pid` only, so it cannot attribute memory per process — the gap that made a separate primitive necessary |
| **FU-B-3** | `oom_host_ram` has no consumer; a SIGKILLed training child is re-reported as a silent crash (`tuner:3325-3343`). **Partly addressed by B-C3b**: the host-memory *signature* is now consumed as corroborating evidence for attribution, so the information is no longer discarded. The mis-routing itself is untouched — that is control flow, and B-C3 changes none |
| **FU-B-4** | Two shell launchers invoke the pair guard and discard its verdict by default (`v19_queue_runner.sh:433-439`) |
| **FU-B-5** | `SIDERIUS_GPU_VRAM_QUOTA_MIB` is never set, so the quota-tightening branch (`pair_admission.py:107-108`) has never executed in production |
| **FU-B-9** | `gpu_evidence` is attached **only** on the `CalledProcessError` path (`sandbox_executor.py:1119`, `:1354`). The watchdog-kill return (`:999-1008`) and the silent-crash return (`:1083-1087`) attach none, so a SIGKILLed child — exactly the FU-B-3 mis-routing case — reaches its record with no GPU evidence at all. Found by the B-C3 restart audit |
| **FU-B-10** | No producer exists for `external_signal_evidence`, so `external_termination` is unreachable in production even though it is implemented and tested. Closing it needs a quota/watchdog marker, which is new observation and therefore out of B-C3's "no new host telemetry" scope. `host_memory_pressure` **is** reachable via the RLIMIT_AS `MemoryError` signal (`sandbox_executor.py:163`), which is genuine corroboration and not derived from `-9` |
| **FU-B-13** | A run that adopts the **compatibility** pair ceiling (`28.0` GiB) on a **new GPU UUID** does so silently. On a card materially larger than ~32 GiB that under-serves the device and refuses legitimate work as `insufficient_headroom`, which reads as "the device is busy" rather than "the ceiling is unset". Proposed: warn loudly at startup — or require explicit confirmation — when the ceiling is defaulted on a UUID with no recorded configuration. **Deliberately not done here**: this is production behaviour or configuration policy, and the audit that raised it was docs-only. Raised by operator review 2026-08-02 |
| **FU-B-12** | `HyperparamTuningAgent.run()` is 2,487 lines and sits **exactly** on pyright's strict complexity ceiling — 258 branch nodes pass, 259 fail. Strict mode abandons the whole function past that limit, so every annotation inside the tuner's main method is unverified whenever it tips over. PR B bought ~5 nodes of headroom by extraction; the next commit that adds a branch pays the same tax. **Promoted to a required prerequisite: B-C4a0** (operator, 2026-08-01) — see §B-C4a0 |
| **FU-B-11** | Two prompt-safety tests assert over **fixed byte windows of `agent/prompts.py` source** (`test_preflight_inconclusive.py:175-179` slices 1400 chars, `:181-188` slices 400). The first already overruns `inconclusive_note` into `slow_warning`, so a new note added beside it would satisfy the assertion even if the original text were deleted; the second ends ~2 lines short of the word it forbids. Both are fragile against exactly the edit B-C3b makes. Found by the B-C3 restart audit |

---

## 7. Merge criteria

**Progress: B-C1, B-C2a1, B-C2a2, B-C2b, B-C3a, B-C3b, B-C4a0, B-C4 and
B-C5 landed. Gates B-G0, B-G1, B-G2a and B-G2b have all been run and
pass (§4d.3g-l); the LLM budget is 9/9 exhausted. Remaining before
D-B4: B-G3 launcher reachability, which the B-G harness does not
satisfy.**

**B-C4a0 complete before B-C4 begins** (§1.5 of the parent doc — the
binding decomposition principle): admission is added through an
extracted control boundary, not as new branches in `run()`. Its
acceptance is behavioural, not numeric — B-C4's refusal path must fit
inside the boundary without a new family of admission-specific `if`s.

All five commits complete; every checklist item `[x]` with recorded
evidence; the B-C4 guardrails proven to fail on a reverted call site;
default-path parity demonstrated on persisted sample sets; CI green
including strict pyright; B-G1 and B-G2 passed **or** explicitly deferred
with operator sign-off.

**On production defaults — corrected 2026-08-01.** An earlier draft said
"no production-default change included", which contradicted D-B4's
approval of the fail-closed flip. The rule is:

> No **unvalidated** production-default change is included. The
> fail-closed `ALLOW_PAIR_CAP_OVERSUBSCRIPTION` change is included only
> after B-G2 passes **on the exact implementation head**. If B-G2 does
> not run, the default does not move and PR B merges without it.

---

## 8. Genericization impact and in-passing refactor

Required by `v20_priorities.md` §1.4.5. PR B is the most
hardware-coupled PR in the ladder, so this is not a formality: almost
every number it touches is currently a constant that behaves like a
universal fact.

### 8.1 Module classification

| Touched module | Class | Consequence |
|---|---|---|
| `core/runtime_control/gpu_accounting.py` (new, B-C1) | **generic runtime infrastructure** | must not import TIDMAD, tuner-agent, denoising or any task module |
| `core/runtime_control/pair_admission.py` (consumed, B-C4) | generic, but its constants are **hardware-owned configuration** wearing infrastructure clothing | see §8.3 |
| `core/sandbox_executor.py` (seams, B-C2/B-C4) | generic execution infrastructure with task-shaped phase names | phase identity must become a caller-supplied parameter, §8.4 |
| `nodes/ml_hyperparameter_tune_agent/…` (B-C2/B-C3) | **task layer** | the right home for agent-facing wording |
| `agent/prompts.py` (B-C3) | **task layer** | task-owned prompt text |

### 8.2 New hardcoded assumptions introduced — must be none

PR B introduces no new TIDMAD constant. Three places where it would be
easy to introduce one, and the rule for each:

- The accounting primitive must **not** learn what a "training" or
  "inference" phase is; it receives a phase identifier (§8.4).
- The attribution module must **not** name `segmentation_size`,
  `batch_size` or any model knob; it returns typed authority (§8.5).
- The admission guard must **not** read `12`, `28`, `29,000` or `30,000`
  as literals; it consumes a resolved policy object (§8.3).

### 8.3 Hardware policy — B-C1 and B-C4

**Corrected 2026-08-01.** The following are currently constants and are
in truth **hardware-owned configuration**:

| Value | Current source | Class | This PR |
|---|---|---|---|
| 12 GiB per-attempt cap | `--formal_vram_budget_gb` default / operator flag | hardware policy | consumed from resolved policy, not re-read |
| 28 GiB pair ceiling | `pair_admission.py:45` `DEFAULT_PAIR_CEILING_GIB` | hardware policy | consumed from resolved policy; the constant stays as the **compatibility default** and is labelled as one |
| 30,000 MiB host quota | operator fact; `SIDERIUS_GPU_VRAM_QUOTA_MIB` is **never set** (`pair_admission.py:81`) | hardware policy | must become a declared value; today's `None` means *unknown*, not *unlimited* |
| 29,000 MiB emergency line | A6 validation only | **example fixture** — validation infrastructure, never product | not shipped |
| host-RSS 40/60/24 GiB | `sandbox_executor.py:92-96` `_ROLE_DEFAULT_RSS_GB` | hardware policy, **keyed by task phase name** | untouched by PR B; filed as **FU-B-6** |
| `MAX_CONC=2` | `v19_queue_runner.sh:80` | hardware/campaign policy | untouched; **FU-B-7** |

**The guard consumes one resolved policy object.** It must not read
environment variables scattered along the call path — the pattern that
made the 28 GiB ceiling unenforceable is precisely that the value lived
in a module nobody called while the shell read a different variable.

**Device identity is part of this.** B-C1's `DeviceIdentity` (§B-C1 3)
already carries GPU UUID, resolved physical index, logical CUDA index,
`CUDA_VISIBLE_DEVICES` snapshot, and the UUID the sample describes. Two
rules follow and are binding:

- **the snapshot records which device it describes**, and
- **unrelated devices are never aggregated into one number.**

A multi-GPU host is not a future hypothetical for a framework that
intends to be portable; it is the ordinary case everywhere except this
one workstation.

Telemetry backend belongs in `DeviceIdentity` too: `nvidia-smi`
availability is a discovered fact, not an unconditional one, and a
non-NVIDIA accelerator must be able to fail cleanly rather than
mysteriously.

### 8.4 Phase identity — B-C2

The sampling lifecycle (`pre_launch` / `peak` / `last_before_exit` /
`post_failure`) is genuinely generic. The **phase names are not**.

The accounting primitive therefore accepts a **caller-supplied phase
identifier** and hardcodes neither "training" nor "inference". The tuner
supplies those two today; a future simulation, reconstruction or
analysis phase must be able to use the same primitive without editing
it. This costs one parameter now and is unbounded to retrofit later,
which is exactly the case §1.4 exists for.

### 8.5 Attribution vs interpretation — B-C3

This is the sharpest boundary in PR B, and the first draft crossed it.

**Generic** (belongs in runtime infrastructure): the attribution outcome
(§B-C3 2b), a `may_recommend_resource_reduction` authority flag, and the
evidence the decision rested on.

**Task-specific** (belongs in the task/agent layer): the strings

```text
"reduce model size, batch_size, or segmentation_size"
"Try smaller architecture."
```

`segmentation_size` is a TIDMAD signal-processing parameter. A generic
attribution module must not know it exists. The generic layer says *"the
candidate exceeded device capacity and this conclusion has downsizing
authority"*; the task layer decides that, for this task, the actionable
form of that authority mentions segmentation size.

The existing literals live at
`ml_hyperparameter_tune_agent.py:3293-3298` and `:3362-3368` — already
in the task layer. B-C3 must gate them there, and must not lift them
into the generic module while making them conditional.

**Honoured, and now enforced (B-C3b).** The literals stayed in the tuner
and moved *down* into `_oom_memory_wording`, still task-layer. The
generic module carries no task vocabulary at all — asserted over the raw
text including docstrings and comments, and over every identifier
position. Two tests hold the boundary from both sides: the generic one
forbids the words, and the task-layer reachability test requires the
words to exist only behind the gate. Neither could have been satisfied
by moving the strings across the line.

### 8.6 What remains, and why

| Deferred | Reason | ID |
|---|---|---|
| `_ROLE_DEFAULT_RSS_GB` keyed by phase name | a real task/hardware coupling, but PR B does not touch host-RSS policy; moving it here would widen the PR past its own scope rule | **FU-B-6** |
| `MAX_CONC=2` in the shell launcher | campaign policy, and PR B changes no launcher | **FU-B-7** |
| Full `ResolvedRunConfig` (§1.4.3) | PR B introduces only the smallest typed hardware/runtime subsection it needs | **FU-B-8** |
| Dataset/task/metric subsections | not touched by PR B | — |

**PR B is not broadened into a configuration rewrite.** It introduces
the smallest typed boundary the code it touches requires, and records
wider consolidation as follow-up.

### 8.7 Compatibility surface

Current TIDMAD behaviour is preserved by defaults, not special cases:
the 12 GiB and 28 GiB values remain the resolved defaults when nothing
declares otherwise, so an unchanged operator command behaves as it does
today. Each default is labelled a compatibility default, carries its
future configuration source, and is stamped into the run manifest — the
five conditions in §1.4.1.

### 8.8 Tests that prove independence

- [ ] `gpu_accounting` imports no TIDMAD, tuner, denoising or task
      module — asserted structurally, in the style of PR A's AST
      guardrails
- [ ] a snapshot for a **non-zero** device index parses correctly and
      records the right UUID
- [ ] a two-GPU listing does **not** sum across devices
- [ ] a requested UUID that does not match the returned one is a
      failure, not a silent fallback
- [ ] the accounting primitive works with an arbitrary phase identifier,
      including one that is neither "training" nor "inference"
- [ ] admission with a **non-default** ceiling and per-attempt cap
      behaves correctly — proving the values are configuration and not
      constants
- [ ] the attribution module's output contains no task vocabulary
      (`segmentation_size`, `batch_size`, model family names)
- [ ] generic runtime-control tests use synthetic fixtures, not TIDMAD
      data

---

## 9. B-C2a2 test-seam migration audit — executed, condensed 2026-08-01

A pre-execution audit of all 54 sites that referenced the pre-migration
mechanism. The migration it planned is complete (`f2e39a9`), so the
per-site inventory, migration order and execution traps are spent and
have been removed. The full text is preserved in git history at
`7d6f336`.

**Conclusions worth keeping:**

- **Counts.** 54 sites inspected, 48 migrated, 6 retained deliberately.
  The earlier figures of 58/59 double-counted 4 intentional
  pre-migration assertions in `test_observed_subprocess_seam.py` and one
  stale docstring mention.
- **The dangerous class was "green while broken."** A stub that no
  longer intercepts does not raise — it hangs, or worse, launches real
  training. That is why `tests/unit/conftest.py` grew the autouse
  `RealSubprocessEscape` guard, which is now the standing protection for
  every unit test in the tree.
- **The one genuine coverage hole was the parity evidence itself.**
  `preexec_fn` / `env` / `cwd` / `text` / `check` were verified in
  exactly one test, which asserted on `subprocess.run` kwargs — so the
  migration invalidated the test holding the evidence for the whole
  codebase. Its `Popen` equivalent was written rather than deleted, and
  `check=True`, which has no `Popen` analogue, is covered behaviourally
  by `test_plain_nonzero_exit_still_raises`.
