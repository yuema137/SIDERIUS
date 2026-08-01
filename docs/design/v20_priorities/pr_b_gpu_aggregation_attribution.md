# PR B — Runtime GPU aggregate accounting and OOM attribution

**Status: DESIGN READY FOR OPERATOR REVIEW — audited, four decisions
resolved 2026-08-01, implementation not started.**
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

### 3.4 The shrink instruction PR B must gate

Two hardcoded string literals, written unconditionally whenever the
child's stderr contains `"CUDA out of memory"` — regardless of why:

```python
# nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py:3277-3283
"discovery": "CUDA OOM — reduce model size, batch_size, or segmentation_size."
"memory_update": "This config exceeds GPU memory. Try smaller architecture."
# :3347-3350  (inference)
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
- [ ] Define `GpuAccountingSnapshot` (frozen, Pydantic): device used /
      total MiB, own-tree MiB, own PIDs with per-PID MiB, other MiB,
      other PID count, `telemetry_available: bool`, and a units-explicit
      field naming convention (`_mib`, never a `_gb` field holding GiB —
      the bug at `probe.py:265`).
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

### B-C2 — Capture GPU context at an OOM

#### 1. Goal

When training or inference fails, record what the GPU looked like at
that moment, so the cause can be attributed later. Today the OOM record
carries **no** GPU context at all (§3.3), which is why V19's
misattribution was possible.

Separate from B-C3 because capturing evidence changes nothing about
behaviour, while acting on it does. Landing them apart means the
attribution logic can be reviewed against real captured records.

#### 2. Scope

- `core/sandbox_executor.py` — capture a `GpuAccountingSnapshot` on the
  training and inference failure branches; carry it in the returned
  status dict.
- `nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.py` —
  persist it into the two OOM/error records (`:3266-3290`, `:3352-3374`).
- `agent/schemas/hyperparam_tuning.py` — a typed, optional field on the
  record so it is validated rather than free-form.
- Unchanged: status strings, control flow, the agent-facing strings
  (B-C3 changes those), scoring.

Depends on B-C1.

#### 3. Implementation plan

- [ ] Read `sandbox_executor.py:960-1000` and `:1195-1220` in full and
      confirm the exact failure branches before editing.
- [ ] Capture the snapshot on the failure path only — **not** on the
      success path, to keep the added cost off the normal route.
- [ ] Decide and record whether the snapshot is taken before or after
      the child is reaped, and why (a snapshot after teardown measures
      the wrong instant).
- [ ] Add the optional field to the record schema with a default that
      keeps every existing record valid.
- [ ] Persist it in both OOM record builders.
- [ ] Confirm `telemetry_available=False` is stored as such, not omitted
      — an absent field and a failed sample must stay distinguishable.

#### 4. Validation plan

**Unit**:
- [ ] a simulated training failure produces a record carrying the
      snapshot
- [ ] same for inference
- [ ] a success record does **not** carry it
- [ ] a record without the field still validates (backward compatibility
      with every existing on-disk record)
- [ ] `telemetry_available=False` round-trips through the schema

**Pseudo/integration**:
- [ ] existing dual-mode tuner tests still pass unchanged

**Negative**: sampling raises → record still written, field marked
unavailable, no exception escapes.

**Real-training Gate**: none.

#### 5. Acceptance criteria

- [ ] A synthetic OOM produces a record whose snapshot shows non-zero
      `other_mib` when a simulated peer holds memory, and `0` when it
      does not.
- [ ] Loading all existing A5/A6 records under the updated schema
      validates with zero failures (run against the real workspaces).
- [ ] No status string and no control-flow branch changed — provable by
      diff.

#### 6. Failure and edge cases

| Case | Handling |
|---|---|
| sampling itself fails during an OOM | record written with `telemetry_available=False`; never lose the record to a telemetry error |
| child already reaped | documented explicitly; snapshot taken at the earliest point that still reflects the failure |
| an existing record lacks the field | valid, treated as "not captured", never as "no contention" |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/core/ tests/unit/agent/tune_ml_hyperparam_agent/ -q
.venv/bin/python -m pytest tests/integration -q -k "not real_run"
```
- [ ] counts and wall time recorded after the run
- [ ] schema-compatibility check run against
      `a5_preflight_lifecycle_v{1,2}` and `a6_{arch,loss}_v1` records

#### 8. Commit boundary

Reviewable as "add evidence, change nothing". No attribution logic, no
prompt change.

---

### B-C3 — Attribution, and gating the agent-facing shrink signal

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
  the two hardcoded shrink strings (`:3277-3283`, `:3347-3350`) become
  conditional on the attribution.
- `agent/prompts.py` — a suppression note for contention-attributed
  failures, following `inconclusive_note` (`:1018-1040`).
- Fix the `"oom_host_ram"` no-consumer defect (§3.3) **only** to the
  extent of classifying it; the deeper silent-crash re-routing at
  `:3325-3343` is recorded as a follow-up, not fixed here.
- Unchanged: no automatic resizing, no retry policy change.

Depends on B-C1, B-C2.

#### 3. Implementation plan

- [ ] Define the outcome vocabulary and its authority set:
      `candidate_attributable` / `contention_attributable` /
      `host_quota_intervention` / `unknown`, with a
      `may_recommend_downsizing` derived property.
- [ ] Record the threshold rule for "the other side held substantial
      memory" and its justification **before** implementing it; do not
      invent a constant here without evidence (V19: 125.94 MiB free =
      contention; 9.20 GiB free = genuine).
- [ ] Route `returncode == -9` correctly: today it means host OOM, but
      the quota watchdog also kills by signal (§3.3). Distinguish using
      the captured snapshot, and where it cannot be distinguished,
      return `unknown` — never a candidate verdict.
- [ ] Make the two shrink strings conditional.
- [ ] Add the prompt suppression note.
- [ ] Persist the attribution on the record.

#### 4. Validation plan

**Unit**:
- [ ] each outcome maps to the correct `may_recommend_downsizing`
- [ ] a CUDA OOM with `other_mib` ≈ 0 → `candidate_attributable`,
      shrink text present
- [ ] a CUDA OOM with large `other_mib` → `contention_attributable`,
      **shrink text absent**
- [ ] `telemetry_available=False` → `unknown`, shrink text absent
- [ ] SIGKILL with the tree near the host limit → host OOM
- [ ] SIGTERM from outside → `host_quota_intervention`, never candidate
- [ ] every outcome has an explicit mapping; an unmapped one raises
      (the exhaustiveness pattern from `preflight_adapter.py`)

**Prompt-level**:
- [ ] the rendered planner prompt contains the shrink instruction for a
      candidate-attributed OOM and does **not** for a
      contention-attributed one — asserted on the rendered string, not
      on the record

**Negative**: contradictory inputs (OOM flagged but no snapshot) →
`unknown`.

**Real-training Gate**: none in this commit.

#### 5. Acceptance criteria

- [ ] For a record attributed to contention, the string
      `"reduce model size"` does not appear anywhere in the rendered
      planner prompt.
- [ ] The V19 signature (125.94 MiB free, peer holding the card)
      classifies as `contention_attributable` when replayed as a fixture.
- [ ] The genuine case (9.20 GiB free) classifies as
      `candidate_attributable`.
- [ ] No automatic parameter change is introduced — provable by diff.

#### 6. Failure and edge cases

| Case | Handling |
|---|---|
| snapshot unavailable | `unknown` → no shrink signal. Silence is safer than a wrong instruction |
| both candidate-large and peer-large | `unknown`, with both figures recorded; do not guess |
| host quota SIGTERM | `host_quota_intervention`; infrastructure failure, never candidate evidence |
| legacy record with no attribution | treated as `unknown` |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/ tests/unit/agent/ -q
.venv/bin/python -m pytest tests/unit/core/ -q
```
- [ ] counts and wall time recorded after the run

#### 8. Commit boundary

Reviewable as "classify, and stop a wrong signal". Contains no headroom
check and no launcher change.

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
  (`:827-829`) and the inference seam (`:1124-1127`), **returning a
  status dict, never raising** (§3.2).
- Reuse `evaluate_pair_admission` (`pair_admission.py:150`) for the
  ceiling arithmetic with **measured** members rather than configured
  caps, so the guard and the CLI answer the same function.
- `nodes/ml_hyperparameter_tune_agent/...` — consume the new refusal
  status as a skip, in the shape of the existing `skipped_*` records.
- **New**: `tests/unit/guardrails/test_gpu_guard_production_reachability.py`
  — AST-based, in the style of PR A's
  `test_preflight_production_reachability.py`.
- Unchanged: no peer killing, no concurrency reshaping, no threshold
  change, no scoring check.

Depends on B-C1, B-C2, B-C3.

#### 3. Implementation plan

- [ ] Re-read both seams and both `try:` blocks immediately before
      editing; confirm the inference path still lacks a generic handler.
- [ ] Implement the check as a function returning
      `None` (proceed) or a refusal dict.
- [ ] Wire it at both seams.
- [ ] Consume the refusal in the tuner as a skipped attempt with a
      record, matching the existing `skipped_oom_risk` shape
      (`:3175-3220`).
- [ ] Ensure `telemetry_available=False` **proceeds** rather than
      blocking — an unmeasurable device must not halt the campaign, and
      this must be an explicit, tested decision.
- [ ] Add the reachability guardrails, and **prove they fail** by
      reverting the call site, exactly as PR A did.

#### 4. Validation plan

**Unit**:
- [ ] ample headroom → proceeds, no record written
- [ ] insufficient headroom → refuses, record written, no subprocess
      launched
- [ ] refusal never raises out of `execute_inference`
- [ ] refusal status is distinct from `error` and from
      `skipped_oom_risk`
- [ ] `telemetry_available=False` → proceeds, and the decision is logged

**Guardrail**:
- [ ] production reaches the check on the training path
- [ ] production reaches it on the inference path
- [ ] **the guardrails fail when the call site is removed** — recorded
      with the actual failure count, as PR A recorded 2/13 then 13/13

**Backward-compatibility / default parity**:
- [ ] with the check satisfied, the visited sample sequence, seed
      behaviour and step count are byte-identical to the pre-PR-B run —
      compared on the persisted `train_sample_set_*.json` /
      `eval_sample_set_*.json` and the training record, not on config
      values
- [ ] full tuner suite passes unchanged

**Real-training Gate — operator approval required, not launched here**:
- [ ] **B-G1** single chain, confirming no refusal on a normal candidate
      and unchanged artifacts
- [ ] **B-G2** dual chain, confirming a refusal actually fires when the
      pair approaches the ceiling, and that the refused chain records it
      as a skip rather than a candidate failure

#### 5. Acceptance criteria

- [ ] With a simulated 20 GiB peer and a 12 GiB request against a 28 GiB
      ceiling, the training seam refuses and **no training subprocess is
      spawned** — asserted on the subprocess mock, not on the return
      value alone.
- [ ] With the same peer and a 4 GiB request, it proceeds.
- [ ] Removing the training call site makes at least one guardrail fail;
      restoring it makes all pass. Both counts recorded.
- [ ] On the default path with headroom available, `git diff` of a
      re-run's `train_sample_set_*.json` against a pre-PR-B run is empty.
- [ ] `execute_inference` never propagates an exception from the check —
      asserted by injecting a raising sampler.

#### 6. Failure and edge cases

| Case | Handling | Rationale |
|---|---|---|
| telemetry unavailable | **proceed**, log explicitly | an unmeasurable device is not evidence of exhaustion; blocking would halt every campaign on any `nvidia-smi` hiccup |
| device total lags per-PID sum | conservative direction only | never manufacture headroom |
| refusal on every attempt of a round | round ends as skipped, not failed; the candidate is not blamed | a refusal is a statement about the device |
| peer disappears between check and launch | accepted race, documented | the check bounds expected exposure, not worst case — the same honest limit A6 recorded for its monitor |
| ceiling env vars unset | falls back to the hardcoded 28.0, as today | changing that default is out of scope (§2) |

#### 7. Verification commands and evidence

```bash
.venv/bin/python -m pytest tests/unit/core/ tests/unit/guardrails/ -q
.venv/bin/python -m pytest tests/unit/agent/tune_ml_hyperparam_agent/ -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```
- [ ] counts and wall time recorded after the run
- [ ] guardrail revert-proof recorded with both counts
- [ ] B-G1 / B-G2 listed as **not run**, pending operator approval

#### 8. Commit boundary

The only control-flow change in PR B, reviewable on its own. Contains no
vocabulary changes (B-C3) and no launcher default change (§2).

---

### B-C5 — Documentation sync

#### 1. Goal

Bring the operator-facing docs in line with the merged behaviour, as the
node/skill doc-sync rule requires, as the last step before merge.

#### 2. Scope

`nodes/ml_hyperparameter_tune_agent/ml_hyperparameter_tune_agent.md`
(new statuses), `core/`-level docs if a new module needs one, this design
document's implementation record, `docs/design/v20_priorities.md` §20.4
status, and the folder README.

Depends on B-C1…B-C4.

#### 3. Implementation plan

- [ ] Quote every new/changed status string against merged source
- [ ] Quote every new CLI flag and default against merged `--help`
      (expected: none — PR B adds no flags unless B-C4 review says
      otherwise)
- [ ] Record the measured evidence from B-G1/B-G2 if they have run, or
      state plainly that they have not

#### 4-8

Documentation only; validation is the quoting check above. Acceptance:
every documented flag, default and status is quoted from merged source.
Boundary: no code.

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
| **FU-B-1** | `probe.py:265` names a GiB quantity `gpu_memory_used_gb`. Unit-lying field name in a memory-safety module |
| **FU-B-2** | `capture_contention_snapshot` queries `--query-compute-apps=pid` only, so it cannot attribute memory per process — the gap that made a separate primitive necessary |
| **FU-B-3** | `oom_host_ram` has no consumer; a SIGKILLed training child is re-reported as a silent crash (`tuner:3325-3343`) |
| **FU-B-4** | Two shell launchers invoke the pair guard and discard its verdict by default (`v19_queue_runner.sh:433-439`) |
| **FU-B-5** | `SIDERIUS_GPU_VRAM_QUOTA_MIB` is never set, so the quota-tightening branch (`pair_admission.py:107-108`) has never executed in production |

---

## 7. Merge criteria

All five commits complete; every checklist item `[x]` with recorded
evidence; the B-C4 guardrails proven to fail on a reverted call site;
default-path parity demonstrated on persisted sample sets; CI green
including strict pyright; B-G1 and B-G2 passed **or** explicitly deferred
with operator sign-off; no production-default change included.
